from __future__ import annotations

from dataclasses import replace
import threading
import unittest

from tori.speech_recognition import (
    AudioFormat, RecognitionError, RecognitionEvent, RecognitionHealth, SpeechRecognitionPort,
)
from tori.voice_input import VoiceInputService, VoiceLimits, VoiceState


class FakeRecognition:
    """Conforming engine-free contract fixture; never opens a store or file."""
    configured = True

    def __init__(self):
        self.prepares = 0
        self.opens = 0
        self.stops = 0
        self.closed = 0
        self.turns = []
        self.audio = []
        self.finalizations = []
        self.cancelled = []
        self.state = "off"
        self.fail_prepare = False
        self.fail_close = False
        self.fail_stop = False
        self.feed_gate = None
        self.session_id = None
        self.emit = None

    def prepare(self):
        self.prepares += 1
        if self.fail_prepare:
            raise RecognitionError("readiness_timeout")
        self.state = "ready"

    def open_session(self, session_id, emit):
        self.opens += 1
        self.session_id, self.emit = session_id, emit

    def begin_utterance(self, utterance_id, audio_format):
        self.turns.append(utterance_id)

    def feed_audio(self, utterance_id, sequence, pcm):
        if self.feed_gate:
            self.feed_gate.wait(2)
        self.audio.append((utterance_id, sequence, pcm))

    def finalize_utterance(self, utterance_id):
        self.finalizations.append(utterance_id)

    def cancel_utterance(self, utterance_id):
        self.cancelled.append(utterance_id)

    def close_session(self):
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("private path / secret / transcript")

    def stop(self):
        self.stops += 1
        if self.fail_stop:
            raise RuntimeError("private details")
        self.state = "off"

    def health(self):
        return RecognitionHealth(self.state)

    def result(self, turn, kind="final", text="A synthetic test turn."):
        self.emit(RecognitionEvent(self.session_id, turn, kind, text))


def binding(document, *, turn=False):
    names = ["epoch", "lease", "lease_generation", "revision"]
    if turn:
        names.append("utterance_id")
    return {k: document[k] for k in names}


