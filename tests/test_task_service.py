from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.providers import ChatResponse, ModelProvider
from tori.task_service import TaskService
from tori.task_service import _direct_civil_point_reminder
from tori.providers import ProviderConnectionError
from tori.tasks import (
    OperationalUnavailableError,
    OperationalVerificationError,
    SQLiteOperationalStore,
)
from tori.reminder_scheduler import ReminderScheduler
from tori.time_context import FakeClock, TimeContext


def intent(name: str, **changes):
    document = {
        "intent": name,
        "task_text": None,
        "reminder_text": None,
        "target": None,
        "schedule": None,
        "clarification": None,
    }
    document.update(changes)
    return document


class IntentProvider(ModelProvider):
    def __init__(self, *documents) -> None:
        self.documents = iter(documents)
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("ordinary chat is not interpretation")

    def interpret_task_intent(self, messages, *, model):  # type: ignore[no-untyped-def]
        self.requests.append((tuple(messages), model))
        value = next(self.documents)
        return ChatResponse(value if isinstance(value, str) else json.dumps(value), model)


class TaskServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = FakeClock(datetime(2026, 8, 10, 15, tzinfo=timezone.utc))
        self.store = SQLiteOperationalStore(Path(self.temporary.name) / "tasks.db", clock=self.clock)
        self.context = TimeContext(self.clock(), "America/Chicago")

    def service(self, *documents) -> TaskService:
        return TaskService(self.store, IntentProvider(*documents), model_name="model")

    def test_explicit_point_reminder_word_orders_do_not_use_provider(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        for request in (
            "Set a reminder to do the dishes at 2:00 PM today.",
            "Set a reminder to do the dishes today at 2:00 PM.",
            "Remind me to do the dishes at 2:00 PM today.",
            "Remind me today at 2:00 PM to do the dishes.",
        ):
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertTrue(result.mutated)
                self.assertEqual(result.reminder.reminder_text, "do the dishes")
                self.assertEqual(result.reminder.scheduled_start_utc, "2026-08-10T19:00:00Z")
                self.assertEqual(result.reminder.scheduled_timezone, "America/Chicago")
                self.assertIsNone(result.reminder.task_id)
        self.assertEqual(provider.requests, [])
        self.assertEqual(len(self.store.list_reminders()), 4)

    def test_point_reminder_parser_rejects_discussion_incomplete_and_recurring(self) -> None:
        for request in (
            "How do I set a reminder to do the dishes at 2:00 PM today?",
            "Don't set a reminder to do the dishes at 2:00 PM today.",
            "Set a reminder to do the dishes at 2:00 today.",
            "Set a reminder to do the dishes at 13:00 PM today.",
            "Set a reminder to do the dishes at 2:60 PM today.",
            "Set a reminder to do the dishes at 2:00 PM.",
            "Set a reminder to do the dishes today.",
            "Set a reminder to do the dishes every day at 2:00 PM today.",
            "Set a reminder to my task at 2:00 PM today.",
        ):
            with self.subTest(request=request):
                self.assertIsNone(_direct_civil_point_reminder(request))
        self.assertEqual(self.store.list_reminders(), ())

    def test_missing_day_clarification_resolves_bounded_follow_up_without_provider(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        for index, reply in enumerate(("Today", "Tonight", "Tomorrow")):
            conversation_id = f"chat-{index}"
            clarification = service.interpret_and_apply(
                "Remember to take out the trash at 8 PM.",
                time_context=self.context,
                conversation_id=conversation_id,
            )
            self.assertIn("today or tomorrow", clarification.text)
            self.assertTrue(service.likely_operational(
                reply, conversation_id=conversation_id
            ))
            resolved = service.interpret_and_apply(
                reply,
                time_context=self.context,
                conversation_id=conversation_id,
            )
            self.assertTrue(resolved.mutated)
            self.assertEqual(resolved.reminder.reminder_text, "take out the trash")
            expected_day = "2026-08-12" if reply == "Tomorrow" else "2026-08-11"
            self.assertTrue(resolved.reminder.scheduled_start_utc.startswith(expected_day))
        self.assertEqual(provider.requests, [])

    def test_missing_day_clarification_is_conversation_bound_and_one_reply_only(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        service.interpret_and_apply(
            "Remember to take out the trash at 8 PM.",
            time_context=self.context,
            conversation_id="chat-a",
        )
        self.assertFalse(service.likely_operational("Tonight", conversation_id="chat-b"))
        unrelated = service.interpret_and_apply(
            "Maybe later",
            time_context=self.context,
            conversation_id="chat-a",
        )
        self.assertFalse(unrelated.handled)
        self.assertFalse(service.likely_operational("Tonight", conversation_id="chat-a"))
        self.assertEqual(self.store.list_reminders(), ())
        self.assertEqual(provider.requests, [])

    def test_interpretation_failure_logs_only_safe_category(self) -> None:
        provider = IntentProvider("private malformed output")
        service = TaskService(self.store, provider, model_name="model")
        for error, category in (
            (None, "invalid_interpretation"),
            (ProviderConnectionError("private provider detail"), "provider_failure"),
        ):
            with self.subTest(category=category):
                with patch.object(provider, "interpret_task_intent", side_effect=error,
                                  return_value=ChatResponse("private malformed output", "model")):
                    with self.assertLogs("tori.task_service", level="WARNING") as logs:
                        result = service.interpret_and_apply(
                            "Set a reminder about private flexible wording", time_context=self.context
                        )
                self.assertFalse(result.mutated)
                self.assertEqual(logs.output, ["WARNING:tori.task_service:Task interpretation failed: " + category])
        self.assertEqual(self.store.list_reminders(), ())

    def test_direct_elapsed_standalone_reminders_use_captured_time_without_model(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            ("Remind me in 2 minutes to check the kitchen.", "2026-08-10T15:02:00Z", "check the kitchen"),
            ("Remind me in 15 minutes to check the oven.", "2026-08-10T15:15:00Z", "check the oven"),
            ("Remind me in an hour to call the shop.", "2026-08-10T16:00:00Z", "call the shop"),
        )
        for request, expected_start, expected_text in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertTrue(result.handled)
                self.assertTrue(result.mutated)
                self.assertEqual(result.intent, "create_reminder")
                self.assertIsNone(result.task)
                self.assertIsNotNone(result.reminder)
                self.assertEqual(result.reminder.reminder_text, expected_text)
                self.assertEqual(result.reminder.scheduled_start_utc, expected_start)
                self.assertEqual(result.reminder.scheduled_timezone, "America/Chicago")
                self.assertIsNone(result.reminder.task_id)
                self.assertEqual(result.reminder.status, "scheduled")
                self.assertIn("I’ll remind you at", result.text)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_tasks(), ())
        self.assertEqual(len(self.store.list_reminders()), 3)

    def test_direct_elapsed_word_orders_are_canonically_equivalent(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        pairs = (
            (
                "Remind me in 2 minutes to make another sandwich.",
                "Remind me to make another sandwich in 2 minutes.",
                "make another sandwich", "2026-08-10T15:02:00Z",
            ),
            (
                "Remind me in 15 minutes to check the oven.",
                "Remind me to check the oven in 15 minutes.",
                "check the oven", "2026-08-10T15:15:00Z",
            ),
            (
                "Remind me in an hour to call the shop.",
                "Remind me to call the shop in an hour.",
                "call the shop", "2026-08-10T16:00:00Z",
            ),
            (
                "Remind me in one hour to check the mail.",
                "Remind me to check the mail in one hour.",
                "check the mail", "2026-08-10T16:00:00Z",
            ),
            (
                "Remind me in 1 hour to lock the door.",
                "Remind me to lock the door in 1 hour.",
                "lock the door", "2026-08-10T16:00:00Z",
            ),
        )
        for duration_first, action_first, expected_text, expected_start in pairs:
            results = tuple(
                service.interpret_and_apply(request, time_context=self.context)
                for request in (duration_first, action_first)
            )
            with self.subTest(duration_first=duration_first, action_first=action_first):
                for result in results:
                    self.assertTrue(result.mutated)
                    self.assertEqual(result.intent, "create_reminder")
                    self.assertIsNone(result.task)
                    self.assertIsNone(result.reminder.task_id)
                    self.assertEqual(result.reminder.reminder_text, expected_text)
                    self.assertEqual(result.reminder.scheduled_start_utc, expected_start)
                    self.assertEqual(result.reminder.scheduled_timezone, "America/Chicago")
                    self.assertEqual(result.reminder.status, "scheduled")
                self.assertEqual(
                    results[0].reminder.scheduled_start_utc,
                    results[1].reminder.scheduled_start_utc,
                )
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_tasks(), ())
        self.assertEqual(len(self.store.list_reminders()), 10)

    def test_direct_civil_point_word_orders_use_authoritative_time_without_model(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                "Remind me tomorrow at 11 PM to back up Tori.",
                "back up Tori",
                "2026-08-12T04:00:00Z",
            ),
            (
                "Remind me to back up Tori tomorrow at 11 PM.",
                "back up Tori",
                "2026-08-12T04:00:00Z",
            ),
            (
                "Remind me tomorrow at 11 PM to check the kitchen.",
                "check the kitchen",
                "2026-08-12T04:00:00Z",
            ),
            (
                "Remind me to check the kitchen tomorrow at 11 PM.",
                "check the kitchen",
                "2026-08-12T04:00:00Z",
            ),
        )
        for request, expected_text, expected_start in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(
                    request, time_context=self.context
                )
                self.assertTrue(result.handled)
                self.assertTrue(result.mutated)
                self.assertEqual(result.intent, "create_reminder")
                self.assertIsNone(result.task)
                self.assertEqual(result.reminder.reminder_text, expected_text)
                self.assertEqual(
                    result.reminder.scheduled_start_utc, expected_start
                )
                self.assertEqual(
                    result.reminder.scheduled_timezone, "America/Chicago"
                )
                self.assertIsNone(result.reminder.scheduled_end_utc)
                self.assertIsNone(result.reminder.task_id)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_tasks(), ())
        self.assertEqual(len(self.store.list_reminders()), 4)

    def test_direct_civil_point_preserves_reminder_dst_rejection(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                TimeContext(
                    datetime(2026, 3, 7, 18, 0, tzinfo=timezone.utc),
                    "America/Chicago",
                ),
                "Set a reminder to check the kitchen at 2:30 AM tomorrow.",
                "does not exist",
            ),
            (
                TimeContext(
                    datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc),
                    "America/Chicago",
                ),
                "Set a reminder to check the kitchen tomorrow at 1:30 AM.",
                "occurs twice",
            ),
        )
        for context, request, expected_text in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=context)
                self.assertTrue(result.handled)
                self.assertFalse(result.mutated)
                self.assertEqual(result.intent, "clarify")
                self.assertIn(expected_text, result.text.casefold())
                self.assertIn("nothing changed", result.text.casefold())
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_reminders(), ())

    def test_elapsed_parser_nonmatches_preserve_specific_routes(self) -> None:
        ordinary_cases = (
            "I should probably make a sandwich in 2 minutes.",
            "Can you tell me what happens in 2 minutes?",
        )
        for request in ordinary_cases:
            provider = IntentProvider(intent("none"))
            result = TaskService(self.store, provider, model_name="model").interpret_and_apply(
                request, time_context=self.context
            )
            self.assertFalse(result.handled)
            self.assertEqual(len(provider.requests), 1)

        for request in (
            "Remind me to stretch in 2 minutes every day.",
            "Remind me to work on my task in 2 minutes.",
        ):
            provider = IntentProvider(intent("clarify", clarification="Please clarify that request."))
            result = TaskService(self.store, provider, model_name="model").interpret_and_apply(
                request, time_context=self.context
            )
            self.assertFalse(result.mutated)
            self.assertEqual(result.intent, "clarify")
            self.assertEqual(len(provider.requests), 1)

        provider = IntentProvider(intent("create_reminder", reminder_text="Call", schedule={
            "kind": "civil", "date": "2026-08-10", "time": "14:48",
            "end_date": None, "end_time": None, "minutes": None,
        }))
        civil = TaskService(self.store, provider, model_name="model").interpret_and_apply(
            "Could you remind me about calling at 2:48 PM today?", time_context=self.context
        )
        self.assertTrue(civil.mutated)
        self.assertEqual(len(provider.requests), 1)

        window_provider = IntentProvider()
        window = TaskService(self.store, window_provider, model_name="model").interpret_and_apply(
            "Remind me to take a break between 12:10 PM and 12:20 PM today.",
            time_context=self.context,
        )
        self.assertTrue(window.mutated)
        self.assertIsNotNone(window.reminder.scheduled_end_utc)
        self.assertEqual(window_provider.requests, [])

        task = self.store.create_task("finish stacking the boxes")
        link_provider = IntentProvider()
        linked = TaskService(self.store, link_provider, model_name="model").interpret_and_apply(
            "Add a reminder to my existing task “finish stacking the boxes” for 2 minutes from now.",
            time_context=self.context,
        )
        self.assertEqual(linked.reminder.task_id, task.identifier)
        self.assertEqual(link_provider.requests, [])

    def test_malformed_elapsed_candidates_clarify_without_model_or_mutation(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        for request in (
            "Remind me to make a sandwich in five minutes.",
            "Remind me to make a sandwich in 2 hours.",
            "Remind me in 0 minutes to make a sandwich.",
            "Remind me in 2 minutes.",
            "Remind me to in 2 minutes.",
        ):
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertFalse(result.mutated)
                self.assertEqual(result.intent, "clarify")
                self.assertIn("supported duration", result.text)
                self.assertNotIn("local date", result.text)
                self.assertNotIn("couldn't save", result.text)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_reminders(), ())

    def test_direct_elapsed_reminder_failure_cannot_claim_success(self) -> None:
        service = self.service()
        with patch.object(
            self.store,
            "create_reminder",
            side_effect=OperationalUnavailableError("synthetic private failure"),
        ):
            result = service.interpret_and_apply(
                "Remind me in 2 minutes to check the kitchen.",
                time_context=self.context,
            )
        self.assertFalse(result.mutated)
        self.assertIn("not changed", result.text)
        for false_claim in ("saved", "scheduled", "I’ll remind"):
            self.assertNotIn(false_claim.casefold(), result.text.casefold())
        self.assertEqual(self.store.list_reminders(), ())

    def test_exact_live_civil_window_is_standalone_verified_and_due_at_start(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")

        result = service.interpret_and_apply(
            "Remind me to take a break between 12:10 PM and 12:20 PM today.",
            time_context=self.context,
        )

        self.assertTrue(result.handled)
        self.assertTrue(result.mutated)
        self.assertEqual(result.intent, "create_reminder")
        self.assertIsNone(result.task)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_tasks(), ())
        reminders = self.store.list_reminders()
        self.assertEqual(len(reminders), 1)
        reminder = reminders[0]
        self.assertEqual(reminder, result.reminder)
        self.assertIsNone(reminder.task_id)
        self.assertEqual(reminder.reminder_text, "take a break")
        self.assertEqual(reminder.scheduled_start_utc, "2026-08-10T17:10:00Z")
        self.assertEqual(reminder.scheduled_end_utc, "2026-08-10T17:20:00Z")
        self.assertEqual(reminder.scheduled_timezone, "America/Chicago")
        self.assertEqual(reminder.status, "scheduled")
        self.assertIn("12:10 PM–12:20 PM CDT", result.text)
        self.assertNotIn("12:15", result.text)

        scheduler = ReminderScheduler(self.store, clock=self.clock)
        self.clock.set(datetime(2026, 8, 10, 17, 9, 59, tzinfo=timezone.utc))
        self.assertEqual(scheduler.scan_once(), ())
        self.assertEqual(self.store.get_reminder(reminder.identifier).status, "scheduled")
        self.clock.set(datetime(2026, 8, 10, 17, 10, tzinfo=timezone.utc))
        due = scheduler.scan_once()
        self.assertEqual([item.identifier for item in due], [reminder.identifier])
        due_reminder = self.store.get_reminder(reminder.identifier)
        self.assertEqual(due_reminder.status, "due")
        self.assertEqual(due_reminder.scheduled_end_utc, "2026-08-10T17:20:00Z")

    def test_direct_civil_window_persistence_failure_cannot_claim_success(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        with patch.object(
            self.store,
            "create_reminder",
            side_effect=OperationalUnavailableError("synthetic private failure"),
        ):
            result = service.interpret_and_apply(
                "Remind me to take a break between 12:10 PM and 12:20 PM today.",
                time_context=self.context,
            )
        self.assertFalse(result.mutated)
        self.assertEqual(result.intent, "create_reminder")
        self.assertIn("not changed", result.text)
        for false_claim in ("saved", "scheduled", "I’ll remind"):
            self.assertNotIn(false_claim.casefold(), result.text.casefold())
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_reminders(), ())

    def test_direct_civil_window_supports_tomorrow_and_twelve_hour_edges(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                "Remind me between 3 PM and 4 PM tomorrow to call the shop.",
                "call the shop", "2026-08-11T20:00:00Z", "2026-08-11T21:00:00Z",
            ),
            (
                "Remind me to check the doors between 12:00 AM and 12:00 PM tomorrow.",
                "check the doors", "2026-08-11T05:00:00Z", "2026-08-11T17:00:00Z",
            ),
        )
        for request, text, start, end in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertTrue(result.mutated)
                self.assertEqual(result.reminder.reminder_text, text)
                self.assertEqual(result.reminder.scheduled_start_utc, start)
                self.assertEqual(result.reminder.scheduled_end_utc, end)
                self.assertIsNone(result.reminder.task_id)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_tasks(), ())

    def test_direct_civil_window_equal_bounds_follow_store_policy(self) -> None:
        result = self.service().interpret_and_apply(
            "Remind me to stretch between 3 PM and 3 PM tomorrow.",
            time_context=self.context,
        )
        self.assertTrue(result.mutated)
        self.assertEqual(
            result.reminder.scheduled_start_utc,
            result.reminder.scheduled_end_utc,
        )

    def test_invalid_or_incomplete_direct_windows_clarify_without_mutation(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                "Remind me to call between 4 PM and 3 PM tomorrow.",
                "before its start",
            ),
            (
                "Remind me to call between 3 PM tomorrow.",
                "one start time, one end time",
            ),
            (
                "Remind me between nonsense and 4 PM tomorrow to call.",
                "one start time, one end time",
            ),
        )
        for request, wording in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertFalse(result.mutated)
                self.assertEqual(result.intent, "clarify")
                self.assertIn(wording, result.text)
                self.assertNotIn("couldn't save", result.text)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_reminders(), ())

    def test_direct_civil_window_dst_gap_and_overlap_clarify(self) -> None:
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                TimeContext(datetime(2026, 3, 8, 6, tzinfo=timezone.utc), "America/Chicago"),
                "Remind me to check the clock between 2:10 AM and 3:20 AM today.",
                "does not exist",
            ),
            (
                TimeContext(datetime(2026, 11, 1, 5, tzinfo=timezone.utc), "America/Chicago"),
                "Remind me to check the clock between 1:10 AM and 2:20 AM today.",
                "occurs twice",
            ),
        )
        for context, request, wording in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=context)
                self.assertFalse(result.mutated)
                self.assertEqual(result.intent, "clarify")
                self.assertIn(wording, result.text)
                self.assertNotIn("couldn't save", result.text)
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_reminders(), ())

    def test_model_cannot_replace_or_drop_an_explicit_window(self) -> None:
        midpoint = intent("create_reminder", reminder_text="Take a break", schedule={
            "kind": "civil", "date": "2026-08-10", "time": "12:15",
            "end_date": None, "end_time": None, "minutes": None,
        })
        dropped_end = intent("create_reminder", reminder_text="Take a break", schedule={
            "kind": "civil", "date": "2026-08-10", "time": "12:10",
            "end_date": None, "end_time": None, "minutes": None,
        })
        mixed = intent("create_reminder", reminder_text="Take a break", schedule={
            "kind": "elapsed", "date": "2026-08-10", "time": "12:10",
            "end_date": "2026-08-10", "end_time": "12:20", "minutes": 15,
        })
        reversed_window = intent("create_reminder", reminder_text="Take a break", schedule={
            "kind": "civil", "date": "2026-08-10", "time": "16:00",
            "end_date": "2026-08-10", "end_time": "15:00", "minutes": None,
        })
        service = self.service(midpoint, dropped_end, mixed, reversed_window)
        requests = (
            "Could you remind me sometime between 12:10 PM and 12:20 PM today to take a break?",
            "Could you remind me between 12:10 PM and 12:20 PM today about a break?",
            "Could you remind me during the interval between noon and lunch today?",
            "Could you remind me during a window between late afternoon and earlier afternoon?",
        )
        for request in requests:
            result = service.interpret_and_apply(request, time_context=self.context)
            self.assertFalse(result.mutated)
            self.assertIn("nothing changed", result.text.casefold())
            self.assertNotIn("couldn't save", result.text.casefold())
        self.assertEqual(self.store.list_reminders(), ())

    def test_direct_existing_task_elapsed_reminder_links_without_duplicate(self) -> None:
        original = self.store.create_task("finish stacking the boxes in the garage")
        original_revision = original.revision
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")
        cases = (
            (
                "Add a reminder to my existing task “finish stacking the boxes in the garage” for 2 minutes from now.",
                "2026-08-10T15:02:00Z",
            ),
            (
                'Add a reminder to my existing task "FINISH   STACKING THE BOXES IN THE GARAGE" for 15 minutes from now.',
                "2026-08-10T15:15:00Z",
            ),
            (
                "Add a reminder to my existing task “finish stacking the boxes in the garage” for one hour from now.",
                "2026-08-10T16:00:00Z",
            ),
        )
        for request, expected_start in cases:
            with self.subTest(request=request):
                result = service.interpret_and_apply(request, time_context=self.context)
                self.assertTrue(result.handled)
                self.assertTrue(result.mutated)
                self.assertEqual(result.intent, "create_reminder")
                self.assertEqual(result.task.identifier, original.identifier)
                self.assertEqual(result.reminder.task_id, original.identifier)
                self.assertEqual(result.reminder.scheduled_start_utc, expected_start)
                self.assertEqual(result.reminder.scheduled_timezone, "America/Chicago")
                self.assertIn("I’ll remind you about", result.text)
                self.assertNotIn("Added", result.text)
        tasks = self.store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].identifier, original.identifier)
        self.assertEqual(tasks[0].revision, original_revision)
        self.assertEqual(len(self.store.list_reminders()), 3)
        self.assertEqual(provider.requests, [])

    def test_direct_existing_task_duplicate_description_clarifies_without_mutation(self) -> None:
        first = self.store.create_task("finish stacking the boxes in the garage")
        second = self.store.create_task("finish stacking the boxes in the garage")
        before_tasks = self.store.list_tasks()
        before_revision = self.store.revision()
        provider = IntentProvider()
        service = TaskService(self.store, provider, model_name="model")

        result = service.interpret_and_apply(
            "Add a reminder to my existing task “finish stacking the boxes in the garage” for 2 minutes from now.",
            time_context=self.context,
        )

        self.assertTrue(result.handled)
        self.assertFalse(result.mutated)
        self.assertEqual(result.intent, "clarify")
        self.assertIn("multiple open tasks", result.text)
        self.assertIn("Which one", result.text)
        self.assertNotIn("couldn't save", result.text)
        self.assertEqual(self.store.list_tasks(), before_tasks)
        self.assertEqual({task.identifier for task in before_tasks}, {first.identifier, second.identifier})
        self.assertEqual(self.store.list_reminders(), ())
        self.assertEqual(self.store.revision(), before_revision)
        self.assertEqual(provider.requests, [])

    def test_clear_task_standalone_reminder_and_linked_pair_create_without_confirmation(self) -> None:
        service = self.service(
            intent("create_task", task_text="Finish stacking boxes"),
            intent("create_reminder", reminder_text="Take lunch", schedule={
                "kind": "civil", "date": "2026-08-10", "time": "11:00",
                "end_date": "2026-08-10", "end_time": "12:00", "minutes": None,
            }),
            intent("create_task_with_reminder", task_text="Call Mom", reminder_text="Call Mom", schedule={
                "kind": "elapsed", "date": None, "time": None,
                "end_date": None, "end_time": None, "minutes": 15,
            }),
        )
        first = service.interpret_and_apply("Add boxes to my tasks", time_context=self.context)
        second = service.interpret_and_apply("Remind me to take lunch", time_context=self.context)
        third = service.interpret_and_apply("Add call Mom and remind me in 15 minutes", time_context=self.context)
        self.assertTrue(first.mutated and second.mutated and third.mutated)
        self.assertIsNone(second.reminder.task_id)
        self.assertEqual(second.reminder.scheduled_end_utc, "2026-08-10T17:00:00Z")
        self.assertEqual(third.reminder.task_id, third.task.identifier)
        self.assertNotIn("confirm", first.text.lower())

    def test_missing_schedule_clarifies_and_malformed_or_fabricated_target_never_mutates(self) -> None:
        task = self.store.create_task("Real task")
        service = self.service(
            intent("create_reminder", reminder_text="No time"),
            "```json\n{}\n```",
            intent("complete_task", target="task-" + "f" * 32),
        )
        missing = service.interpret_and_apply("Remind me later", time_context=self.context)
        malformed = service.interpret_and_apply("Complete my task", time_context=self.context)
        fabricated = service.interpret_and_apply("Complete it", time_context=self.context)
        self.assertIn("When", missing.text)
        self.assertIn("nothing changed", malformed.text)
        self.assertIn("not changed", fabricated.text)
        self.assertEqual(self.store.get_task(task.identifier).status, "open")

    def test_target_allowlist_mutation_delay_and_discuss(self) -> None:
        task = self.store.create_task("Open task")
        reminder = self.store.create_reminder(
            "Original reminder",
            scheduled_start_utc="2026-08-10T16:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        service = self.service(
            intent("complete_task", target=task.identifier),
            intent("delay_reminder", target=reminder.identifier, schedule={
                "kind": "elapsed", "date": None, "time": None,
                "end_date": None, "end_time": None, "minutes": 120,
            }),
            intent("discuss", target=reminder.identifier),
        )
        completed = service.interpret_and_apply("Complete the task", time_context=self.context)
        delayed = service.interpret_and_apply("Delay the reminder an hour", time_context=self.context)
        discussed = service.interpret_and_apply("Discuss that reminder", time_context=self.context)
        self.assertEqual(completed.task.status, "completed")
        self.assertEqual(delayed.reminder.scheduled_start_utc, "2026-08-10T17:00:00Z")
        self.assertFalse(discussed.mutated)
        self.assertIn(reminder.identifier, discussed.discuss_context)

    def test_complete_linked_reminder_uses_atomic_done_semantics(self) -> None:
        task, reminder = self.store.create_task_with_reminder(
            "Finish the boxes",
            "Finish the boxes now",
            scheduled_start_utc="2026-08-10T15:00:00Z",
            scheduled_timezone="America/Chicago",
        )
        service = self.service(intent("complete_reminder", target=reminder.identifier))
        result = service.interpret_and_apply(
            "I'm done with that reminder", time_context=self.context
        )
        self.assertTrue(result.mutated)
        self.assertEqual(result.reminder.status, "completed")
        self.assertEqual(result.reminder.resolution, "task_completed")
        self.assertEqual(self.store.get_task(task.identifier).status, "completed")

    def test_ambiguous_dst_never_schedules_or_claims_success(self) -> None:
        service = self.service(intent("create_reminder", reminder_text="DST", schedule={
            "kind": "civil", "date": "2026-11-01", "time": "01:30",
            "end_date": None, "end_time": None, "minutes": None,
        }))
        result = service.interpret_and_apply("Remind me at 1:30", time_context=self.context)
        self.assertIn("occurs twice", result.text)
        self.assertEqual(self.store.list_reminders(), ())

    def test_store_and_post_write_verification_failures_never_claim_success(self) -> None:
        for failure in (
            OperationalUnavailableError("private database diagnostic"),
            OperationalVerificationError("private verification diagnostic"),
        ):
            with self.subTest(failure=type(failure).__name__):
                service = self.service(intent("create_task", task_text="Unsaved task"))
                with patch.object(self.store, "create_task", side_effect=failure):
                    result = service.interpret_and_apply(
                        "Add this to my tasks", time_context=self.context
                    )
                self.assertFalse(result.mutated)
                self.assertIn("not changed", result.text)
                for false_claim in ("added", "saved", "completed", "scheduled"):
                    self.assertNotIn(false_claim, result.text.casefold())
        self.assertEqual(self.store.list_tasks(), ())

    def test_extra_fields_and_recurring_schedule_have_zero_authority(self) -> None:
        malformed = intent("create_task", task_text="Bad")
        malformed["canonical_id"] = "task-" + "f" * 32
        service = self.service(
            malformed,
            intent(
                "clarify",
                clarification="Recurring reminders are not supported yet.",
            ),
        )
        first = service.interpret_and_apply("Add a task", time_context=self.context)
        second = service.interpret_and_apply(
            "Remind me every day", time_context=self.context
        )
        self.assertIn("nothing changed", first.text)
        self.assertIn("not supported", second.text)
        self.assertEqual(self.store.list_tasks(), ())

    def test_provider_clarification_cannot_claim_unverified_persistence(self) -> None:
        service = self.service(intent(
            "clarify",
            clarification="Saved and scheduled that reminder for you.",
        ))
        result = service.interpret_and_apply(
            "Remind me sometime", time_context=self.context
        )
        self.assertFalse(result.mutated)
        self.assertEqual(
            result.text,
            "I need a little more detail before I can do that. Nothing changed.",
        )
        self.assertEqual(self.store.list_reminders(), ())

    def test_noop_modification_does_not_claim_a_change(self) -> None:
        task = self.store.create_task("Already exact")
        service = self.service(intent(
            "modify_task",
            target=task.identifier,
            task_text="Already exact",
        ))
        result = service.interpret_and_apply(
            "Keep that task as Already exact", time_context=self.context
        )
        self.assertFalse(result.mutated)
        self.assertIn("Nothing changed", result.text)
        self.assertEqual(self.store.get_task(task.identifier).revision, 1)

    def test_model_cannot_turn_read_or_casual_text_into_a_mutation(self) -> None:
        for text in ("What reminders do I have?", "Too much to do then wait and unpredictable lol"):
            service = self.service(intent("create_task", task_text="Invented task"))
            result = service.interpret_and_apply(text, time_context=self.context)
            self.assertFalse(result.mutated)
            self.assertEqual(result.intent, "clarify")
            self.assertEqual(self.store.list_tasks(), ())

    def test_model_cannot_change_requested_operation_family(self) -> None:
        task = self.store.create_task("Keep this")
        service = self.service(intent("cancel_task", target=task.identifier))
        result = service.interpret_and_apply("Add another task", time_context=self.context)
        self.assertFalse(result.mutated)
        self.assertEqual(self.store.get_task(task.identifier), task)


if __name__ == "__main__":
    unittest.main()
