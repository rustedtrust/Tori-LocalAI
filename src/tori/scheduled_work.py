"""Durable definitions, authorization, runs, and execution for scheduled work."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
import ctypes
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time as civil_time, timedelta, timezone
import errno
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
import unicodedata
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .actions import (
    ActionContractError,
    ActionDefinition,
    BACKUP_ACTION_ID,
)
from .backups import BackupError
from .deadline_loop import DeadlineLoop
from .operator_observability import operator_event
from .time_context import (
    NonexistentCivilTimeError,
    TimeContext,
    format_utc_timestamp,
    parse_utc_timestamp,
    validate_timezone_name,
)


LOGGER = logging.getLogger(__name__)

SCHEDULED_WORK_SCHEMA_VERSION = 2
LEGACY_SCHEDULED_WORK_SCHEMA_VERSION = 1
DEFAULT_SCHEDULED_WORK_DATABASE = Path(
    "runtime/scheduled_work/tori_scheduled_work.db"
)
MAX_TITLE_LENGTH = 4_000
MAX_JSON_LENGTH = 32_000
MAX_FAILURE_LENGTH = 1_000
MAX_CONFIRMATION_PROVENANCE_LENGTH = 128
MAX_IDENTIFIER_ATTEMPTS = 5

DEFINITION_STATUSES = frozenset({"active", "paused", "completed", "cancelled"})
AUTHORIZATION_STATUSES = frozenset({"active", "superseded", "revoked", "exhausted"})
RUN_STATUSES = frozenset({
    "queued", "running", "succeeded", "failed", "skipped",
    "cancelled_before_start", "interrupted",
})
TERMINAL_RUN_STATUSES = RUN_STATUSES - {"queued", "running"}
MISSED_POLICIES = frozenset({"run_when_available", "skip_if_missed"})
SCHEDULE_KINDS = frozenset({"one_shot", "daily", "weekly"})
SCHEDULED_MODES = frozenset({"one_shot", "recurring"})

_JOB_ID = re.compile(r"^work-[0-9a-f]{32}$")
_AUTH_ID = re.compile(r"^authorization-[0-9a-f]{32}$")
_RUN_ID = re.compile(r"^run-[0-9a-f]{32}$")
_EVENT_ID = re.compile(r"^event-[0-9a-f]{32}$")
_CHAT_ID = re.compile(r"^chat-[0-9a-f]{32}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ScheduledWorkError(RuntimeError):
    """Base safe scheduled-work failure."""

    code = "scheduled_work_error"


class ScheduledWorkValidationError(ScheduledWorkError):
    code = "invalid_scheduled_work"


class ScheduledWorkNotFoundError(ScheduledWorkError):
    code = "not_found"


class ScheduledWorkStaleRevisionError(ScheduledWorkError):
    code = "stale_revision"


class ScheduledWorkConflictError(ScheduledWorkError):
    code = "conflict"


class ScheduledWorkVersionError(ScheduledWorkError):
    code = "unsupported_version"


class ScheduledWorkCorruptError(ScheduledWorkError):
    code = "store_corrupt"


class ScheduledWorkUnavailableError(ScheduledWorkError):
    code = "store_unavailable"


class ScheduledWorkVerificationError(ScheduledWorkError):
    code = "verification_failed"


class ScheduledCapabilityError(ScheduledWorkError):
    code = "capability_failed"

    def __init__(self, message: str, *, code: str = "capability_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    """One strict application-owned schedule specification."""

    kind: str
    timezone_name: str
    occurrence_utc: str | None = None
    start_date: str | None = None
    local_time: str | None = None
    weekdays: tuple[int, ...] = ()

    @property
    def mode(self) -> str:
        return "one_shot" if self.kind == "one_shot" else "recurring"

    def document(self) -> dict[str, object]:
        if self.kind == "one_shot":
            return {
                "kind": self.kind,
                "timezone": self.timezone_name,
                "occurrence_utc": self.occurrence_utc,
            }
        result: dict[str, object] = {
            "kind": self.kind,
            "timezone": self.timezone_name,
            "start_date": self.start_date,
            "local_time": self.local_time,
        }
        if self.kind == "weekly":
            result["weekdays"] = list(self.weekdays)
        return result


@dataclass(frozen=True, slots=True)
class Occurrence:
    key: str
    due_utc: str
    local_date: str | None
    dst_gap: bool = False


@dataclass(frozen=True, slots=True)
class ScheduledWorkDefinition:
    identifier: str
    title: str
    capability_id: str
    capability_contract_version: int
    arguments_json: str
    schedule_json: str
    schedule_kind: str
    scheduled_mode: str
    timezone_name: str
    missed_policy: str
    status: str
    current_authorization_id: str
    next_occurrence_key: str | None
    next_occurrence_utc: str | None
    next_local_date: str | None
    created_at_utc: str
    updated_at_utc: str
    paused_at_utc: str | None
    cancelled_at_utc: str | None
    completed_at_utc: str | None
    revision: int
    origin_chat_id: str | None

    @property
    def arguments(self) -> Mapping[str, object]:
        return _json_mapping(self.arguments_json)

    @property
    def schedule(self) -> ScheduleSpec:
        return schedule_from_json(self.schedule_json)


@dataclass(frozen=True, slots=True)
class ScheduledAuthorization:
    identifier: str
    job_id: str
    job_revision: int
    capability_id: str
    capability_contract_version: int
    arguments_json: str
    arguments_digest: str
    schedule_json: str
    schedule_digest: str
    scheduled_mode: str
    missed_policy: str
    granted_at_utc: str
    confirmation_provenance: str
    status: str
    status_changed_at_utc: str


@dataclass(frozen=True, slots=True)
class ScheduledRun:
    identifier: str
    job_id: str
    definition_revision: int
    authorization_id: str
    capability_id: str
    capability_contract_version: int
    occurrence_key: str
    scheduled_occurrence_utc: str
    claim_at_utc: str
    started_at_utc: str | None
    finished_at_utc: str | None
    status: str
    work_started: bool
    result_json: str | None
    failure_code: str | None
    failure_message: str | None
    missed_occurrence_count: int
    missed_first_key: str | None
    missed_last_key: str | None
    revision: int

    @property
    def result(self) -> Mapping[str, object] | None:
        return None if self.result_json is None else _json_mapping(self.result_json)


@dataclass(frozen=True, slots=True)
class ScheduledNotification:
    run_id: str
    event_identifier: str
    state: str
    queued_at_utc: str
    archived_at_utc: str | None
    chat_id: str | None
    origin_chat_id: str | None


@dataclass(frozen=True, slots=True)
class ScheduledWorkState:
    revision: int
    definitions: tuple[ScheduledWorkDefinition, ...]
    runs: tuple[ScheduledRun, ...]


_METADATA_SQL = """
CREATE TABLE scheduled_work_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_STATE_SQL = """
CREATE TABLE scheduled_work_state (
    singleton INTEGER PRIMARY KEY
        CHECK (typeof(singleton) = 'integer' AND singleton = 1),
    revision INTEGER NOT NULL
        CHECK (typeof(revision) = 'integer' AND revision >= 1)
)
"""
_LEGACY_DEFINITIONS_SQL = f"""
CREATE TABLE scheduled_work_definitions (
    identifier TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND {MAX_TITLE_LENGTH}),
    capability_id TEXT NOT NULL,
    capability_contract_version INTEGER NOT NULL
        CHECK (typeof(capability_contract_version) = 'integer' AND capability_contract_version >= 1),
    arguments_json TEXT NOT NULL CHECK (length(arguments_json) BETWEEN 2 AND {MAX_JSON_LENGTH}),
    schedule_json TEXT NOT NULL CHECK (length(schedule_json) BETWEEN 2 AND {MAX_JSON_LENGTH}),
    schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('one_shot','daily','weekly')),
    scheduled_mode TEXT NOT NULL CHECK (scheduled_mode IN ('one_shot','recurring')),
    timezone_name TEXT NOT NULL,
    missed_policy TEXT NOT NULL CHECK (missed_policy IN ('run_when_available','skip_if_missed')),
    status TEXT NOT NULL CHECK (status IN ('active','paused','completed','cancelled')),
    current_authorization_id TEXT NOT NULL,
    next_occurrence_key TEXT,
    next_occurrence_utc TEXT,
    next_local_date TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    paused_at_utc TEXT,
    cancelled_at_utc TEXT,
    completed_at_utc TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    CHECK ((status = 'active' AND next_occurrence_key IS NOT NULL AND next_occurrence_utc IS NOT NULL
            AND paused_at_utc IS NULL AND cancelled_at_utc IS NULL AND completed_at_utc IS NULL)
        OR (status = 'paused' AND next_occurrence_key IS NULL AND next_occurrence_utc IS NULL
            AND paused_at_utc IS NOT NULL AND cancelled_at_utc IS NULL AND completed_at_utc IS NULL)
        OR (status = 'completed' AND next_occurrence_key IS NULL AND next_occurrence_utc IS NULL
            AND cancelled_at_utc IS NULL AND completed_at_utc IS NOT NULL)
        OR (status = 'cancelled' AND next_occurrence_key IS NULL AND next_occurrence_utc IS NULL
            AND cancelled_at_utc IS NOT NULL AND completed_at_utc IS NULL)),
    CHECK ((schedule_kind = 'one_shot' AND scheduled_mode = 'one_shot' AND next_local_date IS NULL)
        OR (schedule_kind IN ('daily','weekly') AND scheduled_mode = 'recurring')),
    CHECK (created_at_utc <= updated_at_utc)
)
"""
_DEFINITIONS_SQL = _LEGACY_DEFINITIONS_SQL.replace(
    "    CHECK ((status",
    """    origin_chat_id TEXT CHECK (origin_chat_id IS NULL OR (
        length(origin_chat_id) = 37
        AND substr(origin_chat_id, 1, 5) = 'chat-'
        AND substr(origin_chat_id, 6) NOT GLOB '*[^0-9a-f]*'
    )),
    CHECK ((status""",
    1,
)
_AUTHORIZATIONS_SQL = f"""
CREATE TABLE scheduled_authorizations (
    identifier TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    job_revision INTEGER NOT NULL CHECK (typeof(job_revision) = 'integer' AND job_revision >= 1),
    capability_id TEXT NOT NULL,
    capability_contract_version INTEGER NOT NULL
        CHECK (typeof(capability_contract_version) = 'integer' AND capability_contract_version >= 1),
    arguments_json TEXT NOT NULL CHECK (length(arguments_json) BETWEEN 2 AND {MAX_JSON_LENGTH}),
    arguments_digest TEXT NOT NULL CHECK (length(arguments_digest) = 64),
    schedule_json TEXT NOT NULL CHECK (length(schedule_json) BETWEEN 2 AND {MAX_JSON_LENGTH}),
    schedule_digest TEXT NOT NULL CHECK (length(schedule_digest) = 64),
    scheduled_mode TEXT NOT NULL CHECK (scheduled_mode IN ('one_shot','recurring')),
    missed_policy TEXT NOT NULL CHECK (missed_policy IN ('run_when_available','skip_if_missed')),
    granted_at_utc TEXT NOT NULL,
    confirmation_provenance TEXT NOT NULL
        CHECK (length(confirmation_provenance) BETWEEN 1 AND {MAX_CONFIRMATION_PROVENANCE_LENGTH}),
    status TEXT NOT NULL CHECK (status IN ('active','superseded','revoked','exhausted')),
    status_changed_at_utc TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES scheduled_work_definitions(identifier) ON DELETE CASCADE,
    UNIQUE (job_id, job_revision)
)
"""
_RUNS_SQL = f"""
CREATE TABLE scheduled_runs (
    identifier TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    definition_revision INTEGER NOT NULL
        CHECK (typeof(definition_revision) = 'integer' AND definition_revision >= 1),
    authorization_id TEXT NOT NULL,
    capability_id TEXT NOT NULL,
    capability_contract_version INTEGER NOT NULL
        CHECK (typeof(capability_contract_version) = 'integer' AND capability_contract_version >= 1),
    occurrence_key TEXT NOT NULL,
    scheduled_occurrence_utc TEXT NOT NULL,
    claim_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    finished_at_utc TEXT,
    status TEXT NOT NULL CHECK (status IN (
        'queued','running','succeeded','failed','skipped','cancelled_before_start','interrupted'
    )),
    work_started INTEGER NOT NULL CHECK (work_started IN (0,1)),
    result_json TEXT CHECK (result_json IS NULL OR length(result_json) BETWEEN 2 AND {MAX_JSON_LENGTH}),
    failure_code TEXT,
    failure_message TEXT CHECK (failure_message IS NULL OR length(failure_message) BETWEEN 1 AND {MAX_FAILURE_LENGTH}),
    missed_occurrence_count INTEGER NOT NULL
        CHECK (typeof(missed_occurrence_count) = 'integer' AND missed_occurrence_count >= 0),
    missed_first_key TEXT,
    missed_last_key TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    FOREIGN KEY (job_id) REFERENCES scheduled_work_definitions(identifier),
    FOREIGN KEY (authorization_id) REFERENCES scheduled_authorizations(identifier),
    UNIQUE (job_id, definition_revision, occurrence_key),
    CHECK ((status = 'queued' AND started_at_utc IS NULL AND finished_at_utc IS NULL AND work_started = 0
            AND result_json IS NULL AND failure_code IS NULL AND failure_message IS NULL)
        OR (status = 'running' AND started_at_utc IS NOT NULL AND finished_at_utc IS NULL
            AND result_json IS NULL AND failure_code IS NULL AND failure_message IS NULL)
        OR (status = 'succeeded' AND started_at_utc IS NOT NULL AND finished_at_utc IS NOT NULL
            AND work_started = 1 AND result_json IS NOT NULL AND failure_code IS NULL AND failure_message IS NULL)
        OR (status IN ('failed','skipped','cancelled_before_start','interrupted')
            AND finished_at_utc IS NOT NULL AND result_json IS NULL
            AND failure_code IS NOT NULL AND failure_message IS NOT NULL)),
    CHECK ((missed_occurrence_count = 0 AND missed_first_key IS NULL AND missed_last_key IS NULL)
        OR (missed_occurrence_count >= 1 AND missed_first_key IS NOT NULL AND missed_last_key IS NOT NULL))
)
"""
_LEGACY_NOTIFICATIONS_SQL = """
CREATE TABLE scheduled_notifications (
    run_id TEXT PRIMARY KEY,
    event_identifier TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('pending','archived')),
    queued_at_utc TEXT NOT NULL,
    archived_at_utc TEXT,
    chat_id TEXT,
    FOREIGN KEY (run_id) REFERENCES scheduled_runs(identifier) ON DELETE CASCADE,
    CHECK ((state = 'pending' AND archived_at_utc IS NULL AND chat_id IS NULL)
        OR (state = 'archived' AND archived_at_utc IS NOT NULL AND chat_id IS NOT NULL))
)
"""
_NOTIFICATIONS_SQL = _LEGACY_NOTIFICATIONS_SQL.replace(
    "    FOREIGN KEY (run_id)",
    """    origin_chat_id TEXT CHECK (origin_chat_id IS NULL OR (
        length(origin_chat_id) = 37
        AND substr(origin_chat_id, 1, 5) = 'chat-'
        AND substr(origin_chat_id, 6) NOT GLOB '*[^0-9a-f]*'
    )),
    FOREIGN KEY (run_id)""",
    1,
)
_DEFINITION_INDEX_SQL = """
CREATE INDEX scheduled_work_due_index
ON scheduled_work_definitions(status, next_occurrence_utc, identifier)
"""
_RUN_INDEX_SQL = """
CREATE INDEX scheduled_runs_status_claim_index
ON scheduled_runs(status, claim_at_utc, identifier)
"""
_RUN_JOB_INDEX_SQL = """
CREATE INDEX scheduled_runs_job_finish_index
ON scheduled_runs(job_id, finished_at_utc, identifier)
"""


