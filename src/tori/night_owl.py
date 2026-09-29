"""Default-Off, offline Night Owl authority and findings foundation.

This module deliberately has no network, model, scheduler, capability-growth,
or Companion Initiative dependency.  It persists only bounded, application
validated research state for later slices.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from urllib.parse import quote, urlsplit, urlunsplit

SCHEMA_VERSION = 3
DEFAULT_STORE_PATH = Path("runtime/night_owl/tori_night_owl.db")
SOURCE_POLICY_VERSION = "night_owl_v1"
BUDGET_POLICY_VERSION = "night_owl_budgets_v2_depth"
CATEGORIES = {
    "local_models": "Local models",
    "voice": "Voice / TTS / STT",
    "image_generation": "Image generation",
    "coding_agents": "Coding and agent tooling",
    "mcp_infrastructure": "MCP infrastructure",
    "skills_tori_tools": "Skills and Tori-relevant tools",
    "security": "Security intelligence",
}
SOURCE_KINDS = frozenset({"searxng_discovery", "skills_sh", "github_api", "github_page", "security_advisory"})
RUN_STATES = frozenset({"pending", "running", "completed", "partial", "failed", "interrupted", "skipped"})
TERMINAL_RUN_STATES = RUN_STATES - {"pending", "running"}
FINDING_STATES = frozenset({"new", "seen", "dismissed", "stale", "superseded"})
MAX_SOURCES_PER_VERSION = 3
DEFAULT_BUDGETS = {
    "searches": 18, "search_results": 72, "github_fetches": 24,
    "skills_inspections": 6, "model_calls": 6, "model_input_tokens": 32000,
    "model_output_tokens": 8000, "retrieved_characters": 192000,
    "new_findings": 5, "capability_growth_promotions": 3,
    "run_seconds": 600, "active_runs": 1, "retained_runs": 50,
    "retained_findings": 250, "versions_per_finding": 5,
    "sources_per_version": 3,
}


def budgets_for_categories(categories: Sequence[str]) -> dict[str, int]:
    """Return the versioned, category-scaled V1 depth profile.

    The profile is application-owned: callers cannot choose a larger budget or
    trade one category's research allowance for another's.
    """
    selected = tuple(categories)
    if tuple(sorted(set(selected))) != selected or any(item not in CATEGORIES for item in selected):
        raise NightOwlValidationError("Night Owl categories are invalid.")
    count = len(selected)
    return {
        **DEFAULT_BUDGETS,
        "searches": 3 * count,
        "search_results": 12 * count,
        "github_fetches": 4 * count,
        "skills_inspections": 6 if "skills_tori_tools" in selected else 0,
    }
_ID = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")
_RUN_ID = re.compile(r"run-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")

_SCHEMA_V1 = {
    ("table", "night_owl_metadata"): "CREATE TABLE night_owl_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    ("table", "night_owl_settings"): "CREATE TABLE night_owl_settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL CHECK(revision>=1),enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),paused INTEGER NOT NULL CHECK(paused IN (0,1)),categories_json TEXT NOT NULL,source_policy_version TEXT NOT NULL,budgets_json TEXT NOT NULL,updated_at_utc TEXT NOT NULL)",
    ("table", "night_owl_grants"): "CREATE TABLE night_owl_grants (id TEXT PRIMARY KEY,settings_revision INTEGER NOT NULL,category_json TEXT NOT NULL,source_policy_version TEXT NOT NULL,budgets_json TEXT NOT NULL,digest TEXT NOT NULL UNIQUE,status TEXT NOT NULL CHECK(status IN ('active','revoked')),created_at_utc TEXT NOT NULL,revoked_at_utc TEXT)",
    ("table", "night_owl_runs"): "CREATE TABLE night_owl_runs (id TEXT PRIMARY KEY,trigger TEXT NOT NULL CHECK(trigger IN ('manual','scheduled')),grant_id TEXT NOT NULL,grant_revision INTEGER NOT NULL,grant_digest TEXT NOT NULL,category_json TEXT NOT NULL,source_policy_version TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','running','completed','partial','failed','interrupted','skipped')),revision INTEGER NOT NULL CHECK(revision>=1),budget_used_json TEXT NOT NULL,error_codes_json TEXT NOT NULL,created_at_utc TEXT NOT NULL,started_at_utc TEXT,ended_at_utc TEXT,FOREIGN KEY(grant_id) REFERENCES night_owl_grants(id))",
    ("table", "night_owl_findings"): "CREATE TABLE night_owl_findings (id TEXT PRIMARY KEY,identity_key TEXT NOT NULL UNIQUE,category TEXT NOT NULL,source_identity TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,relevance_json TEXT NOT NULL,risks_json TEXT NOT NULL,unknowns_json TEXT NOT NULL,next_step TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('new','seen','dismissed','stale','superseded')),current_fingerprint TEXT NOT NULL,revision INTEGER NOT NULL CHECK(revision>=1),first_seen_at_utc TEXT NOT NULL,last_seen_at_utc TEXT NOT NULL)",
    ("table", "night_owl_finding_versions"): "CREATE TABLE night_owl_finding_versions (id TEXT PRIMARY KEY,finding_id TEXT NOT NULL,material_fingerprint TEXT NOT NULL,version_identity TEXT NOT NULL,change_reason TEXT NOT NULL,first_seen_at_utc TEXT NOT NULL,last_seen_at_utc TEXT NOT NULL,observation_count INTEGER NOT NULL CHECK(observation_count>=1),surfaced INTEGER NOT NULL CHECK(surfaced IN (0,1)),UNIQUE(finding_id,material_fingerprint),FOREIGN KEY(finding_id) REFERENCES night_owl_findings(id) ON DELETE CASCADE)",
    ("table", "night_owl_sources"): "CREATE TABLE night_owl_sources (id TEXT PRIMARY KEY,version_id TEXT NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,title TEXT NOT NULL,stable_identity TEXT NOT NULL,immutable_identity TEXT,evidence_level TEXT NOT NULL,observed_at_utc TEXT NOT NULL,UNIQUE(version_id,url),FOREIGN KEY(version_id) REFERENCES night_owl_finding_versions(id) ON DELETE CASCADE)",
    ("index", "night_owl_runs_state"): "CREATE INDEX night_owl_runs_state ON night_owl_runs(state,created_at_utc)",
    ("index", "night_owl_findings_state"): "CREATE INDEX night_owl_findings_state ON night_owl_findings(state,last_seen_at_utc)",
    ("index", "night_owl_versions_finding"): "CREATE INDEX night_owl_versions_finding ON night_owl_finding_versions(finding_id,last_seen_at_utc)",
}
_SCHEMA = {
    **_SCHEMA_V1,
    ("table", "night_owl_run_findings"): "CREATE TABLE night_owl_run_findings (run_id TEXT NOT NULL,version_id TEXT NOT NULL,materially_changed INTEGER NOT NULL CHECK(materially_changed IN (0,1)),PRIMARY KEY(run_id,version_id),FOREIGN KEY(run_id) REFERENCES night_owl_runs(id) ON DELETE CASCADE,FOREIGN KEY(version_id) REFERENCES night_owl_finding_versions(id) ON DELETE CASCADE)",
    ("table", "night_owl_enrichments"): "CREATE TABLE night_owl_enrichments (version_id TEXT PRIMARY KEY,summary TEXT NOT NULL,why_it_matters TEXT NOT NULL,risks_json TEXT NOT NULL,unknowns_json TEXT NOT NULL,next_step TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,input_digest TEXT NOT NULL,prompt_version TEXT NOT NULL,created_at_utc TEXT NOT NULL,FOREIGN KEY(version_id) REFERENCES night_owl_finding_versions(id) ON DELETE CASCADE)",
    ("table", "night_owl_promotions"): "CREATE TABLE night_owl_promotions (run_id TEXT NOT NULL,finding_id TEXT NOT NULL,version_id TEXT NOT NULL,recommendation_id TEXT NOT NULL,created_at_utc TEXT NOT NULL,PRIMARY KEY(run_id,finding_id),FOREIGN KEY(run_id) REFERENCES night_owl_runs(id) ON DELETE CASCADE,FOREIGN KEY(finding_id) REFERENCES night_owl_findings(id) ON DELETE CASCADE,FOREIGN KEY(version_id) REFERENCES night_owl_finding_versions(id) ON DELETE CASCADE)",
    ("index", "night_owl_run_findings_version"): "CREATE INDEX night_owl_run_findings_version ON night_owl_run_findings(version_id,run_id)",
}
_SCHEMA_V2 = _SCHEMA
_SCHEMA = {
    **_SCHEMA_V2,
    ("table", "night_owl_run_metrics"): "CREATE TABLE night_owl_run_metrics (run_id TEXT PRIMARY KEY,aggregate_json TEXT NOT NULL,categories_json TEXT NOT NULL,duration_millis INTEGER NOT NULL CHECK(duration_millis>=0),FOREIGN KEY(run_id) REFERENCES night_owl_runs(id) ON DELETE CASCADE)",
}

class NightOwlError(RuntimeError): code = "night_owl_failed"
class NightOwlValidationError(NightOwlError): code = "night_owl_invalid"
class NightOwlUnavailableError(NightOwlError): code = "night_owl_unavailable"
class NightOwlCorruptError(NightOwlError): code = "night_owl_corrupt"
class NightOwlConflictError(NightOwlError): code = "night_owl_conflict"

@dataclass(frozen=True, slots=True)
class NightOwlSettings:
    revision: int = 0
    enabled: bool = False
    paused: bool = False
    categories: tuple[str, ...] = ()
    source_policy_version: str = SOURCE_POLICY_VERSION
    budgets: tuple[tuple[str, int], ...] = tuple(DEFAULT_BUDGETS.items())

@dataclass(frozen=True, slots=True)
class ResearchGrant:
    identifier: str; revision: int; categories: tuple[str, ...]; source_policy_version: str
    budgets: tuple[tuple[str, int], ...]; digest: str; status: str

@dataclass(frozen=True, slots=True)
class NightOwlRun:
    identifier: str; trigger: str; grant_id: str; grant_revision: int; grant_digest: str
    categories: tuple[str, ...]; source_policy_version: str; state: str; revision: int
    budget_used: tuple[tuple[str, int], ...]; error_codes: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class NightOwlRunDetail:
    run: NightOwlRun
    created_at: str
    started_at: str | None
    ended_at: str | None
    metrics: "NightOwlRunMetrics | None" = None

@dataclass(frozen=True, slots=True)
class NightOwlRunMetrics:
    """Sanitized durable diagnostics for a single bounded research run."""
    aggregate: tuple[tuple[str, int], ...]
    categories: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    duration_millis: int

@dataclass(frozen=True, slots=True)
class SourceAttribution:
    kind: str; url: str; title: str; stable_identity: str; immutable_identity: str | None = None; evidence_level: str = "corroborated"

@dataclass(frozen=True, slots=True)
class FindingDraft:
    category: str; source_identity: str; finding_kind: str; title: str; summary: str
    relevance_reasons: tuple[str, ...]; risks: tuple[str, ...]; unknowns: tuple[str, ...]
    next_step: str; material_fingerprint: str; version_identity: str; change_reason: str
    sources: tuple[SourceAttribution, ...]

@dataclass(frozen=True, slots=True)
class Finding:
    identifier: str; identity_key: str; category: str; source_identity: str; state: str
    current_fingerprint: str; revision: int

@dataclass(frozen=True, slots=True)
class FindingVersion:
    identifier: str; finding_id: str; material_fingerprint: str; version_identity: str
    change_reason: str; first_seen_at: str; last_seen_at: str
    observation_count: int; surfaced: bool

@dataclass(frozen=True, slots=True)
class FindingDetail:
    identifier: str; identity_key: str; category: str; source_identity: str
    title: str; summary: str; relevance_reasons: tuple[str, ...]
    risks: tuple[str, ...]; unknowns: tuple[str, ...]; next_step: str
    state: str; current_fingerprint: str; revision: int
    first_seen_at: str; last_seen_at: str

@dataclass(frozen=True, slots=True)
class FindingEnrichment:
    version_id: str; summary: str; why_it_matters: str; risks: tuple[str, ...]
    unknowns: tuple[str, ...]; next_step: str; provider: str; model: str
    input_digest: str; prompt_version: str; created_at: str | None = None

@dataclass(frozen=True, slots=True)
class AttentionCohort:
    count: int; digest: str; oldest_at: str; newest_at: str

@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    run_id: str; finding_id: str; version_id: str; recommendation_id: str
    created_at: str

def source_policy_allows(kind: str, url: str, *, authenticated: bool = False, private: bool = False, binary: bool = False, proxy_credentials: bool = False) -> bool:
    """Validate only the fixed V1 source families; it performs no I/O."""
    if kind not in SOURCE_KINDS or any((authenticated, private, binary, proxy_credentials)): return False
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError: return False
    if p.username or p.password or p.scheme != "https" or port not in {None, 443} or p.query or p.fragment: return False
    host = (p.hostname or "").lower(); path = p.path
    if any(part in {".", ".."} for part in path.split("/")) or "//" in path: return False
    if kind == "skills_sh": return host == "skills.sh" and path == "/api/search"
    if kind == "github_api": return host == "api.github.com" and bool(re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/(?:releases(?:/(?:latest|[0-9]+))?|commits/[A-Za-z0-9._/-]{1,200}|git/(?:trees|blobs)/[0-9a-f]{7,64}))?", path))
    if kind == "github_page": return host == "github.com" and bool(re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", path))
    if kind == "security_advisory":
        return bool(
            (host == "ubuntu.com" and re.fullmatch(r"/security/notices/USN-\d+-\d+/?", path))
            or (host == "www.nvidia.com" and path not in {"/en-us/security/archive/", "/en-us/security/archive"}
                and re.fullmatch(r"/en-us/security/[a-zA-Z0-9._/-]{1,180}/?", path))
            or (host == "nvidia.custhelp.com" and re.fullmatch(
                r"/app/answers/detail/a_id/[1-9]\d{2,6}/~/security-bulletin(?::|%3[Aa])[-a-z0-9]{1,140}/?", path))
            or (host == "www.cisa.gov" and (
                path == "/known-exploited-vulnerabilities-catalog"
                or re.fullmatch(r"/news-events/(?:alerts|cybersecurity-advisories)/(?:20\d\d/(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/)?[a-z0-9-]{1,180}/?", path)
            ))
            or (host == "www.mozilla.org" and re.fullmatch(r"/en-US/security/advisories/mfsa\d{4}-\d+/?", path))
        )
    return kind == "searxng_discovery" and host in {"127.0.0.1", "localhost"} and path.endswith("/search")

def canonical_source_identity(value: str) -> str:
    """Canonicalize GitHub subjects and public URL source identity deterministically."""
    if not isinstance(value, str) or len(value) > 1000: raise NightOwlValidationError("Source identity is invalid.")
    raw = value.strip()
    if raw.startswith("github:"):
        subject = raw[7:].removesuffix(".git").lower().strip("/")
        if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", subject): raise NightOwlValidationError("GitHub identity is invalid.")
        return "github:" + subject
    p = urlsplit(raw)
    if p.scheme != "https" or not p.hostname or p.username or p.password: raise NightOwlValidationError("Source identity is invalid.")
    return urlunsplit(("https", p.hostname.lower(), p.path.rstrip("/") or "/", "", ""))

def finding_identity(category: str, source_identity: str, finding_kind: str) -> str:
    _category(category); _short(finding_kind, 64, "Finding kind")
    material = "\x1f".join((category, canonical_source_identity(source_identity), finding_kind))
    return hashlib.sha256(material.encode()).hexdigest()

def relevance_score(reasons: Sequence[str]) -> int:
    allowed = {"category_match", "local_self_hosted", "protocol_fit", "tori_subsystem_fit", "capability_gap", "operational_friction", "meaningful_improvement", "watch_ubuntu", "watch_linux", "watch_nvidia", "watch_ssh", "watch_firefox", "watch_python", "watch_ollama", "security_general", "kev_listed"}
    values = tuple(reasons)
    if not values or len(values) > len(allowed) or any(item not in allowed for item in values): raise NightOwlValidationError("Relevance reasons are invalid.")
    return len(set(values))

class SQLiteNightOwlStore:
    def __init__(self, path: Path = DEFAULT_STORE_PATH, *, clock=lambda: datetime.now(timezone.utc), token_hex=secrets.token_hex) -> None:
        self._path, self._clock, self._token_hex, self._lock = Path(path), clock, token_hex, threading.RLock()
    @property
    def path(self) -> Path: return self._path
    @property
    def exists(self) -> bool: return self._safe_path(False) is not None
    def settings(self) -> NightOwlSettings:
        if not self.exists: return NightOwlSettings()
        with self._reader() as c:
            row = c.execute("SELECT revision,enabled,paused,categories_json,source_policy_version,budgets_json FROM night_owl_settings WHERE singleton=1").fetchone()
        if row is None: raise NightOwlCorruptError("Night Owl settings are missing.")
        return _settings(row)
    def active_grant(self) -> ResearchGrant | None:
        if not self.exists: return None
        with self._reader() as c:
            row = c.execute("SELECT id,settings_revision,category_json,source_policy_version,budgets_json,digest,status FROM night_owl_grants WHERE status='active'").fetchone()
        return None if row is None else _grant(row)
    def save_settings(self, value: NightOwlSettings, *, expected_revision: int) -> NightOwlSettings:
        if isinstance(value, NightOwlSettings):
            value = replace(
                value, budgets=tuple(budgets_for_categories(value.categories).items())
            )
        _validate_settings(value)
        if type(expected_revision) is not int or expected_revision < 0: raise NightOwlValidationError("Settings revision is invalid.")
        now = _stamp(self._clock())
        with self._lock:
            if not self.exists: self._initialize(value, now); return self.settings()
            c = self._connect(False)
            try:
                with c:
                    current = _settings(c.execute("SELECT revision,enabled,paused,categories_json,source_policy_version,budgets_json FROM night_owl_settings WHERE singleton=1").fetchone())
                    if current.revision != expected_revision: raise NightOwlConflictError("Night Owl settings changed.")
                    c.execute("UPDATE night_owl_grants SET status='revoked',revoked_at_utc=? WHERE status='active'", (now,))
                    revision = current.revision + 1
                    c.execute("UPDATE night_owl_settings SET revision=?,enabled=?,paused=?,categories_json=?,source_policy_version=?,budgets_json=?,updated_at_utc=? WHERE singleton=1", (revision, int(value.enabled), int(value.paused), _json(value.categories), value.source_policy_version, _json(dict(value.budgets)), now))
                    if value.enabled and not value.paused:
                        self._insert_grant(c, revision, value, now)
            finally: c.close()
        return self.settings()
    def verify_grant(self, grant_id: str, *, revision: int, digest: str, category: str, source_policy_version: str) -> ResearchGrant:
        _category(category)
        grant = self.active_grant()
        settings = self.settings()
        if grant is None or not settings.enabled or settings.paused or grant.identifier != grant_id or grant.revision != revision or grant.digest != digest or grant.source_policy_version != source_policy_version or category not in grant.categories: raise NightOwlConflictError("Night Owl research authority is inactive or changed.")
        return grant
    def create_run(self, *, trigger: str, grant: ResearchGrant, invocation_id: str | None = None) -> NightOwlRun:
        if trigger not in {"manual", "scheduled"}: raise NightOwlValidationError("Run trigger is invalid.")
        if invocation_id is not None and (trigger != "scheduled" or not isinstance(invocation_id, str) or _RUN_ID.fullmatch(invocation_id) is None): raise NightOwlValidationError("Run invocation identity is invalid.")
        self.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category=grant.categories[0], source_policy_version=grant.source_policy_version)
        now = _stamp(self._clock()); identifier = invocation_id or "run-" + self._token_hex(16)
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    if c.execute("SELECT COUNT(*) FROM night_owl_runs WHERE state IN ('pending','running')").fetchone()[0]: raise NightOwlConflictError("A Night Owl run is already active.")
                    c.execute("INSERT INTO night_owl_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier,trigger,grant.identifier,grant.revision,grant.digest,_json(grant.categories),grant.source_policy_version,"pending",1,_json({}),_json([]),now,None,None))
            finally: c.close()
        return self.get_run(identifier)
    def record_skipped_run(self, *, trigger: str, grant: ResearchGrant, error_code: str, invocation_id: str | None = None) -> NightOwlRun:
        if trigger not in {"manual", "scheduled"}: raise NightOwlValidationError("Run trigger is invalid.")
        if invocation_id is not None and (trigger != "scheduled" or not isinstance(invocation_id, str) or _RUN_ID.fullmatch(invocation_id) is None): raise NightOwlValidationError("Run invocation identity is invalid.")
        if not isinstance(error_code, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", error_code): raise NightOwlValidationError("Run error code is invalid.")
        for category in grant.categories:
            self.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category=category, source_policy_version=grant.source_policy_version)
        now = _stamp(self._clock()); identifier = invocation_id or "run-" + self._token_hex(16)
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    c.execute("INSERT INTO night_owl_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (identifier,trigger,grant.identifier,grant.revision,grant.digest,_json(grant.categories),grant.source_policy_version,"skipped",1,_json({}),_json([error_code]),now,None,now))
            finally: c.close()
        return self.get_run(identifier)
    def get_run(self, identifier: str) -> NightOwlRun:
        with self._reader() as c: row=c.execute("SELECT id,trigger,grant_id,grant_revision,grant_digest,category_json,source_policy_version,state,revision,budget_used_json,error_codes_json FROM night_owl_runs WHERE id=?",(identifier,)).fetchone()
        if row is None: raise NightOwlConflictError("Night Owl run was not found.")
        return _run(row)
    def list_runs(self, *, limit: int = 10) -> tuple[NightOwlRunDetail, ...]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise NightOwlValidationError("Night Owl run limit is invalid.")
        if not self.exists:
            return ()
        with self._reader() as c:
            rows = c.execute(
                "SELECT id,trigger,grant_id,grant_revision,grant_digest,category_json,"
                "source_policy_version,state,revision,budget_used_json,error_codes_json,"
                "created_at_utc,started_at_utc,ended_at_utc FROM night_owl_runs "
                "ORDER BY created_at_utc DESC,id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(
            NightOwlRunDetail(
                _run(row[:11]), str(row[11]), row[12], row[13],
                self.run_metrics(str(row[0])),
            )
            for row in rows
        )
    def active_run(self) -> NightOwlRunDetail | None:
        if not self.exists:
            return None
        with self._reader() as c:
            row = c.execute(
                "SELECT id,trigger,grant_id,grant_revision,grant_digest,category_json,"
                "source_policy_version,state,revision,budget_used_json,error_codes_json,"
                "created_at_utc,started_at_utc,ended_at_utc FROM night_owl_runs "
                "WHERE state IN ('pending','running') ORDER BY created_at_utc,id LIMIT 1"
            ).fetchone()
        return None if row is None else NightOwlRunDetail(
            _run(row[:11]), str(row[11]), row[12], row[13],
            self.run_metrics(str(row[0])),
        )
    def record_run_metrics(
        self, identifier: str, *, aggregate: dict[str, int],
        categories: dict[str, dict[str, int]], duration_millis: int,
    ) -> NightOwlRunMetrics:
        """Persist bounded counters, never queries, URLs, snippets, or content."""
        metrics = _metrics(aggregate, categories, duration_millis)
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    row = c.execute(
                        "SELECT state FROM night_owl_runs WHERE id=?", (identifier,)
                    ).fetchone()
                    if row is None or row[0] not in TERMINAL_RUN_STATES:
                        raise NightOwlConflictError("Night Owl run metrics require a terminal run.")
                    c.execute(
                        "INSERT OR REPLACE INTO night_owl_run_metrics VALUES (?,?,?,?)",
                        (identifier, _json(dict(metrics.aggregate)),
                         _json({key: dict(values) for key, values in metrics.categories}),
                         metrics.duration_millis),
                    )
            finally:
                c.close()
        return self.run_metrics(identifier) or metrics
    def run_metrics(self, identifier: str) -> NightOwlRunMetrics | None:
        if not self.exists:
            return None
        with self._reader() as c:
            row = c.execute(
                "SELECT aggregate_json,categories_json,duration_millis "
                "FROM night_owl_run_metrics WHERE run_id=?", (identifier,)
            ).fetchone()
        if row is None:
            return None
        try:
            return _metrics(json.loads(row[0]), json.loads(row[1]), int(row[2]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise NightOwlCorruptError("Night Owl run metrics are invalid.") from exc
    def transition_run(self, identifier: str, state: str, *, expected_revision: int, budget_used: dict[str,int] | None=None, error_codes: Sequence[str]=()) -> NightOwlRun:
        if state not in RUN_STATES or type(expected_revision) is not int or expected_revision < 1: raise NightOwlValidationError("Run transition is invalid.")
        errors=tuple(error_codes)
        if any(not isinstance(x,str) or not re.fullmatch(r"[a-z0-9_]{1,64}",x) for x in errors): raise NightOwlValidationError("Run error code is invalid.")
        with self._lock:
            c=self._connect(False)
            try:
                with c:
                    run=self.get_run(identifier)
                    _budget_usage(budget_used or {}, budgets_for_categories(run.categories))
                    allowed={"pending":{"running","skipped","failed","interrupted"},"running":set(TERMINAL_RUN_STATES)}
                    if run.revision!=expected_revision or state not in allowed.get(run.state,set()): raise NightOwlConflictError("Night Owl run changed or cannot transition.")
                    now=_stamp(self._clock()); c.execute("UPDATE night_owl_runs SET state=?,revision=revision+1,budget_used_json=?,error_codes_json=?,started_at_utc=CASE WHEN ?='running' THEN ? ELSE started_at_utc END,ended_at_utc=CASE WHEN ? IN ('completed','partial','failed','interrupted','skipped') THEN ? ELSE NULL END WHERE id=? AND revision=?",(state,_json(budget_used or {}),_json(errors),state,now,state,now,identifier,expected_revision))
            finally: c.close()
        return self.get_run(identifier)
    def recover_startup(self) -> tuple[NightOwlRun,...]:
        if not self.exists: return ()
        with self._lock:
            c=self._connect(False)
            try:
                with c:
                    rows=c.execute("SELECT id,revision FROM night_owl_runs WHERE state IN ('pending','running')").fetchall()
                    for identifier, revision in rows: c.execute("UPDATE night_owl_runs SET state='interrupted',revision=revision+1,ended_at_utc=?,error_codes_json=? WHERE id=? AND revision=?",(_stamp(self._clock()),_json(["shutdown_interrupted"]),identifier,revision))
            finally:c.close()
        return tuple(self.get_run(row[0]) for row in rows)
    def record_finding(
        self, draft: FindingDraft, *, run_id: str | None = None
    ) -> tuple[Finding,bool]:
        _draft(draft); now=_stamp(self._clock()); key=finding_identity(draft.category,draft.source_identity,draft.finding_kind)
        if run_id is not None and (not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None):
            raise NightOwlValidationError("Finding run identity is invalid.")
        with self._lock:
            c=self._connect(False)
            try:
                with c:
                    if run_id is not None:
                        run_row = c.execute(
                            "SELECT state FROM night_owl_runs WHERE id=?", (run_id,)
                        ).fetchone()
                        if run_row is None or run_row[0] != "running":
                            raise NightOwlConflictError("Finding run is not active.")
                    row=c.execute("SELECT id,current_fingerprint,state,revision FROM night_owl_findings WHERE identity_key=?",(key,)).fetchone()
                    if row is None:
                        self._reserve(c,"night_owl_findings",DEFAULT_BUDGETS["retained_findings"]); fid="finding-"+self._token_hex(16)
                        c.execute("INSERT INTO night_owl_findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(fid,key,draft.category,canonical_source_identity(draft.source_identity),_bounded(draft.title,200),_bounded(draft.summary,1000),_json(draft.relevance_reasons),_json(draft.risks),_json(draft.unknowns),_bounded(draft.next_step,500),"new",draft.material_fingerprint,1,now,now)); changed=True
                    else:
                        fid, old, oldstate, rev=row; changed=old!=draft.material_fingerprint; state="new" if changed else oldstate
                        if changed:
                            c.execute(
                                "UPDATE night_owl_findings SET title=?,summary=?,relevance_json=?,"
                                "risks_json=?,unknowns_json=?,next_step=?,current_fingerprint=?,"
                                "state=?,revision=revision+1,last_seen_at_utc=? WHERE id=?",
                                (
                                    _bounded(draft.title,200), _bounded(draft.summary,1000),
                                    _json(draft.relevance_reasons), _json(draft.risks),
                                    _json(draft.unknowns), _bounded(draft.next_step,500),
                                    draft.material_fingerprint, state, now, fid,
                                ),
                            )
                        else:
                            # A repeated observation is not a material source
                            # change, but it may carry better bounded display
                            # metadata (for example a repository description
                            # that was unavailable when the finding was first
                            # recorded).  Refresh that presentation data
                            # without creating a material version or resetting
                            # the user's review state.
                            c.execute(
                                "UPDATE night_owl_findings SET title=?,summary=?,relevance_json=?,"
                                "risks_json=?,unknowns_json=?,next_step=?,current_fingerprint=?,"
                                "state=?,revision=revision+1,last_seen_at_utc=? WHERE id=?",
                                (
                                    _bounded(draft.title,200), _bounded(draft.summary,1000),
                                    _json(draft.relevance_reasons), _json(draft.risks),
                                    _json(draft.unknowns), _bounded(draft.next_step,500),
                                    draft.material_fingerprint, state, now, fid,
                                ),
                            )
                    version=c.execute("SELECT id,observation_count FROM night_owl_finding_versions WHERE finding_id=? AND material_fingerprint=?",(fid,draft.material_fingerprint)).fetchone()
                    if version is None:
                        self._reserve_versions(c,fid); vid="version-"+self._token_hex(16); c.execute("INSERT INTO night_owl_finding_versions VALUES (?,?,?,?,?,?,?,?,?)",(vid,fid,draft.material_fingerprint,draft.version_identity,draft.change_reason,now,now,1,0)); self._sources(c,vid,draft.sources,now)
                    else:
                        vid = version[0]
                        c.execute("UPDATE night_owl_finding_versions SET last_seen_at_utc=?,observation_count=observation_count+1 WHERE id=?",(now,vid))
                    if run_id is not None:
                        c.execute(
                            "INSERT OR IGNORE INTO night_owl_run_findings VALUES (?,?,?)",
                            (run_id, vid, int(changed)),
                        )
            finally:c.close()
        return self.get_finding(key),changed
    def withdraw_finding(
        self, category: str, source_identity: str, finding_kind: str,
    ) -> Finding | None:
        """Keep a historically recorded finding but remove it from active review.

        This is only called after the same source has been inspected again and
        fails the *current* deterministic relevance policy.  It is neither a
        user dismissal nor a retroactive policy sweep.
        """

        key = finding_identity(category, source_identity, finding_kind)
        now = _stamp(self._clock())
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    row = c.execute(
                        "SELECT id,state FROM night_owl_findings WHERE identity_key=?", (key,)
                    ).fetchone()
                    if row is None:
                        return None
                    identifier, state = str(row[0]), str(row[1])
                    if state != "dismissed":
                        c.execute(
                            "UPDATE night_owl_findings SET state='stale',revision=revision+1,"
                            "last_seen_at_utc=? WHERE id=? AND state<> 'stale'", (now, identifier,)
                        )
            finally:
                c.close()
        return self.get_finding(key)
    def get_finding(self, identity_key: str) -> Finding:
        with self._reader() as c: row=c.execute("SELECT id,identity_key,category,source_identity,state,current_fingerprint,revision FROM night_owl_findings WHERE identity_key=?",(identity_key,)).fetchone()
        if row is None: raise NightOwlConflictError("Night Owl finding was not found.")
        return Finding(*row)
    def mark_finding(self, identity_key: str, state: str, *, expected_revision: int) -> Finding:
        if state not in {"seen","dismissed"}: raise NightOwlValidationError("Finding state is invalid.")
        with self._lock:
            c=self._connect(False)
            try:
                with c:
                    item=self.get_finding(identity_key)
                    if item.revision!=expected_revision: raise NightOwlConflictError("Night Owl finding changed.")
                    c.execute("UPDATE night_owl_findings SET state=?,revision=revision+1 WHERE identity_key=? AND revision=?",(state,identity_key,expected_revision))
            finally:c.close()
        return self.get_finding(identity_key)
    def get_finding_detail(self, identifier: str) -> FindingDetail:
        if not isinstance(identifier, str):
            raise NightOwlValidationError("Finding identifier is invalid.")
        with self._reader() as c:
            row = c.execute(
                "SELECT id,identity_key,category,source_identity,title,summary,relevance_json,"
                "risks_json,unknowns_json,next_step,state,current_fingerprint,revision,"
                "first_seen_at_utc,last_seen_at_utc FROM night_owl_findings "
                "WHERE id=? OR identity_key=?", (identifier, identifier)
            ).fetchone()
        if row is None:
            raise NightOwlConflictError("Night Owl finding was not found.")
        return FindingDetail(
            str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
            str(row[5]), tuple(json.loads(row[6])), tuple(json.loads(row[7])),
            tuple(json.loads(row[8])), str(row[9]), str(row[10]), str(row[11]),
            int(row[12]), str(row[13]), str(row[14]),
        )
    def list_finding_details(self, *, limit: int = 50) -> tuple[FindingDetail, ...]:
        if type(limit) is not int or not 1 <= limit <= 250:
            raise NightOwlValidationError("Night Owl finding limit is invalid.")
        if not self.exists:
            return ()
        with self._reader() as c:
            rows = c.execute(
                "SELECT id,identity_key,category,source_identity,title,summary,relevance_json,"
                "risks_json,unknowns_json,next_step,state,current_fingerprint,revision,"
                "first_seen_at_utc,last_seen_at_utc FROM night_owl_findings "
                "ORDER BY last_seen_at_utc DESC,id DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(
            FindingDetail(
                str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
                str(row[5]), tuple(json.loads(row[6])), tuple(json.loads(row[7])),
                tuple(json.loads(row[8])), str(row[9]), str(row[10]), str(row[11]),
                int(row[12]), str(row[13]), str(row[14]),
            )
            for row in rows
        )
    def current_version(self, finding_id: str) -> FindingVersion:
        with self._reader() as c:
            row = c.execute(
                "SELECT v.id,v.finding_id,v.material_fingerprint,v.version_identity,"
                "v.change_reason,v.first_seen_at_utc,v.last_seen_at_utc,"
                "v.observation_count,v.surfaced FROM night_owl_finding_versions v "
                "JOIN night_owl_findings f ON f.id=v.finding_id "
                "AND f.current_fingerprint=v.material_fingerprint WHERE f.id=?",
                (finding_id,),
            ).fetchone()
        if row is None:
            raise NightOwlConflictError("Night Owl finding version was not found.")
        return FindingVersion(*row[:8], bool(row[8]))
    def sources_for_version(self, version_id: str) -> tuple[SourceAttribution, ...]:
        with self._reader() as c:
            rows = c.execute(
                "SELECT kind,url,title,stable_identity,immutable_identity,evidence_level "
                "FROM night_owl_sources WHERE version_id=? ORDER BY id", (version_id,)
            ).fetchall()
        return tuple(SourceAttribution(*row) for row in rows)
    def run_observed_version(self, run_id: str, version_id: str) -> bool:
        with self._reader() as c:
            row = c.execute(
                "SELECT 1 FROM night_owl_run_findings WHERE run_id=? AND version_id=?",
                (run_id, version_id),
            ).fetchone()
        return row is not None
    def latest_run_for_version(self, version_id: str) -> NightOwlRun | None:
        if not self.exists:
            return None
        with self._reader() as c:
            row = c.execute(
                "SELECT r.id,r.trigger,r.grant_id,r.grant_revision,r.grant_digest,"
                "r.category_json,r.source_policy_version,r.state,r.revision,"
                "r.budget_used_json,r.error_codes_json FROM night_owl_runs r "
                "JOIN night_owl_run_findings rf ON rf.run_id=r.id "
                "WHERE rf.version_id=? AND r.state IN ('completed','partial') "
                "ORDER BY r.ended_at_utc DESC,r.id DESC LIMIT 1", (version_id,)
            ).fetchone()
        return None if row is None else _run(row)
    def record_enrichment(
        self, version_id: str, enrichment: FindingEnrichment
    ) -> FindingEnrichment:
        if not isinstance(enrichment, FindingEnrichment) or enrichment.version_id != version_id:
            raise NightOwlValidationError("Finding enrichment is invalid.")
        enrichment = replace(enrichment, created_at=_stamp(self._clock()))
        _enrichment(enrichment)
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    if c.execute(
                        "SELECT 1 FROM night_owl_finding_versions WHERE id=?", (version_id,)
                    ).fetchone() is None:
                        raise NightOwlConflictError("Night Owl finding version was not found.")
                    c.execute(
                        "INSERT OR IGNORE INTO night_owl_enrichments VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            version_id, enrichment.summary, enrichment.why_it_matters,
                            _json(enrichment.risks), _json(enrichment.unknowns),
                            enrichment.next_step, enrichment.provider, enrichment.model,
                            enrichment.input_digest, enrichment.prompt_version,
                            enrichment.created_at,
                        ),
                    )
            finally:
                c.close()
        return self.get_enrichment(version_id)
    def get_enrichment(self, version_id: str) -> FindingEnrichment:
        with self._reader() as c:
            row = c.execute(
                "SELECT version_id,summary,why_it_matters,risks_json,unknowns_json,"
                "next_step,provider,model,input_digest,prompt_version,created_at_utc "
                "FROM night_owl_enrichments WHERE version_id=?", (version_id,)
            ).fetchone()
        if row is None:
            raise NightOwlConflictError("Night Owl finding enrichment was not found.")
        return FindingEnrichment(
            str(row[0]), str(row[1]), str(row[2]), tuple(json.loads(row[3])),
            tuple(json.loads(row[4])), str(row[5]), str(row[6]), str(row[7]),
            str(row[8]), str(row[9]), str(row[10]),
        )
    def attention_cohort(self, *, count_cap: int = 9) -> AttentionCohort | None:
        if type(count_cap) is not int or not 1 <= count_cap <= 99:
            raise NightOwlValidationError("Attention count cap is invalid.")
        if not self.exists:
            return None
        with self._reader() as c:
            rows = c.execute(
                "SELECT f.id,v.id,v.material_fingerprint,v.first_seen_at_utc "
                "FROM night_owl_findings f JOIN night_owl_finding_versions v "
                "ON v.finding_id=f.id AND v.material_fingerprint=f.current_fingerprint "
                "WHERE f.state='new' AND f.category<>'security' ORDER BY v.first_seen_at_utc,v.id"
            ).fetchall()
        if not rows:
            return None
        digest = hashlib.sha256(_json([(row[0], row[1], row[2]) for row in rows]).encode()).hexdigest()
        return AttentionCohort(min(len(rows), count_cap), digest, str(rows[0][3]), str(rows[-1][3]))
    def promotion_count(self, run_id: str) -> int:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise NightOwlValidationError("Promotion run identity is invalid.")
        with self._reader() as c:
            return int(c.execute(
                "SELECT COUNT(*) FROM night_owl_promotions WHERE run_id=?", (run_id,)
            ).fetchone()[0])
    def record_promotion(
        self, *, run_id: str, finding_id: str, version_id: str,
        recommendation_id: str,
    ) -> None:
        if (
            not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None
            or not isinstance(finding_id, str)
            or re.fullmatch(r"finding-[0-9a-f]{32}", finding_id) is None
            or not isinstance(version_id, str)
            or re.fullmatch(r"version-[0-9a-f]{32}", version_id) is None
            or not isinstance(recommendation_id, str)
            or _DIGEST.fullmatch(recommendation_id) is None
        ):
            raise NightOwlValidationError("Promotion provenance is invalid.")
        with self._lock:
            c = self._connect(False)
            try:
                with c:
                    existing = c.execute(
                        "SELECT version_id,recommendation_id FROM night_owl_promotions "
                        "WHERE run_id=? AND finding_id=?", (run_id, finding_id)
                    ).fetchone()
                    if existing is not None:
                        if existing != (version_id, recommendation_id):
                            raise NightOwlConflictError("Promotion provenance conflicts.")
                        return
                    count = c.execute(
                        "SELECT COUNT(*) FROM night_owl_promotions WHERE run_id=?", (run_id,)
                    ).fetchone()[0]
                    if count >= DEFAULT_BUDGETS["capability_growth_promotions"]:
                        raise NightOwlConflictError(
                            "That Night Owl run reached its Capability Growth promotion limit."
                        )
                    if c.execute(
                        "SELECT 1 FROM night_owl_run_findings WHERE run_id=? AND version_id=?",
                        (run_id, version_id),
                    ).fetchone() is None:
                        raise NightOwlConflictError("Promotion provenance was not observed by that run.")
                    c.execute(
                        "INSERT INTO night_owl_promotions VALUES (?,?,?,?,?)",
                        (run_id, finding_id, version_id, recommendation_id, _stamp(self._clock())),
                    )
            finally:
                c.close()
    def promotion_for_finding(self, finding_id: str) -> PromotionReceipt | None:
        if not self.exists:
            return None
        with self._reader() as c:
            row = c.execute(
                "SELECT run_id,finding_id,version_id,recommendation_id,created_at_utc "
                "FROM night_owl_promotions WHERE finding_id=? "
                "ORDER BY created_at_utc DESC,run_id DESC LIMIT 1", (finding_id,)
            ).fetchone()
        return None if row is None else PromotionReceipt(*map(str, row))
    def migrate_v1_to_v2(self) -> tuple[int, int]:
        """Explicitly add analysis/run provenance; normal connects never migrate."""
        with self._lock:
            path = self._safe_path(True); assert path is not None
            c = sqlite3.connect(path, timeout=5.0, isolation_level=None)
            try:
                _connection(c)
                if self._schema_version(c) != 1:
                    raise NightOwlConflictError("Night Owl schema is not version 1.")
                c.execute("BEGIN IMMEDIATE")
                for key, statement in _SCHEMA_V2.items():
                    if key not in _SCHEMA_V1:
                        c.execute(statement)
                c.execute(
                    "UPDATE night_owl_metadata SET value='2' "
                    "WHERE key='schema_version' AND value='1'"
                )
                c.commit()
                if self._schema_version(c) != 2:
                    raise NightOwlCorruptError("Night Owl v1-to-v2 migration did not verify.")
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()
        return (1, 2)
    def migrate_v2_to_v3(self) -> tuple[int, int]:
        """Explicitly add sanitized run diagnostics; normal connects never migrate."""
        with self._lock:
            path = self._safe_path(True); assert path is not None
            c = sqlite3.connect(path, timeout=5.0, isolation_level=None)
            try:
                _connection(c)
                if self._schema_version(c) != 2:
                    raise NightOwlConflictError("Night Owl schema is not version 2.")
                c.execute("BEGIN IMMEDIATE")
                for key, statement in _SCHEMA.items():
                    if key not in _SCHEMA_V2:
                        c.execute(statement)
                c.execute(
                    "UPDATE night_owl_metadata SET value='3' "
                    "WHERE key='schema_version' AND value='2'"
                )
                c.commit()
                self._validate_schema(c)
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()
        return (2, 3)
    def migrate_to_latest(self) -> tuple[int, int]:
        """Apply only the known explicit steps to the current schema version."""
        with self._lock:
            path = self._safe_path(True); assert path is not None
            c = sqlite3.connect(path, timeout=5.0, isolation_level=None)
            try:
                _connection(c)
                before = self._schema_version(c)
            finally:
                c.close()
        version = before
        if version == 1:
            self.migrate_v1_to_v2()
            version = 2
        if version == 2:
            self.migrate_v2_to_v3()
            version = 3
        if version != SCHEMA_VERSION:
            raise NightOwlCorruptError("Night Owl schema is incompatible; it was not repaired.")
        return before, version
    @contextmanager
    def maintenance_guard(self)->Iterator[None]:
        with self._lock:
            if self.exists:
                c=self._connect(True); c.close()
            yield
    def _insert_grant(self,c,revision,value,now):
        identifier="grant-"+self._token_hex(16); digest=_grant_digest(revision,value)
        c.execute("INSERT INTO night_owl_grants VALUES (?,?,?,?,?,?,?,?,?)",(identifier,revision,_json(value.categories),value.source_policy_version,_json(dict(value.budgets)),digest,"active",now,None))
    def _sources(self,c,vid,sources,now):
        for source in sources: c.execute("INSERT INTO night_owl_sources VALUES (?,?,?,?,?,?,?,?,?)",("source-"+self._token_hex(16),vid,source.kind,source.url,source.title,source.stable_identity,source.immutable_identity,source.evidence_level,now))
    def _reserve(self,c,table,maximum):
        if c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]>=maximum: raise NightOwlConflictError("Night Owl retained history is full.")
    def _reserve_versions(self,c,fid):
        rows=c.execute("SELECT id FROM night_owl_finding_versions WHERE finding_id=? ORDER BY first_seen_at_utc,id",(fid,)).fetchall()
        if len(rows)>=DEFAULT_BUDGETS["versions_per_finding"]: c.execute("DELETE FROM night_owl_finding_versions WHERE id=?",(rows[0][0],))
    @contextmanager
    def _reader(self):
        c=self._connect(True)
        try: yield c
        finally:c.close()
    def _initialize(self,value,now):
        value = replace(
            value, budgets=tuple(budgets_for_categories(value.categories).items())
        )
        path=self._safe_parent(); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(path.parent,0o700); temp=path.with_name("."+path.name+".incomplete-"+self._token_hex(16))
        try:
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd); c=sqlite3.connect(temp)
            try:
                _connection(c)
                with c:
                    for sql in _SCHEMA.values():c.execute(sql)
                    c.execute("INSERT INTO night_owl_metadata VALUES ('schema_version',?)",(str(SCHEMA_VERSION),))
                    c.execute("INSERT INTO night_owl_settings VALUES (1,1,?,?,?,?,?,?)",(int(value.enabled),int(value.paused),_json(value.categories),value.source_policy_version,_json(dict(value.budgets)),now))
                    if value.enabled and not value.paused:self._insert_grant(c,1,value,now)
                self._validate_schema(c)
            finally:c.close()
            os.chmod(temp,0o600); os.link(temp,path);temp.unlink();temp=None
        except FileExistsError as exc: raise NightOwlConflictError("Night Owl state already exists.") from exc
        except (OSError,sqlite3.Error) as exc: raise NightOwlUnavailableError("Night Owl state could not be initialized.") from exc
        finally:
            if temp is not None:
                try:temp.unlink()
                except FileNotFoundError:pass
    def _connect(self,readonly):
        path=self._safe_path(True); c=None
        try:
            c=sqlite3.connect(f"file:{quote(os.fspath(path),safe='/')}?mode=ro",uri=True) if readonly else sqlite3.connect(path)
            _connection(c);self._validate_schema(c);result,c=c,None;return result
        except NightOwlError:raise
        except sqlite3.DatabaseError as exc:raise NightOwlCorruptError("Night Owl state is invalid; it was not repaired.") from exc
        except (OSError,sqlite3.Error) as exc:raise NightOwlUnavailableError() from exc
        finally:
            if c is not None:c.close()
    def _safe_parent(self):
        path=Path(os.path.abspath(os.path.normpath(os.fspath(self._path))))
        if ".." in self._path.parts:raise NightOwlUnavailableError("Night Owl path is unsafe.")
        current=Path(path.anchor);missing=False
        for part in path.parent.parts[1:]:
            current/=part
            if missing:continue
            try:info=os.lstat(current)
            except FileNotFoundError:missing=True;continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):raise NightOwlUnavailableError("Night Owl parent path is unsafe.")
        return path
    def _safe_path(self,required):
        path=self._safe_parent()
        try:info=os.lstat(path)
        except FileNotFoundError:
            if required:raise NightOwlUnavailableError()
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise NightOwlUnavailableError("Night Owl store file is unsafe.")
        return path
    @staticmethod
    def _validate_schema(c):
        try:
            if c.execute("PRAGMA integrity_check").fetchone()!=("ok",):raise NightOwlCorruptError()
            schema={(a,b):d for a,b,d in c.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
            metadata=c.execute("SELECT key,value FROM night_owl_metadata").fetchall()
            if schema == _SCHEMA_V1 and metadata == [("schema_version", "1")]:
                raise NightOwlCorruptError("Night Owl requires the explicit v1-to-v2 schema migration.")
            if schema == _SCHEMA_V2 and metadata == [("schema_version", "2")]:
                raise NightOwlCorruptError("Night Owl requires the explicit v2-to-v3 schema migration.")
            if schema!=_SCHEMA or metadata != [("schema_version",str(SCHEMA_VERSION))]:raise NightOwlCorruptError("Night Owl schema is incompatible; it was not repaired.")
        except NightOwlError:raise
        except (sqlite3.Error,TypeError,ValueError) as exc:raise NightOwlCorruptError() from exc
    @staticmethod
    def _schema_version(c):
        schema={(a,b):d for a,b,d in c.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
        metadata=c.execute("SELECT key,value FROM night_owl_metadata").fetchall()
        if schema == _SCHEMA_V1 and metadata == [("schema_version", "1")]:
            return 1
        if schema == _SCHEMA_V2 and metadata == [("schema_version", "2")]:
            return 2
        if schema == _SCHEMA and metadata == [("schema_version", str(SCHEMA_VERSION))]:
            return SCHEMA_VERSION
        raise NightOwlCorruptError("Night Owl schema is incompatible; it was not repaired.")

def _validate_settings(value):
    if not isinstance(value,NightOwlSettings) or type(value.enabled) is not bool or type(value.paused) is not bool or value.revision<0:raise NightOwlValidationError("Night Owl settings are invalid.")
    if value.source_policy_version!=SOURCE_POLICY_VERSION:raise NightOwlValidationError("Night Owl source policy is unsupported.")
    if tuple(sorted(set(value.categories)))!=value.categories or any(x not in CATEGORIES for x in value.categories) or (value.enabled and not value.categories):raise NightOwlValidationError("Night Owl categories are invalid.")
    budgets=dict(value.budgets)
    expected = budgets_for_categories(value.categories)
    # The previous V1 profile remains readable solely so that an explicit save
    # can revoke and replace its grant.  It is never admitted to a run.
    legacy = {
        "searches": 6, "search_results": 24, "github_fetches": 8,
        "skills_inspections": 2, "model_calls": 3,
        "model_input_tokens": 16000, "model_output_tokens": 4000,
        "retrieved_characters": 96000, "new_findings": 5,
        "capability_growth_promotions": 3, "run_seconds": 600,
        "active_runs": 1, "retained_runs": 50, "retained_findings": 250,
        "versions_per_finding": 5, "sources_per_version": 3,
    }
    if budgets != expected and budgets != legacy:
        raise NightOwlValidationError("Night Owl budgets are invalid.")
def _settings(row):
    value=NightOwlSettings(int(row[0]),bool(row[1]),bool(row[2]),tuple(json.loads(row[3])),str(row[4]),tuple(sorted(json.loads(row[5]).items())))
    _validate_settings(value);return value
def _grant(row):
    value=ResearchGrant(str(row[0]),int(row[1]),tuple(json.loads(row[2])),str(row[3]),tuple(sorted(json.loads(row[4]).items())),str(row[5]),str(row[6]));
    if not _DIGEST.fullmatch(value.digest) or value.status not in {"active","revoked"}:raise NightOwlCorruptError()
    return value
def _run(row):return NightOwlRun(str(row[0]),str(row[1]),str(row[2]),int(row[3]),str(row[4]),tuple(json.loads(row[5])),str(row[6]),str(row[7]),int(row[8]),tuple(sorted(json.loads(row[9]).items())),tuple(json.loads(row[10])))
def _grant_digest(revision,value):return hashlib.sha256(_json({"revision":revision,"categories":value.categories,"policy":value.source_policy_version,"budgets":dict(value.budgets)}).encode()).hexdigest()
def _draft(value):
    if not isinstance(value,FindingDraft):raise NightOwlValidationError("Finding draft is invalid.")
    _category(value.category);canonical_source_identity(value.source_identity);_short(value.title,200,"Title");_short(value.summary,1000,"Summary");_short(value.next_step,500,"Next step");_short(value.version_identity,200,"Version identity");_short(value.change_reason,200,"Change reason");
    if not _DIGEST.fullmatch(value.material_fingerprint) or len(value.sources)<1 or len(value.sources)>MAX_SOURCES_PER_VERSION:raise NightOwlValidationError("Finding material is invalid.")
    relevance_score(value.relevance_reasons)
    for values,limit in ((value.risks,5),(value.unknowns,5)):
        if len(values)>limit or any(not isinstance(x,str) or len(x)>500 for x in values):raise NightOwlValidationError("Finding risks or unknowns are invalid.")
    for source in value.sources:
        if not isinstance(source,SourceAttribution) or not source_policy_allows(source.kind,source.url) or len(source.title)>200 or canonical_source_identity(source.stable_identity)!=source.stable_identity:raise NightOwlValidationError("Finding source attribution is invalid.")
def _enrichment(value):
    for text, limit, label in (
        (value.summary,1000,"Analysis summary"),
        (value.why_it_matters,1000,"Analysis relevance"),
        (value.next_step,500,"Analysis next step"),
        (value.provider,64,"Analysis provider"),
        (value.model,255,"Analysis model"),
        (value.prompt_version,64,"Analysis prompt version"),
    ):
        _short(text,limit,label)
    if not _DIGEST.fullmatch(value.input_digest):
        raise NightOwlValidationError("Analysis input digest is invalid.")
    if not isinstance(value.created_at, str) or not _STAMP.fullmatch(value.created_at):
        raise NightOwlValidationError("Analysis timestamp is invalid.")
    for values in (value.risks,value.unknowns):
        if len(values)>5 or any(not isinstance(item,str) or not item.strip() or len(item)>500 for item in values):
            raise NightOwlValidationError("Analysis risks or unknowns are invalid.")
def _budget_usage(value, bounds):
    if any(key not in bounds or type(amount)is not int or amount<0 or amount>bounds[key] for key,amount in value.items()):raise NightOwlValidationError("Night Owl budget usage is invalid.")
_RUN_METRIC_KEYS_V1 = frozenset({
    "discovery_successes", "findings_changed", "source_policy_rejected",
    "relevance_rejected", "corroboration_failures", "corroboration_budget_skipped",
})
_RUN_METRIC_KEYS_V2 = _RUN_METRIC_KEYS_V1 | frozenset({
    "results_considered", "github_eligible_leads", "canonical_repositories_queued",
})
_RUN_METRIC_KEYS = _RUN_METRIC_KEYS_V2 | frozenset({
    "github_hosted_results", "skills_catalog_attempts", "skills_catalog_successes",
    "skills_catalog_failures", "skills_catalog_candidates", "repositories_inspected",
})
_CATEGORY_METRIC_KEYS_V1 = frozenset({
    "searches_executed", "usable_discovery_leads", "repositories_selected",
    "repositories_inspected", "source_policy_rejected", "relevance_rejected",
    "corroboration_failures", "corroboration_budget_skipped", "findings_retained",
})
_CATEGORY_METRIC_KEYS_V2 = _CATEGORY_METRIC_KEYS_V1 | frozenset({
    "results_considered", "github_eligible_leads", "canonical_repositories_queued",
})
_CATEGORY_METRIC_KEYS = _CATEGORY_METRIC_KEYS_V2 | frozenset({
    "github_hosted_results", "skills_catalog_attempts", "skills_catalog_successes",
    "skills_catalog_failures", "skills_catalog_candidates",
})
def _metrics(aggregate, categories, duration_millis):
    if (
        not isinstance(aggregate, dict) or set(aggregate) not in {_RUN_METRIC_KEYS_V1, _RUN_METRIC_KEYS_V2, _RUN_METRIC_KEYS}
        or not isinstance(categories, dict) or tuple(sorted(categories)) != tuple(categories)
        or any(category not in CATEGORIES for category in categories)
        or type(duration_millis) is not int or duration_millis < 0
        or any(type(value) is not int or value < 0 for value in aggregate.values())
        or any(
            not isinstance(values, dict) or set(values) not in {_CATEGORY_METRIC_KEYS_V1, _CATEGORY_METRIC_KEYS_V2, _CATEGORY_METRIC_KEYS}
            or any(type(value) is not int or value < 0 for value in values.values())
            for values in categories.values()
        )
    ):
        raise NightOwlValidationError("Night Owl run metrics are invalid.")
    return NightOwlRunMetrics(
        tuple(sorted(aggregate.items())),
        tuple((category, tuple(sorted(values.items()))) for category, values in categories.items()),
        duration_millis,
    )
def _category(value):
    if value not in CATEGORIES:raise NightOwlValidationError("Night Owl category is invalid.")
def _short(value,limit,label):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or "\x00" in value:raise NightOwlValidationError(f"{label} is invalid.")
def _bounded(value,limit):_short(value,limit,"Text");return value.strip()
def _json(value):return json.dumps(value,sort_keys=True,separators=(",",":"))
def _stamp(value):
    if not isinstance(value,datetime) or value.tzinfo is None:raise NightOwlValidationError("Timestamp is invalid.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
def _connection(c):c.execute("PRAGMA journal_mode=DELETE");c.execute("PRAGMA synchronous=FULL");c.execute("PRAGMA foreign_keys=ON")
