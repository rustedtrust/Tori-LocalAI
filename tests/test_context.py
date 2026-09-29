from __future__ import annotations

import unittest

from tori.context import (
    ESTIMATOR_VERSION,
    ContextPlanningError,
    ContextPolicy,
    context_budget_presets,
    estimate_text_tokens,
    plan_context,
    reply_reserve,
    uncertainty_reserve,
)
from tori.providers import ChatMessage


class ContextPlannerTests(unittest.TestCase):
    def test_policy_and_reserves_are_deterministic(self) -> None:
        self.assertEqual(ContextPolicy.parse("auto").canonical, "auto")
        self.assertEqual(ContextPolicy.parse("fixed:16384").token_budget, 16384)
        self.assertEqual(reply_reserve(16384), 2048)
        self.assertEqual(reply_reserve(65536), 8192)
        self.assertEqual(uncertainty_reserve(16384), 1639)
        with self.assertRaises(ValueError):
            ContextPolicy.parse("fixed:2048")
        self.assertEqual(
            context_budget_presets(None),
            (4096, 8192, 16384, 32768, 65536, 131072),
        )
        self.assertEqual(context_budget_presets(12288), (4096, 8192, 12288))

    def test_estimator_fixtures_are_conservative_and_shape_sensitive(self) -> None:
        fixtures = {
            "english": "This is ordinary conversational prose with several familiar words.",
            "code": "def f(value: str) -> dict[str, int]: return {value: len(value)}",
            "json": '{"identifier":"abc-123","enabled":true,"items":[1,2,3]}',
            "hash": "9870e3d0e8f986ad74caeeaf779a0e50a2b25638",
            "punctuation": "!@#$%^&*()_+-=[]{};':\",./<>?",
            "unicode": "こんにちは世界 Привет мир مرحبا بالعالم",
        }
        estimates = {name: estimate_text_tokens(text) for name, text in fixtures.items()}
        self.assertTrue(all(value > 0 for value in estimates.values()))
        self.assertGreater(estimates["punctuation"], 20)
        self.assertGreaterEqual(estimates["hash"], 14)
        self.assertGreaterEqual(estimates["unicode"], 20)
        self.assertEqual(ESTIMATOR_VERSION, "lexical-v1")

    def test_trims_whole_oldest_exchanges_and_larger_budget_restores_them(self) -> None:
        history = tuple(
            message
            for index in range(8)
            for message in (
                ChatMessage("user", f"old-{index} " + "word " * 250),
                ChatMessage("assistant", f"answer-{index} " + "word " * 250),
            )
        )
        common = dict(
            model_capacity=None,
            mandatory_prefix=(ChatMessage("system", "identity"),),
            mandatory_suffix=(ChatMessage("system", "required time and search context"),),
            optional_context=(ChatMessage("system", "optional memory"),),
            history=history,
            current_user=ChatMessage("user", "current request"),
        )
        small = plan_context(policy=ContextPolicy.fixed(4096), **common)
        large = plan_context(policy=ContextPolicy.fixed(16384), **common)
        self.assertEqual(small.telemetry.included_history_messages % 2, 0)
        self.assertGreater(small.telemetry.omitted_history_messages, 0)
        self.assertGreater(large.telemetry.included_history_messages, small.telemetry.included_history_messages)
        self.assertEqual(small.messages[0].content, "identity")
        self.assertTrue(any("required time" in item.content for item in small.messages))
        self.assertEqual(small.messages[-1].content, "current request")

    def test_capacity_and_mandatory_overflow_fail_before_contact(self) -> None:
        with self.assertRaisesRegex(ContextPlanningError, "known model capacity"):
            plan_context(
                policy=ContextPolicy.fixed(16384), model_capacity=8192,
                mandatory_prefix=(ChatMessage("system", "identity"),),
                optional_context=(), history=(), current_user=ChatMessage("user", "request"),
            )
        with self.assertRaisesRegex(ContextPlanningError, "Required current-turn"):
            plan_context(
                policy=ContextPolicy.fixed(4096), model_capacity=None,
                mandatory_prefix=(ChatMessage("system", "x " * 8000),),
                optional_context=(), history=(), current_user=ChatMessage("user", "request"),
            )


if __name__ == "__main__":
    unittest.main()
