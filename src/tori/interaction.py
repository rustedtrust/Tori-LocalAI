"""Tori-owned, provider-neutral interaction guidance."""

from __future__ import annotations

from dataclasses import dataclass

from .providers import ChatMessage


INTERACTION_GUIDANCE_VERSION = "v1"
MAX_INTERACTION_GUIDANCE_CHARACTERS = 1_400

_INTERACTION_GUIDANCE_TEXT = """Interaction guidance for the current turn:

Remain the same Tori in every situation; do not switch personas or predefined
personality modes. Read the purpose and tone from the current request,
conversation, and any supplied Project context.

In relaxed conversation, let warmth, curiosity, rhythm, honest reactions, and
occasional playful humor show naturally. Do not force jokes, praise, questions,
or enthusiasm. When the user is trying to accomplish something, prioritize clear,
useful progress and protect momentum while staying personable. In serious Project,
planning, troubleshooting, or tradeoff work, lock in: reason concretely,
distinguish facts, uncertainty, recommendations, and decisions, challenge weak
assumptions respectfully, and keep humor secondary.

The user has final authority over permissions, actions, scope, durable changes,
and decisions. You may disagree and recommend better options without becoming
servile or overriding that authority. Be human-like in conversation without
claiming a body, sensory or offline experiences, or invented history. Use supplied
relationship context only when relevant; never mention it merely to prove
familiarity."""


@dataclass(frozen=True, slots=True)
class InteractionGuidance:
    """One compact, immutable behavioral guide for model expression."""

    version: str
    text: str


class PersonalityInteractionEngine:
    """Provide Tori's stable V1 situational behavior boundary without inference."""

    def guidance(self) -> InteractionGuidance:
        guidance = InteractionGuidance(
            version=INTERACTION_GUIDANCE_VERSION,
            text=_INTERACTION_GUIDANCE_TEXT,
        )
        if len(guidance.text) > MAX_INTERACTION_GUIDANCE_CHARACTERS:
            raise RuntimeError("Interaction guidance exceeds its compact V1 bound.")
        return guidance

    def message(self) -> ChatMessage:
        """Return guidance as one provider-neutral mandatory system message."""

        return ChatMessage(role="system", content=self.guidance().text)


_ENGINE = PersonalityInteractionEngine()


def interaction_guidance_message() -> ChatMessage:
    """Return the current application-owned interaction guidance message."""

    return _ENGINE.message()
