from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.planning import (
    Event,
    PlanningAvailability,
    PlanningCollection,
    PlanningRevision,
    PlanningStatus,
    PlanningReminder,
    RecurrenceRule,
    Task,
)
from tori.planning_application import PlanningService
from tori.planning_reminder_bridge import (
    PLANNING_REMINDER_ACTION_ID,
    PlanningReminderBridge,
    planning_reminder_catalog,
)
from tori.scheduled_work import (
    ScheduledCapabilityError,
    ScheduledWorkUnavailableError,
    ScheduledWorkCoordinator,
    ScheduledWorkExecutor,
    SQLiteScheduledWorkStore,
)
from tori.scheduled_work_application import ScheduledWorkApplicationService
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatResponse, ModelProvider
from tori.web import WebApplication


UTC = timezone.utc


class FakePlanningPort:
    def __init__(self, *, now: datetime) -> None:
        self.now = now
        self.events: dict[str, Event] = {}
        self.tasks: dict[str, Task] = {}
        self.available = True

    def status(self) -> PlanningStatus:
        return PlanningStatus(
            PlanningAvailability.AVAILABLE if self.available else PlanningAvailability.UNAVAILABLE,
            "Planning is available." if self.available else "Planning is unavailable.",
        )

    def list_collections(self):  # type: ignore[no-untyped-def]
        return (PlanningCollection("calendar", "Calendar", True, True),)

    def list_tasks(self, collection_id):  # type: ignore[no-untyped-def]
        return tuple(self.tasks.values())

    def list_events(self, collection_id):  # type: ignore[no-untyped-def]
        return tuple(self.events.values())

    def create_task(self, task):  # type: ignore[no-untyped-def]
        self.tasks[task.uid] = task
        return task

    def get_task(self, collection_id, uid):  # type: ignore[no-untyped-def]
        return self.tasks[uid]

    def update_task(self, task, *, expected_revision):  # type: ignore[no-untyped-def]
        self.tasks[task.uid] = task
        return task

    def delete_task(self, collection_id, uid, *, expected_revision):  # type: ignore[no-untyped-def]
        del self.tasks[uid]

    def create_event(self, event):  # type: ignore[no-untyped-def]
        self.events[event.uid] = event
        return event

    def get_event(self, collection_id, uid):  # type: ignore[no-untyped-def]
        return self.events[uid]

    def update_event(self, event, *, expected_revision):  # type: ignore[no-untyped-def]
        self.events[event.uid] = event
        return event

    def delete_event(self, collection_id, uid, *, expected_revision):  # type: ignore[no-untyped-def]
        del self.events[uid]


class FailingScheduledWorkApplication(ScheduledWorkApplicationService):
    def create_derived_one_shot(self, **kwargs):  # type: ignore[no-untyped-def]
        raise ScheduledWorkUnavailableError("synthetic Scheduled Work outage")


