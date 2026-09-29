from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from tori.config import ConfigError, load_settings
from tori.realtimestt_adapter import RealtimeSTTAdapter
from tori.speech_recognition import AudioFormat, RecognitionError
from tori.voice_input_runtime import VoiceRuntimeSettings


class VoiceInputAdapterTests(unittest.TestCase):
    def test_missing_process_metadata_still_reaps_owned_direct_child(self):
        with patch("tori.realtimestt_adapter._process_identity", return_value=None):
            with self.assertRaises(RecognitionError) as caught:
                self.start("identity_missing")
            self.assertEqual(caught.exception.code, "startup_failed")
            self.assertIsNone(self.adapter._process)

    def test_optional_vocabulary_symlink_and_symlink_bin_rejected(self):
        optional = self.models / "tiny.en" / "vocabulary.json"
        optional.symlink_to(self.environment / "pyvenv.cfg")
        with self.assertRaises(RecognitionError):
            self.settings.prerequisites()
        optional.unlink()
        binary = self.environment / "bin"
        binary.rename(self.environment / "real-bin")
        binary.symlink_to(self.environment / "real-bin")
        with self.assertRaises(RecognitionError):
            self.settings.prerequisites()

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = self.root / "env"
        self.models = self.root / "models"
        (self.environment / "bin").mkdir(parents=True)
        (self.environment / "pyvenv.cfg").write_text("Fixture only")
        (self.environment / "bin" / "python").symlink_to(sys.executable)
        self.models.mkdir()
        for model in ("tiny.en", "small.en"):
            (self.models / model).mkdir()
            for filename in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                (self.models / model / filename).write_bytes(b"fixture")
        (self.models / "silero_vad.onnx").write_bytes(b"fixture")
        for entry in self.root.rglob("*"):
            if not entry.is_symlink():
                entry.chmod(0o755 if entry.is_dir() else 0o644)
        self.settings = VoiceRuntimeSettings(self.environment, self.models,
                                            readiness_seconds=0.3, shutdown_seconds=0.3)
        self.adapter = RealtimeSTTAdapter(self.settings)
        self.addCleanup(self.adapter.stop)
        self.events = []
        self.condition = threading.Condition()

    def start(self, mode="normal"):
        popen = subprocess.Popen
        def fixture(argv, **kwargs):
            # Substitute only the child entry point under test; production has no
            # configurable shell/executable supplied by a browser or model.
            self.assertEqual(argv[-1], "--bridge")
            self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "1")
            self.assertNotIn("PYTHONPATH", kwargs["env"])
            return popen([sys.executable, "-B", str(Path(__file__).with_name("voice_runtime_fixture.py")), mode], **kwargs)
        with patch("tori.realtimestt_adapter.subprocess.Popen", side_effect=fixture):
            self.adapter.prepare()

    def receive(self, event):
        with self.condition:
            self.events.append(event)
            self.condition.notify_all()

    def wait_final(self, utterance):
        with self.condition:
            self.assertTrue(self.condition.wait_for(
                lambda: any(e.kind == "final" and e.utterance_id == utterance for e in self.events), 2))

    def test_ten_real_ipc_cycles_models_not_replaced(self):
        self.start()
        pid = self.adapter._process.pid
        self.adapter.open_session("session", self.receive)
        for number in range(10):
            turn = f"turn-{number}"
            self.adapter.begin_utterance(turn, AudioFormat(48000))
            self.adapter.feed_audio(turn, 1, b"\x00\x10" * 100)
            self.adapter.finalize_utterance(turn)
            self.wait_final(turn)
            self.assertEqual(self.adapter._process.pid, pid)
        self.assertEqual(len([e for e in self.events if e.kind == "partial"]), 10)
        self.assertEqual(len([e for e in self.events if e.kind == "final"]), 10)
        self.adapter.close_session()
        self.adapter.stop()
        self.assertEqual(self.adapter.health().state, "off")
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_cancel_and_close_are_nonterminal(self):
        self.start()
        self.adapter.open_session("session", self.receive)
        self.adapter.begin_utterance("old", AudioFormat(44100))
        self.adapter.cancel_utterance("old")
        self.adapter.begin_utterance("new", AudioFormat(48000))
        self.adapter.finalize_utterance("new")
        self.wait_final("new")
        self.adapter.close_session()
        self.adapter.open_session("second", self.receive)
        self.assertEqual(self.adapter.health().state, "ready")

    def test_missing_assets_fail_without_process_or_install(self):
        for model in ("tiny.en", "small.en"):
            for filename in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                with self.subTest(model=model, filename=filename):
                    asset = self.models / model / filename
                    asset.unlink()
                    try:
                        with patch("tori.realtimestt_adapter.subprocess.Popen") as spawn:
                            with self.assertRaises(RecognitionError) as caught:
                                self.adapter.prepare()
                            self.assertEqual(caught.exception.code, "runtime_unavailable")
                            spawn.assert_not_called()
                    finally:
                        asset.write_bytes(b"fixture")
                        asset.chmod(0o644)

    def test_official_style_snapshots_do_not_require_preprocessor_config(self):
        for model in ("tiny.en", "small.en"):
            with self.subTest(model=model):
                self.assertFalse((self.models / model / "preprocessor_config.json").exists())
        executable, model_root = self.settings.prerequisites()
        self.assertEqual(executable, self.environment / "bin" / "python")
        self.assertEqual(model_root, self.models)

    def test_symlink_and_mutable_assets_rejected(self):
        asset = self.models / "silero_vad.onnx"
        asset.chmod(0o666)
        with self.assertRaises(RecognitionError):
            self.settings.prerequisites()
        asset.unlink()
        asset.symlink_to(self.environment / "pyvenv.cfg")
        with self.assertRaises(RecognitionError):
            self.settings.prerequisites()

    def test_timeout_invalid_and_oversized_readiness_cleanup(self):
        for mode in ("timeout", "bad_ready", "oversize"):
            with self.subTest(mode=mode):
                with self.assertRaises(RecognitionError):
                    self.start(mode)
                self.assertIsNone(self.adapter._process)

    def test_unexpected_exit_reports_bounded_error(self):
        self.start("exit")
        self.adapter.open_session("session", self.receive)
        with self.assertRaises(RecognitionError):
            self.adapter.begin_utterance("turn", AudioFormat(48000))
        with self.condition:
            self.assertTrue(self.condition.wait_for(lambda: any(e.code == "runtime_exited" for e in self.events), 2))

    def test_owned_descendants_killed_unrelated_process_preserved(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            self.start("child")
            deadline = time.monotonic() + 1
            while len(self.adapter._members()) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            members = self.adapter._members()
            self.assertEqual(len(members), 2)
            self.adapter.stop()
            self.assertIsNone(unrelated.poll())
            self.assertIsNone(self.adapter._process)
        finally:
            unrelated.terminate()
            unrelated.wait(2)

    def test_stop_prepare_stop_new_incarnation(self):
        self.start()
        first = self.adapter._epoch
        self.adapter.stop()
        self.start()
        self.assertNotEqual(self.adapter._epoch, first)
        self.assertEqual(self.adapter.health().state, "ready")

    def test_typed_configuration_disabled_by_default_and_rejects_authority(self):
        path = self.root / "config.toml"
        self.assertFalse(load_settings(path, environ={}).voice_input.configured)
        for value in ('enabled = true', 'command = "pip install anything"', 'port = true',
                      'environment_root = "/workspaces/RealtimeSTT-PoC/.venv"',
                      'environment_root = "/workspaces/Tori/runtime/voice"'):
            path.write_text("[voice_input]\n" + value)
            with self.assertRaises(ConfigError):
                load_settings(path, environ={})
