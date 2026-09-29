"""Tori-owned Voice Input state, controller authority, and transient events."""

from __future__ import annotations

from contextlib import contextmanager
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
import secrets
import threading
import time

from .operator_observability import operator_error, operator_event
from .speech_recognition import (
    AudioFormat, RecognitionError, RecognitionEvent, SpeechRecognitionPort,
)


class VoiceState(StrEnum):
    OFF = "off"
    PREPARING = "preparing"
    READY = "ready"
    LISTENING_PTT = "listening_ptt"
    FINALIZING = "finalizing"
    ERROR = "error"
    STOPPING = "stopping"


@dataclass(frozen=True, slots=True)
class VoiceLimits:
    chunk_bytes: int = 32768
    utterance_seconds: float = 60.0
    queued_audio_seconds: float = 1.0
    event_count: int = 128
    text_bytes: int = 8192
    heartbeat_seconds: float = 5.0
    finalization_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not (
            2 <= self.chunk_bytes <= 32768 and self.chunk_bytes % 2 == 0
            and 0 < self.utterance_seconds <= 60 and 0 < self.queued_audio_seconds <= 1
            and 4 <= self.event_count <= 128 and 1 <= self.text_bytes <= 8192
            and 0 < self.heartbeat_seconds <= 5 and 0 < self.finalization_seconds <= 10
        ):
            raise ValueError("Invalid Voice Input bounds.")


@dataclass(frozen=True, slots=True)
class VoiceInputSession:
    epoch: str
    state: VoiceState = VoiceState.OFF
    revision: int = 0
    lease_generation: int = 0
    lease: str | None = None
    session_id: str | None = None
    utterance_id: str | None = None
    segment: int = 0
    sequence: int = 0
    audio_bytes: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FinalTranscriptCandidate:
    """One fenced, transient final awaiting normal Conversation admission."""

    lease_generation: int
    session_id: str
    segment: int
    event_sequence: int
    text: str


