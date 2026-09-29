"""Concrete durable domain state for Tori-owned coding work."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
import ctypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from urllib.parse import quote

from .time_context import format_utc_timestamp, parse_utc_timestamp


CODING_WORK_SCHEMA_VERSION = 1
CODING_WORK_CAPABILITY = "tori.coding.work"
MAX_OBJECTIVE_LENGTH = 8_000
MAX_ACCEPTANCE_LENGTH = 8_000
MAX_PROVENANCE_LENGTH = 512
MAX_PROGRESS_JSON_LENGTH = 16_000
MAX_RESULT_JSON_LENGTH = 32_000
MAX_FAILURE_LENGTH = 1_000
MAX_DIRECTIVE_LENGTH = 8_000
MAX_EVENT_JSON_LENGTH = 16_000
MAX_ADAPTER_VALUE_LENGTH = 128
MAX_DURABLE_EVENTS_PER_WORK = 500

WORK_STATES = frozenset({
    "awaiting_authorization", "queued", "starting", "running", "waiting",
    "cancelling", "reconciling", "completed", "failed", "cancelled",
})
TERMINAL_WORK_STATES = frozenset({"completed", "failed", "cancelled"})
NONTERMINAL_OBSERVED_STATES = frozenset({
    "starting", "running", "waiting", "cancelling",
})
RUN_STATES = frozenset({"starting", "attached", "reconciling", "missing", "closed"})
AUTHORIZATION_STATES = frozenset({"active", "superseded", "revoked"})
DIRECTIVE_KINDS = frozenset({"instruction", "cancel"})
DIRECTIVE_STATES = frozenset({"pending", "delivering", "delivered", "failed"})
EVENT_KINDS = frozenset({
    "created", "authorized", "queued", "starting", "session_confirmed",
    "progress", "waiting", "instruction_queued", "cancellation_requested",
    "reconciling", "verification", "completed", "failed", "cancelled",
})

_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "awaiting_authorization": frozenset({"queued"}),
    "queued": frozenset({"starting"}),
    "starting": frozenset({"running", "cancelling", "reconciling", "failed"}),
    "running": frozenset({
        "waiting", "cancelling", "reconciling", "completed", "failed", "cancelled",
    }),
    "waiting": frozenset({
        "running", "cancelling", "reconciling", "completed", "failed", "cancelled",
    }),
    "cancelling": frozenset({"reconciling", "completed", "failed", "cancelled"}),
    "reconciling": frozenset({
        "starting", "running", "waiting", "completed", "failed", "cancelled",
    }),
    "completed": frozenset({"awaiting_authorization"}),
    "failed": frozenset({"awaiting_authorization"}),
    "cancelled": frozenset({"awaiting_authorization"}),
}

_WORK_ID = re.compile(r"^coding-work-[0-9a-f]{32}$")
_AUTH_ID = re.compile(r"^coding-auth-[0-9a-f]{32}$")
_RUN_ID = re.compile(r"^coding-run-[0-9a-f]{32}$")
_DIRECTIVE_ID = re.compile(r"^coding-directive-[0-9a-f]{32}$")
_EVENT_ID = re.compile(r"^coding-event-[0-9a-f]{32}$")
_PROJECT_ID = re.compile(r"^project-[0-9a-f]{32}$")
_CHAT_ID = re.compile(r"^chat-[0-9a-f]{32}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CodingWorkError(RuntimeError):
    """Base safe Coding Work failure."""

    code = "coding_work_error"


class CodingWorkValidationError(CodingWorkError):
    code = "invalid_coding_work"


class CodingWorkNotFoundError(CodingWorkError):
    code = "not_found"


class CodingWorkStaleRevisionError(CodingWorkError):
    code = "stale_revision"


class CodingWorkConflictError(CodingWorkError):
    code = "conflict"


class CodingWorkVersionError(CodingWorkError):
    code = "unsupported_version"


class CodingWorkCorruptError(CodingWorkError):
    code = "store_corrupt"


class CodingWorkUnavailableError(CodingWorkError):
    code = "store_unavailable"


@dataclass(frozen=True, slots=True)
class CodingWorkAuthority:
    """Versioned first-slice authority containing enforceable resource bounds."""

    workspace_root: str
    read_allowed: bool
    modify_allowed: bool
    sandboxed_execution_allowed: bool
    schema_version: int = 1

    @classmethod
    def from_document(cls, value: Mapping[str, object]) -> CodingWorkAuthority:
        """Rebuild only the exact authority schema accepted by this slice."""
        expected_keys = {
            "schema_version", "capability", "workspace", "execution", "repository",
            "host_resources", "network", "external_filesystem",
        }
        if set(value) != expected_keys:
            raise CodingWorkValidationError("The Coding Work authority shape is invalid.")
        workspace = value.get("workspace")
        execution = value.get("execution")
        fixed = {
            "schema_version": 1,
            "capability": CODING_WORK_CAPABILITY,
            "repository": {"authoritative_git_control_state": "read_only_if_present"},
            "host_resources": {
                "home_credentials_and_caches": "unavailable",
                "system_package_environment": "read_only",
            },
            "network": {"general_access": "denied"},
            "external_filesystem": {"access": "denied"},
        }
        if (
            not isinstance(workspace, dict)
            or set(workspace) != {"root", "read", "modify"}
            or not isinstance(execution, dict)
            or set(execution) != {"sandboxed_tools"}
            or any(value.get(key) != item for key, item in fixed.items())
        ):
            raise CodingWorkValidationError("The Coding Work authority shape is invalid.")
        authority = cls(
            workspace["root"],  # type: ignore[arg-type]
            workspace["read"],  # type: ignore[arg-type]
            workspace["modify"],  # type: ignore[arg-type]
            execution["sandboxed_tools"],  # type: ignore[arg-type]
        )
        if authority.document() != dict(value):
            raise CodingWorkValidationError("The Coding Work authority is not canonical.")
        return authority

    def document(self) -> dict[str, object]:
        if self.schema_version != 1:
            raise CodingWorkValidationError("The Coding Work authority version is unsupported.")
        root = _workspace_root(self.workspace_root)
        for value in (
            self.read_allowed, self.modify_allowed, self.sandboxed_execution_allowed,
        ):
            if not isinstance(value, bool):
                raise CodingWorkValidationError("Coding Work authority values must be boolean.")
        if self.modify_allowed and not self.read_allowed:
            raise CodingWorkValidationError(
                "Workspace modification authority requires workspace read authority."
            )
        return {
            "schema_version": 1,
            "capability": CODING_WORK_CAPABILITY,
            "workspace": {
                "root": root,
                "read": self.read_allowed,
                "modify": self.modify_allowed,
            },
            "execution": {"sandboxed_tools": self.sandboxed_execution_allowed},
            "repository": {"authoritative_git_control_state": "read_only_if_present"},
            "host_resources": {
                "home_credentials_and_caches": "unavailable",
                "system_package_environment": "read_only",
            },
            "network": {"general_access": "denied"},
            "external_filesystem": {"access": "denied"},
        }

    @property
    def canonical_json(self) -> str:
        return _canonical_json(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CodingWork:
    identifier: str
    objective: str
    acceptance_criteria: str | None
    workspace_root: str
    project_id: str | None
    origin_chat_id: str | None
    state: str
    current_authorization_id: str | None
    current_run_id: str | None
    revision: int
    created_at_utc: str
    started_at_utc: str | None
    updated_at_utc: str
    terminal_at_utc: str | None
    progress_json: str | None
    result_json: str | None

    @property
    def progress(self) -> Mapping[str, object] | None:
        return None if self.progress_json is None else _json_mapping(self.progress_json)

    @property
    def result(self) -> Mapping[str, object] | None:
        return None if self.result_json is None else _json_mapping(self.result_json)


@dataclass(frozen=True, slots=True)
class CodingProjectMetadata:
    """Bounded source-owned listing without worker result or workspace path."""

    identifier: str
    objective: str
    project_id: str
    state: str
    revision: int
    updated_at_utc: str
    terminal_at_utc: str | None


@dataclass(frozen=True, slots=True)
class CodingWorkResumeMetadata:
    """Content-free state allowed to inform a resume-work check-in."""

    identifier: str
    project_id: str | None
    origin_chat_id: str | None
    state: str
    revision: int
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class CodingWorkAuthorization:
    identifier: str
    work_id: str
    work_revision: int
    authority_json: str
    authority_digest: str
    confirmation_provenance: str
    status: str
    granted_at_utc: str
    status_changed_at_utc: str

    @property
    def authority(self) -> Mapping[str, object]:
        return _json_mapping(self.authority_json)


@dataclass(frozen=True, slots=True)
class CodingWorkRun:
    identifier: str
    work_id: str
    authorization_id: str
    adapter_id: str
    adapter_version: int
    harness_session_id: str | None
    launch_correlation_id: str
    connection_state: str
    last_event_sequence: int
    event_cursor: str | None
    reconciliation_prior_state: str | None
    created_at_utc: str
    started_at_utc: str | None
    last_observed_at_utc: str | None
    ended_at_utc: str | None
    failure_code: str | None
    failure_message: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class CodingWorkDirective:
    identifier: str
    work_id: str
    run_id: str
    authorization_id: str
    kind: str
    instruction: str | None
    source_chat_id: str | None
    status: str
    delivery_receipt: str | None
    failure_code: str | None
    revision: int
    created_at_utc: str
    updated_at_utc: str
    delivered_at_utc: str | None


@dataclass(frozen=True, slots=True)
class CodingWorkEvent:
    identifier: str
    work_id: str
    run_id: str | None
    work_sequence: int
    kind: str
    deduplication_key: str | None
    payload_json: str
    occurred_at_utc: str
    recorded_at_utc: str

    @property
    def payload(self) -> Mapping[str, object]:
        return _json_mapping(self.payload_json)


@dataclass(frozen=True, slots=True)
class CodingWorkState:
    revision: int
    work: tuple[CodingWork, ...]


_METADATA_SQL = """
CREATE TABLE coding_work_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_STATE_SQL = """
CREATE TABLE coding_work_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1)
)
"""
_WORK_SQL = f"""
CREATE TABLE coding_work (
    identifier TEXT PRIMARY KEY,
    objective TEXT NOT NULL CHECK (length(objective) BETWEEN 1 AND {MAX_OBJECTIVE_LENGTH}),
    acceptance_criteria TEXT CHECK (acceptance_criteria IS NULL OR length(acceptance_criteria) BETWEEN 1 AND {MAX_ACCEPTANCE_LENGTH}),
    workspace_root TEXT NOT NULL,
    project_id TEXT,
    origin_chat_id TEXT,
    state TEXT NOT NULL CHECK (state IN ({','.join(repr(value) for value in sorted(WORK_STATES))})),
    current_authorization_id TEXT,
    current_run_id TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    updated_at_utc TEXT NOT NULL,
    terminal_at_utc TEXT,
    progress_json TEXT CHECK (progress_json IS NULL OR length(progress_json) BETWEEN 2 AND {MAX_PROGRESS_JSON_LENGTH}),
    result_json TEXT CHECK (result_json IS NULL OR length(result_json) BETWEEN 2 AND {MAX_RESULT_JSON_LENGTH}),
    CHECK (created_at_utc <= updated_at_utc),
    CHECK ((state IN ('completed','failed','cancelled') AND terminal_at_utc IS NOT NULL)
        OR (state NOT IN ('completed','failed','cancelled') AND terminal_at_utc IS NULL)),
    CHECK ((state = 'awaiting_authorization' AND current_authorization_id IS NULL)
        OR state <> 'awaiting_authorization')
)
"""
_AUTH_SQL = f"""
CREATE TABLE coding_work_authorizations (
    identifier TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    work_revision INTEGER NOT NULL CHECK (typeof(work_revision) = 'integer' AND work_revision >= 1),
    authority_json TEXT NOT NULL CHECK (length(authority_json) BETWEEN 2 AND {MAX_RESULT_JSON_LENGTH}),
    authority_digest TEXT NOT NULL CHECK (length(authority_digest) = 64),
    confirmation_provenance TEXT NOT NULL CHECK (length(confirmation_provenance) BETWEEN 1 AND {MAX_PROVENANCE_LENGTH}),
    status TEXT NOT NULL CHECK (status IN ('active','superseded','revoked')),
    granted_at_utc TEXT NOT NULL,
    status_changed_at_utc TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES coding_work(identifier),
    UNIQUE (work_id, work_revision)
)
"""
_RUN_SQL = f"""
CREATE TABLE coding_work_runs (
    identifier TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    adapter_id TEXT NOT NULL CHECK (length(adapter_id) BETWEEN 1 AND {MAX_ADAPTER_VALUE_LENGTH}),
    adapter_version INTEGER NOT NULL CHECK (typeof(adapter_version) = 'integer' AND adapter_version >= 1),
    harness_session_id TEXT CHECK (harness_session_id IS NULL OR length(harness_session_id) BETWEEN 1 AND {MAX_ADAPTER_VALUE_LENGTH}),
    launch_correlation_id TEXT NOT NULL UNIQUE CHECK (length(launch_correlation_id) BETWEEN 1 AND {MAX_ADAPTER_VALUE_LENGTH}),
    connection_state TEXT NOT NULL CHECK (connection_state IN ('starting','attached','reconciling','missing','closed')),
    last_event_sequence INTEGER NOT NULL CHECK (typeof(last_event_sequence) = 'integer' AND last_event_sequence >= 0),
    event_cursor TEXT CHECK (event_cursor IS NULL OR length(event_cursor) BETWEEN 1 AND {MAX_ADAPTER_VALUE_LENGTH}),
    reconciliation_prior_state TEXT CHECK (reconciliation_prior_state IS NULL OR reconciliation_prior_state IN ('starting','running','waiting','cancelling')),
    created_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    last_observed_at_utc TEXT,
    ended_at_utc TEXT,
    failure_code TEXT,
    failure_message TEXT CHECK (failure_message IS NULL OR length(failure_message) BETWEEN 1 AND {MAX_FAILURE_LENGTH}),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    FOREIGN KEY (work_id) REFERENCES coding_work(identifier),
    FOREIGN KEY (authorization_id) REFERENCES coding_work_authorizations(identifier),
    CHECK ((connection_state IN ('missing','closed') AND ended_at_utc IS NOT NULL)
        OR (connection_state NOT IN ('missing','closed') AND ended_at_utc IS NULL))
)
"""
_DIRECTIVE_SQL = f"""
CREATE TABLE coding_work_directives (
    identifier TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    authorization_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('instruction','cancel')),
    instruction TEXT CHECK (instruction IS NULL OR length(instruction) BETWEEN 1 AND {MAX_DIRECTIVE_LENGTH}),
    source_chat_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending','delivering','delivered','failed')),
    delivery_receipt TEXT CHECK (delivery_receipt IS NULL OR length(delivery_receipt) BETWEEN 1 AND {MAX_ADAPTER_VALUE_LENGTH}),
    failure_code TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    delivered_at_utc TEXT,
    FOREIGN KEY (work_id) REFERENCES coding_work(identifier),
    FOREIGN KEY (run_id) REFERENCES coding_work_runs(identifier),
    FOREIGN KEY (authorization_id) REFERENCES coding_work_authorizations(identifier),
    CHECK ((kind = 'instruction' AND instruction IS NOT NULL)
        OR (kind = 'cancel' AND instruction IS NULL)),
    CHECK ((status = 'delivered' AND delivery_receipt IS NOT NULL AND delivered_at_utc IS NOT NULL)
        OR (status <> 'delivered' AND delivery_receipt IS NULL AND delivered_at_utc IS NULL)),
    CHECK (created_at_utc <= updated_at_utc)
)
"""
_EVENT_SQL = f"""
CREATE TABLE coding_work_events (
    identifier TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    run_id TEXT,
    work_sequence INTEGER NOT NULL CHECK (typeof(work_sequence) = 'integer' AND work_sequence >= 1),
    kind TEXT NOT NULL CHECK (kind IN ({','.join(repr(value) for value in sorted(EVENT_KINDS))})),
    deduplication_key TEXT,
    payload_json TEXT NOT NULL CHECK (length(payload_json) BETWEEN 2 AND {MAX_EVENT_JSON_LENGTH}),
    occurred_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES coding_work(identifier),
    FOREIGN KEY (run_id) REFERENCES coding_work_runs(identifier),
    UNIQUE (work_id, work_sequence),
    UNIQUE (work_id, deduplication_key)
)
"""
_WORK_STATE_INDEX_SQL = """
CREATE INDEX coding_work_state_index ON coding_work(state, updated_at_utc, identifier)
"""
_DIRECTIVE_INDEX_SQL = """
CREATE INDEX coding_work_directive_delivery_index
ON coding_work_directives(status, created_at_utc, identifier)
"""
_EVENT_INDEX_SQL = """
CREATE INDEX coding_work_event_history_index
ON coding_work_events(work_id, work_sequence)
"""


