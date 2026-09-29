from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.task_reminder_application import TaskReminderApplicationService
from tori.tasks import (
    OperationalConflictError,
    OperationalNotFoundError,
    OperationalStaleRevisionError,
    SQLiteOperationalStore,
)


class TaskReminderApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        identifier_counts = {"task": 0, "reminder": 0}

        def next_identifier(prefix: str) -> str:
            identifier_counts[prefix] += 1
            marker = "1" if prefix == "task" else "2"
            return f"{prefix}-" + marker * 31 + str(identifier_counts[prefix])

        self.store = SQLiteOperationalStore(
            Path(self.temporary.name) / "tasks.db",
            clock=lambda: self.now,
            identifier_factory=next_identifier,
        )
        self.application = TaskReminderApplicationService(self.store)

    def scheduled(self, minutes: int = 10) -> str:
        return (self.now + timedelta(minutes=minutes)).isoformat().replace(
            "+00:00", "Z"
        )

    def test_list_create_and_revision_use_canonical_store(self) -> None:
        task = self.application.create_task("Prepare recovery review")
        reminder = self.application.create_reminder(
            "Review recovery",
            scheduled_start_utc=self.scheduled(),
            scheduled_timezone="America/Chicago",
            task_id=task.identifier,
        )
        self.assertEqual(self.application.list_tasks(), (task,))
        self.assertEqual(self.application.list_reminders(), (reminder,))
        self.assertEqual(self.application.revision(), 3)

    def test_task_update_preserves_schedule_and_transitions_are_revision_safe(self) -> None:
        task = self.store.create_task(
            "Original",
            due_start_utc=self.scheduled(20),
            due_timezone="America/Chicago",
        )
        updated = self.application.update_task(
            task.identifier,
            expected_revision=task.revision,
            description="Updated",
        )
        self.assertEqual(updated.description, "Updated")
        self.assertEqual(updated.due_start_utc, task.due_start_utc)
        self.assertEqual(updated.due_timezone, task.due_timezone)
        with self.assertRaises(OperationalStaleRevisionError):
            self.application.cancel_task(
                task.identifier, expected_revision=task.revision
            )
        completed = self.application.complete_task(
            task.identifier, expected_revision=updated.revision
        )
        self.assertEqual(completed.status, "completed")

    def test_reminder_update_delay_and_lifecycle_preserve_explicit_semantics(self) -> None:
        reminder = self.application.create_reminder(
            "Initial reminder",
            scheduled_start_utc=self.scheduled(),
            scheduled_timezone="America/Chicago",
        )
        updated = self.application.update_reminder(
            reminder.identifier,
            expected_revision=reminder.revision,
            reminder_text="Updated reminder",
        )
        self.assertEqual(updated.scheduled_start_utc, reminder.scheduled_start_utc)
        delayed = self.application.delay_reminder(
            reminder.identifier,
            expected_revision=updated.revision,
            scheduled_start_utc=self.scheduled(30),
            scheduled_timezone="America/Chicago",
        )
        self.assertEqual(delayed.reminder_text, "Updated reminder")
        self.assertEqual(delayed.scheduled_start_utc, self.scheduled(30))
        dismissed = self.application.dismiss_reminder(
            reminder.identifier, expected_revision=delayed.revision
        )
        self.assertEqual(dismissed.status, "dismissed")
        with self.assertRaises(OperationalConflictError):
            self.application.complete_reminder(
                reminder.identifier, expected_revision=dismissed.revision
            )

    def test_linked_completion_keeps_existing_atomic_task_semantics(self) -> None:
        task = self.application.create_task("Linked task")
        reminder = self.application.create_reminder(
            "Linked reminder",
            scheduled_start_utc=self.scheduled(),
            scheduled_timezone="America/Chicago",
            task_id=task.identifier,
        )
        completed = self.application.complete_reminder(
            reminder.identifier, expected_revision=reminder.revision
        )
        self.assertEqual(completed.status, "completed")
        self.assertEqual(self.store.get_task(task.identifier).status, "completed")

    def test_historical_deletion_preserves_link_order_and_unrelated_records(self) -> None:
        linked_task = self.application.create_task("Linked history")
        linked_reminder = self.application.create_reminder(
            "Linked history reminder",
            scheduled_start_utc=self.scheduled(),
            scheduled_timezone="America/Chicago",
            task_id=linked_task.identifier,
        )
        linked_task = self.application.cancel_task(
            linked_task.identifier, expected_revision=linked_task.revision
        )
        linked_reminder = self.application.cancel_reminder(
            linked_reminder.identifier,
            expected_revision=linked_reminder.revision,
        )
        unrelated = self.application.create_task("Unrelated task")
        with self.assertRaises(OperationalConflictError):
            self.application.delete_historical_task(
                linked_task.identifier, expected_revision=linked_task.revision
            )
        self.application.delete_historical_reminder(
            linked_reminder.identifier,
            expected_revision=linked_reminder.revision,
        )
        self.application.delete_historical_task(
            linked_task.identifier, expected_revision=linked_task.revision
        )
        with self.assertRaises(OperationalNotFoundError):
            self.store.get_task(linked_task.identifier)
        self.assertEqual(self.store.get_task(unrelated.identifier), unrelated)


class TaskReminderApplicationArchitectureTests(unittest.TestCase):
    def test_module_has_no_presentation_provider_or_unrelated_domain_dependency(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "src"
            / "tori"
            / "task_reminder_application.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden = {
            "http",
            "tori.web",
            "tori.providers",
            "tori.conversation",
            "tori.conversation_archive",
            "tori.memory_extraction",
            "tori.projects",
            "tori.scheduled_work",
            "tori.search_application",
        }
        self.assertTrue(imported.isdisjoint(forbidden), imported & forbidden)


if __name__ == "__main__":
    unittest.main()
