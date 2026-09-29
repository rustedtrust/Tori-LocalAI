"""Web/Conversation integration tests for Capability Growth V1."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import socket
import unittest

from tori.capability_growth import CapabilityEvidence, SQLiteImprovementJournal
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatResponse, ModelDescriptor, ModelProvider
from tori.skills_sh import SkillsShDiscoveryResult
from tori.web import WebApplication, WebApplicationError



class _Provider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[tuple[object, ...]] = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("test answer", "fake")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        yield "test answer"

    def list_models(self):  # type: ignore[no-untyped-def]
        return (ModelDescriptor("fake", "fake", "Fake"),)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


class _EmptyDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: object, *, limit: object, origin: object) -> SkillsShDiscoveryResult:
        assert isinstance(query, str)
        assert isinstance(limit, int)
        self.calls.append((query, limit))
        return SkillsShDiscoveryResult(
            "skills.sh", query, "2026-09-07T12:00:00Z", "search", ()
        )


class CapabilityGrowthWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.provider = _Provider()
        self.discovery = _EmptyDiscovery()
        self.journal = SQLiteImprovementJournal(
            root / "capability-growth/improvement_journal.sqlite3",
            clock=lambda: datetime(2026, 9, 7, 12, tzinfo=UTC),
        )
        self.application = WebApplication(
            self.provider,
            port=_free_port(),
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.sqlite3"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake",
            model_name="fake",
            chat_service=ChatService(ConversationArchiveStore(root / "conversations.sqlite3")),
            skills_sh_discovery=self.discovery,  # type: ignore[arg-type]
            improvement_journal=self.journal,
        )

    def test_conversation_runs_explicit_review_without_model_or_confirmation(self) -> None:
        status, response = self.application.submit("Run a Skills Review.")
        self.assertEqual(status, 200)
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(len(self.discovery.calls), 3)
        answer = response["transcript"][-1]["text"]
        self.assertIn("FIX, IMPROVE, and EXPAND", answer)
        self.assertIn("Nothing was installed, enabled, granted, or executed", answer)
        self.assertNotIn("confirmation", response)
        state = self.application.capability_growth_state()
        self.assertEqual(state["reviews"][0]["status"], "completed")

    def test_user_directed_review_and_ambiguous_this_are_distinct(self) -> None:
        status, response = self.application.submit("Is there a Skill for this?")
        self.assertEqual(status, 200)
        self.assertEqual(self.discovery.calls, [])
        self.assertIn("specific capability", response["transcript"][-1]["text"])
        status, _ = self.application.submit("Find a Skill for Excel files.")
        self.assertEqual(status, 200)
        self.assertEqual(self.discovery.calls[-1], ("Excel files", 3))

    def test_novel_directed_discord_search_reaches_skills_review_service(self) -> None:
        status, response = self.application.submit(
            "Find a Skill that could help you work with Discord."
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.discovery.calls, [("Discord", 3)])
        self.assertIn("Skills Review completed", response["transcript"][-1]["text"])
        state = self.application.capability_growth_state()
        self.assertEqual(state["reviews"][0]["scope"], "user_directed")
        self.assertEqual(state["reviews"][0]["capability_area"], "communication")

    def test_management_review_and_revision_safe_lifecycle(self) -> None:
        finding = self.journal.record(CapabilityEvidence(
            capability_area="documents",
            capability_id="pdf.extract",
            operation_id="extract",
            outcome="friction",
            component_id="builtin.pdf",
            component_version="1.0",
        ))[0]
        status, result = self.application.run_skills_review_for_management("general", "")
        self.assertEqual(status, 200)
        self.assertTrue(result["state"]["available"])
        status, changed = self.application.update_capability_growth_lifecycle({
            "kind": "finding",
            "identifier": finding.identifier,
            "status": "monitoring",
            "expected_revision": finding.revision,
        })
        self.assertEqual(status, 200)
        self.assertEqual(changed["updated"]["status"], "monitoring")
        with self.assertRaises(WebApplicationError):
            self.application.update_capability_growth_lifecycle({
                "kind": "finding",
                "identifier": finding.identifier,
                "status": "resolved",
                "expected_revision": finding.revision,
            })


if __name__ == "__main__":
    unittest.main()
