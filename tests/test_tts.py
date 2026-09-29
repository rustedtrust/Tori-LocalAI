from __future__ import annotations

from collections import deque
from io import BytesIO
import inspect
import json
import threading
import unittest
import wave
from unittest.mock import patch

import tori.tts as tts_module
import tori.tts_provider as tts_provider_module
from tori.tts import (
    SpeechCoordinator,
    SpeechSegmenter,
    SpeechSessionStopped,
    TTSUnavailableError,
    normalize_speakable_text,
)
from tori.tts_adapters.current_qwen import (
    DEFAULT_TTS_ENDPOINT,
    CurrentQwenTTSAdapter,
    _HTTPPCMResponse,
)
from tori.tts_adapters import create_tts_provider
from tori.tts_adapters.openai_compatible import (
    OPENAI_COMPATIBLE_TTS,
    OpenAICompatibleTTSAdapter,
    _HTTPResponse as _OpenAIHTTPResponse,
)
from tori.tts_adapters.kokoro import (
    KOKORO_MODEL,
    KOKORO_PROVIDER,
    KokoroTTSAdapter,
    _HTTPPCMResponse as _KokoroHTTPPCMResponse,
)
from tori.tts_provider import (
    PCM_S16LE_MONO_24000,
    TTSAudioChunk,
    TTSAvailability,
    TTSConfigurationError,
    TTSConfigurationValidation,
    TTSProviderIdentity,
    TTSProviderStatus,
    TTSSynthesisRequest,
    TextToSpeechProvider,
)


class RecordingTTSProvider:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.requests: list[tuple[str, str]] = []
        self.started = threading.Event()
        self.failure = failure

    @property
    def identity(self) -> TTSProviderIdentity:
        return TTSProviderIdentity("recording", "Recording TTS")

    def validate_configuration(self) -> TTSConfigurationValidation:
        return TTSConfigurationValidation(True)

    def status(self) -> TTSProviderStatus:
        return TTSProviderStatus(True, TTSAvailability.AVAILABLE)

    def stream(self, request: TTSSynthesisRequest):  # type: ignore[no-untyped-def]
        self.requests.append((request.text, request.voice))
        self.started.set()
        if self.failure is not None:
            raise self.failure
        yield TTSAudioChunk(b"\x00\x00\x01\x00", request.audio_format)


