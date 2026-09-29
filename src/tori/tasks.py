"""Canonical operational tasks, reminders, and reminder-delivery state."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import closing
import ctypes
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import errno
import os
from pathlib import Path
from urllib.parse import quote
import re
import secrets
import sqlite3
import stat
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .time_context import format_utc_timestamp, parse_utc_timestamp


OPERATIONAL_SCHEMA_VERSION = 1
DEFAULT_OPERATIONAL_DATABASE = Path("runtime/tasks/tori_tasks.db")
MAX_DESCRIPTION_LENGTH = 4_000
MAX_RESOLUTION_LENGTH = 64
MAX_IDENTIFIER_ATTEMPTS = 5
TASK_STATUSES = frozenset({"open", "completed", "cancelled"})
REMINDER_STATUSES = frozenset(
    {"scheduled", "due", "dismissed", "completed", "cancelled"}
)
REMINDER_RESOLUTIONS = frozenset(
    {"dismissed", "completed", "task_completed", "cancelled"}
)

_TASK_ID = re.compile(r"^task-[0-9a-f]{32}$")
_REMINDER_ID = re.compile(r"^reminder-[0-9a-f]{32}$")
_EVENT_ID = re.compile(r"^event-[0-9a-f]{32}$")

_METADATA_SQL = """
CREATE TABLE operational_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_STATE_SQL = """
CREATE TABLE operational_state (
    singleton INTEGER PRIMARY KEY
        CHECK (typeof(singleton) = 'integer' AND singleton = 1),
    revision INTEGER NOT NULL
        CHECK (typeof(revision) = 'integer' AND revision >= 1)
)
"""
_TASKS_SQL = f"""
CREATE TABLE tasks (
    identifier TEXT PRIMARY KEY
        CHECK (length(identifier) = 37 AND substr(identifier, 1, 5) = 'task-'
               AND substr(identifier, 6) NOT GLOB '*[^0-9a-f]*'),
    description TEXT NOT NULL CHECK (length(description) BETWEEN 1 AND {MAX_DESCRIPTION_LENGTH}),
    status TEXT NOT NULL CHECK (status IN ('open', 'completed', 'cancelled')),
    due_start_utc TEXT,
    due_end_utc TEXT,
    due_timezone TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    cancelled_at_utc TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    CHECK (due_end_utc IS NULL OR due_start_utc IS NOT NULL),
    CHECK (due_start_utc IS NULL OR due_timezone IS NOT NULL),
    CHECK (due_start_utc IS NULL OR due_end_utc IS NULL OR due_start_utc <= due_end_utc),
    CHECK (created_at_utc <= updated_at_utc),
    CHECK (completed_at_utc IS NULL OR (created_at_utc <= completed_at_utc AND completed_at_utc <= updated_at_utc)),
    CHECK (cancelled_at_utc IS NULL OR (created_at_utc <= cancelled_at_utc AND cancelled_at_utc <= updated_at_utc)),
    CHECK ((status = 'open' AND completed_at_utc IS NULL AND cancelled_at_utc IS NULL)
        OR (status = 'completed' AND completed_at_utc IS NOT NULL AND cancelled_at_utc IS NULL)
        OR (status = 'cancelled' AND completed_at_utc IS NULL AND cancelled_at_utc IS NOT NULL))
)
"""
_REMINDERS_SQL = f"""
CREATE TABLE reminders (
    identifier TEXT PRIMARY KEY
        CHECK (length(identifier) = 41 AND substr(identifier, 1, 9) = 'reminder-'
               AND substr(identifier, 10) NOT GLOB '*[^0-9a-f]*'),
    task_id TEXT,
    reminder_text TEXT NOT NULL CHECK (length(reminder_text) BETWEEN 1 AND {MAX_DESCRIPTION_LENGTH}),
    status TEXT NOT NULL CHECK (status IN ('scheduled', 'due', 'dismissed', 'completed', 'cancelled')),
    scheduled_start_utc TEXT NOT NULL,
    scheduled_end_utc TEXT,
    scheduled_timezone TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    became_due_at_utc TEXT,
    resolved_at_utc TEXT,
    resolution TEXT CHECK (resolution IN ('dismissed', 'completed', 'task_completed', 'cancelled')),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    FOREIGN KEY (task_id) REFERENCES tasks(identifier),
    CHECK (scheduled_end_utc IS NULL OR scheduled_start_utc <= scheduled_end_utc),
    CHECK (created_at_utc <= updated_at_utc),
    CHECK (became_due_at_utc IS NULL OR became_due_at_utc <= updated_at_utc),
    CHECK (resolved_at_utc IS NULL OR (created_at_utc <= resolved_at_utc AND resolved_at_utc <= updated_at_utc)),
    CHECK ((status = 'scheduled' AND became_due_at_utc IS NULL AND resolved_at_utc IS NULL AND resolution IS NULL)
        OR (status = 'due' AND became_due_at_utc IS NOT NULL AND resolved_at_utc IS NULL AND resolution IS NULL)
        OR (status = 'dismissed' AND resolved_at_utc IS NOT NULL AND resolution = 'dismissed')
        OR (status = 'completed' AND resolved_at_utc IS NOT NULL AND resolution IN ('completed', 'task_completed'))
        OR (status = 'cancelled' AND resolved_at_utc IS NOT NULL AND resolution = 'cancelled'))
)
"""
_DELIVERIES_SQL = """
CREATE TABLE reminder_deliveries (
    reminder_id TEXT PRIMARY KEY,
    event_identifier TEXT NOT NULL UNIQUE
        CHECK (length(event_identifier) = 38 AND substr(event_identifier, 1, 6) = 'event-'
               AND substr(event_identifier, 7) NOT GLOB '*[^0-9a-f]*'),
    state TEXT NOT NULL CHECK (state IN ('pending', 'archived')),
    queued_at_utc TEXT NOT NULL,
    archived_at_utc TEXT,
    chat_id TEXT,
    FOREIGN KEY (reminder_id) REFERENCES reminders(identifier),
    CHECK ((state = 'pending' AND archived_at_utc IS NULL AND chat_id IS NULL)
        OR (state = 'archived' AND archived_at_utc IS NOT NULL AND chat_id IS NOT NULL)),
    CHECK (archived_at_utc IS NULL OR queued_at_utc <= archived_at_utc)
)
"""
_TASK_INDEX_SQL = "CREATE INDEX tasks_status_update_index ON tasks(status, updated_at_utc, identifier)"
_DUE_INDEX_SQL = "CREATE INDEX reminders_due_scan_index ON reminders(status, scheduled_start_utc, identifier)"
_TASK_REMINDER_INDEX_SQL = "CREATE INDEX reminders_task_status_schedule_index ON reminders(task_id, status, scheduled_start_utc, identifier)"


