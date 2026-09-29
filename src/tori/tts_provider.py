"""Tori-owned contract for replaceable text-to-speech provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterator, Protocol, runtime_checkable


class TTSProviderError(RuntimeError):
    """Safe provider configuration, availability, or synthesis failure."""

    code = "tts_provider_error"


# Retain the established public error name while provider-specific errors move
# behind this capability contract.
TTSError = TTSProviderError


class TTSConfigurationError(TTSProviderError):
    """The selected provider configuration cannot satisfy the contract."""

    code = "invalid_configuration"


class TTSUnavailableError(TTSProviderError):
    """The selected provider could not complete a synthesis request."""

    code = "provider_unavailable"


class TTSAvailability(str, Enum):
    """Provider reachability observed without implying broader authority."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class TTSProviderIdentity:
    """Stable adapter identity supplied by Tori's allowlisted composition root."""

    provider_type: str
    display_name: str


@dataclass(frozen=True, slots=True)
class TTSConfigurationValidation:
    """Offline validation of one constructed provider configuration."""

    valid: bool
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class TTSProviderStatus:
    """Truthful provider status; construction alone does not prove reachability."""

    configured: bool
    availability: TTSAvailability
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class TTSAudioFormat:
    """Immutable provider-neutral format for one synthesis stream."""

    encoding: str
    sample_rate: int
    channels: int
    sample_width_bytes: int

    @property
    def frame_width_bytes(self) -> int:
        return self.channels * self.sample_width_bytes


PCM_S16LE_MONO_24000 = TTSAudioFormat(
    encoding="pcm_s16le",
    sample_rate=24_000,
    channels=1,
    sample_width_bytes=2,
)
MAX_TTS_RESPONSE_BYTES = 48 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class TTSSynthesisRequest:
    """The complete bounded input that Tori permits an adapter to receive."""

    request_id: str
    text: str
    voice: str
    model: str | None = None
    audio_format: TTSAudioFormat = PCM_S16LE_MONO_24000

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not re.fullmatch(
            r"[A-Za-z0-9._~-]{1,128}", self.request_id
        ):
            raise TTSConfigurationError("The speech request identifier is invalid.")
        if not isinstance(self.text, str) or not self.text.strip():
            raise TTSConfigurationError("Speech input must be non-empty text.")
        if len(self.text) > 2_000 or any(
            ord(character) < 32 and character not in "\n\r\t"
            for character in self.text
        ):
            raise TTSConfigurationError("Speech input is outside the supported boundary.")
        if not isinstance(self.voice, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", self.voice
        ):
            raise TTSConfigurationError("The speech voice identifier is invalid.")
        if self.model is not None and (
            not isinstance(self.model, str)
            or not self.model
            or len(self.model) > 256
            or any(ord(character) < 33 or ord(character) == 127 for character in self.model)
        ):
            raise TTSConfigurationError("The speech model identifier is invalid.")


@dataclass(frozen=True, slots=True)
class TTSAudioChunk:
    """Ordered untrusted audio returned by a provider adapter."""

    data: bytes
    audio_format: TTSAudioFormat


@runtime_checkable
class TextToSpeechProvider(Protocol):
    """Narrow synthesis port; closing the iterator is the cancellation signal."""

    @property
    def identity(self) -> TTSProviderIdentity:
        """Return the allowlisted adapter identity."""

    def validate_configuration(self) -> TTSConfigurationValidation:
        """Validate configuration without contacting the provider."""

    def status(self) -> TTSProviderStatus:
        """Return current truthful status without claiming an implicit probe."""

    def stream(self, request: TTSSynthesisRequest) -> Iterator[TTSAudioChunk]:
        """Yield ordered canonical audio and release resources when closed."""