class TTSProviderTests(unittest.TestCase):
    @staticmethod
    def _wav(data: bytes = b"\x00\x00\x01\x00") -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(24_000)
            target.writeframes(data)
        return output.getvalue()

    def test_openai_compatible_profile_uses_base_v1_audio_speech_and_protocol_payload(self) -> None:
        captured: dict[str, object] = {}
        payload = self._wav()
        chunks = deque((payload, b""))
        provider = OpenAICompatibleTTSAdapter(
            endpoint="http://192.168.1.50:8000/v1",
            connect_timeout_seconds=3,
            read_timeout_seconds=60,
            transport=lambda url, body, connect, read: (
                captured.update(url=url, payload=json.loads(body), connect=connect, read=read)
                or _OpenAIHTTPResponse(200, "audio/wav", len(payload), lambda _size: chunks.popleft(), lambda: captured.update(closed=True))
            ),
        )
        self.assertEqual(
            list(provider.stream(TTSSynthesisRequest("openai-1", "Text to speak", "tori", "qwen3-tts-1.7b-voicedesign"))),
            [TTSAudioChunk(b"\x00\x00\x01\x00", PCM_S16LE_MONO_24000)],
        )
        self.assertEqual(captured["url"], "http://192.168.1.50:8000/v1/audio/speech")
        self.assertEqual(captured["payload"], {"model": "qwen3-tts-1.7b-voicedesign", "input": "Text to speak", "voice": "tori", "response_format": "wav"})
        self.assertTrue(captured["closed"])

    def test_openai_compatible_model_is_optional_and_endpoint_policy_remains_bounded(self) -> None:
        payload = self._wav()
        captured: dict[str, object] = {}
        chunks = deque((payload, b""))
        provider = OpenAICompatibleTTSAdapter(
            endpoint="http://127.0.0.1:8000/v1",
            connect_timeout_seconds=3,
            read_timeout_seconds=30,
            transport=lambda _url, body, *_timeouts: (
                captured.update(payload=json.loads(body))
                or _OpenAIHTTPResponse(200, "audio/wav", len(payload), lambda _size: chunks.popleft(), lambda: None)
            ),
        )
        self.assertEqual(len(list(provider.stream(TTSSynthesisRequest("openai-2", "Hello", "tori")))), 1)
        self.assertNotIn("model", captured["payload"])
        for endpoint in ("http://8.8.8.8:8000/v1", "http://169.254.169.254:8000/v1", "http://user@192.168.1.2:8000/v1", "http://192.168.1.2:8000/not-v1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(TTSConfigurationError):
                OpenAICompatibleTTSAdapter(endpoint=endpoint, connect_timeout_seconds=3, read_timeout_seconds=30)

    def test_qwen_request_uses_configured_voice_and_streams_even_pcm(self) -> None:
        captured: dict[str, object] = {}
        blocks = deque((b"\x00", b"\x01\x02\x03", b""))

        def transport(url, payload, connect_timeout, read_timeout):  # type: ignore[no-untyped-def]
            captured.update(
                url=url,
                payload=json.loads(payload),
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
            return _HTTPPCMResponse(
                200,
                "application/octet-stream",
                4,
                lambda _size: blocks.popleft(),
                lambda: captured.update(closed=True),
            )

        provider = CurrentQwenTTSAdapter(transport=transport)

        request = TTSSynthesisRequest("request-1", "Hello Tori.", "tori")
        self.assertEqual(
            list(provider.stream(request)),
            [TTSAudioChunk(b"\x00\x01\x02\x03", PCM_S16LE_MONO_24000)],
        )
        self.assertEqual(provider.status().availability, TTSAvailability.AVAILABLE)
        self.assertEqual(captured["url"], f"{DEFAULT_TTS_ENDPOINT}/v1/audio/speech")
        self.assertEqual(
            captured["payload"],
            {
                "model": "tts-1",
                "input": "Hello Tori.",
                "voice": "tori",
                "response_format": "pcm",
            },
        )
        self.assertTrue(captured["closed"])

    def test_qwen_rejects_errors_malformed_audio_and_unapproved_endpoint(self) -> None:
        odd_stream = deque((b"\x00", b""))
        cases = (
            _HTTPPCMResponse(503, "application/octet-stream", 2, lambda _size: b"", lambda: None),
            _HTTPPCMResponse(200, "text/plain", 2, lambda _size: b"\x00\x00", lambda: None),
            _HTTPPCMResponse(
                200, "audio/pcm", 1, lambda _size: odd_stream.popleft(), lambda: None
            ),
        )
        for response in cases:
            with self.subTest(response=response), self.assertRaises(TTSUnavailableError):
                list(CurrentQwenTTSAdapter(transport=lambda *_args: response).stream(
                    TTSSynthesisRequest("request-1", "Hello.", "tori")
                ))
        with self.assertRaises(TTSConfigurationError):
            CurrentQwenTTSAdapter(endpoint="http://example.test:8000")
        for transport_error in (TimeoutError("slow"), OSError("offline")):
            def unavailable(*_args, error=transport_error):  # type: ignore[no-untyped-def]
                raise error

            with self.subTest(error=type(transport_error).__name__), self.assertRaises(
                TTSUnavailableError
            ):
                list(CurrentQwenTTSAdapter(transport=unavailable).stream(
                    TTSSynthesisRequest("request-1", "Hello.", "tori")
                ))

    def test_qwen_accepts_numeric_loopback_and_rfc1918_but_rejects_other_urls(self) -> None:
        owner_lan_endpoint = "http://" + ".".join(("192", "168", "5", "50")) + ":8000"
        for endpoint in (
            DEFAULT_TTS_ENDPOINT,
            "http://127.0.0.2:8000",
            "http://10.1.2.3:8000",
            "http://172.16.0.1:8000",
            "http://172.31.255.254:8000",
            "http://192.168.1.50:8000",
            owner_lan_endpoint,
        ):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(
                    CurrentQwenTTSAdapter(
                        endpoint=endpoint, transport=lambda *_args: None
                    ).validate_configuration().valid
                )

        for endpoint in (
            "http://localhost:8000",
            "http://169.254.169.254:8000",
            "http://100.64.0.1:8000",
            "http://8.8.8.8:8000",
            "http://user@192.168.1.50:8000",
            "http://user:secret@192.168.1.50:8000",
            "http://192.168.1.50:8000/v1",
            "http://192.168.1.50:8000?query=1",
            "http://192.168.1.50:8000#fragment",
            "https://192.168.1.50:8000",
            "http://[::1]:8000",
            "http://192.168.1.50:0",
            "http://192.168.1.50:not-a-port",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(
                TTSConfigurationError
            ):
                CurrentQwenTTSAdapter(endpoint=endpoint)

    def test_current_adapter_satisfies_provider_contract_without_probing(self) -> None:
        provider = CurrentQwenTTSAdapter(transport=lambda *_args: None)  # type: ignore[arg-type]

        self.assertIsInstance(provider, TextToSpeechProvider)
        self.assertEqual(provider.identity.provider_type, "qwen")
        self.assertTrue(provider.validate_configuration().valid)
        self.assertEqual(provider.status().availability, TTSAvailability.UNKNOWN)

    def test_current_adapter_records_every_safe_unavailable_path(self) -> None:
        provider_error = CurrentQwenTTSAdapter(
            transport=lambda *_args: (_ for _ in ()).throw(
                TTSUnavailableError("transport unavailable")
            )
        )
        with self.assertRaises(TTSUnavailableError):
            list(provider_error.stream(
                TTSSynthesisRequest("request-1", "Hello.", "tori")
            ))
        self.assertEqual(
            provider_error.status().availability, TTSAvailability.UNAVAILABLE
        )

        connection_error = CurrentQwenTTSAdapter(
            transport=lambda *_args: (_ for _ in ()).throw(OSError("offline"))
        )
        with self.assertRaises(TTSUnavailableError):
            list(connection_error.stream(
                TTSSynthesisRequest("request-2", "Hello.", "tori")
            ))
        self.assertEqual(
            connection_error.status().availability, TTSAvailability.UNAVAILABLE
        )

        rejected = CurrentQwenTTSAdapter(
            transport=lambda *_args: _HTTPPCMResponse(
                503, "application/octet-stream", 2, lambda _size: b"", lambda: None
            )
        )
        with self.assertRaises(TTSUnavailableError):
            list(rejected.stream(
                TTSSynthesisRequest("request-3", "Hello.", "tori")
            ))
        self.assertEqual(rejected.status().availability, TTSAvailability.UNAVAILABLE)


class KokoroTTSProviderTests(unittest.TestCase):
    endpoint = "http://192.168.1.50:8880"

    def test_kokoro_streams_canonical_pcm_with_provider_specific_translation(self) -> None:
        captured: dict[str, object] = {}
        blocks = deque((b"\x00\x01\x02", b"\x03", b""))

        def transport(url, payload, connect_timeout, read_timeout):  # type: ignore[no-untyped-def]
            captured.update(
                url=url,
                payload=json.loads(payload),
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
            return _KokoroHTTPPCMResponse(
                200,
                "audio/pcm; rate=24000",
                4,
                lambda _size: blocks.popleft(),
                lambda: captured.update(closed=True),
            )

        provider = KokoroTTSAdapter(endpoint=self.endpoint, transport=transport)
        request = TTSSynthesisRequest("request-1", "Hello from Tori.", "af_heart")

        self.assertEqual(
            list(provider.stream(request)),
            [
                TTSAudioChunk(b"\x00\x01", PCM_S16LE_MONO_24000),
                TTSAudioChunk(b"\x02\x03", PCM_S16LE_MONO_24000),
            ],
        )
        self.assertEqual(
            captured["url"], f"{self.endpoint}/v1/audio/speech"
        )
        self.assertEqual(
            captured["payload"],
            {
                "model": KOKORO_MODEL,
                "input": "Hello from Tori.",
                "voice": "af_heart",
                "response_format": "pcm",
                "stream": True,
            },
        )
        self.assertTrue(captured["closed"])
        self.assertEqual(provider.status().availability, TTSAvailability.AVAILABLE)

    def test_kokoro_conforms_without_network_contact_and_factory_is_explicit(self) -> None:
        provider = KokoroTTSAdapter(
            endpoint=self.endpoint,
            transport=lambda *_args: None,  # type: ignore[arg-type]
        )
        qwen = create_tts_provider(
            "qwen",
            endpoint=DEFAULT_TTS_ENDPOINT,
            connect_timeout_seconds=3,
            read_timeout_seconds=30,
        )
        kokoro = create_tts_provider(
            KOKORO_PROVIDER,
            endpoint=self.endpoint,
            connect_timeout_seconds=3,
            read_timeout_seconds=30,
        )

        self.assertIsInstance(provider, TextToSpeechProvider)
        self.assertIsInstance(qwen, TextToSpeechProvider)
        self.assertIsInstance(kokoro, TextToSpeechProvider)
        self.assertEqual(provider.identity.provider_type, KOKORO_PROVIDER)
        self.assertTrue(provider.validate_configuration().valid)
        self.assertEqual(provider.status().availability, TTSAvailability.UNKNOWN)
        with self.assertRaises(ValueError):
            create_tts_provider(
                "unlisted",
                endpoint=self.endpoint,
                connect_timeout_seconds=3,
                read_timeout_seconds=30,
            )

    def test_kokoro_rejects_unsafe_configuration_and_unsupported_requests(self) -> None:
        for endpoint in (
            "http://localhost:8880",
            "http://user@192.168.1.50:8880",
            "http://192.168.1.50:8880/v1",
            "https://192.168.1.50:8880",
            "http://8.8.8.8:8880",
            "http://[::1]:8880",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(
                TTSConfigurationError
            ):
                KokoroTTSAdapter(endpoint=endpoint)

        provider = KokoroTTSAdapter(
            endpoint=self.endpoint,
            transport=lambda *_args: None,  # type: ignore[arg-type]
        )
        with self.assertRaises(TTSConfigurationError):
            provider.stream(
                TTSSynthesisRequest(
                    "request-1", "Hello.", "af_heart", model="other-model"
                )
            )

    def test_kokoro_failures_are_safe_and_update_availability(self) -> None:
        failures = (
            lambda *_args: (_ for _ in ()).throw(OSError("private connection detail")),
            lambda *_args: _KokoroHTTPPCMResponse(
                503, "audio/pcm", 2, lambda _size: b"", lambda: None
            ),
            lambda *_args: _KokoroHTTPPCMResponse(
                200, "application/json", 2, lambda _size: b"{}", lambda: None
            ),
        )
        request = TTSSynthesisRequest("request-1", "Hello.", "af_heart")
        for transport in failures:
            provider = KokoroTTSAdapter(
                endpoint=self.endpoint,
                transport=transport,
            )
            with self.subTest(transport=transport), self.assertRaises(
                TTSUnavailableError
            ):
                list(provider.stream(request))
            self.assertEqual(
                provider.status().availability, TTSAvailability.UNAVAILABLE
            )

    def test_kokoro_active_stream_closes_promptly_without_false_unavailability(self) -> None:
        started = threading.Event()
        closed = threading.Event()

        def read(_size: int) -> bytes:
            started.set()
            closed.wait(timeout=5)
            raise OSError("closed transport")

        provider = KokoroTTSAdapter(
            endpoint=self.endpoint,
            transport=lambda *_args: _KokoroHTTPPCMResponse(
                200, "audio/pcm", None, read, closed.set
            ),
        )
        coordinator = SpeechCoordinator(provider, voice="af_heart")
        identifier = coordinator.start_completed("Cancel this Kokoro stream.")
        failures: list[Exception] = []

        def consume() -> None:
            try:
                list(coordinator.claim_stream(identifier))
            except Exception as exc:  # pragma: no cover - diagnostic capture
                failures.append(exc)

        consumer = threading.Thread(target=consume)
        consumer.start()
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(coordinator.stop(identifier))
        consumer.join(timeout=1)

        self.assertFalse(consumer.is_alive())
        self.assertTrue(closed.is_set())
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], SpeechSessionStopped)
        self.assertEqual(provider.status().availability, TTSAvailability.UNKNOWN)


class SpeechSegmentationTests(unittest.TestCase):
    def test_natural_boundaries_long_fallback_and_final_flush_are_exact(self) -> None:
        segmenter = SpeechSegmenter(
            minimum_characters=8,
            preferred_characters=30,
            maximum_characters=45,
        )
        self.assertEqual(
            segmenter.feed("Dr. Rivera measured 3.14 units. Next sentence!"),
            ("Dr. Rivera measured 3.14 units.", "Next sentence!"),
        )
        self.assertEqual(segmenter.finish(), ())

        long_segmenter = SpeechSegmenter(
            minimum_characters=8,
            preferred_characters=20,
            maximum_characters=35,
        )
        chunks = long_segmenter.feed("A useful opening clause; followed by more words without a period")
        self.assertEqual(chunks, ("A useful opening clause;",))
        self.assertEqual(long_segmenter.finish(), ("followed by more words without a period",))

    def test_speakable_normalization_omits_markdown_urls_citations_and_sources(self) -> None:
        visible = (
            "## Web findings\n**Useful** [project](https://example.test) details [1].\n\n"
            "Sources\n1. Project — https://example.test"
        )
        self.assertEqual(normalize_speakable_text(visible), "Web findings Useful project details .")
        for private in (
            "<think>private reasoning</think>",
            "[[TORI:EXTERNAL_KNOWLEDGE_NEEDED]]",
            '{"tool":"search","query":"private"}',
            '{"name":"search","arguments":{}}',
        ):
            with self.subTest(private=private):
                self.assertEqual(normalize_speakable_text(private), "")


class SpeechCoordinatorTests(unittest.TestCase):
    def test_ordered_queue_speaks_each_segment_once(self) -> None:
        provider = RecordingTTSProvider()
        coordinator = SpeechCoordinator(provider)
        identifier = coordinator.start()
        coordinator.feed(identifier, "First useful sentence. Second useful sentence!")
        coordinator.finish(identifier)

        self.assertEqual(list(coordinator.claim_stream(identifier)), [b"\x00\x00\x01\x00"] * 2)
        self.assertEqual(
            provider.requests,
            [("First useful sentence.", "tori"), ("Second useful sentence!", "tori")],
        )

    def test_stop_clears_queue_and_prevents_stale_replay(self) -> None:
        coordinator = SpeechCoordinator(RecordingTTSProvider())
        identifier = coordinator.start_completed("This sentence should be abandoned.")
        self.assertTrue(coordinator.stop(identifier))
        with self.assertRaises(SpeechSessionStopped):
            list(coordinator.claim_stream(identifier))
        self.assertFalse(coordinator.stop(identifier))

    def test_active_stop_releases_blocked_provider_stream_without_stale_audio(self) -> None:
        started = threading.Event()
        closed = threading.Event()

        class BlockingStream:
            def __iter__(self):  # type: ignore[no-untyped-def]
                return self

            def __next__(self):  # type: ignore[no-untyped-def]
                started.set()
                closed.wait(timeout=5)
                raise StopIteration

            def close(self) -> None:
                closed.set()

        class BlockingProvider(RecordingTTSProvider):
            def stream(self, request):  # type: ignore[no-untyped-def]
                self.requests.append((request.text, request.voice))
                return BlockingStream()

        coordinator = SpeechCoordinator(BlockingProvider())
        identifier = coordinator.start_completed("Stop this active speech safely.")
        audio: list[bytes] = []
        failures: list[Exception] = []

        def consume() -> None:
            try:
                audio.extend(coordinator.claim_stream(identifier))
            except Exception as exc:  # pragma: no cover - diagnostic capture
                failures.append(exc)

        consumer = threading.Thread(target=consume)
        consumer.start()
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(coordinator.stop(identifier))
        consumer.join(timeout=1)
        self.assertFalse(consumer.is_alive())
        self.assertTrue(closed.is_set())
        self.assertEqual(audio, [])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], SpeechSessionStopped)

    def test_invalid_provider_audio_is_rejected_at_tori_boundary(self) -> None:
        class InvalidAudioProvider(RecordingTTSProvider):
            def stream(self, request):  # type: ignore[no-untyped-def]
                yield TTSAudioChunk(
                    b"\x00\x00",
                    type(PCM_S16LE_MONO_24000)("pcm_s16le", 16_000, 1, 2),
                )

        coordinator = SpeechCoordinator(InvalidAudioProvider())
        identifier = coordinator.start_completed("Reject mismatched provider audio.")
        with self.assertRaisesRegex(TTSUnavailableError, "malformed audio"):
            list(coordinator.claim_stream(identifier))

    def test_tori_boundary_rejects_oversized_fake_provider_stream(self) -> None:
        class UnlimitedProvider(RecordingTTSProvider):
            def stream(self, request):  # type: ignore[no-untyped-def]
                while True:
                    yield TTSAudioChunk(b"\x00\x00", request.audio_format)

        coordinator = SpeechCoordinator(UnlimitedProvider())
        identifier = coordinator.start_completed("Bound this provider output.")
        with patch.object(tts_module, "MAX_TTS_RESPONSE_BYTES", 4):
            with self.assertRaisesRegex(TTSUnavailableError, "safety limit"):
                list(coordinator.claim_stream(identifier))

    def test_upstream_failure_is_secondary_and_later_session_can_succeed(self) -> None:
        failing = RecordingTTSProvider(failure=TTSUnavailableError("private"))
        coordinator = SpeechCoordinator(failing)
        identifier = coordinator.start_completed("First attempt fails safely.")
        with self.assertRaisesRegex(TTSUnavailableError, "private"):
            list(coordinator.claim_stream(identifier))

        working = RecordingTTSProvider()
        later = SpeechCoordinator(working)
        later_identifier = later.start_completed("Later speech works.")
        self.assertTrue(list(later.claim_stream(later_identifier)))


class TTSContractBoundaryTests(unittest.TestCase):
    def test_contract_and_coordinator_have_no_provider_specific_dependency(self) -> None:
        contract_source = inspect.getsource(tts_provider_module).casefold()
        coordinator_source = inspect.getsource(tts_module.SpeechCoordinator).casefold()

        for provider_name in ("qwen", "kokoro", "chatterbox"):
            self.assertNotIn(provider_name, contract_source)
            self.assertNotIn(provider_name, coordinator_source)

    def test_request_validation_is_tori_owned_and_bounded(self) -> None:
        with self.assertRaises(TTSConfigurationError):
            TTSSynthesisRequest("bad id", "Hello.", "tori")
        with self.assertRaises(TTSConfigurationError):
            TTSSynthesisRequest("request-1", "\x00private", "tori")
        with self.assertRaises(TTSConfigurationError):
            TTSSynthesisRequest("request-1", "Hello.", "../../voice")


if __name__ == "__main__":
    unittest.main()
