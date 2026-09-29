"""Runtime projection from canonical TTS profiles to provider-neutral speech."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import threading

from .tts import SpeechProviderSelection, SpeechProviderSource
from .tts_adapters import create_tts_provider
from .tts_profile_application import TTSProfileApplicationService
from .tts_profiles import TTSProfile, TTSProfileError
from .tts_provider import (
    TextToSpeechProvider,
    TTSAvailability,
    TTSProviderError,
    TTSProviderStatus,
    TTSUnavailableError,
)


ProviderFactory = Callable[..., TextToSpeechProvider]
UTCClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class _ObservedStatus:
    status: TTSProviderStatus
    observed_at: str | None


class TTSProfileRuntime(SpeechProviderSource):
    """Resolve and observe only the explicitly selected canonical profile."""

    def __init__(
        self,
        application: TTSProfileApplicationService,
        *,
        provider_factory: ProviderFactory = create_tts_provider,
        clock: UTCClock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._application = application
        self._provider_factory = provider_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._providers: dict[tuple[object, ...], TextToSpeechProvider] = {}
        self._observations: dict[tuple[object, ...], _ObservedStatus] = {}

    def resolve(self) -> SpeechProviderSelection:
        """Snapshot one selected profile; never select or contact a fallback."""
        try:
            profile = self._application.require_active_profile()
            key = _runtime_key(profile)
            with self._lock:
                provider = self._providers.get(key)
                if provider is None:
                    provider = self._provider_factory(
                        profile.provider_type,
                        endpoint=profile.endpoint,
                        connect_timeout_seconds=profile.connect_timeout_seconds,
                        read_timeout_seconds=profile.read_timeout_seconds,
                    )
                    self._providers[key] = provider
                    self._observations[key] = _ObservedStatus(
                        provider.status(), None
                    )
            return SpeechProviderSelection(
                provider=provider,
                voice=profile.voice,
                model=profile.model,
                profile_identifier=profile.identifier,
                profile_revision=profile.revision,
            )
        except (TTSProfileError, TTSProviderError, ValueError) as exc:
            raise TTSUnavailableError(
                "The active TTS profile is unavailable; no fallback was used."
            ) from exc

    def invalidate(self, identifier: str) -> None:
        """Discard cached construction after a canonical edit or deletion."""
        with self._lock:
            keys = [key for key in self._providers if key[0] == identifier]
            for key in keys:
                self._providers.pop(key, None)
                self._observations.pop(key, None)

    def status_document(self, profile: TTSProfile) -> dict[str, object]:
        """Return bounded process-local availability without probing a provider."""
        key = _runtime_key(profile)
        with self._lock:
            provider = self._providers.get(key)
            if provider is None:
                status = TTSProviderStatus(
                    configured=True,
                    availability=TTSAvailability.UNKNOWN,
                    reason_code="not_checked",
                )
                observation = _ObservedStatus(status, None)
            else:
                status = provider.status()
                previous = self._observations.get(key)
                if previous is None or previous.status != status:
                    observation = _ObservedStatus(status, self._timestamp())
                    self._observations[key] = observation
                else:
                    observation = previous
        return {
            "configured": observation.status.configured,
            "availability": observation.status.availability.value,
            "reason_code": observation.status.reason_code,
            "observed_at": observation.observed_at,
        }

    def _timestamp(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["TTSProfileRuntime"]


def _runtime_key(profile: TTSProfile) -> tuple[object, ...]:
    return (
        profile.identifier,
        profile.provider_type,
        profile.endpoint,
        profile.model,
        profile.voice,
        profile.connect_timeout_seconds,
        profile.read_timeout_seconds,
        profile.authentication_mode,
        profile.provider_options,
    )
