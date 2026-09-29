from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tori.coding_work import (
    CodingWorkAuthority,
    CodingWorkConflictError,
    CodingWorkCorruptError,
    CodingWorkStaleRevisionError,
    CodingWorkUnavailableError,
    CodingWorkValidationError,
    CodingWorkVersionError,
    SQLiteCodingWorkStore,
)
from tori.time_context import FakeClock


def deterministic_identifiers():  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}

    def create(prefix: str) -> str:
        counts[prefix] = counts.get(prefix, 0) + 1
        return f"{prefix}-{counts[prefix]:032x}"

    return create


class CodingWorkStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.clock = FakeClock(datetime(2026, 8, 23, 12, tzinfo=timezone.utc))
        self.path = self.root / "state" / "coding-work.db"
        self.store = SQLiteCodingWorkStore(
            self.path,
            clock=self.clock,
            identifier_factory=deterministic_identifiers(),
        )

    def initialize(self) -> None:
        self.store.initialize()

    def create(self, **overrides: object):  # type: ignore[no-untyped-def]
        values: dict[str, object] = {
            "objective": "Repair the focused tests",
            "acceptance_criteria": "The focused suite passes.",
            "workspace_root": str(self.workspace),
            "project_id": None,
            "origin_chat_id": None,
        }
        values.update(overrides)
        return self.store.create_work(**values)

    def authorize(self, work, **overrides: object):  # type: ignore[no-untyped-def]
        values = {
            "read_allowed": True,
            "modify_allowed": True,
            "sandboxed_execution_allowed": True,
        }
        values.update(overrides)
        authority = CodingWorkAuthority(str(self.workspace), **values)
        return self.store.authorize(
            work.identifier,
            expected_revision=work.revision,
            authority=authority,
            confirmation_provenance="explicit_test_confirmation",
        )

    def create_run(self, work):  # type: ignore[no-untyped-def]
        return self.store.create_run(
            work.identifier,
            expected_revision=work.revision,
            adapter_id="fake.coding.worker",
            adapter_version=1,
            launch_correlation_id=f"launch-{work.revision}",
        )

    def test_explicit_schema_initialization_reopen_and_unsupported_version_refusal(self) -> None:
        with self.assertRaises(CodingWorkUnavailableError):
            self.store.list_work()
        self.initialize()
        self.assertEqual(self.store.revision(), 1)
        self.assertEqual(self.store.list_work(), ())
        reopened = SQLiteCodingWorkStore(self.path)
        self.assertEqual(reopened.state().revision, 1)
        with self.assertRaises(CodingWorkConflictError):
            self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE coding_work_metadata SET value='2' WHERE key='schema_version'"
            )
        with self.assertRaises(CodingWorkVersionError):
            reopened.list_work()

    def test_creation_revisions_weak_references_and_bounded_events(self) -> None:
        self.initialize()
        work = self.create(
            project_id="project-" + "a" * 32,
            origin_chat_id="chat-" + "b" * 32,
        )
        self.assertEqual(work.revision, 1)
        self.assertEqual(work.state, "awaiting_authorization")
        self.assertEqual(work.project_id, "project-" + "a" * 32)
        self.assertEqual(work.origin_chat_id, "chat-" + "b" * 32)
        self.assertEqual([event.kind for event in self.store.events(work.identifier)], ["created"])
        self.assertGreater(self.store.revision(), 1)
        with self.assertRaises(CodingWorkValidationError):
            self.create(objective="x" * 8_001)

    def test_authority_is_deterministic_immutable_and_replaced_by_snapshot(self) -> None:
        self.initialize()
        work = self.create()
        first_document = CodingWorkAuthority(
            str(self.workspace), True, True, True
        )
        equivalent = CodingWorkAuthority(
            workspace_root=str(self.workspace),
            sandboxed_execution_allowed=True,
            modify_allowed=True,
            read_allowed=True,
        )
        self.assertEqual(first_document.canonical_json, equivalent.canonical_json)
        self.assertEqual(first_document.digest, equivalent.digest)
        authority_document = first_document.document()
        self.assertEqual(
            authority_document["repository"],
            {"authoritative_git_control_state": "read_only_if_present"},
        )
        self.assertEqual(
            authority_document["host_resources"],
            {
                "home_credentials_and_caches": "unavailable",
                "system_package_environment": "read_only",
            },
        )
        self.assertNotIn("dependencies", authority_document)
        self.assertNotIn("local_commit", first_document.canonical_json)
        queued, first = self.authorize(work)
        revised, second = self.store.authorize(
            queued.identifier,
            expected_revision=queued.revision,
            authority=CodingWorkAuthority(str(self.workspace), True, False, True),
            confirmation_provenance="explicit_narrowing_confirmation",
        )
        self.assertNotEqual(first.identifier, second.identifier)
        self.assertNotEqual(first.authority_digest, second.authority_digest)
        history = self.store.list_authorizations(work.identifier)
        self.assertEqual([item.status for item in history], ["superseded", "active"])
        self.assertEqual(revised.current_authorization_id, second.identifier)
        with self.assertRaises(CodingWorkValidationError):
            CodingWorkAuthority(str(self.workspace), False, True, True).document()

    def test_state_machine_valid_invalid_and_terminal_idempotency(self) -> None:
        self.initialize()
        created = self.create()
        queued, _authorization = self.authorize(created)
        starting, run = self.create_run(queued)
        with self.assertRaises(CodingWorkConflictError):
            self.store.transition_work(
                starting.identifier,
                expected_revision=starting.revision,
                target_state="completed",
                event_kind="completed",
                run_id=run.identifier,
                result={"summary": "too early"},
            )
        attached = self.store.bind_session(
            run.identifier,
            expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        running = self.store.get_work(created.identifier)
        self.assertEqual(attached.connection_state, "attached")
        waiting = self.store.transition_work(
            running.identifier,
            expected_revision=running.revision,
            target_state="waiting",
            event_kind="waiting",
            run_id=run.identifier,
        )
        resumed = self.store.transition_work(
            waiting.identifier,
            expected_revision=waiting.revision,
            target_state="running",
            event_kind="session_confirmed",
            run_id=run.identifier,
        )
        completed = self.store.transition_work(
            resumed.identifier,
            expected_revision=resumed.revision,
            target_state="completed",
            event_kind="completed",
            run_id=run.identifier,
            deduplication_key="terminal-one",
            result={"summary": "done"},
        )
        duplicate = self.store.transition_work(
            completed.identifier,
            expected_revision=completed.revision,
            target_state="completed",
            event_kind="completed",
            run_id=run.identifier,
            deduplication_key="terminal-one",
            result={"summary": "done"},
        )
        self.assertEqual(duplicate, completed)
        with self.assertRaises(CodingWorkConflictError):
            self.store.transition_work(
                completed.identifier,
                expected_revision=completed.revision,
                target_state="running",
                event_kind="session_confirmed",
            )

    def test_progress_deduplication_stale_sequence_and_evidence_persistence(self) -> None:
        self.initialize()
        queued, _authorization = self.authorize(self.create())
        _starting, run = self.create_run(queued)
        run = self.store.bind_session(
            run.identifier, expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        work = self.store.get_work(queued.identifier)
        progressed = self.store.update_progress(
            work.identifier,
            expected_revision=work.revision,
            run_id=run.identifier,
            adapter_event_id="progress-1",
            adapter_sequence=1,
            summary="Investigating tests",
            changed_paths=("src/tori/example.py",),
            verification="not run",
            event_cursor="1",
        )
        duplicate = self.store.update_progress(
            work.identifier,
            expected_revision=work.revision,
            run_id=run.identifier,
            adapter_event_id="progress-1",
            adapter_sequence=1,
            summary="Investigating tests",
            changed_paths=("src/tori/example.py",),
            event_cursor="1",
        )
        self.assertEqual(duplicate, progressed)
        with self.assertRaises(CodingWorkStaleRevisionError):
            self.store.update_progress(
                progressed.identifier,
                expected_revision=progressed.revision,
                run_id=run.identifier,
                adapter_event_id="different-stale-event",
                adapter_sequence=1,
                summary="stale",
            )
        result = {"summary": "Verified", "changed_paths": ["src/tori/example.py"]}
        terminal = self.store.transition_work(
            progressed.identifier,
            expected_revision=progressed.revision,
            target_state="completed",
            event_kind="completed",
            run_id=run.identifier,
            result=result,
        )
        self.assertEqual(dict(terminal.result or {}), result)
        self.assertEqual(terminal.progress["summary"], "Investigating tests")

    def test_directive_delivery_state_is_durable_and_idempotent(self) -> None:
        self.initialize()
        queued, _authorization = self.authorize(self.create())
        _starting, run = self.create_run(queued)
        self.store.bind_session(
            run.identifier, expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        running = self.store.get_work(queued.identifier)
        _work, directive = self.store.queue_directive(
            running.identifier,
            expected_revision=running.revision,
            kind="instruction",
            instruction="Run the focused tests again.",
            source_chat_id="chat-" + "c" * 32,
        )
        claimed = self.store.claim_directive(directive.identifier)
        reopened = SQLiteCodingWorkStore(self.path)
        self.assertEqual(reopened.pending_directives()[0].status, "delivering")
        delivered = reopened.finish_directive(
            claimed.identifier,
            expected_revision=claimed.revision,
            receipt="adapter-receipt-1",
        )
        repeated = reopened.finish_directive(
            delivered.identifier,
            expected_revision=delivered.revision,
            receipt="adapter-receipt-1",
        )
        self.assertEqual(repeated, delivered)
        self.assertEqual(reopened.pending_directives(), ())

    def test_restart_marks_observed_nonterminal_work_reconciling(self) -> None:
        self.initialize()
        queued, _authorization = self.authorize(self.create())
        _starting, run = self.create_run(queued)
        self.store.bind_session(
            run.identifier, expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        changed = self.store.mark_reconciling()
        self.assertEqual([item.state for item in changed], ["reconciling"])
        self.assertEqual(self.store.get_run(run.identifier).connection_state, "reconciling")
        self.assertEqual(
            self.store.get_run(run.identifier).reconciliation_prior_state, "running"
        )

    def test_active_run_authority_cannot_be_replaced_or_narrowed_in_place(self) -> None:
        self.initialize()
        queued, authorization = self.authorize(self.create())
        _starting, run = self.create_run(queued)
        self.store.bind_session(
            run.identifier, expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        running = self.store.get_work(queued.identifier)
        waiting = self.store.transition_work(
            running.identifier,
            expected_revision=running.revision,
            target_state="waiting",
            event_kind="waiting",
            run_id=run.identifier,
        )
        with self.assertRaises(CodingWorkConflictError):
            self.store.authorize(
                waiting.identifier,
                expected_revision=waiting.revision,
                authority=CodingWorkAuthority(str(self.workspace), True, False, True),
                confirmation_provenance="must_stop_first",
            )
        unchanged = self.store.get_work(waiting.identifier)
        self.assertEqual(unchanged.current_authorization_id, authorization.identifier)
        self.assertEqual(unchanged.current_run_id, run.identifier)
        self.assertEqual(len(self.store.list_authorizations(waiting.identifier)), 1)

    def test_durable_event_history_is_physically_bounded(self) -> None:
        self.initialize()
        queued, _authorization = self.authorize(self.create())
        _starting, run = self.create_run(queued)
        self.store.bind_session(
            run.identifier, expected_revision=run.revision,
            harness_session_id="fake-session-1",
        )
        current = self.store.get_work(queued.identifier)
        for index in range(260):
            current = self.store.transition_work(
                current.identifier,
                expected_revision=current.revision,
                target_state="waiting",
                event_kind="waiting",
                run_id=run.identifier,
                deduplication_key=f"wait-{index}",
            )
            current = self.store.transition_work(
                current.identifier,
                expected_revision=current.revision,
                target_state="running",
                event_kind="session_confirmed",
                run_id=run.identifier,
                deduplication_key=f"run-{index}",
            )
        events = self.store.events(current.identifier)
        self.assertEqual(len(events), 500)
        self.assertGreater(events[0].work_sequence, 1)
        with sqlite3.connect(self.path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM coding_work_events WHERE work_id=?",
                (current.identifier,),
            ).fetchone()[0]
        self.assertEqual(count, 500)

    def test_cross_record_corruption_and_stale_missing_run_are_refused(self) -> None:
        self.initialize()
        first, _authorization = self.authorize(self.create())
        _starting, first_run = self.create_run(first)
        self.store.bind_session(
            first_run.identifier, expected_revision=first_run.revision,
            harness_session_id="fake-session-1",
        )
        active = self.store.get_work(first.identifier)
        failed = self.store.transition_work(
            active.identifier,
            expected_revision=active.revision,
            target_state="failed",
            event_kind="failed",
            run_id=first_run.identifier,
            result={"summary": "first failed"},
            failure_code="first_failed",
            failure_message="The first run failed.",
        )
        continued = self.store.continue_terminal(
            failed.identifier, expected_revision=failed.revision
        )
        queued, _authorization = self.authorize(continued)
        _starting, second_run = self.create_run(queued)
        self.store.bind_session(
            second_run.identifier, expected_revision=second_run.revision,
            harness_session_id="fake-session-2",
        )
        self.store.mark_reconciling()
        reconciling = self.store.get_work(first.identifier)
        with self.assertRaises(CodingWorkConflictError):
            self.store.mark_session_missing(
                reconciling.identifier,
                expected_revision=reconciling.revision,
                run_id=first_run.identifier,
            )
        self.assertEqual(self.store.get_work(first.identifier).state, "reconciling")

        other, other_authorization = self.authorize(self.create())
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE coding_work SET current_authorization_id=? WHERE identifier=?",
                (other_authorization.identifier, reconciling.identifier),
            )
        with self.assertRaises(CodingWorkCorruptError):
            self.store.get_work(other.identifier)

    def test_continuation_preserves_identity_and_execution_history(self) -> None:
        self.initialize()
        queued, first_authorization = self.authorize(self.create())
        _starting, first_run = self.create_run(queued)
        self.store.bind_session(
            first_run.identifier, expected_revision=first_run.revision,
            harness_session_id="fake-session-1",
        )
        running = self.store.get_work(queued.identifier)
        failed = self.store.transition_work(
            running.identifier,
            expected_revision=running.revision,
            target_state="failed",
            event_kind="failed",
            run_id=first_run.identifier,
            result={"summary": "failed"},
            failure_code="tests_failed",
            failure_message="The tests failed.",
        )
        continued = self.store.continue_terminal(
            failed.identifier, expected_revision=failed.revision
        )
        queued_again, second_authorization = self.authorize(continued)
        _starting_again, second_run = self.create_run(queued_again)
        self.assertEqual(continued.identifier, failed.identifier)
        self.assertNotEqual(first_run.identifier, second_run.identifier)
        self.assertNotEqual(first_authorization.identifier, second_authorization.identifier)
        self.assertEqual(len(self.store.list_runs(failed.identifier)), 2)
        self.assertEqual(
            [item.status for item in self.store.list_authorizations(failed.identifier)],
            ["superseded", "active"],
        )

    def test_symlink_database_path_is_refused_without_following(self) -> None:
        self.path.parent.mkdir()
        target = self.root / "target.db"
        target.write_bytes(b"preserve")
        self.path.symlink_to(target)
        with self.assertRaises(CodingWorkUnavailableError):
            self.store.initialize()
        self.assertEqual(target.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