class _CodingWorkConnection(sqlite3.Connection):
    _safe_descriptors: tuple[int, ...] = ()

    def close(self) -> None:
        try:
            super().close()
        finally:
            descriptors, self._safe_descriptors = self._safe_descriptors, ()
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


IdentifierFactory = Callable[[str], str]
Clock = Callable[[], datetime]


class SQLiteCodingWorkStore:
    """Explicit exact-schema-1 store for concrete Coding Work state."""

    def __init__(
        self,
        path: Path,
        *,
        clock: Clock | None = None,
        identifier_factory: IdentifierFactory | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identifier_factory = identifier_factory or (
            lambda prefix: f"{prefix}-" + secrets.token_hex(16)
        )
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """Explicitly create a new store; never replace an existing entry."""

        with self._lock:
            parent, name = self._open_parent(create=True)
            try:
                existing = _stat_at(parent, name)
                if existing is not None and not stat.S_ISREG(existing.st_mode):
                    raise CodingWorkUnavailableError(
                        "The Coding Work store path is unavailable or unsafe."
                    )
                if existing is not None:
                    raise CodingWorkConflictError("The Coding Work store already exists.")
                if any(_stat_at(parent, name + suffix) is not None for suffix in ("-journal", "-wal", "-shm")):
                    raise CodingWorkUnavailableError("The Coding Work store has orphaned sidecars.")
                self._initialize_then_publish(parent, name)
            finally:
                os.close(parent)

    def revision(self) -> int:
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT revision FROM coding_work_state WHERE singleton=1"
            ).fetchone()
        if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
            raise CodingWorkCorruptError("Coding Work state is invalid.")
        return row[0]

    def state(self) -> CodingWorkState:
        return CodingWorkState(self.revision(), self.list_work())

    def create_work(
        self,
        *,
        objective: object,
        acceptance_criteria: object = None,
        workspace_root: object,
        project_id: object = None,
        origin_chat_id: object = None,
        related_work_id: object = None,
    ) -> CodingWork:
        objective_text = _text(objective, "Coding Work objective", MAX_OBJECTIVE_LENGTH)
        acceptance = _optional_text(
            acceptance_criteria, "acceptance criteria", MAX_ACCEPTANCE_LENGTH
        )
        workspace = _workspace_root(workspace_root)
        project = _optional_identifier(project_id, _PROJECT_ID, "Project")
        origin = _optional_identifier(origin_chat_id, _CHAT_ID, "origin chat")
        related = _optional_identifier(
            related_work_id, _WORK_ID, "related Coding Work"
        )
        if related is not None:
            self.get_work(related)
        stamp = _timestamp(self._clock())
        identifier = _identifier(self._identifier_factory("coding-work"), _WORK_ID, "work")
        record = CodingWork(
            identifier, objective_text, acceptance, workspace, project, origin,
            "awaiting_authorization", None, None, 1, stamp, None, stamp, None, None, None,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            _insert_work(connection, record)
            self._insert_event(
                connection, identifier, None, "created", None,
                {
                    "objective": objective_text,
                    **({"related_work_id": related} if related is not None else {}),
                }, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def get_work(self, identifier: object) -> CodingWork:
        work_id = _identifier(identifier, _WORK_ID, "work")
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM coding_work WHERE identifier=?", (work_id,)
            ).fetchone()
        if row is None:
            raise CodingWorkNotFoundError("The Coding Work item was not found.")
        return _work(row)

    def list_work(self, states: Sequence[str] | None = None) -> tuple[CodingWork, ...]:
        selected = tuple(sorted(WORK_STATES if states is None else {
            _enum(value, WORK_STATES, "Coding Work state") for value in states
        }))
        if not selected:
            return ()
        placeholders = ",".join("?" for _ in selected)
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                f"SELECT * FROM coding_work WHERE state IN ({placeholders}) "
                "ORDER BY updated_at_utc DESC,identifier", selected,
            ).fetchall()
        return tuple(_work(row) for row in rows)

    def list_project_work(self, project_id: str, *, limit: int = 50) -> tuple[CodingProjectMetadata, ...]:
        """Read source-owned Project membership without worker reconciliation."""

        project = _optional_identifier(project_id, _PROJECT_ID, "Project")
        if project is None or isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise CodingWorkValidationError("Project work query is invalid.")
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT identifier,objective,project_id,state,revision,"
                "updated_at_utc,terminal_at_utc FROM coding_work WHERE project_id=? "
                "ORDER BY updated_at_utc DESC,identifier LIMIT ?",
                (project, limit),
            ).fetchall()
        return tuple(CodingProjectMetadata(*row) for row in rows)

    def list_resume_metadata(self) -> tuple[CodingWorkResumeMetadata, ...]:
        """Return only stable identity and timing for waiting work."""

        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT identifier,project_id,origin_chat_id,state,revision,updated_at_utc "
                "FROM coding_work WHERE state='waiting' "
                "ORDER BY updated_at_utc DESC,identifier"
            ).fetchall()
        return tuple(CodingWorkResumeMetadata(*row) for row in rows)

    def get_authorization(self, identifier: object) -> CodingWorkAuthorization:
        authorization_id = _identifier(identifier, _AUTH_ID, "authorization")
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM coding_work_authorizations WHERE identifier=?",
                (authorization_id,),
            ).fetchone()
        if row is None:
            raise CodingWorkNotFoundError("The Coding Work authorization was not found.")
        return _authorization(row)

    def list_authorizations(self, work_id: object) -> tuple[CodingWorkAuthorization, ...]:
        work = _identifier(work_id, _WORK_ID, "work")
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT * FROM coding_work_authorizations WHERE work_id=? "
                "ORDER BY work_revision,identifier", (work,),
            ).fetchall()
        return tuple(_authorization(row) for row in rows)

    def authorize(
        self,
        work_id: object,
        *,
        expected_revision: object,
        authority: CodingWorkAuthority,
        confirmation_provenance: object,
    ) -> tuple[CodingWork, CodingWorkAuthorization]:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        if not isinstance(authority, CodingWorkAuthority):
            raise CodingWorkValidationError("A Coding Work authority envelope is required.")
        authority_json = authority.canonical_json
        provenance = _text(
            confirmation_provenance, "confirmation provenance", MAX_PROVENANCE_LENGTH
        )
        current = self.get_work(identifier)
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        if current.state not in {"awaiting_authorization", "queued"}:
            raise CodingWorkConflictError(
                "Authority can be granted only when no Coding Work run is active."
            )
        if current.workspace_root != authority.document()["workspace"]["root"]:
            raise CodingWorkValidationError(
                "The authority workspace does not match the Coding Work item."
            )
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        authorization_id = _identifier(
            self._identifier_factory("coding-auth"), _AUTH_ID, "authorization"
        )
        next_revision = expected + 1
        authorization = CodingWorkAuthorization(
            authorization_id, identifier, next_revision, authority_json,
            authority.digest, provenance, "active", stamp, stamp,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state,revision,current_authorization_id FROM coding_work "
                "WHERE identifier=?", (identifier,),
            ).fetchone()
            if row is None:
                raise CodingWorkNotFoundError("The Coding Work item was not found.")
            if row[1] != expected:
                raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
            if row[0] not in {"awaiting_authorization", "queued"}:
                raise CodingWorkConflictError("Coding Work cannot be authorized in its current state.")
            if row[2] is not None:
                connection.execute(
                    "UPDATE coding_work_authorizations SET status='superseded',"
                    "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                    (stamp, row[2]),
                )
            connection.execute(
                "INSERT INTO coding_work_authorizations VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    authorization.identifier, authorization.work_id,
                    authorization.work_revision, authorization.authority_json,
                    authorization.authority_digest,
                    authorization.confirmation_provenance, authorization.status,
                    authorization.granted_at_utc, authorization.status_changed_at_utc,
                ),
            )
            connection.execute(
                "UPDATE coding_work SET state='queued',current_authorization_id=?,"
                "revision=revision+1,updated_at_utc=? WHERE identifier=? AND revision=?",
                (authorization_id, stamp, identifier, expected),
            )
            self._insert_event(
                connection, identifier, None, "authorized", None,
                {"authorization_id": authorization_id, "authority_digest": authority.digest},
                stamp, stamp,
            )
            self._insert_event(
                connection, identifier, None, "queued", None, {}, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier), self.get_authorization(authorization_id)

    def create_run(
        self,
        work_id: object,
        *,
        expected_revision: object,
        adapter_id: object,
        adapter_version: object,
        launch_correlation_id: object,
    ) -> tuple[CodingWork, CodingWorkRun]:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        adapter = _text(adapter_id, "adapter identifier", MAX_ADAPTER_VALUE_LENGTH)
        version = _positive_int(adapter_version, "adapter version")
        correlation = _text(
            launch_correlation_id, "launch correlation identifier", MAX_ADAPTER_VALUE_LENGTH
        )
        current = self.get_work(identifier)
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        if current.state != "queued" or current.current_authorization_id is None:
            raise CodingWorkConflictError("Only authorized queued Coding Work can start.")
        authorization = self.get_authorization(current.current_authorization_id)
        if authorization.status != "active":
            raise CodingWorkConflictError("The current Coding Work authority is not active.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        run_id = _identifier(self._identifier_factory("coding-run"), _RUN_ID, "run")
        run = CodingWorkRun(
            run_id, identifier, authorization.identifier, adapter, version, None,
            correlation, "starting", 0, None, None, stamp, None, None, None, None, None, 1,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE coding_work SET state='starting',current_run_id=?,revision=revision+1,"
                "updated_at_utc=? WHERE identifier=? AND revision=? AND state='queued'",
                (run_id, stamp, identifier, expected),
            )
            if cursor.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work item changed before start.")
            _insert_run(connection, run)
            self._insert_event(
                connection, identifier, run_id, "starting", None,
                {"adapter_id": adapter, "adapter_version": version}, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier), self.get_run(run_id)

    def get_run(self, identifier: object) -> CodingWorkRun:
        run_id = _identifier(identifier, _RUN_ID, "run")
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM coding_work_runs WHERE identifier=?", (run_id,)
            ).fetchone()
        if row is None:
            raise CodingWorkNotFoundError("The Coding Work run was not found.")
        return _run(row)

    def list_runs(self, work_id: object) -> tuple[CodingWorkRun, ...]:
        identifier = _identifier(work_id, _WORK_ID, "work")
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT * FROM coding_work_runs WHERE work_id=? "
                "ORDER BY created_at_utc,identifier", (identifier,),
            ).fetchall()
        return tuple(_run(row) for row in rows)

    def bind_session(
        self,
        run_id: object,
        *,
        expected_revision: object,
        harness_session_id: object,
        event_cursor: object = None,
        observed_state: object = "running",
    ) -> CodingWorkRun:
        identifier = _identifier(run_id, _RUN_ID, "run")
        expected = _revision(expected_revision)
        session = _text(
            harness_session_id, "harness session identifier", MAX_ADAPTER_VALUE_LENGTH
        )
        cursor = _optional_text(event_cursor, "event cursor", MAX_ADAPTER_VALUE_LENGTH)
        observed = _enum(
            observed_state, frozenset({"starting", "running"}),
            "observed worker state",
        )
        current = self.get_run(identifier)
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work run changed; reload it.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.created_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            update = connection.execute(
                "UPDATE coding_work_runs SET harness_session_id=?,connection_state='attached',"
                "event_cursor=?,reconciliation_prior_state=NULL,"
                "started_at_utc=COALESCE(started_at_utc,?),"
                "last_observed_at_utc=?,revision=revision+1 WHERE identifier=? AND revision=? "
                "AND connection_state IN ('starting','reconciling')",
                (session, cursor, stamp, stamp, identifier, expected),
            )
            if update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work run changed before attachment.")
            work = connection.execute(
                "SELECT identifier,state,revision,updated_at_utc FROM coding_work "
                "WHERE current_run_id=?", (identifier,),
            ).fetchone()
            if work is None:
                raise CodingWorkCorruptError("The current Coding Work run is not linked.")
            if work[1] not in {"starting", "reconciling"}:
                raise CodingWorkConflictError("The Coding Work item cannot attach in its current state.")
            work_stamp = _later_timestamp(stamp, work[3])
            connection.execute(
                "UPDATE coding_work SET state=?,started_at_utc=COALESCE(started_at_utc,?),"
                "updated_at_utc=?,revision=revision+1 WHERE identifier=? AND revision=?",
                (observed, work_stamp, work_stamp, work[0], work[2]),
            )
            if observed != "starting":
                self._insert_event(
                    connection, work[0], identifier,
                    "session_confirmed", None,
                    {"harness_session_id": session}, work_stamp, work_stamp,
                )
            self._bump(connection)
        return self.get_run(identifier)

    def transition_work(
        self,
        work_id: object,
        *,
        expected_revision: object,
        target_state: object,
        event_kind: object,
        payload: Mapping[str, object] | None = None,
        run_id: object = None,
        deduplication_key: object = None,
        occurred_at_utc: object = None,
        result: Mapping[str, object] | None = None,
        failure_code: object = None,
        failure_message: object = None,
    ) -> CodingWork:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        target = _enum(target_state, WORK_STATES, "Coding Work state")
        kind = _enum(event_kind, EVENT_KINDS, "Coding Work event kind")
        run = None if run_id is None else _identifier(run_id, _RUN_ID, "run")
        dedupe = _optional_text(
            deduplication_key, "event deduplication key", MAX_ADAPTER_VALUE_LENGTH
        )
        event_payload = _canonical_json(payload or {}, MAX_EVENT_JSON_LENGTH)
        result_json = None if result is None else _canonical_json(result, MAX_RESULT_JSON_LENGTH)
        code = _optional_safe_code(failure_code)
        message = _optional_text(failure_message, "failure message", MAX_FAILURE_LENGTH)
        current = self.get_work(identifier)
        if dedupe is not None:
            duplicate = self.event_by_deduplication(identifier, dedupe)
            if duplicate is not None:
                return current
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        if current.state in TERMINAL_WORK_STATES:
            if target in TERMINAL_WORK_STATES:
                return current
            if target != "awaiting_authorization":
                raise CodingWorkConflictError("Terminal Coding Work requires explicit continuation.")
        elif target not in _TRANSITIONS[current.state]:
            raise CodingWorkConflictError(
                f"Coding Work cannot transition from {current.state} to {target}."
            )
        if target in TERMINAL_WORK_STATES and result_json is None:
            result_json = _canonical_json({}, MAX_RESULT_JSON_LENGTH)
        if target == "failed" and (code is None or message is None):
            raise CodingWorkValidationError("Failed Coding Work requires bounded failure evidence.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        occurred = stamp if occurred_at_utc is None else _timestamp_text(occurred_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if dedupe is not None:
                existing = connection.execute(
                    "SELECT identifier FROM coding_work_events WHERE work_id=? "
                    "AND deduplication_key=?", (identifier, dedupe),
                ).fetchone()
                if existing is not None:
                    return current
            terminal_at = stamp if target in TERMINAL_WORK_STATES else None
            current_authorization = None if target == "awaiting_authorization" else current.current_authorization_id
            current_run = None if target == "awaiting_authorization" else current.current_run_id
            progress_json = None if target == "awaiting_authorization" else current.progress_json
            stored_result = None if target == "awaiting_authorization" else (
                result_json if target in TERMINAL_WORK_STATES else current.result_json
            )
            if target == "awaiting_authorization" and current.current_authorization_id is not None:
                connection.execute(
                    "UPDATE coding_work_authorizations SET status='superseded',"
                    "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                    (stamp, current.current_authorization_id),
                )
            cursor = connection.execute(
                "UPDATE coding_work SET state=?,current_authorization_id=?,current_run_id=?,"
                "revision=revision+1,updated_at_utc=?,terminal_at_utc=?,progress_json=?,"
                "result_json=? WHERE identifier=? AND revision=?",
                (
                    target, current_authorization, current_run, stamp, terminal_at,
                    progress_json, stored_result, identifier, expected,
                ),
            )
            if cursor.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
            if run is not None and target in TERMINAL_WORK_STATES:
                connection.execute(
                    "UPDATE coding_work_runs SET connection_state='closed',ended_at_utc=?,"
                    "last_observed_at_utc=?,failure_code=?,failure_message=?,revision=revision+1 "
                    "WHERE identifier=? AND work_id=? AND connection_state NOT IN ('closed','missing')",
                    (stamp, stamp, code, message, run, identifier),
                )
            self._insert_event_json(
                connection, identifier, run, kind, dedupe, event_payload, occurred, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def update_progress(
        self,
        work_id: object,
        *,
        expected_revision: object,
        run_id: object,
        adapter_event_id: object,
        adapter_sequence: object,
        summary: object,
        changed_paths: Sequence[object] = (),
        verification: object = None,
        event_cursor: object = None,
        occurred_at_utc: object = None,
    ) -> CodingWork:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        run_identifier = _identifier(run_id, _RUN_ID, "run")
        event_id = _text(
            adapter_event_id, "adapter event identifier", MAX_ADAPTER_VALUE_LENGTH
        )
        sequence = _positive_int(adapter_sequence, "adapter event sequence")
        dedupe = f"{run_identifier}:{event_id}"
        if len(dedupe) > MAX_ADAPTER_VALUE_LENGTH:
            dedupe = hashlib.sha256(dedupe.encode("utf-8")).hexdigest()
        duplicate = self.event_by_deduplication(identifier, dedupe)
        if duplicate is not None:
            return self.get_work(identifier)
        current_run = self.get_run(run_identifier)
        if current_run.work_id != identifier:
            raise CodingWorkValidationError("The progress event belongs to another Coding Work item.")
        if sequence <= current_run.last_event_sequence:
            raise CodingWorkStaleRevisionError("The worker event sequence is stale.")
        summary_text = _text(summary, "progress summary", 2_000)
        paths = tuple(_relative_path(value) for value in changed_paths)
        if len(paths) > 256:
            raise CodingWorkValidationError("Progress changed paths exceed the bounded limit.")
        verification_text = _optional_text(verification, "verification status", 1_000)
        observed = _timestamp(self._clock()) if occurred_at_utc is None else _timestamp_text(occurred_at_utc)
        progress = {
            "summary": summary_text,
            "observed_at_utc": observed,
            "changed_paths": list(paths),
            "verification": verification_text,
        }
        progress_json = _canonical_json(progress, MAX_PROGRESS_JSON_LENGTH)
        cursor_text = _optional_text(event_cursor, "event cursor", MAX_ADAPTER_VALUE_LENGTH)
        current = self.get_work(identifier)
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        if current.state not in {"running", "waiting", "cancelling", "reconciling"}:
            raise CodingWorkConflictError("Progress cannot update Coding Work in its current state.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM coding_work_events WHERE work_id=? AND deduplication_key=?",
                (identifier, dedupe),
            ).fetchone() is not None:
                return current
            run_row = connection.execute(
                "SELECT last_event_sequence,revision FROM coding_work_runs WHERE identifier=?",
                (run_identifier,),
            ).fetchone()
            if run_row is None or run_row[0] >= sequence:
                raise CodingWorkStaleRevisionError("The worker event sequence is stale.")
            work_update = connection.execute(
                "UPDATE coding_work SET progress_json=?,updated_at_utc=?,revision=revision+1 "
                "WHERE identifier=? AND revision=?",
                (progress_json, stamp, identifier, expected),
            )
            if work_update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
            connection.execute(
                "UPDATE coding_work_runs SET last_event_sequence=?,event_cursor=?,"
                "last_observed_at_utc=?,revision=revision+1 WHERE identifier=?",
                (sequence, cursor_text, observed, run_identifier),
            )
            self._insert_event_json(
                connection, identifier, run_identifier, "progress", dedupe,
                progress_json, observed, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def apply_adapter_event(
        self,
        work_id: object,
        *,
        run_id: object,
        adapter_event_id: object,
        adapter_sequence: object,
        kind: object,
        payload: Mapping[str, object],
        event_cursor: object,
        occurred_at_utc: object,
        result: Mapping[str, object] | None = None,
    ) -> CodingWork:
        """Atomically apply one ordered semantic adapter event."""

        identifier = _identifier(work_id, _WORK_ID, "work")
        run_identifier = _identifier(run_id, _RUN_ID, "run")
        event_id = _text(
            adapter_event_id, "adapter event identifier", MAX_ADAPTER_VALUE_LENGTH
        )
        sequence = _positive_int(adapter_sequence, "adapter event sequence")
        event_kind = _enum(kind, frozenset({
            "session_confirmed", "waiting", "verification", "completed", "failed", "cancelled",
        }), "adapter event kind")
        payload_json = _canonical_json(payload, MAX_EVENT_JSON_LENGTH)
        result_json = None if result is None else _canonical_json(result, MAX_RESULT_JSON_LENGTH)
        cursor = _text(event_cursor, "event cursor", MAX_ADAPTER_VALUE_LENGTH)
        occurred = _timestamp_text(occurred_at_utc)
        dedupe = f"{run_identifier}:{event_id}"
        if len(dedupe) > MAX_ADAPTER_VALUE_LENGTH:
            dedupe = hashlib.sha256(dedupe.encode("utf-8")).hexdigest()
        duplicate = self.event_by_deduplication(identifier, dedupe)
        if duplicate is not None:
            return self.get_work(identifier)
        current = self.get_work(identifier)
        current_run = self.get_run(run_identifier)
        if current.current_run_id != run_identifier or current_run.work_id != identifier:
            raise CodingWorkValidationError("The worker event targets another Coding Work run.")
        if sequence <= current_run.last_event_sequence:
            raise CodingWorkStaleRevisionError("The worker event sequence is stale.")
        if current.state in TERMINAL_WORK_STATES:
            if event_kind not in TERMINAL_WORK_STATES:
                return current
            stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
            with self._lock, closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM coding_work_events WHERE work_id=? AND deduplication_key=?",
                    (identifier, dedupe),
                ).fetchone() is not None:
                    return current
                run_row = connection.execute(
                    "SELECT last_event_sequence FROM coding_work_runs WHERE identifier=?",
                    (run_identifier,),
                ).fetchone()
                if run_row is None or run_row[0] >= sequence:
                    raise CodingWorkStaleRevisionError("The worker event sequence is stale.")
                connection.execute(
                    "UPDATE coding_work_runs SET last_event_sequence=?,event_cursor=?,"
                    "last_observed_at_utc=?,revision=revision+1 WHERE identifier=?",
                    (sequence, cursor, occurred, run_identifier),
                )
                self._insert_event_json(
                    connection, identifier, run_identifier, event_kind, dedupe,
                    payload_json, occurred, stamp,
                )
                self._bump(connection)
            return current
        target = {
            "session_confirmed": "running",
            "waiting": "waiting",
            "verification": current.state,
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
        }[event_kind]
        if event_kind in {"session_confirmed", "waiting"} and current.state == "cancelling":
            target = "cancelling"
        elif event_kind == "session_confirmed" and current.state == "running":
            target = "running"
        elif event_kind == "verification":
            if current.state not in {"running", "waiting", "cancelling", "reconciling"}:
                raise CodingWorkConflictError("Verification is invalid in the current Coding Work state.")
        elif target != current.state and target not in _TRANSITIONS[current.state]:
            raise CodingWorkConflictError(
                f"The worker event cannot transition Coding Work from {current.state} to {target}."
            )
        if event_kind == "failed":
            failure_code = _optional_safe_code(payload.get("failure_code"))
            failure_message = _optional_text(
                payload.get("failure_message"), "failure message", MAX_FAILURE_LENGTH
            )
            if failure_code is None or failure_message is None:
                raise CodingWorkValidationError("A failed worker event requires bounded failure evidence.")
        else:
            failure_code = None
            failure_message = None
        if target in TERMINAL_WORK_STATES and result_json is None:
            result_json = _canonical_json({}, MAX_RESULT_JSON_LENGTH)
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM coding_work_events WHERE work_id=? AND deduplication_key=?",
                (identifier, dedupe),
            ).fetchone() is not None:
                return current
            run_row = connection.execute(
                "SELECT last_event_sequence,connection_state FROM coding_work_runs "
                "WHERE identifier=?", (run_identifier,),
            ).fetchone()
            if run_row is None or run_row[0] >= sequence:
                raise CodingWorkStaleRevisionError("The worker event sequence is stale.")
            terminal = target in TERMINAL_WORK_STATES
            connection.execute(
                "UPDATE coding_work_runs SET last_event_sequence=?,event_cursor=?,"
                "connection_state=?,last_observed_at_utc=?,ended_at_utc=?,failure_code=?,"
                "failure_message=?,reconciliation_prior_state=NULL,"
                "revision=revision+1 WHERE identifier=?",
                (
                    sequence, cursor, "closed" if terminal else "attached", occurred,
                    stamp if terminal else None, failure_code, failure_message,
                    run_identifier,
                ),
            )
            update = connection.execute(
                "UPDATE coding_work SET state=?,revision=revision+1,updated_at_utc=?,"
                "terminal_at_utc=?,result_json=? WHERE identifier=? AND revision=?",
                (
                    target, stamp, stamp if terminal else None,
                    result_json if terminal else current.result_json,
                    identifier, current.revision,
                ),
            )
            if update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
            self._insert_event_json(
                connection, identifier, run_identifier, event_kind, dedupe,
                payload_json, occurred, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def restore_observed_session(
        self,
        work_id: object,
        *,
        expected_revision: object,
        run_id: object,
        harness_session_id: object,
        observed_state: object,
        event_cursor: object,
    ) -> CodingWork:
        """Restore truthful state after an authoritative reconciliation inspection."""

        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        run_identifier = _identifier(run_id, _RUN_ID, "run")
        session = _text(
            harness_session_id, "harness session identifier", MAX_ADAPTER_VALUE_LENGTH
        )
        target = _enum(
            observed_state,
            frozenset({"starting", "running", "waiting", "completed", "failed", "cancelled"}),
            "observed worker state",
        )
        cursor = _optional_text(event_cursor, "event cursor", MAX_ADAPTER_VALUE_LENGTH)
        current = self.get_work(identifier)
        if current.revision != expected or current.state != "reconciling":
            raise CodingWorkStaleRevisionError("The Coding Work reconciliation changed.")
        if current.current_run_id != run_identifier:
            raise CodingWorkValidationError("The observed session targets another Coding Work run.")
        if target not in _TRANSITIONS["reconciling"]:
            raise CodingWorkConflictError("The observed worker state cannot be reconciled.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        terminal = target in TERMINAL_WORK_STATES
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run_update = connection.execute(
                "UPDATE coding_work_runs SET harness_session_id=?,connection_state=?,"
                "event_cursor=?,last_observed_at_utc=?,ended_at_utc=?,"
                "reconciliation_prior_state=NULL,revision=revision+1 "
                "WHERE identifier=? AND work_id=? AND connection_state='reconciling'",
                (
                    session,
                    "closed" if terminal else "starting" if target == "starting" else "attached",
                    cursor, stamp,
                    stamp if terminal else None, run_identifier, identifier,
                ),
            )
            if run_update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work run reconciliation changed.")
            update = connection.execute(
                "UPDATE coding_work SET state=?,revision=revision+1,updated_at_utc=?,"
                "terminal_at_utc=?,result_json=? WHERE identifier=? AND revision=? "
                "AND state='reconciling'",
                (
                    target, stamp, stamp if terminal else None,
                    _canonical_json({}, MAX_RESULT_JSON_LENGTH) if terminal else current.result_json,
                    identifier, expected,
                ),
            )
            if update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work reconciliation changed.")
            self._insert_event(
                connection, identifier, run_identifier,
                "session_confirmed" if target == "running" else target,
                None, {"reason": "reconciled_session"}, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def queue_directive(
        self,
        work_id: object,
        *,
        expected_revision: object,
        kind: object,
        instruction: object = None,
        source_chat_id: object = None,
    ) -> tuple[CodingWork, CodingWorkDirective]:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        directive_kind = _enum(kind, DIRECTIVE_KINDS, "directive kind")
        text = (
            _text(instruction, "directive instruction", MAX_DIRECTIVE_LENGTH)
            if directive_kind == "instruction" else None
        )
        if directive_kind == "cancel" and instruction is not None:
            raise CodingWorkValidationError("Cancellation directives do not contain instructions.")
        source = _optional_identifier(source_chat_id, _CHAT_ID, "source chat")
        current = self.get_work(identifier)
        if current.revision != expected:
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        allowed = (
            {"running", "waiting"}
            if directive_kind == "instruction"
            else {"starting", "running", "waiting"}
        )
        if current.state not in allowed or current.current_run_id is None or current.current_authorization_id is None:
            raise CodingWorkConflictError("The directive is not valid for the current Coding Work state.")
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        directive_id = _identifier(
            self._identifier_factory("coding-directive"), _DIRECTIVE_ID, "directive"
        )
        target_state = "cancelling" if directive_kind == "cancel" else current.state
        event_kind = "cancellation_requested" if directive_kind == "cancel" else "instruction_queued"
        directive = CodingWorkDirective(
            directive_id, identifier, current.current_run_id,
            current.current_authorization_id, directive_kind, text, source,
            "pending", None, None, 1, stamp, stamp, None,
        )
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            update = connection.execute(
                "UPDATE coding_work SET state=?,revision=revision+1,updated_at_utc=? "
                "WHERE identifier=? AND revision=?",
                (target_state, stamp, identifier, expected),
            )
            if update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
            if directive_kind == "cancel":
                connection.execute(
                    "UPDATE coding_work_authorizations SET status='revoked',"
                    "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                    (stamp, current.current_authorization_id),
                )
            _insert_directive(connection, directive)
            self._insert_event(
                connection, identifier, current.current_run_id, event_kind, None,
                {"directive_id": directive_id}, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier), self.get_directive(directive_id)

    def get_directive(self, identifier: object) -> CodingWorkDirective:
        directive_id = _identifier(identifier, _DIRECTIVE_ID, "directive")
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM coding_work_directives WHERE identifier=?",
                (directive_id,),
            ).fetchone()
        if row is None:
            raise CodingWorkNotFoundError("The Coding Work directive was not found.")
        return _directive(row)

    def pending_directives(self, work_id: object | None = None) -> tuple[CodingWorkDirective, ...]:
        parameters: tuple[object, ...] = ()
        where = "status IN ('pending','delivering')"
        if work_id is not None:
            where += " AND work_id=?"
            parameters = (_identifier(work_id, _WORK_ID, "work"),)
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                f"SELECT * FROM coding_work_directives WHERE {where} "
                "ORDER BY created_at_utc,identifier", parameters,
            ).fetchall()
        return tuple(_directive(row) for row in rows)

    def claim_directive(self, identifier: object) -> CodingWorkDirective:
        directive_id = _identifier(identifier, _DIRECTIVE_ID, "directive")
        current = self.get_directive(directive_id)
        if current.status == "delivering":
            return current
        if current.status != "pending":
            return current
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE coding_work_directives SET status='delivering',"
                "updated_at_utc=?,revision=revision+1 WHERE identifier=? AND revision=? "
                "AND status='pending'",
                (stamp, directive_id, current.revision),
            )
            if cursor.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work directive changed.")
            self._bump(connection)
        return self.get_directive(directive_id)

    def finish_directive(
        self,
        identifier: object,
        *,
        expected_revision: object,
        receipt: object = None,
        failure_code: object = None,
    ) -> CodingWorkDirective:
        directive_id = _identifier(identifier, _DIRECTIVE_ID, "directive")
        expected = _revision(expected_revision)
        current = self.get_directive(directive_id)
        if current.status == "delivered":
            if receipt == current.delivery_receipt:
                return current
            raise CodingWorkConflictError("The directive already has another delivery receipt.")
        if current.revision != expected or current.status != "delivering":
            raise CodingWorkStaleRevisionError("The Coding Work directive changed.")
        receipt_text = _optional_text(receipt, "delivery receipt", MAX_ADAPTER_VALUE_LENGTH)
        code = _optional_safe_code(failure_code)
        if (receipt_text is None) == (code is None):
            raise CodingWorkValidationError("Directive completion requires one receipt or failure code.")
        status = "delivered" if receipt_text is not None else "failed"
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        with self._lock, closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE coding_work_directives SET status=?,delivery_receipt=?,failure_code=?,"
                "updated_at_utc=?,delivered_at_utc=?,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status='delivering'",
                (
                    status, receipt_text, code, stamp,
                    stamp if status == "delivered" else None,
                    directive_id, expected,
                ),
            )
            if cursor.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work directive changed.")
            self._bump(connection)
        return self.get_directive(directive_id)

    def mark_reconciling(self) -> tuple[CodingWork, ...]:
        """Truthfully invalidate all prior nonterminal worker observations."""

        changed: list[str] = []
        stamp = _timestamp(self._clock())
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT identifier,current_run_id,revision,updated_at_utc,state FROM coding_work "
                "WHERE state IN ('starting','running','waiting','cancelling')"
            ).fetchall()
            for row in rows:
                next_stamp = _later_timestamp(stamp, row[3])
                connection.execute(
                    "UPDATE coding_work SET state='reconciling',revision=revision+1,"
                    "updated_at_utc=? WHERE identifier=? AND revision=?",
                    (next_stamp, row[0], row[2]),
                )
                if row[1] is not None:
                    connection.execute(
                        "UPDATE coding_work_runs SET connection_state='reconciling',"
                        "reconciliation_prior_state=?,revision=revision+1 "
                        "WHERE identifier=? AND connection_state "
                        "NOT IN ('closed','missing')", (row[4], row[1]),
                    )
                self._insert_event(
                    connection, row[0], row[1], "reconciling", None,
                    {"reason": "application_restart"}, next_stamp, next_stamp,
                )
                changed.append(row[0])
            if changed:
                self._bump(connection)
        return tuple(self.get_work(identifier) for identifier in changed)

    def mark_session_missing(
        self,
        work_id: object,
        *,
        expected_revision: object,
        run_id: object,
        failure_code: object = "session_missing",
        failure_message: object = "The worker session was missing during reconciliation.",
    ) -> CodingWork:
        identifier = _identifier(work_id, _WORK_ID, "work")
        expected = _revision(expected_revision)
        run_identifier = _identifier(run_id, _RUN_ID, "run")
        current = self.get_work(identifier)
        if current.revision != expected or current.state != "reconciling":
            raise CodingWorkStaleRevisionError("The Coding Work reconciliation changed.")
        if current.current_run_id != run_identifier:
            raise CodingWorkConflictError(
                "Only the current Coding Work run can be marked missing."
            )
        code = _optional_safe_code(failure_code)
        message = _optional_text(
            failure_message, "reconciliation failure message", MAX_FAILURE_LENGTH
        )
        if code is None or message is None:
            raise CodingWorkValidationError(
                "A reconciliation failure code and message are required."
            )
        stamp = _later_timestamp(_timestamp(self._clock()), current.updated_at_utc)
        result = {"summary": message}
        with self._lock, closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run_update = connection.execute(
                "UPDATE coding_work_runs SET connection_state='missing',ended_at_utc=?,"
                "failure_code=?,failure_message=?,revision=revision+1 "
                "WHERE identifier=? AND work_id=? AND connection_state='reconciling'",
                (
                    stamp, code, message,
                    run_identifier, identifier,
                ),
            )
            if run_update.rowcount != 1:
                raise CodingWorkStaleRevisionError(
                    "The Coding Work run reconciliation changed."
                )
            update = connection.execute(
                "UPDATE coding_work SET state='failed',revision=revision+1,updated_at_utc=?,"
                "terminal_at_utc=?,result_json=? WHERE identifier=? AND revision=? "
                "AND state='reconciling'",
                (
                    stamp, stamp, _canonical_json(result, MAX_RESULT_JSON_LENGTH),
                    identifier, expected,
                ),
            )
            if update.rowcount != 1:
                raise CodingWorkStaleRevisionError("The Coding Work reconciliation changed.")
            self._insert_event(
                connection, identifier, run_identifier, "failed", None,
                {"failure_code": code}, stamp, stamp,
            )
            self._bump(connection)
        return self.get_work(identifier)

    def continue_terminal(
        self, work_id: object, *, expected_revision: object
    ) -> CodingWork:
        current = self.get_work(work_id)
        if current.revision != _revision(expected_revision):
            raise CodingWorkStaleRevisionError("The Coding Work item changed; reload it.")
        if current.state not in TERMINAL_WORK_STATES:
            raise CodingWorkConflictError("Only terminal Coding Work can be continued.")
        return self.transition_work(
            current.identifier,
            expected_revision=current.revision,
            target_state="awaiting_authorization",
            event_kind="created",
            payload={"continuation_of_run_id": current.current_run_id},
        )

    def events(self, work_id: object, *, limit: int = 500) -> tuple[CodingWorkEvent, ...]:
        identifier = _identifier(work_id, _WORK_ID, "work")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise CodingWorkValidationError("The Coding Work event limit is invalid.")
        with closing(self._connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT * FROM coding_work_events WHERE work_id=? "
                "ORDER BY work_sequence DESC LIMIT ?", (identifier, limit),
            ).fetchall()
        return tuple(reversed(tuple(_event(row) for row in rows)))

    def event_by_deduplication(
        self, work_id: object, key: object
    ) -> CodingWorkEvent | None:
        identifier = _identifier(work_id, _WORK_ID, "work")
        dedupe = _text(key, "event deduplication key", MAX_ADAPTER_VALUE_LENGTH)
        with closing(self._connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT * FROM coding_work_events WHERE work_id=? AND deduplication_key=?",
                (identifier, dedupe),
            ).fetchone()
        return None if row is None else _event(row)

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        work_id: str,
        run_id: str | None,
        kind: str,
        dedupe: str | None,
        payload: Mapping[str, object],
        occurred: str,
        recorded: str,
    ) -> CodingWorkEvent:
        return self._insert_event_json(
            connection, work_id, run_id, kind, dedupe,
            _canonical_json(payload, MAX_EVENT_JSON_LENGTH), occurred, recorded,
        )

    def _insert_event_json(
        self,
        connection: sqlite3.Connection,
        work_id: str,
        run_id: str | None,
        kind: str,
        dedupe: str | None,
        payload_json: str,
        occurred: str,
        recorded: str,
    ) -> CodingWorkEvent:
        row = connection.execute(
            "SELECT COALESCE(MAX(work_sequence),0)+1 FROM coding_work_events WHERE work_id=?",
            (work_id,),
        ).fetchone()
        sequence = row[0]
        identifier = _identifier(
            self._identifier_factory("coding-event"), _EVENT_ID, "event"
        )
        connection.execute(
            "INSERT INTO coding_work_events VALUES (?,?,?,?,?,?,?,?,?)",
            (
                identifier, work_id, run_id, sequence, kind, dedupe,
                payload_json, occurred, recorded,
            ),
        )
        connection.execute(
            "DELETE FROM coding_work_events WHERE work_id=? AND work_sequence <= "
            "(SELECT COALESCE(MAX(work_sequence),0)-? FROM coding_work_events "
            "WHERE work_id=?)",
            (work_id, MAX_DURABLE_EVENTS_PER_WORK, work_id),
        )
        return CodingWorkEvent(
            identifier, work_id, run_id, sequence, kind, dedupe,
            payload_json, occurred, recorded,
        )

    @staticmethod
    def _bump(connection: sqlite3.Connection) -> None:
        cursor = connection.execute(
            "UPDATE coding_work_state SET revision=revision+1 WHERE singleton=1"
        )
        if cursor.rowcount != 1:
            raise CodingWorkCorruptError("Coding Work state is invalid.")

    def _connect(self, *, readonly: bool = False) -> _CodingWorkConnection:
        parent: int | None = None
        database: int | None = None
        connection: _CodingWorkConnection | None = None
        try:
            parent, name = self._open_parent(create=False)
            existing = _stat_at(parent, name)
            if existing is None or not stat.S_ISREG(existing.st_mode):
                raise CodingWorkUnavailableError("The Coding Work store has not been initialized.")
            flags = (os.O_RDONLY if readonly else os.O_RDWR) | _no_follow() | getattr(os, "O_CLOEXEC", 0)
            database = os.open(name, flags, dir_fd=parent)
            if not _same_file(existing, os.fstat(database)):
                raise OSError("Coding Work database changed during open")
            sqlite_path = f"/proc/self/fd/{parent}/{name}"
            mode = "ro" if readonly else "rw"
            connection = sqlite3.connect(
                f"file:{quote(sqlite_path, safe='/')}?mode={mode}",
                uri=True, timeout=5.0, factory=_CodingWorkConnection,
            )
            current = _stat_at(parent, name)
            if current is None or not _same_file(os.fstat(database), current):
                raise OSError("Coding Work database changed during SQLite open")
            self._validate_schema(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            if not readonly:
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("PRAGMA journal_mode=DELETE")
            connection.row_factory = sqlite3.Row
            connection._safe_descriptors = (parent, database)
            return connection
        except CodingWorkError as exc:
            failure: BaseException = exc
        except sqlite3.DatabaseError:
            failure = CodingWorkCorruptError(
                "Tori's Coding Work database is corrupt or invalid; it was preserved."
            )
        except (OSError, sqlite3.Error):
            failure = CodingWorkUnavailableError("Tori's Coding Work database is unavailable.")
        if connection is not None:
            connection.close()
        for descriptor in (database, parent):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise failure

    def _initialize_then_publish(self, parent: int, name: str) -> None:
        temporary = f".{name}.incomplete-{secrets.token_hex(16)}"
        flags = os.O_RDWR | _no_follow() | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(
            temporary, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
        )
        connection: sqlite3.Connection | None = None
        published = False
        try:
            original = os.fstat(descriptor)
            path = f"/proc/self/fd/{parent}/{temporary}"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA journal_mode=DELETE")
            with connection:
                for sql in _EXPECTED_SQL.values():
                    connection.execute(sql)
                connection.execute(
                    "INSERT INTO coding_work_metadata VALUES ('schema_version',?)",
                    (str(CODING_WORK_SCHEMA_VERSION),),
                )
                connection.execute("INSERT INTO coding_work_state VALUES (1,1)")
            self._validate_schema(connection)
            connection.close()
            connection = None
            if any(_stat_at(parent, temporary + suffix) is not None for suffix in ("-journal", "-wal", "-shm")):
                raise OSError("Coding Work initialization sidecar exists")
            if not _same_file(original, _stat_at(parent, temporary)):
                raise OSError("Coding Work initialization entry changed")
            os.fsync(descriptor)
            _rename_noreplace(parent, temporary, name)
            published = True
            os.fsync(parent)
        except BaseException as exc:
            if published:
                raise
            raise CodingWorkUnavailableError(
                f"Coding Work initialization failed; isolated artifact {temporary!r} was preserved."
            ) from exc
        finally:
            if connection is not None:
                connection.close()
            os.close(descriptor)

    def _open_parent(self, *, create: bool) -> tuple[int, str]:
        raw = os.fspath(self._path)
        if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
            raise CodingWorkUnavailableError("The Coding Work path is unsafe.")
        absolute = Path(os.path.abspath(os.path.normpath(raw)))
        if not absolute.name:
            raise CodingWorkUnavailableError("The Coding Work path is unsafe.")
        flags = os.O_RDONLY | _directory() | _no_follow() | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open("/", flags)
        try:
            for part in absolute.parent.parts[1:]:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise CodingWorkUnavailableError(
                            "The Coding Work store has not been initialized."
                        )
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=descriptor)
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    os.close(child)
                    raise OSError("unsafe Coding Work ancestor")
                os.close(descriptor)
                descriptor = child
            return descriptor, absolute.name
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        actual = {
            name: sql
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_autoindex_%'"
            )
            if kind in {"table", "index"}
        }
        if set(actual) != set(_EXPECTED_SQL) or any(
            not isinstance(actual[name], str)
            or _normalize_sql(actual[name]) != _normalize_sql(sql)
            for name, sql in _EXPECTED_SQL.items()
        ):
            raise CodingWorkCorruptError(
                "Tori's Coding Work database has an invalid schema; it was preserved."
            )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1"
        ).fetchone() is not None:
            raise CodingWorkCorruptError("The Coding Work store has unexpected schema objects.")
        metadata = connection.execute(
            "SELECT key,value FROM coding_work_metadata"
        ).fetchall()
        if len(metadata) != 1 or tuple(metadata[0]) != (
            "schema_version", str(CODING_WORK_SCHEMA_VERSION)
        ):
            if (
                len(metadata) == 1 and metadata[0][0] == "schema_version"
                and isinstance(metadata[0][1], str) and metadata[0][1].isdigit()
            ):
                raise CodingWorkVersionError(
                    f"Coding Work schema version {metadata[0][1]} is unsupported; it was not modified."
                )
            raise CodingWorkCorruptError("Coding Work schema metadata is invalid.")
        state = connection.execute(
            "SELECT singleton,revision FROM coding_work_state"
        ).fetchall()
        if len(state) != 1 or state[0][0] != 1 or state[0][1] < 1:
            raise CodingWorkCorruptError("Coding Work global state is invalid.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise CodingWorkCorruptError("Coding Work foreign-key state is invalid.")
        semantic_violation = connection.execute(
            """
            SELECT 1
            FROM coding_work AS w
            LEFT JOIN coding_work_authorizations AS ca
              ON ca.identifier=w.current_authorization_id
            LEFT JOIN coding_work_runs AS cr
              ON cr.identifier=w.current_run_id
            WHERE (w.current_authorization_id IS NOT NULL
                   AND (ca.identifier IS NULL OR ca.work_id<>w.identifier))
               OR (w.current_run_id IS NOT NULL
                   AND (cr.identifier IS NULL OR cr.work_id<>w.identifier))
               OR (w.current_run_id IS NOT NULL
                   AND w.state NOT IN ('awaiting_authorization','queued')
                   AND cr.authorization_id<>w.current_authorization_id)
            UNION ALL
            SELECT 1
            FROM coding_work_authorizations AS a
            JOIN coding_work AS w ON w.identifier=a.work_id
            WHERE a.status='active' AND w.current_authorization_id IS NOT a.identifier
            UNION ALL
            SELECT 1
            FROM coding_work_runs AS r
            JOIN coding_work_authorizations AS a ON a.identifier=r.authorization_id
            WHERE a.work_id<>r.work_id
            UNION ALL
            SELECT 1
            FROM coding_work_directives AS d
            JOIN coding_work_runs AS r ON r.identifier=d.run_id
            JOIN coding_work_authorizations AS a ON a.identifier=d.authorization_id
            WHERE d.work_id<>r.work_id OR d.work_id<>a.work_id
               OR d.authorization_id<>r.authorization_id
            UNION ALL
            SELECT 1
            FROM coding_work_events AS e
            JOIN coding_work_runs AS r ON r.identifier=e.run_id
            WHERE e.run_id IS NOT NULL AND e.work_id<>r.work_id
            LIMIT 1
            """
        ).fetchone()
        if semantic_violation is not None:
            raise CodingWorkCorruptError(
                "Tori's Coding Work database has inconsistent record ownership; it was preserved."
            )
        try:
            for row in connection.execute("SELECT * FROM coding_work"):
                _work(row)
            for row in connection.execute("SELECT * FROM coding_work_authorizations"):
                _authorization(row)
            for row in connection.execute("SELECT * FROM coding_work_runs"):
                _run(row)
            for row in connection.execute("SELECT * FROM coding_work_directives"):
                _directive(row)
            for row in connection.execute("SELECT * FROM coding_work_events"):
                _event(row)
        except CodingWorkCorruptError:
            raise
        except (CodingWorkValidationError, ValueError) as exc:
            raise CodingWorkCorruptError(
                "Tori's Coding Work database contains invalid records; it was preserved."
            ) from exc


_EXPECTED_SQL: Mapping[str, str] = {
    "coding_work_metadata": _METADATA_SQL,
    "coding_work_state": _STATE_SQL,
    "coding_work": _WORK_SQL,
    "coding_work_authorizations": _AUTH_SQL,
    "coding_work_runs": _RUN_SQL,
    "coding_work_directives": _DIRECTIVE_SQL,
    "coding_work_events": _EVENT_SQL,
    "coding_work_state_index": _WORK_STATE_INDEX_SQL,
    "coding_work_directive_delivery_index": _DIRECTIVE_INDEX_SQL,
    "coding_work_event_history_index": _EVENT_INDEX_SQL,
}


def _insert_work(connection: sqlite3.Connection, item: CodingWork) -> None:
    connection.execute(
        "INSERT INTO coding_work VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.objective, item.acceptance_criteria,
            item.workspace_root, item.project_id, item.origin_chat_id, item.state,
            item.current_authorization_id, item.current_run_id, item.revision,
            item.created_at_utc, item.started_at_utc, item.updated_at_utc,
            item.terminal_at_utc, item.progress_json, item.result_json,
        ),
    )


