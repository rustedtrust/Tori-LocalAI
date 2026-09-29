from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.companion_initiative import AttentionSignal, SQLiteCompanionInitiativeStore
from tori.companion_initiative_runtime import CompanionInitiativeEvaluator
from tori.companion_initiative_service import (
    CompanionInitiativeService,
    InitiativeEvaluation,
)
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.operation_coordinator import OperationCoordinator
from tori.providers import ChatResponse, ModelProvider
from tori.remote_chat import RemoteChatConfigStore
from tori.user_settings import CapabilitySettingsController
from tori.web import WebApplication, WebApplicationError, run_web_server


UTC = timezone.utc
CHAT_ID = "chat-" + "4" * 32
OTHER_CHAT_ID = "chat-" + "5" * 32


class FixedProvider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("ordinary reply", "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "ordinary reply"


class NoAnchor:
    def current(self, settings, activity, *, at):  # type: ignore[no-untyped-def]
        return None


class CountingService:
    def __init__(self) -> None:
        self.calls = 0
        self.called = threading.Event()

    def evaluate(self) -> InitiativeEvaluation:
        self.calls += 1
        self.called.set()
        return InitiativeEvaluation("suppressed", reasons=("fixture",))


class CompanionInitiativeEvaluatorTests(unittest.TestCase):
    def test_process_local_evaluator_starts_scans_and_stops_cleanly(self) -> None:
        service = CountingService()
        evaluator = CompanionInitiativeEvaluator(  # type: ignore[arg-type]
            service, recheck_seconds=0.05
        )
        evaluator.start()
        self.assertTrue(service.called.wait(1))
        self.assertTrue(evaluator.running)
        evaluator.start()
        evaluator.stop()
        self.assertFalse(evaluator.running)
        self.assertGreaterEqual(service.calls, 1)
        evaluator.stop()

    def test_web_process_composition_starts_and_stops_evaluator(self) -> None:
        class FakeServer:
            def serve_forever(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            chats = ChatService(ConversationArchiveStore(root / "archive.db"))
            chats.create_chat(
                (
                    ArchiveEntry("user", "Earlier user turn."),
                    ArchiveEntry(
                        "assistant",
                        "Earlier answer.",
                        provider="test",
                        model="test-model",
                    ),
                ),
                provider="test",
                model="test-model",
            )
            store = SQLiteCompanionInitiativeStore(root / "initiative.db")
            runtime = Mock()
            with (
                patch("tori.web.create_web_server", return_value=FakeServer()),
                patch(
                    "tori.web.CompanionInitiativeEvaluator", return_value=runtime
                ) as evaluator_type,
            ):
                result = run_web_server(
                    FixedProvider(),
                    port=8765,
                    checkpoint_store=CheckpointStore(root / "checkpoints"),
                    memory_store=SQLiteMemoryStore(root / "memory.db"),
                    knowledge_registry=KnowledgeRegistry(root / "knowledge"),
                    provider_name="test",
                    model_name="test-model",
                    chat_service=chats,
                    timezone_name="UTC",
                    companion_initiative_store=store,
                    remote_chat_config_store=RemoteChatConfigStore(root / "remote"),
                    output_function=lambda _message: None,
                )
        self.assertEqual(result, 0)
        evaluator_type.assert_called_once()
        runtime.start.assert_called_once_with()
        runtime.stop.assert_called_once_with()


class CompanionInitiativeWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
        self.store = SQLiteCompanionInitiativeStore(
            self.root / "initiative.db", clock=lambda: self.now
        )
        self.archive = ConversationArchiveStore(
            self.root / "archive.db",
            clock=lambda: self.now,
            identifier_factory=iter((CHAT_ID, OTHER_CHAT_ID)).__next__,
        )
        self.chats = ChatService(self.archive)
        self.chat = self.chats.create_chat((
            ArchiveEntry("user", "Earlier user turn."),
            ArchiveEntry(
                "assistant", "Earlier answer.", provider="test", model="test-model"
            ),
        ), provider="test", model="test-model")
        self.coordinator = OperationCoordinator()
        application: WebApplication | None = None
        self.service = CompanionInitiativeService(
            store=self.store,
            chats=self.chats,
            anchors=NoAnchor(),  # type: ignore[arg-type]
            coordinator=self.coordinator,
            timezone_name="UTC",
            clock=lambda: self.now,
            readiness=lambda: (
                application is not None
                and application.companion_initiative_ready()
            ),
            owner="slice-four-test",
        )
        application = WebApplication(
            FixedProvider(),
            port=8765,
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(self.root / "knowledge"),
            provider_name="test",
            model_name="test-model",
            chat_service=self.chats,
            timezone_name="UTC",
            utc_clock=lambda: self.now,
            operation_coordinator=self.coordinator,
            companion_initiative_store=self.store,
            companion_initiative_service=self.service,
        )
        self.application = application
        self.application._conversation_turns.configure_initiative_reply_context(
            self.service.reply_context
        )
        self.evaluator = CompanionInitiativeEvaluator(self.service)

    @staticmethod
    def settings_document(**overrides: object) -> dict[str, object]:
        document: dict[str, object] = {
            "expected_revision": 0,
            "master_enabled": False,
            "morning_enabled": False,
            "resume_enabled": False,
            "long_silence_enabled": False,
            "night_owl_findings_enabled": False,
            "morning_start": "08:00",
            "morning_end": "10:00",
            "quiet_start": "22:00",
            "quiet_end": "08:00",
        }
        document.update(overrides)
        return document

    def enable_morning(self) -> None:
        prior = self.now
        self.now -= timedelta(minutes=20)
        self.application.set_companion_initiative_settings(self.settings_document(
            master_enabled=True, morning_enabled=True
        ))
        self.now = prior

    def initiative_events(self) -> tuple[ArchiveEntry, ...]:
        return tuple(
            item for item in self.chats.get_chat(CHAT_ID).entries
            if item.application_event_type == "companion_initiative"
        )

    def create_other_chat(self):  # type: ignore[no-untyped-def]
        return self.chats.create_chat((
            ArchiveEntry("user", "Other conversation user turn."),
            ArchiveEntry(
                "assistant",
                "Other conversation answer.",
                provider="test",
                model="test-model",
            ),
        ), provider="test", model="test-model")

    def create_attention(self, *, attention_class: str = "needs_attention"):
        return self.store.reconcile_attention("research", (AttentionSignal(
            "research", "research-" + "9" * 32, "research_failed",
            "Voice research", "Requested research did not complete.",
            attention_class,
            "conversational" if attention_class == "needs_attention" else "silent",
            2, "material-one", self.now, None,
        ),))[0]

    def test_defaults_settings_persistence_toggles_and_quiet_hours(self) -> None:
        initial = self.application.settings_state()["companion_initiative"]
        self.assertTrue(initial["available"])
        self.assertEqual(initial["revision"], 0)
        self.assertFalse(initial["master_enabled"])
        self.assertFalse(initial["morning_enabled"])
        self.assertFalse(initial["resume_enabled"])
        self.assertFalse(initial["long_silence_enabled"])
        self.assertFalse(initial["night_owl_findings_enabled"])
        self.assertNotIn("candidate_key", initial)
        self.assertNotIn("lease_owner", initial)
        self.assertFalse(self.store.path.exists())

        _, response = self.application.set_companion_initiative_settings(
            self.settings_document(
                master_enabled=True,
                morning_enabled=True,
                resume_enabled=True,
                long_silence_enabled=True,
                morning_start="07:30",
                morning_end="09:45",
                quiet_start="21:15",
                quiet_end="07:00",
            )
        )
        saved = response["companion_initiative"]
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["morning_start"], "07:30")
        self.assertEqual(saved["quiet_start"], "21:15")
        reopened = SQLiteCompanionInitiativeStore(self.store.path, clock=lambda: self.now)
        self.assertTrue(reopened.settings().master_enabled)
        self.assertTrue(reopened.settings().resume_enabled)

    def test_attention_workspace_actions_are_revision_safe_and_durable(self) -> None:
        self.application.set_companion_initiative_settings(self.settings_document())
        item = self.create_attention()
        document = self.application.companion_attention_state()
        self.assertEqual(document["items"][0]["identifier"], item.identifier)
        status, updated = self.application.update_companion_attention({
            "identifier": item.identifier,
            "expected_revision": item.revision,
            "action": "later",
        })
        self.assertEqual(status, 200)
        self.assertEqual(updated["updated"]["state"], "deferred")
        with self.assertRaises(WebApplicationError):
            self.application.update_companion_attention({
                "identifier": item.identifier,
                "expected_revision": item.revision,
                "action": "dismiss",
            })

    def test_attention_conversation_read_is_provider_free_and_bounded(self) -> None:
        self.application.set_companion_initiative_settings(self.settings_document())
        self.create_attention()
        self.application._timezone_name = "America/Chicago"
        status, response = self.application.submit("What needs my attention?")
        self.assertEqual(status, 200)
        self.assertIn("Voice research", response["transcript"][-1]["text"])
        self.assertEqual(
            self.chats.get_chat(CHAT_ID).entries[-1].application_event_type,
            "companion_attention_result",
        )

    def test_invalid_and_stale_settings_are_rejected_without_change(self) -> None:
        self.application.set_companion_initiative_settings(self.settings_document())
        for changes in (
            {"expected_revision": 0},
            {"expected_revision": 1, "master_enabled": 1},
            {"expected_revision": 1, "morning_start": "9:00"},
            {"expected_revision": 1, "morning_start": "10:00", "morning_end": "08:00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(WebApplicationError):
                self.application.set_companion_initiative_settings(
                    self.settings_document(**changes)
                )
        self.assertEqual(self.store.settings().revision, 1)

    def test_active_chat_poll_reconciles_new_event_once_without_chat_switch(self) -> None:
        self.enable_morning()
        initial = self.application.session_state()
        initial_revision = initial["transcript_revision"]
        before_activity = self.store.activity()

        delivered = self.evaluator.scan_once()
        self.assertEqual(delivered.outcome, "delivered")
        self.assertEqual(self.store.activity(), before_activity)
        self.assertEqual(self.application._active_chat_revision, initial_revision)

        attention = self.application.attention_state()
        self.assertGreater(attention["transcript_revision"], initial_revision)
        first_tab = self.application.session_state()
        second_tab = self.application.session_state()
        for session in (first_tab, second_tab):
            self.assertEqual(len(session["transcript"]), 3)
            self.assertEqual(
                session["transcript"][-1]["application_event"]["type"],
                "companion_initiative",
            )
        self.assertEqual(len(self.initiative_events()), 1)
        self.assertEqual(self.evaluator.scan_once().reasons, ("unresolved_initiative",))
        self.assertEqual(len(self.initiative_events()), 1)

    def test_client_open_reconciles_event_archived_without_connected_browser(self) -> None:
        self.enable_morning()
        delivered = self.evaluator.scan_once()
        self.assertEqual(delivered.outcome, "delivered")
        self.assertEqual(len(self.initiative_events()), 1)

        later_client = self.application.session_state()
        self.assertEqual(later_client["active_chat_id"], CHAT_ID)
        self.assertEqual(
            later_client["transcript"][-1]["application_event"]["id"],
            delivered.candidate.application_event_id,  # type: ignore[union-attr]
        )

    def test_no_chat_busy_and_uncertain_readiness_suppress(self) -> None:
        self.enable_morning()
        self.chats.new_session()
        self.assertIn("no_active_chat", self.evaluator.scan_once().reasons)
        self.assertEqual(self.initiative_events(), ())

        self.chats.open_chat(CHAT_ID, expected_revision=self.chat.metadata.revision)
        self.application._active_chat_id = CHAT_ID
        self.application._active_chat_revision = self.chat.metadata.revision
        self.coordinator.acquire_foreground()
        try:
            self.assertEqual(self.evaluator.scan_once().reasons, ("busy",))
        finally:
            self.coordinator.release_foreground()
        self.assertEqual(self.initiative_events(), ())

        self.application._pending_project_intent = object()  # type: ignore[assignment]
        self.assertFalse(self.application.companion_initiative_ready())
        self.assertIn("busy", self.evaluator.scan_once().reasons)
        self.assertEqual(self.initiative_events(), ())

    def test_dismiss_is_exact_idempotent_and_preserves_archive(self) -> None:
        self.enable_morning()
        self.evaluator.scan_once()
        self.application.attention_state()
        event = self.initiative_events()[0]
        speech = Mock()
        self.application._speech = speech
        first = self.application.dismiss_companion_initiative(event.application_event_id)
        second = self.application.dismiss_companion_initiative(event.application_event_id)
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "dismissed")  # type: ignore[union-attr]
        self.assertEqual(len(self.initiative_events()), 1)
        self.assertIsNone(
            self.application.session_state()["companion_initiative"]["current_event_id"]
        )
        speech.start_completed.assert_not_called()

    def test_manual_speak_is_presentation_only_and_controls_survive_polling(self) -> None:
        self.enable_morning()
        delivered = self.evaluator.scan_once()
        self.assertEqual(delivered.outcome, "delivered")
        self.application.attention_state()
        event = self.initiative_events()[0]
        before_candidate = self.store.candidate_for_event(event.application_event_id)
        before_activity = self.store.activity()
        speech = Mock()
        speech.configured.return_value = True
        speech.start_completed.return_value = "speech-session"
        self.application._speech = speech
        self.application._capability_settings = CapabilitySettingsController(
            administrator_web_search=False,
            administrator_speech_output=True,
            store=None,
        )

        status, response = self.application.prepare_speech(2)
        self.assertEqual(status, 200)
        self.assertEqual(response["speech_session"], "speech-session")
        self.application.record_explicit_user_control("/api/speech/replay")

        self.assertEqual(
            self.store.candidate_for_event(event.application_event_id),
            before_candidate,
        )
        self.assertEqual(self.store.activity(), before_activity)
        for document in (
            self.application.attention_state(),
            self.application.session_state(),
        ):
            self.assertEqual(
                document["companion_initiative"]["current_event_id"],
                event.application_event_id,
            )
        speech.start_completed.assert_called_once_with(event.text)

    def test_chat_navigation_is_meaningful_but_does_not_acknowledge_target(self) -> None:
        other = self.create_other_chat()
        target = self.chats.get_chat(CHAT_ID)
        self.application.open_chat(CHAT_ID, target.metadata.revision)
        self.enable_morning()
        delivered = self.evaluator.scan_once()
        self.assertEqual(delivered.outcome, "delivered")
        self.application.attention_state()
        event = self.initiative_events()[0]
        before_activity = self.store.activity()

        self.application.open_chat(OTHER_CHAT_ID, other.metadata.revision)
        self.application.record_explicit_user_control("/api/chats/open")

        activity = self.store.activity()
        self.assertEqual(activity.revision, before_activity.revision + 1)
        self.assertEqual(activity.kind, "mutation")
        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "delivered")  # type: ignore[union-attr]
        self.assertIsNone(
            self.application.session_state()["companion_initiative"]["current_event_id"]
        )
        self.assertTrue(all(
            item.application_event_type != "companion_initiative"
            for item in self.chats.get_chat(OTHER_CHAT_ID).entries
        ))

        target = self.chats.get_chat(CHAT_ID)
        self.application.open_chat(CHAT_ID, target.metadata.revision)
        self.application.record_explicit_user_control("/api/chats/open")
        self.assertEqual(
            self.application.session_state()["companion_initiative"]["current_event_id"],
            event.application_event_id,
        )
        self.assertEqual(
            self.store.candidate_for_event(event.application_event_id).state,  # type: ignore[union-attr]
            "delivered",
        )
        self.assertEqual(len(self.initiative_events()), 1)

        self.application.new_session(True)
        self.application.record_explicit_user_control("/api/new-session")
        self.assertEqual(
            self.store.candidate_for_event(event.application_event_id).state,  # type: ignore[union-attr]
            "delivered",
        )
        target = self.chats.get_chat(CHAT_ID)
        self.application.open_chat(CHAT_ID, target.metadata.revision)
        self.assertEqual(
            self.application.session_state()["companion_initiative"]["current_event_id"],
            event.application_event_id,
        )

    def test_other_chat_turn_does_not_consume_target_reply_context(self) -> None:
        other = self.create_other_chat()
        target = self.chats.get_chat(CHAT_ID)
        self.application.open_chat(CHAT_ID, target.metadata.revision)
        self.enable_morning()
        self.evaluator.scan_once()
        self.application.attention_state()
        event = self.initiative_events()[0]

        self.application.open_chat(OTHER_CHAT_ID, other.metadata.revision)
        self.application._timezone_name = "America/Chicago"
        self.application.submit("An unrelated turn in another conversation.")
        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "delivered")  # type: ignore[union-attr]

        target = self.chats.get_chat(CHAT_ID)
        self.application.open_chat(CHAT_ID, target.metadata.revision)
        self.application.submit("Yes, about that check-in.")
        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "acknowledged")  # type: ignore[union-attr]

    def test_pause_resolves_current_initiative_without_removing_archive(self) -> None:
        self.enable_morning()
        delivered = self.evaluator.scan_once()
        self.assertEqual(delivered.outcome, "delivered")
        event = self.initiative_events()[0]
        revision = self.store.settings().revision

        self.application.set_companion_initiative_pause(
            "one_day", revision, event.application_event_id
        )

        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "acknowledged")  # type: ignore[union-attr]
        self.assertEqual(len(self.initiative_events()), 1)
        self.assertIsNone(
            self.application.session_state()["companion_initiative"]["current_event_id"]
        )

    def test_settings_pause_is_meaningful_without_acknowledging_a_check_in(self) -> None:
        self.enable_morning()
        self.evaluator.scan_once()
        event = self.initiative_events()[0]
        revision = self.store.settings().revision

        self.application.set_companion_initiative_pause("one_day", revision)

        candidate = self.store.candidate_for_event(event.application_event_id)
        self.assertEqual(candidate.state, "delivered")  # type: ignore[union-attr]
        self.assertEqual(self.store.activity().kind, "snooze")
        self.assertEqual(
            self.application.session_state()["companion_initiative"]["current_event_id"],
            event.application_event_id,
        )

    def test_one_day_and_week_pause_persist_and_expiry_has_no_catchup_spam(self) -> None:
        self.enable_morning()
        revision = self.store.settings().revision
        self.application.set_companion_initiative_pause("one_day", revision)
        reopened = SQLiteCompanionInitiativeStore(self.store.path, clock=lambda: self.now)
        self.assertEqual(
            reopened.settings().snoozed_until_utc, self.now + timedelta(days=1)
        )
        self.assertIn("snoozed", self.evaluator.scan_once().reasons)
        self.assertEqual(self.initiative_events(), ())

        self.application.set_companion_initiative_pause(
            "one_week", self.store.settings().revision
        )
        self.assertEqual(
            reopened.settings().snoozed_until_utc, self.now + timedelta(days=7)
        )
        self.now += timedelta(days=7, minutes=1)
        self.assertEqual(self.evaluator.scan_once().outcome, "delivered")
        self.assertEqual(len(self.initiative_events()), 1)

    def test_disabling_master_prevents_process_evaluation_delivery(self) -> None:
        self.enable_morning()
        settings = self.store.settings()
        self.application.set_companion_initiative_settings(self.settings_document(
            expected_revision=settings.revision,
            master_enabled=False,
            morning_enabled=True,
        ))
        self.now += timedelta(minutes=20)
        self.assertIn("master_off", self.evaluator.scan_once().reasons)
        self.assertEqual(self.initiative_events(), ())

    def test_packaged_web_controls_have_no_presence_eligibility_endpoint(self) -> None:
        assets = Path(__file__).resolve().parents[1] / "src" / "tori" / "web_assets"
        application_script = (assets / "app.js").read_text(encoding="utf-8")
        settings_script = (assets / "settings.js").read_text(encoding="utf-8")
        styles = (assets / "styles.css").read_text(encoding="utf-8")

        self.assertNotIn("/api/companion-initiative/presence", application_script)
        self.assertNotIn("companionPageInstanceId", application_script)
        self.assertNotIn("document.hasFocus()", application_script)
        self.assertIn('"/api/companion-initiative/dismiss"', application_script)
        self.assertIn('"/api/companion-initiative/pause"', application_script)
        self.assertIn('textContent = "Dismiss"', application_script)
        self.assertNotIn("/api/settings", application_script)
        self.assertIn('"/api/settings/companion-initiative"', settings_script)
        self.assertIn("toggle-companion-master", settings_script)
        self.assertIn("companion-morning-start", settings_script)
        self.assertIn("pause-companion-week", settings_script)
        self.assertIn(".companion-check-in", styles)


if __name__ == "__main__":
    unittest.main()
