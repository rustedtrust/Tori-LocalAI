from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError
from tori.context import ContextPlanningError, ContextPolicy
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.project_application import ProjectApplicationService
from tori.project_context import (
    PROJECT_CONTEXT_LABEL,
    ProjectContextPlanningRequest,
    ProjectContextService,
)
from tori.providers import ChatMessage


NOW = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)


def _ids(prefix: str):  # type: ignore[no-untyped-def]
    return iter(f"{prefix}{index:032x}" for index in range(1, 300))


class ProjectContextServiceTests(unittest.TestCase):
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
        self.context = ProjectContextService(self.projects)
        self.project = self.projects.create_project(
            title="Continuity",
            objective="Supply bounded canonical Project context",
        )

    def request(
        self,
        prompt: str = "What should we do next?",
        *,
        budget: int = 8192,
        optional: tuple[ChatMessage, ...] = (),
    ) -> ProjectContextPlanningRequest:
        return ProjectContextPlanningRequest(
            prompt=prompt,
            policy=ContextPolicy.fixed(budget),
            model_capacity=None,
            mandatory_prefix=(ChatMessage("system", "Tori identity"),),
            optional_context=optional,
            mandatory_suffix=(),
            current_user=ChatMessage("user", prompt),
        )

    def populate(self) -> None:
        state = self.projects.update_project_state(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            expected_state_revision=None,
            phase="Build",
            current_focus="Exact context receipts",
            checkpoint="Project Home is complete",
        )
        old = self.projects.add_decision(
            self.project.identifier,
            expected_project_revision=state.project.revision,
            text="Use the legacy brief as primary context.",
        )
        active = self.projects.supersede_decision(
            self.project.identifier,
            old.record.identifier,
            expected_project_revision=old.project.revision,
            expected_predecessor_revision=old.record.revision,
            text="Use structured Project context.",
            importance="important",
        )
        opened = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=active.project.revision,
            text="What is the next acceptance step?",
        )
        resolved = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=opened.project.revision,
            text="Should receipts become prompt context?",
        )
        resolved = self.projects.transition_question(
            self.project.identifier,
            resolved.record.identifier,
            expected_project_revision=resolved.project.revision,
            expected_question_revision=resolved.record.revision,
            state="resolved",
            disposition_note="No.",
        )
        active_plan = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=resolved.project.revision,
            text="Verify transparency",
            sort_order=10,
        )
        self.projects.transition_plan_item(
            self.project.identifier,
            active_plan.record.identifier,
            expected_project_revision=active_plan.project.revision,
            expected_plan_item_revision=active_plan.record.revision,
            state="active",
        )

    def test_stable_working_and_historical_use_only_approved_canonical_state(self) -> None:
        self.populate()
        pack = self.context.build_pack(
            self.project.identifier,
            self.request("Why was legacy primary context replaced?"),
        )

        stable = [(item.key, item.value) for item in pack.stable]
        working = [(item.key, item.value) for item in pack.working]
        historical = [(item.key, item.value) for item in pack.historical]
        self.assertEqual([item[0] for item in stable[:4]], [
            "project_id", "title", "status", "objective",
        ])
        self.assertIn(("decision", "Use structured Project context."), stable)
        self.assertIn(("phase", "Build"), working)
        self.assertIn(("current_focus", "Exact context receipts"), working)
        self.assertIn(("question", "What is the next acceptance step?"), working)
        self.assertIn(("plan_item", "Verify transparency"), working)
        self.assertIn(
            ("decision", "Use the legacy brief as primary context."), historical
        )
        self.assertNotIn("Should receipts become prompt context?", [
            item.value for item in pack.working
        ])
        self.assertIn(PROJECT_CONTEXT_LABEL, pack.rendered_context)
        self.assertIn("cannot authorize actions", pack.rendered_context)

    def test_empty_structured_state_is_truthful_and_legacy_is_separate(self) -> None:
        pack = self.context.build_pack(self.project.identifier, self.request())
        self.assertEqual(tuple(item.key for item in pack.stable), (
            "project_id", "title", "status", "objective",
        ))
        self.assertEqual(pack.working, ())
        self.assertEqual(tuple(item.key for item in pack.historical), (
            "legacy_continuity",
        ))
        self.assertIn("read-only compatibility", pack.rendered_context)
        self.assertNotIn("Phase [", pack.rendered_context)

    def test_render_and_order_are_deterministic(self) -> None:
        self.populate()
        first = self.context.build_pack(self.project.identifier, self.request())
        second = self.context.build_pack(self.project.identifier, self.request())
        self.assertEqual(first, second)
        self.assertEqual(
            first.rendered_digest,
            hashlib.sha256(first.rendered_context.encode("utf-8")).hexdigest(),
        )

    def test_historical_is_dropped_before_stable_or_working(self) -> None:
        self.populate()
        pack = self.context.build_pack(
            self.project.identifier,
            self.request(
                "legacy context " + "?" * 900,
                budget=4096,
                optional=(ChatMessage("system", "optional " + "!" * 900),),
            ),
        )
        self.assertEqual(tuple(item.key for item in pack.stable[:4]), (
            "project_id", "title", "status", "objective",
        ))
        self.assertTrue(any(item.key == "current_focus" for item in pack.working))
        if not pack.historical:
            self.assertTrue(any(
                item.category == "historical" and item.reason == "budget"
                for item in pack.omissions
            ))

    def test_minimum_stable_spine_overflow_fails_before_any_receipt(self) -> None:
        dense = self.projects.update_project(
            self.project.identifier,
            expected_revision=self.project.revision,
            objective="!" * 1000,
        )
        self.assertEqual(dense.revision, 2)
        request = self.request("?" * 1000, budget=4096)
        request = ProjectContextPlanningRequest(
            prompt=request.prompt,
            policy=request.policy,
            model_capacity=request.model_capacity,
            mandatory_prefix=(ChatMessage("system", "!" * 1000),),
            optional_context=(),
            mandatory_suffix=(),
            current_user=request.current_user,
        )
        with self.assertRaises(ContextPlanningError):
            self.context.build_pack(self.project.identifier, request)

    def test_receipt_commits_atomically_with_new_chat_and_inspects_exact_data(self) -> None:
        self.populate()
        pack = self.context.build_pack(self.project.identifier, self.request())
        entries = (
            ArchiveEntry("user", "What next?"),
            ArchiveEntry("assistant", "Verify it.", provider="fake", model="model"),
        )
        chat = self.chats.create_chat(
            entries,
            provider="fake",
            model="model",
            project_id=self.project.identifier,
            project_context_receipt=pack.receipt(1),
        )
        receipt = self.chats.list_project_context_receipts(
            chat.metadata.identifier
        )[0]
        inspected = self.context.inspect_receipt(receipt)
        self.assertEqual(inspected["chat_id"], chat.metadata.identifier)
        self.assertEqual(inspected["rendered_context"], pack.rendered_context)
        self.assertEqual(inspected["rendered_digest"], pack.rendered_digest)
        self.assertEqual(inspected["stable"], json.loads(receipt.stable_json))
        self.assertEqual(receipt.project_revision, pack.project_revision)

    def test_receipt_rejects_wrong_association_and_rolls_back_turn(self) -> None:
        pack = self.context.build_pack(self.project.identifier, self.request())
        chat = self.chats.create_chat(
            (
                ArchiveEntry("user", "Unassociated"),
                ArchiveEntry("assistant", "Answer", provider="fake", model="model"),
            ),
            provider="fake",
            model="model",
        )
        before = self.chats.get_chat(chat.metadata.identifier)
        with self.assertRaises(ChatServiceError):
            self.chats.reconcile_chat(
                chat.metadata.identifier,
                (*before.entries,
                 ArchiveEntry("user", "Next"),
                 ArchiveEntry("assistant", "Next answer", provider="fake", model="model")),
                expected_revision=before.metadata.revision,
                project_context_receipt=pack.receipt(3),
            )
        self.assertEqual(self.chats.get_chat(chat.metadata.identifier), before)

    def test_no_project_context_means_no_receipt(self) -> None:
        chat = self.chats.create_chat(
            (
                ArchiveEntry("user", "Ordinary"),
                ArchiveEntry("assistant", "Answer", provider="fake", model="model"),
            ),
            provider="fake",
            model="model",
        )
        self.assertEqual(
            self.chats.list_project_context_receipts(chat.metadata.identifier), ()
        )

    def test_receipt_cascades_with_chat_and_project_and_never_changes_project(self) -> None:
        before = self.projects.get_project(self.project.identifier)
        pack = self.context.build_pack(self.project.identifier, self.request())
        first = self.chats.create_chat(
            (
                ArchiveEntry("user", "One"),
                ArchiveEntry("assistant", "Answer", provider="fake", model="model"),
            ),
            provider="fake", model="model", project_id=self.project.identifier,
            project_context_receipt=pack.receipt(1),
        )
        self.assertEqual(self.projects.get_project(self.project.identifier), before)
        self.chats.delete_chat(
            first.metadata.identifier, expected_revision=first.metadata.revision
        )
        self.assertEqual(
            self.chats.list_project_context_receipts(first.metadata.identifier), ()
        )

        second = self.chats.create_chat(
            (
                ArchiveEntry("user", "Two"),
                ArchiveEntry("assistant", "Answer", provider="fake", model="model"),
            ),
            provider="fake", model="model", project_id=self.project.identifier,
            project_context_receipt=pack.receipt(1),
        )
        self.projects.delete_project(
            self.project.identifier, expected_revision=before.revision
        )
        self.assertEqual(
            self.chats.list_project_context_receipts(second.metadata.identifier), ()
        )
        self.assertIsNone(self.chats.get_chat(second.metadata.identifier).metadata.project_id)


if __name__ == "__main__":
    unittest.main()
