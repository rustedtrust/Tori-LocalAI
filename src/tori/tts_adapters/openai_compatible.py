"""OpenAI-compatible local text-to-speech adapter.

This is Tori's normal profile contract.  It intentionally knows no vendor or
model names: a configured local endpoint accepts the standard speech request
and returns a WAV representation that can be checked before browser playback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
import http.client
import json
import threading
from urllib.parse import urlsplit
import wave

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


OPENAI_COMPATIBLE_TTS = "openai_compatible"


@dataclass(frozen=True, slots=True)
class _HTTPResponse:
    status: int
    content_type: str
    content_length: int | None
    read: Callable[[int], bytes]
    close: Callable[[], None]


TTSHTTPTransport = Callable[[str, bytes, float, float], _HTTPResponse]


class OpenAICompatibleTTSAdapter:
    """Translate the bounded Tori request to one local OpenAI-style endpoint."""

    def __init__(
        self,
        *,
        endpoint: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        transport: TTSHTTPTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.connect_timeout_seconds = float(connect_timeout_seconds)
        self.read_timeout_seconds = float(read_timeout_seconds)
        validation = self.validate_configuration()
        if not validation.valid:
            raise TTSConfigurationError("The configured OpenAI-compatible speech profile is invalid.")
        self._transport = transport or _default_http_transport
        self._status_lock = threading.Lock()
        self._status = TTSProviderStatus(True, TTSAvailability.UNKNOWN, "not_checked")

    @property
    def identity(self) -> TTSProviderIdentity:
        return TTSProviderIdentity(OPENAI_COMPATIBLE_TTS, "OpenAI-compatible TTS")

    def validate_configuration(self) -> TTSConfigurationValidation:
        if not is_valid_openai_compatible_endpoint(self.endpoint):
            return TTSConfigurationValidation(False, "endpoint_not_approved")
        if not 0 < self.connect_timeout_seconds <= 10:
            return TTSConfigurationValidation(False, "invalid_connect_timeout")
        if not 0 < self.read_timeout_seconds <= 120:
            return TTSConfigurationValidation(False, "invalid_read_timeout")
        return TTSConfigurationValidation(True)

    def status(self) -> TTSProviderStatus:
        with self._status_lock:
            return self._status

    def _set_status(self, availability: TTSAvailability, reason_code: str | None = None) -> None:
        with self._status_lock:
            self._status = TTSProviderStatus(True, availability, reason_code)

    def stream(self, request: TTSSynthesisRequest) -> Iterator[TTSAudioChunk]:
        if not isinstance(request, TTSSynthesisRequest):
            raise TTSConfigurationError("The speech request is invalid.")
        if request.audio_format != PCM_S16LE_MONO_24000:
            raise TTSConfigurationError("The requested speech audio format is unsupported.")
        payload_document: dict[str, object] = {
            "input": request.text,
            "voice": request.voice,
            "response_format": "wav",
        }
        if request.model is not None:
            payload_document["model"] = request.model
        payload = json.dumps(payload_document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            response = self._transport(
                f"{self.endpoint}/audio/speech", payload,
                self.connect_timeout_seconds, self.read_timeout_seconds,
            )
        except TTSProviderError as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, exc.code)
            raise
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, "provider_unreachable")
            raise TTSUnavailableError("The configured speech service is unavailable.") from exc
        try:
            if response.status != 200:
                raise TTSUnavailableError("The configured speech service could not generate audio.")
            content_type = response.content_type.split(";", 1)[0].strip().casefold()
            if content_type not in {"audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"}:
                raise TTSUnavailableError("The configured speech service returned an unsupported audio format.")
            if response.content_length is not None and not 0 < response.content_length <= MAX_TTS_RESPONSE_BYTES:
                raise TTSUnavailableError("The configured speech service returned an invalid audio size.")
            data = _read_bounded_response(response)
            pcm = _decode_wav(data)
            self._set_status(TTSAvailability.AVAILABLE)
            return _PCMStream(pcm, response.close)
        except TTSUnavailableError as exc:
            self._set_status(TTSAvailability.UNAVAILABLE, exc.code)
            response.close()
            raise


class _PCMStream(Iterator[TTSAudioChunk]):
    def __init__(self, data: bytes, close: Callable[[], None]) -> None:
        self._data = data
        self._close = close
        self._offset = 0
        self._closed = False

    def __iter__(self) -> _PCMStream:
        return self

    def __next__(self) -> TTSAudioChunk:
        if self._closed or self._offset >= len(self._data):
            self.close()
            raise StopIteration
        block = self._data[self._offset:self._offset + 16 * 1024]
        self._offset += len(block)
        return TTSAudioChunk(block, PCM_S16LE_MONO_24000)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._close()
        except (OSError, http.client.HTTPException):
            pass


def is_valid_openai_compatible_endpoint(endpoint: str) -> bool:
    """Allow only numeric local API roots, optionally with the conventional /v1."""
    if not isinstance(endpoint, str):
        return False
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return False
    if (
        port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/v1"}
    ):
        return False
    return is_valid_local_http_endpoint(f"{parsed.scheme}://{parsed.hostname}:{port}")


def _read_bounded_response(response: _HTTPResponse) -> bytes:
    parts: list[bytes] = []
    total = 0
    while True:
        try:
            block = response.read(16 * 1024)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise TTSUnavailableError("The configured speech service response was interrupted.") from exc
        if not block:
            break
        if not isinstance(block, bytes):
            raise TTSUnavailableError("The configured speech service returned malformed audio.")
        total += len(block)
        if total > MAX_TTS_RESPONSE_BYTES:
            raise TTSUnavailableError("The configured speech service returned an invalid audio size.")
        parts.append(block)
    if not parts:
        raise TTSUnavailableError("The configured speech service returned malformed audio.")
    return b"".join(parts)


def _decode_wav(data: bytes) -> bytes:
    try:
        with wave.open(BytesIO(data), "rb") as source:
            if source.getcomptype() != "NONE" or source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != 24_000:
                raise TTSUnavailableError("The configured speech service returned an unsupported audio format.")
            pcm = source.readframes(source.getnframes())
    except (wave.Error, EOFError) as exc:
        raise TTSUnavailableError("The configured speech service returned malformed audio.") from exc
    if not pcm or len(pcm) % 2:
        raise TTSUnavailableError("The configured speech service returned malformed audio.")
    return pcm


def _default_http_transport(url: str, payload: bytes, connect_timeout_seconds: float, read_timeout_seconds: float) -> _HTTPResponse:
    parsed = urlsplit(url)
    endpoint = url.rsplit("/audio/speech", 1)[0]
    if not is_valid_openai_compatible_endpoint(endpoint) or parsed.path not in {"/audio/speech", "/v1/audio/speech"} or parsed.query or parsed.fragment:
        raise TTSUnavailableError("The configured speech endpoint is invalid.")
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=connect_timeout_seconds)
    try:
        connection.connect()
        if connection.sock is None:
            raise TTSUnavailableError("The configured speech service is unavailable.")
        connection.sock.settimeout(read_timeout_seconds)
        connection.request("POST", parsed.path, body=payload, headers={"Accept": "audio/wav", "Content-Type": "application/json", "User-Agent": f"Tori/{__version__}"})
        response = connection.getresponse()
        try:
            length = response.getheader("Content-Length")
            content_length = int(length) if length is not None else None
        except ValueError as exc:
            response.close(); connection.close()
            raise TTSUnavailableError("The configured speech service returned invalid response metadata.") from exc
        return _HTTPResponse(response.status, response.getheader("Content-Type", ""), content_length, response.read, lambda: (response.close(), connection.close()))
    except Exception:
        connection.close()
        raise


__all__ = ["OPENAI_COMPATIBLE_TTS", "OpenAICompatibleTTSAdapter", "TTSHTTPTransport", "_HTTPResponse", "is_valid_openai_compatible_endpoint"]
