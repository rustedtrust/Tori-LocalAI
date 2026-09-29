from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from tori.actions import ActionContractError
from tori.night_owl import DEFAULT_BUDGETS, NightOwlConflictError, NightOwlSettings, SQLiteNightOwlStore
from tori.night_owl_research import DiscoveryLead, InspectedProject, NightOwlResearchRunner
from tori.night_owl_scheduling import (
    BUDGET_POLICY_VERSION,
    NIGHT_OWL_ACTION_ID,
    NightOwlScheduleService,
    authorization_snapshot,
    night_owl_scheduled_definition,
)
from tori.scheduled_work import (
    ScheduledCapabilityCatalog,
    ScheduledWorkExecutor,
    ScheduledWorkValidationError,
    SQLiteScheduledWorkStore,
)
from tori.scheduled_work_application import ScheduledWorkApplicationService


UTC = timezone.utc


class Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value
    def advance(self, value): self.value += value
    def set(self, value): self.value = value


class Discovery:
    def __init__(self): self.calls = []
    def discover(self, plan, *, limit):
        self.calls.append((plan.identifier, limit))
        return (DiscoveryLead("Tool", "https://github.com/example/tool"),)


class GitHub:
    def __init__(self): self.calls = []
    def inspect(self, url):
        self.calls.append(url)
        return InspectedProject(
            "example", "tool", "Example/Tool", "Local self-hosted LLM runtime",
            "https://github.com/example/tool", 42, "main", None, 1, "v1",
            False, False, "MIT", ("llm", "local"),
            "2026-09-17T00:00:00Z", 100,
        )


class NightOwlSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.clock = Clock(datetime(2026, 8, 10, 12, tzinfo=UTC))
        root = Path(self.temp.name)
        self.night = SQLiteNightOwlStore(root / "night/state.db", clock=self.clock)
        self.night.save_settings(
            NightOwlSettings(
                enabled=True,
                categories=("local_models",),
                budgets=tuple(DEFAULT_BUDGETS.items()),
            ),
            expected_revision=0,
        )
        self.grant = self.night.active_grant()
        self.discovery, self.github = Discovery(), GitHub()
        self.runner = NightOwlResearchRunner(
            self.night, self.discovery, self.github,
            monotonic=lambda: self.clock.value.timestamp(),
        )
        self.definition = night_owl_scheduled_definition(self.night, self.runner)
        self.scheduled = SQLiteScheduledWorkStore(root / "scheduled/state.db", clock=self.clock)
        self.scheduled.initialize()
        self.application = ScheduledWorkApplicationService(self.scheduled)
        self.service = NightOwlScheduleService(
            self.application, self.night, self.definition,
            lambda: self.clock.value.date(),
        )
        self.catalog = ScheduledCapabilityCatalog((self.definition,))

    def create(self, mode="nightly", **values):
        return self.service.create(
            self.grant,
            mode=mode,
            timezone_name=values.pop("timezone_name", "America/Chicago"),
            confirmation_provenance="night_owl_settings",
            **values,
        )[0]

    def test_capability_is_recurring_only_and_snapshot_is_closed(self):
        self.assertEqual(self.definition.identifier, NIGHT_OWL_ACTION_ID)
        self.assertTrue(self.definition.scheduled_recurring_eligible)
        self.assertFalse(self.definition.scheduled_one_shot_eligible)
        self.assertFalse(self.definition.interactive_eligible)
        snapshot = authorization_snapshot(self.grant)
        self.catalog.validate(NIGHT_OWL_ACTION_ID, 1, snapshot, "recurring")
        for extra in ({"query": "anything"}, {"prompt": "research anything"}, {"url": "https://example.com"}):
            with self.assertRaises(ActionContractError):
                self.definition.validate_arguments({**snapshot, **extra})
        with self.assertRaises(ActionContractError):
            self.definition.validate_arguments({**snapshot, "category_digest": "0" * 64})

    def test_no_schedule_exists_until_explicit_nightly_or_weekly_creation(self):
        self.assertEqual(self.scheduled.list_definitions(), ())
        nightly = self.create()
        self.assertEqual(nightly.schedule_kind, "daily")
        self.assertEqual(nightly.schedule.local_time, "02:00:00")
        self.assertEqual(nightly.missed_policy, "skip_if_missed")
        with self.assertRaises(ScheduledWorkValidationError): self.create()

        other = SQLiteScheduledWorkStore(Path(self.temp.name) / "other/state.db", clock=self.clock)
        other.initialize()
        service = NightOwlScheduleService(
            ScheduledWorkApplicationService(other), self.night, self.definition,
            lambda: self.clock.value.date(),
        )
        weekly, _ = service.create(
            self.grant, mode="weekly", timezone_name="America/Chicago",
            confirmation_provenance="night_owl_settings",
        )
        self.assertEqual(weekly.schedule_kind, "weekly")
        self.assertEqual(weekly.schedule.weekdays, (6,))
        self.assertEqual(weekly.schedule.local_time, "02:00:00")

    def test_valid_occurrence_executes_and_links_bounded_result(self):
        job = self.create()
        due = datetime.fromisoformat(job.next_occurrence_utc.replace("Z", "+00:00"))
        self.clock.set(due)
        claimed = self.scheduled.claim_due(self.clock())[0]
        terminal = ScheduledWorkExecutor(self.scheduled, self.catalog).execute_next()
        self.assertEqual(terminal.status, "succeeded")
        self.assertEqual(terminal.result["night_owl_state"], "completed")
        night_run = self.night.get_run(terminal.result["night_owl_run_id"])
        self.assertEqual((night_run.trigger, night_run.state), ("scheduled", "completed"))
        self.assertEqual(night_run.identifier, terminal.identifier)
        self.assertEqual(claimed.authorization_id, terminal.authorization_id)

    def test_revoked_changed_or_policy_mismatched_authority_never_researches(self):
        job = self.create()
        current = self.night.settings()
        self.night.save_settings(
            replace(current, categories=("local_models", "voice")),
            expected_revision=current.revision,
        )
        self.clock.set(datetime.fromisoformat(job.next_occurrence_utc.replace("Z", "+00:00")))
        self.scheduled.claim_due(self.clock())
        terminal = ScheduledWorkExecutor(self.scheduled, self.catalog).execute_next()
        self.assertEqual(terminal.status, "failed")
        self.assertEqual(terminal.failure_code, "night_owl_authorization_stale")
        self.assertEqual(self.discovery.calls, [])

        snapshot = authorization_snapshot(self.night.active_grant())
        with self.assertRaises(ActionContractError):
            self.definition.validate_arguments({**snapshot, "source_policy_version": "future"})
        with self.assertRaises(ActionContractError):
            self.definition.validate_arguments({**snapshot, "budget_policy_version": "future"})

    def test_missed_startup_skips_without_catchup_and_advances(self):
        job = self.create()
        due = datetime.fromisoformat(job.next_occurrence_utc.replace("Z", "+00:00"))
        self.clock.set(due + timedelta(hours=10))
        recovered = self.scheduled.recover_startup(self.clock())
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].status, "skipped")
        self.assertEqual(recovered[0].failure_code, "missed_while_unavailable")
        self.assertGreater(self.scheduled.get_definition(job.identifier).next_occurrence_utc, recovered[0].scheduled_occurrence_utc)
        self.assertEqual(self.discovery.calls, [])

    def test_overlap_is_skipped_and_manual_conflict_remains_bounded(self):
        active = self.night.create_run(trigger="manual", grant=self.grant)
        active = self.night.transition_run(active.identifier, "running", expected_revision=active.revision)
        scheduled_result = self.runner.run_now(
            self.grant, trigger="scheduled", invocation_id="run-" + "a" * 32
        )
        self.assertEqual(scheduled_result.state, "skipped")
        self.assertEqual(scheduled_result.error_codes, ("already_running",))
        with self.assertRaises(NightOwlConflictError):
            self.runner.run_now(self.grant)

    def test_restart_marks_both_histories_interrupted_without_retry(self):
        job = self.create()
        self.clock.set(datetime.fromisoformat(job.next_occurrence_utc.replace("Z", "+00:00")))
        scheduled_run = self.scheduled.claim_due(self.clock())[0]
        scheduled_run = self.scheduled.start_run(scheduled_run.identifier)
        scheduled_run = self.scheduled.mark_work_started(
            scheduled_run.identifier, expected_revision=scheduled_run.revision
        )
        night_run = self.night.create_run(
            trigger="scheduled", grant=self.grant,
            invocation_id=scheduled_run.identifier,
        )
        night_run = self.night.transition_run(night_run.identifier, "running", expected_revision=night_run.revision)
        self.clock.advance(timedelta(minutes=1))
        self.night.recover_startup()
        self.scheduled.recover_startup(self.clock())
        self.assertEqual(self.night.get_run(night_run.identifier).state, "interrupted")
        self.assertEqual(self.scheduled.get_run(scheduled_run.identifier).status, "interrupted")
        self.assertEqual(night_run.identifier, scheduled_run.identifier)
        self.assertIsNone(self.scheduled.next_queued_run())
        self.assertEqual(self.discovery.calls, [])

    def test_graceful_interrupt_fences_external_work_and_is_truthful(self):
        self.runner.request_interrupt()
        result = self.runner.run_now(self.grant, trigger="scheduled")
        self.assertEqual(result.state, "interrupted")
        self.assertEqual(result.error_codes, ("night_owl_interrupted",))
        self.assertEqual(self.discovery.calls, [])

    def test_pause_resume_reauthorization_timezone_and_dst_use_scheduler_rules(self):
        job = self.create(mode="weekly", timezone_name="America/Chicago")
        paused = self.service.transition(job.identifier, expected_revision=job.revision, action="pause")
        self.night.save_settings(
            replace(self.night.settings(), categories=("local_models", "voice")),
            expected_revision=self.night.settings().revision,
        )
        with self.assertRaises(ScheduledWorkValidationError):
            self.service.transition(paused.identifier, expected_revision=paused.revision, action="resume")
        replaced, _ = self.service.replace(
            paused.identifier, expected_revision=paused.revision,
            grant=self.night.active_grant(), mode="weekly", timezone_name="America/New_York",
            local_time=time(3), weekday=0,
            confirmation_provenance="night_owl_settings",
        )
        self.assertEqual(replaced.timezone_name, "America/New_York")
        resumed = self.service.transition(replaced.identifier, expected_revision=replaced.revision, action="resume")
        self.assertEqual(resumed.status, "active")

        spring_store = SQLiteScheduledWorkStore(Path(self.temp.name) / "spring/state.db", clock=self.clock)
        spring_store.initialize()
        spring_service = NightOwlScheduleService(
            ScheduledWorkApplicationService(spring_store), self.night, self.definition,
            lambda: date(2026, 3, 8),
        )
        self.clock.set(datetime(2026, 3, 7, 12, tzinfo=UTC))
        spring, _ = spring_service.create(
            self.night.active_grant(), mode="nightly", timezone_name="America/Chicago",
            local_time=time(2, 30), confirmation_provenance="night_owl_settings",
        )
        self.assertEqual(spring.next_occurrence_utc, "2026-03-08T08:00:00Z")
        self.clock.set(datetime(2026, 3, 8, 8, tzinfo=UTC))
        skipped = spring_store.claim_due(self.clock())[0]
        self.assertEqual(skipped.failure_code, "dst_nonexistent_local_time")

    def test_definition_has_no_model_companion_or_delivery_authority(self):
        self.create()
        self.assertEqual(self.discovery.calls, [])
        self.assertEqual(self.github.calls, [])
        self.assertNotIn("prompt", authorization_snapshot(self.grant))
        self.assertNotIn("query", authorization_snapshot(self.grant))
        self.assertNotIn("url", authorization_snapshot(self.grant))

    def test_cancel_and_delete_use_existing_revision_safe_lifecycle(self):
        job = self.create()
        cancelled = self.service.transition(
            job.identifier, expected_revision=job.revision, action="cancel"
        )
        self.assertEqual(cancelled.status, "cancelled")
        self.service.delete(cancelled.identifier, expected_revision=cancelled.revision)
        self.assertEqual(self.scheduled.list_definitions(), ())


if __name__ == "__main__":
    unittest.main()