class VoiceInputTests(unittest.TestCase):
    def test_stale_cleanup_does_not_revoke_new_controller(self):
        first = self.service.acquire()
        self.service.release(binding(first))
        second = self.service.acquire()
        self.service._fail("runtime_exited", expected_session=first["session_id"])
        self.assertEqual(self.service.heartbeat(binding(second))["session_id"], second["session_id"])

    def test_off_during_startup_revokes_before_prepare_returns(self):
        entered = threading.Event()
        resume = threading.Event()
        original = self.fake.prepare
        def prepare():
            entered.set()
            resume.wait(2)
            original()
        self.fake.prepare = prepare
        errors = []
        def acquire():
            try:
                self.service.acquire()
            except RecognitionError as exc:
                errors.append(exc.code)
        thread = threading.Thread(target=acquire)
        thread.start()
        self.assertTrue(entered.wait(1))
        self.service.shutdown()
        resume.set()
        thread.join(2)
        self.assertEqual(errors, ["stale_controller"])
        self.assertEqual(self.fake.opens, 0)
        self.assertEqual(self.service.status()["state"], "off")

    def test_operation_backpressure_does_not_create_an_audio_queue(self):
        _, turn = self.start()
        self.service._operation_lock.acquire()
        try:
            self.error("backpressure", self.service.audio, binding(turn, turn=True), 1, b"\x00\x10")
            self.error("backpressure", self.service.finalize, binding(turn, turn=True), 0)
        finally:
            self.service._operation_lock.release()
        self.assertEqual(self.fake.audio, [])

    def test_wall_clock_utterance_limit_even_without_audio(self):
        self.start()
        self.now[0] = 61
        # Fresh heartbeat prevents lease expiry taking precedence.
        self.service._last_heartbeat = 61
        self.service.check_liveness()
        self.assertEqual(self.service.status()["error"], "utterance_limit")

    def setUp(self):
        self.fake = FakeRecognition()
        self.now = [0.0]
        self.service = VoiceInputService(self.fake, clock=lambda: self.now[0])
        self.addCleanup(self.service.shutdown)

    def error(self, code, function, *args):
        with self.assertRaises(RecognitionError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def start(self):
        ready = self.service.acquire()
        listening = self.service.begin(binding(ready), AudioFormat(48000))
        return ready, listening

    def test_port_is_replaceable_and_starts_off(self):
        self.assertIsInstance(self.fake, SpeechRecognitionPort)
        self.assertEqual(self.service.status()["state"], "off")
        self.assertEqual(self.fake.prepares, 0)
        self.assertTrue(self.service.status()["user_accessible"])

    def test_off_preparing_ready_stopping_off_and_sanitized_status(self):
        ready = self.service.acquire()
        self.assertEqual(ready["state"], "ready")
        status = self.service.status()
        self.assertNotIn("lease", status)
        self.assertNotIn("session_id", status)
        self.assertNotIn("text", status)
        self.service.release(binding(ready))
        self.assertEqual(self.service.status()["state"], "off")
        self.assertEqual((self.fake.prepares, self.fake.opens, self.fake.closed, self.fake.stops), (1,1,1,1))

    def test_startup_failure_is_truthful_cleaned_and_explicitly_retryable(self):
        self.fake.fail_prepare = True
        self.error("readiness_timeout", self.service.acquire)
        self.assertEqual(self.service.status()["state"], "error")
        self.assertFalse(self.service.status()["enabled"])
        self.assertEqual(self.fake.stops, 1)
        self.fake.fail_prepare = False
        self.assertEqual(self.service.acquire()["state"], "ready")

    def test_competing_controller_and_reconnect_do_not_inherit_authority(self):
        old = self.service.acquire()
        self.error("controller_busy", self.service.acquire)
        self.service.release(binding(old))
        new = self.service.acquire()
        self.assertNotEqual(old["lease"], new["lease"])
        self.assertGreater(new["lease_generation"], old["lease_generation"])
        self.error("stale_controller", self.service.heartbeat, binding(old))
        self.error("stale_controller", self.service.release, binding(old))
        self.assertEqual(self.service.status()["state"], "ready")

    def test_off_and_invalid_transitions(self):
        self.error("stale_controller", self.service.audio, {}, 1, b"\0\0")
        ready = self.service.acquire()
        self.error("stale_segment", self.service.finalize, binding(ready, turn=True), 0)
        self.error("stale_revision", self.service.begin, {**binding(ready), "revision": -1}, AudioFormat(48000))
        listening = self.service.begin(binding(ready), AudioFormat(48000))
        self.error("invalid_transition", self.service.begin, binding(listening), AudioFormat(48000))
        pending = self.service.finalize(binding(listening, turn=True), 0)
        self.error("invalid_transition", self.service.begin, binding(pending), AudioFormat(48000))
        self.error("invalid_transition", self.service.finalize, binding(pending, turn=True), 0)
        self.assertEqual(len(self.fake.finalizations), 1)

    def test_ten_reusable_turns_with_isolated_partial_and_final_events(self):
        document = self.service.acquire()
        session = document["session_id"]
        stream = self.service.events(binding(document))
        self.addCleanup(stream.close)
        seen = []
        for n in range(10):
            document = self.service.begin(binding(document), AudioFormat(48000))
            turn = document["utterance_id"]
            seen.append(turn)
            self.fake.result(turn, "partial", f"Partial {n}")
            document = self.service.audio(binding(document, turn=True), 1, b"\x10\x01" * 4800)
            document = self.service.finalize(binding(document, turn=True), 1)
            self.fake.result(turn, text=f"Final {n}")
            finals = []
            while not finals:
                event = next(stream)
                if event["kind"] == "partial":
                    self.assertEqual(event["utterance_id"], turn)
                if event["kind"] == "final":
                    finals.append(event)
            self.assertEqual(finals[0]["text"], f"Final {n}")
            self.assertEqual(finals[0]["segment"], n+1)
            self.assertEqual(finals[0]["utterance_id"], turn)
            self.assertEqual(finals[0]["session_id"], session)
            document = self.service.heartbeat({**binding(document), "revision": self.service.status()["revision"]})
            self.assertEqual(document["state"], "ready")
        self.assertEqual(len(set(seen)), 10)
        self.assertEqual((self.fake.prepares, self.fake.opens), (1,1))
        self.assertEqual(len(self.fake.finalizations), 10)

    def test_heartbeating_ready_controller_survives_and_ptt_turns_do_not_release_it(self):
        ready = self.service.acquire()
        for _ in range(3):
            self.now[0] += 4
            ready = self.service.heartbeat(binding(ready))
            self.service.check_liveness()
            self.assertEqual(self.service.status()["state"], "ready")
            self.assertTrue(self.service.status()["controller_active"])
        for _ in range(2):
            turn = self.service.begin(binding(ready), AudioFormat(48000))
            turn = self.service.audio(binding(turn, turn=True), 1, b"\x00\x10" * 100)
            pending = self.service.finalize(binding(turn, turn=True), 1)
            self.fake.result(turn["utterance_id"])
            ready = self.service.heartbeat({
                **binding(pending), "revision": self.service.status()["revision"],
            })
            self.assertEqual(ready["state"], "ready")
            self.assertEqual(self.fake.stops, 0)
        self.service.release(binding(ready))
        self.assertEqual(self.service.status()["state"], "off")
        self.assertEqual(self.fake.stops, 1)

    def test_late_and_wrong_segment_results_cannot_cross_turns(self):
        ready, old = self.start()
        pending = self.service.finalize(binding(old, turn=True), 0)
        self.fake.result(old["utterance_id"])
        current = self.service.heartbeat({**binding(pending), "revision": self.service.status()["revision"]})
        new = self.service.begin(binding(current), AudioFormat(48000))
        self.fake.result(old["utterance_id"], "partial", "stale")
        self.fake.result(old["utterance_id"], "final", "stale")
        self.error("stale_segment", self.service.audio,
                   {**binding(new, turn=True), "utterance_id": old["utterance_id"]}, 1, b"\0\0")
        self.assertEqual(self.service.status()["state"], "listening_ptt")
        self.assertFalse(any(e.get("text") == "stale" for e in self.service._events))

    def test_final_candidate_is_fenced_single_use_and_not_persisted(self):
        _, turn = self.start()
        pending = self.service.finalize(binding(turn, turn=True), 0)
        self.fake.result(turn["utterance_id"], text="Recognized locally")
        candidate_event = next(e for e in self.service._events if e["kind"] == "final")
        ready = self.service.heartbeat({
            **binding(pending), "revision": self.service.status()["revision"],
        })
        self.assertEqual(
            self.service.claim_final(
                binding(ready), candidate_event["segment"], candidate_event["event_sequence"]
            ),
            "Recognized locally",
        )
        self.error(
            "stale_segment", self.service.claim_final, binding(ready),
            candidate_event["segment"], candidate_event["event_sequence"],
        )
        self.assertFalse(hasattr(self.service, "transcript_store"))

    def test_audio_formats_sequences_and_limits_are_bounded(self):
        for format in (AudioFormat(16000), AudioFormat(True), AudioFormat(48000,2), AudioFormat(48000,1,"wav")):
            self.error("malformed_audio", format.validate)
        _, doc = self.start()
        b = binding(doc, turn=True)
        for sequence, pcm in ((True,b"\0\0"),(2,b"\0\0"),(1,b"x"),(1,b""),(1,b"\0\0"*16385)):
            self.error("malformed_audio", self.service.audio, b, sequence, pcm)
        for n in range(1, 181):
            doc = self.service.audio(b, n, b"\0\0"*16000)
        self.error("utterance_limit", self.service.audio, b, 181, b"\0\0"*16000)
        self.assertEqual(len(self.fake.audio), 180)

    def test_cancel_reset_clear_and_empty_result_do_not_destroy_session(self):
        _, doc = self.start()
        clear = self.service.clear(binding(doc))
        self.assertEqual(clear["state"], "listening_ptt")
        ready = self.service.cancel(binding(clear, turn=True))
        self.assertEqual(ready["state"], "ready")
        doc = self.service.begin(binding(ready), AudioFormat(48000))
        pending = self.service.finalize(binding(doc, turn=True), 0)
        self.fake.result(doc["utterance_id"], text=" ")
        self.assertEqual(self.service.status()["state"], "ready")
        event = next(e for e in self.service._events if e["kind"] == "no_speech")
        self.assertEqual(event["code"], "empty_transcript")
        self.assertEqual(self.fake.opens, 1)

    def test_disconnect_revokes_controller_and_cleans_up(self):
        doc = self.service.acquire()
        stream = self.service.events(binding(doc))
        next(stream)
        stream.close()
        self.assertEqual(self.service.status()["state"], "off")
        self.error("stale_controller", self.service.heartbeat, binding(doc))

    def test_heartbeat_loss_and_finalization_timeout(self):
        doc = self.service.acquire()
        self.now[0] = 6
        self.service.check_liveness()
        self.assertEqual(self.service.status()["state"], "off")
        _, doc = self.start()
        self.service.finalize(binding(doc, turn=True), 0)
        self.now[0] += 11
        self.service._last_heartbeat = self.now[0]
        self.service.check_liveness()
        self.assertEqual(self.service.status()["error"], "finalization_timeout")

    def test_runtime_exit_and_off_during_work_fence_late_final(self):
        _, doc = self.start()
        self.service.release(binding(doc))
        self.fake.result(doc["utterance_id"])
        self.assertEqual(self.service.status()["state"], "off")
        doc = self.service.acquire()
        self.fake.state = "failed"
        self.service.check_liveness()
        self.assertEqual(self.service.status()["error"], "runtime_exited")

    def test_shutdown_attempts_stop_after_session_error_and_does_not_lie(self):
        doc = self.service.acquire()
        self.fake.fail_close = True
        self.service.release(binding(doc))
        self.assertEqual(self.service.status()["state"], "off")
        doc = self.service.acquire()
        self.fake.fail_stop = True
        self.service.release(binding(doc))
        self.assertEqual(self.service.status()["state"], "stopping")
        self.assertEqual(self.service.status()["error"], "cleanup_pending")
        self.error("controller_busy", self.service.acquire)
        self.fake.fail_stop = False

    def test_bounded_errors_never_expose_engine_exception_content(self):
        self.assertEqual(RecognitionError("private transcript").code, "communication_failed")
        self.assertNotIn("private", str(RecognitionError("private transcript")))


if __name__ == "__main__":
    unittest.main()
