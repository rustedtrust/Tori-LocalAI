from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.tasks import (
    OperationalConflictError,
    OperationalNotFoundError,
    OperationalStaleRevisionError,
    OperationalUnavailableError,
    OperationalVerificationError,
    SQLiteOperationalStore,
)
from tori.time_context import FakeClock, format_utc_timestamp


class OperationalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = FakeClock(datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc))
        self.path = Path(self.temporary.name) / "runtime" / "tasks" / "tori_tasks.db"
        self.store = SQLiteOperationalStore(self.path, clock=self.clock)

    def test_exact_schema_permissions_and_pragmas(self) -> None:
        self.store.initialize()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.path.parent).st_mode & 0o777, 0o700)
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(
                {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")},
                {"operational_metadata", "operational_state", "tasks", "reminders", "reminder_deliveries"},
            )
            self.assertEqual(connection.execute("SELECT value FROM operational_metadata WHERE key='schema_version'").fetchone()[0], "1")
        finally:
            connection.close()

    def test_task_standalone_and_multiple_linked_reminders_round_trip(self) -> None:
        task = self.store.create_task("Stack the garage boxes")
        first = self.store.create_reminder(
            "Start the garage boxes",
            task_id=task.identifier,
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        second = self.store.create_reminder(
            "Finish the garage boxes",
            task_id=task.identifier,
            scheduled_start_utc="2026-08-11T16:00:00Z",
            scheduled_end_utc="2026-08-11T17:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        standalone = self.store.create_reminder(
            "Take lunch early",
            scheduled_start_utc="2026-08-10T15:30:00Z",
            scheduled_end_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.assertEqual(self.store.get_task(task.identifier), task)
        self.assertEqual([item.identifier for item in self.store.list_reminders()], [standalone.identifier, first.identifier, second.identifier])
        self.assertIsNone(standalone.task_id)
        self.assertEqual(second.scheduled_end_utc, "2026-08-11T17:00:00Z")

    def test_due_scan_delivery_uniqueness_delay_and_deterministic_attention(self) -> None:
        later = self.store.create_reminder(
            "later",
            scheduled_start_utc="2026-08-10T15:10:00Z",
            scheduled_timezone="America/Chicago",
        )
        earlier = self.store.create_reminder(
            "earlier",
            scheduled_start_utc="2026-08-10T15:05:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.clock.advance(timedelta(minutes=11))
        due = self.store.mark_due(self.clock())
        self.assertEqual([item.identifier for item in due], [earlier.identifier, later.identifier])
        self.assertEqual(self.store.mark_due(self.clock()), ())
        self.assertEqual(len(self.store.pending_deliveries()), 2)
        state = self.store.attention()
        self.assertEqual(state.active.identifier, earlier.identifier)
        self.assertEqual(state.queued_count, 1)
        delayed = self.store.delay_reminder(
            earlier.identifier,
            expected_revision=2,
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.assertEqual(delayed.status, "scheduled")
        self.assertIsNone(delayed.became_due_at_utc)
        self.assertEqual(len(self.store.pending_deliveries()), 1)
        self.assertEqual(self.store.attention().active.identifier, later.identifier)

    def test_two_client_race_and_idempotent_retry(self) -> None:
        task = self.store.create_task("one mutation")
        completed = self.store.complete_task(task.identifier, expected_revision=1)
        self.assertEqual(self.store.complete_task(task.identifier, expected_revision=1), completed)
        with self.assertRaises(OperationalStaleRevisionError):
            self.store.update_task(
                task.identifier,
                expected_revision=1,
                description="stale rewrite",
            )

    def test_update_and_resolution_require_exact_fresh_read_verification(self) -> None:
        task = self.store.create_task("verify update")
        with patch.object(
            self.store,
            "get_task",
            side_effect=[task, OperationalUnavailableError("synthetic read failure")],
        ):
            with self.assertRaises(OperationalVerificationError):
                self.store.update_task(
                    task.identifier,
                    expected_revision=1,
                    description="verified update",
                )
        self.assertEqual(self.store.get_task(task.identifier).description, "verified update")

        reminder = self.store.create_reminder(
            "verify resolution",
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        with patch.object(
            self.store,
            "get_reminder",
            side_effect=[reminder, OperationalUnavailableError("synthetic read failure")],
        ):
            with self.assertRaises(OperationalVerificationError):
                self.store.dismiss_reminder(reminder.identifier, expected_revision=1)
        self.assertEqual(self.store.get_reminder(reminder.identifier).status, "dismissed")

    def test_linked_done_is_atomic_and_cancelled_task_is_never_revived(self) -> None:
        task, reminder = self.store.create_task_with_reminder(
            "Finish boxes", "Finish the boxes now",
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.store.mark_due(self.clock())
        done = self.store.done_reminder(reminder.identifier, expected_revision=2)
        self.assertEqual(done.resolution, "task_completed")
        self.assertEqual(self.store.get_task(task.identifier).status, "completed")

        task2, reminder2 = self.store.create_task_with_reminder(
            "Cancelled work", "Do cancelled work",
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.store.cancel_task(task2.identifier, expected_revision=1)
        with self.assertRaises(OperationalConflictError):
            self.store.done_reminder(reminder2.identifier, expected_revision=1)
        self.assertEqual(self.store.get_task(task2.identifier).status, "cancelled")
        self.assertEqual(self.store.get_reminder(reminder2.identifier).status, "scheduled")

    def test_historical_reminder_delete_enforces_status_revision_and_atomic_delivery_removal(self) -> None:
        task = self.store.create_task("Linked task remains")
        scheduled = self.store.create_reminder(
            "Scheduled",
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        due = self.store.create_reminder(
            "Due",
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        dismissed = self.store.create_reminder(
            "Dismissed linked",
            task_id=task.identifier,
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        completed = self.store.create_reminder(
            "Completed",
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        cancelled = self.store.create_reminder(
            "Cancelled",
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        self.store.mark_due(self.clock())
        dismissed = self.store.dismiss_reminder(dismissed.identifier, expected_revision=2)
        completed = self.store.done_reminder(completed.identifier, expected_revision=2)
        cancelled = self.store.cancel_reminder(cancelled.identifier, expected_revision=1)

        for active in (scheduled, self.store.get_reminder(due.identifier)):
            with self.subTest(active_status=active.status):
                with self.assertRaises(OperationalConflictError):
                    self.store.delete_historical_reminder(
                        active.identifier, expected_revision=active.revision
                    )
        with self.assertRaises(OperationalStaleRevisionError):
            self.store.delete_historical_reminder(
                dismissed.identifier, expected_revision=dismissed.revision - 1
            )

        for resolved in (dismissed, completed, cancelled):
            before_revision = self.store.revision()
            self.store.delete_historical_reminder(
                resolved.identifier, expected_revision=resolved.revision
            )
            self.assertEqual(self.store.revision(), before_revision + 1)
            with self.assertRaises(OperationalNotFoundError):
                self.store.get_reminder(resolved.identifier)
            with self.assertRaises(OperationalNotFoundError):
                self.store.delivery(resolved.identifier)
        self.assertEqual(self.store.get_task(task.identifier), task)

    def test_historical_task_delete_refuses_links_then_succeeds_without_cascade(self) -> None:
        open_task = self.store.create_task("Still open")
        with self.assertRaises(OperationalConflictError):
            self.store.delete_historical_task(
                open_task.identifier, expected_revision=open_task.revision
            )

        completed = self.store.complete_task(
            self.store.create_task("Completed unreferenced").identifier,
            expected_revision=1,
        )
        cancelled = self.store.cancel_task(
            self.store.create_task("Cancelled unreferenced").identifier,
            expected_revision=1,
        )
        with self.assertRaises(OperationalStaleRevisionError):
            self.store.delete_historical_task(
                completed.identifier, expected_revision=completed.revision - 1
            )
        for historical in (completed, cancelled):
            before_revision = self.store.revision()
            self.store.delete_historical_task(
                historical.identifier, expected_revision=historical.revision
            )
            self.assertEqual(self.store.revision(), before_revision + 1)
            with self.assertRaises(OperationalNotFoundError):
                self.store.get_task(historical.identifier)

        linked_task = self.store.create_task("Historical with reminder")
        linked_reminder = self.store.create_reminder(
            "Linked history",
            task_id=linked_task.identifier,
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        linked_task = self.store.complete_task(
            linked_task.identifier, expected_revision=1
        )
        self.store.mark_due(self.clock())
        linked_reminder = self.store.dismiss_reminder(
            linked_reminder.identifier, expected_revision=2
        )
        before_refusal = self.store.revision()
        with self.assertRaisesRegex(
            OperationalConflictError, "Delete those reminders first"
        ):
            self.store.delete_historical_task(
                linked_task.identifier, expected_revision=linked_task.revision
            )
        self.assertEqual(self.store.revision(), before_refusal)
        self.assertEqual(
            self.store.get_reminder(linked_reminder.identifier).task_id,
            linked_task.identifier,
        )
        self.store.delete_historical_reminder(
            linked_reminder.identifier, expected_revision=linked_reminder.revision
        )
        self.store.delete_historical_task(
            linked_task.identifier, expected_revision=linked_task.revision
        )
        with self.assertRaises(OperationalNotFoundError):
            self.store.get_task(linked_task.identifier)

    def test_simultaneous_history_deletes_have_one_winner(self) -> None:
        task = self.store.complete_task(
            self.store.create_task("Delete task race").identifier,
            expected_revision=1,
        )
        reminder = self.store.cancel_reminder(
            self.store.create_reminder(
                "Delete reminder race",
                scheduled_start_utc="2026-08-10T16:00:00Z",
                scheduled_timezone="America/Chicago",
            ).identifier,
            expected_revision=1,
        )

        def race(function):  # type: ignore[no-untyped-def]
            try:
                function()
                return "deleted"
            except (OperationalNotFoundError, OperationalStaleRevisionError):
                return "stale"

        for function in (
            lambda: self.store.delete_historical_task(
                task.identifier, expected_revision=task.revision
            ),
            lambda: self.store.delete_historical_reminder(
                reminder.identifier, expected_revision=reminder.revision
            ),
        ):
            with self.subTest(function=function):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outcomes = list(executor.map(lambda _index: race(function), range(2)))
                self.assertEqual(sorted(outcomes), ["deleted", "stale"])

    def test_symlink_database_ancestor_orphan_sidecar_and_corrupt_state_are_preserved(self) -> None:
        external = Path(self.temporary.name) / "external.db"
        external.write_bytes(b"private")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(external)
        with self.assertRaises(OperationalUnavailableError):
            self.store.initialize()
        self.assertEqual(external.read_bytes(), b"private")

        sidecar_path = Path(self.temporary.name) / "sidecar" / "tasks.db"
        sidecar_path.parent.mkdir()
        journal = Path(str(sidecar_path) + "-journal")
        journal.write_bytes(b"ambiguous")
        with self.assertRaises(OperationalUnavailableError):
            SQLiteOperationalStore(sidecar_path).initialize()
        self.assertEqual(journal.read_bytes(), b"ambiguous")


if __name__ == "__main__":
    unittest.main()
