from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.conversation_archive import (
    ARCHIVE_SCHEMA_VERSION,
    ArchiveCorruptError,
    ArchiveEntry,
    ArchiveVersionError,
    ConversationArchiveStore,
)
from tori.conversation_archive_migration import ArchiveMigrationError
from tori.conversation_archive_schema7_migration import migrate_archive_schema6_to7


CHAT_ID = "chat-" + "a" * 32
PROJECT_ID = "project-" + "b" * 32
OTHER_PROJECT_ID = "project-" + "c" * 32
DECISION_ONE = "decision-" + "1" * 32
DECISION_TWO = "decision-" + "2" * 32
DECISION_THREE = "decision-" + "3" * 32
QUESTION_ID = "question-" + "4" * 32
PLAN_ID = "plan-item-" + "5" * 32
LINK_ID = "project-link-" + "6" * 32
STAMP = "2026-09-22T12:00:00Z"
LEGACY_BRIEF = (
    "Current focus\nPreserve this exact legacy value.\n\n"
    "Key decisions\nNo semantic inference.\n\n"
    "Open issues / blockers\nNone.\n\n"
    "Next step\nMigrate structure only."
)


class ProjectsSchema7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def store(self, name: str = "archive.db") -> ConversationArchiveStore:
        return ConversationArchiveStore(
            self.root / name,
            identifier_factory=lambda: CHAT_ID,
            project_identifier_factory=lambda: PROJECT_ID,
        )

    def populated_store(self, name: str = "archive.db") -> ConversationArchiveStore:
        store = self.store(name)
        store.create_project(
            title="Continuity",
            objective="Preserve exact archive state",
            continuity_brief=LEGACY_BRIEF,
        )
        store.create_chat(
            (
                ArchiveEntry("user", "Continue the Project"),
                ArchiveEntry("assistant", "Ready", provider="fake", model="model"),
            ),
            provider="fake",
            model="model",
            identifier=CHAT_ID,
            project_id=PROJECT_ID,
        )
        return store

    def schema6_archive(self, name: str = "schema6.db") -> Path:
        store = self.populated_store(name)
        with sqlite3.connect(store.path) as connection:
            for table in (
                "project_context_receipts",
                "project_links",
                "project_plan_items",
                "project_questions",
                "project_decisions",
                "project_state",
            ):
                connection.execute(f"DROP TABLE {table}")
            connection.execute(
                "UPDATE archive_metadata SET value='6' WHERE key='schema_version'"
            )
        return store.path

    @staticmethod
    def insert_project_owned_rows(path: Path) -> None:
        rendered = "Project context data only."
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                "INSERT INTO project_state VALUES (?,?,?,?,?,?,?)",
                (PROJECT_ID, "Build", "Schema foundation", "Validated", 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                (DECISION_ONE, PROJECT_ID, "Use schema 7", "important", "superseded", None, 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                (DECISION_TWO, PROJECT_ID, "Use exact schema 7", "normal", "active", DECISION_ONE, 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_questions VALUES (?,?,?,?,?,?,?,?)",
                (QUESTION_ID, PROJECT_ID, "What is next?", "open", None, 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_plan_items VALUES (?,?,?,?,?,?,?,?,?)",
                (PLAN_ID, PROJECT_ID, "Verify migration", "active", None, 0, 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_links VALUES (?,?,?,?,?,?,?)",
                (LINK_ID, PROJECT_ID, "knowledge_source", "ksrc-" + "7" * 32, 1, STAMP, STAMP),
            )
            connection.execute(
                "INSERT INTO project_context_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    CHAT_ID, 1, PROJECT_ID, 1, "lexical-v1", 512,
                    "[]", "[]", "[]", "[]", rendered, digest, STAMP,
                ),
            )

    def test_fresh_schema7_creation_and_exact_validation(self) -> None:
        store = self.store()
        store.initialize()
        with sqlite3.connect(store.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM archive_metadata WHERE key='schema_version'"
                ).fetchone()[0],
                str(ARCHIVE_SCHEMA_VERSION),
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(
                tables,
                {
                    "archive_metadata", "projects", "chats", "transcript_entries",
                    "archive_state", "memory_extractions", "project_state",
                    "project_decisions", "project_questions", "project_plan_items",
                    "project_links", "project_context_receipts",
                },
            )
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
        store.initialize()

        with sqlite3.connect(store.path) as connection:
            connection.execute("DROP INDEX project_plan_items_order_index")
        before = store.path.read_bytes()
        with self.assertRaisesRegex(ArchiveCorruptError, "invalid schema"):
            store.initialize()
        self.assertEqual(store.path.read_bytes(), before)

    def test_schema6_to7_migration_preserves_every_existing_value(self) -> None:
        path = self.schema6_archive()
        with sqlite3.connect(path) as connection:
            before = {
                table: connection.execute(f"SELECT * FROM {table}").fetchall()
                for table in (
                    "projects", "chats", "transcript_entries", "archive_state",
                    "memory_extractions",
                )
            }
        before_startup = path.read_bytes()
        with self.assertRaisesRegex(ArchiveVersionError, "6-to-7"):
            ConversationArchiveStore(path).initialize()
        self.assertEqual(path.read_bytes(), before_startup)

        self.assertEqual(migrate_archive_schema6_to7(path), (1, 1, 2, 0))
        with sqlite3.connect(path) as connection:
            self.assertEqual(
                connection.execute("SELECT value FROM archive_metadata").fetchone()[0], "7"
            )
            for table, rows in before.items():
                self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), rows)
            self.assertEqual(
                connection.execute(
                    "SELECT continuity_brief FROM projects WHERE identifier=?",
                    (PROJECT_ID,),
                ).fetchone()[0],
                LEGACY_BRIEF,
            )
            for table in (
                "project_state", "project_decisions", "project_questions",
                "project_plan_items", "project_links", "project_context_receipts",
            ):
                self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
        ConversationArchiveStore(path).initialize()

    def test_migration_failure_rolls_back_and_rejects_unsupported_sources(self) -> None:
        for index, failure_stage in enumerate((
            "preflight", "transaction_started", "structures_created",
            "validated_before_commit",
        )):
            path = self.schema6_archive(f"rollback-{index}.db")
            before = path.read_bytes()

            def fail(stage: str, *, expected: str = failure_stage) -> None:
                if stage == expected:
                    raise RuntimeError("synthetic failure")

            with self.assertRaisesRegex(ArchiveMigrationError, "schema 6 was preserved"):
                migrate_archive_schema6_to7(path, stage_hook=fail)
            self.assertEqual(path.read_bytes(), before)
            with sqlite3.connect(path) as connection:
                self.assertEqual(
                    connection.execute("SELECT value FROM archive_metadata").fetchone()[0],
                    "6",
                )
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='project_state'"
                ).fetchone())

        lookalike = self.schema6_archive("lookalike.db")
        with sqlite3.connect(lookalike) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaisesRegex(ArchiveMigrationError, "not exact"):
            migrate_archive_schema6_to7(lookalike)

        current = self.store("current.db")
        current.initialize()
        with self.assertRaisesRegex(ArchiveMigrationError, "not schema version 6"):
            migrate_archive_schema6_to7(current.path)

        stale = self.schema6_archive("stale.db")
        with sqlite3.connect(stale) as connection:
            connection.execute(
                "UPDATE archive_metadata SET value='5' WHERE key='schema_version'"
            )
        stale_before = stale.read_bytes()
        with self.assertRaisesRegex(ArchiveMigrationError, "not schema version 6"):
            migrate_archive_schema6_to7(stale)
        self.assertEqual(stale.read_bytes(), stale_before)

    def test_migration_rejects_symlinks_and_sidecars_without_modification(self) -> None:
        path = self.schema6_archive("safe-source.db")
        link = self.root / "linked.db"
        link.symlink_to(path)
        before = path.read_bytes()
        with self.assertRaises(ArchiveMigrationError):
            migrate_archive_schema6_to7(link)
        self.assertEqual(path.read_bytes(), before)

        sidecar = Path(str(path) + "-wal")
        sidecar.write_bytes(b"valuable ambiguous state")
        with self.assertRaisesRegex(ArchiveMigrationError, "sidecar"):
            migrate_archive_schema6_to7(path)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sidecar.read_bytes(), b"valuable ambiguous state")

    def test_project_and_conversation_deletion_own_receipts_independently(self) -> None:
        store = self.populated_store()
        self.insert_project_owned_rows(store.path)
        store.initialize()
        self.assertIsNotNone(store.get_project_state(PROJECT_ID))
        self.assertEqual(len(store.list_project_decisions(PROJECT_ID)), 2)
        self.assertEqual(len(store.list_project_questions(PROJECT_ID)), 1)
        self.assertEqual(len(store.list_project_plan_items(PROJECT_ID)), 1)
        self.assertEqual(len(store.list_project_links(PROJECT_ID)), 1)
        self.assertIsNotNone(store.get_project_context_receipt(CHAT_ID, 1))

        store.delete_project(PROJECT_ID, expected_revision=1)
        with sqlite3.connect(store.path) as connection:
            for table in (
                "project_state", "project_decisions", "project_questions",
                "project_plan_items", "project_links", "project_context_receipts",
            ):
                self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), [])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM chats").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM transcript_entries").fetchone()[0], 2)
            self.assertIsNone(connection.execute("SELECT project_id FROM chats").fetchone()[0])

        other = self.populated_store("chat-delete.db")
        self.insert_project_owned_rows(other.path)
        chat = other.get_chat(CHAT_ID)
        other.delete_chat(CHAT_ID, expected_revision=chat.metadata.revision)
        with sqlite3.connect(other.path) as connection:
            self.assertEqual(connection.execute("SELECT * FROM project_context_receipts").fetchall(), [])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM project_state").fetchone()[0], 1)

    def test_decision_constraints_reject_branching_cross_project_and_cycles(self) -> None:
        store = self.populated_store()
        self.insert_project_owned_rows(store.path)
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                    (DECISION_THREE, PROJECT_ID, "Branch", "normal", "active", DECISION_ONE, 1, STAMP, STAMP),
                )
            connection.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)",
                (OTHER_PROJECT_ID, "Other", "active", "Other objective", LEGACY_BRIEF, 1, STAMP, STAMP),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                    (DECISION_THREE, OTHER_PROJECT_ID, "Cross", "normal", "active", DECISION_TWO, 1, STAMP, STAMP),
                )

            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE project_decisions SET state='superseded', "
                    "supersedes_decision_id=? WHERE identifier=?",
                    (DECISION_TWO, DECISION_ONE),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE project_decisions SET text='rewritten history' "
                    "WHERE identifier=?",
                    (DECISION_ONE,),
                )
        store.initialize()

    def test_project_deletion_does_not_touch_source_owned_files(self) -> None:
        store = self.populated_store()
        sources = []
        for name in ("research.db", "coding.db", "attention.db"):
            path = self.root / name
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE records(project_id TEXT,value TEXT)")
                connection.execute("INSERT INTO records VALUES (?,?)", (PROJECT_ID, name))
            sources.append((path, hashlib.sha256(path.read_bytes()).hexdigest()))

        store.delete_project(PROJECT_ID, expected_revision=1)
        for path, digest in sources:
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("SELECT project_id FROM records").fetchone()[0], PROJECT_ID)


if __name__ == "__main__":
    unittest.main()
