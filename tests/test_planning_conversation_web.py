from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.planning import PlanningRevision
from tori.planning_application import PlanningService
from tori.providers import ChatResponse, ModelProvider
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.tasks import SQLiteOperationalStore
from tori.web import WebApplication, WebApplicationError

from tests.test_planning_conversation import FakePlanningPort


UTC = timezone.utc


class _Provider(ModelProvider):
    def __init__(self) -> None:
        self.requests = []
        self.answer = "ordinary answer"

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse(self.answer, "model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        yield self.answer


class PlanningConversationWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 8, 26, 14, tzinfo=UTC)
        self.port = FakePlanningPort()
        self.scheduled = SQLiteScheduledWorkStore(
            self.root / "scheduled.db", clock=lambda: self.now
        )
        self.scheduled.initialize()
        self.operational = SQLiteOperationalStore(self.root / "operational.db", clock=lambda: self.now)
        self.operational.initialize()
        self.chats = ChatService(ConversationArchiveStore(
            self.root / "archive.db", clock=lambda: self.now
        ))
        self.provider = _Provider()
        self.application = WebApplication(
            self.provider,
            port=8765,
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "knowledge", working_directory=self.root
            ),
            provider_name="fake", model_name="model", chat_service=self.chats,
            scheduled_work_store=self.scheduled,
            operational_store=self.operational,
            planning_service=PlanningService(self.port),
            planning_default_task_list="calendar",
            planning_default_calendar="calendar",
            timezone_name="America/Chicago", utc_clock=lambda: self.now,
        )

    def test_read_bypasses_model_and_confirmed_reminder_is_one_use(self) -> None:
        status, empty = self.application.submit("What do I have today?")
        self.assertEqual(status, 200)
        self.assertIn("Nothing scheduled", empty["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])

        status, proposed = self.application.submit("Remind me tomorrow at 3 to call Mom.")
        self.assertEqual(status, 200)
        self.assertEqual(proposed["confirmation"]["action"], "planning.authorize")
        self.assertEqual(self.port.tasks, {})
        token = proposed["confirmation"]["token"]
        confirmed_status, confirmed = self.application.confirm(token, "confirm")
        self.assertEqual(confirmed_status, 201)
        self.assertEqual(len(self.port.tasks), 1)
        self.assertEqual(len(self.scheduled.list_definitions()), 1)
        self.assertEqual(self.operational.list_tasks(), ())
        projection = self.application.planning_workspace_state()
        self.assertTrue(projection["available"])
        self.assertIn("Call Mom", repr(projection["tasks"]["open"]))
        archived = self.chats.get_chat(self.application._active_chat_id)
        self.assertEqual(archived.entries[-1].application_event_type, "planning_result")
        with self.assertRaises(WebApplicationError) as reused:
            self.application.confirm(token, "confirm")
        self.assertEqual(reused.exception.code, "unknown_confirmation")

    def test_current_weekday_questions_use_captured_clock_not_planning_or_model(self) -> None:
        for question in (
            "What day of the week is it today?",
            "What day of the week is today?",
            "What weekday is it?",
            "What day is it today?",
        ):
            status, response = self.application.submit(question)
            self.assertEqual(status, 200)
            self.assertEqual(response["transcript"][-1]["text"], "Today is Wednesday.")
        self.assertEqual(self.provider.requests, [])

        response = list(self.application.stream_submit("What weekday is it?"))[-1]
        self.assertEqual(response["type"], "complete")
        self.assertEqual(response["transcript"][-1]["text"], "Today is Wednesday.")
        self.assertEqual(self.provider.requests, [])

        archived = self.chats.get_chat(self.application._active_chat_id)
        self.assertEqual(archived.metadata.completed_turn_count, 0)
        self.assertEqual(
            tuple(entry.application_event_type for entry in archived.entries[1::2]),
            ("calendar_information",) * 5,
        )

    def test_calendar_then_repeated_today_reads_archive_as_distinct_turns(self) -> None:
        weekday = list(self.application.stream_submit("What weekday is it?"))[-1]
        self.assertEqual(weekday["type"], "complete")

        questions = (
            "What do I have today?",
            "What do I have today?",
            "What do I have today?",
            "Anything scheduled today?",
            "What's happening today?",
            "Show me today's schedule.",
        )
        for question in questions:
            response = list(self.application.stream_submit(question))[-1]
            self.assertEqual(response["type"], "complete")
            self.assertIn("Nothing scheduled", response["transcript"][-1]["text"])

        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.port.tasks, {})
        self.assertEqual(self.port.events, {})
        archived = self.chats.get_chat(self.application._active_chat_id)
        self.assertEqual(archived.metadata.completed_turn_count, 0)
        self.assertEqual(len(archived.entries), 2 * (1 + len(questions)))
        self.assertEqual(
            tuple(entry.role for entry in archived.entries),
            ("user", "assistant") * (1 + len(questions)),
        )
        event_ids = tuple(
            entry.application_event_id for entry in archived.entries[1::2]
        )
        self.assertNotIn(None, event_ids)
        self.assertEqual(len(set(event_ids)), len(event_ids))
        self.assertEqual(
            tuple(entry.application_event_type for entry in archived.entries[1::2]),
            ("calendar_information",) + ("planning_read",) * len(questions),
        )

    def test_weekday_route_preserves_today_schedule_and_ordinary_conversation(self) -> None:
        for question in (
            "What's on my schedule today?",
            "What do I have today?",
            "Anything scheduled today?",
            "What's happening today?",
            "Show me today's schedule.",
        ):
            status, response = self.application.submit(question)
            self.assertEqual(status, 200)
            self.assertIn("Nothing scheduled", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])

        status, response = self.application.submit("I finished a project earlier today.")
        self.assertEqual(status, 200)
        self.assertEqual(response["transcript"][-1]["text"], "ordinary answer")
        self.assertEqual(len(self.provider.requests), 1)

    def test_weather_today_does_not_collide_with_planning_read(self) -> None:
        status, response = self.application.submit(
            "What's the weather today in Exampleville, IL?"
        )
        self.assertEqual(status, 200)
        self.assertNotIn("Nothing scheduled", response["transcript"][-1]["text"])
        self.assertIn("search", response["transcript"][-1]["text"].casefold())
        self.assertEqual(self.provider.requests, [])

    def test_streaming_weather_today_does_not_collide_with_planning_read(self) -> None:
        response = list(self.application.stream_submit(
            "What's the forecast today in Exampleville?"
        ))[-1]
        self.assertEqual(response["type"], "complete")
        self.assertNotIn("Nothing scheduled", response["transcript"][-1]["text"])
        self.assertIn("search", response["transcript"][-1]["text"].casefold())
        self.assertEqual(self.provider.requests, [])

    def test_cancel_cross_chat_and_expiry_never_mutate(self) -> None:
        _status, proposed = self.application.submit("Add dentist Thursday at 2.")
        token = proposed["confirmation"]["token"]
        self.application.confirm(token, "cancel")
        self.assertEqual(self.port.events, {})

        _status, proposed = self.application.submit("Add dentist Thursday at 2.")
        other = self.chats.create_chat(
            (ArchiveEntry("user", "Hello"), ArchiveEntry("assistant", "Hi", provider="fake", model="model")),
            provider="fake", model="model", select_active=True,
        )
        self.application.open_chat(other.metadata.identifier, other.metadata.revision)
        with self.assertRaises(WebApplicationError) as cleared:
            self.application.confirm(proposed["confirmation"]["token"], "confirm")
        self.assertEqual(cleared.exception.code, "unknown_confirmation")
        self.assertEqual(self.port.events, {})

        _status, expiring = self.application.submit("Add dentist Thursday at 2.")
        self.application._pending_confirmations[expiring["confirmation"]["token"]] = replace(
            self.application._pending_confirmations[expiring["confirmation"]["token"]],
            expires_at=-1,
        )
        with self.assertRaises(WebApplicationError) as expired:
            self.application.confirm(expiring["confirmation"]["token"], "confirm")
        self.assertEqual(expired.exception.code, "expired_confirmation")
        self.assertEqual(self.port.events, {})

    def test_external_edit_rejects_stale_confirmation_and_preserves_edit(self) -> None:
        _status, proposed = self.application.submit("Add dentist Thursday at 2.")
        self.application.confirm(proposed["confirmation"]["token"], "confirm")
        event = next(iter(self.port.events.values()))
        _status, moved = self.application.submit("Move the dentist appointment to 3.")
        self.port.events[event.uid] = replace(
            event, title="Dentist externally edited",
            revision=PlanningRevision("external-r2"),
        )
        status, response = self.application.confirm(moved["confirmation"]["token"], "confirm")
        self.assertEqual(status, 409)
        self.assertEqual(response["code"], "stale_confirmation")
        self.assertEqual(self.port.events[event.uid].title, "Dentist externally edited")

    def test_unavailable_planning_does_not_fall_through_to_model_or_shadow_store(self) -> None:
        self.port.available = False
        status, response = self.application.submit("What do I have today?")
        self.assertEqual(status, 200)
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "planning_unavailable")
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.port.tasks, {})

    def test_backend_becoming_unavailable_at_confirmation_fails_without_shadow_write(self) -> None:
        _status, proposed = self.application.submit("Add dentist Thursday at 2.")
        self.port.available = False
        status, response = self.application.confirm(
            proposed["confirmation"]["token"], "confirm"
        )
        self.assertEqual(status, 503)
        self.assertEqual(response["code"], "planning_unavailable")
        self.assertEqual(self.port.events, {})

    def test_streaming_path_returns_planning_proposal_without_model_turn(self) -> None:
        events = list(self.application.stream_submit("Add lunch with Jim Friday from noon to 1."))
        self.assertEqual(events[-1]["type"], "complete")
        self.assertEqual(events[-1]["confirmation"]["action"], "planning.authorize")
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.port.events, {})

    def test_model_output_has_zero_planning_mutation_authority(self) -> None:
        self.provider.answer = "Add dentist Thursday at 2 and mark it confirmed."
        status, response = self.application.submit("Tell me something cheerful.")
        self.assertEqual(status, 200)
        self.assertIn("Add dentist", response["transcript"][-1]["text"])
        self.assertEqual(self.port.events, {})
        self.assertNotIn("confirmation", response)


if __name__ == "__main__":
    unittest.main()
