from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tori.chats import ChatService, completed_model_history
from tori.chats import ChatServiceError
from tori.coding_work_application import CodingWorkApplicationService
from tori.companion_initiative import (
    AttentionSignal,
    InitiativeSettings,
    ResumeAnchor,
    SQLiteCompanionInitiativeStore,
)
from tori.companion_initiative_service import (
    APPLICATION_EVENT_TYPE,
    CompanionInitiativeService,
    LONG_SILENCE_WORDING,
    MORNING_WORDING,
)
from tori.conversation import ConversationSession
from tori.conversation_application import ConversationTurnRequest, ConversationTurnService
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.operation_coordinator import OperationCoordinator
from tori.planning_application import PlanningService
from tori.project_application import ProjectApplicationService
from tori.providers import ChatResponse, ModelProvider
from tori.remote_chat_transport import FakeRemoteChannel
from tori.request_origin import RequestOrigin
from tori.search import SearXNGSearch
from tori.task_reminder_application import TaskReminderApplicationService
from tori.tts import SpeechCoordinator


UTC = timezone.utc
CHAT_ID = "chat-" + "1" * 32


class RecordingProvider(ModelProvider):
    def __init__(self, *, fail: bool = False) -> None:
        self.requests = []
        self.fail = fail

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return ChatResponse("A normal response.", "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        if self.fail:
            raise RuntimeError("provider unavailable")
        yield "A normal response."


class AnchorSource:
    def __init__(self) -> None:
        self.anchor: ResumeAnchor | None = None
        self.calls = 0
        self.drop_on_call: int | None = None

    def current(self, settings, activity, *, at):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.drop_on_call is not None and self.calls >= self.drop_on_call:
            return None
        if not settings.master_enabled or not settings.resume_enabled:
            return None
        return self.anchor


class AttentionSources:
    def __init__(self, signals=()):
        self.signals = tuple(signals)
        self.calls = 0

    def snapshots(self):
        self.calls += 1
        return (("research", self.signals),)


class CompanionInitiativeDeliveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.now = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
        self.store = SQLiteCompanionInitiativeStore(
            root / "initiative.db", clock=lambda: self.now
        )
        archive = ConversationArchiveStore(
            root / "archive.db",
            clock=lambda: self.now,
            identifier_factory=lambda: CHAT_ID,
        )
        self.chats = ChatService(archive)
        self.chat = self.chats.create_chat(
            (
                ArchiveEntry("user", "Initial user turn."),
                ArchiveEntry(
                    "assistant",
                    "Initial model response.",
                    provider="test",
                    model="test-model",
                ),
            ),
            provider="test",
            model="test-model",
        )
        self.anchors = AnchorSource()
        self.coordinator = OperationCoordinator()

    def configure(self, **values: object) -> InitiativeSettings:
        original_now = self.now
        self.now = self.now - timedelta(days=10)
        settings = InitiativeSettings(master_enabled=True, **values)
        saved = self.store.save_settings(settings, expected_revision=0)
        self.now = original_now
        return saved

    def service(self, **values: object) -> CompanionInitiativeService:
        return CompanionInitiativeService(
            store=self.store,
            chats=self.chats,
            anchors=self.anchors,  # type: ignore[arg-type]
            coordinator=self.coordinator,
            timezone_name=str(values.pop("timezone_name", "UTC")),
            clock=lambda: self.now,
            readiness=values.pop("readiness", lambda: True),  # type: ignore[arg-type]
            owner=str(values.pop("owner", "initiative-test-owner")),
            **values,
        )

    def delivered_event(self):  # type: ignore[no-untyped-def]
        entries = self.chats.get_chat(CHAT_ID).entries
        return [item for item in entries if item.application_event_type == APPLICATION_EVENT_TYPE]

    def record_delivery(self, initiative_type: str, at: datetime, number: int) -> None:
        self.now = at
        candidate = self.store.create_candidate(
            initiative_type=initiative_type,
            dedupe_key=f"history:{initiative_type}:{number}",
            eligible_at=at - timedelta(minutes=1),
            expires_at=None,
            wording="Historical check-in.",
            anchor_kind="coding_work" if initiative_type == "resume" else None,
            anchor_id=f"work-{number}" if initiative_type == "resume" else None,
            anchor_revision=number + 1 if initiative_type == "resume" else None,
        )
        claimed = self.store.claim(
            candidate.identifier,
            expected_revision=candidate.revision,
            owner="history-owner",
            target_chat_id=CHAT_ID,
            target_chat_revision=self.chats.active_chat_metadata().revision,  # type: ignore[union-attr]
            lease_until=at + timedelta(minutes=1),
        )
        delivered = self.store.mark_delivered(
            claimed.identifier,
            expected_revision=claimed.revision,
            owner="history-owner",
            delivered_at=at,
        )
        self.store.transition_candidate(
            delivered.identifier,
            "acknowledged",
            expected_revision=delivered.revision,
            at=at,
        )

    def test_master_and_individual_type_off_create_nothing(self) -> None:
        absent = self.service().evaluate()
        self.assertEqual(absent.reasons, ("master_off",))
        self.configure()
        disabled = self.service().evaluate()
        self.assertIn("type_off", disabled.reasons)
        self.assertEqual(self.store.list_candidates(), ())
        self.assertEqual(self.delivered_event(), [])

    def attention_signal(self, *, level="conversational", revision=1, material="m1"):
        return AttentionSignal(
            "research", "research-" + "a" * 32, "research_failed",
            "Voice research", "Requested research failed and needs a decision.",
            "needs_attention", level, revision, material, self.now, None,
        )

    def test_attention_is_the_reason_for_conversation_and_unchanged_item_does_not_repeat(self) -> None:
        self.configure(resume_enabled=True)
        sources = AttentionSources((self.attention_signal(),))
        first = self.service(attention_sources=sources).evaluate()
        self.assertEqual(first.outcome, "delivered")
        self.assertIn("Voice research", self.delivered_event()[0].text)
        self.assertEqual(self.store.eligible_attention(at=self.now), ())
        second = self.service(attention_sources=sources).evaluate()
        self.assertEqual(second.outcome, "suppressed")
        self.assertEqual(len(self.delivered_event()), 1)

    def test_silent_attention_stays_in_workspace_and_quiet_hours_preserve_conversational_item(self) -> None:
        self.configure(resume_enabled=True)
        silent = AttentionSources((self.attention_signal(level="silent"),))
        result = self.service(attention_sources=silent).evaluate()
        self.assertEqual(result.outcome, "suppressed")
        self.assertEqual(len(self.store.list_attention(include_resolved=False)), 1)
        self.assertEqual(self.delivered_event(), [])

        self.now = self.now.replace(hour=23)
        loud = AttentionSources((self.attention_signal(level="conversational"),))
        quiet = self.service(attention_sources=loud).evaluate()
        self.assertIn("quiet_hours", quiet.reasons)
        self.assertEqual(len(self.store.eligible_attention(at=self.now)), 1)

    def test_morning_brief_is_bounded_and_empty_brief_is_suppressed(self) -> None:
        self.configure(morning_enabled=True)
        empty = self.service(attention_sources=AttentionSources()).evaluate()
        self.assertEqual(empty.outcome, "suppressed")
        self.assertEqual(self.delivered_event(), [])

        signals = tuple(
            replace(
                self.attention_signal(level="silent", revision=index),
                source_object_id=f"research-{index:032x}",
                title=f"Finding {index}", material_key=f"material-{index}",
            )
            for index in range(1, 5)
        )
        result = self.service(attention_sources=AttentionSources(signals)).evaluate()
        self.assertEqual(result.outcome, "delivered")
        wording = self.delivered_event()[0].text
        self.assertLessEqual(len(wording), 280)
        self.assertIn("Finding 1", wording)
        self.assertNotIn("Finding 4", wording)

    def test_morning_inside_window_delivers_one_truthful_application_event(self) -> None:
        self.configure(morning_enabled=True)
        result = self.service().evaluate()
        self.assertEqual(result.outcome, "delivered")
        event = self.delivered_event()
        self.assertEqual(len(event), 1)
        self.assertEqual(event[0].role, "assistant")
        self.assertEqual(event[0].text, MORNING_WORDING)
        self.assertIsNone(event[0].provider)
        self.assertIsNone(event[0].model)
        self.assertIsNotNone(event[0].application_event_id)
        self.assertRegex(event[0].application_event_id, r"^event-[0-9a-f]{32}$")
        self.assertEqual([item.role for item in self.chats.get_chat(CHAT_ID).entries], ["user", "assistant", "assistant"])

    def test_morning_outside_window_or_recent_activity_does_not_catch_up(self) -> None:
        self.configure(morning_enabled=True)
        self.now = self.now.replace(hour=11)
        missed = self.service().evaluate()
        self.assertIn("outside_morning_window", missed.reasons)
        self.assertEqual(self.store.list_candidates(), ())
        self.now = self.now.replace(hour=9)
        self.store.record_meaningful_interaction("local_turn", occurred_at=self.now - timedelta(minutes=5))
        recent = self.service().evaluate()
        self.assertIn("recent_activity", recent.reasons)
        self.assertEqual(self.delivered_event(), [])

    def test_quiet_snooze_and_busy_suppress_without_browser_dependency(self) -> None:
        settings = self.configure(morning_enabled=True)
        self.now = self.now.replace(hour=23)
        self.assertIn("quiet_hours", self.service().evaluate().reasons)
        self.now = self.now.replace(hour=9)
        self.store.snooze(self.now + timedelta(days=1), expected_revision=settings.revision)
        self.assertIn("snoozed", self.service().evaluate().reasons)
        self.coordinator.acquire_foreground()
        try:
            self.assertEqual(self.service().evaluate().reasons, ("busy",))
        finally:
            self.coordinator.release_foreground()
        self.assertEqual(self.delivered_event(), [])

    def test_resume_uses_current_anchor_and_stale_anchor_is_superseded(self) -> None:
        self.configure(resume_enabled=True)
        self.anchors.anchor = ResumeAnchor(
            "coding_work", "work-1", 4, "Go Fast!",
            self.now - timedelta(hours=5), CHAT_ID, None,
        )
        delivered = self.service().evaluate()
        self.assertEqual(delivered.outcome, "delivered")
        self.assertIn("Go Fast!", self.delivered_event()[0].text)

        # A source that changes after claim is terminalized without an append.
        other_root = Path(self.temporary.name) / "stale"
        store = SQLiteCompanionInitiativeStore(other_root / "initiative.db", clock=lambda: self.now)
        prior = self.now
        self.now -= timedelta(days=10)
        store.save_settings(InitiativeSettings(master_enabled=True, resume_enabled=True), expected_revision=0)
        self.now = prior
        anchors = AnchorSource()
        anchors.anchor = ResumeAnchor(
            "coding_work", "work-stale", 2, None,
            self.now - timedelta(hours=5), CHAT_ID, None,
        )
        anchors.drop_on_call = 3
        service = CompanionInitiativeService(
            store=store, chats=self.chats, anchors=anchors,  # type: ignore[arg-type]
            coordinator=OperationCoordinator(), timezone_name="UTC",
            clock=lambda: self.now, owner="stale-owner",
        )
        result = service.evaluate()
        self.assertEqual(result.outcome, "suppressed")
        self.assertEqual(result.candidate.state, "superseded")  # type: ignore[union-attr]
        self.assertEqual(len(self.delivered_event()), 1)

    def test_expired_resume_and_long_silence_threshold(self) -> None:
        self.configure(resume_enabled=True, long_silence_enabled=True)
        self.anchors.anchor = ResumeAnchor(
            "coding_work", "old-work", 1, None,
            self.now - timedelta(hours=72), CHAT_ID, None,
        )
        # Resume is expired, while the settings interaction is ten days old.
        result = self.service().evaluate()
        self.assertEqual(result.outcome, "delivered")
        self.assertEqual(result.candidate.type, "long_silence")  # type: ignore[union-attr]
        self.assertEqual(self.delivered_event()[0].text, LONG_SILENCE_WORDING)

    def test_long_silence_before_seven_days_is_suppressed(self) -> None:
        self.configure(long_silence_enabled=True)
        self.store.record_meaningful_interaction(
            "local_turn", occurred_at=self.now - timedelta(days=6)
        )
        result = self.service().evaluate()
        self.assertIn("silence_threshold", result.reasons)
        self.assertEqual(self.delivered_event(), [])

    def test_same_silence_episode_and_duplicate_evaluation_never_repeat(self) -> None:
        self.configure(long_silence_enabled=True)
        service = self.service()
        first = service.evaluate()
        second = service.evaluate()
        self.assertEqual(first.outcome, "delivered")
        self.assertEqual(second.reasons, ("unresolved_initiative",))
        self.assertEqual(len(self.delivered_event()), 1)

        context = self.store.claim_reply_context(CHAT_ID, at=self.now)
        self.assertIsNotNone(context)
        again = service.evaluate()
        self.assertIn("global_cooldown", again.reasons)
        self.assertEqual(len(self.store.list_candidates()), 1)
        self.assertEqual(len(self.delivered_event()), 1)

    def test_global_cooldown_and_rolling_caps_suppress(self) -> None:
        self.configure(morning_enabled=True)
        target = self.now
        self.record_delivery("morning", target - timedelta(hours=1), 1)
        self.now = target
        self.assertIn("global_cooldown", self.service().evaluate().reasons)

        for count, age in enumerate((2, 3), start=2):
            self.record_delivery("morning", target - timedelta(days=age), count)
        self.now = target
        self.assertIn("seven_day_cap", self.service().evaluate().reasons)

        cap_root = Path(self.temporary.name) / "cap30"
        self.store = SQLiteCompanionInitiativeStore(cap_root / "initiative.db", clock=lambda: self.now)
        self.configure(morning_enabled=True)
        target = self.now
        for number in range(8):
            self.record_delivery("morning", target - timedelta(days=8 + number), number)
        self.now = target
        self.assertIn("thirty_day_cap", self.service().evaluate().reasons)

    def test_event_is_idempotent_across_append_finalize_crash_and_restart(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service(owner="first-owner")
        with patch.object(
            self.store, "mark_delivered", side_effect=RuntimeError("crash after append")
        ):
            result = service.evaluate()
        self.assertEqual(result.outcome, "suppressed")
        self.assertEqual(len(self.delivered_event()), 1)
        self.assertEqual(self.store.list_candidates()[0].state, "delivering")

        self.now += timedelta(minutes=6)
        recovered = self.service(owner="restart-owner").recover_startup()
        self.assertEqual(recovered[0].state, "delivered")
        self.assertEqual(len(self.delivered_event()), 1)
        reloaded = self.chats.get_chat(CHAT_ID)
        self.assertEqual(reloaded.entries[-1].application_event_id, recovered[0].application_event_id)

    def test_claim_without_append_recovers_to_pending_then_delivers_once(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service(owner="first-owner")
        settings = self.store.settings()
        local_date = self.now.date()
        candidate = self.store.create_candidate(
            initiative_type="morning",
            dedupe_key=f"morning:UTC:{local_date.isoformat()}",
            eligible_at=self.now.replace(hour=8),
            expires_at=self.now.replace(hour=10),
            wording=MORNING_WORDING,
        )
        claimed = self.store.claim(
            candidate.identifier, expected_revision=candidate.revision,
            owner="abandoned-owner", target_chat_id=CHAT_ID,
            target_chat_revision=self.chat.metadata.revision,
            lease_until=self.now + timedelta(minutes=1),
        )
        self.assertEqual(claimed.state, "delivering")
        self.now += timedelta(minutes=2)
        recovered = service.recover_startup()
        self.assertEqual(recovered[0].state, "pending")
        self.assertEqual(service.evaluate().outcome, "delivered")
        self.assertEqual(len(self.delivered_event()), 1)
        self.assertTrue(settings.master_enabled)

    def test_conflicting_or_uncertain_event_recovery_fails_closed(self) -> None:
        self.configure(morning_enabled=True)
        candidate = self.store.create_candidate(
            initiative_type="morning", dedupe_key="recovery:conflict",
            eligible_at=self.now - timedelta(minutes=1), expires_at=None,
            wording=MORNING_WORDING,
        )
        conflict = self.chats.append_application_event(
            CHAT_ID, expected_revision=self.chat.metadata.revision,
            event_id=candidate.application_event_id,
            event_type=APPLICATION_EVENT_TYPE, text="Different semantics.",
        )
        claimed = self.store.claim(
            candidate.identifier, expected_revision=candidate.revision,
            owner="conflict-owner", target_chat_id=CHAT_ID,
            target_chat_revision=conflict.metadata.revision,
            lease_until=self.now + timedelta(minutes=1),
        )
        self.now += timedelta(minutes=2)
        recovered = self.service().recover_startup()
        self.assertEqual(recovered[0].state, "failed")
        self.assertEqual(recovered[0].terminal_reason, "event_semantics_conflict")

        uncertain = self.store.create_candidate(
            initiative_type="morning", dedupe_key="recovery:uncertain",
            eligible_at=self.now - timedelta(minutes=1), expires_at=None,
            wording=MORNING_WORDING,
        )
        uncertain_claim = self.store.claim(
            uncertain.identifier, expected_revision=uncertain.revision,
            owner="uncertain-owner", target_chat_id=CHAT_ID,
            target_chat_revision=conflict.metadata.revision,
            lease_until=self.now + timedelta(minutes=1),
        )
        self.now += timedelta(minutes=2)
        with patch.object(
            self.chats,
            "get_application_event",
            side_effect=ChatServiceError("Unavailable.", code="store_unavailable"),
        ):
            self.assertEqual(self.service().recover_startup(), ())
        self.assertEqual(
            self.store.get_candidate(uncertain_claim.identifier).state,
            "delivering",
        )

    def test_archive_failure_preserves_fence_and_releases_primary_operation(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service()
        with patch.object(
            self.chats,
            "append_application_event",
            side_effect=ChatServiceError("Unavailable.", code="store_unavailable"),
        ):
            result = service.evaluate()
        self.assertEqual(result.outcome, "suppressed")
        self.assertEqual(self.store.list_candidates()[0].state, "delivering")
        self.assertFalse(self.coordinator.locked())

        provider = RecordingProvider()
        turns = ConversationTurnService(self.coordinator)
        turns.attach_session(
            ConversationSession(provider),
            origin_kind=RequestOrigin.local_web().kind,
            conversation_id=CHAT_ID,
        )
        request = ConversationTurnRequest(
            "Ordinary conversation still works.", RequestOrigin.local_web(),
            CHAT_ID, 1, interaction_id="after-initiative-failure",
        )
        self.assertEqual(turns.complete(request), "A normal response.")

    def test_dst_gap_boundary_advances_to_next_valid_instant(self) -> None:
        self.now = datetime(2027, 3, 14, 8, 15, tzinfo=UTC)
        self.configure(
            morning_enabled=True,
            morning_start=time(2, 0),
            morning_end=time(3, 30),
            quiet_start=time(0, 0),
            quiet_end=time(1, 0),
        )
        result = self.service(timezone_name="America/Chicago").evaluate()
        self.assertEqual(result.outcome, "delivered")
        self.assertEqual(result.candidate.eligible_at_utc, datetime(2027, 3, 14, 8, 0, tzinfo=UTC))  # type: ignore[union-attr]
        self.assertEqual(result.candidate.expires_at_utc, datetime(2027, 3, 14, 8, 30, tzinfo=UTC))  # type: ignore[union-attr]

    def test_application_event_never_enters_model_history_or_memory_evidence(self) -> None:
        self.configure(morning_enabled=True)
        before = completed_model_history(self.chats.get_chat(CHAT_ID).entries)
        provider = RecordingProvider()
        self.assertEqual(self.service().evaluate().outcome, "delivered")
        after = completed_model_history(self.chats.get_chat(CHAT_ID).entries)
        self.assertEqual(after, before)
        self.assertEqual(provider.requests, [])

    def test_delivery_and_yes_reply_never_invoke_forbidden_capabilities(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service()
        forbidden = (
            (SearXNGSearch, "search"),
            (SpeechCoordinator, "start_completed"),
            (FakeRemoteChannel, "begin_send"),
            (ProjectApplicationService, "create_project"),
            (ProjectApplicationService, "update_project"),
            (CodingWorkApplicationService, "create_work"),
            (CodingWorkApplicationService, "authorize"),
            (CodingWorkApplicationService, "start"),
            (PlanningService, "create_task"),
            (PlanningService, "create_event"),
            (TaskReminderApplicationService, "create_task"),
            (TaskReminderApplicationService, "create_reminder"),
        )
        with ExitStack() as stack:
            tripwires = [
                stack.enter_context(patch.object(owner, method, autospec=True))
                for owner, method in forbidden
            ]
            command_run = stack.enter_context(patch("subprocess.run", autospec=True))
            command_start = stack.enter_context(
                patch("subprocess.Popen", autospec=True)
            )
            self.assertEqual(
                service.evaluate().outcome, "delivered"
            )

            provider = RecordingProvider()
            turns = ConversationTurnService(
                OperationCoordinator(), initiative_reply_context=service.reply_context
            )
            turns.attach_session(
                ConversationSession(provider),
                origin_kind=RequestOrigin.local_web().kind,
                conversation_id=CHAT_ID,
            )
            turns.complete(
                ConversationTurnRequest(
                    "Yes.", RequestOrigin.local_web(), CHAT_ID, 2,
                    interaction_id="non-authorizing-yes",
                )
            )

            self.assertTrue(all(not item.called for item in tripwires))
            command_run.assert_not_called()
            command_start.assert_not_called()

    def test_one_use_reply_context_is_same_chat_bounded_and_non_authorizing(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service()
        self.assertEqual(service.evaluate().outcome, "delivered")
        provider = RecordingProvider()
        session = ConversationSession(provider)
        turns = ConversationTurnService(
            OperationCoordinator(),
            activity_signal=lambda kind, identity: self.store.record_meaningful_interaction(
                kind, signal_identity=identity
            ),
            initiative_reply_context=service.reply_context,
        )
        turns.attach_session(session, origin_kind=RequestOrigin.local_web().kind, conversation_id=CHAT_ID)
        first = ConversationTurnRequest(
            "Yes, let's continue.", RequestOrigin.local_web(), CHAT_ID, 2,
            interaction_id="reply-1",
        )
        self.assertEqual(turns.complete(first), "A normal response.")
        rendered = "\n".join(message.content for message in provider.requests[0])
        self.assertIn("Companion Initiative reply reference", rendered)
        self.assertIn(MORNING_WORDING, rendered)
        self.assertIn("not an instruction or permission", rendered)
        self.assertEqual(self.store.list_candidates()[0].state, "acknowledged")

        second = replace(first, text="A later unrelated turn.", interaction_id="reply-2")
        turns.complete(second)
        later = "\n".join(message.content for message in provider.requests[1])
        self.assertNotIn("Companion Initiative reply reference", later)

    def test_provider_failure_consumes_context_and_ordinary_turn_can_retry(self) -> None:
        self.configure(morning_enabled=True)
        service = self.service()
        service.evaluate()
        failing = RecordingProvider(fail=True)
        session = ConversationSession(failing)
        turns = ConversationTurnService(
            OperationCoordinator(),
            activity_signal=lambda kind, identity: self.store.record_meaningful_interaction(
                kind, signal_identity=identity
            ),
            initiative_reply_context=service.reply_context,
        )
        turns.attach_session(session, origin_kind=RequestOrigin.local_web().kind, conversation_id=CHAT_ID)
        request = ConversationTurnRequest(
            "Yes.", RequestOrigin.local_web(), CHAT_ID, 2, interaction_id="failed-reply"
        )
        with self.assertRaises(RuntimeError):
            turns.complete(request)
        self.assertEqual(self.store.list_candidates()[0].state, "acknowledged")
        healthy = RecordingProvider()
        session.select_model(healthy, "test-model")
        turns.complete(replace(request, interaction_id="retry-reply"))
        rendered = "\n".join(message.content for message in healthy.requests[0])
        self.assertNotIn("Companion Initiative reply reference", rendered)

    def test_malformed_context_and_initiative_failure_do_not_break_conversation(self) -> None:
        provider = RecordingProvider()
        session = ConversationSession(provider)
        turns = ConversationTurnService(
            OperationCoordinator(), initiative_reply_context=lambda request: "x" * 2000
        )
        turns.attach_session(session, origin_kind=RequestOrigin.local_web().kind, conversation_id=CHAT_ID)
        request = ConversationTurnRequest(
            "Hello.", RequestOrigin.local_web(), CHAT_ID, 1, interaction_id="ordinary"
        )
        self.assertEqual(turns.complete(request), "A normal response.")
        rendered = "\n".join(message.content for message in provider.requests[0])
        self.assertNotIn("x" * 100, rendered)


if __name__ == "__main__":
    unittest.main()
