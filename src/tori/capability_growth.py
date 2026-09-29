"""Bounded application-owned capability growth and advisory Skills review.

The Improvement Journal is operational evidence about Tori, not curated user
Memory.  It stores only normalized application outcomes and immutable component
identity.  Models, conversations, catalog prose, and downloaded code are never
canonical evidence and cannot grant authority through this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from typing import Protocol
from urllib.parse import quote, urlsplit

from .capabilities import CapabilityResult
from .capability_registry import CAPABILITIES, CapabilityRegistry
from .github_skills import GitHubSkillError, GitHubSkillLifecycleService
from .mcp import MCPError, MCPServerRegistry
from .request_origin import ConversationOperation, OriginAuthority, RequestOrigin
from .skills import SkillApplicationService, SkillError
from .skills_sh import (
    SkillsShCandidate,
    SkillsShDiscoveryError,
    SkillsShDiscoveryService,
)


IMPROVEMENT_JOURNAL_SCHEMA_VERSION = 2
PREVIOUS_IMPROVEMENT_JOURNAL_SCHEMA_VERSION = 1
DEFAULT_IMPROVEMENT_JOURNAL = Path(
    "runtime/capability_growth/improvement_journal.sqlite3"
)
MAX_TEXT = 1_000
MAX_FINDINGS = 200
MAX_RECOMMENDATIONS = 100
MAX_REVIEWS = 30
MAX_REVIEW_SEARCHES = 3
MAX_REVIEW_CANDIDATES_PER_SEARCH = 3
MAX_REVIEW_INSPECTIONS = 2
RECOMMENDATION_COOLDOWN_DAYS = 30
MAX_EXTERNAL_PROMOTIONS_PER_RUN = 3

EVIDENCE_KINDS = frozenset(
    {"success", "friction", "failure", "regression", "workaround", "opportunity"}
)
FINDING_STATUSES = frozenset(
    {"open", "monitoring", "resolved", "obsolete", "historical"}
)
RECOMMENDATION_STATUSES = frozenset(
    {"open", "dismissed", "accepted", "resolved", "obsolete"}
)
LANES = frozenset({"fix", "improve", "expand"})
SEVERITIES = frozenset({"low", "medium", "high", "critical"})
CLASSIFICATIONS = frozenset(
    {
        "ready_existing_authority",
        "needs_skill_lifecycle_or_permission",
        "needs_application_adapter",
        "needs_mcp_or_external_integration",
        "requires_unsupported_executable",
        "duplicate_little_benefit",
        "not_recommended",
    }
)
AUTHORITY_CHANGES = frozenset(
    {
        "none",
        "user_decision",
        "skill_install",
        "skill_enable",
        "permission_change",
        "application_adapter",
        "mcp_integration",
        "external_integration",
        "unsupported_executable",
    }
)
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_DIGEST = re.compile(r"(?:sha256:)?[0-9a-f]{64}\Z")
_UTC_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z"
)

_JOURNAL_SCHEMA_SQL = {
    ("table", "journal_metadata"):
        "CREATE TABLE journal_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    ("table", "findings"):
        "CREATE TABLE findings (id TEXT PRIMARY KEY,identity_key TEXT NOT NULL,"
        "lane TEXT NOT NULL CHECK(lane IN ('fix','improve','expand')),"
        "capability_area TEXT NOT NULL,capability_id TEXT NOT NULL,operation_id TEXT NOT NULL,"
        "evidence_kind TEXT NOT NULL CHECK(evidence_kind IN "
        "('success','friction','failure','regression','workaround','opportunity')),"
        "error_code TEXT,severity TEXT NOT NULL CHECK(severity IN ('low','medium','high','critical')),"
        "component_id TEXT NOT NULL,component_version TEXT NOT NULL,component_digest TEXT,"
        "count INTEGER NOT NULL CHECK(count>=1),priority INTEGER NOT NULL CHECK(priority>=0),"
        "status TEXT NOT NULL CHECK(status IN ('open','monitoring','resolved','obsolete','historical')),"
        "revision INTEGER NOT NULL CHECK(revision>=1),first_seen TEXT NOT NULL,last_seen TEXT NOT NULL)",
    ("table", "recommendations"):
        "CREATE TABLE recommendations (id TEXT PRIMARY KEY,lane TEXT NOT NULL CHECK(lane IN "
        "('fix','improve','expand')),capability_area TEXT NOT NULL,title TEXT NOT NULL,"
        "rationale TEXT NOT NULL,evidence TEXT NOT NULL,candidate_json TEXT NOT NULL,"
        "classification TEXT NOT NULL,required_authority_json TEXT NOT NULL,"
        "material_fingerprint TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN "
        "('open','dismissed','accepted','resolved','obsolete')),revision INTEGER NOT NULL CHECK(revision>=1),"
        "first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,cooldown_until TEXT)",
    ("table", "skills_reviews"):
        "CREATE TABLE skills_reviews (id TEXT PRIMARY KEY,scope TEXT NOT NULL CHECK(scope IN "
        "('general','user_directed')),capability_area TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN "
        "('running','completed','partial','failed')),searches INTEGER NOT NULL,candidates INTEGER NOT NULL,"
        "inspections INTEGER NOT NULL,recommendation_count INTEGER NOT NULL,error_codes_json TEXT NOT NULL,"
        "started_at TEXT NOT NULL,completed_at TEXT)",
    ("index", "findings_priority"):
        "CREATE INDEX findings_priority ON findings(status,priority DESC,last_seen DESC)",
    ("index", "recommendations_status"):
        "CREATE INDEX recommendations_status ON recommendations(status,last_seen DESC)",
    ("index", "reviews_started"):
        "CREATE INDEX reviews_started ON skills_reviews(started_at DESC)",
}


class CapabilityGrowthError(RuntimeError):
    """A bounded capability-growth failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CapabilityGrowthValidationError(CapabilityGrowthError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="capability_growth_invalid")


class ImprovementJournalUnavailableError(CapabilityGrowthError):
    def __init__(self, message: str = "Tori's Improvement Journal is unavailable.") -> None:
        super().__init__(message, code="improvement_journal_unavailable")


class ImprovementJournalCorruptError(CapabilityGrowthError):
    def __init__(self, message: str = "Tori's Improvement Journal is invalid; it was not repaired.") -> None:
        super().__init__(message, code="improvement_journal_corrupt")


class ImprovementJournalConflictError(CapabilityGrowthError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="improvement_journal_conflict")


@dataclass(frozen=True, slots=True)
class CapabilityEvidence:
    """One deterministic verified outcome; intentionally no free-form payload."""

    capability_area: str
    capability_id: str
    operation_id: str
    outcome: str
    severity: str = "medium"
    error_code: str | None = None
    component_id: str = "tori.core"
    component_version: str = "unknown"
    component_digest: str | None = None
    observed_at: str | None = None
    verified: bool = True

    def __post_init__(self) -> None:
        _slug(self.capability_area, "capability area")
        _identifier(self.capability_id, "capability identifier")
        _identifier(self.operation_id, "operation identifier")
        _identifier(self.component_id, "component identifier")
        _bounded_text(self.component_version, "component version", 128)
        if self.outcome not in EVIDENCE_KINDS - {"regression"}:
            raise CapabilityGrowthValidationError("Evidence outcome is invalid.")
        if self.severity not in SEVERITIES:
            raise CapabilityGrowthValidationError("Evidence severity is invalid.")
        if self.error_code is not None:
            _slug(self.error_code, "error code")
        if self.component_digest is not None and _DIGEST.fullmatch(self.component_digest) is None:
            raise CapabilityGrowthValidationError("Component digest is invalid.")
        if self.observed_at is not None:
            _timestamp(self.observed_at)
        if self.verified is not True:
            raise CapabilityGrowthValidationError(
                "Only application-verified outcomes may enter the Improvement Journal."
            )
        if self.outcome in {"success", "opportunity"} and self.error_code is not None:
            raise CapabilityGrowthValidationError(
                "Successful or opportunity evidence cannot carry an error code."
            )


