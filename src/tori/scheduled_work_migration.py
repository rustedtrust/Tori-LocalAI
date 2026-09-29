"""Controlled, explicit Scheduled Work schema-1 to schema-2 migration."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .scheduled_work import (
    LEGACY_SCHEDULED_WORK_SCHEMA_VERSION,
    SCHEDULED_WORK_SCHEMA_VERSION,
    SQLiteScheduledWorkStore,
    ScheduledWorkCorruptError,
    ScheduledWorkVersionError,
    _legacy_scheduled_schema_is_exact,
)


class ScheduledWorkMigrationError(RuntimeError):
    """A provenance-safe migration refusal or failure."""


_ORIGIN_COLUMN_SQL = """
origin_chat_id TEXT CHECK (origin_chat_id IS NULL OR (
    length(origin_chat_id) = 37
    AND substr(origin_chat_id, 1, 5) = 'chat-'
    AND substr(origin_chat_id, 6) NOT GLOB '*[^0-9a-f]*'
))
"""


def migrate_scheduled_work_schema(
    path: Path | str,
    *,
    stage_hook: Callable[[str], None] | None = None,
) -> tuple[int, int, int, int]:
    """Migrate one exact supplied schema-1 store while Tori is stopped."""

    target = _safe_existing_path(path)
    parent = _open_parent_no_follow(target)
    descriptor: int | None = None
    connection: sqlite3.Connection | None = None
    committed = False
    try:
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ScheduledWorkMigrationError(
                    "Scheduled-work sidecar state is present; stop Tori and inspect it before migration."
                )
        before_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before_stat.st_mode):
            raise ScheduledWorkMigrationError("The supplied store is not a regular file.")
        descriptor = os.open(
            target.name,
            os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent,
        )
        if not _same_identity(before_stat, os.fstat(descriptor)):
            raise ScheduledWorkMigrationError("The supplied store changed during safe open.")
        sqlite_path = f"/proc/self/fd/{parent}/{target.name}"
        readonly = sqlite3.connect(
            "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1",
            uri=True,
        )
        try:
            _validate_source(readonly)
            if readonly.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
                raise ScheduledWorkMigrationError(
                    "The supplied store is not in the required DELETE journal mode."
                )
            if readonly.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ScheduledWorkMigrationError(
                    "Scheduled-work integrity_check did not return exactly ok."
                )
            baseline = _capture_values(readonly, legacy=True)
        finally:
            readonly.close()
        _stage(stage_hook, "preflight")

        connection = sqlite3.connect(sqlite_path, isolation_level=None, timeout=5.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            raise ScheduledWorkMigrationError(
                "The scheduled-work journal mode changed before migration."
            )
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
            if not _same_identity(before_stat, current_stat):
                raise ScheduledWorkMigrationError(
                    "The supplied store changed before migration."
                )
            _validate_source(connection)
            _stage(stage_hook, "transaction_started")
            connection.execute(
                "ALTER TABLE scheduled_work_definitions ADD COLUMN "
                + _ORIGIN_COLUMN_SQL.strip()
            )
            connection.execute(
                "ALTER TABLE scheduled_notifications ADD COLUMN "
                + _ORIGIN_COLUMN_SQL.strip()
            )
            _stage(stage_hook, "origin_columns_added")
            cursor = connection.execute(
                "UPDATE scheduled_work_metadata SET value=? "
                "WHERE key='schema_version' AND value=?",
                (
                    str(SCHEDULED_WORK_SCHEMA_VERSION),
                    str(LEGACY_SCHEDULED_WORK_SCHEMA_VERSION),
                ),
            )
            if cursor.rowcount != 1:
                raise ScheduledWorkMigrationError(
                    "The scheduled-work version changed during migration."
                )
            SQLiteScheduledWorkStore._validate_schema(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ScheduledWorkMigrationError(
                    "Foreign-key verification failed before commit."
                )
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
        with closing(SQLiteScheduledWorkStore(target)._connect()) as verification:
            integrity = verification.execute("PRAGMA integrity_check").fetchall()
            if len(integrity) != 1 or integrity[0][0] != "ok":
                raise ScheduledWorkMigrationError(
                    "Post-migration integrity verification failed."
                )
            if verification.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ScheduledWorkMigrationError(
                    "Post-migration foreign-key verification failed."
                )
            final = _capture_values(verification, legacy=False)
        _require_preserved(baseline, final)
        after_stat = os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        if not _same_identity(before_stat, after_stat):
            raise ScheduledWorkMigrationError(
                "The scheduled-work file identity changed during migration."
            )
        for suffix in ("-journal", "-wal", "-shm"):
            if os.path.lexists(os.fspath(target) + suffix):
                raise ScheduledWorkMigrationError(
                    "Unexpected scheduled-work sidecar remained after migration."
                )
        return tuple(len(baseline[index]) for index in (2, 3, 4, 5))  # type: ignore[return-value]
    except (
        ScheduledWorkMigrationError,
        ScheduledWorkCorruptError,
        ScheduledWorkVersionError,
    ):
        raise
    except BaseException as exc:
        message = (
            "Scheduled-work migration failed after commit; the store requires inspection."
            if committed
            else "Scheduled-work migration failed safely before commit; schema 1 was preserved."
        )
        raise ScheduledWorkMigrationError(message) from exc
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
        raise ScheduledWorkMigrationError("An exact safe scheduled-work path is required.")
    target = Path(os.path.abspath(os.path.normpath(raw)))
    if not target.name:
        raise ScheduledWorkMigrationError("An exact scheduled-work file path is required.")
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
        raise ScheduledWorkMigrationError(
            "The supplied scheduled-work path has an unavailable or unsafe ancestor."
        ) from exc


def _validate_source(connection: sqlite3.Connection) -> None:
    if not _legacy_scheduled_schema_is_exact(connection):
        try:
            metadata = connection.execute(
                "SELECT key,value FROM scheduled_work_metadata"
            ).fetchall()
        except sqlite3.Error as exc:
            raise ScheduledWorkMigrationError(
                "The supplied database is not a recognized scheduled-work store."
            ) from exc
        version = metadata[0][1] if len(metadata) == 1 else None
        if version != str(LEGACY_SCHEDULED_WORK_SCHEMA_VERSION):
            raise ScheduledWorkMigrationError(
                f"Invalid source schema version {version!r}; expected version 1."
            )
        raise ScheduledWorkMigrationError(
            "The supplied schema-1 scheduled-work store is not exact; it was not modified."
        )
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ScheduledWorkMigrationError(
            "The supplied scheduled-work store has invalid foreign keys."
        )


def _capture_values(
    connection: sqlite3.Connection, *, legacy: bool
) -> tuple[tuple[object, ...], ...]:
    definitions = tuple(tuple(row) for row in connection.execute(
        "SELECT * FROM scheduled_work_definitions ORDER BY identifier"
    ))
    notifications = tuple(tuple(row) for row in connection.execute(
        "SELECT * FROM scheduled_notifications ORDER BY run_id"
    ))
    if not legacy:
        if any(row[-1] is not None for row in definitions + notifications):
            raise ScheduledWorkMigrationError(
                "Historical conversational-origin fields are not null."
            )
        definitions = tuple(row[:-1] for row in definitions)
        notifications = tuple(row[:-1] for row in notifications)
    return (
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM scheduled_work_metadata ORDER BY key"
        )),
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM scheduled_work_state ORDER BY singleton"
        )),
        definitions,
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM scheduled_authorizations ORDER BY identifier"
        )),
        tuple(tuple(row) for row in connection.execute(
            "SELECT * FROM scheduled_runs ORDER BY identifier"
        )),
        notifications,
    )


def _require_preserved(
    before: tuple[tuple[object, ...], ...],
    after: tuple[tuple[object, ...], ...],
) -> None:
    if before[1:] != after[1:]:
        raise ScheduledWorkMigrationError(
            "Historical scheduled-work values were not preserved exactly."
        )
    if before[0] != (("schema_version", "1"),) or after[0] != (("schema_version", "2"),):
        raise ScheduledWorkMigrationError(
            "Only the scheduled-work schema version may change."
        )


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _stage(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)
