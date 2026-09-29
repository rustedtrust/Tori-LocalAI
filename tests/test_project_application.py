from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError
from tori.conversation_archive import (
    ArchiveEntry,
    ConversationArchiveStore,
    MemoryExtractionRequest,
)
from tori.project_application import ProjectApplicationService


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class ProjectApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        chat_ids = iter(f"chat-{index:032x}" for index in range(1, 20))
        project_ids = iter(f"project-{index:032x}" for index in range(1, 20))
        self.store = ConversationArchiveStore(
            Path(self.temporary.name) / "archive.db",
            clock=lambda: NOW,
            identifier_factory=lambda: next(chat_ids),
            project_identifier_factory=lambda: next(project_ids),
        )
        self.chats = ChatService(self.store)
        self.projects = ProjectApplicationService(self.chats)

    def create_chat(self, label: str = "Exact question"):  # type: ignore[no-untyped-def]
        return self.chats.create_chat(
            (
                ArchiveEntry("user", label),
                ArchiveEntry(
                    "assistant", "Exact answer", provider="fake", model="model"
                ),
            ),
            provider="fake",
            model="model",
        )

    def test_list_get_and_project_for_conversation(self) -> None:
        chat = self.create_chat()
        project = self.projects.create_project(
            title="Application boundary", objective="Extract Project use cases"
        )
        self.assertEqual(self.projects.list_projects(), (project,))
        self.assertEqual(self.projects.get_project(project.identifier), project)
        self.assertIsNone(
            self.projects.project_for_conversation(chat.metadata.identifier)
        )
        associated = self.projects.associate_conversation(
            chat.metadata.identifier,
            project.identifier,
            expected_conversation_revision=chat.metadata.revision,
        )
        self.assertEqual(associated.metadata.project_id, project.identifier)
        self.assertEqual(
            self.projects.project_for_conversation(chat.metadata.identifier), project
        )

    def test_create_and_atomic_create_associate_preserve_exact_revision(self) -> None:
        standalone = self.projects.create_project(
            title="Standalone", objective="Remain unassociated"
        )
        self.assertEqual(standalone.revision, 1)
        chat = self.create_chat()
        transcript = chat.entries
        project = self.projects.create_project(
            title="Atomic",
            objective="Create and associate",
            conversation_id=chat.metadata.identifier,
            expected_conversation_revision=chat.metadata.revision,
        )
        self.assertIn("Current focus\nNot yet recorded.", project.continuity_brief)
        revised = self.chats.get_chat(chat.metadata.identifier)
        self.assertEqual(revised.metadata.project_id, project.identifier)
        self.assertEqual(revised.metadata.revision, chat.metadata.revision + 1)
        self.assertEqual(revised.entries, transcript)

        count = len(self.projects.list_projects())
        with self.assertRaises(ChatServiceError) as caught:
            self.projects.create_project(
                title="Stale",
                objective="Must roll back",
                conversation_id=chat.metadata.identifier,
                expected_conversation_revision=chat.metadata.revision,
            )
        self.assertEqual(caught.exception.code, "stale_revision")
        self.assertEqual(len(self.projects.list_projects()), count)

    def test_content_update_and_explicit_lifecycle_transition(self) -> None:
        project = self.projects.create_project(
            title="Initial", objective="Initial objective"
        )
        updated = self.projects.update_project(
            project.identifier,
            expected_revision=project.revision,
            title="Revised",
            objective="Revised objective",
        )
        self.assertEqual(
            (updated.title, updated.objective, updated.status, updated.revision),
            ("Revised", "Revised objective", "active", 2),
        )
        paused = self.projects.transition_project(
            project.identifier, expected_revision=updated.revision, status="paused"
        )
        completed = self.projects.transition_project(
            project.identifier, expected_revision=paused.revision, status="completed"
        )
        active = self.projects.transition_project(
            project.identifier, expected_revision=completed.revision, status="active"
        )
        self.assertEqual((paused.status, completed.status, active.status), (
            "paused", "completed", "active"
        ))
        with self.assertRaises(ChatServiceError) as stale:
            self.projects.update_project(
                project.identifier, expected_revision=1, title="Too late"
            )
        self.assertEqual(stale.exception.code, "stale_revision")
        with self.assertRaises(ChatServiceError) as invalid:
            self.projects.update_project(
                project.identifier,
                expected_revision=active.revision,
                title="x" * 121,
            )
        self.assertEqual(invalid.exception.code, "invalid_record")

    def test_associate_detach_and_delete_preserve_transcripts(self) -> None:
        first = self.create_chat("First exact question")
        second = self.create_chat("Second exact question")
        originals = {
            first.metadata.identifier: first.entries,
            second.metadata.identifier: second.entries,
        }
        project = self.projects.create_project(
            title="Shared", objective="Support multiple conversations"
        )
        first = self.projects.associate_conversation(
            first.metadata.identifier,
            project.identifier,
            expected_conversation_revision=first.metadata.revision,
        )
        second = self.projects.associate_conversation(
            second.metadata.identifier,
            project.identifier,
            expected_conversation_revision=second.metadata.revision,
        )
        detached = self.projects.detach_conversation(
            first.metadata.identifier,
            expected_conversation_revision=first.metadata.revision,
        )
        self.assertIsNone(detached.metadata.project_id)
        first = self.projects.associate_conversation(
            first.metadata.identifier,
            project.identifier,
            expected_conversation_revision=detached.metadata.revision,
        )
        self.projects.delete_project(
            project.identifier, expected_revision=project.revision
        )
        for chat_id, entries in originals.items():
            persisted = self.chats.get_chat(chat_id)
            self.assertIsNone(persisted.metadata.project_id)
            self.assertEqual(persisted.entries, entries)
        with self.assertRaises(ChatServiceError) as missing:
            self.projects.get_project(project.identifier)
        self.assertEqual(missing.exception.code, "not_found")

    def test_project_use_cases_preserve_memory_extraction_state(self) -> None:
        chat = self.chats.create_chat(
            (
                ArchiveEntry("user", "Exact extraction source"),
                ArchiveEntry(
                    "assistant", "Exact extraction answer", provider="fake", model="model"
                ),
            ),
            provider="fake",
            model="model",
            memory_extraction=MemoryExtractionRequest(
                "extract-" + "c" * 32, 0, 1, "fake", "model", "d" * 64
            ),
        )
        before = self.chats.list_memory_extractions()
        project = self.projects.create_project(
            title="Separated",
            objective="Leave memory-specific state alone",
            conversation_id=chat.metadata.identifier,
            expected_conversation_revision=chat.metadata.revision,
        )
        revised = self.projects.transition_project(
            project.identifier, expected_revision=project.revision, status="paused"
        )
        self.projects.delete_project(
            revised.identifier, expected_revision=revised.revision
        )
        self.assertEqual(self.chats.list_memory_extractions(), before)

    def test_conflicting_transition_preserves_chat_service_error(self) -> None:
        project = self.projects.create_project(title="Status", objective="Stay exact")
        completed = self.projects.transition_project(
            project.identifier, expected_revision=project.revision, status="completed"
        )
        with self.assertRaises(ChatServiceError) as caught:
            self.projects.transition_project(
                project.identifier,
                expected_revision=completed.revision,
                status="paused",
            )
        self.assertEqual(caught.exception.code, "conflict")


class ProjectApplicationArchitectureTests(unittest.TestCase):
    def test_module_has_no_web_or_unrelated_capability_dependency(self) -> None:
        path = Path(__file__).parents[1] / "src" / "tori" / "project_application.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        forbidden = {
            "http", "web", "providers", "memory", "tasks", "scheduled_work",
            "search", "tts", "speech", "actions", "commands", "backups",
        }
        self.assertFalse(
            {
                module
                for module in imported
                if any(
                    module == name
                    or module.startswith(name + ".")
                    or module == "tori." + name
                    or module.startswith("tori." + name + ".")
                    for name in forbidden
                )
            }
        )
