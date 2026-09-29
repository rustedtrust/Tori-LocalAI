"""Presentation-neutral explicit task and reminder application use cases."""

from __future__ import annotations

from .tasks import ReminderRecord, SQLiteOperationalStore, TaskRecord


class TaskReminderApplicationService:
    """Apply explicit task/reminder use cases through the canonical store."""

    def __init__(self, store: SQLiteOperationalStore) -> None:
        self._store = store

    def revision(self) -> int:
        return self._store.revision()

    def list_tasks(self) -> tuple[TaskRecord, ...]:
        return self._store.list_tasks()

    def list_reminders(self) -> tuple[ReminderRecord, ...]:
        return self._store.list_reminders()

    def create_task(self, description: str) -> TaskRecord:
        return self._store.create_task(description)

    def update_task(
        self,
        identifier: str,
        *,
        expected_revision: int,
        description: str,
    ) -> TaskRecord:
        current = self._store.get_task(identifier)
        return self._store.update_task(
            current.identifier,
            expected_revision=expected_revision,
            description=description,
            due_start_utc=current.due_start_utc,
            due_end_utc=current.due_end_utc,
            due_timezone=current.due_timezone,
        )

    def complete_task(
        self, identifier: str, *, expected_revision: int
    ) -> TaskRecord:
        return self._store.complete_task(
            identifier, expected_revision=expected_revision
        )

    def cancel_task(
        self, identifier: str, *, expected_revision: int
    ) -> TaskRecord:
        return self._store.cancel_task(
            identifier, expected_revision=expected_revision
        )

    def delete_historical_task(
        self, identifier: str, *, expected_revision: int
    ) -> None:
        self._store.delete_historical_task(
            identifier, expected_revision=expected_revision
        )

    def create_reminder(
        self,
        reminder_text: str,
        *,
        scheduled_start_utc: str,
        scheduled_timezone: str,
        scheduled_end_utc: str | None = None,
        task_id: str | None = None,
    ) -> ReminderRecord:
        return self._store.create_reminder(
            reminder_text,
            scheduled_start_utc=scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            scheduled_timezone=scheduled_timezone,
            task_id=task_id,
        )

    def update_reminder(
        self,
        identifier: str,
        *,
        expected_revision: int,
        reminder_text: str,
    ) -> ReminderRecord:
        current = self._store.get_reminder(identifier)
        return self._store.update_reminder(
            current.identifier,
            expected_revision=expected_revision,
            reminder_text=reminder_text,
            scheduled_start_utc=current.scheduled_start_utc,
            scheduled_end_utc=current.scheduled_end_utc,
            scheduled_timezone=current.scheduled_timezone,
        )

    def delay_reminder(
        self,
        identifier: str,
        *,
        expected_revision: int,
        scheduled_start_utc: str,
        scheduled_timezone: str,
        scheduled_end_utc: str | None = None,
    ) -> ReminderRecord:
        return self._store.delay_reminder(
            identifier,
            expected_revision=expected_revision,
            scheduled_start_utc=scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            scheduled_timezone=scheduled_timezone,
        )

    def dismiss_reminder(
        self, identifier: str, *, expected_revision: int
    ) -> ReminderRecord:
        return self._store.dismiss_reminder(
            identifier, expected_revision=expected_revision
        )

    def complete_reminder(
        self, identifier: str, *, expected_revision: int
    ) -> ReminderRecord:
        return self._store.done_reminder(
            identifier, expected_revision=expected_revision
        )

    def cancel_reminder(
        self, identifier: str, *, expected_revision: int
    ) -> ReminderRecord:
        return self._store.cancel_reminder(
            identifier, expected_revision=expected_revision
        )

    def delete_historical_reminder(
        self, identifier: str, *, expected_revision: int
    ) -> None:
        self._store.delete_historical_reminder(
            identifier, expected_revision=expected_revision
        )
