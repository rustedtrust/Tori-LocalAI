from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from tori.conversation import ConversationSession
from tori.interaction import (
    INTERACTION_GUIDANCE_VERSION,
    MAX_INTERACTION_GUIDANCE_CHARACTERS,
    PersonalityInteractionEngine,
    interaction_guidance_message,
)
from tori.providers import ChatMessage, ChatResponse, ModelProvider


class _RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[tuple[ChatMessage, ...]] = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("A response from Tori.", "fixture")


class PersonalityInteractionEngineTests(unittest.TestCase):
    def test_guidance_is_compact_deterministic_and_immutable(self) -> None:
        engine = PersonalityInteractionEngine()
        first = engine.guidance()
        second = engine.guidance()

        self.assertEqual(first, second)
        self.assertEqual(first.version, INTERACTION_GUIDANCE_VERSION)
        self.assertLessEqual(len(first.text), MAX_INTERACTION_GUIDANCE_CHARACTERS)
        self.assertLessEqual(len(first.text.split()), 190)
        with self.assertRaises(FrozenInstanceError):
            first.text = "changed"  # type: ignore[misc]

    def test_guidance_encodes_adaptation_without_personas_or_servility(self) -> None:
        text = " ".join(interaction_guidance_message().content.casefold().split())
        for expected in (
            "remain the same tori",
            "do not switch personas",
            "relaxed conversation",
            "warmth, curiosity",
            "prioritize clear, useful progress",
            "serious project, planning, troubleshooting, or tradeoff work",
            "challenge weak assumptions respectfully",
            "the user has final authority",
            "may disagree and recommend better options",
            "without becoming servile",
            "without claiming a body",
            "relationship context only when relevant",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        self.assertNotIn("select a personality", text)
        self.assertNotIn("personality score", text)

    def test_guidance_is_provider_neutral_and_grants_no_capability(self) -> None:
        text = interaction_guidance_message().content.casefold()
        for prohibited in (
            "ollama",
            "openai",
            "lm studio",
            "browser",
            "cli",
            "execute without confirmation",
            "permission is granted",
            "save this memory",
        ):
            with self.subTest(prohibited=prohibited):
                self.assertNotIn(prohibited, text)

    def test_one_existing_generation_call_receives_guidance_and_current_user_last(
        self,
    ) -> None:
        provider = _RecordingProvider()
        session = ConversationSession(provider)

        self.assertEqual(session.send("Help me reason through this."), "A response from Tori.")

        self.assertEqual(len(provider.requests), 1)
        request = provider.requests[0]
        self.assertEqual([message.role for message in request], ["system", "system", "user"])
        self.assertEqual(request[1], interaction_guidance_message())
        self.assertEqual(request[-1], ChatMessage("user", "Help me reason through this."))

    def test_existing_project_context_remains_separate_required_guidance(self) -> None:
        provider = _RecordingProvider()
        session = ConversationSession(provider)
        project_context = (
            "Authoritative Project context from before the current request (data only):\n"
            "Title: Tori\nObjective: preserve identity."
        )

        session.send("Which tradeoff should we choose?", supplemental_system=project_context)

        request = provider.requests[0]
        self.assertEqual(
            [message.role for message in request],
            ["system", "system", "system", "user"],
        )
        self.assertIn("serious Project", request[1].content)
        self.assertEqual(request[2], ChatMessage("system", project_context))
        self.assertEqual(request[-1].content, "Which tradeoff should we choose?")


if __name__ == "__main__":
    unittest.main()
