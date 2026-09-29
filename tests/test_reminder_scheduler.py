from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from tori.reminder_scheduler import ReminderScheduler
from tori.tasks import SQLiteOperationalStore
from tori.time_context import FakeClock, format_utc_timestamp


class ReminderSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = FakeClock(datetime(2026, 8, 10, 12, tzinfo=timezone.utc))
        self.store = SQLiteOperationalStore(
            Path(self.temporary.name) / "tasks.db", clock=self.clock
        )

    def add(self, minutes: int, text: str = "test"):
        return self.store.create_reminder(
            text,
            scheduled_start_utc=format_utc_timestamp(self.clock() + timedelta(minutes=minutes)),
            scheduled_timezone="America/Chicago",
        )

    def test_startup_catchup_records_actual_detection_and_outbox(self) -> None:
        reminder = self.add(5)
        self.clock.advance(timedelta(minutes=20))
        scheduler = ReminderScheduler(self.store, clock=self.clock, recheck_seconds=1)
        due = scheduler.scan_once()
        self.assertEqual([item.identifier for item in due], [reminder.identifier])
        loaded = self.store.get_reminder(reminder.identifier)
        self.assertEqual(loaded.became_due_at_utc, format_utc_timestamp(self.clock()))
        self.assertGreater(loaded.became_due_at_utc, loaded.scheduled_start_utc)
        self.assertEqual(len(self.store.pending_deliveries()), 1)

    def test_wake_for_new_schedule_and_clean_stop(self) -> None:
        observed = []
        scheduler = ReminderScheduler(
            self.store,
            clock=self.clock,
            state_changed=lambda items: observed.extend(items),
            recheck_seconds=0.2,
        )
        scheduler.start()
        reminder = self.add(1)
        self.clock.advance(timedelta(minutes=2))
        scheduler.notify_schedule_changed()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not observed:
            time.sleep(0.01)
        scheduler.stop()
        self.assertFalse(scheduler.running)
        self.assertEqual([item.identifier for item in observed], [reminder.identifier])

    def test_duplicate_scans_cannot_duplicate_delivery(self) -> None:
        reminder = self.add(0)
        first = ReminderScheduler(self.store, clock=self.clock).scan_once()
        second = ReminderScheduler(self.store, clock=self.clock).scan_once()
        self.assertEqual([item.identifier for item in first], [reminder.identifier])
        self.assertEqual(second, ())
        self.assertEqual(len(self.store.pending_deliveries()), 1)


if __name__ == "__main__":
    unittest.main()
