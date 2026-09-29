from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from tori.planning import (
    Event, PlanningAvailability, PlanningCollection, PlanningConflictError,
    PlanningNotFoundError, PlanningReminder, PlanningRevision, PlanningStatus,
    RecurrenceRule, Task,
)
from tori.planning_application import PlanningService
from tori.planning_conversation import (
    PlanningConversationError, PlanningConversationService, PlanningReference,
)
from tori.planning_reminder_bridge import ReminderBridgeResult
from tori.time_context import TimeContext


UTC = timezone.utc


class FakePlanningPort:
    def __init__(self) -> None:
        self.available = True
        self.tasks: dict[str, Task] = {}
        self.events: dict[str, Event] = {}
        self.revision = 0

    def status(self):  # type: ignore[no-untyped-def]
        return PlanningStatus(
            PlanningAvailability.AVAILABLE if self.available else PlanningAvailability.UNAVAILABLE,
            "Planning is available." if self.available else "Planning is unavailable.",
        )

    def list_collections(self):  # type: ignore[no-untyped-def]
        self._check()
        return (PlanningCollection("calendar", "Calendar", True, True),)

    def list_tasks(self, collection_id):  # type: ignore[no-untyped-def]
        self._check()
        return tuple(self.tasks.values())

    def list_events(self, collection_id):  # type: ignore[no-untyped-def]
        self._check()
        return tuple(self.events.values())

    def create_task(self, task):  # type: ignore[no-untyped-def]
        self._check(); self.revision += 1
        value = replace(task, revision=PlanningRevision(f"r{self.revision}"))
        self.tasks[value.uid] = value
        return value

    def get_task(self, collection_id, uid):  # type: ignore[no-untyped-def]
        self._check()
        if uid not in self.tasks: raise PlanningNotFoundError("missing")
        return self.tasks[uid]

    def update_task(self, task, *, expected_revision):  # type: ignore[no-untyped-def]
        current = self.get_task(task.collection_id, task.uid)
        if current.revision.token != expected_revision: raise PlanningConflictError("stale")
        self.revision += 1
        value = replace(task, revision=PlanningRevision(f"r{self.revision}"))
        self.tasks[value.uid] = value
        return value

    def delete_task(self, collection_id, uid, *, expected_revision):  # type: ignore[no-untyped-def]
        current = self.get_task(collection_id, uid)
        if current.revision.token != expected_revision: raise PlanningConflictError("stale")
        del self.tasks[uid]

    def create_event(self, event):  # type: ignore[no-untyped-def]
        self._check(); self.revision += 1
        value = replace(event, revision=PlanningRevision(f"r{self.revision}"))
        self.events[value.uid] = value
        return value

    def get_event(self, collection_id, uid):  # type: ignore[no-untyped-def]
        self._check()
        if uid not in self.events: raise PlanningNotFoundError("missing")
        return self.events[uid]

    def update_event(self, event, *, expected_revision):  # type: ignore[no-untyped-def]
        current = self.get_event(event.collection_id, event.uid)
        if current.revision.token != expected_revision: raise PlanningConflictError("stale")
        self.revision += 1
        value = replace(event, revision=PlanningRevision(f"r{self.revision}"))
        self.events[value.uid] = value
        return value

    def delete_event(self, collection_id, uid, *, expected_revision):  # type: ignore[no-untyped-def]
        current = self.get_event(collection_id, uid)
        if current.revision.token != expected_revision: raise PlanningConflictError("stale")
        del self.events[uid]

    def _check(self):  # type: ignore[no-untyped-def]
        if not self.available:
            from tori.planning import PlanningUnavailableError
            raise PlanningUnavailableError("offline")


class FakeBridge:
    def __init__(self) -> None:
        self.objects = []
        self.full = 0

    def reconcile_object(self, item):  # type: ignore[no-untyped-def]
        self.objects.append(item)
        return ReminderBridgeResult(True, created=(item.uid,))

    def reconcile(self):  # type: ignore[no-untyped-def]
        self.full += 1
        return ReminderBridgeResult(True, cancelled=("derived",))


class PlanningConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = FakePlanningPort()
        self.bridge = FakeBridge()
        self.context = TimeContext(datetime(2026, 8, 26, 14, tzinfo=UTC), "America/Chicago")
        self.counter = 0
        def uid():  # type: ignore[no-untyped-def]
            self.counter += 1
            return f"uid-{self.counter}"
        self.service = PlanningConversationService(
            PlanningService(self.port), reminder_bridge=self.bridge,  # type: ignore[arg-type]
            default_task_list="calendar", default_calendar="calendar",
            uid_factory=uid,
        )

    def add_task(self, title="Call Mom", *, due=None, completed=False):  # type: ignore[no-untyped-def]
        task = Task(
            f"task-{len(self.port.tasks)+1}", title, "calendar", due=due,
            completed=completed,
            completed_at=datetime(2026, 8, 25, 14, tzinfo=UTC) if completed else None,
            revision=PlanningRevision(f"seed-{len(self.port.tasks)+1}"),
        )
        self.port.tasks[task.uid] = task
        return task

    def add_event(self, title="Dentist", *, hour=19, reminder=False):  # type: ignore[no-untyped-def]
        event = Event(
            f"event-{len(self.port.events)+1}", title, "calendar",
            datetime(2026, 8, 27, hour, tzinfo=UTC),
            datetime(2026, 8, 27, hour + 1, tzinfo=UTC),
            reminders=(PlanningReminder(timedelta(minutes=-30), title),) if reminder else (),
            revision=PlanningRevision(f"event-seed-{len(self.port.events)+1}"),
        )
        self.port.events[event.uid] = event
        return event

    def test_today_upcoming_task_and_calendar_reads_are_compact(self) -> None:
        self.add_task(due=datetime(2026, 8, 26, 22, tzinfo=UTC))
        self.port.events["today"] = Event(
            "today", "Team meeting", "calendar",
            datetime(2026, 8, 26, 16, tzinfo=UTC),
            datetime(2026, 8, 26, 17, tzinfo=UTC),
            revision=PlanningRevision("today-r1"),
        )
        today = self.service.interpret("What do I have today?", time_context=self.context)
        self.assertIn("Today", today.text)
        self.assertIn("Team meeting", today.text)
        self.assertIn("Call Mom", today.text)
        upcoming = self.service.interpret("What's coming up this week?", time_context=self.context)
        self.assertIn("next 7 days", upcoming.text)
        tasks = self.service.interpret("What tasks are due?", time_context=self.context)
        self.assertIn("Open tasks", tasks.text)
        calendar = self.service.interpret("What's on my calendar Thursday?", time_context=self.context)
        self.assertIn("Thursday", calendar.text)

    def test_overdue_completed_and_external_read_refresh(self) -> None:
        task = self.add_task("Old bill", due=date(2026, 8, 25))
        self.add_task("Finished", completed=True)
        self.assertIn("Old bill", self.service.interpret("What tasks are overdue?", time_context=self.context).text)
        self.assertIn("Finished", self.service.interpret("Show me completed tasks", time_context=self.context).text)
        self.port.tasks[task.uid] = replace(task, title="Externally renamed bill")
        self.assertIn("Externally renamed", self.service.interpret("Show my todo list", time_context=self.context).text)

    def test_create_task_reminder_event_and_recurrence_proposals(self) -> None:
        task = self.service.interpret("Add buy filters to my todo list.", time_context=self.context)
        self.assertEqual(task.mutation.operation, "create_task")
        reminder = self.service.interpret("Remind me tomorrow at 3 to call Mom.", time_context=self.context)
        self.assertEqual(reminder.mutation.after.reminders[0].trigger, timedelta(0))
        dentist = self.service.interpret("Add dentist Thursday at 2.", time_context=self.context)
        self.assertEqual(dentist.mutation.operation, "create_event")
        self.assertIn("2:00 PM", dentist.text)
        lunch = self.service.interpret("Add lunch with Jim Friday from noon to 1.", time_context=self.context)
        self.assertIn("12:00 PM", lunch.text)
        recurring = self.service.interpret(
            "Add a task every Tuesday at 9 to take out the bins.", time_context=self.context
        )
        self.assertEqual(recurring.mutation.after.recurrence, RecurrenceRule("FREQ=WEEKLY;BYDAY=TU"))

    def test_confirmed_create_update_complete_and_delete_invoke_bridge(self) -> None:
        proposal = self.service.interpret("Remind me tomorrow at 3 to call Mom.", time_context=self.context).mutation
        created = self.service.apply(proposal, completed_at=self.context.captured_utc)
        self.assertIn("Created task", created.text)
        task = next(iter(self.port.tasks.values()))
        self.assertEqual(self.bridge.objects[-1], task)
        recent = PlanningReference("task", task.collection_id, task.uid, task.title)
        complete = self.service.interpret("Mark call Mom done.", time_context=self.context, recent=recent).mutation
        self.service.apply(complete, completed_at=self.context.captured_utc)
        self.assertTrue(self.port.tasks[task.uid].completed)
        delete = self.service.interpret("Delete that task.", time_context=self.context, recent=recent).mutation
        self.service.apply(delete, completed_at=self.context.captured_utc)
        self.assertNotIn(task.uid, self.port.tasks)
        self.assertEqual(self.bridge.full, 1)

    def test_reschedule_recurrence_and_event_reminder_updates(self) -> None:
        event = self.add_event()
        recent = PlanningReference("event", event.collection_id, event.uid, event.title)
        moved = self.service.interpret(
            "Move the dentist appointment to 3.", time_context=self.context, recent=recent
        )
        self.assertIn("3:00 PM", moved.text)
        self.service.apply(moved.mutation, completed_at=self.context.captured_utc)
        reminded = self.service.interpret(
            "Remind me 30 minutes before my dentist appointment.", time_context=self.context
        )
        self.service.apply(reminded.mutation, completed_at=self.context.captured_utc)
        self.assertEqual(self.port.events[event.uid].reminders[0].trigger, timedelta(minutes=-30))
        recurring = self.service.interpret(
            "Change it to every other Tuesday.", time_context=self.context, recent=recent
        )
        self.assertEqual(recurring.mutation.after.recurrence.value, "FREQ=WEEKLY;BYDAY=TU;INTERVAL=2")

        remove = self.service.interpret(
            "Remove that reminder.", time_context=self.context, recent=recent
        )
        self.assertEqual(remove.mutation.operation, "update_event")
        self.assertEqual(remove.mutation.after.reminders, ())

    def test_realistic_title_delete_and_revisionless_mutation_are_safe(self) -> None:
        task = self.add_task("Buy filters")
        deleted = self.service.interpret(
            "Delete the filter task.", time_context=self.context
        )
        self.assertEqual(deleted.mutation.before.uid, task.uid)

        self.port.tasks[task.uid] = replace(task, revision=None)
        with self.assertRaises(PlanningConversationError) as raised:
            self.service.interpret(
                "Delete the filter task.", time_context=self.context
            )
        self.assertEqual(raised.exception.code, "stale_confirmation")

    def test_common_interval_count_until_and_recent_time_updates(self) -> None:
        every_two = self.service.interpret(
            "Add a task every 2 weeks at 9 to review the budget.",
            time_context=self.context,
        )
        self.assertEqual(every_two.mutation.after.recurrence.value, "FREQ=WEEKLY;INTERVAL=2")
        self.assertIn("Every 2 weeks", every_two.text)
        counted = self.service.interpret(
            "Add a task every 3 days at 10 for 5 days to stretch.",
            time_context=self.context,
        )
        self.assertEqual(counted.mutation.after.recurrence.value, "FREQ=DAILY;INTERVAL=3;COUNT=5")
        until = self.service.interpret(
            "Add a task every Friday at 9 until November 30 to submit status.",
            time_context=self.context,
        )
        self.assertIn("BYDAY=FR", until.mutation.after.recurrence.value)
        self.assertIn("UNTIL=20261130", until.mutation.after.recurrence.value)

        reminder = self.service.interpret(
            "Remind me tomorrow at 3 to call Mom.", time_context=self.context
        ).mutation
        self.service.apply(reminder, completed_at=self.context.captured_utc)
        task = next(iter(self.port.tasks.values()))
        recent = PlanningReference("task", task.collection_id, task.uid, task.title)
        changed = self.service.interpret(
            "Change my reminder to 5 PM.", time_context=self.context, recent=recent
        )
        self.assertIn("5:00 PM", changed.text)
        due = self.service.interpret(
            "Make that task due Friday instead.", time_context=self.context, recent=recent
        )
        self.assertIn("August 28", due.text)

    def test_date_range_afternoon_all_day_location_and_formatting_boundaries(self) -> None:
        all_day = self.service.interpret(
            "Add all-day vacation Thursday.", time_context=self.context
        )
        self.assertTrue(all_day.mutation.after.all_day)
        located = self.service.interpret(
            "Add dentist Thursday at 2 at Downtown Dental.", time_context=self.context
        )
        self.assertEqual(located.mutation.after.location, "Downtown Dental")
        self.assertNotIn("FREQ=", located.text)
        self.assertNotIn("etag", located.text.casefold())
        self.assertNotIn("calendar/", located.text)
        self.port.events["afternoon"] = Event(
            "afternoon", "Coffee", "calendar",
            datetime(2026, 9, 1, 19, tzinfo=UTC),
            datetime(2026, 9, 1, 20, tzinfo=UTC),
            revision=PlanningRevision("coffee-r1"),
        )
        query = self.service.interpret(
            "Do I have anything Tuesday afternoon?", time_context=self.context
        )
        self.assertIn("Coffee", query.text)

    def test_ambiguous_reference_never_proposes_mutation(self) -> None:
        self.add_event("Dentist")
        self.add_event("Dentist")
        with self.assertRaises(PlanningConversationError) as raised:
            self.service.interpret("Move the dentist appointment to 3.", time_context=self.context)
        self.assertEqual(raised.exception.code, "ambiguous_reference")

    def test_external_revision_invalidates_proposal(self) -> None:
        event = self.add_event()
        proposal = self.service.interpret(
            "Move the dentist appointment to 3.", time_context=self.context
        ).mutation
        self.port.events[event.uid] = replace(event, title="External edit", revision=PlanningRevision("external-r2"))
        with self.assertRaises(PlanningConversationError) as raised:
            self.service.apply(proposal, completed_at=self.context.captured_utc)
        self.assertEqual(raised.exception.code, "stale_confirmation")
        self.assertEqual(self.port.events[event.uid].title, "External edit")

    def test_backend_unavailable_is_truthful_and_casual_language_is_not_claimed(self) -> None:
        for casual in (
            "I have a plan for the weekend.",
            "That was quite an event.",
            "This task is harder than expected.",
            "Please remind me why this matters.",
        ):
            self.assertFalse(self.service.interpret(casual, time_context=self.context).handled)
        self.port.available = False
        with self.assertRaises(PlanningConversationError) as raised:
            self.service.interpret("What do I have today?", time_context=self.context)
        self.assertEqual(raised.exception.code, "planning_unavailable")


if __name__ == "__main__":
    unittest.main()
