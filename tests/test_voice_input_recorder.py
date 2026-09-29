from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import threading
from types import SimpleNamespace
import unittest


spec = importlib.util.spec_from_file_location(
    "voice_recognizer_under_test", Path(__file__).resolve().parents[1] / "deploy/voice/recognizer.py")
recognizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recognizer)


class Samples(list):
    def astype(self, _):
        return self

    def __mul__(self, other):
        return Samples(a * b for a, b in zip(self, other))

    def copy(self):
        return Samples(self)


class FakeNumpy:
    float32 = float

    @staticmethod
    def frombuffer(pcm, dtype):
        return Samples(struct.unpack("<" + "h" * (len(pcm) // 2), pcm))

    @staticmethod
    def mean(values):
        return sum(values) / len(values)

    @staticmethod
    def zeros(count, dtype):
        return Samples([0] * count)


class NativeRecorderFixture:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.realtime_recording_id = 0
        self.calls = []
        self.frames_lock = threading.RLock()
        self.frames = []
        self.feed_calls = []
        self.last_frames = []
        self.text_storage = []
        self.active_speech_tail_buffer = bytearray()
        self.transcription_gate = threading.Event()
        self.transcription_gate.set()

    def start(self):
        self.calls.append("start")
        self.realtime_recording_id += 1

    def stop(self):
        self.calls.append("stop")
        self.last_frames = list(self.frames)
        self.frames.clear()

    def wait_audio(self):
        if not self.last_frames:
            raise AssertionError("Native wait_audio would re-arm on empty stop")
        self.calls.append("wait_audio")

    def transcribe(self):
        self.calls.append("transcribe")
        self.transcription_gate.wait(2)
        return "Tori, set a reminder."

    def feed_audio(self, pcm, original_sample_rate):
        self.feed_calls.append((pcm, original_sample_rate))
        self.frames.append(pcm)

    def flush_audio_input(self):
        self.calls.append("flush")

    def drain_audio_input(self, timeout):
        return True

    def clear_audio_queue(self):
        self.calls.append("clear")

    def shutdown(self):
        self.calls.append("shutdown")


class VoiceInputRecorderTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.scheduler = SimpleNamespace(close=lambda: None)
        self.wrapper = recognizer.ManualRecognizer(
            NativeRecorderFixture, self.scheduler, "/tmp/prepared-model-fixture",
            lambda *event: self.events.append(event), FakeNumpy)
        self.addCleanup(self.wrapper.shutdown)
        self.wrapper.open("same-session")

    def test_ten_native_stop_wait_transcribe_cycles_with_no_shutdown(self):
        recorder = self.wrapper.recorder
        for number in range(10):
            turn = f"turn-{number}"
            self.wrapper.begin(turn, 48000)
            self.wrapper.audio(turn, 1, b"\x00\x10" * 100)
            self.wrapper._partial(SimpleNamespace(recording_id=number + 1, raw_observation_text="Tori"))
            self.wrapper.finalize(turn)
            self.assertTrue(self.wrapper.final_done.wait(2))
            self.assertEqual(self.events[-1][0:3], ("same-session", turn, "final"))
            self.assertIs(self.wrapper.recorder, recorder)
            self.assertEqual(recorder.frames, [])
        self.assertEqual(recorder.calls.count("transcribe"), 10)
        self.assertEqual(recorder.calls.count("stop"), 10)
        self.assertEqual(recorder.calls.count("wait_audio"), 10)
        self.assertNotIn("shutdown", recorder.calls)

    def test_manual_boundaries_pause_independent_no_auto_stop(self):
        self.wrapper.begin("turn", 48000)
        self.assertFalse(self.wrapper.recorder.stop_recording_on_voice_deactivity)
        self.assertFalse(self.wrapper.recorder.start_recording_on_voice_activity)
        self.wrapper.audio("turn", 1, b"\x00\x10" * 100)
        self.wrapper.audio("turn", 2, b"\x00\x00" * 16000)
        self.wrapper.audio("turn", 3, b"\x00\x00" * 16000)
        self.wrapper.audio("turn", 4, b"\x00\x10" * 100)
        self.assertNotIn("stop", self.wrapper.recorder.calls)
        self.wrapper.finalize("turn")
        self.assertTrue(self.wrapper.final_done.wait(2))
        self.assertEqual(self.events[-1][2], "final")

    def test_speech_pcm_uses_the_supported_array_resampling_path(self):
        self.wrapper.begin("speech", 48000)
        result = self.wrapper.audio("speech", 1, struct.pack("<hhh", -32768, 0, 32767))
        samples, sample_rate = self.wrapper.recorder.feed_calls[-1]
        self.assertIsInstance(samples, Samples)
        self.assertEqual(samples, [-32768, 0, 32767])
        self.assertEqual(sample_rate, 48000)
        self.assertTrue(self.wrapper.heard_signal)
        self.assertEqual(result, {"input_frames": 3, "native_frames": 1})

    def test_stale_structured_partial_is_not_reassigned(self):
        self.wrapper.begin("old", 48000)
        old_id = self.wrapper.recording_id
        self.wrapper.cancel("old")
        self.wrapper.begin("new", 48000)
        self.wrapper._partial(SimpleNamespace(recording_id=old_id, raw_observation_text="Old text"))
        self.assertEqual(self.events, [])
        self.wrapper._partial(SimpleNamespace(recording_id=self.wrapper.recording_id, raw_observation_text="New text"))
        self.assertEqual(self.events[-1][1], "new")

    def test_silence_and_immediate_release_never_invoke_final_asr(self):
        self.wrapper.begin("silent", 48000)
        self.wrapper.audio("silent", 1, b"\x00\x00" * 100)
        self.wrapper.finalize("silent")
        self.assertTrue(self.wrapper.final_done.wait(2))
        self.assertEqual(self.events[-1][2], "no_speech")
        self.wrapper.begin("empty", 48000)
        self.wrapper.finalize("empty")
        self.assertTrue(self.wrapper.final_done.wait(2))
        self.assertNotIn("transcribe", self.wrapper.recorder.calls)

    def test_cancel_pending_final_fences_result_before_reset(self):
        recorder = self.wrapper.recorder
        recorder.transcription_gate.clear()
        self.wrapper.begin("cancelled", 48000)
        self.wrapper.audio("cancelled", 1, b"\x00\x10" * 100)
        self.wrapper.finalize("cancelled")
        cancelled = threading.Thread(target=self.wrapper.cancel, args=("cancelled",))
        cancelled.start()
        import time
        deadline = time.monotonic() + 1
        while self.wrapper.turn is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(self.wrapper.turn)
        recorder.transcription_gate.set()
        cancelled.join(2)
        self.assertFalse(cancelled.is_alive())
        self.assertEqual(self.events, [])
        self.wrapper.begin("next", 48000)

    def test_recorder_privacy_and_local_model_configuration(self):
        options = self.wrapper.recorder.options
        self.assertFalse(options["use_microphone"])
        self.assertTrue(options["no_log_file"])
        self.assertEqual(options["silero_backend"], "raw_onnx")
        self.assertTrue(options["model"].endswith("/small.en"))
        self.assertEqual(options["batch_size"], 0)
        self.assertEqual(options["compute_type"], "int8_float16")

    def test_shared_scheduler_reuses_two_engines_and_cleans_up(self):
        calls = []
        class Engine:
            def __init__(self, kind):
                self.kind = kind
            def transcribe(self, *args):
                calls.append(self.kind)
                return SimpleNamespace(text=self.kind)
        scheduler = recognizer.SharedInferenceScheduler(Engine("final"), Engine("realtime"))
        try:
            for _ in range(10):
                self.assertEqual(scheduler.execute("realtime", Samples([1]), "en", False).text, "realtime")
                self.assertEqual(scheduler.execute("final", Samples([1]), "en", False).text, "final")
            self.assertEqual(len(calls), 20)
        finally:
            scheduler.close()
        self.assertFalse(scheduler.thread.is_alive())
        self.assertEqual(scheduler.engines, {})