def _insert_run(connection: sqlite3.Connection, item: CodingWorkRun) -> None:
    connection.execute(
        "INSERT INTO coding_work_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.work_id, item.authorization_id, item.adapter_id,
            item.adapter_version, item.harness_session_id,
            item.launch_correlation_id, item.connection_state,
            item.last_event_sequence, item.event_cursor,
            item.reconciliation_prior_state, item.created_at_utc,
            item.started_at_utc, item.last_observed_at_utc, item.ended_at_utc,
            item.failure_code, item.failure_message, item.revision,
        ),
    )


def _insert_directive(connection: sqlite3.Connection, item: CodingWorkDirective) -> None:
    connection.execute(
        "INSERT INTO coding_work_directives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.work_id, item.run_id, item.authorization_id,
            item.kind, item.instruction, item.source_chat_id, item.status,
            item.delivery_receipt, item.failure_code, item.revision,
            item.created_at_utc, item.updated_at_utc, item.delivered_at_utc,
        ),
    )


def _work(row: Sequence[object]) -> CodingWork:
    item = CodingWork(*row)
    _identifier(item.identifier, _WORK_ID, "work")
    _text(item.objective, "Coding Work objective", MAX_OBJECTIVE_LENGTH)
    _optional_text(item.acceptance_criteria, "acceptance criteria", MAX_ACCEPTANCE_LENGTH)
    _workspace_root(item.workspace_root)
    _optional_identifier(item.project_id, _PROJECT_ID, "Project")
    _optional_identifier(item.origin_chat_id, _CHAT_ID, "origin chat")
    _enum(item.state, WORK_STATES, "Coding Work state")
    if item.current_authorization_id is not None:
        _identifier(item.current_authorization_id, _AUTH_ID, "authorization")
    if item.current_run_id is not None:
        _identifier(item.current_run_id, _RUN_ID, "run")
    _revision(item.revision)
    for value in (item.created_at_utc, item.updated_at_utc):
        _timestamp_text(value)
    for value in (item.started_at_utc, item.terminal_at_utc):
        if value is not None:
            _timestamp_text(value)
    if item.progress_json is not None:
        _bounded_json(item.progress_json, MAX_PROGRESS_JSON_LENGTH)
    if item.result_json is not None:
        _bounded_json(item.result_json, MAX_RESULT_JSON_LENGTH)
    return item


