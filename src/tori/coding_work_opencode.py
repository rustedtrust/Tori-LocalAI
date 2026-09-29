"""Production OpenCode ACP adapter for Tori-owned Coding Work.

OpenCode remains a replaceable harness.  This module owns only its private
configuration, ACP translation, and composition with Tori's process supervisor,
Bubblewrap boundary, and fixed-destination provider relay.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import threading
import time
from types import MappingProxyType
from urllib.parse import unquote, urlparse

from .coding_work import CodingWorkAuthority, CodingWorkDirective
from .coding_work_private_state import SnapshotImport
from .coding_work_provider_transport import (
    NarrowOpenAIProviderRelay,
    OpenAICompatibleInferencePolicy,
    ProviderTransportError,
)
from .coding_work_supervisor import (
    BubblewrapCodingWorkSandbox,
    CodingWorkProcessSandbox,
    CodingWorkProcessSupervisor,
    CodingWorkProcessDiagnostics,
    CodingWorkSandboxAvailability,
    CodingWorkSandboxPlan,
    CodingWorkSupervisorBounds,
    _process_exit_diagnostic,
    _SupervisedSession,
)
from .coding_worker import (
    CodingWorkerBinding,
    CodingWorkerCapabilities,
    CodingWorkerDirectiveReceipt,
    CodingWorkerError,
    CodingWorkerEvent,
    CodingWorkerEvidence,
    CodingWorkerObservation,
    CodingWorkerReconnectRequest,
    CodingWorkerStartRequest,
)


OPENCODE_ADAPTER_ID = "opencode.acp"
OPENCODE_ADAPTER_VERSION = 1
OPENCODE_TARGET_VERSION = "1.18.31"
ACP_PROTOCOL_VERSION = 1
ACP_CONTROL_TIMEOUT_SECONDS = 30.0
ACP_MODEL_TURN_TIMEOUT_SECONDS = 15 * 60.0
MAX_ACP_MESSAGE_BYTES = 256 * 1024
MAX_AGENT_SUMMARY_LENGTH = 2_000
MAX_CHANGED_PATHS = 500
MAX_VERIFICATION_ITEMS = 100
MAX_DIRECTIVE_RECEIPTS_PER_WORK = 512
MAX_WORKSPACE_FILES = 20_000
MAX_EVIDENCE_FILE_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 64 * 1024 * 1024
SANDBOX_WORKSPACE_ROOT = "/workspace"


class OpenCodeAdapterError(CodingWorkerError):
    """Bounded, safe OpenCode adapter failure."""


@dataclass(frozen=True, slots=True)
class OpenCodeAdapterSettings:
    executable: Path
    private_root: Path
    provider_policy: OpenAICompatibleInferencePolicy
    provider_transport_source: Path = Path(__file__).with_name(
        "coding_work_provider_transport.py"
    )
    control_timeout_seconds: float = ACP_CONTROL_TIMEOUT_SECONDS
    model_turn_timeout_seconds: float = ACP_MODEL_TURN_TIMEOUT_SECONDS
    security_probe: bool = False
    probe_host_port: int | None = None

    def __post_init__(self) -> None:
        if self.control_timeout_seconds <= 0 or self.model_turn_timeout_seconds <= 0:
            raise ValueError("OpenCode ACP timeouts must be positive.")
        if self.probe_host_port is not None and (
            isinstance(self.probe_host_port, bool) or not 1 <= self.probe_host_port <= 65535
        ):
            raise ValueError("The OpenCode security-probe host port is invalid.")


@dataclass(slots=True)
class _ACPResult:
    ready: threading.Event = field(default_factory=threading.Event)
    document: dict[str, object] | None = None
    failure: CodingWorkerError | None = None


class ACPJSONRPCClient:
    """Bounded concurrent ACP JSON-RPC client over an owned subprocess."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        notification: Callable[[dict[str, object]], None],
        request: Callable[[str, Mapping[str, object]], object],
        raw_output: Callable[[bytes], None],
        max_message_bytes: int = MAX_ACP_MESSAGE_BYTES,
    ) -> None:
        if max_message_bytes < 1:
            raise ValueError("The ACP message bound must be positive.")
        self.process = process
        self._notification = notification
        self._request = request
        self._raw_output = raw_output
        self._max_message_bytes = max_message_bytes
        self._pending: dict[int, _ACPResult] = {}
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._closed = False
        self._failure: CodingWorkerError | None = None

    def call(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> Mapping[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("The ACP call timeout must be positive.")
        with self._state_lock:
            if self._closed or self._failure is not None:
                raise self._failure or OpenCodeAdapterError(
                    "The OpenCode ACP transport is closed.", code="transport_closed"
                )
            identifier = self._next_id
            self._next_id += 1
            pending = _ACPResult()
            self._pending[identifier] = pending
        try:
            self._write({
                "jsonrpc": "2.0",
                "id": identifier,
                "method": method,
                "params": dict(params),
            })
            deadline = time.monotonic() + timeout_seconds
            while not pending.ready.wait(timeout=min(0.25, max(0.0, deadline - time.monotonic()))):
                if time.monotonic() >= deadline:
                    raise OpenCodeAdapterError(
                        f"OpenCode did not complete {method} within its bounded deadline.",
                        code="acp_timeout",
                    )
                if self.process.poll() is not None:
                    raise OpenCodeAdapterError(
                        "OpenCode stopped before completing an ACP operation.",
                        code="transport_eof",
                    )
            if pending.failure is not None:
                raise pending.failure
            assert pending.document is not None
            if "error" in pending.document:
                raise OpenCodeAdapterError(
                    f"OpenCode rejected the ACP operation {method}.",
                    code="acp_operation_failed",
                )
            result = pending.document.get("result", {})
            if not isinstance(result, dict):
                raise OpenCodeAdapterError(
                    "OpenCode returned an invalid ACP result.", code="invalid_acp_message"
                )
            return result
        finally:
            with self._state_lock:
                self._pending.pop(identifier, None)

    def read_loop(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                line = self.process.stdout.readline(self._max_message_bytes + 1)
                if not line:
                    self._fail_all("OpenCode ACP closed unexpectedly.", "transport_eof")
                    return
                self._raw_output(line)
                if len(line) > self._max_message_bytes or not line.endswith(b"\n"):
                    self._fail_all("OpenCode emitted an oversized ACP message.", "acp_message_too_large")
                    return
                try:
                    document = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._fail_all("OpenCode emitted malformed ACP data.", "invalid_acp_message")
                    return
                if not isinstance(document, dict) or document.get("jsonrpc") != "2.0":
                    self._fail_all("OpenCode emitted invalid ACP data.", "invalid_acp_message")
                    return
                identifier = document.get("id")
                method = document.get("method")
                valid_identifier = isinstance(identifier, int) and not isinstance(identifier, bool)
                if isinstance(identifier, bool):
                    self._fail_all("OpenCode emitted invalid ACP data.", "invalid_acp_message")
                    return
                try:
                    if valid_identifier and isinstance(method, str):
                        self._answer_server_request(identifier, method, document.get("params"))
                    elif valid_identifier:
                        with self._state_lock:
                            pending = self._pending.get(identifier)
                        if pending is not None:
                            pending.document = document
                            pending.ready.set()
                    elif isinstance(method, str):
                        self._notification(document)
                    else:
                        self._fail_all("OpenCode emitted invalid ACP data.", "invalid_acp_message")
                        return
                except Exception:
                    self._fail_all(
                        "An OpenCode ACP handler failed.", "acp_handler_failed"
                    )
                    return
        except (OSError, ValueError):
            self._fail_all("OpenCode ACP transport failed.", "transport_eof")

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._fail_all("OpenCode ACP transport closed.", "transport_closed")

    def _answer_server_request(self, identifier: int, method: str, params: object) -> None:
        if not isinstance(params, dict):
            self._write({
                "jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32602, "message": "Invalid ACP parameters"},
            })
            return
        try:
            result = self._request(method, params)
        except CodingWorkerError:
            self._write({
                "jsonrpc": "2.0", "id": identifier,
                "error": {"code": -32000, "message": "Authority denied"},
            })
        else:
            self._write({"jsonrpc": "2.0", "id": identifier, "result": result})

    def _write(self, document: Mapping[str, object]) -> None:
        payload = (json.dumps(document, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > self._max_message_bytes:
            raise OpenCodeAdapterError("The ACP request is too large.", code="acp_message_too_large")
        assert self.process.stdin is not None
        with self._write_lock:
            try:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise OpenCodeAdapterError(
                    "OpenCode ACP is unavailable.", code="transport_eof"
                ) from exc

    def _fail_all(self, message: str, code: str) -> None:
        failure = OpenCodeAdapterError(message, code=code)
        with self._state_lock:
            if self._failure is None:
                self._failure = failure
            pending = tuple(self._pending.values())
        for item in pending:
            item.failure = failure
            item.ready.set()


@dataclass(frozen=True, slots=True)
class _OpenCodeSandboxResources:
    config: Path
    state: Path
    ipc: Path


class _OpenCodeSandbox(CodingWorkProcessSandbox):
    """Add only adapter-private mounts to the accepted Bubblewrap plan."""

    def __init__(
        self,
        base: BubblewrapCodingWorkSandbox,
        executable: Path,
        provider_source: Path,
        resources: Callable[[CodingWorkAuthority], _OpenCodeSandboxResources],
        extra_environment: Mapping[str, str] = MappingProxyType({}),
    ) -> None:
        self._base = base
        self._executable = executable
        self._provider_source = provider_source
        self._resources = resources
        self._extra_environment = dict(extra_environment)

    def availability(self, authority: CodingWorkAuthority) -> CodingWorkSandboxAvailability:
        return self._base.availability(authority)

    def plan(
        self, worker_argv: Sequence[str], authority: CodingWorkAuthority
    ) -> CodingWorkSandboxPlan:
        base = self._base.plan(worker_argv, authority)
        resources = self._resources(authority)
        arguments = list(base.argv)
        insertion = arguments.index("--chdir")
        arguments[insertion:insertion] = [
            "--dir", "/harness",
            "--ro-bind", str(self._executable), "/harness/opencode",
            "--ro-bind", str(self._provider_source), "/harness/provider.py",
            "--ro-bind", str(resources.config), "/harness/config",
            "--bind", str(resources.state), "/harness/state",
            "--ro-bind", str(resources.ipc), "/harness/ipc",
        ]
        environment = dict(base.environment)
        environment.update({
            "HOME": "/harness/state/home",
            "XDG_CONFIG_HOME": "/harness/config",
            "XDG_DATA_HOME": "/harness/state/data",
            "XDG_CACHE_HOME": "/harness/state/cache",
            "XDG_STATE_HOME": "/harness/state/state",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
        })
        environment.update(self._extra_environment)
        return CodingWorkSandboxPlan(
            tuple(arguments), MappingProxyType(environment), base.workspace_root,
            base.workspace_mode, base.authoritative_git_policy,
            base.canonical_runtime_policy, base.isolation,
        )


@dataclass(slots=True)
class _OpenCodeSession:
    supervisor_binding: CodingWorkerBinding
    client: ACPJSONRPCClient
    request: CodingWorkerStartRequest
    native_session_id: str | None = None
    baseline: "_WorkspaceSnapshot" = field(default_factory=lambda: _WorkspaceSnapshot({}))
    changed_paths: set[str] = field(default_factory=set)
    omitted_changed_paths: int = 0
    verifications: list[dict[str, object]] = field(default_factory=list)
    agent_summary: str = ""
    authority_required: bool = False
    prompt_lock: threading.Lock = field(default_factory=threading.Lock)
    directive_lock: threading.Lock = field(default_factory=threading.Lock)


class OpenCodeCodingWorkerAdapter(CodingWorkProcessSupervisor):
    """OpenCode 1.18.31 ACP adapter composed with Tori process supervision."""

    contract_version = OPENCODE_ADAPTER_VERSION

    def __init__(
        self,
        settings: OpenCodeAdapterSettings,
        *,
        sandbox: BubblewrapCodingWorkSandbox | None = None,
        process_sandbox: CodingWorkProcessSandbox | None = None,
        worker_command: Callable[[CodingWorkerStartRequest], Sequence[str]] | None = None,
        bounds: CodingWorkSupervisorBounds = CodingWorkSupervisorBounds(),
    ) -> None:
        self.settings = settings
        self._private_root = _prepare_private_root(settings.private_root)
        _ensure_private_directory(self._private_root / "ipc")
        self._instance_token = _load_or_create_instance_token(self._private_root)
        self._resource_lock = threading.RLock()
        self._resources_by_workspace: dict[str, _OpenCodeSandboxResources] = {}
        self._snapshot_imports: dict[str, SnapshotImport] = {}
        self._open_sessions: dict[str, _OpenCodeSession] = {}
        self._native_to_internal: dict[str, str] = {}
        self._clients_by_internal: dict[str, ACPJSONRPCClient] = {}
        self._sequence_offsets: dict[str, int] = {}
        self._relay = NarrowOpenAIProviderRelay(
            self._private_root / "ipc/provider.sock",
            settings.provider_policy,
            ownership_token=self._instance_token,
        )
        self._relay_started = False
        self._relay.recover_stale()
        self._worker_command_override = worker_command
        executable = settings.executable
        provider_source = settings.provider_transport_source
        if process_sandbox is None:
            executable = _require_regular_file(settings.executable, "OpenCode executable")
            provider_source = _require_regular_file(
                settings.provider_transport_source, "provider transport"
            )
            _verify_opencode_version(executable, self._private_root)
        chosen_sandbox = process_sandbox or _OpenCodeSandbox(
            sandbox or BubblewrapCodingWorkSandbox(),
            executable,
            provider_source,
            self._resources_for,
            _security_probe_environment(settings),
        )
        super().__init__(
            self._worker_argv,
            sandbox=chosen_sandbox,
            adapter_id=OPENCODE_ADAPTER_ID,
            bounds=bounds,
        )

    def describe_capabilities(self) -> CodingWorkerCapabilities:
        return CodingWorkerCapabilities(True, True, True, True)

    @property
    def provider_audit(self):  # type: ignore[no-untyped-def]
        """Return the relay's bounded, credential-free transport audit."""

        return self._relay.audit

    def start(self, request: CodingWorkerStartRequest) -> CodingWorkerBinding:
        return self._launch(
            request,
            native_session_id=None,
            submit_objective=True,
            sequence_offset=0,
            prior_observed_state=None,
        )

    def reconnect(
        self,
        request: CodingWorkerReconnectRequest,
        binding: CodingWorkerBinding,
    ) -> CodingWorkerObservation:
        self._validate_external_binding(binding)
        if binding.session_id is None or not binding.session_id.startswith("ses_"):
            return CodingWorkerObservation(False, None, None, None)
        current = self._native_to_internal.get(binding.session_id)
        if current is not None:
            return self.inspect(binding)
        start_request = CodingWorkerStartRequest(
            request.work_id,
            request.run_id,
            request.objective,
            request.acceptance_criteria,
            request.authority,
            binding.launch_correlation_id,
        )
        try:
            self._launch(
                start_request,
                native_session_id=binding.session_id,
                submit_objective=False,
                sequence_offset=request.after_sequence,
                prior_observed_state=request.prior_observed_state,
            )
        except CodingWorkerError as exc:
            if exc.code in {"session_missing", "session_unloadable", "acp_operation_failed"}:
                return CodingWorkerObservation(False, None, None, None)
            raise
        return self.inspect(binding)

    def inspect(self, binding: CodingWorkerBinding) -> CodingWorkerObservation:
        internal = self._internal_binding(binding, required=False)
        if internal is None:
            return CodingWorkerObservation(False, None, None, None)
        observation = super().inspect(internal)
        return CodingWorkerObservation(
            observation.found,
            observation.state,
            binding.session_id if observation.found else None,
            observation.event_cursor,
        )

    def attach(
        self, binding: CodingWorkerBinding, *, after_sequence: int
    ) -> tuple[CodingWorkerEvent, ...]:
        return super().attach(self._internal_binding(binding), after_sequence=after_sequence)

    def submit_directive(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        if directive.kind != "instruction" or directive.instruction is None:
            raise CodingWorkerError("An instruction directive is required.", code="invalid_directive")
        internal = self._internal_binding(binding)
        session = self._open_session(internal)
        if (
            directive.work_id != session.request.work_id
            or directive.run_id != session.request.run_id
            or not re.fullmatch(r"coding-directive-[0-9a-f]{32}", directive.identifier)
        ):
            raise CodingWorkerError(
                "The instruction targets another Coding Work run.",
                code="invalid_directive",
            )
        with session.directive_lock:
            receipt_root = _ensure_private_directory(
                self._private_root / "works" / directive.work_id / "receipts"
            )
            receipt_path = receipt_root / (directive.identifier + ".json")
            existing = _read_receipt(receipt_path)
            if existing == "delivered":
                return CodingWorkerDirectiveReceipt(
                    directive.identifier, "opencode-receipt-" + directive.identifier, duplicate=True
                )
            if existing == "inflight":
                raise CodingWorkerError(
                    "The prior OpenCode directive outcome is uncertain and was not duplicated.",
                    code="directive_delivery_uncertain",
                )
            _prune_receipts(receipt_root, preserve=receipt_path)
            _write_receipt(receipt_path, "inflight", exclusive=True)
            instruction = _sandbox_workspace_text(
                directive.instruction, session.request.authority
            )
            prompt = f"[Tori directive {directive.identifier}]\n{instruction}"
            self._perform_prompt(session, prompt)
            _write_receipt(receipt_path, "delivered", exclusive=False)
            receipt = CodingWorkerDirectiveReceipt(
                directive.identifier, "opencode-receipt-" + directive.identifier
            )
            return receipt

    def cancel(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        return super().cancel(self._internal_binding(binding), directive)

    def collect_evidence(self, binding: CodingWorkerBinding) -> CodingWorkerEvidence:
        return super().collect_evidence(self._internal_binding(binding))

    def diagnostics(self, binding: CodingWorkerBinding) -> CodingWorkProcessDiagnostics:
        return super().diagnostics(self._internal_binding(binding))

    def diagnostics_for_launch(self, launch_correlation_id: str) -> CodingWorkProcessDiagnostics:
        internal_id = self._correlations.get(launch_correlation_id)
        if internal_id is None:
            raise CodingWorkerError("The OpenCode launch is missing.", code="session_missing")
        return super().diagnostics(CodingWorkerBinding(
            self.identifier, self.contract_version, launch_correlation_id, internal_id
        ))

    def close(self, binding: CodingWorkerBinding) -> None:
        internal = self._internal_binding(binding, required=False)
        if internal is None:
            return
        session = self._open_sessions.get(internal.session_id or "")
        if session is not None and session.native_session_id is not None:
            try:
                session.client.call(
                    "session/close",
                    {"sessionId": session.native_session_id},
                    timeout_seconds=self.settings.control_timeout_seconds,
                )
            except CodingWorkerError:
                pass
            session.client.close()
        try:
            super().close(internal)
        except CodingWorkerError as exc:
            if exc.code != "session_missing":
                raise
        if internal.session_id is not None:
            self._open_sessions.pop(internal.session_id, None)
            self._clients_by_internal.pop(internal.session_id, None)
        if binding.session_id is not None:
            self._native_to_internal.pop(binding.session_id, None)

    def shutdown(self) -> None:
        for session in tuple(self._open_sessions.values()):
            session.client.close()
        super().shutdown()
        # Runtime ownership must outlive the last private-state import. The
        # generic supervisor's short join is insufficient for filesystem I/O.
        for supervised in tuple(self._sessions.values()):
            watcher = supervised.watcher_thread
            if watcher is not None and watcher is not threading.current_thread():
                watcher.join()
        if self._relay_started:
            self._relay.close()
            self._relay_started = False
        self._open_sessions.clear()
        self._clients_by_internal.clear()
        self._native_to_internal.clear()

    def _launch(
        self,
        request: CodingWorkerStartRequest,
        *,
        native_session_id: str | None,
        submit_objective: bool,
        sequence_offset: int,
        prior_observed_state: str | None,
    ) -> CodingWorkerBinding:
        internal: CodingWorkerBinding | None = None
        try:
            request.authority.document()
            workspace = str(Path(request.authority.workspace_root).resolve(strict=True))
            resources = self._prepare_resources(request)
            snapshot_root = _ensure_private_directory(resources.state / "data/opencode/snapshot")
            snapshot_import = SnapshotImport(snapshot_root)
            with self._resource_lock:
                self._snapshot_imports[request.launch_correlation_id] = snapshot_import
                self._resources_by_workspace[workspace] = resources
                self._sequence_offsets[request.launch_correlation_id] = sequence_offset
                if not self._relay_started:
                    self._relay.start()
                    self._relay_started = True
            internal = super().start(request)
            session = self._open_session(internal)
            initialized = session.client.call(
                "initialize",
                {
                    "protocolVersion": ACP_PROTOCOL_VERSION,
                    "clientCapabilities": {},
                    "clientInfo": {"name": "tori", "version": "1"},
                },
                timeout_seconds=self.settings.control_timeout_seconds,
            )
            if initialized.get("protocolVersion") != ACP_PROTOCOL_VERSION:
                raise OpenCodeAdapterError(
                    "OpenCode negotiated an unsupported ACP version.", code="unsupported_acp_version"
                )
            if native_session_id is None:
                created = session.client.call(
                    "session/new",
                    {"cwd": "/workspace", "mcpServers": []},
                    timeout_seconds=self.settings.control_timeout_seconds,
                )
                candidate = created.get("sessionId")
            else:
                loaded = session.client.call(
                    "session/load",
                    {"sessionId": native_session_id, "cwd": "/workspace", "mcpServers": []},
                    timeout_seconds=self.settings.control_timeout_seconds,
                )
                candidate = loaded.get("sessionId", native_session_id)
            if not isinstance(candidate, str) or not candidate.startswith("ses_") or len(candidate) > 128:
                raise OpenCodeAdapterError(
                    "OpenCode returned an invalid durable session identity.",
                    code="session_unloadable" if native_session_id else "invalid_session_id",
                )
            if native_session_id is not None and candidate != native_session_id:
                raise OpenCodeAdapterError(
                    "OpenCode loaded a different session identity.", code="session_unloadable"
                )
            session.native_session_id = candidate
            session.baseline = _workspace_snapshot(Path(workspace))
            assert internal.session_id is not None
            self._native_to_internal[candidate] = internal.session_id
            supervised = super()._require(internal)
            with supervised.lock:
                if submit_objective:
                    supervised.state = "running"
                    super()._emit_locked(supervised, "session_confirmed", {"reason": "created"})
                elif prior_observed_state == "waiting":
                    supervised.state = "waiting"
                    super()._emit_locked(
                        supervised, "session_confirmed", {"reason": "quiescent_session_reloaded"}
                    )
                    super()._emit_locked(
                        supervised, "waiting", {"reason": "quiescent_session_reloaded"}
                    )
                elif prior_observed_state == "cancelling":
                    supervised.state = "cancelled"
                    supervised.evidence = CodingWorkerEvidence(
                        "The interrupted worker was authoritatively stopped during restart."
                    )
                    super()._emit_locked(
                        supervised, "cancelled", {"reason": "restart_after_cancellation"}
                    )
                else:
                    supervised.state = "failed"
                    message = (
                        "OpenCode was interrupted during an active turn; Tori did not replay it."
                    )
                    supervised.evidence = CodingWorkerEvidence(message)
                    super()._emit_locked(supervised, "failed", {
                        "failure_code": "interrupted_active_turn",
                        "failure_message": message,
                        "evidence": _evidence_document(session, message),
                    })
            external = CodingWorkerBinding(
                self.identifier, self.contract_version,
                request.launch_correlation_id, candidate,
            )
            if not submit_objective and prior_observed_state != "waiting":
                threading.Thread(
                    target=self._terminate_session_process,
                    args=(supervised, "restart_containment"),
                    daemon=True,
                ).start()
            if submit_objective:
                prompt = _initial_prompt(request)
                threading.Thread(
                    target=self._prompt_background,
                    args=(session, prompt),
                    name="tori-opencode-initial-prompt",
                    daemon=True,
                ).start()
            return external
        except (CodingWorkerError, ProviderTransportError, OSError) as exc:
            diagnostic_suffix = ""
            try:
                if internal is not None:
                    if self.settings.security_probe:
                        diagnostics = super().diagnostics(internal)
                        excerpt = diagnostics.stderr[-4_000:].replace("\x00", "")
                        if excerpt:
                            diagnostic_suffix = " Sandboxed stderr: " + excerpt
                    super().close(internal)
            except CodingWorkerError:
                pass
            if internal is not None:
                self._discard_failed_internal(internal)
            else:
                with self._resource_lock:
                    unused = self._snapshot_imports.pop(request.launch_correlation_id, None)
                if unused is not None:
                    unused.close()
            self._sequence_offsets.pop(request.launch_correlation_id, None)
            self._close_relay_if_idle()
            if isinstance(exc, ProviderTransportError):
                raise OpenCodeAdapterError(
                    "The approved provider transport could not be established.",
                    code=exc.code,
                ) from exc
            if isinstance(exc, OSError):
                raise OpenCodeAdapterError(
                    "OpenCode private state or process setup failed.",
                    code="opencode_setup_failed",
                ) from exc
            if diagnostic_suffix:
                raise OpenCodeAdapterError(
                    (str(exc) + diagnostic_suffix)[:8_000], code=exc.code
                ) from exc
            raise

    def _finalize_stopped_session(self, session: _SupervisedSession) -> None:
        with self._resource_lock:
            scope = self._snapshot_imports.pop(session.request.launch_correlation_id, None)
        if scope is None:
            raise OpenCodeAdapterError("The worker snapshot import scope is missing.", code="private_state_import_unsafe")
        try:
            try:
                os.killpg(session.process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise OpenCodeAdapterError("The worker process group is not quiescent.", code="private_state_import_unsafe")
            scope.finish()
        finally:
            scope.close()
            self._close_relay_if_idle(excluding=session)

    def _close_relay_if_idle(
        self, *, excluding: _SupervisedSession | None = None
    ) -> None:
        """Close shared provider IPC after the last owned worker is quiescent."""

        with self._resource_lock:
            with self._lock:
                another_live_session = any(
                    candidate is not excluding and self._session_active(candidate)
                    for candidate in self._sessions.values()
                )
            if self._relay_started and not another_live_session:
                self._relay.close()
                self._relay_started = False

    def _discard_failed_internal(self, internal: CodingWorkerBinding) -> None:
        identifier = internal.session_id
        if identifier is None:
            return
        client = self._clients_by_internal.pop(identifier, None)
        if client is not None:
            client.close()
        session = self._open_sessions.pop(identifier, None)
        if session is not None and session.native_session_id is not None:
            self._native_to_internal.pop(session.native_session_id, None)
        with self._lock:
            supervised = self._sessions.pop(identifier, None)
            if (
                self._correlations.get(internal.launch_correlation_id)
                == identifier
            ):
                self._correlations.pop(internal.launch_correlation_id, None)
        if supervised is not None:
            self._release_workspace(supervised)

    def _start_readers(self, supervised: _SupervisedSession) -> None:
        supervised.sequence_offset = self._sequence_offsets.pop(
            supervised.request.launch_correlation_id, 0
        )
        client = ACPJSONRPCClient(
            supervised.process,
            notification=lambda document: self._notification(supervised, document),
            request=lambda method, params: self._server_request(supervised, method, params),
            raw_output=supervised.stdout.add,
        )
        session = _OpenCodeSession(
            self._binding(supervised), client, supervised.request
        )
        self._clients_by_internal[supervised.identifier] = client
        self._open_sessions[supervised.identifier] = session
        supervised.stdout_thread = threading.Thread(
            target=client.read_loop, name="tori-opencode-acp", daemon=True
        )
        supervised.stderr_thread = threading.Thread(
            target=super()._read_stderr, args=(supervised,), daemon=True
        )
        supervised.watcher_thread = threading.Thread(
            target=super()._watch, args=(supervised,), daemon=True
        )
        supervised.stdout_thread.start()
        supervised.stderr_thread.start()
        supervised.watcher_thread.start()

    def _notification(self, supervised: _SupervisedSession, document: dict[str, object]) -> None:
        if document.get("method") != "session/update":
            return
        params = document.get("params")
        update = params.get("update") if isinstance(params, dict) else None
        if not isinstance(update, dict):
            return
        kind = update.get("sessionUpdate")
        session = self._open_sessions.get(supervised.identifier)
        if session is None or not isinstance(kind, str):
            return
        if kind in {"agent_thought_chunk", "usage_update", "available_commands_update"}:
            return
        if kind == "agent_message_chunk":
            text = _find_text(update)
            if text:
                session.agent_summary = (session.agent_summary + text)[-MAX_AGENT_SUMMARY_LENGTH:]
            return
        locations, omitted_locations = _locations(
            update, Path(session.request.authority.workspace_root)
        )
        _record_changed_paths(session, locations, omitted=omitted_locations)
        if kind == "tool_call":
            summary = _bounded_text(update.get("title"), "OpenCode started a workspace tool operation.")
            self._semantic(supervised, "progress", {
                "summary": summary,
                "changed_paths": sorted(locations),
                "verification": None,
            })
        elif kind == "tool_call_update":
            status = _bounded_text(update.get("status"), "updated")
            title = _bounded_text(update.get("title"), "OpenCode tool operation")
            if status in {"completed", "failed", "error"}:
                verification = {"operation": title, "status": status}
                if len(session.verifications) < MAX_VERIFICATION_ITEMS:
                    session.verifications.append(verification)
                self._semantic(supervised, "verification", verification)

    def _server_request(
        self, supervised: _SupervisedSession, method: str, params: Mapping[str, object]
    ) -> object:
        if method not in {"session/request_permission", "session/permission"}:
            raise OpenCodeAdapterError("OpenCode requested an unsupported ACP operation.", code="authority_denied")
        session = self._open_sessions[supervised.identifier]
        permission = _permission_name(params)
        allowed = _permission_allowed(permission, session.request.authority)
        options = params.get("options", [])
        option_id = _permission_option(options, allow=allowed)
        if not allowed:
            session.authority_required = True
            self._semantic(supervised, "waiting", {
                "reason": "authority_required",
                "permission": permission,
            })
        if option_id is None:
            raise OpenCodeAdapterError("OpenCode permission request could not be answered safely.", code="authority_denied")
        return {"outcome": {"outcome": "selected", "optionId": option_id}}

    def _prompt_background(self, session: _OpenCodeSession, prompt: str) -> None:
        try:
            self._perform_prompt(session, prompt)
        except CodingWorkerError as exc:
            try:
                supervised = super()._require(session.supervisor_binding)
            except CodingWorkerError as missing:
                if missing.code == "session_missing":
                    return
                raise
            with supervised.lock:
                if supervised.stop_requested or supervised.state in {"cancelled", "cancelling"}:
                    return
            diagnostic = self._prompt_failure_diagnostic(supervised)
            self._semantic(supervised, "failed", {
                "failure_code": exc.code,
                "failure_message": str(exc)[:1_000],
                "evidence": _evidence_document(
                    session,
                    "OpenCode stopped before verified completion.",
                    process_diagnostic=diagnostic,
                ),
                **diagnostic,
            })

    def _prompt_failure_diagnostic(
        self, supervised: _SupervisedSession
    ) -> dict[str, object]:
        if supervised.process.poll() is None:
            try:
                supervised.process.wait(timeout=self._bounds.termination_grace_seconds)
            except subprocess.TimeoutExpired:
                pass
        stderr_thread = supervised.stderr_thread
        if stderr_thread is not None and stderr_thread is not threading.current_thread():
            stderr_thread.join(timeout=self._bounds.termination_grace_seconds)
        with supervised.lock:
            return _process_exit_diagnostic(
                supervised.process.poll(),
                supervised.stderr.text(),
                stderr_truncated=supervised.stderr.truncated,
                termination=supervised.termination,
                termination_signal_sent=supervised.termination_signal_sent,
                forced_kill_sent=supervised.forced_kill_sent,
            )

    def _perform_prompt(self, session: _OpenCodeSession, prompt: str) -> None:
        if session.native_session_id is None:
            raise OpenCodeAdapterError("The OpenCode session is unavailable.", code="session_missing")
        with session.prompt_lock:
            session.authority_required = False
            result = session.client.call(
                "session/prompt",
                {
                    "sessionId": session.native_session_id,
                    "prompt": [{"type": "text", "text": prompt}],
                },
                timeout_seconds=self.settings.model_turn_timeout_seconds,
            )
        supervised = super()._require(session.supervisor_binding)
        if session.authority_required:
            return
        if result.get("stopReason") != "end_turn":
            raise OpenCodeAdapterError(
                "OpenCode ended without a complete model turn.", code="incomplete_model_turn"
            )
        current = _workspace_snapshot(Path(session.request.authority.workspace_root))
        _record_changed_paths(session, _snapshot_changes(session.baseline, current))
        session.baseline = current
        self._semantic(supervised, "progress", {
            "summary": "OpenCode completed a bounded model turn.",
            "changed_paths": sorted(session.changed_paths)[:MAX_CHANGED_PATHS],
            "verification": "workspace_snapshot_observed",
        })
        summary = session.agent_summary.strip() or "OpenCode completed the authorized model turn."
        super()._complete_after_finalization(supervised, {
            "evidence": _evidence_document(session, summary),
        })

    def _semantic(
        self, supervised: _SupervisedSession, kind: str, payload: Mapping[str, object]
    ) -> None:
        super()._record_message(supervised, {"kind": kind, "payload": dict(payload)})

    def _prepare_resources(self, request: CodingWorkerStartRequest) -> _OpenCodeSandboxResources:
        if (
            not re.fullmatch(r"coding-work-[0-9a-f]{32}", request.work_id)
            or not re.fullmatch(r"coding-run-[0-9a-f]{32}", request.run_id)
        ):
            raise OpenCodeAdapterError(
                "The OpenCode private-state identity is invalid.",
                code="private_state_unsafe",
            )
        work_root = _ensure_private_directory(
            self._private_root / "works" / request.work_id
        )
        run_root = _ensure_private_directory(work_root / "runs" / request.run_id)
        config = _ensure_private_directory(run_root / "config")
        _ensure_private_directory(config / "opencode")
        state = _ensure_private_directory(work_root / "state")
        for path in (
            state / "home", state / "data", state / "cache", state / "state",
            work_root / "receipts",
        ):
            _ensure_private_directory(path)
        _seed_offline_bootstrap_state(
            self._private_root / "bootstrap-cache" / "prepared", state
        )
        _write_private_file(
            config / "opencode/opencode.json",
            _configuration(request.authority, self.settings.provider_policy.model).encode("utf-8"),
        )
        _write_private_file(
            config / "opencode/.gitignore",
            b"node_modules\npackage.json\npackage-lock.json\nbun.lock\n.gitignore",
        )
        resources = _OpenCodeSandboxResources(config, state, self._private_root / "ipc")
        workspace = str(Path(request.authority.workspace_root).resolve(strict=True))
        with self._resource_lock:
            self._resources_by_workspace[workspace] = resources
        return resources

    def _resources_for(self, authority: CodingWorkAuthority) -> _OpenCodeSandboxResources:
        workspace = str(Path(authority.workspace_root).resolve(strict=True))
        try:
            return self._resources_by_workspace[workspace]
        except KeyError as exc:
            raise CodingWorkerError("OpenCode private state is unavailable.", code="private_state_unavailable") from exc

    def _worker_argv(self, request: CodingWorkerStartRequest) -> Sequence[str]:
        if self._worker_command_override is not None:
            return self._worker_command_override(request)
        return (
            "/usr/bin/python3", "/harness/provider.py",
            "--unix-socket", "/harness/ipc/provider.sock",
            "--port", "11434", "--",
            "/harness/opencode", "acp", "--pure", "--cwd", "/workspace",
        )

    def _internal_binding(
        self, binding: CodingWorkerBinding, *, required: bool = True
    ) -> CodingWorkerBinding | None:
        self._validate_external_binding(binding)
        internal_id = (
            self._native_to_internal.get(binding.session_id)
            if binding.session_id is not None
            else self._correlations.get(binding.launch_correlation_id)
        )
        if internal_id is None:
            if required:
                raise CodingWorkerError("The OpenCode session is missing.", code="session_missing")
            return None
        supervised = self._sessions.get(internal_id)
        if (
            supervised is None
            or supervised.request.launch_correlation_id
            != binding.launch_correlation_id
        ):
            if required:
                raise CodingWorkerError(
                    "The OpenCode binding does not match its launch.",
                    code="adapter_mismatch",
                )
            return None
        return CodingWorkerBinding(
            self.identifier, self.contract_version,
            binding.launch_correlation_id, internal_id,
        )

    def _open_session(self, internal: CodingWorkerBinding) -> _OpenCodeSession:
        if internal.session_id is None or internal.session_id not in self._open_sessions:
            raise CodingWorkerError("The OpenCode session is missing.", code="session_missing")
        return self._open_sessions[internal.session_id]

    def _validate_external_binding(self, binding: CodingWorkerBinding) -> None:
        if binding.adapter_id != self.identifier or binding.adapter_version != self.contract_version:
            raise CodingWorkerError("The worker binding targets another adapter.", code="adapter_mismatch")


def _configuration(authority: CodingWorkAuthority, model: str) -> str:
    permissions = {
        "*": "deny",
        "read": "allow" if authority.read_allowed else "deny",
        "edit": "allow" if authority.modify_allowed else "deny",
        "bash": "allow" if authority.sandboxed_execution_allowed else "deny",
        "external_directory": "deny",
        "webfetch": "deny",
        "websearch": "deny",
    }
    return json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "plugin": [],
        "enabled_providers": ["tori-approved-local"],
        "provider": {
            "tori-approved-local": {
                "name": "Tori Approved Local Relay",
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "apiKey": "non-secret-required-by-client-library",
                    "baseURL": "http://127.0.0.1:11434/v1",
                    "timeout": 120000,
                },
                "models": {model: {"name": "Tori Approved Coding Model", "tool_call": True}},
            }
        },
        "permission": permissions,
    }, sort_keys=True, separators=(",", ":"))


def _security_probe_environment(settings: OpenCodeAdapterSettings) -> Mapping[str, str]:
    if not settings.security_probe:
        return MappingProxyType({})
    values = {"TORI_PROVIDER_SECURITY_PROBE": "1"}
    if settings.probe_host_port is not None:
        values["TORI_PROBE_HOST_PORT"] = str(settings.probe_host_port)
    return MappingProxyType(values)


def _initial_prompt(request: CodingWorkerStartRequest) -> str:
    parts = [
        "The authorized workspace is mounted inside this sandbox at /workspace. "
        "Use /workspace for every workspace file operation. The original host "
        "workspace path is identity metadata only and is not accessible inside "
        "the sandbox. Resolve relative workspace paths beneath /workspace.",
        "Task:\n" + _sandbox_workspace_text(request.objective, request.authority),
    ]
    if request.acceptance_criteria:
        parts.append(
            "Acceptance criteria:\n"
            + _sandbox_workspace_text(request.acceptance_criteria, request.authority)
        )
    parts.append(
        "Work only inside the authorized workspace. Do not access external directories, "
        "network services, or Git control state. Report verification honestly."
    )
    return "\n\n".join(parts)


def _sandbox_workspace_text(text: str, authority: CodingWorkAuthority) -> str:
    """Translate the authorized host identity only at the worker-text boundary."""

    host_workspace = str(Path(authority.workspace_root).resolve(strict=True))
    boundary = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(host_workspace)}"
        r"(?=$|[/\s,.;:!?\"')\]}])"
    )
    return boundary.sub(SANDBOX_WORKSPACE_ROOT, text)


def _permission_name(params: Mapping[str, object]) -> str:
    candidates = [params.get("permission"), params.get("tool"), params.get("title"), params.get("kind")]
    return " ".join(str(item).lower() for item in candidates if isinstance(item, str))[:512]


def _permission_allowed(name: str, authority: CodingWorkAuthority) -> bool:
    if any(token in name for token in ("external", "web", "network", "fetch", "search")):
        return False
    if any(token in name for token in ("edit", "write", "patch")):
        return authority.modify_allowed
    if any(token in name for token in ("bash", "shell", "command", "tool")):
        return authority.sandboxed_execution_allowed
    if "read" in name:
        return authority.read_allowed
    return False


def _permission_option(options: object, *, allow: bool) -> str | None:
    if not isinstance(options, list):
        return None
    desired = {"allow_once", "allow"} if allow else {"reject_once", "reject", "deny"}
    for option in options:
        if not isinstance(option, dict):
            continue
        kind = option.get("kind") or option.get("name")
        identifier = option.get("optionId") or option.get("id")
        if isinstance(kind, str) and kind.lower() in desired and isinstance(identifier, str):
            return identifier
    return None


def _locations(update: Mapping[str, object], workspace: Path) -> tuple[set[str], int]:
    result: set[str] = set()
    omitted = 0
    values = update.get("locations", [])
    if not isinstance(values, list):
        return result, 0
    workspace = workspace.resolve(strict=True)
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        raw = item["path"]
        parsed = urlparse(raw)
        candidate = Path(unquote(parsed.path) if parsed.scheme == "file" else raw)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            relative = candidate.resolve(strict=False).relative_to(workspace)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] not in {".git", "runtime"}:
            rendered = relative.as_posix()
            if rendered in result:
                continue
            if len(result) < MAX_CHANGED_PATHS:
                result.add(rendered)
            else:
                omitted += 1
    return result, omitted


def _find_text(update: Mapping[str, object]) -> str:
    for key in ("content", "text"):
        value = update.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and isinstance(value.get("text"), str):
            return value["text"]
    return ""


def _bounded_text(value: object, fallback: str) -> str:
    return value[:1_000] if isinstance(value, str) and value else fallback


def _record_changed_paths(
    session: _OpenCodeSession,
    paths: Sequence[str] | set[str],
    *,
    omitted: int = 0,
) -> None:
    session.omitted_changed_paths += omitted
    for path in sorted(set(paths)):
        if path in session.changed_paths:
            continue
        if len(session.changed_paths) < MAX_CHANGED_PATHS:
            session.changed_paths.add(path)
        else:
            session.omitted_changed_paths += 1


@dataclass(frozen=True, slots=True)
class _WorkspaceSnapshot:
    entries: dict[str, tuple[int, int, str]]
    omitted_files: int = 0
    oversized_files: int = 0
    hashed_bytes: int = 0


def _workspace_snapshot(root: Path) -> _WorkspaceSnapshot:
    result: dict[str, tuple[int, int, str]] = {}
    omitted_files = 0
    oversized_files = 0
    hashed_bytes = 0
    protected_names = {".git"}
    canonical_runtime = Path(__file__).resolve().parents[2] / "runtime"
    try:
        runtime_relative = canonical_runtime.relative_to(root.resolve(strict=True))
    except ValueError:
        runtime_relative = None
    if runtime_relative is not None and len(runtime_relative.parts) == 1:
        protected_names.add(runtime_relative.parts[0])
    for directory, names, files in os.walk(root, followlinks=False):
        relative_directory = Path(directory).relative_to(root)
        names[:] = [
            name for name in names
            if not (relative_directory == Path() and name in protected_names)
        ]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISREG(metadata.st_mode):
                remaining = max(0, MAX_EVIDENCE_TOTAL_BYTES - hashed_bytes)
                verified = _hash_regular_no_follow(
                    path,
                    max_bytes=min(MAX_EVIDENCE_FILE_BYTES, remaining),
                )
                if verified is not None:
                    size, mtime_ns, digest = verified
                    result[relative] = (size, mtime_ns, digest)
                    if digest == "oversized":
                        oversized_files += 1
                        omitted_files += 1
                    elif digest in {"budget_omitted", "changed_during_scan"}:
                        omitted_files += 1
                    else:
                        hashed_bytes += size
            elif stat.S_ISLNK(metadata.st_mode):
                result[relative] = (metadata.st_size, metadata.st_mtime_ns, "symlink")
            if len(result) >= MAX_WORKSPACE_FILES:
                omitted_files += 1
                return _WorkspaceSnapshot(
                    result, omitted_files, oversized_files, hashed_bytes
                )
    return _WorkspaceSnapshot(result, omitted_files, oversized_files, hashed_bytes)


def _snapshot_changes(
    before: _WorkspaceSnapshot, after: _WorkspaceSnapshot
) -> set[str]:
    return {
        path
        for path in set(before.entries) | set(after.entries)
        if before.entries.get(path) != after.entries.get(path)
    }


def _evidence_document(
    session: _OpenCodeSession,
    summary: str,
    *,
    process_diagnostic: Mapping[str, object] | None = None,
) -> dict[str, object]:
    partial = session.baseline.omitted_files > 0 or session.omitted_changed_paths > 0
    verification = list(session.verifications[:MAX_VERIFICATION_ITEMS - 1])
    if process_diagnostic is not None and len(verification) < MAX_VERIFICATION_ITEMS - 1:
        verification.append(dict(process_diagnostic))
    verification.append({
        "kind": "workspace_snapshot",
        "status": "partial" if partial else "observed",
        "omitted_files": session.baseline.omitted_files,
        "oversized_files": session.baseline.oversized_files,
        "omitted_changed_paths": session.omitted_changed_paths,
        "hashed_bytes": session.baseline.hashed_bytes,
    })
    return {
        "summary": summary,
        "changed_paths": sorted(session.changed_paths)[:MAX_CHANGED_PATHS],
        "verification": verification,
        "artifacts": [],
    }


def _prepare_private_root(path: Path) -> Path:
    return _ensure_private_directory(path)


def _ensure_private_directory(path: Path) -> Path:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
        raise OpenCodeAdapterError(
            "The OpenCode private-state path is unsafe.", code="private_state_unsafe"
        )
    absolute = Path(os.path.abspath(os.path.normpath(raw)))
    if absolute == Path("/") or len(absolute.parts) < 3:
        raise OpenCodeAdapterError(
            "The OpenCode private-state path is too broad.", code="private_state_unsafe"
        )
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=descriptor)
            child_metadata = os.fstat(child)
            if not stat.S_ISDIR(child_metadata.st_mode):
                os.close(child)
                raise OpenCodeAdapterError(
                    "The OpenCode private-state path is unsafe.",
                    code="private_state_unsafe",
                )
            os.close(descriptor)
            descriptor = child
        final_metadata = os.fstat(descriptor)
        if (
            final_metadata.st_uid != os.geteuid()
            or final_metadata.st_gid != os.getegid()
            or stat.S_IMODE(final_metadata.st_mode) != 0o700
        ):
            raise OpenCodeAdapterError(
                "The OpenCode private-state path has unsafe ownership or permissions.",
                code="private_state_unsafe",
            )
    except (OSError, OpenCodeAdapterError) as exc:
        if isinstance(exc, OpenCodeAdapterError):
            raise
        raise OpenCodeAdapterError(
            "The OpenCode private-state path is unsafe.", code="private_state_unsafe"
        ) from exc
    finally:
        os.close(descriptor)
    return absolute


def _seed_offline_bootstrap_state(source: Path, destination: Path) -> None:
    """Copy prepared regenerable XDG material into one new per-work state."""

    if not os.path.lexists(source):
        return
    source = _validate_existing_private_directory(source)
    destination = _validate_existing_private_directory(destination)
    roots = ("data", "cache", "state")
    with os.scandir(source) as entries:
        source_names = {entry.name for entry in entries}
    if not source_names or not source_names.issubset(roots):
        raise OpenCodeAdapterError(
            "The offline OpenCode bootstrap cache has an unexpected layout.",
            code="private_state_unsafe",
        )
    for name in roots:
        target = _validate_existing_private_directory(destination / name)
        with os.scandir(target) as entries:
            if next(entries, None) is not None:
                return
    file_count = 0
    total_bytes = 0
    for root_name in sorted(source_names):
        source_root = _validate_existing_private_directory(source / root_name)
        destination_root = _validate_existing_private_directory(destination / root_name)
        file_count, total_bytes = _copy_bootstrap_tree(
            source_root, destination_root, file_count, total_bytes
        )


def _copy_bootstrap_tree(
    source: Path,
    destination: Path,
    file_count: int,
    total_bytes: int,
) -> tuple[int, int]:
    for directory, names, files in os.walk(source, followlinks=False):
        current = Path(directory)
        _validate_existing_private_directory(current)
        relative = current.relative_to(source)
        target = destination / relative
        if relative != Path("."):
            os.mkdir(target, 0o700)
        names.sort()
        files.sort()
        for name in names:
            child = current / name
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise OpenCodeAdapterError(
                    "The offline OpenCode bootstrap cache is unsafe.",
                    code="private_state_unsafe",
                )
        for name in files:
            child = current / name
            metadata = child.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_gid != os.getegid()
                or metadata.st_nlink != 1
                or mode not in {0o600, 0o700}
            ):
                raise OpenCodeAdapterError(
                    "The offline OpenCode bootstrap cache is unsafe.",
                    code="private_state_unsafe",
                )
            file_count += 1
            total_bytes += metadata.st_size
            if file_count > 50_000 or total_bytes > 2 * 1024 * 1024 * 1024:
                raise OpenCodeAdapterError(
                    "The offline OpenCode bootstrap cache exceeds its safe budget.",
                    code="private_state_unsafe",
                )
            source_fd = os.open(child, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            target_fd = os.open(
                target / name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                # Bootstrap permits executables; per-work private state does
                # not. Normalize only the newly created copy, never the source.
                0o600,
            )
            try:
                while chunk := os.read(source_fd, 1024 * 1024):
                    pending = memoryview(chunk)
                    while pending:
                        written = os.write(target_fd, pending)
                        pending = pending[written:]
                os.fsync(target_fd)
            finally:
                os.close(source_fd)
                os.close(target_fd)
    return file_count, total_bytes


def _validate_existing_private_directory(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.path.normpath(os.fspath(path))))
    descriptor = os.open(
        absolute,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise OpenCodeAdapterError(
                "The offline OpenCode bootstrap cache is unsafe.",
                code="private_state_unsafe",
            )
    finally:
        os.close(descriptor)
    return absolute


def _load_or_create_instance_token(private_root: Path) -> str:
    path = private_root / "instance.json"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        token = secrets.token_hex(32)
        payload = json.dumps(
            {"schema": 1, "token": token}, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise OpenCodeAdapterError(
                "The OpenCode private-state identity could not be created.",
                code="private_state_unsafe",
            ) from exc
        return token
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise OpenCodeAdapterError(
            "The OpenCode private-state identity is unsafe.", code="private_state_unsafe"
        )
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise OpenCodeAdapterError(
            "The OpenCode private-state identity is unsafe.", code="private_state_unsafe"
        )
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            payload = stream.read(1025)
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenCodeAdapterError(
            "The OpenCode private-state identity is corrupt.", code="private_state_unsafe"
        ) from exc
    token = document.get("token") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "token"}
        or document.get("schema") != 1
        or not isinstance(token, str)
        or len(token) != 64
        or any(character not in "0123456789abcdef" for character in token)
    ):
        raise OpenCodeAdapterError(
            "The OpenCode private-state identity is corrupt.", code="private_state_unsafe"
        )
    return token


