from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest

from tori.realtimestt_adapter import PROFILE

spec = importlib.util.spec_from_file_location(
    "private_voice_wire_under_test", Path(__file__).resolve().parents[1] / "deploy/voice/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class VoiceInputRuntimeWireTests(unittest.TestCase):
    def test_private_runtime_requirements_pin_only_required_recognition_extras(self):
        requirements = (Path(__file__).resolve().parents[1] / "deploy/voice/requirements.txt")
        self.assertEqual(requirements.read_text(encoding="utf-8").splitlines(), [
            "# Provision separately into deploy/voice/.venv; never installed by enable/start.",
            "# These packages do not enter Tori's main environment or requirements.txt.",
            "RealtimeSTT[faster-whisper,silero-onnx-cpu]==1.1.2",
            "websockets==16.0",
        ])

    def test_profile_matches_adapter(self):
        self.assertEqual(runtime.PROFILE, PROFILE)

    def test_auth_requires_secret_epoch_and_exact_shape(self):
        data = {"epoch": "current", "secret": "secret"}
        self.assertTrue(runtime.authenticated_bootstrap(data, data))
        for auth in (None, [], {}, {"epoch": "old", "secret": "secret"},
                     {"epoch": "current", "secret": "wrong"},
                     {"epoch": "current", "secret": "é"},
                     {"epoch": "current", "secret": "secret", "extra": True}):
            self.assertFalse(runtime.authenticated_bootstrap(data, auth))

    def test_framing_rejects_oversize_unterminated_nonobject(self):
        for raw in (b"[]\n", b"{" + b" " * 65536, b"{}", b"bad\n"):
            with self.assertRaises((RuntimeError, ValueError)):
                runtime.read_frame(io.BytesIO(raw))
        with self.assertRaises(RuntimeError):
            runtime.frame({"data": "x" * 65536})
        self.assertEqual(runtime.read_frame(io.BytesIO(b'{}\n')), {})

    def test_private_commands_are_not_public_upstream_stop(self):
        calls = []
        fake = SimpleNamespace(session="session", finalize=lambda turn: calls.append(turn))
        base = {"epoch": "epoch", "id": 1, "session_id": "session"}
        data = {"epoch": "epoch"}
        runtime.dispatch(fake, data, {**base, "command": "finalize", "utterance_id": "turn"})
        self.assertEqual(calls, ["turn"])
        for command in ("stop", "start", "clear", "anything"):
            with self.assertRaises(RuntimeError):
                runtime.dispatch(fake, data, {**base, "command": command})

    def test_stale_session_epoch_and_malformed_command_rejected(self):
        fake = SimpleNamespace(session="session", finalize=lambda _: self.fail("Must not finalize"))
        base = {"epoch": "epoch", "id": 1, "session_id": "session",
                "command": "finalize", "utterance_id": "turn"}
        for document in ([], {**base, "id": True}, {**base, "epoch": "old"},
                         {**base, "session_id": "old"}, {**base, "command": []},
                         {**base, "utterance_id": []}, {**base, "extra": True}):
            with self.assertRaises(RuntimeError):
                runtime.dispatch(fake, {"epoch": "epoch"}, document)
