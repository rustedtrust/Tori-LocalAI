#!/usr/bin/env python3
"""Snapshot, compare, and inspect Tori runtime data without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from typing import Any


Snapshot = dict[str, Any]

_CURRENT_MEMORY_SCHEMA_VERSION = "3"
_PREVIOUS_MEMORY_SCHEMA_VERSION = "2"
_MEMORY_METADATA_TABLE_SQL = """
CREATE TABLE memory_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_MEMORIES_TABLE_SQL = """
CREATE TABLE memories (
    identifier TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN ('general', 'preference', 'project', 'goal', 'routine', 'constraint')
    ),
    sensitivity TEXT NOT NULL CHECK (sensitivity = 'ordinary'),
    provenance TEXT NOT NULL CHECK (
        provenance IN (
            'explicit_user_command',
            'legacy_explicit_user_command',
            'automatic_direct_user_statement',
            'user_confirmed_inferred_candidate',
            'user_confirmed_correction_update'
        )
    ),
    source_chat_id TEXT,
    source_user_sequence INTEGER,
    extraction_provider TEXT,
    extraction_model TEXT,
    user_confirmed INTEGER NOT NULL CHECK (user_confirmed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_MEMORIES_NORMALIZED_TEXT_INDEX_SQL = """
CREATE INDEX memories_normalized_text_index
ON memories(lower(trim(text)))
"""
_MEMORY_EXTRACTION_EFFECTS_TABLE_SQL = """
CREATE TABLE memory_extraction_effects (
    effect_id TEXT PRIMARY KEY CHECK (
        length(effect_id) = 39
        AND substr(effect_id, 1, 7) = 'effect-'
        AND substr(effect_id, 8) NOT GLOB '*[^0-9a-f]*'
    ),
    extraction_id TEXT NOT NULL CHECK (
        length(extraction_id) = 40
        AND substr(extraction_id, 1, 8) = 'extract-'
        AND substr(extraction_id, 9) NOT GLOB '*[^0-9a-f]*'
    ),
    candidate_index INTEGER NOT NULL CHECK (
        typeof(candidate_index) = 'integer' AND candidate_index BETWEEN 0 AND 2
    ),
    action TEXT NOT NULL CHECK (
        action IN ('automatic_create', 'confirmed_create', 'confirmed_update')
    ),
    outcome TEXT NOT NULL CHECK (
        outcome IN ('created', 'updated', 'duplicate', 'stale')
    ),
    result_memory_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (extraction_id, candidate_index, action)
)
"""
_CURRENT_MEMORY_COLUMNS = {
    "memory_metadata": (
        ("key", "TEXT", 0, 1),
        ("value", "TEXT", 1, 0),
    ),
    "memories": (
        ("identifier", "TEXT", 0, 1),
        ("text", "TEXT", 1, 0),
        ("category", "TEXT", 1, 0),
        ("sensitivity", "TEXT", 1, 0),
        ("provenance", "TEXT", 1, 0),
        ("source_chat_id", "TEXT", 0, 0),
        ("source_user_sequence", "INTEGER", 0, 0),
        ("extraction_provider", "TEXT", 0, 0),
        ("extraction_model", "TEXT", 0, 0),
        ("user_confirmed", "INTEGER", 1, 0),
        ("created_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ),
}
_CODING_WORK_COLUMNS = {
    "coding_work_metadata": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
    "coding_work_state": (("singleton", "INTEGER", 0, 1), ("revision", "INTEGER", 1, 0)),
    "coding_work": (
        ("identifier", "TEXT", 0, 1), ("objective", "TEXT", 1, 0),
        ("acceptance_criteria", "TEXT", 0, 0), ("workspace_root", "TEXT", 1, 0),
        ("project_id", "TEXT", 0, 0), ("origin_chat_id", "TEXT", 0, 0),
        ("state", "TEXT", 1, 0), ("current_authorization_id", "TEXT", 0, 0),
        ("current_run_id", "TEXT", 0, 0), ("revision", "INTEGER", 1, 0),
        ("created_at_utc", "TEXT", 1, 0), ("started_at_utc", "TEXT", 0, 0),
        ("updated_at_utc", "TEXT", 1, 0), ("terminal_at_utc", "TEXT", 0, 0),
        ("progress_json", "TEXT", 0, 0), ("result_json", "TEXT", 0, 0),
    ),
    "coding_work_authorizations": (
        ("identifier", "TEXT", 0, 1), ("work_id", "TEXT", 1, 0),
        ("work_revision", "INTEGER", 1, 0), ("authority_json", "TEXT", 1, 0),
        ("authority_digest", "TEXT", 1, 0),
        ("confirmation_provenance", "TEXT", 1, 0), ("status", "TEXT", 1, 0),
        ("granted_at_utc", "TEXT", 1, 0), ("status_changed_at_utc", "TEXT", 1, 0),
    ),
    "coding_work_runs": (
        ("identifier", "TEXT", 0, 1), ("work_id", "TEXT", 1, 0),
        ("authorization_id", "TEXT", 1, 0), ("adapter_id", "TEXT", 1, 0),
        ("adapter_version", "INTEGER", 1, 0), ("harness_session_id", "TEXT", 0, 0),
        ("launch_correlation_id", "TEXT", 1, 0), ("connection_state", "TEXT", 1, 0),
        ("last_event_sequence", "INTEGER", 1, 0), ("event_cursor", "TEXT", 0, 0),
        ("reconciliation_prior_state", "TEXT", 0, 0), ("created_at_utc", "TEXT", 1, 0),
        ("started_at_utc", "TEXT", 0, 0), ("last_observed_at_utc", "TEXT", 0, 0),
        ("ended_at_utc", "TEXT", 0, 0), ("failure_code", "TEXT", 0, 0),
        ("failure_message", "TEXT", 0, 0), ("revision", "INTEGER", 1, 0),
    ),
    "coding_work_directives": (
        ("identifier", "TEXT", 0, 1), ("work_id", "TEXT", 1, 0),
        ("run_id", "TEXT", 1, 0), ("authorization_id", "TEXT", 1, 0),
        ("kind", "TEXT", 1, 0), ("instruction", "TEXT", 0, 0),
        ("source_chat_id", "TEXT", 0, 0), ("status", "TEXT", 1, 0),
        ("delivery_receipt", "TEXT", 0, 0), ("failure_code", "TEXT", 0, 0),
        ("revision", "INTEGER", 1, 0), ("created_at_utc", "TEXT", 1, 0),
        ("updated_at_utc", "TEXT", 1, 0), ("delivered_at_utc", "TEXT", 0, 0),
    ),
    "coding_work_events": (
        ("identifier", "TEXT", 0, 1), ("work_id", "TEXT", 1, 0),
        ("run_id", "TEXT", 0, 0), ("work_sequence", "INTEGER", 1, 0),
        ("kind", "TEXT", 1, 0), ("deduplication_key", "TEXT", 0, 0),
        ("payload_json", "TEXT", 1, 0), ("occurred_at_utc", "TEXT", 1, 0),
        ("recorded_at_utc", "TEXT", 1, 0),
    ),
}
_RESEARCH_COLUMNS = {
    "research_metadata": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
    "research_jobs": (
        ("identifier", "TEXT", 0, 1), ("objective", "TEXT", 1, 0),
        ("origin_chat_id", "TEXT", 0, 0), ("origin_chat_revision", "INTEGER", 0, 0),
        ("project_id", "TEXT", 0, 0), ("state", "TEXT", 1, 0),
        ("revision", "INTEGER", 1, 0), ("authorization_id", "TEXT", 0, 0),
        ("attempt_id", "TEXT", 0, 0), ("worker_type", "TEXT", 0, 0),
        ("phase", "TEXT", 0, 0), ("progress_message", "TEXT", 0, 0),
        ("limits_json", "TEXT", 1, 0), ("created_at_utc", "TEXT", 1, 0),
        ("updated_at_utc", "TEXT", 1, 0), ("started_at_utc", "TEXT", 0, 0),
        ("terminal_at_utc", "TEXT", 0, 0), ("report", "TEXT", 0, 0),
        ("validation_json", "TEXT", 0, 0), ("metrics_json", "TEXT", 0, 0),
        ("failure_code", "TEXT", 0, 0), ("failure_message", "TEXT", 0, 0),
    ),
    "research_authorizations": (
        ("identifier", "TEXT", 0, 1), ("job_id", "TEXT", 1, 0),
        ("job_revision", "INTEGER", 1, 0), ("authority_json", "TEXT", 1, 0),
        ("authority_digest", "TEXT", 1, 0),
        ("confirmation_provenance", "TEXT", 1, 0),
        ("granted_at_utc", "TEXT", 1, 0),
    ),
    "research_events": (
        ("job_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
        ("kind", "TEXT", 1, 0), ("payload_json", "TEXT", 1, 0),
        ("occurred_at_utc", "TEXT", 1, 0),
    ),
        "research_sources": (
            ("job_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
            ("url", "TEXT", 1, 0), ("title", "TEXT", 1, 0),
            ("source_type", "TEXT", 1, 0), ("authority_reason", "TEXT", 1, 0),
            ("search_provider", "TEXT", 1, 0),
            ("retrieved_at_utc", "TEXT", 0, 0), ("content_hash", "TEXT", 0, 0),
        ("used_in_report", "INTEGER", 1, 0),
    ),
}
_RESEARCH_LEDGER_COLUMNS = {
    "research_claims": (
        ("job_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
        ("text", "TEXT", 1, 0), ("support_state", "TEXT", 1, 0),
        ("report_location", "TEXT", 1, 0), ("finalization", "TEXT", 1, 0),
        ("note", "TEXT", 0, 0),
    ),
    "research_evidence": (
        ("job_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
        ("source_sequence", "INTEGER", 1, 0), ("excerpt", "TEXT", 1, 0),
        ("source_locator", "TEXT", 1, 0), ("extract_index", "INTEGER", 1, 0),
        ("excerpt_hash", "TEXT", 1, 0),
    ),
    "research_claim_evidence": (
        ("job_id", "TEXT", 1, 1), ("claim_sequence", "INTEGER", 1, 2),
        ("evidence_sequence", "INTEGER", 1, 3),
    ),
}
_RESEARCH_LEDGER_FOREIGN_KEYS = {
    "research_claims": frozenset({
        ("research_jobs", (("job_id", "identifier"),)),
    }),
    "research_evidence": frozenset({
        ("research_sources", (("job_id", "job_id"), ("source_sequence", "sequence"))),
    }),
    "research_claim_evidence": frozenset({
        ("research_claims", (("job_id", "job_id"), ("claim_sequence", "sequence"))),
        ("research_evidence", (("job_id", "job_id"), ("evidence_sequence", "sequence"))),
    }),
}
_MIGRATED_RESEARCH_SOURCE_COLUMNS = (
    ("job_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
    ("url", "TEXT", 1, 0), ("title", "TEXT", 1, 0),
    ("source_type", "TEXT", 1, 0), ("authority_reason", "TEXT", 1, 0),
    ("retrieved_at_utc", "TEXT", 0, 0), ("content_hash", "TEXT", 0, 0),
    ("used_in_report", "INTEGER", 1, 0),
    ("search_provider", "TEXT", 1, 0),
)


class RuntimeSafetyError(RuntimeError):
    """Raised when a runtime tree cannot be inspected safely."""


def _hash_regular_file(path: Path, expected: os.stat_result) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        actual = os.fstat(descriptor)
        if not stat.S_ISREG(actual.st_mode) or (
            actual.st_dev,
            actual.st_ino,
        ) != (expected.st_dev, expected.st_ino):
            raise RuntimeSafetyError(
                f"Runtime entry changed while it was being read: {path}"
            )
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _entry(path: Path, relative: str) -> dict[str, Any]:
    metadata = path.lstat()
    mode = metadata.st_mode
    result: dict[str, Any] = {
        "path": relative,
        "mode": stat.S_IMODE(mode),
    }
    if stat.S_ISREG(mode):
        result.update(
            type="file",
            size=metadata.st_size,
            sha256=_hash_regular_file(path, metadata),
        )
    elif stat.S_ISDIR(mode):
        result["type"] = "directory"
    elif stat.S_ISLNK(mode):
        result.update(type="symlink", target=os.readlink(path))
    else:
        result.update(type="special", file_type=stat.S_IFMT(mode))
    return result


def capture_runtime(root: Path) -> Snapshot:
    """Return a deterministic no-follow description of a complete runtime tree."""

    root = Path(root)
    if not root.exists() and not root.is_symlink():
        return {"present": False, "entries": []}

    entries: list[dict[str, Any]] = []

    def visit(path: Path, relative: str) -> None:
        item = _entry(path, relative)
        entries.append(item)
        if item["type"] != "directory":
            return
        try:
            children = sorted(os.scandir(path), key=lambda child: child.name)
        except OSError as exc:
            raise RuntimeSafetyError(
                f"Runtime directory could not be inspected: {path}"
            ) from exc
        for child in children:
            child_relative = child.name if relative == "." else f"{relative}/{child.name}"
            visit(Path(child.path), child_relative)

    visit(root, ".")
    return {"present": True, "entries": entries}


def write_snapshot(root: Path, destination: Path) -> None:
    snapshot = capture_runtime(root)
    Path(destination).write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_snapshot(path: Path) -> Snapshot:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeSafetyError(f"Runtime snapshot is unreadable: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise RuntimeSafetyError(f"Runtime snapshot has an invalid shape: {path}")
    return value


def compare_snapshots(before: Snapshot, after: Snapshot) -> list[str]:
    """Describe mutations without repairing, deleting, or rewriting anything."""

    differences: list[str] = []
    if before.get("present") != after.get("present"):
        differences.append(
            "runtime root presence changed: "
            f"before={before.get('present')} after={after.get('present')}"
        )
    before_entries = {item["path"]: item for item in before["entries"]}
    after_entries = {item["path"]: item for item in after["entries"]}
    for path in sorted(before_entries.keys() - after_entries.keys()):
        differences.append(f"removed runtime entry: {path}: {before_entries[path]}")
    for path in sorted(after_entries.keys() - before_entries.keys()):
        differences.append(f"added runtime entry: {path}: {after_entries[path]}")
    for path in sorted(before_entries.keys() & after_entries.keys()):
        if before_entries[path] != after_entries[path]:
            differences.append(
                f"changed runtime entry: {path}: "
                f"before={before_entries[path]} after={after_entries[path]}"
            )
    return differences


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def _normalize_schema_sql(value: str) -> str:
    return "".join(value.split()).lower()


def _is_exact_memory_schema(connection: sqlite3.Connection, version: str) -> bool:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    expected_tables_set = {"memory_metadata", "memories"}
    if version == _CURRENT_MEMORY_SCHEMA_VERSION:
        expected_tables_set.add("memory_extraction_effects")
    if tables != expected_tables_set:
        return False

    for table_name, expected in _CURRENT_MEMORY_COLUMNS.items():
        columns = tuple(
            (row[1], row[2].upper(), row[3], row[5])
            for row in connection.execute(f"PRAGMA table_info({table_name})")
        )
        if columns != expected:
            return False

    expected_tables = {
        "memory_metadata": _MEMORY_METADATA_TABLE_SQL,
        "memories": _MEMORIES_TABLE_SQL,
    }
    if version == _CURRENT_MEMORY_SCHEMA_VERSION:
        expected_tables["memory_extraction_effects"] = (
            _MEMORY_EXTRACTION_EFFECTS_TABLE_SQL
        )
    for table_name, expected_sql in expected_tables.items():
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if (
            row is None
            or not isinstance(row[0], str)
            or _normalize_schema_sql(row[0])
            != _normalize_schema_sql(expected_sql)
        ):
            return False

    indexes = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND sql IS NOT NULL"
        )
    }
    return set(indexes) == {"memories_normalized_text_index"} and (
        _normalize_schema_sql(indexes["memories_normalized_text_index"])
        == _normalize_schema_sql(_MEMORIES_NORMALIZED_TEXT_INDEX_SQL)
    )


def _is_exact_coding_work_schema(connection: sqlite3.Connection, version: str) -> bool:
    if version != "1":
        return False
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != {
        "coding_work_metadata", "coding_work_state", "coding_work",
        "coding_work_authorizations", "coding_work_runs",
        "coding_work_directives", "coding_work_events",
    }:
        return False
    for table, expected in _CODING_WORK_COLUMNS.items():
        columns = tuple(
            (row[1], row[2].upper(), row[3], row[5])
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
        if columns != expected:
            return False
    indexes = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
    }
    if indexes != {
        "coding_work_state_index", "coding_work_directive_delivery_index",
        "coding_work_event_history_index",
    }:
        return False
    state = connection.execute(
        "SELECT singleton,revision FROM coding_work_state"
    ).fetchall()
    valid_state = (
        len(state) == 1
        and state[0][0] == 1
        and isinstance(state[0][1], int)
        and not isinstance(state[0][1], bool)
        and state[0][1] >= 1
    )
    return valid_state and connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []


def _is_exact_research_schema(connection: sqlite3.Connection, version: str) -> bool:
    if version not in {"2", "3"}:
        return False
    expected_tables = _RESEARCH_COLUMNS if version == "2" else {**_RESEARCH_COLUMNS, **_RESEARCH_LEDGER_COLUMNS}
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    if tables != set(expected_tables):
        return False
    for table, expected in expected_tables.items():
        columns = tuple(
            (row[1], row[2].upper(), row[3], row[5])
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
        accepted = (expected,)
        if table == "research_sources":
            # Schema 1 -> 2 added provider provenance with ALTER TABLE, so a
            # legitimately upgraded store has the new column last. Fresh V2
            # stores place it before retrieval metadata. Both are exact V2.
            accepted = (expected, _MIGRATED_RESEARCH_SOURCE_COLUMNS)
        if columns not in accepted:
            return False
    if version == "3":
        for table, expected in _RESEARCH_LEDGER_FOREIGN_KEYS.items():
            grouped: dict[int, list[tuple[int, str, str, str, str, str, str]]] = {}
            for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
                grouped.setdefault(row[0], []).append(
                    (row[1], row[2], row[3], row[4], row[5], row[6], row[7])
                )
            actual = set()
            for rows in grouped.values():
                rows.sort()
                if any(
                    sequence != index or update != "NO ACTION" or delete != "NO ACTION" or match != "NONE"
                    for index, (sequence, _, _, _, update, delete, match) in enumerate(rows)
                ) or len({target for _, target, *_ in rows}) != 1:
                    return False
                actual.add((rows[0][1], tuple((source, target) for _, _, source, target, *_ in rows)))
            if len(actual) != len(grouped) or actual != expected:
                return False
    indexes = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        )
    }
    return indexes == {"research_jobs_state"} and connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []


def inspect_runtime(root: Path) -> tuple[bool, list[str]]:
    """Inspect regular SQLite databases read-only and report canonical metadata."""

    root = Path(root)
    snapshot = capture_runtime(root)
    lines: list[str] = []
    failed = False
    if not snapshot["present"]:
        return True, [
            "Runtime directory is absent; no canonical data was created.",
            "Canonical memory: absent (accepted; not created).",
            "Canonical conversation archive: absent (accepted; not created).",
            "Canonical operational store: absent (accepted; not created).",
            "Canonical scheduled-work store: absent (accepted; not created).",
            "Canonical Coding Work store: absent (accepted; not created).",
        ]

    entries = {item["path"]: item for item in snapshot["entries"]}
    lines.append(f"Runtime inventory: {len(entries)} entries (including runtime root).")
    for relative, item in sorted(entries.items()):
        if item["type"] == "symlink":
            lines.append(f"Runtime symlink preserved: {relative} -> {item['target']}")
        elif item["type"] == "special":
            lines.append(f"Runtime special entry preserved: {relative}")

    known = {
        "memory/tori_memory.db": (
            "memory_metadata",
            "memories",
            (_PREVIOUS_MEMORY_SCHEMA_VERSION, _CURRENT_MEMORY_SCHEMA_VERSION),
        ),
        "conversations/tori_conversations.db": (
            "archive_metadata",
            "chats",
            "transcript_entries",
            ("1", "2", "3", "4", "5", "6", "7"),
        ),
        "tasks/tori_tasks.db": (
            "operational_metadata",
            "operational_state",
            "tasks",
            "reminders",
            "reminder_deliveries",
            ("1",),
        ),
        "scheduled_work/tori_scheduled_work.db": (
            "scheduled_work_metadata",
            "scheduled_work_state",
            "scheduled_work_definitions",
            "scheduled_authorizations",
            "scheduled_runs",
            "scheduled_notifications",
            ("1", "2"),
        ),
        "coding_work/tori_coding_work.db": (
            "coding_work_metadata",
            "coding_work",
            "coding_work_runs",
            "coding_work_directives",
            "coding_work_events",
            ("1",),
        ),
        "research/tori_research.db": (
            "research_metadata", "research_jobs", "research_authorizations",
            "research_events", "research_sources", ("2", "3"),
        ),
        "supervised_terminal/tori_execution_policy.db": (
            "policy_metadata", "policy_rules", "execution_grants", ("1",),
        ),
        "supervised_terminal/tori_terminal_receipts.db": (
            "receipt_metadata", "terminal_receipts", ("1", "2"),
        ),
    }
    for relative, (metadata_table, *table_and_version) in known.items():
        *count_tables, expected_versions = table_and_version
        item = entries.get(relative)
        label = (
            "Canonical memory" if relative.startswith("memory/")
            else "Canonical operational store" if relative.startswith("tasks/")
            else "Canonical scheduled-work store" if relative.startswith("scheduled_work/")
            else "Canonical Coding Work store" if relative.startswith("coding_work/")
            else "Canonical Research store" if relative.startswith("research/")
            else "Canonical conversation archive"
        )
        if item is None:
            lines.append(f"{label}: absent (accepted; not created).")
            continue
        if item["type"] != "file":
            lines.append(f"{label}: cannot inspect non-regular entry at {relative}.")
            failed = True
            continue
        path = root / relative
        try:
            connection = _readonly_connection(path)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                row = connection.execute(
                    f"SELECT value FROM {metadata_table} WHERE key='schema_version'"
                ).fetchone()
                schema = None if row is None else row[0]
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in count_tables
                }
                exact_schema = (
                    _is_exact_memory_schema(connection, schema)
                    if relative == "memory/tori_memory.db"
                    else _is_exact_coding_work_schema(connection, schema)
                    if relative == "coding_work/tori_coding_work.db"
                    else _is_exact_research_schema(connection, schema)
                    if relative == "research/tori_research.db"
                    else True
                )
            finally:
                connection.close()
        except sqlite3.Error as exc:
            lines.append(f"{label}: read-only SQLite inspection failed ({type(exc).__name__}).")
            failed = True
            continue
        count_text = " ".join(f"{table}={count}" for table, count in counts.items())
        exact_schema_text = (
            f" exact_schema={'yes' if exact_schema else 'no'}"
            if relative in {
                "memory/tori_memory.db", "coding_work/tori_coding_work.db",
                "research/tori_research.db",
            }
            else ""
        )
        lines.append(
            f"{label}: path={relative} size={item['size']} sha256={item['sha256']} "
            f"integrity={integrity} schema_version={schema}"
            f"{exact_schema_text} {count_text}".rstrip()
        )
        failed |= (
            integrity != "ok"
            or schema not in expected_versions
            or not exact_schema
        )

    for relative, item in sorted(entries.items()):
        if relative in known or item["type"] != "file" or not relative.endswith(".db"):
            continue
        try:
            connection = _readonly_connection(root / relative)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.Error as exc:
            lines.append(
                f"Additional runtime database {relative}: read-only inspection failed "
                f"({type(exc).__name__})."
            )
            failed = True
            continue
        lines.append(
            f"Additional runtime database: path={relative} size={item['size']} "
            f"sha256={item['sha256']} integrity={integrity}"
        )
        failed |= integrity != "ok"
    return not failed, lines


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("root", type=Path)
    snapshot.add_argument("destination", type=Path)
    compare = subparsers.add_parser("compare")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "snapshot":
            write_snapshot(arguments.root, arguments.destination)
            print(f"Captured runtime snapshot: {arguments.destination}")
            return 0
        if arguments.command == "compare":
            differences = compare_snapshots(
                read_snapshot(arguments.before), read_snapshot(arguments.after)
            )
            if differences:
                print("Canonical runtime mutation detected; no repair was attempted.")
                for difference in differences:
                    print(difference)
                return 1
            print("Canonical runtime tree is unchanged.")
            return 0
        passed, lines = inspect_runtime(arguments.root)
        for line in lines:
            print(line)
        return 0 if passed else 1
    except (OSError, RuntimeSafetyError) as exc:
        print(f"Runtime safety check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
