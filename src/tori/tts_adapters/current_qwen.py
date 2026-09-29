"""Compatibility adapter for Tori's currently approved local Qwen TTS service."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import http.client
import json
import threading
from urllib.parse import urlsplit

from .. import __version__
from ..local_endpoints import is_valid_local_http_endpoint
from ..tts_provider import (
    MAX_TTS_RESPONSE_BYTES,
    PCM_S16LE_MONO_24000,
    TTSAudioChunk,
    TTSAvailability,
    TTSConfigurationError,
    TTSConfigurationValidation,
    TTSProviderIdentity,
    TTSProviderError,
    TTSProviderStatus,
    TTSSynthesisRequest,
    TTSUnavailableError,
)


DEFAULT_TTS_ENDPOINT = "http://127.0.0.1:8000"
DEFAULT_TTS_PROVIDER = "qwen"
_CURRENT_MODEL = "tts-1"


@dataclass(frozen=True, slots=True)
class _HTTPPCMResponse:
    status: int
    content_type: str
    content_length: int | None
    read: Callable[[int], bytes]
    close: Callable[[], None]


TTSHTTPTransport = Callable[[str, bytes, float, float], _HTTPPCMResponse]


class CurrentQwenTTSAdapter:
    """Preserve the current streaming behavior behind Tori's provider port."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_TTS_ENDPOINT,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 30.0,
        transport: TTSHTTPTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self.read_timeout_seconds = float(read_timeout_seconds)
        validation = self.validate_configuration()
        if not validation.valid:
            raise TTSConfigurationError(
                "The configured local speech provider is invalid."
            )
        self._transport = transport or _default_http_transport
        self._status_lock = threading.Lock()
        self._status = TTSProviderStatus(
            configured=True,
            availability=TTSAvailability.UNKNOWN,
            reason_code="not_checked",
        )

    @property
    def identity(self) -> TTSProviderIdentity:
        return TTSProviderIdentity(DEFAULT_TTS_PROVIDER, "Local Qwen TTS")

    def validate_configuration(self) -> TTSConfigurationValidation:
        if not is_valid_qwen_endpoint(self.endpoint):
            return TTSConfigurationValidation(False, "endpoint_not_approved")
        if not 0 < self.connect_timeout_seconds <= 10:
            return TTSConfigurationValidation(False, "invalid_connect_timeout")
        if not 0 < self.read_timeout_seconds <= 120:
            return TTSConfigurationValidation(False, "invalid_read_timeout")
        return TTSConfigurationValidation(True)

    def status(self) -> TTSProviderStatus:
        with self._status_lock:
            return self._status

    def _set_status(
        self, availability: TTSAvailability, reason_code: str | None = None
    ) -> None:
        with self._status_lock:
            self._status = TTSProviderStatus(True, availability, reason_code)

    def stream(self, request: TTSSynthesisRequest) -> Iterator[TTSAudioChunk]:
        _validate_request(request)
        payload = json.dumps(
            {
                "model": request.model or _CURRENT_MODEL,
                "input": request.text,
                "voice": request.voice,
                "response_format": "pcm",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            response = self._transport(
                f"{self.endpoint}/v1/audio/speech",
                payload,
                self.connect_timeout_seconds,
                self.read_timeout_seconds,
            )
        except TTSProviderError as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, exc.code)
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, "provider_unreachable")
            raise TTSUnavailableError(
                "The local speech service is unavailable."
            ) from exc

        try:
            if response.status != 200:
                raise TTSUnavailableError(
                    "The local speech service could not generate audio."
                )
            content_type = response.content_type.split(";", 1)[0].strip().casefold()
            if content_type not in {
                "application/octet-stream", "audio/l16", "audio/pcm", "audio/raw",
            }:
                raise TTSUnavailableError(
                    "The local speech service returned an unsupported audio format."
                )
            if response.content_length is not None and not (
                0 < response.content_length <= MAX_TTS_RESPONSE_BYTES
            ):
                raise TTSUnavailableError(
                    "The local speech service returned an invalid audio size."
                )

            return _QwenAudioStream(
                response,
                on_available=lambda: self._set_status(TTSAvailability.AVAILABLE),
                on_failure=lambda code: self._set_status(
                    TTSAvailability.UNAVAILABLE, code
                ),
            )
        except TTSUnavailableError as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, exc.code)
            response.close()
            raise


