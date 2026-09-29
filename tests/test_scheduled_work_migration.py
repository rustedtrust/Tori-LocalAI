from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from tori.scheduled_work import (
    SQLiteScheduledWorkStore,
    ScheduledWorkCorruptError,
    ScheduledWorkVersionError,
    _AUTHORIZATIONS_SQL,
    _DEFINITION_INDEX_SQL,
    _LEGACY_DEFINITIONS_SQL,
    _LEGACY_NOTIFICATIONS_SQL,
    _METADATA_SQL,
    _RUN_INDEX_SQL,
    _RUN_JOB_INDEX_SQL,
    _RUNS_SQL,
    _STATE_SQL,
)
from tori.scheduled_work_migration import (
    ScheduledWorkMigrationError,
    migrate_scheduled_work_schema,
)


WORK_ID = "work-" + "a" * 32
AUTH_ID = "authorization-" + "b" * 32
RUN_ID = "run-" + "c" * 32
EVENT_ID = "event-" + "d" * 32
CHAT_ID = "chat-" + "e" * 32
STAMP = "2026-08-11T12:00:00Z"
FINISHED = "2026-08-11T12:01:00Z"


def schema1_store(path: Path) -> None:
    arguments = "{}"
    schedule = (
        '{"kind":"one_shot","occurrence_utc":"2026-08-11T12:00:00Z",'
        '"timezone":"America/Chicago"}'
    )
    connection = sqlite3.connect(path)
    for sql in (
        _METADATA_SQL,
        _STATE_SQL,
        _LEGACY_DEFINITIONS_SQL,
        _AUTHORIZATIONS_SQL,
        _RUNS_SQL,
        _LEGACY_NOTIFICATIONS_SQL,
        _DEFINITION_INDEX_SQL,
        _RUN_INDEX_SQL,
        _RUN_JOB_INDEX_SQL,
    ):
        connection.execute(sql)
    connection.execute(
        "INSERT INTO scheduled_work_metadata VALUES ('schema_version','1')"
    )
    connection.execute("INSERT INTO scheduled_work_state VALUES (1,8)")
    connection.execute(
        "INSERT INTO scheduled_work_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            WORK_ID,
            "Historical backup",
            "tori.backup",
            1,
            arguments,
            schedule,
            "one_shot",
            "one_shot",
            "America/Chicago",
            "run_when_available",
            "completed",
            AUTH_ID,
            None,
            None,
            None,
            STAMP,
            FINISHED,
            None,
            None,
            FINISHED,
            2,
        ),
    )
    connection.execute(
        "INSERT INTO scheduled_authorizations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            AUTH_ID,
            WORK_ID,
            1,
            "tori.backup",
            1,
            arguments,
            hashlib.sha256(arguments.encode()).hexdigest(),
            schedule,
            hashlib.sha256(schedule.encode()).hexdigest(),
            "one_shot",
            "run_when_available",
            STAMP,
            "explicit_conversation_confirmation",
            "exhausted",
            STAMP,
        ),
    )
    connection.execute(
        "INSERT INTO scheduled_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            RUN_ID,
            WORK_ID,
            1,
            AUTH_ID,
            "tori.backup",
            1,
            "one_shot:2026-08-11T12:00:00Z",
            STAMP,
            STAMP,
            STAMP,
            FINISHED,
            "succeeded",
            1,
            '{"identifier":"historical"}',
            None,
            None,
            0,
            None,
            None,
            3,
        ),
    )
    connection.execute(
        "INSERT INTO scheduled_notifications VALUES (?,?,?,?,?,?)",
        (RUN_ID, EVENT_ID, "archived", STAMP, FINISHED, CHAT_ID),
    )
    connection.commit()
    connection.close()


class ScheduledWorkMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "scheduled.db"
        schema1_store(self.path)

    def test_normal_startup_requires_explicit_migration_without_mutation(self) -> None:
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ScheduledWorkVersionError, "explicit 1-to-2"):
            SQLiteScheduledWorkStore(self.path).initialize()
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_exact_migration_preserves_all_values_and_adds_null_origins(self) -> None:
        before = sqlite3.connect(self.path)
        try:
            baseline = {
                table: before.execute(f"SELECT * FROM {table}").fetchall()
                for table in (
                    "scheduled_work_state",
                    "scheduled_work_definitions",
                    "scheduled_authorizations",
                    "scheduled_runs",
                    "scheduled_notifications",
                )
            }
        finally:
            before.close()
        self.assertEqual(migrate_scheduled_work_schema(self.path), (1, 1, 1, 1))
        store = SQLiteScheduledWorkStore(self.path)
        definition = store.get_definition(WORK_ID)
        notification = store._notification(RUN_ID)
        self.assertIsNone(definition.origin_chat_id)
        self.assertIsNone(notification.origin_chat_id)
        self.assertEqual(notification.chat_id, CHAT_ID)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)]
            )
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(
                connection.execute("SELECT * FROM scheduled_work_state").fetchall(),
                baseline["scheduled_work_state"],
            )
            self.assertEqual(
                [row[:-1] for row in connection.execute(
                    "SELECT * FROM scheduled_work_definitions"
                ).fetchall()],
                baseline["scheduled_work_definitions"],
            )
            self.assertEqual(
                connection.execute("SELECT * FROM scheduled_authorizations").fetchall(),
                baseline["scheduled_authorizations"],
            )
            self.assertEqual(
                connection.execute("SELECT * FROM scheduled_runs").fetchall(),
                baseline["scheduled_runs"],
            )
            self.assertEqual(
                [row[:-1] for row in connection.execute(
                    "SELECT * FROM scheduled_notifications"
                ).fetchall()],
                baseline["scheduled_notifications"],
            )

    def test_failure_before_commit_rolls_back_and_post_commit_stops(self) -> None:
        before = self.path.read_bytes()
        with self.assertRaises(ScheduledWorkMigrationError):
            migrate_scheduled_work_schema(
                self.path,
                stage_hook=lambda stage: (_ for _ in ()).throw(RuntimeError("stop"))
                if stage == "origin_columns_added"
                else None,
            )
        self.assertEqual(self.path.read_bytes(), before)
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM scheduled_work_metadata"
                ).fetchone(),
                ("1",),
            )

        with self.assertRaisesRegex(ScheduledWorkMigrationError, "after commit"):
            migrate_scheduled_work_schema(
                self.path,
                stage_hook=lambda stage: (_ for _ in ()).throw(RuntimeError("lost"))
                if stage == "committed"
                else None,
            )
        SQLiteScheduledWorkStore(self.path).initialize()

    def test_lookalike_symlink_sidecar_and_repeat_are_refused(self) -> None:
        lookalike = Path(self.temporary.name) / "lookalike.db"
        schema1_store(lookalike)
        with sqlite3.connect(lookalike) as connection:
            connection.execute("DROP INDEX scheduled_work_due_index")
        before = lookalike.read_bytes()
        with self.assertRaises(ScheduledWorkMigrationError):
            migrate_scheduled_work_schema(lookalike)
        self.assertEqual(lookalike.read_bytes(), before)
        with self.assertRaises(ScheduledWorkCorruptError):
            SQLiteScheduledWorkStore(lookalike).initialize()

        link = Path(self.temporary.name) / "link.db"
        link.symlink_to(self.path)
        with self.assertRaises(ScheduledWorkMigrationError):
            migrate_scheduled_work_schema(link)
        sidecar = Path(str(self.path) + "-wal")
        sidecar.write_bytes(b"ambiguous")
        with self.assertRaises(ScheduledWorkMigrationError):
            migrate_scheduled_work_schema(self.path)
        self.assertEqual(sidecar.read_bytes(), b"ambiguous")
        sidecar.unlink()
        migrate_scheduled_work_schema(self.path)
        with self.assertRaises(ScheduledWorkMigrationError):
            migrate_scheduled_work_schema(self.path)

    def test_cli_requires_exact_path_and_reports_only_counts(self) -> None:
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrate-scheduled-work-schema"
        )
        result = subprocess.run(
            [sys.executable, str(script), str(self.path)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("schema 1 -> 2", result.stdout)
        self.assertIn("definitions=1", result.stdout)
        self.assertNotIn("Historical backup", result.stdout + result.stderr)
        missing = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        self.assertNotEqual(missing.returncode, 0)


if __name__ == "__main__":
    unittest.main()