def _authorization(row: Sequence[object]) -> CodingWorkAuthorization:
    item = CodingWorkAuthorization(*row)
    _identifier(item.identifier, _AUTH_ID, "authorization")
    _identifier(item.work_id, _WORK_ID, "work")
    _revision(item.work_revision)
    document = _bounded_json(item.authority_json, MAX_RESULT_JSON_LENGTH)
    try:
        authority = CodingWorkAuthority.from_document(document)
    except CodingWorkValidationError as exc:
        raise CodingWorkCorruptError("A Coding Work authority record is invalid.") from exc
    if authority.canonical_json != item.authority_json:
        raise CodingWorkCorruptError("A Coding Work authority record is not canonical.")
    if hashlib.sha256(item.authority_json.encode("utf-8")).hexdigest() != item.authority_digest:
        raise CodingWorkCorruptError("A Coding Work authority digest is invalid.")
    _text(item.confirmation_provenance, "confirmation provenance", MAX_PROVENANCE_LENGTH)
    _enum(item.status, AUTHORIZATION_STATES, "authorization state")
    _timestamp_text(item.granted_at_utc)
    _timestamp_text(item.status_changed_at_utc)
    return item


def _run(row: Sequence[object]) -> CodingWorkRun:
    item = CodingWorkRun(*row)
    _identifier(item.identifier, _RUN_ID, "run")
    _identifier(item.work_id, _WORK_ID, "work")
    _identifier(item.authorization_id, _AUTH_ID, "authorization")
    _text(item.adapter_id, "adapter identifier", MAX_ADAPTER_VALUE_LENGTH)
    _positive_int(item.adapter_version, "adapter version")
    _optional_text(item.harness_session_id, "harness session identifier", MAX_ADAPTER_VALUE_LENGTH)
    _text(item.launch_correlation_id, "launch correlation identifier", MAX_ADAPTER_VALUE_LENGTH)
    _enum(item.connection_state, RUN_STATES, "run connection state")
    if isinstance(item.last_event_sequence, bool) or not isinstance(item.last_event_sequence, int) or item.last_event_sequence < 0:
        raise CodingWorkCorruptError("A Coding Work event sequence is invalid.")
    _optional_text(item.event_cursor, "event cursor", MAX_ADAPTER_VALUE_LENGTH)
    if item.reconciliation_prior_state is not None:
        _enum(
            item.reconciliation_prior_state,
            NONTERMINAL_OBSERVED_STATES,
            "prior reconciliation state",
        )
    for value in (item.created_at_utc, item.started_at_utc, item.last_observed_at_utc, item.ended_at_utc):
        if value is not None:
            _timestamp_text(value)
    _optional_safe_code(item.failure_code)
    _optional_text(item.failure_message, "failure message", MAX_FAILURE_LENGTH)
    _revision(item.revision)
    return item


