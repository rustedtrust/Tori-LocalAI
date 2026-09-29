"""Untrusted model evidence is bounded and never acts as command authority."""

from __future__ import annotations

import unittest

from tori.terminal_output import MAX_RESULT_BYTES, TerminalModelCapture


class TerminalOutputTests(unittest.TestCase):
    def test_ansi_osc_clipboard_controls_and_invalid_utf8_are_plain_text(self) -> None:
        capture = TerminalModelCapture()
        capture.feed(b"before\x1b[31mred\x1b[0m\x1b]0;secret title\x07", private=False)
        capture.feed(b"\x1b]52;c;clipboard\x1b\\\x1b]8;;https://bad.invalid\x1b\\link", private=False)
        capture.feed(b"\x1b]8;;\x1b\\\x00\x08\xff\rnext", private=False)
        output, truncated = capture.result()
        self.assertFalse(truncated)
        self.assertEqual(output, "beforeredlink�\nnext")
        for forbidden in ("secret title", "clipboard", "bad.invalid", "\x1b", "\x00"):
            self.assertNotIn(forbidden, output)

    def test_head_tail_limit_and_secret_redaction(self) -> None:
        capture = TerminalModelCapture()
        capture.feed(b"H" * 20_000 + b"M" * 100_000 + b"T" * 60_000, private=False)
        output, truncated = capture.result()
        self.assertTrue(truncated)
        self.assertLessEqual(len(output.encode()), MAX_RESULT_BYTES)
        self.assertTrue(output.startswith("H" * 16_000))
        self.assertIn("terminal output omitted", output)
        self.assertTrue(output.endswith("T" * 47_000))
        self.assertNotIn("M" * 100, output)
        secret = TerminalModelCapture()
        secret.feed(b"API_KEY=synthetic-token\n", private=False)
        self.assertEqual(secret.result()[0], "API_KEY=[redacted]\n")

    def test_private_activation_permanently_locks_model_capture(self) -> None:
        capture = TerminalModelCapture()
        capture.feed(b"before\n", private=False)
        capture.begin_private()
        capture.feed(b"UNIQUE_FAKE_SECRET_947326\n", private=True)
        capture.end_private()
        capture.feed(b"after UNIQUE_FAKE_SECRET_947326\n", private=False)
        capture.begin_private()
        capture.end_private()
        capture.feed(b"even later\n", private=False)
        output, _ = capture.result()
        self.assertIn("before", output)
        self.assertNotIn("after", output)
        self.assertNotIn("even later", output)
        self.assertIn("[private terminal activity and subsequent output withheld]", output)
        self.assertNotIn("UNIQUE_FAKE_SECRET_947326", output)
        self.assertEqual(capture.private_intervals, 2)
        self.assertTrue(capture.model_capture_locked)
        fresh = TerminalModelCapture()
        fresh.feed(b"new process\n", private=False)
        self.assertEqual(fresh.result()[0], "new process\n")


if __name__ == "__main__":
    unittest.main()
