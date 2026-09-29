from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest

from tori.checkpoints import CheckpointStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatResponse, ModelProvider
from tori.tts_adapters import DEFAULT_TTS_ENDPOINT
from tori.tts import SpeechCoordinator
from tori.tts_profile_application import TTSProfileApplicationService
from tori.tts_profile_runtime import TTSProfileRuntime
from tori.tts_profiles import SQLiteTTSProfileStore
from tori.tts_provider import (
    PCM_S16LE_MONO_24000,
    TTSAudioChunk,
    TTSAvailability,
    TTSConfigurationValidation,
    TTSProviderIdentity,
    TTSProviderStatus,
)
from tori.web import (
    LOOPBACK_HOST,
    WebApplication,
    WebApplicationError,
    create_web_server,
)


class _Provider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("test", "fake")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "test"


class _ClosableAudioStream:
    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):  # type: ignore[no-untyped-def]
        return self

    def __next__(self) -> TTSAudioChunk:
        if self.closed:
            raise StopIteration
        return TTSAudioChunk(b"\x01\x00", PCM_S16LE_MONO_24000)

    def close(self) -> None:
        self.closed = True


class _ProfileSpeechProvider:
    def __init__(self, provider_type: str) -> None:
        self.provider_type = provider_type
        self.streams: list[_ClosableAudioStream] = []
        self.requests: list[object] = []

    @property
    def identity(self) -> TTSProviderIdentity:
        return TTSProviderIdentity(self.provider_type, self.provider_type)

    def validate_configuration(self) -> TTSConfigurationValidation:
        return TTSConfigurationValidation(True)

    def status(self) -> TTSProviderStatus:
        return TTSProviderStatus(
            True,
            TTSAvailability.AVAILABLE if self.streams else TTSAvailability.UNKNOWN,
            None if self.streams else "not_checked",
        )

    def stream(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        stream = _ClosableAudioStream()
        self.streams.append(stream)
        return stream


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as listener:
        listener.bind((LOOPBACK_HOST, 0))
        return listener.getsockname()[1]


class TTSProfileWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        store = SQLiteTTSProfileStore(root / "tts-profiles.db")
        store.initialize(initial_selection_timestamp="2026-08-22T12:00:00Z")
        service = TTSProfileApplicationService(
            store,
            clock=lambda: datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc),
        )
        self.speech_providers: list[_ProfileSpeechProvider] = []

        def tts_factory(provider_type: str, **_configuration: object) -> _ProfileSpeechProvider:
            provider = _ProfileSpeechProvider(provider_type)
            self.speech_providers.append(provider)
            return provider

        self.tts_runtime = TTSProfileRuntime(service, provider_factory=tts_factory)
        self.speech = SpeechCoordinator(self.tts_runtime)
        self.application = WebApplication(
            _Provider(),
            port=_free_port(),
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake",
            model_name="fake",
            speech_coordinator=self.speech,
            tts_profile_application=service,
            tts_profile_runtime=self.tts_runtime,
        )
        self.server = create_web_server(self.application)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _request(
        self, method: str, path: str, document: object | None = None
    ) -> tuple[int, dict[str, object]]:
        body = None if document is None else json.dumps(document).encode()
        headers = {"Host": self.application.expected_host}
        if document is not None:
            headers.update(
                {
                    "Origin": self.application.expected_origin,
                    "X-Tori-CSRF": self.application.csrf_token,
                    "Content-Type": "application/json",
                }
            )
        connection = HTTPConnection(
            LOOPBACK_HOST, self.application.port, timeout=2
        )
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    @staticmethod
    def profile_document(**overrides: object) -> dict[str, object]:
        document: dict[str, object] = {
            "display_name": "Local speech",
            "endpoint": "http://192.168.1.50:8880/v1",
            "model": "future-model",
            "voice": "tori",
            "enabled": True,
            "connect_timeout_seconds": 3.0,
            "read_timeout_seconds": 30.0,
            "authentication_mode": "none",
            "provider_options": {},
        }
        document.update(overrides)
        return document

    def test_profile_crud_and_selection_use_application_api(self) -> None:
        status, created = self._request(
            "POST", "/api/tts-profiles/create", self.profile_document()
        )
        self.assertEqual(status, 201)
        profile = created["profile"]
        self.assertIsInstance(profile, dict)
        identifier = profile["identifier"]

        status, listed = self._request("GET", "/api/tts-profiles")
        self.assertEqual(status, 200)
        self.assertEqual(listed["profiles"], [profile])

        status, active = self._request("GET", "/api/tts-profiles/active")
        self.assertEqual(status, 200)
        self.assertIsNone(active["profile"])
        selection = active["selection"]
        status, selected = self._request(
            "POST",
            "/api/tts-profiles/select",
            {
                "identifier": identifier,
                "expected_revision": selection["revision"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(selected["selection"]["profile_identifier"], identifier)

        update = self.profile_document(display_name="Updated speech")
        update.update(
            {"identifier": identifier, "expected_revision": profile["revision"]}
        )
        status, revised = self._request(
            "POST", "/api/tts-profiles/update", update
        )
        self.assertEqual(status, 200)
        self.assertEqual(revised["profile"]["display_name"], "Updated speech")

        status, stale = self._request(
            "POST", "/api/tts-profiles/update", update
        )
        self.assertEqual(status, 409)
        self.assertEqual(stale["code"], "stale_revision")

        status, conflict = self._request(
            "POST",
            "/api/tts-profiles/delete",
            {
                "identifier": identifier,
                "expected_revision": revised["profile"]["revision"],
                "confirmed": True,
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(conflict["code"], "tts_profile_conflict")

    def test_missing_selection_never_fails_text_or_uses_a_fallback_provider(self) -> None:
        events = list(
            self.application.stream_submit(
                "Text remains primary.", auto_speech=True
            )
        )
        self.assertEqual(events[-1]["type"], "complete")
        self.assertFalse(any(event["type"] == "speech" for event in events))
        self.assertEqual(self.speech_providers, [])
        with self.assertRaises(WebApplicationError) as context:
            self.application.prepare_speech(1)
        self.assertEqual(context.exception.code, "tts_unavailable")

    def test_profile_selection_cancels_old_stream_and_future_speech_uses_new_provider(self) -> None:
        status, first_document = self._request(
            "POST", "/api/tts-profiles/create", self.profile_document()
        )
        self.assertEqual(status, 201)
        status, second_document = self._request(
            "POST",
            "/api/tts-profiles/create",
            self.profile_document(
                display_name="Secondary speech",
                endpoint="http://192.168.1.50:8881/v1",
                model="another-future-model",
                voice="tori_secondary",
            ),
        )
        self.assertEqual(status, 201)
        status, active = self._request("GET", "/api/tts-profiles/active")
        self.assertEqual(status, 200)
        status, selected = self._request(
            "POST",
            "/api/tts-profiles/select",
            {
                "identifier": first_document["profile"]["identifier"],
                "expected_revision": active["selection"]["revision"],
            },
        )
        self.assertEqual(status, 200)

        first_session = self.speech.start_completed("First selected provider.")
        first_audio = self.speech.claim_stream(first_session)
        self.assertEqual(next(first_audio), b"\x01\x00")
        first_stream = self.speech_providers[-1].streams[-1]
        self.assertEqual(self.speech_providers[-1].provider_type, "openai_compatible")

        status, switched = self._request(
            "POST",
            "/api/tts-profiles/select",
            {
                "identifier": second_document["profile"]["identifier"],
                "expected_revision": selected["selection"]["revision"],
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(first_stream.closed)

        second_session = self.speech.start_completed("New selected provider.")
        second_audio = self.speech.claim_stream(second_session)
        self.assertEqual(next(second_audio), b"\x01\x00")
        second_provider = self.speech_providers[-1]
        second_stream = second_provider.streams[-1]
        self.assertEqual(second_provider.provider_type, "openai_compatible")

        update = self.profile_document(
            display_name="Secondary speech updated",
            endpoint="http://192.168.1.50:8881/v1",
            model="another-future-model",
            voice="tori_updated",
        )
        update.update(
            {
                "identifier": second_document["profile"]["identifier"],
                "expected_revision": second_document["profile"]["revision"],
            }
        )
        status, _updated = self._request(
            "POST", "/api/tts-profiles/update", update
        )
        self.assertEqual(status, 200)
        self.assertTrue(second_stream.closed)

        revised_session = self.speech.start_completed("Updated selected voice.")
        revised_audio = self.speech.claim_stream(revised_session)
        self.assertEqual(next(revised_audio), b"\x01\x00")
        self.assertEqual(self.speech_providers[-1].requests[-1].voice, "tori_updated")
        revised_audio.close()

        status, profiles = self._request("GET", "/api/tts-profiles")
        self.assertEqual(status, 200)
        selected_profile = next(
            profile for profile in profiles["profiles"]
            if profile["identifier"] == second_document["profile"]["identifier"]
        )
        self.assertEqual(selected_profile["status"]["availability"], "available")

    def test_api_rejects_unknown_fields_without_a_provider_selector(self) -> None:
        invalid = self.profile_document()
        invalid["provider_type"] = "invented"
        status, response = self._request(
            "POST", "/api/tts-profiles/create", invalid
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["code"], "invalid_request")

        extra = self.profile_document()
        extra["credential"] = "must-not-be-accepted"
        status, response = self._request(
            "POST", "/api/tts-profiles/create", extra
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["code"], "invalid_request")

    def test_uninitialized_store_fails_closed_without_creating_runtime_state(self) -> None:
        root = Path(self.temporary.name) / "uninitialized"
        path = root / "tts-profiles.db"
        application = WebApplication(
            _Provider(),
            port=_free_port(),
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake",
            model_name="fake",
            tts_profile_application=TTSProfileApplicationService(
                SQLiteTTSProfileStore(path)
            ),
        )
        with self.assertRaises(WebApplicationError) as context:
            application.tts_profiles_state()
        self.assertEqual(context.exception.status, 503)
        self.assertEqual(context.exception.code, "tts_profiles_unavailable")
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
