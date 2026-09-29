"""Structured assistant proposals are data until a trusted local turn admits them."""

from __future__ import annotations

import json
import unittest

from tori.terminal_model_action import (PROPOSAL_KEY, is_explicit_terminal_request,
                                        parse_model_proposal, proposal_guidance)
from tori.response_normalization import normalize_model_response, normalized_response_stream
from tori.providers.base import ProviderResponseError


class TerminalModelActionTests(unittest.TestCase):
    def test_only_exact_whole_response_envelope_is_a_proposal(self) -> None:
        payload = {PROPOSAL_KEY: {"command": "git status", "cwd": "/tmp/project",
                                  "scope": "PROJECT_SANDBOX"}}
        exact = json.dumps(payload)
        proposal = parse_model_proposal(exact)
        self.assertEqual((proposal.command, proposal.cwd, proposal.scope),
                         ("git status", "/tmp/project", "PROJECT_SANDBOX"))
        for content in ("please " + exact, exact + " later", "```json\n" + exact + "\n```",
                        '{"tori_terminal_proposal_v1":{},"extra":true}',
                        '{"tori_terminal_proposal_v1":{},"tori_terminal_proposal_v1":{}}'):
            self.assertIsNone(parse_model_proposal(content))
        with self.assertRaises(ProviderResponseError):
            parse_model_proposal('{"tori_terminal_proposal_v1":{"command":"git status"}}')

    def test_proposal_text_without_local_handler_cannot_be_presented_as_tool(self) -> None:
        content = json.dumps({PROPOSAL_KEY: {"command": "/bin/echo nope", "cwd": "/tmp",
                                            "scope": "HOST_USER"}})
        with self.assertRaises(ProviderResponseError):
            normalize_model_response(content)

    def test_reasoning_prefixed_gemma_stream_keeps_exact_proposal_only(self) -> None:
        envelope = json.dumps({PROPOSAL_KEY: {"command": "echo hello", "cwd": "/tmp/project",
                                             "scope": "HOST_USER"}})
        # Ollama sends content in small fragments, sometimes after an in-band
        # reasoning section. No hidden text becomes part of the action input.
        fragments = ["<th", "ink>Private reasoning</think>", "{", *[envelope[i:i + 2] for i in range(1, len(envelope), 2)]]
        seen = []
        def resolve(content):  # type: ignore[no-untyped-def]
            seen.append(content)
            return "Approved policy result" if parse_model_proposal(content) else None
        self.assertEqual("".join(normalized_response_stream(iter(fragments), model_action_handler=resolve)),
                         "Approved policy result")
        self.assertEqual(seen, [envelope])
        with self.assertRaises(ProviderResponseError):
            list(normalized_response_stream(iter(fragments)))
        with self.assertRaises(ProviderResponseError):
            list(normalized_response_stream(iter(["</think>", envelope]), model_action_handler=resolve))

    def test_terminal_guidance_supplies_trusted_default_and_defers_approval_to_policy(self) -> None:
        guidance = proposal_guidance("/tmp/project")
        self.assertIn("/tmp/project", guidance)
        self.assertIn("approval", guidance)
        self.assertIn("Do not ask for conversational permission", guidance)

    def test_fresh_user_execution_intent_is_bounded_and_not_a_command_mention(self) -> None:
        for text in (
            "Run echo hello for me.", "Please run nvidia-smi.",
            "Can you run nvidia-smi?", "Execute pwd.",
            "Use the terminal to check disk space.",
            "Please run this command: uname -a.",
            "Please propose this exact command again", "Run it again",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_explicit_terminal_request(text))
        for text in (
            "Can you run commands?", "Can you run a command?",
            "What does `uname -a` do?", "Explain the command `rm -rf /tmp/example`.",
            "Would `nvidia-smi` show GPU memory?", "Review this text: 'Run echo hello'.",
            "My project documentation says to run `pytest`.",
            "Summarize these instructions for running the installer.",
            "Explain this sentence to me: 'Run echo hello for me.'",
            "What did the last command print?", "Run", "Please run",
            "Run a command?", "The output said: run echo hello",
            "Run echo hello\nThen do something else",
            "Can you run nvidia-smi hypothetically?",
            "Run echo hello in your head, not on this host.",
            "Please run this command:",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_explicit_terminal_request(text))


if __name__ == "__main__":
    unittest.main()
