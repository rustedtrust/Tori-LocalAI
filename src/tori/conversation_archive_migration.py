"""Controlled, explicit conversation archive schema-2 to schema-3 migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .conversation_archive import (
    LEGACY_ARCHIVE_SCHEMA_VERSION,
    SCHEMA3_ARCHIVE_SCHEMA_VERSION,
    ArchiveCorruptError,
    ArchiveVersionError,
    ConversationArchiveStore,
    _CHATS_SQL,
    _ENTRIES_SQL,
    _EVENT_INDEX_SQL,
    _LEGACY_CHATS_SQL,
    _SCHEMA3_CHATS_SQL,
    _SCHEMA3_ENTRIES_SQL,
    _METADATA_SQL,
    _STATE_SQL,
    _normalize_schema_sql,
    _schema3_objects_are_exact,
)


class ArchiveMigrationError(RuntimeError):
    """A transcript-safe migration refusal or failure."""


def migrate_archive_schema(
    path: Path | str,
    *,
    stage_hook: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    """Migrate exactly one supplied regular schema-2 archive while Tori is stopped."""

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
            _validate_legacy_schema(readonly)
            if readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ArchiveMigrationError(
                    "The supplied archive is not in the required DELETE journal mode."
                )
            if readonly.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ArchiveMigrationError("Archive integrity_check did not return exactly ok.")
            baseline = _capture_values(readonly, legacy=True)
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
            _validate_legacy_schema(connection)
            _stage(stage_hook, "transaction_started")
            connection.execute(
                "ALTER TABLE transcript_entries RENAME TO transcript_entries_schema2"
            )
            connection.execute("DROP INDEX transcript_entries_application_event_id_index")
            connection.execute("ALTER TABLE archive_state RENAME TO archive_state_schema2")
            connection.execute("ALTER TABLE chats RENAME TO chats_schema2")
            connection.execute(_SCHEMA3_CHATS_SQL)
            connection.execute(_SCHEMA3_ENTRIES_SQL)
            connection.execute(_EVENT_INDEX_SQL)
            connection.execute(_STATE_SQL)
            connection.execute(
                """
                INSERT INTO chats (
                    identifier,label,created_at,updated_at,last_opened_at,revision,
                    first_provider,first_model,latest_provider,latest_model,
                    selected_provider,selected_model,entry_count,completed_turn_count
                )
                SELECT identifier,label,created_at,updated_at,last_opened_at,revision,
                       first_provider,first_model,latest_provider,latest_model,
                       latest_provider,latest_model,entry_count,completed_turn_count
                FROM chats_schema2 ORDER BY identifier
                """
            )
            connection.execute(
                """
                INSERT INTO transcript_entries (
                    chat_id,sequence,role,text,sources_json,provider,model,created_at,
                    application_event_id,application_event_type
                )
                SELECT chat_id,sequence,role,text,sources_json,provider,model,created_at,
                       application_event_id,application_event_type
                FROM transcript_entries_schema2 ORDER BY chat_id,sequence
                """
            )
            connection.execute(
                "INSERT INTO archive_state SELECT * FROM archive_state_schema2"
            )
            _stage(stage_hook, "copied_values")
            connection.execute("DROP TABLE transcript_entries_schema2")
            connection.execute("DROP TABLE archive_state_schema2")
            connection.execute("DROP TABLE chats_schema2")
            cursor = connection.execute(
                "UPDATE archive_metadata SET value=? WHERE key='schema_version' AND value=?",
                (str(SCHEMA3_ARCHIVE_SCHEMA_VERSION), str(LEGACY_ARCHIVE_SCHEMA_VERSION)),
            )
            if cursor.rowcount != 1:
                raise ArchiveMigrationError("The archive version changed during migration.")
            if not _schema3_objects_are_exact(connection):
                raise ArchiveMigrationError("Migrated schema 3 is not exact.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Foreign-key verification failed before commit.")
            candidate = _capture_values(connection, legacy=False)
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
        with closing(sqlite3.connect(
            "file:" + quote(os.fspath(target), safe="/") + "?mode=ro&immutable=1",
            uri=True,
        )) as verification:
            integrity = verification.execute("PRAGMA integrity_check").fetchall()
            if len(integrity) != 1 or integrity[0][0] != "ok":
                raise ArchiveMigrationError("Post-migration integrity verification failed.")
            if verification.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ArchiveMigrationError("Post-migration foreign-key verification failed.")
            final = _capture_values(verification, legacy=False)
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
            else "Archive migration failed safely before commit; the source version was preserved."
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


def _safe_existing_path(path: Path | str) -> Path:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
        raise ArchiveMigrationError("An exact safe archive path is required.")
    target = Path(os.path.abspath(os.path.normpath(raw)))
    if not target.name:
        raise ArchiveMigrationError("An exact archive file path is required.")
    return target


def _open_parent_no_follow(target: Path) -> int:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for component in target.parent.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        os.close(descriptor)
        raise ArchiveMigrationError(
            "The supplied archive path has an unavailable or unsafe ancestor."
        ) from exc


def _validate_legacy_schema(connection: sqlite3.Connection) -> None:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "chats": _LEGACY_CHATS_SQL,
        "transcript_entries": _SCHEMA3_ENTRIES_SQL,
        "archive_state": _STATE_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql)) for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
        (
            "index", "transcript_entries_application_event_id_index",
            "transcript_entries", _normalize_schema_sql(_EVENT_INDEX_SQL),
        ),
    }
    actual = {
        (kind, name, table, _normalize_schema_sql(sql) if isinstance(sql, str) else None)
        for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    }
    metadata_table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='archive_metadata'"
    ).fetchone()
    if metadata_table is None:
        raise ArchiveMigrationError("The supplied database is not a recognized archive.")
    try:
        metadata = connection.execute("SELECT key,value FROM archive_metadata").fetchall()
    except sqlite3.Error as exc:
        raise ArchiveMigrationError("The supplied database is not a recognized archive.") from exc
    if len(metadata) != 1 or metadata[0][0] != "schema_version":
        raise ArchiveMigrationError("The supplied archive has invalid schema metadata.")
    if metadata[0][1] != str(LEGACY_ARCHIVE_SCHEMA_VERSION):
        raise ArchiveMigrationError(
            f"Invalid source schema version {metadata[0][1]!r}; expected version 2."
        )
    if actual != expected:
        raise ArchiveMigrationError("The supplied schema-2 archive is not exact; it was not modified.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ArchiveMigrationError("The supplied archive has invalid foreign keys.")


def _capture_values(
    connection: sqlite3.Connection, *, legacy: bool
) -> tuple[tuple[object, ...], ...]:
    chats = connection.execute(
        "SELECT * FROM chats ORDER BY identifier"
    ).fetchall()
    if legacy:
        projected_chats = tuple(tuple(row) for row in chats)
    else:
        projected_chats = tuple(tuple((*row[:10], *row[12:])) for row in chats)
        if any(tuple(row[10:12]) != tuple(row[8:10]) for row in chats):
            raise ArchiveMigrationError("Migrated selected-model state was not preserved.")
    return (
        tuple(tuple(row) for row in connection.execute(
            "SELECT key,value FROM archive_metadata ORDER BY key"
        )),
        projected_chats,
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM transcript_entries ORDER BY chat_id,sequence"
        )),
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM archive_state ORDER BY singleton"
        )),
    )


def _require_preserved(
    before: tuple[tuple[object, ...], ...],
    after: tuple[tuple[object, ...], ...],
) -> None:
    if before[1:] != after[1:]:
        raise ArchiveMigrationError("Historical archive values were not preserved exactly.")
    if before[0] != (("schema_version", "2"),) or after[0] != (("schema_version", "3"),):
        raise ArchiveMigrationError("Only the archive schema version may change.")


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stage(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)
