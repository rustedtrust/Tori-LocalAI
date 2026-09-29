from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError
from tori.conversation_archive import ConversationArchiveStore
from tori.project_application import ProjectApplicationService
from tori.projects import initial_continuity_brief


NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _ids(prefix: str):  # type: ignore[no-untyped-def]
    return iter(f"{prefix}{index:032x}" for index in range(1, 100))


class StructuredProjectApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive.db"
        projects = _ids("project-")
        decisions = _ids("decision-")
        questions = _ids("question-")
        plans = _ids("plan-item-")
        links = _ids("project-link-")
        self.verified_targets: list[tuple[str, str]] = []

        def verify_target(target_type: str, target_id: str) -> bool:
            self.verified_targets.append((target_type, target_id))
            return True

        self.store = ConversationArchiveStore(
            self.path,
            clock=lambda: NOW,
            project_identifier_factory=lambda: next(projects),
            project_decision_identifier_factory=lambda: next(decisions),
            project_question_identifier_factory=lambda: next(questions),
            project_plan_identifier_factory=lambda: next(plans),
            project_link_identifier_factory=lambda: next(links),
        )
        self.chats = ChatService(self.store)
        self.projects = ProjectApplicationService(
            self.chats, link_target_verifier=verify_target
        )
        self.project = self.projects.create_project(
            title="Continuity",
            objective="Exercise explicit structured Project state",
        )

    def test_workspace_state_is_explicit_revision_safe_and_aggregate_fenced(self) -> None:
        self.assertIsNone(self.projects.get_project_state(self.project.identifier))
        created = self.projects.update_project_state(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            expected_state_revision=None,
            phase="Design",
            current_focus="Lock the domain behavior",
            checkpoint=None,
        )
        self.assertEqual(created.project.revision, self.project.revision + 1)
        self.assertEqual(created.record.revision, 1)
        self.assertEqual(created.record.phase, "Design")

        with self.assertRaises(ChatServiceError) as stale_parent:
            self.projects.update_project_state(
                self.project.identifier,
                expected_project_revision=self.project.revision,
                expected_state_revision=created.record.revision,
                phase="Build",
                current_focus="Too late",
                checkpoint=None,
            )
        self.assertEqual(stale_parent.exception.code, "stale_revision")

        with self.assertRaises(ChatServiceError) as stale_child:
            self.projects.update_project_state(
                self.project.identifier,
                expected_project_revision=created.project.revision,
                expected_state_revision=2,
                phase="Build",
                current_focus="Wrong child revision",
                checkpoint=None,
            )
        self.assertEqual(stale_child.exception.code, "stale_revision")
        self.assertEqual(
            self.projects.get_project(self.project.identifier), created.project
        )
        self.assertEqual(
            self.projects.get_project_state(self.project.identifier), created.record
        )

        updated = self.projects.update_project_state(
            self.project.identifier,
            expected_project_revision=created.project.revision,
            expected_state_revision=created.record.revision,
            phase="Build",
            current_focus="Implement Slice 2",
            checkpoint="State mutation verified",
        )
        self.assertEqual(updated.project.revision, created.project.revision + 1)
        self.assertEqual(updated.record.revision, created.record.revision + 1)

    def test_decisions_are_immutable_linear_and_deterministically_queryable(self) -> None:
        first = self.projects.add_decision(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            text="Use explicit structured state.",
        )
        important = self.projects.mark_decision_important(
            self.project.identifier,
            first.record.identifier,
            expected_project_revision=first.project.revision,
            expected_decision_revision=first.record.revision,
        )
        replacement = self.projects.supersede_decision(
            self.project.identifier,
            important.record.identifier,
            expected_project_revision=important.project.revision,
            expected_predecessor_revision=important.record.revision,
            text="Use structured state and preserve the legacy brief read-only.",
            importance="important",
        )
        predecessor = self.store.get_project_decision(important.record.identifier)
        self.assertEqual(predecessor.state, "superseded")
        self.assertEqual(predecessor.text, "Use explicit structured state.")
        self.assertEqual(replacement.record.supersedes_decision_id, predecessor.identifier)
        self.assertEqual(
            self.projects.list_decisions(self.project.identifier, active_only=True),
            (replacement.record,),
        )
        self.assertEqual(replacement.project.revision, self.project.revision + 3)

        with self.assertRaises(ChatServiceError) as branch:
            self.projects.supersede_decision(
                self.project.identifier,
                predecessor.identifier,
                expected_project_revision=replacement.project.revision,
                expected_predecessor_revision=predecessor.revision,
                text="A branch is forbidden.",
            )
        self.assertEqual(branch.exception.code, "conflict")

        with closing(sqlite3.connect(self.path)) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE project_decisions SET text=? WHERE identifier=?",
                    ("Rewritten history", predecessor.identifier),
                )

    def test_decision_cross_project_and_cycle_attempts_are_rejected(self) -> None:
        decision = self.projects.add_decision(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            text="Stay in this Project.",
        )
        other = self.projects.create_project(title="Other", objective="Stay separate")
        with self.assertRaises(ChatServiceError) as crossed:
            self.projects.supersede_decision(
                other.identifier,
                decision.record.identifier,
                expected_project_revision=other.revision,
                expected_predecessor_revision=decision.record.revision,
                text="Cross-Project mutation",
            )
        self.assertEqual(crossed.exception.code, "conflict")
        self.assertEqual(self.projects.get_project(other.identifier), other)

        cycle_path = Path(self.temporary.name) / "cycle.db"
        repeated = "decision-" + "f" * 32
        cycle_store = ConversationArchiveStore(
            cycle_path,
            clock=lambda: NOW,
            project_identifier_factory=lambda: "project-" + "f" * 32,
            project_decision_identifier_factory=lambda: repeated,
        )
        cycle_projects = ProjectApplicationService(ChatService(cycle_store))
        cycle_project = cycle_projects.create_project(
            title="Cycle", objective="Reject a self-cycle"
        )
        original = cycle_projects.add_decision(
            cycle_project.identifier,
            expected_project_revision=cycle_project.revision,
            text="Original",
        )
        with self.assertRaises(ChatServiceError) as cycle:
            cycle_projects.supersede_decision(
                cycle_project.identifier,
                original.record.identifier,
                expected_project_revision=original.project.revision,
                expected_predecessor_revision=original.record.revision,
                text="Cycle",
            )
        self.assertEqual(cycle.exception.code, "conflict")
        self.assertEqual(cycle_store.list_project_decisions(cycle_project.identifier), (
            original.record,
        ))

    def test_question_transitions_and_active_filter_are_explicit(self) -> None:
        first = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            text="Which source should be linked?",
        )
        with self.assertRaises(ChatServiceError) as stale:
            self.projects.transition_question(
                self.project.identifier,
                first.record.identifier,
                expected_project_revision=first.project.revision,
                expected_question_revision=2,
                state="deferred",
            )
        self.assertEqual(stale.exception.code, "stale_revision")
        deferred = self.projects.transition_question(
            self.project.identifier,
            first.record.identifier,
            expected_project_revision=first.project.revision,
            expected_question_revision=first.record.revision,
            state="deferred",
            disposition_note="Wait for Slice 5.",
        )
        self.assertEqual(
            self.projects.list_questions(self.project.identifier, active_only=True),
            (deferred.record,),
        )
        reopened = self.projects.transition_question(
            self.project.identifier,
            deferred.record.identifier,
            expected_project_revision=deferred.project.revision,
            expected_question_revision=deferred.record.revision,
            state="open",
        )
        resolved = self.projects.transition_question(
            self.project.identifier,
            reopened.record.identifier,
            expected_project_revision=reopened.project.revision,
            expected_question_revision=reopened.record.revision,
            state="resolved",
            disposition_note="The source owner verifies it.",
        )
        self.assertEqual(
            self.projects.list_questions(self.project.identifier, active_only=True), ()
        )
        with self.assertRaises(ChatServiceError) as terminal:
            self.projects.transition_question(
                self.project.identifier,
                resolved.record.identifier,
                expected_project_revision=resolved.project.revision,
                expected_question_revision=resolved.record.revision,
                state="open",
            )
        self.assertEqual(terminal.exception.code, "conflict")
        second = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=resolved.project.revision,
            text="Should this duplicate an existing capability record?",
        )
        dismissed = self.projects.transition_question(
            self.project.identifier,
            second.record.identifier,
            expected_project_revision=second.project.revision,
            expected_question_revision=second.record.revision,
            state="dismissed",
            disposition_note="No; source ownership remains canonical.",
        )
        self.assertEqual(
            self.projects.list_questions(self.project.identifier, active_only=True), ()
        )
        self.assertEqual(
            self.projects.get_project(self.project.identifier), dismissed.project
        )

    def test_plan_items_order_updates_transitions_and_stale_fences(self) -> None:
        later = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            text="Second step",
            sort_order=20,
        )
        earlier = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=later.project.revision,
            text="First step",
            sort_order=10,
        )
        self.assertEqual(
            [item.text for item in self.projects.list_plan_items(self.project.identifier)],
            ["First step", "Second step"],
        )
        updated = self.projects.update_plan_item(
            self.project.identifier,
            later.record.identifier,
            expected_project_revision=earlier.project.revision,
            expected_plan_item_revision=later.record.revision,
            text="Second step, refined",
            state_note=None,
            sort_order=30,
        )
        active = self.projects.transition_plan_item(
            self.project.identifier,
            updated.record.identifier,
            expected_project_revision=updated.project.revision,
            expected_plan_item_revision=updated.record.revision,
            state="active",
        )
        blocked = self.projects.transition_plan_item(
            self.project.identifier,
            active.record.identifier,
            expected_project_revision=active.project.revision,
            expected_plan_item_revision=active.record.revision,
            state="blocked",
            state_note="Needs a human decision.",
        )
        self.assertEqual(blocked.record.state, "blocked")
        with self.assertRaises(ChatServiceError) as stale_child:
            self.projects.update_plan_item(
                self.project.identifier,
                blocked.record.identifier,
                expected_project_revision=blocked.project.revision,
                expected_plan_item_revision=1,
                text="Stale edit",
                state_note="Still blocked",
                sort_order=40,
            )
        self.assertEqual(stale_child.exception.code, "stale_revision")
        self.assertEqual(
            self.projects.get_project(self.project.identifier), blocked.project
        )
        deferred = self.projects.transition_plan_item(
            self.project.identifier,
            blocked.record.identifier,
            expected_project_revision=blocked.project.revision,
            expected_plan_item_revision=blocked.record.revision,
            state="deferred",
            state_note="Move to the later context slice.",
        )
        completed = self.projects.transition_plan_item(
            self.project.identifier,
            deferred.record.identifier,
            expected_project_revision=deferred.project.revision,
            expected_plan_item_revision=deferred.record.revision,
            state="completed",
            state_note="The bounded foundation is complete.",
        )
        self.assertEqual(completed.record.state, "completed")

    def test_links_are_narrow_verified_unique_and_revision_safe(self) -> None:
        target = "finding-" + "1" * 32
        linked = self.projects.link_resource(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            target_type="night_owl_finding",
            target_id=target,
        )
        self.assertEqual(self.verified_targets, [("night_owl_finding", target)])
        self.assertEqual(self.projects.list_links(self.project.identifier), (linked.record,))

        with self.assertRaises(ChatServiceError) as duplicate:
            self.projects.link_resource(
                self.project.identifier,
                expected_project_revision=linked.project.revision,
                target_type="night_owl_finding",
                target_id=target,
            )
        self.assertEqual(duplicate.exception.code, "conflict")

        with self.assertRaises(ChatServiceError) as invalid:
            self.projects.link_resource(  # type: ignore[arg-type]
                self.project.identifier,
                expected_project_revision=linked.project.revision,
                target_type="research_job",
                target_id="research-" + "2" * 32,
            )
        self.assertEqual(invalid.exception.code, "invalid_record")
        self.assertEqual(self.verified_targets, [
            ("night_owl_finding", target),
            ("night_owl_finding", target),
        ])

        unlinked = self.projects.unlink_resource(
            self.project.identifier,
            linked.record.identifier,
            expected_project_revision=linked.project.revision,
            expected_link_revision=linked.record.revision,
        )
        self.assertEqual(unlinked.revision, linked.project.revision + 1)
        self.assertEqual(self.projects.list_links(self.project.identifier), ())

        unavailable = ProjectApplicationService(self.chats)
        with self.assertRaises(ChatServiceError) as missing_verifier:
            unavailable.link_resource(
                self.project.identifier,
                expected_project_revision=unlinked.revision,
                target_type="knowledge_source",
                target_id="ksrc-" + "3" * 32,
            )
        self.assertEqual(missing_verifier.exception.code, "link_target_unavailable")
        self.assertEqual(self.projects.get_project(self.project.identifier), unlinked)

    def test_project_deletion_cascades_owned_rows_only(self) -> None:
        unrelated = Path(self.temporary.name) / "source-owned.db"
        unrelated.write_bytes(b"source-owned canonical state")
        before = unrelated.read_bytes()

        state = self.projects.update_project_state(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            expected_state_revision=None,
            phase="Build",
            current_focus=None,
            checkpoint=None,
        )
        decision = self.projects.add_decision(
            self.project.identifier,
            expected_project_revision=state.project.revision,
            text="Keep source ownership separate.",
        )
        question = self.projects.add_question(
            self.project.identifier,
            expected_project_revision=decision.project.revision,
            text="Is deletion bounded?",
        )
        plan = self.projects.add_plan_item(
            self.project.identifier,
            expected_project_revision=question.project.revision,
            text="Verify the cascade",
            sort_order=0,
        )
        link = self.projects.link_resource(
            self.project.identifier,
            expected_project_revision=plan.project.revision,
            target_type="knowledge_source",
            target_id="ksrc-" + "4" * 32,
        )
        self.projects.delete_project(
            self.project.identifier, expected_revision=link.project.revision
        )

        with closing(sqlite3.connect(self.path)) as connection:
            for table in (
                "project_state",
                "project_decisions",
                "project_questions",
                "project_plan_items",
                "project_links",
                "project_context_receipts",
            ):
                self.assertEqual(
                    connection.execute(
                        f"SELECT count(*) FROM {table} WHERE project_id=?",
                        (self.project.identifier,),
                    ).fetchone()[0],
                    0,
                )
        self.assertEqual(unrelated.read_bytes(), before)

    def test_legacy_brief_is_readable_and_normal_application_writes_preserve_it(self) -> None:
        legacy = initial_continuity_brief("Preserve the historical checkpoint")
        legacy_project = self.store.create_project(
            title="Legacy",
            objective="Remain readable",
            continuity_brief=legacy,
        )
        updated = self.projects.update_project(
            legacy_project.identifier,
            expected_revision=legacy_project.revision,
            title="Legacy renamed",
        )
        self.assertEqual(updated.continuity_brief, legacy)
        self.assertEqual(self.projects.get_project(updated.identifier).continuity_brief, legacy)
        self.assertIsNone(self.projects.get_project_state(updated.identifier))
        self.assertEqual(self.projects.list_decisions(updated.identifier), ())


if __name__ == "__main__":
    unittest.main()
