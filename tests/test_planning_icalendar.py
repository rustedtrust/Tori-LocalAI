from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from tori.planning import Event, PlanningDataError, PlanningReminder, RecurrenceRule, Task
from tori.planning_icalendar import (
    deserialize_event, deserialize_task, serialize_event, serialize_task,
)


UTC = timezone.utc


class PlanningICalendarTests(unittest.TestCase):
    def test_vtodo_round_trip_preserves_recurrence_alarm_and_completion(self) -> None:
        task = Task(
            "task-1", "Weekly review", "tasks", description="Review the plan",
            start=datetime(2026, 8, 27, 14, tzinfo=UTC),
            due=datetime(2026, 8, 27, 15, tzinfo=UTC), priority=2,
            recurrence=RecurrenceRule("FREQ=WEEKLY;COUNT=4"),
            reminders=(PlanningReminder(timedelta(minutes=-30), "Weekly review"),),
        )
        encoded = serialize_task(task)
        self.assertIn("BEGIN:VTODO", encoded)
        self.assertIn("RRULE:FREQ=WEEKLY;COUNT=4", encoded)
        self.assertIn("BEGIN:VALARM", encoded)
        self.assertIn("TRIGGER:-PT30M", encoded)
        decoded = deserialize_task(encoded, collection_id="tasks", revision='"one"')
        self.assertEqual(replace(decoded, revision=None), task)
        self.assertEqual(decoded.revision.token, '"one"')

        completed = replace(
            task, completed=True, completed_at=datetime(2026, 8, 27, 16, tzinfo=UTC)
        )
        completed_decoded = deserialize_task(
            serialize_task(completed), collection_id="tasks"
        )
        self.assertTrue(completed_decoded.completed)
        self.assertEqual(completed_decoded.completed_at, completed.completed_at)

    def test_vevent_round_trip_preserves_timed_and_all_day_values(self) -> None:
        event = Event(
            "event-1", "Planning review", "calendar",
            datetime(2026, 8, 28, 15, tzinfo=UTC),
            datetime(2026, 8, 28, 16, tzinfo=UTC),
            description="Review", location="Desk",
            recurrence=RecurrenceRule("FREQ=DAILY;COUNT=3"),
            reminders=(PlanningReminder(timedelta(minutes=-30), "Planning review"),),
        )
        encoded = serialize_event(event)
        self.assertIn("BEGIN:VEVENT", encoded)
        self.assertIn("RRULE:FREQ=DAILY;COUNT=3", encoded)
        self.assertIn("TRIGGER:-PT30M", encoded)
        self.assertEqual(deserialize_event(encoded, collection_id="calendar"), event)

        all_day = Event(
            "event-2", "Day off", "calendar", date(2026, 8, 29), date(2026, 8, 30),
            all_day=True,
        )
        self.assertEqual(
            deserialize_event(serialize_event(all_day), collection_id="calendar"),
            all_day,
        )

    def test_at_due_time_alarm_round_trip_preserves_zero_relative_trigger(self) -> None:
        task = Task(
            "task-due-alarm", "Call Mom", "tasks",
            due=datetime(2026, 8, 27, 20, tzinfo=UTC),
            reminders=(PlanningReminder(timedelta(0), "Call Mom"),),
        )
        encoded = serialize_task(task)
        self.assertIn("TRIGGER:P0D", encoded)
        self.assertEqual(deserialize_task(encoded, collection_id="tasks"), task)

    def test_rejects_missing_components_and_unsupported_absolute_alarm(self) -> None:
        with self.assertRaises(PlanningDataError):
            deserialize_task("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", collection_id="tasks")
        absolute = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:event-1\r
SUMMARY:Event\r
DTSTART:20260827T150000Z\r
DTEND:20260827T160000Z\r
BEGIN:VALARM\r
ACTION:DISPLAY\r
TRIGGER:20260827T143000Z\r
DESCRIPTION:Event\r
END:VALARM\r
END:VEVENT\r
END:VCALENDAR\r
"""
        with self.assertRaisesRegex(PlanningDataError, "relative DISPLAY"):
            deserialize_event(absolute, collection_id="calendar")
