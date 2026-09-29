from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.checkpoints import CheckpointStore
from tori.knowledge import KnowledgeRegistry
from tori.management import (
    CHECKPOINT_REMOVE,
    KNOWLEDGE_REMOVE,
    MEMORY_FORGET,
    ManagementError,
    ManagementService,
)
from tori.management_removal import (
    SUPPORTED_REMOVAL_ACTIONS,
    ManagementRemovalError,
    ManagementRemovalWorkflow,
)
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatMessage


class ManagementRemovalWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        self.clock_value = 100.0
        self.token_number = 0
        self.checkpoints = CheckpointStore(
            self.root / "checkpoints",
            clock=lambda: self.now,
            identifier_factory=lambda: "cp-20260821T000000Z-1234abcd",
        )
        self.memory = SQLiteMemoryStore(
            self.root / "memory" / "tori.db",
            clock=lambda: self.now,
            identifier_factory=lambda: "mem-" + "1" * 32,
        )
        self.knowledge = KnowledgeRegistry(
            self.root / "knowledge",
            clock=lambda: self.now,
            identifier_factory=lambda: "ksrc-" + "2" * 32,
            working_directory=self.root,
        )
        self.management = ManagementService(
            checkpoint_store=self.checkpoints,
            memory_store=self.memory,
            knowledge_registry=self.knowledge,
            provider_name="fake",
            model_name="fake-model",
        )
        self.workflow = ManagementRemovalWorkflow(
            self.management,
            clock=lambda: self.clock_value,
            token_factory=self.next_token,
        )

    def next_token(self) -> str:
        self.token_number += 1
        return f"removal-token-{self.token_number}"

    def create_checkpoint(self):  # type: ignore[no-untyped-def]
        return self.management.save_checkpoint(
            (
                ChatMessage("user", "Preserved checkpoint question."),
                ChatMessage("assistant", "Preserved checkpoint answer."),
            ),
            display_name="Recovery checkpoint",
        )

    def create_memory(self):  # type: ignore[no-untyped-def]
        return self.management.create_memory("Preserved curated memory.")

    def create_knowledge(self):  # type: ignore[no-untyped-def]
        source = self.root / "source.md"
        source.write_bytes(b"Preserved source bytes.\n")
        return source, self.management.register_knowledge(str(source))

    def test_explicit_proposals_preserve_target_action_and_origin(self) -> None:
        checkpoint = self.create_checkpoint()
        memory = self.create_memory()
        _source, knowledge = self.create_knowledge()

        proposals = (
            self.workflow.propose_checkpoint(checkpoint.identifier),
            self.workflow.propose_memory(
                memory.identifier,
                expected_updated_at=memory.updated_at,
                origin="conversation_command",
            ),
            self.workflow.propose_knowledge(knowledge.identifier),
        )

        self.assertEqual(
            tuple(proposal.action for proposal in proposals),
            (CHECKPOINT_REMOVE, MEMORY_FORGET, KNOWLEDGE_REMOVE),
        )
        self.assertEqual(
            tuple(proposal.target.action for proposal in proposals),
            (CHECKPOINT_REMOVE, MEMORY_FORGET, KNOWLEDGE_REMOVE),
        )
        self.assertEqual(proposals[1].origin, "conversation_command")
        self.assertEqual(self.workflow.proposal(proposals[0].token), proposals[0])

    def test_confirmed_removals_delegate_and_preserve_unrelated_domains(self) -> None:
        checkpoint = self.create_checkpoint()
        memory = self.create_memory()
        source, knowledge = self.create_knowledge()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

        checkpoint_outcome = self.workflow.decide(
            self.workflow.propose_checkpoint(checkpoint.identifier).token,
            "confirm",
        )
        self.assertEqual(checkpoint_outcome.removed, checkpoint)
        self.assertEqual(self.memory.list_memories()[0].identifier, memory.identifier)
        self.assertIsNotNone(self.knowledge.get(knowledge.identifier))

        memory_outcome = self.workflow.decide(
            self.workflow.propose_memory(memory.identifier).token,
            "confirm",
        )
        self.assertEqual(memory_outcome.removed, memory)
        self.assertIsNotNone(self.knowledge.get(knowledge.identifier))

        knowledge_outcome = self.workflow.decide(
            self.workflow.propose_knowledge(knowledge.identifier).token,
            "confirm",
        )
        self.assertEqual(knowledge_outcome.removed.identifier, knowledge.identifier)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)

    def test_cancel_is_one_use_and_mutation_free(self) -> None:
        memory = self.create_memory()
        proposal = self.workflow.propose_memory(memory.identifier)

        outcome = self.workflow.decide(proposal.token, "cancel")

        self.assertTrue(outcome.cancelled)
        self.assertIsNone(outcome.removed)
        self.assertIsNotNone(self.memory.get(memory.identifier))
        with self.assertRaisesRegex(ManagementRemovalError, "already been used"):
            self.workflow.decide(proposal.token, "confirm")

    def test_expired_proposal_is_consumed_without_mutation(self) -> None:
        checkpoint = self.create_checkpoint()
        proposal = self.workflow.propose_checkpoint(checkpoint.identifier)
        self.clock_value = proposal.expires_at + 0.01

        with self.assertRaises(ManagementRemovalError) as expired:
            self.workflow.decide(proposal.token, "confirm")

        self.assertEqual(expired.exception.code, "expired_confirmation")
        self.assertTrue(
            (self.checkpoints.root / f"{checkpoint.identifier}.json").exists()
        )
        with self.assertRaises(ManagementRemovalError) as reused:
            self.workflow.decide(proposal.token, "confirm")
        self.assertEqual(reused.exception.code, "unknown_confirmation")

    def test_unknown_token_is_rejected(self) -> None:
        with self.assertRaises(ManagementRemovalError) as unknown:
            self.workflow.decide("not-issued", "confirm")
        self.assertEqual(unknown.exception.code, "unknown_confirmation")

    def test_unsupported_decision_does_not_consume_valid_token(self) -> None:
        memory = self.create_memory()
        proposal = self.workflow.propose_memory(memory.identifier)

        with self.assertRaises(ManagementRemovalError) as invalid:
            self.workflow.decide(proposal.token, "approve")

        self.assertEqual(invalid.exception.code, "invalid_decision")
        self.assertEqual(self.workflow.proposal(proposal.token), proposal)
        self.assertTrue(self.workflow.decide(proposal.token, "cancel").cancelled)

    def test_clear_invalidates_all_proposals_without_mutation(self) -> None:
        checkpoint = self.create_checkpoint()
        memory = self.create_memory()
        proposals = (
            self.workflow.propose_checkpoint(checkpoint.identifier),
            self.workflow.propose_memory(memory.identifier),
        )

        self.workflow.clear()

        for proposal in proposals:
            self.assertIsNone(self.workflow.proposal(proposal.token))
        self.assertIsNotNone(self.memory.get(memory.identifier))
        self.assertTrue(
            (self.checkpoints.root / f"{checkpoint.identifier}.json").exists()
        )

    def test_changed_checkpoint_fails_closed_and_consumes_token(self) -> None:
        checkpoint = self.create_checkpoint()
        proposal = self.workflow.propose_checkpoint(checkpoint.identifier)
        path = self.checkpoints.root / f"{checkpoint.identifier}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["messages"][0]["content"] = "Changed after proposal."
        path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaises(ManagementError) as stale:
            self.workflow.decide(proposal.token, "confirm")

        self.assertEqual(stale.exception.code, "stale_target")
        self.assertTrue(path.exists())
        self.assertIsNone(self.workflow.proposal(proposal.token))

    def test_changed_memory_fails_closed_and_consumes_token(self) -> None:
        memory = self.create_memory()
        proposal = self.workflow.propose_memory(memory.identifier)
        self.now = datetime(2026, 8, 21, 0, 0, 1, tzinfo=timezone.utc)
        updated = self.management.update_memory(
            memory.identifier,
            "Changed after proposal.",
            expected_updated_at=memory.updated_at,
        )

        with self.assertRaises(ManagementError) as stale:
            self.workflow.decide(proposal.token, "confirm")

        self.assertEqual(stale.exception.code, "stale_target")
        self.assertEqual(self.memory.get(memory.identifier).text, updated.text)
        self.assertIsNone(self.workflow.proposal(proposal.token))

    def test_changed_knowledge_fails_closed_without_changing_source(self) -> None:
        source, knowledge = self.create_knowledge()
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        proposal = self.workflow.propose_knowledge(knowledge.identifier)
        record_path = self.knowledge.root / f"{knowledge.identifier}.json"
        document = json.loads(record_path.read_text(encoding="utf-8"))
        document["registered_at"] = "2026-08-21T00:00:01Z"
        record_path.write_text(json.dumps(document), encoding="utf-8")

        with self.assertRaises(ManagementError) as stale:
            self.workflow.decide(proposal.token, "confirm")

        self.assertEqual(stale.exception.code, "stale_target")
        self.assertIsNotNone(self.knowledge.get(knowledge.identifier))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
        self.assertIsNone(self.workflow.proposal(proposal.token))

    def test_supported_actions_are_exactly_the_bounded_removal_set(self) -> None:
        self.assertEqual(
            SUPPORTED_REMOVAL_ACTIONS,
            (CHECKPOINT_REMOVE, MEMORY_FORGET, KNOWLEDGE_REMOVE),
        )

    def test_module_has_no_web_or_cross_domain_dependencies(self) -> None:
        module_path = (
            Path(__file__).parents[1] / "src" / "tori" / "management_removal.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            (
                f"tori.{node.module}"
                if node.level and node.module
                else node.module or ""
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = {
            "http",
            "tori.web",
            "tori.providers",
            "tori.project_application",
            "tori.actions",
            "tori.commands",
            "tori.scheduled_work",
            "tori.memory_extraction",
            "tori.tasks",
            "tori.search",
            "tori.tts",
        }
        self.assertTrue(imported.isdisjoint(forbidden), imported & forbidden)


if __name__ == "__main__":
    unittest.main()
