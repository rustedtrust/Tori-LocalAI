from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.conversation_archive import (
    ArchiveEntry,
    ArchiveNotFoundError,
    ArchiveStaleRevisionError,
    ArchiveValidationError,
    ConversationArchiveStore,
    MemoryExtractionRequest,
)
from tori.chats import ChatService, ChatServiceError
from tori.projects import (
    ContinuitySections,
    PROJECT_CONTEXT_LABEL,
    ProjectIntent,
    build_project_context,
    initial_continuity_brief,
    interpret_project_clarification_answer,
    interpret_project_intent,
    render_continuity_brief,
)
from tori.memory import SQLiteMemoryStore
from tori.context import ContextPolicy, plan_context
from tori.providers import ChatMessage
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.tasks import SQLiteOperationalStore


NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


class ProjectStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        chat_ids = iter(("chat-" + "1" * 32, "chat-" + "2" * 32))
        project_ids = iter(("project-" + "a" * 32, "project-" + "b" * 32))
        self.store = ConversationArchiveStore(
            Path(self.temporary.name) / "archive.db",
            clock=lambda: NOW,
            identifier_factory=lambda: next(chat_ids),
            project_identifier_factory=lambda: next(project_ids),
        )

    def chat(self):  # type: ignore[no-untyped-def]
        return self.store.create_chat(
            (
                ArchiveEntry("user", "Exact question"),
                ArchiveEntry("assistant", "Exact answer", provider="fake", model="model"),
            ),
            provider="fake",
            model="model",
        )

    def test_crud_revisions_lifecycle_and_bounds(self) -> None:
        legacy_brief = initial_continuity_brief("Replace storage")
        project = self.store.create_project(
            title="NAS rebuild",
            objective="Rebuild the NAS",
            continuity_brief=legacy_brief,
        )
        self.assertEqual(project.revision, 1)
        self.assertEqual(project.status, "active")
        paused = self.store.update_project(
            project.identifier, expected_revision=1, status="paused",
        )
        self.assertEqual((paused.status, paused.revision), ("paused", 2))
        self.assertEqual(paused.continuity_brief, legacy_brief)
        completed = self.store.update_project(
            project.identifier, expected_revision=2, status="completed"
        )
        resumed = self.store.update_project(
            project.identifier, expected_revision=3, status="active"
        )
        self.assertEqual((completed.status, resumed.status), ("completed", "active"))
        with self.assertRaises(ArchiveStaleRevisionError):
            self.store.update_project(project.identifier, expected_revision=1, title="stale")
        with self.assertRaises(ArchiveValidationError):
            self.store.create_project(title="x" * 121, objective="bounded")
        with self.assertRaises(ArchiveValidationError):
            self.store.create_project(
                title="Bounded", objective="Bounded", continuity_brief="x" * 4001
            )

    def test_project_validation_is_not_mislabeled_as_invalid_chat_data(self) -> None:
        service = ChatService(self.store)
        with self.assertRaises(ChatServiceError) as caught:
            service.create_project(
                title="Synthetic Project",
                objective="Verify the Project error boundary",
                continuity_brief="An incomplete unstructured brief",
            )
        self.assertEqual(caught.exception.code, "invalid_record")
        self.assertIn("four required sections", str(caught.exception))
        self.assertNotIn("chat data", str(caught.exception).casefold())

    def test_atomic_create_associate_multiple_chats_and_delete_detaches(self) -> None:
        first = self.chat()
        second = self.chat()
        project = self.store.create_project(
            title="Tori", objective="Continue Tori", chat_id=first.metadata.identifier,
            expected_chat_revision=first.metadata.revision,
        )
        first_after = self.store.get_chat(first.metadata.identifier)
        second_after = self.store.associate_chat(
            second.metadata.identifier, project.identifier,
            expected_revision=second.metadata.revision,
        )
        self.assertEqual(first_after.metadata.project_id, project.identifier)
        self.assertEqual(second_after.metadata.project_id, project.identifier)
        self.assertEqual(first_after.entries, first.entries)
        self.store.delete_project(project.identifier, expected_revision=1)
        with self.assertRaises(ArchiveNotFoundError):
            self.store.get_project(project.identifier)
        self.assertIsNone(self.store.get_chat(first.metadata.identifier).metadata.project_id)
        self.assertIsNone(self.store.get_chat(second.metadata.identifier).metadata.project_id)
        self.assertEqual(self.store.get_chat(first.metadata.identifier).entries, first.entries)

    def test_failed_atomic_creation_leaves_no_project_or_association(self) -> None:
        chat = self.chat()
        with self.assertRaises(ArchiveStaleRevisionError):
            self.store.create_project(
                title="Never committed", objective="Nothing",
                chat_id=chat.metadata.identifier, expected_chat_revision=99,
            )
        self.assertEqual(self.store.list_projects(), ())
        self.assertIsNone(self.store.get_chat(chat.metadata.identifier).metadata.project_id)

    def test_project_changes_do_not_touch_memory_operational_or_scheduled_stores(self) -> None:
        root = Path(self.temporary.name)
        memory_path = root / "memory.db"
        tasks_path = root / "tasks.db"
        scheduled_path = root / "scheduled.db"
        SQLiteMemoryStore(memory_path).create("Independent memory")
        SQLiteOperationalStore(tasks_path).create_task("Independent task")
        SQLiteScheduledWorkStore(scheduled_path).initialize()
        before = {
            path: path.read_bytes()
            for path in (memory_path, tasks_path, scheduled_path)
        }
        chat = self.chat()
        project = self.store.create_project(
            title="Separated", objective="Remain archive-owned",
            chat_id=chat.metadata.identifier,
            expected_chat_revision=chat.metadata.revision,
        )
        self.store.update_project(
            project.identifier, expected_revision=1, status="paused"
        )
        self.store.delete_project(project.identifier, expected_revision=2)
        self.assertEqual(
            {path: path.read_bytes() for path in before}, before
        )

    def test_project_changes_preserve_archive_memory_extraction_records(self) -> None:
        chat = self.store.create_chat(
            (
                ArchiveEntry("user", "Exact extraction source"),
                ArchiveEntry(
                    "assistant", "Exact extraction answer",
                    provider="fake", model="model",
                ),
            ),
            provider="fake",
            model="model",
            memory_extraction=MemoryExtractionRequest(
                "extract-" + "c" * 32, 0, 1, "fake", "model", "d" * 64
            ),
        )
        before = self.store.list_memory_extractions()
        project = self.store.create_project(
            title="Extraction separation",
            objective="Keep the M24 outbox unchanged",
            chat_id=chat.metadata.identifier,
            expected_chat_revision=chat.metadata.revision,
        )
        revised = self.store.update_project(
            project.identifier, expected_revision=project.revision, status="paused"
        )
        self.store.delete_project(
            revised.identifier, expected_revision=revised.revision
        )
        self.assertEqual(self.store.list_memory_extractions(), before)