class OperationalError(RuntimeError):
    pass


class OperationalValidationError(OperationalError):
    pass


class OperationalNotFoundError(OperationalError):
    pass


class OperationalStaleRevisionError(OperationalError):
    pass


class OperationalConflictError(OperationalError):
    pass


class OperationalVersionError(OperationalError):
    pass


class OperationalCorruptError(OperationalError):
    pass


class OperationalUnavailableError(OperationalError):
    pass


class OperationalVerificationError(OperationalError):
    pass


@dataclass(frozen=True, slots=True)
class TaskRecord:
    identifier: str
    description: str
    status: str
    due_start_utc: str | None
    due_end_utc: str | None
    due_timezone: str | None
    created_at_utc: str
    updated_at_utc: str
    completed_at_utc: str | None
    cancelled_at_utc: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class ReminderRecord:
    identifier: str
    task_id: str | None
    reminder_text: str
    status: str
    scheduled_start_utc: str
    scheduled_end_utc: str | None
    scheduled_timezone: str
    created_at_utc: str
    updated_at_utc: str
    became_due_at_utc: str | None
    resolved_at_utc: str | None
    resolution: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class ReminderDelivery:
    reminder_id: str
    event_identifier: str
    state: str
    queued_at_utc: str
    archived_at_utc: str | None
    chat_id: str | None


@dataclass(frozen=True, slots=True)
class AttentionState:
    operational_revision: int
    active: ReminderRecord | None
    queued_count: int
    next_due_utc: str | None


Clock = Callable[[], datetime]
IdentifierFactory = Callable[[str], str]


class _OperationalConnection(sqlite3.Connection):
    _safe_descriptors: tuple[int, ...] = ()

    def close(self) -> None:
        try:
            super().close()
        finally:
            descriptors, self._safe_descriptors = self._safe_descriptors, ()
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


