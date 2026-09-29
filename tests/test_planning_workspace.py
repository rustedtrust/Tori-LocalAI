from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from tori.planning import Event, PlanningReminder, PlanningRevision, RecurrenceRule, Task
from tori.planning_application import PlanningService
from tori.planning_workspace import PlanningWorkspaceProjection
from tori.time_context import TimeContext
from tests.test_planning_conversation import FakePlanningPort


class PlanningWorkspaceProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = FakePlanningPort()
        self.context = TimeContext(datetime(2026, 8, 26, 14, tzinfo=timezone.utc), "America/Chicago")
        self.projection = PlanningWorkspaceProjection(PlanningService(self.port))  # type: ignore[arg-type]

    def test_today_tasks_calendar_and_human_metadata_are_bounded(self) -> None:
        self.port.tasks["due"] = Task("due", "Call Mom", "calendar", due=datetime(2026, 8, 26, 22, tzinfo=timezone.utc), reminders=(PlanningReminder(timedelta(0), "Call Mom"),), revision=PlanningRevision("secret-etag"))
        self.port.tasks["old"] = Task("old", "Submit form", "calendar", due=date(2026, 8, 25), priority=2, revision=PlanningRevision("old-etag"))
        self.port.events["timed"] = Event("timed", "Dentist", "calendar", datetime(2026, 8, 26, 19, tzinfo=timezone.utc), datetime(2026, 8, 26, 20, tzinfo=timezone.utc), location="Clinic", reminders=(PlanningReminder(timedelta(minutes=-30), "Dentist"),), revision=PlanningRevision("event-etag"))
        self.port.events["all-day"] = Event("all-day", "Vacation", "calendar", date(2026, 8, 26), date(2026, 8, 27), all_day=True, revision=PlanningRevision("all-day-etag"))
        document = self.projection.document(self.context)
        self.assertTrue(document["available"])
        self.assertEqual({item["title"] for item in document["today"]["events"]}, {"Dentist", "Vacation"})
        self.assertEqual(document["today"]["due_tasks"][0]["reminders"], ["At due time"])
        self.assertTrue(document["today"]["overdue_tasks"][0]["overdue"])
        rendered = repr(document)
        for secret in ("secret-etag", "event-etag", "all-day-etag", "http://"):
            self.assertNotIn(secret, rendered)

    def test_upcoming_recurs_boundedly_and_external_edits_refresh(self) -> None:
        event = Event("weekly", "Bins", "calendar", datetime(2026, 8, 27, 14, tzinfo=timezone.utc), datetime(2026, 8, 27, 15, tzinfo=timezone.utc), recurrence=RecurrenceRule("FREQ=DAILY;COUNT=3"), revision=PlanningRevision("r1"))
        self.port.events[event.uid] = event
        first = self.projection.document(self.context)
        self.assertEqual(sum(item["title"] == "Bins" for item in first["upcoming"]["items"]), 3)
        self.port.events[event.uid] = replace(event, title="Externally renamed", revision=PlanningRevision("r2"))
        second = self.projection.document(self.context)
        self.assertIn("Externally renamed", repr(second))

    def test_timed_tomorrow_task_is_visible_in_open_and_upcoming_once(self) -> None:
        task = Task(
            "cookies", "Make cookies", "calendar",
            due=datetime(2026, 8, 27, 17, tzinfo=timezone.utc),
            revision=PlanningRevision("cookies-etag"),
        )
        self.port.tasks[task.uid] = task
        document = self.projection.document(self.context)
        self.assertEqual([item["title"] for item in document["tasks"]["open"]], ["Make cookies"])
        self.assertEqual([item["title"] for item in document["upcoming"]["items"]], ["Make cookies"])
        self.assertEqual(sum(item["title"] == "Make cookies" for item in document["upcoming"]["items"]), 1)

    def test_completed_filters_and_unavailable_state(self) -> None:
        self.port.tasks["open"] = Task("open", "Open", "calendar", revision=PlanningRevision("r1"))
        self.port.tasks["done"] = Task("done", "Done", "calendar", completed=True, completed_at=datetime(2026, 8, 25, tzinfo=timezone.utc), revision=PlanningRevision("r2"))
        document = self.projection.document(self.context)
        self.assertEqual([item["title"] for item in document["tasks"]["open"]], ["Open"])
        self.assertEqual([item["title"] for item in document["tasks"]["completed"]], ["Done"])
        self.port.available = False
        self.assertEqual(self.projection.document(self.context), {"available": False, "message": "Planning is currently unavailable."})


if __name__ == "__main__":
    unittest.main()
