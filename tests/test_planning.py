from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest

from tori.planning import (
    DisabledPlanningPort, Event, PlanningAvailability, PlanningConflictError,
    PlanningDataError, PlanningNotFoundError, PlanningPort, PlanningReminder,
    PlanningRevision, PlanningStatus, RecurrenceRule, Task,
)
from tori.planning_application import PlanningService


UTC = timezone.utc


class FakePlanningPort:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.events: dict[str, Event] = {}
        self.revision = 0

    def status(self):
        return PlanningStatus(PlanningAvailability.AVAILABLE, "Planning is available.")

    def list_collections(self):
        return ()

    def create_task(self, task):
        return self._store(self.tasks, task)

    def get_task(self, collection_id, uid):
        return self.tasks[uid]

    def list_tasks(self, collection_id):
        return tuple(self.tasks.values())

    def update_task(self, task, *, expected_revision):
        self._check(self.tasks, task.uid, expected_revision)
        return self._store(self.tasks, task)

    def delete_task(self, collection_id, uid, *, expected_revision):
        self._check(self.tasks, uid, expected_revision)
        del self.tasks[uid]

    def create_event(self, event):
        return self._store(self.events, event)

    def get_event(self, collection_id, uid):
        return self.events[uid]

    def list_events(self, collection_id):
        return tuple(self.events.values())

    def update_event(self, event, *, expected_revision):
        self._check(self.events, event.uid, expected_revision)
        return self._store(self.events, event)

    def delete_event(self, collection_id, uid, *, expected_revision):
        self._check(self.events, uid, expected_revision)
        del self.events[uid]

    def _store(self, store, value):
        self.revision += 1
        stored = replace(value, revision=PlanningRevision(str(self.revision)))
        store[value.uid] = stored
        return stored

    @staticmethod
    def _check(store, uid, expected):
        if uid not in store:
            raise PlanningNotFoundError("missing")
        if store[uid].revision.token != expected:
            raise PlanningConflictError("stale")


class PlanningDomainTests(unittest.TestCase):
    def test_task_and_event_validate_portable_shapes(self) -> None:
        task = Task(
            "task-1", "Plan week", "collection", due=datetime(2026, 8, 27, 15, tzinfo=UTC),
            priority=3, recurrence=RecurrenceRule("freq=weekly;count=4"),
            reminders=(PlanningReminder(timedelta(minutes=-30), "Plan week"),),
        )
        event = Event(
            "event-1", "Planning review", "collection",
            datetime(2026, 8, 27, 15, tzinfo=UTC),
            datetime(2026, 8, 27, 16, tzinfo=UTC),
            location="Desk",
        )
        self.assertEqual(task.recurrence.value, "FREQ=WEEKLY;COUNT=4")
        self.assertFalse(event.all_day)

        with self.assertRaises(PlanningDataError):
            Task("bad uid", "Title", "collection")
        with self.assertRaises(PlanningDataError):
            Event("event-2", "All day", "collection", date(2026, 8, 27), date(2026, 8, 28))

    def test_service_uses_only_port_contract_and_revision_checks(self) -> None:
        port = FakePlanningPort()
        self.assertIsInstance(port, PlanningPort)
        service = PlanningService(port)
        created = service.create_task(Task("task-1", "Draft", "collection"))
        updated = service.update_task(
            replace(created, title="Revised"), expected_revision=created.revision.token
        )
        completed = service.complete_task(
            updated,
            when=datetime(2026, 8, 27, 20, tzinfo=UTC),
            expected_revision=updated.revision.token,
        )
        self.assertTrue(completed.completed)
        with self.assertRaises(PlanningConflictError):
            service.update_task(created, expected_revision=created.revision.token)
        service.delete_task(
            "collection", completed.uid, expected_revision=completed.revision.token
        )
        self.assertEqual(service.list_tasks("collection"), ())

    def test_disabled_port_is_truthful_and_fails_boundedly(self) -> None:
        service = PlanningService(DisabledPlanningPort())
        self.assertEqual(service.status().availability, PlanningAvailability.DISABLED)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            service.list_tasks("collection")
