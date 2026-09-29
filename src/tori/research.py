"""Tori-owned durable state for authorized public-web research jobs."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from urllib.parse import urlsplit

from .time_context import format_utc_timestamp


RESEARCH_SCHEMA_VERSION = 3
RESEARCH_CAPABILITY = "tori.research.public_web"
TERMINAL_RESEARCH_STATES = frozenset({
    "completed", "completed_with_limits", "failed", "cancelled", "interrupted",
})
ACTIVE_RESEARCH_STATES = frozenset({"queued", "starting", "running", "cancelling"})
RESEARCH_STATES = frozenset({"awaiting_authorization", *ACTIVE_RESEARCH_STATES, *TERMINAL_RESEARCH_STATES})
VALIDATION_STATES = frozenset({"supported", "partially_supported", "unsupported", "conflicting"})
SOURCE_TYPES = frozenset({"primary", "secondary", "other"})
MAX_OBJECTIVE_LENGTH = 8_000
MAX_REPORT_LENGTH = 1_000_000
MAX_EVENT_PAYLOAD = 1_500_000
MAX_SOURCES = 512
MAX_EVENTS = 2_000
MAX_CLAIMS = 64
MAX_CLAIM_LENGTH = 1_000
MAX_EVIDENCE_PER_CLAIM = 12
MAX_EVIDENCE_RECORDS = 128
MAX_EXCERPT_LENGTH = 1_600
MAX_EVIDENCE_TEXT = 64_000
SUPPORT_STATES = {"supported": "SUPPORTED", "partially_supported": "PARTIALLY_SUPPORTED",
                  "conflicting": "CONFLICTED", "unsupported": "UNSUPPORTED"}

_JOB_ID = re.compile(r"^research-[0-9a-f]{32}$")
_AUTH_ID = re.compile(r"^research-auth-[0-9a-f]{32}$")
_ATTEMPT_ID = re.compile(r"^research-attempt-[0-9a-f]{32}$")


class ResearchError(RuntimeError):
    code = "research_error"


class ResearchValidationError(ResearchError):
    code = "invalid_research"


class ResearchNotFoundError(ResearchError):
    code = "not_found"


class ResearchConflictError(ResearchError):
    code = "conflict"


class ResearchStaleRevisionError(ResearchError):
    code = "stale_revision"


class ResearchUnavailableError(ResearchError):
    code = "research_unavailable"


@dataclass(frozen=True, slots=True)
class ResearchLimits:
    maximum_duration_seconds: int = 1800
    maximum_search_queries: int = 20
    maximum_results_considered: int = 100
    maximum_sources_fetched: int = 30
    maximum_bytes_per_page: int = 2_000_000
    maximum_total_fetched_bytes: int = 25_000_000
    maximum_concurrent_fetches: int = 4
    maximum_report_characters: int = 100_000

    def document(self) -> dict[str, int]:
        values = {
            "maximum_duration_seconds": self.maximum_duration_seconds,
            "maximum_search_queries": self.maximum_search_queries,
            "maximum_results_considered": self.maximum_results_considered,
            "maximum_sources_fetched": self.maximum_sources_fetched,
            "maximum_bytes_per_page": self.maximum_bytes_per_page,
            "maximum_total_fetched_bytes": self.maximum_total_fetched_bytes,
            "maximum_concurrent_fetches": self.maximum_concurrent_fetches,
            "maximum_report_characters": self.maximum_report_characters,
        }
        ceilings = {
            "maximum_duration_seconds": 7200,
            "maximum_search_queries": 100,
            "maximum_results_considered": 500,
            "maximum_sources_fetched": 100,
            "maximum_bytes_per_page": 10_000_000,
            "maximum_total_fetched_bytes": 100_000_000,
            "maximum_concurrent_fetches": 8,
            "maximum_report_characters": MAX_REPORT_LENGTH,
        }
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= ceilings[key]:
                raise ResearchValidationError(f"Research limit {key} is outside its safe range.")
        if self.maximum_bytes_per_page > self.maximum_total_fetched_bytes:
            raise ResearchValidationError("The per-page byte limit exceeds the total fetch limit.")
        return values

    def wire_document(self) -> dict[str, int]:
        """Map Tori-owned domain names to the explicit worker protocol."""

        values = self.document()
        return {
            "max_duration_seconds": values["maximum_duration_seconds"],
            "max_search_queries": values["maximum_search_queries"],
            "max_results_considered": values["maximum_results_considered"],
            "max_sources_fetched": values["maximum_sources_fetched"],
            "max_bytes_per_page": values["maximum_bytes_per_page"],
            "max_total_fetched_bytes": values["maximum_total_fetched_bytes"],
            "max_concurrent_fetches": values["maximum_concurrent_fetches"],
            "max_report_chars": values["maximum_report_characters"],
        }


@dataclass(frozen=True, slots=True)
class ResearchAuthority:
    """Exact authority granted to one job revision."""

    source_scope: str = "public_web_only"
    disclosure_scope: str = "public_objective_only"
    network_policy: str = "public_http_https_via_tori_broker"
    local_inference_only: bool = True
    schema_version: int = 1

    def document(self) -> dict[str, object]:
        if (
            self.schema_version != 1
            or self.source_scope != "public_web_only"
            or self.disclosure_scope != "public_objective_only"
            or self.network_policy != "public_http_https_via_tori_broker"
            or self.local_inference_only is not True
        ):
            raise ResearchValidationError("Research authority is not the supported V1 authority.")
        return {
            "schema_version": 1,
            "capability": RESEARCH_CAPABILITY,
            "source_scope": self.source_scope,
            "disclosure_scope": self.disclosure_scope,
            "network_policy": self.network_policy,
            "local_inference_only": True,
            "private_tori_data": "denied",
            "browser_credentials": "denied",
            "cloud_providers": "denied",
        }

    @property
    def canonical_json(self) -> str:
        return _json(self.document())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchJob:
    identifier: str
    objective: str
    origin_chat_id: str | None
    origin_chat_revision: int | None
    project_id: str | None
    state: str
    revision: int
    authorization_id: str | None
    attempt_id: str | None
    worker_type: str | None
    phase: str | None
    progress_message: str | None
    limits_json: str
    created_at_utc: str
    updated_at_utc: str
    started_at_utc: str | None
    terminal_at_utc: str | None
    report: str | None
    validation_json: str | None
    metrics_json: str | None
    failure_code: str | None
    failure_message: str | None

    @property
    def limits(self) -> Mapping[str, object]:
        return json.loads(self.limits_json)

    @property
    def validation(self) -> Mapping[str, object] | None:
        return None if self.validation_json is None else json.loads(self.validation_json)

    @property
    def metrics(self) -> Mapping[str, object] | None:
        return None if self.metrics_json is None else json.loads(self.metrics_json)


@dataclass(frozen=True, slots=True)
class ResearchProjectMetadata:
    """Bounded source-owned listing without report or worker payload."""

    identifier: str
    objective: str
    project_id: str
    state: str
    revision: int
    progress_message: str | None
    updated_at_utc: str
    terminal_at_utc: str | None


@dataclass(frozen=True, slots=True)
class ResearchSource:
    job_id: str
    sequence: int
    url: str
    title: str
    source_type: str
    authority_reason: str
    search_provider: str
    retrieved_at_utc: str | None
    content_hash: str | None
    used_in_report: bool


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    job_id: str
    sequence: int
    text: str
    support_state: str
    report_location: str
    finalization: str
    note: str | None


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    job_id: str
    sequence: int
    source_sequence: int
    excerpt: str
    source_locator: str
    extract_index: int
    excerpt_hash: str
    source: ResearchSource


@dataclass(frozen=True, slots=True)
class ResearchEvent:
    job_id: str
    sequence: int
    kind: str
    payload_json: str
    occurred_at_utc: str

    @property
    def payload(self) -> Mapping[str, object]:
        return json.loads(self.payload_json)


class SQLiteResearchStore:
    """Dedicated durable repository; the worker never receives its path."""

    def __init__(self, path: Path = Path("runtime/research/tori_research.db")) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._preexisting = self.path.exists() or self.path.is_symlink()
        if self._preexisting:
            entry = self.path.lstat()
            if (
                stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != os.geteuid()
                or stat.S_IMODE(entry.st_mode) & 0o077
            ):
                raise ResearchUnavailableError("The Research store path is unsafe.")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS research_metadata(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_jobs(
                    identifier TEXT PRIMARY KEY, objective TEXT NOT NULL,
                    origin_chat_id TEXT, origin_chat_revision INTEGER, project_id TEXT,
                    state TEXT NOT NULL, revision INTEGER NOT NULL,
                    authorization_id TEXT, attempt_id TEXT, worker_type TEXT,
                    phase TEXT, progress_message TEXT, limits_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
                    started_at_utc TEXT, terminal_at_utc TEXT, report TEXT,
                    validation_json TEXT, metrics_json TEXT,
                    failure_code TEXT, failure_message TEXT
                );
                CREATE TABLE IF NOT EXISTS research_authorizations(
                    identifier TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                    job_revision INTEGER NOT NULL, authority_json TEXT NOT NULL,
                    authority_digest TEXT NOT NULL, confirmation_provenance TEXT NOT NULL,
                    granted_at_utc TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES research_jobs(identifier)
                );
                CREATE TABLE IF NOT EXISTS research_events(
                    job_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL, occurred_at_utc TEXT NOT NULL,
                    PRIMARY KEY(job_id, sequence),
                    FOREIGN KEY(job_id) REFERENCES research_jobs(identifier)
                );
                CREATE TABLE IF NOT EXISTS research_sources(
                    job_id TEXT NOT NULL, sequence INTEGER NOT NULL, url TEXT NOT NULL,
                    title TEXT NOT NULL, source_type TEXT NOT NULL,
                    authority_reason TEXT NOT NULL, search_provider TEXT NOT NULL DEFAULT 'unknown', retrieved_at_utc TEXT,
                    content_hash TEXT, used_in_report INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id, sequence), UNIQUE(job_id, url),
                    FOREIGN KEY(job_id) REFERENCES research_jobs(identifier)
                );
                CREATE INDEX IF NOT EXISTS research_jobs_state ON research_jobs(state, updated_at_utc);
            """)
            # executescript commits implicitly. Start an explicit transaction
            # only after the pre-existing base schema has been opened, so the
            # entire version upgrade (including DDL) can roll back together.
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT value FROM research_metadata WHERE key='schema_version'"
            ).fetchone()
            if current is not None and current[0] == "1":
                # The only V2 addition is durable search-provider provenance.
                # Existing evidence remains readable but truthfully unknown.
                connection.execute(
                    "ALTER TABLE research_sources ADD COLUMN search_provider TEXT NOT NULL DEFAULT 'unknown'"
                )
            elif current is not None and current[0] not in {"2", str(RESEARCH_SCHEMA_VERSION)}:
                raise ResearchUnavailableError("The Research store schema is unsupported.")
            connection.execute("""CREATE TABLE IF NOT EXISTS research_claims(
                job_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL,
                support_state TEXT NOT NULL, report_location TEXT NOT NULL,
                finalization TEXT NOT NULL, note TEXT,
                PRIMARY KEY(job_id,sequence),
                FOREIGN KEY(job_id) REFERENCES research_jobs(identifier))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS research_evidence(
                job_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                source_sequence INTEGER NOT NULL, excerpt TEXT NOT NULL,
                source_locator TEXT NOT NULL, extract_index INTEGER NOT NULL,
                excerpt_hash TEXT NOT NULL,
                PRIMARY KEY(job_id,sequence),
                FOREIGN KEY(job_id,source_sequence) REFERENCES research_sources(job_id,sequence))""")
            connection.execute("""CREATE TABLE IF NOT EXISTS research_claim_evidence(
                job_id TEXT NOT NULL, claim_sequence INTEGER NOT NULL,
                evidence_sequence INTEGER NOT NULL,
                PRIMARY KEY(job_id,claim_sequence,evidence_sequence),
                FOREIGN KEY(job_id,claim_sequence) REFERENCES research_claims(job_id,sequence),
                FOREIGN KEY(job_id,evidence_sequence) REFERENCES research_evidence(job_id,sequence))""")
            if current is None:
                connection.execute("INSERT INTO research_metadata(key,value) VALUES('schema_version',?)",
                                   (str(RESEARCH_SCHEMA_VERSION),))
            elif current[0] != str(RESEARCH_SCHEMA_VERSION):
                connection.execute("UPDATE research_metadata SET value=? WHERE key='schema_version'",
                                   (str(RESEARCH_SCHEMA_VERSION),))
        if not self._preexisting:
            try:
                self.path.chmod(0o600)
            except OSError as exc:
                raise ResearchUnavailableError("The Research store permissions could not be secured.") from exc

    def create_proposal(
        self, objective: str, *, limits: ResearchLimits,
        origin_chat_id: str | None, origin_chat_revision: int | None,
        project_id: str | None = None,
    ) -> ResearchJob:
        objective = _text(objective, "objective", MAX_OBJECTIVE_LENGTH)
        if origin_chat_id is not None and not origin_chat_id.startswith("chat-"):
            raise ResearchValidationError("The Research conversation origin is invalid.")
        if (origin_chat_id is None) != (origin_chat_revision is None):
            raise ResearchValidationError("Research origin identity and revision must be paired.")
        identifier = "research-" + secrets.token_hex(16)
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO research_jobs(
                    identifier,objective,origin_chat_id,origin_chat_revision,project_id,
                    state,revision,limits_json,created_at_utc,updated_at_utc
                ) VALUES(?,?,?,?,?,'awaiting_authorization',1,?,?,?)""",
                (identifier, objective, origin_chat_id, origin_chat_revision, project_id,
                 _json(limits.document()), now, now),
            )
            self._event(connection, identifier, "proposed", {"disclosure_scope": "public_objective_only"}, now)
        return self.get(identifier)

    def authorize(
        self, job_id: str, *, expected_revision: int, authority: ResearchAuthority,
        confirmation_provenance: str,
    ) -> ResearchJob:
        auth_id = "research-auth-" + secrets.token_hex(16)
        now = _now()
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            self._expected(row, expected_revision, state="awaiting_authorization")
            provenance = _text(confirmation_provenance, "confirmation provenance", 256)
            connection.execute(
                """INSERT INTO research_authorizations
                (identifier,job_id,job_revision,authority_json,authority_digest,
                 confirmation_provenance,granted_at_utc) VALUES(?,?,?,?,?,?,?)""",
                (auth_id, job_id, expected_revision, authority.canonical_json,
                 authority.digest, provenance, now),
            )
            connection.execute(
                """UPDATE research_jobs SET state='queued', revision=revision+1,
                authorization_id=?, updated_at_utc=? WHERE identifier=?""",
                (auth_id, now, job_id),
            )
            self._event(connection, job_id, "authorized", {"authority_digest": authority.digest}, now)
        return self.get(job_id)

    def decline(self, job_id: str, *, expected_revision: int) -> ResearchJob:
        now = _now()
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            self._expected(row, expected_revision, state="awaiting_authorization")
            connection.execute(
                """UPDATE research_jobs SET state='cancelled',revision=revision+1,
                terminal_at_utc=?,updated_at_utc=?,progress_message=? WHERE identifier=?""",
                (now, now, "Research authorization was declined.", job_id),
            )
            self._event(connection, job_id, "authorization_declined", {}, now)
        return self.get(job_id)

    def mark_starting(self, job_id: str, *, expected_revision: int, worker_type: str) -> ResearchJob:
        now = _now()
        attempt = "research-attempt-" + secrets.token_hex(16)
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            self._expected(row, expected_revision, state="queued")
            connection.execute(
                """UPDATE research_jobs SET state='starting',revision=revision+1,
                attempt_id=?,worker_type=?,phase='planning',progress_message=?,
                started_at_utc=?,updated_at_utc=? WHERE identifier=?""",
                (attempt, _text(worker_type, "worker type", 128),
                 "Starting the supervised research worker.", now, now, job_id),
            )
            self._event(connection, job_id, "starting", {"attempt_id": attempt}, now)
        return self.get(job_id)

    def record_worker_event(
        self, job_id: str, kind: str, payload: Mapping[str, object], *,
        completion_origin: bool = False,
    ) -> ResearchJob:
        allowed = {
            "accepted", "progress", "source", "status", "completed",
            "completed_with_limits", "cancelled", "failed", "error",
        }
        if kind not in allowed:
            raise ResearchValidationError("The research worker event kind is unsupported.")
        now = _now()
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            state = row["state"]
            if state in TERMINAL_RESEARCH_STATES:
                return self._row(row)
            if state == "cancelling" and completion_origin:
                # The observer may have translated a malformed completion to
                # "failed". Preserve the durable cancellation intent before
                # parsing that untrusted payload or writing a terminal event.
                return self._row(row)
            if state == "cancelling" and kind in {"failed", "error"}:
                # Cancellation is already durable even if the adapter has not
                # yet observed its request or reports a protocol failure.
                return self._row(row)
            if state == "cancelling" and kind in {"completed", "completed_with_limits"}:
                raise ResearchConflictError("Cancelled Research cannot publish a completed report.")
            document = dict(payload)
            if len(_json(document)) > MAX_EVENT_PAYLOAD:
                raise ResearchValidationError("The research worker event is too large.")
            if kind == "source":
                self._source(connection, job_id, document, now)
            terminal = kind if kind in {"completed", "completed_with_limits", "cancelled", "failed"} else None
            canonical_report = None
            canonical_summary = None
            if terminal in {"completed", "completed_with_limits"}:
                canonical_report, canonical_summary = self._persist_ledger(connection, job_id, document)
            new_state = terminal or ("running" if state != "cancelling" and kind in {
                "accepted", "progress", "source", "status"
            } else state)
            phase = document.get("phase") if isinstance(document.get("phase"), str) else row["phase"]
            message = document.get("message") if isinstance(document.get("message"), str) else row["progress_message"]
            report = canonical_report if canonical_report is not None else (
                document.get("report") if isinstance(document.get("report"), str) else None
            )
            if report is not None and len(report) > MAX_REPORT_LENGTH:
                raise ResearchValidationError("The research report exceeds Tori's durable bound.")
            validation = canonical_summary if canonical_summary is not None else document.get("validation_summary")
            metrics = document.get("metrics")
            failure_code = document.get("code") if terminal == "failed" else None
            failure_message = document.get("message") if terminal == "failed" else None
            connection.execute(
                """UPDATE research_jobs SET state=?,revision=revision+1,phase=?,
                progress_message=?,updated_at_utc=?,terminal_at_utc=?,report=COALESCE(?,report),
                validation_json=COALESCE(?,validation_json),metrics_json=COALESCE(?,metrics_json),
                failure_code=?,failure_message=? WHERE identifier=?""",
                (new_state, phase, _bounded(message, 2000), now,
                 now if terminal else None, report,
                 _json(validation) if isinstance(validation, dict) else None,
                 _json(metrics) if isinstance(metrics, dict) else None,
                 _bounded(failure_code, 128), _bounded(failure_message, 2000), job_id),
            )
            event_document = document
            if terminal in {"completed", "completed_with_limits"}:
                # Keep the structured ledger as the only retained excerpt copy.
                event_document = dict(document)
                worker_narrative = event_document.pop("report", None)
                if isinstance(worker_narrative, str):
                    event_document["unverified_worker_narrative"] = worker_narrative
                event_document["canonical_report_sha256"] = hashlib.sha256(canonical_report.encode()).hexdigest()
                event_document["validation_summary"] = canonical_summary
                event_document["sources"] = [
                    {key: value for key, value in source.items() if key != "relevant_extracts"}
                    for source in document["sources"]
                ]
            self._event(connection, job_id, kind, event_document, now)
            if terminal in {"completed", "completed_with_limits"}:
                self._mark_used_sources(connection, job_id, document)
        return self.get(job_id)

    def request_cancel(self, job_id: str, *, expected_revision: int) -> ResearchJob:
        now = _now()
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            self._expected(row, expected_revision)
            if row["state"] not in ACTIVE_RESEARCH_STATES:
                raise ResearchConflictError("Only active Research can be cancelled.")
            connection.execute(
                "UPDATE research_jobs SET state='cancelling',revision=revision+1,updated_at_utc=? WHERE identifier=?",
                (now, job_id),
            )
            self._event(connection, job_id, "cancellation_requested", {}, now)
        return self.get(job_id)

    def mark_interrupted(
        self, job_id: str, *, reason: str, completion_origin: bool = False,
    ) -> ResearchJob:
        now = _now()
        with self._lock, self._connect() as connection:
            row = self._job_row(connection, job_id)
            if row["state"] in TERMINAL_RESEARCH_STATES:
                return self._row(row)
            if completion_origin and row["state"] == "cancelling":
                return self._row(row)
            connection.execute(
                """UPDATE research_jobs SET state='interrupted',revision=revision+1,
                terminal_at_utc=?,updated_at_utc=?,failure_code='interrupted',failure_message=?
                WHERE identifier=?""", (now, now, _bounded(reason, 2000), job_id),
            )
            self._event(connection, job_id, "interrupted", {"message": reason}, now)
        return self.get(job_id)

    def get(self, identifier: str) -> ResearchJob:
        if not _JOB_ID.fullmatch(identifier):
            raise ResearchNotFoundError("Research was not found.")
        with self._lock, self._connect() as connection:
            return self._row(self._job_row(connection, identifier))

    def list_jobs(self, *, limit: int = 50) -> tuple[ResearchJob, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ResearchValidationError("The Research listing limit is invalid.")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_jobs ORDER BY updated_at_utc DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def list_project_jobs(self, project_id: str, *, limit: int = 50) -> tuple[ResearchProjectMetadata, ...]:
        """Read bounded native Project membership for a metadata-only projection."""

        if not isinstance(project_id, str) or not re.fullmatch(r"project-[0-9a-f]{32}", project_id):
            raise ResearchValidationError("Project identifier is invalid.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ResearchValidationError("The Research listing limit is invalid.")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT identifier,objective,project_id,state,revision,"
                "progress_message,updated_at_utc,terminal_at_utc "
                "FROM research_jobs WHERE project_id=? "
                "ORDER BY updated_at_utc DESC,identifier LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return tuple(ResearchProjectMetadata(*row) for row in rows)

    def active_jobs(self) -> tuple[ResearchJob, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_jobs WHERE state IN ('queued','starting','running','cancelling') ORDER BY created_at_utc"
            ).fetchall()
        return tuple(self._row(row) for row in rows)

    def sources(self, job_id: str) -> tuple[ResearchSource, ...]:
        self.get(job_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
            "SELECT * FROM research_sources WHERE job_id=? ORDER BY sequence", (job_id,)
            ).fetchall()
        return tuple(ResearchSource(
            row["job_id"], row["sequence"], row["url"], row["title"], row["source_type"],
            row["authority_reason"], row["search_provider"], row["retrieved_at_utc"],
            row["content_hash"], bool(row["used_in_report"])
        ) for row in rows)

    def claims(self, job_id: str) -> tuple[ResearchClaim, ...]:
        self.get(job_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_claims WHERE job_id=? ORDER BY sequence", (job_id,)
            ).fetchall()
        return tuple(ResearchClaim(*row) for row in rows)

    def evidence_for_claim(self, job_id: str, claim_sequence: int) -> tuple[ResearchEvidence, ...]:
        if isinstance(claim_sequence, bool) or not isinstance(claim_sequence, int) or claim_sequence < 1:
            raise ResearchValidationError("The Research claim selector is invalid.")
        self.get(job_id)
        with self._lock, self._connect() as connection:
            claim = connection.execute(
                "SELECT 1 FROM research_claims WHERE job_id=? AND sequence=?", (job_id, claim_sequence)
            ).fetchone()
            if claim is None:
                raise ResearchNotFoundError("Research claim was not found.")
            rows = connection.execute("""SELECT e.*,s.url,s.title,s.source_type,s.authority_reason,
                s.search_provider,s.retrieved_at_utc,s.content_hash,s.used_in_report
                FROM research_claim_evidence l JOIN research_evidence e
                ON e.job_id=l.job_id AND e.sequence=l.evidence_sequence
                JOIN research_sources s ON s.job_id=e.job_id AND s.sequence=e.source_sequence
                WHERE l.job_id=? AND l.claim_sequence=? ORDER BY e.sequence""",
                (job_id, claim_sequence),
            ).fetchall()
        return tuple(ResearchEvidence(
            row["job_id"], row["sequence"], row["source_sequence"], row["excerpt"],
            row["source_locator"], row["extract_index"], row["excerpt_hash"],
            ResearchSource(row["job_id"], row["source_sequence"], row["url"], row["title"],
                           row["source_type"], row["authority_reason"], row["search_provider"],
                           row["retrieved_at_utc"], row["content_hash"], bool(row["used_in_report"])),
        ) for row in rows)

    def ledger_status(self, job_id: str) -> str:
        job = self.get(job_id)
        if job.state not in {"completed", "completed_with_limits"}:
            return "not_applicable"
        return "evidence_gated" if self.claims(job_id) else "legacy_report_only"

    def events(self, job_id: str, *, after_sequence: int = 0) -> tuple[ResearchEvent, ...]:
        self.get(job_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_events WHERE job_id=? AND sequence>? ORDER BY sequence",
                (job_id, after_sequence),
            ).fetchall()
        return tuple(ResearchEvent(*row) for row in rows)

    @contextmanager
    def maintenance_guard(self) -> Iterator[None]:
        with self._lock:
            yield

    def integrity_check(self) -> bool:
        with self._lock, self._connect() as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            return (
                bool(integrity_rows)
                and all(row[0] == "ok" for row in integrity_rows)
                and not foreign_key_rows
            )

    def _job_row(self, connection: sqlite3.Connection, identifier: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM research_jobs WHERE identifier=?", (identifier,)).fetchone()
        if row is None:
            raise ResearchNotFoundError("Research was not found.")
        return row

    @staticmethod
    def _expected(row: sqlite3.Row, revision: int, *, state: str | None = None) -> None:
        if row["revision"] != revision:
            raise ResearchStaleRevisionError("Research changed before this operation.")
        if state is not None and row["state"] != state:
            raise ResearchConflictError("Research is not in the required state.")

    @staticmethod
    def _row(row: sqlite3.Row) -> ResearchJob:
        job = ResearchJob(*(row[key] for key in row.keys()))
        try:
            if (
                not _JOB_ID.fullmatch(job.identifier)
                or job.state not in RESEARCH_STATES
                or isinstance(job.revision, bool) or not isinstance(job.revision, int)
                or job.revision < 1
                or not job.objective or len(job.objective) > MAX_OBJECTIVE_LENGTH
                or (job.authorization_id is not None and not _AUTH_ID.fullmatch(job.authorization_id))
                or (job.attempt_id is not None and not _ATTEMPT_ID.fullmatch(job.attempt_id))
                or (job.report is not None and len(job.report) > MAX_REPORT_LENGTH)
            ):
                raise ValueError
            limits = json.loads(job.limits_json)
            if not isinstance(limits, dict):
                raise ValueError
            ResearchLimits(**limits).document()
            for document in (job.validation_json, job.metrics_json):
                if document is not None and not isinstance(json.loads(document), dict):
                    raise ValueError
        except (TypeError, ValueError, json.JSONDecodeError, ResearchValidationError) as exc:
            raise ResearchUnavailableError("The Research store contains an invalid job record.") from exc
        return job

    @staticmethod
    def _event(connection: sqlite3.Connection, job_id: str, kind: str, payload: Mapping[str, object], now: str) -> None:
        count = connection.execute(
            "SELECT COUNT(*) FROM research_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        if count >= MAX_EVENTS:
            raise ResearchValidationError("The Research event limit was reached.")
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM research_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO research_events VALUES(?,?,?,?,?)",
            (job_id, sequence, kind, _json(dict(payload)), now),
        )

    def validate_terminal_ledger(self, job_id: str, payload: Mapping[str, object]) -> None:
        """Run the same fail-closed gate without committing terminal state."""
        with self._lock, self._connect() as connection:
            self._job_row(connection, job_id)
            self._ledger_rows(connection, job_id, payload)

    @staticmethod
    def _ledger_rows(connection: sqlite3.Connection, job_id: str, payload: Mapping[str, object]):
        report = payload.get("report")
        claims = payload.get("validation")
        source_documents = payload.get("sources")
        summary = payload.get("validation_summary")
        if (report is not None and (not isinstance(report, str) or len(report) > MAX_REPORT_LENGTH)):
            raise ResearchValidationError("The unverified worker narrative is invalid or excessive.")
        if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CLAIMS:
            raise ResearchValidationError("The Research report has no bounded claim ledger.")
        if not isinstance(source_documents, list) or not isinstance(summary, dict):
            raise ResearchValidationError("The Research evidence provenance is malformed.")
        observed = {
            row["url"]: row for row in connection.execute(
                "SELECT * FROM research_sources WHERE job_id=?", (job_id,)
            )
        }
        extracts: dict[str, list[str]] = {}
        if len(source_documents) > MAX_SOURCES:
            raise ResearchValidationError("The Research source list exceeds its bound.")
        for item in source_documents:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise ResearchValidationError("The Research evidence source is malformed.")
            url = item["url"]
            source = observed.get(url)
            if source is None or url in extracts:
                raise ResearchValidationError("Research evidence references an unobserved or duplicate source.")
            if item.get("used_in_report") is not True:
                extracts[url] = []
                continue
            if (source["content_hash"] and item.get("content_hash") and
                    source["content_hash"] != item["content_hash"]):
                raise ResearchValidationError("Research evidence source fingerprint changed.")
            values = item.get("relevant_extracts")
            if not isinstance(values, list):
                raise ResearchValidationError("A cited Research source has no retained extracts.")
            extracts[url] = values
        claim_rows = []
        evidence_rows = []
        link_rows = []
        evidence_ids: dict[tuple[str, int], int] = {}
        total_text = 0
        counts = {state: 0 for state in SUPPORT_STATES}
        for number, item in enumerate(claims, 1):
            if not isinstance(item, dict):
                raise ResearchValidationError("A Research claim is malformed.")
            claim = _text(item.get("claim"), "claim", MAX_CLAIM_LENGTH)
            if len(claim.splitlines()) != 1:
                raise ResearchValidationError("A Research claim must occupy one report line.")
            status = item.get("status")
            if not isinstance(status, str) or status not in SUPPORT_STATES:
                raise ResearchValidationError("A Research claim support state is invalid.")
            counts[status] += 1
            location = item.get("report_location")
            match = re.fullmatch(r"line ([1-9][0-9]*)", location) if isinstance(location, str) else None
            if match is None:
                raise ResearchValidationError("A Research claim location is invalid.")
            # This is a locator in unverified worker prose, not a source of
            # validated findings. The canonical report comes from the ledger.
            finalization = item.get("finalization")
            if not isinstance(finalization, str) or finalization not in {"kept", "qualified"}:
                raise ResearchValidationError("A Research claim finalization is invalid.")
            if status == "supported" and finalization != "kept":
                raise ResearchValidationError("A supported Research claim has inconsistent finalization.")
            if status == "unsupported" and finalization != "qualified":
                raise ResearchValidationError("An unsupported Research claim was presented as fact.")
            if status in {"partially_supported", "conflicting"} and finalization != "qualified":
                raise ResearchValidationError("A limited Research claim was presented without qualification.")
            note = item.get("notes")
            if note is not None:
                note = _text(note, "claim note", 1_000)
            urls = item.get("source_urls")
            if (not isinstance(urls, list) or len(urls) > MAX_EVIDENCE_PER_CLAIM
                    or any(not isinstance(url, str) for url in urls)
                    or len(urls) != len(set(urls))):
                raise ResearchValidationError("Research claim source references are malformed or excessive.")
            linked_sources = set()
            claim_links = []
            for url in urls:
                if not isinstance(url, str) or url not in extracts or url not in observed:
                    raise ResearchValidationError("Research claim references a foreign or unobserved source.")
                for index, excerpt in enumerate(extracts[url], 1):
                    excerpt = _text(excerpt, "evidence excerpt", MAX_EXCERPT_LENGTH)
                    if any(ord(char) < 32 and char not in "\n\t" for char in excerpt):
                        raise ResearchValidationError("Research evidence contains unsafe controls.")
                    key = (url, index)
                    if key not in evidence_ids:
                        if len(evidence_rows) >= MAX_EVIDENCE_RECORDS:
                            raise ResearchValidationError("Research evidence record limit was reached.")
                        total_text += len(excerpt)
                        if total_text > MAX_EVIDENCE_TEXT:
                            raise ResearchValidationError("Research evidence text limit was reached.")
                        evidence_id = len(evidence_rows) + 1
                        evidence_ids[key] = evidence_id
                        evidence_rows.append((job_id, evidence_id, observed[url]["sequence"],
                                              excerpt, url, index, hashlib.sha256(excerpt.encode()).hexdigest()))
                    claim_links.append((job_id, number, evidence_ids[key]))
                    linked_sources.add(url)
            if len(claim_links) > MAX_EVIDENCE_PER_CLAIM:
                raise ResearchValidationError("Research claim evidence limit was reached.")
            if status in {"supported", "partially_supported", "conflicting"} and not claim_links:
                raise ResearchValidationError("A Research claim has no retained supporting evidence.")
            if status == "conflicting" and len(linked_sources) < 2:
                raise ResearchValidationError("A conflicting Research claim needs two retained sources.")
            claim_rows.append((job_id, number, claim, SUPPORT_STATES[status], location, finalization, note))
            link_rows.extend(claim_links)
        for state, count in counts.items():
            value = summary.get(state, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value != count:
                raise ResearchValidationError("Research claim counts disagree with the validation summary.")
        if not evidence_rows or not any(counts[state] for state in (
            "supported", "partially_supported", "conflicting"
        )):
            raise ResearchValidationError("The Research report has no retained usable evidence.")
        return claim_rows, evidence_rows, link_rows

    @classmethod
    def _persist_ledger(cls, connection: sqlite3.Connection, job_id: str, payload: Mapping[str, object]) -> tuple[str, dict[str, object]]:
        claims, evidence, links = cls._ledger_rows(connection, job_id, payload)
        connection.executemany("INSERT INTO research_claims VALUES(?,?,?,?,?,?,?)", claims)
        connection.executemany("INSERT INTO research_evidence VALUES(?,?,?,?,?,?,?)", evidence)
        connection.executemany("INSERT INTO research_claim_evidence VALUES(?,?,?)", links)
        source_by_evidence = {row[1]: row[2] for row in evidence}
        sources_by_claim: dict[int, set[int]] = {}
        for _, claim_sequence, evidence_sequence in links:
            sources_by_claim.setdefault(claim_sequence, set()).add(source_by_evidence[evidence_sequence])
        labels = {
            "SUPPORTED": "SUPPORTED — worker-classified; source-linked evidence retained",
            "PARTIALLY_SUPPORTED": "PARTIALLY SUPPORTED — evidence is limited",
            "CONFLICTED": "CONFLICTED — worker-classified disagreement between retained sources",
            "UNSUPPORTED": "UNSUPPORTED — unverified; not an established finding",
        }
        lines = [
            "Research findings — retained source-linked provenance",
            "Support states are worker classifications; Tori has not independently verified semantic entailment or remote content.",
        ]
        for _, sequence, claim, state, _, _, _ in claims:
            lines.extend(("", f"{sequence}. [{labels[state]}] {claim}"))
            source_ids = sorted(sources_by_claim.get(sequence, ()))
            lines.append("   Retained source IDs: " + (
                ", ".join(str(identifier) for identifier in source_ids)
                if source_ids else "none; no established supporting evidence"
            ))
        report = "\n".join(lines)
        if len(report) > MAX_REPORT_LENGTH:
            raise ResearchValidationError("The canonical Research report exceeds its durable bound.")
        summary: dict[str, object] = {
            state: sum(row[3] == label for row in claims)
            for state, label in SUPPORT_STATES.items()
        }
        summary["unsupported_presented_as_fact"] = 0
        summary["provenance"] = "source_linked_worker_classification"
        return report, summary

    @staticmethod
    def _source(connection: sqlite3.Connection, job_id: str, payload: Mapping[str, object], now: str) -> None:
        url = payload.get("url")
        title = payload.get("title")
        source_type = payload.get("source_type", "other")
        reason = payload.get("authority_reason", "No authority classification supplied.")
        search_provider = payload.get("search_provider", "unknown")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ResearchValidationError("A worker source URL is invalid.")
        parsed = urlsplit(url)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise ResearchValidationError("A worker source URL has an invalid port.") from exc
        if (
            parsed.scheme not in {"http", "https"} or parsed.hostname is None
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment or parsed_port not in {None, 80, 443}
        ):
            raise ResearchValidationError("A worker source URL is outside the public-web contract.")
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ResearchValidationError("A worker source URL names a non-public address.")
        if not isinstance(title, str) or not title or len(title) > 1000:
            raise ResearchValidationError("A worker source title is invalid.")
        if source_type not in SOURCE_TYPES:
            raise ResearchValidationError("A worker source classification is invalid.")
        if not isinstance(reason, str) or not reason or len(reason) > 1000:
            raise ResearchValidationError("A worker authority reason is invalid.")
        if not isinstance(search_provider, str) or search_provider not in {
            "github", "huggingface", "searxng", "unknown",
        }:
            raise ResearchValidationError("A worker source search provider is invalid.")
        count = connection.execute("SELECT COUNT(*) FROM research_sources WHERE job_id=?", (job_id,)).fetchone()[0]
        if count >= MAX_SOURCES:
            raise ResearchValidationError("The Research source limit was reached.")
        sequence = count + 1
        connection.execute(
            """INSERT INTO research_sources
            (job_id,sequence,url,title,source_type,authority_reason,search_provider,retrieved_at_utc,content_hash,used_in_report)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id,url) DO UPDATE SET
                title=excluded.title,
                retrieved_at_utc=excluded.retrieved_at_utc,
                content_hash=COALESCE(excluded.content_hash,research_sources.content_hash),
                search_provider=CASE WHEN research_sources.search_provider='unknown' THEN excluded.search_provider ELSE research_sources.search_provider END,
                used_in_report=MAX(research_sources.used_in_report,excluded.used_in_report)""",
            (job_id, sequence, url, title, source_type, reason, search_provider,
             payload.get("retrieved_at") if isinstance(payload.get("retrieved_at"), str) else now,
             payload.get("content_hash") if isinstance(payload.get("content_hash"), str) else None,
             1 if payload.get("used_in_report") is True else 0),
        )

    @staticmethod
    def _mark_used_sources(connection: sqlite3.Connection, job_id: str, payload: Mapping[str, object]) -> None:
        used = payload.get("sources")
        if not isinstance(used, list):
            return
        urls = [item.get("url") for item in used if isinstance(item, dict) and item.get("used_in_report") is True]
        for url in urls:
            if isinstance(url, str):
                connection.execute(
                    "UPDATE research_sources SET used_in_report=1 WHERE job_id=? AND url=?",
                    (job_id, url),
                )


def _now() -> str:
    return format_utc_timestamp(datetime.now(timezone.utc))


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum or "\x00" in value:
        raise ResearchValidationError(f"The Research {label} is invalid.")
    return value.strip()


def _bounded(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:maximum]


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ResearchValidationError("Research data is not JSON-safe.") from exc
