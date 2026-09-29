"""Provider-neutral Research Worker contract and supervised NDJSON adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Protocol
from weakref import WeakKeyDictionary

from .research import ResearchAuthority, ResearchLimits, ResearchValidationError
from .research_network import _UnixBrokerServer, public_egress_broker


RESEARCH_WORKER_CONTRACT_VERSION = 1
WORKER_EVENT_TYPES = frozenset({
    "accepted", "progress", "source", "status", "completed",
    "completed_with_limits", "cancelled", "failed", "error",
})
TERMINAL_WORKER_EVENTS = frozenset({
    "completed", "completed_with_limits", "cancelled", "failed", "error",
})
MAX_WORKER_LINE = 2_000_000
MAX_STDERR = 64 * 1024
READINESS_CACHE_SECONDS = 30.0


class ResearchWorkerError(RuntimeError):
    def __init__(self, message: str, *, code: str = "research_worker_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResearchWorkerStartRequest:
    job_id: str
    attempt_id: str
    objective: str
    limits: ResearchLimits
    authority: ResearchAuthority

    def document(self) -> dict[str, object]:
        self.authority.document()
        return {
            "type": "start",
            "protocol_version": RESEARCH_WORKER_CONTRACT_VERSION,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "objective": self.objective,
            "limits": self.limits.document(),
            "authority": self.authority.document(),
        }

    def wire_document(
        self, *, model: str, embedding_model: str,
        search_providers: Sequence[str] = ("github", "huggingface", "searxng"),
    ) -> dict[str, object]:
        return {
            "type": "start",
            "protocol_version": RESEARCH_WORKER_CONTRACT_VERSION,
            "job_id": self.job_id,
            "attempt_id": self.attempt_id,
            "objective": self.objective,
            "provider": "ollama",
            "retriever": "authoritative_source",
            "search_providers": list(search_providers),
            "model": model,
            "embedding_model": embedding_model,
            "limits": self.limits.wire_document(),
            "authority": self.authority.document(),
        }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ResearchWorkerBinding:
    job_id: str
    attempt_id: str
    session_id: str
    process_id: int | None


@dataclass(frozen=True, slots=True)
class ResearchWorkerEvent:
    type: str
    job_id: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ResearchWorkerStatus:
    available: bool
    state: str
    reason: str | None = None


EventObserver = Callable[[ResearchWorkerEvent], None]


class ResearchWorkerPort(Protocol):
    identifier: str

    def readiness(self) -> ResearchWorkerStatus: ...
    def start(self, request: ResearchWorkerStartRequest, observer: EventObserver) -> ResearchWorkerBinding: ...
    def status(self, binding: ResearchWorkerBinding) -> ResearchWorkerStatus: ...
    def result(self, binding: ResearchWorkerBinding) -> ResearchWorkerEvent | None: ...
    def cancel(self, binding: ResearchWorkerBinding) -> None: ...
    def confirm_cancelled(self, binding: ResearchWorkerBinding) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ResearchProcessSettings:
    worker_root: Path
    worker_argv: tuple[str, ...]
    bubblewrap_executable: Path
    ollama_host: str = "127.0.0.1"
    ollama_port: int = 11434
    searxng_host: str = "127.0.0.1"
    searxng_port: int = 8080
    model: str = "qwen3.8:latest"
    embedding_model: str = "nomic-embed-text:latest"
    search_providers: tuple[str, ...] = ("github", "huggingface", "searxng")
    cancellation_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.worker_root.is_absolute() or not self.bubblewrap_executable.is_absolute():
            raise ValueError("Research worker paths must be absolute.")
        if not self.worker_argv or not Path(self.worker_argv[0]).is_absolute():
            raise ValueError("The Research worker command must start with an absolute executable.")
        if self.ollama_host not in {"127.0.0.1", "::1"} or not 1 <= self.ollama_port <= 65535:
            raise ValueError("Research Ollama must be an exact loopback endpoint.")
        try:
            import ipaddress
            searxng_address = ipaddress.ip_address(self.searxng_host)
        except ValueError as exc:
            raise ValueError("Research SearXNG must use a numeric local address.") from exc
        if (not searxng_address.is_loopback and not searxng_address.is_private) or not 1 <= self.searxng_port <= 65535:
            raise ValueError("Research SearXNG must be an exact local endpoint.")
        for value in (self.model, self.embedding_model):
            if not value or len(value) > 200 or "\x00" in value:
                raise ValueError("Research model identities must be bounded non-empty text.")
        if tuple(self.search_providers) != ("github", "huggingface", "searxng"):
            raise ValueError("Research providers must be the approved authoritative-source sequence.")
        if not 0.25 <= self.cancellation_grace_seconds <= 30:
            raise ValueError("Research cancellation grace must be between 0.25 and 30 seconds.")


class _BoundedStderr:
    def __init__(self) -> None:
        self.value = bytearray()
        self.lock = threading.Lock()

    def add(self, value: bytes) -> None:
        with self.lock:
            remaining = MAX_STDERR - len(self.value)
            if remaining > 0:
                self.value.extend(value[:remaining])

    def text(self) -> str:
        with self.lock:
            return bytes(self.value).decode(errors="replace")


@dataclass(slots=True)
class _Session:
    binding: ResearchWorkerBinding
    observer: EventObserver
    request: ResearchWorkerStartRequest
    wire_document: Mapping[str, object]
    expected_limits: Mapping[str, int]
    expected_runtime: Mapping[str, object]
    process: subprocess.Popen[bytes] | None = None
    broker: _UnixBrokerServer | None = None
    broker_thread: threading.Thread | None = None
    socket_path: Path | None = None
    stderr: _BoundedStderr = field(default_factory=_BoundedStderr)
    state: str = "queued"
    launch_started: bool = False
    cancellation_enforcer_started: bool = False
    cooperative_cancel_sent: bool = False
    terminal_seen: bool = False
    cancellation_requested: bool = False
    cancellation_acknowledged: bool = False
    terminal_event: ResearchWorkerEvent | None = None
    terminal_document: Mapping[str, object] | None = None
    result_verified: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)
    process_ready: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True, slots=True)
class _LaunchCommand:
    session: _Session


_STOP_OWNER = object()


class SupervisedResearchWorker:
    """One-process-per-job adapter with bwrap and a Tori-owned egress broker."""

    identifier = "gpt-researcher.tori-hardened.v1"

    def __init__(self, settings: ResearchProcessSettings, state_root: Path) -> None:
        self.settings = settings
        self.state_root = Path(state_root)
        self._sessions: dict[str, _Session] = {}
        self._results: dict[tuple[str, str], ResearchWorkerEvent] = {}
        # A live binding is held by every session/callback that can still
        # deliver a late terminal event. Weak keys release finality only after
        # that identity and its supported result handle are no longer held.
        self._cancelled_finality: WeakKeyDictionary[
            ResearchWorkerBinding, ResearchWorkerEvent
        ] = WeakKeyDictionary()
        self._lock = threading.RLock()
        self._readiness_cache: tuple[float, ResearchWorkerStatus] | None = None
        self._launch_queue: queue.Queue[_LaunchCommand | object] = queue.Queue()
        self._owner_thread: threading.Thread | None = None
        self._closing = False

    def readiness(self) -> ResearchWorkerStatus:
        with self._lock:
            now = time.monotonic()
            if self._readiness_cache is not None and self._readiness_cache[0] > now:
                return self._readiness_cache[1]
            status = self._uncached_readiness()
            self._readiness_cache = (now + READINESS_CACHE_SECONDS, status)
            return status

    def _uncached_readiness(self) -> ResearchWorkerStatus:
        if not self.settings.worker_root.is_dir():
            return ResearchWorkerStatus(False, "unavailable", "The hardened Research Worker installation is missing.")
        executable = Path(self.settings.worker_argv[0])
        if not executable.is_file() or not os.access(executable, os.X_OK):
            return ResearchWorkerStatus(False, "unavailable", "The Research Worker executable is unavailable.")
        if len(self.settings.worker_argv) != 2:
            return ResearchWorkerStatus(False, "unavailable", "The Research Worker command shape is invalid.")
        entrypoint = Path(self.settings.worker_argv[1])
        if (
            entrypoint.name != "supervisor.py"
            or self.settings.worker_root not in entrypoint.parents
            or not entrypoint.is_file()
            or entrypoint.is_symlink()
        ):
            return ResearchWorkerStatus(False, "unavailable", "The persistent Research supervisor entrypoint is invalid.")
        if not self.settings.bubblewrap_executable.is_file():
            return ResearchWorkerStatus(False, "unavailable", "Bubblewrap is unavailable.")
        if not self.state_root.is_dir():
            return ResearchWorkerStatus(False, "unavailable", "The Research session root is unavailable.")
        network_module = Path(__file__).resolve().with_name("research_network.py")
        if not network_module.is_file():
            return ResearchWorkerStatus(False, "unavailable", "The Research network broker is unavailable.")
        for name in (".env", ".env.local", ".env.production", "secrets.json", "credentials.json"):
            if (self.settings.worker_root / name).is_symlink():
                return ResearchWorkerStatus(False, "unavailable", "The Research Worker contains an unsafe credential symlink.")
        try:
            probe = subprocess.run(
                [*self._base_sandbox_argv(), "--", "/usr/bin/true"],
                env={}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ResearchWorkerStatus(False, "unavailable", "Linux namespace isolation could not be probed safely.")
        if probe.returncode != 0:
            return ResearchWorkerStatus(False, "unavailable", "Linux namespace isolation is unavailable to Tori.")
        runtime_failure = self._runtime_probe()
        if runtime_failure is not None:
            return ResearchWorkerStatus(False, "unavailable", runtime_failure)
        return ResearchWorkerStatus(True, "ready")

    def _runtime_probe(self) -> str | None:
        """Prove the private namespace can reach only brokered local inference."""

        network_module = Path(__file__).resolve().with_name("research_network.py")
        probe_source = (
            "import json,urllib.request;"
            "d=json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5));"
            "print(json.dumps(sorted({str(x.get('name') or x.get('model')) for x in d.get('models',[]) if isinstance(x,dict)})))"
        )
        try:
            with tempfile.TemporaryDirectory(prefix=".readiness-", dir=self.state_root) as temporary:
                session_root = Path(temporary)
                socket_path = session_root / "egress.sock"
                with public_egress_broker(
                    socket_path, (self.settings.ollama_host, self.settings.ollama_port)
                ):
                    argv = [
                        *self._base_sandbox_argv(), "--new-session",
                        "--tmpfs", "/tmp", "--dir", "/tmp/tori-research-home",
                        "--dir", "/run/tori-research",
                        "--bind", str(session_root), "/run/tori-research",
                        "--ro-bind", str(network_module), "/opt/tori-research-network.py",
                        "--", "/usr/bin/python3", "/opt/tori-research-network.py",
                        "--child", "--broker", "/run/tori-research/egress.sock",
                        "--model", self.settings.model,
                        "--embedding-model", self.settings.embedding_model,
                        "--", "/usr/bin/python3", "-c", probe_source,
                    ]
                    completed = subprocess.run(
                        argv, env={}, stdin=subprocess.DEVNULL, capture_output=True,
                        timeout=10, check=False,
                    )
            if completed.returncode != 0 or len(completed.stdout) > 64 * 1024:
                return "Ollama is not reachable through the approved Research broker path."
            models = json.loads(completed.stdout)
            if not isinstance(models, list) or not all(isinstance(item, str) for item in models):
                return "Ollama returned an invalid model inventory through the Research broker."
            missing = [
                model for model in (self.settings.model, self.settings.embedding_model)
                if model not in models
            ]
            if missing:
                return "A configured local Research model is unavailable through Ollama."
        except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
            return "The Research broker and local model readiness probe failed safely."
        return None

    def start(self, request: ResearchWorkerStartRequest, observer: EventObserver) -> ResearchWorkerBinding:
        if not self.readiness().available:
            raise ResearchWorkerError("The Research Worker is unavailable.", code="worker_unavailable")
        wire_document = request.wire_document(
            model=self.settings.model, embedding_model=self.settings.embedding_model,
            search_providers=self.settings.search_providers,
        )
        with self._lock:
            if self._closing:
                raise ResearchWorkerError("The Research Worker is shutting down.", code="worker_unavailable")
            if request.job_id in self._sessions:
                raise ResearchWorkerError("Research is already supervised.", code="duplicate_start")
            binding = ResearchWorkerBinding(
                request.job_id, request.attempt_id,
                "research-session-" + secrets.token_hex(16), None,
            )
            session = _Session(
                binding, observer, request, wire_document,
                request.limits.wire_document(),
                {"provider": "ollama", "retriever": "authoritative_source",
                 "search_providers": list(self.settings.search_providers),
                 "model": self.settings.model, "embedding_model": self.settings.embedding_model},
            )
            self._sessions[request.job_id] = session
            self._ensure_owner_locked()
            self._launch_queue.put(_LaunchCommand(session))
        return binding

    def status(self, binding: ResearchWorkerBinding) -> ResearchWorkerStatus:
        session = self._session(binding)
        with session.lock:
            if session.process is None:
                return ResearchWorkerStatus(
                    not session.terminal_seen,
                    session.state if not session.terminal_seen else "stopped",
                    None,
                )
            return ResearchWorkerStatus(
                session.process.poll() is None,
                session.state if session.process.poll() is None else "stopped",
                None,
            )

    def result(self, binding: ResearchWorkerBinding) -> ResearchWorkerEvent | None:
        with self._lock:
            finality = self._cancelled_finality.get(binding)
            if finality is not None:
                return finality
            retained = self._results.get((binding.job_id, binding.attempt_id))
            session = self._sessions.get(binding.job_id)
        if session is not None and session.binding == binding:
            with session.lock:
                if session.cancellation_requested:
                    return session.terminal_event if (
                        session.cancellation_acknowledged
                        and session.terminal_event is not None
                        and session.terminal_event.type == "cancelled"
                    ) else None
                if session.result_verified:
                    return session.terminal_event
        return retained

    def cancel(self, binding: ResearchWorkerBinding) -> None:
        session = self._session(binding)
        process = None
        acknowledgement = None
        with session.lock:
            if session.cancellation_acknowledged:
                return
            session.cancellation_requested = True
            session.state = "cancelling"
            process = session.process
            if process is not None and process.poll() is not None:
                session.cancellation_acknowledged = True
                session.terminal_seen = True
                session.state = "cancelled"
                acknowledgement = ResearchWorkerEvent("cancelled", binding.job_id, {
                    "message": "Research was cancelled after the supervised worker exited.",
                    "code": "cancelled", "exit_code": process.returncode,
                })
                session.terminal_event = acknowledgement
                session.result_verified = True
            else:
                self._send_cancel_locked(session)
                if session.cancellation_enforcer_started:
                    return
                session.cancellation_enforcer_started = True
        if acknowledgement is not None:
            self._retain_result(session, acknowledgement)
            session.observer(acknowledgement)
            return
        threading.Thread(target=self._enforce_cancellation, args=(session,), daemon=True).start()

    def confirm_cancelled(self, binding: ResearchWorkerBinding) -> None:
        """Align a retired session's cached result with durable cancellation."""

        event = ResearchWorkerEvent("cancelled", binding.job_id, {
            "code": "cancelled",
            "message": "Research was cancelled after the supervised session ended.",
        })
        with self._lock:
            self._cancelled_finality[binding] = event
            self._results[(binding.job_id, binding.attempt_id)] = event
            while len(self._results) > 100:
                self._results.pop(next(iter(self._results)))

    def close(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            sessions = tuple(self._sessions.values())
        for session in sessions:
            with session.lock:
                process = session.process
                terminal = session.terminal_seen
                if not terminal:
                    # Application shutdown is not user cancellation.  Suppress
                    # worker terminal delivery while terminating the ephemeral
                    # process tree so startup reconciliation can truthfully
                    # change the still-active durable job to ``interrupted``.
                    session.terminal_seen = True
                    session.state = "interrupted"
            if terminal:
                if process is not None and process.stdin is not None:
                    process.stdin.close()
            elif process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + self.settings.cancellation_grace_seconds + 2
        for session in sessions:
            session.finished.wait(max(0.0, deadline - time.monotonic()))
            with session.lock:
                process = session.process
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                session.finished.wait(self.settings.cancellation_grace_seconds)
        with self._lock:
            owner = self._owner_thread
            if owner is not None:
                self._launch_queue.put(_STOP_OWNER)
        if owner is not None:
            owner.join(timeout=2)

    def _ensure_owner_locked(self) -> None:
        owner = self._owner_thread
        if owner is not None and owner.is_alive():
            return
        owner = threading.Thread(
            target=self._run_owner,
            name="tori-research-supervisor",
            daemon=False,
        )
        self._owner_thread = owner
        owner.start()

    def _run_owner(self) -> None:
        """Launch Bubblewrap only from this runtime-lifetime thread.

        Bubblewrap's ``--die-with-parent`` is intentionally retained. On Linux,
        PR_SET_PDEATHSIG follows the particular thread that created the child,
        so this owner must outlive transient HTTP request threads.
        """

        while True:
            command = self._launch_queue.get()
            try:
                if command is _STOP_OWNER:
                    return
                assert isinstance(command, _LaunchCommand)
                self._launch(command.session)
            finally:
                self._launch_queue.task_done()

    def _launch(self, session: _Session) -> None:
        with self._lock:
            closing = self._closing
        with session.lock:
            if session.terminal_seen:
                session.process_ready.set()
                session.finished.set()
                return
            if closing or session.cancellation_requested:
                session.terminal_seen = True
                session.state = "cancelled"
                session.cancellation_acknowledged = True
                cancelled_before_launch = True
            else:
                session.launch_started = True
                session.state = "starting"
                cancelled_before_launch = False
        if cancelled_before_launch:
            session.process_ready.set()
            event = ResearchWorkerEvent("cancelled", session.binding.job_id, {
                "message": "Research was cancelled before worker launch.",
                "code": "cancelled",
            })
            with session.lock:
                session.terminal_event = event
                session.result_verified = True
            self._retain_result(session, event)
            session.observer(event)
            self._retire(session)
            return

        session_root = self.state_root / session.binding.attempt_id
        broker = None
        broker_thread = None
        process = None
        try:
            session_root.mkdir(parents=True, exist_ok=False, mode=0o700)
            socket_path = session_root / "egress.sock"
            broker = _UnixBrokerServer(
                str(socket_path), (self.settings.ollama_host, self.settings.ollama_port),
                (self.settings.searxng_host, self.settings.searxng_port),
            )
            os.chmod(socket_path, 0o600)
            broker_thread = threading.Thread(
                target=broker.serve_forever,
                name=f"research-egress-{session.binding.job_id}",
                daemon=True,
            )
            broker_thread.start()
            process = subprocess.Popen(
                self._sandbox_argv(session_root),
                cwd=self.settings.worker_root,
                env={},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                umask=0o077,
            )
            with session.lock:
                session.process = process
                session.broker = broker
                session.broker_thread = broker_thread
                session.socket_path = socket_path
                session.process_ready.set()
                assert process.stdin is not None
                process.stdin.write(
                    json.dumps(session.wire_document, separators=(",", ":")).encode() + b"\n"
                )
                process.stdin.flush()
                if session.cancellation_requested:
                    self._send_cancel_locked(session)
            threading.Thread(target=self._read_stdout, args=(session,), daemon=True).start()
            threading.Thread(target=self._read_stderr, args=(session,), daemon=True).start()
            threading.Thread(target=self._watch, args=(session,), daemon=True).start()
        except Exception as exc:
            session.process_ready.set()
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            if broker is not None:
                broker.shutdown()
                broker.server_close()
            if broker_thread is not None:
                broker_thread.join(timeout=2)
            try:
                (session_root / "egress.sock").unlink()
            except FileNotFoundError:
                pass
            try:
                session_root.rmdir()
            except OSError:
                pass
            with session.lock:
                if session.state == "interrupted" or session.cancellation_acknowledged:
                    should_report = False
                elif session.cancellation_requested:
                    session.terminal_seen = True
                    session.state = "cancelled"
                    session.cancellation_acknowledged = True
                    cancelled = True
                    should_report = True
                elif session.terminal_seen:
                    should_report = False
                else:
                    session.terminal_seen = True
                    cancelled = False
                    session.state = "failed"
                    should_report = True
            if should_report:
                event = ResearchWorkerEvent("cancelled" if cancelled else "failed", session.binding.job_id, {
                    "message": "Research was cancelled." if cancelled else "The supervised Research Worker could not be started.",
                    "code": "cancelled" if cancelled else getattr(exc, "code", "worker_start_failed"),
                })
                if cancelled:
                    with session.lock:
                        session.terminal_event = event
                        session.result_verified = True
                    self._retain_result(session, event)
                session.observer(event)
            self._retire(session)

    def _retire(self, session: _Session) -> None:
        session.process_ready.set()
        session.finished.set()
        with self._lock:
            if self._sessions.get(session.binding.job_id) is session:
                self._sessions.pop(session.binding.job_id, None)

    def _retain_result(self, session: _Session, event: ResearchWorkerEvent) -> None:
        with self._lock:
            if event.type == "cancelled":
                self._cancelled_finality[session.binding] = event
            elif session.binding in self._cancelled_finality:
                return
            key = (session.binding.job_id, session.binding.attempt_id)
            self._results[key] = event
            while len(self._results) > 100:
                self._results.pop(next(iter(self._results)))

    @staticmethod
    def _send_cancel_locked(session: _Session) -> None:
        process = session.process
        if (
            session.cooperative_cancel_sent
            or process is None
            or process.poll() is not None
            or process.stdin is None
        ):
            return
        try:
            process.stdin.write(json.dumps({
                "type": "cancel",
                "protocol_version": RESEARCH_WORKER_CONTRACT_VERSION,
                "job_id": session.binding.job_id,
                "attempt_id": session.binding.attempt_id,
            }, separators=(",", ":")).encode() + b"\n")
            process.stdin.flush()
            session.cooperative_cancel_sent = True
        except (OSError, ValueError):
            pass

    def _sandbox_argv(self, session_root: Path) -> list[str]:
        bwrap = str(self.settings.bubblewrap_executable)
        network_module = Path(__file__).resolve().with_name("research_network.py")
        args = [
            *self._base_sandbox_argv(), "--new-session",
            "--tmpfs", "/tmp", "--dir", "/tmp/tori-research-home",
            "--dir", "/run/tori-research",
            "--ro-bind", str(self.settings.worker_root), str(self.settings.worker_root),
            "--bind", str(session_root), "/run/tori-research",
            "--ro-bind", str(network_module), "/opt/tori-research-network.py",
        ]
        for name in (".env", ".env.local", ".env.production", "secrets.json", "credentials.json"):
            candidate = self.settings.worker_root / name
            if candidate.is_file() and not candidate.is_symlink():
                args.extend(("--ro-bind", "/dev/null", str(candidate)))
        args.extend((
            "--chdir", str(self.settings.worker_root), "--", "/usr/bin/python3",
            "/opt/tori-research-network.py", "--child", "--broker",
            "/run/tori-research/egress.sock", "--model", self.settings.model,
            "--embedding-model", self.settings.embedding_model,
            "--", *self.settings.worker_argv,
        ))
        return args

    def _base_sandbox_argv(self) -> list[str]:
        args = [
            str(self.settings.bubblewrap_executable), "--die-with-parent", "--unshare-all",
            "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib",
        ]
        if Path("/usr/lib64").exists():
            args.extend(("--symlink", "usr/lib64", "/lib64"))
        ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
        if ca_bundle.is_file() and not ca_bundle.is_symlink():
            args.extend((
                "--dir", "/etc", "--dir", "/etc/ssl", "--dir", "/etc/ssl/certs",
                "--ro-bind", str(ca_bundle), str(ca_bundle),
            ))
        args.extend(("--proc", "/proc", "--dev", "/dev"))
        return args

    def _read_stdout(self, session: _Session) -> None:
        process = session.process
        assert process is not None and process.stdout is not None
        try:
            for raw in iter(process.stdout.readline, b""):
                if len(raw) > MAX_WORKER_LINE:
                    self._fail_protocol(session, "The worker emitted an oversized event.")
                    return
                try:
                    value = json.loads(raw)
                    if isinstance(value, dict) and value.get("type") == "result":
                        self._verify_result_replay(session, value)
                        continue
                    event = self._event(session, value)
                except (ValueError, TypeError, ResearchWorkerError, ResearchValidationError):
                    self._fail_protocol(session, "The worker emitted a malformed event.")
                    return
                with session.lock:
                    if session.terminal_seen:
                        continue
                    if not session.cancellation_requested:
                        session.state = str(event.payload.get("phase", event.type))
                    if event.type in TERMINAL_WORKER_EVENTS:
                        if session.terminal_document is not None:
                            self._fail_protocol(session, "The worker emitted more than one terminal result.")
                            return
                        session.terminal_event = event
                        session.terminal_document = dict(value)
                if event.type in TERMINAL_WORKER_EVENTS and process.stdin is not None:
                    process.stdin.write(json.dumps({
                        "type": "result", "protocol_version": RESEARCH_WORKER_CONTRACT_VERSION,
                        "job_id": session.binding.job_id,
                        "attempt_id": session.binding.attempt_id,
                    }, separators=(",", ":")).encode() + b"\n")
                    process.stdin.flush()
                    continue
                session.observer(event)
        finally:
            process.stdout.close()

    def _read_stderr(self, session: _Session) -> None:
        process = session.process
        assert process is not None and process.stderr is not None
        for data in iter(lambda: process.stderr.read(4096), b""):
            session.stderr.add(data)

    def _watch(self, session: _Session) -> None:
        process = session.process
        assert process is not None
        code = process.wait()
        with session.lock:
            if session.state == "interrupted" or session.cancellation_acknowledged:
                kind = None
            elif session.cancellation_requested:
                kind = "cancelled"
                session.cancellation_acknowledged = True
                session.state = "cancelled"
                session.terminal_seen = True
            elif not session.terminal_seen:
                kind = "failed"
                session.state = "failed"
                session.terminal_seen = True
            else:
                kind = None
        if kind == "failed":
            with session.lock:
                if session.cancellation_requested:
                    kind = None
        if kind is not None:
            message = "Research was cancelled." if kind == "cancelled" else "The supervised Research Worker exited without a terminal result."
            event = ResearchWorkerEvent(kind, session.binding.job_id, {
                "message": message,
                "code": "cancelled" if kind == "cancelled" else "worker_exited",
                "exit_code": code,
            })
            if kind == "cancelled":
                with session.lock:
                    session.terminal_event = event
                    session.result_verified = True
                self._retain_result(session, event)
            session.observer(event)
        if session.broker is not None:
            session.broker.shutdown()
            session.broker.server_close()
        if session.broker_thread is not None:
            session.broker_thread.join(timeout=2)
        if session.socket_path is not None:
            try:
                session.socket_path.unlink()
            except FileNotFoundError:
                pass
            try:
                session.socket_path.parent.rmdir()
            except OSError:
                pass
        self._retire(session)

    def _enforce_cancellation(self, session: _Session) -> None:
        session.process_ready.wait(self.settings.cancellation_grace_seconds)
        with session.lock:
            process = session.process
            if process is None:
                return
            self._send_cancel_locked(session)
        try:
            process.wait(timeout=self.settings.cancellation_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.settings.cancellation_grace_seconds)
            return
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _fail_protocol(self, session: _Session, message: str) -> None:
        with session.lock:
            if session.terminal_seen:
                return
            session.terminal_seen = True
            cancelled = session.cancellation_requested
            session.state = "cancelling" if cancelled else "failed"
        if not cancelled:
            session.observer(ResearchWorkerEvent("failed", session.binding.job_id, {
                "message": message, "code": "malformed_worker_event",
            }))
        process = session.process
        if process is None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    def _verify_result_replay(self, session: _Session, value: Mapping[str, object]) -> None:
        binding = session.binding
        if (
            value.get("protocol_version") != RESEARCH_WORKER_CONTRACT_VERSION
            or value.get("job_id") != binding.job_id
            or value.get("attempt_id") != binding.attempt_id
            or value.get("terminal") != session.terminal_document
        ):
            self._fail_protocol(session, "The retained worker result differs from the streamed terminal result.")
            return
        with session.lock:
            if session.state == "interrupted":
                return
            session.result_verified = True
            session.terminal_seen = True
            terminal_event = session.terminal_event
            cancelled = session.cancellation_requested
            deliver = terminal_event is not None and (
                not cancelled or (
                    terminal_event.type == "cancelled"
                    and not session.cancellation_acknowledged
                )
            )
            if cancelled and not session.cancellation_acknowledged:
                if deliver:
                    session.cancellation_acknowledged = True
                    session.state = "cancelled"
                else:
                    session.state = "cancelling"
        if deliver:
            self._retain_result(session, terminal_event)
            session.observer(terminal_event)
        process = session.process
        if process is not None and process.stdin is not None:
            process.stdin.close()

    def _session(self, binding: ResearchWorkerBinding) -> _Session:
        with self._lock:
            session = self._sessions.get(binding.job_id)
        if session is None:
            raise ResearchWorkerError("The Research Worker session is unavailable.", code="session_unavailable")
        if session.binding != binding:
            raise ResearchWorkerError("The Research Worker binding is stale.", code="binding_mismatch")
        return session

    @staticmethod
    def _event(session: _Session, value: object) -> ResearchWorkerEvent:
        binding = session.binding
        if not isinstance(value, dict):
            raise ResearchWorkerError("The worker event must be an object.")
        if value.get("protocol_version") != RESEARCH_WORKER_CONTRACT_VERSION:
            raise ResearchWorkerError("The worker protocol version is invalid.")
        kind = value.get("type")
        if kind not in WORKER_EVENT_TYPES:
            raise ResearchWorkerError("The worker event type is unsupported.")
        if value.get("job_id") != binding.job_id:
            raise ResearchWorkerError("The worker event job identity is invalid.")
        if value.get("attempt_id") != binding.attempt_id:
            raise ResearchWorkerError("The worker event attempt identity is invalid.")
        if kind in {"accepted", "status", "completed", "completed_with_limits"}:
            if value.get("effective_limits") != dict(session.expected_limits):
                raise ResearchWorkerError("The worker effective limits differ from authorization.")
            if value.get("effective_runtime") != dict(session.expected_runtime):
                raise ResearchWorkerError("The worker effective runtime differs from configuration.")
        payload = {key: item for key, item in value.items() if key not in {"type", "job_id", "attempt_id", "protocol_version"}}
        json.dumps(payload)
        return ResearchWorkerEvent(str(kind), binding.job_id, payload)


@dataclass(slots=True)
class _FakeResearchSession:
    binding: ResearchWorkerBinding
    observer: EventObserver
    state: str = "running"


class FakeResearchWorker:
    identifier = "fake.research.worker"

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.sessions: dict[str, _FakeResearchSession] = {}

    def readiness(self) -> ResearchWorkerStatus:
        return ResearchWorkerStatus(self.available, "ready" if self.available else "unavailable")

    def start(self, request: ResearchWorkerStartRequest, observer: EventObserver) -> ResearchWorkerBinding:
        if not self.available:
            raise ResearchWorkerError("The fake worker is unavailable.", code="worker_unavailable")
        binding = ResearchWorkerBinding(request.job_id, request.attempt_id, "fake-" + request.attempt_id, None)
        self.sessions[request.job_id] = _FakeResearchSession(binding, observer)
        observer(ResearchWorkerEvent("accepted", request.job_id, {"phase": "planning", "message": "Planning research."}))
        return binding

    def emit(self, job_id: str, kind: str, **payload: object) -> None:
        session = self.sessions[job_id]
        session.observer(ResearchWorkerEvent(kind, job_id, payload))
        if kind in TERMINAL_WORKER_EVENTS:
            session.state = kind

    def status(self, binding: ResearchWorkerBinding) -> ResearchWorkerStatus:
        session = self.sessions.get(binding.job_id)
        return ResearchWorkerStatus(session is not None and session.state == "running", session.state if session else "missing")

    def result(self, binding: ResearchWorkerBinding) -> ResearchWorkerEvent | None:
        session = self.sessions.get(binding.job_id)
        if session is None or session.state not in TERMINAL_WORKER_EVENTS:
            return None
        return ResearchWorkerEvent(session.state, binding.job_id, {})

    def cancel(self, binding: ResearchWorkerBinding) -> None:
        session = self.sessions[binding.job_id]
        self.emit(binding.job_id, "cancelled", message="Research was cancelled.")

    def confirm_cancelled(self, binding: ResearchWorkerBinding) -> None:
        session = self.sessions.get(binding.job_id)
        if session is not None and session.binding == binding:
            session.state = "cancelled"

    def close(self) -> None:
        return