@dataclass(frozen=True, slots=True)
class ImprovementFinding:
    identifier: str
    identity_key: str
    lane: str
    capability_area: str
    capability_id: str
    operation_id: str
    evidence_kind: str
    error_code: str | None
    severity: str
    component_id: str
    component_version: str
    component_digest: str | None
    count: int
    priority: int
    status: str
    revision: int
    first_seen: str
    last_seen: str

    def __post_init__(self) -> None:
        _hex_identifier(self.identifier, "finding identifier")
        _hex_identifier(self.identity_key, "finding identity")
        if self.lane not in LANES or self.evidence_kind not in EVIDENCE_KINDS:
            raise CapabilityGrowthValidationError("Stored finding classification is invalid.")
        _slug(self.capability_area, "capability area")
        _identifier(self.capability_id, "capability identifier")
        _identifier(self.operation_id, "operation identifier")
        _identifier(self.component_id, "component identifier")
        _bounded_text(self.component_version, "component version", 128)
        if self.error_code is not None:
            _slug(self.error_code, "error code")
        if self.severity not in SEVERITIES or self.status not in FINDING_STATUSES:
            raise CapabilityGrowthValidationError("Stored finding lifecycle is invalid.")
        if self.component_digest is not None and _DIGEST.fullmatch(self.component_digest) is None:
            raise CapabilityGrowthValidationError("Stored component digest is invalid.")
        if type(self.count) is not int or self.count < 1 or type(self.priority) is not int or self.priority < 0:
            raise CapabilityGrowthValidationError("Stored finding counts are invalid.")
        _revision(self.revision)
        _timestamp(self.first_seen)
        _timestamp(self.last_seen)

    def document(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "lane": self.lane.upper(),
            "capability_area": self.capability_area,
            "capability_id": self.capability_id,
            "operation_id": self.operation_id,
            "evidence_kind": self.evidence_kind,
            "error_code": self.error_code,
            "severity": self.severity,
            "component": {
                "identifier": self.component_id,
                "version": self.component_version,
                "digest": self.component_digest,
            },
            "count": self.count,
            "priority": self.priority,
            "status": self.status,
            "revision": self.revision,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass(frozen=True, slots=True)
class CandidateProvenance:
    catalog_id: str
    skill_id: str
    name: str
    repository: str
    commit: str | None
    package_path: str
    version: str | None
    digest: str | None
    compatibility: str
    inspected: bool

    def __post_init__(self) -> None:
        for label, value, maximum in (
            ("catalog identity", self.catalog_id, 300),
            ("Skill identity", self.skill_id, 400),
            ("candidate name", self.name, 200),
            ("repository", self.repository, 500),
            ("package path", self.package_path, 500),
            ("compatibility", self.compatibility, 100),
        ):
            _bounded_text(value, label, maximum)
        if self.commit is not None and re.fullmatch(r"[0-9a-f]{40}", self.commit) is None:
            raise CapabilityGrowthValidationError("Candidate commit is invalid.")
        if self.version is not None:
            _bounded_text(self.version, "candidate version", 128)
        if self.digest is not None and _DIGEST.fullmatch(self.digest) is None:
            raise CapabilityGrowthValidationError("Candidate digest is invalid.")
        if type(self.inspected) is not bool or self.inspected != (self.commit is not None):
            raise CapabilityGrowthValidationError("Candidate inspection provenance is inconsistent.")

    def document(self) -> dict[str, object]:
        return {
            "kind": "skill_candidate",
            "catalog_id": self.catalog_id,
            "skill_id": self.skill_id,
            "name": self.name,
            "repository": self.repository,
            "commit": self.commit,
            "package_path": self.package_path,
            "version": self.version,
            "digest": self.digest,
            "compatibility": self.compatibility,
            "inspected": self.inspected,
        }

    @classmethod
    def from_document(cls, value: object) -> CandidateProvenance:
        item = _exact_mapping(
            value,
            {
                "kind", "catalog_id", "skill_id", "name", "repository", "commit",
                "package_path", "version", "digest", "compatibility", "inspected",
            },
            "candidate provenance",
        )
        if item.pop("kind") != "skill_candidate":
            raise CapabilityGrowthValidationError("Candidate provenance kind is invalid.")
        return cls(**item)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ExternalSourceProvenance:
    kind: str
    url: str
    stable_identity: str
    immutable_identity: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"github_page", "github_api", "skills_sh"}:
            raise CapabilityGrowthValidationError("External source kind is invalid.")
        _bounded_text(self.url, "source URL", 2_048)
        _bounded_text(self.stable_identity, "source identity", 500)
        if self.immutable_identity is not None:
            _bounded_text(self.immutable_identity, "immutable source identity", 500)
        try:
            parsed = urlsplit(self.url)
        except ValueError as exc:
            raise CapabilityGrowthValidationError("External source URL is invalid.") from exc
        allowed_host = {
            "github_page": "github.com",
            "github_api": "api.github.com",
            "skills_sh": "skills.sh",
        }[self.kind]
        if (
            parsed.scheme != "https" or parsed.hostname != allowed_host
            or parsed.port not in {None, 443} or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
        ):
            raise CapabilityGrowthValidationError("External source URL is invalid.")

    def document(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "url": self.url,
            "stable_identity": self.stable_identity,
            "immutable_identity": self.immutable_identity,
        }

    @classmethod
    def from_document(cls, value: object) -> ExternalSourceProvenance:
        item = _exact_mapping(
            value,
            {"kind", "url", "stable_identity", "immutable_identity"},
            "external source provenance",
        )
        return cls(**item)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ExternalResearchProvenance:
    finding_id: str
    finding_version_id: str
    source_identity: str
    run_id: str
    sources: tuple[ExternalSourceProvenance, ...]
    promotion_reason: str
    model_assisted: bool
    friction_finding_id: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"finding-[0-9a-f]{32}", self.finding_id) is None:
            raise CapabilityGrowthValidationError("Night Owl finding identity is invalid.")
        if re.fullmatch(r"version-[0-9a-f]{32}", self.finding_version_id) is None:
            raise CapabilityGrowthValidationError("Night Owl version identity is invalid.")
        if re.fullmatch(r"run-[0-9a-f]{32}", self.run_id) is None:
            raise CapabilityGrowthValidationError("Night Owl run identity is invalid.")
        _bounded_text(self.source_identity, "external source identity", 500)
        _bounded_text(self.promotion_reason, "promotion reason", 500)
        if not self.sources or len(self.sources) > 3 or any(
            not isinstance(item, ExternalSourceProvenance) for item in self.sources
        ):
            raise CapabilityGrowthValidationError("External source attribution is invalid.")
        if type(self.model_assisted) is not bool:
            raise CapabilityGrowthValidationError("Model-assistance provenance is invalid.")
        if self.friction_finding_id is not None:
            _hex_identifier(self.friction_finding_id, "friction finding identifier")

    def document(self) -> dict[str, object]:
        return {
            "kind": "external_research",
            "finding_id": self.finding_id,
            "finding_version_id": self.finding_version_id,
            "source_identity": self.source_identity,
            "run_id": self.run_id,
            "sources": [item.document() for item in self.sources],
            "promotion_reason": self.promotion_reason,
            "model_assisted": self.model_assisted,
            "friction_finding_id": self.friction_finding_id,
        }

    @classmethod
    def from_document(cls, value: object) -> ExternalResearchProvenance:
        item = _exact_mapping(
            value,
            {
                "kind", "finding_id", "finding_version_id", "source_identity",
                "run_id", "sources", "promotion_reason", "model_assisted",
                "friction_finding_id",
            },
            "external research provenance",
        )
        if item.pop("kind") != "external_research" or not isinstance(item["sources"], list):
            raise CapabilityGrowthValidationError("External research provenance is invalid.")
        item["sources"] = tuple(
            ExternalSourceProvenance.from_document(source)
            for source in item["sources"]
        )
        return cls(**item)  # type: ignore[arg-type]


RecommendationProvenance = CandidateProvenance | ExternalResearchProvenance


@dataclass(frozen=True, slots=True)
class ImprovementRecommendation:
    identifier: str
    lane: str
    capability_area: str
    title: str
    rationale: str
    evidence: str
    candidate: RecommendationProvenance | None
    classification: str
    required_authority: tuple[str, ...]
    status: str
    revision: int
    first_seen: str
    last_seen: str
    cooldown_until: str | None

    def __post_init__(self) -> None:
        _hex_identifier(self.identifier, "recommendation identifier")
        if self.lane not in LANES:
            raise CapabilityGrowthValidationError("Stored recommendation lane is invalid.")
        _slug(self.capability_area, "capability area")
        _bounded_text(self.title, "recommendation title", 200)
        _bounded_text(self.rationale, "recommendation rationale", MAX_TEXT)
        _bounded_text(self.evidence, "recommendation evidence", MAX_TEXT)
        if self.candidate is not None and not isinstance(
            self.candidate, (CandidateProvenance, ExternalResearchProvenance)
        ):
            raise CapabilityGrowthValidationError("Stored candidate provenance is invalid.")
        if self.classification not in CLASSIFICATIONS or self.status not in RECOMMENDATION_STATUSES:
            raise CapabilityGrowthValidationError("Stored recommendation classification is invalid.")
        if not self.required_authority or any(item not in AUTHORITY_CHANGES for item in self.required_authority):
            raise CapabilityGrowthValidationError("Stored recommendation authority is invalid.")
        _revision(self.revision)
        _timestamp(self.first_seen)
        _timestamp(self.last_seen)
        if self.cooldown_until is not None:
            _timestamp(self.cooldown_until)

    def document(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "lane": self.lane.upper(),
            "capability_area": self.capability_area,
            "title": self.title,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "candidate": None if self.candidate is None else self.candidate.document(),
            "classification": self.classification,
            "classification_label": _classification_label(self.classification),
            "required_authority": list(self.required_authority),
            "status": self.status,
            "revision": self.revision,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "cooldown_until": self.cooldown_until,
        }


@dataclass(frozen=True, slots=True)
class ExternalRecommendationProposal:
    lane: str
    capability_area: str
    title: str
    rationale: str
    source_summary: str
    classification: str
    required_authority: tuple[str, ...]
    provenance: ExternalResearchProvenance

    def __post_init__(self) -> None:
        if self.lane not in {"expand", "improve"}:
            raise CapabilityGrowthValidationError(
                "External research can create only EXPAND or linked IMPROVE recommendations."
            )
        if not isinstance(self.provenance, ExternalResearchProvenance):
            raise CapabilityGrowthValidationError("External research provenance is required.")


