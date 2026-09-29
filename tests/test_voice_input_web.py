from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from test_voice_input import FakeRecognition, binding
from test_web import RecordingProvider, RecordingSpeechProvider, free_port
from tori.checkpoints import CheckpointStore
from tori.companion_initiative import InitiativeSettings, SQLiteCompanionInitiativeStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.voice_input import VoiceInputService
from tori.voice_input_web import decode_document
from tori.speech_recognition import RecognitionError
from tori.tts import SpeechCoordinator
from tori.user_settings import CapabilitySettingsController
from tori.web import WebApplication, create_web_server


class VoiceInputWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.fake = FakeRecognition()
        self.service = VoiceInputService(self.fake)
        self.initiative = SQLiteCompanionInitiativeStore(root / "initiative.db")
        self.initiative.save_settings(
            InitiativeSettings(master_enabled=True), expected_revision=0
        )
        self.application = WebApplication(
            RecordingProvider(), port=free_port(),
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake", model_name="fake", voice_input=self.service,
            companion_initiative_store=self.initiative,
        )
        self.server = create_web_server(self.application)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.service.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, operation, document=None, *, raw=None, headers=None, method="POST"):
        connection = HTTPConnection("127.0.0.1", self.application.port, timeout=3)
        values = {"Host": self.application.expected_host,
                  "Origin": self.application.expected_origin,
                  "X-Tori-CSRF": self.application.csrf_token,
                  "Content-Type": "application/json"}
        values.update(headers or {})
        connection.request(method, "/api/voice-input/" + operation,
                           body=raw if raw is not None else json.dumps(document or {}).encode(),
                           headers=values)
        response = connection.getresponse()
        if operation == "events" and response.status == 200:
            return connection, response
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def begin(self, ready):
        code, turn = self.request("begin", {**binding(ready), "sample_rate": 48000,
                                            "channels": 1, "encoding": "pcm_s16le"})
        self.assertEqual(code, 200)
        return turn

    def test_status_and_typed_conversation_independent(self):
        activity = self.initiative.activity()
        code, status = self.request("status", method="GET")
        self.assertEqual(code, 200)
        self.assertTrue(status["user_accessible"])
        self.assertNotIn("lease", status)
        code, status = self.request("acquire")
        self.assertEqual(code, 200)
        self.assertEqual(self.application._visible_transcript(), [])
        self.assertEqual(self.request("release", binding(status))[0], 200)
        self.assertEqual(self.initiative.activity(), activity)

    def test_fenced_final_is_admitted_once_through_normal_stream(self):
        before = self.initiative.activity().revision
        _, ready = self.request("acquire")
        turn = self.begin(ready)
        _, pending = self.request(
            "finalize", {**binding(turn, turn=True), "last_sequence": 0}
        )
        self.fake.result(turn["utterance_id"], text="Voice final text")
        event = next(item for item in self.service._events if item["kind"] == "final")
        owner = self.service.heartbeat({
            **binding(pending), "revision": self.service.status()["revision"],
        })
        connection = HTTPConnection("127.0.0.1", self.application.port, timeout=3)
        headers = {
            "Host": self.application.expected_host,
            "Origin": self.application.expected_origin,
            "X-Tori-CSRF": self.application.csrf_token,
            "Content-Type": "application/json",
        }
        body = json.dumps({
            **binding(owner), "segment": event["segment"],
            "event_sequence": event["event_sequence"], "auto_speech": False,
        }).encode()
        connection.request("POST", "/api/voice-input/admit", body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn('"type":"complete"', payload)
        self.assertIn("Voice final text", payload)
        self.assertEqual(self.initiative.activity().revision, before + 1)
        self.assertEqual(self.request("admit", {**binding(owner), "segment": event["segment"], "event_sequence": event["event_sequence"], "auto_speech": False})[1]["code"], "stale_segment")
        self.assertEqual(self.initiative.activity().revision, before + 1)

    def test_voice_final_preserves_normal_auto_speech_path(self):
        speech = RecordingSpeechProvider()
        self.application._speech = SpeechCoordinator(speech)
        self.application._capability_settings = CapabilitySettingsController(
            administrator_web_search=False,
            administrator_speech_output=True,
            store=None,
        )
        _, ready = self.request("acquire")
        turn = self.begin(ready)
        self.request("finalize", {**binding(turn, turn=True), "last_sequence": 0})
        self.fake.result(turn["utterance_id"], text="Speak this voice response")
        event = next(item for item in self.service._events if item["kind"] == "final")
        owner = self.service.heartbeat({
            **binding(turn), "revision": self.service.status()["revision"],
        })
        code, _ = self.request("admit", {
            **binding(owner), "segment": event["segment"],
            "event_sequence": event["event_sequence"], "auto_speech": "yes",
        })
        self.assertEqual(code, 400)

        connection = HTTPConnection("127.0.0.1", self.application.port, timeout=3)
        headers = {"Host": self.application.expected_host,
                   "Origin": self.application.expected_origin,
                   "X-Tori-CSRF": self.application.csrf_token,
                   "Content-Type": "application/json"}
        body = json.dumps({
            **binding(owner), "segment": event["segment"],
            "event_sequence": event["event_sequence"], "auto_speech": True,
        }).encode()
        connection.request("POST", "/api/voice-input/admit", body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn('"type":"speech"', payload)
        self.assertIn('"type":"complete"', payload)
        status, replay = self.application.prepare_speech(1)
        self.assertEqual(status, 200)
        self.assertEqual(
            [item["type"] for item in self.application.stream_speech(
                replay["speech_session"]
            )],
            ["start", "audio", "complete"],
        )

    def test_ten_turns_fenced_events_on_one_connection(self):
        _, ready = self.request("acquire")
        connection, events = self.request("events", binding(ready))
        session = ready["session_id"]
        try:
            for number in range(1, 11):
                turn = self.begin(ready)
                audio_binding = {**binding(turn, turn=True), "sequence": 1}
                code, turn = self.request("audio", raw=b"\x00\x10" * 100,
                                         headers={"Content-Type": "application/octet-stream",
                                                  "X-Tori-Voice-Binding": json.dumps(audio_binding)})
                self.assertEqual(code, 200)
                self.fake.result(turn["utterance_id"], "partial", "Transient partial")
                code, finalizing = self.request("finalize", {**binding(turn, turn=True), "last_sequence": 1})
                self.assertEqual(code, 200)
                self.fake.result(turn["utterance_id"], text=f"Turn {number}")
                while True:
                    event = json.loads(events.readline())
                    if event["kind"] == "final":
                        break
                self.assertEqual(event["utterance_id"], turn["utterance_id"])
                self.assertEqual(event["segment"], number)
                self.assertEqual(event["text"], f"Turn {number}")
                ready = self.service.heartbeat(binding(self.service._owner_document()))
                self.assertEqual(ready["session_id"], session)
            self.assertEqual(self.fake.prepares, 1)
            self.assertEqual(self.fake.opens, 1)
            self.assertEqual(self.application._visible_transcript(), [])
            self.request("release", binding(ready))
        finally:
            connection.close()

    def test_competitor_stale_owner_wrong_segment_double_finalize(self):
        before = self.initiative.activity()
        _, ready = self.request("acquire")
        self.assertEqual(self.request("acquire")[1]["code"], "controller_busy")
        turn = self.begin(ready)
        self.assertEqual(self.request("cancel", {**binding(turn, turn=True), "utterance_id": "wrong"})[1]["code"], "stale_segment")
        _, finalizing = self.request("finalize", {**binding(turn, turn=True), "last_sequence": 0})
        self.assertEqual(self.request("finalize", {**binding(finalizing, turn=True), "last_sequence": 0})[1]["code"], "invalid_transition")
        _, ready = self.request("cancel", binding(finalizing, turn=True))
        self.assertEqual(self.request("clear", binding(ready))[0], 200)
        self.request("release", binding(ready))
        self.assertEqual(self.request("heartbeat", binding(ready))[1]["code"], "stale_controller")
        self.assertEqual(self.request("acquire")[0], 200)
        self.assertEqual(self.initiative.activity(), before)

    def test_empty_recognition_never_reaches_meaningful_activity(self):
        before = self.initiative.activity()
        _, ready = self.request("acquire")
        turn = self.begin(ready)
        self.request("finalize", {**binding(turn, turn=True), "last_sequence": 0})
        self.fake.result(turn["utterance_id"], text="")
        self.assertEqual(self.initiative.activity(), before)

    def test_malformed_oversized_wrong_format_no_mutation(self):
        for raw in (b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"{"):
            self.assertEqual(self.request("acquire", raw=raw)[0], 400)
        self.assertEqual(self.request("acquire", raw=b" " * 4097)[0], 413)
        _, ready = self.request("acquire")
        turn = self.begin(ready)
        headers = {"Content-Type": "application/octet-stream",
                   "X-Tori-Voice-Binding": json.dumps({**binding(turn, turn=True), "sequence": 1})}
        self.assertEqual(self.request("audio", raw=b"x" * 32770, headers=headers)[0], 413)
        self.assertEqual(self.request("audio", raw=b"x", headers=headers)[1]["code"], "malformed_audio")
        self.assertEqual(self.fake.audio, [])

    def test_csrf_origin_and_nonloopback_rejected(self):
        for headers in ({"X-Tori-CSRF": "wrong"}, {"Origin": "http://evil.local"}):
            self.assertEqual(self.request("acquire", headers=headers)[0], 403)
        with patch("tori.web.is_loopback_client", return_value=False):
            self.assertEqual(self.request("acquire")[1]["code"], "local_only")
        self.assertEqual(self.fake.prepares, 0)

    def test_strict_json_and_boolean_fences(self):
        for raw in ("{" + '"a":0,' * 500 + '"b":1}', "[" * 1100):
            with self.assertRaises(RecognitionError):
                decode_document(raw)
        _, ready = self.request("acquire")
        bad = {**binding(ready), "revision": True}
        self.assertEqual(self.request("heartbeat", bad)[0], 400)

    def test_disconnect_releases_ownership(self):
        _, ready = self.request("acquire")
        connection, response = self.request("events", binding(ready))
        response.readline()
        response.close()
        connection.close()
        # Force the next bounded heartbeat write to observe the closed socket.
        import time
        deadline = time.monotonic() + 4
        while self.service.status()["controller_active"] and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.service.status()["controller_active"])
