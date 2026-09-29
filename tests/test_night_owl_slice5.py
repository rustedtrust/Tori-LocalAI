"""Night Owl V1 Slice 5 application and review boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.capability_growth import SQLiteImprovementJournal
from tori.night_owl import (
    NightOwlConflictError,
    NightOwlValidationError,
    SQLiteNightOwlStore,
)
from tori.night_owl_application import (
    NightOwlApplicationService,
    recognize_findings_request,
    recognize_run_request,
)
from tori.night_owl_research import (
    DiscoveryLead,
    InspectedProject,
    NightOwlResearchRunner,
)
from tori.night_owl_scheduling import (
    NightOwlScheduleService,
    night_owl_scheduled_definition,
)
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.scheduled_work_application import ScheduledWorkApplicationService


UTC = timezone.utc
NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


class _Discovery:
    def __init__(self, names=("tool",)):
        self.names = names
        self.calls = []

    def discover(self, plan, *, limit):  # type: ignore[no-untyped-def]
        self.calls.append(plan.identifier)
        return tuple(
            DiscoveryLead(name, f"https://github.com/example/{name}", "untrusted")
            for name in self.names[:limit]
        )


class _GitHub:
    def inspect(self, repository_url):  # type: ignore[no-untyped-def]
        name = repository_url.rsplit("/", 1)[-1]
        return InspectedProject(
            "example", name, f"example/{name}",
            "Local self-hosted LLM inference with an OpenAI-compatible API.",
            repository_url, 100, "main", "a" * 40, 1, "v1", False, False,
            "MIT", ("llm", "local-model"), "2026-09-17T00:00:00Z", 1000,
        )


class _ImmediateThread:
    def __init__(self, *, target, args, name, daemon):  # type: ignore[no-untyped-def]
        self._target = target
        self._args = args
        self._alive = False

    def start(self):
        self._alive = True
        try:
            self._target(*self._args)
        finally:
            self._alive = False

    def is_alive(self):
        return self._alive


class Slice5ApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SQLiteNightOwlStore(
            self.root / "night-owl.sqlite3", clock=lambda: NOW
        )
        self.discovery = _Discovery()
        self.runner = NightOwlResearchRunner(
            self.store, self.discovery, _GitHub()
        )
        self.journal = SQLiteImprovementJournal(
            self.root / "journal.sqlite3", clock=lambda: NOW
        )
        self.service = NightOwlApplicationService(
            self.store,
            self.runner,
            schedule=None,
            improvement_journal=self.journal,
            timezone_name="America/Chicago",
            thread_factory=_ImmediateThread,
        )

    def enable(self):
        return self.service.update_settings(
            expected_revision=0, enabled=True, categories=["local_models"]
        )

    def research(self):
        self.enable()
        return self.service.start_run()

    def test_absent_status_is_off_and_noncreating(self) -> None:
        state = self.service.state()
        self.assertFalse(state["enabled"])
        self.assertEqual(state["categories"], [])
        self.assertFalse(self.store.path.exists())

    def test_settings_are_explicit_revisioned_and_category_limited(self) -> None:
        state = self.enable()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["categories"], ["local_models"])
        first = self.store.active_grant()
        self.assertIsNotNone(first)
        with self.assertRaises(NightOwlConflictError):
            self.service.update_settings(
                expected_revision=0, enabled=True, categories=["voice"]
            )
        state = self.service.update_settings(
            expected_revision=state["revision"], enabled=True, categories=["voice"]
        )
        self.assertEqual(state["categories"], ["voice"])
        self.assertNotEqual(first.digest, self.store.active_grant().digest)  # type: ignore[union-attr]

    def test_security_settings_round_trip_and_explicit_deselection(self) -> None:
        initial = self.enable()
        selected = self.service.update_settings(
            expected_revision=initial["revision"], enabled=True,
            categories=["local_models", "security"],
        )
        self.assertEqual(selected["categories"], ["local_models", "security"])
        self.assertTrue(next(option for option in selected["category_options"]
                             if option["id"] == "security")["enabled"])
        saved = SQLiteNightOwlStore(self.store.path).settings()
        self.assertEqual(saved.categories, ("local_models", "security"))
        unchanged = self.service.update_settings(
            expected_revision=selected["revision"], enabled=True,
            categories=list(selected["categories"]),
        )
        self.assertEqual(unchanged["categories"], ["local_models", "security"])
        self.assertEqual(unchanged["revision"], selected["revision"])
        removed = self.service.update_settings(
            expected_revision=unchanged["revision"], enabled=True,
            categories=["local_models"],
        )
        self.assertEqual(removed["categories"], ["local_models"])
        self.assertFalse(next(option for option in removed["category_options"]
                              if option["id"] == "security")["enabled"])
        self.assertEqual(SQLiteNightOwlStore(self.store.path).settings().categories,
                         ("local_models",))

    def test_on_demand_run_uses_no_user_query_and_persists_attribution(self) -> None:
        state = self.research()
        self.assertEqual(
            self.discovery.calls,
            ["local_models_recent", "local_models_api", "local_models_updates"],
        )
        self.assertEqual(state["status"]["last_run_outcome"], "completed")
        details = state["runs"][0]["details"]
        self.assertEqual(details["aggregate"]["findings_changed"], 1)
        self.assertEqual(details["categories"]["local_models"]["searches_executed"], 3)
        self.assertNotIn("query", str(details).casefold())
        finding = state["findings"][0]
        self.assertEqual(finding["sources"][0]["url"], "https://github.com/example/tool")
        self.assertNotIn("material identity", finding["source_description"].casefold())
        self.assertIn("Local self-hosted LLM", finding["source_description"])
        self.assertIsNone(finding["analysis"])
        self.assertNotIn("install", finding)
        self.assertNotIn("execute", finding)

    def test_review_dismiss_and_conversation_read_stored_results_only(self) -> None:
        state = self.research()
        finding = state["findings"][0]
        before_calls = list(self.discovery.calls)
        summary = self.service.conversation_summary()
        self.assertIn("https://github.com/example/tool", summary)
        self.assertIn("did not start research", summary)
        self.assertEqual(self.discovery.calls, before_calls)
        reviewed = self.service.mark_finding(
            finding["id"], expected_revision=finding["revision"], action="reviewed"
        )
        self.assertEqual(reviewed["findings"][0]["state"], "reviewed")
        current = reviewed["findings"][0]
        dismissed = self.service.mark_finding(
            current["id"], expected_revision=current["revision"], action="dismissed"
        )
        self.assertEqual(dismissed["findings"], [])
        self.assertEqual(dismissed["status"]["reviewable_count"], 0)
        self.assertEqual(dismissed["status"]["unseen_count"], 0)
        self.assertEqual(dismissed["status"]["findings_count"], 1)
        self.assertEqual(self.service.state()["findings"], [])
        historical = self.store.get_finding_detail(current["id"])
        self.assertEqual(historical.state, "dismissed")
        with self.assertRaises(NightOwlConflictError):
            self.service.promote(
                current["id"], lane="expand", friction_finding_id=None
            )

    def test_explicit_expand_promotion_is_idempotent_and_never_fix(self) -> None:
        state = self.research()
        finding = state["findings"][0]
        promoted = self.service.promote(
            finding["id"], lane="expand", friction_finding_id=None
        )
        receipt = promoted["promotion"]
        self.assertEqual(receipt["lane"], "EXPAND")
        again = self.service.promote(
            finding["id"], lane="expand", friction_finding_id=None
        )
        self.assertEqual(again["promotion"]["recommendation_id"], receipt["recommendation_id"])
        self.assertEqual(len(self.journal.list_recommendations()), 1)
        with self.assertRaises(NightOwlValidationError):
            self.service.promote(
                finding["id"], lane="fix", friction_finding_id=None
            )

    def test_off_and_active_run_conflicts_fail_closed(self) -> None:
        with self.assertRaises(NightOwlConflictError):
            self.service.start_run()
        self.enable()
        grant = self.store.active_grant()
        active = self.store.create_run(trigger="manual", grant=grant)  # type: ignore[arg-type]
        self.store.transition_run(
            active.identifier, "running", expected_revision=active.revision
        )
        with self.assertRaises(NightOwlConflictError):
            self.service.start_run()

    def test_conversation_recognizer_is_bounded_and_not_a_search_parser(self) -> None:
        self.assertTrue(recognize_findings_request("What did Night Owl find?"))
        self.assertTrue(recognize_findings_request("Show me the latest Night Owl findings."))
        self.assertFalse(recognize_findings_request("Night Owl research this URL"))
        self.assertFalse(recognize_findings_request("Find arbitrary quantum news"))
        self.assertEqual(recognize_run_request("Run Night Owl now."), "run")
        self.assertEqual(
            recognize_run_request("Run Night Owl and research a custom URL"),
            "scope_rejected",
        )
        self.assertIsNone(recognize_run_request("Research arbitrary quantum news"))

    def test_stored_finding_detail_is_plain_english_and_never_researches(self) -> None:
        self.research()
        before_calls = list(self.discovery.calls)
        detail = self.service.conversation_finding_detail(
            "Tell me more about example/tool."
        )
        assert detail is not None
        self.assertIn("Source-derived facts", detail)
        self.assertIn("https://github.com/example/tool", detail)
        self.assertIn("no new research", detail)
        self.assertEqual(self.discovery.calls, before_calls)
        numbered = self.service.conversation_finding_detail(
            "Tell me more about: 5. example/tool"
        )
        self.assertIn("Source-derived facts", numbered or "")
        natural = self.service.conversation_finding_detail(
            "Tell me about the example tool finding."
        )
        self.assertIn("Source-derived facts", natural or "")
        ambiguous = self.service.conversation_finding_detail(
            "Tell me more about the finding."
        )
        self.assertIsNone(ambiguous)

    def test_legacy_summary_has_safe_read_time_fallback_and_withdrawn_is_hidden(self) -> None:
        state = self.research()
        finding = state["findings"][0]
        with self.store._connect(False) as connection:  # test-only legacy fixture
            connection.execute(
                "UPDATE night_owl_findings SET summary=? WHERE id=?",
                ("Public GitHub project with material identity github-repository:123.", finding["id"]),
            )
        refreshed = self.service.state()
        self.assertNotIn("material identity", refreshed["findings"][0]["source_description"].casefold())
        detail = self.store.get_finding_detail(finding["id"])
        self.store.withdraw_finding(detail.category, detail.source_identity, "github_project")
        hidden = self.service.state()
        self.assertEqual(hidden["findings"], [])
        self.assertEqual(hidden["status"]["findings_count"], 1)

    def test_nightly_weekly_pause_resume_and_cancel_use_scheduled_work(self) -> None:
        self.enable()
        scheduled_store = SQLiteScheduledWorkStore(
            self.root / "scheduled.sqlite3", clock=lambda: NOW
        )
        scheduled_store.initialize()
        definition = night_owl_scheduled_definition(self.store, self.runner)
        schedule = NightOwlScheduleService(
            ScheduledWorkApplicationService(scheduled_store),
            self.store,
            definition,
            lambda: NOW.date(),
        )
        service = NightOwlApplicationService(
            self.store,
            self.runner,
            schedule=schedule,
            improvement_journal=self.journal,
            timezone_name="America/Chicago",
            thread_factory=_ImmediateThread,
        )
        nightly = service.update_schedule(
            mode="nightly", local_time_text="02:00", weekday=6
        )
        self.assertEqual(nightly["schedule"]["mode"], "nightly")
        definition_record = scheduled_store.list_definitions()[0]
        self.assertEqual(definition_record.missed_policy, "skip_if_missed")
        weekly = service.update_schedule(
            mode="weekly", local_time_text="03:15", weekday=2
        )
        self.assertEqual(weekly["schedule"]["mode"], "weekly")
        self.assertEqual(weekly["schedule"]["weekday"], 2)
        self.assertEqual(service.schedule_action("pause")["schedule"]["status"], "paused")
        self.assertEqual(service.schedule_action("resume")["schedule"]["status"], "active")
        disabled = service.schedule_action("cancel")
        self.assertEqual(disabled["schedule"]["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
