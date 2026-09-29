"""Controlled, explicit conversation archive schema-5 to schema-6 migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .conversation_archive import (
    SCHEMA5_ARCHIVE_SCHEMA_VERSION,
    ArchiveCorruptError,
    ArchiveVersionError,
    _PROJECTS_SQL,
    _schema5_objects_are_exact,
    _schema6_objects_are_exact,
)
from .conversation_archive_migration import (
    ArchiveMigrationError,
    _open_parent_no_follow,
    _safe_existing_path,
    _same_identity,
    _stage,
)


def migrate_archive_schema5_to6(
    path: Path | str,
    *,
    stage_hook: Callable[[str], None] | None = None,
) -> tuple[int, int, int]:
    """Add empty Project state and nullable chat associations to exact schema 5."""

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
            _validate_schema5(readonly)
            if readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ArchiveMigrationError(
                    "The supplied archive is not in the required DELETE journal mode."
                )
            if readonly.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Archive integrity_check did not return exactly ok.")
            baseline = _capture_schema5(readonly)
        finally:
            readonly.close()
        _stage(stage_hook, "preflight")

        connection = sqlite3.connect(sqlite_path, isolation_level=None, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise ArchiveMigrationError("The archive journal mode changed before migration.")
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if not _same_identity(before_stat, current_stat):
                raise ArchiveMigrationError("The supplied archive changed before migration.")
            _validate_schema5(connection)
            _stage(stage_hook, "transaction_started")
            connection.execute(_PROJECTS_SQL)
            connection.execute(
                "ALTER TABLE chats ADD COLUMN project_id TEXT "
                "REFERENCES projects(identifier) ON DELETE SET NULL"
            )
            cursor = connection.execute(
                "UPDATE archive_metadata SET value=? WHERE key='schema_version' AND value=?",
                ("6", str(SCHEMA5_ARCHIVE_SCHEMA_VERSION)),
            )
            if cursor.rowcount != 1:
                raise ArchiveMigrationError("The archive version changed during migration.")
            if not _schema6_objects_are_exact(connection):
                raise ArchiveMigrationError("The migrated schema-6 archive is not exact.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Foreign-key verification failed before commit.")
            _require_preserved(baseline, _capture_schema6(connection))
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
        verification = sqlite3.connect(
            "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1", uri=True
        )
        with closing(verification):
            integrity = verification.execute("PRAGMA integrity_check").fetchall()
            if len(integrity) != 1 or integrity[0][0] != "ok":
                raise ArchiveMigrationError("Post-migration integrity verification failed.")
            if verification.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Post-migration foreign-key verification failed.")
            final = _capture_schema6(verification)
        _require_preserved(baseline, final)
        after_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not _same_identity(before_stat, after_stat):
            raise ArchiveMigrationError("The archive file identity changed during migration.")
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ArchiveMigrationError("Unexpected sidecar remained after migration.")
        return len(baseline[1]), len(baseline[2]), len(baseline[4])
    except (ArchiveMigrationError, ArchiveCorruptError, ArchiveVersionError):
        raise
    except BaseException as exc:
        message = (
            "Archive migration failed after commit; the archive requires inspection."
            if committed
            else "Archive migration failed safely before commit; schema 5 was preserved."
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


def _validate_schema5(connection: sqlite3.Connection) -> None:
    try:
        metadata = connection.execute("SELECT key,value FROM archive_metadata").fetchall()
    except sqlite3.Error as exc:
        raise ArchiveMigrationError("The supplied database is not a recognized archive.") from exc
    if metadata != [("schema_version", str(SCHEMA5_ARCHIVE_SCHEMA_VERSION))]:
        raise ArchiveMigrationError("The supplied archive is not schema version 5.")
    if not _schema5_objects_are_exact(connection):
        raise ArchiveMigrationError(
            "The supplied schema-5 archive is not exact; it was not modified."
        )
    if connection.execute(
        "SELECT 1 FROM transcript_entries "
        "WHERE application_event_type IN ('project_proposal','project_result') LIMIT 1"
    ).fetchone() is not None:
        raise ArchiveMigrationError(
            "The supplied schema-5 archive contains unsupported Project event data."
        )
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ArchiveMigrationError("The supplied archive has invalid foreign keys.")


def _capture_schema5(connection: sqlite3.Connection):  # type: ignore[no-untyped-def]
    return tuple(
        tuple(tuple(row) for row in connection.execute(query))
        for query in (
            "SELECT key,value FROM archive_metadata ORDER BY key",
            "SELECT * FROM chats ORDER BY identifier",
            "SELECT * FROM transcript_entries ORDER BY chat_id,sequence",
            "SELECT * FROM archive_state ORDER BY singleton",
            "SELECT * FROM memory_extractions ORDER BY extraction_id",
        )
    )


def _capture_schema6(connection: sqlite3.Connection):  # type: ignore[no-untyped-def]
    projects = tuple(tuple(row) for row in connection.execute("SELECT * FROM projects ORDER BY identifier"))
    chats = tuple(tuple(row) for row in connection.execute("SELECT * FROM chats ORDER BY identifier"))
    if projects or any(row[-1] is not None for row in chats):
        raise ArchiveMigrationError("Migration must not infer Projects or associations.")
    return (
        tuple(tuple(row) for row in connection.execute("SELECT key,value FROM archive_metadata ORDER BY key")),
        tuple(row[:-1] for row in chats),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM transcript_entries ORDER BY chat_id,sequence")),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM archive_state ORDER BY singleton")),
        tuple(tuple(row) for row in connection.execute("SELECT * FROM memory_extractions ORDER BY extraction_id")),
        projects,
    )


def _require_preserved(before, after) -> None:  # type: ignore[no-untyped-def]
    if before[1:] != after[1:-1]:
        raise ArchiveMigrationError("Historical archive values were not preserved exactly.")
    if before[0] != (("schema_version", "5"),) or after[0] != (("schema_version", "6"),):
        raise ArchiveMigrationError("Only the archive schema version may change.")
