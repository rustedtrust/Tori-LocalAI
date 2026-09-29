from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.checkpoints import (
    CheckpointError,
    CheckpointStore,
    CheckpointVerificationError,
)
from tori.knowledge import KnowledgeRegistry
from tori.management import (
    CHECKPOINT_REMOVE,
    KNOWLEDGE_REMOVE,
    MEMORY_FORGET,
    ConfirmationTarget,
    ManagementError,
    ManagementService,
)
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatMessage


class ManagementServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.checkpoints = CheckpointStore(
            root / "checkpoints",
            clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
            identifier_factory=lambda: "cp-20260730T000000Z-1234abcd",
        )
        self.memory = SQLiteMemoryStore(
            root / "memory.db",
            clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
            identifier_factory=lambda: "mem-" + "1" * 32,
        )
        self.knowledge = KnowledgeRegistry(
            root / "knowledge",
            clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
            identifier_factory=lambda: "ksrc-" + "2" * 32,
            working_directory=root,
        )
        self.service = ManagementService(
            checkpoint_store=self.checkpoints,
            memory_store=self.memory,
            knowledge_registry=self.knowledge,
            provider_name="fake",
            model_name="fake-model",
        )
        self.history = (
            ChatMessage(role="user", content="Question"),
            ChatMessage(role="assistant", content="Answer"),
        )

    def test_empty_lists_are_typed_and_do_not_create_persistence(self) -> None:
        self.assertEqual(self.service.list_checkpoints(), ())
        self.assertEqual(self.service.list_memories(), ())
        listing = self.service.list_knowledge()
        self.assertEqual(listing.sources, ())
        self.assertEqual(listing.invalid_registrations, ())
        self.assertFalse(self.checkpoints.root.exists())
        self.assertFalse(self.knowledge.root.exists())

    def test_checkpoint_save_list_target_and_verified_removal(self) -> None:
        created = self.service.save_checkpoint(
            self.history,
            display_name="Managed checkpoint",
        )
        self.assertEqual(self.service.list_checkpoints(), (created,))
        self.assertFalse(hasattr(created, "messages"))

        target = self.service.checkpoint_removal_target(created.identifier)
        self.assertEqual(target.action, CHECKPOINT_REMOVE)
        self.assertNotIn("Question", repr(target.summary))
        removed = self.service.remove_checkpoint(target)

        self.assertEqual(removed, created)
        self.assertEqual(self.service.list_checkpoints(), ())

    def test_changed_checkpoint_fingerprint_prevents_removal(self) -> None:
        created = self.service.save_checkpoint(
            self.history,
            display_name=None,
        )
        target = self.service.checkpoint_removal_target(created.identifier)
        path = self.checkpoints.root / f"{created.identifier}.json"
        document = path.read_text(encoding="utf-8")
        path.write_text(
            document.replace('"display_name": null', '"display_name": "Changed"'),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ManagementError, "changed"):
            self.service.remove_checkpoint(target)
        self.assertIsNotNone(
            self.checkpoints.load_checkpoint(created.identifier)
        )

    def test_memory_create_update_and_version_bound_forget(self) -> None:
        created = self.service.create_memory("Explicit cedar preference.")
        updated = self.service.update_memory(
            created.identifier,
            "Explicit maple preference.",
            expected_updated_at=created.updated_at,
        )
        self.assertEqual(updated.identifier, created.identifier)
        self.assertEqual(updated.created_at, created.created_at)

        with self.assertRaisesRegex(ManagementError, "changed"):
            self.service.update_memory(
                created.identifier,
                "Stale edit.",
                expected_updated_at=created.updated_at,
            )
        target = self.service.memory_forget_target(
            updated.identifier,
            expected_updated_at=updated.updated_at,
        )
        self.assertEqual(target.action, MEMORY_FORGET)
        self.assertEqual(target.fingerprint, updated.updated_at)
        self.assertEqual(target.summary["text"], updated.text)
        self.assertEqual(self.service.forget_memory(target), updated)
        self.assertEqual(self.service.list_memories(), ())

    def test_memory_policy_error_has_stable_code_and_does_not_echo_value(
        self,
    ) -> None:
        protected = "password: synthetic-do-not-store-value"
        with self.assertRaises(ManagementError) as caught:
            self.service.create_memory(protected)
        self.assertEqual(caught.exception.code, "policy_rejection")
        self.assertNotIn("synthetic-do-not-store-value", str(caught.exception))

    def test_knowledge_safe_listing_and_registration_only_removal(self) -> None:
        source_path = Path(self.temporary.name) / "source notes.md"
        source_path.write_text("Local source text.", encoding="utf-8")
        before = hashlib.sha256(source_path.read_bytes()).hexdigest()

        created = self.service.register_knowledge(str(source_path))
        self.assertEqual(created.display_path, str(source_path))
        self.assertFalse(hasattr(created, "path"))
        self.assertEqual(self.service.list_knowledge().sources, (created,))
        target = self.service.knowledge_removal_target(created.identifier)
        self.assertEqual(target.action, KNOWLEDGE_REMOVE)
        self.assertTrue(target.summary["source_unchanged"])
        removed = self.service.remove_knowledge(target)

        self.assertEqual(removed.identifier, created.identifier)
        self.assertEqual(self.service.list_knowledge().sources, ())
        self.assertEqual(
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
            before,
        )

    def test_changed_knowledge_fingerprint_prevents_removal(self) -> None:
        source_path = Path(self.temporary.name) / "changed.txt"
        source_path.write_text("Current source.", encoding="utf-8")
        created = self.service.register_knowledge(str(source_path))
        target = self.service.knowledge_removal_target(created.identifier)
        record_path = self.knowledge.root / f"{created.identifier}.json"
        document = record_path.read_text(encoding="utf-8")
        record_path.write_text(
            document.replace(
                '"registered_at": "2026-07-30T00:00:00Z"',
                '"registered_at": "2026-07-30T00:00:01Z"',
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ManagementError, "changed"):
            self.service.remove_knowledge(target)
        self.assertIsNotNone(self.knowledge.get(created.identifier))

    def test_wrong_action_target_is_rejected_without_mutation(self) -> None:
        memory = self.service.create_memory("Target binding marker.")
        wrong = ConfirmationTarget(
            action=KNOWLEDGE_REMOVE,
            identifier=memory.identifier,
            fingerprint=memory.updated_at,
            summary={},
        )
        with self.assertRaisesRegex(ManagementError, "cannot be used"):
            self.service.forget_memory(wrong)
        self.assertEqual(self.service.list_memories(), (memory,))

    def test_unavailable_optional_store_has_stable_safe_error(self) -> None:
        service = ManagementService(
            checkpoint_store=self.checkpoints,
            memory_store=None,
            knowledge_registry=None,
            provider_name="fake",
            model_name="fake",
        )
        with self.assertRaises(ManagementError) as memory_error:
            service.list_memories()
        with self.assertRaises(ManagementError) as knowledge_error:
            service.list_knowledge()
        self.assertEqual(memory_error.exception.code, "store_unavailable")
        self.assertEqual(knowledge_error.exception.code, "store_unavailable")

    def test_checkpoint_caller_errors_and_missing_target_are_safe(self) -> None:
        with self.assertRaises(ManagementError) as invalid_identifier:
            self.service.checkpoint_removal_target("../../private")
        self.assertEqual(invalid_identifier.exception.code, "invalid_field")
        self.assertNotIn("private", str(invalid_identifier.exception))

        with self.assertRaises(ManagementError) as invalid_name:
            self.service.save_checkpoint(
                self.history,
                display_name="x" * 81,
            )
        self.assertEqual(invalid_name.exception.code, "invalid_field")
        self.assertEqual(
            str(invalid_name.exception),
            "Checkpoint display_name cannot exceed 80 characters.",
        )

        with self.assertRaises(ManagementError) as missing:
            self.service.checkpoint_removal_target(
                "cp-20260730T000000Z-deadbeef"
            )
        self.assertEqual(missing.exception.code, "not_found")
        self.assertEqual(
            str(missing.exception),
            "The selected checkpoint was not found.",
        )

    def test_checkpoint_persisted_format_failures_are_safe(self) -> None:
        self.checkpoints.root.mkdir(parents=True)
        identifier = "cp-20260730T000000Z-1234abcd"
        path = self.checkpoints.root / f"{identifier}.json"
        path.write_text("{malformed", encoding="utf-8")
        with self.assertRaises(ManagementError) as malformed:
            self.service.list_checkpoints()
        self.assertEqual(malformed.exception.code, "store_corrupt")
        self.assertEqual(
            str(malformed.exception),
            "Checkpoint storage contains an invalid checkpoint record.",
        )

        path.write_text(
            json.dumps(
                {
                    "schema_version": 99,
                    "identifier": identifier,
                    "display_name": None,
                    "created_at": "2026-07-30T00:00:00Z",
                    "provider": "fake",
                    "model": "fake-model",
                    "message_count": 2,
                    "messages": [
                        {"role": "user", "content": "Question"},
                        {"role": "assistant", "content": "Answer"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ManagementError) as unsupported:
            self.service.list_checkpoints()
        self.assertEqual(unsupported.exception.code, "store_corrupt")
        self.assertEqual(
            str(unsupported.exception),
            "Checkpoint storage contains an unsupported checkpoint record.",
        )

    def test_checkpoint_storage_diagnostics_are_never_forwarded(self) -> None:
        private_detail = (
            "synthetic errno for /private/checkpoints/user-conversation.json"
        )
        with patch.object(
            self.checkpoints,
            "save_checkpoint",
            side_effect=CheckpointError(private_detail),
        ):
            with self.assertRaises(ManagementError) as unavailable:
                self.service.save_checkpoint(
                    self.history,
                    display_name=None,
                )
        self.assertEqual(unavailable.exception.code, "store_unavailable")
        self.assertEqual(
            str(unavailable.exception),
            "Checkpoint storage is unavailable.",
        )
        self.assertNotIn("/private", str(unavailable.exception))
        self.assertNotIn("errno", str(unavailable.exception))

    def test_checkpoint_unavailable_directory_is_safe(self) -> None:
        blocked_parent = Path(self.temporary.name) / "private-storage"
        blocked_parent.write_text("not a directory", encoding="utf-8")
        service = ManagementService(
            checkpoint_store=CheckpointStore(blocked_parent / "checkpoints"),
            memory_store=self.memory,
            knowledge_registry=self.knowledge,
            provider_name="fake",
            model_name="fake-model",
        )

        with self.assertRaises(ManagementError) as unavailable:
            service.save_checkpoint(self.history, display_name=None)
        self.assertEqual(unavailable.exception.code, "store_unavailable")
        self.assertEqual(
            str(unavailable.exception),
            "Checkpoint storage is unavailable.",
        )
        self.assertNotIn(str(blocked_parent), str(unavailable.exception))

    def test_checkpoint_verification_failures_are_safe(self) -> None:
        private_detail = "verification failed at /private/checkpoints"
        for method_name, call in (
            (
                "save_checkpoint",
                lambda: self.service.save_checkpoint(
                    self.history,
                    display_name=None,
                ),
            ),
            (
                "remove_checkpoint",
                lambda: self.service.remove_checkpoint(
                    ConfirmationTarget(
                        action=CHECKPOINT_REMOVE,
                        identifier="cp-20260730T000000Z-1234abcd",
                        fingerprint="fingerprint",
                        summary={},
                    )
                ),
            ),
        ):
            with self.subTest(method=method_name):
                with patch.object(
                    self.checkpoints,
                    method_name,
                    side_effect=CheckpointVerificationError(private_detail),
                ):
                    if method_name == "remove_checkpoint":
                        with patch.object(
                            self.checkpoints,
                            "load_checkpoint",
                            side_effect=CheckpointVerificationError(
                                private_detail
                            ),
                        ):
                            with self.assertRaises(ManagementError) as caught:
                                call()
                    else:
                        with self.assertRaises(ManagementError) as caught:
                            call()
                self.assertEqual(
                    caught.exception.code,
                    "verification_failed",
                )
                self.assertEqual(
                    str(caught.exception),
                    "The checkpoint change could not be verified.",
                )
                self.assertNotIn("/private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
