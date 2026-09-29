"""Provider-neutral transient text-to-speech presentation support."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
import re
import secrets
import threading
import time
from typing import Protocol

from .tts_provider import (
    PCM_S16LE_MONO_24000,
    MAX_TTS_RESPONSE_BYTES,
    TTSAudioChunk,
    TTSError,
    TextToSpeechProvider,
    TTSSynthesisRequest,
    TTSUnavailableError,
)


DEFAULT_TTS_VOICE = "tori"
PCM_SAMPLE_RATE = PCM_S16LE_MONO_24000.sample_rate
PCM_CHANNELS = PCM_S16LE_MONO_24000.channels
PCM_SAMPLE_WIDTH_BYTES = PCM_S16LE_MONO_24000.sample_width_bytes
MAX_TTS_INPUT_CHARACTERS = 2_000
MAX_QUEUED_SPEECH_CHARACTERS = 12_000
MAX_SPEECH_SESSIONS = 8
SPEECH_SESSION_LIFETIME_SECONDS = 600.0


class SpeechSessionStopped(TTSError):
    """A transient speech session was deliberately superseded or stopped."""


@dataclass(frozen=True, slots=True)
class SpeechProviderSelection:
    """One provider-neutral profile snapshot for one speech session."""

    provider: TextToSpeechProvider
    voice: str
    model: str | None = None
    profile_identifier: str | None = None
    profile_revision: int | None = None

    def __post_init__(self) -> None:
        validate_voice(self.voice)


class SpeechProviderSource(Protocol):
    """Resolve the one authoritative provider selection for future speech."""

    def resolve(self) -> SpeechProviderSelection:
        """Return a validated immutable selection without contacting it."""


class _FixedSpeechProviderSource:
    """Compatibility source for isolated callers without canonical profiles."""

    def __init__(self, provider: TextToSpeechProvider, voice: str) -> None:
        self._selection = SpeechProviderSelection(provider, validate_voice(voice))

    def resolve(self) -> SpeechProviderSelection:
        return self._selection


_COMMON_ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e"}
)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^\s)]+\)")
_CITATION = re.compile(r"\[\d+\]")
_MARKDOWN_PREFIX = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+|>\s*)")
_MARKDOWN_RULE = re.compile(r"(?m)^\s*(?:[-*_]\s*){3,}$")
_SOURCES_HEADING = re.compile(r"(?im)^\s*(?:#+\s*)?sources\s*:?[ \t]*$")
_PRIVATE_CONTROL = re.compile(
    r"(?:<\/?think>|\[\[TORI:[A-Z0-9_:-]+\]\]|"
    r'\{\s*"(?:tool|name)"\s*:\s*"[^"\\]+")',
    re.IGNORECASE,
)


class SpeechSegmenter:
    """Incrementally split approved visible prose at natural speech boundaries."""

    def __init__(
        self,
        *,
        minimum_characters: int = 12,
        preferred_characters: int = 360,
        maximum_characters: int = 560,
    ) -> None:
        if not 1 <= minimum_characters < preferred_characters < maximum_characters:
            raise ValueError("Speech segmentation limits are invalid.")
        self.minimum_characters = minimum_characters
        self.preferred_characters = preferred_characters
        self.maximum_characters = maximum_characters
        self._buffer = ""
        self._sources_reached = False

    def feed(self, visible_text: str) -> tuple[str, ...]:
        if not isinstance(visible_text, str):
            raise ValueError("Visible speech input must be text.")
        if self._sources_reached or not visible_text:
            return ()
        self._buffer += visible_text
        source = _SOURCES_HEADING.search(self._buffer)
        if source is not None:
            self._buffer = self._buffer[:source.start()]
            self._sources_reached = True
        return self._drain(final=False)

    def finish(self) -> tuple[str, ...]:
        return self._drain(final=True)

    def _drain(self, *, final: bool) -> tuple[str, ...]:
        chunks: list[str] = []
        while self._buffer:
            boundary = _speech_boundary(
                self._buffer,
                minimum=self.minimum_characters,
                preferred=self.preferred_characters,
                maximum=self.maximum_characters,
                final=final,
            )
            if boundary is None:
                break
            candidate = self._buffer[:boundary]
            self._buffer = self._buffer[boundary:]
            speakable = normalize_speakable_text(candidate)
            if speakable:
                chunks.append(speakable)
        if final:
            candidate, self._buffer = self._buffer, ""
            speakable = normalize_speakable_text(candidate)
            if speakable:
                chunks.append(speakable)
        return tuple(chunks)


def _speech_boundary(
    text: str,
    *,
    minimum: int,
    preferred: int,
    maximum: int,
    final: bool,
) -> int | None:
    for index, character in enumerate(text):
        end = index + 1
        if end < minimum:
            continue
        if character in "!?" and _boundary_follows(text, end):
            return end
        if character == "." and _boundary_follows(text, end) and not _period_is_internal(text, index):
            return end
        if character == "\n" and (end >= preferred or text[index:index + 2] == "\n\n"):
            return end
    # Leave enough buffered prose for a useful following chunk instead of
    # stranding a tiny tail when one long provider fragment is drained.
    if len(text) >= maximum + minimum:
        window = text[:maximum]
        for separators in (";:\n", ",", " \t"):
            candidate = max(window.rfind(separator) for separator in separators)
            if candidate + 1 >= minimum:
                return candidate + 1
    if final and text:
        return len(text)
    return None


def _boundary_follows(text: str, end: int) -> bool:
    return end == len(text) or text[end].isspace() or text[end] in {'"', "'", ")", "]"}


def _period_is_internal(text: str, index: int) -> bool:
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if before.isdigit() and after.isdigit():
        return True
    prefix = text[:index].rstrip()
    word = re.search(r"([A-Za-z](?:[A-Za-z.]*)?)$", prefix)
    if word is None:
        return False
    value = word.group(1).casefold()
    return value in _COMMON_ABBREVIATIONS or (len(value) == 1 and value.isalpha())


def normalize_speakable_text(text: str) -> str:
    """Return faithful prose without interface-only Markdown/source machinery."""

    if _PRIVATE_CONTROL.search(text):
        return ""
    source = _SOURCES_HEADING.search(text)
    if source is not None:
        text = text[:source.start()]
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _CITATION.sub("", text)
    text = _MARKDOWN_RULE.sub("", text)
    text = _MARKDOWN_PREFIX.sub("", text)
    text = text.replace("```", "").replace("`", "")
    text = re.sub(r"(?<!\w)[*_~]{1,3}|[*_~]{1,3}(?!\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text.casefold() == "web findings":
        return ""
    return text


def validate_speech_input(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Speech input must be non-empty text.")
    normalized = value.strip()
    if len(normalized) > MAX_TTS_INPUT_CHARACTERS:
        raise ValueError("Speech input exceeds the per-segment limit.")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in normalized):
        raise ValueError("Speech input contains unsupported control characters.")
    return normalized


def validate_voice(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError("TTS voice must be a simple local voice identifier.")
    return value


@dataclass(slots=True)
class _SpeechSession:
    identifier: str
    segmenter: SpeechSegmenter
    created_at: float
    selection: SpeechProviderSelection
    condition: threading.Condition = field(default_factory=threading.Condition)
    queue: deque[str] = field(default_factory=deque)
    queued_characters: int = 0
    finished: bool = False
    cancelled: bool = False
    consumer_claimed: bool = False
    segment_index: int = 0
    active_stream: Iterator[TTSAudioChunk] | None = None


class SpeechCoordinator:
    """Own bounded transient sessions and one ordered provider worker per session."""

    def __init__(
        self,
        provider: TextToSpeechProvider | SpeechProviderSource,
        *,
        voice: str = DEFAULT_TTS_VOICE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider if isinstance(provider, TextToSpeechProvider) else None
        self._provider_source = (
            provider
            if not isinstance(provider, TextToSpeechProvider)
            else _FixedSpeechProviderSource(provider, voice)
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, _SpeechSession] = {}
        self._active_identifier: str | None = None

    @property
    def voice(self) -> str:
        """Return the voice currently selected for the next speech session."""
        return self._provider_source.resolve().voice

    def configured(self) -> bool:
        """Report whether one valid explicit provider selection can be resolved."""
        try:
            self._provider_source.resolve()
        except (TTSError, ValueError):
            return False
        return True

    def start(self) -> str:
        selection = self._provider_source.resolve()
        streams_to_close: list[Iterator[TTSAudioChunk]] = []
        with self._lock:
            streams_to_close.extend(self._prune_locked())
            if self._active_identifier is not None:
                stream = self._cancel_locked(self._active_identifier)
                if stream is not None:
                    streams_to_close.append(stream)
            identifier = secrets.token_urlsafe(24)
            self._sessions[identifier] = _SpeechSession(
                identifier,
                SpeechSegmenter(),
                self._clock(),
                selection,
            )
            self._active_identifier = identifier
        for stream in streams_to_close:
            _close_provider_stream(stream)
        return identifier

    def feed(self, identifier: str, visible_text: str) -> None:
        session = self._get(identifier)
        self._enqueue(session, session.segmenter.feed(visible_text))

    def finish(self, identifier: str) -> None:
        session = self._get(identifier)
        self._enqueue(session, session.segmenter.finish())
        with session.condition:
            session.finished = True
            session.condition.notify_all()

    def start_completed(self, visible_text: str) -> str:
        identifier = self.start()
        self.feed(identifier, visible_text)
        self.finish(identifier)
        return identifier

    def stop(self, identifier: str | None = None) -> bool:
        with self._lock:
            target = identifier or self._active_identifier
            if target is None or target not in self._sessions:
                return False
            stream = self._cancel_locked(target)
        if stream is not None:
            _close_provider_stream(stream)
        return True

    def claim_stream(self, identifier: object) -> Iterator[bytes]:
        if not isinstance(identifier, str):
            raise TTSUnavailableError("The speech session is invalid or expired.")
        session = self._get(identifier)
        with session.condition:
            if session.consumer_claimed:
                raise TTSUnavailableError("The speech session has already been used.")
            session.consumer_claimed = True
        return self._stream(session)

    def _stream(self, session: _SpeechSession) -> Iterator[bytes]:
        total_audio_bytes = 0
        try:
            while True:
                with session.condition:
                    while not session.queue and not session.finished and not session.cancelled:
                        session.condition.wait(timeout=1.0)
                    if session.cancelled:
                        raise SpeechSessionStopped("Speech was stopped.")
                    if not session.queue:
                        if session.finished:
                            return
                        continue
                    text = session.queue.popleft()
                    session.queued_characters -= len(text)
                session.segment_index += 1
                stream = session.selection.provider.stream(
                    TTSSynthesisRequest(
                        request_id=f"{session.identifier}.{session.segment_index}",
                        text=validate_speech_input(text),
                        voice=session.selection.voice,
                        model=session.selection.model,
                    )
                )
                with session.condition:
                    if session.cancelled:
                        _close_provider_stream(stream)
                        raise SpeechSessionStopped("Speech was stopped.")
                    session.active_stream = stream
                try:
                    for chunk in stream:
                        with session.condition:
                            if session.cancelled:
                                raise SpeechSessionStopped("Speech was stopped.")
                        if (
                            chunk.audio_format != PCM_S16LE_MONO_24000
                            or not isinstance(chunk.data, bytes)
                            or not chunk.data
                            or len(chunk.data) % PCM_S16LE_MONO_24000.frame_width_bytes
                        ):
                            raise TTSUnavailableError(
                                "The speech provider returned malformed audio."
                            )
                        total_audio_bytes += len(chunk.data)
                        if total_audio_bytes > MAX_TTS_RESPONSE_BYTES:
                            raise TTSUnavailableError(
                                "The speech response exceeded its safety limit."
                            )
                        yield chunk.data
                finally:
                    with session.condition:
                        if session.active_stream is stream:
                            session.active_stream = None
                    _close_provider_stream(stream)
        finally:
            with self._lock:
                self._sessions.pop(session.identifier, None)
                if self._active_identifier == session.identifier:
                    self._active_identifier = None

    def _enqueue(self, session: _SpeechSession, chunks: tuple[str, ...]) -> None:
        with session.condition:
            if session.cancelled:
                raise SpeechSessionStopped("Speech was stopped.")
            for chunk in chunks:
                validate_speech_input(chunk)
                if session.queued_characters + len(chunk) > MAX_QUEUED_SPEECH_CHARACTERS:
                    session.cancelled = True
                    session.queue.clear()
                    session.queued_characters = 0
                    session.condition.notify_all()
                    raise TTSUnavailableError("The speech queue exceeded its safety limit.")
                session.queue.append(chunk)
                session.queued_characters += len(chunk)
            session.condition.notify_all()

    def _get(self, identifier: str) -> _SpeechSession:
        with self._lock:
            streams_to_close = self._prune_locked()
            session = self._sessions.get(identifier)
        for stream in streams_to_close:
            _close_provider_stream(stream)
        if session is None:
            raise TTSUnavailableError("The speech session is invalid or expired.")
        return session

    def _cancel_locked(self, identifier: str) -> Iterator[TTSAudioChunk] | None:
        session = self._sessions.get(identifier)
        if session is None:
            return None
        with session.condition:
            session.cancelled = True
            session.queue.clear()
            session.queued_characters = 0
            stream = session.active_stream
            session.condition.notify_all()
        if self._active_identifier == identifier:
            self._active_identifier = None
        return stream

    def _prune_locked(self) -> tuple[Iterator[TTSAudioChunk], ...]:
        streams: list[Iterator[TTSAudioChunk]] = []
        cutoff = self._clock() - SPEECH_SESSION_LIFETIME_SECONDS
        expired = [
            identifier
            for identifier, session in self._sessions.items()
            if session.created_at < cutoff
        ]
        for identifier in expired:
            stream = self._cancel_locked(identifier)
            if stream is not None:
                streams.append(stream)
            self._sessions.pop(identifier, None)
        while len(self._sessions) >= MAX_SPEECH_SESSIONS:
            oldest = min(self._sessions.values(), key=lambda item: item.created_at)
            stream = self._cancel_locked(oldest.identifier)
            if stream is not None:
                streams.append(stream)
            self._sessions.pop(oldest.identifier, None)
        return tuple(streams)


def _close_provider_stream(stream: Iterator[TTSAudioChunk]) -> None:
    close = getattr(stream, "close", None)
    if close is not None:
        try:
            close()
        except (OSError, RuntimeError, ValueError):
            # Cancellation and cleanup are best-effort provider operations. The
            # session remains cancelled and no later audio is presented.
            pass