def _directive(row: Sequence[object]) -> CodingWorkDirective:
    item = CodingWorkDirective(*row)
    _identifier(item.identifier, _DIRECTIVE_ID, "directive")
    _identifier(item.work_id, _WORK_ID, "work")
    _identifier(item.run_id, _RUN_ID, "run")
    _identifier(item.authorization_id, _AUTH_ID, "authorization")
    _enum(item.kind, DIRECTIVE_KINDS, "directive kind")
    _optional_text(item.instruction, "directive instruction", MAX_DIRECTIVE_LENGTH)
    _optional_identifier(item.source_chat_id, _CHAT_ID, "source chat")
    _enum(item.status, DIRECTIVE_STATES, "directive state")
    _optional_text(item.delivery_receipt, "delivery receipt", MAX_ADAPTER_VALUE_LENGTH)
    _optional_safe_code(item.failure_code)
    _revision(item.revision)
    for value in (item.created_at_utc, item.updated_at_utc, item.delivered_at_utc):
        if value is not None:
            _timestamp_text(value)
    return item


def _event(row: Sequence[object]) -> CodingWorkEvent:
    item = CodingWorkEvent(*row)
    _identifier(item.identifier, _EVENT_ID, "event")
    _identifier(item.work_id, _WORK_ID, "work")
    if item.run_id is not None:
        _identifier(item.run_id, _RUN_ID, "run")
    _positive_int(item.work_sequence, "work event sequence")
    _enum(item.kind, EVENT_KINDS, "event kind")
    _optional_text(item.deduplication_key, "event deduplication key", MAX_ADAPTER_VALUE_LENGTH)
    _bounded_json(item.payload_json, MAX_EVENT_JSON_LENGTH)
    _timestamp_text(item.occurred_at_utc)
    _timestamp_text(item.recorded_at_utc)
    return item


