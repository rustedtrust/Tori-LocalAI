"""Deterministic, local-only Companion Initiative policy and durable state.

This module decides only whether one bounded application-authored utterance may
be considered.  It has no capability, Conversation, model, network, scheduler,
or remote-delivery authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = 4
DEFAULT_STORE_PATH = Path("runtime/companion_initiative/tori_companion_initiative.db")
DEFAULT_MORNING_START = time(8)
DEFAULT_MORNING_END = time(10)
DEFAULT_QUIET_START = time(22)
DEFAULT_QUIET_END = time(8)
RECENT_ACTIVITY = timedelta(minutes=15)
GLOBAL_COOLDOWN = timedelta(hours=24)
SEVEN_DAY_CAP = 3
THIRTY_DAY_CAP = 8
RESUME_QUIET = timedelta(hours=4)
RESUME_EXPIRY = timedelta(hours=72)
RESUME_COOLDOWN = timedelta(hours=72)
LONG_SILENCE_THRESHOLD = timedelta(days=7)
LONG_SILENCE_COOLDOWN = timedelta(days=14)
MAX_LEASE = timedelta(minutes=5)
MAX_CANDIDATES = 512
MAX_ACTIVITY_SIGNALS = 4096
INITIATIVE_TYPES = frozenset({"morning", "resume", "long_silence", "night_owl_findings"})
CANDIDATE_STATES = frozenset(
    {"pending", "delivering", "delivered", "acknowledged", "dismissed", "expired", "superseded", "failed"}
)
TERMINAL_STATES = frozenset({"acknowledged", "dismissed", "expired", "superseded", "failed"})
ACTIVITY_KINDS = frozenset(
    {"local_turn", "remote_turn", "confirmation", "mutation", "dismiss", "snooze", "manual_speak", "user_control", "settings_change"}
)
RECOVERY_OBSERVATIONS = frozenset({"matching", "absent", "conflict"})
ATTENTION_SOURCES = frozenset({"research", "coding_work", "night_owl", "scheduled_work"})
ATTENTION_CLASSES = frozenset({"needs_attention", "worth_reviewing", "informational"})
DELIVERY_LEVELS = frozenset({"silent", "gentle", "conversational"})
ATTENTION_STATES = frozenset({"open", "deferred", "dismissed", "reviewed", "resolved"})
MAX_ATTENTION_ITEMS = 512
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_DEDUPE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,299}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")

_SCHEMA_V1 = {
    ("table", "initiative_metadata"):
        "CREATE TABLE initiative_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    ("table", "initiative_settings"):
        "CREATE TABLE initiative_settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL CHECK(revision>=1),master_enabled INTEGER NOT NULL CHECK(master_enabled IN (0,1)),morning_enabled INTEGER NOT NULL CHECK(morning_enabled IN (0,1)),resume_enabled INTEGER NOT NULL CHECK(resume_enabled IN (0,1)),long_silence_enabled INTEGER NOT NULL CHECK(long_silence_enabled IN (0,1)),morning_start TEXT NOT NULL,morning_end TEXT NOT NULL,quiet_start TEXT NOT NULL,quiet_end TEXT NOT NULL,snoozed_until_utc TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL)",
    ("table", "initiative_activity"):
        "CREATE TABLE initiative_activity (singleton INTEGER PRIMARY KEY CHECK(singleton=1),activity_revision INTEGER NOT NULL CHECK(activity_revision>=0),last_meaningful_at_utc TEXT,last_kind TEXT)",
    ("table", "initiative_candidates"):
        "CREATE TABLE initiative_candidates (id TEXT PRIMARY KEY,type TEXT NOT NULL CHECK(type IN ('morning','resume','long_silence')),dedupe_key TEXT NOT NULL UNIQUE,anchor_kind TEXT,anchor_id TEXT,anchor_revision INTEGER,eligible_at_utc TEXT NOT NULL,expires_at_utc TEXT,state TEXT NOT NULL CHECK(state IN ('pending','delivering','delivered','acknowledged','dismissed','expired','superseded','failed')),revision INTEGER NOT NULL CHECK(revision>=1),application_event_id TEXT NOT NULL UNIQUE,wording TEXT NOT NULL,target_chat_id TEXT,target_chat_revision INTEGER,lease_owner TEXT,lease_expires_at_utc TEXT,created_at_utc TEXT NOT NULL,delivered_at_utc TEXT,acknowledged_at_utc TEXT,terminal_reason TEXT)",
    ("index", "initiative_candidates_delivery"):
        "CREATE INDEX initiative_candidates_delivery ON initiative_candidates(state,delivered_at_utc)",
    ("index", "initiative_candidates_lease"):
        "CREATE INDEX initiative_candidates_lease ON initiative_candidates(state,lease_expires_at_utc)",
    ("index", "initiative_candidates_type"):
        "CREATE INDEX initiative_candidates_type ON initiative_candidates(type,state,created_at_utc)",
}
_SCHEMA_V2 = {
    **_SCHEMA_V1,
    ("table", "initiative_activity_signals"):
        "CREATE TABLE initiative_activity_signals (signal_key TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('local_turn','remote_turn','confirmation','mutation','dismiss','snooze','manual_speak','user_control','settings_change')),occurred_at_utc TEXT NOT NULL,activity_revision INTEGER NOT NULL UNIQUE CHECK(activity_revision>=1),recorded_at_utc TEXT NOT NULL)",
    ("index", "initiative_activity_signals_revision"):
        "CREATE INDEX initiative_activity_signals_revision ON initiative_activity_signals(activity_revision)",
}
_SCHEMA_V3 = {
    **_SCHEMA_V2,
    ("table", "initiative_settings"):
        "CREATE TABLE initiative_settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL CHECK(revision>=1),master_enabled INTEGER NOT NULL CHECK(master_enabled IN (0,1)),morning_enabled INTEGER NOT NULL CHECK(morning_enabled IN (0,1)),resume_enabled INTEGER NOT NULL CHECK(resume_enabled IN (0,1)),long_silence_enabled INTEGER NOT NULL CHECK(long_silence_enabled IN (0,1)),night_owl_findings_enabled INTEGER NOT NULL CHECK(night_owl_findings_enabled IN (0,1)),morning_start TEXT NOT NULL,morning_end TEXT NOT NULL,quiet_start TEXT NOT NULL,quiet_end TEXT NOT NULL,snoozed_until_utc TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL)",
    ("table", "initiative_candidates"):
        "CREATE TABLE initiative_candidates (id TEXT PRIMARY KEY,type TEXT NOT NULL CHECK(type IN ('morning','resume','long_silence','night_owl_findings')),dedupe_key TEXT NOT NULL UNIQUE,anchor_kind TEXT,anchor_id TEXT,anchor_revision INTEGER,eligible_at_utc TEXT NOT NULL,expires_at_utc TEXT,state TEXT NOT NULL CHECK(state IN ('pending','delivering','delivered','acknowledged','dismissed','expired','superseded','failed')),revision INTEGER NOT NULL CHECK(revision>=1),application_event_id TEXT NOT NULL UNIQUE,wording TEXT NOT NULL,target_chat_id TEXT,target_chat_revision INTEGER,lease_owner TEXT,lease_expires_at_utc TEXT,created_at_utc TEXT NOT NULL,delivered_at_utc TEXT,acknowledged_at_utc TEXT,terminal_reason TEXT)",
}
_SCHEMA = {
    **_SCHEMA_V3,
    ("table", "attention_items"):
        "CREATE TABLE attention_items (id TEXT PRIMARY KEY,source TEXT NOT NULL CHECK(source IN ('research','coding_work','night_owl','scheduled_work')),source_object_id TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,attention_class TEXT NOT NULL CHECK(attention_class IN ('needs_attention','worth_reviewing','informational')),delivery_level TEXT NOT NULL CHECK(delivery_level IN ('silent','gentle','conversational')),source_revision INTEGER NOT NULL CHECK(source_revision>=1),material_key TEXT NOT NULL,project_id TEXT,source_updated_at_utc TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('open','deferred','dismissed','reviewed','resolved')),revision INTEGER NOT NULL CHECK(revision>=1),surfaced_material_key TEXT,last_surfaced_at_utc TEXT,deferred_until_utc TEXT,created_at_utc TEXT NOT NULL,updated_at_utc TEXT NOT NULL,UNIQUE(source,source_object_id))",
    ("table", "initiative_candidate_attention"):
        "CREATE TABLE initiative_candidate_attention (candidate_id TEXT NOT NULL,attention_id TEXT NOT NULL,material_key TEXT NOT NULL,PRIMARY KEY(candidate_id,attention_id),FOREIGN KEY(candidate_id) REFERENCES initiative_candidates(id) ON DELETE CASCADE,FOREIGN KEY(attention_id) REFERENCES attention_items(id) ON DELETE CASCADE)",
    ("index", "attention_items_state"):
        "CREATE INDEX attention_items_state ON attention_items(state,attention_class,updated_at_utc)",
}


class CompanionInitiativeError(RuntimeError):
    code = "companion_initiative_failed"


class CompanionInitiativeValidationError(CompanionInitiativeError):
    code = "companion_initiative_invalid"


class CompanionInitiativeUnavailableError(CompanionInitiativeError):
    code = "companion_initiative_unavailable"


class CompanionInitiativeCorruptError(CompanionInitiativeError):
    code = "companion_initiative_corrupt"


class CompanionInitiativeConflictError(CompanionInitiativeError):
    code = "companion_initiative_conflict"


@dataclass(frozen=True, slots=True)
class InitiativeSettings:
    revision: int = 0
    master_enabled: bool = False
    morning_enabled: bool = False
    resume_enabled: bool = False
    long_silence_enabled: bool = False
    night_owl_findings_enabled: bool = False
    morning_start: time = DEFAULT_MORNING_START
    morning_end: time = DEFAULT_MORNING_END
    quiet_start: time = DEFAULT_QUIET_START
    quiet_end: time = DEFAULT_QUIET_END
    snoozed_until_utc: datetime | None = None


@dataclass(frozen=True, slots=True)
class InitiativeActivity:
    revision: int = 0
    last_meaningful_at_utc: datetime | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class InitiativeCandidate:
    identifier: str
    type: str
    dedupe_key: str
    anchor_kind: str | None
    anchor_id: str | None
    anchor_revision: int | None
    eligible_at_utc: datetime
    expires_at_utc: datetime | None
    state: str
    revision: int
    application_event_id: str
    wording: str
    target_chat_id: str | None
    target_chat_revision: int | None
    lease_owner: str | None
    lease_expires_at_utc: datetime | None
    created_at_utc: datetime
    delivered_at_utc: datetime | None
    acknowledged_at_utc: datetime | None
    terminal_reason: str | None


@dataclass(frozen=True, slots=True)
class AttentionSignal:
    source: str
    source_object_id: str
    kind: str
    title: str
    summary: str
    attention_class: str
    delivery_level: str
    source_revision: int
    material_key: str
    source_updated_at_utc: datetime
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    identifier: str
    source: str
    source_object_id: str
    kind: str
    title: str
    summary: str
    attention_class: str
    delivery_level: str
    source_revision: int
    material_key: str
    project_id: str | None
    source_updated_at_utc: datetime
    state: str
    revision: int
    surfaced_material_key: str | None
    last_surfaced_at_utc: datetime | None
    deferred_until_utc: datetime | None
    created_at_utc: datetime
    updated_at_utc: datetime


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResumeAnchor:
    """Content-limited, source-owned evidence suitable for resume policy."""

    kind: str
    identifier: str
    revision: int
    safe_title: str | None
    last_active_at_utc: datetime
    origin_chat_id: str
    project_id: str | None


@dataclass(frozen=True, slots=True)
class ResumeWindow:
    eligible_at_utc: datetime
    expires_at_utc: datetime


@dataclass(frozen=True, slots=True)
class InitiativeReplyContext:
    """Bounded data from one delivered check-in for one local reply."""

    candidate_id: str
    initiative_type: str
    application_event_id: str
    wording: str
    anchor_kind: str | None
    anchor_id: str | None
    anchor_revision: int | None


def resume_window(anchor: ResumeAnchor, activity: InitiativeActivity) -> ResumeWindow:
    if not isinstance(anchor, ResumeAnchor):
        raise CompanionInitiativeValidationError("A structured resume anchor is required.")
    last_active = _aware_utc(anchor.last_active_at_utc)
    baseline = last_active
    if activity.last_meaningful_at_utc is not None:
        baseline = max(baseline, _aware_utc(activity.last_meaningful_at_utc))
    return ResumeWindow(baseline + RESUME_QUIET, last_active + RESUME_EXPIRY)


def morning_candidate_key(timezone_name: str, local_date: date) -> str:
    zone = _zone(timezone_name)
    if not isinstance(local_date, date):
        raise CompanionInitiativeValidationError("A local date is required.")
    return f"morning:{zone.key}:{local_date.isoformat()}"


def resume_candidate_key(anchor_kind: str, anchor_id: str, anchor_revision: int) -> str:
    return f"resume:{_id(anchor_kind, 'anchor kind')}:{_id(anchor_id, 'anchor identifier')}:{_positive_revision(anchor_revision)}"


def silence_candidate_key(activity_revision: int) -> str:
    if type(activity_revision) is not int or activity_revision < 0:
        raise CompanionInitiativeValidationError("Activity revision is invalid.")
    return f"silence:{activity_revision}"


def in_local_window(now: datetime, timezone_name: str, start: time, end: time) -> bool:
    local = _aware_utc(now).astimezone(_zone(timezone_name)).timetz().replace(tzinfo=None)
    start, end = _civil_time(start), _civil_time(end)
    if start == end:
        raise CompanionInitiativeValidationError("A civil-time window cannot be empty.")
    return start <= local < end if start < end else local >= start or local < end


def is_quiet_hour(now: datetime, timezone_name: str, settings: InitiativeSettings) -> bool:
    return in_local_window(now, timezone_name, settings.quiet_start, settings.quiet_end)


def cooldown_active(now: datetime, last_at: datetime | None, duration: timedelta) -> bool:
    now = _aware_utc(now)
    if last_at is None:
        return False
    last = _aware_utc(last_at)
    # A backward clock movement fails closed until chronology is coherent.
    return now < last or now - last < duration


def rolling_cap_reached(now: datetime, delivered: Sequence[datetime], *, window: timedelta, maximum: int) -> bool:
    now = _aware_utc(now)
    if maximum < 1 or window <= timedelta(0):
        raise CompanionInitiativeValidationError("A rolling cap is invalid.")
    count = 0
    for value in delivered:
        stamp = _aware_utc(value)
        if stamp > now:  # future history is uncertainty, so suppress
            return True
        if now - stamp < window:
            count += 1
    return count >= maximum


def evaluate_policy(
    initiative_type: str,
    *,
    now: datetime,
    timezone_name: str,
    settings: InitiativeSettings,
    activity: InitiativeActivity,
    delivered_history: Sequence[tuple[str, datetime]] = (),
    type_ready: bool = True,
) -> PolicyDecision:
    if initiative_type not in INITIATIVE_TYPES:
        raise CompanionInitiativeValidationError("Initiative type is invalid.")
    now = _aware_utc(now)
    _zone(timezone_name)
    reasons: list[str] = []
    enabled = {
        "morning": settings.morning_enabled,
        "resume": settings.resume_enabled,
        "long_silence": settings.long_silence_enabled,
        "night_owl_findings": settings.night_owl_findings_enabled,
    }
    if not settings.master_enabled:
        reasons.append("master_off")
    if not enabled[initiative_type]:
        reasons.append("type_off")
    if not type_ready:
        reasons.append("type_not_ready")
    if settings.snoozed_until_utc is not None and cooldown_active(now, settings.snoozed_until_utc, timedelta(0)):
        reasons.append("snoozed")
    if is_quiet_hour(now, timezone_name, settings):
        reasons.append("quiet_hours")
    if activity.last_meaningful_at_utc is not None and cooldown_active(now, activity.last_meaningful_at_utc, RECENT_ACTIVITY):
        reasons.append("recent_activity")
    history = tuple((kind, _aware_utc(stamp)) for kind, stamp in delivered_history)
    all_times = tuple(stamp for _, stamp in history)
    if all_times and cooldown_active(now, max(all_times), GLOBAL_COOLDOWN):
        reasons.append("global_cooldown")
    if rolling_cap_reached(now, all_times, window=timedelta(days=7), maximum=SEVEN_DAY_CAP):
        reasons.append("seven_day_cap")
    if rolling_cap_reached(now, all_times, window=timedelta(days=30), maximum=THIRTY_DAY_CAP):
        reasons.append("thirty_day_cap")
    same_type = tuple(stamp for kind, stamp in history if kind == initiative_type)
    type_cooldown = RESUME_COOLDOWN if initiative_type == "resume" else LONG_SILENCE_COOLDOWN if initiative_type == "long_silence" else None
    if type_cooldown is not None and same_type and cooldown_active(now, max(same_type), type_cooldown):
        reasons.append("type_cooldown")
    if initiative_type == "morning" and not in_local_window(now, timezone_name, settings.morning_start, settings.morning_end):
        reasons.append("outside_morning_window")
    if initiative_type == "long_silence" and (
        activity.last_meaningful_at_utc is None
        or cooldown_active(now, activity.last_meaningful_at_utc, LONG_SILENCE_THRESHOLD)
    ):
        reasons.append("silence_threshold")
    return PolicyDecision(not reasons, tuple(reasons))


class SQLiteCompanionInitiativeStore:
    """Owner-private exact-schema initiative state with revision fencing."""

    def __init__(self, path: Path = DEFAULT_STORE_PATH, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._safe_path(False) is not None

    def settings(self) -> InitiativeSettings:
        if not self.exists:
            return InitiativeSettings()
        connection = self._connect(True)
        try:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(initiative_settings)"
                )
            }
            if "night_owl_findings_enabled" in columns:
                row = connection.execute("SELECT revision,master_enabled,morning_enabled,resume_enabled,long_silence_enabled,night_owl_findings_enabled,morning_start,morning_end,quiet_start,quiet_end,snoozed_until_utc FROM initiative_settings WHERE singleton=1").fetchone()
            else:
                legacy = connection.execute("SELECT revision,master_enabled,morning_enabled,resume_enabled,long_silence_enabled,morning_start,morning_end,quiet_start,quiet_end,snoozed_until_utc FROM initiative_settings WHERE singleton=1").fetchone()
                row = (*legacy[:5], 0, *legacy[5:]) if legacy is not None else None
        finally:
            connection.close()
        if row is None:
            raise CompanionInitiativeCorruptError("Companion Initiative settings are missing.")
        return _settings_from_row(row)

    def activity(self) -> InitiativeActivity:
        if not self.exists:
            return InitiativeActivity()
        connection = self._connect(True)
        try:
            row = connection.execute("SELECT activity_revision,last_meaningful_at_utc,last_kind FROM initiative_activity WHERE singleton=1").fetchone()
        finally:
            connection.close()
        if row is None:
            raise CompanionInitiativeCorruptError("Companion Initiative activity is missing.")
        return InitiativeActivity(row[0], _parse_optional(row[1]), row[2])

    def save_settings(self, settings: InitiativeSettings, *, expected_revision: int) -> InitiativeSettings:
        return self._save_settings(
            settings, expected_revision=expected_revision, activity_kind="settings_change"
        )

    def _save_settings(
        self,
        settings: InitiativeSettings,
        *,
        expected_revision: int,
        activity_kind: str,
        acknowledge_event_id: str | None = None,
    ) -> InitiativeSettings:
        if not isinstance(settings, InitiativeSettings) or type(expected_revision) is not int or expected_revision < 0:
            raise CompanionInitiativeValidationError("Companion Initiative settings revision is invalid.")
        if activity_kind not in {"settings_change", "snooze"}:
            raise CompanionInitiativeValidationError("Settings activity kind is invalid.")
        if acknowledge_event_id is not None and (
            not isinstance(acknowledge_event_id, str)
            or re.fullmatch(r"event-[0-9a-f]{32}", acknowledge_event_id) is None
        ):
            raise CompanionInitiativeValidationError(
                "Companion Initiative event identifier is invalid."
            )
        _validate_settings(settings)
        now = _stamp(self._clock())
        with self._lock:
            if not self.exists:
                if acknowledge_event_id is not None:
                    raise CompanionInitiativeConflictError(
                        "No delivered initiative is available to acknowledge."
                    )
                if expected_revision != 0:
                    raise CompanionInitiativeConflictError("Companion Initiative settings changed; refresh and try again.")
                self._initialize_atomic(settings, now)
                return self.settings()
            connection = self._connect(False)
            try:
                with connection:
                    prior_activity = connection.execute(
                        "SELECT last_meaningful_at_utc FROM initiative_activity WHERE singleton=1"
                    ).fetchone()
                    if (
                        prior_activity is None
                        or prior_activity[0] is not None
                        and _parse(prior_activity[0]) > _parse(now)
                    ):
                        raise CompanionInitiativeConflictError(
                            "The clock moved backward; settings were not changed."
                        )
                    changed = connection.execute(
                        "UPDATE initiative_settings SET revision=revision+1,master_enabled=?,morning_enabled=?,resume_enabled=?,long_silence_enabled=?,night_owl_findings_enabled=?,morning_start=?,morning_end=?,quiet_start=?,quiet_end=?,snoozed_until_utc=?,updated_at_utc=? WHERE singleton=1 AND revision=?",
                        (_bool(settings.master_enabled), _bool(settings.morning_enabled), _bool(settings.resume_enabled), _bool(settings.long_silence_enabled), _bool(settings.night_owl_findings_enabled), _time_text(settings.morning_start), _time_text(settings.morning_end), _time_text(settings.quiet_start), _time_text(settings.quiet_end), _optional_stamp(settings.snoozed_until_utc), now, expected_revision),
                    ).rowcount
                    if changed != 1:
                        raise CompanionInitiativeConflictError("Companion Initiative settings changed; refresh and try again.")
                    connection.execute(
                        "UPDATE initiative_activity SET activity_revision=activity_revision+1,"
                        "last_meaningful_at_utc=?,last_kind=? WHERE singleton=1",
                        (now, activity_kind),
                    )
                    if acknowledge_event_id is not None:
                        acknowledged = connection.execute(
                            "UPDATE initiative_candidates SET state='acknowledged',"
                            "revision=revision+1,acknowledged_at_utc=?,"
                            "terminal_reason='user_paused',lease_owner=NULL,"
                            "lease_expires_at_utc=NULL "
                            "WHERE application_event_id=? AND state='delivered'",
                            (now, acknowledge_event_id),
                        ).rowcount
                        if acknowledged != 1:
                            raise CompanionInitiativeConflictError(
                                "The exact initiative is no longer available to pause."
                            )
                    if not settings.master_enabled:
                        connection.execute(
                            "UPDATE initiative_candidates SET state='superseded',revision=revision+1,terminal_reason='master_disabled' WHERE state='pending'"
                        )
            finally:
                connection.close()
        return self.settings()

    def snooze(
        self,
        until: datetime | None,
        *,
        expected_revision: int,
        acknowledge_event_id: str | None = None,
    ) -> InitiativeSettings:
        current = self.settings()
        if current.revision == 0:
            raise CompanionInitiativeConflictError("Enable Companion Initiative settings before snoozing.")
        return self._save_settings(
            replace(
                current,
                snoozed_until_utc=None if until is None else _aware_utc(until),
            ),
            expected_revision=expected_revision,
            activity_kind="snooze",
            acknowledge_event_id=acknowledge_event_id,
        )

    def record_meaningful_interaction(
        self,
        kind: str,
        *,
        occurred_at: datetime | None = None,
        signal_identity: str | None = None,
    ) -> InitiativeActivity:
        if kind not in ACTIVITY_KINDS:
            raise CompanionInitiativeValidationError("Meaningful interaction kind is invalid.")
        if not self.exists:
            return InitiativeActivity()
        now = _stamp(occurred_at or self._clock())
        signal_key = None
        if signal_identity is not None:
            if (
                not isinstance(signal_identity, str)
                or not signal_identity
                or len(signal_identity) > 500
                or any(ord(character) < 0x20 for character in signal_identity)
            ):
                raise CompanionInitiativeValidationError(
                    "Meaningful interaction identity is invalid."
                )
            signal_key = hashlib.sha256(signal_identity.encode("utf-8")).hexdigest()
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    if signal_key is not None and connection.execute(
                        "SELECT 1 FROM initiative_activity_signals WHERE signal_key=?",
                        (signal_key,),
                    ).fetchone() is not None:
                        row = connection.execute(
                            "SELECT activity_revision,last_meaningful_at_utc,last_kind FROM initiative_activity WHERE singleton=1"
                        ).fetchone()
                        return InitiativeActivity(row[0], _parse_optional(row[1]), row[2])
                    prior = connection.execute("SELECT last_meaningful_at_utc FROM initiative_activity WHERE singleton=1").fetchone()
                    if prior is None:
                        raise CompanionInitiativeCorruptError()
                    if prior[0] is not None and _parse(prior[0]) > _parse(now):
                        raise CompanionInitiativeConflictError("Meaningful interaction time moved backward; state was not changed.")
                    connection.execute("UPDATE initiative_activity SET activity_revision=activity_revision+1,last_meaningful_at_utc=?,last_kind=? WHERE singleton=1", (now, kind))
                    if signal_key is not None:
                        revision = connection.execute(
                            "SELECT activity_revision FROM initiative_activity WHERE singleton=1"
                        ).fetchone()[0]
                        connection.execute(
                            "INSERT INTO initiative_activity_signals VALUES (?,?,?,?,?)",
                            (signal_key, kind, now, revision, _stamp(self._clock())),
                        )
                        connection.execute(
                            "DELETE FROM initiative_activity_signals WHERE activity_revision <= ?",
                            (revision - MAX_ACTIVITY_SIGNALS,),
                        )
            finally:
                connection.close()
        return self.activity()

    def reconcile_attention(
        self, source: str, signals: Sequence[AttentionSignal]
    ) -> tuple[AttentionItem, ...]:
        """Reconcile one authoritative source without disturbing other sources."""

        if source not in ATTENTION_SOURCES:
            raise CompanionInitiativeValidationError("Attention source is invalid.")
        validated = tuple(_validate_attention_signal(item, source) for item in signals)
        identities = [item.source_object_id for item in validated]
        if len(identities) != len(set(identities)):
            raise CompanionInitiativeValidationError("Attention source identities are duplicated.")
        if not self.exists:
            return ()
        now = _stamp(self._clock())
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    for signal in validated:
                        digest = hashlib.sha256(
                            f"{signal.source}\0{signal.source_object_id}".encode("utf-8")
                        ).hexdigest()
                        row = connection.execute(
                            "SELECT id,material_key,state,kind,title,summary,"
                            "attention_class,delivery_level,project_id FROM attention_items "
                            "WHERE source=? AND source_object_id=?",
                            (source, signal.source_object_id),
                        ).fetchone()
                        if row is None:
                            self._reserve_attention_capacity(connection)
                            connection.execute(
                                "INSERT INTO attention_items VALUES "
                                "(?,?,?,?,?,?,?,?,?,?,?,?,'open',1,NULL,NULL,NULL,?,?)",
                                (
                                    digest, source, signal.source_object_id, signal.kind,
                                    signal.title, signal.summary, signal.attention_class,
                                    signal.delivery_level, signal.source_revision,
                                    signal.material_key, signal.project_id,
                                    _stamp(signal.source_updated_at_utc), now, now,
                                ),
                            )
                            continue
                        material_changed = row[1] != signal.material_key
                        presentation_changed = row[3:] != (
                            signal.kind, signal.title, signal.summary,
                            signal.attention_class, signal.delivery_level,
                            signal.project_id,
                        )
                        state = "open" if material_changed else row[2]
                        if material_changed or presentation_changed:
                            connection.execute(
                                "UPDATE attention_items SET kind=?,title=?,summary=?,"
                                "attention_class=?,delivery_level=?,source_revision=?,"
                                "material_key=?,project_id=?,source_updated_at_utc=?,state=?,"
                                "revision=revision+1,surfaced_material_key=CASE WHEN ? THEN NULL ELSE surfaced_material_key END,"
                                "last_surfaced_at_utc=CASE WHEN ? THEN NULL ELSE last_surfaced_at_utc END,"
                                "deferred_until_utc=CASE WHEN ? THEN NULL ELSE deferred_until_utc END,updated_at_utc=? "
                                "WHERE id=?",
                                (
                                    signal.kind, signal.title, signal.summary,
                                    signal.attention_class, signal.delivery_level,
                                    signal.source_revision, signal.material_key,
                                    signal.project_id, _stamp(signal.source_updated_at_utc),
                                    state, material_changed, material_changed,
                                    material_changed, now, row[0],
                                ),
                            )
                        else:
                            # Source bookkeeping can advance without invalidating a
                            # user's current Review/Later/Dismiss control revision.
                            connection.execute(
                                "UPDATE attention_items SET source_revision=?,"
                                "source_updated_at_utc=? WHERE id=?",
                                (
                                    signal.source_revision,
                                    _stamp(signal.source_updated_at_utc), row[0],
                                ),
                            )
                    if identities:
                        placeholders = ",".join("?" for _ in identities)
                        connection.execute(
                            f"UPDATE attention_items SET state='resolved',revision=revision+1,"
                            f"updated_at_utc=? WHERE source=? AND state IN ('open','deferred') "
                            f"AND source_object_id NOT IN ({placeholders})",
                            (now, source, *identities),
                        )
                    else:
                        connection.execute(
                            "UPDATE attention_items SET state='resolved',revision=revision+1,"
                            "updated_at_utc=? WHERE source=? AND state IN ('open','deferred')",
                            (now, source),
                        )
            finally:
                connection.close()
        return self.list_attention(source=source)

    def list_attention(
        self, *, source: str | None = None, include_resolved: bool = True
    ) -> tuple[AttentionItem, ...]:
        if source is not None and source not in ATTENTION_SOURCES:
            raise CompanionInitiativeValidationError("Attention source is invalid.")
        if not self.exists:
            return ()
        clauses: list[str] = []
        parameters: list[object] = []
        if source is not None:
            clauses.append("source=?")
            parameters.append(source)
        if not include_resolved:
            clauses.append("state!='resolved'")
        where = "" if not clauses else " WHERE " + " AND ".join(clauses)
        connection = self._connect(True)
        try:
            rows = connection.execute(
                "SELECT * FROM attention_items" + where +
                " ORDER BY CASE attention_class WHEN 'needs_attention' THEN 0 "
                "WHEN 'worth_reviewing' THEN 1 ELSE 2 END,updated_at_utc DESC,id",
                tuple(parameters),
            ).fetchall()
            return tuple(_attention_from_row(row) for row in rows)
        finally:
            connection.close()

    def list_project_attention(
        self, project_id: str, *, limit: int = 50
    ) -> tuple[AttentionItem, ...]:
        """Read bounded native Project membership without changing attention."""

        if not isinstance(project_id, str) or re.fullmatch(r"project-[0-9a-f]{32}", project_id) is None:
            raise CompanionInitiativeValidationError("Attention Project is invalid.")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise CompanionInitiativeValidationError("Attention limit is invalid.")
        if not self.exists:
            return ()
        connection = self._connect(True)
        try:
            rows = connection.execute(
                "SELECT * FROM attention_items WHERE project_id=? "
                "ORDER BY updated_at_utc DESC,id LIMIT ?", (project_id, limit)
            ).fetchall()
            return tuple(_attention_from_row(row) for row in rows)
        finally:
            connection.close()

    def get_attention(self, identifier: str) -> AttentionItem:
        _id(identifier, "attention identifier")
        connection = self._connect(True)
        try:
            row = connection.execute(
                "SELECT * FROM attention_items WHERE id=?", (identifier,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise CompanionInitiativeConflictError("Attention item was not found.")
        return _attention_from_row(row)

    def update_attention(
        self,
        identifier: str,
        action: str,
        *,
        expected_revision: int,
        defer_until: datetime | None = None,
    ) -> AttentionItem:
        if action not in {"dismiss", "review", "defer"}:
            raise CompanionInitiativeValidationError("Attention action is invalid.")
        if type(expected_revision) is not int or expected_revision < 1:
            raise CompanionInitiativeValidationError("Attention revision is invalid.")
        now_value = _aware_utc(self._clock())
        if action == "defer":
            if defer_until is None or _aware_utc(defer_until) <= now_value:
                raise CompanionInitiativeValidationError("Attention deferral is invalid.")
        elif defer_until is not None:
            raise CompanionInitiativeValidationError("Only a deferral accepts a future time.")
        state = {"dismiss": "dismissed", "review": "reviewed", "defer": "deferred"}[action]
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE attention_items SET state=?,revision=revision+1,"
                        "deferred_until_utc=?,updated_at_utc=? WHERE id=? AND revision=? "
                        "AND state IN ('open','deferred')",
                        (
                            state, _optional_stamp(defer_until), _stamp(now_value),
                            identifier, expected_revision,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise CompanionInitiativeConflictError(
                            "Attention item changed; refresh and try again."
                        )
            finally:
                connection.close()
        return self.get_attention(identifier)

    def eligible_attention(self, *, at: datetime | None = None) -> tuple[AttentionItem, ...]:
        now = _aware_utc(at or self._clock())
        result = []
        for item in self.list_attention(include_resolved=False):
            if item.state == "deferred" and (
                item.deferred_until_utc is None or item.deferred_until_utc > now
            ):
                continue
            if item.state not in {"open", "deferred"}:
                continue
            if item.surfaced_material_key == item.material_key:
                continue
            result.append(item)
        return tuple(result)

    def create_candidate(self, *, initiative_type: str, dedupe_key: str, eligible_at: datetime, expires_at: datetime | None, wording: str, anchor_kind: str | None = None, anchor_id: str | None = None, anchor_revision: int | None = None, attention_ids: Sequence[str] = ()) -> InitiativeCandidate:
        _validate_candidate_input(initiative_type, dedupe_key, eligible_at, expires_at, wording, anchor_kind, anchor_id, anchor_revision)
        if not self.exists:
            raise CompanionInitiativeUnavailableError("Companion Initiative is not configured.")
        digest = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
        identifier = digest
        event_id = f"event-{digest[:32]}"
        now = _stamp(self._clock())
        with self._lock:
            connection = self._connect(False)
            try:
                row = connection.execute("SELECT id FROM initiative_candidates WHERE dedupe_key=?", (dedupe_key,)).fetchone()
                if row is None:
                    try:
                        with connection:
                            self._reserve_capacity(connection)
                            connection.execute(
                                "INSERT INTO initiative_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (identifier, initiative_type, dedupe_key, anchor_kind, anchor_id, anchor_revision, _stamp(eligible_at), _optional_stamp(expires_at), "pending", 1, event_id, wording, None, None, None, None, now, None, None, None),
                            )
                            for attention_id in attention_ids:
                                _id(attention_id, "attention identifier")
                                attention_row = connection.execute(
                                    "SELECT material_key FROM attention_items WHERE id=?",
                                    (attention_id,),
                                ).fetchone()
                                if attention_row is None:
                                    raise CompanionInitiativeConflictError(
                                        "Attention item was not found."
                                    )
                                connection.execute(
                                    "INSERT INTO initiative_candidate_attention VALUES (?,?,?)",
                                    (identifier, attention_id, attention_row[0]),
                                )
                    except sqlite3.IntegrityError as exc:
                        raise CompanionInitiativeConflictError("Candidate identity conflicts with stored state.") from exc
                else:
                    existing = self._candidate(connection, row[0])
                    asserted = (initiative_type, dedupe_key, anchor_kind, anchor_id, anchor_revision, _aware_utc(eligible_at), None if expires_at is None else _aware_utc(expires_at), wording)
                    actual = (existing.type, existing.dedupe_key, existing.anchor_kind, existing.anchor_id, existing.anchor_revision, existing.eligible_at_utc, existing.expires_at_utc, existing.wording)
                    if asserted != actual:
                        raise CompanionInitiativeConflictError("Candidate identity has different stored semantics.")
            finally:
                connection.close()
        return self.get_candidate(identifier)

    def get_candidate(self, identifier: str) -> InitiativeCandidate:
        _id(identifier, "candidate identifier")
        connection = self._connect(True)
        try:
            result = self._candidate(connection, identifier)
        finally:
            connection.close()
        return result

    def candidate_for_event(self, event_id: str) -> InitiativeCandidate | None:
        """Return the candidate owning one fixed application event identity."""

        if not isinstance(event_id, str) or re.fullmatch(r"event-[0-9a-f]{32}", event_id) is None:
            raise CompanionInitiativeValidationError("Application event identifier is invalid.")
        if not self.exists:
            return None
        connection = self._connect(True)
        try:
            row = connection.execute(
                "SELECT id FROM initiative_candidates WHERE application_event_id=?",
                (event_id,),
            ).fetchone()
            return None if row is None else self._candidate(connection, row[0])
        finally:
            connection.close()

    def list_candidates(self) -> tuple[InitiativeCandidate, ...]:
        if not self.exists:
            return ()
        connection = self._connect(True)
        try:
            rows = connection.execute("SELECT id FROM initiative_candidates ORDER BY created_at_utc,id").fetchall()
            return tuple(self._candidate(connection, row[0]) for row in rows)
        finally:
            connection.close()

    def delivery_history(self) -> tuple[tuple[str, datetime], ...]:
        if not self.exists:
            return ()
        connection = self._connect(True)
        try:
            rows = connection.execute("SELECT type,delivered_at_utc FROM initiative_candidates WHERE delivered_at_utc IS NOT NULL ORDER BY delivered_at_utc,id").fetchall()
        finally:
            connection.close()
        return tuple((row[0], _parse(row[1])) for row in rows)

    def claim(self, identifier: str, *, expected_revision: int, owner: str, target_chat_id: str, target_chat_revision: int, lease_until: datetime) -> InitiativeCandidate:
        _id(identifier, "candidate identifier"); _id(owner, "lease owner"); _id(target_chat_id, "chat identifier")
        _positive_revision(target_chat_revision)
        now = _aware_utc(self._clock()); lease_until = _aware_utc(lease_until)
        if lease_until <= now or lease_until - now > MAX_LEASE:
            raise CompanionInitiativeValidationError("Claim lease is invalid.")
        with self._lock:
            connection = self._connect(False)
            try:
                connection.execute("BEGIN IMMEDIATE")
                candidate = self._candidate(connection, identifier)
                if candidate.state != "pending" or candidate.revision != expected_revision or candidate.eligible_at_utc > now or (candidate.expires_at_utc is not None and candidate.expires_at_utc <= now):
                    raise CompanionInitiativeConflictError("Candidate cannot be claimed from this revision.")
                if connection.execute("SELECT 1 FROM initiative_candidates WHERE state='delivering' OR state='delivered' LIMIT 1").fetchone() is not None:
                    raise CompanionInitiativeConflictError("Another initiative is unresolved.")
                connection.execute("UPDATE initiative_candidates SET state='delivering',revision=revision+1,target_chat_id=?,target_chat_revision=?,lease_owner=?,lease_expires_at_utc=? WHERE id=? AND revision=?", (target_chat_id, target_chat_revision, owner, _stamp(lease_until), identifier, expected_revision))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return self.get_candidate(identifier)

    def mark_delivered(self, identifier: str, *, expected_revision: int, owner: str, delivered_at: datetime | None = None) -> InitiativeCandidate:
        return self._finish_delivery(identifier, expected_revision, owner, _aware_utc(delivered_at or self._clock()))

    def release_claim(
        self,
        identifier: str,
        *,
        expected_revision: int,
        owner: str,
        disposition: str = "pending",
        reason: str | None = None,
    ) -> InitiativeCandidate:
        """Revision-safely release one claim whose archive append did not occur."""

        if disposition not in {"pending", "expired", "superseded"}:
            raise CompanionInitiativeValidationError("Claim disposition is invalid.")
        _id(identifier, "candidate identifier")
        _id(owner, "lease owner")
        if reason is not None and (
            not isinstance(reason, str) or _IDENTIFIER.fullmatch(reason) is None
        ):
            raise CompanionInitiativeValidationError("Candidate terminal reason is invalid.")
        if disposition == "pending" and reason is not None:
            raise CompanionInitiativeValidationError(
                "A retryable candidate cannot have a terminal reason."
            )
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    candidate = self._candidate(connection, identifier)
                    if (
                        candidate.state != "delivering"
                        or candidate.revision != expected_revision
                        or candidate.lease_owner != owner
                    ):
                        raise CompanionInitiativeConflictError(
                            "Delivery claim changed or belongs to another process."
                        )
                    connection.execute(
                        "UPDATE initiative_candidates SET state=?,revision=revision+1,"
                        "target_chat_id=CASE WHEN ?='pending' THEN NULL ELSE target_chat_id END,"
                        "target_chat_revision=CASE WHEN ?='pending' THEN NULL ELSE target_chat_revision END,"
                        "lease_owner=NULL,lease_expires_at_utc=NULL,terminal_reason=? "
                        "WHERE id=? AND revision=?",
                        (
                            disposition,
                            disposition,
                            disposition,
                            reason,
                            identifier,
                            expected_revision,
                        ),
                    )
            finally:
                connection.close()
        return self.get_candidate(identifier)

    def claim_reply_context(
        self, chat_id: str, *, at: datetime | None = None
    ) -> InitiativeReplyContext | None:
        """Acknowledge and return the one delivered initiative for this chat."""

        _id(chat_id, "chat identifier")
        now = _stamp(at or self._clock())
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    rows = connection.execute(
                        "SELECT id FROM initiative_candidates WHERE state='delivered' "
                        "ORDER BY delivered_at_utc,id"
                    ).fetchall()
                    if len(rows) > 1:
                        raise CompanionInitiativeCorruptError(
                            "Companion Initiative has multiple unresolved deliveries."
                        )
                    if not rows:
                        return None
                    candidate = self._candidate(connection, rows[0][0])
                    if candidate.target_chat_id != chat_id:
                        return None
                    changed = connection.execute(
                        "UPDATE initiative_candidates SET state='acknowledged',"
                        "revision=revision+1,acknowledged_at_utc=? "
                        "WHERE id=? AND revision=? AND state='delivered'",
                        (now, candidate.identifier, candidate.revision),
                    ).rowcount
                    if changed != 1:
                        raise CompanionInitiativeConflictError(
                            "Initiative reply context was already consumed."
                        )
                    return InitiativeReplyContext(
                        candidate.identifier,
                        candidate.type,
                        candidate.application_event_id,
                        candidate.wording,
                        candidate.anchor_kind,
                        candidate.anchor_id,
                        candidate.anchor_revision,
                    )
            finally:
                connection.close()

    def transition_candidate(
        self,
        identifier: str,
        state: str,
        *,
        expected_revision: int,
        reason: str | None = None,
        at: datetime | None = None,
    ) -> InitiativeCandidate:
        allowed = {
            "pending": {"dismissed", "expired", "superseded"},
            "delivered": {"acknowledged", "dismissed"},
        }
        if state not in {"acknowledged", "dismissed", "expired", "superseded"}:
            raise CompanionInitiativeValidationError("Candidate transition is invalid.")
        if reason is not None and (not isinstance(reason, str) or _IDENTIFIER.fullmatch(reason) is None):
            raise CompanionInitiativeValidationError("Candidate terminal reason is invalid.")
        now = _stamp(at or self._clock())
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    candidate = self._candidate(connection, identifier)
                    if candidate.revision != expected_revision or state not in allowed.get(candidate.state, set()):
                        raise CompanionInitiativeConflictError("Candidate changed or cannot make that transition.")
                    acknowledged = now if state in {"acknowledged", "dismissed"} else None
                    connection.execute(
                        "UPDATE initiative_candidates SET state=?,revision=revision+1,acknowledged_at_utc=?,terminal_reason=?,lease_owner=NULL,lease_expires_at_utc=NULL WHERE id=? AND revision=?",
                        (state, acknowledged, reason, identifier, expected_revision),
                    )
            finally:
                connection.close()
        return self.get_candidate(identifier)

    def reconcile_stale_claim(self, identifier: str, *, expected_revision: int, observation: str, observed_at: datetime | None = None) -> InitiativeCandidate:
        if observation not in RECOVERY_OBSERVATIONS:
            raise CompanionInitiativeValidationError("Recovery observation is invalid.")
        now = _aware_utc(observed_at or self._clock())
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    candidate = self._candidate(connection, identifier)
                    if candidate.state != "delivering" or candidate.revision != expected_revision or candidate.lease_expires_at_utc is None or candidate.lease_expires_at_utc > now:
                        raise CompanionInitiativeConflictError("Only an expired claim at the expected revision may be reconciled.")
                    if observation == "matching":
                        state, delivered, reason = "delivered", _stamp(now), None
                    elif observation == "conflict":
                        state, delivered, reason = "failed", None, "event_semantics_conflict"
                    elif candidate.expires_at_utc is not None and candidate.expires_at_utc <= now:
                        state, delivered, reason = "expired", None, "eligibility_expired"
                    else:
                        state, delivered, reason = "pending", None, None
                    connection.execute(
                        "UPDATE initiative_candidates SET state=?,revision=revision+1,"
                        "target_chat_id=CASE WHEN ?='pending' THEN NULL ELSE target_chat_id END,"
                        "target_chat_revision=CASE WHEN ?='pending' THEN NULL ELSE target_chat_revision END,"
                        "lease_owner=NULL,lease_expires_at_utc=NULL,"
                        "delivered_at_utc=COALESCE(delivered_at_utc,?),terminal_reason=? "
                        "WHERE id=? AND revision=?",
                        (
                            state, state, state, delivered, reason, identifier,
                            expected_revision,
                        ),
                    )
            finally:
                connection.close()
        return self.get_candidate(identifier)

    def stale_claims(self, *, at: datetime | None = None) -> tuple[InitiativeCandidate, ...]:
        if not self.exists:
            return ()
        now = _stamp(at or self._clock())
        connection = self._connect(True)
        try:
            rows = connection.execute("SELECT id FROM initiative_candidates WHERE state='delivering' AND lease_expires_at_utc<=? ORDER BY lease_expires_at_utc,id", (now,)).fetchall()
            return tuple(self._candidate(connection, row[0]) for row in rows)
        finally:
            connection.close()

    def recover_startup(self, observe_event: Callable[[InitiativeCandidate], str] | None, *, at: datetime | None = None) -> tuple[InitiativeCandidate, ...]:
        stale = self.stale_claims(at=at)
        if observe_event is None:  # uncertainty preserves the durable fence
            return stale
        return tuple(self.reconcile_stale_claim(item.identifier, expected_revision=item.revision, observation=observe_event(item), observed_at=at) for item in stale)

    @contextmanager
    def maintenance_guard(self) -> Iterator[None]:
        with self._lock:
            if self.exists:
                connection = self._connect(True); connection.close()
            yield

    def _finish_delivery(self, identifier: str, revision: int, owner: str, at: datetime) -> InitiativeCandidate:
        _id(owner, "lease owner")
        with self._lock:
            connection = self._connect(False)
            try:
                with connection:
                    candidate = self._candidate(connection, identifier)
                    if candidate.state != "delivering" or candidate.revision != revision or candidate.lease_owner != owner or candidate.lease_expires_at_utc is None or candidate.lease_expires_at_utc < at:
                        raise CompanionInitiativeConflictError("Delivery claim is stale or owned by another process.")
                    connection.execute("UPDATE initiative_candidates SET state='delivered',revision=revision+1,delivered_at_utc=?,lease_owner=NULL,lease_expires_at_utc=NULL WHERE id=? AND revision=?", (_stamp(at), identifier, revision))
                    connection.execute(
                        "UPDATE attention_items SET surfaced_material_key=(SELECT material_key "
                        "FROM initiative_candidate_attention WHERE candidate_id=? AND attention_id=attention_items.id),"
                        "last_surfaced_at_utc=?,revision=revision+1,updated_at_utc=? "
                        "WHERE id IN (SELECT attention_id FROM initiative_candidate_attention WHERE candidate_id=?)",
                        (identifier, _stamp(at), _stamp(at), identifier),
                    )
            finally:
                connection.close()
        return self.get_candidate(identifier)

    @staticmethod
    def _candidate(connection: sqlite3.Connection, identifier: str) -> InitiativeCandidate:
        row = connection.execute("SELECT id,type,dedupe_key,anchor_kind,anchor_id,anchor_revision,eligible_at_utc,expires_at_utc,state,revision,application_event_id,wording,target_chat_id,target_chat_revision,lease_owner,lease_expires_at_utc,created_at_utc,delivered_at_utc,acknowledged_at_utc,terminal_reason FROM initiative_candidates WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise CompanionInitiativeConflictError("Candidate was not found.")
        return InitiativeCandidate(row[0], row[1], row[2], row[3], row[4], row[5], _parse(row[6]), _parse_optional(row[7]), row[8], row[9], row[10], row[11], row[12], row[13], row[14], _parse_optional(row[15]), _parse(row[16]), _parse_optional(row[17]), _parse_optional(row[18]), row[19])

    @staticmethod
    def _reserve_capacity(connection: sqlite3.Connection) -> None:
        count = connection.execute("SELECT COUNT(*) FROM initiative_candidates").fetchone()[0]
        if count < MAX_CANDIDATES:
            return
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        row = connection.execute(f"SELECT id FROM initiative_candidates WHERE state IN ({placeholders}) ORDER BY COALESCE(acknowledged_at_utc,delivered_at_utc,created_at_utc),id LIMIT 1", tuple(TERMINAL_STATES)).fetchone()
        if row is None:
            raise CompanionInitiativeConflictError("Companion Initiative active history is full.")
        connection.execute("DELETE FROM initiative_candidates WHERE id=?", (row[0],))

    @staticmethod
    def _reserve_attention_capacity(connection: sqlite3.Connection) -> None:
        count = connection.execute("SELECT COUNT(*) FROM attention_items").fetchone()[0]
        if count < MAX_ATTENTION_ITEMS:
            return
        row = connection.execute(
            "SELECT id FROM attention_items WHERE state IN ('dismissed','reviewed','resolved') "
            "ORDER BY updated_at_utc,id LIMIT 1"
        ).fetchone()
        if row is None:
            raise CompanionInitiativeConflictError("Companion attention history is full.")
        connection.execute("DELETE FROM attention_items WHERE id=?", (row[0],))

    def _initialize_atomic(self, settings: InitiativeSettings, now: str) -> None:
        temporary: Path | None = None
        try:
            path = self._safe_parent(); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(path.parent, 0o700); self._safe_parent()
            temporary = path.with_name(f".{path.name}.incomplete-{secrets.token_hex(16)}")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
            connection = sqlite3.connect(temporary, timeout=5.0)
            try:
                _connection_settings(connection)
                with connection:
                    for statement in _SCHEMA.values(): connection.execute(statement)
                    connection.execute("INSERT INTO initiative_metadata VALUES ('schema_version',?)", (str(SCHEMA_VERSION),))
                    connection.execute("INSERT INTO initiative_settings VALUES (1,1,?,?,?,?,?,?,?,?,?,?,?,?)", (_bool(settings.master_enabled), _bool(settings.morning_enabled), _bool(settings.resume_enabled), _bool(settings.long_silence_enabled), _bool(settings.night_owl_findings_enabled), _time_text(settings.morning_start), _time_text(settings.morning_end), _time_text(settings.quiet_start), _time_text(settings.quiet_end), _optional_stamp(settings.snoozed_until_utc), now, now))
                    connection.execute("INSERT INTO initiative_activity VALUES (1,1,?,'settings_change')", (now,))
                self._validate_schema(connection)
            finally: connection.close()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as stream: os.fsync(stream.fileno())
            os.link(temporary, path); temporary.unlink(); temporary = None
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
            self._safe_path(True)
        except CompanionInitiativeError: raise
        except FileExistsError as exc: raise CompanionInitiativeConflictError("Companion Initiative store already exists.") from exc
        except (OSError, sqlite3.Error) as exc: raise CompanionInitiativeUnavailableError("Tori could not initialize Companion Initiative state.") from exc
        finally:
            if temporary is not None:
                try: temporary.unlink()
                except FileNotFoundError: pass

    def _connect(self, readonly: bool) -> sqlite3.Connection:
        path = self._safe_path(True); assert path is not None
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{quote(os.fspath(path), safe='/')}?mode=ro", uri=True, timeout=5.0) if readonly else sqlite3.connect(path, timeout=5.0, isolation_level="DEFERRED")
            connection.execute("PRAGMA foreign_keys=ON")
            version = self._validate_schema(connection)
            if not readonly:
                _connection_settings(connection)
                if version == 1:
                    self._migrate_v1(connection)
                    version = self._validate_schema(connection)
                if version == 2:
                    self._migrate_v2(connection)
                    version = self._validate_schema(connection)
                if version == 3:
                    self._migrate_v3(connection)
                    self._validate_schema(connection)
            result, connection = connection, None
            return result
        except CompanionInitiativeError: raise
        except sqlite3.DatabaseError as exc: raise CompanionInitiativeCorruptError("Companion Initiative state is invalid; it was not repaired.") from exc
        except (OSError, sqlite3.Error) as exc: raise CompanionInitiativeUnavailableError() from exc
        finally:
            if connection is not None: connection.close()

    def _safe_parent(self) -> Path:
        raw = os.fspath(self._path)
        if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts: raise CompanionInitiativeUnavailableError("Companion Initiative path is unsafe.")
        path = Path(os.path.abspath(os.path.normpath(raw))); current = Path(path.anchor); missing = False
        for component in path.parent.parts[1:]:
            current /= component
            if missing: continue
            try: info = os.lstat(current)
            except FileNotFoundError: missing = True; continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode): raise CompanionInitiativeUnavailableError("Companion Initiative parent path is unsafe.")
        if not missing:
            info = os.lstat(path.parent)
            if info.st_uid != os.geteuid() or info.st_mode & 0o022: raise CompanionInitiativeUnavailableError("Companion Initiative parent is not owner-controlled.")
        return path

    def _safe_path(self, require_existing: bool) -> Path | None:
        path = self._safe_parent()
        try: info = os.lstat(path)
        except FileNotFoundError:
            if require_existing: raise CompanionInitiativeUnavailableError()
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise CompanionInitiativeUnavailableError("Companion Initiative store file is unsafe.")
        return path

    @staticmethod
    def _migrate_v1(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for key, statement in _SCHEMA_V2.items():
                if key not in _SCHEMA_V1:
                    connection.execute(statement)
            connection.execute(
                "UPDATE initiative_metadata SET value=? WHERE key='schema_version' AND value='1'",
                ("2",),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise CompanionInitiativeUnavailableError(
                "Companion Initiative state could not be upgraded safely."
            ) from exc

    @staticmethod
    def _migrate_v2(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for name in (
                "initiative_candidates_delivery",
                "initiative_candidates_lease",
                "initiative_candidates_type",
            ):
                connection.execute(f"DROP INDEX {name}")
            connection.execute(
                "ALTER TABLE initiative_settings RENAME TO initiative_settings_v2"
            )
            connection.execute(
                "ALTER TABLE initiative_candidates RENAME TO initiative_candidates_v2"
            )
            connection.execute(_SCHEMA[("table", "initiative_settings")])
            connection.execute(_SCHEMA[("table", "initiative_candidates")])
            connection.execute(
                "INSERT INTO initiative_settings SELECT singleton,revision,master_enabled,"
                "morning_enabled,resume_enabled,long_silence_enabled,0,morning_start,"
                "morning_end,quiet_start,quiet_end,snoozed_until_utc,created_at_utc,"
                "updated_at_utc FROM initiative_settings_v2"
            )
            connection.execute(
                "INSERT INTO initiative_candidates SELECT * FROM initiative_candidates_v2"
            )
            connection.execute("DROP TABLE initiative_settings_v2")
            connection.execute("DROP TABLE initiative_candidates_v2")
            for key in (
                ("index", "initiative_candidates_delivery"),
                ("index", "initiative_candidates_lease"),
                ("index", "initiative_candidates_type"),
            ):
                connection.execute(_SCHEMA[key])
            connection.execute(
                "UPDATE initiative_metadata SET value='3' "
                "WHERE key='schema_version' AND value='2'"
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise CompanionInitiativeUnavailableError(
                "Companion Initiative state could not be upgraded safely."
            ) from exc

    @staticmethod
    def _migrate_v3(connection: sqlite3.Connection) -> None:
        try:
            connection.execute("BEGIN IMMEDIATE")
            for key, statement in _SCHEMA.items():
                if key not in _SCHEMA_V3:
                    connection.execute(statement)
            connection.execute(
                "UPDATE initiative_metadata SET value='4' "
                "WHERE key='schema_version' AND value='3'"
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise CompanionInitiativeUnavailableError(
                "Companion Initiative state could not be upgraded safely."
            ) from exc

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> int:
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",): raise CompanionInitiativeCorruptError()
            schema = {(row[0], row[1]): row[2] for row in connection.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
            metadata = connection.execute("SELECT key,value FROM initiative_metadata").fetchall()
            if schema == _SCHEMA and metadata == [("schema_version", str(SCHEMA_VERSION))]:
                version = SCHEMA_VERSION
            elif schema == _SCHEMA_V3 and metadata == [("schema_version", "3")]:
                version = 3
            elif schema == _SCHEMA_V2 and metadata == [("schema_version", "2")]:
                version = 2
            elif schema == _SCHEMA_V1 and metadata == [("schema_version", "1")]:
                version = 1
            else:
                raise CompanionInitiativeCorruptError("Companion Initiative schema is incompatible; it was not repaired.")
            if connection.execute("SELECT COUNT(*) FROM initiative_settings WHERE singleton=1").fetchone() != (1,) or connection.execute("SELECT COUNT(*) FROM initiative_activity WHERE singleton=1").fetchone() != (1,): raise CompanionInitiativeCorruptError()
            settings_row = connection.execute(
                "SELECT revision,master_enabled,morning_enabled,resume_enabled,"
                "long_silence_enabled,night_owl_findings_enabled,morning_start,"
                "morning_end,quiet_start,quiet_end,snoozed_until_utc "
                "FROM initiative_settings WHERE singleton=1"
                if version == SCHEMA_VERSION else
                "SELECT revision,master_enabled,morning_enabled,resume_enabled,"
                "long_silence_enabled,0,morning_start,morning_end,quiet_start,"
                "quiet_end,snoozed_until_utc FROM initiative_settings WHERE singleton=1"
            ).fetchone()
            _settings_from_row(settings_row)
            activity = connection.execute("SELECT activity_revision,last_meaningful_at_utc,last_kind FROM initiative_activity WHERE singleton=1").fetchone()
            if activity[0] < 0 or (activity[1] is None) != (activity[2] is None) or (activity[1] is not None and (activity[2] not in ACTIVITY_KINDS or _parse(activity[1]) is None)): raise CompanionInitiativeCorruptError()
            if version >= 2:
                signals = connection.execute(
                    "SELECT signal_key,kind,occurred_at_utc,activity_revision,recorded_at_utc FROM initiative_activity_signals"
                ).fetchall()
                if len(signals) > MAX_ACTIVITY_SIGNALS:
                    raise CompanionInitiativeCorruptError()
                for signal_key, kind, occurred, revision, recorded in signals:
                    if (
                        not isinstance(signal_key, str)
                        or re.fullmatch(r"[0-9a-f]{64}", signal_key) is None
                        or kind not in ACTIVITY_KINDS
                        or type(revision) is not int
                        or revision < 1
                    ):
                        raise CompanionInitiativeCorruptError()
                    _parse(occurred)
                    _parse(recorded)
            if version == SCHEMA_VERSION:
                attention_rows = connection.execute(
                    "SELECT * FROM attention_items"
                ).fetchall()
                if len(attention_rows) > MAX_ATTENTION_ITEMS:
                    raise CompanionInitiativeCorruptError()
                for row in attention_rows:
                    _attention_from_row(row)
            return version
        except CompanionInitiativeError: raise
        except (sqlite3.DatabaseError, TypeError, ValueError) as exc: raise CompanionInitiativeCorruptError() from exc


def _validate_settings(value: InitiativeSettings) -> None:
    for flag in (value.master_enabled, value.morning_enabled, value.resume_enabled, value.long_silence_enabled, value.night_owl_findings_enabled):
        if type(flag) is not bool: raise CompanionInitiativeValidationError("Initiative flags must be boolean.")
    if value.revision < 0: raise CompanionInitiativeValidationError("Settings revision is invalid.")
    for item in (value.morning_start, value.morning_end, value.quiet_start, value.quiet_end): _civil_time(item)
    if value.morning_start >= value.morning_end: raise CompanionInitiativeValidationError("Morning window must be a same-day window.")
    if value.quiet_start == value.quiet_end: raise CompanionInitiativeValidationError("Quiet-hours window cannot be empty.")
    if value.snoozed_until_utc is not None: _aware_utc(value.snoozed_until_utc)


def _validate_candidate_input(kind: str, key: str, eligible: datetime, expires: datetime | None, wording: str, anchor_kind: str | None, anchor_id: str | None, anchor_revision: int | None) -> None:
    if kind not in INITIATIVE_TYPES: raise CompanionInitiativeValidationError("Initiative type is invalid.")
    if not isinstance(key, str) or _DEDUPE_KEY.fullmatch(key) is None:
        raise CompanionInitiativeValidationError("Deduplication key is invalid.")
    eligible = _aware_utc(eligible)
    if expires is not None and _aware_utc(expires) <= eligible: raise CompanionInitiativeValidationError("Candidate expiry must follow eligibility.")
    if not isinstance(wording, str) or not wording.strip() or len(wording) > 280 or "\n" in wording: raise CompanionInitiativeValidationError("Candidate wording is invalid.")
    supplied = (anchor_kind is not None, anchor_id is not None, anchor_revision is not None)
    if any(supplied) and not all(supplied): raise CompanionInitiativeValidationError("Candidate anchor is incomplete.")
    if all(supplied): _id(anchor_kind, "anchor kind"); _id(anchor_id, "anchor identifier"); _positive_revision(anchor_revision)
    if kind == "resume" and not all(supplied): raise CompanionInitiativeValidationError("Resume candidate requires an anchor.")
    if kind != "resume" and any(supplied): raise CompanionInitiativeValidationError("Only resume candidates may carry an anchor.")


def _validate_attention_signal(value: AttentionSignal, source: str) -> AttentionSignal:
    if not isinstance(value, AttentionSignal) or value.source != source:
        raise CompanionInitiativeValidationError("Attention signal source is invalid.")
    if source not in ATTENTION_SOURCES:
        raise CompanionInitiativeValidationError("Attention source is invalid.")
    _id(value.source_object_id, "attention source object")
    _id(value.kind, "attention kind")
    if value.attention_class not in ATTENTION_CLASSES:
        raise CompanionInitiativeValidationError("Attention class is invalid.")
    if value.delivery_level not in DELIVERY_LEVELS:
        raise CompanionInitiativeValidationError("Attention delivery level is invalid.")
    _positive_revision(value.source_revision)
    if (
        not isinstance(value.material_key, str)
        or not value.material_key
        or len(value.material_key) > 256
        or any(ord(character) < 0x20 for character in value.material_key)
    ):
        raise CompanionInitiativeValidationError("Attention material key is invalid.")
    for text, maximum, label in (
        (value.title, 200, "title"), (value.summary, 500, "summary")
    ):
        if not isinstance(text, str) or not text.strip() or len(text) > maximum or "\x00" in text:
            raise CompanionInitiativeValidationError(f"Attention {label} is invalid.")
    if value.project_id is not None:
        _id(value.project_id, "attention project")
    _aware_utc(value.source_updated_at_utc)
    return value


def _attention_from_row(row: Sequence[object]) -> AttentionItem:
    value = AttentionItem(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
        str(row[5]), str(row[6]), str(row[7]), int(row[8]), str(row[9]),
        None if row[10] is None else str(row[10]), _parse(row[11]), str(row[12]),
        int(row[13]), None if row[14] is None else str(row[14]),
        _parse_optional(row[15]), _parse_optional(row[16]), _parse(row[17]),
        _parse(row[18]),
    )
    _validate_attention_signal(
        AttentionSignal(
            value.source, value.source_object_id, value.kind, value.title,
            value.summary, value.attention_class, value.delivery_level,
            value.source_revision, value.material_key,
            value.source_updated_at_utc, value.project_id,
        ),
        value.source,
    )
    if value.state not in ATTENTION_STATES:
        raise CompanionInitiativeCorruptError("Stored attention state is invalid.")
    if value.revision < 1:
        raise CompanionInitiativeCorruptError("Stored attention revision is invalid.")
    if value.surfaced_material_key is not None and len(value.surfaced_material_key) > 256:
        raise CompanionInitiativeCorruptError("Stored attention surface state is invalid.")
    return value


def _settings_from_row(row: Sequence[object]) -> InitiativeSettings:
    value = InitiativeSettings(int(row[0]), bool(row[1]), bool(row[2]), bool(row[3]), bool(row[4]), bool(row[5]), _parse_time(str(row[6])), _parse_time(str(row[7])), _parse_time(str(row[8])), _parse_time(str(row[9])), _parse_optional(row[10]))
    _validate_settings(value); return value


def _connection_settings(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=DELETE"); connection.execute("PRAGMA synchronous=FULL"); connection.execute("PRAGMA foreign_keys=ON")


def _zone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name or len(name) > 100: raise CompanionInitiativeValidationError("Timezone is invalid.")
    try: return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc: raise CompanionInitiativeValidationError("Timezone is unavailable.") from exc


def _civil_time(value: time) -> time:
    if not isinstance(value, time) or value.tzinfo is not None or value.second or value.microsecond: raise CompanionInitiativeValidationError("Civil time must use local hour and minute only.")
    return value


def _time_text(value: time) -> str: return _civil_time(value).strftime("%H:%M")
def _parse_time(value: str) -> time:
    try: parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError as exc: raise CompanionInitiativeCorruptError("Stored civil time is invalid.") from exc
    return parsed


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None: raise CompanionInitiativeValidationError("An aware timestamp is required.")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str: return _aware_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
def _optional_stamp(value: datetime | None) -> str | None: return None if value is None else _stamp(value)
def _parse(value: object) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None: raise CompanionInitiativeCorruptError("Stored timestamp is invalid.")
    return datetime.fromisoformat(value[:-1] + "+00:00")
def _parse_optional(value: object) -> datetime | None: return None if value is None else _parse(value)
def _bool(value: bool) -> int:
    if type(value) is not bool: raise CompanionInitiativeValidationError("A boolean is required.")
    return int(value)
def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None: raise CompanionInitiativeValidationError(f"{label.capitalize()} is invalid.")
    return value
def _positive_revision(value: object) -> int:
    if type(value) is not int or value < 1: raise CompanionInitiativeValidationError("Revision is invalid.")
    return value
