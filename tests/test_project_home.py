from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.project_application import (
    PROJECT_STATE_NOT_RECORDED,
    ProjectApplicationService,
)


NOW = datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)


def _ids(prefix: str):  # type: ignore[no-untyped-def]
    return iter(f"{prefix}{index:032x}" for index in range(1, 100))


class ProjectHomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        chats = _ids("chat-")
        projects = _ids("project-")
        decisions = _ids("decision-")
        questions = _ids("question-")
        plans = _ids("plan-item-")
        self.store = ConversationArchiveStore(
            Path(self.temporary.name) / "archive.db",
            clock=lambda: NOW,
            identifier_factory=lambda: next(chats),
            project_identifier_factory=lambda: next(projects),
            project_decision_identifier_factory=lambda: next(decisions),
            project_question_identifier_factory=lambda: next(questions),
            project_plan_identifier_factory=lambda: next(plans),
        )
        self.chats = ChatService(self.store)
        self.projects = ProjectApplicationService(self.chats)
        self.project = self.projects.create_project(
            title="Project Home",
            objective="Show truthful continuity without inference",
        )

    def _chat(self, text: str, *, project_id: str | None = None):  # type: ignore[no-untyped-def]
        return self.chats.create_chat(
            (
                ArchiveEntry("user", text),
                ArchiveEntry(
                    "assistant", f"Answer: {text}", provider="fake", model="model"
                ),
            ),
            provider="fake",
            model="model",
            project_id=project_id,
        )

    def test_empty_home_is_explicit_deterministic_and_read_only(self) -> None:
        before = self.projects.get_project(self.project.identifier)
        home = self.projects.get_project_home(self.project.identifier)

        self.assertEqual(home.project, before)
        self.assertIsNone(home.workspace_state)
        self.assertFalse(home.where_we_are.structured_state_present)
        self.assertEqual(home.where_we_are.objective, before.objective)
        self.assertEqual(home.where_we_are.status, "active")
        self.assertEqual(home.where_we_are.phase, PROJECT_STATE_NOT_RECORDED)
        self.assertEqual(home.where_we_are.current_focus, PROJECT_STATE_NOT_RECORDED)
        self.assertEqual(home.where_we_are.checkpoint, PROJECT_STATE_NOT_RECORDED)
        self.assertIsNone(home.where_we_are.next_planned_step)
        self.assertEqual(home.active_decisions, ())
        self.assertEqual(home.active_questions, ())
        self.assertEqual(home.plan_items, ())
        self.assertEqual(home.conversations, ())
        self.assertTrue(home.legacy_continuity.present)
        self.assertIn("Current focus\nNot yet recorded.", home.legacy_continuity.text)
        self.assertEqual(home.freshness.project_revision, before.revision)
        self.assertIsNone(home.freshness.structured_updated_at)
        self.assertIsNone(home.freshness.conversations_updated_at)
        self.assertEqual(self.projects.get_project(self.project.identifier), before)
        self.assertIsNone(self.projects.get_project_state(self.project.identifier))

    def test_where_we_are_filters_history_and_uses_structured_order(self) -> None:
        state = self.projects.update_project_state(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            expected_state_revision=None,
            phase="Build",
            current_focus="Project Home",
            checkpoint="Domain projection ready",
        )
        old_decision = self.projects.add_decision(
            self.project.identifier,
            expected_project_revision=state.project.revision,
            text="Use the old projection.",
        )
        decision = self.projects.supersede_decision(
            self.project.identifier,
            old_decision.record.identifier,
            expected_project_revision=old_decision.project.revision,
            expected_predecessor_revision=old_decision.record.revision,
            text="Use the presentation-neutral projection.",
            importance="important",
        )
        open_question = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=decision.project.revision,
            text="What should we show next?",
        )
        resolved_question = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=open_question.project.revision,
            text="Should legacy text become structured truth?",
        )
        resolved = self.projects.transition_question(
            self.project.identifier,
            resolved_question.record.identifier,
            expected_project_revision=resolved_question.project.revision,
            expected_question_revision=resolved_question.record.revision,
            state="resolved",
            disposition_note="No.",
        )
        deferred_question = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=resolved.project.revision,
            text="When does source integration arrive?",
        )
        deferred = self.projects.transition_question(
            self.project.identifier,
            deferred_question.record.identifier,
            expected_project_revision=deferred_question.project.revision,
            expected_question_revision=deferred_question.record.revision,
            state="deferred",
            disposition_note="Slice 5.",
        )
        planned = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=deferred.project.revision,
            text="Planned lower-order fallback",
            sort_order=20,
        )
        active_item = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=planned.project.revision,
            text="Active next step",
            sort_order=30,
        )
        active = self.projects.transition_plan_item(
            self.project.identifier,
            active_item.record.identifier,
            expected_project_revision=active_item.project.revision,
            expected_plan_item_revision=active_item.record.revision,
            state="active",
        )
        blocked_item = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=active.project.revision,
            text="Blocked earlier item",
            sort_order=10,
        )
        self.projects.transition_plan_item(
            self.project.identifier,
            blocked_item.record.identifier,
            expected_project_revision=blocked_item.project.revision,
            expected_plan_item_revision=blocked_item.record.revision,
            state="blocked",
            state_note="Awaiting review.",
        )

        home = self.projects.get_project_home(self.project.identifier)
        where = home.where_we_are
        self.assertEqual((where.phase, where.current_focus, where.checkpoint), (
            "Build", "Project Home", "Domain projection ready"
        ))
        self.assertEqual(home.active_decisions, (decision.record,))
        self.assertEqual(home.superseded_decisions, (
            self.store.get_project_decision(old_decision.record.identifier),
        ))
        self.assertEqual(
            [item.identifier for item in home.active_questions],
            [open_question.record.identifier, deferred.record.identifier],
        )
        self.assertEqual(home.closed_questions, (resolved.record,))
        self.assertEqual(where.open_questions, (open_question.record,))
        self.assertEqual(where.open_question_count, 1)
        self.assertEqual(where.deferred_question_count, 1)
        self.assertEqual(where.next_planned_step.identifier, active.record.identifier)
        self.assertEqual(where.active_plan_items, (active.record,))
        self.assertEqual(where.blocked_plan_items[0].state_note, "Awaiting review.")
        self.assertEqual(
            [item.sort_order for item in home.plan_items], [10, 20, 30]
        )

    def test_associated_conversations_are_metadata_only_ordered_and_detached_on_delete(self) -> None:
        first = self._chat("First", project_id=self.project.identifier)
        unrelated = self._chat("Unrelated")
        second = self._chat("Second", project_id=self.project.identifier)
        original_entries = {item.metadata.identifier: item.entries for item in (first, second)}

        conversations = self.projects.list_project_conversations(
            self.project.identifier
        )
        self.assertEqual(
            [item.identifier for item in conversations],
            [second.metadata.identifier, first.metadata.identifier],
        )
        self.assertNotIn("entries", {field.name for field in fields(conversations[0])})
        self.assertNotIn("text", {field.name for field in fields(conversations[0])})
        self.assertNotIn(unrelated.metadata.identifier, {
            item.identifier for item in conversations
        })
        self.assertEqual(
            self.projects.get_project_home(self.project.identifier).conversations,
            conversations,
        )
        for identifier, entries in original_entries.items():
            self.assertEqual(self.chats.get_chat(identifier).entries, entries)

        self.projects.delete_project(
            self.project.identifier, expected_revision=self.project.revision
        )
        for identifier, entries in original_entries.items():
            detached = self.chats.get_chat(identifier)
            self.assertIsNone(detached.metadata.project_id)
            self.assertEqual(detached.entries, entries)
        self.assertIsNone(
            self.chats.get_chat(unrelated.metadata.identifier).metadata.project_id
        )

    def test_legacy_continuity_is_separate_exact_and_never_inferred(self) -> None:
        legacy = (
            "Current focus\nLegacy focus.\n\n"
            "Key decisions\nLegacy decision.\n\n"
            "Open issues / blockers\nLegacy question.\n\n"
            "Next step\nLegacy next step."
        )
        project = self.store.create_project(
            title="Legacy",
            objective="Keep compatibility data separate",
            continuity_brief=legacy,
        )
        home = self.projects.get_project_home(project.identifier)
        self.assertTrue(home.legacy_continuity.present)
        self.assertEqual(home.legacy_continuity.text, legacy)
        self.assertFalse(home.where_we_are.structured_state_present)
        self.assertEqual(home.where_we_are.current_focus, PROJECT_STATE_NOT_RECORDED)
        self.assertEqual(self.store.get_project(project.identifier).continuity_brief, legacy)

    def test_new_project_chat_preparation_is_inert_and_revision_checked(self) -> None:
        before_chats = self.chats.list_chats()
        prepared = self.projects.prepare_new_project_chat(
            self.project.identifier,
            expected_project_revision=self.project.revision,
        )
        self.assertEqual(prepared, self.project)
        self.assertEqual(self.chats.list_chats(), before_chats)
        revised = self.projects.update_project(
            self.project.identifier,
            expected_revision=self.project.revision,
            title="Project Home revised",
        )
        with self.assertRaises(ChatServiceError) as stale:
            self.projects.prepare_new_project_chat(
                revised.identifier,
                expected_project_revision=self.project.revision,
            )
        self.assertEqual(stale.exception.code, "stale_revision")
        self.assertEqual(self.chats.list_chats(), before_chats)


if __name__ == "__main__":
    unittest.main()