class SQLiteOperationalStore:
    """Own one exact, fail-closed SQLite operational store."""

    def __init__(
        self,
        path: Path = DEFAULT_OPERATIONAL_DATABASE,
        *,
        clock: Clock | None = None,
        identifier_factory: IdentifierFactory | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identifier_factory = identifier_factory or _identifier

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        with closing(self._connect()):
            pass

    def revision(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT revision FROM operational_state WHERE singleton = 1"
            ).fetchone()
        if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
            raise OperationalCorruptError("Tori's operational state is invalid.")
        return row[0]

    def create_task(
        self,
        description: object,
        *,
        due_start_utc: object = None,
        due_end_utc: object = None,
        due_timezone: object = None,
    ) -> TaskRecord:
        text = _text(description, "Task description")
        start, end, zone = _schedule(due_start_utc, due_end_utc, due_timezone, optional=True)
        stamp = format_utc_timestamp(self._clock())
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_task_identifier(self._identifier_factory("task"))
            expected = TaskRecord(identifier, text, "open", start, end, zone, stamp, stamp, None, None, 1)
            try:
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        tuple(expected.__dict__.values()) if hasattr(expected, "__dict__") else (
                            expected.identifier, expected.description, expected.status,
                            expected.due_start_utc, expected.due_end_utc, expected.due_timezone,
                            expected.created_at_utc, expected.updated_at_utc,
                            expected.completed_at_utc, expected.cancelled_at_utc, expected.revision,
                        ),
                    )
                    self._bump(connection)
            except sqlite3.IntegrityError as exc:
                if self._task_exists(identifier):
                    continue
                raise _database_error(exc) from exc
            return self._verify_task(expected)
        raise OperationalConflictError("Could not generate a unique task identifier.")

    def create_reminder(
        self,
        reminder_text: object,
        *,
        scheduled_start_utc: object,
        scheduled_timezone: object,
        scheduled_end_utc: object = None,
        task_id: object = None,
    ) -> ReminderRecord:
        text = _text(reminder_text, "Reminder text")
        start, end, zone = _schedule(
            scheduled_start_utc, scheduled_end_utc, scheduled_timezone, optional=False
        )
        linked = validate_task_identifier(task_id) if task_id is not None else None
        stamp = format_utc_timestamp(self._clock())
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_reminder_identifier(self._identifier_factory("reminder"))
            expected = ReminderRecord(
                identifier, linked, text, "scheduled", start, end, zone,
                stamp, stamp, None, None, None, 1,
            )
            try:
                with closing(self._connect()) as connection, connection:
                    if linked is not None and connection.execute(
                        "SELECT 1 FROM tasks WHERE identifier = ?", (linked,)
                    ).fetchone() is None:
                        raise OperationalNotFoundError("The linked task was not found.")
                    connection.execute(
                        "INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            expected.identifier, expected.task_id, expected.reminder_text,
                            expected.status, expected.scheduled_start_utc,
                            expected.scheduled_end_utc, expected.scheduled_timezone,
                            expected.created_at_utc, expected.updated_at_utc,
                            expected.became_due_at_utc, expected.resolved_at_utc,
                            expected.resolution, expected.revision,
                        ),
                    )
                    self._bump(connection)
            except sqlite3.IntegrityError as exc:
                if self._reminder_exists(identifier):
                    continue
                raise _database_error(exc) from exc
            return self._verify_reminder(expected)
        raise OperationalConflictError("Could not generate a unique reminder identifier.")

    def get_task(self, identifier: object) -> TaskRecord:
        item = validate_task_identifier(identifier)
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE identifier = ?", (item,)).fetchone()
        if row is None:
            raise OperationalNotFoundError("The task was not found.")
        return _task(row)

    def create_task_with_reminder(
        self,
        task_description: object,
        reminder_text: object,
        *,
        scheduled_start_utc: object,
        scheduled_timezone: object,
        scheduled_end_utc: object = None,
    ) -> tuple[TaskRecord, ReminderRecord]:
        """Create one linked task/reminder pair in a single transaction."""

        task_text = _text(task_description, "Task description")
        reminder_value = _text(reminder_text, "Reminder text")
        start, end, zone = _schedule(
            scheduled_start_utc, scheduled_end_utc, scheduled_timezone, optional=False
        )
        stamp = format_utc_timestamp(self._clock())
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            task_id = validate_task_identifier(self._identifier_factory("task"))
            reminder_id = validate_reminder_identifier(self._identifier_factory("reminder"))
            task = TaskRecord(task_id, task_text, "open", None, None, None, stamp, stamp, None, None, 1)
            reminder = ReminderRecord(
                reminder_id, task_id, reminder_value, "scheduled", start, end,
                zone, stamp, stamp, None, None, None, 1,
            )
            try:
                with closing(self._connect()) as connection, connection:
                    connection.execute(
                        "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            task.identifier, task.description, task.status,
                            task.due_start_utc, task.due_end_utc, task.due_timezone,
                            task.created_at_utc, task.updated_at_utc,
                            task.completed_at_utc, task.cancelled_at_utc, task.revision,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            reminder.identifier, reminder.task_id,
                            reminder.reminder_text, reminder.status,
                            reminder.scheduled_start_utc, reminder.scheduled_end_utc,
                            reminder.scheduled_timezone, reminder.created_at_utc,
                            reminder.updated_at_utc, reminder.became_due_at_utc,
                            reminder.resolved_at_utc, reminder.resolution,
                            reminder.revision,
                        ),
                    )
                    self._bump(connection)
                    self._bump(connection)
            except sqlite3.IntegrityError as exc:
                if self._task_exists(task_id) or self._reminder_exists(reminder_id):
                    continue
                raise _database_error(exc) from exc
            return self._verify_task(task), self._verify_reminder(reminder)
        raise OperationalConflictError("Could not generate unique task/reminder identifiers.")

    def get_reminder(self, identifier: object) -> ReminderRecord:
        item = validate_reminder_identifier(identifier)
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM reminders WHERE identifier = ?", (item,)).fetchone()
        if row is None:
            raise OperationalNotFoundError("The reminder was not found.")
        return _reminder(row)

    def list_tasks(self, statuses: Sequence[str] | None = None) -> tuple[TaskRecord, ...]:
        selected = _statuses(statuses, TASK_STATUSES)
        placeholders = ",".join("?" for _ in selected)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY updated_at_utc DESC, identifier",
                selected,
            ).fetchall()
        return tuple(_task(row) for row in rows)

    def list_reminders(self, statuses: Sequence[str] | None = None) -> tuple[ReminderRecord, ...]:
        selected = _statuses(statuses, REMINDER_STATUSES)
        placeholders = ",".join("?" for _ in selected)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM reminders WHERE status IN ({placeholders}) ORDER BY scheduled_start_utc, identifier",
                selected,
            ).fetchall()
        return tuple(_reminder(row) for row in rows)

    def delete_historical_task(
        self,
        identifier: object,
        *,
        expected_revision: object,
    ) -> None:
        """Permanently delete one unreferenced completed/cancelled task."""

        task_id = validate_task_identifier(identifier)
        revision = _revision(expected_revision)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, revision FROM tasks WHERE identifier=?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise OperationalNotFoundError("The task was not found.")
            if row["revision"] != revision:
                raise OperationalStaleRevisionError(
                    "The task changed; refresh and try again."
                )
            if row["status"] not in {"completed", "cancelled"}:
                raise OperationalConflictError(
                    "Only completed or cancelled task history can be permanently deleted."
                )
            if connection.execute(
                "SELECT 1 FROM reminders WHERE task_id=? LIMIT 1",
                (task_id,),
            ).fetchone() is not None:
                raise OperationalConflictError(
                    "This task still has reminder history linked to it. Delete those reminders first, then delete the task."
                )
            cursor = connection.execute(
                "DELETE FROM tasks WHERE identifier=? AND revision=? "
                "AND status IN ('completed','cancelled')",
                (task_id, revision),
            )
            self._require_updated(cursor, "task")
            self._bump(connection)
        self._verify_task_deleted(task_id)

    def delete_historical_reminder(
        self,
        identifier: object,
        *,
        expected_revision: object,
    ) -> None:
        """Permanently delete one resolved reminder and its delivery row."""

        reminder_id = validate_reminder_identifier(identifier)
        revision = _revision(expected_revision)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, revision FROM reminders WHERE identifier=?",
                (reminder_id,),
            ).fetchone()
            if row is None:
                raise OperationalNotFoundError("The reminder was not found.")
            if row["revision"] != revision:
                raise OperationalStaleRevisionError(
                    "The reminder changed; refresh and try again."
                )
            if row["status"] not in {"dismissed", "completed", "cancelled"}:
                raise OperationalConflictError(
                    "Only resolved reminder history can be permanently deleted."
                )
            connection.execute(
                "DELETE FROM reminder_deliveries WHERE reminder_id=?",
                (reminder_id,),
            )
            cursor = connection.execute(
                "DELETE FROM reminders WHERE identifier=? AND revision=? "
                "AND status IN ('dismissed','completed','cancelled')",
                (reminder_id, revision),
            )
            self._require_updated(cursor, "reminder")
            self._bump(connection)
        self._verify_reminder_deleted(reminder_id)

    def update_task(
        self,
        identifier: object,
        *,
        expected_revision: object,
        description: object,
        due_start_utc: object = None,
        due_end_utc: object = None,
        due_timezone: object = None,
    ) -> TaskRecord:
        item = validate_task_identifier(identifier)
        expected_revision = _revision(expected_revision)
        text = _text(description, "Task description")
        start, end, zone = _schedule(due_start_utc, due_end_utc, due_timezone, optional=True)
        current = self.get_task(item)
        if current.revision != expected_revision:
            raise OperationalStaleRevisionError("The task changed; refresh and try again.")
        if current.status != "open":
            raise OperationalConflictError("Only an open task can be edited.")
        if (current.description, current.due_start_utc, current.due_end_utc, current.due_timezone) == (text, start, end, zone):
            return current
        stamp = self._next_stamp(current.updated_at_utc)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE tasks SET description=?, due_start_utc=?, due_end_utc=?, due_timezone=?, updated_at_utc=?, revision=revision+1 WHERE identifier=? AND revision=? AND status='open'",
                (text, start, end, zone, stamp, item, expected_revision),
            )
            self._require_updated(cursor, "task")
            self._bump(connection)
        return self._verify_task(replace(
            current,
            description=text,
            due_start_utc=start,
            due_end_utc=end,
            due_timezone=zone,
            updated_at_utc=stamp,
            revision=expected_revision + 1,
        ))

    def complete_task(self, identifier: object, *, expected_revision: object) -> TaskRecord:
        return self._resolve_task(identifier, expected_revision, "completed")

    def cancel_task(self, identifier: object, *, expected_revision: object) -> TaskRecord:
        return self._resolve_task(identifier, expected_revision, "cancelled")

    def _resolve_task(self, identifier: object, expected_revision: object, status_value: str) -> TaskRecord:
        item = validate_task_identifier(identifier)
        expected = _revision(expected_revision)
        current = self.get_task(item)
        if current.status == status_value:
            return current
        if current.revision != expected:
            raise OperationalStaleRevisionError("The task changed; refresh and try again.")
        if current.status != "open":
            raise OperationalConflictError("The task cannot make that transition.")
        stamp = self._next_stamp(current.updated_at_utc)
        completed = stamp if status_value == "completed" else None
        cancelled = stamp if status_value == "cancelled" else None
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE tasks SET status=?, updated_at_utc=?, completed_at_utc=?, cancelled_at_utc=?, revision=revision+1 WHERE identifier=? AND revision=? AND status='open'",
                (status_value, stamp, completed, cancelled, item, expected),
            )
            self._require_updated(cursor, "task")
            self._bump(connection)
        return self._verify_task(replace(
            current,
            status=status_value,
            updated_at_utc=stamp,
            completed_at_utc=completed,
            cancelled_at_utc=cancelled,
            revision=expected + 1,
        ))

    def update_reminder(
        self,
        identifier: object,
        *,
        expected_revision: object,
        reminder_text: object,
        scheduled_start_utc: object,
        scheduled_timezone: object,
        scheduled_end_utc: object = None,
    ) -> ReminderRecord:
        item = validate_reminder_identifier(identifier)
        expected = _revision(expected_revision)
        text = _text(reminder_text, "Reminder text")
        start, end, zone = _schedule(scheduled_start_utc, scheduled_end_utc, scheduled_timezone, optional=False)
        current = self.get_reminder(item)
        if current.revision != expected:
            raise OperationalStaleRevisionError("The reminder changed; refresh and try again.")
        if current.status not in {"scheduled", "due"}:
            raise OperationalConflictError("A resolved reminder cannot be changed.")
        target = (text, start, end, zone)
        if target == (current.reminder_text, current.scheduled_start_utc, current.scheduled_end_utc, current.scheduled_timezone) and current.status == "scheduled":
            return current
        stamp = self._next_stamp(current.updated_at_utc)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE reminders SET reminder_text=?, status='scheduled', scheduled_start_utc=?, scheduled_end_utc=?, scheduled_timezone=?, updated_at_utc=?, became_due_at_utc=NULL, resolved_at_utc=NULL, resolution=NULL, revision=revision+1 WHERE identifier=? AND revision=? AND status IN ('scheduled','due')",
                (text, start, end, zone, stamp, item, expected),
            )
            self._require_updated(cursor, "reminder")
            connection.execute("DELETE FROM reminder_deliveries WHERE reminder_id=?", (item,))
            self._bump(connection)
        return self._verify_reminder(replace(
            current,
            reminder_text=text,
            status="scheduled",
            scheduled_start_utc=start,
            scheduled_end_utc=end,
            scheduled_timezone=zone,
            updated_at_utc=stamp,
            became_due_at_utc=None,
            resolved_at_utc=None,
            resolution=None,
            revision=expected + 1,
        ))

    def delay_reminder(
        self,
        identifier: object,
        *,
        expected_revision: object,
        scheduled_start_utc: object,
        scheduled_timezone: object,
        scheduled_end_utc: object = None,
    ) -> ReminderRecord:
        current = self.get_reminder(identifier)
        return self.update_reminder(
            current.identifier,
            expected_revision=expected_revision,
            reminder_text=current.reminder_text,
            scheduled_start_utc=scheduled_start_utc,
            scheduled_end_utc=scheduled_end_utc,
            scheduled_timezone=scheduled_timezone,
        )

    def dismiss_reminder(self, identifier: object, *, expected_revision: object) -> ReminderRecord:
        return self._resolve_reminder(identifier, expected_revision, "dismissed", "dismissed")

    def cancel_reminder(self, identifier: object, *, expected_revision: object) -> ReminderRecord:
        return self._resolve_reminder(identifier, expected_revision, "cancelled", "cancelled")

    def done_reminder(self, identifier: object, *, expected_revision: object) -> ReminderRecord:
        item = validate_reminder_identifier(identifier)
        expected = _revision(expected_revision)
        current = self.get_reminder(item)
        expected_resolution = "task_completed" if current.task_id else "completed"
        if current.status == "completed" and current.resolution == expected_resolution:
            return current
        if current.revision != expected:
            raise OperationalStaleRevisionError("The reminder changed; refresh and try again.")
        if current.status not in {"scheduled", "due"}:
            raise OperationalConflictError("The reminder is already resolved.")
        stamp = self._next_stamp(current.updated_at_utc)
        expected_task: TaskRecord | None = None
        with closing(self._connect()) as connection, connection:
            if current.task_id is not None:
                row = connection.execute("SELECT * FROM tasks WHERE identifier=?", (current.task_id,)).fetchone()
                if row is None:
                    raise OperationalCorruptError("The linked task is missing.")
                task = _task(row)
                if task.status == "cancelled":
                    raise OperationalConflictError("A cancelled linked task cannot be completed.")
                if task.status == "open":
                    task_stamp = _later_stamp(stamp, task.updated_at_utc)
                    cursor = connection.execute(
                        "UPDATE tasks SET status='completed', updated_at_utc=?, completed_at_utc=?, revision=revision+1 WHERE identifier=? AND revision=? AND status='open'",
                        (task_stamp, task_stamp, task.identifier, task.revision),
                    )
                    self._require_updated(cursor, "linked task")
                    self._bump(connection)
                    expected_task = replace(
                        task,
                        status="completed",
                        updated_at_utc=task_stamp,
                        completed_at_utc=task_stamp,
                        revision=task.revision + 1,
                    )
            cursor = connection.execute(
                "UPDATE reminders SET status='completed', updated_at_utc=?, resolved_at_utc=?, resolution=?, revision=revision+1 WHERE identifier=? AND revision=? AND status IN ('scheduled','due')",
                (stamp, stamp, expected_resolution, item, expected),
            )
            self._require_updated(cursor, "reminder")
            self._bump(connection)
        expected_reminder = replace(
            current,
            status="completed",
            updated_at_utc=stamp,
            resolved_at_utc=stamp,
            resolution=expected_resolution,
            revision=expected + 1,
        )
        if expected_task is not None:
            self._verify_task(expected_task)
        return self._verify_reminder(expected_reminder)

    def _resolve_reminder(self, identifier: object, expected_revision: object, status_value: str, resolution: str) -> ReminderRecord:
        item = validate_reminder_identifier(identifier)
        expected = _revision(expected_revision)
        current = self.get_reminder(item)
        if current.status == status_value and current.resolution == resolution:
            return current
        if current.revision != expected:
            raise OperationalStaleRevisionError("The reminder changed; refresh and try again.")
        if current.status not in {"scheduled", "due"}:
            raise OperationalConflictError("The reminder is already resolved.")
        stamp = self._next_stamp(current.updated_at_utc)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE reminders SET status=?, updated_at_utc=?, resolved_at_utc=?, resolution=?, revision=revision+1 WHERE identifier=? AND revision=? AND status IN ('scheduled','due')",
                (status_value, stamp, stamp, resolution, item, expected),
            )
            self._require_updated(cursor, "reminder")
            self._bump(connection)
        return self._verify_reminder(replace(
            current,
            status=status_value,
            updated_at_utc=stamp,
            resolved_at_utc=stamp,
            resolution=resolution,
            revision=expected + 1,
        ))

    def mark_due(self, detected_at: datetime) -> tuple[ReminderRecord, ...]:
        stamp = format_utc_timestamp(detected_at)
        expected_reminders: list[ReminderRecord] = []
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE status='scheduled' AND scheduled_start_utc <= ? ORDER BY scheduled_start_utc, identifier",
                (stamp,),
            ).fetchall()
            for row in rows:
                current = _reminder(row)
                update_stamp = _later_stamp(stamp, current.updated_at_utc)
                cursor = connection.execute(
                    "UPDATE reminders SET status='due', updated_at_utc=?, became_due_at_utc=?, revision=revision+1 WHERE identifier=? AND status='scheduled'",
                    (update_stamp, stamp, current.identifier),
                )
                if cursor.rowcount != 1:
                    continue
                expected_reminders.append(replace(
                    current,
                    status="due",
                    updated_at_utc=update_stamp,
                    became_due_at_utc=stamp,
                    revision=current.revision + 1,
                ))
                event_identifier = self._unique_event(connection)
                connection.execute(
                    "INSERT INTO reminder_deliveries VALUES (?, ?, 'pending', ?, NULL, NULL)",
                    (current.identifier, event_identifier, stamp),
                )
                self._bump(connection)
        return tuple(self._verify_reminder(expected) for expected in expected_reminders)

    def next_scheduled_utc(self) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT scheduled_start_utc FROM reminders WHERE status='scheduled' ORDER BY scheduled_start_utc, identifier LIMIT 1"
            ).fetchone()
        return None if row is None else _timestamp(row[0])

    def attention(self) -> AttentionState:
        with closing(self._connect()) as connection:
            revision = connection.execute("SELECT revision FROM operational_state WHERE singleton=1").fetchone()[0]
            due = connection.execute(
                "SELECT * FROM reminders WHERE status='due' ORDER BY scheduled_start_utc, identifier"
            ).fetchall()
            next_row = connection.execute(
                "SELECT scheduled_start_utc FROM reminders WHERE status='scheduled' ORDER BY scheduled_start_utc, identifier LIMIT 1"
            ).fetchone()
        reminders = tuple(_reminder(row) for row in due)
        return AttentionState(revision, reminders[0] if reminders else None, max(0, len(reminders)-1), None if next_row is None else _timestamp(next_row[0]))

    def pending_deliveries(self) -> tuple[ReminderDelivery, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT d.* FROM reminder_deliveries d JOIN reminders r ON r.identifier=d.reminder_id WHERE d.state='pending' AND r.status='due' ORDER BY r.scheduled_start_utc, r.identifier"
            ).fetchall()
        return tuple(_delivery(row) for row in rows)

    def mark_delivery_archived(self, reminder_id: object, event_identifier: object, *, chat_id: object) -> ReminderDelivery:
        reminder = validate_reminder_identifier(reminder_id)
        event = validate_event_identifier(event_identifier)
        if not isinstance(chat_id, str) or not re.fullmatch(r"chat-[0-9a-f]{32}", chat_id):
            raise OperationalValidationError("A valid chat identifier is required.")
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM reminder_deliveries WHERE reminder_id=?", (reminder,)).fetchone()
            if row is None:
                raise OperationalNotFoundError("The reminder delivery was not found.")
            current = _delivery(row)
            if current.event_identifier != event:
                raise OperationalConflictError("The reminder delivery event does not match.")
            if current.state == "archived":
                if current.chat_id != chat_id:
                    raise OperationalConflictError("The reminder delivery was archived elsewhere.")
                return current
            stamp = _later_stamp(
                format_utc_timestamp(self._clock()), current.queued_at_utc
            )
            connection.execute(
                "UPDATE reminder_deliveries SET state='archived', archived_at_utc=?, chat_id=? WHERE reminder_id=? AND state='pending'",
                (stamp, chat_id, reminder),
            )
            self._bump(connection)
        row = self._delivery(reminder)
        if row.state != "archived" or row.chat_id != chat_id:
            raise OperationalVerificationError("The reminder delivery could not be verified.")
        return row

    def delivery(self, reminder_id: object) -> ReminderDelivery:
        return self._delivery(validate_reminder_identifier(reminder_id))

    def _delivery(self, reminder_id: str) -> ReminderDelivery:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM reminder_deliveries WHERE reminder_id=?", (reminder_id,)).fetchone()
        if row is None:
            raise OperationalNotFoundError("The reminder delivery was not found.")
        return _delivery(row)

    @staticmethod
    def _bump(connection: sqlite3.Connection) -> None:
        cursor = connection.execute("UPDATE operational_state SET revision=revision+1 WHERE singleton=1")
        if cursor.rowcount != 1:
            raise OperationalCorruptError("Tori's operational state is invalid.")

    @staticmethod
    def _require_updated(cursor: sqlite3.Cursor, label: str) -> None:
        if cursor.rowcount != 1:
            raise OperationalStaleRevisionError(f"The {label} changed; refresh and try again.")

    def _next_stamp(self, previous: str) -> str:
        return _later_stamp(format_utc_timestamp(self._clock()), previous)

    def _unique_event(self, connection: sqlite3.Connection) -> str:
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            value = validate_event_identifier(self._identifier_factory("event"))
            if connection.execute("SELECT 1 FROM reminder_deliveries WHERE event_identifier=?", (value,)).fetchone() is None:
                return value
        raise OperationalConflictError("Could not generate a unique delivery event identifier.")

    def _task_exists(self, identifier: str) -> bool:
        try:
            self.get_task(identifier)
        except OperationalNotFoundError:
            return False
        return True

    def _reminder_exists(self, identifier: str) -> bool:
        try:
            self.get_reminder(identifier)
        except OperationalNotFoundError:
            return False
        return True

    def _verify_task(self, expected: TaskRecord) -> TaskRecord:
        try:
            actual = self.get_task(expected.identifier)
        except OperationalError as exc:
            raise OperationalVerificationError("The task was saved but could not be verified.") from exc
        if actual != expected:
            raise OperationalVerificationError("The task was saved but could not be verified.")
        return actual

    def _verify_reminder(self, expected: ReminderRecord) -> ReminderRecord:
        try:
            actual = self.get_reminder(expected.identifier)
        except OperationalError as exc:
            raise OperationalVerificationError("The reminder was saved but could not be verified.") from exc
        if actual != expected:
            raise OperationalVerificationError("The reminder was saved but could not be verified.")
        return actual

    def _verify_task_deleted(self, identifier: str) -> None:
        with closing(self._connect()) as connection:
            task = connection.execute(
                "SELECT 1 FROM tasks WHERE identifier=?", (identifier,)
            ).fetchone()
        if task is not None:
            raise OperationalVerificationError(
                "The task deletion could not be verified."
            )

    def _verify_reminder_deleted(self, identifier: str) -> None:
        with closing(self._connect()) as connection:
            reminder = connection.execute(
                "SELECT 1 FROM reminders WHERE identifier=?", (identifier,)
            ).fetchone()
            delivery = connection.execute(
                "SELECT 1 FROM reminder_deliveries WHERE reminder_id=?",
                (identifier,),
            ).fetchone()
        if reminder is not None or delivery is not None:
            raise OperationalVerificationError(
                "The reminder deletion could not be verified."
            )

    def _connect(self) -> _OperationalConnection:
        parent: int | None = None
        database: int | None = None
        connection: _OperationalConnection | None = None
        try:
            parent, name = self._open_parent(create=True)
            sidecars = [_stat_at(parent, name + suffix) for suffix in ("-journal", "-wal", "-shm")]
            existing = _stat_at(parent, name)
            flags = os.O_RDWR | _no_follow() | getattr(os, "O_CLOEXEC", 0)
            if existing is None:
                if any(sidecar is not None for sidecar in sidecars):
                    raise OSError("orphaned operational sidecar")
                self._initialize_then_publish(parent, name, flags)
                existing = _stat_at(parent, name)
            if existing is None or not stat.S_ISREG(existing.st_mode):
                raise OSError("unsafe operational database entry")
            database = os.open(name, flags, dir_fd=parent)
            if not _same_file(existing, os.fstat(database)):
                raise OSError("operational database changed during open")
            sqlite_path = f"/proc/self/fd/{parent}/{name}"
            readonly = sqlite3.connect(
                "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1",
                uri=True,
            )
            try:
                self._validate_schema(readonly)
            finally:
                readonly.close()
            connection = sqlite3.connect(sqlite_path, factory=_OperationalConnection, timeout=5.0)
            current = _stat_at(parent, name)
            if current is None or not _same_file(os.fstat(database), current):
                raise OSError("operational database changed during SQLite open")
            self._validate_schema(connection)
            self._apply_settings(connection)
            connection.row_factory = sqlite3.Row
            connection._safe_descriptors = (parent, database)
            return connection
        except OperationalError as exc:
            failure: BaseException = exc
        except sqlite3.DatabaseError:
            failure = OperationalCorruptError("Tori's operational database is corrupt or invalid; it was preserved.")
        except (OSError, sqlite3.Error):
            failure = OperationalUnavailableError("Tori's operational database is unavailable.")
        if connection is not None:
            connection.close()
        for descriptor in (database, parent):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise failure

    def _initialize_then_publish(self, parent: int, name: str, flags: int) -> None:
        temporary = f".{name}.incomplete-{secrets.token_hex(16)}"
        descriptor = os.open(temporary, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        published = False
        connection: sqlite3.Connection | None = None
        try:
            original = os.fstat(descriptor)
            sqlite_path = f"/proc/self/fd/{parent}/{temporary}"
            connection = sqlite3.connect(sqlite_path)
            self._apply_settings(connection)
            with connection:
                for sql in (_METADATA_SQL, _STATE_SQL, _TASKS_SQL, _REMINDERS_SQL, _DELIVERIES_SQL, _TASK_INDEX_SQL, _DUE_INDEX_SQL, _TASK_REMINDER_INDEX_SQL):
                    connection.execute(sql)
                connection.execute("INSERT INTO operational_metadata VALUES ('schema_version', ?)", (str(OPERATIONAL_SCHEMA_VERSION),))
                connection.execute("INSERT INTO operational_state VALUES (1, 1)")
            self._validate_schema(connection)
            connection.close()
            connection = None
            if any(_stat_at(parent, temporary + suffix) is not None for suffix in ("-journal", "-wal", "-shm")):
                raise OSError("initialization sidecar exists")
            if not _same_file(original, _stat_at(parent, temporary)):
                raise OSError("initialization entry changed")
            os.fsync(descriptor)
            _rename_noreplace(parent, temporary, name)
            published = True
            os.fsync(parent)
        except BaseException as exc:
            if published:
                raise
            raise OperationalUnavailableError(
                f"Operational initialization failed; isolated artifact {temporary!r} was preserved."
            ) from exc
        finally:
            if connection is not None:
                connection.close()
            os.close(descriptor)

    def _open_parent(self, *, create: bool) -> tuple[int, str]:
        raw = os.fspath(self._path)
        if not isinstance(raw, str) or "\x00" in raw or ".." in Path(raw).parts:
            raise OperationalUnavailableError("The operational path is unsafe.")
        absolute = Path(os.path.abspath(os.path.normpath(raw)))
        if not absolute.name:
            raise OperationalUnavailableError("The operational path is unsafe.")
        flags = os.O_RDONLY | _directory() | _no_follow() | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open("/", flags)
        try:
            for part in absolute.parent.parts[1:]:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=descriptor)
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    os.close(child)
                    raise OSError("unsafe operational ancestor")
                os.close(descriptor)
                descriptor = child
            return descriptor, absolute.name
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _apply_settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA journal_mode=DELETE")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        expected_sql = {
            "operational_metadata": _METADATA_SQL,
            "operational_state": _STATE_SQL,
            "tasks": _TASKS_SQL,
            "reminders": _REMINDERS_SQL,
            "reminder_deliveries": _DELIVERIES_SQL,
            "tasks_status_update_index": _TASK_INDEX_SQL,
            "reminders_due_scan_index": _DUE_INDEX_SQL,
            "reminders_task_status_schedule_index": _TASK_REMINDER_INDEX_SQL,
        }
        actual = {
            name: sql for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_autoindex_%'"
            ) if kind in {"table", "index"}
        }
        if set(actual) != set(expected_sql) or any(
            not isinstance(actual[name], str) or _normalize_sql(actual[name]) != _normalize_sql(sql)
            for name, sql in expected_sql.items()
        ):
            raise OperationalCorruptError("Tori's operational database has an invalid schema; it was preserved.")
        unsupported = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1"
        ).fetchone()
        if unsupported is not None:
            raise OperationalCorruptError("Tori's operational database has unexpected schema objects.")
        expected_columns = {
            "operational_metadata": ("key", "value"),
            "operational_state": ("singleton", "revision"),
            "tasks": (
                "identifier", "description", "status", "due_start_utc", "due_end_utc",
                "due_timezone", "created_at_utc", "updated_at_utc", "completed_at_utc",
                "cancelled_at_utc", "revision",
            ),
            "reminders": (
                "identifier", "task_id", "reminder_text", "status",
                "scheduled_start_utc", "scheduled_end_utc", "scheduled_timezone",
                "created_at_utc", "updated_at_utc", "became_due_at_utc",
                "resolved_at_utc", "resolution", "revision",
            ),
            "reminder_deliveries": (
                "reminder_id", "event_identifier", "state", "queued_at_utc",
                "archived_at_utc", "chat_id",
            ),
        }
        for table, columns in expected_columns.items():
            if tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})")) != columns:
                raise OperationalCorruptError("Tori's operational database has invalid columns.")
        expected_user_indexes = {
            "tasks_status_update_index",
            "reminders_due_scan_index",
            "reminders_task_status_schedule_index",
        }
        actual_user_indexes = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            )
        }
        if actual_user_indexes != expected_user_indexes:
            raise OperationalCorruptError("Tori's operational database has invalid indexes.")
        foreign_keys = {
            (table, row[2], row[3], row[4], row[5], row[6])
            for table in ("reminders", "reminder_deliveries")
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        }
        if foreign_keys != {
            ("reminders", "tasks", "task_id", "identifier", "NO ACTION", "NO ACTION"),
            ("reminder_deliveries", "reminders", "reminder_id", "identifier", "NO ACTION", "NO ACTION"),
        }:
            raise OperationalCorruptError("Tori's operational database has invalid foreign keys.")
        metadata = connection.execute("SELECT key,value FROM operational_metadata").fetchall()
        if len(metadata) != 1 or tuple(metadata[0]) != ("schema_version", str(OPERATIONAL_SCHEMA_VERSION)):
            if len(metadata) == 1 and metadata[0][0] == "schema_version" and isinstance(metadata[0][1], str) and metadata[0][1].isdigit():
                raise OperationalVersionError(
                    f"Operational schema version {metadata[0][1]} is unsupported; it was not modified."
                )
            raise OperationalCorruptError("Tori's operational schema metadata is invalid.")
        state = connection.execute("SELECT singleton,revision FROM operational_state").fetchall()
        if len(state) != 1 or state[0][0] != 1 or isinstance(state[0][1], bool) or not isinstance(state[0][1], int) or state[0][1] < 1:
            raise OperationalCorruptError("Tori's operational state is invalid.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise OperationalCorruptError("Tori's operational foreign-key state is invalid.")
        for row in connection.execute("SELECT * FROM tasks"):
            _task(row)
        for row in connection.execute("SELECT * FROM reminders"):
            _reminder(row)
        for row in connection.execute("SELECT * FROM reminder_deliveries"):
            _delivery(row)


def validate_task_identifier(value: object) -> str:
    if not isinstance(value, str) or not _TASK_ID.fullmatch(value):
        raise OperationalValidationError("Task identifiers are invalid.")
    return value


def validate_reminder_identifier(value: object) -> str:
    if not isinstance(value, str) or not _REMINDER_ID.fullmatch(value):
        raise OperationalValidationError("Reminder identifiers are invalid.")
    return value


def validate_event_identifier(value: object) -> str:
    if not isinstance(value, str) or not _EVENT_ID.fullmatch(value):
        raise OperationalValidationError("Application event identifiers are invalid.")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > MAX_DESCRIPTION_LENGTH or "\x00" in value or any(unicodedata.category(c) in {"Cs", "Zl", "Zp"} for c in value):
        raise OperationalValidationError(f"{label} must contain safe nonempty text.")
    return value


def _timestamp(value: object) -> str:
    try:
        parse_utc_timestamp(value)
    except ValueError as exc:
        raise OperationalValidationError("Operational timestamps must be UTC Z timestamps.") from exc
    assert isinstance(value, str)
    return value


def _timezone(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "/" not in value or len(value) > 255:
        raise OperationalValidationError("A valid IANA timezone is required.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise OperationalValidationError("A valid IANA timezone is required.") from exc
    return value


def _schedule(start: object, end: object, zone: object, *, optional: bool) -> tuple[str | None, str | None, str | None]:
    if start is None:
        if optional and end is None and zone is None:
            return None, None, None
        raise OperationalValidationError("A schedule start and timezone are required.")
    first = _timestamp(start)
    last = None if end is None else _timestamp(end)
    timezone_name = _timezone(zone)
    if last is not None and last < first:
        raise OperationalValidationError("A schedule window cannot end before it starts.")
    return first, last, timezone_name


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OperationalValidationError("Expected revision must be a positive integer.")
    return value


def _statuses(values: Sequence[str] | None, allowed: frozenset[str]) -> tuple[str, ...]:
    if values is None:
        return tuple(sorted(allowed))
    if isinstance(values, (str, bytes)):
        raise OperationalValidationError("Statuses must be a sequence.")
    result = tuple(dict.fromkeys(values))
    if not result or any(value not in allowed for value in result):
        raise OperationalValidationError("A status filter is invalid.")
    return result


def _task(row: Sequence[object]) -> TaskRecord:
    try:
        item = TaskRecord(*row)
        validate_task_identifier(item.identifier)
        _text(item.description, "Task description")
        if item.status not in TASK_STATUSES:
            raise ValueError
        _schedule(item.due_start_utc, item.due_end_utc, item.due_timezone, optional=True)
        for stamp in (item.created_at_utc, item.updated_at_utc):
            _timestamp(stamp)
        if item.completed_at_utc is not None:
            _timestamp(item.completed_at_utc)
        if item.cancelled_at_utc is not None:
            _timestamp(item.cancelled_at_utc)
        _revision(item.revision)
        if item.created_at_utc > item.updated_at_utc or (item.status == "open" and (item.completed_at_utc or item.cancelled_at_utc)) or (item.status == "completed" and (not item.completed_at_utc or item.cancelled_at_utc)) or (item.status == "cancelled" and (item.completed_at_utc or not item.cancelled_at_utc)):
            raise ValueError
        return item
    except (TypeError, ValueError, OperationalValidationError) as exc:
        raise OperationalCorruptError("Tori's operational database contains an invalid task.") from exc


def _reminder(row: Sequence[object]) -> ReminderRecord:
    try:
        item = ReminderRecord(*row)
        validate_reminder_identifier(item.identifier)
        if item.task_id is not None:
            validate_task_identifier(item.task_id)
        _text(item.reminder_text, "Reminder text")
        if item.status not in REMINDER_STATUSES:
            raise ValueError
        _schedule(item.scheduled_start_utc, item.scheduled_end_utc, item.scheduled_timezone, optional=False)
        for stamp in (item.created_at_utc, item.updated_at_utc):
            _timestamp(stamp)
        if item.became_due_at_utc is not None:
            _timestamp(item.became_due_at_utc)
        if item.resolved_at_utc is not None:
            _timestamp(item.resolved_at_utc)
        if item.resolution is not None and item.resolution not in REMINDER_RESOLUTIONS:
            raise ValueError
        _revision(item.revision)
        if item.status == "scheduled" and any((item.became_due_at_utc, item.resolved_at_utc, item.resolution)):
            raise ValueError
        if item.status == "due" and (not item.became_due_at_utc or item.resolved_at_utc or item.resolution):
            raise ValueError
        if item.status in {"dismissed", "completed", "cancelled"} and (not item.resolved_at_utc or not item.resolution):
            raise ValueError
        return item
    except (TypeError, ValueError, OperationalValidationError) as exc:
        raise OperationalCorruptError("Tori's operational database contains an invalid reminder.") from exc


def _delivery(row: Sequence[object]) -> ReminderDelivery:
    try:
        item = ReminderDelivery(*row)
        validate_reminder_identifier(item.reminder_id)
        validate_event_identifier(item.event_identifier)
        if item.state not in {"pending", "archived"}:
            raise ValueError
        _timestamp(item.queued_at_utc)
        if item.archived_at_utc is not None:
            _timestamp(item.archived_at_utc)
        if item.state == "pending" and (item.archived_at_utc is not None or item.chat_id is not None):
            raise ValueError
        if item.state == "archived" and (item.archived_at_utc is None or not isinstance(item.chat_id, str) or not re.fullmatch(r"chat-[0-9a-f]{32}", item.chat_id)):
            raise ValueError
        return item
    except (TypeError, ValueError, OperationalValidationError) as exc:
        raise OperationalCorruptError("Tori's operational database contains an invalid delivery.") from exc


def _identifier(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


def _later_stamp(candidate: str, previous: str) -> str:
    first = parse_utc_timestamp(candidate)
    prior = parse_utc_timestamp(previous)
    if first > prior:
        return candidate
    return format_utc_timestamp(prior.replace(microsecond=0) + timedelta(seconds=1))


def _normalize_sql(value: str) -> str:
    return "".join(value.lower().split()).rstrip(";")


def _no_follow() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise OperationalUnavailableError("Safe no-follow opens are unavailable.")
    return os.O_NOFOLLOW


def _directory() -> int:
    if not hasattr(os, "O_DIRECTORY"):
        raise OperationalUnavailableError("Safe directory opens are unavailable.")
    return os.O_DIRECTORY


def _stat_at(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_file(first: os.stat_result, second: os.stat_result | None) -> bool:
    return second is not None and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _rename_noreplace(parent: int, source: str, destination: str) -> None:
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as exc:
        raise OSError(errno.ENOSYS, "renameat2 is required") from exc
    function.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    if function(parent, os.fsencode(source), parent, os.fsencode(destination), 1) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def _database_error(error: sqlite3.Error) -> OperationalError:
    message = str(error).lower()
    if "malformed" in message or "not a database" in message:
        return OperationalCorruptError("Tori's operational database is corrupt; it was preserved.")
    return OperationalUnavailableError("Tori's operational database is unavailable.")
