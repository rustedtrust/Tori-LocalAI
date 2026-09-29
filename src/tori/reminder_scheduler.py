"""A narrow application-owned scheduler for canonical reminders."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging

from .deadline_loop import DeadlineLoop
from .operator_observability import operator_event
from .tasks import OperationalError, ReminderRecord, SQLiteOperationalStore
from .time_context import parse_utc_timestamp


LOGGER = logging.getLogger(__name__)


class ReminderScheduler:
    """Move eligible reminders to due without invoking a model or transcript."""

    def __init__(
        self,
        store: SQLiteOperationalStore,
        *,
        clock: Callable[[], datetime] | None = None,
        state_changed: Callable[[tuple[ReminderRecord, ...]], None] | None = None,
        recheck_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state_changed = state_changed or (lambda _items: None)
        self._loop = DeadlineLoop(
            initialize=self._store.initialize,
            scan=lambda: self.scan_once(),
            next_deadline=self._next_deadline,
            clock=self._clock,
            handled_error=OperationalError,
            name="tori-reminder-scheduler",
            failure_message="The reminder scheduler could not access operational state safely.",
            recheck_seconds=recheck_seconds,
        )

    @property
    def running(self) -> bool:
        return self._loop.running

    @property
    def failed(self) -> bool:
        return self._loop.failed

    def start(self) -> None:
        self._loop.start()

    def notify_schedule_changed(self) -> None:
        self._loop.wake()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._loop.stop(timeout=timeout)

    def scan_once(self) -> tuple[ReminderRecord, ...]:
        """Perform one deterministic catch-up scan (also useful in tests)."""

        detected = self._clock()
        if not isinstance(detected, datetime) or detected.tzinfo is None:
            raise ValueError("Scheduler clocks must return aware datetimes.")
        due = self._store.mark_due(detected.astimezone(timezone.utc))
        if due:
            operator_event("reminder.due", result_count=len(due))
            self._state_changed(due)
        return due

    def _next_deadline(self) -> datetime | None:
        next_due = self._store.next_scheduled_utc()
        return None if next_due is None else parse_utc_timestamp(next_due)
