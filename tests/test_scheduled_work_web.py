from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch

from tori.actions import ActionDefinition, PermissionClass
from tori.backups import BackupError, BackupService
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService, ChatServiceError, completed_model_history
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.project_application import ProjectApplicationService
from tori.providers import ChatResponse, ModelProvider
from tori.scheduled_work import (
    ScheduledCapabilityCatalog,
    ScheduledWorkCoordinator,
    ScheduledWorkExecutor,
    ScheduledWorkUnavailableError,
    SQLiteScheduledWorkStore,
    one_shot_schedule,
)
from tori.tasks import SQLiteOperationalStore
from tori.web import WebApplication, WebApplicationError


class _Provider(ModelProvider):
    def __init__(self) -> None:
        self.chat_requests = []
        self.stream_requests = []
        self.answer = "ordinary answer"

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.chat_requests.append(tuple(messages))
        return ChatResponse(self.answer, "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.stream_requests.append(tuple(messages))
        yield self.answer


class _FailIfSearched:
    enabled = True
    available = True

    def __init__(self) -> None:
        self.queries = []

    def search(self, query, *, category="general"):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        raise AssertionError("scheduled backup routing must not search")


class ScheduledWorkWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
        self.store = SQLiteScheduledWorkStore(
            self.root / "scheduled" / "tori.db", clock=lambda: self.now
        )
        self.store.initialize()
        self.operational = SQLiteOperationalStore(
            self.root / "tasks" / "tori.db", clock=lambda: self.now
        )
        self.operational.initialize()
        project = self.root / "project"
        project.mkdir()
        backup_root = self.root / "backups"
        self.backup = BackupService(
            project_root=project, backup_root=backup_root, clock=lambda: self.now
        )
        self.archive = ConversationArchiveStore(
            self.root / "conversations" / "tori.db", clock=lambda: self.now
        )
        self.chats = ChatService(self.archive)
        self.provider = _Provider()
        self.search = _FailIfSearched()
        self.application = WebApplication(
            self.provider,
            port=8123,
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "memory" / "tori.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "knowledge", working_directory=self.root
            ),
            provider_name="test",
            model_name="test-model",
            chat_service=self.chats,
            backup_service=self.backup,
            operational_store=self.operational,
            scheduled_work_store=self.store,
            web_search=self.search,
            timezone_name="America/Chicago",
            utc_clock=lambda: self.now,
        )

    def test_future_work_and_coordinator_waiting_never_report_working(self) -> None:
        definition = self.application._actions.definition("tori.backup")
        due = self.now + timedelta(minutes=2)
        item, _authorization = self.store.create_definition(
            title="Future backup",
            definition=definition,
            arguments={},
            schedule=one_shot_schedule(due, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="explicit_test_confirmation",
        )
        current = [self.now]
        coordinator = ScheduledWorkCoordinator(
            self.store,
            self.application.scheduled_capability_catalog,
            clock=lambda: current[0],
            recheck_seconds=0.05,
        )
        self.application.set_scheduled_work_coordinator(coordinator)
        coordinator.start()
        self.addCleanup(coordinator.stop)

        self.assertTrue(coordinator.running)
        self.assertTrue(coordinator.worker_running)
        self.assertFalse(self.application.busy)
        self.assertFalse(self.application.session_state()["busy"])
        self.assertFalse(self.application.checkpoints_state()["busy"])
        self.assertEqual(self.store.list_runs(), ())

        paused = self.application.scheduled_work_action(
            "pause", item.identifier, item.revision
        )[1]["definition"]
        resumed = self.application.scheduled_work_action(
            "resume", item.identifier, paused["revision"]
        )[1]["definition"]
        self.assertEqual(resumed["status"], "active")
        self.assertFalse(self.application.busy)

        current[0] = due - timedelta(minutes=1)
        coordinator.notify_schedule_changed()
        threading.Event().wait(0.1)
        self.assertEqual(self.store.list_runs(), ())
        self.assertFalse(self.application.session_state()["busy"])
        self.assertFalse(self.application.memories_state()["busy"])
        self.assertFalse(self.application.knowledge_state()["busy"])

    def test_quiet_result_reconciliation_is_not_global_working_state(self) -> None:
        entered = threading.Event()
        release = threading.Event()

        def hold_delivery() -> None:
            entered.set()
            self.assertTrue(release.wait(2))

        with patch.object(
            self.application,
            "_deliver_pending_scheduled_results",
            side_effect=hold_delivery,
        ):
            with ThreadPoolExecutor(max_workers=1) as executor:
                request = executor.submit(self.application.attention_state)
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.application._operation_lock.locked())
                self.assertFalse(self.application.busy)
                self.assertFalse(self.application.session_state()["busy"])
                self.assertFalse(self.application.checkpoints_state()["busy"])
                self.assertFalse(self.application.memories_state()["busy"])
                self.assertFalse(self.application.knowledge_state()["busy"])
                release.set()
                self.assertTrue(request.result(timeout=2)["ok"])

        self.assertFalse(self.application._operation_lock.locked())
        self.assertFalse(self.application.session_state()["busy"])

    def test_every_scheduled_terminal_executor_path_leaves_status_not_working(self) -> None:
        def invalid_result(_result):  # type: ignore[no-untyped-def]
            raise ValueError("synthetic invalid scheduled result")

        cases = (
            ActionDefinition(
                "test.scheduled.success", "Success", "test only",
                PermissionClass.PERSISTENT, lambda arguments: {},
                lambda arguments, invocation_id: {"ok": True},
                scheduled_one_shot_eligible=True,
            ),
            ActionDefinition(
                "test.scheduled.failure", "Failure", "test only",
                PermissionClass.PERSISTENT, lambda arguments: {},
                lambda arguments, invocation_id: (_ for _ in ()).throw(
                    BackupError("synthetic capability failure")
                ),
                scheduled_one_shot_eligible=True,
            ),
            ActionDefinition(
                "test.scheduled.exception", "Exception", "test only",
                PermissionClass.PERSISTENT, lambda arguments: {},
                lambda arguments, invocation_id: (_ for _ in ()).throw(
                    RuntimeError("synthetic executor exception")
                ),
                scheduled_one_shot_eligible=True,
            ),
            ActionDefinition(
                "test.scheduled.invalid-result", "Invalid result", "test only",
                PermissionClass.PERSISTENT, lambda arguments: {},
                lambda arguments, invocation_id: {"invalid": True},
                scheduled_one_shot_eligible=True,
                _validate_result=invalid_result,
            ),
        )
        for capability in cases:
            with self.subTest(capability=capability.identifier):
                self.store.create_definition(
                    title=capability.name,
                    definition=capability,
                    arguments={},
                    schedule=one_shot_schedule(self.now, "America/Chicago"),
                    missed_policy="run_when_available",
                    confirmation_provenance="explicit_test_confirmation",
                )
                self.store.claim_due(self.now)
                terminal = ScheduledWorkExecutor(
                    self.store, ScheduledCapabilityCatalog((capability,))
                ).execute_next()
                self.assertIsNotNone(terminal)
                self.assertIn(terminal.status, {"succeeded", "failed"})
                self.assertFalse(self.application.busy)
                self.assertFalse(self.application.session_state()["busy"])

    def test_terminal_delivery_failure_refresh_and_multiple_browsers_are_not_busy(self) -> None:
        self.application.submit("Keep an origin-bound conversation.")
        active_id = self.chats.active_chat_id()
        self.assertIsNotNone(active_id)
        capability = ActionDefinition(
            "test.scheduled.delivery", "Delivery", "test only",
            PermissionClass.PERSISTENT, lambda arguments: {},
            lambda arguments, invocation_id: {"ok": True},
            scheduled_one_shot_eligible=True,
        )
        self.store.create_definition(
            title="Delivery result",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="explicit_test_confirmation",
            origin_chat_id=active_id,
        )
        self.store.claim_due(self.now)
        terminal = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        self.assertEqual(terminal.status, "succeeded")

        with patch.object(
            self.chats,
            "append_application_event",
            side_effect=ChatServiceError(
                "synthetic delivery failure", code="store_unavailable"
            ),
        ), self.assertRaises(ChatServiceError):
            self.application.attention_state()
        self.assertFalse(self.application.busy)
        self.assertFalse(self.application.session_state()["busy"])
        self.assertEqual(len(self.store.pending_notifications()), 1)

        self.application.attention_state()
        self.assertEqual(self.store.pending_notifications(), ())
        restarted = WebApplication(
            self.provider,
            port=8123,
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=self.application._memory_store,
            knowledge_registry=self.application._knowledge_registry,
            provider_name="test",
            model_name="test-model",
            chat_service=ChatService(self.archive),
            operational_store=self.operational,
            scheduled_work_store=self.store,
            timezone_name="America/Chicago",
            utc_clock=lambda: self.now,
        )
        self.assertFalse(self.application.session_state()["busy"])
        self.assertFalse(restarted.session_state()["busy"])
        self.assertFalse(restarted.checkpoints_state()["busy"])

    def test_interactive_backup_retains_existing_visible_busy_lifecycle(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original = self.backup.create_backup

        def blocked_backup():  # type: ignore[no-untyped-def]
            entered.set()
            self.assertTrue(release.wait(2))
            return original()

        with patch.object(self.backup, "create_backup", side_effect=blocked_backup):
            with ThreadPoolExecutor(max_workers=1) as executor:
                request = executor.submit(self.application.submit, "Back up Tori.")
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.application.busy)
                self.assertTrue(self.application.session_state()["busy"])
                release.set()
                status, result = request.result(timeout=2)
        self.assertEqual(status, 200)
        self.assertEqual(result["action"]["status"], "succeeded")
        self.assertFalse(self.application.busy)

    def test_natural_backup_is_inert_until_separate_confirmation(self) -> None:
        memories_before = self.application._memory_store.list_memories()
        status, proposed = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(
            proposed["confirmation"]["action"], "scheduled_work.authorize"
        )
        summary = proposed["confirmation"]["proposal"]
        self.assertEqual(summary["capability_id"], "tori.backup")
        self.assertEqual(summary["scheduled_mode"], "one_shot")
        self.assertTrue(summary["persistent_permission"])
        self.assertNotIn("origin_chat_id", summary)
        self.assertEqual(self.chats.list_chats(), ())

        with patch.object(
            self.application._scheduled_work_application,
            "apply_draft",
            wraps=self.application._scheduled_work_application.apply_draft,
        ) as apply_draft:
            status, created = self.application.confirm(
                proposed["confirmation"]["token"], "confirm"
            )
        self.assertEqual(status, 201)
        apply_draft.assert_called_once()
        self.assertEqual(len(self.store.list_definitions()), 1)
        definition = self.store.list_definitions()[0]
        origin_id = self.chats.active_chat_id()
        self.assertIsNotNone(origin_id)
        self.assertEqual(definition.origin_chat_id, origin_id)
        origin = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(origin.metadata.completed_turn_count, 0)
        self.assertEqual(completed_model_history(origin.entries), ())
        self.assertEqual(
            [entry.application_event_type for entry in origin.entries],
            [None, "scheduled_work_proposal", "scheduled_work_created"],
        )
        authorization = self.store.get_authorization(
            definition.current_authorization_id
        )
        self.assertEqual(
            authorization.confirmation_provenance,
            "explicit_conversation_confirmation",
        )
        self.assertEqual(created["scheduled_work_revision"], self.store.revision())
        self.assertEqual(self.provider.chat_requests, [])
        self.assertEqual(self.provider.stream_requests, [])
        self.assertEqual(
            self.application._memory_store.list_memories(), memories_before
        )

    def test_confirmation_reconciles_existing_completed_chat_without_new_model_turn(self) -> None:
        self.application.submit("Start an ordinary archived conversation.")
        origin_id = self.chats.active_chat_id()
        self.assertIsNotNone(origin_id)
        before = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        provider_calls = len(self.provider.chat_requests) + len(self.provider.stream_requests)
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        self.application.confirm(proposal["confirmation"]["token"], "confirm")
        definition = self.store.list_definitions()[0]
        self.assertEqual(definition.origin_chat_id, origin_id)
        after = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(
            after.metadata.completed_turn_count,
            before.metadata.completed_turn_count,
        )
        self.assertEqual(
            len(self.provider.chat_requests) + len(self.provider.stream_requests),
            provider_calls,
        )

    def test_model_output_cannot_select_a_scheduled_work_origin(self) -> None:
        selected = "chat-" + "f" * 32
        self.provider.answer = '{"origin_chat_id":"' + selected + '"}'

        status, _response = self.application.submit(
            "Explain what an opaque conversation identifier is."
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(self.provider.chat_requests), 1)
        self.assertEqual(self.store.list_definitions(), ())
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM scheduled_authorizations"
                ).fetchone(),
                (0,),
            )

    def test_bounded_schedule_word_orders_route_before_freshness_and_remain_inert(self) -> None:
        cases = (
            (
                "Schedule a Tori backup for 11:45 PM today.",
                "2026-08-12T04:45:00Z",
            ),
            (
                "Schedule a Tori backup for today at 11:45 PM.",
                "2026-08-12T04:45:00Z",
            ),
            (
                "Schedule a Tori backup for tomorrow at 11 PM.",
                "2026-08-13T04:00:00Z",
            ),
            (
                "Schedule a Tori backup tomorrow at 11 PM.",
                "2026-08-13T04:00:00Z",
            ),
        )
        for request, expected_occurrence in cases:
            with self.subTest(request=request):
                status, proposed = self.application.submit(request)
                self.assertEqual(status, 200)
                self.assertNotIn("search the web", proposed["transcript"][-1]["text"])
                confirmation = proposed["confirmation"]
                self.assertEqual(confirmation["action"], "scheduled_work.authorize")
                summary = confirmation["proposal"]
                self.assertEqual(summary["capability_id"], "tori.backup")
                self.assertEqual(summary["capability_contract_version"], 1)
                self.assertEqual(summary["arguments"], {})
                self.assertEqual(summary["scheduled_mode"], "one_shot")
                self.assertEqual(summary["schedule"], {
                    "kind": "one_shot",
                    "timezone": "America/Chicago",
                    "occurrence_utc": expected_occurrence,
                })
                self.assertTrue(summary["persistent_permission"])
                self.assertEqual(self.store.list_definitions(), ())
                self.application.confirm(confirmation["token"], "cancel")
                self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.provider.chat_requests, [])
        self.assertEqual(self.provider.stream_requests, [])
        self.assertEqual(self.search.queries, [])

    def test_live_schedule_word_order_streams_persistent_proposal_without_search(self) -> None:
        events = list(self.application.stream_submit(
            "Schedule a Tori backup for 11:45 PM today."
        ))
        self.assertEqual(events[-1]["type"], "complete")
        confirmation = events[-1]["confirmation"]
        self.assertEqual(confirmation["action"], "scheduled_work.authorize")
        self.assertEqual(
            confirmation["proposal"]["schedule"]["occurrence_utc"],
            "2026-08-12T04:45:00Z",
        )
        self.assertEqual(self.store.list_definitions(), ())
        self.application.confirm(confirmation["token"], "cancel")
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.provider.stream_requests, [])
        self.assertEqual(self.search.queries, [])

    def test_malformed_and_elapsed_today_schedule_requests_fail_before_search(self) -> None:
        status, malformed = self.application.submit(
            "Schedule a Tori backup sometime today."
        )
        self.assertEqual(status, 200)
        self.assertNotIn("confirmation", malformed)
        self.assertIn("exact future time", malformed["transcript"][-1]["text"])
        self.assertNotIn("search the web", malformed["transcript"][-1]["text"])

        self.now = datetime(2026, 8, 12, 4, 46, tzinfo=timezone.utc)
        status, elapsed = self.application.submit(
            "Schedule a Tori backup for 11:45 PM today."
        )
        self.assertEqual(status, 200)
        self.assertNotIn("confirmation", elapsed)
        self.assertIn("not in the future", elapsed["transcript"][-1]["text"])
        self.assertNotIn("search the web", elapsed["transcript"][-1]["text"])
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.provider.chat_requests, [])
        self.assertEqual(self.provider.stream_requests, [])
        self.assertEqual(self.search.queries, [])

    def test_cancel_and_recurring_request_create_no_authority(self) -> None:
        _status, proposed = self.application.submit(
            "Back up Tori tomorrow at 11 PM."
        )
        self.application.confirm(proposed["confirmation"]["token"], "cancel")
        self.assertEqual(self.store.list_definitions(), ())

        _status, rejected = self.application.submit("Back up Tori every day.")
        self.assertNotIn("confirmation", rejected)
        self.assertIn("not authorized", rejected["transcript"][-1]["text"])
        self.assertEqual(self.store.list_definitions(), ())

    def test_reminder_wording_stays_a_reminder(self) -> None:
        with patch.object(
            self.backup, "create_backup", wraps=self.backup.create_backup
        ) as create_backup:
            status, response = self.application.submit(
                "Remind me tomorrow at 11 PM to back up Tori."
            )
        self.assertEqual(status, 200)
        self.assertNotIn("confirmation", response)
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.store.list_runs(), ())
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM scheduled_authorizations"
                ).fetchone(),
                (0,),
            )
        reminders = self.operational.list_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].reminder_text, "back up Tori")
        self.assertEqual(reminders[0].scheduled_start_utc, "2026-08-13T04:00:00Z")
        self.assertEqual(reminders[0].scheduled_timezone, "America/Chicago")
        self.assertIsNone(reminders[0].scheduled_end_utc)
        create_backup.assert_not_called()
        self.assertIn("remind", response["transcript"][-1]["text"].casefold())

    def test_action_first_and_capability_like_reminder_payloads_stay_attention_only(self) -> None:
        requests = (
            ("Remind me to back up Tori tomorrow at 11 PM.", "back up Tori"),
            (
                "Remind me tomorrow at 11 PM to review tori.backup.",
                "review tori.backup",
            ),
            ("Remind me tomorrow at 11 PM to update Ollama.", "update Ollama"),
            ("Remind me tomorrow at 11 PM to run a command.", "run a command"),
        )
        with patch.object(
            self.backup, "create_backup", wraps=self.backup.create_backup
        ) as create_backup:
            for index, (request, expected_text) in enumerate(requests, start=1):
                with self.subTest(request=request):
                    status, response = self.application.submit(request)
                    self.assertEqual(status, 200)
                    self.assertNotIn("confirmation", response)
                    reminders = self.operational.list_reminders()
                    self.assertEqual(len(reminders), index)
                    self.assertIn(
                        expected_text,
                        {reminder.reminder_text for reminder in reminders},
                    )
        create_backup.assert_not_called()
        self.assertEqual(len(self.operational.list_reminders()), 4)
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.store.list_runs(), ())
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM scheduled_authorizations"
                ).fetchone(),
                (0,),
            )

    def test_management_confirmation_and_stale_mutation(self) -> None:
        _status, proposal = self.application.propose_scheduled_backup(
            title="Nightly-looking one-shot",
            local_date="2026-08-12",
            local_time="23:00",
            missed_policy="skip_if_missed",
        )
        self.assertEqual(self.store.list_definitions(), ())
        status, created = self.application.confirm(
            proposal["confirmation"]["token"], "confirm"
        )
        self.assertEqual(status, 201)
        item = self.store.list_definitions()[0]
        self.assertIsNone(item.origin_chat_id)
        self.application.scheduled_work_action(
            "pause", item.identifier, item.revision
        )
        with self.assertRaises(WebApplicationError) as stale:
            self.application.scheduled_work_action(
                "cancel", item.identifier, item.revision
            )
        self.assertEqual(stale.exception.code, "stale_revision")
        self.assertIn("authorization", created)

    def test_management_edit_uses_persisted_timezone_and_preserves_origin(self) -> None:
        capability = self.application._actions.definition("tori.backup")
        occurrence = datetime(2026, 8, 12, 18, 25, tzinfo=timezone.utc)
        for origin in (None, "chat-" + "e" * 32):
            with self.subTest(origin=origin):
                item, original_authorization = self.store.create_definition(
                    title="Timezone-stable backup",
                    definition=capability,
                    arguments={},
                    schedule=one_shot_schedule(occurrence, "Asia/Kathmandu"),
                    missed_policy="run_when_available",
                    confirmation_provenance="explicit_test_confirmation",
                    origin_chat_id=origin,
                )
                revision_before = item.revision

                _status, proposal = self.application.propose_scheduled_backup(
                    title=item.title,
                    local_date="2026-08-13",
                    local_time="00:10",
                    missed_policy=item.missed_policy,
                    identifier=item.identifier,
                    expected_revision=item.revision,
                )

                self.assertEqual(self.store.get_definition(item.identifier), item)
                self.assertEqual(
                    self.store.get_authorization(original_authorization.identifier),
                    original_authorization,
                )
                self.assertEqual(
                    proposal["confirmation"]["proposal"]["schedule"],
                    item.schedule.document(),
                )
                _confirmed_status, result = self.application.confirm(
                    proposal["confirmation"]["token"], "confirm"
                )
                changed = self.store.get_definition(item.identifier)
                self.assertEqual(changed.revision, revision_before + 1)
                self.assertEqual(changed.schedule.document(), item.schedule.document())
                self.assertEqual(changed.origin_chat_id, origin)
                self.assertNotEqual(
                    changed.current_authorization_id,
                    original_authorization.identifier,
                )
                self.assertEqual(result["definition"]["identifier"], item.identifier)
                self.assertNotIn("origin_chat_id", result["definition"])

    def test_result_event_is_application_only_and_idempotent(self) -> None:
        self.application.submit("Hello Tori")
        active_id = self.chats.active_chat_id()
        self.assertIsNotNone(active_id)
        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {"recorded": True},
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        definition, _authorization = self.store.create_definition(
            title="Test result",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )
        self.store.claim_due(self.now)
        ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        self.application.scheduled_work_state()
        self.application.scheduled_work_state()
        detail = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        events = [
            entry for entry in detail.entries
            if entry.application_event_type == "scheduled_work_result"
        ]
        self.assertEqual(len(events), 1)
        self.assertNotIn(events[0].text, [item.content for item in completed_model_history(detail.entries)])
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(self.store.get_definition(definition.identifier).status, "completed")

    def test_no_browser_execution_stays_pending_until_reconnect_then_delivers_once(self) -> None:
        self.application.submit("Establish the archived conversation.")
        active_id = self.chats.active_chat_id()
        self.assertIsNotNone(active_id)
        before_chat = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        before_memories = self.application._memory_store.list_memories()
        before_sources = self.application._knowledge_registry.list_sources()
        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {
                "recorded": True,
                "identifier": invocation_id,
            },
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        definition, authorization = self.store.create_definition(
            title="Browserless result",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )

        # The scheduler/executor path is independent of every browser request.
        claimed = self.store.claim_due(self.now)
        self.assertEqual(len(claimed), 1)
        run = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")  # type: ignore[union-attr]
        self.assertIsNotNone(run.result)  # type: ignore[union-attr]
        notifications = self.store.pending_notifications()
        self.assertEqual(len(notifications), 1)
        notification = notifications[0]
        self.assertEqual(notification.run_id, run.identifier)  # type: ignore[union-attr]
        self.assertEqual(self.chats.get_chat(active_id), before_chat)  # type: ignore[arg-type]

        provider_calls = len(self.provider.chat_requests) + len(self.provider.stream_requests)
        search_calls = len(self.search.queries)
        extractions_before = self.chats.list_memory_extractions()
        first = self.application.attention_state()
        refreshed = self.application.attention_state()

        detail = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        events = tuple(
            entry for entry in detail.entries
            if entry.application_event_id == notification.event_identifier
        )
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event.role, "assistant")
        self.assertEqual(event.application_event_type, "scheduled_work_result")
        self.assertIsNone(event.provider)
        self.assertIsNone(event.model)
        self.assertEqual(event.sources, ())
        self.assertEqual(first["transcript_revision"], detail.metadata.revision)
        self.assertEqual(refreshed["transcript_revision"], detail.metadata.revision)
        self.assertIn(event.text, [item["text"] for item in self.application.session_state()["transcript"]])
        self.assertNotIn(event.text, [item.content for item in completed_model_history(detail.entries)])
        self.assertEqual(detail.metadata.completed_turn_count, before_chat.metadata.completed_turn_count)
        self.assertEqual(self.application._session.history, completed_model_history(before_chat.entries))
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(self.store.get_definition(definition.identifier).status, "completed")
        self.assertEqual(
            self.store.get_authorization(authorization.identifier).status,
            "exhausted",
        )
        self.assertEqual(
            len(self.provider.chat_requests) + len(self.provider.stream_requests),
            provider_calls,
        )
        self.assertEqual(len(self.search.queries), search_calls)
        self.assertEqual(self.chats.list_memory_extractions(), extractions_before)
        self.assertEqual(self.application._memory_store.list_memories(), before_memories)
        self.assertEqual(self.application._knowledge_registry.list_sources(), before_sources)

    def test_restart_and_concurrent_browsers_archive_one_pending_result(self) -> None:
        self.application.submit("Keep this conversation selected.")
        active_id = self.chats.active_chat_id()
        self.assertIsNotNone(active_id)
        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {"recorded": True},
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        self.store.create_definition(
            title="Restart result",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )
        self.store.claim_due(self.now)
        run = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        notification = self.store.pending_notifications()[0]

        def restarted_application() -> WebApplication:
            return WebApplication(
                self.provider,
                port=8123,
                checkpoint_store=CheckpointStore(self.root / "checkpoints"),
                memory_store=self.application._memory_store,
                knowledge_registry=self.application._knowledge_registry,
                provider_name="test",
                model_name="test-model",
                chat_service=ChatService(self.archive),
                operational_store=self.operational,
                scheduled_work_store=self.store,
                timezone_name="America/Chicago",
                utc_clock=lambda: self.now,
            )

        browsers = (restarted_application(), restarted_application())
        with ThreadPoolExecutor(max_workers=2) as executor:
            states = tuple(executor.map(lambda app: app.attention_state(), browsers))
        for application in browsers:
            application.attention_state()

        detail = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        events = [
            entry for entry in detail.entries
            if entry.application_event_id == notification.event_identifier
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].application_event_type, "scheduled_work_result")
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(self.store.get_run(run.identifier).status, "succeeded")  # type: ignore[union-attr]
        self.assertTrue(all(state["ok"] for state in states))
        for application in browsers:
            transcript = application.session_state()["transcript"]
            self.assertEqual(
                sum(item["text"] == events[0].text for item in transcript),
                1,
            )

    def test_opening_existing_chat_delivers_pending_failure_without_new_turn(self) -> None:
        self.application.submit("Archive this conversation.")
        active_id = self.chats.active_chat_id()
        self.assertIsNotNone(active_id)
        detail = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        self.application.new_session(True)
        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {"recorded": True},
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        self.store.create_definition(
            title="Truthful failure",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )
        claimed = self.store.claim_due(self.now)[0]
        running = self.store.start_run(claimed.identifier)
        running = self.store.mark_work_started(
            running.identifier, expected_revision=running.revision
        )
        failed = self.store.finish_run_failure(
            running.identifier,
            expected_revision=running.revision,
            code="capability_failed",
            message="The scheduled capability failed safely.",
        )
        self.assertEqual(failed.status, "failed")
        self.assertEqual(len(self.store.pending_notifications()), 1)
        self.assertEqual(
            [entry.application_event_type for entry in self.chats.get_chat(active_id).entries],  # type: ignore[arg-type]
            [entry.application_event_type for entry in detail.entries],
        )

        provider_calls = len(self.provider.chat_requests) + len(self.provider.stream_requests)
        status, opened = self.application.open_chat(active_id, detail.metadata.revision)  # type: ignore[arg-type]
        self.assertEqual(status, 200)
        self.assertIn("Scheduled work failed: Truthful failure.", opened["transcript"][-1]["text"])
        archived = self.chats.get_chat(active_id)  # type: ignore[arg-type]
        self.assertEqual(archived.entries[-1].application_event_type, "scheduled_work_result")
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(
            len(self.provider.chat_requests) + len(self.provider.stream_requests),
            provider_calls,
        )

    def test_no_active_conversation_keeps_result_pending(self) -> None:
        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {"recorded": True},
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        self.store.create_definition(
            title="No target",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )
        self.store.claim_due(self.now)
        run = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        self.application.attention_state()
        self.application.scheduled_work_state()
        self.assertEqual(len(self.store.pending_notifications()), 1)
        self.assertEqual(self.store.get_run(run.identifier).status, "succeeded")  # type: ignore[union-attr]
        self.assertEqual(self.chats.list_chats(), ())

    def test_background_result_never_poisons_an_active_project_proposal_chat(self) -> None:
        application = WebApplication(
            self.provider,
            port=8123,
            checkpoint_store=CheckpointStore(self.root / "checkpoints-proposal"),
            memory_store=self.application._memory_store,
            knowledge_registry=self.application._knowledge_registry,
            provider_name="test",
            model_name="test-model",
            chat_service=self.chats,
            project_application=ProjectApplicationService(self.chats),
            operational_store=self.operational,
            scheduled_work_store=self.store,
            web_search=self.search,
            timezone_name="America/Chicago",
            utc_clock=lambda: self.now,
        )
        status, response = application.submit(
            "Let's create a new project for rebuilding my NAS."
        )
        self.assertEqual(status, 200)
        self.assertIn("confirmation", response)
        proposal_id = self.chats.active_chat_id()
        self.assertIsNotNone(proposal_id)
        proposal_before = self.chats.get_chat(proposal_id)  # type: ignore[arg-type]
        self.assertEqual(proposal_before.metadata.completed_turn_count, 0)
        self.assertEqual(
            [entry.application_event_type for entry in proposal_before.entries],
            [None, "project_proposal"],
        )

        capability = ActionDefinition(
            "test.scheduled.record",
            "Record test",
            "test only",
            PermissionClass.PERSISTENT,
            lambda arguments: {},
            lambda arguments, invocation_id: {"recorded": True},
            scheduled_one_shot_eligible=True,
            scheduled_recurring_eligible=True,
        )
        definition, _authorization = self.store.create_definition(
            title="Background result",
            definition=capability,
            arguments={},
            schedule=one_shot_schedule(self.now, "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="test_confirmation",
        )
        claimed = self.store.claim_due(self.now)
        self.assertEqual(len(claimed), 1)
        run = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((capability,))
        ).execute_next()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")  # type: ignore[union-attr]
        pending = self.store.pending_notifications()
        self.assertEqual(len(pending), 1)
        self.assertIsNone(pending[0].origin_chat_id)

        application.attention_state()
        proposal_after = self.chats.get_chat(proposal_id)  # type: ignore[arg-type]
        self.assertEqual(proposal_after, proposal_before)
        self.assertEqual(
            [entry.application_event_type for entry in proposal_after.entries],
            [None, "project_proposal"],
        )
        self.assertEqual(self.store.pending_notifications(), pending)

        application.new_session(True)
        application.submit("Hello Tori")
        ordinary_id = self.chats.active_chat_id()
        self.assertIsNotNone(ordinary_id)
        self.assertNotEqual(ordinary_id, proposal_id)
        application.attention_state()

        delivered = self.chats.get_chat(ordinary_id)  # type: ignore[arg-type]
        events = [
            entry for entry in delivered.entries
            if entry.application_event_type == "scheduled_work_result"
        ]
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].provider)
        self.assertIsNone(events[0].model)
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(
            self.store.get_definition(definition.identifier).status, "completed"
        )

        reopened = ConversationArchiveStore(
            self.archive.path, clock=lambda: self.now
        )
        reopened.initialize()
        reloaded = reopened.get_chat(proposal_id)
        self.assertEqual(reloaded.entries, proposal_before.entries)
        self.assertEqual(reloaded.metadata.revision, proposal_before.metadata.revision)
        self.assertEqual(
            reloaded.metadata.completed_turn_count, 0
        )

    def test_conversational_origin_survives_unrelated_active_chat_restart_and_model_transition(self) -> None:
        memories_before = self.application._memory_store.list_memories()
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        status, _created = self.application.confirm(
            proposal["confirmation"]["token"], "confirm"
        )
        self.assertEqual(status, 201)
        definition = self.store.list_definitions()[0]
        origin_id = definition.origin_chat_id
        self.assertIsNotNone(origin_id)
        origin_before = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(origin_before.metadata.completed_turn_count, 0)

        self.application.new_session(True)
        self.application.submit("Keep this unrelated conversation separate.")
        unrelated_id = self.chats.active_chat_id()
        self.assertIsNotNone(unrelated_id)
        self.assertNotEqual(unrelated_id, origin_id)

        self.now = datetime.fromisoformat(
            definition.next_occurrence_utc.replace("Z", "+00:00")
        )
        claimed = self.store.claim_due(self.now)
        self.assertEqual(len(claimed), 1)
        run = ScheduledWorkExecutor(
            self.store, self.application.scheduled_capability_catalog
        ).execute_next()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "succeeded")  # type: ignore[union-attr]
        pending = self.store.pending_notifications()[0]
        self.assertEqual(pending.origin_chat_id, origin_id)

        self.application.attention_state()
        unrelated_state = self.application.session_state()
        self.assertFalse(any(
            "Scheduled work succeeded" in item["text"]
            for item in unrelated_state["transcript"]
        ))
        origin_after = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        unrelated_after = self.chats.get_chat(unrelated_id)  # type: ignore[arg-type]
        self.assertEqual(
            sum(
                item.application_event_type == "scheduled_work_created"
                for item in origin_after.entries
            ),
            1,
        )
        self.assertEqual(
            sum(
                item.application_event_type == "scheduled_work_result"
                for item in origin_after.entries
            ),
            1,
        )
        self.assertFalse(any(
            item.application_event_type == "scheduled_work_result"
            for item in unrelated_after.entries
        ))
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(
            self.application._memory_store.list_memories(), memories_before
        )

        restarted = WebApplication(
            self.provider,
            port=8123,
            checkpoint_store=CheckpointStore(self.root / "checkpoints-restart"),
            memory_store=self.application._memory_store,
            knowledge_registry=self.application._knowledge_registry,
            provider_name="test",
            model_name="test-model",
            chat_service=ChatService(self.archive),
            backup_service=self.backup,
            operational_store=self.operational,
            scheduled_work_store=self.store,
            timezone_name="America/Chicago",
            utc_clock=lambda: self.now,
        )
        status, opened = restarted.open_chat(
            origin_id, origin_after.metadata.revision  # type: ignore[arg-type]
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            sum(
                "Persistent authorization is limited to" in item["text"]
                for item in opened["transcript"]
            ),
            1,
        )
        restarted.attention_state()
        self.application.attention_state()
        stable = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(
            sum(
                item.application_event_type == "scheduled_work_result"
                for item in stable.entries
            ),
            1,
        )

        restarted.submit("What should I review now?")
        transitioned = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(transitioned.metadata.completed_turn_count, 1)
        self.assertEqual(transitioned.metadata.first_provider, "test")
        self.assertEqual(transitioned.metadata.first_model, "test-model")

    def test_origin_anchor_failure_consumes_confirmation_without_authority(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        token = proposal["confirmation"]["token"]
        with patch.object(
            self.chats,
            "establish_scheduled_work_origin",
            side_effect=ChatServiceError("injected", code="store_unavailable"),
        ), self.assertRaises(WebApplicationError) as raised:
            self.application.confirm(token, "confirm")
        self.assertEqual(raised.exception.code, "scheduled_work_origin_unavailable")
        self.assertEqual(self.store.list_definitions(), ())
        self.assertEqual(self.chats.list_chats(), ())
        with self.assertRaises(WebApplicationError) as reused:
            self.application.confirm(token, "confirm")
        self.assertEqual(reused.exception.code, "unknown_confirmation")

    def test_scheduled_commit_failure_keeps_truthful_anchor_without_work(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        with patch.object(
            self.store,
            "create_definition",
            side_effect=ScheduledWorkUnavailableError("injected"),
        ), self.assertRaises(WebApplicationError):
            self.application.confirm(proposal["confirmation"]["token"], "confirm")
        self.assertEqual(self.store.list_definitions(), ())
        origin_id = self.chats.active_chat_id()
        self.assertIsNotNone(origin_id)
        origin = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.assertEqual(origin.metadata.completed_turn_count, 0)
        self.assertEqual(
            [item.application_event_type for item in origin.entries],
            [None, "scheduled_work_proposal", "scheduled_work_creation_failed"],
        )

    def test_creation_append_response_loss_leaves_work_and_idempotent_event(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        original_append = self.chats.append_application_event

        def append_then_lose(*args, **kwargs):  # type: ignore[no-untyped-def]
            original_append(*args, **kwargs)
            raise ChatServiceError("response lost", code="verification_failed")

        with patch.object(
            self.chats, "append_application_event", side_effect=append_then_lose
        ):
            status, response = self.application.confirm(
                proposal["confirmation"]["token"], "confirm"
            )
        self.assertEqual(status, 201)
        self.assertTrue(response["partial_success"])
        definition = self.store.list_definitions()[0]
        origin = self.chats.get_chat(definition.origin_chat_id)  # type: ignore[arg-type]
        creation = [
            item for item in origin.entries
            if item.application_event_type == "scheduled_work_created"
        ]
        self.assertEqual(len(creation), 1)
        retried = original_append(
            definition.origin_chat_id,  # type: ignore[arg-type]
            expected_revision=1,
            event_id=creation[0].application_event_id,  # type: ignore[arg-type]
            event_type="scheduled_work_created",
            text=creation[0].text,
        )
        self.assertEqual(
            sum(
                item.application_event_type == "scheduled_work_created"
                for item in retried.entries
            ),
            1,
        )

    def test_creation_append_failure_leaves_work_with_a_valid_origin(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        with patch.object(
            self.chats,
            "append_application_event",
            side_effect=ChatServiceError("injected", code="store_unavailable"),
        ):
            status, response = self.application.confirm(
                proposal["confirmation"]["token"], "confirm"
            )

        self.assertEqual(status, 201)
        self.assertTrue(response["partial_success"])
        definition = self.store.list_definitions()[0]
        self.assertIsNotNone(definition.origin_chat_id)
        origin = self.chats.get_chat(definition.origin_chat_id)  # type: ignore[arg-type]
        self.assertEqual(origin.metadata.completed_turn_count, 0)
        self.assertEqual(
            [item.application_event_type for item in origin.entries],
            [None, "scheduled_work_proposal"],
        )

    def test_result_append_and_notification_mark_failures_remain_retry_safe(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        self.application.confirm(proposal["confirmation"]["token"], "confirm")
        definition = self.store.list_definitions()[0]
        self.now = datetime.fromisoformat(
            definition.next_occurrence_utc.replace("Z", "+00:00")
        )
        self.store.claim_due(self.now)
        ScheduledWorkExecutor(
            self.store, self.application.scheduled_capability_catalog
        ).execute_next()
        notification = self.store.pending_notifications()[0]

        with patch.object(
            self.chats,
            "append_application_event",
            side_effect=ChatServiceError("injected", code="store_unavailable"),
        ), self.assertRaises(ChatServiceError):
            self.application.attention_state()
        self.assertEqual(len(self.store.pending_notifications()), 1)

        with patch.object(
            self.store,
            "mark_notification_archived",
            side_effect=ScheduledWorkUnavailableError("injected"),
        ), self.assertRaises(ScheduledWorkUnavailableError):
            self.application.attention_state()
        self.assertEqual(len(self.store.pending_notifications()), 1)
        origin = self.chats.get_chat(definition.origin_chat_id)  # type: ignore[arg-type]
        self.assertEqual(
            sum(
                item.application_event_id == notification.event_identifier
                for item in origin.entries
            ),
            1,
        )

        self.application.attention_state()
        self.assertEqual(self.store.pending_notifications(), ())
        origin = self.chats.get_chat(definition.origin_chat_id)  # type: ignore[arg-type]
        self.assertEqual(
            sum(
                item.application_event_id == notification.event_identifier
                for item in origin.entries
            ),
            1,
        )

    def test_deleted_origin_never_falls_back_to_unrelated_active_chat(self) -> None:
        _status, proposal = self.application.submit(
            "Schedule a Tori backup for tomorrow at 11 PM."
        )
        self.application.confirm(proposal["confirmation"]["token"], "confirm")
        definition = self.store.list_definitions()[0]
        origin_id = definition.origin_chat_id
        origin = self.chats.get_chat(origin_id)  # type: ignore[arg-type]
        self.application.delete_chat(origin_id, origin.metadata.revision)
        self.application.submit("This is an unrelated active conversation.")
        unrelated_id = self.chats.active_chat_id()
        self.assertNotEqual(unrelated_id, origin_id)

        self.now = datetime.fromisoformat(
            definition.next_occurrence_utc.replace("Z", "+00:00")
        )
        self.store.claim_due(self.now)
        ScheduledWorkExecutor(
            self.store, self.application.scheduled_capability_catalog
        ).execute_next()
        self.application.attention_state()
        self.assertEqual(len(self.store.pending_notifications()), 1)
        unrelated = self.chats.get_chat(unrelated_id)  # type: ignore[arg-type]
        self.assertFalse(any(
            item.application_event_type == "scheduled_work_result"
            for item in unrelated.entries
        ))
        self.assertEqual(
            self.store.get_definition(definition.identifier).status, "completed"
        )


if __name__ == "__main__":
    unittest.main()
