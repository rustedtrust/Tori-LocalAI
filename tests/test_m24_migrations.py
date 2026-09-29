from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tori.conversation_archive import (
    ArchiveEntry,
    ArchiveVersionError,
    ConversationArchiveStore,
)
from tori.conversation_archive_migration import ArchiveMigrationError
from tori.conversation_archive_schema5_migration import migrate_archive_schema4_to5
from tori.memory import MemoryVersionError, SQLiteMemoryStore


class M24MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def schema4_archive(self, name: str = "archive.db") -> Path:
        path = self.root / name
        store = ConversationArchiveStore(
            path, identifier_factory=lambda: "chat-" + "a" * 32
        )
        store.create_chat(
            (
                ArchiveEntry("user", "Exact user text"),
                ArchiveEntry("assistant", "Exact answer", provider="fake", model="model"),
            ),
            provider="fake",
            model="model",
        )
        connection = sqlite3.connect(path)
        for table in (
            "project_context_receipts", "project_links", "project_plan_items",
            "project_questions", "project_decisions", "project_state",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("ALTER TABLE chats DROP COLUMN project_id")
        connection.execute("DROP TABLE projects")
        connection.execute("DROP TABLE memory_extractions")
        connection.execute(
            "UPDATE archive_metadata SET value='4' WHERE key='schema_version'"
        )
        connection.commit()
        connection.close()
        return path

    def schema2_memory(self, name: str = "memory.db") -> Path:
        path = self.root / name
        SQLiteMemoryStore(path).create("Exact existing memory")
        connection = sqlite3.connect(path)
        connection.execute("DROP TABLE memory_extraction_effects")
        connection.execute(
            "UPDATE memory_metadata SET value='2' WHERE key='schema_version'"
        )
        connection.commit()
        connection.close()
        return path

    def test_archive_4_to_5_preserves_history_and_adds_empty_outbox(self) -> None:
        path = self.schema4_archive()
        with self.assertRaisesRegex(ArchiveVersionError, "4-to-5"):
            ConversationArchiveStore(path).initialize()

        self.assertEqual(migrate_archive_schema4_to5(path), (1, 2))

        connection = sqlite3.connect(path)
        self.assertEqual(
            [row[0] for row in connection.execute(
                "SELECT text FROM transcript_entries ORDER BY sequence"
            )],
            ["Exact user text", "Exact answer"],
        )
        self.assertEqual(
            connection.execute("SELECT * FROM memory_extractions").fetchall(), []
        )
        connection.close()
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema4_to5(path)

    def test_archive_migration_failure_rolls_back_to_exact_schema4(self) -> None:
        path = self.schema4_archive("rollback.db")

        def fail(stage: str) -> None:
            if stage == "transaction_started":
                raise RuntimeError("synthetic interruption")

        with self.assertRaisesRegex(ArchiveMigrationError, "schema 4 was preserved"):
            migrate_archive_schema4_to5(path, stage_hook=fail)
        connection = sqlite3.connect(path)
        self.assertEqual(
            connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()[0],
            "4",
        )
        self.assertIsNone(connection.execute(
            "SELECT name FROM sqlite_master WHERE name='memory_extractions'"
        ).fetchone())
        connection.close()

    def test_archive_migration_refuses_schema4_lookalike(self) -> None:
        path = self.schema4_archive("lookalike.db")
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE unexpected(value TEXT)")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(ArchiveMigrationError, "not exact"):
            migrate_archive_schema4_to5(path)

    def test_archive_migration_retains_historical_row_validation(self) -> None:
        path = self.schema4_archive("invalid-project-event.db")
        with sqlite3.connect(path) as connection:
            chat_id, updated_at = connection.execute(
                "SELECT identifier,updated_at FROM chats"
            ).fetchone()
            connection.execute(
                "INSERT INTO transcript_entries "
                "(chat_id,sequence,role,text,sources_json,provider,model,created_at,"
                "application_event_id,application_event_type,context_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    chat_id, 2, "assistant", "Impossible M25 event in schema 4",
                    None, None, None, updated_at, "event-" + "9" * 32,
                    "project_result", None,
                ),
            )
            connection.execute(
                "UPDATE chats SET entry_count=3,revision=revision+1 WHERE identifier=?",
                (chat_id,),
            )
        before = path.read_bytes()
        with self.assertRaisesRegex(ArchiveMigrationError, "Project event"):
            migrate_archive_schema4_to5(path)
        self.assertEqual(path.read_bytes(), before)

    def test_memory_2_to_3_preserves_records_and_adds_empty_ledger(self) -> None:
        path = self.schema2_memory()
        store = SQLiteMemoryStore(path)
        self.assertEqual(store.schema_version(), 2)
        self.assertEqual(store.migrate_v2_to_v3(), (1, 1))
        self.assertEqual(store.schema_version(), 3)
        self.assertEqual([item.text for item in store.list_memories()], ["Exact existing memory"])
        connection = sqlite3.connect(path)
        self.assertEqual(
            connection.execute("SELECT count(*) FROM memory_extraction_effects").fetchone()[0],
            0,
        )
        connection.close()
        with self.assertRaises(MemoryVersionError):
            store.migrate_v2_to_v3()

    def test_memory_migration_validation_failure_rolls_back(self) -> None:
        path = self.schema2_memory("rollback-memory.db")
        store = SQLiteMemoryStore(path)
        original = SQLiteMemoryStore._validate_schema

        def fail(connection):  # type: ignore[no-untyped-def]
            original(connection)
            if SQLiteMemoryStore._schema_version(connection) == 3:
                raise MemoryVersionError("synthetic validation failure")

        with patch.object(
            SQLiteMemoryStore, "_validate_schema", side_effect=fail
        ):
            with self.assertRaises(MemoryVersionError):
                store.migrate_v2_to_v3()
        self.assertEqual(SQLiteMemoryStore(path).schema_version(), 2)


if __name__ == "__main__":
    unittest.main()
