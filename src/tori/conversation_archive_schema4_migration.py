"""Controlled, explicit conversation archive schema-3 to schema-4 migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .conversation_archive import (
    SCHEMA3_ARCHIVE_SCHEMA_VERSION,
    ArchiveCorruptError,
    ArchiveVersionError,
    ConversationArchiveStore,
    _SCHEMA5_CHATS_SQL,
    _ENTRIES_SQL,
    _EVENT_INDEX_SQL,
    _STATE_SQL,
    _schema4_objects_are_exact,
    _schema3_objects_are_exact,
)
from .conversation_archive_migration import (
    ArchiveMigrationError,
    _open_parent_no_follow,
    _safe_existing_path,
    _same_identity,
    _stage,
)

SCHEMA4_VERSION = 4


def migrate_archive_schema3_to4(
    path: Path | str,
    *,
    stage_hook: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """Migrate exactly one supplied schema-3 archive while Tori is stopped."""

    target = _safe_existing_path(path)
    parent = _open_parent_no_follow(target)
    descriptor: int | None = None
    connection: sqlite3.Connection | None = None
    committed = False
    try:
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ArchiveMigrationError(
                    "Archive sidecar state is present; stop Tori and inspect it before migration."
                )
        before_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before_stat.st_mode):
            raise ArchiveMigrationError("The supplied archive is not a regular file.")
        descriptor = os.open(
            target.name,
            os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        if not _same_identity(before_stat, os.fstat(descriptor)):
            raise ArchiveMigrationError("The supplied archive changed during safe open.")
        sqlite_path = f"/proc/self/fd/{parent}/{target.name}"
        readonly = sqlite3.connect(
            "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1",
            uri=True,
        )
        try:
            _validate_schema3(readonly)
            if readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ArchiveMigrationError(
                    "The supplied archive is not in the required DELETE journal mode."
                )
            if readonly.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Archive integrity_check did not return exactly ok.")
            baseline = _capture_schema3(readonly)
        finally:
            readonly.close()
        _stage(stage_hook, "preflight")

        connection = sqlite3.connect(sqlite_path, isolation_level=None, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA secure_delete=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise ArchiveMigrationError("The archive journal mode changed before migration.")
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if not _same_identity(before_stat, current_stat):
                raise ArchiveMigrationError("The supplied archive changed before migration.")
            _validate_schema3(connection)
            _stage(stage_hook, "transaction_started")
            connection.execute("ALTER TABLE transcript_entries RENAME TO transcript_entries_schema3")
            connection.execute("DROP INDEX transcript_entries_application_event_id_index")
            connection.execute("ALTER TABLE archive_state RENAME TO archive_state_schema3")
            connection.execute("ALTER TABLE chats RENAME TO chats_schema3")
            connection.execute(_SCHEMA5_CHATS_SQL)
            connection.execute(_ENTRIES_SQL)
            connection.execute(_EVENT_INDEX_SQL)
            connection.execute(_STATE_SQL)
            connection.execute(
                """
                INSERT INTO chats (
                    identifier,label,created_at,updated_at,last_opened_at,revision,
                    first_provider,first_model,latest_provider,latest_model,
                    selected_provider,selected_model,entry_count,completed_turn_count,
                    selected_context_policy
                )
                SELECT identifier,label,created_at,updated_at,last_opened_at,revision,
                       first_provider,first_model,latest_provider,latest_model,
                       selected_provider,selected_model,entry_count,completed_turn_count,
                       'auto'
                FROM chats_schema3 ORDER BY identifier
                """
            )
            connection.execute(
                """
                INSERT INTO transcript_entries (
                    chat_id,sequence,role,text,sources_json,provider,model,created_at,
                    application_event_id,application_event_type,context_json
                )
                SELECT chat_id,sequence,role,text,sources_json,provider,model,created_at,
                       application_event_id,application_event_type,NULL
                FROM transcript_entries_schema3 ORDER BY chat_id,sequence
                """
            )
            connection.execute("INSERT INTO archive_state SELECT * FROM archive_state_schema3")
            _stage(stage_hook, "copied_values")
            connection.execute("DROP TABLE transcript_entries_schema3")
            connection.execute("DROP TABLE archive_state_schema3")
            connection.execute("DROP TABLE chats_schema3")
            cursor = connection.execute(
                "UPDATE archive_metadata SET value=? WHERE key='schema_version' AND value=?",
                (str(SCHEMA4_VERSION), str(SCHEMA3_ARCHIVE_SCHEMA_VERSION)),
            )
            if cursor.rowcount != 1:
                raise ArchiveMigrationError("The archive version changed during migration.")
            if not _schema4_objects_are_exact(connection):
                raise ArchiveMigrationError("Migrated schema 4 is not exact.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Foreign-key verification failed before commit.")
            _require_preserved(baseline, _capture_schema4(connection))
            _stage(stage_hook, "validated_before_commit")
            connection.execute("COMMIT")
            committed = True
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        connection.close()
        connection = None
        _stage(stage_hook, "committed")
        with closing(sqlite3.connect(sqlite_path)) as verification:
            if not _schema4_objects_are_exact(verification):
                raise ArchiveMigrationError("Post-migration schema 4 is not exact.")
            integrity = verification.execute("PRAGMA integrity_check").fetchall()
            if len(integrity) != 1 or integrity[0][0] != "ok":
                raise ArchiveMigrationError("Post-migration integrity verification failed.")
            if verification.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Post-migration foreign-key verification failed.")
            final = _capture_schema4(verification)
        _require_preserved(baseline, final)
        after_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not _same_identity(before_stat, after_stat):
            raise ArchiveMigrationError("The archive file identity changed during migration.")
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ArchiveMigrationError("Unexpected sidecar remained after migration.")
        return len(baseline[1]), len(baseline[2])
    except (ArchiveMigrationError, ArchiveCorruptError, ArchiveVersionError):
        raise
    except BaseException as exc:
        message = (
            "Archive migration failed after commit; the archive requires inspection."
            if committed
            else "Archive migration failed safely before commit; schema 3 was preserved."
        )
        raise ArchiveMigrationError(message) from exc
    finally:
        if connection is not None:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _validate_schema3(connection: sqlite3.Connection) -> None:
    try:
        metadata = connection.execute(
            "SELECT key,value FROM archive_metadata"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ArchiveMigrationError("The supplied database is not a recognized archive.") from exc
    if metadata != [("schema_version", str(SCHEMA3_ARCHIVE_SCHEMA_VERSION))]:
        raise ArchiveMigrationError("The supplied archive is not schema version 3.")
    if not _schema3_objects_are_exact(connection):
        raise ArchiveMigrationError("The supplied schema-3 archive is not exact; it was not modified.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ArchiveMigrationError("The supplied archive has invalid foreign keys.")


def _capture_schema3(connection: sqlite3.Connection) -> tuple[tuple[tuple[object, ...], ...], ...]:
    return (
        tuple(tuple(row) for row in connection.execute("SELECT key,value FROM archive_metadata ORDER BY key")),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM chats ORDER BY identifier")),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM transcript_entries ORDER BY chat_id,sequence")),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM archive_state ORDER BY singleton")),
    )


def _capture_schema4(connection: sqlite3.Connection) -> tuple[tuple[tuple[object, ...], ...], ...]:
    chats = connection.execute("SELECT * FROM chats ORDER BY identifier").fetchall()
    entries = connection.execute(
        "SELECT * FROM transcript_entries ORDER BY chat_id,sequence"
    ).fetchall()
    if any(row[-1] != "auto" for row in chats) or any(row[-1] is not None for row in entries):
        raise ArchiveMigrationError("Migrated context defaults are invalid.")
    return (
        tuple(tuple(row) for row in connection.execute("SELECT key,value FROM archive_metadata ORDER BY key")),
        tuple(tuple(row[:-1]) for row in chats),
        tuple(tuple(row[:-1]) for row in entries),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM archive_state ORDER BY singleton")),
    )


def _require_preserved(before, after) -> None:  # type: ignore[no-untyped-def]
    if before[1:] != after[1:]:
        raise ArchiveMigrationError("Historical archive values were not preserved exactly.")
    if before[0] != (("schema_version", "3"),) or after[0] != (("schema_version", "4"),):
        raise ArchiveMigrationError("Only the archive schema version may change.")