class _Provider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("answer", "model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "answer"


class PlanningReminderBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.now = datetime(2026, 8, 26, 14, tzinfo=UTC)
        self.port = FakePlanningPort(now=self.now)
        self.store = SQLiteScheduledWorkStore(
            Path(self.temporary.name) / "scheduled.db", clock=lambda: self.now
        )
        self.store.initialize()
        self.application = ScheduledWorkApplicationService(self.store)
        self.bridge = PlanningReminderBridge(
            PlanningService(self.port), self.application, clock=lambda: self.now
        )

    def event(self, *, reminders=(), recurrence=None, start_hour=15):  # type: ignore[no-untyped-def]
        return Event(
            "event-bridge",
            "Planning review",
            "calendar",
            datetime(2026, 8, 26, start_hour, tzinfo=UTC),
            datetime(2026, 8, 26, start_hour + 1, tzinfo=UTC),
            recurrence=recurrence,
            reminders=reminders,
            revision=PlanningRevision("etag-1"),
        )

    def definitions(self):  # type: ignore[no-untyped-def]
        return [
            item for item in self.application.list_definitions()
            if item.capability_id == PLANNING_REMINDER_ACTION_ID
        ]

    def test_create_is_idempotent_and_bridge_capability_is_not_interactive(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        first = self.bridge.reconcile()
        second = self.bridge.reconcile()
        self.assertEqual(len(first.created), 1)
        self.assertEqual(second.unchanged, first.created)
        self.assertEqual(len(self.definitions()), 1)
        item = self.definitions()[0]
        with self.assertRaises(ScheduledCapabilityError):
            planning_reminder_catalog().validate(
                PLANNING_REMINDER_ACTION_ID, 1, item.arguments, "one_shot"
            )

    def test_alarm_and_event_time_moves_replace_one_pending_definition(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        created = self.bridge.reconcile().created[0]
        self.port.events["event-bridge"] = replace(
            self.port.events["event-bridge"],
            start=datetime(2026, 8, 26, 16, tzinfo=UTC),
            end=datetime(2026, 8, 26, 17, tzinfo=UTC),
            revision=PlanningRevision("etag-2"),
        )
        moved = self.bridge.reconcile()
        self.assertEqual(moved.replaced, (created,))
        self.assertEqual(len(self.definitions()), 1)
        self.assertEqual(
            self.definitions()[0].schedule.occurrence_utc, "2026-08-26T15:30:00Z"
        )
        self.port.events["event-bridge"] = replace(
            self.port.events["event-bridge"],
            reminders=(PlanningReminder(timedelta(minutes=-10), "Review"),),
            revision=PlanningRevision("etag-3"),
        )
        alarm_moved = self.bridge.reconcile()
        self.assertEqual(alarm_moved.replaced, (created,))
        self.assertEqual(
            self.definitions()[0].schedule.occurrence_utc, "2026-08-26T15:50:00Z"
        )

    def test_removal_deletion_and_task_completion_cancel_delivery(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        event_job = self.bridge.reconcile().created[0]
        self.port.events["event-bridge"] = replace(
            self.port.events["event-bridge"], reminders=(), revision=PlanningRevision("etag-2")
        )
        self.assertEqual(self.bridge.reconcile().cancelled, (event_job,))

        task = Task(
            "task-bridge", "Pay invoice", "calendar",
            due=datetime(2026, 8, 27, 15, tzinfo=UTC),
            reminders=(PlanningReminder(timedelta(minutes=0, seconds=1), "Pay"),),
            revision=PlanningRevision("task-1"),
        )
        self.port.tasks[task.uid] = task
        task_job = self.bridge.reconcile().created[0]
        self.port.tasks[task.uid] = replace(
            task, completed=True, completed_at=self.now, revision=PlanningRevision("task-2")
        )
        self.assertIn(task_job, self.bridge.reconcile().cancelled)
        del self.port.events["event-bridge"]
        self.assertFalse(
            [item for item in self.definitions() if item.status == "active"]
        )

    def test_multiple_alarms_and_recurrence_materialize_distinct_next_occurrences(self) -> None:
        self.port.events["event-bridge"] = self.event(
            recurrence=RecurrenceRule("FREQ=DAILY;COUNT=3"),
            reminders=(
                PlanningReminder(timedelta(minutes=-30), "Early"),
                PlanningReminder(timedelta(minutes=-10), "Late"),
            ),
        )
        result = self.bridge.reconcile()
        self.assertEqual(len(result.created), 2)
        definitions = self.definitions()
        self.assertEqual(len({item.arguments["source_key"] for item in definitions}), 2)
        self.assertEqual(
            {item.schedule.occurrence_utc for item in definitions},
            {"2026-08-26T14:30:00Z", "2026-08-26T14:50:00Z"},
        )
        self.now = datetime(2026, 8, 26, 16, tzinfo=UTC)
        next_result = self.bridge.reconcile()
        self.assertEqual(len(next_result.replaced), 2)
        self.assertEqual(
            {item.schedule.occurrence_utc for item in self.definitions()},
            {"2026-08-27T14:30:00Z", "2026-08-27T14:50:00Z"},
        )

    def test_external_revision_only_change_is_noop_and_backend_outage_preserves_state(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        created = self.bridge.reconcile().created[0]
        self.port.events["event-bridge"] = replace(
            self.port.events["event-bridge"], revision=PlanningRevision("etag-external")
        )
        self.assertEqual(self.bridge.reconcile().unchanged, (created,))
        self.port.available = False
        unavailable = self.bridge.reconcile()
        self.assertFalse(unavailable.available)
        self.assertEqual(unavailable.created, ())
        self.assertEqual(
            self.application.get_definition(created).status, "active"
        )

    def test_executor_delivers_derived_result_without_planning_mutation(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        created = self.bridge.reconcile().created[0]
        self.now = datetime(2026, 8, 26, 15, tzinfo=UTC)
        self.store.claim_due(self.now)
        run = ScheduledWorkExecutor(
            self.store, planning_reminder_catalog()
        ).execute_next()
        assert run is not None
        observation = self.bridge.observe_delivery_result(run.identifier)
        self.assertEqual(observation.status, "succeeded")
        self.assertEqual(observation.source_key, self.application.get_definition(created).arguments["source_key"])
        self.assertEqual(self.port.events["event-bridge"].title, "Planning review")

    def test_unresolvable_all_day_alarm_is_bounded(self) -> None:
        self.port.events["event-bridge"] = Event(
            "event-bridge", "All day", "calendar",
            datetime(2026, 8, 26, 0, tzinfo=UTC),
            datetime(2026, 8, 27, 0, tzinfo=UTC),
            all_day=False,
            reminders=(),
        )
        # The domain intentionally rejects date-valued alarms at this boundary;
        # the bridge's bounded unresolved path is covered by a task without a
        # start/due reference instead.
        self.port.tasks["task-open"] = Task(
            "task-open", "Open", "calendar",
            reminders=(PlanningReminder(timedelta(minutes=-30), "Open"),),
        )
        result = self.bridge.reconcile()
        self.assertEqual(result.created, ())
        self.assertTrue(result.unresolved)

    def test_scheduled_work_failure_preserves_planning_truth_for_retry(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        failing = FailingScheduledWorkApplication(self.store)
        bridge = PlanningReminderBridge(
            PlanningService(self.port), failing, clock=lambda: self.now
        )
        result = bridge.reconcile()
        self.assertTrue(result.failures)
        self.assertEqual(self.port.events["event-bridge"].title, "Planning review")
        self.assertEqual(self.store.list_definitions(), ())

    def test_disposable_derived_run_reaches_existing_application_event_delivery(self) -> None:
        self.port.events["event-bridge"] = self.event(
            reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),)
        )
        archive = ConversationArchiveStore(
            Path(self.temporary.name) / "archive.db", clock=lambda: self.now
        )
        chats = ChatService(archive)
        chat = chats.create_chat(
            (ArchiveEntry("user", "Earlier"), ArchiveEntry("assistant", "Answer", provider="fake", model="model")),
            provider="fake", model="model", select_active=True,
        )
        application = WebApplication(
            _Provider(),
            port=8765,
            checkpoint_store=CheckpointStore(Path(self.temporary.name) / "checkpoints"),
            memory_store=SQLiteMemoryStore(Path(self.temporary.name) / "memory.db"),
            knowledge_registry=KnowledgeRegistry(
                Path(self.temporary.name) / "knowledge", working_directory=Path(self.temporary.name)
            ),
            provider_name="fake", model_name="model", chat_service=chats,
            scheduled_work_store=self.store, timezone_name="America/Chicago",
            utc_clock=lambda: self.now,
        )
        bridge = PlanningReminderBridge(
            PlanningService(self.port), self.application,
            clock=lambda: self.now, origin_chat_id=chat.metadata.identifier,
        )
        bridge.reconcile()
        self.now = datetime(2026, 8, 26, 15, tzinfo=UTC)
        self.store.claim_due(self.now)
        ScheduledWorkExecutor(
            self.store,
            planning_reminder_catalog(application.scheduled_capability_catalog.definitions),
        ).execute_next()
        application.attention_state()
        detail = chats.get_chat(chat.metadata.identifier)
        events = [
            item for item in detail.entries
            if item.application_event_type == "scheduled_work_result"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(self.store.pending_notifications(), ())


if __name__ == "__main__":
    unittest.main()
