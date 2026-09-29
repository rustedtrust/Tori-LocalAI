from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.tts import SpeechCoordinator
from tori.tts_profile_application import TTSProfileApplicationService
from tori.tts_adapters import OPENAI_COMPATIBLE_TTS
from tori.tts_profile_runtime import TTSProfileRuntime
from tori.tts_profiles import SQLiteTTSProfileStore
from tori.tts_provider import (
    PCM_S16LE_MONO_24000,
    TTSAudioChunk,
    TTSAvailability,
    TTSConfigurationValidation,
    TTSProviderIdentity,
    TTSProviderStatus,
    TTSSynthesisRequest,
    TTSUnavailableError,
)


class _AudioStream:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._sent = False
        self.closed = False

    def __iter__(self):  # type: ignore[no-untyped-def]
        return self

    def __next__(self) -> TTSAudioChunk:
        if self.closed or self._sent:
            raise StopIteration
        self._sent = True
        return TTSAudioChunk(self._data, PCM_S16LE_MONO_24000)

    def close(self) -> None:
        self.closed = True


class _RecordingTTSProvider:
    def __init__(self, provider_type: str, *, fail: bool = False) -> None:
        self.provider_type = provider_type
        self.fail = fail
        self.requests: list[TTSSynthesisRequest] = []
        self.streams: list[_AudioStream] = []
        self._status = TTSProviderStatus(
            True, TTSAvailability.UNKNOWN, "not_checked"
        )

    @property
    def identity(self) -> TTSProviderIdentity:
        return TTSProviderIdentity(self.provider_type, self.provider_type.title())

    def validate_configuration(self) -> TTSConfigurationValidation:
        return TTSConfigurationValidation(True)

    def status(self) -> TTSProviderStatus:
        return self._status

    def stream(self, request: TTSSynthesisRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if self.fail:
            self._status = TTSProviderStatus(
                True, TTSAvailability.UNAVAILABLE, "provider_unreachable"
            )
            raise TTSUnavailableError("The selected provider is unavailable.")
        self._status = TTSProviderStatus(True, TTSAvailability.AVAILABLE)
        stream = _AudioStream(b"\x01\x00")
        self.streams.append(stream)
        return stream


class TTSProfileRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        store = SQLiteTTSProfileStore(Path(self.temporary.name) / "profiles.db")
        store.initialize(initial_selection_timestamp="2026-08-22T12:00:00Z")
        self.application = TTSProfileApplicationService(
            store,
            clock=lambda: datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc),
        )
        self.created_providers: list[_RecordingTTSProvider] = []

        def factory(provider_type: str, **_configuration: object) -> _RecordingTTSProvider:
            provider = _RecordingTTSProvider(provider_type)
            self.created_providers.append(provider)
            return provider

        self.runtime = TTSProfileRuntime(
            self.application,
            provider_factory=factory,
            clock=lambda: datetime(2026, 8, 22, 12, 45, tzinfo=timezone.utc),
        )

    @staticmethod
    def values(provider_type: str = OPENAI_COMPATIBLE_TTS, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "display_name": provider_type.title(),
            "endpoint": "http://192.168.1.50:8880/v1",
            "model": "future-model",
            "voice": "tori",
            "enabled": True,
            "connect_timeout_seconds": 3,
            "read_timeout_seconds": 30,
            "authentication_mode": "none",
            "provider_options": {},
        }
        values.update(overrides)
        return values

    def _create_and_select(self, provider_type: str = OPENAI_COMPATIBLE_TTS):  # type: ignore[no-untyped-def]
        profile = self.application.create_profile(**self.values(provider_type))
        selection = self.application.get_active_profile()[0]
        self.application.select_active_profile(
            profile.identifier, expected_revision=selection.revision
        )
        return profile

    def test_selected_profile_supplies_provider_model_and_voice_to_future_speech(self) -> None:
        qwen = self._create_and_select()
        coordinator = SpeechCoordinator(self.runtime)
        first = coordinator.start_completed("First provider.")
        self.assertEqual(list(coordinator.claim_stream(first)), [b"\x01\x00"])
        self.assertEqual(self.created_providers[-1].provider_type, OPENAI_COMPATIBLE_TTS)
        self.assertEqual(self.created_providers[-1].requests[0].model, "future-model")
        self.assertEqual(self.created_providers[-1].requests[0].voice, "tori")

        kokoro = self.application.create_profile(**self.values())
        selection = self.application.get_active_profile()[0]
        self.application.select_active_profile(
            kokoro.identifier, expected_revision=selection.revision
        )
        second = coordinator.start_completed("Second provider.")
        self.assertEqual(list(coordinator.claim_stream(second)), [b"\x01\x00"])
        self.assertEqual(self.created_providers[-1].provider_type, OPENAI_COMPATIBLE_TTS)
        self.assertEqual(self.created_providers[-1].requests[0].model, "future-model")
        self.assertEqual(self.created_providers[-1].requests[0].voice, "tori")
        self.assertNotEqual(qwen.identifier, kokoro.identifier)

    def test_failure_updates_only_selected_provider_status_without_fallback(self) -> None:
        profile = self._create_and_select()

        def failing_factory(provider_type: str, **_configuration: object) -> _RecordingTTSProvider:
            provider = _RecordingTTSProvider(provider_type, fail=True)
            self.created_providers.append(provider)
            return provider

        runtime = TTSProfileRuntime(
            self.application,
            provider_factory=failing_factory,
            clock=lambda: datetime(2026, 8, 22, 12, 45, tzinfo=timezone.utc),
        )
        coordinator = SpeechCoordinator(runtime)
        identifier = coordinator.start_completed("No fallback.")
        with self.assertRaises(TTSUnavailableError):
            list(coordinator.claim_stream(identifier))

        status = runtime.status_document(profile)
        self.assertEqual(len(self.created_providers), 1)
        self.assertEqual(status["availability"], "unavailable")
        self.assertEqual(status["reason_code"], "provider_unreachable")
        self.assertEqual(status["observed_at"], "2026-08-22T12:45:00Z")

    def test_no_selection_is_unavailable_without_constructing_any_provider(self) -> None:
        coordinator = SpeechCoordinator(self.runtime)
        self.assertFalse(coordinator.configured())
        with self.assertRaises(TTSUnavailableError):
            coordinator.start_completed("Must not fall back.")
        self.assertEqual(self.created_providers, [])


if __name__ == "__main__":
    unittest.main()
