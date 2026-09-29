from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.search import MAX_SEARCH_QUERY_LENGTH, SearchConsent
from tori.search_application import SearchApplicationPolicy
from tori.user_settings import CapabilitySettingsController, SQLiteUserSettingsStore


class SearchApplicationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = 100.0
        self.available = True
        self.settings = CapabilitySettingsController(
            administrator_web_search=True,
            administrator_speech_output=False,
            store=SQLiteUserSettingsStore(
                Path(self.temporary.name) / "settings.db"
            ),
        )
        self.policy = SearchApplicationPolicy(
            SearchConsent(clock=lambda: self.now),
            implementation_available=lambda: self.available,
            capability_settings=self.settings,
        )

    def test_ordinary_explicit_bare_and_invalid_requests(self) -> None:
        self.assertEqual(
            self.policy.evaluate("Explain binary search", conversation_id="chat-a").disposition,
            "normal",
        )
        explicit = self.policy.evaluate(
            "Search the web for current release notes", conversation_id="chat-a"
        )
        self.assertEqual(
            (explicit.disposition, explicit.query, explicit.source),
            ("authorized", "current release notes", "explicit"),
        )
        bare = self.policy.evaluate("Search the web", conversation_id="chat-a")
        self.assertEqual((bare.disposition, bare.source), ("clarification", "bare"))
        with self.assertRaises(ValueError):
            self.policy.evaluate("/search", conversation_id="chat-a")
        with self.assertRaises(ValueError):
            self.policy.evaluate(
                "/search " + "x" * (MAX_SEARCH_QUERY_LENGTH + 1),
                conversation_id="chat-a",
            )

    def test_freshness_consent_decline_and_one_use(self) -> None:
        request = "What is the latest product price?"
        proposal = self.policy.evaluate(request, conversation_id="chat-a")
        self.assertEqual((proposal.disposition, proposal.source), ("proposal", "freshness"))
        authorized = self.policy.evaluate("Yes, search it", conversation_id="chat-a")
        self.assertEqual(
            (authorized.disposition, authorized.query, authorized.source),
            ("authorized", request, "consent"),
        )
        self.assertEqual(
            self.policy.evaluate("Yes, search it", conversation_id="chat-a").disposition,
            "normal",
        )
        self.policy.evaluate(request, conversation_id="chat-a")
        declined = self.policy.evaluate("No thanks", conversation_id="chat-a")
        self.assertEqual((declined.disposition, declined.source), ("declined", "consent"))

    def test_unrelated_wrong_conversation_and_expired_responses_consume_consent(self) -> None:
        request = "What is the current release version?"
        self.policy.evaluate(request, conversation_id="chat-a")
        self.assertEqual(
            self.policy.evaluate("Tell me a poem", conversation_id="chat-a").disposition,
            "normal",
        )
        self.assertEqual(
            self.policy.evaluate("yes", conversation_id="chat-a").disposition,
            "normal",
        )
        self.policy.evaluate(request, conversation_id="chat-a")
        self.assertEqual(
            self.policy.evaluate("yes", conversation_id="chat-b").disposition,
            "normal",
        )
        self.policy.evaluate(request, conversation_id="chat-a")
        self.now += 301
        self.assertEqual(
            self.policy.evaluate("yes", conversation_id="chat-a").disposition,
            "normal",
        )

    def test_clear_invalidates_pending_consent(self) -> None:
        self.policy.evaluate("What is today's weather?", conversation_id="chat-a")
        self.policy.clear()
        self.assertEqual(
            self.policy.evaluate("yes", conversation_id="chat-a").disposition,
            "normal",
        )

    def test_locationless_weather_clarifies_without_creating_or_resuming_consent(self) -> None:
        decision = self.policy.evaluate(
            "Can you tell me the weather for tonight?", conversation_id="chat-a"
        )
        self.assertEqual(
            (decision.disposition, decision.source),
            ("weather_location_clarification", "freshness"),
        )
        self.assertEqual(
            self.policy.evaluate("yes", conversation_id="chat-a").disposition,
            "normal",
        )

    def test_location_reply_restores_freshness_consent_without_authorizing_search(self) -> None:
        initial = self.policy.evaluate(
            "Can you tell me the weather for tonight?", conversation_id="chat-a"
        )
        self.assertEqual(initial.disposition, "weather_location_clarification")
        location = self.policy.evaluate("Exampleville, IL", conversation_id="chat-a")
        self.assertEqual(
            (location.disposition, location.source), ("proposal", "freshness")
        )
        authorized = self.policy.evaluate("Yes, please", conversation_id="chat-a")
        self.assertEqual(
            (authorized.disposition, authorized.source), ("authorized", "consent")
        )
        self.assertEqual(
            authorized.query,
            "Can you tell me the weather for tonight in Exampleville, IL",
        )

    def test_explicit_search_remains_authorized_after_missing_location_reply(self) -> None:
        initial = self.policy.evaluate(
            "/search weather for tonight", conversation_id="chat-a"
        )
        self.assertEqual(initial.disposition, "weather_location_clarification")
        completed = self.policy.evaluate("Exampleville, IL", conversation_id="chat-a")
        self.assertEqual(
            (completed.disposition, completed.source), ("authorized", "explicit")
        )
        self.assertEqual(completed.query, "weather for tonight in Exampleville, IL")

    def test_capability_unavailable_disabled_and_settings_failure(self) -> None:
        self.available = False
        unavailable = self.policy.evaluate(
            "/search current status", conversation_id="chat-a"
        )
        self.assertEqual(unavailable.disposition, "unavailable")
        self.available = True
        self.settings.set_web_search_enabled(False)
        disabled = self.policy.evaluate(
            "/search current status", conversation_id="chat-a"
        )
        self.assertEqual(disabled.disposition, "disabled")

        class BrokenSettings:
            def state(self):  # type: ignore[no-untyped-def]
                from tori.user_settings import UserSettingsError
                raise UserSettingsError("broken")

        broken = SearchApplicationPolicy(
            SearchConsent(clock=lambda: self.now),
            implementation_available=lambda: True,
            capability_settings=BrokenSettings(),  # type: ignore[arg-type]
        )
        self.assertEqual(
            broken.evaluate("/search current status", conversation_id=None).disposition,
            "settings_failure",
        )

    def test_external_advisory_proposes_without_authorizing_or_executing(self) -> None:
        calls = []
        policy = SearchApplicationPolicy(
            SearchConsent(clock=lambda: self.now),
            implementation_available=lambda: not calls,
            capability_settings=None,
        )
        proposal = policy.propose_external_knowledge(
            "An obscure question", conversation_id="chat-a"
        )
        self.assertEqual(
            (proposal.disposition, proposal.query, proposal.source),
            ("proposal", None, "external_knowledge"),
        )
        self.assertEqual(calls, [])
        confirmed = policy.evaluate("yes", conversation_id="chat-a")
        self.assertEqual(confirmed.query, "An obscure question")

    def test_external_advisory_obeys_gate_and_rejects_oversized_topic(self) -> None:
        self.settings.set_web_search_enabled(False)
        blocked = self.policy.propose_external_knowledge(
            "An obscure question", conversation_id="chat-a"
        )
        self.assertEqual(blocked.disposition, "disabled")
        self.settings.set_web_search_enabled(True)
        malformed = self.policy.propose_external_knowledge(
            "x" * (MAX_SEARCH_QUERY_LENGTH + 1), conversation_id="chat-a"
        )
        self.assertEqual(
            (malformed.disposition, malformed.source),
            ("clarification", "external_knowledge"),
        )

    def test_one_shot_evaluates_only_explicit_subset_without_pending_state(self) -> None:
        self.assertEqual(
            self.policy.evaluate_explicit("What is today's weather?").disposition,
            "normal",
        )
        direct = self.policy.evaluate_explicit("/search current weather")
        self.assertEqual(
            (direct.disposition, direct.query),
            ("weather_location_clarification", None),
        )


class SearchApplicationArchitectureTests(unittest.TestCase):
    def test_module_has_no_presentation_execution_or_unrelated_domain_dependency(self) -> None:
        path = Path(__file__).parents[1] / "src" / "tori" / "search_application.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden = {
            "http", "tori.web", "tori.providers", "tori.conversation_archive",
            "tori.memory_extraction", "tori.projects", "tori.tasks",
            "tori.scheduled_work", "tori.command_execution", "tori.tts",
        }
        self.assertTrue(imported.isdisjoint(forbidden), imported & forbidden)


if __name__ == "__main__":
    unittest.main()