@dataclass(frozen=True, slots=True)
class SkillsReviewRecord:
    identifier: str
    scope: str
    capability_area: str
    status: str
    searches: int
    candidates: int
    inspections: int
    recommendation_count: int
    error_codes: tuple[str, ...]
    started_at: str
    completed_at: str | None

    def __post_init__(self) -> None:
        _hex_identifier(self.identifier, "review identifier", length=32)
        if self.scope not in {"general", "user_directed"}:
            raise CapabilityGrowthValidationError("Stored review scope is invalid.")
        _slug(self.capability_area, "review capability area")
        if self.status not in {"running", "completed", "partial", "failed"}:
            raise CapabilityGrowthValidationError("Stored review status is invalid.")
        for value in (self.searches, self.candidates, self.inspections, self.recommendation_count):
            if type(value) is not int or not 0 <= value <= 100:
                raise CapabilityGrowthValidationError("Stored review counts are invalid.")
        if len(self.error_codes) > 10 or any(_SLUG.fullmatch(item) is None for item in self.error_codes):
            raise CapabilityGrowthValidationError("Stored review error codes are invalid.")
        _timestamp(self.started_at)
        if self.completed_at is not None:
            _timestamp(self.completed_at)

    def document(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "scope": self.scope,
            "capability_area": self.capability_area,
            "status": self.status,
            "searches": self.searches,
            "candidates": self.candidates,
            "inspections": self.inspections,
            "recommendation_count": self.recommendation_count,
            "error_codes": list(self.error_codes),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class SQLiteImprovementJournal:
    """Owner-private exact-schema durable evidence and recommendation history."""

    def __init__(
        self,
        path: Path = DEFAULT_IMPROVEMENT_JOURNAL,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._safe_path(require_existing=False) is not None

    def initialize(self) -> None:
        with self._lock:
            if self.exists:
                connection = self._connect(readonly=True)
                connection.close()
                return
            self._initialize_atomic()

    def migrate_v1_to_v2(self) -> tuple[int, int]:
        """Explicitly type stored recommendation provenance while Tori is stopped."""

        with self._lock:
            path = self._safe_path(require_existing=True)
            assert path is not None
            connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ImprovementJournalCorruptError()
                schema = {
                    (row[0], row[1]): row[2]
                    for row in connection.execute(
                        "SELECT type,name,sql FROM sqlite_master "
                        "WHERE name NOT LIKE 'sqlite_%'"
                    )
                }
                metadata = connection.execute(
                    "SELECT key,value FROM journal_metadata"
                ).fetchall()
                if schema != _JOURNAL_SCHEMA_SQL or metadata != [
                    ("schema_version", str(PREVIOUS_IMPROVEMENT_JOURNAL_SCHEMA_VERSION))
                ]:
                    raise ImprovementJournalConflictError(
                        "The Improvement Journal is not schema version 1."
                    )
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT id,candidate_json FROM recommendations "
                    "WHERE candidate_json!='null'"
                ).fetchall()
                for identifier, encoded in rows:
                    try:
                        value = json.loads(encoded)
                        legacy = _legacy_candidate_from_document(value)
                    except (TypeError, ValueError, json.JSONDecodeError, CapabilityGrowthError) as exc:
                        raise ImprovementJournalCorruptError() from exc
                    connection.execute(
                        "UPDATE recommendations SET candidate_json=? WHERE id=?",
                        (_canonical_json(legacy.document()), identifier),
                    )
                connection.execute(
                    "UPDATE journal_metadata SET value=? "
                    "WHERE key='schema_version' AND value=?",
                    (
                        str(IMPROVEMENT_JOURNAL_SCHEMA_VERSION),
                        str(PREVIOUS_IMPROVEMENT_JOURNAL_SCHEMA_VERSION),
                    ),
                )
                connection.commit()
                self._validate_schema(connection)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return (1, 2)

    @contextmanager
    def maintenance_guard(self) -> Iterator[None]:
        with self._lock:
            if self.exists:
                connection = self._connect(readonly=True)
                connection.close()
            yield

    def record(self, evidence: CapabilityEvidence) -> tuple[ImprovementFinding, ...]:
        if not isinstance(evidence, CapabilityEvidence):
            raise CapabilityGrowthValidationError("Normalized capability evidence is required.")
        with self._lock:
            self.initialize()
            connection = self._connect(readonly=False)
            now = evidence.observed_at or _clock_timestamp(self._clock)
            identity_key = _identity_key(evidence)
            produced: list[str] = []
            try:
                with connection:
                    prior_success = connection.execute(
                        "SELECT count FROM findings WHERE identity_key=? AND evidence_kind='success'",
                        (identity_key,),
                    ).fetchone()
                    identifier = self._upsert_finding(
                        connection, evidence, identity_key, evidence.outcome, now
                    )
                    produced.append(identifier)
                    if evidence.outcome == "failure" and prior_success is not None and prior_success[0] > 0:
                        produced.append(
                            self._upsert_finding(
                                connection, evidence, identity_key, "regression", now
                            )
                        )
                    self._bound_history(connection)
            except sqlite3.Error as exc:
                raise ImprovementJournalUnavailableError() from exc
            finally:
                connection.close()
        return tuple(self.get_finding(identifier) for identifier in produced)

    def record_result(
        self,
        result: CapabilityResult,
        *,
        capability_area: str,
        operation_id: str,
        component_id: str,
        component_version: str,
        component_digest: str | None = None,
        error_code: str | None = None,
    ) -> tuple[ImprovementFinding, ...]:
        if not isinstance(result, CapabilityResult):
            raise CapabilityGrowthValidationError("A normalized capability result is required.")
        return self.record(CapabilityEvidence(
            capability_area=capability_area,
            capability_id=result.capability_id,
            operation_id=operation_id,
            outcome="success" if result.status == "succeeded" else "failure",
            error_code=error_code if result.status != "succeeded" else None,
            component_id=component_id,
            component_version=component_version,
            component_digest=component_digest,
        ))

    def get_finding(self, identifier: str) -> ImprovementFinding:
        _hex_identifier(identifier, "finding identifier")
        connection = self._connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT id,identity_key,lane,capability_area,capability_id,operation_id,"
                "evidence_kind,error_code,severity,component_id,component_version,component_digest,"
                "count,priority,status,revision,first_seen,last_seen FROM findings WHERE id=?",
                (identifier,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ImprovementJournalConflictError("That Improvement Journal finding was not found.")
        return _finding_from_row(row)

    def list_findings(
        self, *, statuses: Sequence[str] | None = None
    ) -> tuple[ImprovementFinding, ...]:
        if not self.exists:
            return ()
        selected = tuple(statuses or FINDING_STATUSES)
        if not selected or any(status not in FINDING_STATUSES for status in selected):
            raise CapabilityGrowthValidationError("Finding status filter is invalid.")
        connection = self._connect(readonly=True)
        placeholders = ",".join("?" for _ in selected)
        try:
            rows = connection.execute(
                "SELECT id,identity_key,lane,capability_area,capability_id,operation_id,"
                "evidence_kind,error_code,severity,component_id,component_version,component_digest,"
                "count,priority,status,revision,first_seen,last_seen FROM findings "
                f"WHERE status IN ({placeholders}) ORDER BY priority DESC,last_seen DESC,id LIMIT ?",
                (*selected, MAX_FINDINGS),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_finding_from_row(row) for row in rows)

    def update_finding_status(
        self, identifier: str, status: str, *, expected_revision: int
    ) -> ImprovementFinding:
        _hex_identifier(identifier, "finding identifier")
        if status not in FINDING_STATUSES:
            raise CapabilityGrowthValidationError("Finding lifecycle status is invalid.")
        revision = _revision(expected_revision)
        now = _clock_timestamp(self._clock)
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE findings SET status=?,revision=revision+1,last_seen=? "
                        "WHERE id=? AND revision=?",
                        (status, now, identifier, revision),
                    ).rowcount
                if changed != 1:
                    raise ImprovementJournalConflictError(
                        "That finding changed; refresh and review it again."
                    )
            finally:
                connection.close()
        return self.get_finding(identifier)

    def known_good_baselines(self) -> tuple[dict[str, object], ...]:
        if not self.exists:
            return ()
        connection = self._connect(readonly=True)
        try:
            rows = connection.execute(
                "SELECT identity_key,capability_area,capability_id,operation_id,component_id,"
                "component_version,component_digest,count,last_seen FROM findings "
                "WHERE evidence_kind='success' ORDER BY count DESC,last_seen DESC LIMIT 100"
            ).fetchall()
            failures = connection.execute(
                "SELECT identity_key,COALESCE(SUM(count),0),MAX(last_seen) FROM findings "
                "WHERE evidence_kind='failure' GROUP BY identity_key"
            ).fetchall()
        finally:
            connection.close()
        by_identity = {row[0]: (row[1], row[2]) for row in failures}
        result = []
        for row in rows:
            failure_count, failure_time = by_identity.get(row[0], (0, None))
            recent = failure_count if failure_time is not None and failure_time > row[8] else 0
            result.append({
                "capability_area": row[1],
                "capability_id": row[2],
                "operation_id": row[3],
                "component": {"identifier": row[4], "version": row[5], "digest": row[6]},
                "verified_successes": row[7],
                "recent_failures": recent,
                "last_success": row[8],
            })
        return tuple(result)

    def recommend(
        self,
        *,
        lane: str,
        capability_area: str,
        title: str,
        rationale: str,
        evidence: str,
        classification: str,
        required_authority: Sequence[str],
        candidate: RecommendationProvenance | None = None,
    ) -> ImprovementRecommendation:
        if lane not in LANES:
            raise CapabilityGrowthValidationError("Recommendation lane is invalid.")
        _slug(capability_area, "capability area")
        title = _bounded_text(title, "recommendation title", 200)
        rationale = _bounded_text(rationale, "recommendation rationale", MAX_TEXT)
        evidence = _bounded_text(evidence, "recommendation evidence", MAX_TEXT)
        if classification not in CLASSIFICATIONS:
            raise CapabilityGrowthValidationError("Recommendation classification is invalid.")
        authority = tuple(required_authority)
        if (
            not authority
            or len(authority) > 8
            or len(set(authority)) != len(authority)
            or any(item not in AUTHORITY_CHANGES for item in authority)
        ):
            raise CapabilityGrowthValidationError("Required authority changes are invalid.")
        if candidate is not None and not isinstance(
            candidate, (CandidateProvenance, ExternalResearchProvenance)
        ):
            raise CapabilityGrowthValidationError("Candidate provenance is invalid.")
        candidate_json = "null" if candidate is None else _canonical_json(candidate.document())
        dedupe_document = {
            "lane": lane,
            "capability_area": capability_area,
            "candidate": _provenance_identity(candidate),
            "title": title,
        }
        identifier = hashlib.sha256(_canonical_json(dedupe_document).encode()).hexdigest()
        material = hashlib.sha256(_canonical_json({
            "rationale": rationale,
            "evidence": evidence,
            "candidate": None if candidate is None else candidate.document(),
            "classification": classification,
            "required_authority": authority,
        }).encode()).hexdigest()
        now = _clock_timestamp(self._clock)
        with self._lock:
            self.initialize()
            connection = self._connect(readonly=False)
            try:
                row = connection.execute(
                    "SELECT material_fingerprint,status,cooldown_until FROM recommendations WHERE id=?",
                    (identifier,),
                ).fetchone()
                with connection:
                    if row is None:
                        self._reserve_capacity(
                            connection,
                            table="recommendations",
                            limit=MAX_RECOMMENDATIONS,
                            terminal_statuses=("dismissed", "resolved", "obsolete"),
                            timestamp_column="last_seen",
                        )
                        connection.execute(
                            "INSERT INTO recommendations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                identifier, lane, capability_area, title, rationale, evidence,
                                candidate_json, classification, _canonical_json(list(authority)),
                                material, "open", 1, now, now, None,
                            ),
                        )
                    else:
                        old_material, status, cooldown = row
                        within_cooldown = (
                            status == "dismissed"
                            and cooldown is not None
                            and _parse_timestamp(cooldown) > _parse_timestamp(now)
                            and old_material == material
                        )
                        if not within_cooldown and (
                            status in {"open", "dismissed", "obsolete"}
                            or old_material != material
                        ):
                            connection.execute(
                                "UPDATE recommendations SET rationale=?,evidence=?,candidate_json=?,"
                                "classification=?,required_authority_json=?,material_fingerprint=?,"
                                "status='open',revision=revision+1,last_seen=?,cooldown_until=NULL WHERE id=?",
                                (
                                    rationale, evidence, candidate_json, classification,
                                    _canonical_json(list(authority)), material, now, identifier,
                                ),
                            )
                    self._bound_history(connection)
            except sqlite3.Error as exc:
                raise ImprovementJournalUnavailableError() from exc
            finally:
                connection.close()
        return self.get_recommendation(identifier)

    def get_recommendation(self, identifier: str) -> ImprovementRecommendation:
        _hex_identifier(identifier, "recommendation identifier")
        connection = self._connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT id,lane,capability_area,title,rationale,evidence,candidate_json,"
                "classification,required_authority_json,status,revision,first_seen,last_seen,cooldown_until "
                "FROM recommendations WHERE id=?",
                (identifier,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ImprovementJournalConflictError("That recommendation was not found.")
        return _recommendation_from_row(row)

    def list_recommendations(
        self, *, statuses: Sequence[str] | None = None
    ) -> tuple[ImprovementRecommendation, ...]:
        if not self.exists:
            return ()
        selected = tuple(statuses or RECOMMENDATION_STATUSES)
        if not selected or any(status not in RECOMMENDATION_STATUSES for status in selected):
            raise CapabilityGrowthValidationError("Recommendation status filter is invalid.")
        connection = self._connect(readonly=True)
        placeholders = ",".join("?" for _ in selected)
        try:
            rows = connection.execute(
                "SELECT id,lane,capability_area,title,rationale,evidence,candidate_json,"
                "classification,required_authority_json,status,revision,first_seen,last_seen,cooldown_until "
                f"FROM recommendations WHERE status IN ({placeholders}) "
                "ORDER BY CASE lane WHEN 'fix' THEN 0 WHEN 'improve' THEN 1 ELSE 2 END,"
                "last_seen DESC,id LIMIT ?",
                (*selected, MAX_RECOMMENDATIONS),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_recommendation_from_row(row) for row in rows)

    def update_recommendation_status(
        self, identifier: str, status: str, *, expected_revision: int
    ) -> ImprovementRecommendation:
        _hex_identifier(identifier, "recommendation identifier")
        if status not in RECOMMENDATION_STATUSES:
            raise CapabilityGrowthValidationError("Recommendation lifecycle status is invalid.")
        revision = _revision(expected_revision)
        now = _clock_timestamp(self._clock)
        cooldown = (
            _timestamp_from_datetime(_parse_timestamp(now) + timedelta(days=RECOMMENDATION_COOLDOWN_DAYS))
            if status == "dismissed"
            else None
        )
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE recommendations SET status=?,revision=revision+1,last_seen=?,cooldown_until=? "
                        "WHERE id=? AND revision=?",
                        (status, now, cooldown, identifier, revision),
                    ).rowcount
                if changed != 1:
                    raise ImprovementJournalConflictError(
                        "That recommendation changed; refresh and review it again."
                    )
            finally:
                connection.close()
        return self.get_recommendation(identifier)

    def reconcile_active_evidence_recommendations(
        self, supported_identifiers: Sequence[str],
    ) -> tuple[str, ...]:
        """Obsolete only open evidence recommendations absent from current policy.

        Candidate-backed recommendations and every terminal or accepted user
        decision retain their own lifecycle.  Evidence rows are never changed.
        """

        supported = tuple(supported_identifiers)
        if len(set(supported)) != len(supported):
            raise CapabilityGrowthValidationError("Supported recommendation identifiers are invalid.")
        for identifier in supported:
            _hex_identifier(identifier, "recommendation identifier")
        now = _clock_timestamp(self._clock)
        with self._lock:
            self.initialize()
            connection = self._connect(readonly=False)
            try:
                clauses = [
                    "status='open'",
                    "candidate_json='null'",
                    "classification='ready_existing_authority'",
                    "(title LIKE 'Review % evidence for %' OR title LIKE 'Investigate regression in %')",
                ]
                parameters: list[object] = []
                if supported:
                    clauses.append("id NOT IN (" + ",".join("?" for _ in supported) + ")")
                    parameters.extend(supported)
                rows = connection.execute(
                    "SELECT id FROM recommendations WHERE " + " AND ".join(clauses),
                    parameters,
                ).fetchall()
                identifiers = tuple(str(row[0]) for row in rows)
                if identifiers:
                    with connection:
                        connection.execute(
                            "UPDATE recommendations SET status='obsolete',revision=revision+1,last_seen=? "
                            "WHERE id IN (" + ",".join("?" for _ in identifiers) + ")",
                            (now, *identifiers),
                        )
            except sqlite3.Error as exc:
                raise ImprovementJournalUnavailableError() from exc
            finally:
                connection.close()
        return identifiers

    def begin_review(self, *, scope: str, capability_area: str) -> SkillsReviewRecord:
        if scope not in {"general", "user_directed"}:
            raise CapabilityGrowthValidationError("Skills Review scope is invalid.")
        _slug(capability_area, "capability area")
        with self._lock:
            self.initialize()
            identifier = secrets.token_hex(16)
            now = _clock_timestamp(self._clock)
            connection = self._connect(readonly=False)
            try:
                with connection:
                    self._reserve_capacity(
                        connection,
                        table="skills_reviews",
                        limit=MAX_REVIEWS,
                        terminal_statuses=("completed", "partial", "failed"),
                        timestamp_column="started_at",
                    )
                    connection.execute(
                        "INSERT INTO skills_reviews VALUES (?,?,?,'running',0,0,0,0,'[]',?,NULL)",
                        (identifier, scope, capability_area, now),
                    )
            finally:
                connection.close()
        return self.get_review(identifier)

    def complete_review(
        self,
        identifier: str,
        *,
        status: str,
        searches: int,
        candidates: int,
        inspections: int,
        recommendation_count: int,
        error_codes: Sequence[str] = (),
    ) -> SkillsReviewRecord:
        _hex_identifier(identifier, "review identifier", length=32)
        if status not in {"completed", "partial", "failed"}:
            raise CapabilityGrowthValidationError("Skills Review result status is invalid.")
        counts = (searches, candidates, inspections, recommendation_count)
        if any(type(value) is not int or not 0 <= value <= 100 for value in counts):
            raise CapabilityGrowthValidationError("Skills Review counts are invalid.")
        errors = tuple(error_codes)
        if len(errors) > 10 or len(set(errors)) != len(errors):
            raise CapabilityGrowthValidationError("Skills Review error codes are invalid.")
        for code in errors:
            _slug(code, "Skills Review error code")
        now = _clock_timestamp(self._clock)
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE skills_reviews SET status=?,searches=?,candidates=?,inspections=?,"
                        "recommendation_count=?,error_codes_json=?,completed_at=? "
                        "WHERE id=? AND status='running'",
                        (
                            status, searches, candidates, inspections, recommendation_count,
                            _canonical_json(list(errors)), now, identifier,
                        ),
                    ).rowcount
                if changed != 1:
                    raise ImprovementJournalConflictError("That Skills Review is not running.")
            finally:
                connection.close()
        return self.get_review(identifier)

    def get_review(self, identifier: str) -> SkillsReviewRecord:
        _hex_identifier(identifier, "review identifier", length=32)
        connection = self._connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT id,scope,capability_area,status,searches,candidates,inspections,"
                "recommendation_count,error_codes_json,started_at,completed_at "
                "FROM skills_reviews WHERE id=?",
                (identifier,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ImprovementJournalConflictError("That Skills Review was not found.")
        return _review_from_row(row)

    def list_reviews(self) -> tuple[SkillsReviewRecord, ...]:
        if not self.exists:
            return ()
        connection = self._connect(readonly=True)
        try:
            rows = connection.execute(
                "SELECT id,scope,capability_area,status,searches,candidates,inspections,"
                "recommendation_count,error_codes_json,started_at,completed_at "
                "FROM skills_reviews ORDER BY started_at DESC,id LIMIT ?",
                (MAX_REVIEWS,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_review_from_row(row) for row in rows)

    def _upsert_finding(
        self,
        connection: sqlite3.Connection,
        evidence: CapabilityEvidence,
        identity_key: str,
        kind: str,
        now: str,
    ) -> str:
        error_code = evidence.error_code if kind in {"failure", "regression"} else None
        identifier = hashlib.sha256(
            f"{identity_key}\0{kind}\0{error_code or ''}".encode()
        ).hexdigest()
        existing = connection.execute(
            "SELECT count,status FROM findings WHERE id=?", (identifier,)
        ).fetchone()
        count = 1 if existing is None else existing[0] + 1
        priority = _priority(kind, count, evidence.severity)
        lane = _lane(kind)
        if existing is None:
            self._reserve_capacity(
                connection,
                table="findings",
                limit=MAX_FINDINGS,
                terminal_statuses=("resolved", "obsolete", "historical"),
                timestamp_column="last_seen",
            )
            connection.execute(
                "INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier, identity_key, lane, evidence.capability_area,
                    evidence.capability_id, evidence.operation_id, kind, error_code,
                    evidence.severity, evidence.component_id, evidence.component_version,
                    evidence.component_digest, count, priority, "open", 1, now, now,
                ),
            )
        else:
            status = "open" if existing[1] in {"resolved", "obsolete", "historical"} else existing[1]
            connection.execute(
                "UPDATE findings SET count=?,priority=?,severity=?,status=?,"
                "revision=revision+1,last_seen=? WHERE id=?",
                (count, priority, evidence.severity, status, now, identifier),
            )
        return identifier

    @staticmethod
    def _bound_history(connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM findings WHERE id IN (SELECT id FROM findings WHERE status IN "
            "('resolved','obsolete','historical') ORDER BY last_seen,id LIMIT MAX(0,"
            "(SELECT COUNT(*) FROM findings)-?))",
            (MAX_FINDINGS,),
        )
        connection.execute(
            "DELETE FROM recommendations WHERE id IN (SELECT id FROM recommendations WHERE status IN "
            "('dismissed','resolved','obsolete') ORDER BY last_seen,id LIMIT MAX(0,"
            "(SELECT COUNT(*) FROM recommendations)-?))",
            (MAX_RECOMMENDATIONS,),
        )
        connection.execute(
            "DELETE FROM skills_reviews WHERE id IN (SELECT id FROM skills_reviews "
            "WHERE status != 'running' ORDER BY started_at,id LIMIT MAX(0,"
            "(SELECT COUNT(*) FROM skills_reviews)-?))",
            (MAX_REVIEWS,),
        )

    @classmethod
    def _reserve_capacity(
        cls,
        connection: sqlite3.Connection,
        *,
        table: str,
        limit: int,
        terminal_statuses: Sequence[str],
        timestamp_column: str,
    ) -> None:
        """Make one bounded slot without discarding active evidence or decisions."""

        cls._bound_history(connection)
        count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count < limit:
            return
        placeholders = ",".join("?" for _ in terminal_statuses)
        row = connection.execute(
            f"SELECT id FROM {table} WHERE status IN ({placeholders}) "
            f"ORDER BY {timestamp_column},id LIMIT 1",
            tuple(terminal_statuses),
        ).fetchone()
        if row is None:
            raise ImprovementJournalConflictError(
                "The Improvement Journal is at its bounded active-record limit."
            )
        connection.execute(f"DELETE FROM {table} WHERE id=?", (row[0],))

    def _initialize_atomic(self) -> None:
        temporary: Path | None = None
        try:
            path = self._safe_parent()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(path.parent, 0o700)
            self._safe_parent()
            temporary = path.with_name(f".{path.name}.incomplete-{secrets.token_hex(16)}")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            connection = sqlite3.connect(temporary, timeout=5.0)
            try:
                _settings(connection)
                with connection:
                    for statement in _JOURNAL_SCHEMA_SQL.values():
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO journal_metadata VALUES ('schema_version',?)",
                        (str(IMPROVEMENT_JOURNAL_SCHEMA_VERSION),),
                    )
                self._validate_schema(connection)
            finally:
                connection.close()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, path)
            temporary.unlink()
            temporary = None
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self._safe_path(require_existing=True)
        except CapabilityGrowthError:
            raise
        except FileExistsError as exc:
            raise ImprovementJournalConflictError("The Improvement Journal already exists.") from exc
        except (OSError, sqlite3.Error) as exc:
            raise ImprovementJournalUnavailableError(
                "Tori could not initialize the Improvement Journal."
            ) from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        path = self._safe_path(require_existing=True)
        assert path is not None
        connection: sqlite3.Connection | None = None
        retain = False
        try:
            if readonly:
                connection = sqlite3.connect(
                    f"file:{quote(os.fspath(path), safe='/')}?mode=ro", uri=True, timeout=5.0
                )
            else:
                connection = sqlite3.connect(path, timeout=5.0, isolation_level="DEFERRED")
            connection.execute("PRAGMA foreign_keys=ON")
            self._validate_schema(connection)
            if not readonly:
                _settings(connection)
            retain = True
            return connection
        except CapabilityGrowthError:
            raise
        except sqlite3.DatabaseError as exc:
            raise ImprovementJournalCorruptError() from exc
        except (OSError, sqlite3.Error) as exc:
            raise ImprovementJournalUnavailableError() from exc
        finally:
            if connection is not None and not retain:
                connection.close()

    def _safe_parent(self) -> Path:
        raw = os.fspath(self._path)
        if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
            raise ImprovementJournalUnavailableError("The Improvement Journal path is unsafe.")
        path = Path(os.path.abspath(os.path.normpath(raw)))
        current = Path(path.anchor)
        missing = False
        for component in path.parent.parts[1:]:
            current /= component
            if missing:
                continue
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                missing = True
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ImprovementJournalUnavailableError("The Improvement Journal parent path is unsafe.")
        if not missing:
            info = os.lstat(path.parent)
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ImprovementJournalUnavailableError("The Improvement Journal parent is not owner-controlled.")
        return path

    def _safe_path(self, *, require_existing: bool) -> Path | None:
        path = self._safe_parent()
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            if require_existing:
                raise ImprovementJournalUnavailableError()
            return None
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ImprovementJournalUnavailableError("The Improvement Journal file is unsafe.")
        return path

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ImprovementJournalCorruptError()
            schema = {
                (row[0], row[1]): row[2]
                for row in connection.execute(
                    "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            metadata = connection.execute(
                "SELECT key,value FROM journal_metadata"
            ).fetchall()
            if schema == _JOURNAL_SCHEMA_SQL and metadata == [
                ("schema_version", str(PREVIOUS_IMPROVEMENT_JOURNAL_SCHEMA_VERSION))
            ]:
                raise ImprovementJournalCorruptError(
                    "The Improvement Journal requires the explicit v1-to-v2 schema migration."
                )
            if schema != _JOURNAL_SCHEMA_SQL:
                raise ImprovementJournalCorruptError()
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            indexes = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables != {"journal_metadata", "findings", "recommendations", "skills_reviews"}:
                raise ImprovementJournalCorruptError()
            if indexes != {"findings_priority", "recommendations_status", "reviews_started"}:
                raise ImprovementJournalCorruptError()
            expected = {
                "journal_metadata": ("key", "value"),
                "findings": (
                    "id", "identity_key", "lane", "capability_area", "capability_id", "operation_id",
                    "evidence_kind", "error_code", "severity", "component_id", "component_version",
                    "component_digest", "count", "priority", "status", "revision", "first_seen", "last_seen",
                ),
                "recommendations": (
                    "id", "lane", "capability_area", "title", "rationale", "evidence", "candidate_json",
                    "classification", "required_authority_json", "material_fingerprint", "status", "revision",
                    "first_seen", "last_seen", "cooldown_until",
                ),
                "skills_reviews": (
                    "id", "scope", "capability_area", "status", "searches", "candidates", "inspections",
                    "recommendation_count", "error_codes_json", "started_at", "completed_at",
                ),
            }
            for table, columns in expected.items():
                rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
                actual = tuple(row[1] for row in rows)
                if actual != columns:
                    raise ImprovementJournalCorruptError()
            expected_shapes = {
                "journal_metadata": (
                    ("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0),
                ),
                "findings": (
                    ("id", "TEXT", 0, 1), ("identity_key", "TEXT", 1, 0),
                    ("lane", "TEXT", 1, 0), ("capability_area", "TEXT", 1, 0),
                    ("capability_id", "TEXT", 1, 0), ("operation_id", "TEXT", 1, 0),
                    ("evidence_kind", "TEXT", 1, 0), ("error_code", "TEXT", 0, 0),
                    ("severity", "TEXT", 1, 0), ("component_id", "TEXT", 1, 0),
                    ("component_version", "TEXT", 1, 0), ("component_digest", "TEXT", 0, 0),
                    ("count", "INTEGER", 1, 0), ("priority", "INTEGER", 1, 0),
                    ("status", "TEXT", 1, 0), ("revision", "INTEGER", 1, 0),
                    ("first_seen", "TEXT", 1, 0), ("last_seen", "TEXT", 1, 0),
                ),
                "recommendations": (
                    ("id", "TEXT", 0, 1), ("lane", "TEXT", 1, 0),
                    ("capability_area", "TEXT", 1, 0), ("title", "TEXT", 1, 0),
                    ("rationale", "TEXT", 1, 0), ("evidence", "TEXT", 1, 0),
                    ("candidate_json", "TEXT", 1, 0), ("classification", "TEXT", 1, 0),
                    ("required_authority_json", "TEXT", 1, 0),
                    ("material_fingerprint", "TEXT", 1, 0), ("status", "TEXT", 1, 0),
                    ("revision", "INTEGER", 1, 0), ("first_seen", "TEXT", 1, 0),
                    ("last_seen", "TEXT", 1, 0), ("cooldown_until", "TEXT", 0, 0),
                ),
                "skills_reviews": (
                    ("id", "TEXT", 0, 1), ("scope", "TEXT", 1, 0),
                    ("capability_area", "TEXT", 1, 0), ("status", "TEXT", 1, 0),
                    ("searches", "INTEGER", 1, 0), ("candidates", "INTEGER", 1, 0),
                    ("inspections", "INTEGER", 1, 0),
                    ("recommendation_count", "INTEGER", 1, 0),
                    ("error_codes_json", "TEXT", 1, 0), ("started_at", "TEXT", 1, 0),
                    ("completed_at", "TEXT", 0, 0),
                ),
            }
            for table, shape in expected_shapes.items():
                actual_shape = tuple(
                    (row[1], row[2], row[3], row[5])
                    for row in connection.execute(f"PRAGMA table_info({table})")
                )
                if actual_shape != shape:
                    raise ImprovementJournalCorruptError()
            if metadata != [("schema_version", str(IMPROVEMENT_JOURNAL_SCHEMA_VERSION))]:
                raise ImprovementJournalCorruptError()
        except CapabilityGrowthError:
            raise
        except sqlite3.DatabaseError as exc:
            raise ImprovementJournalCorruptError() from exc


class CapabilityGrowthApplicationService:
    """Validated ingestion seam; external research never enters evidence tables."""

    def __init__(self, journal: SQLiteImprovementJournal) -> None:
        self._journal = journal

    def promote_external(
        self, proposal: ExternalRecommendationProposal
    ) -> ImprovementRecommendation:
        if not isinstance(proposal, ExternalRecommendationProposal):
            raise CapabilityGrowthValidationError(
                "A validated external recommendation proposal is required."
            )
        provenance = proposal.provenance
        with self._journal._lock:
            if proposal.lane == "improve":
                if provenance.friction_finding_id is None:
                    raise CapabilityGrowthValidationError(
                        "IMPROVE requires an existing operational-friction link."
                    )
                friction = self._journal.get_finding(provenance.friction_finding_id)
                if (
                    friction.status not in {"open", "monitoring"}
                    or friction.evidence_kind not in {"friction", "workaround", "opportunity"}
                    or friction.capability_area != proposal.capability_area
                ):
                    raise CapabilityGrowthValidationError(
                        "The linked operational-friction evidence is not eligible."
                    )
            elif provenance.friction_finding_id is not None:
                raise CapabilityGrowthValidationError(
                    "EXPAND promotion cannot claim operational-friction linkage."
                )

            existing = tuple(
                item for item in self._journal.list_recommendations()
                if isinstance(item.candidate, ExternalResearchProvenance)
                and item.candidate.run_id == provenance.run_id
            )
            same_finding = next(
                (
                    item for item in existing
                    if isinstance(item.candidate, ExternalResearchProvenance)
                    and item.candidate.finding_id == provenance.finding_id
                ),
                None,
            )
            if (
                same_finding is None
                and len({item.candidate.finding_id for item in existing})
                >= MAX_EXTERNAL_PROMOTIONS_PER_RUN
            ):
                raise ImprovementJournalConflictError(
                    "That Night Owl run reached its Capability Growth promotion limit."
                )
            return self._journal.recommend(
                lane=proposal.lane,
                capability_area=proposal.capability_area,
                title=proposal.title,
                rationale=proposal.rationale,
                evidence=proposal.source_summary,
                classification=proposal.classification,
                required_authority=proposal.required_authority,
                candidate=provenance,
            )


@dataclass(frozen=True, slots=True)
class CapabilityInventoryItem:
    identifier: str
    name: str
    kind: str
    state: str
    detail: str
    version: str | None = None
    digest: str | None = None
    operations: tuple[str, ...] = ()

    def document(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "name": self.name,
            "kind": self.kind,
            "state": self.state,
            "detail": self.detail,
            "version": self.version,
            "digest": self.digest,
            "operations": list(self.operations),
        }


class CapabilityInventory:
    """Compact read-only inventory derived only from application-owned state."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        skills: SkillApplicationService | None = None,
        mcp: MCPServerRegistry | None = None,
        origin: RequestOrigin,
    ) -> None:
        self._registry = registry
        self._skills = skills
        self._mcp = mcp
        self._origin = origin

    def snapshot(self) -> tuple[CapabilityInventoryItem, ...]:
        state = self._registry.snapshot()
        items = [
            CapabilityInventoryItem(
                capability.identifier,
                capability.name,
                "native",
                state[capability.identifier].state,
                state[capability.identifier].detail,
            )
            for capability in CAPABILITIES
        ]
        if self._skills is not None:
            try:
                for entry in self._skills.registry.list_entries():
                    reference = entry.manifest.version_ref
                    operations = tuple(operation.identifier for operation in entry.manifest.operations)
                    items.append(CapabilityInventoryItem(
                        identifier=f"skill.{entry.manifest.identity.canonical_id}",
                        name=entry.manifest.display_name,
                        kind="skill",
                        state=entry.state,
                        detail=self._skills.compatibility_status(entry.manifest),
                        version=reference.version,
                        digest=reference.content_digest,
                        operations=operations,
                    ))
            except SkillError:
                items.append(CapabilityInventoryItem(
                    "skills.registry", "Skills registry", "skill", "unavailable",
                    "state could not be read",
                ))
        if self._mcp is not None:
            for server_id in self._mcp.server_ids():
                try:
                    document = self._mcp.document(server_id)
                    items.append(CapabilityInventoryItem(
                        identifier=f"mcp.{server_id}",
                        name=f"MCP {server_id}",
                        kind="mcp",
                        state="enabled" if document["enabled"] is True else "disabled",
                        detail="approved tools only",
                        version=str(document["server_version"]),
                        digest=str(document["configuration_digest"]),
                        operations=tuple(sorted(str(name) for name in document["approved_tools"])),
                    ))
                except (MCPError, KeyError, TypeError):
                    items.append(CapabilityInventoryItem(
                        f"mcp.{server_id}", f"MCP {server_id}", "mcp", "unavailable",
                        "state could not be read",
                    ))
        return tuple(items[:256])

    def has_markers(self, markers: Sequence[str]) -> bool:
        terms = tuple(marker.casefold() for marker in markers)
        for item in self.snapshot():
            if item.state not in {"available", "configured", "enabled"}:
                continue
            text = " ".join((item.identifier, item.name, *item.operations)).casefold()
            if any(marker in text for marker in terms):
                return True
        return False

    def document(self) -> dict[str, object]:
        items = self.snapshot()
        return {
            "items": [item.document() for item in items],
            "counts": {
                "native": sum(item.kind == "native" for item in items),
                "skills": sum(item.kind == "skill" for item in items),
                "mcp": sum(item.kind == "mcp" for item in items),
            },
        }


@dataclass(frozen=True, slots=True)
class SkillsReviewIntent:
    scope: str
    capability_area: str
    search_query: str | None


@dataclass(frozen=True, slots=True)
class CapabilityHorizon:
    area: str
    label: str
    query: str
    markers: tuple[str, ...]
    classification: str
    required_authority: tuple[str, ...]


CAPABILITY_HORIZON = (
    CapabilityHorizon("documents", "document creation and conversion", "document files docx pdf", ("document.convert", "docx", "pdf.modify"), "needs_application_adapter", ("application_adapter", "user_decision")),
    CapabilityHorizon("spreadsheets_data", "general spreadsheet and data files", "excel spreadsheet xlsx csv", ("excel", "spreadsheet", "xlsx", "csv_tools"), "needs_application_adapter", ("application_adapter", "user_decision")),
    CapabilityHorizon("images_media", "image generation and editing", "image generation editing", ("image.generate", "image_generation", "image.edit"), "needs_mcp_or_external_integration", ("external_integration", "user_decision")),
    CapabilityHorizon("communication", "communication services", "communication messaging", ("email", "discord", "slack", "messaging"), "needs_mcp_or_external_integration", ("mcp_integration", "user_decision")),
    CapabilityHorizon("coding", "coding workflows", "coding development", ("coding_work", "code", "github"), "needs_skill_lifecycle_or_permission", ("skill_install", "skill_enable", "user_decision")),
    CapabilityHorizon("system_administration", "system administration", "linux system administration", ("host", "services", "run"), "needs_skill_lifecycle_or_permission", ("skill_install", "skill_enable", "user_decision")),
    CapabilityHorizon("planning_productivity", "planning and productivity", "planning productivity", ("planning", "tasks", "projects"), "needs_skill_lifecycle_or_permission", ("skill_install", "skill_enable", "user_decision")),
    CapabilityHorizon("research_knowledge", "research and knowledge", "research knowledge", ("search", "knowledge"), "needs_skill_lifecycle_or_permission", ("skill_install", "skill_enable", "user_decision")),
    CapabilityHorizon("automation_integration", "automation and integration", "automation integration", ("scheduled_work", "mcp."), "needs_mcp_or_external_integration", ("mcp_integration", "user_decision")),
    CapabilityHorizon("local_ai_integration", "local AI integration", "local ai model integration", ("tts", "model", "ollama"), "needs_application_adapter", ("application_adapter", "user_decision")),
)


class SkillsResearchPort(Protocol):
    def search(
        self, query: object, *, limit: object, origin: RequestOrigin
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class SkillsReviewResult:
    review: SkillsReviewRecord
    recommendations: tuple[ImprovementRecommendation, ...]
    searched_areas: tuple[str, ...]
    successful_inspections: int

    @property
    def failed_inspections(self) -> int:
        """Inspection attempts that failed before immutable bytes were verified."""

        return self.review.inspections - self.successful_inspections

    def document(self) -> dict[str, object]:
        return {
            "review": self.review.document(),
            "recommendations": [item.document() for item in self.recommendations],
            "searched_areas": list(self.searched_areas),
            # The durable review schema intentionally records the bounded attempt
            # count. Successes are request-result detail, so a failed attempt is
            # never represented as an immutable inspection.
            "inspection_attempts": self.review.inspections,
            "successful_inspections": self.successful_inspections,
            "failed_inspections": self.failed_inspections,
            "authority": (
                "Advisory only. Nothing was installed, enabled, granted, executed, "
                "downloaded outside quarantine, or changed in Tori's configuration."
            ),
        }


class SkillsReviewService:
    """Reusable manual review service; a future scheduler may call only with authority."""

    def __init__(
        self,
        journal: SQLiteImprovementJournal,
        inventory: CapabilityInventory,
        discovery: SkillsShDiscoveryService,
        *,
        github: GitHubSkillLifecycleService | None = None,
        origin_authority: OriginAuthority | None = None,
    ) -> None:
        self.journal = journal
        self.inventory = inventory
        self.discovery = discovery
        self.github = github
        self._authority = origin_authority or OriginAuthority()
        self._review_lock = threading.Lock()

    def run(self, intent: SkillsReviewIntent, *, origin: RequestOrigin) -> SkillsReviewResult:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        if not isinstance(intent, SkillsReviewIntent) or intent.scope not in {"general", "user_directed"}:
            raise CapabilityGrowthValidationError("A valid explicit Skills Review request is required.")
        if not self._review_lock.acquire(blocking=False):
            raise ImprovementJournalConflictError("A Skills Review is already running.")
        try:
            return self._run(intent, origin=origin)
        finally:
            self._review_lock.release()

    def _run(self, intent: SkillsReviewIntent, *, origin: RequestOrigin) -> SkillsReviewResult:
        horizons = self._horizons(intent)
        review = self.journal.begin_review(
            scope=intent.scope,
            capability_area=intent.capability_area,
        )
        recommendations: list[ImprovementRecommendation] = []
        errors: list[str] = []
        searches = candidates_seen = inspections = successful_inspections = 0
        searched_areas: list[str] = []
        try:
            if intent.scope == "general":
                journal_recommendations = self._journal_recommendations()
                recommendations.extend(journal_recommendations)
                self.journal.reconcile_active_evidence_recommendations(
                    tuple(item.identifier for item in journal_recommendations)
                )
            for horizon in horizons[:MAX_REVIEW_SEARCHES]:
                searched_areas.append(horizon.area)
                searches += 1
                try:
                    result = self.discovery.search(
                        horizon.query,
                        limit=MAX_REVIEW_CANDIDATES_PER_SEARCH,
                        origin=origin,
                    )
                    self.journal.record(CapabilityEvidence(
                        capability_area="skill_research",
                        capability_id="skills.sh",
                        operation_id="search",
                        outcome="success",
                        component_id="skills.sh",
                        component_version="v1",
                    ))
                except SkillsShDiscoveryError as exc:
                    errors.append(exc.code)
                    self.journal.record(CapabilityEvidence(
                        capability_area="skill_research",
                        capability_id="skills.sh",
                        operation_id="search",
                        outcome="failure",
                        error_code=exc.code,
                        component_id="skills.sh",
                        component_version="v1",
                    ))
                    continue
                selected = _rank_candidates(horizon.query, result.candidates)
                candidates_seen += len(selected)
                for candidate in selected:
                    inspected = None
                    if self.github is not None and inspections < MAX_REVIEW_INSPECTIONS:
                        inspections += 1
                        try:
                            inspected = self.github.inspect(candidate.github_url, origin=origin)
                            successful_inspections += 1
                            self.journal.record(CapabilityEvidence(
                                capability_area="skill_research",
                                capability_id="github.skill.inspect",
                                operation_id="inspect",
                                outcome="success",
                                component_id="github.skill.acquisition",
                                component_version="v1",
                                component_digest=inspected.digest,
                            ))
                        except GitHubSkillError as exc:
                            errors.append(exc.code)
                            self.journal.record(CapabilityEvidence(
                                capability_area="skill_research",
                                capability_id="github.skill.inspect",
                                operation_id="inspect",
                                outcome="failure",
                                error_code=exc.code,
                                component_id="github.skill.acquisition",
                                component_version="v1",
                            ))
                    provenance = _candidate_provenance(candidate, inspected)
                    classification, authority, rationale = self._classify(
                        horizon, provenance, inspected
                    )
                    recommendation = self.journal.recommend(
                        lane="expand",
                        capability_area=horizon.area,
                        title=f"Review {provenance.name} for {horizon.label}",
                        rationale=rationale,
                        evidence=(
                            "Immutable GitHub bytes were inspected through Tori's trusted pipeline."
                            if provenance.inspected
                            else "skills.sh returned an uninspected GitHub candidate; catalog text is not proof."
                        ),
                        classification=classification,
                        required_authority=authority,
                        candidate=provenance,
                    )
                    recommendations.append(recommendation)
            # A completed review is about completing its bounded evaluation, not
            # finding a catalog candidate.  Discovery and inspection faults are
            # preserved as partial evidence; only an exception that prevents this
            # service from completing records a failed review below.
            status = "completed" if not errors else "partial"
            completed = self.journal.complete_review(
                review.identifier,
                status=status,
                searches=searches,
                candidates=candidates_seen,
                inspections=inspections,
                recommendation_count=len({item.identifier for item in recommendations}),
                error_codes=tuple(dict.fromkeys(errors)),
            )
            return SkillsReviewResult(
                completed,
                tuple(_dedupe_recommendations(recommendations)),
                tuple(searched_areas),
                successful_inspections,
            )
        except Exception:
            try:
                self.journal.complete_review(
                    review.identifier,
                    status="failed",
                    searches=searches,
                    candidates=candidates_seen,
                    inspections=inspections,
                    recommendation_count=len({item.identifier for item in recommendations}),
                    error_codes=tuple(dict.fromkeys(errors or ["review_failed"])),
                )
            except CapabilityGrowthError:
                pass
            raise

    def _horizons(self, intent: SkillsReviewIntent) -> tuple[CapabilityHorizon, ...]:
        if intent.scope == "user_directed":
            horizon = next(
                (item for item in CAPABILITY_HORIZON if item.area == intent.capability_area),
                None,
            )
            if horizon is None:
                query = _bounded_search_query(intent.search_query)
                return (CapabilityHorizon(
                    intent.capability_area, intent.capability_area.replace("_", " "), query,
                    (intent.capability_area,), "needs_skill_lifecycle_or_permission",
                    ("skill_install", "skill_enable", "user_decision"),
                ),)
            if intent.search_query is not None:
                return (CapabilityHorizon(
                    horizon.area, horizon.label, _bounded_search_query(intent.search_query),
                    horizon.markers, horizon.classification, horizon.required_authority,
                ),)
            return (horizon,)
        missing = tuple(
            item for item in CAPABILITY_HORIZON
            if not self.inventory.has_markers(item.markers)
        )
        return missing

    def _journal_recommendations(self) -> tuple[ImprovementRecommendation, ...]:
        recommendations = []
        findings = self.journal.list_findings(statuses=("open", "monitoring"))
        regression_identities = {
            finding.identity_key for finding in findings
            if finding.evidence_kind == "regression"
        }
        for finding in findings:
            # Success is retained as a known-good regression baseline.  It is
            # deliberately not an improvement signal on its own.
            if finding.evidence_kind == "success":
                continue
            # A regression is the higher-priority interpretation of the same
            # component/operation lineage, so its FIX recommendation supersedes
            # the lower-priority duplicate failure recommendation.
            if (
                finding.evidence_kind == "failure"
                and finding.identity_key in regression_identities
            ):
                continue
            if finding.lane not in {"fix", "improve"}:
                continue
            recommendations.append(self.journal.recommend(
                lane=finding.lane,
                capability_area=finding.capability_area,
                title=(
                    f"Investigate regression in {finding.capability_id}"
                    if finding.evidence_kind == "regression"
                    else f"Review {finding.evidence_kind} evidence for {finding.capability_id}"
                ),
                rationale=(
                    f"Tori recorded {finding.count} verified {finding.evidence_kind} outcome"
                    f"{'s' if finding.count != 1 else ''} for {finding.operation_id}."
                ),
                evidence=(
                    f"Component {finding.component_id} {finding.component_version}; "
                    f"priority {finding.priority}; error {finding.error_code or 'none'}."
                ),
                classification="ready_existing_authority",
                required_authority=("user_decision",),
            ))
        return tuple(recommendations)

    def _classify(
        self,
        horizon: CapabilityHorizon,
        provenance: CandidateProvenance,
        inspection: object,
    ) -> tuple[str, tuple[str, ...], str]:
        installed = any(
            item.kind == "skill"
            and item.identifier.endswith(provenance.skill_id)
            and item.state != "uninstalled"
            for item in self.inventory.snapshot()
        )
        if installed:
            return (
                "duplicate_little_benefit",
                ("none",),
                "Tori already has this Skill identity; unchanged duplicate installation offers little benefit.",
            )
        if inspection is not None:
            compatibility = provenance.compatibility
            unsupported = tuple(getattr(inspection, "unsupported_components", ()))
            if compatibility not in {"compatible", "compatible_instruction_only"}:
                if "scripts" in unsupported:
                    return (
                        "requires_unsupported_executable",
                        ("unsupported_executable", "user_decision"),
                        "The package includes behavior Tori cannot execute; bundled scripts remain inert.",
                    )
                return (
                    "not_recommended", ("none",),
                    "The inspected package is not compatible with Tori's current Skill contract.",
                )
        if horizon.classification in {"needs_application_adapter", "needs_mcp_or_external_integration"}:
            return (
                horizon.classification,
                horizon.required_authority,
                f"The Skill may provide useful guidance, but Tori still lacks the approved "
                f"{horizon.label} adapter or integration required to perform the capability.",
            )
        return (
            "needs_skill_lifecycle_or_permission",
            ("skill_install", "skill_enable", "user_decision"),
            "The candidate may fit Tori's existing instruction-Skill boundary, but installation and enablement remain separate user decisions.",
        )


def recognize_skills_review(text: object) -> SkillsReviewIntent | None:
    """Recognize only explicit manual review or user-directed Skill research."""

    if not isinstance(text, str) or not text.strip() or len(text) > 2_000:
        return None
    value = " ".join(text.strip().split())
    if re.fullmatch(
        r"(?is)(?:please\s+)?(?:run|start|perform)\s+(?:a\s+)?skills? review[.!?]*",
        value,
    ) or re.fullmatch(
        r"(?is)(?:please\s+)?(?:look for useful skills? (?:we|you) (?:do not|don't) have(?: yet)?|"
        r"what capabilities are you missing)[.!?]*",
        value,
    ):
        return SkillsReviewIntent("general", "all", None)
    patterns = (
        r"(?:please\s+)?find (?:a|some) skills? for (.+?)[.!?]*",
        r"(?:please\s+)?find (?:a|some) skills? that could help(?: you)?(?: work)? with (.+?)[.!?]*",
        r"(?:please\s+)?is there (?:a|some) skills? for (.+?)[.!?]*",
        r"(?:please\s+)?find something useful for (.+?)[.!?]*",
        r"(?:please\s+)?look for (.+?) skills?[.!?]*",
    )
    topic = None
    for pattern in patterns:
        match = re.fullmatch(pattern, value, re.IGNORECASE)
        if match is not None:
            topic = match.group(1).strip()
            break
    if topic is None:
        return None
    if topic.casefold() in {"this", "this task", "that", "it"}:
        return SkillsReviewIntent("user_directed", "unspecified", None)
    area = _area_for_topic(topic)
    return SkillsReviewIntent("user_directed", area.area, topic)


def capability_growth_document(
    journal: SQLiteImprovementJournal | None,
    inventory: CapabilityInventory | None,
) -> dict[str, object]:
    if journal is None or inventory is None:
        return {
            "available": False,
            "message": "Capability Growth is not configured.",
            "inventory": {"items": [], "counts": {"native": 0, "skills": 0, "mcp": 0}},
            "findings": [], "recommendations": [], "history": [], "reviews": [], "baselines": [],
        }
    recommendations = journal.list_recommendations()
    return {
        "available": True,
        "message": "Advisory only; Tori cannot modify herself or grant authority.",
        "inventory": inventory.document(),
        "findings": [
            item.document()
            for item in journal.list_findings(statuses=("open", "monitoring"))
            if item.evidence_kind != "success"
        ],
        "recommendations": [
            item.document() for item in recommendations if item.status in {"open", "accepted"}
        ],
        "history": [
            item.document() for item in recommendations
            if item.status in {"dismissed", "resolved", "obsolete"}
        ],
        "reviews": [item.document() for item in journal.list_reviews()],
        "baselines": list(journal.known_good_baselines()),
    }


def format_skills_review(result: SkillsReviewResult) -> str:
    review = result.review
    review_status = (
        "completed with no new candidates"
        if review.status == "completed" and review.candidates == 0
        else review.status
    )
    lines = [
        f"Skills Review {review_status}: examined FIX, IMPROVE, and EXPAND under the current capability inventory.",
        f"Bounded research: {review.searches} search(es), {review.candidates} candidate(s), "
        f"and {review.inspections} immutable inspection attempt(s): "
        f"{result.successful_inspections} successful and {result.failed_inspections} failed.",
    ]
    if not result.recommendations:
        lines.append("I found no new actionable recommendation within this review's bounded horizon.")
    for index, recommendation in enumerate(result.recommendations[:9], start=1):
        lines.append(
            f"{index}. {recommendation.lane.upper()} — {recommendation.title}. "
            f"{_classification_label(recommendation.classification)}. {recommendation.rationale}"
        )
        if recommendation.candidate is not None:
            provenance = recommendation.candidate
            if isinstance(provenance, ExternalResearchProvenance):
                lines.append(
                    f"   External research provenance: {provenance.source_identity}; "
                    f"Night Owl finding {provenance.finding_id}."
                )
            elif provenance.inspected:
                lines.append(
                    f"   Inspected provenance: {provenance.repository}@{provenance.commit} "
                    f"path {provenance.package_path}; digest {provenance.digest}."
                )
            else:
                lines.append(
                    f"   Uninspected catalog identity: {provenance.catalog_id}; GitHub path mapping remains unverified."
                )
        lines.append(
            "   Required next authority: " + ", ".join(recommendation.required_authority) + "."
        )
    lines.append(
        "Nothing was installed, enabled, granted, or executed. Any change remains a separate user decision through the existing lifecycle."
    )
    return "\n".join(lines)


def _area_for_topic(topic: str) -> CapabilityHorizon:
    value = topic.casefold()
    mappings = (
        (("excel", "spreadsheet", "xlsx", "csv", "data"), "spreadsheets_data"),
        (("image", "photo", "picture", "graphic", "media"), "images_media"),
        (("discord", "email", "slack", "message", "communication"), "communication"),
        (("document", "docx", "word", "pdf"), "documents"),
        (("code", "coding", "developer", "github"), "coding"),
        (("linux", "system", "admin"), "system_administration"),
        (("plan", "calendar", "productivity", "task"), "planning_productivity"),
        (("research", "knowledge", "citation"), "research_knowledge"),
        (("automation", "integration", "workflow"), "automation_integration"),
        (("local ai", "ollama", "model", "llm"), "local_ai_integration"),
    )
    for terms, area in mappings:
        if any(term in value for term in terms):
            return next(item for item in CAPABILITY_HORIZON if item.area == area)
    tokens = re.findall(r"[a-z0-9]+", value)[:4]
    slug = "_".join(tokens) or "other"
    if len(slug) > 128 or _SLUG.fullmatch(slug) is None:
        slug = "other"
    return CapabilityHorizon(
        slug, slug.replace("_", " "), " ".join(tokens) or "useful capability",
        (slug,), "needs_skill_lifecycle_or_permission",
        ("skill_install", "skill_enable", "user_decision"),
    )


def _bounded_search_query(value: object) -> str:
    if not isinstance(value, str):
        raise CapabilityGrowthValidationError("A specific Skill capability is required.")
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9+._-]{0,39}", value)[:8]
    query = " ".join(tokens)
    if not query or len(query) > 200:
        raise CapabilityGrowthValidationError("The Skill search topic is invalid or too broad.")
    return query


def _rank_candidates(
    query: str, candidates: Sequence[SkillsShCandidate]
) -> tuple[SkillsShCandidate, ...]:
    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))

    def key(candidate: SkillsShCandidate) -> tuple[int, bool, int, str]:
        identity = set(re.findall(
            r"[a-z0-9]+",
            f"{candidate.name} {candidate.skill_id} {candidate.source}".casefold(),
        ))
        installs = candidate.installs if candidate.installs is not None else -1
        return (-len(terms & identity), candidate.is_duplicate, -installs, candidate.catalog_id)

    return tuple(sorted(candidates, key=key)[:MAX_REVIEW_CANDIDATES_PER_SEARCH])


def _candidate_provenance(candidate: SkillsShCandidate, inspection: object) -> CandidateProvenance:
    if inspection is None:
        return CandidateProvenance(
            candidate.catalog_id, candidate.skill_id, candidate.name,
            f"https://github.com/{candidate.source}", None, f"skills/{candidate.skill_id}",
            None, None, "uninspected", False,
        )
    return CandidateProvenance(
        candidate.catalog_id,
        str(getattr(inspection, "skill_id")),
        str(getattr(inspection, "name")),
        str(getattr(inspection, "repository")),
        str(getattr(inspection, "commit")),
        str(getattr(inspection, "package_path")),
        str(getattr(inspection, "version")),
        str(getattr(inspection, "digest")),
        str(getattr(inspection, "compatibility")),
        True,
    )


def _dedupe_recommendations(
    recommendations: Sequence[ImprovementRecommendation],
) -> tuple[ImprovementRecommendation, ...]:
    result: dict[str, ImprovementRecommendation] = {}
    for recommendation in recommendations:
        result[recommendation.identifier] = recommendation
    return tuple(result.values())


def _finding_from_row(row: Sequence[object]) -> ImprovementFinding:
    try:
        return ImprovementFinding(
            identifier=str(row[0]), identity_key=str(row[1]), lane=str(row[2]),
            capability_area=str(row[3]), capability_id=str(row[4]), operation_id=str(row[5]),
            evidence_kind=str(row[6]), error_code=None if row[7] is None else str(row[7]),
            severity=str(row[8]), component_id=str(row[9]), component_version=str(row[10]),
            component_digest=None if row[11] is None else str(row[11]), count=int(row[12]),
            priority=int(row[13]), status=str(row[14]), revision=int(row[15]),
            first_seen=str(row[16]), last_seen=str(row[17]),
        )
    except (TypeError, ValueError, CapabilityGrowthError) as exc:
        raise ImprovementJournalCorruptError() from exc


def _recommendation_from_row(row: Sequence[object]) -> ImprovementRecommendation:
    try:
        candidate_value = json.loads(str(row[6]))
        authority_value = json.loads(str(row[8]))
        if candidate_value is not None and not isinstance(candidate_value, dict):
            raise ValueError("invalid candidate")
        if not isinstance(authority_value, list):
            raise ValueError("invalid authority")
        candidate = None if candidate_value is None else _provenance_from_document(candidate_value)
        recommendation = ImprovementRecommendation(
            identifier=str(row[0]), lane=str(row[1]), capability_area=str(row[2]),
            title=str(row[3]), rationale=str(row[4]), evidence=str(row[5]), candidate=candidate,
            classification=str(row[7]), required_authority=tuple(authority_value),
            status=str(row[9]), revision=int(row[10]), first_seen=str(row[11]),
            last_seen=str(row[12]), cooldown_until=None if row[13] is None else str(row[13]),
        )
        if recommendation.lane not in LANES or recommendation.classification not in CLASSIFICATIONS:
            raise ValueError("invalid recommendation")
        if recommendation.status not in RECOMMENDATION_STATUSES:
            raise ValueError("invalid recommendation status")
        if any(item not in AUTHORITY_CHANGES for item in recommendation.required_authority):
            raise ValueError("invalid recommendation authority")
        return recommendation
    except (TypeError, ValueError, json.JSONDecodeError, CapabilityGrowthError) as exc:
        raise ImprovementJournalCorruptError() from exc


def _review_from_row(row: Sequence[object]) -> SkillsReviewRecord:
    try:
        errors = json.loads(str(row[8]))
        if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
            raise ValueError("invalid errors")
        return SkillsReviewRecord(
            str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]),
            int(row[5]), int(row[6]), int(row[7]), tuple(errors), str(row[9]),
            None if row[10] is None else str(row[10]),
        )
    except (TypeError, ValueError, json.JSONDecodeError, CapabilityGrowthError) as exc:
        raise ImprovementJournalCorruptError() from exc


def _identity_key(evidence: CapabilityEvidence) -> str:
    return hashlib.sha256(_canonical_json({
        "capability_area": evidence.capability_area,
        "capability_id": evidence.capability_id,
        "operation_id": evidence.operation_id,
        "component_id": evidence.component_id,
        "component_version": evidence.component_version,
        "component_digest": evidence.component_digest,
    }).encode()).hexdigest()


def _provenance_from_document(value: object) -> RecommendationProvenance:
    if not isinstance(value, Mapping):
        raise CapabilityGrowthValidationError("Recommendation provenance is invalid.")
    kind = value.get("kind")
    if kind == "skill_candidate":
        return CandidateProvenance.from_document(value)
    if kind == "external_research":
        return ExternalResearchProvenance.from_document(value)
    raise CapabilityGrowthValidationError("Recommendation provenance kind is invalid.")


def _legacy_candidate_from_document(value: object) -> CandidateProvenance:
    item = _exact_mapping(
        value,
        {
            "catalog_id", "skill_id", "name", "repository", "commit",
            "package_path", "version", "digest", "compatibility", "inspected",
        },
        "legacy candidate provenance",
    )
    return CandidateProvenance(**item)  # type: ignore[arg-type]


def _provenance_identity(
    value: RecommendationProvenance | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, CandidateProvenance):
        return {
            "kind": "skill_candidate",
            "skill_id": value.skill_id,
            "repository": value.repository,
            "package_path": value.package_path,
        }
    return {
        "kind": "external_research",
        "finding_id": value.finding_id,
        "source_identity": value.source_identity,
    }


def _lane(kind: str) -> str:
    if kind in {"failure", "regression"}:
        return "fix"
    if kind in {"friction", "workaround"}:
        return "improve"
    return "expand" if kind == "opportunity" else "improve"


def _priority(kind: str, count: int, severity: str) -> int:
    if kind == "regression":
        return 600 + min(count, 99)
    if kind == "failure" and count >= 2:
        return 500 + min(count, 99)
    if kind == "failure" and severity in {"high", "critical"}:
        return 450 + (25 if severity == "critical" else 0)
    if kind == "failure":
        return 400
    if kind == "friction":
        return 300 + min(count, 99)
    if kind == "workaround":
        return 275 + min(count, 99)
    if kind == "opportunity":
        return 200 + min(count, 99)
    return 100 + min(count, 99)


def _classification_label(value: str) -> str:
    return {
        "ready_existing_authority": "Ready under existing authority",
        "needs_skill_lifecycle_or_permission": "Needs Skill install/enable or permission change",
        "needs_application_adapter": "Needs application adapter",
        "needs_mcp_or_external_integration": "Needs MCP/external integration",
        "requires_unsupported_executable": "Requires unsupported executable behavior",
        "duplicate_little_benefit": "Duplicate / little benefit",
        "not_recommended": "Not recommended",
    }[value]


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise CapabilityGrowthValidationError(f"{label} is invalid or too long.")
    return value.strip()


def _slug(value: object, label: str) -> str:
    text = _bounded_text(value, label, 128)
    if _SLUG.fullmatch(text) is None:
        raise CapabilityGrowthValidationError(f"{label} must be a stable lowercase identifier.")
    return text


def _identifier(value: object, label: str) -> str:
    text = _bounded_text(value, label, 400)
    if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,399}", text) is None:
        raise CapabilityGrowthValidationError(f"{label} is invalid.")
    return text


def _hex_identifier(value: object, label: str, *, length: int = 64) -> str:
    if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
        raise CapabilityGrowthValidationError(f"{label} is invalid.")
    return value


def _timestamp(value: object) -> str:
    text = _bounded_text(value, "timestamp", 40)
    if _UTC_TIMESTAMP.fullmatch(text) is None:
        raise CapabilityGrowthValidationError("Timestamp must be UTC RFC 3339 text.")
    _parse_timestamp(text)
    return text


def _parse_timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise CapabilityGrowthValidationError("Timestamp is invalid.") from exc
    if result.tzinfo is None:
        raise CapabilityGrowthValidationError("Timestamp is invalid.")
    return result.astimezone(timezone.utc)


def _timestamp_from_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ImprovementJournalUnavailableError("The Improvement Journal clock is invalid.")
    return _timestamp_from_datetime(value)


def _revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise CapabilityGrowthValidationError("Lifecycle revision is invalid.")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CapabilityGrowthValidationError("Capability Growth data is not canonical JSON.") from exc


def _exact_mapping(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilityGrowthValidationError(f"{label} has unknown or missing fields.")
    return value


def _settings(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA secure_delete=ON")
    connection.execute("PRAGMA journal_mode=DELETE")
