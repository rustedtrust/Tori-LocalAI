from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.conversation_archive import (
    ArchiveContext,
    ArchiveEntry,
    ArchiveSource,
    ArchiveVersionError,
    ConversationArchiveStore,
    MemoryExtractionRequest,
)
from tori.conversation_archive_migration import ArchiveMigrationError
from tori.conversation_archive_schema6_migration import migrate_archive_schema5_to6


class M25MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def schema5_archive(self, name: str = "archive.db") -> Path:
        path = self.root / name
        store = ConversationArchiveStore(
            path, identifier_factory=lambda: "chat-" + "a" * 32
        )
        store.create_chat(
            (
                ArchiveEntry("user", "Exact historical request"),
                ArchiveEntry(
                    "assistant", "Exact historical response",
                    sources=(ArchiveSource("historical.md", 2, 4),),
                    provider="fake", model="model",
                    context=ArchiveContext(
                        requested_policy="fixed:8192",
                        effective_budget=8192,
                        estimator_version="chars-v1",
                        estimated_input_tokens=321,
                        included_history_messages=4,
                        omitted_history_messages=2,
                        actual_prompt_tokens=300,
                        actual_completion_tokens=21,
                        actual_total_tokens=321,
                    ),
                ),
            ),
            provider="fake", model="model",
            select_active=True,
            context_policy="fixed:8192",
            memory_extraction=MemoryExtractionRequest(
                "extract-" + "1" * 32, 0, 1, "fake", "model", "a" * 64
            ),
        )
        claimed = store.claim_next_memory_extraction("migration-review")
        assert claimed is not None
        store.transition_memory_extraction(
            claimed.extraction_id,
            expected_revision=claimed.revision,
            process_incarnation="migration-review",
            state="awaiting_confirmation",
            plan_json='{"effects":[]}',
            proposal_json='{"summary":"exact historical proposal"}',
        )
        chat = store.get_chat("chat-" + "a" * 32)
        store.append_application_event(
            chat.metadata.identifier,
            expected_revision=chat.metadata.revision,
            event_id="event-" + "e" * 32,
            event_type="operational_result",
            text="Exact historical application event",
        )
        with sqlite3.connect(path) as connection:
            for table in (
                "project_context_receipts", "project_links", "project_plan_items",
                "project_questions", "project_decisions", "project_state",
            ):
                connection.execute(f"DROP TABLE {table}")
            connection.execute("ALTER TABLE chats DROP COLUMN project_id")
            connection.execute("DROP TABLE projects")
            connection.execute(
                "UPDATE archive_metadata SET value='5' WHERE key='schema_version'"
            )
        return path

    def test_exact_migration_preserves_schema5_and_infers_nothing(self) -> None:
        path = self.schema5_archive()
        before_startup = path.read_bytes()
        with self.assertRaisesRegex(ArchiveVersionError, "5-to-6"):
            ConversationArchiveStore(path).initialize()
        self.assertEqual(path.read_bytes(), before_startup)
        with sqlite3.connect(path) as connection:
            before_chat = connection.execute("SELECT * FROM chats").fetchall()
            before_entries = connection.execute(
                "SELECT * FROM transcript_entries ORDER BY sequence"
            ).fetchall()
            before_state = connection.execute("SELECT * FROM archive_state").fetchall()
            before_extractions = connection.execute(
                "SELECT * FROM memory_extractions"
            ).fetchall()
        self.assertEqual(migrate_archive_schema5_to6(path), (1, 3, 1))
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()[0], "6")
            self.assertEqual(
                [row[:-1] for row in connection.execute("SELECT * FROM chats")],
                before_chat,
            )
            self.assertEqual(
                connection.execute("SELECT * FROM transcript_entries ORDER BY sequence").fetchall(),
                before_entries,
            )
            self.assertEqual(connection.execute("SELECT * FROM archive_state").fetchall(), before_state)
            self.assertEqual(connection.execute("SELECT * FROM memory_extractions").fetchall(), before_extractions)
            self.assertEqual(connection.execute("SELECT * FROM projects").fetchall(), [])
            self.assertEqual(connection.execute("SELECT project_id FROM chats").fetchall(), [(None,)])
            self.assertEqual(connection.execute(
                "SELECT state,revision,claim_owner,plan_json,proposal_json "
                "FROM memory_extractions"
            ).fetchone(), (
                "awaiting_confirmation", 3, None, '{"effects":[]}',
                '{"summary":"exact historical proposal"}',
            ))
        store = ConversationArchiveStore(path)
        with self.assertRaisesRegex(ArchiveVersionError, "6-to-7"):
            store.initialize()

    def test_injected_failure_rolls_back_to_exact_schema5(self) -> None:
        path = self.schema5_archive("rollback.db")

        def fail(stage: str) -> None:
            if stage == "validated_before_commit":
                raise RuntimeError("synthetic failure")

        with self.assertRaisesRegex(ArchiveMigrationError, "schema 5 was preserved"):
            migrate_archive_schema5_to6(path, stage_hook=fail)
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()[0], "5")
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='projects'"
            ).fetchone())
            self.assertNotIn(
                "project_id", [row[1] for row in connection.execute("PRAGMA table_info(chats)")]
            )

    def test_refuses_lookalike_and_already_migrated(self) -> None:
        lookalike = self.schema5_archive("lookalike.db")
        with sqlite3.connect(lookalike) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaisesRegex(ArchiveMigrationError, "not exact"):
            migrate_archive_schema5_to6(lookalike)

        migrated = self.schema5_archive("migrated.db")
        migrate_archive_schema5_to6(migrated)
        with self.assertRaisesRegex(ArchiveMigrationError, "not schema version 5"):
            migrate_archive_schema5_to6(migrated)

        newer = self.schema5_archive("newer-field.db")
        with sqlite3.connect(newer) as connection:
            connection.execute("ALTER TABLE chats ADD COLUMN unrecognized_future_value TEXT")
        newer_before = newer.read_bytes()
        with self.assertRaisesRegex(ArchiveMigrationError, "not exact"):
            migrate_archive_schema5_to6(newer)
        self.assertEqual(newer.read_bytes(), newer_before)

        project_event = self.schema5_archive("project-event.db")
        with sqlite3.connect(project_event) as connection:
            connection.execute(
                "UPDATE transcript_entries SET application_event_type='project_result' "
                "WHERE application_event_id IS NOT NULL"
            )
        project_event_before = project_event.read_bytes()
        with self.assertRaisesRegex(ArchiveMigrationError, "Project event"):
            migrate_archive_schema5_to6(project_event)
        self.assertEqual(project_event.read_bytes(), project_event_before)

    def test_refuses_symlink_and_sidecar_without_modifying_target(self) -> None:
        path = self.schema5_archive("protected.db")
        before = path.read_bytes()
        link = self.root / "archive-link.db"
        link.symlink_to(path)
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema5_to6(link)
        self.assertEqual(path.read_bytes(), before)

        sidecar = Path(str(path) + "-wal")
        sidecar.write_bytes(b"ambiguous valuable sidecar")
        with self.assertRaisesRegex(ArchiveMigrationError, "sidecar"):
            migrate_archive_schema5_to6(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sidecar.read_bytes(), b"ambiguous valuable sidecar")


if __name__ == "__main__":
    unittest.main()
