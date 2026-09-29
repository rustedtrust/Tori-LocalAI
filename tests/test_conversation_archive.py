from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import tori.conversation_archive as archive_module
from tori.conversation_archive import (
    ARCHIVE_SCHEMA_VERSION,
    ArchiveConflictError,
    ArchiveCorruptError,
    ArchiveDivergenceError,
    ArchiveContext,
    ArchiveEntry,
    ArchiveNotFoundError,
    ArchiveSource,
    ArchiveStaleRevisionError,
    ArchiveUnavailableError,
    ArchiveValidationError,
    ArchiveVerificationError,
    ArchiveVersionError,
    ConversationArchiveStore,
    TERMINAL_PROPOSAL_ORIGIN_TEXT,
    chat_accepts_application_event,
    derive_chat_label,
    validate_chat_identifier,
)


FIRST_ID = "chat-" + "1" * 32
SECOND_ID = "chat-" + "2" * 32
TEST_TIME = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


class ConversationArchiveStoreTests(unittest.TestCase):
    def test_terminal_origin_is_zero_turn_internal_and_reconciles_one_model_reply(self) -> None:
        store = self.store()
        receipt = ArchiveEntry(
            "assistant", TERMINAL_PROPOSAL_ORIGIN_TEXT,
            application_event_id="event-" + "c" * 32,
            application_event_type="terminal_proposal_origin",
        )
        entries = (ArchiveEntry("user", "Run echo hello for me."), receipt)
        for invalid in (replace(receipt, text="Internal JSON leaked"),
                        replace(receipt, application_event_id=None),
                        replace(receipt, provider="ollama", model="model-a")):
            with self.assertRaises(ArchiveValidationError):
                store.create_terminal_proposal_origin(
                    (entries[0], invalid), selected_provider="ollama", selected_model="model-a",
                )
        created = store.create_terminal_proposal_origin(
            entries, selected_provider="ollama", selected_model="model-a",
        )
        self.assertEqual(created.metadata.completed_turn_count, 0)
        self.assertEqual(store.get_chat(created.metadata.identifier), created)
        self.assertFalse(chat_accepts_application_event(0, created.entries, "reminder_due"))
        with self.assertRaises(ArchiveValidationError):
            store.append_application_event(
                created.metadata.identifier, expected_revision=1,
                event_id="event-" + "d" * 32, event_type="reminder_due", text="not allowed",
            )
        reopened = self.store()
        self.assertEqual(reopened.get_active_chat_id(), created.metadata.identifier)
        assistant = ArchiveEntry("assistant", "It printed hello.", provider="ollama", model="gemma4:12b")
        completed = reopened.reconcile_chat(
            created.metadata.identifier, (*created.entries, assistant), expected_revision=1,
        )
        self.assertEqual(completed.metadata.completed_turn_count, 1)
        self.assertEqual(completed.entries[-1].text, "It printed hello.")

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive" / "tori.db"
        self.entries = (
            ArchiveEntry("user", "First exact question"),
            ArchiveEntry(
                "assistant", "First exact answer",
                provider="ollama", model="model-a",
            ),
        )

    def store(self, identifier=FIRST_ID, clock=lambda: TEST_TIME):  # type: ignore[no-untyped-def]
        return ConversationArchiveStore(
            self.path, clock=clock, identifier_factory=lambda: identifier
        )

    def create(self, store=None, entries=None):  # type: ignore[no-untyped-def]
        selected = store or self.store()
        selected_entries = tuple(
            replace(item, provider="ollama", model="model-a")
            if (
                item.role == "assistant"
                and item.provider is None
                and item.application_event_id is None
            )
            else item
            for item in (entries or self.entries)
        )
        return selected.create_chat(
            selected_entries, provider="ollama", model="model-a"
        )

    def alternate_store(self, name: str) -> ConversationArchiveStore:
        return ConversationArchiveStore(
            Path(self.temporary.name) / name / "tori.db",
            clock=lambda: TEST_TIME,
            identifier_factory=lambda: FIRST_ID,
        )

    def legacy_research_archive(self, name: str = "legacy-research"):  # type: ignore[no-untyped-def]
        store = self.alternate_store(name)
        created = store.create_scheduled_work_origin(
            (
                ArchiveEntry("user", "Synthetic research request"),
                ArchiveEntry(
                    "assistant",
                    "Synthetic research start",
                    application_event_id="event-" + "d" * 32,
                    application_event_type="scheduled_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        completed_at = "2026-08-02T12:00:01Z"
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE transcript_entries SET application_event_type=? "
                "WHERE chat_id=? AND sequence=1",
                ("deep_research_started", created.metadata.identifier),
            )
            connection.execute(
                "INSERT INTO transcript_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    created.metadata.identifier,
                    2,
                    "assistant",
                    "Synthetic research result",
                    None,
                    None,
                    None,
                    completed_at,
                    "event-" + "e" * 32,
                    "deep_research_result",
                    None,
                ),
            )
            connection.execute(
                "UPDATE chats SET updated_at=?, revision=2, entry_count=3 "
                "WHERE identifier=?",
                (completed_at, created.metadata.identifier),
            )
        return store, created.metadata.identifier

    def test_initialize_reopen_version_pragmas_and_exact_schema(self) -> None:
        self.store().initialize()
        reopened = ConversationArchiveStore(self.path)
        reopened.initialize()
        with sqlite3.connect(self.path) as connection:
            version = connection.execute(
                "SELECT value FROM archive_metadata WHERE key='schema_version'"
            ).fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
            self.assertEqual(connection.execute("PRAGMA secure_delete").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(version, str(ARCHIVE_SCHEMA_VERSION))
        self.assertEqual(
            tables,
            {
                "archive_metadata",
                "chats",
                "transcript_entries",
                "archive_state",
                "memory_extractions",
                "projects",
                "project_state",
                "project_decisions",
                "project_questions",
                "project_plan_items",
                "project_links",
                "project_context_receipts",
            },
        )

    def test_schema_columns_types_nullability_keys_checks_and_foreign_keys(self) -> None:
        self.store().initialize()
        with sqlite3.connect(self.path) as connection:
            chat_columns = connection.execute("PRAGMA table_info(chats)").fetchall()
            self.assertEqual(
                [(row[1], row[2], row[3], row[5]) for row in chat_columns],
                [
                    ("identifier", "TEXT", 0, 1), ("label", "TEXT", 1, 0),
                    ("created_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
                    ("last_opened_at", "TEXT", 0, 0), ("revision", "INTEGER", 1, 0),
                    ("first_provider", "TEXT", 0, 0), ("first_model", "TEXT", 0, 0),
                    ("latest_provider", "TEXT", 0, 0), ("latest_model", "TEXT", 0, 0),
                    ("selected_provider", "TEXT", 1, 0), ("selected_model", "TEXT", 1, 0),
                    ("entry_count", "INTEGER", 1, 0),
                    ("completed_turn_count", "INTEGER", 1, 0),
                    ("selected_context_policy", "TEXT", 1, 0),
                    ("project_id", "TEXT", 0, 0),
                ],
            )
            chats_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='chats'"
            ).fetchone()[0]
            self.assertIn("completed_turn_count = 0", chats_sql)
            self.assertIn("first_provider IS NULL", chats_sql)
            columns = connection.execute("PRAGMA table_info(transcript_entries)").fetchall()
            self.assertEqual(
                [(row[1], row[2], row[3], row[5]) for row in columns],
                [
                    ("chat_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
                    ("role", "TEXT", 1, 0), ("text", "TEXT", 1, 0),
                    ("sources_json", "TEXT", 0, 0), ("provider", "TEXT", 0, 0),
                    ("model", "TEXT", 0, 0), ("created_at", "TEXT", 1, 0),
                    ("application_event_id", "TEXT", 0, 0),
                    ("application_event_type", "TEXT", 0, 0),
                    ("context_json", "TEXT", 0, 0),
                ],
            )
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='transcript_entries'"
            ).fetchone()[0]
            self.assertIn("CHECK (role IN", sql)
            self.assertIn("ON DELETE CASCADE", sql)
            self.assertEqual(len(connection.execute("PRAGMA foreign_key_list(transcript_entries)").fetchall()), 1)
            project_columns = connection.execute("PRAGMA table_info(projects)").fetchall()
            self.assertEqual(
                [(row[1], row[2], row[3], row[5]) for row in project_columns],
                [
                    ("identifier", "TEXT", 0, 1), ("title", "TEXT", 1, 0),
                    ("status", "TEXT", 1, 0), ("objective", "TEXT", 1, 0),
                    ("continuity_brief", "TEXT", 1, 0),
                    ("revision", "INTEGER", 1, 0),
                    ("created_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
                ],
            )
            project_foreign_keys = connection.execute(
                "PRAGMA foreign_key_list(chats)"
            ).fetchall()
            self.assertEqual(len(project_foreign_keys), 1)
            self.assertEqual(
                (project_foreign_keys[0][2], project_foreign_keys[0][3],
                 project_foreign_keys[0][4], project_foreign_keys[0][6]),
                ("projects", "project_id", "identifier", "SET NULL"),
            )

    def test_schema_rejects_altered_quoted_check_literals_without_modification(self) -> None:
        replacements = (
            ("'chat-'", "'CHAT-'"),
            ("'warning'", "'Warning'"),
        )
        for offset, (original, changed) in enumerate(replacements):
            store = self.alternate_store(f"literal-{offset}")
            store.initialize()
            with sqlite3.connect(store.path) as connection:
                connection.execute("PRAGMA writable_schema=ON")
                connection.execute(
                    "UPDATE sqlite_master SET sql=replace(sql, ?, ?) "
                    "WHERE type='table' AND instr(sql, ?) > 0",
                    (original, changed, original),
                )
                connection.commit()
            before = store.path.read_bytes()
            with self.subTest(changed=changed), self.assertRaises(ArchiveCorruptError):
                store.initialize()
            self.assertEqual(store.path.read_bytes(), before)

    def test_schema_rejects_extra_trigger_view_and_user_index_without_modification(self) -> None:
        statements = (
            "CREATE TRIGGER extra_trigger AFTER INSERT ON chats BEGIN "
            "SELECT 1; END",
            "CREATE VIEW extra_view AS SELECT identifier FROM chats",
            "CREATE INDEX extra_index ON chats(updated_at)",
        )
        for offset, statement in enumerate(statements):
            store = self.alternate_store(f"object-{offset}")
            store.initialize()
            with sqlite3.connect(store.path) as connection:
                connection.execute(statement)
            before = store.path.read_bytes()
            with self.subTest(statement=statement), self.assertRaises(ArchiveCorruptError):
                store.initialize()
            self.assertEqual(store.path.read_bytes(), before)

    def test_schema_expected_autoindexes_are_deliberately_accepted(self) -> None:
        self.store().initialize()
        with sqlite3.connect(self.path) as connection:
            indexes = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        self.assertEqual(
            indexes,
            {
                "sqlite_autoindex_archive_metadata_1",
                "sqlite_autoindex_chats_1",
                "sqlite_autoindex_transcript_entries_1",
                "sqlite_autoindex_archive_state_1",
                "sqlite_autoindex_memory_extractions_1",
                "sqlite_autoindex_memory_extractions_2",
                "sqlite_autoindex_projects_1",
                "memory_extractions_fifo_index",
                "transcript_entries_application_event_id_index",
                "sqlite_autoindex_project_state_1",
                "sqlite_autoindex_project_decisions_1",
                "sqlite_autoindex_project_decisions_2",
                "sqlite_autoindex_project_decisions_3",
                "project_decisions_state_index",
                "sqlite_autoindex_project_questions_1",
                "project_questions_state_index",
                "sqlite_autoindex_project_plan_items_1",
                "project_plan_items_state_index",
                "project_plan_items_order_index",
                "sqlite_autoindex_project_links_1",
                "sqlite_autoindex_project_links_2",
                "sqlite_autoindex_project_context_receipts_1",
                "project_context_receipts_project_index",
            },
        )
        ConversationArchiveStore(self.path).initialize()

    def test_unsupported_version_and_wal_mode_are_preserved_before_pragmas(self) -> None:
        self.store().initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE archive_metadata SET value='99'")
            connection.commit()
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ArchiveVersionError):
            self.store().initialize()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(connection.execute("SELECT value FROM archive_metadata").fetchone()[0], "99")
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_corrupt_database_is_preserved(self) -> None:
        self.path.parent.mkdir(parents=True)
        original = b"not a sqlite database"
        self.path.write_bytes(original)
        with self.assertRaises(ArchiveCorruptError):
            self.store().initialize()
        self.assertEqual(self.path.read_bytes(), original)

    def test_malformed_lookalike_schema_is_rejected_without_rewrite(self) -> None:
        self.store().initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute("ALTER TABLE archive_state RENAME TO old_state")
            connection.execute(
                "CREATE TABLE archive_state (singleton INTEGER PRIMARY KEY, active_chat_id TEXT)"
            )
            connection.execute("INSERT INTO archive_state VALUES (1, NULL)")
            connection.execute("DROP TABLE old_state")
        before = self.path.read_bytes()
        with self.assertRaises(ArchiveCorruptError):
            self.store().initialize()
        self.assertEqual(self.path.read_bytes(), before)

    def test_creation_requires_completed_exchange_and_valid_identifier(self) -> None:
        with self.assertRaises(ArchiveValidationError):
            self.store().create_chat((), provider="ollama", model="model-a")
        with self.assertRaises(ArchiveValidationError):
            self.create(entries=(ArchiveEntry("user", "Only user"),))
        self.assertFalse(self.path.exists())
        self.assertEqual(validate_chat_identifier(FIRST_ID), FIRST_ID)
        for invalid in ("chat-ABC", "chat-" + "g" * 32, "../chat-" + "1" * 32):
            with self.subTest(invalid=invalid), self.assertRaises(ArchiveValidationError):
                validate_chat_identifier(invalid)

    def test_completed_turn_attribution_nullability_is_fail_closed(self) -> None:
        created = self.create()
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE chats SET first_provider=NULL WHERE identifier=?",
                (created.metadata.identifier,),
            )
        with self.assertRaises(ArchiveCorruptError):
            self.store().initialize()

        other = self.alternate_store("zero-attribution")
        zero = other.create_scheduled_work_origin(
            (
                ArchiveEntry("user", "schedule request"),
                ArchiveEntry(
                    "assistant",
                    "safe proposal",
                    application_event_id="event-" + "e" * 32,
                    application_event_type="scheduled_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        with sqlite3.connect(other.path) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE chats SET latest_model='fabricated' WHERE identifier=?",
                (zero.metadata.identifier,),
            )
        with self.assertRaises(ArchiveCorruptError):
            other.initialize()

    def test_zero_turn_record_requires_the_scheduled_work_origin_prefix(self) -> None:
        store = self.alternate_store("zero-prefix")
        created = store.create_scheduled_work_origin(
            (
                ArchiveEntry("user", "schedule request"),
                ArchiveEntry(
                    "assistant",
                    "safe proposal",
                    application_event_id="event-" + "d" * 32,
                    application_event_type="scheduled_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE transcript_entries SET application_event_type='operational_result' "
                "WHERE chat_id=? AND sequence=1",
                (created.metadata.identifier,),
            )
        with self.assertRaisesRegex(ArchiveCorruptError, "zero-turn"):
            store.initialize()

    def test_calendar_origin_accepts_distinct_repeated_planning_reads_only(self) -> None:
        store = self.alternate_store("calendar-planning-origin")
        calendar_event_id = "event-" + "a" * 32
        created = store.create_planning_origin(
            (
                ArchiveEntry("user", "What weekday is it?"),
                ArchiveEntry(
                    "assistant", "Today is Sunday.",
                    application_event_id=calendar_event_id,
                    application_event_type="calendar_information",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        current = created
        for marker in ("b", "c", "d"):
            current = store.reconcile_planning_origin(
                current.metadata.identifier,
                (
                    *current.entries,
                    ArchiveEntry("user", "What do I have today?"),
                    ArchiveEntry(
                        "assistant", "Today\n- Nothing scheduled.",
                        application_event_id="event-" + marker * 32,
                        application_event_type="planning_read",
                    ),
                ),
                expected_revision=current.metadata.revision,
            )

        self.assertEqual(current.metadata.entry_count, 8)
        self.assertEqual(current.metadata.completed_turn_count, 0)
        self.assertEqual(len({entry.application_event_id for entry in current.entries[1::2]}), 4)
        with self.assertRaises(ArchiveValidationError):
            store.reconcile_planning_origin(
                current.metadata.identifier,
                (
                    *current.entries,
                    ArchiveEntry(
                        "assistant", "Malformed orphan response.",
                        application_event_id="event-" + "e" * 32,
                        application_event_type="planning_read",
                    ),
                ),
                expected_revision=current.metadata.revision,
            )
        with self.assertRaises(ArchiveConflictError):
            store.append_application_event(
                current.metadata.identifier,
                expected_revision=current.metadata.revision,
                event_id=calendar_event_id,
                event_type="calendar_information",
                text="Conflicting replay semantics.",
            )

    def test_legacy_research_events_open_read_only_but_cannot_be_written_new(self) -> None:
        store, identifier = self.legacy_research_archive()
        before = hashlib.sha256(store.path.read_bytes()).hexdigest()

        store.initialize()
        loaded = store.get_chat(identifier)

        self.assertEqual(
            tuple(item.application_event_type for item in loaded.entries),
            (None, "deep_research_started", "deep_research_result"),
        )
        self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), before)
        with self.assertRaises(ArchiveValidationError):
            store.append_application_event(
                identifier,
                expected_revision=loaded.metadata.revision,
                event_id="event-" + "f" * 32,
                event_type="deep_research_result",
                text="A new legacy event must not be writable.",
            )

    def test_reminder_delivery_can_follow_a_zero_turn_coding_work_result(self) -> None:
        store = self.alternate_store("coding-work-reminder")
        created = store.create_coding_work_proposal_origin(
            (
                ArchiveEntry("user", "Synthetic bounded work request"),
                ArchiveEntry(
                    "assistant",
                    "Synthetic Coding Work proposal",
                    application_event_id="event-" + "a" * 32,
                    application_event_type="coding_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        completed = store.reconcile_coding_work_origin(
            created.metadata.identifier,
            (
                *created.entries,
                ArchiveEntry(
                    "assistant",
                    "Synthetic Coding Work result",
                    application_event_id="event-" + "b" * 32,
                    application_event_type="coding_work_result",
                ),
            ),
            expected_revision=created.metadata.revision,
        )

        delivered = store.append_application_event(
            created.metadata.identifier,
            expected_revision=completed.metadata.revision,
            event_id="event-" + "c" * 32,
            event_type="reminder_due",
            text="Reminder: synthetic task",
        )

        self.assertEqual(
            tuple(item.application_event_type for item in delivered.entries),
            (None, "coding_work_proposal", "coding_work_result", "reminder_due"),
        )
        self.assertEqual(store.get_chat(created.metadata.identifier), delivered)

    def test_project_proposal_origin_rejects_a_background_scheduled_result(self) -> None:
        store = self.alternate_store("project-proposal-poisoning")
        created = store.create_project_proposal_origin(
            (
                ArchiveEntry("user", "I want to create a Project for my garden plan."),
                ArchiveEntry(
                    "assistant",
                    'Create Project "garden" and associate this conversation with it? '
                    "No capability permission is granted.",
                    application_event_id="event-" + "a" * 32,
                    application_event_type="project_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        identifier = created.metadata.identifier
        before = store.get_chat(identifier)
        file_before = hashlib.sha256(store.path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(
            ArchiveValidationError, "cannot accept that application event"
        ):
            store.append_application_event(
                identifier,
                expected_revision=before.metadata.revision,
                event_id="event-" + "b" * 32,
                event_type="scheduled_work_result",
                text="Night Owl missed occurrence result.",
            )

        after = store.get_chat(identifier)
        self.assertEqual(after, before)
        self.assertEqual(
            tuple(item.application_event_type for item in after.entries),
            (None, "project_proposal"),
        )
        self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), file_before)

        reopened = ConversationArchiveStore(
            store.path, clock=lambda: TEST_TIME, identifier_factory=lambda: FIRST_ID
        )
        reopened.initialize()
        self.assertEqual(reopened.get_chat(identifier), before)

    def test_project_proposal_origin_rejects_a_background_reminder(self) -> None:
        store = self.alternate_store("project-proposal-reminder")
        created = store.create_project_proposal_origin(
            (
                ArchiveEntry("user", "I want to create a Project for my garden plan."),
                ArchiveEntry(
                    "assistant",
                    'Create Project "garden" and associate this conversation with it? '
                    "No capability permission is granted.",
                    application_event_id="event-" + "a" * 32,
                    application_event_type="project_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        identifier = created.metadata.identifier
        before = store.get_chat(identifier)

        with self.assertRaisesRegex(
            ArchiveValidationError, "cannot accept that application event"
        ):
            store.append_application_event(
                identifier,
                expected_revision=before.metadata.revision,
                event_id="event-" + "c" * 32,
                event_type="reminder_due",
                text="Reminder: synthetic task",
            )

        self.assertEqual(store.get_chat(identifier), before)

    def test_special_origin_appends_validate_the_complete_resulting_sequence(self) -> None:
        project = self.alternate_store("accept-project")
        project_chat = project.create_project_proposal_origin(
            (
                ArchiveEntry("user", "I want to create a Project."),
                ArchiveEntry(
                    "assistant", "Create it?",
                    application_event_id="event-" + "a" * 32,
                    application_event_type="project_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        scheduled = self.alternate_store("accept-scheduled")
        scheduled_chat = scheduled.create_scheduled_work_origin(
            (
                ArchiveEntry("user", "schedule request"),
                ArchiveEntry(
                    "assistant", "safe proposal",
                    application_event_id="event-" + "b" * 32,
                    application_event_type="scheduled_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        coding = self.alternate_store("accept-coding")
        coding_chat = coding.create_coding_work_proposal_origin(
            (
                ArchiveEntry("user", "work request"),
                ArchiveEntry(
                    "assistant", "safe proposal",
                    application_event_id="event-" + "c" * 32,
                    application_event_type="coding_work_proposal",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        planning = self.alternate_store("accept-planning")
        planning_chat = planning.create_planning_origin(
            (
                ArchiveEntry("user", "What weekday is it?"),
                ArchiveEntry(
                    "assistant", "Today is Sunday.",
                    application_event_id="event-" + "d" * 32,
                    application_event_type="calendar_information",
                ),
            ),
            selected_provider="selected",
            selected_model="selected-model",
        )
        legacy_store, legacy_identifier = self.legacy_research_archive(
            "accept-legacy"
        )
        legacy_chat = legacy_store.get_chat(legacy_identifier)

        def accepts(chat: object, event_type: str) -> bool:
            return chat_accepts_application_event(
                chat.metadata.completed_turn_count,  # type: ignore[attr-defined]
                chat.entries,  # type: ignore[attr-defined]
                event_type,
            )

        self.assertFalse(accepts(project_chat, "scheduled_work_result"))
        self.assertFalse(accepts(project_chat, "reminder_due"))
        self.assertTrue(accepts(project_chat, "project_result"))
        self.assertTrue(accepts(scheduled_chat, "scheduled_work_result"))
        self.assertTrue(accepts(scheduled_chat, "reminder_due"))
        self.assertFalse(accepts(coding_chat, "scheduled_work_result"))
        self.assertTrue(accepts(coding_chat, "reminder_due"))
        self.assertFalse(accepts(planning_chat, "scheduled_work_result"))
        self.assertFalse(accepts(planning_chat, "reminder_due"))
        self.assertTrue(accepts(planning_chat, "planning_result"))
        self.assertFalse(accepts(legacy_chat, "scheduled_work_result"))
        self.assertFalse(accepts(legacy_chat, "reminder_due"))

    def test_legacy_research_origin_rejects_a_background_reminder(self) -> None:
        store, identifier = self.legacy_research_archive("legacy-reminder")
        before = store.get_chat(identifier)

        with self.assertRaisesRegex(
            ArchiveValidationError, "cannot accept that application event"
        ):
            store.append_application_event(
                identifier,
                expected_revision=before.metadata.revision,
                event_id="event-" + "f" * 32,
                event_type="reminder_due",
                text="Reminder: synthetic task",
            )

        self.assertEqual(store.get_chat(identifier), before)

    def test_project_creation_can_associate_a_legacy_research_chat_without_rewrite(self) -> None:
        store, identifier = self.legacy_research_archive("legacy-project")
        loaded = store.get_chat(identifier)
        with sqlite3.connect(store.path) as connection:
            before = tuple(connection.execute(
                "SELECT sequence,role,text,application_event_id,application_event_type "
                "FROM transcript_entries WHERE chat_id=? ORDER BY sequence",
                (identifier,),
            ))

        project = store.create_project(
            title="Synthetic recovery Project",
            objective="Verify bounded legacy compatibility",
            chat_id=identifier,
            expected_chat_revision=loaded.metadata.revision,
        )

        self.assertEqual(store.get_chat(identifier).metadata.project_id, project.identifier)
        with sqlite3.connect(store.path) as connection:
            after = tuple(connection.execute(
                "SELECT sequence,role,text,application_event_id,application_event_type "
                "FROM transcript_entries WHERE chat_id=? ORDER BY sequence",
                (identifier,),
            ))
        self.assertEqual(after, before)

    def test_legacy_compatibility_keeps_unknown_types_fail_closed(self) -> None:
        store, identifier = self.legacy_research_archive("legacy-unknown")
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE transcript_entries SET application_event_type=? "
                "WHERE chat_id=? AND sequence=2",
                ("deep_research_unrecognized", identifier),
            )
        before = hashlib.sha256(store.path.read_bytes()).hexdigest()
        with self.assertRaises(ArchiveCorruptError):
            store.initialize()
        self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), before)

    def test_legacy_compatibility_keeps_null_event_pairing_fail_closed(self) -> None:
        store, identifier = self.legacy_research_archive("legacy-null-pair")
        with sqlite3.connect(store.path) as connection:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE transcript_entries SET application_event_id=NULL "
                "WHERE chat_id=? AND sequence=2",
                (identifier,),
            )
        before = hashlib.sha256(store.path.read_bytes()).hexdigest()
        with self.assertRaises(ArchiveCorruptError):
            store.initialize()
        self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(), before)

    def test_unavailable_storage_is_distinct(self) -> None:
        blocking_file = Path(self.temporary.name) / "not-a-directory"
        blocking_file.write_text("preserve", encoding="utf-8")
        store = ConversationArchiveStore(blocking_file / "archive.db")
        with self.assertRaises(ArchiveUnavailableError):
            store.initialize()
        self.assertEqual(blocking_file.read_text(encoding="utf-8"), "preserve")

    def test_database_symlink_is_rejected_and_external_target_is_untouched(self) -> None:
        external = Path(self.temporary.name) / "external.db"
        external.write_bytes(b"external database bytes")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(external)
        link_before = os.readlink(self.path)
        target_before = external.read_bytes()
        with self.assertRaises(ArchiveUnavailableError):
            self.store().initialize()
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(os.readlink(self.path), link_before)
        self.assertEqual(external.read_bytes(), target_before)

    def test_parent_and_nested_parent_symlinks_are_rejected_without_traversal(self) -> None:
        for nested in (False, True):
            root = Path(self.temporary.name) / ("nested" if nested else "direct")
            target = Path(self.temporary.name) / ("target-nested" if nested else "target-direct")
            target.mkdir()
            target.joinpath("sentinel").write_bytes(b"preserve")
            if nested:
                root.mkdir()
                root.joinpath("link").symlink_to(target, target_is_directory=True)
                path = root / "link" / "deeper" / "archive.db"
                link = root / "link"
            else:
                root.symlink_to(target, target_is_directory=True)
                path = root / "archive.db"
                link = root
            before_entries = tuple(sorted(item.name for item in target.iterdir()))
            before_link = os.readlink(link)
            with self.subTest(nested=nested), self.assertRaises(ArchiveUnavailableError):
                ConversationArchiveStore(path).initialize()
            self.assertEqual(os.readlink(link), before_link)
            self.assertEqual(tuple(sorted(item.name for item in target.iterdir())), before_entries)
            self.assertEqual(target.joinpath("sentinel").read_bytes(), b"preserve")
            self.assertFalse(target.joinpath("archive.db").exists())
            self.assertFalse(target.joinpath("deeper").exists())

    def test_missing_parent_components_are_created_without_canonical_access(self) -> None:
        path = Path(self.temporary.name) / "one" / "two" / "three" / "archive.db"
        ambiguous = Path(self.temporary.name) / "preexisting-ambiguous-entry"
        ambiguous.write_bytes(b"preserve exactly")
        ambiguous_before = ambiguous.read_bytes()
        self.assertFalse(path.parent.exists())
        ConversationArchiveStore(path).initialize()
        self.assertTrue(path.is_file())
        self.assertTrue(path.parent.is_dir())
        self.assertEqual(ambiguous.read_bytes(), ambiguous_before)

    def test_failed_first_initialization_is_isolated_and_retryable(self) -> None:
        store = self.store()
        unrelated = self.path.parent / "unrelated.txt"
        self.path.parent.mkdir(parents=True)
        unrelated.write_bytes(b"preserve")
        with patch.object(
            store,
            "_create_schema",
            side_effect=sqlite3.OperationalError("injected schema failure"),
        ):
            with self.assertRaisesRegex(ArchiveUnavailableError, "was preserved"):
                store.initialize()
        self.assertFalse(self.path.exists())
        self.assertEqual(unrelated.read_bytes(), b"preserve")
        incomplete = tuple(
            item
            for item in self.path.parent.iterdir()
            if item.name.startswith(".tori.db.incomplete-")
        )
        self.assertEqual(len(incomplete), 1)
        self.assertTrue(incomplete[0].is_file())
        store.initialize()
        self.assertTrue(self.path.is_file())

    def test_entries_created_during_failed_initialization_are_preserved(self) -> None:
        for suffix in ("-journal", "-wal", "-shm"):
            store = self.alternate_store("post-snapshot-" + suffix[1:])
            store.path.parent.mkdir(parents=True)
            sidecar = Path(str(store.path) + suffix)
            unrelated = store.path.parent / "unrelated.bin"
            marker = b"unrelated sidecar-shaped marker " + suffix.encode("ascii")
            unrelated.write_bytes(b"unrelated entry")
            created_identity: tuple[int, int] | None = None

            def create_marker_then_fail(_connection, *, path=sidecar, data=marker):  # type: ignore[no-untyped-def]
                nonlocal created_identity
                path.write_bytes(data)
                marker_stat = path.stat()
                created_identity = (marker_stat.st_dev, marker_stat.st_ino)
                raise sqlite3.OperationalError("injected schema failure")

            with self.subTest(suffix=suffix), patch.object(
                store, "_create_schema", side_effect=create_marker_then_fail
            ):
                with self.assertRaisesRegex(
                    ArchiveUnavailableError, "was preserved"
                ) as raised:
                    store.initialize()

            self.assertIsNotNone(created_identity)
            self.assertEqual(sidecar.read_bytes(), marker)
            self.assertEqual(
                (sidecar.stat().st_dev, sidecar.stat().st_ino), created_identity
            )
            self.assertFalse(store.path.exists())
            self.assertEqual(unrelated.read_bytes(), b"unrelated entry")
            self.assertNotIn(str(store.path), str(raised.exception))

    def test_symlink_created_during_failed_initialization_is_preserved(self) -> None:
        store = self.alternate_store("post-snapshot-symlink")
        store.path.parent.mkdir(parents=True)
        target = Path(self.temporary.name) / "external-sidecar-target"
        target.write_bytes(b"external target bytes")
        sidecar = Path(str(store.path) + "-wal")

        def create_symlink_then_fail(_connection):  # type: ignore[no-untyped-def]
            sidecar.symlink_to(target)
            raise sqlite3.OperationalError("injected schema failure")

        with patch.object(
            store, "_create_schema", side_effect=create_symlink_then_fail
        ):
            with self.assertRaisesRegex(
                ArchiveUnavailableError, "was preserved"
            ) as raised:
                store.initialize()

        self.assertTrue(sidecar.is_symlink())
        self.assertEqual(os.readlink(sidecar), str(target))
        self.assertEqual(target.read_bytes(), b"external target bytes")
        self.assertFalse(store.path.exists())
        self.assertNotIn(str(target), str(raised.exception))

    def test_special_entry_created_during_failed_initialization_is_preserved(self) -> None:
        store = self.alternate_store("post-snapshot-directory")
        store.path.parent.mkdir(parents=True)
        sidecar = Path(str(store.path) + "-shm")

        def create_directory_then_fail(_connection):  # type: ignore[no-untyped-def]
            sidecar.mkdir()
            raise sqlite3.OperationalError("injected schema failure")

        with patch.object(
            store, "_create_schema", side_effect=create_directory_then_fail
        ):
            with self.assertRaisesRegex(
                ArchiveUnavailableError, "was preserved"
            ):
                store.initialize()

        self.assertTrue(sidecar.is_dir())
        self.assertFalse(store.path.exists())

    def test_canonical_substitution_at_publish_is_preserved_and_retryable(self) -> None:
        store = self.alternate_store("publish-replacement")
        store.path.parent.mkdir(parents=True)
        target = Path(self.temporary.name) / "replacement-target"
        target.write_bytes(b"replacement target bytes")
        real_publish = archive_module._rename_without_replacement

        def substitute_then_publish(descriptor, source, destination):  # type: ignore[no-untyped-def]
            os.symlink(str(target), destination, dir_fd=descriptor)
            real_publish(descriptor, source, destination)

        with patch(
            "tori.conversation_archive._rename_without_replacement",
            side_effect=substitute_then_publish,
        ):
            with self.assertRaisesRegex(ArchiveUnavailableError, "was preserved"):
                store.initialize()

        self.assertTrue(store.path.is_symlink())
        self.assertEqual(os.readlink(store.path), str(target))
        self.assertEqual(target.read_bytes(), b"replacement target bytes")
        incomplete = tuple(
            item
            for item in store.path.parent.iterdir()
            if item.name.startswith(f".{store.path.name}.incomplete-")
        )
        self.assertEqual(len(incomplete), 1)
        with sqlite3.connect(incomplete[0]) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        store.path.unlink()
        store.initialize()
        self.assertTrue(store.path.is_file())
        self.assertFalse(store.path.is_symlink())
        self.assertEqual(target.read_bytes(), b"replacement target bytes")

    def test_preexisting_invalid_database_and_sidecars_are_never_removed(self) -> None:
        for offset, payload in enumerate((b"", b"not sqlite")):
            store = self.alternate_store(f"invalid-{offset}")
            store.path.parent.mkdir(parents=True)
            store.path.write_bytes(payload)
            sidecars = {
                suffix: b"preserve-" + suffix.encode("ascii")
                for suffix in ("-journal", "-wal", "-shm")
            }
            for suffix, content in sidecars.items():
                Path(str(store.path) + suffix).write_bytes(content)
            with self.subTest(payload=payload), self.assertRaises(ArchiveCorruptError):
                store.initialize()
            self.assertEqual(store.path.read_bytes(), payload)
            for suffix, content in sidecars.items():
                self.assertEqual(Path(str(store.path) + suffix).read_bytes(), content)

        orphan_store = self.alternate_store("orphan-sidecars")
        orphan_store.path.parent.mkdir(parents=True)
        orphan = Path(str(orphan_store.path) + "-journal")
        orphan.write_bytes(b"preexisting orphan")
        with self.assertRaises(ArchiveUnavailableError):
            orphan_store.initialize()
        self.assertFalse(orphan_store.path.exists())
        self.assertEqual(orphan.read_bytes(), b"preexisting orphan")

    def test_unavailable_atomic_publish_is_reported_and_artifact_is_preserved(self) -> None:
        store = self.store()
        with patch(
            "tori.conversation_archive._rename_without_replacement",
            side_effect=OSError(errno.ENOSYS, "injected unavailable renameat2"),
        ):
            with self.assertRaisesRegex(ArchiveUnavailableError, "was preserved"):
                store.initialize()
        self.assertFalse(self.path.exists())
        self.assertEqual(
            len(tuple(self.path.parent.glob(".tori.db.incomplete-*"))), 1
        )

    def test_collision_retries_then_exhausts_without_overwrite(self) -> None:
        identifiers = iter((FIRST_ID, FIRST_ID, SECOND_ID))
        store = ConversationArchiveStore(
            self.path, clock=lambda: TEST_TIME, identifier_factory=lambda: next(identifiers)
        )
        first = self.create(store)
        second = self.create(store)
        self.assertEqual((first.metadata.identifier, second.metadata.identifier), (FIRST_ID, SECOND_ID))
        with self.assertRaises(ArchiveConflictError):
            self.create(self.store(FIRST_ID))
        self.assertEqual(self.store().get_chat(FIRST_ID), first)

    def test_full_transcript_all_roles_sources_and_metadata_round_trip(self) -> None:
        entries = (
            ArchiveEntry("system", "Visible system notice"),
            ArchiveEntry("user", "  exact user text  "),
            ArchiveEntry("warning", "Visible warning"),
            ArchiveEntry(
                "assistant",
                "Exact answer",
                (
                    ArchiveSource("notes.md", 2, 5),
                    ArchiveSource(r"'escaped\x1f.md'", 1, 1),
                ),
                provider="ollama", model="model-entry",
            ),
            ArchiveEntry("user", "failed question"),
            ArchiveEntry("error", "Visible error"),
        )
        created = self.create(entries=entries)
        loaded = ConversationArchiveStore(self.path).get_chat(FIRST_ID)
        self.assertEqual(created, loaded)
        self.assertEqual([item.role for item in loaded.entries], ["system", "user", "warning", "assistant", "user", "error"])
        self.assertEqual(loaded.entries[1].text, "  exact user text  ")
        self.assertEqual(
            loaded.entries[3].sources,
            (
                ArchiveSource("notes.md", 2, 5),
                ArchiveSource(r"'escaped\x1f.md'", 1, 1),
            ),
        )
        self.assertEqual((loaded.metadata.first_provider, loaded.metadata.latest_model), ("ollama", "model-entry"))

    def test_unknown_roles_and_unsafe_or_malformed_sources_are_rejected(self) -> None:
        invalid_entries = (
            (ArchiveEntry("tool", "hidden"),),
            (ArchiveEntry("assistant", "answer", (ArchiveSource("/raw/path", 1, 1),)),),
            (ArchiveEntry("assistant", "answer", (ArchiveSource("notes.md", 4, 2),)),),
            (ArchiveEntry("user", "question", (ArchiveSource("notes.md", 1, 1),)),),
        )
        for entries in invalid_entries:
            with self.subTest(entries=entries), self.assertRaises(ArchiveValidationError):
                self.create(entries=entries)

    def test_display_escaped_source_paths_are_validated_after_narrow_decoding(self) -> None:
        unsafe = (
            r"'C:\\Users\\private.txt'",
            r"'..\\private.txt'",
            r"'\\\\server\\share.txt'",
            r"'folder\x2fprivate.txt'",
            "/absolute.txt",
        )
        for filename in unsafe:
            entries = (
                ArchiveEntry("user", "q"),
                ArchiveEntry(
                    "assistant", "a", (ArchiveSource(filename, 1, 1),)
                ),
            )
            with self.subTest(filename=filename), self.assertRaises(ArchiveValidationError):
                self.create(entries=entries)
        for filename in ("ordinary.md", "filename with spaces.txt", r"'safe\x1f.md'"):
            store = self.alternate_store("safe-" + str(len(filename)))
            created = self.create(
                store,
                (
                    ArchiveEntry("user", "q"),
                    ArchiveEntry(
                        "assistant", "a", (ArchiveSource(filename, 1, 1),)
                    ),
                ),
            )
            self.assertEqual(created.entries[1].sources[0].filename, filename)

    def test_boolean_source_line_numbers_are_rejected(self) -> None:
        for line_start, line_end in ((True, 1), (1, True)):
            entries = (
                ArchiveEntry("user", "q"),
                ArchiveEntry(
                    "assistant",
                    "a",
                    (ArchiveSource("safe.md", line_start, line_end),),
                ),
            )
            with self.assertRaises(ArchiveValidationError):
                self.create(entries=entries)

    def test_persisted_source_extra_fields_are_rejected_as_invalid_record(self) -> None:
        created = self.create(entries=(
            ArchiveEntry("user", "q"),
            ArchiveEntry("assistant", "a", (ArchiveSource("safe.md", 1, 2),)),
        ))
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE transcript_entries SET sources_json=? WHERE chat_id=? AND sequence=1",
                ('[{"filename":"safe.md","line_start":1,"line_end":2,"path":"/raw"}]', created.metadata.identifier),
            )
        with self.assertRaises(ArchiveCorruptError):
            self.store().get_chat(FIRST_ID)

    def test_labels_cover_whitespace_multiline_controls_unicode_empty_and_length(self) -> None:
        timestamp = "2026-08-02T12:00:00Z"
        cases = (
            ((ArchiveEntry("user", "\n  hello   world \n later"),), "Hello world"),
            ((ArchiveEntry("user", "hello\t  world"),), "Hello world"),
            ((ArchiveEntry("user", "hello\u200bworld"),), r"Hello\u200Bworld"),
            ((ArchiveEntry("user", "こんにちは 世界"),), "こんにちは 世界"),
            ((ArchiveEntry("system", "notice"),), "Chat 2026-08-02T12:00:00Z"),
        )
        for entries, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(derive_chat_label(entries, created_at=timestamp), expected)
        self.assertEqual(len(derive_chat_label((ArchiveEntry("user", "x" * 81),), created_at=timestamp)), 80)

    def test_label_skips_blank_user_entries_and_uses_first_nonblank_line(self) -> None:
        timestamp = "2026-08-02T12:00:00Z"
        cases = (
            (
                (ArchiveEntry("user", "   "), ArchiveEntry("user", "usable later")),
                "Usable later",
            ),
            ((ArchiveEntry("user", "\n \n  first line\nsecond"),), "First line"),
            (
                (ArchiveEntry("user", "\n"), ArchiveEntry("user", "\t")),
                "Chat 2026-08-02T12:00:00Z",
            ),
        )
        for entries, expected in cases:
            self.assertEqual(derive_chat_label(entries, created_at=timestamp), expected)

    def test_labels_remove_fillers_without_fabricating_a_subject(self) -> None:
        timestamp = "2026-08-02T12:00:00Z"
        cases = (
            ("Hi Tori", "Just checking in"),
            ("I have a question", "Just checking in"),
            ("Hi Tori. I want to compare Qwen and Kokoro for TTS.", "TTS engine comparison"),
            ("We need to create a new scheduled backup for tomorrow.", "Create a scheduled backup"),
            ("Let's work on the web UI redesign today.", "Tori UI redesign"),
            ("Let's discuss memory architecture.", "Memory architecture discussion"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    derive_chat_label((ArchiveEntry("user", text),), created_at=timestamp),
                    expected,
                )

    def test_label_fixed_width_escaping_and_boundary_do_not_change_text(self) -> None:
        timestamp = "2026-08-02T12:00:00Z"
        bmp_text = "before\u200bafter"
        non_bmp_text = "before\U000e0001after"
        self.assertEqual(
            derive_chat_label((ArchiveEntry("user", bmp_text),), created_at=timestamp),
            r"Before\u200Bafter",
        )
        self.assertEqual(
            derive_chat_label((ArchiveEntry("user", non_bmp_text),), created_at=timestamp),
            r"Before\U000E0001after",
        )
        boundary_text = "x" * 75 + "\u200b"
        label = derive_chat_label(
            (ArchiveEntry("user", boundary_text),), created_at=timestamp
        )
        self.assertEqual(label, "X" + "x" * 74)
        self.assertLessEqual(len(label), 80)
        self.assertEqual(boundary_text, "x" * 75 + "\u200b")
        fallback_entries = (ArchiveEntry("system", "notice"),)
        self.assertEqual(
            derive_chat_label(fallback_entries, created_at=timestamp),
            derive_chat_label(fallback_entries, created_at=timestamp),
        )

    def test_nul_transcript_is_rejected_before_any_filesystem_work(self) -> None:
        from tori.chats import ChatService, ChatServiceError

        for offset, text in enumerate(("\x00leading", "embedded\x00nul", "trailing\x00")):
            store = self.alternate_store(f"nul-{offset}/missing-parent")
            service = ChatService(store)
            with self.subTest(text=repr(text)), self.assertRaises(ArchiveValidationError):
                store.create_chat(
                    (ArchiveEntry("user", text), ArchiveEntry("assistant", "a")),
                    provider="ollama",
                    model="model-a",
                )
            self.assertFalse(store.path.exists())
            self.assertFalse(store.path.parent.exists())
            with self.assertRaises(ChatServiceError) as raised:
                service.create_chat(
                    (ArchiveEntry("user", text), ArchiveEntry("assistant", "a")),
                    provider="ollama",
                    model="model-a",
                )
            self.assertEqual(raised.exception.code, "invalid_record")
            self.assertNotIn(str(store.path), str(raised.exception))
            self.assertFalse(store.path.parent.exists())

    def test_multiline_unicode_without_nul_round_trips_exactly(self) -> None:
        text = " first line \n第二行 🌿\nlast line  "
        created = self.create(
            entries=(ArchiveEntry("user", text), ArchiveEntry("assistant", "answer"))
        )
        self.assertEqual(created.entries[0].text, text)
        self.assertEqual(self.store().get_chat(FIRST_ID).entries[0].text, text)

    def test_created_updated_opened_revision_and_provider_metadata(self) -> None:
        store = self.store()
        created = self.create(store)
        reconciled = store.reconcile_chat(
            FIRST_ID,
            (
                *self.entries,
                ArchiveEntry("user", "q2"),
                ArchiveEntry(
                    "assistant", "a2",
                    provider="configured-two", model="model-two",
                ),
            ),
            expected_revision=1,
            provider="configured-two",
            model="model-two",
        )
        opened = store.mark_chat_opened(FIRST_ID, expected_revision=2)
        self.assertEqual(opened.metadata.created_at, created.metadata.created_at)
        self.assertGreater(reconciled.metadata.updated_at, created.metadata.updated_at)
        self.assertGreater(opened.metadata.updated_at, reconciled.metadata.updated_at)
        self.assertEqual(opened.metadata.last_opened_at, opened.metadata.updated_at)
        self.assertEqual(opened.metadata.revision, 3)
        self.assertEqual(opened.metadata.first_model, "model-a")
        self.assertEqual(opened.metadata.latest_model, "model-two")
        self.assertEqual(opened.metadata.selected_model, "model-two")

    def test_last_opened_timestamp_bounds_and_equalities(self) -> None:
        for offset, invalid in enumerate(
            ("2026-08-02T11:59:59Z", "2026-08-02T12:00:01Z")
        ):
            store = self.alternate_store(f"opened-invalid-{offset}")
            self.create(store)
            with sqlite3.connect(store.path) as connection:
                connection.execute("PRAGMA ignore_check_constraints=ON")
                connection.execute(
                    "UPDATE chats SET last_opened_at=?", (invalid,)
                )
            before = store.path.read_bytes()
            with self.subTest(invalid=invalid), self.assertRaises(ArchiveCorruptError):
                store.get_chat(FIRST_ID)
            self.assertEqual(store.path.read_bytes(), before)

        store = self.alternate_store("opened-equalities")
        created = self.create(store)
        with sqlite3.connect(store.path) as connection:
            connection.execute(
                "UPDATE chats SET last_opened_at=created_at WHERE identifier=?",
                (FIRST_ID,),
            )
        equal_created = store.get_chat(FIRST_ID)
        self.assertEqual(
            equal_created.metadata.last_opened_at,
            equal_created.metadata.created_at,
        )
        opened = store.mark_chat_opened(FIRST_ID, expected_revision=1)
        self.assertEqual(opened.metadata.last_opened_at, opened.metadata.updated_at)

    def test_repeated_and_backward_clocks_remain_monotonic(self) -> None:
        values = iter(
            (
                TEST_TIME,
                TEST_TIME,
                TEST_TIME - timedelta(hours=1),
            )
        )
        store = self.store(clock=lambda: next(values))
        created = self.create(store)
        opened_once = store.mark_chat_opened(FIRST_ID, expected_revision=1)
        opened_twice = store.mark_chat_opened(FIRST_ID, expected_revision=2)
        self.assertLess(created.metadata.updated_at, opened_once.metadata.updated_at)
        self.assertLess(opened_once.metadata.updated_at, opened_twice.metadata.updated_at)
        self.assertEqual(opened_twice.metadata.last_opened_at, opened_twice.metadata.updated_at)

    def test_listing_is_deterministic_and_contains_no_transcript(self) -> None:
        first = self.create(self.store(FIRST_ID))
        second = self.create(self.store(SECOND_ID), entries=(ArchiveEntry("user", "private marker"), ArchiveEntry("assistant", "private response")))
        listing = self.store().list_chats()
        self.assertEqual([item.identifier for item in listing], [SECOND_ID, FIRST_ID])
        self.assertFalse(hasattr(listing[0], "entries"))
        self.assertNotIn("private response", repr(listing))
        self.assertEqual(first.metadata.updated_at, second.metadata.updated_at)

    def test_active_pointer_set_replace_clear_and_missing_rejection(self) -> None:
        self.create(self.store(FIRST_ID))
        self.create(self.store(SECOND_ID))
        store = self.store()
        self.assertIsNone(store.get_active_chat_id())
        self.assertEqual(store.set_active_chat(FIRST_ID, expected_revision=1), FIRST_ID)
        self.assertEqual(store.set_active_chat(SECOND_ID), SECOND_ID)
        self.assertIsNone(store.set_active_chat(None))
        with self.assertRaises(ArchiveNotFoundError):
            store.set_active_chat("chat-" + "9" * 32)

    def test_stale_revision_and_divergence_are_rejected(self) -> None:
        created = self.create()
        with self.assertRaises(ArchiveStaleRevisionError):
            self.store().reconcile_chat(FIRST_ID, self.entries, expected_revision=2)
        with self.assertRaises(ArchiveDivergenceError):
            self.store().reconcile_chat(
                FIRST_ID,
                (ArchiveEntry("user", "changed"), self.entries[1]),
                expected_revision=created.metadata.revision,
            )
        self.assertEqual(self.store().get_chat(FIRST_ID), created)

    def test_reconcile_exact_noop_suffix_and_retry_do_not_duplicate(self) -> None:
        store = self.store()
        created = self.create(store)
        noop = store.reconcile_chat(FIRST_ID, self.entries, expected_revision=1)
        self.assertEqual(noop, created)
        complete = (*self.entries, ArchiveEntry("user", "q2"), ArchiveEntry("assistant", "a2"))
        appended = store.reconcile_chat(FIRST_ID, complete, expected_revision=1)
        retried = store.reconcile_chat(FIRST_ID, complete, expected_revision=2)
        self.assertEqual(retried, appended)
        self.assertEqual(retried.metadata.entry_count, 4)
        self.assertEqual(retried.metadata.revision, 2)

    def test_reconcile_verifies_exact_commit_before_a_concurrent_later_event(self) -> None:
        class SupersedingReadStore(ConversationArchiveStore):
            inject_later_event = False

            def get_chat(self, identifier):  # type: ignore[no-untyped-def]
                if self.inject_later_event:
                    self.inject_later_event = False
                    other = ConversationArchiveStore(self.path, clock=lambda: TEST_TIME)
                    current = other.get_chat(identifier)
                    other.append_application_event(
                        identifier,
                        expected_revision=current.metadata.revision,
                        event_id="event-" + "a" * 32,
                        event_type="operational_result",
                        text="A distinct later application result.",
                    )
                return super().get_chat(identifier)

        store = SupersedingReadStore(
            self.path, clock=lambda: TEST_TIME, identifier_factory=lambda: FIRST_ID
        )
        created = self.create(store)
        supplied = (
            *created.entries,
            ArchiveEntry("user", "Second exact question"),
            ArchiveEntry(
                "assistant", "Second exact answer", provider="ollama", model="model-a"
            ),
        )
        store.inject_later_event = True

        reconciled = store.reconcile_chat(
            FIRST_ID, supplied, expected_revision=created.metadata.revision
        )

        self.assertEqual(reconciled.metadata.revision, 3)
        self.assertEqual(
            [(entry.role, entry.text) for entry in reconciled.entries[:4]],
            [
                ("user", "First exact question"),
                ("assistant", "First exact answer"),
                ("user", "Second exact question"),
                ("assistant", "Second exact answer"),
            ],
        )
        self.assertEqual(
            [entry.text for entry in reconciled.entries].count("Second exact question"), 1
        )
        self.assertEqual(
            [entry.text for entry in reconciled.entries].count("Second exact answer"), 1
        )
        self.assertEqual(reconciled.entries[-1].application_event_id, "event-" + "a" * 32)

    def test_reconcile_verification_still_rejects_a_missing_committed_suffix(self) -> None:
        store = self.store()
        created = self.create(store)
        supplied = (
            *created.entries,
            ArchiveEntry("user", "Second exact question"),
            ArchiveEntry(
                "assistant", "Second exact answer", provider="ollama", model="model-a"
            ),
        )

        with patch.object(store, "get_chat", return_value=created):
            with self.assertRaises(ArchiveVerificationError):
                store.reconcile_chat(
                    FIRST_ID, supplied, expected_revision=created.metadata.revision
                )

    def test_reconcile_existing_timestamp_assertions_and_unspecified_retry(self) -> None:
        store = self.store()
        created = self.create(store)
        asserted = tuple(
            replace(item, created_at=created.entries[index].created_at)
            for index, item in enumerate(self.entries)
        )
        self.assertEqual(
            store.reconcile_chat(FIRST_ID, asserted, expected_revision=1), created
        )
        mismatched = (
            replace(asserted[0], created_at="2026-08-02T12:00:01Z"),
            asserted[1],
        )
        before = self.path.read_bytes()
        with self.assertRaises(ArchiveDivergenceError):
            store.reconcile_chat(FIRST_ID, mismatched, expected_revision=1)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(
            store.reconcile_chat(FIRST_ID, self.entries, expected_revision=1), created
        )

    def test_reconcile_suffix_preserves_asserted_and_assigns_unspecified_timestamps(self) -> None:
        operation_time = TEST_TIME + timedelta(seconds=10)
        clock_values = iter((TEST_TIME, operation_time))
        store = self.store(clock=lambda: next(clock_values))
        created = self.create(store)
        asserted_time = "2026-08-02T12:00:05Z"
        supplied = (
            *self.entries,
            ArchiveEntry("user", "q2", created_at=asserted_time),
            ArchiveEntry("assistant", "a2"),
        )
        appended = store.reconcile_chat(FIRST_ID, supplied, expected_revision=1)
        self.assertEqual(appended.entries[2].created_at, asserted_time)
        self.assertEqual(appended.entries[3].created_at, appended.metadata.updated_at)
        asserted_retry = tuple(
            replace(item, created_at=appended.entries[index].created_at)
            for index, item in enumerate(supplied)
        )
        self.assertEqual(
            store.reconcile_chat(FIRST_ID, asserted_retry, expected_revision=2),
            appended,
        )
        unspecified_retry = tuple(replace(item, created_at=None) for item in supplied)
        self.assertEqual(
            store.reconcile_chat(FIRST_ID, unspecified_retry, expected_revision=2),
            appended,
        )
        self.assertEqual(store.get_chat(FIRST_ID).metadata.entry_count, 4)
        self.assertEqual(store.get_chat(FIRST_ID).metadata.revision, 2)

    def test_reconcile_rejects_decreasing_or_beyond_updated_suffix_atomically(self) -> None:
        cases = (
            (
                "decreasing",
                TEST_TIME + timedelta(seconds=10),
                ArchiveEntry("user", "q2", created_at="2026-08-02T12:00:09Z"),
                ArchiveEntry("assistant", "a2", created_at="2026-08-02T12:00:08Z"),
            ),
            (
                "beyond-updated",
                TEST_TIME + timedelta(seconds=5),
                ArchiveEntry("user", "q2", created_at="2026-08-02T12:00:06Z"),
                ArchiveEntry("assistant", "a2", created_at="2026-08-02T12:00:06Z"),
            ),
        )
        for name, clock_value, user, assistant in cases:
            store = self.alternate_store(name)
            created = self.create(store)
            timed_store = ConversationArchiveStore(store.path, clock=lambda: clock_value)
            before = store.path.read_bytes()
            with self.subTest(name=name), self.assertRaises(ArchiveValidationError):
                timed_store.reconcile_chat(
                    FIRST_ID,
                    (*self.entries, user, assistant),
                    expected_revision=1,
                )
            self.assertEqual(store.path.read_bytes(), before)
            self.assertEqual(store.get_chat(FIRST_ID), created)

    def test_injected_write_failure_rolls_back(self) -> None:
        store = self.store()
        with patch.object(store, "_insert_entries", side_effect=sqlite3.OperationalError("injected")):
            with self.assertRaises(Exception):
                self.create(store)
        store.initialize()
        self.assertEqual(store.list_chats(), ())

    def test_revision_increments_only_for_durable_changes(self) -> None:
        store = self.store()
        self.create(store)
        self.assertEqual(store.reconcile_chat(FIRST_ID, self.entries, expected_revision=1).metadata.revision, 1)
        changed = store.reconcile_chat(FIRST_ID, self.entries, expected_revision=1, label="Renamed")
        self.assertEqual(changed.metadata.revision, 2)
        self.assertEqual(changed.metadata.label, "Renamed")

    def test_context_policy_and_optional_telemetry_round_trip_without_prompt_data(self) -> None:
        context = ArchiveContext(
            requested_policy="fixed:16384",
            effective_budget=16384,
            estimator_version="lexical-v1",
            estimated_input_tokens=4210,
            included_history_messages=8,
            omitted_history_messages=4,
            actual_prompt_tokens=4000,
            actual_completion_tokens=200,
            actual_total_tokens=4200,
        )
        entries = (
            ArchiveEntry("user", "question"),
            ArchiveEntry("assistant", "answer", provider="lab", model="shared", context=context),
        )
        created = self.store().create_chat(
            entries, provider="lab", model="shared", context_policy="fixed:16384"
        )
        self.assertEqual(created.metadata.selected_context_policy, "fixed:16384")
        self.assertEqual(created.entries[-1].context, context)
        revised = self.store().select_chat_context(
            FIRST_ID, expected_revision=1, policy="auto"
        )
        self.assertEqual(revised.metadata.selected_context_policy, "auto")
        self.assertEqual(revised.entries[-1].context, context)
        with sqlite3.connect(self.path) as connection:
            encoded = connection.execute(
                "SELECT context_json FROM transcript_entries WHERE sequence=1"
            ).fetchone()[0]
        self.assertNotIn("question", encoded)
        self.assertNotIn("answer", encoded)

    def test_model_and_context_selection_commit_atomically_at_one_revision(self) -> None:
        store = self.store()
        created = self.create(store)
        revised = store.select_chat_configuration(
            FIRST_ID,
            expected_revision=created.metadata.revision,
            provider="lab",
            model="shared",
            policy="fixed:32768",
        )
        self.assertEqual(revised.metadata.revision, created.metadata.revision + 1)
        self.assertEqual(revised.metadata.selected_provider, "lab")
        self.assertEqual(revised.metadata.selected_model, "shared")
        self.assertEqual(revised.metadata.selected_context_policy, "fixed:32768")
        self.assertEqual(revised.entries, created.entries)
        with self.assertRaises(ArchiveStaleRevisionError):
            store.select_chat_configuration(
                FIRST_ID,
                expected_revision=created.metadata.revision,
                provider="other",
                model="other",
                policy="auto",
            )
        self.assertEqual(store.get_chat(FIRST_ID), revised)

    def test_delete_verifies_and_updates_active_pointer_only_when_needed(self) -> None:
        self.create(self.store(FIRST_ID))
        second = self.create(self.store(SECOND_ID))
        store = self.store()
        store.set_active_chat(FIRST_ID)
        store.delete_chat(SECOND_ID, expected_revision=second.metadata.revision)
        self.assertEqual(store.get_active_chat_id(), FIRST_ID)
        store.delete_chat(FIRST_ID, expected_revision=1)
        self.assertIsNone(store.get_active_chat_id())
        with self.assertRaises(ArchiveNotFoundError):
            store.get_chat(FIRST_ID)

    def test_foreign_key_and_duplicate_sequence_constraints(self) -> None:
        self.create()
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            values = ("chat-" + "9" * 32, 0, "user", "x", None, None, None, "2026-08-02T12:00:00Z", None, None, None)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transcript_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)", values)
            row = connection.execute("SELECT * FROM transcript_entries WHERE sequence=0").fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO transcript_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(row))

    def test_fresh_create_and_delete_verification_failures_are_reported(self) -> None:
        store = self.store()
        with patch.object(store, "get_chat", return_value=None):
            with self.assertRaises(ArchiveVerificationError):
                self.create(store)
        actual = ConversationArchiveStore(self.path).get_chat(FIRST_ID)
        with patch.object(store, "get_chat", return_value=actual):
            with self.assertRaises(ArchiveVerificationError):
                store.delete_chat(FIRST_ID, expected_revision=1)

    def test_clean_close_leaves_no_sidecars_or_temporary_residue(self) -> None:
        store = self.store()
        self.create(store)
        store.get_chat(FIRST_ID)
        store.list_chats()
        self.assertEqual(
            sorted(path.name for path in self.path.parent.iterdir()),
            [self.path.name],
        )


if __name__ == "__main__":
    unittest.main()
