"""Standard-library IPC port to an owned, isolated RealtimeSTT bridge."""

from __future__ import annotations

import base64
from collections.abc import Callable
import json
import os
from pathlib import Path
import secrets
import select
import signal
import subprocess
from tempfile import TemporaryDirectory
import threading
import time

from .operator_observability import operator_event
from .speech_recognition import (
    AudioFormat, RecognitionError, RecognitionEvent, RecognitionHealth,
)
from .voice_input_runtime import VoiceRuntimeSettings


MAX_FRAME = 65536
PROFILE = {"realtime": "tiny.en", "final": "small.en", "device": "cuda",
           "compute_type": "int8_float16", "energy_threshold": 100,
           "pre_roll": 0.5, "trailing_silence": 0.8}


def _process_identity(pid: int) -> tuple[int, int, int] | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[2]), int(fields[3]), int(fields[19])  # pgrp, session, start ticks
    except (OSError, ValueError, IndexError):
        return None


class RealtimeSTTAdapter:
    def __init__(self, settings: VoiceRuntimeSettings = VoiceRuntimeSettings()) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self._requests = threading.Lock()
        self._prepare_lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._identity: tuple[int, int, int] | None = None
        self._temporary: TemporaryDirectory[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr: threading.Thread | None = None
        self._ready = threading.Event()
        self._response = threading.Event()
        self._pending_id: int | None = None
        self._reply: dict[str, object] | None = None
        self._request_id = 0
        self._epoch: str | None = None
        self._session_id: str | None = None
        self._emit: Callable[[RecognitionEvent], None] | None = None
        self._state = "off"
        self._stopping = False
        self._stderr_bytes = 0

    @property
    def configured(self) -> bool:
        return self.settings.configured

    def prepare(self) -> None:
        if not self._prepare_lock.acquire(blocking=False):
            raise RecognitionError("invalid_transition")
        try:
            self._prepare()
        finally:
            self._prepare_lock.release()

    def _prepare(self) -> None:
        startup_failed = False
        with self._lock:
            if self._process is not None:
                raise RecognitionError("invalid_transition")
            try:
                executable, models = self.settings.prerequisites()
            except (OSError, RecognitionError):
                self._state = "unavailable"
                raise RecognitionError("runtime_unavailable") from None
            script = Path(__file__).resolve().parents[2] / "deploy" / "voice" / "runtime.py"
            if not script.is_file():
                raise RecognitionError("runtime_unavailable")
            self._temporary = TemporaryDirectory(prefix="tori-voice-")
            root = self._temporary.name
            self._epoch = secrets.token_hex(16)
            self._ready = threading.Event()
            ready_event = self._ready
            self._stopping = False
            self._state = "starting"
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "HOME": root, "TMPDIR": root, "XDG_CACHE_HOME": root,
                   "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                   "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONUNBUFFERED": "1"}
            # Runtime GPU libraries may be explicitly prepared beside the venv.
            library_root = self.settings.environment_root / "lib"  # type: ignore[operator]
            env["LD_LIBRARY_PATH"] = str(library_root)
            try:
                self._process = subprocess.Popen(
                    [str(executable), "-B", str(script), "--bridge"],
                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, start_new_session=True, umask=0o077,
                )
                self._identity = _process_identity(self._process.pid)
                if self._identity is None:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=self.settings.shutdown_seconds)
                    except subprocess.TimeoutExpired:
                        # An unreaped direct Popen child cannot have its PID reused.
                        self._process.kill()
                        self._process.wait(timeout=self.settings.shutdown_seconds)
                    raise OSError("Process identity unavailable")
                bootstrap = {"version": 1, "epoch": self._epoch,
                             "secret": secrets.token_hex(32), "models": str(models),
                             "port": self.settings.port, "profile": PROFILE,
                             "readiness_seconds": self.settings.readiness_seconds}
                assert self._process.stdin is not None
                self._process.stdin.write(_frame(bootstrap))
                self._process.stdin.flush()
                self._reader = threading.Thread(target=self._read, args=(self._process, self._epoch, ready_event), name="tori-voice-ipc", daemon=True)
                self._stderr = threading.Thread(target=self._drain_stderr, args=(self._process,), daemon=True)
                self._reader.start()
                self._stderr.start()
            except (OSError, ValueError):
                self._state = "failed"
                startup_failed = True
        if startup_failed:
            self.stop()
            raise RecognitionError("startup_failed") from None
        operator_event("voice.runtime.starting")
        if not ready_event.wait(self.settings.readiness_seconds):
            self.stop()
            raise RecognitionError("readiness_timeout")
        with self._lock:
            failed = self._state != "ready"
        if failed:
            self.stop()
            raise RecognitionError("startup_failed")
        operator_event("voice.runtime.ready")

    def open_session(self, session_id: str, emit: Callable[[RecognitionEvent], None]) -> None:
        with self._lock:
            if self._session_id is not None:
                raise RecognitionError("invalid_transition")
            self._session_id, self._emit = session_id, emit
        self._request("open", session_id=session_id)
        operator_event("voice.session.opened")

    def begin_utterance(self, utterance_id: str, audio_format: AudioFormat) -> None:
        audio_format.validate()
        self._request("begin", utterance_id=utterance_id,
                      sample_rate=audio_format.sample_rate)

    def feed_audio(self, utterance_id: str, sequence: int, pcm: bytes) -> None:
        self._request("audio", utterance_id=utterance_id, sequence=sequence,
                      pcm=base64.b64encode(pcm).decode("ascii"))

    def finalize_utterance(self, utterance_id: str) -> None:
        self._request("finalize", utterance_id=utterance_id)

    def cancel_utterance(self, utterance_id: str) -> None:
        self._request("cancel", utterance_id=utterance_id)

    def close_session(self) -> None:
        with self._lock:
            if self._session_id is None:
                return
        try:
            self._request("close")
        finally:
            with self._lock:
                self._session_id, self._emit = None, None
            operator_event("voice.session.closed")

    def _request(self, command: str, **fields: object) -> dict[str, object]:
        if not self._requests.acquire(blocking=False):
            raise RecognitionError("backpressure")
        try:
            with self._lock:
                process = self._process
                if self._state != "ready" or not process or process.poll() is not None:
                    raise RecognitionError("session_unavailable")
                self._request_id += 1
                self._pending_id = self._request_id
                self._reply = None
                self._response.clear()
                record = {"command": command, "id": self._request_id,
                          "epoch": self._epoch, "session_id": self._session_id, **fields}
                assert process.stdin is not None
                try:
                    _write_bounded(process.stdin, _frame(record))
                except (OSError, ValueError):
                    raise RecognitionError("communication_failed") from None
            if not self._response.wait(5.0):
                raise RecognitionError("communication_failed")
            with self._lock:
                reply = self._reply
                if not reply or reply.get("ok") is not True:
                    raise RecognitionError(str((reply or {}).get("code", "communication_failed")))
                return reply
        finally:
            with self._lock:
                self._pending_id = None
            self._requests.release()

    def _read(self, process, epoch, ready_event) -> None:
        assert process is not None and process.stdout is not None
        try:
            while True:
                raw = process.stdout.readline(MAX_FRAME + 1)
                if not raw:
                    break
                if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                    raise ValueError("Invalid frame")
                with self._lock:
                    if self._process is not process:
                        return
                record = json.loads(raw)
                if not isinstance(record, dict) or record.get("epoch") != epoch:
                    raise ValueError("Invalid incarnation")
                if record.get("kind") == "ready":
                    if record.get("version") != 1 or record.get("profile") != PROFILE:
                        raise ValueError("Invalid readiness")
                    with self._lock:
                        if not self._stopping:
                            self._state = "ready"
                    ready_event.set()
                elif record.get("kind") == "reply":
                    with self._lock:
                        if type(record.get("id")) is int and record.get("id") == self._pending_id:
                            self._reply = record
                            self._response.set()
                elif record.get("kind") == "event":
                    turn = record.get("utterance_id")
                    if (record.get("event") not in {"partial", "final", "no_speech", "error"}
                        or not isinstance(record.get("session_id"), str)
                        or (turn is not None and (not isinstance(turn, str) or len(turn) > 128))
                        or not isinstance(record.get("text", ""), str)
                        or (record.get("code") is not None and not isinstance(record["code"], str))):
                        raise ValueError("Malformed recognition event")
                    with self._lock:
                        emit, session_id = self._emit, self._session_id
                    if emit and session_id and record.get("session_id") == session_id:
                        emit(RecognitionEvent(session_id, record.get("utterance_id"),  # type: ignore[arg-type]
                                              str(record.get("event")), record.get("text", ""),  # type: ignore[arg-type]
                                              record.get("code")))  # type: ignore[arg-type]
                elif record.get("kind") == "failure":
                    raise ValueError("Worker failed")
                else:
                    raise ValueError("Unknown frame")
        except (OSError, ValueError, TypeError):
            pass
        finally:
            with self._lock:
                if self._process is not process:
                    return
                self._state = "stopping" if self._stopping else "failed"
                emit, session_id = self._emit, self._session_id
                ready_event.set()
                self._response.set()
            if not self._stopping and emit and session_id:
                emit(RecognitionEvent(session_id, None, "error", code="runtime_exited"))

    def _drain_stderr(self, process) -> None:
        assert process is not None and process.stderr is not None
        while True:
            raw = process.stderr.read(4096)
            if not raw:
                return
            # Never retain or log engine stderr; only bounded byte counts are observable.
            self._stderr_bytes = min(65536, self._stderr_bytes + len(raw))

    def health(self) -> RecognitionHealth:
        with self._lock:
            if self._process and self._process.poll() is not None and not self._stopping:
                self._state = "failed"
            return RecognitionHealth(self._state if self.configured else "not_configured")

    def stop(self) -> None:
        with self._stop_lock:
            self._stop()

    def _stop(self) -> None:
        with self._lock:
            process = self._process
            self._stopping = True
            self._state = "stopping"
            self._emit = None
        if process is not None:
            # No executable-name killing; target only the owned Linux session identities.
            self._signal_owned(signal.SIGTERM)
            deadline = time.monotonic() + self.settings.shutdown_seconds
            while self._members() and time.monotonic() < deadline:
                time.sleep(0.02)
            if self._members():
                self._signal_owned(signal.SIGKILL)
                deadline = time.monotonic() + self.settings.shutdown_seconds
                while self._members() and time.monotonic() < deadline:
                    time.sleep(0.02)
            try:
                process.wait(timeout=self.settings.shutdown_seconds)
            except subprocess.TimeoutExpired:
                raise RecognitionError("cleanup_pending") from None
            if self._members():
                raise RecognitionError("cleanup_pending")
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe:
                    pipe.close()
        with self._lock:
            self._process = None
            self._identity = None
            self._session_id, self._emit = None, None
            self._state = "off"
            if self._temporary:
                self._temporary.cleanup()
                self._temporary = None

    def _members(self) -> dict[int, tuple[int, int, int]]:
        process, identity = self._process, self._identity
        if not process or identity is None:
            return {}
        current = _process_identity(process.pid)
        if current is not None and current != identity:
            raise RecognitionError("cleanup_pending")
        members = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            found = _process_identity(pid)
            if found and found[1] == process.pid and found[2] >= identity[2]:
                # Reap the child leader and ignore already-dead zombie descendants.
                try:
                    state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
                except OSError:
                    continue
                if state != "Z":
                    members[pid] = found
        return members

    def _signal_owned(self, signum: int) -> None:
        for pid, identity in self._members().items():
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    if _process_identity(pid) == identity:
                        signal.pidfd_send_signal(descriptor, signum)
                finally:
                    os.close(descriptor)
            except ProcessLookupError:
                pass
            except (AttributeError, OSError):
                # Linux pidfds are the required race-safe forced-cleanup boundary.
                raise RecognitionError("cleanup_pending") from None


def _frame(document: dict[str, object]) -> bytes:
    raw = json.dumps(document, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(raw) > MAX_FRAME:
        raise RecognitionError("backpressure")
    return raw


def _write_bounded(pipe, raw: bytes) -> None:
    descriptor = pipe.fileno()
    os.set_blocking(descriptor, False)
    deadline = time.monotonic() + 5
    try:
        offset = 0
        while offset < len(raw):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [descriptor], [], remaining)[1]:
                raise RecognitionError("communication_failed")
            try:
                offset += os.write(descriptor, raw[offset:])
            except BlockingIOError:
                continue
    finally:
        os.set_blocking(descriptor, True)
