from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import unittest
from unittest.mock import patch

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService, completed_model_history
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatResponse, ModelProvider, ProviderConnectionError
from tori.tasks import (
    OperationalConflictError,
    OperationalNotFoundError,
    OperationalStaleRevisionError,
    SQLiteOperationalStore,
)
from tori.time_context import FakeClock, format_utc_timestamp
from tori.web import WebApplication


class BlockingProvider(ModelProvider):
    def __init__(self) -> None:
        self.release = threading.Event()
        self.memory_started = threading.Event()
        self.memory_release = threading.Event()

    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("answer", "model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "first "
        self.release.wait(3)
        yield "second"

    def extract_memory_candidates(self, messages, *, model):  # type: ignore[no-untyped-def]
        self.memory_started.set()
        self.memory_release.wait(3)
        return ChatResponse('{"candidates":[]}', model)


class FailingProvider(BlockingProvider):
    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "partial sentence. "
        self.release.wait(3)
        raise ProviderConnectionError("synthetic private failure")


class AbandonProvider(BlockingProvider):
    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "abandoned sentence. "
        self.release.wait(3)
        yield "unreachable"


class CompleteBlockingProvider(BlockingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.started.set()
        self.release.wait(3)
        return ChatResponse("complete answer", "model")


class AttentionWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.clock = FakeClock(datetime(2026, 8, 10, 15, tzinfo=timezone.utc))
        self.operational = SQLiteOperationalStore(root / "tasks.db", clock=self.clock)
        self.chat_service = ChatService(ConversationArchiveStore(root / "archive.db", clock=self.clock))
        self.chat = self.chat_service.create_chat(
            (ArchiveEntry("user", "Earlier"), ArchiveEntry("assistant", "Earlier answer", provider="fake", model="model")),
            provider="fake",
            model="model",
            select_active=True,
        )
        self.provider = BlockingProvider()
        self.application = WebApplication(
            self.provider,
            port=8765,
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge", working_directory=root),
            provider_name="fake",
            model_name="model",
            chat_service=self.chat_service,
            operational_store=self.operational,
            timezone_name="America/Chicago",
            utc_clock=self.clock,
        )

    def reminder(self, minutes: int, text: str = "Take lunch"):
        return self.operational.create_reminder(
            text,
            scheduled_start_utc=format_utc_timestamp(self.clock() + timedelta(minutes=minutes)),
            scheduled_timezone="America/Chicago",
        )

    def test_no_browser_due_survives_then_two_clients_converge_without_duplicate_chat(self) -> None:
        reminder = self.reminder(0)
        self.operational.mark_due(self.clock())
        self.assertEqual(len(self.operational.pending_deliveries()), 1)

        first_client = self.application.attention_state()
        second_client = self.application.attention_state()
        self.assertEqual(first_client["active_reminder"]["identifier"], reminder.identifier)
        self.assertEqual(second_client["operational_revision"], first_client["operational_revision"])
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        events = [item for item in archived.entries if item.application_event_type == "reminder_due"]
        self.assertEqual(len(events), 1)
        self.assertEqual(self.operational.pending_deliveries(), ())

        status, acting = self.application.reminder_action("dismiss", reminder.identifier, 2)
        self.assertEqual(status, 200)
        self.assertIsNone(acting["active_reminder"])
        with self.assertRaises(OperationalStaleRevisionError):
            self.operational.delay_reminder(
                reminder.identifier,
                expected_revision=2,
                scheduled_start_utc="2026-08-10T16:00:00Z",
                scheduled_timezone="America/Chicago",
            )
        self.assertIsNone(self.application.attention_state()["active_reminder"])
        self.assertEqual(len([item for item in self.chat_service.get_chat(self.chat.metadata.identifier).entries if item.application_event_type == "reminder_due"]), 1)

    def test_due_during_stream_is_canonical_but_presented_only_after_model_archive(self) -> None:
        reminder = self.reminder(1, "Crossing response")
        stream = self.application.stream_submit("Continue our conversation")
        first = next(stream)
        self.assertEqual(first["type"], "delta")
        self.clock.advance(timedelta(minutes=2))
        self.operational.mark_due(self.clock())
        busy_attention = self.application.attention_state()
        self.assertEqual(busy_attention["active_reminder"]["identifier"], reminder.identifier)
        self.assertEqual(len(self.operational.pending_deliveries()), 1)
        self.assertEqual(
            len([item for item in self.chat_service.get_chat(self.chat.metadata.identifier).entries if item.application_event_type == "reminder_due"]),
            0,
        )
        self.provider.release.set()
        remaining = list(stream)
        self.assertEqual(remaining[-1]["type"], "complete")
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        self.assertEqual(archived.entries[-2].text, "first second")
        self.assertEqual(archived.entries[-1].application_event_type, "reminder_due")
        self.assertEqual(archived.metadata.completed_turn_count, 2)
        self.assertEqual(len(completed_model_history(archived.entries)), 4)

    def test_authoritative_busy_state_clears_after_every_terminal_path(self) -> None:
        stream = self.application.stream_submit("Successful stream")
        self.assertTrue(self.application.attention_state()["busy"])
        self.assertEqual(next(stream)["type"], "delta")
        self.provider.release.set()
        self.assertEqual(list(stream)[-1]["type"], "complete")
        self.assertFalse(self.application.attention_state()["busy"])

        failure = FailingProvider()
        self.application._session._provider = failure
        failed_stream = self.application.stream_submit("Failed stream")
        self.assertEqual(next(failed_stream)["type"], "delta")
        self.assertTrue(self.application.attention_state()["busy"])
        failure.release.set()
        self.assertEqual(list(failed_stream)[-1]["type"], "error")
        self.assertFalse(self.application.attention_state()["busy"])

        abandoned = AbandonProvider()
        self.application._session._provider = abandoned
        abandoned_stream = self.application.stream_submit("Disconnected stream")
        self.assertEqual(next(abandoned_stream)["type"], "delta")
        self.assertTrue(self.application.attention_state()["busy"])
        abandoned_stream.close()
        self.assertFalse(self.application.attention_state()["busy"])

        complete = CompleteBlockingProvider()
        self.application._provider = complete
        self.application._session._provider = complete
        self.application._task_service = None
        result: list[tuple[int, dict[str, object]]] = []
        worker = threading.Thread(
            target=lambda: result.append(
                self.application.submit("What color is a cedar tree?")
            )
        )
        worker.start()
        self.assertTrue(complete.started.wait(timeout=2))
        self.assertTrue(self.application.attention_state()["busy"])
        complete.release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0][0], 200)
        self.assertFalse(self.application.attention_state()["busy"])

    def test_transcript_revision_remains_new_across_post_archive_busy_to_idle(self) -> None:
        initial_session = self.application.session_state()
        initial_revision = initial_session["transcript_revision"]
        self.assertEqual(initial_session["active_chat_id"], self.chat.metadata.identifier)

        stream = self.application.stream_submit("Cross-browser revision race")
        self.assertEqual(next(stream)["type"], "delta")
        terminal: list[dict[str, object]] = []
        worker = threading.Thread(target=lambda: terminal.extend(stream))
        worker.start()
        self.provider.release.set()
        worker.join(timeout=3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(terminal[-1]["type"], "complete")
        post_archive = self.application.attention_state()
        self.assertFalse(post_archive["busy"])
        self.assertEqual(post_archive["active_chat_id"], self.chat.metadata.identifier)
        self.assertGreater(post_archive["transcript_revision"], initial_revision)

        coordinator = self.application.memory_extraction_coordinator
        self.assertIsNotNone(coordinator)
        extraction_worker = threading.Thread(target=coordinator.process_one)  # type: ignore[union-attr]
        extraction_worker.start()
        self.assertTrue(self.provider.memory_started.wait(timeout=2))
        idle = self.application.attention_state()
        self.assertFalse(idle["busy"])
        self.assertEqual(idle["active_chat_id"], post_archive["active_chat_id"])
        self.assertEqual(idle["transcript_revision"], post_archive["transcript_revision"])
        self.provider.memory_release.set()
        extraction_worker.join(timeout=3)
        self.assertFalse(extraction_worker.is_alive())
        final_session = self.application.session_state()
        self.assertEqual(final_session["transcript_revision"], idle["transcript_revision"])
        self.assertEqual(final_session["transcript"][-2]["text"], "Cross-browser revision race")
        self.assertEqual(final_session["transcript"][-1]["text"], "first second")

    def test_multiple_due_uses_one_card_and_deterministic_queue(self) -> None:
        later = self.reminder(2, "Later")
        earlier = self.reminder(1, "Earlier")
        self.clock.advance(timedelta(minutes=3))
        self.operational.mark_due(self.clock())
        state = self.application.attention_state()
        self.assertEqual(state["active_reminder"]["identifier"], earlier.identifier)
        self.assertEqual(state["queued_count"], 1)
        self.application.reminder_action("dismiss", earlier.identifier, 2)
        self.assertEqual(self.application.attention_state()["active_reminder"]["identifier"], later.identifier)

    def test_operational_result_is_application_authored_and_excluded_from_history_and_memory(self) -> None:
        interpretation = json.dumps({
            "intent": "create_task",
            "task_text": "Review the operational result",
            "reminder_text": None,
            "target": None,
            "schedule": None,
            "clarification": None,
        })
        before_history = completed_model_history(
            self.chat_service.get_chat(self.chat.metadata.identifier).entries
        )
        with patch.object(
            self.provider,
            "interpret_task_intent",
            return_value=ChatResponse(interpretation, "model"),
        ):
            status, _response = self.application.submit("Add this to my tasks")
        self.assertEqual(status, 200)
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        event = archived.entries[-1]
        self.assertEqual(event.application_event_type, "operational_result")
        self.assertIsNone(event.provider)
        self.assertIsNone(event.model)
        self.assertEqual(event.sources, ())
        self.assertEqual(completed_model_history(archived.entries), before_history)
        self.assertEqual(self.application._memory_store.list_memories(), ())

    def test_exact_two_minute_standalone_reminder_routes_and_persists(self) -> None:
        with patch.object(
            self.provider,
            "interpret_task_intent",
            side_effect=AssertionError("clear relative reminder must not require a model"),
        ):
            status, response = self.application.submit(
                "Remind me in 2 minutes to check the kitchen."
            )
        self.assertEqual(status, 200)
        reminders = self.operational.list_reminders()
        self.assertEqual(len(reminders), 1)
        reminder = reminders[0]
        self.assertEqual(reminder.reminder_text, "check the kitchen")
        self.assertEqual(reminder.scheduled_start_utc, "2026-08-10T15:02:00Z")
        self.assertEqual(reminder.scheduled_timezone, "America/Chicago")
        self.assertIsNone(reminder.task_id)
        self.assertEqual(reminder.status, "scheduled")
        self.assertIn("I’ll remind you at", response["transcript"][-1]["text"])
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        self.assertEqual(archived.entries[-1].application_event_type, "operational_result")

    def test_exact_action_first_elapsed_reminder_routes_without_model(self) -> None:
        with patch.object(
            self.provider,
            "interpret_task_intent",
            side_effect=AssertionError("clear trailing duration must not require a model"),
        ):
            status, response = self.application.submit(
                "Remind me to make another sandwich in 2 minutes."
            )
        self.assertEqual(status, 200)
        reminders = self.operational.list_reminders()
        self.assertEqual(len(reminders), 1)
        reminder = reminders[0]
        self.assertEqual(reminder.reminder_text, "make another sandwich")
        self.assertEqual(reminder.scheduled_start_utc, "2026-08-10T15:02:00Z")
        self.assertEqual(reminder.scheduled_timezone, "America/Chicago")
        self.assertIsNone(reminder.task_id)
        self.assertEqual(reminder.status, "scheduled")
        self.assertEqual(self.operational.list_tasks(), ())
        self.assertNotIn("local date", response["transcript"][-1]["text"])
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        self.assertEqual(archived.entries[-1].application_event_type, "operational_result")

    def test_exact_live_window_is_visible_in_management_and_attention_at_start(self) -> None:
        with patch.object(
            self.provider,
            "interpret_task_intent",
            side_effect=AssertionError("clear civil window must not require a model"),
        ):
            status, response = self.application.submit(
                "Remind me to take a break between 12:10 PM and 12:20 PM today."
            )
        self.assertEqual(status, 200)
        reminders = self.operational.list_reminders()
        self.assertEqual(len(reminders), 1)
        reminder = reminders[0]
        self.assertIsNone(reminder.task_id)
        self.assertEqual(self.operational.list_tasks(), ())
        self.assertEqual(reminder.scheduled_start_utc, "2026-08-10T17:10:00Z")
        self.assertEqual(reminder.scheduled_end_utc, "2026-08-10T17:20:00Z")
        self.assertEqual(reminder.scheduled_timezone, "America/Chicago")
        self.assertIn("12:10 PM–12:20 PM CDT", response["transcript"][-1]["text"])

        management = self.application.reminders_state()["reminders"]
        self.assertEqual(management[0]["scheduled_start_utc"], "2026-08-10T17:10:00Z")
        self.assertEqual(management[0]["scheduled_end_utc"], "2026-08-10T17:20:00Z")
        self.assertIsNone(self.application.attention_state()["active_reminder"])
        self.clock.set(datetime(2026, 8, 10, 17, 10, tzinfo=timezone.utc))
        self.operational.mark_due(self.clock())
        active = self.application.attention_state()["active_reminder"]
        self.assertEqual(active["identifier"], reminder.identifier)
        self.assertEqual(active["scheduled_start_utc"], "2026-08-10T17:10:00Z")
        self.assertEqual(active["scheduled_end_utc"], "2026-08-10T17:20:00Z")
        self.assertEqual(active["scheduled_timezone"], "America/Chicago")
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        self.assertEqual(archived.entries[-2].application_event_type, "operational_result")
        self.assertIsNone(archived.entries[-2].provider)
        self.assertIsNone(archived.entries[-2].model)

    def test_exact_existing_task_reminder_routes_without_creating_task(self) -> None:
        task = self.operational.create_task("finish stacking the boxes in the garage")
        with patch.object(
            self.provider,
            "interpret_task_intent",
            side_effect=AssertionError("explicit existing-task linkage must not require a model"),
        ):
            status, response = self.application.submit(
                "Add a reminder to my existing task “finish stacking the boxes in the garage” for 2 minutes from now."
            )
        self.assertEqual(status, 200)
        tasks = self.operational.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].identifier, task.identifier)
        self.assertEqual(tasks[0].revision, task.revision)
        reminders = self.operational.list_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].task_id, task.identifier)
        self.assertEqual(reminders[0].scheduled_start_utc, "2026-08-10T15:02:00Z")
        result_text = response["transcript"][-1]["text"]
        self.assertIn("I’ll remind you about", result_text)
        self.assertNotIn("Added", result_text)
        archived = self.chat_service.get_chat(self.chat.metadata.identifier)
        self.assertEqual(archived.entries[-1].application_event_type, "operational_result")

    def test_history_delete_preserves_chat_event_and_enforces_linked_task_order(self) -> None:
        task = self.operational.create_task("Task with archived reminder")
        reminder = self.operational.create_reminder(
            "Archived reminder remains in chat",
            task_id=task.identifier,
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        task = self.operational.complete_task(task.identifier, expected_revision=1)
        self.operational.mark_due(self.clock())
        self.application.attention_state()
        reminder = self.operational.get_reminder(reminder.identifier)
        _status, _state = self.application.reminder_action(
            "dismiss", reminder.identifier, reminder.revision
        )
        reminder = self.operational.get_reminder(reminder.identifier)
        archived_before = self.chat_service.get_chat(self.chat.metadata.identifier)

        with self.assertRaisesRegex(
            OperationalConflictError, "Delete those reminders first"
        ):
            self.application.delete_historical_task(
                task.identifier, task.revision
            )
        status, response = self.application.delete_historical_reminder(
            reminder.identifier, reminder.revision
        )
        self.assertEqual(status, 200)
        self.assertNotIn(
            reminder.identifier,
            {item["identifier"] for item in response["reminders"]},
        )
        self.application.delete_historical_task(task.identifier, task.revision)
        with self.assertRaises(OperationalNotFoundError):
            self.operational.get_task(task.identifier)
        self.assertEqual(
            self.chat_service.get_chat(self.chat.metadata.identifier),
            archived_before,
        )

    def test_failed_and_abandoned_streams_release_then_deliver_once(self) -> None:
        for provider_type in (FailingProvider, AbandonProvider):
            with self.subTest(provider=provider_type.__name__):
                provider = provider_type()
                self.application._provider = provider
                self.application._session.select_model(provider, "model")
                reminder = self.reminder(0, provider_type.__name__)
                stream = self.application.stream_submit("A separate ordinary turn")
                self.assertEqual(next(stream)["type"], "delta")
                self.operational.mark_due(self.clock())
                if provider_type is FailingProvider:
                    provider.release.set()
                    self.assertEqual(list(stream)[-1]["type"], "error")
                else:
                    stream.close()
                events = [
                    item for item in self.chat_service.get_chat(self.chat.metadata.identifier).entries
                    if item.application_event_type == "reminder_due"
                    and item.text.endswith(provider_type.__name__)
                ]
                self.assertEqual(len(events), 1)
                self.application.reminder_action("dismiss", reminder.identifier, 2)


if __name__ == "__main__":
    unittest.main()
