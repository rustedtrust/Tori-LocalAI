"""Private RealtimeSTT implementation; imported only in the isolated worker.

Uses the 1.1.2 public recorder/executor APIs. See NOTICE.md for upstream evidence.
No microphone, file input, automatic endpoint admission, or transcript logging.
"""

from concurrent.futures import Future
import math
from pathlib import Path
import queue
import threading
from contextlib import nullcontext


class SharedInferenceScheduler:
    """One bounded interactive scheduler and two loaded models for the runtime."""

    def __init__(self, final_engine, realtime_engine):
        self.engines = {"final": final_engine, "realtime": realtime_engine}
        self.jobs = queue.PriorityQueue(maxsize=2)
        self.lock = threading.Lock()
        self.sequence = 0
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._work, name="voice-inference", daemon=True)
        self.thread.start()

    def execute(self, kind, audio, language, use_prompt):
        future = Future()
        with self.lock:
            self.sequence += 1
            number = self.sequence
        if self.stopping.is_set():
            raise RuntimeError("scheduler_stopped")
        try:
            self.jobs.put_nowait((0 if kind == "final" else 1, number, kind,
                                 audio.copy(), language, use_prompt, future))
        except queue.Full:
            raise RuntimeError("backpressure") from None
        return future.result(timeout=10)

    def _work(self):
        while not self.stopping.is_set():
            try:
                _, _, kind, audio, language, use_prompt, future = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if future.set_running_or_notify_cancel():
                    result = self.engines[kind].transcribe(audio, language, use_prompt)
                    future.set_result(result)
            except Exception:
                future.set_exception(RuntimeError("inference_failed"))
            finally:
                self.jobs.task_done()
                del audio

    def close(self):
        self.stopping.set()
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            job[-1].cancel()
            self.jobs.task_done()
        self.thread.join(timeout=4)
        if self.thread.is_alive():
            raise RuntimeError("cleanup_pending")
        self.engines.clear()


class EngineExecutor:
    supports_streaming = False

    def __init__(self, scheduler, kind):
        self.scheduler, self.kind = scheduler, kind

    def transcribe(self, audio, language=None, use_prompt=True):
        return self.scheduler.execute(self.kind, audio, language, use_prompt)


def prepare_recognizer(models, emit):
    # Imports must never occur in Tori's main Python environment.
    from importlib.metadata import version
    if version("RealtimeSTT") != "1.1.2":
        raise RuntimeError("runtime_unavailable")
    import numpy as np
    from RealtimeSTT import AudioToTextRecorder
    from RealtimeSTT.transcription_engines import TranscriptionEngineConfig, create_transcription_engine

    engines = []
    for model in ("small.en", "tiny.en"):
        root = Path(models) / model
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError("runtime_unavailable")
        config = TranscriptionEngineConfig(
            model=str(root), device="cuda", compute_type="int8_float16",
            gpu_device_index=0, batch_size=0, beam_size=5 if model == "small.en" else 3,
            vad_filter=True, normalize_audio=False,
        )
        engine = create_transcription_engine("faster_whisper", config)
        # Verify actual model usability; process existence is not readiness.
        engine.transcribe(np.zeros(1600, dtype=np.float32), "en", False)
        engines.append(engine)
    scheduler = SharedInferenceScheduler(*engines)
    return ManualRecognizer(AudioToTextRecorder, scheduler, models, emit, np)