def _require_regular_file(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    metadata = resolved.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"The {label} is unavailable.")
    return resolved


def _verify_opencode_version(executable: Path, private_root: Path) -> None:
    version_root = _ensure_private_directory(private_root / "version-check")
    for name in ("home", "config", "data", "cache", "state"):
        _ensure_private_directory(version_root / name)
    environment = {
        "HOME": str(version_root / "home"),
        "XDG_CONFIG_HOME": str(version_root / "config"),
        "XDG_DATA_HOME": str(version_root / "data"),
        "XDG_CACHE_HOME": str(version_root / "cache"),
        "XDG_STATE_HOME": str(version_root / "state"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
    }
    try:
        completed = subprocess.run(
            (str(executable), "--version"),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            umask=0o077,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("OpenCode version could not be verified safely.") from exc
    version = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or version != OPENCODE_TARGET_VERSION:
        raise ValueError(
            f"This adapter requires OpenCode {OPENCODE_TARGET_VERSION}; found {version or 'unknown'}."
        )


def _read_receipt(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise CodingWorkerError("The OpenCode directive receipt is corrupt.", code="receipt_corrupt")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise CodingWorkerError("The OpenCode directive receipt is corrupt.", code="receipt_corrupt") from exc
    status = document.get("status") if isinstance(document, dict) else None
    if status not in {"inflight", "delivered"}:
        raise CodingWorkerError("The OpenCode directive receipt is corrupt.", code="receipt_corrupt")
    return str(status)


def _write_receipt(path: Path, status: str, *, exclusive: bool) -> None:
    _ensure_private_directory(path.parent)
    payload = json.dumps({"status": status}, separators=(",", ":")).encode("utf-8")
    if exclusive:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            return
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _prune_receipts(root: Path, *, preserve: Path) -> None:
    candidates: list[tuple[int, Path]] = []
    count = 0
    with os.scandir(root) as entries:
        for entry in entries:
            if not entry.name.endswith(".json"):
                continue
            count += 1
            path = root / entry.name
            if path == preserve:
                continue
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise CodingWorkerError(
                    "The OpenCode directive receipt directory is unsafe.",
                    code="receipt_corrupt",
                )
            if _read_receipt(path) == "delivered":
                candidates.append((metadata.st_mtime_ns, path))
    remove = max(0, count - MAX_DIRECTIVE_RECEIPTS_PER_WORK + 1)
    if remove > len(candidates):
        raise CodingWorkerError(
            "The OpenCode directive receipt budget is exhausted.",
            code="directive_receipt_limit",
        )
    for _mtime, path in sorted(candidates)[:remove]:
        path.unlink()


def _write_private_file(path: Path, payload: bytes) -> None:
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        stat.S_ISLNK(existing.st_mode)
        or not stat.S_ISREG(existing.st_mode)
        or existing.st_uid != os.geteuid()
        or existing.st_nlink != 1
    ):
        raise OpenCodeAdapterError(
            "The OpenCode private configuration is unsafe.",
            code="private_state_unsafe",
        )
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _hash_regular_no_follow(
    path: Path, *, max_bytes: int
) -> tuple[int, int, str] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except (FileNotFoundError, OSError):
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        if metadata.st_size > MAX_EVIDENCE_FILE_BYTES:
            return metadata.st_size, metadata.st_mtime_ns, "oversized"
        if metadata.st_size > max_bytes:
            return metadata.st_size, metadata.st_mtime_ns, "budget_omitted"
        digest = hashlib.sha256()
        read_bytes = 0
        while True:
            remaining = max_bytes - read_bytes
            if remaining < 0:
                return metadata.st_size, metadata.st_mtime_ns, "budget_omitted"
            chunk = os.read(descriptor, min(64 * 1024, remaining + 1))
            if not chunk:
                break
            read_bytes += len(chunk)
            if read_bytes > max_bytes:
                return metadata.st_size, metadata.st_mtime_ns, "budget_omitted"
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
            or read_bytes != metadata.st_size
        ):
            return after.st_size, after.st_mtime_ns, "changed_during_scan"
        return metadata.st_size, metadata.st_mtime_ns, digest.hexdigest()
    finally:
        os.close(descriptor)