def _canonical_json(value: object, limit: int = MAX_RESULT_JSON_LENGTH) -> str:
    try:
        rendered = json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise CodingWorkValidationError("Coding Work structured data is invalid.") from exc
    if not 2 <= len(rendered) <= limit:
        raise CodingWorkValidationError("Coding Work structured data exceeds its bounded limit.")
    if not isinstance(json.loads(rendered), dict):
        raise CodingWorkValidationError("Coding Work structured data must be an object.")
    return rendered


def _bounded_json(value: object, limit: int) -> Mapping[str, object]:
    if not isinstance(value, str) or not 2 <= len(value) <= limit:
        raise CodingWorkCorruptError("Coding Work structured data is invalid.")
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise CodingWorkCorruptError("Coding Work structured data is invalid.") from exc
    if not isinstance(parsed, dict) or _canonical_json(parsed, limit) != value:
        raise CodingWorkCorruptError("Coding Work structured data is not canonical.")
    return parsed


def _json_mapping(value: str) -> Mapping[str, object]:
    return _bounded_json(value, max(len(value), 2))


def _text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value or len(value) > limit:
        raise CodingWorkValidationError(f"The {label} is invalid.")
    return value


def _optional_text(value: object, label: str, limit: int) -> str | None:
    return None if value is None else _text(value, label, limit)


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CodingWorkValidationError(f"The Coding Work {label} identifier is invalid.")
    return value