class _ScheduledConnection(sqlite3.Connection):
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


class ScheduledCapabilityCatalog:
    """An explicit application-owned catalog with scheduling disabled by default."""

    def __init__(self, definitions: Sequence[ActionDefinition] = ()) -> None:
        if isinstance(definitions, (str, bytes)):
            raise ScheduledWorkValidationError("Capability definitions are invalid.")
        selected: dict[str, ActionDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, ActionDefinition):
                raise ScheduledWorkValidationError("Capability definitions are invalid.")
            if definition.identifier in selected:
                raise ScheduledWorkValidationError("Capability identifiers must be unique.")
            selected[definition.identifier] = definition
        self._definitions = selected

    @property
    def definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, capability_id: object) -> ActionDefinition:
        if not isinstance(capability_id, str) or capability_id not in self._definitions:
            raise ScheduledCapabilityError(
                "The scheduled capability is not registered.", code="unknown_capability"
            )
        return self._definitions[capability_id]

    def validate(
        self,
        capability_id: object,
        contract_version: object,
        arguments: object,
        scheduled_mode: object,
        *,
        system_derived: bool = False,
    ) -> tuple[ActionDefinition, Mapping[str, object]]:
        definition = self.definition(capability_id)
        if (
            isinstance(contract_version, bool)
            or not isinstance(contract_version, int)
            or contract_version != definition.contract_version
        ):
            raise ScheduledCapabilityError(
                "The scheduled capability contract version is unavailable.",
                code="contract_version_mismatch",
            )
        if scheduled_mode == "one_shot":
            eligible = definition.scheduled_one_shot_eligible
        elif scheduled_mode == "recurring":
            eligible = definition.scheduled_recurring_eligible
        else:
            raise ScheduledWorkValidationError("The scheduled mode is invalid.")
        if (
            scheduled_mode == "one_shot"
            and system_derived
            and definition.system_derived_one_shot_eligible
        ):
            eligible = True
        if not eligible:
            raise ScheduledCapabilityError(
                "That capability is not eligible for the requested scheduled mode.",
                code="scheduling_not_allowed",
            )
        try:
            canonical = definition.validate_arguments(arguments)
        except ActionContractError as exc:
            raise ScheduledCapabilityError(str(exc), code=exc.code) from exc
        return definition, canonical


