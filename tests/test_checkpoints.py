from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tori.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointError,
    CheckpointFormatError,
    CheckpointNotFoundError,
    CheckpointStore,
    CheckpointVerificationError,
    CheckpointVersionError,
)
from tori.providers import ChatMessage


TEST_IDENTIFIER = "cp-20260725T064810Z-a1b2c3d4"
SECOND_IDENTIFIER = "cp-20260725T064811Z-b2c3d4e5"
TEST_TIME = datetime(2026, 7, 25, 6, 48, 10, tzinfo=timezone.utc)


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "checkpoints"
        self.messages = (
            ChatMessage(role="user", content="Remember the word cobalt."),
            ChatMessage(role="assistant", content="I will remember it here."),
            ChatMessage(role="user", content="What was the word?"),
            ChatMessage(role="assistant", content="The word was cobalt."),
        )

    def make_store(
        self,
        identifier: str = TEST_IDENTIFIER,
    ) -> CheckpointStore:
        return CheckpointStore(
            self.root,
            clock=lambda: TEST_TIME,
            identifier_factory=lambda: identifier,
        )

    def test_explicit_save_creates_one_versioned_checkpoint(self) -> None:
        metadata = self.make_store().save_checkpoint(
            self.messages,
            display_name="Cobalt conversation",
            provider="ollama",
            model="gemma4:12b",
        )

        files = tuple(self.root.glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(metadata.identifier, TEST_IDENTIFIER)
        self.assertEqual(metadata.display_name, "Cobalt conversation")
        self.assertEqual(metadata.message_count, 4)

        document = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(
            document["schema_version"],
            CHECKPOINT_SCHEMA_VERSION,
        )
        self.assertEqual(document["identifier"], TEST_IDENTIFIER)
        self.assertEqual(
            [message["role"] for message in document["messages"]],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(
            [message["content"] for message in document["messages"]],
            [message.content for message in self.messages],
        )

    def test_save_freshly_reloads_and_reports_verification_failure(self) -> None:
        store = self.make_store()
        with patch.object(
            store,
            "_load_path",
            return_value=SimpleNamespace(metadata=None, messages=()),
        ):
            with self.assertRaisesRegex(
                CheckpointVerificationError,
                "could not be verified",
            ):
                store.save_checkpoint(
                    self.messages,
                    display_name="Verification",
                    provider="ollama",
                    model="test-model",
                )

        self.assertTrue(
            (self.root / f"{TEST_IDENTIFIER}.json").exists()
        )

    def test_save_rejects_incomplete_exchanges(self) -> None:
        store = self.make_store()

        with self.assertRaisesRegex(
            CheckpointFormatError,
            "complete user/assistant exchanges",
        ):
            store.save_checkpoint(
                (ChatMessage(role="user", content="Incomplete"),),
                display_name=None,
                provider="ollama",
                model="test-model",
            )

        self.assertFalse(self.root.exists())

    def test_listing_returns_metadata_without_transcript(self) -> None:
        store = self.make_store()
        store.save_checkpoint(
            self.messages,
            display_name="Private conversation",
            provider="ollama",
            model="gemma4:12b",
        )

        listed = store.list_checkpoints()

        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0].identifier, TEST_IDENTIFIER)
        self.assertEqual(listed[0].display_name, "Private conversation")
        self.assertEqual(listed[0].message_count, 4)
        self.assertFalse(hasattr(listed[0], "messages"))
        self.assertNotIn("cobalt", repr(listed[0]).lower())

    def test_load_restores_ordered_provider_neutral_messages(self) -> None:
        store = self.make_store()
        store.save_checkpoint(
            self.messages,
            display_name=None,
            provider="ollama",
            model="gemma4:12b",
        )

        loaded = store.load_checkpoint(TEST_IDENTIFIER)

        self.assertEqual(loaded.messages, self.messages)
        self.assertEqual(loaded.metadata.provider, "ollama")
        self.assertEqual(loaded.metadata.model, "gemma4:12b")

    def test_missing_checkpoint_fails_clearly(self) -> None:
        with self.assertRaisesRegex(
            CheckpointNotFoundError,
            "was not found",
        ):
            self.make_store().load_checkpoint(TEST_IDENTIFIER)

    def test_malformed_json_fails_clearly(self) -> None:
        self.root.mkdir(parents=True)
        path = self.root / f"{TEST_IDENTIFIER}.json"
        path.write_text("{not valid json", encoding="utf-8")

        with self.assertRaisesRegex(
            CheckpointFormatError,
            "not valid JSON",
        ):
            self.make_store().load_checkpoint(TEST_IDENTIFIER)

    def test_unsupported_schema_version_fails_clearly(self) -> None:
        document = self.valid_document()
        document["schema_version"] = 99
        self.write_document(document)

        with self.assertRaisesRegex(
            CheckpointVersionError,
            "unsupported schema version 99",
        ):
            self.make_store().load_checkpoint(TEST_IDENTIFIER)

    def test_invalid_role_is_rejected(self) -> None:
        document = self.valid_document()
        document["messages"][1]["role"] = "system"
        self.write_document(document)

        with self.assertRaisesRegex(
            CheckpointFormatError,
            "invalid role",
        ):
            self.make_store().load_checkpoint(TEST_IDENTIFIER)

    def test_invalid_message_shape_is_rejected(self) -> None:
        document = self.valid_document()
        document["messages"][0]["extra"] = "unexpected"
        self.write_document(document)

        with self.assertRaisesRegex(
            CheckpointFormatError,
            "message fields are invalid",
        ):
            self.make_store().load_checkpoint(TEST_IDENTIFIER)

    def test_path_traversal_identifier_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            CheckpointFormatError,
            "Checkpoint identifiers must use the form",
        ):
            self.make_store().load_checkpoint("../../outside")

        self.assertFalse(
            (Path(self.temporary_directory.name) / "outside.json").exists()
        )

    def test_remove_deletes_only_selected_checkpoint(self) -> None:
        first_store = self.make_store(TEST_IDENTIFIER)
        second_store = self.make_store(SECOND_IDENTIFIER)

        first_store.save_checkpoint(
            self.messages,
            display_name="First",
            provider="ollama",
            model="test-model",
        )
        second_store.save_checkpoint(
            self.messages,
            display_name="Second",
            provider="ollama",
            model="test-model",
        )

        removed = first_store.remove_checkpoint(TEST_IDENTIFIER)

        self.assertEqual(removed.identifier, TEST_IDENTIFIER)
        self.assertFalse(
            (self.root / f"{TEST_IDENTIFIER}.json").exists()
        )
        self.assertTrue(
            (self.root / f"{SECOND_IDENTIFIER}.json").exists()
        )

    def test_removal_reports_failed_fresh_absence_verification(self) -> None:
        store = self.make_store()
        store.save_checkpoint(
            self.messages,
            display_name=None,
            provider="ollama",
            model="test-model",
        )
        checkpoint = store.load_checkpoint(TEST_IDENTIFIER)

        with patch.object(
            store,
            "_load_path",
            side_effect=(checkpoint, checkpoint),
        ):
            with self.assertRaisesRegex(
                CheckpointVerificationError,
                "could not be verified",
            ):
                store.remove_checkpoint(TEST_IDENTIFIER)

    def test_failed_atomic_write_does_not_damage_valid_checkpoint(self) -> None:
        valid_store = self.make_store(TEST_IDENTIFIER)
        valid_store.save_checkpoint(
            self.messages,
            display_name="Valid",
            provider="ollama",
            model="test-model",
        )

        failing_store = self.make_store(SECOND_IDENTIFIER)
        with patch(
            "tori.checkpoints.os.replace",
            side_effect=OSError("simulated interruption"),
        ):
            with self.assertRaisesRegex(
                CheckpointError,
                "Could not save checkpoint",
            ):
                failing_store.save_checkpoint(
                    self.messages,
                    display_name="Interrupted",
                    provider="ollama",
                    model="test-model",
                )

        loaded = valid_store.load_checkpoint(TEST_IDENTIFIER)
        self.assertEqual(loaded.messages, self.messages)
        self.assertFalse(
            (self.root / f"{SECOND_IDENTIFIER}.json").exists()
        )
        self.assertFalse(
            any(path.suffix == ".tmp" for path in self.root.iterdir())
        )

    def valid_document(self) -> dict[str, object]:
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "identifier": TEST_IDENTIFIER,
            "display_name": "Test checkpoint",
            "created_at": "2026-07-25T06:48:10Z",
            "provider": "ollama",
            "model": "gemma4:12b",
            "message_count": 4,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in self.messages
            ],
        }

    def write_document(self, document: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{TEST_IDENTIFIER}.json"
        path.write_text(
            json.dumps(document, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
