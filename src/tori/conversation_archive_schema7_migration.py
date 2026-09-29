"""Controlled, explicit conversation archive schema-6 to schema-7 migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .conversation_archive import (
    ARCHIVE_SCHEMA_VERSION,
    PREVIOUS_ARCHIVE_SCHEMA_VERSION,
    ArchiveCorruptError,
    ArchiveVersionError,
    ConversationArchiveStore,
    _create_schema7_project_objects,
    _schema6_objects_are_exact,
)
from .conversation_archive_migration import (
    ArchiveMigrationError,
    _open_parent_no_follow,
    _safe_existing_path,
    _same_identity,
    _stage,
)


def migrate_archive_schema6_to7(
    path: Path | str,
    *,
    stage_hook: Callable[[str], None] | None = None,
) -> tuple[int, int, int, int]:
    """Add empty structured Project tables to one exact schema-6 archive."""

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
            _validate_schema6(readonly)
            if readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ArchiveMigrationError(
                    "The supplied archive is not in the required DELETE journal mode."
                )
            if readonly.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Archive integrity_check did not return exactly ok.")
            baseline = _capture_schema6(readonly)
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
            _validate_schema6(connection)
            _stage(stage_hook, "transaction_started")
            _create_schema7_project_objects(connection)
            _stage(stage_hook, "structures_created")
            cursor = connection.execute(
                "UPDATE archive_metadata SET value=? WHERE key='schema_version' AND value=?",
                (str(ARCHIVE_SCHEMA_VERSION), str(PREVIOUS_ARCHIVE_SCHEMA_VERSION)),
            )
            if cursor.rowcount != 1:
                raise ArchiveMigrationError("The archive version changed during migration.")
            ConversationArchiveStore._validate_schema(connection)
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Pre-commit integrity verification failed.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Pre-commit foreign-key verification failed.")
            candidate = _capture_schema7(connection)
            _require_preserved(baseline, candidate)
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
            "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1",
            uri=True,
        )
        with closing(verification):
            ConversationArchiveStore._validate_schema(verification)
            if verification.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Post-migration integrity verification failed.")
            if verification.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Post-migration foreign-key verification failed.")
            final = _capture_schema7(verification)
        _require_preserved(baseline, final)
        after_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not _same_identity(before_stat, after_stat):
            raise ArchiveMigrationError("The archive file identity changed during migration.")
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ArchiveMigrationError("Unexpected sidecar remained after migration.")
        return (
            len(baseline[1]),
            len(baseline[2]),
            len(baseline[3]),
            len(baseline[5]),
        )
    except ArchiveMigrationError:
        raise
    except (ArchiveCorruptError, ArchiveVersionError) as exc:
        message = (
            "Archive migration failed after commit; the archive requires inspection."
            if committed
            else "Archive migration failed safely before commit; schema 6 was preserved."
        )
        raise ArchiveMigrationError(message) from exc
    except BaseException as exc:
        message = (
            "Archive migration failed after commit; the archive requires inspection."
            if committed
            else "Archive migration failed safely before commit; schema 6 was preserved."
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


def _validate_schema6(connection: sqlite3.Connection) -> None:
    try:
        metadata = connection.execute("SELECT key,value FROM archive_metadata").fetchall()
    except sqlite3.Error as exc:
        raise ArchiveMigrationError("The supplied database is not a recognized archive.") from exc
    if metadata != [("schema_version", str(PREVIOUS_ARCHIVE_SCHEMA_VERSION))]:
        raise ArchiveMigrationError("The supplied archive is not schema version 6.")
    if not _schema6_objects_are_exact(connection):
        raise ArchiveMigrationError(
            "The supplied schema-6 archive is not exact; it was not modified."
        )
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ArchiveMigrationError("The supplied archive has invalid foreign keys.")


def _capture_schema6(
    connection: sqlite3.Connection,
) -> tuple[tuple[tuple[object, ...], ...], ...]:
    return tuple(
        tuple(tuple(row) for row in connection.execute(query))
        for query in (
            "SELECT key,value FROM archive_metadata ORDER BY key",
            "SELECT * FROM projects ORDER BY identifier",
            "SELECT * FROM chats ORDER BY identifier",
            "SELECT * FROM transcript_entries ORDER BY chat_id,sequence",
            "SELECT * FROM archive_state ORDER BY singleton",
            "SELECT * FROM memory_extractions ORDER BY extraction_id",
        )
    )


def _capture_schema7(
    connection: sqlite3.Connection,
) -> tuple[tuple[tuple[object, ...], ...], ...]:
    base = _capture_schema6(connection)
    additions = tuple(
        tuple(tuple(row) for row in connection.execute(query))
        for query in (
            "SELECT * FROM project_state ORDER BY project_id",
            "SELECT * FROM project_decisions ORDER BY identifier",
            "SELECT * FROM project_questions ORDER BY identifier",
            "SELECT * FROM project_plan_items ORDER BY identifier",
            "SELECT * FROM project_links ORDER BY identifier",
            "SELECT * FROM project_context_receipts ORDER BY chat_id,assistant_sequence",
        )
    )
    if any(additions):
        raise ArchiveMigrationError(
            "Migration must not infer structured Project state, links, or context receipts."
        )
    return (*base, *additions)


def _require_preserved(
    before: tuple[tuple[tuple[object, ...], ...], ...],
    after: tuple[tuple[tuple[object, ...], ...], ...],
) -> None:
    if before[1:] != after[1:len(before)]:
        raise ArchiveMigrationError("Historical archive values were not preserved exactly.")
    if any(after[len(before):]):
        raise ArchiveMigrationError("New schema-7 Project tables must be empty.")
    if before[0] != (("schema_version", "6"),) or after[0] != (("schema_version", "7"),):
        raise ArchiveMigrationError("Only the archive schema version may change.")
