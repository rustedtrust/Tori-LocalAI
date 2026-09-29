"""Engine-independent contracts for transient, manually bounded recognition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


ERROR_CODES = frozenset({
    "runtime_unavailable", "startup_failed", "readiness_timeout", "runtime_exited",
    "session_unavailable", "stale_controller", "stale_revision", "stale_segment",
    "invalid_transition", "malformed_audio", "backpressure", "finalization_timeout",
    "empty_transcript", "communication_failed", "cleanup_pending", "controller_busy",
    "invalid_request", "event_gap", "utterance_limit",
})


class RecognitionError(RuntimeError):
    """A closed error category; engine exception text is never public."""

    def __init__(self, code: str) -> None:
        self.code = code if code in ERROR_CODES else "communication_failed"
        super().__init__(f"Voice Input: {self.code.replace('_', ' ')}.")


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int = 1
    encoding: str = "pcm_s16le"

    def validate(self) -> None:
        if (
            type(self.sample_rate) is not int or self.sample_rate not in {44100, 48000}
            or type(self.channels) is not int or self.channels != 1
            or self.encoding != "pcm_s16le"
        ):
            raise RecognitionError("malformed_audio")


@dataclass(frozen=True, slots=True)
class RecognitionEvent:
    session_id: str
    utterance_id: str | None
    kind: str
    text: str = ""
    code: str | None = None


@dataclass(frozen=True, slots=True)
class RecognitionHealth:
    state: str  # not_configured, starting, ready, unavailable, failed, stopping, off


@runtime_checkable
class SpeechRecognitionPort(Protocol):
    """No Conversation, device, TTS, persistence, or provider objects cross here."""

    @property
    def configured(self) -> bool: ...

    def prepare(self) -> None:
        """Prepare preinstalled assets within the adapter's readiness deadline."""

    def open_session(self, session_id: str, emit: Callable[[RecognitionEvent], None]) -> None: ...

    def begin_utterance(self, utterance_id: str, audio_format: AudioFormat) -> None: ...

    def feed_audio(self, utterance_id: str, sequence: int, pcm: bytes) -> None: ...

    def finalize_utterance(self, utterance_id: str) -> None:
        """Acknowledge pending final; emit exactly one final/no-speech/error later."""

    def cancel_utterance(self, utterance_id: str) -> None:
        """Return only after old turn work cannot contaminate a new turn."""

    def close_session(self) -> None: ...

    def stop(self) -> None:
        """Boundedly stop owned descendants or report cleanup_pending."""

    def health(self) -> RecognitionHealth: ...
