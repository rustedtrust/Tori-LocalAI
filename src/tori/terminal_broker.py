"""Process-centric PTY sessions admitted only by the execution policy grant.

This is an application-internal broker. Model tools receive neither this object
nor a method for writing to its PTY; input belongs to an attached human browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import fcntl
import hashlib
import os
from pathlib import Path
import queue
from concurrent.futures import ThreadPoolExecutor
import re
import secrets
import select
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time
from typing import Callable

from .coding_work import CodingWorkAuthority
from .coding_work_supervisor import BubblewrapCodingWorkSandbox, CodingWorkerError
from .execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyError
from .terminal_authority import TerminalLocalAuthority
from .terminal_receipts import TerminalReceiptError, TerminalReceiptStore
from .terminal_output import TerminalModelCapture


SCROLLBACK_BYTES = 256 * 1024
ATTACH_TTL_SECONDS = 30
MAX_SESSIONS = 16
MAX_RECENT_SESSIONS = 64
MAX_ATTACH_TICKETS = 128
MAX_FRAME_BYTES = 16 * 1024
MAX_INPUT_BYTES = 4096
_PATH = "/usr/local/bin:/usr/bin:/bin"
_PR_SET_PDEATHSIG = 1
_LIBC = ctypes.CDLL(None, use_errno=True)


class TerminalError(RuntimeError):
    """A safe terminal refusal without command text or output."""


def sanitized_terminal_environment(scope: ExecutionScope) -> dict[str, str]:
    """Construct a complete child environment; never copy the service environment."""
    if scope is ExecutionScope.PROJECT_SANDBOX:
        return {"PATH": _PATH, "HOME": "/tmp/tori-worker-home", "USER": "tori",
                "LOGNAME": "tori", "SHELL": "/bin/sh", "LANG": "C.UTF-8", "TERM": "xterm-256color", "TMPDIR": "/tmp"}
    home = str(Path.home())
    user = os.environ.get("USER") or Path(home).name
    return {"PATH": _PATH, "HOME": home, "USER": user, "LOGNAME": user,
            "SHELL": "/bin/sh", "LANG": "C.UTF-8", "TERM": "xterm-256color", "TMPDIR": "/tmp"}


def _child_terminal_setup(expected_parent: int) -> None:
    # Called after fork, before exec: only kernel-facing operations here.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    if _LIBC.prctl(_PR_SET_PDEATHSIG, signal.SIGHUP, 0, 0, 0) != 0:
        os._exit(127)
    if os.getppid() != expected_parent:
        os._exit(127)


def _command_argv(request: ExecutionRequest) -> tuple[str, ...]:
    if (request.shell_operators or request.opaque or
            (request.argv and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", request.argv[0]))):
        return ("/bin/sh", "-c", request.command)
    try:
        argv = tuple(shlex.split(request.command, posix=True))
    except ValueError as exc:
        raise TerminalError("The approved command cannot be parsed safely.") from exc
    if not argv:
        raise TerminalError("An executable is required.")
    return argv


@dataclass(slots=True)
class _Ticket:
    session_id: str
    owner_digest: str
    expires_at: float


@dataclass(slots=True)
class TerminalAttachment:
    identifier: str
    session_id: str
    owner_digest: str
    events: queue.Queue[tuple[str, object]] = field(default_factory=lambda: queue.Queue(maxsize=128))
    active: bool = True
    controlling: bool = False


@dataclass(slots=True)
class _Session:
    identifier: str
    request: ExecutionRequest
    owner_digest: str
    process: subprocess.Popen[bytes]
    master_fd: int
    started_at: float
    grant_digest: str
    conversation_id: str
    turn_id: str
    state: str = "running"
    exit_code: int | None = None
    ended_at: float | None = None
    termination_reason: str | None = None
    scrollback: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    attachment: TerminalAttachment | None = None
    closed: bool = False
    reader_thread: threading.Thread | None = None
    private_input: bool = False
    capture: TerminalModelCapture = field(default_factory=TerminalModelCapture)


class TerminalBroker:
    def __init__(self, policy: ExecutionPolicyService, *, sandbox: BubblewrapCodingWorkSandbox | None = None,
                 receipts: TerminalReceiptStore,
                 clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic,
                 scrollback_bytes: int = SCROLLBACK_BYTES) -> None:
        if scrollback_bytes < 1024 or scrollback_bytes > SCROLLBACK_BYTES:
            raise ValueError("Invalid terminal scrollback bound.")
        if receipts is None:
            raise ValueError("Durable terminal receipt storage is required.")
        self._policy = policy
        self._receipts = receipts
        self._sandbox = sandbox or BubblewrapCodingWorkSandbox()
        self._clock = clock
        self._monotonic = monotonic
        self._scrollback_bytes = scrollback_bytes
        self._sessions: dict[str, _Session] = {}
        self._tickets: dict[str, _Ticket] = {}
        self._lock = threading.RLock()
        self._shutdown = False
        # PR_SET_PDEATHSIG tracks the creating Linux *thread*. HTTP request
        # threads are short-lived, so all children must be forked here.
        self._spawn_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tori-terminal-spawn")

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _owner(owner: str) -> str:
        if not isinstance(owner, str) or len(owner) < 32 or len(owner) > 256:
            raise TerminalError("A browser session owner is required.")
        return TerminalBroker._digest(owner)

    def launch(self, request: ExecutionRequest, *, grant_token: str, grant_owner: str,
               browser_owner: str, authority: TerminalLocalAuthority,
               conversation_id: str, turn_id: str,
               rows: int = 24, columns: int = 80) -> str:
        """Trusted application entry point; no browser or model route calls it."""
        if not isinstance(authority, TerminalLocalAuthority) or not authority.permits(browser_owner):
            raise TerminalError("A direct local browser interaction is required.")
        owner_digest = self._owner(browser_owner)
        if (not isinstance(conversation_id, str) or not conversation_id
                or len(conversation_id) > 128 or not isinstance(turn_id, str)
                or not turn_id or len(turn_id) > 128):
            raise TerminalError("A conversation and turn binding are required.")
        self._validate_size(rows, columns)
        if not isinstance(request, ExecutionRequest) or request.origin != "tori":
            raise TerminalError("A Tori execution request is required.")
        if request.environment_names:
            raise TerminalError("Explicit environment requests are not supported yet.")
        try:
            if not self._policy.consume_grant(grant_token, request, grant_owner):
                raise TerminalError("A valid execution grant is required.")
        except PolicyError as exc:
            raise TerminalError("Execution policy denied the request.") from exc
        with self._lock:
            if self._shutdown or sum(session.state == "running" for session in self._sessions.values()) >= MAX_SESSIONS:
                raise TerminalError("The terminal broker is unavailable or full.")
            ended = sorted((s for s in self._sessions.values()
                            if s.state == "exited" and s.attachment is None),
                           key=lambda s: s.ended_at or 0)
            for old in ended[:max(0, len(self._sessions) - MAX_RECENT_SESSIONS + 1)]:
                self._sessions.pop(old.identifier, None)
            if len(self._sessions) >= MAX_RECENT_SESSIONS:
                raise TerminalError("The terminal session history is full.")
            argv = _command_argv(request)
            cwd = request.cwd
            if request.scope is ExecutionScope.PROJECT_SANDBOX:
                try:
                    authority = CodingWorkAuthority(cwd, True, True, True)
                    plan = self._sandbox.plan(argv, authority)
                    if tuple(plan.argv[-len(argv):]) != argv:
                        raise TerminalError("The sandbox changed the approved command.")
                    planned = list(plan.argv)
                    # The outer PTY child already calls setsid/TIOCSCTTY. A
                    # second session inside bwrap would detach job control.
                    separator = planned.index("--") if "--" in planned else len(planned) - len(argv)
                    if "--new-session" in planned[:separator]:
                        planned.remove("--new-session")
                    argv = tuple(planned)
                    cwd = plan.workspace_root
                except (CodingWorkerError, OSError, ValueError) as exc:
                    raise TerminalError("Project isolation is unavailable for this request.") from exc
            master = slave = -1
            identifier = "term-" + secrets.token_hex(16)
            started_at = self._clock()
            try:
                self._receipts.start(identifier, request.identity_digest, owner_digest,
                                     self._digest(grant_token), request.scope.value,
                                     request.cwd, started_at, conversation_id, turn_id)
            except TerminalReceiptError as exc:
                raise TerminalError("Terminal audit storage is unavailable.") from exc
            try:
                master, slave = os.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
                parent_pid = os.getpid()
                process = self._spawn_executor.submit(
                    self._spawn_child, argv, cwd, request.scope, slave, parent_pid).result()
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                self._receipts.finish(identifier, state="failed", ended_at=self._clock(),
                                      exit_code=None, reason="spawn_failed")
                raise TerminalError("The terminal process could not be started.") from exc
            finally:
                if slave >= 0:
                    os.close(slave)
                if master >= 0 and "process" not in locals():
                    os.close(master)
            try:
                self._receipts.mark_running(identifier)
            except TerminalReceiptError as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                os.close(master)
                raise TerminalError("Terminal audit storage is unavailable.") from exc
            os.set_blocking(master, False)
            session = _Session(identifier, request, owner_digest, process, master,
                               started_at, self._digest(grant_token), conversation_id, turn_id)
            self._sessions[identifier] = session
            session.reader_thread = threading.Thread(target=self._read_output, args=(session,), daemon=True,
                                                      name="tori-terminal-output")
            session.reader_thread.start()
            threading.Thread(target=self._wait_child, args=(session,), daemon=True,
                             name="tori-terminal-reaper").start()
            return identifier

    @staticmethod
    def _spawn_child(argv: tuple[str, ...], cwd: str, scope: ExecutionScope,
                     slave: int, parent_pid: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            argv, cwd=cwd, env=sanitized_terminal_environment(scope),
            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
            start_new_session=True,
            preexec_fn=lambda: _child_terminal_setup(parent_pid),
        )

    @staticmethod
    def _validate_size(rows: int, columns: int) -> None:
        if type(rows) is not int or type(columns) is not int or not 2 <= rows <= 200 or not 2 <= columns <= 400:
            raise TerminalError("Invalid terminal dimensions.")

    def _owned(self, session_id: str, owner: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None or session.owner_digest != self._owner(owner):
            raise TerminalError("Terminal session unavailable.")
        return session

    def list_sessions(self, owner: str, conversation_id: str | None = None) -> list[dict[str, object]]:
        digest = self._owner(owner)
        with self._lock:
            return [self._metadata(s) for s in self._sessions.values()
                    if s.owner_digest == digest and (conversation_id is None or s.conversation_id == conversation_id)]

    def owns_session(self, session_id: str, owner: str, conversation_id: str | None = None) -> bool:
        with self._lock:
            try:
                session = self._owned(session_id, owner)
                if conversation_id is not None and session.conversation_id != conversation_id:
                    return False
            except TerminalError:
                return False
            return True

    @staticmethod
    def _metadata(session: _Session) -> dict[str, object]:
        return {"id": session.identifier, "request_digest": session.request.identity_digest,
                "conversation_id": session.conversation_id, "turn_id": session.turn_id,
                "scope": session.request.scope.value, "cwd": session.request.cwd,
                "pid": session.process.pid, "state": session.state,
                "started_at": session.started_at, "ended_at": session.ended_at,
                "exit_code": session.exit_code, "termination_reason": session.termination_reason,
                "attached": bool(session.attachment and session.attachment.active),
                "human_control": bool(session.attachment and session.attachment.controlling),
                "private_input": session.private_input,
                "model_capture_locked": session.capture.model_capture_locked,
                "private_interval_count": session.capture.private_intervals,
                "scrollback_truncated": session.truncated}

    def issue_attach_ticket(self, session_id: str, owner: str) -> str:
        with self._lock:
            if self._shutdown:
                raise TerminalError("The terminal broker is shutting down.")
            self._owned(session_id, owner)
            self._tickets = {digest: record for digest, record in self._tickets.items()
                             if record.expires_at > self._monotonic()}
            if len(self._tickets) >= MAX_ATTACH_TICKETS:
                raise TerminalError("Too many pending terminal attachments.")
            token = secrets.token_urlsafe(32)
            self._tickets[self._digest(token)] = _Ticket(session_id, self._owner(owner),
                                                         self._monotonic() + ATTACH_TTL_SECONDS)
            return token

    def attach(self, session_id: str, owner: str, ticket: str) -> tuple[TerminalAttachment, bytes, dict[str, object]]:
        with self._lock:
            if self._shutdown:
                raise TerminalError("The terminal broker is shutting down.")
            session = self._owned(session_id, owner)
            if not isinstance(ticket, str) or not ticket:
                raise TerminalError("A fresh attach ticket is required.")
            record = self._tickets.pop(self._digest(ticket), None)
            if (record is None or record.session_id != session_id or
                    record.owner_digest != session.owner_digest or record.expires_at <= self._monotonic()):
                raise TerminalError("The attach ticket is invalid or expired.")
            if session.attachment is not None:
                session.attachment.active = False
                session.attachment.controlling = False
                self._offer(session.attachment, ("superseded", None))
            attachment = TerminalAttachment(secrets.token_hex(16), session_id, session.owner_digest)
            session.attachment = attachment
            return attachment, bytes(session.scrollback), self._metadata(session)

    @staticmethod
    def _offer(attachment: TerminalAttachment, event: tuple[str, object]) -> None:
        try:
            attachment.events.put_nowait(event)
        except queue.Full:
            attachment.active = False
            attachment.controlling = False

    def _active(self, attachment: TerminalAttachment) -> _Session:
        session = self._sessions.get(attachment.session_id)
        if session is None or session.attachment is not attachment or not attachment.active:
            raise TerminalError("The terminal attachment is no longer active.")
        return session

    def session_state(self, attachment: TerminalAttachment) -> dict[str, object]:
        with self._lock:
            return self._metadata(self._active(attachment))

    def detach(self, attachment: TerminalAttachment) -> None:
        with self._lock:
            attachment.active = False
            attachment.controlling = False
            session = self._sessions.get(attachment.session_id)
            if session is not None and session.attachment is attachment:
                session.attachment = None

    def take_control(self, attachment: TerminalAttachment) -> None:
        with self._lock:
            session = self._active(attachment)
            if session.state != "running":
                raise TerminalError("The process has exited.")
            attachment.controlling = True

    def release_control(self, attachment: TerminalAttachment) -> None:
        with self._lock:
            self._active(attachment)
            attachment.controlling = False

    def enter_private(self, attachment: TerminalAttachment) -> None:
        with self._lock:
            session = self._active(attachment)
            if not attachment.controlling or session.state != "running":
                raise TerminalError("Human terminal control is required for Private Input.")
            if session.private_input:
                return
            try:
                self._receipts.mark_private(session.identifier)
            except TerminalReceiptError as exc:
                raise TerminalError("Private Input audit state is unavailable.") from exc
            session.private_input = True
            session.capture.begin_private()

    def exit_private(self, attachment: TerminalAttachment) -> None:
        with self._lock:
            session = self._active(attachment)
            if not attachment.controlling or not session.private_input:
                raise TerminalError("Human Private Input control is required.")
            # The reader may have taken a chunk before acquiring this lock.
            # Its read epoch remains private. Drain bytes already available
            # before publishing the non-private state to new reads.
            while select.select([session.master_fd], [], [], 0)[0]:
                try:
                    chunk = os.read(session.master_fd, 8192)
                except BlockingIOError:
                    break
                except OSError:
                    break
                if not chunk:
                    break
                self._record_output(session, chunk, private=True)
            session.private_input = False
            session.capture.end_private()

    def model_result(self, session_id: str, *, conversation_id: str,
                     browser_owner: str) -> dict[str, object]:
        """Read-only evidence for the original conversation and browser owner."""
        with self._lock:
            session = self._owned(session_id, browser_owner)
            if session.conversation_id != conversation_id:
                raise TerminalError("Terminal result belongs to another conversation.")
            output, truncated = session.capture.result()
            return {
                "classification": "untrusted_execution_output",
                "session_id": session.identifier, "turn_id": session.turn_id,
                "conversation_id": session.conversation_id,
                "command": session.request.command, "cwd": session.request.cwd,
                "scope": session.request.scope.value, "status": session.state,
                "exit_code": session.exit_code,
                "duration_seconds": round((session.ended_at or self._clock()) - session.started_at, 3),
                "truncated": truncated,
                "private_interval_count": session.capture.private_intervals,
                "model_capture_locked": session.capture.model_capture_locked,
                "output": output,
            }

    def human_input(self, attachment: TerminalAttachment, data: bytes) -> None:
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_INPUT_BYTES:
            raise TerminalError("Invalid terminal input frame.")
        with self._lock:
            session = self._active(attachment)
            if not attachment.controlling or session.state != "running":
                raise TerminalError("Human terminal control is required.")
            try:
                remaining = memoryview(data)
                while remaining:
                    if not select.select([], [session.master_fd], [], 0.25)[1]:
                        raise TerminalError("Terminal input is temporarily unavailable.")
                    written = os.write(session.master_fd, remaining)
                    if written <= 0:
                        raise TerminalError("Terminal input failed.")
                    remaining = remaining[written:]
            except OSError as exc:
                raise TerminalError("Terminal input failed.") from exc

    def resize(self, attachment: TerminalAttachment, rows: int, columns: int) -> None:
        self._validate_size(rows, columns)
        with self._lock:
            session = self._active(attachment)
            if session.state != "running":
                raise TerminalError("The process has exited.")
            fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, columns, 0, 0))
            if not self._signal(session, signal.SIGWINCH):
                raise TerminalError("The terminal process group is unavailable.")

    @staticmethod
    def _signal(session: _Session, sig: signal.Signals) -> bool:
        # The unreaped session leader pins this PGID and prevents PID reuse.
        try:
            if session.closed or os.getpgid(session.process.pid) != session.process.pid:
                return False
            try:
                foreground = os.tcgetpgrp(session.master_fd)
            except OSError:
                foreground = session.process.pid
            try:
                foreground_same_session = os.getsid(foreground) == session.process.pid
            except ProcessLookupError:
                foreground_same_session = False
            if (foreground > 1 and foreground != os.getpgrp()
                    and foreground != session.process.pid
                    and foreground_same_session):
                try:
                    os.killpg(foreground, sig)
                except ProcessLookupError:
                    pass
                else:
                    if sig == signal.SIGINT:
                        return True
            os.killpg(session.process.pid, sig)
            return True
        except (ProcessLookupError, OSError):
            return False

    def signal(self, attachment: TerminalAttachment, kind: str) -> None:
        signals = {"interrupt": signal.SIGINT, "terminate": signal.SIGTERM,
                   "force_kill": signal.SIGKILL}
        if kind not in signals:
            raise TerminalError("Unknown terminal lifecycle operation.")
        with self._lock:
            session = self._active(attachment)
            if session.state != "running":
                raise TerminalError("The process has exited.")
            if not self._signal(session, signals[kind]):
                raise TerminalError("The terminal process group is unavailable.")
            session.termination_reason = kind

    def _read_output(self, session: _Session) -> None:
        while True:
            try:
                if not select.select([session.master_fd], [], [], 0.25)[0]:
                    continue
            except OSError:
                break
            try:
                with self._lock:
                    private_at_read = session.private_input
                    chunk = os.read(session.master_fd, 8192)
                    if not chunk:
                        break
                    self._record_output(session, chunk, private=private_at_read)
            except BlockingIOError:
                continue
            except OSError:
                break

    def _record_output(self, session: _Session, chunk: bytes, *, private: bool) -> None:
        session.capture.feed(chunk, private=private)
        session.scrollback.extend(chunk)
        overflow = len(session.scrollback) - self._scrollback_bytes
        if overflow > 0:
            del session.scrollback[:overflow]
            session.truncated = True
        if session.attachment is not None and session.attachment.active:
            self._offer(session.attachment, ("output", chunk))

    def _wait_child(self, session: _Session) -> None:
        # WNOWAIT leaves the group leader unreaped while descendants are cleaned.
        try:
            os.waitid(os.P_PID, session.process.pid, os.WEXITED | os.WNOWAIT)
        except ChildProcessError:
            pass
        with self._lock:
            if not session.closed:
                self._signal(session, signal.SIGTERM)
        time.sleep(0.1)
        with self._lock:
            if not session.closed:
                self._signal(session, signal.SIGKILL)
        if session.reader_thread is not None:
            session.reader_thread.join(timeout=1)
        with self._lock:
            result = session.process.wait()
            session.closed = True
            session.state = "exited"
            session.exit_code = result
            session.ended_at = self._clock()
            try:
                self._receipts.finish(session.identifier, state="exited",
                                      ended_at=session.ended_at, exit_code=result,
                                      reason=session.termination_reason)
            except TerminalReceiptError:
                session.termination_reason = "audit_failure"
            if session.attachment is not None:
                self._offer(session.attachment, ("exit", self._metadata(session)))
            try:
                os.close(session.master_fd)
            except OSError:
                pass

    def _shutdown_processes(self) -> None:
        with self._lock:
            self._shutdown = True
            self._tickets.clear()
            for session in self._sessions.values():
                if session.attachment is not None:
                    session.attachment.active = False
                    session.attachment.controlling = False
            active = [s for s in self._sessions.values() if s.state == "running"]
            for session in active:
                session.termination_reason = "backend_shutdown"
                self._signal(session, signal.SIGTERM)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with self._lock:
                if all(s.state != "running" for s in active):
                    return
            time.sleep(0.02)
        with self._lock:
            for session in active:
                if session.state == "running":
                    self._signal(session, signal.SIGKILL)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with self._lock:
                if all(s.state != "running" for s in active):
                    return
            time.sleep(0.02)
        raise TerminalError("Terminal shutdown could not prove process cleanup.")

    def shutdown(self) -> None:
        try:
            self._shutdown_processes()
        finally:
            self._spawn_executor.shutdown(wait=True)