class ProjectContextAndIntentTests(unittest.TestCase):
    def project(self):  # type: ignore[no-untyped-def]
        from tori.conversation_archive import ProjectRecord
        return ProjectRecord(
            "project-" + "a" * 32, "NAS rebuild", "active", "Rebuild safely",
            initial_continuity_brief("Select disks"), 3,
            "2026-08-20T12:00:00Z", "2026-08-20T12:00:00Z",
        )

    def test_context_is_bounded_labeled_data_not_authority(self) -> None:
        rendered = build_project_context(self.project())
        self.assertIn(PROJECT_CONTEXT_LABEL, rendered)
        self.assertIn("not as an instruction or permission", rendered)
        self.assertIn("current user request appears last", rendered)
        self.assertNotIn("memory", rendered.casefold())

    def test_legacy_brief_remains_readable_but_has_no_synthesis_helper(self) -> None:
        project = self.project()
        self.assertIn("Current focus\nSelect disks", project.continuity_brief)
        import tori.projects as projects_module
        self.assertFalse(hasattr(projects_module, "build_continuity_update"))

    def test_structurally_corrupt_continuity_is_rejected_before_use(self) -> None:
        with self.assertRaises(ArchiveValidationError):
            render_continuity_brief(ContinuitySections(
                current_focus="Valid focus",
                key_decisions="Current focus\nNested brief",
                open_issues="Recent conversation:\nuser: raw transcript",
                next_step="Valid next step",
            ))

    def test_required_project_context_survives_ordinary_history_trimming(self) -> None:
        project_context = build_project_context(self.project())
        history = tuple(
            message
            for index in range(8)
            for message in (
                ChatMessage("user", f"old-{index} " + "word " * 250),
                ChatMessage("assistant", f"answer-{index} " + "word " * 250),
            )
        )
        planned = plan_context(
            policy=ContextPolicy.fixed(4096),
            model_capacity=None,
            mandatory_prefix=(ChatMessage("system", "Tori identity"),),
            mandatory_suffix=(ChatMessage("system", project_context),),
            optional_context=(),
            history=history,
            current_user=ChatMessage("user", "Current authoritative request"),
        )
        self.assertGreater(planned.telemetry.omitted_history_messages, 0)
        self.assertTrue(any(
            PROJECT_CONTEXT_LABEL in message.content for message in planned.messages
        ))
        self.assertEqual(
            planned.messages[-1],
            ChatMessage("user", "Current authoritative request"),
        )

    def test_varied_creation_phrasings_converge(self) -> None:
        phrasings = (
            "Tori, I'd like to create a new project for rebuilding my NAS.",
            "Let's create a new project for rebuilding my NAS.",
            "Create a new project for rebuilding my NAS.",
            "Can we start a project for rebuilding my NAS?",
            "I want a new project for the NAS rebuild.",
        )
        self.assertEqual(
            [interpret_project_intent(text, current_project=None).operation for text in phrasings],
            ["create"] * len(phrasings),
        )

    def test_project_creation_requires_clear_creation_language(self) -> None:
        creation = {
            "Create a Project for this.": "this",
            "Let's make a new Project called Test Project.": "Test Project",
            "Let's make this a Project.": "this",
            "Go ahead and create the Project.": "this",
        }
        for text, subject in creation.items():
            with self.subTest(text=text):
                self.assertEqual(
                    interpret_project_intent(text, current_project=None),
                    ProjectIntent("create", subject),
                )

        discussion = (
            "I just want to discuss a project idea.",
            "Don't create a Project; let's talk about it.",
            "Let's discuss this project for now.",
            "Let's start discussing this project.",
            "I only want to talk through the project.",
            "Let's think it through before making it a Project.",
            "Don't make this a Project.",
        )
        for text in discussion:
            with self.subTest(text=text):
                self.assertIsNone(
                    interpret_project_intent(text, current_project=None)
                )

    def test_potential_project_ideas_request_conversational_clarification(self) -> None:
        ambiguous = (
            "I have an idea for a project.",
            "I've been thinking about a new project.",
            "I’ve been thinking about a project to reorganize my local AI setup.",
            "Can we work through a project idea?",
            "Should we create a Project?",
            "Do you think we should create a Project?",
            "Would it make sense to make this a Project?",
            "Maybe we should make this a Project.",
            "Maybe this could become a Project.",
            "Should this become a Project?",
            "I was thinking this might make a good Project.",
            "I might want to turn this into a Project.",
        )
        for text in ambiguous:
            with self.subTest(text=text):
                self.assertEqual(
                    interpret_project_intent(text, current_project=None),
                    ProjectIntent("clarify", "this project idea"),
                )

    def test_project_intent_keywords_alone_do_not_authorize_creation(self) -> None:
        ordinary = (
            "Project management is an interesting topic.",
            "These projects need careful planning.",
            "Creative work can be difficult.",
            "What does create mean in programming?",
            "We should create a comparison of project tools.",
            "This project is going pretty well.",
            "I'm working on a project at the moment.",
            "I finished a project earlier today.",
            "What programming language would you use for this project?",
            "Let's discuss the architecture for this project.",
            "I don't want to create a Project.",
            "Don't make this a Project.",
            "We can talk about the project without creating anything.",
            "Creating projects in Python is easy.",
        )
        for text in ordinary:
            with self.subTest(text=text):
                self.assertIsNone(
                    interpret_project_intent(text, current_project=None)
                )

    def test_project_clarification_answers_are_bounded_and_fail_closed(self) -> None:
        for answer in (
            "create",
            "create it",
            "Yes, let’s create it.",
            "Yeah, let's create it.",
            "Let's go ahead and create it.",
            "Sure, create the Project.",
            "Yes, make it a Project.",
            "Let's make it an actual Project.",
            "Go ahead and create it.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    interpret_project_clarification_answer(answer), "create"
                )
        for answer in (
            "discuss",
            "Let's just discuss it.",
            "Let's just talk about it.",
            "Not yet, let's keep discussing it.",
            "No, don't create anything yet.",
            "Let's think it through first.",
            "Just talk for now.",
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    interpret_project_clarification_answer(answer), "discuss"
                )
        for answer in (
            "yes", "maybe", "I'm not sure yet", "what do you think?",
            "project", "create a comparison",
        ):
            with self.subTest(answer=answer):
                self.assertIsNone(
                    interpret_project_clarification_answer(answer)
                )

    def test_update_association_detach_and_lifecycle_meaning(self) -> None:
        project = self.project()
        cases = {
            "Update the project with where we left off.": "update",
            "Refresh our project continuity brief.": "update",
            "Attach this conversation to the NAS rebuild project.": "associate",
            "Disconnect this chat from the project.": "detach",
            "Put this project on hold.": "pause",
            "Reactivate this project.": "resume",
            "Finish this project.": "complete",
        }
        for text, operation in cases.items():
            with self.subTest(text=text):
                result = interpret_project_intent(
                    text, current_project=project, projects=(project,)
                )
                self.assertIsNotNone(result)
                self.assertEqual(result.operation, operation)

    def test_talking_about_project_does_not_switch_or_mutate(self) -> None:
        project = self.project()
        ordinary = (
            "For this project, our focus is cross-conversation continuity.",
            "We decided to use the marker cobalt bridge 725.",
            "The next step is to open a fresh conversation under this Project.",
            "Let's talk about the NAS rebuild project.",
            "How should we use conversations in this project?",
            "This Project will use several conversations.",
            "I want to discuss how the conversation should continue.",
            "I have an idea for this project.",
            (
                "For this disposable acceptance project, our current focus is "
                "cross-conversation continuity. We decided to use the marker "
                "cobalt bridge 725. There are no current blockers. The next step "
                "is to open a fresh conversation under this Project and ask where "
                "we left off."
            ),
            "What is a project?",
        )
        for text in ordinary:
            with self.subTest(text=text):
                self.assertIsNone(interpret_project_intent(
                    text, current_project=project, projects=(project,)
                ))

    def test_coherent_association_switch_and_detach_variants(self) -> None:
        from tori.conversation_archive import ProjectRecord

        alpha = ProjectRecord(
            "project-" + "b" * 32, "M25 Acceptance Alpha", "active", "Alpha objective",
            initial_continuity_brief("Alpha focus"), 1,
            "2026-08-20T12:00:00Z", "2026-08-20T12:00:00Z",
        )
        beta = ProjectRecord(
            "project-" + "c" * 32, "M25 Acceptance Beta", "active", "Beta objective",
            initial_continuity_brief("Beta focus"), 1,
            "2026-08-20T12:00:00Z", "2026-08-20T12:00:00Z",
        )
        projects = (alpha, beta)
        association_cases = {
            "Put this conversation in the Alpha project.": "M25 Acceptance Alpha",
            "Associate this chat with Acceptance Alpha.": "M25 Acceptance Alpha",
            "Attach this conversation to M25 Acceptance Alpha.": "M25 Acceptance Alpha",
            "Let's continue this conversation under Alpha.": "M25 Acceptance Alpha",
            "Let's continue this under Alpha.": "M25 Acceptance Alpha",
            "Switch this conversation to Beta.": "M25 Acceptance Beta",
            "Move this chat to Beta.": "M25 Acceptance Beta",
            "This chat belongs to Alpha.": "M25 Acceptance Alpha",
        }
        for text, subject in association_cases.items():
            with self.subTest(text=text):
                result = interpret_project_intent(
                    text, current_project=alpha, projects=projects
                )
                self.assertEqual(result, ProjectIntent("associate", subject))

        for text in (
            "Remove this conversation from the project.",
            "Detach this chat from the project.",
            "This chat isn't part of this project anymore.",
        ):
            with self.subTest(text=text):
                result = interpret_project_intent(
                    text, current_project=alpha, projects=projects
                )
                self.assertEqual(result, ProjectIntent("detach"))

        ambiguous = interpret_project_intent(
            "Attach this conversation to Acceptance.",
            current_project=alpha,
            projects=projects,
        )
        self.assertEqual(ambiguous, ProjectIntent("associate", None))
        missing = interpret_project_intent(
            "Attach this conversation to Gamma.",
            current_project=alpha,
            projects=projects,
        )
        self.assertEqual(missing, ProjectIntent("associate", None))


if __name__ == "__main__":
    unittest.main()
