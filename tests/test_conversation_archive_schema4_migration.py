from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tori.conversation_archive import (
    ArchiveVersionError,
    ConversationArchiveStore,
    _EVENT_INDEX_SQL,
    _METADATA_SQL,
    _SCHEMA3_CHATS_SQL,
    _SCHEMA3_ENTRIES_SQL,
    _STATE_SQL,
)
from tori.conversation_archive_migration import ArchiveMigrationError
from tori.conversation_archive_schema4_migration import migrate_archive_schema3_to4
from tori.conversation_archive_schema5_migration import migrate_archive_schema4_to5
from tori.conversation_archive_schema6_migration import migrate_archive_schema5_to6
from tori.conversation_archive_schema7_migration import migrate_archive_schema6_to7


CHAT_ID = "chat-" + "a" * 32


def schema3_archive(path: Path) -> None:
    connection = sqlite3.connect(path)
    for sql in (
        _METADATA_SQL, _SCHEMA3_CHATS_SQL, _SCHEMA3_ENTRIES_SQL,
        _EVENT_INDEX_SQL, _STATE_SQL,
    ):
        connection.execute(sql)
    connection.execute("INSERT INTO archive_metadata VALUES ('schema_version','3')")
    connection.execute(
        "INSERT INTO chats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            CHAT_ID, "Private label", "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:05Z", "2026-01-01T00:00:04Z", 7,
            "old", "model", "new", "model2", "selected", "shared", 3, 1,
        ),
    )
    connection.executemany(
        "INSERT INTO transcript_entries VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            (CHAT_ID, 0, "user", "private question", None, None, None, "2026-01-01T00:00:00Z", None, None),
            (CHAT_ID, 1, "assistant", "private answer", None, "old", "model", "2026-01-01T00:00:01Z", None, None),
            (CHAT_ID, 2, "assistant", "private reminder", None, None, None, "2026-01-01T00:00:02Z", "event-" + "b" * 32, "reminder_due"),
        ),
    )
    connection.execute("INSERT INTO archive_state VALUES (1,?)", (CHAT_ID,))
    connection.commit()
    connection.close()


class Schema4MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive.db"
        schema3_archive(self.path)

    def test_normal_startup_refuses_schema3_without_mutation(self) -> None:
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArchiveVersionError, "3-to-4"):
            ConversationArchiveStore(self.path).initialize()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_exact_migration_preserves_schema3_values_and_adds_truthful_defaults(self) -> None:
        with sqlite3.connect(self.path) as connection:
            chats_before = connection.execute("SELECT * FROM chats").fetchall()
            entries_before = connection.execute("SELECT * FROM transcript_entries ORDER BY sequence").fetchall()
            state_before = connection.execute("SELECT * FROM archive_state").fetchall()
        self.assertEqual(migrate_archive_schema3_to4(self.path), (1, 3))
        self.assertEqual(migrate_archive_schema4_to5(self.path), (1, 3))
        self.assertEqual(migrate_archive_schema5_to6(self.path), (1, 3, 0))
        self.assertEqual(migrate_archive_schema6_to7(self.path), (0, 1, 3, 0))
        store = ConversationArchiveStore(self.path)
        detail = store.get_chat(CHAT_ID)
        self.assertEqual(detail.metadata.selected_context_policy, "auto")
        self.assertTrue(all(entry.context is None for entry in detail.entries))
        self.assertEqual(store.get_active_chat_id(), CHAT_ID)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual([row[:-2] for row in connection.execute("SELECT * FROM chats")], chats_before)
            self.assertEqual([row[:-1] for row in connection.execute("SELECT * FROM transcript_entries ORDER BY sequence")], entries_before)
            self.assertEqual(connection.execute("SELECT * FROM archive_state").fetchall(), state_before)
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_stage_notifications_fire_once_and_schema4_repeat_is_read_only(self) -> None:
        stages: list[str] = []
        self.assertEqual(
            migrate_archive_schema3_to4(self.path, stage_hook=stages.append),
            (1, 3),
        )
        self.assertEqual(
            stages,
            [
                "preflight",
                "transaction_started",
                "copied_values",
                "validated_before_commit",
                "committed",
            ],
        )
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArchiveMigrationError, "not schema version 3"):
            migrate_archive_schema3_to4(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_injected_failure_rolls_back_exactly_and_repeat_refuses(self) -> None:
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        def fail(stage: str) -> None:
            if stage == "copied_values":
                raise RuntimeError("injected private failure")
        with self.assertRaisesRegex(ArchiveMigrationError, "preserved"):
            migrate_archive_schema3_to4(self.path, stage_hook=fail)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertEqual(migrate_archive_schema3_to4(self.path), (1, 3))
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema3_to4(self.path)

    def test_sidecars_and_altered_schema_fail_without_modification(self) -> None:
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"valuable")
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArchiveMigrationError, "sidecar"):
            migrate_archive_schema3_to4(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        sidecar.unlink()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE unexpected(private TEXT)")
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ArchiveMigrationError, "not exact"):
            migrate_archive_schema3_to4(self.path)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
