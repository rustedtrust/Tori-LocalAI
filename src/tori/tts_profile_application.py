"""Tori-owned application boundary for canonical TTS profile management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
import re
import secrets
import unicodedata

from .tts_adapters import (
    OPENAI_COMPATIBLE_TTS,
    SUPPORTED_TTS_PROVIDERS,
    validate_tts_profile_configuration,
)
from .tts_provider import TTSProviderError
from .tts_profiles import (
    SQLiteTTSProfileStore,
    TTSProfile,
    TTSProfileSelection,
    TTSProfileValidationError,
)


ProfileValidator = Callable[..., None]
Clock = Callable[[], datetime]
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


class TTSProfileApplicationService:
    """Validate user commands before invoking the canonical repository."""

    def __init__(
        self,
        store: SQLiteTTSProfileStore,
        *,
        validator: ProfileValidator = validate_tts_profile_configuration,
        clock: Clock = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._store = store
        self._validator = validator
        self._clock = clock

    @property
    def initialized(self) -> bool:
        return self._store.exists

    def list_profiles(self) -> tuple[TTSProfile, ...]:
        return self._store.list_profiles()

    def get_profile(self, identifier: object) -> TTSProfile:
        return self._store.get_profile(_profile_identifier(identifier))

    def get_active_profile(
        self,
    ) -> tuple[TTSProfileSelection, TTSProfile | None]:
        selection = self._store.get_selection()
        profile = (
            self._store.get_profile(selection.profile_identifier)
            if selection.profile_identifier is not None
            else None
        )
        return selection, profile

    def initialize_from_configured_profile(
        self,
        *,
        display_name: object,
        provider_type: object,
        endpoint: object,
        model: object,
        voice: object,
        connect_timeout_seconds: object,
        read_timeout_seconds: object,
    ) -> bool:
        """Atomically seed an absent store from validated legacy configuration.

        Existing canonical state is never projected, merged, or overwritten.
        """
        if self.initialized:
            return False
        profile = self._new_profile(
            identifier="configured-speech",
            display_name=display_name,
            provider_type=provider_type,
            endpoint=endpoint,
            model=model,
            voice=voice,
            enabled=True,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            authentication_mode="none",
            provider_options={},
            preserve_legacy_provider=True,
        )
        self._validate(profile)
        self._store.initialize(
            initial_selection_timestamp=profile.created_at,
            initial_profile=profile,
        )
        return True

    def require_active_profile(self) -> TTSProfile:
        """Return the validated explicit selection or fail without fallback."""
        _selection, profile = self.get_active_profile()
        if profile is None:
            raise TTSProfileValidationError(
                "No active TTS profile has been selected."
            )
        if not profile.enabled:
            raise TTSProfileValidationError(
                "The active TTS profile is disabled."
            )
        self._validate(profile)
        return profile

    def create_profile(
        self,
        *,
        display_name: object,
        provider_type: object | None = None,
        endpoint: object,
        model: object,
        voice: object,
        enabled: object,
        connect_timeout_seconds: object,
        read_timeout_seconds: object,
        authentication_mode: object,
        provider_options: object,
        identifier: object | None = None,
    ) -> TTSProfile:
        profile = self._new_profile(
            identifier=identifier,
            display_name=display_name,
            provider_type=provider_type,
            endpoint=endpoint,
            model=model,
            voice=voice,
            enabled=enabled,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            authentication_mode=authentication_mode,
            provider_options=provider_options,
            preserve_legacy_provider=False,
        )
        self._validate(profile)
        return self._store.create_profile(profile)

    def _new_profile(
        self,
        *,
        identifier: object | None,
        display_name: object,
        provider_type: object,
        endpoint: object,
        model: object,
        voice: object,
        enabled: object,
        connect_timeout_seconds: object,
        read_timeout_seconds: object,
        authentication_mode: object,
        provider_options: object,
        preserve_legacy_provider: bool = False,
    ) -> TTSProfile:
        now = self._timestamp()
        return TTSProfile(
            identifier=(
                f"tts-{secrets.token_hex(6)}"
                if identifier is None
                else _profile_identifier(identifier)
            ),
            display_name=_display_name(display_name),
            provider_type=_provider_type(
                provider_type, preserve_legacy_provider=preserve_legacy_provider
            ),
            endpoint=_required_text(endpoint, "endpoint", maximum=512),
            model=_optional_identifier(model, "model", maximum=256),
            voice=_required_identifier(voice, "voice", maximum=64),
            enabled=_boolean(enabled, "enabled"),
            connect_timeout_seconds=_timeout(
                connect_timeout_seconds, "connect_timeout_seconds", maximum=10
            ),
            read_timeout_seconds=_timeout(
                read_timeout_seconds, "read_timeout_seconds", maximum=120
            ),
            authentication_mode=_authentication_mode(authentication_mode),
            provider_options=_provider_options(provider_options),
            revision=1,
            created_at=now,
            updated_at=now,
        )

    def update_profile(
        self,
        identifier: object,
        *,
        expected_revision: object,
        display_name: object,
        endpoint: object,
        model: object,
        voice: object,
        enabled: object,
        connect_timeout_seconds: object,
        read_timeout_seconds: object,
        authentication_mode: object,
        provider_options: object,
    ) -> TTSProfile:
        current = self._store.get_profile(_profile_identifier(identifier))
        revision = _revision(expected_revision)
        updated = replace(
            current,
            display_name=_display_name(display_name),
            endpoint=_required_text(endpoint, "endpoint", maximum=512),
            model=_optional_identifier(model, "model", maximum=256),
            voice=_required_identifier(voice, "voice", maximum=64),
            enabled=_boolean(enabled, "enabled"),
            connect_timeout_seconds=_timeout(
                connect_timeout_seconds, "connect_timeout_seconds", maximum=10
            ),
            read_timeout_seconds=_timeout(
                read_timeout_seconds, "read_timeout_seconds", maximum=120
            ),
            authentication_mode=_authentication_mode(authentication_mode),
            provider_options=_provider_options(provider_options),
            revision=revision + 1,
            updated_at=self._timestamp(),
        )
        self._validate(updated)
        return self._store.update_profile(updated, expected_revision=revision)

    def delete_profile(
        self, identifier: object, *, expected_revision: object
    ) -> None:
        self._store.delete_profile(
            _profile_identifier(identifier),
            expected_revision=_revision(expected_revision),
        )

    def select_active_profile(
        self, identifier: object, *, expected_revision: object
    ) -> TTSProfileSelection:
        profile = self._store.get_profile(_profile_identifier(identifier))
        if not profile.enabled:
            raise TTSProfileValidationError(
                "A disabled TTS profile cannot be selected."
            )
        # Revalidate exactly the requested profile. Never search for or select
        # another profile when this one cannot be used.
        self._validate(profile)
        return self._store.select_profile(
            profile.identifier,
            expected_revision=_revision(expected_revision),
            updated_at=self._timestamp(),
        )

    def _validate(self, profile: TTSProfile) -> None:
        if profile.provider_type not in SUPPORTED_TTS_PROVIDERS:
            raise TTSProfileValidationError(
                "The selected TTS provider is not supported."
            )
        try:
            self._validator(
                profile.provider_type,
                endpoint=profile.endpoint,
                model=profile.model,
                voice=profile.voice,
                connect_timeout_seconds=profile.connect_timeout_seconds,
                read_timeout_seconds=profile.read_timeout_seconds,
            )
        except (TTSProviderError, ValueError) as exc:
            raise TTSProfileValidationError(
                "The TTS profile configuration is invalid."
            ) from exc

    def _timestamp(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TTSProfileValidationError(
                "Authoritative profile time is unavailable."
            )
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def tts_profile_document(profile: TTSProfile) -> dict[str, object]:
    """Return the bounded non-secret client representation."""
    return {
        "identifier": profile.identifier,
        "display_name": profile.display_name,
        "provider_type": profile.provider_type,
        "endpoint": profile.endpoint,
        "model": profile.model,
        "voice": profile.voice,
        "enabled": profile.enabled,
        "connect_timeout_seconds": profile.connect_timeout_seconds,
        "read_timeout_seconds": profile.read_timeout_seconds,
        "authentication_mode": profile.authentication_mode,
        "provider_options": dict(profile.provider_options),
        "revision": profile.revision,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def tts_selection_document(selection: TTSProfileSelection) -> dict[str, object]:
    return {
        "profile_identifier": selection.profile_identifier,
        "revision": selection.revision,
        "updated_at": selection.updated_at,
    }


def _profile_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise TTSProfileValidationError("The TTS profile identifier is invalid.")
    return value


def _display_name(value: object) -> str:
    text = _required_text(value, "display_name", maximum=80)
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in text
    ):
        raise TTSProfileValidationError("display_name is invalid.")
    return text


def _provider_type(value: object, *, preserve_legacy_provider: bool) -> str:
    """Choose the normal protocol without letting user text select adapters.

    Only the one-time seed may retain a legacy adapter identity that was already
    configured locally.  Ordinary profile creation is always protocol-oriented.
    """
    if not preserve_legacy_provider:
        return OPENAI_COMPATIBLE_TTS
    text = _required_identifier(value, "provider_type", maximum=64).lower()
    if text not in SUPPORTED_TTS_PROVIDERS:
        raise TTSProfileValidationError("The configured legacy TTS adapter is not supported.")
    return text


def _required_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TTSProfileValidationError(f"{field} must be non-empty text.")
    text = value.strip()
    if len(text) > maximum or any(ord(character) < 32 for character in text):
        raise TTSProfileValidationError(f"{field} is outside the supported boundary.")
    return text


def _required_identifier(value: object, field: str, *, maximum: int) -> str:
    text = _required_text(value, field, maximum=maximum)
    if any(ord(character) < 33 or ord(character) == 127 for character in text):
        raise TTSProfileValidationError(f"{field} is invalid.")
    return text


def _optional_identifier(value: object, field: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _required_identifier(value, field, maximum=maximum)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise TTSProfileValidationError(f"{field} must be a boolean.")
    return value


def _timeout(value: object, field: str, *, maximum: float) -> float:
    if isinstance(value, bool):
        raise TTSProfileValidationError(f"{field} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TTSProfileValidationError(f"{field} must be a number.") from exc
    if not 0 < result <= maximum:
        raise TTSProfileValidationError(f"{field} is outside the supported boundary.")
    return result


def _authentication_mode(value: object) -> str:
    if value != "none":
        raise TTSProfileValidationError(
            "TTS profile credentials are not available in this phase."
        )
    return "none"


def _provider_options(value: object) -> tuple[tuple[str, object], ...]:
    if not isinstance(value, Mapping) or value:
        raise TTSProfileValidationError(
            "Provider-specific TTS options are not available in this phase."
        )
    return ()


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TTSProfileValidationError(
            "expected_revision must be a positive integer."
        )
    return value


__all__ = [
    "TTSProfileApplicationService",
    "tts_profile_document",
    "tts_selection_document",
]
