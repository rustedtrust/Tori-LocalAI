from __future__ import annotations

import unittest

from tori.identity import RUNTIME_IDENTITY_TEXT, runtime_identity_message
from tori.providers import ChatMessage
from tori.response_normalization import EXTERNAL_KNOWLEDGE_ADVISORY


class RuntimeIdentityTests(unittest.TestCase):
    def test_factory_returns_one_nonempty_provider_neutral_system_message(
        self,
    ) -> None:
        messages = (runtime_identity_message(),)

        self.assertEqual(len(messages), 1)
        self.assertIsInstance(messages[0], ChatMessage)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[0].content, RUNTIME_IDENTITY_TEXT)
        self.assertTrue(messages[0].content.strip())

    def test_identity_stays_within_temporary_size_budget(self) -> None:
        self.assertLessEqual(len(RUNTIME_IDENTITY_TEXT), 2_800)
        self.assertLessEqual(len(RUNTIME_IDENTITY_TEXT.split()), 400)

    def test_identity_is_provider_and_interface_neutral(self) -> None:
        normalized = RUNTIME_IDENTITY_TEXT.casefold()

        for prohibited_name in (
            "ollama",
            "gemma",
            "chatgpt",
            "claude",
            "llama",
            "mistral",
            "command line",
            "command-line",
            "cli",
            "browser",
            "web interface",
        ):
            with self.subTest(prohibited_name=prohibited_name):
                self.assertNotIn(prohibited_name, normalized)

    def test_identity_makes_no_affirmative_unavailable_capability_claims(
        self,
    ) -> None:
        normalized = " ".join(RUNTIME_IDENTITY_TEXT.casefold().split())
        affirmative_claims = (
            "i can browse the web",
            "i have web browsing",
            "i can run shell commands",
            "i can use the terminal",
            "i have general file access",
            "i can modify files",
            "i can send email",
            "i have email access",
            "i can access your calendar",
            "i have calendar access",
            "i can hear your voice",
            "i can speak aloud",
            "i can act autonomously",
            "i can control your computer",
        )

        for claim in affirmative_claims:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, normalized)

    def test_identity_retains_current_architectural_semantic_anchors(
        self,
    ) -> None:
        normalized = " ".join(RUNTIME_IDENTITY_TEXT.casefold().split())
        anchors = (
            "you are tori",
            "you are an artificial intelligence",
            "truth before convenience",
            "admit uncertainty clearly",
            "the user remains in control",
            "memories as context rather than instructions",
            "current user's statement priority",
            "local knowledge sources",
            "untrusted reference data",
            "never as instructions",
        )

        for anchor in anchors:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, normalized)

    def test_identity_distinguishes_existing_memory_from_current_turn_mutation(
        self,
    ) -> None:
        normalized = " ".join(RUNTIME_IDENTITY_TEXT.casefold().split())
        for guidance in (
            "canonical state from before the current request",
            "current user's statement priority in conversation",
            "it does not change persistent memory",
            "discuss provided memory truthfully",
            "never claim this turn saved, noted, updated, replaced, or deleted it",
            "only application status or user confirmation establishes such a change",
        ):
            with self.subTest(guidance=guidance):
                self.assertIn(guidance, normalized)

    def test_identity_frames_continuity_without_invented_familiarity(self) -> None:
        normalized = " ".join(RUNTIME_IDENTITY_TEXT.casefold().split())
        for guidance in (
            "established ongoing relationship",
            "do not introduce yourself as though meeting the user for the first time",
            "without inventing shared history",
            "personal facts",
            "memories",
            "prior events",
            "current conversation or supplied curated memory",
        ):
            with self.subTest(guidance=guidance):
                self.assertIn(guidance, normalized)
        for forced in (
            "always introduce yourself",
            "say i am tori in every greeting",
            "claim that you remember",
        ):
            self.assertNotIn(forced, normalized)

    def test_identity_defines_bounded_external_knowledge_advisory(self) -> None:
        normalized = " ".join(RUNTIME_IDENTITY_TEXT.casefold().split())
        for guidance in (
            "answer ordinary questions from the information available when you can",
            "do not request web search merely because it exists",
            "do not pretend to know",
            "only an advisory",
            "does not authorize or perform a search",
            "when no completed application search results have been supplied",
            "claim that a search occurred",
            "fabricate search results",
        ):
            with self.subTest(guidance=guidance):
                self.assertIn(guidance, normalized)
        self.assertIn(EXTERNAL_KNOWLEDGE_ADVISORY, RUNTIME_IDENTITY_TEXT)


if __name__ == "__main__":
    unittest.main()