class ManualRecognizer:
    def __init__(self, recorder_factory, scheduler, models, emit, numpy):
        self.np = numpy
        self.scheduler, self.emit = scheduler, emit
        self.lock = threading.RLock()
        self.session = None
        self.turn = None
        self.recording_id = None
        self.sequence = 0
        self.sample_rate = 48000
        self.audio_bytes = 0
        self.heard_signal = False
        self.finalizing = False
        self.final_done = threading.Event()
        self.final_done.set()
        self.recorder = recorder_factory(
            model=str(Path(models) / "small.en"), realtime_model_type=str(Path(models) / "tiny.en"),
            language="en", device="cuda", compute_type="int8_float16",
            use_microphone=False, spinner=False, debug_mode=False, no_log_file=True,
            level=50, batch_size=0, realtime_batch_size=0,
            enable_realtime_transcription=True, realtime_processing_pause=0.2,
            init_realtime_after_seconds=0.2, min_length_of_recording=0,
            min_gap_between_recordings=0, post_speech_silence_duration=0.8,
            pre_recording_buffer_duration=0.5, start_callback_in_new_thread=False,
            silero_backend="raw_onnx", silero_onnx_model_path=str(Path(models) / "silero_vad.onnx"),
            early_transcription_on_silence=0, realtime_punctuation_split_marks="off",
            transcription_executor=EngineExecutor(scheduler, "final"),
            realtime_transcription_executor=EngineExecutor(scheduler, "realtime"),
            on_realtime_text_stabilization_update=self._partial,
        )

    def _partial(self, event):
        with self.lock:
            # A native event carries the recording ID captured when its inference began.
            if (
                not self.session or not self.turn or self.finalizing
                or getattr(event, "recording_id", None) != self.recording_id
            ):
                return
            text = getattr(event, "raw_observation_text", "") or ""
            if isinstance(text, str) and text.strip():
                self.emit(self.session, self.turn, "partial", text)

    def open(self, session_id):
        with self.lock:
            if self.session is not None:
                raise RuntimeError("invalid_transition")
            self.session = session_id

    def begin(self, turn_id, sample_rate):
        with self.lock:
            if not self.session or self.turn or self.finalizing or not self.final_done.is_set():
                raise RuntimeError("invalid_transition")
            if type(sample_rate) is not int or sample_rate not in {44100, 48000}:
                raise RuntimeError("malformed_audio")
            self._wipe()
            self.turn = turn_id
            self.sample_rate = sample_rate
            self.sequence = 0
            self.audio_bytes = 0
            self.heard_signal = False
            self.recorder.start_recording_on_voice_activity = False
            self.recorder.stop_recording_on_voice_deactivity = False
            self.recorder.start()
            self.recording_id = self.recorder.realtime_recording_id

    def audio(self, turn_id, sequence, pcm):
        with self.lock:
            if turn_id != self.turn:
                raise RuntimeError("stale_segment")
            if type(sequence) is not int or self.finalizing or sequence != self.sequence + 1 or not pcm or len(pcm)%2 or len(pcm)>32768:
                raise RuntimeError("malformed_audio")
            if self.audio_bytes + len(pcm) > self.sample_rate * 2 * 60:
                raise RuntimeError("utterance_limit")
            # RealtimeSTT's manual byte path assumes its native 16 kHz rate and
            # ignores ``original_sample_rate``. Passing the original signed-16
            # array uses its documented ndarray path, which resamples 44.1/48 kHz
            # browser PCM to the recorder's 16 kHz input without altering level.
            samples = self.np.frombuffer(pcm, dtype="<i2")
            levels = samples.astype(self.np.float32)
            rms = math.sqrt(float(self.np.mean(levels * levels)))
            self.heard_signal = self.heard_signal or rms >= 100
            self.recorder.feed_audio(samples, original_sample_rate=self.sample_rate)
            # Each acknowledged chunk has reached native recording memory, not an unbounded input queue.
            self.recorder.flush_audio_input()
            if not self.recorder.drain_audio_input(timeout=1):
                raise RuntimeError("backpressure")
            self.sequence = sequence
            self.audio_bytes += len(pcm)
            return {
                "input_frames": len(samples),
                "native_frames": int(len(samples) * 16000 / self.sample_rate),
            }

    def finalize(self, turn_id):
        with self.lock:
            if turn_id != self.turn or self.finalizing:
                raise RuntimeError("invalid_transition")
            self.finalizing = True
            self.final_done.clear()
            session = self.session
        def finish():
            try:
                self.recorder.flush_audio_input()
                if not self.recorder.drain_audio_input(timeout=1):
                    raise RuntimeError("backpressure")
                has_audio = self._stop_recording()
                text = self.recorder.transcribe() if self.heard_signal and has_audio else ""
                with self.lock:
                    valid = self.turn == turn_id and self.session == session
                    self.turn = None
                    self.recording_id = None
                    self.finalizing = False
                    self._wipe()
                    self.final_done.set()
                    if valid:
                        self.emit(session, turn_id, "final" if text and text.strip() else "no_speech", text or "")
            except Exception:
                with self.lock:
                    valid = self.turn == turn_id and self.session == session
                    self.turn = None
                    self.recording_id = None
                    self.finalizing = False
                    self.final_done.set()
                    if valid:
                        self.emit(session, turn_id, "error", "", "communication_failed")
        threading.Thread(target=finish, name="voice-final", daemon=True).start()

    def cancel(self, turn_id):
        with self.lock:
            if self.turn != turn_id:
                raise RuntimeError("stale_segment")
            was_finalizing = self.finalizing
            self.turn = None
            self.recording_id = None
        if was_finalizing:
            if not self.final_done.wait(4):
                raise RuntimeError("cleanup_pending")
        else:
            self.recorder.flush_audio_input()
            if not self.recorder.drain_audio_input(timeout=1):
                raise RuntimeError("backpressure")
            self._stop_recording()
        with self.lock:
            self.finalizing = False
            self._wipe()

    def _stop_recording(self):
        self.recorder.stop()  # native reusable end, never shutdown
        with getattr(self.recorder, "frames_lock", nullcontext()):
            has_audio = bool(getattr(self.recorder, "last_frames", None))
        # Native wait_audio arms automatic listening if stop queued no frames.
        # An immediate empty release must acknowledge no-speech, never re-arm.
        if has_audio:
            self.recorder.wait_audio()
        return has_audio

    def close(self):
        with self.lock:
            turn = self.turn
        if turn:
            self.cancel(turn)
        with self.lock:
            self.session = None
            self._wipe()

    def _wipe(self):
        # RealtimeSTT retains last-audio/text convenience fields; clear them per turn.
        self.recorder.clear_audio_queue()
        recorded = getattr(self.recorder, "recorded_audio_queue", None)
        if recorded is not None:
            while True:
                try:
                    recorded.get_nowait()
                except queue.Empty:
                    break
        with getattr(self.recorder, "frames_lock", nullcontext()):
            for name in ("frames", "last_frames", "text_storage", "active_speech_tail_buffer"):
                value = getattr(self.recorder, name, None)
                if value is not None:
                    value.clear()
        for name in ("audio", "last_transcription_bytes", "_current_transcription_tail_audio"):
            setattr(self.recorder, name, self.np.zeros(0, dtype=self.np.float32))
        self.recorder.last_transcription_metadata = None
        for name in ("last_transcription_bytes_b64", "realtime_transcription_text",
                     "realtime_stabilized_text", "realtime_stabilized_safetext",
                     "_current_transcription_live_text"):
            setattr(self.recorder, name, "")

    def shutdown(self):
        self.close()
        self.recorder.shutdown()
        self.scheduler.close()
