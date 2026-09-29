from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError, completed_model_history
from tori.conversation_archive import (
    ArchiveCorruptError,
    ArchiveEntry,
    ArchiveVersionError,
    ConversationArchiveStore,
    _SCHEMA3_ENTRIES_SQL,
    _EVENT_INDEX_SQL,
    _LEGACY_CHATS_SQL,
    _METADATA_SQL,
    _STATE_SQL,
)
from tori.conversation_archive_migration import ArchiveMigrationError, migrate_archive_schema
from tori.conversation_archive_schema4_migration import migrate_archive_schema3_to4
from tori.conversation_archive_schema5_migration import migrate_archive_schema4_to5
from tori.conversation_archive_schema6_migration import migrate_archive_schema5_to6
from tori.conversation_archive_schema7_migration import migrate_archive_schema6_to7


CHAT_ID = "chat-" + "a" * 32


def legacy_archive(path: Path) -> None:
    connection = sqlite3.connect(path)
    for sql in (
        _METADATA_SQL, _LEGACY_CHATS_SQL, _SCHEMA3_ENTRIES_SQL,
        _EVENT_INDEX_SQL, _STATE_SQL,
    ):
        connection.execute(sql)
    connection.execute("INSERT INTO archive_metadata VALUES ('schema_version','2')")
    connection.execute(
        "INSERT INTO chats VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (CHAT_ID, "Private label", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", 7, "old", "model", "new", "model2", 3, 1),
    )
    connection.executemany(
        "INSERT INTO transcript_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (CHAT_ID, 0, "user", "private historical question", None, None, None, "2026-01-01T00:00:00Z", None, None),
            (CHAT_ID, 1, "assistant", "private historical answer", None, "old", "model", "2026-01-01T00:00:00Z", None, None),
            (CHAT_ID, 2, "assistant", "private reminder", None, None, None, "2026-01-01T00:00:00Z", "event-" + "c" * 32, "reminder_due"),
        ],
    )
    connection.execute("INSERT INTO archive_state VALUES (1,?)", (CHAT_ID,))
    connection.commit()
    connection.close()


class ArchiveMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive.db"
        legacy_archive(self.path)

    def test_normal_startup_refuses_schema2_without_mutation(self) -> None:
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArchiveVersionError, "explicit 2-to-3 schema migration"):
            ConversationArchiveStore(self.path).initialize()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_normal_startup_does_not_label_schema1_lookalike_as_migration_ready(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DROP TABLE transcript_entries")
            connection.execute("CREATE TABLE transcript_entries (private_value TEXT)")
            connection.commit()
        finally:
            connection.close()
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ArchiveCorruptError):
            ConversationArchiveStore(self.path).initialize()
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_exact_migration_preserves_history_and_adds_nullable_unique_event(self) -> None:
        self.assertEqual(migrate_archive_schema(self.path), (1, 3))
        self.assertEqual(migrate_archive_schema3_to4(self.path), (1, 3))
        self.assertEqual(migrate_archive_schema4_to5(self.path), (1, 3))
        self.assertEqual(migrate_archive_schema5_to6(self.path), (1, 3, 0))
        self.assertEqual(migrate_archive_schema6_to7(self.path), (0, 1, 3, 0))
        service = ChatService(ConversationArchiveStore(self.path))
        detail = service.get_chat(CHAT_ID)
        self.assertEqual(detail.metadata.revision, 7)
        self.assertEqual(detail.metadata.completed_turn_count, 1)
        self.assertEqual([item.text for item in detail.entries], ["private historical question", "private historical answer", "private reminder"])
        self.assertEqual(detail.entries[-1].application_event_type, "reminder_due")
        self.assertEqual(detail.metadata.selected_provider_name, "new")
        self.assertEqual(detail.metadata.selected_model_name, "model2")
        history = completed_model_history(detail.entries)
        appended = service.append_application_event(
            CHAT_ID,
            expected_revision=7,
            event_id="event-" + "b" * 32,
            event_type="reminder_due",
            text="Reminder: private marker",
        )
        self.assertEqual(appended.metadata.completed_turn_count, 1)
        self.assertEqual(completed_model_history(appended.entries), history)
        self.assertEqual(
            service.append_application_event(
                CHAT_ID,
                expected_revision=7,
                event_id="event-" + "b" * 32,
                event_type="reminder_due",
                text="Reminder: private marker",
            ),
            appended,
        )
        with self.assertRaisesRegex(ChatServiceError, "conflicts"):
            service.append_application_event(
                CHAT_ID,
                expected_revision=8,
                event_id="event-" + "b" * 32,
                event_type="reminder_due",
                text="different",
            )

    def test_failure_rolls_back_repeated_refuses_and_output_has_no_transcript(self) -> None:
        with self.assertRaises(RuntimeError):
            migrate_archive_schema(
                self.path,
                stage_hook=lambda stage: (_ for _ in ()).throw(RuntimeError("stop")) if stage == "copied_values" else None,
            )
        connection = sqlite3.connect(self.path)
        try:
            self.assertEqual(connection.execute("SELECT value FROM archive_metadata").fetchone()[0], "2")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transcript_entries").fetchone()[0], 3)
        finally:
            connection.close()
        migrate_archive_schema(self.path)
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(self.path)

    def test_post_commit_verification_boundary_stops_without_reversal(self) -> None:
        with self.assertRaisesRegex(ArchiveMigrationError, "after commit"):
            migrate_archive_schema(
                self.path,
                stage_hook=lambda stage: (_ for _ in ()).throw(RuntimeError("lost"))
                if stage == "committed"
                else None,
            )
        migrate_archive_schema3_to4(self.path)
        migrate_archive_schema4_to5(self.path)
        migrate_archive_schema5_to6(self.path)
        migrate_archive_schema6_to7(self.path)
        detail = ChatService(ConversationArchiveStore(self.path)).get_chat(CHAT_ID)
        self.assertEqual(detail.metadata.selected_model.model, "model2")
        self.assertEqual(len(detail.entries), 3)

    def test_symlink_sidecar_and_unknown_schema_are_untouched(self) -> None:
        link = Path(self.temporary.name) / "link.db"
        link.symlink_to(self.path)
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(link)
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"ambiguous")
        before = self.path.read_bytes()
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sidecar.read_bytes(), b"ambiguous")

    def test_symlink_ancestor_corrupt_database_and_unsafe_type_are_rejected(self) -> None:
        real_parent = Path(self.temporary.name) / "real"
        real_parent.mkdir()
        ancestor_link = Path(self.temporary.name) / "linked"
        ancestor_link.symlink_to(real_parent, target_is_directory=True)
        linked_archive = ancestor_link / "archive.db"
        legacy_archive(real_parent / "archive.db")
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(linked_archive)

        corrupt = Path(self.temporary.name) / "corrupt.db"
        corrupt.write_bytes(b"not sqlite")
        corrupt_before = corrupt.read_bytes()
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(corrupt)
        self.assertEqual(corrupt.read_bytes(), corrupt_before)

        fifo = Path(self.temporary.name) / "archive.fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema(fifo)

    def test_cli_requires_exact_path_and_reports_counts_without_content(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts" / "migrate-conversation-archive-schema"
        migrate_archive_schema(self.path)
        migrate_archive_schema3_to4(self.path)
        migrate_archive_schema4_to5(self.path)
        migrate_archive_schema5_to6(self.path)
        result = subprocess.run(
            [sys.executable, str(script), str(self.path)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(
            "schema 6 -> 7; projects=0; chats=1; transcript_entries=3; "
            "memory_extractions=0; structured_project_rows=0",
            result.stdout,
        )
        self.assertNotIn("private historical", result.stdout + result.stderr)
        missing = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertNotIn("runtime/conversations", missing.stdout + missing.stderr)


if __name__ == "__main__":
    unittest.main()