class _QwenAudioStream(Iterator[TTSAudioChunk]):
    """Thread-closeable view over one current-provider PCM response."""

    def __init__(
        self,
        response: _HTTPPCMResponse,
        *,
        on_available: Callable[[], None],
        on_failure: Callable[[str], None],
    ) -> None:
        self._response = response
        self._on_available = on_available
        self._on_failure = on_failure
        self._lock = threading.Lock()
        self._closed = False
        self._carry = b""
        self._yielded = False
        self._total = 0

    def __iter__(self) -> _QwenAudioStream:
        return self

    def __next__(self) -> TTSAudioChunk:
        with self._lock:
            if self._closed:
                raise StopIteration
        try:
            block = self._response.read(16 * 1024)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            with self._lock:
                cancelled = self._closed
            if cancelled:
                raise StopIteration from None
            self._fail("stream_interrupted")
            raise AssertionError("unreachable") from exc
        with self._lock:
            if self._closed:
                raise StopIteration
        if not block:
            if self._carry or not self._yielded:
                self._fail("invalid_response")
            self._on_available()
            self.close()
            raise StopIteration
        if not isinstance(block, bytes):
            self._fail("invalid_response")
        self._total += len(block)
        if self._total > MAX_TTS_RESPONSE_BYTES:
            self._fail("response_too_large")
        block = self._carry + block
        even_length = len(block) - (len(block) % 2)
        self._carry = block[even_length:]
        if not even_length:
            return self.__next__()
        self._yielded = True
        return TTSAudioChunk(block[:even_length], PCM_S16LE_MONO_24000)

    def _fail(self, reason_code: str) -> None:
        self._on_failure(reason_code)
        self.close()
        raise TTSUnavailableError(
            "The local speech service returned malformed audio."
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._response.close()
        except (OSError, http.client.HTTPException):
            pass


def _validate_request(request: TTSSynthesisRequest) -> None:
    if not isinstance(request, TTSSynthesisRequest):
        raise TTSConfigurationError("The speech request is invalid.")
    if request.audio_format != PCM_S16LE_MONO_24000:
        raise TTSConfigurationError("The requested speech audio format is unsupported.")
    if request.model not in {None, _CURRENT_MODEL}:
        raise TTSConfigurationError("The requested speech model is unsupported.")
    if not isinstance(request.request_id, str) or not request.request_id:
        raise TTSConfigurationError("The speech request identifier is invalid.")
    if not isinstance(request.text, str) or not request.text:
        raise TTSConfigurationError("The speech input is invalid.")
    if not isinstance(request.voice, str) or not request.voice:
        raise TTSConfigurationError("The speech voice is invalid.")


def validate_qwen_profile_selection(model: str | None) -> None:
    """Validate adapter-scoped saved selection without contacting Qwen."""
    if model not in {None, _CURRENT_MODEL}:
        raise TTSConfigurationError("The selected speech model is unsupported.")


def is_valid_qwen_endpoint(endpoint: str) -> bool:
    """Accept Qwen only at an explicit numeric loopback/RFC1918 HTTP root."""

    return is_valid_local_http_endpoint(endpoint)


def _default_http_transport(
    url: str,
    payload: bytes,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
) -> _HTTPPCMResponse:
    parsed = urlsplit(url)
    base_endpoint = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    if (
        not is_valid_qwen_endpoint(base_endpoint)
        or parsed.path != "/v1/audio/speech"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise TTSUnavailableError("The local speech endpoint is invalid.")
    connection = http.client.HTTPConnection(
        parsed.hostname, parsed.port, timeout=connect_timeout_seconds
    )
    try:
        connection.connect()
        if connection.sock is None:
            raise TTSUnavailableError("The local speech service is unavailable.")
        connection.sock.settimeout(read_timeout_seconds)
        connection.request(
            "POST",
            parsed.path,
            body=payload,
            headers={
                "Accept": "application/octet-stream, audio/pcm",
                "Content-Type": "application/json",
            "User-Agent": f"Tori/{__version__}",
            },
        )
        response = connection.getresponse()
        length_header = response.getheader("Content-Length")
        try:
            content_length = int(length_header) if length_header is not None else None
        except ValueError as exc:
            response.close()
            connection.close()
            raise TTSUnavailableError(
                "The local speech service returned invalid response metadata."
            ) from exc

        def close_response() -> None:
            response.close()
            connection.close()

        return _HTTPPCMResponse(
            response.status,
            response.getheader("Content-Type", ""),
            content_length,
            response.read,
            close_response,
        )
    except Exception:
        connection.close()
        raise


__all__ = [
    "CurrentQwenTTSAdapter",
    "DEFAULT_TTS_ENDPOINT",
    "DEFAULT_TTS_PROVIDER",
    "MAX_TTS_RESPONSE_BYTES",
    "TTSHTTPTransport",
    "is_valid_qwen_endpoint",
    "validate_qwen_profile_selection",
    "_HTTPPCMResponse",
]