class SQLiteScheduledWorkStore:
    """Own one exact, fail-closed scheduled-work SQLite store."""

    def __init__(
        self,
        path: Path = DEFAULT_SCHEDULED_WORK_DATABASE,
        *,
        clock: Callable[[], datetime] | None = None,
        identifier_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._identifier_factory = identifier_factory or _identifier

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        with closing(self._connect()):
            pass

    def revision(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT revision FROM scheduled_work_state WHERE singleton=1"
            ).fetchone()
        if row is None or isinstance(row[0], bool) or not isinstance(row[0], int):
            raise ScheduledWorkCorruptError("Scheduled-work state is invalid.")
        return row[0]

    def create_definition(
        self,
        *,
        title: object,
        definition: ActionDefinition,
        arguments: Mapping[str, object],
        schedule: ScheduleSpec,
        missed_policy: object,
        confirmation_provenance: object,
        origin_chat_id: object = None,
        system_derived: bool = False,
    ) -> tuple[ScheduledWorkDefinition, ScheduledAuthorization]:
        text = _safe_text(title, "Scheduled-work title", MAX_TITLE_LENGTH)
        if not isinstance(definition, ActionDefinition):
            raise ScheduledWorkValidationError("A registered capability is required.")
        validated_schedule = validate_schedule(schedule)
        canonical_arguments = _validated_definition_arguments(
            definition, arguments, validated_schedule.mode,
            system_derived=system_derived,
        )
        policy = _enum(missed_policy, MISSED_POLICIES, "missed-run policy")
        provenance = _safe_text(
            confirmation_provenance,
            "Confirmation provenance",
            MAX_CONFIRMATION_PROVENANCE_LENGTH,
        )
        origin = validate_origin_chat_id(origin_chat_id)
        arguments_json = _canonical_json(canonical_arguments)
        schedule_json = schedule_to_json(validated_schedule)
        captured_now = _aware_utc(self._clock())
        stamp = format_utc_timestamp(captured_now)
        first = next_occurrence(validated_schedule, captured_now, inclusive=True)
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            job_id = validate_job_id(self._identifier_factory("work"))
            authorization_id = validate_authorization_id(
                self._identifier_factory("authorization")
            )
            job = ScheduledWorkDefinition(
                job_id, text, definition.identifier, definition.contract_version,
                arguments_json, schedule_json, validated_schedule.kind,
                validated_schedule.mode, validated_schedule.timezone_name, policy,
                "active", authorization_id, first.key, first.due_utc,
                first.local_date, stamp, stamp, None, None, None, 1, origin,
            )
            authorization = ScheduledAuthorization(
                authorization_id, job_id, 1, definition.identifier,
                definition.contract_version, arguments_json, _digest(arguments_json),
                schedule_json, _digest(schedule_json), validated_schedule.mode, policy,
                stamp, provenance, "active", stamp,
            )
            try:
                with closing(self._connect()) as connection, connection:
                    connection.execute("BEGIN IMMEDIATE")
                    _insert_definition(connection, job)
                    _insert_authorization(connection, authorization)
                    self._bump(connection)
            except sqlite3.IntegrityError as exc:
                if self._identifier_exists(job_id, authorization_id):
                    continue
                raise _database_error(exc) from exc
            return self._verify_definition(job), self._verify_authorization(authorization)
        raise ScheduledWorkConflictError("Could not allocate unique scheduled-work identifiers.")

    def get_definition(self, identifier: object) -> ScheduledWorkDefinition:
        job_id = validate_job_id(identifier)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_work_definitions WHERE identifier=?", (job_id,)
            ).fetchone()
        if row is None:
            raise ScheduledWorkNotFoundError("The scheduled-work definition was not found.")
        return _definition(row)

    def get_authorization(self, identifier: object) -> ScheduledAuthorization:
        authorization_id = validate_authorization_id(identifier)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_authorizations WHERE identifier=?",
                (authorization_id,),
            ).fetchone()
        if row is None:
            raise ScheduledWorkNotFoundError("The scheduled authorization was not found.")
        return _authorization(row)

    def get_run(self, identifier: object) -> ScheduledRun:
        run_id = validate_run_id(identifier)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_runs WHERE identifier=?", (run_id,)
            ).fetchone()
        if row is None:
            raise ScheduledWorkNotFoundError("The scheduled run was not found.")
        return _run(row)

    def list_definitions(
        self, statuses: Sequence[str] | None = None
    ) -> tuple[ScheduledWorkDefinition, ...]:
        selected = _statuses(statuses, DEFINITION_STATUSES)
        placeholders = ",".join("?" for _ in selected)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM scheduled_work_definitions WHERE status IN ({placeholders}) "
                "ORDER BY updated_at_utc DESC, identifier", selected,
            ).fetchall()
        return tuple(_definition(row) for row in rows)

    def list_runs(
        self, *, job_id: object | None = None, limit: int = 100
    ) -> tuple[ScheduledRun, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ScheduledWorkValidationError("The run-history limit is invalid.")
        parameters: tuple[object, ...] = (limit,)
        where = ""
        if job_id is not None:
            where = "WHERE job_id=?"
            parameters = (validate_job_id(job_id), limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM scheduled_runs {where} "
                "ORDER BY claim_at_utc DESC, identifier LIMIT ?", parameters,
            ).fetchall()
        return tuple(_run(row) for row in rows)

    def state(self) -> ScheduledWorkState:
        return ScheduledWorkState(
            self.revision(), self.list_definitions(), self.list_runs(limit=100)
        )

    def replace_definition(
        self,
        identifier: object,
        *,
        expected_revision: object,
        title: object,
        definition: ActionDefinition,
        arguments: Mapping[str, object],
        schedule: ScheduleSpec,
        missed_policy: object,
        confirmation_provenance: object,
        system_derived: bool = False,
    ) -> tuple[ScheduledWorkDefinition, ScheduledAuthorization]:
        job_id = validate_job_id(identifier)
        expected = _revision(expected_revision)
        text = _safe_text(title, "Scheduled-work title", MAX_TITLE_LENGTH)
        validated_schedule = validate_schedule(schedule)
        canonical_arguments = _validated_definition_arguments(
            definition, arguments, validated_schedule.mode,
            system_derived=system_derived,
        )
        policy = _enum(missed_policy, MISSED_POLICIES, "missed-run policy")
        provenance = _safe_text(
            confirmation_provenance,
            "Confirmation provenance",
            MAX_CONFIRMATION_PROVENANCE_LENGTH,
        )
        arguments_json = _canonical_json(canonical_arguments)
        schedule_json = schedule_to_json(validated_schedule)
        current = self.get_definition(job_id)
        if current.revision != expected:
            raise ScheduledWorkStaleRevisionError(
                "The scheduled work changed; refresh and try again."
            )
        if current.status not in {"active", "paused"}:
            raise ScheduledWorkConflictError(
                "Only active or paused scheduled work can be edited."
            )
        authorization_id = validate_authorization_id(
            self._identifier_factory("authorization")
        )
        stamp = self._next_stamp(current.updated_at_utc)
        first = (
            next_occurrence(validated_schedule, self._clock(), inclusive=True)
            if current.status == "active" else None
        )
        replacement = replace(
            current,
            title=text,
            capability_id=definition.identifier,
            capability_contract_version=definition.contract_version,
            arguments_json=arguments_json,
            schedule_json=schedule_json,
            schedule_kind=validated_schedule.kind,
            scheduled_mode=validated_schedule.mode,
            timezone_name=validated_schedule.timezone_name,
            missed_policy=policy,
            current_authorization_id=authorization_id,
            next_occurrence_key=None if first is None else first.key,
            next_occurrence_utc=None if first is None else first.due_utc,
            next_local_date=None if first is None else first.local_date,
            updated_at_utc=stamp,
            revision=expected + 1,
        )
        authorization = ScheduledAuthorization(
            authorization_id, job_id, expected + 1, definition.identifier,
            definition.contract_version, arguments_json, _digest(arguments_json),
            schedule_json, _digest(schedule_json), validated_schedule.mode, policy,
            stamp, provenance, "active", stamp,
        )
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,revision,current_authorization_id FROM scheduled_work_definitions "
                "WHERE identifier=?", (job_id,),
            ).fetchone()
            if row is None:
                raise ScheduledWorkNotFoundError("The scheduled-work definition was not found.")
            if row[1] != expected:
                raise ScheduledWorkStaleRevisionError(
                    "The scheduled work changed; refresh and try again."
                )
            if row[0] not in {"active", "paused"}:
                raise ScheduledWorkConflictError(
                    "Only active or paused scheduled work can be edited."
                )
            connection.execute(
                "UPDATE scheduled_authorizations SET status='superseded', "
                "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                (stamp, row[2]),
            )
            self._cancel_queued(connection, job_id, stamp, "authority_superseded",
                                "The scheduled authorization was replaced before execution.")
            _insert_authorization(connection, authorization)
            cursor = connection.execute(
                "UPDATE scheduled_work_definitions SET title=?,capability_id=?,"
                "capability_contract_version=?,arguments_json=?,schedule_json=?,"
                "schedule_kind=?,scheduled_mode=?,timezone_name=?,missed_policy=?,"
                "current_authorization_id=?,next_occurrence_key=?,next_occurrence_utc=?,"
                "next_local_date=?,updated_at_utc=?,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status IN ('active','paused')",
                (
                    replacement.title, replacement.capability_id,
                    replacement.capability_contract_version, replacement.arguments_json,
                    replacement.schedule_json, replacement.schedule_kind,
                    replacement.scheduled_mode, replacement.timezone_name,
                    replacement.missed_policy, replacement.current_authorization_id,
                    replacement.next_occurrence_key, replacement.next_occurrence_utc,
                    replacement.next_local_date, stamp, job_id, expected,
                ),
            )
            self._require_updated(cursor, "scheduled work")
            self._bump(connection)
        return self._verify_definition(replacement), self._verify_authorization(authorization)

    def pause_definition(
        self, identifier: object, *, expected_revision: object
    ) -> ScheduledWorkDefinition:
        return self._lifecycle(identifier, expected_revision, "paused")

    def resume_definition(
        self, identifier: object, *, expected_revision: object
    ) -> ScheduledWorkDefinition:
        job_id = validate_job_id(identifier)
        expected = _revision(expected_revision)
        current = self.get_definition(job_id)
        if current.status == "active":
            return current
        if current.revision != expected:
            raise ScheduledWorkStaleRevisionError(
                "The scheduled work changed; refresh and try again."
            )
        if current.status != "paused":
            raise ScheduledWorkConflictError("Only paused scheduled work can be resumed.")
        authorization = self.get_authorization(current.current_authorization_id)
        if authorization.status != "active":
            raise ScheduledWorkConflictError(
                "The scheduled authorization is no longer active."
            )
        stamp = self._next_stamp(current.updated_at_utc)
        occurrence = next_occurrence(current.schedule, self._clock(), inclusive=False)
        expected_record = replace(
            current, status="active", next_occurrence_key=occurrence.key,
            next_occurrence_utc=occurrence.due_utc,
            next_local_date=occurrence.local_date, updated_at_utc=stamp,
            paused_at_utc=None, revision=expected + 1,
        )
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE scheduled_work_definitions SET status='active',"
                "next_occurrence_key=?,next_occurrence_utc=?,next_local_date=?,"
                "updated_at_utc=?,paused_at_utc=NULL,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status='paused'",
                (occurrence.key, occurrence.due_utc, occurrence.local_date,
                 stamp, job_id, expected),
            )
            self._require_updated(cursor, "scheduled work")
            self._bump(connection)
        return self._verify_definition(expected_record)

    def cancel_definition(
        self, identifier: object, *, expected_revision: object
    ) -> ScheduledWorkDefinition:
        return self._lifecycle(identifier, expected_revision, "cancelled")

    def _lifecycle(
        self, identifier: object, expected_revision: object, target: str
    ) -> ScheduledWorkDefinition:
        job_id = validate_job_id(identifier)
        expected = _revision(expected_revision)
        current = self.get_definition(job_id)
        if current.status == target:
            return current
        if current.revision != expected:
            raise ScheduledWorkStaleRevisionError(
                "The scheduled work changed; refresh and try again."
            )
        if target == "paused" and current.status != "active":
            raise ScheduledWorkConflictError("Only active scheduled work can be paused.")
        if target == "cancelled" and current.status not in {"active", "paused"}:
            raise ScheduledWorkConflictError(
                "Only active or paused scheduled work can be cancelled."
            )
        stamp = self._next_stamp(current.updated_at_utc)
        expected_record = replace(
            current, status=target, next_occurrence_key=None,
            next_occurrence_utc=None,
            next_local_date=(current.next_local_date if target == "paused" else None),
            updated_at_utc=stamp,
            paused_at_utc=stamp if target == "paused" else None,
            cancelled_at_utc=stamp if target == "cancelled" else None,
            revision=expected + 1,
        )
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE scheduled_work_definitions SET status=?,next_occurrence_key=NULL,"
                "next_occurrence_utc=NULL,next_local_date=?,updated_at_utc=?,"
                "paused_at_utc=?,cancelled_at_utc=?,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status=?",
                (
                    target, expected_record.next_local_date, stamp,
                    expected_record.paused_at_utc, expected_record.cancelled_at_utc,
                    job_id, expected, current.status,
                ),
            )
            self._require_updated(cursor, "scheduled work")
            if target == "cancelled":
                connection.execute(
                    "UPDATE scheduled_authorizations SET status='revoked',"
                    "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                    (stamp, current.current_authorization_id),
                )
            self._cancel_queued(
                connection, job_id, stamp,
                "definition_paused" if target == "paused" else "authorization_revoked",
                "The scheduled work was paused before execution."
                if target == "paused" else
                "The scheduled work was cancelled before execution.",
            )
            self._bump(connection)
        return self._verify_definition(expected_record)

    def claim_due(
        self, detected_at: datetime, *, recovery: bool = False
    ) -> tuple[ScheduledRun, ...]:
        now = _aware_utc(detected_at)
        stamp = format_utc_timestamp(now)
        claimed: list[ScheduledRun] = []
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM scheduled_work_definitions WHERE status='active' "
                "AND next_occurrence_utc<=? ORDER BY next_occurrence_utc,identifier",
                (stamp,),
            ).fetchall()
            for row in rows:
                current = _definition(row)
                authorization_row = connection.execute(
                    "SELECT * FROM scheduled_authorizations WHERE identifier=?",
                    (current.current_authorization_id,),
                ).fetchone()
                if authorization_row is None:
                    raise ScheduledWorkCorruptError(
                        "A scheduled-work authorization is missing."
                    )
                authorization = _authorization(authorization_row)
                self._require_bound_authorization(current, authorization)
                occurrence = Occurrence(
                    current.next_occurrence_key or "",
                    current.next_occurrence_utc or "",
                    current.next_local_date,
                    _occurrence_is_gap(current.next_occurrence_key or ""),
                )
                missed = (
                    recovery and parse_utc_timestamp(occurrence.due_utc) < now
                )
                if current.scheduled_mode == "recurring" and missed:
                    occurrence, missed_count, first_key = _latest_missed_occurrence(
                        current.schedule, occurrence, now
                    )
                else:
                    missed_count = 1 if missed else 0
                    first_key = occurrence.key if missed else None
                should_skip = occurrence.dst_gap or (
                    missed and current.missed_policy == "skip_if_missed"
                )
                run = self._new_run(
                    current, occurrence, stamp,
                    status="skipped" if should_skip else "queued",
                    failure_code=(
                        "dst_nonexistent_local_time" if occurrence.dst_gap else
                        "missed_while_unavailable" if should_skip else None
                    ),
                    failure_message=(
                        "This recurring local time did not exist because the clock moved forward."
                        if occurrence.dst_gap else
                        "The occurrence was skipped by its missed-run policy."
                        if should_skip else None
                    ),
                    missed_count=missed_count,
                    missed_first_key=first_key,
                    missed_last_key=occurrence.key if missed_count else None,
                )
                try:
                    _insert_run(connection, run)
                except sqlite3.IntegrityError:
                    continue
                if should_skip:
                    self._insert_notification(connection, run.identifier, stamp)
                if current.scheduled_mode == "one_shot":
                    update_stamp = _later_stamp(stamp, current.updated_at_utc)
                    connection.execute(
                        "UPDATE scheduled_work_definitions SET status='completed',"
                        "next_occurrence_key=NULL,next_occurrence_utc=NULL,next_local_date=NULL,"
                        "updated_at_utc=?,completed_at_utc=?,revision=revision+1 "
                        "WHERE identifier=? AND revision=? AND status='active'",
                        (update_stamp, update_stamp, current.identifier, current.revision),
                    )
                    connection.execute(
                        "UPDATE scheduled_authorizations SET status='exhausted',"
                        "status_changed_at_utc=? WHERE identifier=? AND status='active'",
                        (update_stamp, authorization.identifier),
                    )
                else:
                    following = next_occurrence_after(
                        current.schedule, occurrence.local_date, occurrence.due_utc
                    )
                    connection.execute(
                        "UPDATE scheduled_work_definitions SET next_occurrence_key=?,"
                        "next_occurrence_utc=?,next_local_date=?,updated_at_utc=?,"
                        "revision=revision+1 WHERE identifier=? AND revision=? AND status='active'",
                        (
                            following.key, following.due_utc, following.local_date,
                            _later_stamp(stamp, current.updated_at_utc), current.identifier,
                            current.revision,
                        ),
                    )
                self._bump(connection)
                claimed.append(run)
        return tuple(self.get_run(item.identifier) for item in claimed)

    def recover_startup(self, detected_at: datetime) -> tuple[ScheduledRun, ...]:
        now = _aware_utc(detected_at)
        stamp = format_utc_timestamp(now)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM scheduled_runs WHERE status='running'"
            ).fetchall()
            for row in rows:
                run = _run(row)
                finished = _later_stamp(stamp, run.started_at_utc or run.claim_at_utc)
                cursor = connection.execute(
                    "UPDATE scheduled_runs SET status='interrupted',finished_at_utc=?,"
                    "failure_code='process_interrupted',failure_message=?,revision=revision+1 "
                    "WHERE identifier=? AND revision=? AND status='running'",
                    (
                        finished,
                        "The application stopped after work may have started; the outcome is indeterminate.",
                        run.identifier, run.revision,
                    ),
                )
                if cursor.rowcount == 1:
                    self._insert_notification(connection, run.identifier, finished)
                    self._bump(connection)
        return self.claim_due(now, recovery=True)

    def next_due_utc(self) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT next_occurrence_utc FROM scheduled_work_definitions "
                "WHERE status='active' ORDER BY next_occurrence_utc,identifier LIMIT 1"
            ).fetchone()
        return None if row is None else _timestamp(row[0])

    def next_queued_run(self) -> ScheduledRun | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_runs WHERE status='queued' "
                "ORDER BY claim_at_utc,identifier LIMIT 1"
            ).fetchone()
        return None if row is None else _run(row)

    def start_run(self, identifier: object) -> ScheduledRun:
        run_id = validate_run_id(identifier)
        current = self.get_run(run_id)
        if current.status != "queued":
            return current
        stamp = self._next_stamp(current.claim_at_utc)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE scheduled_runs SET status='running',started_at_utc=?,"
                "revision=revision+1 WHERE identifier=? AND revision=? AND status='queued'",
                (stamp, run_id, current.revision),
            )
            self._require_updated(cursor, "scheduled run")
            self._bump(connection)
        return self.get_run(run_id)

    def mark_work_started(self, identifier: object, *, expected_revision: object) -> ScheduledRun:
        run_id = validate_run_id(identifier)
        expected = _revision(expected_revision)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE scheduled_runs SET work_started=1,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status='running' AND work_started=0",
                (run_id, expected),
            )
            self._require_updated(cursor, "scheduled run")
            self._bump(connection)
        return self.get_run(run_id)

    def finish_run_success(
        self, identifier: object, *, expected_revision: object, result: Mapping[str, object]
    ) -> ScheduledRun:
        return self._finish_run(
            identifier, expected_revision=expected_revision, status="succeeded",
            result_json=_canonical_json(result), failure_code=None, failure_message=None,
        )

    def finish_run_failure(
        self,
        identifier: object,
        *,
        expected_revision: object,
        code: object,
        message: object,
    ) -> ScheduledRun:
        failure_code = _failure_code(code)
        failure_message = _safe_text(message, "Failure message", MAX_FAILURE_LENGTH)
        return self._finish_run(
            identifier, expected_revision=expected_revision, status="failed",
            result_json=None, failure_code=failure_code,
            failure_message=failure_message,
        )

    def _finish_run(
        self,
        identifier: object,
        *,
        expected_revision: object,
        status: str,
        result_json: str | None,
        failure_code: str | None,
        failure_message: str | None,
    ) -> ScheduledRun:
        run_id = validate_run_id(identifier)
        expected = _revision(expected_revision)
        current = self.get_run(run_id)
        if current.status in TERMINAL_RUN_STATUSES:
            return current
        if current.revision != expected or current.status != "running":
            raise ScheduledWorkStaleRevisionError(
                "The scheduled run changed; refresh and try again."
            )
        if status == "succeeded" and not current.work_started:
            raise ScheduledWorkConflictError(
                "A scheduled run cannot succeed before work starts."
            )
        stamp = self._next_stamp(current.started_at_utc or current.claim_at_utc)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE scheduled_runs SET status=?,finished_at_utc=?,result_json=?,"
                "failure_code=?,failure_message=?,revision=revision+1 "
                "WHERE identifier=? AND revision=? AND status='running'",
                (
                    status, stamp, result_json, failure_code, failure_message,
                    run_id, expected,
                ),
            )
            self._require_updated(cursor, "scheduled run")
            self._insert_notification(connection, run_id, stamp)
            self._bump(connection)
        return self.get_run(run_id)

    def pending_notifications(self) -> tuple[ScheduledNotification, ...]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_notifications WHERE state='pending' "
                "ORDER BY queued_at_utc,event_identifier"
            ).fetchall()
        return tuple(_notification(row) for row in rows)

    def mark_notification_archived(
        self, run_id: object, event_identifier: object, *, chat_id: object
    ) -> ScheduledNotification:
        run = validate_run_id(run_id)
        event = validate_event_id(event_identifier)
        if not isinstance(chat_id, str) or not re.fullmatch(r"chat-[0-9a-f]{32}", chat_id):
            raise ScheduledWorkValidationError("A valid chat identifier is required.")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM scheduled_notifications WHERE run_id=?", (run,)
            ).fetchone()
            if row is None:
                raise ScheduledWorkNotFoundError("The scheduled notification was not found.")
            current = _notification(row)
            if current.event_identifier != event:
                raise ScheduledWorkConflictError("The notification identity does not match.")
            if (
                current.origin_chat_id is not None
                and current.origin_chat_id != chat_id
            ):
                raise ScheduledWorkConflictError(
                    "An origin-bound notification cannot be archived in another conversation."
                )
            if current.state == "archived":
                if current.chat_id != chat_id:
                    raise ScheduledWorkConflictError(
                        "The notification was archived in another conversation."
                    )
                return current
            stamp = _later_stamp(
                format_utc_timestamp(self._clock()), current.queued_at_utc
            )
            cursor = connection.execute(
                "UPDATE scheduled_notifications SET state='archived',archived_at_utc=?,"
                "chat_id=? WHERE run_id=? AND state='pending'",
                (stamp, chat_id, run),
            )
            self._require_updated(cursor, "scheduled notification")
            self._bump(connection)
        return self._notification(run)

    def delete_terminal_run(
        self, identifier: object, *, expected_revision: object
    ) -> None:
        run_id = validate_run_id(identifier)
        expected = _revision(expected_revision)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,revision FROM scheduled_runs WHERE identifier=?", (run_id,)
            ).fetchone()
            if row is None:
                raise ScheduledWorkNotFoundError("The scheduled run was not found.")
            if row[1] != expected:
                raise ScheduledWorkStaleRevisionError(
                    "The scheduled run changed; refresh and try again."
                )
            if row[0] not in TERMINAL_RUN_STATUSES:
                raise ScheduledWorkConflictError(
                    "Only terminal scheduled-run history can be permanently deleted."
                )
            connection.execute(
                "DELETE FROM scheduled_notifications WHERE run_id=?", (run_id,)
            )
            cursor = connection.execute(
                "DELETE FROM scheduled_runs WHERE identifier=? AND revision=?",
                (run_id, expected),
            )
            self._require_updated(cursor, "scheduled run")
            self._bump(connection)
        with closing(self._connect()) as connection:
            if connection.execute(
                "SELECT 1 FROM scheduled_runs WHERE identifier=?", (run_id,)
            ).fetchone() is not None:
                raise ScheduledWorkVerificationError(
                    "The scheduled-run deletion could not be verified."
                )

    def delete_resolved_definition(
        self, identifier: object, *, expected_revision: object
    ) -> None:
        job_id = validate_job_id(identifier)
        expected = _revision(expected_revision)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,revision FROM scheduled_work_definitions WHERE identifier=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise ScheduledWorkNotFoundError("The scheduled-work definition was not found.")
            if row[1] != expected:
                raise ScheduledWorkStaleRevisionError(
                    "The scheduled work changed; refresh and try again."
                )
            if row[0] not in {"completed", "cancelled"}:
                raise ScheduledWorkConflictError(
                    "Only completed or cancelled scheduled-work history can be deleted."
                )
            if connection.execute(
                "SELECT 1 FROM scheduled_runs WHERE job_id=? LIMIT 1", (job_id,)
            ).fetchone() is not None:
                raise ScheduledWorkConflictError(
                    "This scheduled work still has run history. Delete those runs first."
                )
            cursor = connection.execute(
                "DELETE FROM scheduled_work_definitions WHERE identifier=? AND revision=?",
                (job_id, expected),
            )
            self._require_updated(cursor, "scheduled work")
            self._bump(connection)
        with closing(self._connect()) as connection:
            if connection.execute(
                "SELECT 1 FROM scheduled_work_definitions WHERE identifier=?", (job_id,)
            ).fetchone() is not None:
                raise ScheduledWorkVerificationError(
                    "The scheduled-work deletion could not be verified."
                )

    def _new_run(
        self,
        definition: ScheduledWorkDefinition,
        occurrence: Occurrence,
        stamp: str,
        *,
        status: str,
        failure_code: str | None,
        failure_message: str | None,
        missed_count: int,
        missed_first_key: str | None,
        missed_last_key: str | None,
    ) -> ScheduledRun:
        run_id = validate_run_id(self._identifier_factory("run"))
        terminal = status in TERMINAL_RUN_STATUSES
        return ScheduledRun(
            run_id, definition.identifier, definition.revision,
            definition.current_authorization_id, definition.capability_id,
            definition.capability_contract_version, occurrence.key,
            occurrence.due_utc, stamp, None, stamp if terminal else None,
            status, False, None, failure_code, failure_message,
            missed_count, missed_first_key, missed_last_key, 1,
        )

    def _cancel_queued(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        stamp: str,
        code: str,
        message: str,
    ) -> None:
        rows = connection.execute(
            "SELECT identifier,claim_at_utc FROM scheduled_runs "
            "WHERE job_id=? AND status='queued'", (job_id,),
        ).fetchall()
        for run_id, claim in rows:
            finished = _later_stamp(stamp, claim)
            cursor = connection.execute(
                "UPDATE scheduled_runs SET status='cancelled_before_start',"
                "finished_at_utc=?,failure_code=?,failure_message=?,revision=revision+1 "
                "WHERE identifier=? AND status='queued'",
                (finished, code, message, run_id),
            )
            if cursor.rowcount == 1:
                self._insert_notification(connection, run_id, finished)

    def _insert_notification(
        self, connection: sqlite3.Connection, run_id: str, stamp: str
    ) -> None:
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            event_id = validate_event_id(self._identifier_factory("event"))
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO scheduled_notifications (
                        run_id,event_identifier,state,queued_at_utc,
                        archived_at_utc,chat_id,origin_chat_id
                    )
                    SELECT ?,?,'pending',?,NULL,NULL,d.origin_chat_id
                    FROM scheduled_runs AS r
                    JOIN scheduled_work_definitions AS d ON d.identifier=r.job_id
                    WHERE r.identifier=?
                    """,
                    (run_id, event_id, stamp, run_id),
                )
                if cursor.rowcount != 1:
                    raise ScheduledWorkCorruptError(
                        "The scheduled notification has no durable definition origin."
                    )
                return
            except sqlite3.IntegrityError:
                if connection.execute(
                    "SELECT 1 FROM scheduled_notifications WHERE run_id=?", (run_id,)
                ).fetchone() is not None:
                    return
        raise ScheduledWorkConflictError("Could not allocate a notification identity.")

    def _notification(self, run_id: str) -> ScheduledNotification:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_notifications WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise ScheduledWorkNotFoundError("The scheduled notification was not found.")
        return _notification(row)

    @staticmethod
    def _require_bound_authorization(
        definition: ScheduledWorkDefinition,
        authorization: ScheduledAuthorization,
    ) -> None:
        if (
            authorization.status != "active"
            or authorization.identifier != definition.current_authorization_id
            or authorization.job_id != definition.identifier
            or authorization.job_revision > definition.revision
            or authorization.capability_id != definition.capability_id
            or authorization.capability_contract_version
            != definition.capability_contract_version
            or authorization.arguments_json != definition.arguments_json
            or authorization.arguments_digest != _digest(definition.arguments_json)
            or authorization.schedule_json != definition.schedule_json
            or authorization.schedule_digest != _digest(definition.schedule_json)
            or authorization.scheduled_mode != definition.scheduled_mode
            or authorization.missed_policy != definition.missed_policy
        ):
            raise ScheduledWorkConflictError(
                "The scheduled authorization no longer matches its definition."
            )

    def _identifier_exists(self, job_id: str, authorization_id: str) -> bool:
        with closing(self._connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM scheduled_work_definitions WHERE identifier=? "
                "UNION SELECT 1 FROM scheduled_authorizations WHERE identifier=?",
                (job_id, authorization_id),
            ).fetchone() is not None

    def _verify_definition(
        self, expected: ScheduledWorkDefinition
    ) -> ScheduledWorkDefinition:
        try:
            actual = self.get_definition(expected.identifier)
        except ScheduledWorkError as exc:
            raise ScheduledWorkVerificationError(
                "The scheduled-work change committed but could not be verified."
            ) from exc
        if actual != expected:
            raise ScheduledWorkVerificationError(
                "The scheduled-work change did not verify."
            )
        return actual

    def _verify_authorization(
        self, expected: ScheduledAuthorization
    ) -> ScheduledAuthorization:
        try:
            actual = self.get_authorization(expected.identifier)
        except ScheduledWorkError as exc:
            raise ScheduledWorkVerificationError(
                "The scheduled authorization committed but could not be verified."
            ) from exc
        if actual != expected:
            raise ScheduledWorkVerificationError(
                "The scheduled authorization did not verify."
            )
        return actual

    @staticmethod
    def _bump(connection: sqlite3.Connection) -> None:
        cursor = connection.execute(
            "UPDATE scheduled_work_state SET revision=revision+1 WHERE singleton=1"
        )
        if cursor.rowcount != 1:
            raise ScheduledWorkCorruptError("Scheduled-work state is invalid.")

    @staticmethod
    def _require_updated(cursor: sqlite3.Cursor, label: str) -> None:
        if cursor.rowcount != 1:
            raise ScheduledWorkStaleRevisionError(
                f"The {label} changed; refresh and try again."
            )

    def _next_stamp(self, previous: str) -> str:
        return _later_stamp(format_utc_timestamp(self._clock()), previous)

    def _connect(self) -> _ScheduledConnection:
        parent: int | None = None
        database: int | None = None
        connection: _ScheduledConnection | None = None
        try:
            parent, name = self._open_parent(create=True)
            sidecars = [
                _stat_at(parent, name + suffix)
                for suffix in ("-journal", "-wal", "-shm")
            ]
            existing = _stat_at(parent, name)
            flags = os.O_RDWR | _no_follow() | getattr(os, "O_CLOEXEC", 0)
            if existing is None:
                if any(item is not None for item in sidecars):
                    raise OSError("orphaned scheduled-work sidecar")
                self._initialize_then_publish(parent, name, flags)
                existing = _stat_at(parent, name)
            if existing is None or not stat.S_ISREG(existing.st_mode):
                raise OSError("unsafe scheduled-work database entry")
            database = os.open(name, flags, dir_fd=parent)
            if not _same_file(existing, os.fstat(database)):
                raise OSError("scheduled-work database changed during open")
            sqlite_path = f"/proc/self/fd/{parent}/{name}"
            readonly = sqlite3.connect(
                "file:" + quote(sqlite_path, safe="/") + "?mode=ro&immutable=1",
                uri=True,
            )
            try:
                self._validate_schema(readonly)
            finally:
                readonly.close()
            connection = sqlite3.connect(
                sqlite_path, factory=_ScheduledConnection, timeout=5.0
            )
            current = _stat_at(parent, name)
            if current is None or not _same_file(os.fstat(database), current):
                raise OSError("scheduled-work database changed during SQLite open")
            self._validate_schema(connection)
            self._apply_settings(connection)
            connection.row_factory = sqlite3.Row
            connection._safe_descriptors = (parent, database)
            return connection
        except ScheduledWorkError as exc:
            failure: BaseException = exc
        except sqlite3.DatabaseError:
            failure = ScheduledWorkCorruptError(
                "Tori's scheduled-work database is corrupt or invalid; it was preserved."
            )
        except (OSError, sqlite3.Error):
            failure = ScheduledWorkUnavailableError(
                "Tori's scheduled-work database is unavailable."
            )
        if connection is not None:
            connection.close()
        for descriptor in (database, parent):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise failure

    def _initialize_then_publish(self, parent: int, name: str, flags: int) -> None:
        temporary = f".{name}.incomplete-{secrets.token_hex(16)}"
        descriptor = os.open(
            temporary, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
        )
        published = False
        connection: sqlite3.Connection | None = None
        try:
            original = os.fstat(descriptor)
            sqlite_path = f"/proc/self/fd/{parent}/{temporary}"
            connection = sqlite3.connect(sqlite_path)
            self._apply_settings(connection)
            with connection:
                for sql in (
                    _METADATA_SQL, _STATE_SQL, _DEFINITIONS_SQL,
                    _AUTHORIZATIONS_SQL, _RUNS_SQL, _NOTIFICATIONS_SQL,
                    _DEFINITION_INDEX_SQL, _RUN_INDEX_SQL, _RUN_JOB_INDEX_SQL,
                ):
                    connection.execute(sql)
                connection.execute(
                    "INSERT INTO scheduled_work_metadata VALUES ('schema_version',?)",
                    (str(SCHEDULED_WORK_SCHEMA_VERSION),),
                )
                connection.execute("INSERT INTO scheduled_work_state VALUES (1,1)")
            self._validate_schema(connection)
            connection.close()
            connection = None
            if any(
                _stat_at(parent, temporary + suffix) is not None
                for suffix in ("-journal", "-wal", "-shm")
            ):
                raise OSError("scheduled-work initialization sidecar exists")
            if not _same_file(original, _stat_at(parent, temporary)):
                raise OSError("scheduled-work initialization entry changed")
            os.fsync(descriptor)
            _rename_noreplace(parent, temporary, name)
            published = True
            os.fsync(parent)
        except BaseException as exc:
            if published:
                raise
            raise ScheduledWorkUnavailableError(
                f"Scheduled-work initialization failed; isolated artifact {temporary!r} was preserved."
            ) from exc
        finally:
            if connection is not None:
                connection.close()
            os.close(descriptor)

    def _open_parent(self, *, create: bool) -> tuple[int, str]:
        raw = os.fspath(self._path)
        if not isinstance(raw, str) or "\x00" in raw or ".." in Path(raw).parts:
            raise ScheduledWorkUnavailableError("The scheduled-work path is unsafe.")
        absolute = Path(os.path.abspath(os.path.normpath(raw)))
        if not absolute.name:
            raise ScheduledWorkUnavailableError("The scheduled-work path is unsafe.")
        flags = os.O_RDONLY | _directory() | _no_follow() | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open("/", flags)
        try:
            for part in absolute.parent.parts[1:]:
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=descriptor)
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    os.close(child)
                    raise OSError("unsafe scheduled-work ancestor")
                os.close(descriptor)
                descriptor = child
            return descriptor, absolute.name
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _apply_settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA journal_mode=DELETE")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        if _legacy_scheduled_schema_is_exact(connection):
            raise ScheduledWorkVersionError(
                "Scheduled-work schema version 1 requires the explicit 1-to-2 "
                "migration while Tori is stopped; it was not modified."
            )
        expected_sql = {
            "scheduled_work_metadata": _METADATA_SQL,
            "scheduled_work_state": _STATE_SQL,
            "scheduled_work_definitions": _DEFINITIONS_SQL,
            "scheduled_authorizations": _AUTHORIZATIONS_SQL,
            "scheduled_runs": _RUNS_SQL,
            "scheduled_notifications": _NOTIFICATIONS_SQL,
            "scheduled_work_due_index": _DEFINITION_INDEX_SQL,
            "scheduled_runs_status_claim_index": _RUN_INDEX_SQL,
            "scheduled_runs_job_finish_index": _RUN_JOB_INDEX_SQL,
        }
        actual = {
            name: sql
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_autoindex_%'"
            )
            if kind in {"table", "index"}
        }
        if set(actual) != set(expected_sql) or any(
            not isinstance(actual[name], str)
            or _normalize_sql(actual[name]) != _normalize_sql(sql)
            for name, sql in expected_sql.items()
        ):
            raise ScheduledWorkCorruptError(
                "Tori's scheduled-work database has an invalid schema; it was preserved."
            )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1"
        ).fetchone() is not None:
            raise ScheduledWorkCorruptError(
                "Tori's scheduled-work database has unexpected schema objects."
            )
        metadata = connection.execute(
            "SELECT key,value FROM scheduled_work_metadata"
        ).fetchall()
        if len(metadata) != 1 or tuple(metadata[0]) != (
            "schema_version", str(SCHEDULED_WORK_SCHEMA_VERSION)
        ):
            if (
                len(metadata) == 1 and metadata[0][0] == "schema_version"
                and isinstance(metadata[0][1], str) and metadata[0][1].isdigit()
            ):
                raise ScheduledWorkVersionError(
                    f"Scheduled-work schema version {metadata[0][1]} is unsupported; it was not modified."
                )
            raise ScheduledWorkCorruptError(
                "Tori's scheduled-work schema metadata is invalid."
            )
        state = connection.execute(
            "SELECT singleton,revision FROM scheduled_work_state"
        ).fetchall()
        if (
            len(state) != 1 or state[0][0] != 1
            or isinstance(state[0][1], bool) or not isinstance(state[0][1], int)
            or state[0][1] < 1
        ):
            raise ScheduledWorkCorruptError("Scheduled-work state is invalid.")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ScheduledWorkCorruptError(
                "Tori's scheduled-work foreign-key state is invalid."
            )
        for row in connection.execute("SELECT * FROM scheduled_work_definitions"):
            _definition(row)
        for row in connection.execute("SELECT * FROM scheduled_authorizations"):
            _authorization(row)
        for row in connection.execute("SELECT * FROM scheduled_runs"):
            _run(row)
        for row in connection.execute("SELECT * FROM scheduled_notifications"):
            _notification(row)


def _legacy_scheduled_schema_is_exact(connection: sqlite3.Connection) -> bool:
    expected_sql = {
        "scheduled_work_metadata": _METADATA_SQL,
        "scheduled_work_state": _STATE_SQL,
        "scheduled_work_definitions": _LEGACY_DEFINITIONS_SQL,
        "scheduled_authorizations": _AUTHORIZATIONS_SQL,
        "scheduled_runs": _RUNS_SQL,
        "scheduled_notifications": _LEGACY_NOTIFICATIONS_SQL,
        "scheduled_work_due_index": _DEFINITION_INDEX_SQL,
        "scheduled_runs_status_claim_index": _RUN_INDEX_SQL,
        "scheduled_runs_job_finish_index": _RUN_JOB_INDEX_SQL,
    }
    try:
        actual = {
            name: sql
            for kind, name, sql in connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_autoindex_%'"
            )
            if kind in {"table", "index"}
        }
        metadata = connection.execute(
            "SELECT key,value FROM scheduled_work_metadata"
        ).fetchall()
    except sqlite3.Error:
        return False
    return (
        len(metadata) == 1
        and tuple(metadata[0])
        == ("schema_version", str(LEGACY_SCHEDULED_WORK_SCHEMA_VERSION))
        and set(actual) == set(expected_sql)
        and all(
            isinstance(actual[name], str)
            and _normalize_sql(actual[name]) == _normalize_sql(sql)
            for name, sql in expected_sql.items()
        )
        and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') LIMIT 1"
        ).fetchone()
        is None
    )


class ScheduledWorkExecutor:
    """Execute only queued durable runs proven against the capability catalog."""

    def __init__(
        self, store: SQLiteScheduledWorkStore, catalog: ScheduledCapabilityCatalog
    ) -> None:
        self._store = store
        self._catalog = catalog

    def execute_next(self) -> ScheduledRun | None:
        queued = self._store.next_queued_run()
        if queued is None:
            return None
        try:
            running = self._store.start_run(queued.identifier)
        except ScheduledWorkStaleRevisionError:
            return None
        if running.status != "running":
            return running
        try:
            authorization = self._store.get_authorization(running.authorization_id)
            definition = self._store.get_definition(running.job_id)
            allowed_authorization_status = (
                "exhausted" if authorization.scheduled_mode == "one_shot" else "active"
            )
            if (
                authorization.status != allowed_authorization_status
                or authorization.job_id != running.job_id
                or authorization.job_revision > running.definition_revision
                or authorization.capability_id != running.capability_id
                or authorization.capability_contract_version
                != running.capability_contract_version
                or authorization.arguments_digest != _digest(authorization.arguments_json)
                or authorization.schedule_digest != _digest(authorization.schedule_json)
                or definition.current_authorization_id != authorization.identifier
                and authorization.scheduled_mode != "one_shot"
            ):
                raise ScheduledCapabilityError(
                    "The durable scheduled authorization no longer matches this run.",
                    code="authorization_mismatch",
                )
            capability, canonical_arguments = self._catalog.validate(
                running.capability_id,
                running.capability_contract_version,
                _json_mapping(authorization.arguments_json),
                authorization.scheduled_mode,
                system_derived=True,
            )
            if _canonical_json(canonical_arguments) != authorization.arguments_json:
                raise ScheduledCapabilityError(
                    "The scheduled arguments no longer match their authorization.",
                    code="argument_mismatch",
                )
            availability = capability.availability()
            if not availability.available:
                return self._store.finish_run_failure(
                    running.identifier,
                    expected_revision=running.revision,
                    code=availability.code,
                    message=availability.message or "The capability is unavailable.",
                )
            running = self._store.mark_work_started(
                running.identifier, expected_revision=running.revision
            )
            result = capability.execute(canonical_arguments, running.identifier)
            return self._store.finish_run_success(
                running.identifier,
                expected_revision=running.revision,
                result=result,
            )
        except (ScheduledCapabilityError, ActionContractError, BackupError) as exc:
            current = self._store.get_run(running.identifier)
            if current.status in TERMINAL_RUN_STATUSES:
                return current
            code = getattr(exc, "code", "capability_failed")
            message = _bounded_failure(str(exc))
            return self._store.finish_run_failure(
                current.identifier,
                expected_revision=current.revision,
                code=code,
                message=message,
            )
        except Exception as error:
            current = self._store.get_run(running.identifier)
            if current.status in TERMINAL_RUN_STATUSES:
                return current
            supplied_code = getattr(error, "code", None)
            if isinstance(supplied_code, str) and _SAFE_CODE.fullmatch(supplied_code):
                return self._store.finish_run_failure(
                    current.identifier,
                    expected_revision=current.revision,
                    code=supplied_code,
                    message=_bounded_failure(str(error)),
                )
            LOGGER.exception("A scheduled capability failed safely.")
            return self._store.finish_run_failure(
                current.identifier,
                expected_revision=current.revision,
                code="executor_internal_error",
                message="The scheduled capability executor failed safely.",
            )


class ScheduledWorkCoordinator:
    """Claim due work and run one bounded scheduled execution at a time."""

    def __init__(
        self,
        store: SQLiteScheduledWorkStore,
        catalog: ScheduledCapabilityCatalog,
        *,
        clock: Callable[[], datetime] | None = None,
        state_changed: Callable[[], None] | None = None,
        recheck_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state_changed = state_changed or (lambda: None)
        self._executor = ScheduledWorkExecutor(store, catalog)
        self._worker_wake = threading.Event()
        self._worker_stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._startup_recovered = False
        self._loop = DeadlineLoop(
            initialize=self._initialize,
            scan=self._scan,
            next_deadline=self._next_deadline,
            clock=self._clock,
            handled_error=ScheduledWorkError,
            name="tori-scheduled-work-coordinator",
            failure_message="The scheduled-work coordinator could not access durable state safely.",
            recheck_seconds=recheck_seconds,
        )

    @property
    def running(self) -> bool:
        return self._loop.running

    @property
    def failed(self) -> bool:
        return self._loop.failed

    @property
    def worker_running(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    def start(self) -> None:
        self._loop.start()

    def notify_schedule_changed(self) -> None:
        self._loop.wake()
        self._worker_wake.set()

    def scan_once(self, *, recovery: bool = False) -> tuple[ScheduledRun, ...]:
        now = _aware_utc(self._clock())
        claimed = (
            self._store.recover_startup(now)
            if recovery else self._store.claim_due(now)
        )
        if claimed:
            self._state_changed()
        if claimed or self._store.next_queued_run() is not None:
            self._worker_wake.set()
        return claimed

    def execute_once(self) -> ScheduledRun | None:
        result = self._executor.execute_next()
        if result is not None:
            operator_event(
                "scheduled_work.execution.completed",
                capability=result.capability_id,
                state=result.status,
            )
            self._state_changed()
        return result

    def stop(self, *, timeout: float = 5.0) -> None:
        self._loop.stop(timeout=timeout)
        self._worker_stop.set()
        self._worker_wake.set()
        worker = self._worker
        if worker is not None:
            # A synchronous capability, notably backup, is allowed to finish.
            worker.join()
        with self._worker_lock:
            if self._worker is worker:
                self._worker = None

    def _initialize(self) -> None:
        self._store.initialize()
        self._worker_stop.clear()
        self._worker_wake.clear()
        self._startup_recovered = False
        with self._worker_lock:
            if not self.worker_running:
                self._worker = threading.Thread(
                    target=self._worker_main,
                    name="tori-scheduled-work-executor",
                    daemon=False,
                )
                self._worker.start()

    def _scan(self) -> None:
        self.scan_once(recovery=not self._startup_recovered)
        self._startup_recovered = True

    def _next_deadline(self) -> datetime | None:
        value = self._store.next_due_utc()
        return None if value is None else parse_utc_timestamp(value)

    def _worker_main(self) -> None:
        while not self._worker_stop.is_set():
            try:
                while not self._worker_stop.is_set():
                    result = self.execute_once()
                    if result is None:
                        break
            except ScheduledWorkError:
                LOGGER.error("The scheduled-work executor could not access durable state safely.")
            self._worker_wake.wait(1.0)
            self._worker_wake.clear()


def one_shot_schedule(occurrence_utc: datetime, timezone_name: str) -> ScheduleSpec:
    return validate_schedule(ScheduleSpec(
        "one_shot", validate_timezone_name(timezone_name),
        occurrence_utc=format_utc_timestamp(occurrence_utc),
    ))


def daily_schedule(
    start_date: date, local_time: civil_time, timezone_name: str
) -> ScheduleSpec:
    return validate_schedule(ScheduleSpec(
        "daily", validate_timezone_name(timezone_name),
        start_date=start_date.isoformat(), local_time=_format_local_time(local_time),
    ))


def weekly_schedule(
    start_date: date,
    local_time: civil_time,
    timezone_name: str,
    weekdays: Sequence[int],
) -> ScheduleSpec:
    return validate_schedule(ScheduleSpec(
        "weekly", validate_timezone_name(timezone_name),
        start_date=start_date.isoformat(), local_time=_format_local_time(local_time),
        weekdays=tuple(weekdays),
    ))


def validate_schedule(value: object) -> ScheduleSpec:
    if not isinstance(value, ScheduleSpec) or value.kind not in SCHEDULE_KINDS:
        raise ScheduledWorkValidationError("The schedule type is invalid.")
    zone = validate_timezone_name(value.timezone_name)
    if value.kind == "one_shot":
        if (
            value.occurrence_utc is None or value.start_date is not None
            or value.local_time is not None or value.weekdays
        ):
            raise ScheduledWorkValidationError("The one-shot schedule is invalid.")
        _timestamp(value.occurrence_utc)
        return ScheduleSpec("one_shot", zone, occurrence_utc=value.occurrence_utc)
    if value.occurrence_utc is not None:
        raise ScheduledWorkValidationError("A recurring schedule cannot contain a one-shot instant.")
    start = _date(value.start_date)
    local = _local_time(value.local_time)
    if value.kind == "daily":
        if value.weekdays:
            raise ScheduledWorkValidationError("A daily schedule cannot contain weekdays.")
        return ScheduleSpec(
            "daily", zone, start_date=start.isoformat(),
            local_time=_format_local_time(local),
        )
    weekdays = tuple(sorted(dict.fromkeys(value.weekdays)))
    if not weekdays or any(
        isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6
        for item in weekdays
    ):
        raise ScheduledWorkValidationError("A weekly schedule requires valid weekdays.")
    return ScheduleSpec(
        "weekly", zone, start_date=start.isoformat(),
        local_time=_format_local_time(local), weekdays=weekdays,
    )


def schedule_to_json(schedule: ScheduleSpec) -> str:
    return _canonical_json(validate_schedule(schedule).document())


def schedule_from_json(value: object) -> ScheduleSpec:
    document = _json_mapping(value)
    kind = document.get("kind")
    timezone_name = document.get("timezone")
    if kind == "one_shot" and set(document) == {"kind", "timezone", "occurrence_utc"}:
        return validate_schedule(ScheduleSpec(
            kind, timezone_name, occurrence_utc=document["occurrence_utc"]  # type: ignore[arg-type]
        ))
    if kind == "daily" and set(document) == {
        "kind", "timezone", "start_date", "local_time"
    }:
        return validate_schedule(ScheduleSpec(
            kind, timezone_name, start_date=document["start_date"],  # type: ignore[arg-type]
            local_time=document["local_time"],  # type: ignore[arg-type]
        ))
    if kind == "weekly" and set(document) == {
        "kind", "timezone", "start_date", "local_time", "weekdays"
    }:
        weekdays = document["weekdays"]
        if not isinstance(weekdays, list):
            raise ScheduledWorkValidationError("The weekly schedule is invalid.")
        return validate_schedule(ScheduleSpec(
            kind, timezone_name, start_date=document["start_date"],  # type: ignore[arg-type]
            local_time=document["local_time"], weekdays=tuple(weekdays),  # type: ignore[arg-type]
        ))
    raise ScheduledWorkValidationError("The schedule document is invalid.")


def next_occurrence(
    schedule: ScheduleSpec, after: datetime, *, inclusive: bool
) -> Occurrence:
    selected = validate_schedule(schedule)
    now = _aware_utc(after)
    if selected.kind == "one_shot":
        assert selected.occurrence_utc is not None
        instant = parse_utc_timestamp(selected.occurrence_utc)
        if instant < now or (instant == now and not inclusive):
            raise ScheduledWorkValidationError(
                "A one-shot schedule must be in the future."
            )
        return Occurrence(
            f"one-shot:{selected.occurrence_utc}", selected.occurrence_utc, None
        )
    start = _date(selected.start_date)
    local = _local_time(selected.local_time)
    local_now = now.astimezone(ZoneInfo(selected.timezone_name))
    candidate = max(start, local_now.date())
    for _offset in range(3700):
        if _date_allowed(selected, candidate):
            occurrence = _civil_occurrence(selected, candidate, local)
            due = parse_utc_timestamp(occurrence.due_utc)
            if due > now or (inclusive and due == now):
                return occurrence
        candidate += timedelta(days=1)
    raise ScheduledWorkValidationError("The next scheduled occurrence is too distant.")


def next_occurrence_after(
    schedule: ScheduleSpec, local_date_value: str | None, due_utc: str
) -> Occurrence:
    selected = validate_schedule(schedule)
    if selected.kind == "one_shot":
        raise ScheduledWorkConflictError("A one-shot schedule has no later occurrence.")
    candidate = (
        _date(local_date_value) + timedelta(days=1)
        if local_date_value is not None
        else parse_utc_timestamp(due_utc).astimezone(
            ZoneInfo(selected.timezone_name)
        ).date() + timedelta(days=1)
    )
    local = _local_time(selected.local_time)
    for _offset in range(3700):
        if candidate >= _date(selected.start_date) and _date_allowed(selected, candidate):
            return _civil_occurrence(selected, candidate, local)
        candidate += timedelta(days=1)
    raise ScheduledWorkValidationError("The next scheduled occurrence is too distant.")


def _civil_occurrence(
    schedule: ScheduleSpec, local_date_value: date, local: civil_time
) -> Occurrence:
    context = TimeContext(datetime(2000, 1, 1, tzinfo=timezone.utc), schedule.timezone_name)
    key_base = (
        f"{schedule.kind}:{local_date_value.isoformat()}T{_format_local_time(local)}"
        f"[{schedule.timezone_name}]"
    )
    try:
        instant = context.resolve_civil(local_date_value, local, fold=0)
        return Occurrence(
            key_base, format_utc_timestamp(instant), local_date_value.isoformat()
        )
    except NonexistentCivilTimeError:
        # A nonexistent nominal time becomes due at the first real local minute
        # after the gap, solely so the scheduler can persist a truthful skip.
        candidate = datetime.combine(local_date_value, local)
        for minute in range(1, 181):
            shifted = candidate + timedelta(minutes=minute)
            try:
                instant = context.resolve_civil(shifted.date(), shifted.time(), fold=0)
                return Occurrence(
                    key_base + ":dst-gap", format_utc_timestamp(instant),
                    local_date_value.isoformat(), True,
                )
            except NonexistentCivilTimeError:
                continue
        raise ScheduledWorkValidationError("The recurring DST gap could not be resolved.")


def _latest_missed_occurrence(
    schedule: ScheduleSpec, first: Occurrence, now: datetime
) -> tuple[Occurrence, int, str]:
    selected = validate_schedule(schedule)
    if selected.kind == "one_shot":
        return first, 1, first.key
    first_date = _date(first.local_date)
    local_now = now.astimezone(ZoneInfo(selected.timezone_name))
    last_date = local_now.date()
    local = _local_time(selected.local_time)
    latest: Occurrence | None = None
    if selected.kind == "daily":
        candidate = last_date
        latest = _civil_occurrence(selected, candidate, local)
        if parse_utc_timestamp(latest.due_utc) > now:
            candidate -= timedelta(days=1)
            latest = _civil_occurrence(selected, candidate, local)
        count = (candidate - first_date).days + 1
    else:
        candidate = last_date
        for _offset in range(8):
            if candidate >= first_date and _date_allowed(selected, candidate):
                item = _civil_occurrence(selected, candidate, local)
                if parse_utc_timestamp(item.due_utc) <= now:
                    latest = item
                    break
            candidate -= timedelta(days=1)
        if latest is None:
            return first, 1, first.key
        count = _weekly_occurrence_count(first_date, candidate, selected.weekdays)
    if latest is None or count < 1:
        return first, 1, first.key
    return latest, count, first.key


def _weekly_occurrence_count(first: date, last: date, weekdays: tuple[int, ...]) -> int:
    if last < first:
        return 0
    days = (last - first).days + 1
    weeks, remainder = divmod(days, 7)
    count = weeks * len(weekdays)
    for offset in range(remainder):
        if (first + timedelta(days=weeks * 7 + offset)).weekday() in weekdays:
            count += 1
    return count


def _date_allowed(schedule: ScheduleSpec, value: date) -> bool:
    return schedule.kind == "daily" or value.weekday() in schedule.weekdays


def _occurrence_is_gap(key: str) -> bool:
    return key.endswith(":dst-gap")


def validate_job_id(value: object) -> str:
    if not isinstance(value, str) or _JOB_ID.fullmatch(value) is None:
        raise ScheduledWorkValidationError("Scheduled-work identifiers are invalid.")
    return value


def validate_authorization_id(value: object) -> str:
    if not isinstance(value, str) or _AUTH_ID.fullmatch(value) is None:
        raise ScheduledWorkValidationError("Scheduled authorization identifiers are invalid.")
    return value


def validate_run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ScheduledWorkValidationError("Scheduled-run identifiers are invalid.")
    return value


def validate_event_id(value: object) -> str:
    if not isinstance(value, str) or _EVENT_ID.fullmatch(value) is None:
        raise ScheduledWorkValidationError("Application-event identifiers are invalid.")
    return value


def validate_origin_chat_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _CHAT_ID.fullmatch(value) is None:
        raise ScheduledWorkValidationError(
            "Scheduled-work origin chat identifiers are invalid."
        )
    return value


def definition_document(item: ScheduledWorkDefinition) -> dict[str, object]:
    document = asdict(item)
    document["arguments"] = dict(item.arguments)
    document["schedule"] = item.schedule.document()
    document.pop("arguments_json")
    document.pop("schedule_json")
    document.pop("origin_chat_id")
    return document


def authorization_document(item: ScheduledAuthorization) -> dict[str, object]:
    return {
        "identifier": item.identifier,
        "job_id": item.job_id,
        "job_revision": item.job_revision,
        "capability_id": item.capability_id,
        "capability_contract_version": item.capability_contract_version,
        "arguments": dict(_json_mapping(item.arguments_json)),
        "schedule": schedule_from_json(item.schedule_json).document(),
        "scheduled_mode": item.scheduled_mode,
        "missed_policy": item.missed_policy,
        "granted_at_utc": item.granted_at_utc,
        "confirmation_provenance": item.confirmation_provenance,
        "status": item.status,
        "status_changed_at_utc": item.status_changed_at_utc,
    }


def run_document(item: ScheduledRun) -> dict[str, object]:
    document = asdict(item)
    document["result"] = None if item.result is None else dict(item.result)
    document.pop("result_json")
    return document


def _insert_definition(
    connection: sqlite3.Connection, item: ScheduledWorkDefinition
) -> None:
    connection.execute(
        "INSERT INTO scheduled_work_definitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.title, item.capability_id,
            item.capability_contract_version, item.arguments_json,
            item.schedule_json, item.schedule_kind, item.scheduled_mode,
            item.timezone_name, item.missed_policy, item.status,
            item.current_authorization_id, item.next_occurrence_key,
            item.next_occurrence_utc, item.next_local_date, item.created_at_utc,
            item.updated_at_utc, item.paused_at_utc, item.cancelled_at_utc,
            item.completed_at_utc, item.revision,
            item.origin_chat_id,
        ),
    )


def _insert_authorization(
    connection: sqlite3.Connection, item: ScheduledAuthorization
) -> None:
    connection.execute(
        "INSERT INTO scheduled_authorizations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.job_id, item.job_revision, item.capability_id,
            item.capability_contract_version, item.arguments_json,
            item.arguments_digest, item.schedule_json, item.schedule_digest,
            item.scheduled_mode, item.missed_policy, item.granted_at_utc,
            item.confirmation_provenance, item.status, item.status_changed_at_utc,
        ),
    )


def _insert_run(connection: sqlite3.Connection, item: ScheduledRun) -> None:
    connection.execute(
        "INSERT INTO scheduled_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.identifier, item.job_id, item.definition_revision,
            item.authorization_id, item.capability_id,
            item.capability_contract_version, item.occurrence_key,
            item.scheduled_occurrence_utc, item.claim_at_utc,
            item.started_at_utc, item.finished_at_utc, item.status,
            int(item.work_started), item.result_json, item.failure_code,
            item.failure_message, item.missed_occurrence_count,
            item.missed_first_key, item.missed_last_key, item.revision,
        ),
    )


def _definition(row: Sequence[object]) -> ScheduledWorkDefinition:
    try:
        item = ScheduledWorkDefinition(*row)
        validate_job_id(item.identifier)
        _safe_text(item.title, "Scheduled-work title", MAX_TITLE_LENGTH)
        _capability_id(item.capability_id)
        _revision(item.capability_contract_version)
        _json_mapping(item.arguments_json)
        schedule = schedule_from_json(item.schedule_json)
        if (
            item.schedule_kind != schedule.kind
            or item.scheduled_mode != schedule.mode
            or item.timezone_name != schedule.timezone_name
            or item.missed_policy not in MISSED_POLICIES
            or item.status not in DEFINITION_STATUSES
        ):
            raise ValueError
        validate_authorization_id(item.current_authorization_id)
        if item.next_occurrence_utc is not None:
            _timestamp(item.next_occurrence_utc)
        if item.next_local_date is not None:
            _date(item.next_local_date)
        for stamp in (item.created_at_utc, item.updated_at_utc):
            _timestamp(stamp)
        for stamp in (item.paused_at_utc, item.cancelled_at_utc, item.completed_at_utc):
            if stamp is not None:
                _timestamp(stamp)
        _revision(item.revision)
        validate_origin_chat_id(item.origin_chat_id)
        return item
    except (TypeError, ValueError, ScheduledWorkError) as exc:
        raise ScheduledWorkCorruptError(
            "Tori's scheduled-work database contains an invalid definition."
        ) from exc


def _authorization(row: Sequence[object]) -> ScheduledAuthorization:
    try:
        item = ScheduledAuthorization(*row)
        validate_authorization_id(item.identifier)
        validate_job_id(item.job_id)
        _revision(item.job_revision)
        _capability_id(item.capability_id)
        _revision(item.capability_contract_version)
        _json_mapping(item.arguments_json)
        schedule_from_json(item.schedule_json)
        if item.arguments_digest != _digest(item.arguments_json):
            raise ValueError
        if item.schedule_digest != _digest(item.schedule_json):
            raise ValueError
        if (
            item.scheduled_mode not in SCHEDULED_MODES
            or item.missed_policy not in MISSED_POLICIES
            or item.status not in AUTHORIZATION_STATUSES
        ):
            raise ValueError
        _timestamp(item.granted_at_utc)
        _safe_text(
            item.confirmation_provenance,
            "Confirmation provenance", MAX_CONFIRMATION_PROVENANCE_LENGTH,
        )
        _timestamp(item.status_changed_at_utc)
        return item
    except (TypeError, ValueError, ScheduledWorkError) as exc:
        raise ScheduledWorkCorruptError(
            "Tori's scheduled-work database contains an invalid authorization."
        ) from exc


def _run(row: Sequence[object]) -> ScheduledRun:
    try:
        values = list(row)
        values[12] = bool(values[12])
        item = ScheduledRun(*values)
        validate_run_id(item.identifier)
        validate_job_id(item.job_id)
        _revision(item.definition_revision)
        validate_authorization_id(item.authorization_id)
        _capability_id(item.capability_id)
        _revision(item.capability_contract_version)
        _safe_text(item.occurrence_key, "Occurrence identity", 500)
        _timestamp(item.scheduled_occurrence_utc)
        _timestamp(item.claim_at_utc)
        if item.started_at_utc is not None:
            _timestamp(item.started_at_utc)
        if item.finished_at_utc is not None:
            _timestamp(item.finished_at_utc)
        if item.status not in RUN_STATUSES:
            raise ValueError
        if item.result_json is not None:
            _json_mapping(item.result_json)
        if item.failure_code is not None:
            _failure_code(item.failure_code)
        if item.failure_message is not None:
            _safe_text(item.failure_message, "Failure message", MAX_FAILURE_LENGTH)
        if (
            isinstance(item.missed_occurrence_count, bool)
            or not isinstance(item.missed_occurrence_count, int)
            or item.missed_occurrence_count < 0
        ):
            raise ValueError
        _revision(item.revision)
        return item
    except (TypeError, ValueError, ScheduledWorkError) as exc:
        raise ScheduledWorkCorruptError(
            "Tori's scheduled-work database contains an invalid run."
        ) from exc


def _notification(row: Sequence[object]) -> ScheduledNotification:
    try:
        item = ScheduledNotification(*row)
        validate_run_id(item.run_id)
        validate_event_id(item.event_identifier)
        if item.state not in {"pending", "archived"}:
            raise ValueError
        _timestamp(item.queued_at_utc)
        if item.archived_at_utc is not None:
            _timestamp(item.archived_at_utc)
        if item.state == "pending" and (
            item.archived_at_utc is not None or item.chat_id is not None
        ):
            raise ValueError
        if item.state == "archived" and (
            item.archived_at_utc is None
            or not isinstance(item.chat_id, str)
            or re.fullmatch(r"chat-[0-9a-f]{32}", item.chat_id) is None
        ):
            raise ValueError
        validate_origin_chat_id(item.origin_chat_id)
        return item
    except (TypeError, ValueError, ScheduledWorkError) as exc:
        raise ScheduledWorkCorruptError(
            "Tori's scheduled-work database contains an invalid notification."
        ) from exc


def _canonical_json(value: object) -> str:
    _validate_json_value(value)
    try:
        rendered = json.dumps(
            _plain_json(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ScheduledWorkValidationError("Scheduled-work data is not valid JSON.") from exc
    if not 2 <= len(rendered) <= MAX_JSON_LENGTH:
        raise ScheduledWorkValidationError("Scheduled-work data is too large.")
    return rendered


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _json_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ScheduledWorkValidationError("Scheduled-work JSON is invalid.") from exc
    else:
        parsed = value
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ScheduledWorkValidationError("Scheduled-work data must be an object.")
    _validate_json_value(parsed)
    return parsed


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 8:
        raise ScheduledWorkValidationError("Scheduled-work data is too deeply nested.")
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and ("\x00" in value or len(value) > 8_000):
            raise ScheduledWorkValidationError("Scheduled-work text is invalid.")
        return
    if isinstance(value, float):
        raise ScheduledWorkValidationError("Scheduled-work numbers must be integers.")
    if isinstance(value, Mapping):
        if len(value) > 64 or any(
            not isinstance(key, str) or not key or len(key) > 128 for key in value
        ):
            raise ScheduledWorkValidationError("Scheduled-work object keys are invalid.")
        for item in value.values():
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ScheduledWorkValidationError("Scheduled-work lists are too large.")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    raise ScheduledWorkValidationError("Scheduled-work data contains an unsupported value.")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _validated_definition_arguments(
    definition: object, arguments: object, scheduled_mode: str, *,
    system_derived: bool = False,
) -> Mapping[str, object]:
    if not isinstance(definition, ActionDefinition):
        raise ScheduledWorkValidationError("A registered capability is required.")
    if (
        isinstance(definition.contract_version, bool)
        or not isinstance(definition.contract_version, int)
        or definition.contract_version < 1
    ):
        raise ScheduledWorkValidationError("The capability contract version is invalid.")
    eligible = (
        definition.scheduled_one_shot_eligible
        if scheduled_mode == "one_shot"
        else definition.scheduled_recurring_eligible
    )
    if (
        scheduled_mode == "one_shot"
        and system_derived
        and definition.system_derived_one_shot_eligible
    ):
        eligible = True
    if not eligible:
        raise ScheduledCapabilityError(
            "That capability is not eligible for the requested scheduled mode.",
            code="scheduling_not_allowed",
        )
    try:
        return definition.validate_arguments(arguments)
    except ActionContractError as exc:
        raise ScheduledCapabilityError(str(exc), code=exc.code) from exc


def _safe_text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str) or not value.strip() or value != value.strip()
        or len(value) > maximum or "\x00" in value
        or any(unicodedata.category(character) in {"Cs", "Zl", "Zp"} for character in value)
    ):
        raise ScheduledWorkValidationError(f"{label} must contain safe nonempty text.")
    return value


def _bounded_failure(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        return "The scheduled capability failed safely."
    return text[:MAX_FAILURE_LENGTH]


def _failure_code(value: object) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise ScheduledWorkValidationError("The failure code is invalid.")
    return value


def _capability_id(value: object) -> str:
    if (
        not isinstance(value, str) or not 1 <= len(value) <= 128
        or re.fullmatch(r"[a-z][a-z0-9_.-]*", value) is None
    ):
        raise ScheduledWorkValidationError("The capability identifier is invalid.")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ScheduledWorkValidationError(f"The {label} is invalid.")
    return value


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScheduledWorkValidationError("Expected revision must be a positive integer.")
    return value


def _statuses(values: Sequence[str] | None, allowed: frozenset[str]) -> tuple[str, ...]:
    if values is None:
        return tuple(sorted(allowed))
    if isinstance(values, (str, bytes)):
        raise ScheduledWorkValidationError("Statuses must be a sequence.")
    result = tuple(dict.fromkeys(values))
    if not result or any(value not in allowed for value in result):
        raise ScheduledWorkValidationError("A status filter is invalid.")
    return result


def _timestamp(value: object) -> str:
    try:
        parse_utc_timestamp(value)
    except ValueError as exc:
        raise ScheduledWorkValidationError("Scheduled-work timestamps must be UTC Z timestamps.") from exc
    assert isinstance(value, str)
    return value


def _date(value: object) -> date:
    if not isinstance(value, str):
        raise ScheduledWorkValidationError("The local schedule date is invalid.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ScheduledWorkValidationError("The local schedule date is invalid.") from exc
    if parsed.isoformat() != value:
        raise ScheduledWorkValidationError("The local schedule date is invalid.")
    return parsed


def _local_time(value: object) -> civil_time:
    if not isinstance(value, str) or re.fullmatch(r"\d{2}:\d{2}:\d{2}", value) is None:
        raise ScheduledWorkValidationError("The local schedule time is invalid.")
    try:
        parsed = civil_time.fromisoformat(value)
    except ValueError as exc:
        raise ScheduledWorkValidationError("The local schedule time is invalid.") from exc
    if parsed.tzinfo is not None or parsed.microsecond:
        raise ScheduledWorkValidationError("The local schedule time is invalid.")
    return parsed


def _format_local_time(value: civil_time) -> str:
    if not isinstance(value, civil_time) or value.tzinfo is not None or value.microsecond:
        raise ScheduledWorkValidationError("The local schedule time is invalid.")
    return value.strftime("%H:%M:%S")


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ScheduledWorkValidationError("Scheduled-work clocks must return aware datetimes.")
    return value.astimezone(timezone.utc)


def _identifier(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(16)}"


def _later_stamp(candidate: str, previous: str) -> str:
    first = parse_utc_timestamp(candidate)
    prior = parse_utc_timestamp(previous)
    if first > prior:
        return candidate
    return format_utc_timestamp(prior + timedelta(seconds=1))


def _database_error(error: sqlite3.Error) -> ScheduledWorkError:
    if isinstance(error, sqlite3.IntegrityError):
        return ScheduledWorkConflictError("The scheduled-work change conflicts with current state.")
    if isinstance(error, sqlite3.DatabaseError):
        return ScheduledWorkCorruptError(
            "Tori's scheduled-work database is corrupt or invalid; it was preserved."
        )
    return ScheduledWorkUnavailableError("Tori's scheduled-work database is unavailable.")


def _normalize_sql(value: str) -> str:
    return "".join(value.lower().split()).rstrip(";")


def _no_follow() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ScheduledWorkUnavailableError("Safe no-follow opens are unavailable.")
    return os.O_NOFOLLOW


def _directory() -> int:
    if not hasattr(os, "O_DIRECTORY"):
        raise ScheduledWorkUnavailableError("Safe directory opens are unavailable.")
    return os.O_DIRECTORY


def _stat_at(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_file(first: os.stat_result, second: os.stat_result | None) -> bool:
    return second is not None and (first.st_dev, first.st_ino) == (
        second.st_dev, second.st_ino
    )


def _rename_noreplace(parent: int, source: str, destination: str) -> None:
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
        parent, os.fsencode(source), parent, os.fsencode(destination), 1
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination)