class VoiceInputService:
    """One explicit controller; finals are transient, never Conversation turns."""

    def __init__(
        self, recognition: SpeechRecognitionPort, *, limits: VoiceLimits = VoiceLimits(),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.recognition = recognition
        self.limits = limits
        self._clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._session = VoiceInputSession(secrets.token_hex(16))
        self._events: deque[dict[str, object]] = deque()
        self._event_sequence = 0
        self._stream_id: str | None = None
        self._format: AudioFormat | None = None
        self._last_heartbeat = 0.0
        self._deadline: float | None = None
        self._watch_stop = threading.Event()
        self._watch: threading.Thread | None = None
        self._operation_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._failure_session: str | None = None
        self._candidate: FinalTranscriptCandidate | None = None

    def status(self) -> dict[str, object]:
        with self._condition:
            s = self._session
            return {
                "state": s.state.value, "enabled": s.lease is not None,
                "configured": self.recognition.configured,
                "controller_active": s.lease is not None,
                "revision": s.revision, "error": s.error,
                "user_accessible": True,
            }

    def _owner_document(self) -> dict[str, object]:
        s = self._session
        return {**self.status(), "epoch": s.epoch, "lease": s.lease,
                "lease_generation": s.lease_generation, "session_id": s.session_id,
                "utterance_id": s.utterance_id, "segment": s.segment,
                "next_sequence": s.sequence + 1}

    def _transition(self, state: VoiceState, **changes: object) -> None:
        if len(self._events) >= self.limits.event_count:
            raise RecognitionError("backpressure")
        self._session = replace(self._session, state=state,
                                revision=self._session.revision + 1, **changes)
        self._publish("state")

    def _publish(self, kind: str, **fields: object) -> None:
        s = self._session
        # Replace old partials; terminal/control events are never silently evicted.
        if kind == "partial":
            self._events = deque(e for e in self._events if e["kind"] != "partial")
        if len(self._events) >= self.limits.event_count:
            raise RecognitionError("backpressure")
        self._event_sequence += 1
        self._events.append({"kind": kind, "event_sequence": self._event_sequence,
                             "revision": s.revision, "state": s.state.value,
                             "session_id": s.session_id, "utterance_id": s.utterance_id,
                             "segment": s.segment, **fields})
        self._condition.notify_all()

    def _validate(self, binding: Mapping[str, object], *, turn: bool = False) -> None:
        s = self._session
        if (
            not s.lease or binding.get("epoch") != s.epoch
            or not isinstance(binding.get("lease"), str)
            or not binding["lease"].isascii()
            or not secrets.compare_digest(str(binding["lease"]), s.lease)
            or type(binding.get("lease_generation")) is not int
            or binding.get("lease_generation") != s.lease_generation
        ):
            raise RecognitionError("stale_controller")
        if type(binding.get("revision")) is not int or binding["revision"] != s.revision:
            raise RecognitionError("stale_revision")
        if turn and (not s.utterance_id or binding.get("utterance_id") != s.utterance_id):
            raise RecognitionError("stale_segment")

    def acquire(self) -> dict[str, object]:
        with self._condition:
            if self._session.lease is not None or self._session.state is VoiceState.STOPPING:
                raise RecognitionError("controller_busy")
            if self._session.state not in {VoiceState.OFF, VoiceState.ERROR}:
                raise RecognitionError("invalid_transition")
            self._events.clear()
            self._candidate = None
            self._failure_session = None
            self._event_sequence = 0
            self._stream_id = None
            self._last_heartbeat = self._clock()
            lease = secrets.token_hex(32)
            session_id = secrets.token_hex(16)
            self._transition(VoiceState.PREPARING, lease=lease, session_id=session_id,
                             lease_generation=self._session.lease_generation + 1,
                             utterance_id=None, segment=0, sequence=0, audio_bytes=0, error=None)
        operator_event("voice.controller.acquired")
        try:
            self.recognition.prepare()
            with self._condition:
                if self._session.lease != lease:
                    raise RecognitionError("stale_controller")
            self.recognition.open_session(session_id, self._receive)
            with self._condition:
                if self._session.lease != lease:
                    raise RecognitionError("stale_controller")
                self._last_heartbeat = self._clock()
                self._transition(VoiceState.READY)
                self._start_watch()
                return self._owner_document()
        except Exception as exc:
            code = exc.code if isinstance(exc, RecognitionError) else "startup_failed"
            self._fail(code, expected_session=session_id)
            raise RecognitionError(code) from None

    def heartbeat(self, binding: Mapping[str, object]) -> dict[str, object]:
        with self._condition:
            self._validate(binding)
            self._last_heartbeat = self._clock()
            return self._owner_document()

    @contextmanager
    def _operation(self):
        if not self._operation_lock.acquire(blocking=False):
            raise RecognitionError("backpressure")
        try:
            yield
        finally:
            self._operation_lock.release()

    def begin(self, binding: Mapping[str, object], audio_format: AudioFormat) -> dict[str, object]:
        audio_format.validate()
        with self._operation():
            with self._condition:
                self._validate(binding)
                if self._session.state is not VoiceState.READY:
                    raise RecognitionError("invalid_transition")
                utterance = secrets.token_hex(16)
                self._format = audio_format
                self._events = deque(e for e in self._events if e["kind"] != "partial")
                self._candidate = None
                self._deadline = self._clock() + self.limits.utterance_seconds
                self._transition(VoiceState.LISTENING_PTT, utterance_id=utterance,
                                 segment=self._session.segment + 1, sequence=0, audio_bytes=0,
                                 error=None)
                session_id = self._session.session_id
            try:
                self.recognition.begin_utterance(utterance, audio_format)
            except Exception:
                self._fail("communication_failed", expected_session=session_id)
                raise RecognitionError("communication_failed") from None
            with self._condition:
                if self._session.session_id != session_id or self._session.utterance_id != utterance:
                    raise RecognitionError("stale_controller")
                operator_event("voice.utterance.began", segment=self._session.segment)
                return self._owner_document()

    def audio(self, binding: Mapping[str, object], sequence: object, pcm: bytes) -> dict[str, object]:
        # Serialized bounded requests: no unbounded executor queue or audio upload path.
        if not self._operation_lock.acquire(blocking=False):
            raise RecognitionError("backpressure")
        try:
            with self._condition:
                self._validate(binding, turn=True)
                s = self._session
                if s.state is not VoiceState.LISTENING_PTT:
                    raise RecognitionError("invalid_transition")
                if (
                    type(sequence) is not int or sequence != s.sequence + 1
                    or not isinstance(pcm, bytes) or not pcm or len(pcm) % 2
                    or len(pcm) > self.limits.chunk_bytes
                ):
                    raise RecognitionError("malformed_audio")
                assert self._format is not None
                if len(pcm) > self._format.sample_rate * 2 * self.limits.queued_audio_seconds:
                    raise RecognitionError("backpressure")
                total = s.audio_bytes + len(pcm)
                if total > self._format.sample_rate * 2 * self.limits.utterance_seconds:
                    raise RecognitionError("utterance_limit")
                utterance, session_id = s.utterance_id, s.session_id
            try:
                assert utterance is not None
                self.recognition.feed_audio(utterance, sequence, pcm)
            except Exception:
                self._fail("communication_failed", expected_session=session_id)
                raise RecognitionError("communication_failed") from None
            with self._condition:
                self._validate(binding, turn=True)
                self._session = replace(self._session, sequence=sequence, audio_bytes=total)
                return self._owner_document()
        finally:
            self._operation_lock.release()

    def finalize(self, binding: Mapping[str, object], last_sequence: object) -> dict[str, object]:
        with self._operation():
            with self._condition:
                self._validate(binding, turn=True)
                s = self._session
                if s.state is not VoiceState.LISTENING_PTT:
                    raise RecognitionError("invalid_transition")
                if type(last_sequence) is not int or last_sequence != s.sequence:
                    raise RecognitionError("malformed_audio")
                self._transition(VoiceState.FINALIZING)
                self._deadline = self._clock() + self.limits.finalization_seconds
                utterance, session_id = s.utterance_id, s.session_id
            try:
                assert utterance is not None
                self.recognition.finalize_utterance(utterance)
            except Exception:
                self._fail("communication_failed", expected_session=session_id)
                raise RecognitionError("communication_failed") from None
            with self._condition:
                operator_event("voice.utterance.finalized", segment=s.segment)
                return self._owner_document()

    def cancel(self, binding: Mapping[str, object]) -> dict[str, object]:
        with self._operation():
            with self._condition:
                self._validate(binding, turn=True)
                if self._session.state not in {VoiceState.LISTENING_PTT, VoiceState.FINALIZING}:
                    raise RecognitionError("invalid_transition")
                utterance, session_id = self._session.utterance_id, self._session.session_id
                # Fence before native reset, without claiming READY before quiescence.
                self._transition(VoiceState.FINALIZING, utterance_id=None)
                self._deadline = None
            try:
                assert utterance is not None
                self.recognition.cancel_utterance(utterance)
            except Exception:
                self._fail("communication_failed", expected_session=session_id)
                raise RecognitionError("communication_failed") from None
            with self._condition:
                if self._session.session_id != session_id:
                    raise RecognitionError("stale_controller")
                self._events.clear()
                self._candidate = None
                self._transition(VoiceState.READY)
                operator_event("voice.utterance.cancelled")
                return self._owner_document()

    def clear(self, binding: Mapping[str, object]) -> dict[str, object]:
        with self._condition:
            self._validate(binding)
            self._events.clear()
            self._candidate = None
            self._publish("cleared")
            return self._owner_document()

    def release(self, binding: Mapping[str, object]) -> dict[str, object]:
        with self._condition:
            self._validate(binding)
        self.shutdown(expected_session=self._session.session_id, binding=binding)
        return self.status()

    def shutdown(self, *, expected_session: str | None = None,
                 binding: Mapping[str, object] | None = None,
                 failure_code: str | None = None) -> None:
        with self._condition:
            if binding is not None:
                self._validate(binding)
            if expected_session is not None and self._session.session_id != expected_session:
                return
            if self._session.state is VoiceState.OFF:
                return
            if not self._cleanup_lock.acquire(blocking=False):
                return
            self._events.clear()
            self._deadline = None
            self._stream_id = None
            self._transition(VoiceState.STOPPING, lease=None, session_id=None,
                             utterance_id=None, lease_generation=self._session.lease_generation + 1)
            self._watch_stop.set()
        try:
            try:
                self.recognition.close_session()
            except Exception:
                pass  # confirmed runtime stop supersedes a close error
            try:
                self.recognition.stop()
            except Exception:
                with self._condition:
                    self._transition(VoiceState.STOPPING, error="cleanup_pending")
                operator_error("voice.runtime.cleanup_failed", code="cleanup_pending")
                return
            with self._condition:
                self._format = None
                self._transition(VoiceState.ERROR if failure_code else VoiceState.OFF,
                                 error=failure_code, sequence=0, audio_bytes=0)
            operator_event("voice.runtime.stopped")
        finally:
            self._cleanup_lock.release()

    def _fail(self, code: str, *, expected_session: str | None) -> None:
        if expected_session is None:
            return
        code = RecognitionError(code).code
        self.shutdown(expected_session=expected_session, failure_code=code)
        operator_error("voice.runtime.failed", code=code)

    def _receive(self, event: RecognitionEvent) -> None:
        try:
            with self._condition:
                s = self._session
                if event.session_id != s.session_id or not s.lease:
                    return
                if event.kind == "error" and event.utterance_id is None:
                    code = event.code or "communication_failed"
                elif not s.utterance_id or event.utterance_id != s.utterance_id:
                    return
                elif event.kind == "partial" and s.state is VoiceState.LISTENING_PTT:
                    self._validate_text(event.text)
                    self._publish("partial", text=event.text)
                    return
                elif event.kind in {"final", "no_speech"} and s.state is VoiceState.FINALIZING:
                    self._validate_text(event.text)
                    text = event.text.strip()
                    kind = "final" if event.kind == "final" and text else "no_speech"
                    operator_event("voice.recognition.result", chars=len(text) if kind == "final" else 0,
                                   kind=kind, segment=s.segment)
                    self._publish(kind, text=text if kind == "final" else "",
                                  code=None if kind == "final" else "empty_transcript")
                    if kind == "final":
                        self._candidate = FinalTranscriptCandidate(
                            lease_generation=s.lease_generation,
                            session_id=s.session_id or "",
                            segment=s.segment,
                            event_sequence=self._event_sequence,
                            text=text,
                        )
                    self._deadline = None
                    self._transition(VoiceState.READY, utterance_id=None, audio_bytes=0)
                    return
                elif event.kind == "error":
                    operator_event("voice.recognition.result", chars=0, kind="error", segment=s.segment)
                    code = event.code or "communication_failed"
                else:
                    return
            self._schedule_failure(code, event.session_id)
        except RecognitionError as exc:
            self._schedule_failure(exc.code, event.session_id)

    def _schedule_failure(self, code: str, session_id: str) -> None:
        # One cleanup task per lease; malicious/repeated errors cannot spawn a queue.
        with self._condition:
            if self._session.session_id != session_id or self._failure_session == session_id:
                return
            self._failure_session = session_id
        threading.Thread(target=self._fail, kwargs={"code": code,
                         "expected_session": session_id}, daemon=True).start()

    def _validate_text(self, text: object) -> None:
        if not isinstance(text, str):
            raise RecognitionError("communication_failed")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeError:
            raise RecognitionError("communication_failed") from None
        if size > self.limits.text_bytes:
            raise RecognitionError("communication_failed")
        if any(ord(c) < 32 and c not in "\n\t" for c in text):
            raise RecognitionError("communication_failed")

    def claim_final(
        self, binding: Mapping[str, object], segment: object, event_sequence: object
    ) -> str:
        """Claim one current final exactly once for ordinary Conversation admission."""

        with self._condition:
            self._validate(binding)
            candidate = self._candidate
            if (
                candidate is None
                or type(segment) is not int
                or type(event_sequence) is not int
                or candidate.lease_generation != self._session.lease_generation
                or candidate.session_id != self._session.session_id
                or candidate.segment != segment
                or candidate.event_sequence != event_sequence
            ):
                raise RecognitionError("stale_segment")
            self._candidate = None
            return candidate.text

    def events(self, binding: Mapping[str, object]) -> Iterator[dict[str, object]]:
        with self._condition:
            self._validate(binding)
            if self._stream_id is not None:
                raise RecognitionError("controller_busy")
            stream_id = secrets.token_hex(16)
            self._stream_id = stream_id
            lease = self._session.lease
            session_id = self._session.session_id

        def stream() -> Iterator[dict[str, object]]:
            try:
                while True:
                    with self._condition:
                        if self._stream_id != stream_id or self._session.lease != lease:
                            return
                        if not self._events:
                            self._condition.wait(timeout=1.0)
                        if self._events:
                            event = self._events.popleft()
                        else:
                            event = {"kind": "heartbeat", "revision": self._session.revision}
                    yield event
            finally:
                with self._condition:
                    current = self._stream_id == stream_id and self._session.lease == lease
                if current:
                    self.shutdown(expected_session=session_id)  # disconnect never transfers control
        return stream()

    def _start_watch(self) -> None:
        self._watch_stop = threading.Event()
        stop = self._watch_stop
        def watch() -> None:
            while not stop.wait(0.25):
                self.check_liveness()
        self._watch = threading.Thread(target=watch, name="tori-voice-watch", daemon=True)
        self._watch.start()

    def check_liveness(self) -> None:
        with self._condition:
            s = self._session
            if not s.lease or s.state is VoiceState.PREPARING:
                return
            expired = self._clock() - self._last_heartbeat > self.limits.heartbeat_seconds
            timeout = self._deadline is not None and self._clock() > self._deadline
        if expired:
            self.shutdown(expected_session=s.session_id)
        elif timeout:
            self._fail("utterance_limit" if s.state is VoiceState.LISTENING_PTT
                       else "finalization_timeout", expected_session=s.session_id)
        else:
            try:
                health = self.recognition.health()
            except Exception:
                self._fail("communication_failed", expected_session=s.session_id)
            else:
                if health.state != "ready":
                    self._fail("runtime_exited", expected_session=s.session_id)
