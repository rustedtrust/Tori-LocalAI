from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.coding_work import (
    CodingWorkStaleRevisionError,
    SQLiteCodingWorkStore,
)
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_worker import (
    CodingWorkerError,
    CodingWorkerUnsupportedError,
    FakeCodingWorkerAdapter,
)
from tori.time_context import FakeClock


def identifier_factory():  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}

    def create(prefix: str) -> str:
        counts[prefix] = counts.get(prefix, 0) + 1
        return f"{prefix}-{counts[prefix]:032x}"

    return create


class CodingWorkApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.clock = FakeClock(datetime(2026, 8, 23, 12, tzinfo=timezone.utc))
        self.store = SQLiteCodingWorkStore(
            self.root / "state" / "coding-work.db",
            clock=self.clock,
            identifier_factory=identifier_factory(),
        )
        self.store.initialize()
        self.adapter = FakeCodingWorkerAdapter(clock=self.clock)
        correlations = iter(f"launch-{index}" for index in range(1, 20))
        self.application = CodingWorkApplicationService(
            self.store,
            self.adapter,
            project_exists=lambda value: value == "project-" + "a" * 32,
            correlation_factory=lambda: next(correlations),
        )

    def create_authorized(self):  # type: ignore[no-untyped-def]
        work = self.application.create_work(
            objective="Repair the focused tests",
            acceptance_criteria="The focused suite passes.",
            workspace_root=self.workspace,
            project_id="project-" + "a" * 32,
            origin_chat_id="chat-" + "b" * 32,
        )
        return self.application.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )

    def start(self):  # type: ignore[no-untyped-def]
        queued = self.create_authorized()
        return self.application.start(
            queued.identifier, expected_revision=queued.revision
        )

    def session_id(self, work) -> str:  # type: ignore[no-untyped-def]
        run = self.store.get_run(work.current_run_id)
        assert run.harness_session_id is not None
        return run.harness_session_id

    def test_start_attach_progress_duplicate_and_terminal_duplicate(self) -> None:
        running = self.start()
        self.assertEqual(running.state, "running")
        run = self.store.get_run(running.current_run_id)
        session_id = self.session_id(running)
        progress = self.adapter.progress(
            session_id,
            "Investigating focused tests",
            changed_paths=("src/tori/coding_work.py",),
            verification="not run",
            identifier="fake-progress-1",
        )
        self.adapter.duplicate_event(session_id, progress)
        progressed = self.application.observe(running.identifier)
        self.assertEqual(progressed.progress["summary"], "Investigating focused tests")
        self.assertEqual(
            [event.kind for event in self.store.events(running.identifier)].count("progress"),
            1,
        )
        terminal = self.adapter.complete(
            session_id,
            summary="Focused tests pass.",
            changed_paths=("src/tori/coding_work.py",),
            verification=({"command": "focused tests", "status": "passed"},),
            identifier="fake-terminal-1",
        )
        self.adapter.duplicate_event(session_id, terminal)
        completed = self.application.observe(running.identifier)
        repeated = self.application.observe(running.identifier)
        self.assertEqual(completed.state, "completed")
        self.assertEqual(repeated, completed)
        self.assertEqual(completed.result["summary"], "Focused tests pass.")
        self.assertEqual(self.store.get_run(run.identifier).last_event_sequence, terminal.sequence)
        self.assertEqual(
            [event.kind for event in self.store.events(running.identifier)].count("completed"),
            1,
        )

    def test_restart_reconciles_same_session_without_claiming_running_early(self) -> None:
        running = self.start()
        run_id = running.current_run_id
        changed = self.application.prepare_restart_reconciliation()
        self.assertEqual(changed[0].state, "reconciling")
        reopened = CodingWorkApplicationService(self.store, self.adapter)
        reconciled = reopened.reconcile(running.identifier)
        self.assertEqual(reconciled.state, "running")
        self.assertEqual(reconciled.current_run_id, run_id)
        self.assertEqual(
            self.store.get_run(run_id).harness_session_id,
            self.session_id(reconciled),
        )

    def test_restart_terminalizes_exact_legacy_model_turn_completion(self) -> None:
        running = self.start()
        session_id = self.session_id(running)
        self.adapter.progress(
            session_id,
            "OpenCode completed a bounded model turn.",
            changed_paths=(),
            verification="workspace_snapshot_observed",
        )
        self.adapter.wait(session_id, "model_turn_complete")
        waiting = self.application.observe(running.identifier)
        self.assertEqual(waiting.state, "waiting")

        self.application.prepare_restart_reconciliation()
        self.adapter.lose_session(session_id)
        restarted = CodingWorkApplicationService(self.store, self.adapter)
        completed = restarted.reconcile(waiting.identifier)

        self.assertEqual(completed.state, "completed")
        self.assertEqual(
            completed.result["summary"],
            "OpenCode completed a bounded model turn.",
        )
        self.assertEqual(
            completed.result["verification"][0]["source"],
            "durable_model_turn_complete",
        )
        self.assertEqual(
            [event.kind for event in self.store.events(waiting.identifier)].count("completed"),
            1,
        )

    def test_restart_with_missing_session_fails_truthfully(self) -> None:
        running = self.start()
        run_id = running.current_run_id
        self.adapter.lose_session(self.session_id(running))
        self.application.prepare_restart_reconciliation()
        failed = self.application.reconcile(running.identifier)
        self.assertEqual(failed.state, "failed")
        self.assertEqual(self.store.get_run(run_id).connection_state, "missing")
        self.assertEqual(self.store.get_run(run_id).failure_code, "session_missing")

    def test_restart_reattaches_same_still_starting_session_without_claiming_running(self) -> None:
        adapter = FakeCodingWorkerAdapter(auto_confirm_start=False, clock=self.clock)
        app = CodingWorkApplicationService(
            self.store, adapter, correlation_factory=lambda: "launch-still-starting"
        )
        work = app.create_work(objective="Start deliberately", workspace_root=self.workspace)
        queued = app.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        starting = app.start(queued.identifier, expected_revision=queued.revision)
        run_id = starting.current_run_id
        self.assertEqual(starting.state, "starting")
        app.prepare_restart_reconciliation()
        reconciled = CodingWorkApplicationService(self.store, adapter).reconcile(
            starting.identifier
        )
        self.assertEqual(reconciled.state, "starting")
        self.assertEqual(reconciled.current_run_id, run_id)
        self.assertEqual(self.store.get_run(run_id).connection_state, "starting")
        self.assertIsNotNone(self.store.get_run(run_id).harness_session_id)

    def test_distinct_stale_worker_event_is_rejected(self) -> None:
        running = self.start()
        run = self.store.get_run(running.current_run_id)
        with self.assertRaises(CodingWorkStaleRevisionError):
            self.store.update_progress(
                running.identifier,
                expected_revision=running.revision,
                run_id=run.identifier,
                adapter_event_id="stale-different-event",
                adapter_sequence=run.last_event_sequence,
                summary="stale",
            )

    def test_directive_retry_after_crash_and_duplicate_delivery(self) -> None:
        running = self.start()
        session_id = self.session_id(running)
        directive = self.application.submit_follow_up(
            running.identifier,
            expected_revision=running.revision,
            instruction="Run the focused tests again.",
            source_chat_id="chat-" + "c" * 32,
        )
        claimed = self.store.claim_directive(directive.identifier)
        run = self.store.get_run(claimed.run_id)
        binding = self.adapter.binding_for_session(session_id)
        receipt = self.adapter.submit_directive(binding, claimed)
        self.assertFalse(receipt.duplicate)
        reopened = CodingWorkApplicationService(self.store, self.adapter)
        delivered = reopened.deliver_directives(running.identifier)
        self.assertEqual(delivered[0].status, "delivered")
        self.assertEqual(
            self.adapter.delivered_directive_ids(session_id), (directive.identifier,)
        )
        self.assertEqual(reopened.deliver_directives(running.identifier), ())

    def test_cancellation_while_running_and_during_starting(self) -> None:
        running = self.start()
        cancellation = self.application.request_cancellation(
            running.identifier, expected_revision=running.revision
        )
        self.assertEqual(self.store.get_work(running.identifier).state, "cancelling")
        self.application.deliver_directives(running.identifier)
        cancelled = self.application.observe(running.identifier)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(self.store.get_directive(cancellation.identifier).status, "delivered")

        delayed_adapter = FakeCodingWorkerAdapter(
            auto_confirm_start=False, clock=self.clock
        )
        starting_app = CodingWorkApplicationService(
            self.store,
            delayed_adapter,
            correlation_factory=lambda: "launch-starting-cancel",
        )
        work = starting_app.create_work(
            objective="Start slowly", workspace_root=self.workspace
        )
        queued = starting_app.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        starting = starting_app.start(queued.identifier, expected_revision=queued.revision)
        self.assertEqual(starting.state, "starting")
        starting_app.request_cancellation(
            starting.identifier, expected_revision=starting.revision
        )
        starting_app.deliver_directives(starting.identifier)
        self.assertEqual(starting_app.observe(starting.identifier).state, "cancelled")

    def test_completion_racing_delayed_cancellation_preserves_first_terminal_outcome(self) -> None:
        delayed = FakeCodingWorkerAdapter(
            delayed_cancellation=True, clock=self.clock
        )
        app = CodingWorkApplicationService(
            self.store, delayed, correlation_factory=lambda: "launch-race"
        )
        work = app.create_work(objective="Race cancellation", workspace_root=self.workspace)
        queued = app.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        running = app.start(queued.identifier, expected_revision=queued.revision)
        session_id = self.store.get_run(running.current_run_id).harness_session_id
        app.request_cancellation(running.identifier, expected_revision=running.revision)
        app.deliver_directives(running.identifier)
        delayed.complete(session_id, summary="Completed before cancellation took effect.")
        completed = app.observe(running.identifier)
        self.assertEqual(completed.state, "completed")
        delayed.acknowledge_cancellation(session_id)
        still_completed = app.observe(running.identifier)
        self.assertEqual(still_completed.state, "completed")
        self.assertEqual(
            still_completed.result["summary"],
            "Completed before cancellation took effect.",
        )

    def test_continuation_after_completed_and_failed_creates_new_runs(self) -> None:
        completed = self.start()
        first_run = completed.current_run_id
        self.adapter.complete(self.session_id(completed), summary="First attempt completed.")
        completed = self.application.observe(completed.identifier)
        continued = self.application.continue_work(
            completed.identifier,
            expected_revision=completed.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_continue_confirmation",
        )
        self.assertEqual(continued.identifier, completed.identifier)
        self.assertNotEqual(continued.current_run_id, first_run)
        self.assertEqual(len(self.store.list_runs(completed.identifier)), 2)

        self.adapter.fail(
            self.session_id(continued), code="tests_failed", message="Tests failed."
        )
        failed = self.application.observe(continued.identifier)
        self.assertEqual(failed.state, "failed")
        third = self.application.continue_work(
            failed.identifier,
            expected_revision=failed.revision,
            read_allowed=True,
            modify_allowed=False,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_second_continue_confirmation",
        )
        self.assertEqual(third.state, "running")
        self.assertEqual(len(self.store.list_runs(failed.identifier)), 3)

    def test_weak_project_origin_and_unsupported_optional_capability(self) -> None:
        running = self.start()
        self.assertEqual(running.project_id, "project-" + "a" * 32)
        self.assertEqual(running.origin_chat_id, "chat-" + "b" * 32)
        directive = self.application.submit_follow_up(
            running.identifier,
            expected_revision=running.revision,
            instruction="Also update the living documentation.",
            source_chat_id="chat-" + "d" * 32,
        )
        self.assertNotEqual(directive.source_chat_id, running.origin_chat_id)
        with self.assertRaises(CodingWorkerUnsupportedError):
            self.adapter.unsupported("native_diff_retrieval")

    def test_operational_post_launch_inspection_failure_is_durable_and_cleaned_up(self) -> None:
        class InspectFailureAdapter(FakeCodingWorkerAdapter):
            def inspect(self, binding):  # type: ignore[no-untyped-def]
                raise CodingWorkerError(
                    "Synthetic ACP initialization failure.", code="acp_initialization_failed"
                )

        adapter = InspectFailureAdapter(clock=self.clock)
        application = CodingWorkApplicationService(
            self.store, adapter, correlation_factory=lambda: "launch-inspect-failure"
        )
        work = application.create_work(
            objective="Fail during adapter setup", workspace_root=self.workspace
        )
        queued = application.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        failed = application.start(queued.identifier, expected_revision=queued.revision)
        self.assertEqual(failed.state, "failed")
        run = self.store.get_run(failed.current_run_id)
        self.assertEqual(run.failure_code, "acp_initialization_failed")
        with self.assertRaises(CodingWorkerError) as captured:
            adapter.attach(adapter.binding_for_session("fake-session-1"), after_sequence=0)
        self.assertEqual(captured.exception.code, "session_missing")


if __name__ == "__main__":
    unittest.main()