def _optional_identifier(
    value: object, pattern: re.Pattern[str], label: str
) -> str | None:
    return None if value is None else _identifier(value, pattern, label)


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CodingWorkValidationError("The Coding Work revision is invalid.")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CodingWorkValidationError(f"The {label} is invalid.")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise CodingWorkValidationError(f"The {label} is invalid.")
    return value


def _optional_safe_code(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise CodingWorkValidationError("The Coding Work failure code is invalid.")
    return value


def _workspace_root(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CodingWorkValidationError("The authorized workspace root is invalid.")
    path = Path(value)
    if not path.is_absolute() or Path(os.path.normpath(value)) != path:
        raise CodingWorkValidationError("The authorized workspace root must be exact and absolute.")
    return os.fspath(path)


def _relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CodingWorkValidationError("A changed path is invalid.")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or os.fspath(path) != os.path.normpath(value):
        raise CodingWorkValidationError("Changed paths must be normalized workspace-relative paths.")
    return os.fspath(path)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CodingWorkValidationError("A timezone-aware Coding Work timestamp is required.")
    return format_utc_timestamp(value.astimezone(timezone.utc))


def _timestamp_text(value: object) -> str:
    if not isinstance(value, str):
        raise CodingWorkValidationError("A Coding Work timestamp is invalid.")
    try:
        parsed = parse_utc_timestamp(value)
    except ValueError as exc:
        raise CodingWorkValidationError("A Coding Work timestamp is invalid.") from exc
    if format_utc_timestamp(parsed) != value:
        raise CodingWorkValidationError("A Coding Work timestamp is not canonical.")
    return value


def _later_timestamp(candidate: str, previous: str) -> str:
    current = parse_utc_timestamp(candidate)
    prior = parse_utc_timestamp(previous)
    if current <= prior:
        current = prior + timedelta(seconds=1)
    return format_utc_timestamp(current)


def _stat_at(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_file(first: os.stat_result, second: os.stat_result | None) -> bool:
    return second is not None and (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _directory() -> int:
    return getattr(os, "O_DIRECTORY", 0)


def _no_follow() -> int:
    return getattr(os, "O_NOFOLLOW", 0)


def _rename_noreplace(parent: int, source: str, target: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = library.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        parent, os.fsencode(source), parent, os.fsencode(target), 1
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def _normalize_sql(value: str) -> str:
    return " ".join(value.replace("\n", " ").split()).casefold()
