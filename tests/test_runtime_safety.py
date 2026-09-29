from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from scripts.runtime_safety import (
    capture_runtime,
    compare_snapshots,
    inspect_runtime,
)
from tori.coding_work import SQLiteCodingWorkStore
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.memory import (
    SQLiteMemoryStore,
    _EFFECTS_TABLE_SQL,
    _MEMORIES_TABLE_SQL,
    _METADATA_TABLE_SQL,
    _NORMALIZED_TEXT_INDEX_SQL,
)
from tori.tasks import SQLiteOperationalStore
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.coding_work_runtime import CodingWorkRuntimeInitializer
from tori.research import SQLiteResearchStore


class RuntimeSafetyTests(unittest.TestCase):
    def test_research_schema_is_recognized_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            SQLiteResearchStore(root / "research" / "tori_research.db")
            before = capture_runtime(root)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            rendered = "\n".join(lines)
            self.assertIn("Canonical Research store", rendered)
            self.assertIn("exact_schema=yes", rendered)

    def test_unmigrated_research_schema_two_remains_exact_and_migrates_in_temp(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            path = root / "research" / "tori_research.db"
            SQLiteResearchStore(path)
            with sqlite3.connect(path) as connection:
                for table in ("research_claim_evidence", "research_evidence", "research_claims"):
                    connection.execute(f"DROP TABLE {table}")
                connection.execute("UPDATE research_metadata SET value='2' WHERE key='schema_version'")
            before = capture_runtime(root)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertIn("schema_version=2 exact_schema=yes", "\n".join(lines))
            self.assertEqual(capture_runtime(root), before)
            SQLiteResearchStore(path)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertIn("schema_version=3 exact_schema=yes", "\n".join(lines))

    def test_research_schema_three_rejects_correct_columns_without_ownership_fks(self) -> None:
        for declaration in ("", ", FOREIGN KEY(job_id) REFERENCES research_jobs(identifier)"):
            with self.subTest(declaration=declaration), TemporaryDirectory() as directory:
                root = Path(directory) / "runtime"
                root.mkdir(mode=0o700)
                path = root / "research" / "tori_research.db"
                SQLiteResearchStore(path)
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP TABLE research_claim_evidence")
                    connection.execute("""CREATE TABLE research_claim_evidence(
                        job_id TEXT NOT NULL, claim_sequence INTEGER NOT NULL,
                        evidence_sequence INTEGER NOT NULL,
                        PRIMARY KEY(job_id,claim_sequence,evidence_sequence)""" + declaration + ")")
                passed, lines = inspect_runtime(root)
                self.assertFalse(passed)
                self.assertIn("exact_schema=no", "\n".join(lines))

    def test_research_schema_accepts_legitimate_v1_to_v2_column_order(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            path = root / "research" / "tori_research.db"
            SQLiteResearchStore(path)
            with sqlite3.connect(path) as connection:
                for table in ("research_claim_evidence", "research_evidence", "research_claims"):
                    connection.execute(f"DROP TABLE {table}")
                connection.execute("UPDATE research_metadata SET value='2' WHERE key='schema_version'")
                connection.execute("ALTER TABLE research_sources RENAME TO old_sources")
                connection.execute("""
                    CREATE TABLE research_sources(
                        job_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                        url TEXT NOT NULL, title TEXT NOT NULL,
                        source_type TEXT NOT NULL, authority_reason TEXT NOT NULL,
                        retrieved_at_utc TEXT, content_hash TEXT,
                        used_in_report INTEGER NOT NULL DEFAULT 0,
                        search_provider TEXT NOT NULL DEFAULT 'unknown',
                        PRIMARY KEY(job_id, sequence), UNIQUE(job_id, url),
                        FOREIGN KEY(job_id) REFERENCES research_jobs(identifier)
                    )
                """)
                connection.execute("DROP TABLE old_sources")
            before = capture_runtime(root)

            passed, lines = inspect_runtime(root)

            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            self.assertIn("exact_schema=yes", "\n".join(lines))
            SQLiteResearchStore(path)
            self.assertTrue(inspect_runtime(root)[0])

    def test_coding_work_schema_is_recognized_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            CodingWorkRuntimeInitializer(root).initialize()
            before = capture_runtime(root)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            rendered = "\n".join(lines)
            self.assertIn("Canonical Coding Work store", rendered)
            self.assertIn("schema_version=1", rendered)
            self.assertIn("exact_schema=yes", rendered)

    def test_coding_work_schema_accepts_legitimate_advanced_revision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            layout = CodingWorkRuntimeInitializer(root).initialize()
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            store = SQLiteCodingWorkStore(layout.database)
            store.create_work(
                objective="Advance the durable Coding Work revision.",
                workspace_root=str(workspace),
            )
            self.assertGreater(store.revision(), 1)
            before = capture_runtime(root)

            passed, lines = inspect_runtime(root)

            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            self.assertIn("exact_schema=yes", "\n".join(lines))

    def test_coding_work_lookalike_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir(mode=0o700)
            layout = CodingWorkRuntimeInitializer(root).initialize()
            with sqlite3.connect(layout.database) as connection:
                connection.execute("ALTER TABLE coding_work ADD COLUMN unexpected TEXT")
            passed, lines = inspect_runtime(root)
            self.assertFalse(passed)
            self.assertIn("exact_schema=no", "\n".join(lines))

    @staticmethod
    def _memory_path(root: Path) -> Path:
        return root / "memory" / "tori_memory.db"

    def _create_current_memory(self, root: Path) -> Path:
        path = self._memory_path(root)
        SQLiteMemoryStore(path).initialize()
        return path

    def test_verifier_snapshots_before_tests_and_never_cleans_runtime(self) -> None:
        verifier = (Path(__file__).parents[1] / "scripts" / "verify-milestone").read_text(
            encoding="utf-8"
        )
        before = verifier.index("snapshot runtime \"$RUNTIME_BEFORE\"")
        suite = verifier.index("-m unittest discover")
        after = verifier.index("snapshot runtime \"$RUNTIME_AFTER\"")
        comparison = verifier.index("compare \"$RUNTIME_BEFORE\" \"$RUNTIME_AFTER\"")
        self.assertLess(before, suite)
        self.assertLess(suite, after)
        self.assertLess(after, comparison)
        self.assertNotIn("rm -rf -- runtime", verifier)
        self.assertNotIn("rm -- runtime", verifier)

    def test_populated_runtime_is_accepted_and_inspected_without_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            archive = ConversationArchiveStore(
                root / "conversations" / "tori_conversations.db",
                identifier_factory=lambda: "chat-" + "a" * 32,
            )
            archive.create_chat(
                (
                    ArchiveEntry("user", "Synthetic question"),
                    ArchiveEntry(
                        "assistant",
                        "Synthetic answer",
                        provider="fake",
                        model="fake-model",
                    ),
                ),
                provider="fake",
                model="fake-model",
            )
            (root / "checkpoints").mkdir()
            (root / "checkpoints" / "ambiguous.data").write_bytes(b"preserve")
            (root / "knowledge" / "sources").mkdir(parents=True)
            (root / "knowledge" / "sources" / "record.json").write_text(
                "{}", encoding="utf-8"
            )
            before = capture_runtime(root)

            passed, lines = inspect_runtime(root)

            after = capture_runtime(root)
            rendered = "\n".join(lines)
            self.assertTrue(passed)
            self.assertEqual(compare_snapshots(before, after), [])
            self.assertIn("chats=1", rendered)
            self.assertIn("transcript_entries=2", rendered)
            self.assertIn("Canonical memory: absent (accepted; not created)", rendered)

    def test_absent_runtime_and_absent_archive_are_accepted_without_creation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            self.assertEqual(capture_runtime(root), {"present": False, "entries": []})
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertIn("Runtime directory is absent", lines[0])
            self.assertTrue(
                any("Canonical conversation archive: absent" in line for line in lines)
            )
            self.assertFalse(root.exists())

    def test_exact_current_memory_schema_is_accepted_read_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            self._create_current_memory(root)
            before = capture_runtime(root)

            passed, lines = inspect_runtime(root)

            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            self.assertIn("schema_version=3", "\n".join(lines))
            self.assertIn("exact_schema=yes", "\n".join(lines))

    def test_legacy_and_future_memory_versions_are_not_current(self) -> None:
        for version in ("1", "4"):
            with self.subTest(version=version), TemporaryDirectory() as directory:
                root = Path(directory) / "runtime"
                path = self._create_current_memory(root)
                with sqlite3.connect(path) as connection:
                    connection.execute(
                        "UPDATE memory_metadata SET value=? WHERE key='schema_version'",
                        (version,),
                    )

                passed, lines = inspect_runtime(root)

                self.assertFalse(passed)
                self.assertIn(f"schema_version={version}", "\n".join(lines))

    def test_schema_two_metadata_cannot_mask_legacy_or_partial_shape(self) -> None:
        legacy_memories_sql = """
            CREATE TABLE memories (
                identifier TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category = 'general'),
                sensitivity TEXT NOT NULL CHECK (sensitivity = 'ordinary'),
                provenance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        malformed_shapes = {
            "legacy": legacy_memories_sql,
            "missing_column": _MEMORIES_TABLE_SQL.replace(
                "    extraction_model TEXT,\n", ""
            ),
            "weakened_constraint": _MEMORIES_TABLE_SQL.replace(
                " CHECK (user_confirmed IN (0, 1))", ""
            ),
        }
        for name, memories_sql in malformed_shapes.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory) / "runtime"
                path = self._memory_path(root)
                path.parent.mkdir(parents=True)
                with sqlite3.connect(path) as connection:
                    connection.execute(_METADATA_TABLE_SQL)
                    connection.execute(memories_sql)
                    connection.execute(
                        "INSERT INTO memory_metadata VALUES ('schema_version', '2')"
                    )

                passed, lines = inspect_runtime(root)

                self.assertFalse(passed)
                self.assertIn("exact_schema=no", "\n".join(lines))

    def test_exact_previous_memory_schema_is_accepted_pre_migration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            path = self._create_current_memory(root)
            with sqlite3.connect(path) as connection:
                connection.execute("DROP TABLE memory_extraction_effects")
                connection.execute(
                    "UPDATE memory_metadata SET value='2' WHERE key='schema_version'"
                )
            before = capture_runtime(root)

            passed, lines = inspect_runtime(root)

            self.assertTrue(passed)
            self.assertEqual(capture_runtime(root), before)
            self.assertIn("schema_version=2", "\n".join(lines))
            self.assertIn("exact_schema=yes", "\n".join(lines))

    def test_unexpected_memory_table_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            path = self._create_current_memory(root)
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE lookalike (value TEXT)")

            passed, lines = inspect_runtime(root)

            self.assertFalse(passed)
            self.assertIn("exact_schema=no", "\n".join(lines))

    def test_missing_or_lookalike_normalized_index_is_rejected(self) -> None:
        malformed_indexes = {
            "missing": None,
            "wrong_expression": (
                "CREATE INDEX memories_normalized_text_index "
                "ON memories(lower(text))"
            ),
            "wrong_name": (
                "CREATE INDEX memories_text_index ON memories(lower(trim(text)))"
            ),
        }
        for name, replacement in malformed_indexes.items():
            with self.subTest(name=name), TemporaryDirectory() as directory:
                root = Path(directory) / "runtime"
                path = self._create_current_memory(root)
                with sqlite3.connect(path) as connection:
                    connection.execute("DROP INDEX memories_normalized_text_index")
                    if replacement is not None:
                        connection.execute(replacement)

                passed, lines = inspect_runtime(root)

                self.assertFalse(passed)
                self.assertIn("exact_schema=no", "\n".join(lines))

    def test_runtime_memory_contract_matches_store_schema_definitions(self) -> None:
        from scripts import runtime_safety

        def normalize(value: str) -> str:
            return "".join(value.split()).lower()

        self.assertEqual(
            normalize(runtime_safety._MEMORY_METADATA_TABLE_SQL),
            normalize(_METADATA_TABLE_SQL),
        )
        self.assertEqual(
            normalize(runtime_safety._MEMORIES_TABLE_SQL),
            normalize(_MEMORIES_TABLE_SQL),
        )
        self.assertEqual(
            normalize(runtime_safety._MEMORIES_NORMALIZED_TEXT_INDEX_SQL),
            normalize(_NORMALIZED_TEXT_INDEX_SQL),
        )
        self.assertEqual(
            normalize(runtime_safety._MEMORY_EXTRACTION_EFFECTS_TABLE_SQL),
            normalize(_EFFECTS_TABLE_SQL),
        )

    def test_corrupt_memory_database_is_rejected_without_rewrite(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            path = self._memory_path(root)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"not a sqlite database")
            before = path.read_bytes()

            passed, lines = inspect_runtime(root)

            self.assertFalse(passed)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("read-only SQLite inspection failed", "\n".join(lines))

    def test_mutation_is_reported_without_repair(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir()
            data = root / "valuable.bin"
            data.write_bytes(b"before")
            before = capture_runtime(root)
            data.write_bytes(b"after")

            differences = compare_snapshots(before, capture_runtime(root))

            self.assertTrue(any("changed runtime entry: valuable.bin" in item for item in differences))
            self.assertEqual(data.read_bytes(), b"after")

    def test_ambiguous_added_entry_is_reported_and_never_deleted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir()
            before = capture_runtime(root)
            ambiguous = root / "unknown-entry"
            ambiguous.write_bytes(b"keep me")

            differences = compare_snapshots(before, capture_runtime(root))

            self.assertTrue(any("added runtime entry: unknown-entry" in item for item in differences))
            self.assertEqual(ambiguous.read_bytes(), b"keep me")

    def test_operational_store_is_recognized_read_only_when_present(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            store = SQLiteOperationalStore(root / "tasks" / "tori_tasks.db")
            task = store.create_task("temporary runtime-safety fixture")
            before = capture_runtime(root)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertEqual(compare_snapshots(before, capture_runtime(root)), [])
            rendered = "\n".join(lines)
            self.assertIn("Canonical operational store", rendered)
            self.assertIn("tasks=1", rendered)
            self.assertEqual(store.get_task(task.identifier), task)

    def test_scheduled_work_store_is_recognized_read_only_when_present(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            store = SQLiteScheduledWorkStore(
                root / "scheduled_work" / "tori_scheduled_work.db"
            )
            store.initialize()
            before = capture_runtime(root)
            passed, lines = inspect_runtime(root)
            self.assertTrue(passed)
            self.assertEqual(compare_snapshots(before, capture_runtime(root)), [])
            rendered = "\n".join(lines)
            self.assertIn("Canonical scheduled-work store", rendered)
            self.assertIn("scheduled_work_definitions=0", rendered)


if __name__ == "__main__":
    unittest.main()
