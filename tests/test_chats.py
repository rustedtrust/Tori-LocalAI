from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.chats import (
    ChatDetail,
    ChatItem,
    ChatService,
    ChatServiceError,
    completed_model_history,
)
from tori.conversation_archive import (
    ArchiveEntry,
    ArchiveSource,
    ArchiveUnavailableError,
    ConversationArchiveStore,
)
from tori.context import ContextPolicy
from tori.providers import ChatMessage
from tori.response_normalization import EXTERNAL_KNOWLEDGE_ADVISORY
from tori.user_settings import SEARCH_DISABLED_MESSAGE


CHAT_ID = "chat-" + "a" * 32
TEST_TIME = datetime(2026, 8, 2, 15, 0, 0, tzinfo=timezone.utc)


class ChatServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = ConversationArchiveStore(
            Path(self.temporary.name) / "chats.db",
            clock=lambda: TEST_TIME,
            identifier_factory=lambda: CHAT_ID,
        )
        self.service = ChatService(self.store)
        self.entries = (
            ArchiveEntry("user", "Question"),
            ArchiveEntry(
                "assistant", "Answer",
                provider="configured-provider", model="configured-model",
            ),
        )

    def create(self, entries=None):  # type: ignore[no-untyped-def]
        selected = tuple(
            replace(
                item,
                provider="configured-provider",
                model="configured-model",
            )
            if (
                item.role == "assistant"
                and item.provider is None
                and item.application_event_id is None
            )
            else item
            for item in (entries or self.entries)
        )
        return self.service.create_chat(
            selected,
            provider="configured-provider",
            model="configured-model",
        )

    @staticmethod
    def scheduled_origin_entries() -> tuple[ArchiveEntry, ...]:
        return (
            ArchiveEntry("user", "Schedule a Tori backup tomorrow at 11 PM."),
            ArchiveEntry(
                "assistant",
                "Scheduled Work proposal: Back up Tori at the approved time.",
                application_event_id="event-" + "b" * 32,
                application_event_type="scheduled_work_proposal",
            ),
        )

    def test_provider_free_scheduled_origin_requires_dedicated_path(self) -> None:
        entries = self.scheduled_origin_entries()
        with self.assertRaises(ChatServiceError):
            self.service.create_chat(
                entries,
                provider="configured-provider",
                model="configured-model",
            )
        self.assertFalse(self.store.path.exists())

        created = self.service.establish_scheduled_work_origin(
            entries,
            selected_provider="configured-provider",
            selected_model="configured-model",
        )
        self.assertEqual(created.metadata.completed_turn_count, 0)
        self.assertIsNone(created.metadata.first_provider)
        self.assertIsNone(created.metadata.first_model)
        self.assertIsNone(created.metadata.latest_provider)
        self.assertIsNone(created.metadata.latest_model)
        self.assertEqual(created.metadata.selected_model.model, "configured-model")
        self.assertEqual(completed_model_history(created.entries), ())
        self.assertEqual(self.service.active_chat_id(), CHAT_ID)
        with self.assertRaises(ChatServiceError):
            self.service.reconcile_chat(
                CHAT_ID,
                created.entries,
                expected_revision=created.metadata.revision,
            )

    def test_zero_turn_origin_transitions_from_actual_model_execution(self) -> None:
        origin = self.service.establish_scheduled_work_origin(
            self.scheduled_origin_entries(),
            selected_provider="configured-provider",
            selected_model="configured-model",
        )
        complete = (
            *origin.entries,
            ArchiveEntry("user", "What should I do next?"),
            ArchiveEntry(
                "assistant",
                "Review the result after it runs.",
                provider="actual-provider",
                model="actual-model",
            ),
        )
        transitioned = self.service.reconcile_chat(
            CHAT_ID,
            complete,
            expected_revision=origin.metadata.revision,
            provider="actual-provider",
            model="actual-model",
        )
        self.assertEqual(transitioned.metadata.completed_turn_count, 1)
        self.assertEqual(transitioned.metadata.first_provider, "actual-provider")
        self.assertEqual(transitioned.metadata.first_model, "actual-model")
        self.assertEqual(transitioned.metadata.latest_provider, "actual-provider")
        self.assertEqual(transitioned.metadata.latest_model, "actual-model")
        self.assertEqual(
            completed_model_history(transitioned.entries),
            (
                ChatMessage("user", "What should I do next?"),
                ChatMessage("assistant", "Review the result after it runs."),
            ),
        )

    def test_scheduled_origin_allowlist_and_application_events_remain_zero_turn(self) -> None:
        invalid = (
            ArchiveEntry("user", "request"),
            ArchiveEntry(
                "assistant",
                "not a scheduled proposal",
                application_event_id="event-" + "c" * 32,
                application_event_type="operational_result",
            ),
        )
        with self.assertRaises(ChatServiceError):
            self.service.establish_scheduled_work_origin(
                invalid,
                selected_provider="configured-provider",
                selected_model="configured-model",
            )
        origin = self.service.establish_scheduled_work_origin(
            self.scheduled_origin_entries(),
            selected_provider="configured-provider",
            selected_model="configured-model",
        )
        appended = self.service.append_application_event(
            CHAT_ID,
            expected_revision=origin.metadata.revision,
            event_id="event-" + "d" * 32,
            event_type="scheduled_work_created",
            text="Scheduled work created and verified.",
        )
        self.assertEqual(appended.metadata.completed_turn_count, 0)
        self.assertEqual(completed_model_history(appended.entries), ())
        self.assertEqual(self.service.active_chat_id(), CHAT_ID)

    def test_immutable_safe_listing_has_no_transcript_preview(self) -> None:
        created = self.create()
        listed = self.service.list_chats()
        self.assertEqual(listed, (created.metadata,))
        self.assertIsInstance(listed[0], ChatItem)
        self.assertFalse(hasattr(listed[0], "entries"))
        self.assertNotIn("Answer", repr(listed))
        with self.assertRaises(FrozenInstanceError):
            listed[0].label = "changed"  # type: ignore[misc]

    def test_provisional_title_refines_once_and_manual_rename_remains_owned(self) -> None:
        created = self.create((
            ArchiveEntry("user", "Good evening again, Tori!"),
            ArchiveEntry("assistant", "Good evening.", provider="configured-provider", model="configured-model"),
        ))
        self.assertEqual(created.metadata.label, "Just checking in")
        refined_entries = (*created.entries,
            ArchiveEntry("user", "Let's work on the web UI redesign today."),
            ArchiveEntry("assistant", "Let's do it.", provider="configured-provider", model="configured-model"),
        )
        refined = self.service.reconcile_chat(
            CHAT_ID, refined_entries, expected_revision=created.metadata.revision,
            provider="configured-provider", model="configured-model",
        )
        self.assertEqual(refined.metadata.label, "Tori UI redesign")

        renamed = self.service.rename_chat(
            CHAT_ID, expected_revision=refined.metadata.revision,
            label="My frontend notes",
        )
        later = self.service.reconcile_chat(
            CHAT_ID,
            (*renamed.entries,
             ArchiveEntry("user", "Now compare TTS engines."),
             ArchiveEntry("assistant", "Okay.", provider="configured-provider", model="configured-model")),
            expected_revision=renamed.metadata.revision,
            provider="configured-provider", model="configured-model",
        )
        self.assertEqual(later.metadata.label, "My frontend notes")
        with self.assertRaisesRegex(ChatServiceError, "more specific"):
            self.service.rename_chat(
                CHAT_ID, expected_revision=later.metadata.revision,
                label="Just checking in",
            )

    def test_complete_chat_retrieval_keeps_full_visible_transcript(self) -> None:
        entries = tuple(
            entry
            for index in range(12)
            for entry in (
                ArchiveEntry("user", f"Question {index}"),
                ArchiveEntry("assistant", f"Answer {index}"),
            )
        )
        self.create(entries)
        loaded = self.service.get_chat(CHAT_ID)
        self.assertIsInstance(loaded, ChatDetail)
        self.assertEqual(loaded.entries, self.store.get_chat(CHAT_ID).entries)
        self.assertEqual(len(loaded.entries), 24)
        self.assertEqual(len(self.service.model_history(CHAT_ID)), 24)

    def test_model_history_retains_all_complete_exchanges(self) -> None:
        entries = tuple(
            entry
            for index in range(12)
            for entry in (
                ArchiveEntry("user", f"Q{index}"),
                ArchiveEntry("assistant", f"A{index}"),
            )
        )
        history = completed_model_history(entries)
        self.assertEqual(len(history), 24)
        self.assertEqual(history[0], ChatMessage(role="user", content="Q0"))
        self.assertEqual(history[-1], ChatMessage(role="assistant", content="A11"))

    def test_nonordinary_visible_records_never_enter_provider_history(self) -> None:
        entries = (
            ArchiveEntry("system", "visible system"),
            ArchiveEntry("user", "question"),
            ArchiveEntry("warning", "visible warning"),
            ArchiveEntry("assistant", "answer"),
            ArchiveEntry("user", "failed"),
            ArchiveEntry("error", "visible error"),
        )
        self.create(entries)
        detail = self.service.get_chat(CHAT_ID)
        self.assertEqual([entry.role for entry in detail.entries], ["system", "user", "warning", "assistant", "user", "error"])
        self.assertEqual(
            self.service.model_history(CHAT_ID),
            (ChatMessage("user", "question"), ChatMessage("assistant", "answer")),
        )

    def test_archived_internal_control_data_never_reenters_model_history(self) -> None:
        entries = (
            ArchiveEntry("user", "unsafe exchange"),
            ArchiveEntry(
                "assistant",
                EXTERNAL_KNOWLEDGE_ADVISORY.replace(":", "_", 1),
                provider="fake",
                model="fake-model",
            ),
            ArchiveEntry("user", "safe exchange"),
            ArchiveEntry("assistant", "safe answer"),
        )

        self.assertEqual(
            completed_model_history(entries),
            (
                ChatMessage("user", "safe exchange"),
                ChatMessage("assistant", "safe answer"),
            ),
        )

    def test_archived_transient_capability_notice_is_not_model_history(self) -> None:
        entries = (
            ArchiveEntry("user", "explicit search"),
            ArchiveEntry("assistant", SEARCH_DISABLED_MESSAGE),
            ArchiveEntry("user", "ordinary question"),
            ArchiveEntry(
                "assistant", "ordinary answer", provider="fake", model="fake-model"
            ),
        )

        self.assertEqual(
            completed_model_history(entries),
            (
                ChatMessage("user", "ordinary question"),
                ChatMessage("assistant", "ordinary answer"),
            ),
        )
        self.assertEqual(entries[1].text, SEARCH_DISABLED_MESSAGE)

    def test_incomplete_and_invalid_ordering_does_not_make_invalid_history(self) -> None:
        entries = (
            ArchiveEntry("assistant", "orphan"),
            ArchiveEntry("user", "abandoned first"),
            ArchiveEntry("user", "current user"),
            ArchiveEntry("assistant", "current answer"),
            ArchiveEntry("assistant", "second orphan"),
            ArchiveEntry("user", "failed user"),
            ArchiveEntry("error", "failed"),
            ArchiveEntry("assistant", "after error orphan"),
        )
        self.assertEqual(
            completed_model_history(entries),
            (ChatMessage("user", "current user"), ChatMessage("assistant", "current answer")),
        )

    def test_sources_and_informational_metadata_do_not_change_messages_or_route(self) -> None:
        entries = (
            ArchiveEntry("user", "source question"),
            ArchiveEntry(
                "assistant",
                "source answer",
                (ArchiveSource("safe.md", 3, 4),),
                provider="entry-provider",
                model="entry-model",
            ),
        )
        detail = self.create(entries)
        self.assertEqual(detail.metadata.first_provider, "entry-provider")
        self.assertEqual(detail.entries[1].provider, "entry-provider")
        self.assertEqual(
            self.service.model_history(CHAT_ID)[1].content,
            "source answer",
        )
        self.assertNotIn("safe.md", self.service.model_history(CHAT_ID)[1].content)
        self.assertFalse(hasattr(self.service, "provider"))

    def test_create_and_reconcile_map_complete_results(self) -> None:
        created = self.create()
        self.assertEqual(created.metadata.revision, 1)
        complete = (
            *self.entries,
            ArchiveEntry("user", "Q2"),
            ArchiveEntry(
                "assistant", "A2",
                provider="configured-provider-2", model="configured-model-2",
            ),
        )
        reconciled = self.service.reconcile_chat(
            CHAT_ID,
            complete,
            expected_revision=1,
            provider="configured-provider-2",
            model="configured-model-2",
        )
        self.assertEqual(reconciled.metadata.revision, 2)
        self.assertEqual(reconciled.metadata.latest_model, "configured-model-2")
        self.assertEqual(len(reconciled.entries), 4)

    def test_explicit_open_updates_selection_and_last_opened(self) -> None:
        created = self.create()
        self.service.new_session()
        self.assertIsNone(self.service.active_chat_id())
        opened = self.service.open_chat(
            CHAT_ID, expected_revision=created.metadata.revision
        )
        self.assertEqual(self.service.active_chat_id(), CHAT_ID)
        self.assertIsNotNone(opened.metadata.last_opened_at)
        self.assertEqual(opened.metadata.updated_at, opened.metadata.last_opened_at)

    def test_new_session_clears_selection_and_preserves_chat(self) -> None:
        created = self.create()
        self.assertEqual(self.service.active_chat_id(), CHAT_ID)
        self.service.clear_active_chat()
        self.assertIsNone(self.service.active_chat_id())
        self.assertEqual(self.service.get_chat(CHAT_ID), created)

    def test_model_selection_is_immediate_durable_and_transcript_preserving(self) -> None:
        created = self.create()
        selected = self.service.select_model(
            CHAT_ID,
            expected_revision=created.metadata.revision,
            provider="ollama",
            model="new/model:Q4",
        )
        self.assertEqual(selected.metadata.selected_model.provider, "ollama")
        self.assertEqual(selected.metadata.selected_model.model, "new/model:Q4")
        self.assertEqual(selected.entries, created.entries)
        reopened = ChatService(ConversationArchiveStore(self.store.path)).get_chat(CHAT_ID)
        self.assertEqual(reopened.metadata.selected_model.model, "new/model:Q4")
        self.assertEqual(reopened.entries, created.entries)

    def test_model_selection_failure_is_atomic_and_validated(self) -> None:
        created = self.create()
        selected = self.service.select_model(
            CHAT_ID,
            expected_revision=created.metadata.revision,
            provider="ollama",
            model="model-b",
        )
        with self.assertRaisesRegex(ChatServiceError, "changed"):
            self.service.select_model(
                CHAT_ID,
                expected_revision=created.metadata.revision,
                provider="ollama",
                model="model-c",
            )
        with self.assertRaisesRegex(ChatServiceError, "invalid"):
            self.service.select_model(
                CHAT_ID,
                expected_revision=selected.metadata.revision,
                provider="ollama",
                model="bad\nmodel",
            )
        final = self.service.get_chat(CHAT_ID)
        self.assertEqual(final.metadata.selected_model.model, "model-b")
        self.assertEqual(final.entries, selected.entries)

    def test_context_selection_is_durable_and_transcript_preserving(self) -> None:
        created = self.create()
        selected = self.service.select_context(
            CHAT_ID,
            expected_revision=created.metadata.revision,
            policy=ContextPolicy.fixed(32768),
        )
        self.assertEqual(selected.metadata.context_policy.canonical, "fixed:32768")
        self.assertEqual(selected.entries, created.entries)
        reopened = ChatService(ConversationArchiveStore(self.store.path)).get_chat(CHAT_ID)
        self.assertEqual(reopened.metadata.context_policy.canonical, "fixed:32768")
        self.assertEqual(reopened.entries, created.entries)

    def test_new_session_on_absent_archive_is_filesystem_neutral(self) -> None:
        absent = Path(self.temporary.name) / "absent" / "chats.db"
        ChatService(ConversationArchiveStore(absent)).new_session()
        self.assertFalse(absent.exists())
        self.assertFalse(absent.parent.exists())

    def test_delete_maps_safe_metadata_and_verified_absence(self) -> None:
        created = self.create()
        removed = self.service.delete_chat(
            CHAT_ID, expected_revision=created.metadata.revision
        )
        self.assertEqual(removed, created.metadata)
        self.assertEqual(self.service.list_chats(), ())
        self.assertIsNone(self.service.active_chat_id())

    def test_errors_are_stable_and_do_not_expose_sql_paths_or_transcript(self) -> None:
        secret = "private transcript marker /private/archive/path sqlite malformed"
        with patch.object(
            self.store,
            "list_chats",
            side_effect=ArchiveUnavailableError(secret),
        ):
            with self.assertRaises(ChatServiceError) as caught:
                self.service.list_chats()
        self.assertEqual(caught.exception.code, "store_unavailable")
        rendered = str(caught.exception)
        self.assertNotIn("private transcript marker", rendered)
        self.assertNotIn("/private/archive/path", rendered)
        self.assertNotIn("sqlite", rendered.lower())

    def test_checkpoint_memory_and_knowledge_are_not_dependencies(self) -> None:
        import tori.chats as chats_module

        names = set(chats_module.__dict__)
        self.assertNotIn("CheckpointStore", names)
        self.assertNotIn("SQLiteMemoryStore", names)
        self.assertNotIn("KnowledgeRegistry", names)
        self.create()
        self.assertEqual(len(self.service.model_history(CHAT_ID)), 2)

    def test_application_event_does_not_consume_pending_user_history(self) -> None:
        entries = (
            ArchiveEntry("user", "ordinary question"),
            ArchiveEntry(
                "assistant",
                "Reminder: unrelated attention",
                application_event_id="event-" + "b" * 32,
                application_event_type="reminder_due",
            ),
            ArchiveEntry("assistant", "ordinary answer", provider="fake", model="model"),
        )
        self.assertEqual(
            completed_model_history(entries),
            (
                ChatMessage("user", "ordinary question"),
                ChatMessage("assistant", "ordinary answer"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
