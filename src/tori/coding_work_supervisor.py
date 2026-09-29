"""Process supervision and Bubblewrap isolation for concrete Coding Work."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import secrets
import select
import shlex
import shutil
import signal
import stat
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from types import MappingProxyType
from typing import Protocol

from .coding_work import CodingWorkAuthority, CodingWorkDirective
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
from .time_context import format_utc_timestamp


MAX_DIAGNOSTIC_BYTES = 64 * 1024
MAX_FAILURE_STDERR_SUMMARY = 2_000
MAX_WORKER_MESSAGE_BYTES = 32 * 1024
MAX_SUPERVISOR_EVENTS = 512
MAX_SUPERVISOR_DIRECTIVE_RECEIPTS = 512
DEFAULT_TERMINATION_GRACE_SECONDS = 1.0
SANITIZED_WORKER_PATH = "/usr/local/bin:/usr/bin:/bin"
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
WORKER_EVENT_KINDS = frozenset({
    "session_confirmed", "progress", "waiting", "verification",
    "completed", "failed", "cancelled",
})


def sanitized_worker_environment() -> Mapping[str, str]:
    """Return the complete environment inherited by a supervised worker."""

    return MappingProxyType({
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/tmp/tori-worker-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": SANITIZED_WORKER_PATH,
        "SHELL": "/bin/sh",
        "TMPDIR": "/tmp",
        "XDG_CACHE_HOME": "/tmp/tori-worker-home/.cache",
        "XDG_CONFIG_HOME": "/tmp/tori-worker-home/.config",
        "XDG_DATA_HOME": "/tmp/tori-worker-home/.local/share",
    })


@dataclass(frozen=True, slots=True)
class CodingWorkSandboxAvailability:
    available: bool
    name: str
    isolation: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CodingWorkSandboxPlan:
    argv: tuple[str, ...]
    environment: Mapping[str, str]
    workspace_root: str
    workspace_mode: str
    authoritative_git_policy: str
    canonical_runtime_policy: str
    isolation: str


class CodingWorkProcessSandbox(Protocol):
    def availability(self, authority: CodingWorkAuthority) -> CodingWorkSandboxAvailability: ...

    def plan(
        self, worker_argv: Sequence[str], authority: CodingWorkAuthority
    ) -> CodingWorkSandboxPlan: ...


class BubblewrapCodingWorkSandbox:
    """Fail-closed Linux boundary derived only from Coding Work authority."""

    name = "bubblewrap"

    def __init__(
        self,
        executable: str | None = None,
        *,
        protected_runtime_root: Path = Path(__file__).resolve().parents[2] / "runtime",
        project_collection_root: Path = Path(__file__).resolve().parents[2].parent,
    ) -> None:
        self._executable = executable or shutil.which("bwrap")
        self._protected_runtime = protected_runtime_root.resolve(strict=False)
        self._project_collection = project_collection_root.resolve(strict=False)

    def availability(self, authority: CodingWorkAuthority) -> CodingWorkSandboxAvailability:
        try:
            authority.document()
        except Exception:
            return CodingWorkSandboxAvailability(
                False, self.name, "disabled", "The Coding Work authority is invalid."
            )
        if self._executable is None:
            return CodingWorkSandboxAvailability(
                False, self.name, "disabled", "Bubblewrap is not installed."
            )
        try:
            with TemporaryDirectory(prefix="tori-coding-worker-probe-") as temporary:
                workspace = Path(temporary) / "workspace"
                workspace.mkdir()
                (workspace / "probe").write_text("inside\n", encoding="utf-8")
                probe_authority = CodingWorkAuthority(
                    str(workspace), True, authority.modify_allowed, True
                )
                plan = self.plan(
                    ("/bin/sh", "-c", "test \"$(cat probe)\" = inside && "
                     f"test ! -e {shlex.quote(str(self._project_collection))} && "
                     "test ! -e /run/docker.sock && test ! -e /var/run/docker.sock"),
                    probe_authority,
                )
                completed = subprocess.run(
                    plan.argv,
                    cwd=workspace,
                    env=dict(plan.environment),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=5,
                    check=False,
                    umask=0o077,
                )
        except (OSError, subprocess.SubprocessError, CodingWorkerError):
            return CodingWorkSandboxAvailability(
                False, self.name, "disabled", "Bubblewrap could not be started safely."
            )
        if completed.returncode != 0:
            return CodingWorkSandboxAvailability(
                False,
                self.name,
                "disabled",
                "Native namespace isolation is unavailable to this process.",
            )
        return CodingWorkSandboxAvailability(
            True,
            self.name,
            "Bubblewrap private filesystem, process, and network namespaces",
        )

    def plan(
        self, worker_argv: Sequence[str], authority: CodingWorkAuthority
    ) -> CodingWorkSandboxPlan:
        document = authority.document()
        if not authority.sandboxed_execution_allowed or not authority.read_allowed:
            raise CodingWorkerError(
                "Coding Work execution and workspace read authority are required.",
                code="authority_denied",
            )
        if self._executable is None:
            raise CodingWorkerError(
                "Coding Work is disabled because Bubblewrap is unavailable.",
                code="isolation_unavailable",
            )
        command = _worker_argv(worker_argv)
        workspace = Path(str(document["workspace"]["root"])).resolve(strict=True)  # type: ignore[index]
        if not workspace.is_dir():
            raise CodingWorkerError("The authorized workspace is unavailable.", code="workspace_unavailable")
        if workspace == self._project_collection or workspace in self._project_collection.parents:
            raise CodingWorkerError(
                "A broad project collection cannot be a Coding Work workspace.",
                code="workspace_too_broad",
            )
        if workspace == self._protected_runtime or self._protected_runtime in workspace.parents:
            raise CodingWorkerError(
                "Canonical Tori runtime cannot be a Coding Work workspace.",
                code="protected_runtime",
            )

        arguments: list[str] = [
            self._executable,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--dir", "/tmp/tori-worker-home",
        ]
        if Path("/usr/lib64").exists():
            arguments.extend(("--symlink", "usr/lib64", "/lib64"))
        workspace_mount = "--bind" if authority.modify_allowed else "--ro-bind"
        arguments.extend((workspace_mount, str(workspace), "/workspace"))

        git_path = workspace / ".git"
        git_policy = "absent"
        git_entry = _lstat(git_path)
        if git_entry is not None:
            if stat.S_ISREG(git_entry.st_mode):
                raise CodingWorkerError(
                    "Git-file and linked-worktree control layouts are not supported safely yet.",
                    code="unsupported_git_layout",
                )
            if stat.S_ISLNK(git_entry.st_mode) or not stat.S_ISDIR(git_entry.st_mode):
                raise CodingWorkerError(
                    "The authoritative Git control path is unsafe.",
                    code="unsafe_git_control_state",
                )
            arguments.extend(("--ro-bind", str(git_path), "/workspace/.git"))
            git_policy = "existing_authoritative_control_state_read_only"

        runtime_policy = "outside_sandbox"
        try:
            relative_runtime = self._protected_runtime.relative_to(workspace)
        except ValueError:
            relative_runtime = None
        if relative_runtime is not None:
            runtime_path = workspace / relative_runtime
            runtime_entry = _lstat(runtime_path)
            if runtime_entry is not None:
                if stat.S_ISLNK(runtime_entry.st_mode) or not stat.S_ISDIR(runtime_entry.st_mode):
                    raise CodingWorkerError(
                        "The protected runtime mount point is unsafe.",
                        code="protected_runtime",
                    )
                destination = "/workspace/" + relative_runtime.as_posix()
                arguments.extend(("--tmpfs", destination, "--remount-ro", destination))
                runtime_policy = "empty_read_only_mask"

        arguments.extend(("--chdir", "/workspace", "--", *command))
        return CodingWorkSandboxPlan(
            tuple(arguments),
            sanitized_worker_environment(),
            str(workspace),
            "read_write" if authority.modify_allowed else "read_only",
            git_policy,
            runtime_policy,
            "Bubblewrap private filesystem, process, and network namespaces",
        )


@dataclass(frozen=True, slots=True)
class CodingWorkSupervisorBounds:
    stdout_bytes: int = MAX_DIAGNOSTIC_BYTES
    stderr_bytes: int = MAX_DIAGNOSTIC_BYTES
    termination_grace_seconds: float = DEFAULT_TERMINATION_GRACE_SECONDS

    def __post_init__(self) -> None:
        if self.stdout_bytes < 1 or self.stderr_bytes < 1:
            raise ValueError("Coding Work diagnostic bounds must be positive.")
        if self.termination_grace_seconds <= 0:
            raise ValueError("Coding Work termination grace must be positive.")


@dataclass(frozen=True, slots=True)
class CodingWorkProcessDiagnostics:
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    exit_code: int | None
    termination: str | None
    termination_signal_sent: bool
    forced_kill_sent: bool


class _BoundedBytes:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._data = bytearray()
        self._lock = threading.Lock()
        self.truncated = False

    def add(self, data: bytes) -> None:
        with self._lock:
            remaining = self._limit - len(self._data)
            if remaining > 0:
                self._data.extend(data[:remaining])
            if len(data) > remaining:
                self.truncated = True

    def text(self) -> str:
        with self._lock:
            return bytes(self._data).decode("utf-8", errors="replace")


@dataclass(slots=True)
class _SupervisedSession:
    identifier: str
    request: CodingWorkerStartRequest
    workspace: str
    process: subprocess.Popen[bytes]
    stdout: _BoundedBytes
    stderr: _BoundedBytes
    state: str = "starting"
    events: list[CodingWorkerEvent] = field(default_factory=list)
    directives: dict[str, CodingWorkerDirectiveReceipt] = field(default_factory=dict)
    evidence: CodingWorkerEvidence = field(
        default_factory=lambda: CodingWorkerEvidence("No terminal evidence is available.")
    )
    stop_requested: bool = False
    termination: str | None = None
    termination_signal_sent: bool = False
    forced_kill_sent: bool = False
    closed: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    watcher_thread: threading.Thread | None = None
    sequence_offset: int = 0
    finalization_done: threading.Event = field(default_factory=threading.Event)
    finalization_failed: bool = False
    completion_payload: dict[str, object] | None = None


WorkerCommandFactory = Callable[[CodingWorkerStartRequest], Sequence[str]]
Clock = Callable[[], datetime]


@dataclass(slots=True)
class _ProcessSpawnRequest:
    plan: CodingWorkSandboxPlan
    workspace: str
    completed: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen[bytes] | None = None
    error: Exception | None = None


class _DurableProcessSpawner:
    """Keep parent-death process ownership outside transient caller threads."""

    def __init__(self) -> None:
        self._requests: queue.Queue[_ProcessSpawnRequest | None] = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="tori-coding-work-process-owner",
            daemon=False,
        )
        self._thread.start()
        self._ready.wait()

    @property
    def native_id(self) -> int | None:
        return self._thread.native_id

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def spawn(
        self, plan: CodingWorkSandboxPlan, workspace: str
    ) -> subprocess.Popen[bytes]:
        request = _ProcessSpawnRequest(plan, workspace)
        with self._lock:
            if self._closed:
                raise CodingWorkerError(
                    "Coding Work process supervision has stopped.",
                    code="supervisor_stopped",
                )
            self._requests.put(request)
        request.completed.wait()
        if request.error is not None:
            if isinstance(request.error, OSError):
                raise request.error
            raise CodingWorkerError(
                "The isolated Coding Work process could not be started.",
                code="process_start_failed",
            ) from request.error
        if request.process is None:
            raise CodingWorkerError(
                "The isolated Coding Work process could not be started.",
                code="process_start_failed",
            )
        return request.process

    def shutdown(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._requests.put(None)
        if threading.current_thread() is not self._thread:
            self._thread.join()

    def _run(self) -> None:
        self._ready.set()
        while True:
            request = self._requests.get()
            if request is None:
                return
            try:
                request.process = subprocess.Popen(
                    request.plan.argv,
                    cwd=request.workspace,
                    env=dict(request.plan.environment),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                    umask=0o077,
                )
            except Exception as exc:
                request.error = exc
            finally:
                request.completed.set()


class CodingWorkProcessSupervisor:
    """Own real worker process groups behind the portable worker adapter contract."""

    contract_version = 1

    def __init__(
        self,
        worker_command: WorkerCommandFactory,
        *,
        sandbox: CodingWorkProcessSandbox | None = None,
        adapter_id: str = "tori.supervised.coding.worker",
        bounds: CodingWorkSupervisorBounds = CodingWorkSupervisorBounds(),
        clock: Clock | None = None,
        session_factory: Callable[[], str] | None = None,
    ) -> None:
        if not adapter_id or len(adapter_id) > 128:
            raise ValueError("A bounded Coding Work supervisor adapter identifier is required.")
        self._worker_command = worker_command
        self._sandbox = sandbox or BubblewrapCodingWorkSandbox()
        self._identifier = adapter_id
        self._bounds = bounds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._session_factory = session_factory or (
            lambda: "supervised-session-" + secrets.token_hex(16)
        )
        self._lock = threading.RLock()
        self._sessions: dict[str, _SupervisedSession] = {}
        self._correlations: dict[str, str] = {}
        self._active_workspaces: dict[str, str] = {}
        self._closed = False
        self._process_spawner = _DurableProcessSpawner()

    @property
    def identifier(self) -> str:
        return self._identifier

    def describe_capabilities(self) -> CodingWorkerCapabilities:
        return CodingWorkerCapabilities(True, True, False, True)

    def has_live_writer(self) -> bool:
        """Return whether this supervisor still owns a running worker process."""

        with self._lock:
            return any(
                session.process.poll() is None or not session.finalization_done.is_set()
                or session.finalization_failed
                for session in self._sessions.values()
            )

    def start(self, request: CodingWorkerStartRequest) -> CodingWorkerBinding:
        request.authority.document()
        if (
            not request.authority.sandboxed_execution_allowed
            or not request.authority.read_allowed
        ):
            raise CodingWorkerError(
                "Coding Work execution and workspace read authority are required.",
                code="authority_denied",
            )
        workspace = str(Path(request.authority.workspace_root).resolve(strict=True))
        with self._lock:
            if self._closed:
                raise CodingWorkerError(
                    "Coding Work process supervision has stopped.",
                    code="supervisor_stopped",
                )
            existing_id = self._correlations.get(request.launch_correlation_id)
            if existing_id is not None:
                return self._binding(self._sessions[existing_id])
            active_id = self._active_workspaces.get(workspace)
            if active_id is not None and self._session_active(self._sessions[active_id]):
                raise CodingWorkerError(
                    "Another Coding Work worker is active for this workspace.",
                    code="workspace_busy",
                )
            availability = self._sandbox.availability(request.authority)
            if not availability.available:
                raise CodingWorkerError(
                    availability.reason or "Coding Work isolation is unavailable.",
                    code="isolation_unavailable",
                )
            plan = self._sandbox.plan(self._worker_command(request), request.authority)
            try:
                process = self._process_spawner.spawn(plan, workspace)
            except OSError as exc:
                raise CodingWorkerError(
                    "The isolated Coding Work process could not be started.",
                    code="process_start_failed",
                ) from exc
            session_id = self._session_factory()
            if session_id in self._sessions or not session_id or len(session_id) > 128:
                self._terminate_process_group(process, self._bounds.termination_grace_seconds)
                raise CodingWorkerError("The worker session identity is invalid.", code="session_collision")
            session = _SupervisedSession(
                session_id,
                request,
                workspace,
                process,
                _BoundedBytes(self._bounds.stdout_bytes),
                _BoundedBytes(self._bounds.stderr_bytes),
            )
            self._sessions[session_id] = session
            self._correlations[request.launch_correlation_id] = session_id
            self._active_workspaces[workspace] = session_id
            self._start_readers(session)
            return self._binding(session)

    def inspect(self, binding: CodingWorkerBinding) -> CodingWorkerObservation:
        session = self._find(binding)
        if session is None or session.closed:
            return CodingWorkerObservation(False, None, None, None)
        with session.lock:
            return CodingWorkerObservation(
                True,
                session.state,
                session.identifier,
                str(session.events[-1].sequence if session.events else session.sequence_offset),
            )

    def reconnect(
        self,
        request: CodingWorkerReconnectRequest,
        binding: CodingWorkerBinding,
    ) -> CodingWorkerObservation:
        """Raw processes cannot be reattached safely after supervisor restart."""

        request.authority.document()
        return self.inspect(binding)

    def attach(
        self, binding: CodingWorkerBinding, *, after_sequence: int
    ) -> tuple[CodingWorkerEvent, ...]:
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise CodingWorkerError("The worker event cursor is invalid.", code="invalid_cursor")
        session = self._require(binding)
        with session.lock:
            if session.events and after_sequence < session.events[0].sequence - 1:
                boundary = session.events[0].sequence - 1
                omitted = CodingWorkerEvent(
                    f"supervisor-history-truncated-{boundary}",
                    boundary,
                    "progress",
                    session.events[0].occurred_at_utc,
                    {
                        "summary": "Earlier worker progress detail was omitted by the bounded history policy.",
                        "changed_paths": [],
                        "verification": "history_truncated",
                    },
                )
                return (omitted,) + tuple(session.events)
            return tuple(event for event in session.events if event.sequence > after_sequence)

    def submit_directive(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        if directive.kind != "instruction":
            raise CodingWorkerError("An instruction directive is required.", code="invalid_directive")
        return self._deliver_directive(self._require(binding), directive)

    def cancel(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        if directive.kind != "cancel":
            raise CodingWorkerError("A cancellation directive is required.", code="invalid_directive")
        session = self._require(binding)
        with session.lock:
            session.stop_requested = True
        try:
            return self._deliver_directive(session, directive)
        finally:
            self._terminate_session_process(session, "cancelled_by_user")

    def collect_evidence(self, binding: CodingWorkerBinding) -> CodingWorkerEvidence:
        session = self._require(binding)
        with session.lock:
            return session.evidence

    def _complete_after_finalization(
        self,
        session: _SupervisedSession,
        payload: Mapping[str, object],
    ) -> None:
        """Stop one bounded worker and publish success only after safe finalization."""

        evidence = _evidence_from_terminal("completed", payload)
        with session.lock:
            if session.closed or session.state in TERMINAL_STATES:
                return
            if session.completion_payload is not None:
                raise CodingWorkerError(
                    "The worker completion is already pending.",
                    code="invalid_state_transition",
                )
            session.completion_payload = dict(payload)
            session.evidence = evidence
            session.state = "finalizing"
        self._terminate_session_process(session, "bounded_turn_complete")

    def close(self, binding: CodingWorkerBinding) -> None:
        session = self._require(binding)
        with session.lock:
            session.closed = True
            process = session.process
        if process.poll() is None:
            self._terminate_session_process(session, "adapter_close")
        watcher = session.watcher_thread
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=self._bounds.termination_grace_seconds * 3)
        if session.finalization_done.is_set() and not session.finalization_failed:
            self._release_workspace(session)

    def diagnostics(self, binding: CodingWorkerBinding) -> CodingWorkProcessDiagnostics:
        session = self._require(binding)
        with session.lock:
            return CodingWorkProcessDiagnostics(
                session.stdout.text(),
                session.stderr.text(),
                session.stdout.truncated,
                session.stderr.truncated,
                session.process.poll(),
                session.termination,
                session.termination_signal_sent,
                session.forced_kill_sent,
            )

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            sessions = tuple(self._sessions.values())
        try:
            for session in sessions:
                with session.lock:
                    session.closed = True
                if session.process.poll() is None:
                    self._terminate_session_process(session, "supervisor_shutdown")
            for session in sessions:
                watcher = session.watcher_thread
                if watcher is not None:
                    watcher.join(timeout=self._bounds.termination_grace_seconds * 3)
        finally:
            self._process_spawner.shutdown()

    def _start_readers(self, session: _SupervisedSession) -> None:
        assert session.process.stdout is not None and session.process.stderr is not None
        session.stdout_thread = threading.Thread(
            target=self._read_stdout, args=(session,), daemon=True
        )
        session.stderr_thread = threading.Thread(
            target=self._read_stderr, args=(session,), daemon=True
        )
        session.watcher_thread = threading.Thread(
            target=self._watch, args=(session,), daemon=True
        )
        session.stdout_thread.start()
        session.stderr_thread.start()
        session.watcher_thread.start()

    def _read_stdout(self, session: _SupervisedSession) -> None:
        assert session.process.stdout is not None
        while True:
            line = session.process.stdout.readline(MAX_WORKER_MESSAGE_BYTES + 1)
            if not line:
                return
            session.stdout.add(line)
            if len(line) > MAX_WORKER_MESSAGE_BYTES:
                self._protocol_failure(session, "worker_message_too_large")
                continue
            try:
                document = json.loads(line.decode("utf-8"))
                self._record_message(session, document)
            except (UnicodeDecodeError, json.JSONDecodeError, CodingWorkerError):
                self._protocol_failure(session, "invalid_worker_message")

    def _read_stderr(self, session: _SupervisedSession) -> None:
        assert session.process.stderr is not None
        while True:
            chunk = session.process.stderr.read(8192)
            if not chunk:
                return
            session.stderr.add(chunk)

    def _record_message(self, session: _SupervisedSession, document: object) -> None:
        if not isinstance(document, dict) or set(document) != {"kind", "payload"}:
            raise CodingWorkerError("The worker message shape is invalid.", code="invalid_protocol")
        kind = document["kind"]
        payload = document["payload"]
        if kind not in WORKER_EVENT_KINDS or not isinstance(payload, dict):
            raise CodingWorkerError("The worker semantic event is invalid.", code="invalid_protocol")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_WORKER_MESSAGE_BYTES:
            raise CodingWorkerError("The worker semantic event is too large.", code="invalid_protocol")
        terminal_evidence = (
            _evidence_from_terminal(str(kind), payload)
            if kind in TERMINAL_STATES
            else None
        )
        with session.lock:
            if session.closed or session.state in TERMINAL_STATES:
                return
            if kind == "session_confirmed":
                session.state = "running"
            elif kind == "waiting":
                session.state = "waiting"
            elif kind in TERMINAL_STATES:
                session.state = str(kind)
                assert terminal_evidence is not None
                session.evidence = terminal_evidence
            self._emit_locked(session, str(kind), payload)
        if kind in TERMINAL_STATES:
            threading.Thread(
                target=self._terminate_session_process,
                args=(session, f"terminal_{kind}_cleanup"),
                daemon=True,
            ).start()

    def _protocol_failure(self, session: _SupervisedSession, code: str) -> None:
        with session.lock:
            if session.closed or session.state in TERMINAL_STATES:
                return
            session.state = "failed"
            message = "The supervised worker emitted invalid protocol data."
            session.evidence = CodingWorkerEvidence(message)
            self._emit_locked(
                session,
                "failed",
                {"failure_code": code, "failure_message": message},
            )
        try:
            os.killpg(session.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            with session.lock:
                session.termination = "protocol_failure"
                session.termination_signal_sent = True

    def _watch(self, session: _SupervisedSession) -> None:
        return_code = session.process.wait()
        self._cleanup_remaining_group(session.process, self._bounds.termination_grace_seconds)
        for reader in (session.stdout_thread, session.stderr_thread):
            if reader is not None:
                reader.join(timeout=self._bounds.termination_grace_seconds)
        for stream in (
            session.process.stdin, session.process.stdout, session.process.stderr,
        ):
            if stream is not None and not stream.closed:
                stream.close()
        with session.lock:
            if not session.closed and session.state not in TERMINAL_STATES:
                if session.stop_requested and session.completion_payload is None:
                    session.state = "cancelled"
                    if session.termination is None:
                        session.termination = "cancelled_by_user"
                    session.evidence = CodingWorkerEvidence("The Coding Work worker was cancelled.")
                    self._emit_locked(session, "cancelled", {})
                elif session.completion_payload is None:
                    session.state = "failed"
                    if session.termination is None:
                        session.termination = "process_exit"
                    message = (
                        "The supervised worker exited without a terminal result."
                        if return_code == 0
                        else "The supervised worker process stopped unexpectedly."
                    )
                    code = "worker_exited_without_result" if return_code == 0 else "worker_process_crashed"
                    diagnostic = _process_exit_diagnostic(
                        return_code,
                        session.stderr.text(),
                        stderr_truncated=session.stderr.truncated,
                        termination=session.termination,
                        termination_signal_sent=session.termination_signal_sent,
                        forced_kill_sent=session.forced_kill_sent,
                    )
                    session.evidence = CodingWorkerEvidence(
                        message, verification=(diagnostic,)
                    )
                    payload = {
                        "failure_code": code,
                        "failure_message": message,
                        "evidence": session.evidence.document(),
                        **diagnostic,
                    }
                    self._emit_locked(
                        session,
                        "failed",
                        payload,
                    )
        try:
            self._finalize_stopped_session(session)
        except (CodingWorkerError, OSError):
            with session.lock:
                session.finalization_failed = True
                session.state = "failed"
                message = "Worker private state could not be finalized safely."
                session.evidence = CodingWorkerEvidence(message)
                self._emit_locked(session, "failed", {
                    "failure_code": "private_state_import_unsafe",
                    "failure_message": message,
                    "evidence": session.evidence.document(),
                })
        else:
            session.finalization_done.set()
            with session.lock:
                if (
                    not session.closed
                    and session.state not in TERMINAL_STATES
                    and session.completion_payload is not None
                ):
                    session.state = "completed"
                    self._emit_locked(session, "completed", session.completion_payload)
        finally:
            session.finalization_done.set()
        if not session.finalization_failed:
            self._release_workspace(session)

    def _finalize_stopped_session(self, session: _SupervisedSession) -> None:
        """Adapter hook after process-group cleanup and reader completion."""

    def _deliver_directive(
        self, session: _SupervisedSession, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        with session.lock:
            if (
                directive.work_id != session.request.work_id
                or directive.run_id != session.request.run_id
            ):
                raise CodingWorkerError(
                    "The directive targets another Coding Work run.",
                    code="invalid_directive",
                )
            existing = session.directives.get(directive.identifier)
            if existing is not None:
                return CodingWorkerDirectiveReceipt(
                    existing.directive_id, existing.receipt, duplicate=True
                )
            if len(session.directives) >= MAX_SUPERVISOR_DIRECTIVE_RECEIPTS:
                raise CodingWorkerError(
                    "The supervised worker directive receipt budget is exhausted.",
                    code="directive_receipt_limit",
                )
            if session.process.poll() is not None or session.process.stdin is None:
                raise CodingWorkerError("The worker session is missing.", code="session_missing")
            document = {
                "directive_id": directive.identifier,
                "kind": directive.kind,
                "instruction": directive.instruction,
            }
            payload = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            try:
                descriptor = session.process.stdin.fileno()
                remaining = memoryview(payload)
                deadline = time.monotonic() + 1.0
                while remaining:
                    wait = deadline - time.monotonic()
                    if wait <= 0 or not select.select((), (descriptor,), (), wait)[1]:
                        raise TimeoutError
                    written = os.write(descriptor, remaining)
                    if written < 1:
                        raise BrokenPipeError
                    remaining = remaining[written:]
            except (BrokenPipeError, OSError, TimeoutError) as exc:
                raise CodingWorkerError(
                    "The worker directive could not be delivered.",
                    code="directive_delivery_failed",
                ) from exc
            receipt = CodingWorkerDirectiveReceipt(
                directive.identifier, "supervisor-receipt-" + directive.identifier
            )
            session.directives[directive.identifier] = receipt
            return receipt

    def _emit_locked(
        self, session: _SupervisedSession, kind: str, payload: Mapping[str, object]
    ) -> None:
        sequence = (
            session.events[-1].sequence + 1
            if session.events
            else session.sequence_offset + 1
        )
        session.events.append(CodingWorkerEvent(
            f"supervisor-event-{sequence}",
            sequence,
            kind,
            format_utc_timestamp(self._clock().astimezone(timezone.utc)),
            dict(payload),
        ))
        if len(session.events) > MAX_SUPERVISOR_EVENTS:
            removed = session.events.pop(0)
            session.sequence_offset = removed.sequence

    def _find(self, binding: CodingWorkerBinding) -> _SupervisedSession | None:
        if binding.adapter_id != self.identifier or binding.adapter_version != self.contract_version:
            raise CodingWorkerError("The worker binding targets another adapter.", code="adapter_mismatch")
        with self._lock:
            session_id = binding.session_id or self._correlations.get(binding.launch_correlation_id)
            return None if session_id is None else self._sessions.get(session_id)

    def _require(self, binding: CodingWorkerBinding) -> _SupervisedSession:
        session = self._find(binding)
        if session is None or session.closed:
            raise CodingWorkerError("The worker session is missing.", code="session_missing")
        return session

    def _binding(self, session: _SupervisedSession) -> CodingWorkerBinding:
        return CodingWorkerBinding(
            self.identifier,
            self.contract_version,
            session.request.launch_correlation_id,
            session.identifier,
        )

    @staticmethod
    def _session_active(session: _SupervisedSession) -> bool:
        return (session.process.poll() is None or not session.finalization_done.is_set()
                or session.finalization_failed)

    def _release_workspace(self, session: _SupervisedSession) -> None:
        with self._lock:
            if self._active_workspaces.get(session.workspace) == session.identifier:
                del self._active_workspaces[session.workspace]

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes], grace: float) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            pass

    def _terminate_session_process(
        self, session: _SupervisedSession, reason: str
    ) -> None:
        """Contain one owned process group while retaining Tori's bounded reason."""

        process = session.process
        with session.lock:
            if process.poll() is not None:
                return
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            if session.termination in {None, "process_exit"}:
                session.termination = reason
            session.termination_signal_sent = True
        try:
            process.wait(timeout=self._bounds.termination_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        with session.lock:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            session.forced_kill_sent = True
        try:
            process.wait(timeout=self._bounds.termination_grace_seconds)
        except subprocess.TimeoutExpired:
            pass

    @staticmethod
    def _cleanup_remaining_group(process: subprocess.Popen[bytes], grace: float) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _evidence_from_terminal(kind: str, payload: Mapping[str, object]) -> CodingWorkerEvidence:
    evidence = payload.get("evidence", {})
    if not isinstance(evidence, dict):
        raise CodingWorkerError("The worker terminal evidence is invalid.", code="invalid_protocol")
    summary = evidence.get("summary")
    if not isinstance(summary, str) or not summary or len(summary) > 8_000:
        if kind == "failed":
            summary = payload.get("failure_message")
        if not isinstance(summary, str) or not summary or len(summary) > 8_000:
            raise CodingWorkerError("The worker terminal summary is invalid.", code="invalid_protocol")
    changed = evidence.get("changed_paths", [])
    verification = evidence.get("verification", [])
    artifacts = evidence.get("artifacts", [])
    if not isinstance(changed, list) or not all(isinstance(item, str) for item in changed):
        raise CodingWorkerError("The worker changed paths are invalid.", code="invalid_protocol")
    if not isinstance(verification, list) or not all(isinstance(item, dict) for item in verification):
        raise CodingWorkerError("The worker verification evidence is invalid.", code="invalid_protocol")
    if not isinstance(artifacts, list) or not all(isinstance(item, dict) for item in artifacts):
        raise CodingWorkerError("The worker artifacts are invalid.", code="invalid_protocol")
    if len(changed) > 500 or len(verification) > 100 or len(artifacts) > 100:
        raise CodingWorkerError("The worker terminal evidence is too large.", code="invalid_protocol")
    return CodingWorkerEvidence(
        summary,
        tuple(changed),
        tuple(dict(item) for item in verification),
        tuple(dict(item) for item in artifacts),
    )


def _process_exit_diagnostic(
    return_code: int | None,
    stderr: str,
    *,
    stderr_truncated: bool,
    termination: str | None,
    termination_signal_sent: bool = False,
    forced_kill_sent: bool = False,
) -> dict[str, object]:
    """Build bounded, sanitized process-exit evidence without raw protocol output."""

    cleaned = "".join(
        character
        for character in stderr.replace("\x00", "")
        if character in {"\n", "\t"} or ord(character) >= 32
    ).strip()
    classification = (
        "exit_status_unavailable"
        if return_code is None
        else "signal_exit"
        if return_code < 0
        else "clean_exit"
        if return_code == 0
        else "nonzero_exit"
    )
    diagnostic: dict[str, object] = {
        "kind": "process_exit",
        "status": "observed" if return_code is not None else "exit_status_unavailable",
        "exit_code": return_code,
        "stderr_truncated": stderr_truncated,
        "termination": classification,
    }
    if return_code is not None and return_code < 0:
        observed_signal = -return_code
        diagnostic["signal"] = observed_signal
        diagnostic["signal_origin"] = (
            "tori"
            if (
                forced_kill_sent and observed_signal == signal.SIGKILL
            ) or (
                termination_signal_sent and observed_signal == signal.SIGTERM
            )
            else "unknown"
        )
    if (
        termination not in {None, "process_exit"}
        and (termination_signal_sent or forced_kill_sent)
    ):
        diagnostic["termination_reason"] = termination
        diagnostic["termination_origin"] = "tori"
    if forced_kill_sent:
        diagnostic["forced_kill_sent"] = True
    if cleaned:
        diagnostic["stderr_summary"] = cleaned[-MAX_FAILURE_STDERR_SUMMARY:]
    return diagnostic


def _worker_argv(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not value:
        raise CodingWorkerError("A worker command is required.", code="invalid_worker_command")
    command = tuple(value)
    if len(command) > 64 or any(
        not isinstance(item, str) or not item or "\x00" in item or len(item) > 8_000
        for item in command
    ):
        raise CodingWorkerError("The worker command is invalid.", code="invalid_worker_command")
    return command


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
