"""Canonical, versioned SQLite storage for Tori conversation archives."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import sqlite3
import stat
import unicodedata
from urllib.parse import quote, urlsplit


ARCHIVE_SCHEMA_VERSION = 7
PREVIOUS_ARCHIVE_SCHEMA_VERSION = 6
SCHEMA5_ARCHIVE_SCHEMA_VERSION = 5
SCHEMA4_ARCHIVE_SCHEMA_VERSION = 4
SCHEMA3_ARCHIVE_SCHEMA_VERSION = 3
LEGACY_ARCHIVE_SCHEMA_VERSION = 2
DEFAULT_ARCHIVE_DATABASE = Path("runtime/conversations/tori_conversations.db")
MAX_ARCHIVE_ENTRY_TEXT_LENGTH = 1_000_000
MAX_CHAT_LABEL_LENGTH = 80
MAX_SOURCE_FILENAME_LENGTH = 255
MAX_METADATA_TEXT_LENGTH = 255
MAX_WEB_QUERY_LENGTH = 500
MAX_WEB_TITLE_LENGTH = 500
MAX_WEB_URL_LENGTH = 4096
MAX_IDENTIFIER_ATTEMPTS = 5
MAX_INITIALIZATION_NAME_ATTEMPTS = 5
MAX_APPLICATION_EVENT_ID_LENGTH = 38
MAX_APPLICATION_EVENT_TYPE_LENGTH = 64
MAX_CONTEXT_JSON_LENGTH = 2048
MAX_PROJECT_TITLE_LENGTH = 120
MAX_PROJECT_OBJECTIVE_LENGTH = 1_000
MAX_PROJECT_CONTINUITY_LENGTH = 4_000
MAX_PROJECT_PHASE_LENGTH = 120
MAX_PROJECT_FOCUS_LENGTH = 1_000
MAX_PROJECT_CHECKPOINT_LENGTH = 2_000
MAX_PROJECT_DECISION_LENGTH = 2_000
MAX_PROJECT_QUESTION_LENGTH = 1_500
MAX_PROJECT_DISPOSITION_NOTE_LENGTH = 2_000
MAX_PROJECT_PLAN_ITEM_LENGTH = 1_000
MAX_PROJECT_PLAN_NOTE_LENGTH = 1_000
MAX_PROJECT_LINK_TARGET_ID_LENGTH = 255
MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH = 24_000
MAX_PROJECT_CONTEXT_RENDERED_LENGTH = 32_000
MAX_PROJECT_CONTEXT_RECEIPT_TOTAL_LENGTH = 64_000
EMPTY_PROJECT_CONTINUITY_BRIEF = (
    "Current focus\nNot yet recorded.\n\n"
    "Key decisions\nNone recorded.\n\n"
    "Open issues / blockers\nNone recorded.\n\n"
    "Next step\nNot yet recorded."
)
APPLICATION_EVENT_TYPES = frozenset({
    "reminder_due", "operational_result", "scheduled_work_proposal",
    "scheduled_work_created", "scheduled_work_creation_failed",
    "scheduled_work_result",
    "project_intent_clarification", "project_proposal", "project_result",
    "coding_work_proposal", "coding_work_result", "research_proposal", "research_result",
    "terminal_proposal_origin",
    "planning_read", "planning_proposal", "planning_result", "system_capability",
    "night_owl_findings_result", "night_owl_run_result",
    "calendar_information",
    "finance_read", "finance_proposal", "finance_result",
    "remote_chat_binding", "remote_chat_turn", "companion_initiative",
    "companion_attention_result",
})
LEGACY_APPLICATION_EVENT_TYPES = frozenset({
    "deep_research_started", "deep_research_clarification",
    "deep_research_control", "deep_research_result",
})

ARCHIVE_ROLES = frozenset({"user", "assistant", "system", "warning", "error"})
_IDENTIFIER_PATTERN = re.compile(r"^chat-[0-9a-f]{32}$")
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GREETING_PREFIX_PATTERN = re.compile(
    r"^(?:hi|hello|hey|good morning|good afternoon|good evening)(?:\s+again)?"
    r"(?:,?\s+tori(?:[!.?,:;\s-]+|$)|[!.?,:;-]+(?:\s+|$)|$)",
    re.IGNORECASE,
)
_INTENT_PREFIX_PATTERN = re.compile(
    r"^(?:i (?:have (?:a|another) question|want to|wanted to|would like to|need to)|"
    r"i(?:'|’)d like to|we (?:need to|want to|should)|let(?:'|’)s|"
    r"can you(?: help me(?: with)?)?|could you|please)\s+",
    re.IGNORECASE,
)
_PROVISIONAL_CHAT_LABELS = frozenset({"Just checking in", "Question"})

_METADATA_SQL = """
CREATE TABLE archive_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_LEGACY_CHATS_SQL = """
CREATE TABLE chats (
    identifier TEXT PRIMARY KEY
        CHECK (
            length(identifier) = 37
            AND substr(identifier, 1, 5) = 'chat-'
            AND substr(identifier, 6) NOT GLOB '*[^0-9a-f]*'
        ),
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    first_provider TEXT NOT NULL,
    first_model TEXT NOT NULL,
    latest_provider TEXT NOT NULL,
    latest_model TEXT NOT NULL,
    entry_count INTEGER NOT NULL
        CHECK (typeof(entry_count) = 'integer' AND entry_count >= 2),
    completed_turn_count INTEGER NOT NULL
        CHECK (typeof(completed_turn_count) = 'integer' AND completed_turn_count >= 1),
    CHECK (created_at <= updated_at),
    CHECK (last_opened_at IS NULL OR
           (created_at <= last_opened_at AND last_opened_at <= updated_at))
)
"""
_SCHEMA3_CHATS_SQL = """
CREATE TABLE chats (
    identifier TEXT PRIMARY KEY
        CHECK (
            length(identifier) = 37
            AND substr(identifier, 1, 5) = 'chat-'
            AND substr(identifier, 6) NOT GLOB '*[^0-9a-f]*'
        ),
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    first_provider TEXT,
    first_model TEXT,
    latest_provider TEXT,
    latest_model TEXT,
    selected_provider TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    entry_count INTEGER NOT NULL
        CHECK (typeof(entry_count) = 'integer' AND entry_count >= 2),
    completed_turn_count INTEGER NOT NULL
        CHECK (typeof(completed_turn_count) = 'integer' AND completed_turn_count >= 0),
    CHECK ((completed_turn_count = 0
            AND first_provider IS NULL AND first_model IS NULL
            AND latest_provider IS NULL AND latest_model IS NULL)
        OR (completed_turn_count > 0
            AND first_provider IS NOT NULL AND first_model IS NOT NULL
            AND latest_provider IS NOT NULL AND latest_model IS NOT NULL)),
    CHECK (created_at <= updated_at),
    CHECK (last_opened_at IS NULL OR
           (created_at <= last_opened_at AND last_opened_at <= updated_at))
)
"""
_SCHEMA5_CHATS_SQL = """
CREATE TABLE chats (
    identifier TEXT PRIMARY KEY
        CHECK (
            length(identifier) = 37
            AND substr(identifier, 1, 5) = 'chat-'
            AND substr(identifier, 6) NOT GLOB '*[^0-9a-f]*'
        ),
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    first_provider TEXT,
    first_model TEXT,
    latest_provider TEXT,
    latest_model TEXT,
    selected_provider TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    entry_count INTEGER NOT NULL
        CHECK (typeof(entry_count) = 'integer' AND entry_count >= 2),
    completed_turn_count INTEGER NOT NULL
        CHECK (typeof(completed_turn_count) = 'integer' AND completed_turn_count >= 0),
    selected_context_policy TEXT NOT NULL
        CHECK (selected_context_policy = 'auto' OR (
            substr(selected_context_policy, 1, 6) = 'fixed:'
            AND length(selected_context_policy) > 6
            AND substr(selected_context_policy, 7) NOT GLOB '*[^0-9]*'
            AND CAST(substr(selected_context_policy, 7) AS INTEGER)
                BETWEEN 4096 AND 1048576
        )),
    CHECK ((completed_turn_count = 0
            AND first_provider IS NULL AND first_model IS NULL
            AND latest_provider IS NULL AND latest_model IS NULL)
        OR (completed_turn_count > 0
            AND first_provider IS NOT NULL AND first_model IS NOT NULL
            AND latest_provider IS NOT NULL AND latest_model IS NOT NULL)),
    CHECK (created_at <= updated_at),
    CHECK (last_opened_at IS NULL OR
           (created_at <= last_opened_at AND last_opened_at <= updated_at))
)
"""
_CHATS_SQL = """
CREATE TABLE chats (
    identifier TEXT PRIMARY KEY
        CHECK (
            length(identifier) = 37
            AND substr(identifier, 1, 5) = 'chat-'
            AND substr(identifier, 6) NOT GLOB '*[^0-9a-f]*'
        ),
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    first_provider TEXT,
    first_model TEXT,
    latest_provider TEXT,
    latest_model TEXT,
    selected_provider TEXT NOT NULL,
    selected_model TEXT NOT NULL,
    entry_count INTEGER NOT NULL
        CHECK (typeof(entry_count) = 'integer' AND entry_count >= 2),
    completed_turn_count INTEGER NOT NULL
        CHECK (typeof(completed_turn_count) = 'integer' AND completed_turn_count >= 0),
    selected_context_policy TEXT NOT NULL
        CHECK (selected_context_policy = 'auto' OR (
            substr(selected_context_policy, 1, 6) = 'fixed:'
            AND length(selected_context_policy) > 6
            AND substr(selected_context_policy, 7) NOT GLOB '*[^0-9]*'
            AND CAST(substr(selected_context_policy, 7) AS INTEGER)
                BETWEEN 4096 AND 1048576
        )),
    project_id TEXT REFERENCES projects(identifier) ON DELETE SET NULL,
    CHECK ((completed_turn_count = 0
            AND first_provider IS NULL AND first_model IS NULL
            AND latest_provider IS NULL AND latest_model IS NULL)
        OR (completed_turn_count > 0
            AND first_provider IS NOT NULL AND first_model IS NOT NULL
            AND latest_provider IS NOT NULL AND latest_model IS NOT NULL)),
    CHECK (created_at <= updated_at),
    CHECK (last_opened_at IS NULL OR
           (created_at <= last_opened_at AND last_opened_at <= updated_at))
)
"""
_PROJECTS_SQL = f"""
CREATE TABLE projects (
    identifier TEXT PRIMARY KEY CHECK (
        length(identifier) = 40
        AND substr(identifier, 1, 8) = 'project-'
        AND substr(identifier, 9) NOT GLOB '*[^0-9a-f]*'
    ),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND {MAX_PROJECT_TITLE_LENGTH}),
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'completed')),
    objective TEXT NOT NULL CHECK (length(objective) BETWEEN 1 AND {MAX_PROJECT_OBJECTIVE_LENGTH}),
    continuity_brief TEXT NOT NULL CHECK (length(continuity_brief) <= {MAX_PROJECT_CONTINUITY_LENGTH}),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_STATE_SQL = f"""
CREATE TABLE project_state (
    project_id TEXT PRIMARY KEY NOT NULL,
    phase TEXT CHECK (
        phase IS NULL OR length(phase) BETWEEN 1 AND {MAX_PROJECT_PHASE_LENGTH}
    ),
    current_focus TEXT CHECK (
        current_focus IS NULL OR length(current_focus) BETWEEN 1 AND {MAX_PROJECT_FOCUS_LENGTH}
    ),
    checkpoint TEXT CHECK (
        checkpoint IS NULL OR length(checkpoint) BETWEEN 1 AND {MAX_PROJECT_CHECKPOINT_LENGTH}
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(identifier) ON DELETE CASCADE,
    CHECK (phase IS NOT NULL OR current_focus IS NOT NULL OR checkpoint IS NOT NULL),
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_DECISIONS_SQL = f"""
CREATE TABLE project_decisions (
    identifier TEXT PRIMARY KEY NOT NULL CHECK (
        length(identifier) = 41
        AND substr(identifier, 1, 9) = 'decision-'
        AND substr(identifier, 10) NOT GLOB '*[^0-9a-f]*'
    ),
    project_id TEXT NOT NULL,
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND {MAX_PROJECT_DECISION_LENGTH}),
    importance TEXT NOT NULL CHECK (importance IN ('normal', 'important')),
    state TEXT NOT NULL CHECK (state IN ('active', 'superseded')),
    supersedes_decision_id TEXT UNIQUE,
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(identifier) ON DELETE CASCADE,
    FOREIGN KEY (project_id, supersedes_decision_id)
        REFERENCES project_decisions(project_id, identifier),
    UNIQUE (project_id, identifier),
    CHECK (supersedes_decision_id IS NULL OR supersedes_decision_id != identifier),
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_QUESTIONS_SQL = f"""
CREATE TABLE project_questions (
    identifier TEXT PRIMARY KEY NOT NULL CHECK (
        length(identifier) = 41
        AND substr(identifier, 1, 9) = 'question-'
        AND substr(identifier, 10) NOT GLOB '*[^0-9a-f]*'
    ),
    project_id TEXT NOT NULL REFERENCES projects(identifier) ON DELETE CASCADE,
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND {MAX_PROJECT_QUESTION_LENGTH}),
    state TEXT NOT NULL CHECK (state IN ('open', 'resolved', 'deferred', 'dismissed')),
    disposition_note TEXT CHECK (
        disposition_note IS NULL
        OR length(disposition_note) BETWEEN 1 AND {MAX_PROJECT_DISPOSITION_NOTE_LENGTH}
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_PLAN_ITEMS_SQL = f"""
CREATE TABLE project_plan_items (
    identifier TEXT PRIMARY KEY NOT NULL CHECK (
        length(identifier) = 42
        AND substr(identifier, 1, 10) = 'plan-item-'
        AND substr(identifier, 11) NOT GLOB '*[^0-9a-f]*'
    ),
    project_id TEXT NOT NULL REFERENCES projects(identifier) ON DELETE CASCADE,
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND {MAX_PROJECT_PLAN_ITEM_LENGTH}),
    state TEXT NOT NULL CHECK (
        state IN ('planned', 'active', 'blocked', 'deferred', 'completed')
    ),
    state_note TEXT CHECK (
        state_note IS NULL OR length(state_note) BETWEEN 1 AND {MAX_PROJECT_PLAN_NOTE_LENGTH}
    ),
    sort_order INTEGER NOT NULL CHECK (
        typeof(sort_order) = 'integer' AND sort_order >= 0
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_LINKS_SQL = f"""
CREATE TABLE project_links (
    identifier TEXT PRIMARY KEY NOT NULL CHECK (
        length(identifier) = 45
        AND substr(identifier, 1, 13) = 'project-link-'
        AND substr(identifier, 14) NOT GLOB '*[^0-9a-f]*'
    ),
    project_id TEXT NOT NULL REFERENCES projects(identifier) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (
        target_type IN ('night_owl_finding', 'scheduled_work_definition', 'knowledge_source')
    ),
    target_id TEXT NOT NULL CHECK (
        length(target_id) BETWEEN 1 AND {MAX_PROJECT_LINK_TARGET_ID_LENGTH}
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, target_type, target_id),
    CHECK (created_at <= updated_at)
)
"""
_PROJECT_CONTEXT_RECEIPTS_SQL = f"""
CREATE TABLE project_context_receipts (
    chat_id TEXT NOT NULL,
    assistant_sequence INTEGER NOT NULL CHECK (
        typeof(assistant_sequence) = 'integer' AND assistant_sequence >= 0
    ),
    project_id TEXT NOT NULL,
    project_revision INTEGER NOT NULL CHECK (
        typeof(project_revision) = 'integer' AND project_revision >= 1
    ),
    estimator_version TEXT NOT NULL CHECK (length(estimator_version) BETWEEN 1 AND 64),
    budget_tokens INTEGER NOT NULL CHECK (
        typeof(budget_tokens) = 'integer' AND budget_tokens >= 1
    ),
    stable_json TEXT NOT NULL CHECK (
        length(stable_json) BETWEEN 2 AND {MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH}
    ),
    working_json TEXT NOT NULL CHECK (
        length(working_json) BETWEEN 2 AND {MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH}
    ),
    historical_json TEXT NOT NULL CHECK (
        length(historical_json) BETWEEN 2 AND {MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH}
    ),
    omitted_json TEXT NOT NULL CHECK (
        length(omitted_json) BETWEEN 2 AND {MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH}
    ),
    rendered_context TEXT NOT NULL CHECK (
        length(rendered_context) BETWEEN 1 AND {MAX_PROJECT_CONTEXT_RENDERED_LENGTH}
    ),
    rendered_digest TEXT NOT NULL CHECK (
        length(rendered_digest) = 64
        AND rendered_digest NOT GLOB '*[^0-9a-f]*'
    ),
    created_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, assistant_sequence),
    FOREIGN KEY (chat_id, assistant_sequence)
        REFERENCES transcript_entries(chat_id, sequence) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(identifier) ON DELETE CASCADE,
    CHECK (
        length(stable_json) + length(working_json) + length(historical_json)
        + length(omitted_json) + length(rendered_context)
        <= {MAX_PROJECT_CONTEXT_RECEIPT_TOTAL_LENGTH}
    )
)
"""
_PROJECT_DECISIONS_STATE_INDEX_SQL = """
CREATE INDEX project_decisions_state_index
ON project_decisions(project_id, state, updated_at)
"""
_PROJECT_DECISIONS_IMMUTABILITY_TRIGGER_SQL = """
CREATE TRIGGER project_decisions_immutable_fields
BEFORE UPDATE OF identifier, project_id, text, supersedes_decision_id, created_at
ON project_decisions
BEGIN
    SELECT RAISE(ABORT, 'immutable Project decision fields cannot change');
END
"""
_PROJECT_QUESTIONS_STATE_INDEX_SQL = """
CREATE INDEX project_questions_state_index
ON project_questions(project_id, state, updated_at)
"""
_PROJECT_PLAN_ITEMS_STATE_INDEX_SQL = """
CREATE INDEX project_plan_items_state_index
ON project_plan_items(project_id, state, updated_at)
"""
_PROJECT_PLAN_ITEMS_ORDER_INDEX_SQL = """
CREATE INDEX project_plan_items_order_index
ON project_plan_items(project_id, sort_order, identifier)
"""
_PROJECT_CONTEXT_RECEIPTS_PROJECT_INDEX_SQL = """
CREATE INDEX project_context_receipts_project_index
ON project_context_receipts(project_id)
"""
_ENTRIES_SQL = f"""
CREATE TABLE transcript_entries (
    chat_id TEXT NOT NULL,
    sequence INTEGER NOT NULL
        CHECK (typeof(sequence) = 'integer' AND sequence >= 0),
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant', 'system', 'warning', 'error')),
    text TEXT NOT NULL
        CHECK (length(text) BETWEEN 1 AND {MAX_ARCHIVE_ENTRY_TEXT_LENGTH}),
    sources_json TEXT,
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    application_event_id TEXT,
    application_event_type TEXT,
    context_json TEXT,
    PRIMARY KEY (chat_id, sequence),
    FOREIGN KEY (chat_id) REFERENCES chats(identifier) ON DELETE CASCADE,
    CHECK ((application_event_id IS NULL) = (application_event_type IS NULL)),
    CHECK (application_event_id IS NULL OR (
        role = 'assistant' AND sources_json IS NULL AND provider IS NULL AND model IS NULL
        AND context_json IS NULL
        AND length(application_event_id) = 38
        AND substr(application_event_id, 1, 6) = 'event-'
        AND substr(application_event_id, 7) NOT GLOB '*[^0-9a-f]*'
        AND length(application_event_type) BETWEEN 1 AND {MAX_APPLICATION_EVENT_TYPE_LENGTH}
    ))
)
"""
_SCHEMA3_ENTRIES_SQL = f"""
CREATE TABLE transcript_entries (
    chat_id TEXT NOT NULL,
    sequence INTEGER NOT NULL
        CHECK (typeof(sequence) = 'integer' AND sequence >= 0),
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant', 'system', 'warning', 'error')),
    text TEXT NOT NULL
        CHECK (length(text) BETWEEN 1 AND {MAX_ARCHIVE_ENTRY_TEXT_LENGTH}),
    sources_json TEXT,
    provider TEXT,
    model TEXT,
    created_at TEXT NOT NULL,
    application_event_id TEXT,
    application_event_type TEXT,
    PRIMARY KEY (chat_id, sequence),
    FOREIGN KEY (chat_id) REFERENCES chats(identifier) ON DELETE CASCADE,
    CHECK ((application_event_id IS NULL) = (application_event_type IS NULL)),
    CHECK (application_event_id IS NULL OR (
        role = 'assistant' AND sources_json IS NULL AND provider IS NULL AND model IS NULL
        AND length(application_event_id) = 38
        AND substr(application_event_id, 1, 6) = 'event-'
        AND substr(application_event_id, 7) NOT GLOB '*[^0-9a-f]*'
        AND length(application_event_type) BETWEEN 1 AND {MAX_APPLICATION_EVENT_TYPE_LENGTH}
    ))
)
"""
_EVENT_INDEX_SQL = """
CREATE UNIQUE INDEX transcript_entries_application_event_id_index
ON transcript_entries(application_event_id)
WHERE application_event_id IS NOT NULL
"""
_STATE_SQL = """
CREATE TABLE archive_state (
    singleton INTEGER PRIMARY KEY
        CHECK (typeof(singleton) = 'integer' AND singleton = 1),
    active_chat_id TEXT UNIQUE,
    FOREIGN KEY (active_chat_id) REFERENCES chats(identifier) ON DELETE SET NULL
)
"""
_EXTRACTIONS_SQL = """
CREATE TABLE memory_extractions (
    extraction_id TEXT PRIMARY KEY CHECK (
        length(extraction_id) = 40
        AND substr(extraction_id, 1, 8) = 'extract-'
        AND substr(extraction_id, 9) NOT GLOB '*[^0-9a-f]*'
    ),
    source_chat_id TEXT NOT NULL,
    source_user_sequence INTEGER NOT NULL CHECK (
        typeof(source_user_sequence) = 'integer' AND source_user_sequence >= 0
    ),
    source_assistant_sequence INTEGER NOT NULL CHECK (
        typeof(source_assistant_sequence) = 'integer'
        AND source_assistant_sequence > source_user_sequence
    ),
    source_archive_revision INTEGER NOT NULL CHECK (
        typeof(source_archive_revision) = 'integer' AND source_archive_revision >= 1
    ),
    provider_id TEXT NOT NULL CHECK (length(provider_id) BETWEEN 1 AND 64),
    model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 255),
    provider_fingerprint TEXT NOT NULL CHECK (
        length(provider_fingerprint) = 64
        AND provider_fingerprint NOT GLOB '*[^0-9a-f]*'
    ),
    state TEXT NOT NULL CHECK (
        state IN ('pending', 'running', 'planned', 'awaiting_confirmation',
                  'completed', 'failed', 'cancelled')
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    claim_owner TEXT,
    plan_json TEXT,
    proposal_json TEXT,
    safe_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (source_chat_id) REFERENCES chats(identifier) ON DELETE CASCADE,
    UNIQUE (source_chat_id, source_user_sequence, source_assistant_sequence),
    CHECK (claim_owner IS NULL OR length(claim_owner) BETWEEN 1 AND 128),
    CHECK (plan_json IS NULL OR length(plan_json) BETWEEN 2 AND 24000),
    CHECK (proposal_json IS NULL OR length(proposal_json) BETWEEN 2 AND 12000),
    CHECK (safe_error_code IS NULL OR length(safe_error_code) BETWEEN 1 AND 64),
    CHECK (created_at <= updated_at),
    CHECK (completed_at IS NULL OR updated_at <= completed_at)
)
"""
_EXTRACTIONS_FIFO_INDEX_SQL = """
CREATE INDEX memory_extractions_fifo_index
ON memory_extractions(state, created_at, extraction_id)
"""

_EXTRACTION_IDENTIFIER_PATTERN = re.compile(r"^extract-[0-9a-f]{32}$")
_PROJECT_IDENTIFIER_PATTERN = re.compile(r"^project-[0-9a-f]{32}$")
_PROJECT_DECISION_IDENTIFIER_PATTERN = re.compile(r"^decision-[0-9a-f]{32}$")
_PROJECT_QUESTION_IDENTIFIER_PATTERN = re.compile(r"^question-[0-9a-f]{32}$")
_PROJECT_PLAN_ITEM_IDENTIFIER_PATTERN = re.compile(r"^plan-item-[0-9a-f]{32}$")
_PROJECT_LINK_IDENTIFIER_PATTERN = re.compile(r"^project-link-[0-9a-f]{32}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")

Clock = Callable[[], datetime]
IdentifierFactory = Callable[[], str]


class _ArchiveConnection(sqlite3.Connection):
    """SQLite connection retaining the no-follow descriptors behind its path."""

    _archive_descriptors: tuple[int, ...] = ()

    def close(self) -> None:
        try:
            super().close()
        finally:
            descriptors, self._archive_descriptors = self._archive_descriptors, ()
            for descriptor in descriptors:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


class ConversationArchiveError(RuntimeError):
    """Base exception for canonical conversation-archive failures."""


class ArchiveValidationError(ConversationArchiveError):
    """Raised when caller-supplied archive data is invalid."""


class ArchiveNotFoundError(ConversationArchiveError):
    """Raised when a requested chat does not exist."""


class ArchiveConflictError(ConversationArchiveError):
    """Raised when a requested archive mutation conflicts."""


class ArchiveStaleRevisionError(ArchiveConflictError):
    """Raised when a mutation targets an older chat revision."""


class ArchiveDivergenceError(ArchiveConflictError):
    """Raised when reconciliation would rewrite durable transcript history."""


class ArchiveVersionError(ConversationArchiveError):
    """Raised when an existing database has an unsupported schema version."""


class ArchiveCorruptError(ConversationArchiveError):
    """Raised for a corrupt, malformed, or look-alike archive database."""


class ArchiveUnavailableError(ConversationArchiveError):
    """Raised when configured archive storage cannot be accessed."""


class ArchiveVerificationError(ConversationArchiveError):
    """Raised when a committed mutation fails a fresh verification read."""


@dataclass(frozen=True, slots=True)
class ArchiveSource:
    """One safe visible knowledge-source reference."""

    filename: str
    line_start: int
    line_end: int


@dataclass(frozen=True, slots=True)
class ArchiveWebSource:
    """One exact source title and URL used by a web-assisted answer."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class ArchiveWebSearch:
    """Durable attribution for one completed authorized web search."""

    query: str
    status: str
    sources: tuple[ArchiveWebSource, ...]


@dataclass(frozen=True, slots=True)
class ArchiveContext:
    """Bounded non-authoritative context telemetry for one model turn."""

    requested_policy: str
    effective_budget: int
    estimator_version: str
    estimated_input_tokens: int
    included_history_messages: int
    omitted_history_messages: int
    actual_prompt_tokens: int | None = None
    actual_completion_tokens: int | None = None
    actual_total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """One authoritative server-visible transcript entry."""

    role: str
    text: str
    sources: tuple[ArchiveSource, ...] = ()
    provider: str | None = None
    model: str | None = None
    created_at: str | None = None
    web_search: ArchiveWebSearch | None = None
    application_event_id: str | None = None
    application_event_type: str | None = None
    context: ArchiveContext | None = None


@dataclass(frozen=True, slots=True)
class ChatMetadata:
    """Safe chat listing metadata, deliberately excluding transcript text."""

    identifier: str
    label: str
    created_at: str
    updated_at: str
    last_opened_at: str | None
    revision: int
    first_provider: str | None
    first_model: str | None
    latest_provider: str | None
    latest_model: str | None
    selected_provider: str
    selected_model: str
    entry_count: int
    completed_turn_count: int
    selected_context_policy: str = "auto"
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    """One bounded, user-owned Project continuity record."""

    identifier: str
    title: str
    status: str
    objective: str
    continuity_brief: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectStateRecord:
    """One optional structured workspace-state row owned by a Project."""

    project_id: str
    phase: str | None
    current_focus: str | None
    checkpoint: str | None
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectDecisionRecord:
    """One immutable historical decision node in a linear Project chain."""

    identifier: str
    project_id: str
    text: str
    importance: str
    state: str
    supersedes_decision_id: str | None
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectQuestionRecord:
    """One durable Project question and its current disposition."""

    identifier: str
    project_id: str
    text: str
    state: str
    disposition_note: str | None
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectPlanItemRecord:
    """One flat, user-ordered Project plan item."""

    identifier: str
    project_id: str
    text: str
    state: str
    state_note: str | None
    sort_order: int
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectLinkRecord:
    """One minimal Project-owned reference to a stable source-owned target."""

    identifier: str
    project_id: str
    target_type: str
    target_id: str
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectContextReceiptRecord:
    """One bounded per-turn Project-context transparency record."""

    chat_id: str
    assistant_sequence: int
    project_id: str
    project_revision: int
    estimator_version: str
    budget_tokens: int
    stable_json: str
    working_json: str
    historical_json: str
    omitted_json: str
    rendered_context: str
    rendered_digest: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ProjectContextReceiptInput:
    """Validated receipt payload to commit with one new assistant entry."""

    assistant_sequence: int
    project_id: str
    project_revision: int
    estimator_version: str
    budget_tokens: int
    stable_json: str
    working_json: str
    historical_json: str
    omitted_json: str
    rendered_context: str
    rendered_digest: str


@dataclass(frozen=True, slots=True)
class ProjectResumeMetadata:
    """Content-free active-Project and ordinary-exchange evidence."""

    project_id: str
    title: str
    project_revision: int
    chat_id: str
    exchange_revision: int
    last_active_at_utc: str


@dataclass(frozen=True, slots=True)
class ApplicationEventRecord:
    """One exact application event found without scanning transcript bodies."""

    chat_id: str
    sequence: int
    entry: ArchiveEntry


@dataclass(frozen=True, slots=True)
class ArchivedChat:
    """One complete, validated canonical chat."""

    metadata: ChatMetadata
    entries: tuple[ArchiveEntry, ...]


@dataclass(frozen=True, slots=True)
class MemoryExtractionRequest:
    extraction_id: str
    user_sequence: int
    assistant_sequence: int
    provider_id: str
    model_id: str
    provider_fingerprint: str


@dataclass(frozen=True, slots=True)
class MemoryExtractionRecord:
    extraction_id: str
    source_chat_id: str
    source_user_sequence: int
    source_assistant_sequence: int
    source_archive_revision: int
    provider_id: str
    model_id: str
    provider_fingerprint: str
    state: str
    revision: int
    claim_owner: str | None
    plan_json: str | None
    proposal_json: str | None
    safe_error_code: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


class ConversationArchiveStore:
    """Own one canonical conversation-archive SQLite database."""

    def __init__(
        self,
        path: Path = DEFAULT_ARCHIVE_DATABASE,
        *,
        clock: Clock | None = None,
        identifier_factory: IdentifierFactory | None = None,
        project_identifier_factory: IdentifierFactory | None = None,
        project_decision_identifier_factory: IdentifierFactory | None = None,
        project_question_identifier_factory: IdentifierFactory | None = None,
        project_plan_identifier_factory: IdentifierFactory | None = None,
        project_link_identifier_factory: IdentifierFactory | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or _utc_now
        self._identifier_factory = identifier_factory or _generate_identifier
        self._project_identifier_factory = (
            project_identifier_factory or _generate_project_identifier
        )
        self._project_decision_identifier_factory = (
            project_decision_identifier_factory or _generate_project_decision_identifier
        )
        self._project_question_identifier_factory = (
            project_question_identifier_factory or _generate_project_question_identifier
        )
        self._project_plan_identifier_factory = (
            project_plan_identifier_factory or _generate_project_plan_identifier
        )
        self._project_link_identifier_factory = (
            project_link_identifier_factory or _generate_project_link_identifier
        )

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        """Deliberately initialize a new store or validate an existing one."""

        with closing(self._connect()):
            pass

    def create_chat(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        provider: str,
        model: str,
        identifier: str | None = None,
        label: str | None = None,
        select_active: bool = False,
        context_policy: str = "auto",
        project_id: str | None = None,
        memory_extraction: MemoryExtractionRequest | None = None,
        project_context_receipt: ProjectContextReceiptInput | None = None,
    ) -> ArchivedChat:
        """Atomically persist a first completed conversation and optionally select it."""

        validated_entries = validate_archive_entries(entries)
        attributions = completed_model_attributions(validated_entries)
        if not attributions:
            raise ArchiveValidationError(
                "A chat requires at least one completed provider/model exchange."
            )
        selected_provider = _required_metadata(provider, "provider")
        selected_model = _required_metadata(model, "model")
        selected_project = (
            validate_project_identifier(project_id) if project_id is not None else None
        )
        if selected_project is not None and not self._project_identifier_exists(selected_project):
            raise ArchiveNotFoundError("The selected Project was not found.")
        return self._create_chat_record(
            validated_entries,
            first_provider=attributions[0][0],
            first_model=attributions[0][1],
            latest_provider=attributions[-1][0],
            latest_model=attributions[-1][1],
            selected_provider=selected_provider,
            selected_model=selected_model,
            identifier=identifier,
            label=label,
            select_active=select_active,
            context_policy=_validate_context_policy(context_policy),
            project_id=selected_project,
            memory_extraction=memory_extraction,
            project_context_receipt=project_context_receipt,
        )

    def create_scheduled_work_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        label: str | None = None,
    ) -> ArchivedChat:
        """Create the one approved provider-free Scheduled Work origin form."""

        validated_entries = validate_scheduled_work_origin_entries(entries)
        return self._create_chat_record(
            validated_entries,
            first_provider=None,
            first_model=None,
            latest_provider=None,
            latest_model=None,
            selected_provider=_required_metadata(selected_provider, "provider"),
            selected_model=_required_metadata(selected_model, "model"),
            label=label,
            select_active=True,
        )

    def create_project_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
    ) -> ArchivedChat:
        """Create the narrow provider-free Project proposal origin form."""

        validated_entries = validate_project_proposal_origin_entries(entries)
        return self._create_chat_record(
            validated_entries,
            first_provider=None,
            first_model=None,
            latest_provider=None,
            latest_model=None,
            selected_provider=_required_metadata(selected_provider, "provider"),
            selected_model=_required_metadata(selected_model, "model"),
            label=None,
            select_active=True,
        )

    def create_coding_work_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        project_id: str | None = None,
    ) -> ArchivedChat:
        """Create the narrow provider-free Coding Work proposal origin form."""

        validated_entries = validate_coding_work_proposal_origin_entries(entries)
        return self._create_chat_record(
            validated_entries,
            first_provider=None,
            first_model=None,
            latest_provider=None,
            latest_model=None,
            selected_provider=_required_metadata(selected_provider, "provider"),
            selected_model=_required_metadata(selected_model, "model"),
            label=None,
            select_active=True,
            project_id=project_id,
        )

    def create_terminal_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        project_id: str | None = None,
        context_policy: str = "auto",
    ) -> ArchivedChat:
        """Create a verified first-turn terminal origin without a model reply."""

        validated_entries = validate_terminal_proposal_origin_entries(entries)
        selected_project = (
            validate_project_identifier(project_id) if project_id is not None else None
        )
        if selected_project is not None and not self._project_identifier_exists(selected_project):
            raise ArchiveNotFoundError("The selected Project was not found.")
        return self._create_chat_record(
            validated_entries,
            first_provider=None, first_model=None,
            latest_provider=None, latest_model=None,
            selected_provider=_required_metadata(selected_provider, "provider"),
            selected_model=_required_metadata(selected_model, "model"),
            label=None, select_active=True, project_id=selected_project,
            context_policy=_validate_context_policy(context_policy),
        )

    def create_planning_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
    ) -> ArchivedChat:
        """Create one provider-free Planning read or proposal origin."""

        validated_entries = validate_planning_origin_entries(entries)
        return self._create_chat_record(
            validated_entries,
            first_provider=None,
            first_model=None,
            latest_provider=None,
            latest_model=None,
            selected_provider=_required_metadata(selected_provider, "provider"),
            selected_model=_required_metadata(selected_model, "model"),
            label=None,
            select_active=True,
        )

    def _create_chat_record(
        self,
        validated_entries: tuple[ArchiveEntry, ...],
        *,
        first_provider: str | None,
        first_model: str | None,
        latest_provider: str | None,
        latest_model: str | None,
        selected_provider: str,
        selected_model: str,
        identifier: str | None = None,
        label: str | None,
        select_active: bool,
        context_policy: str = "auto",
        project_id: str | None = None,
        memory_extraction: MemoryExtractionRequest | None = None,
        project_context_receipt: ProjectContextReceiptInput | None = None,
    ) -> ArchivedChat:
        created_at = _format_timestamp(self._clock())
        extraction = (
            _validate_memory_extraction_request(memory_extraction, validated_entries)
            if memory_extraction is not None else None
        )
        selected_label = (
            derive_chat_label(validated_entries, created_at=created_at)
            if label is None
            else _validate_label(label)
        )

        selected_identifier = (
            None if identifier is None else validate_chat_identifier(identifier)
        )
        attempts = 1 if selected_identifier is not None else MAX_IDENTIFIER_ATTEMPTS
        for _attempt in range(attempts):
            identifier = selected_identifier or validate_chat_identifier(
                self._identifier_factory()
            )
            metadata = ChatMetadata(
                identifier=identifier,
                label=selected_label,
                created_at=created_at,
                updated_at=created_at,
                last_opened_at=None,
                revision=1,
                first_provider=first_provider,
                first_model=first_model,
                latest_provider=latest_provider,
                latest_model=latest_model,
                selected_provider=selected_provider,
                selected_model=selected_model,
                entry_count=len(validated_entries),
                completed_turn_count=len(completed_model_attributions(validated_entries)),
                selected_context_policy=context_policy,
                project_id=project_id,
            )
            stamped_entries = _stamp_entries(validated_entries, created_at)
            receipt = None
            if project_context_receipt is not None:
                receipt = _prepare_project_context_receipt(
                    project_context_receipt,
                    chat_id=identifier,
                    entries=stamped_entries,
                    chat_project_id=project_id,
                    created_at=created_at,
                )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        self._insert_chat(connection, metadata)
                        self._insert_entries(connection, identifier, 0, stamped_entries)
                        if receipt is not None:
                            self._insert_project_context_receipt(connection, receipt)
                        if extraction is not None:
                            self._insert_memory_extraction(
                                connection, identifier, 1, extraction, created_at
                            )
                        if select_active:
                            self._set_active(connection, identifier)
            except sqlite3.IntegrityError as exc:
                if self._identifier_exists(identifier):
                    if selected_identifier is not None:
                        raise ArchiveConflictError(
                            "The reserved chat identifier is already in use."
                        ) from exc
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc

            expected = ArchivedChat(metadata=metadata, entries=stamped_entries)
            try:
                verified = self.get_chat(identifier)
                active_id = self.get_active_chat_id() if select_active else None
                verified_extraction = (
                    self.get_memory_extraction(extraction.extraction_id)
                    if extraction is not None else None
                )
                verified_receipt = (
                    self.get_project_context_receipt(
                        identifier, receipt.assistant_sequence
                    )
                    if receipt is not None else None
                )
            except ConversationArchiveError as exc:
                raise ArchiveVerificationError(
                    "The chat was committed but could not be verified."
                ) from exc
            if (
                verified != expected
                or (select_active and active_id != identifier)
                or (receipt is not None and verified_receipt != receipt)
                or (
                    extraction is not None
                    and (
                        verified_extraction is None
                        or verified_extraction.source_chat_id != identifier
                        or verified_extraction.source_archive_revision != 1
                        or verified_extraction.state != "pending"
                    )
                )
            ):
                raise ArchiveVerificationError(
                    "The chat was committed but could not be verified."
                )
            return verified

        raise ArchiveConflictError(
            "Could not generate a unique chat identifier; nothing was saved."
        )

    def get_chat(self, identifier: str) -> ArchivedChat:
        """Freshly load one complete validated chat."""

        validated_id = validate_chat_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                ).fetchone()
                if row is None:
                    raise ArchiveNotFoundError("The selected chat was not found.")
                entry_rows = connection.execute(
                    """
                    SELECT sequence, role, text, sources_json, provider, model,
                           created_at, application_event_id, application_event_type,
                           context_json
                    FROM transcript_entries WHERE chat_id = ?
                    ORDER BY sequence ASC
                    """,
                    (validated_id,),
                ).fetchall()
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return _chat_from_rows(row, entry_rows)

    def list_chats(self) -> tuple[ChatMetadata, ...]:
        """List safe metadata in deterministic newest-first order."""

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    _CHAT_SELECT + " ORDER BY updated_at DESC, identifier DESC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_metadata_from_row(row) for row in rows)

    def list_project_chats(self, project_id: str) -> tuple[ChatMetadata, ...]:
        """List one Project's chat metadata without loading transcript text."""

        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    _CHAT_SELECT
                    + " WHERE project_id=? ORDER BY updated_at DESC, identifier DESC",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_metadata_from_row(row) for row in rows)

    def get_active_chat_metadata(self) -> ChatMetadata | None:
        """Return only metadata for the active chat, without transcript text."""

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    _CHAT_SELECT
                    + " WHERE identifier=(SELECT active_chat_id FROM archive_state "
                    "WHERE singleton=1)"
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return None if row is None else _metadata_from_row(row)

    def create_project(
        self,
        *,
        title: str,
        objective: str,
        continuity_brief: str = "",
        chat_id: str | None = None,
        expected_chat_revision: int | None = None,
    ) -> ProjectRecord:
        """Create one Project and optionally associate one chat atomically."""

        validated_title = _validate_project_text(
            title, "Project title", MAX_PROJECT_TITLE_LENGTH
        )
        validated_objective = _validate_project_text(
            objective, "Project objective", MAX_PROJECT_OBJECTIVE_LENGTH
        )
        validated_brief = _validate_project_brief(continuity_brief)
        validated_chat = validate_chat_identifier(chat_id) if chat_id is not None else None
        if (validated_chat is None) != (expected_chat_revision is None):
            raise ArchiveValidationError(
                "An initial Project association requires a chat and its revision."
            )
        expected = (
            _validate_revision(expected_chat_revision)
            if expected_chat_revision is not None else None
        )
        timestamp = _format_timestamp(self._clock())
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_identifier(
                self._project_identifier_factory()
            )
            record = ProjectRecord(
                identifier, validated_title, "active", validated_objective,
                validated_brief, 1, timestamp, timestamp,
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        self._insert_project(connection, record)
                        if validated_chat is not None:
                            row = connection.execute(
                                "SELECT updated_at FROM chats WHERE identifier=? AND revision=?",
                                (validated_chat, expected),
                            ).fetchone()
                            if row is None:
                                if connection.execute(
                                    "SELECT 1 FROM chats WHERE identifier=?", (validated_chat,)
                                ).fetchone() is None:
                                    raise ArchiveNotFoundError("The selected chat was not found.")
                                raise ArchiveStaleRevisionError(
                                    "The chat changed before Project creation."
                                )
                            chat_timestamp = _next_timestamp(self._clock(), row[0])
                            connection.execute(
                                "UPDATE chats SET project_id=?, revision=revision+1, updated_at=? "
                                "WHERE identifier=? AND revision=?",
                                (identifier, chat_timestamp, validated_chat, expected),
                            )
            except sqlite3.IntegrityError as exc:
                if self._project_identifier_exists(identifier):
                    continue
                raise _database_error(exc) from exc
            verified = self.get_project(identifier)
            if verified != record:
                raise ArchiveVerificationError(
                    "The Project was committed but could not be verified."
                )
            if validated_chat is not None and self.get_chat(validated_chat).metadata.project_id != identifier:
                raise ArchiveVerificationError(
                    "The Project association was committed but could not be verified."
                )
            return verified
        raise ArchiveConflictError(
            "Could not generate a unique Project identifier; nothing was saved."
        )

    def get_project(self, identifier: str) -> ProjectRecord:
        validated = validate_project_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    _PROJECT_SELECT + " WHERE identifier=?", (validated,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveNotFoundError("The selected Project was not found.")
        return _project_from_row(row)

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    _PROJECT_SELECT + " ORDER BY updated_at DESC, identifier DESC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_from_row(row) for row in rows)

    def get_project_state(self, project_id: str) -> ProjectStateRecord | None:
        """Read the optional structured state row without synthesizing legacy data."""

        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT project_id,phase,current_focus,checkpoint,revision,"
                    "created_at,updated_at FROM project_state WHERE project_id=?",
                    (project,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return _project_state_from_row(row) if row is not None else None

    def list_project_decisions(
        self, project_id: str
    ) -> tuple[ProjectDecisionRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,text,importance,state,"
                    "supersedes_decision_id,revision,created_at,updated_at "
                    "FROM project_decisions WHERE project_id=? "
                    "ORDER BY created_at,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_decision_from_row(row) for row in rows)

    def get_project_decision(self, identifier: str) -> ProjectDecisionRecord:
        decision = validate_project_decision_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT identifier,project_id,text,importance,state,"
                    "supersedes_decision_id,revision,created_at,updated_at "
                    "FROM project_decisions WHERE identifier=?",
                    (decision,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveNotFoundError("The selected Project decision was not found.")
        return _project_decision_from_row(row)

    def list_active_project_decisions(
        self, project_id: str
    ) -> tuple[ProjectDecisionRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,text,importance,state,"
                    "supersedes_decision_id,revision,created_at,updated_at "
                    "FROM project_decisions WHERE project_id=? AND state='active' "
                    "ORDER BY CASE importance WHEN 'important' THEN 0 ELSE 1 END,"
                    "created_at,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_decision_from_row(row) for row in rows)

    def list_project_questions(
        self, project_id: str
    ) -> tuple[ProjectQuestionRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,text,state,disposition_note,revision,"
                    "created_at,updated_at FROM project_questions WHERE project_id=? "
                    "ORDER BY created_at,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_question_from_row(row) for row in rows)

    def get_project_question(self, identifier: str) -> ProjectQuestionRecord:
        question = validate_project_question_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT identifier,project_id,text,state,disposition_note,revision,"
                    "created_at,updated_at FROM project_questions WHERE identifier=?",
                    (question,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveNotFoundError("The selected Project question was not found.")
        return _project_question_from_row(row)

    def list_active_project_questions(
        self, project_id: str
    ) -> tuple[ProjectQuestionRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,text,state,disposition_note,revision,"
                    "created_at,updated_at FROM project_questions WHERE project_id=? "
                    "AND state IN ('open','deferred') "
                    "ORDER BY CASE state WHEN 'open' THEN 0 ELSE 1 END,created_at,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_question_from_row(row) for row in rows)

    def list_project_plan_items(
        self, project_id: str
    ) -> tuple[ProjectPlanItemRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,text,state,state_note,sort_order,"
                    "revision,created_at,updated_at FROM project_plan_items "
                    "WHERE project_id=? ORDER BY sort_order,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_plan_item_from_row(row) for row in rows)

    def get_project_plan_item(self, identifier: str) -> ProjectPlanItemRecord:
        item = validate_project_plan_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT identifier,project_id,text,state,state_note,sort_order,"
                    "revision,created_at,updated_at FROM project_plan_items "
                    "WHERE identifier=?",
                    (item,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveNotFoundError("The selected Project plan item was not found.")
        return _project_plan_item_from_row(row)

    def list_project_links(self, project_id: str) -> tuple[ProjectLinkRecord, ...]:
        project = validate_project_identifier(project_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT identifier,project_id,target_type,target_id,revision,"
                    "created_at,updated_at FROM project_links WHERE project_id=? "
                    "ORDER BY target_type,target_id,identifier",
                    (project,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_link_from_row(row) for row in rows)

    def get_project_link(self, identifier: str) -> ProjectLinkRecord:
        link = validate_project_link_identifier(identifier)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT identifier,project_id,target_type,target_id,revision,"
                    "created_at,updated_at FROM project_links WHERE identifier=?",
                    (link,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveNotFoundError("The selected Project link was not found.")
        return _project_link_from_row(row)

    def get_project_context_receipt(
        self, chat_id: str, assistant_sequence: int
    ) -> ProjectContextReceiptRecord | None:
        chat = validate_chat_identifier(chat_id)
        if (
            isinstance(assistant_sequence, bool)
            or not isinstance(assistant_sequence, int)
            or assistant_sequence < 0
        ):
            raise ArchiveValidationError("The assistant sequence is invalid.")
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT chat_id,assistant_sequence,project_id,project_revision,"
                    "estimator_version,budget_tokens,stable_json,working_json,"
                    "historical_json,omitted_json,rendered_context,rendered_digest,"
                    "created_at FROM project_context_receipts "
                    "WHERE chat_id=? AND assistant_sequence=?",
                    (chat, assistant_sequence),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return _project_context_receipt_from_row(row) if row is not None else None

    def list_project_context_receipts(
        self, chat_id: str
    ) -> tuple[ProjectContextReceiptRecord, ...]:
        chat = validate_chat_identifier(chat_id)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT chat_id,assistant_sequence,project_id,project_revision,"
                    "estimator_version,budget_tokens,stable_json,working_json,"
                    "historical_json,omitted_json,rendered_context,rendered_digest,"
                    "created_at FROM project_context_receipts WHERE chat_id=? "
                    "ORDER BY assistant_sequence",
                    (chat,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_project_context_receipt_from_row(row) for row in rows)

    def list_project_resume_metadata(self) -> tuple[ProjectResumeMetadata, ...]:
        """Read active Project associations without loading transcript bodies."""

        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT p.identifier,p.title,p.revision,c.identifier,e.sequence,e.created_at "
                    "FROM projects p JOIN chats c ON c.project_id=p.identifier "
                    "JOIN transcript_entries e ON e.chat_id=c.identifier "
                    "WHERE p.status='active' AND e.role='assistant' "
                    "AND e.application_event_id IS NULL AND e.provider IS NOT NULL "
                    "AND e.model IS NOT NULL AND e.sequence=("
                    "SELECT MAX(latest.sequence) FROM transcript_entries latest "
                    "WHERE latest.chat_id=c.identifier AND latest.role='assistant' "
                    "AND latest.application_event_id IS NULL "
                    "AND latest.provider IS NOT NULL AND latest.model IS NOT NULL) "
                    "ORDER BY e.created_at DESC,p.identifier,c.identifier"
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(ProjectResumeMetadata(*row) for row in rows)

    def update_project_state(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        expected_state_revision: int | None,
        phase: str | None,
        current_focus: str | None,
        checkpoint: str | None,
    ) -> tuple[ProjectRecord, ProjectStateRecord]:
        """Create or replace one explicit workspace-state row atomically."""

        project = validate_project_identifier(project_id)
        parent_revision = _validate_revision(expected_project_revision)
        state_revision = (
            None if expected_state_revision is None
            else _validate_revision(expected_state_revision)
        )
        validated_phase = _validate_optional_project_text(
            phase, "Project phase", MAX_PROJECT_PHASE_LENGTH
        )
        validated_focus = _validate_optional_project_text(
            current_focus, "Project current focus", MAX_PROJECT_FOCUS_LENGTH
        )
        validated_checkpoint = _validate_optional_project_text(
            checkpoint, "Project checkpoint", MAX_PROJECT_CHECKPOINT_LENGTH
        )
        if all(value is None for value in (
            validated_phase, validated_focus, validated_checkpoint,
        )):
            raise ArchiveValidationError(
                "Project workspace state must record a phase, focus, or checkpoint."
            )
        target: ProjectStateRecord
        revised_project: ProjectRecord
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current_project = _require_project_revision(
                        connection, project, parent_revision
                    )
                    row = connection.execute(
                        "SELECT project_id,phase,current_focus,checkpoint,revision,"
                        "created_at,updated_at FROM project_state WHERE project_id=?",
                        (project,),
                    ).fetchone()
                    if row is None:
                        if state_revision is not None:
                            raise ArchiveStaleRevisionError(
                                "Project workspace state changed after it was loaded."
                            )
                        timestamp = _next_timestamp(
                            self._clock(), current_project.updated_at
                        )
                        target = ProjectStateRecord(
                            project, validated_phase, validated_focus,
                            validated_checkpoint, 1, timestamp, timestamp,
                        )
                        connection.execute(
                            "INSERT INTO project_state VALUES (?,?,?,?,?,?,?)",
                            (
                                target.project_id, target.phase, target.current_focus,
                                target.checkpoint, target.revision, target.created_at,
                                target.updated_at,
                            ),
                        )
                    else:
                        current = _project_state_from_row(row)
                        if state_revision is None or current.revision != state_revision:
                            raise ArchiveStaleRevisionError(
                                "Project workspace state changed after it was loaded."
                            )
                        timestamp = _next_timestamp(
                            self._clock(), max(current_project.updated_at, current.updated_at)
                        )
                        target = ProjectStateRecord(
                            project, validated_phase, validated_focus,
                            validated_checkpoint, current.revision + 1,
                            current.created_at, timestamp,
                        )
                        cursor = connection.execute(
                            "UPDATE project_state SET phase=?,current_focus=?,checkpoint=?,"
                            "revision=?,updated_at=? WHERE project_id=? AND revision=?",
                            (
                                target.phase, target.current_focus, target.checkpoint,
                                target.revision, target.updated_at, project,
                                state_revision,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise ArchiveStaleRevisionError(
                                "Project workspace state changed before it was saved."
                            )
                    revised_project = _advance_project_revision(
                        connection, current_project, target.updated_at
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_project_state(project)
        if verified != target or self.get_project(project) != revised_project:
            raise ArchiveVerificationError(
                "The Project workspace-state update could not be verified."
            )
        return revised_project, verified

    def add_project_decision(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
        importance: str = "normal",
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        project = validate_project_identifier(project_id)
        parent_revision = _validate_revision(expected_project_revision)
        decision_text = _validate_project_text(
            text, "Project decision", MAX_PROJECT_DECISION_LENGTH
        )
        decision_importance = _validate_decision_importance(importance)
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_decision_identifier(
                self._project_decision_identifier_factory()
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        current_project = _require_project_revision(
                            connection, project, parent_revision
                        )
                        timestamp = _next_timestamp(
                            self._clock(), current_project.updated_at
                        )
                        target = ProjectDecisionRecord(
                            identifier, project, decision_text, decision_importance,
                            "active", None, 1, timestamp, timestamp,
                        )
                        connection.execute(
                            "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                target.identifier, target.project_id, target.text,
                                target.importance, target.state,
                                target.supersedes_decision_id, target.revision,
                                target.created_at, target.updated_at,
                            ),
                        )
                        revised_project = _advance_project_revision(
                            connection, current_project, timestamp
                        )
            except sqlite3.IntegrityError as exc:
                if self._project_child_identifier_exists(
                    "project_decisions", identifier
                ):
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            verified = self.get_project_decision(identifier)
            if verified != target or self.get_project(project) != revised_project:
                raise ArchiveVerificationError(
                    "The Project decision creation could not be verified."
                )
            return revised_project, verified
        raise ArchiveConflictError(
            "Could not generate a unique Project decision identifier; nothing was saved."
        )

    def mark_project_decision_important(
        self,
        project_id: str,
        decision_id: str,
        *,
        expected_project_revision: int,
        expected_decision_revision: int,
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        project = validate_project_identifier(project_id)
        decision = validate_project_decision_identifier(decision_id)
        parent_revision = _validate_revision(expected_project_revision)
        child_revision = _validate_revision(expected_decision_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current_project = _require_project_revision(
                        connection, project, parent_revision
                    )
                    current = _require_project_decision(
                        connection, decision, project, child_revision
                    )
                    if current.importance == "important":
                        raise ArchiveConflictError(
                            "That Project decision is already important."
                        )
                    timestamp = _next_timestamp(
                        self._clock(), max(current_project.updated_at, current.updated_at)
                    )
                    cursor = connection.execute(
                        "UPDATE project_decisions SET importance='important',"
                        "revision=revision+1,updated_at=? "
                        "WHERE identifier=? AND project_id=? AND revision=?",
                        (timestamp, decision, project, child_revision),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The Project decision changed before it was saved."
                        )
                    target = ProjectDecisionRecord(
                        current.identifier, current.project_id, current.text,
                        "important", current.state, current.supersedes_decision_id,
                        current.revision + 1, current.created_at, timestamp,
                    )
                    revised_project = _advance_project_revision(
                        connection, current_project, timestamp
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_project_decision(decision)
        if verified != target or self.get_project(project) != revised_project:
            raise ArchiveVerificationError(
                "The Project decision importance update could not be verified."
            )
        return revised_project, verified

    def supersede_project_decision(
        self,
        project_id: str,
        predecessor_id: str,
        *,
        expected_project_revision: int,
        expected_predecessor_revision: int,
        text: str,
        importance: str = "normal",
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        project = validate_project_identifier(project_id)
        predecessor = validate_project_decision_identifier(predecessor_id)
        parent_revision = _validate_revision(expected_project_revision)
        predecessor_revision = _validate_revision(expected_predecessor_revision)
        decision_text = _validate_project_text(
            text, "Project decision", MAX_PROJECT_DECISION_LENGTH
        )
        decision_importance = _validate_decision_importance(importance)
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_decision_identifier(
                self._project_decision_identifier_factory()
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        current_project = _require_project_revision(
                            connection, project, parent_revision
                        )
                        current = _require_project_decision(
                            connection, predecessor, project, predecessor_revision
                        )
                        if current.state != "active":
                            raise ArchiveConflictError(
                                "Only an active Project decision can be superseded."
                            )
                        if _decision_chain_contains(
                            connection, predecessor, identifier
                        ):
                            raise ArchiveConflictError(
                                "Project decision supersession cannot form a cycle."
                            )
                        if connection.execute(
                            "SELECT 1 FROM project_decisions "
                            "WHERE supersedes_decision_id=?",
                            (predecessor,),
                        ).fetchone() is not None:
                            raise ArchiveConflictError(
                                "A Project decision cannot have more than one successor."
                            )
                        timestamp = _next_timestamp(
                            self._clock(), max(current_project.updated_at, current.updated_at)
                        )
                        target = ProjectDecisionRecord(
                            identifier, project, decision_text, decision_importance,
                            "active", predecessor, 1, timestamp, timestamp,
                        )
                        cursor = connection.execute(
                            "UPDATE project_decisions SET state='superseded',"
                            "revision=revision+1,updated_at=? "
                            "WHERE identifier=? AND project_id=? AND revision=? "
                            "AND state='active'",
                            (timestamp, predecessor, project, predecessor_revision),
                        )
                        if cursor.rowcount != 1:
                            raise ArchiveStaleRevisionError(
                                "The predecessor decision changed before it was saved."
                            )
                        connection.execute(
                            "INSERT INTO project_decisions VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                target.identifier, target.project_id, target.text,
                                target.importance, target.state,
                                target.supersedes_decision_id, target.revision,
                                target.created_at, target.updated_at,
                            ),
                        )
                        revised_project = _advance_project_revision(
                            connection, current_project, timestamp
                        )
            except sqlite3.IntegrityError as exc:
                if self._project_child_identifier_exists(
                    "project_decisions", identifier
                ):
                    if identifier == predecessor:
                        raise ArchiveConflictError(
                            "Project decision supersession cannot form a cycle."
                        ) from exc
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            verified = self.get_project_decision(identifier)
            previous = self.get_project_decision(predecessor)
            if (
                verified != target
                or previous.state != "superseded"
                or previous.revision != predecessor_revision + 1
                or self.get_project(project) != revised_project
            ):
                raise ArchiveVerificationError(
                    "The Project decision supersession could not be verified."
                )
            return revised_project, verified
        raise ArchiveConflictError(
            "Could not generate a unique Project decision identifier; nothing was saved."
        )

    def add_project_question(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
    ) -> tuple[ProjectRecord, ProjectQuestionRecord]:
        project = validate_project_identifier(project_id)
        parent_revision = _validate_revision(expected_project_revision)
        question_text = _validate_project_text(
            text, "Project question", MAX_PROJECT_QUESTION_LENGTH
        )
        return self._insert_project_question(
            project, parent_revision, question_text
        )

    def transition_project_question(
        self,
        project_id: str,
        question_id: str,
        *,
        expected_project_revision: int,
        expected_question_revision: int,
        state: str,
        disposition_note: str | None = None,
    ) -> tuple[ProjectRecord, ProjectQuestionRecord]:
        project = validate_project_identifier(project_id)
        question = validate_project_question_identifier(question_id)
        parent_revision = _validate_revision(expected_project_revision)
        child_revision = _validate_revision(expected_question_revision)
        target_state = _validate_question_state(state)
        note = _validate_optional_project_text(
            disposition_note,
            "Project question disposition",
            MAX_PROJECT_DISPOSITION_NOTE_LENGTH,
        )
        if target_state == "open" and note is not None:
            raise ArchiveValidationError(
                "An open Project question cannot retain a disposition note."
            )
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current_project = _require_project_revision(
                        connection, project, parent_revision
                    )
                    current = _require_project_question(
                        connection, question, project, child_revision
                    )
                    allowed = {
                        "open": {"deferred", "resolved", "dismissed"},
                        "deferred": {"open", "resolved", "dismissed"},
                        "resolved": set(),
                        "dismissed": set(),
                    }
                    if target_state not in allowed[current.state]:
                        raise ArchiveConflictError(
                            "That Project question transition is not allowed."
                        )
                    timestamp = _next_timestamp(
                        self._clock(), max(current_project.updated_at, current.updated_at)
                    )
                    target = ProjectQuestionRecord(
                        current.identifier, current.project_id, current.text,
                        target_state, note, current.revision + 1,
                        current.created_at, timestamp,
                    )
                    cursor = connection.execute(
                        "UPDATE project_questions SET state=?,disposition_note=?,"
                        "revision=?,updated_at=? WHERE identifier=? AND project_id=? "
                        "AND revision=?",
                        (
                            target.state, target.disposition_note, target.revision,
                            target.updated_at, question, project, child_revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The Project question changed before it was saved."
                        )
                    revised_project = _advance_project_revision(
                        connection, current_project, timestamp
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_project_question(question)
        if verified != target or self.get_project(project) != revised_project:
            raise ArchiveVerificationError(
                "The Project question transition could not be verified."
            )
        return revised_project, verified

    def add_project_plan_item(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
        sort_order: int,
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        project = validate_project_identifier(project_id)
        parent_revision = _validate_revision(expected_project_revision)
        item_text = _validate_project_text(
            text, "Project plan item", MAX_PROJECT_PLAN_ITEM_LENGTH
        )
        order = _validate_plan_order(sort_order)
        return self._insert_project_plan_item(
            project, parent_revision, item_text, order
        )

    def update_project_plan_item(
        self,
        project_id: str,
        plan_item_id: str,
        *,
        expected_project_revision: int,
        expected_plan_item_revision: int,
        text: str,
        state_note: str | None,
        sort_order: int,
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        project = validate_project_identifier(project_id)
        item = validate_project_plan_identifier(plan_item_id)
        parent_revision = _validate_revision(expected_project_revision)
        child_revision = _validate_revision(expected_plan_item_revision)
        item_text = _validate_project_text(
            text, "Project plan item", MAX_PROJECT_PLAN_ITEM_LENGTH
        )
        note = _validate_optional_project_text(
            state_note, "Project plan note", MAX_PROJECT_PLAN_NOTE_LENGTH
        )
        order = _validate_plan_order(sort_order)
        return self._replace_project_plan_item(
            project, item, parent_revision, child_revision,
            text=item_text, state=None, state_note=note, sort_order=order,
        )

    def transition_project_plan_item(
        self,
        project_id: str,
        plan_item_id: str,
        *,
        expected_project_revision: int,
        expected_plan_item_revision: int,
        state: str,
        state_note: str | None = None,
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        project = validate_project_identifier(project_id)
        item = validate_project_plan_identifier(plan_item_id)
        parent_revision = _validate_revision(expected_project_revision)
        child_revision = _validate_revision(expected_plan_item_revision)
        target_state = _validate_plan_state(state)
        note = _validate_optional_project_text(
            state_note, "Project plan note", MAX_PROJECT_PLAN_NOTE_LENGTH
        )
        if target_state in {"planned", "active"} and note is not None:
            raise ArchiveValidationError(
                "A planned or active Project plan item cannot retain a state note."
            )
        return self._replace_project_plan_item(
            project, item, parent_revision, child_revision,
            text=None, state=target_state, state_note=note, sort_order=None,
        )

    def add_project_link(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        target_type: str,
        target_id: str,
    ) -> tuple[ProjectRecord, ProjectLinkRecord]:
        project = validate_project_identifier(project_id)
        parent_revision = _validate_revision(expected_project_revision)
        kind, target = _validate_project_link_target(target_type, target_id)
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_link_identifier(
                self._project_link_identifier_factory()
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        current_project = _require_project_revision(
                            connection, project, parent_revision
                        )
                        if connection.execute(
                            "SELECT 1 FROM project_links WHERE project_id=? "
                            "AND target_type=? AND target_id=?",
                            (project, kind, target),
                        ).fetchone() is not None:
                            raise ArchiveConflictError(
                                "That resource is already linked to the Project."
                            )
                        timestamp = _next_timestamp(
                            self._clock(), current_project.updated_at
                        )
                        record = ProjectLinkRecord(
                            identifier, project, kind, target, 1,
                            timestamp, timestamp,
                        )
                        connection.execute(
                            "INSERT INTO project_links VALUES (?,?,?,?,?,?,?)",
                            (
                                record.identifier, record.project_id,
                                record.target_type, record.target_id, record.revision,
                                record.created_at, record.updated_at,
                            ),
                        )
                        revised_project = _advance_project_revision(
                            connection, current_project, timestamp
                        )
            except sqlite3.IntegrityError as exc:
                if self._project_child_identifier_exists("project_links", identifier):
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            verified = self.get_project_link(identifier)
            if verified != record or self.get_project(project) != revised_project:
                raise ArchiveVerificationError(
                    "The Project link creation could not be verified."
                )
            return revised_project, verified
        raise ArchiveConflictError(
            "Could not generate a unique Project link identifier; nothing was saved."
        )

    def remove_project_link(
        self,
        project_id: str,
        link_id: str,
        *,
        expected_project_revision: int,
        expected_link_revision: int,
    ) -> ProjectRecord:
        project = validate_project_identifier(project_id)
        link = validate_project_link_identifier(link_id)
        parent_revision = _validate_revision(expected_project_revision)
        child_revision = _validate_revision(expected_link_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current_project = _require_project_revision(
                        connection, project, parent_revision
                    )
                    current = _require_project_link(
                        connection, link, project, child_revision
                    )
                    timestamp = _next_timestamp(
                        self._clock(), max(current_project.updated_at, current.updated_at)
                    )
                    cursor = connection.execute(
                        "DELETE FROM project_links WHERE identifier=? AND project_id=? "
                        "AND revision=?",
                        (link, project, child_revision),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The Project link changed before it was removed."
                        )
                    revised_project = _advance_project_revision(
                        connection, current_project, timestamp
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        try:
            self.get_project_link(link)
        except ArchiveNotFoundError:
            if self.get_project(project) == revised_project:
                return revised_project
        raise ArchiveVerificationError("The Project unlink could not be verified.")

    def _insert_project_question(
        self, project: str, parent_revision: int, text: str
    ) -> tuple[ProjectRecord, ProjectQuestionRecord]:
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_question_identifier(
                self._project_question_identifier_factory()
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        current_project = _require_project_revision(
                            connection, project, parent_revision
                        )
                        timestamp = _next_timestamp(
                            self._clock(), current_project.updated_at
                        )
                        record = ProjectQuestionRecord(
                            identifier, project, text, "open", None, 1,
                            timestamp, timestamp,
                        )
                        connection.execute(
                            "INSERT INTO project_questions VALUES (?,?,?,?,?,?,?,?)",
                            (
                                record.identifier, record.project_id, record.text,
                                record.state, record.disposition_note, record.revision,
                                record.created_at, record.updated_at,
                            ),
                        )
                        revised_project = _advance_project_revision(
                            connection, current_project, timestamp
                        )
            except sqlite3.IntegrityError as exc:
                if self._project_child_identifier_exists(
                    "project_questions", identifier
                ):
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            verified = self.get_project_question(identifier)
            if verified != record or self.get_project(project) != revised_project:
                raise ArchiveVerificationError(
                    "The Project question creation could not be verified."
                )
            return revised_project, verified
        raise ArchiveConflictError(
            "Could not generate a unique Project question identifier; nothing was saved."
        )

    def _insert_project_plan_item(
        self, project: str, parent_revision: int, text: str, sort_order: int
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        for _attempt in range(MAX_IDENTIFIER_ATTEMPTS):
            identifier = validate_project_plan_identifier(
                self._project_plan_identifier_factory()
            )
            try:
                with closing(self._connect()) as connection:
                    with connection:
                        connection.execute("BEGIN IMMEDIATE")
                        current_project = _require_project_revision(
                            connection, project, parent_revision
                        )
                        timestamp = _next_timestamp(
                            self._clock(), current_project.updated_at
                        )
                        record = ProjectPlanItemRecord(
                            identifier, project, text, "planned", None,
                            sort_order, 1, timestamp, timestamp,
                        )
                        connection.execute(
                            "INSERT INTO project_plan_items VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                record.identifier, record.project_id, record.text,
                                record.state, record.state_note, record.sort_order,
                                record.revision, record.created_at, record.updated_at,
                            ),
                        )
                        revised_project = _advance_project_revision(
                            connection, current_project, timestamp
                        )
            except sqlite3.IntegrityError as exc:
                if self._project_child_identifier_exists(
                    "project_plan_items", identifier
                ):
                    continue
                raise _database_error(exc) from exc
            except ConversationArchiveError:
                raise
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            verified = self.get_project_plan_item(identifier)
            if verified != record or self.get_project(project) != revised_project:
                raise ArchiveVerificationError(
                    "The Project plan-item creation could not be verified."
                )
            return revised_project, verified
        raise ArchiveConflictError(
            "Could not generate a unique Project plan-item identifier; nothing was saved."
        )

    def _replace_project_plan_item(
        self,
        project: str,
        identifier: str,
        parent_revision: int,
        child_revision: int,
        *,
        text: str | None,
        state: str | None,
        state_note: str | None,
        sort_order: int | None,
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        try:
            with closing(self._connect()) as connection:
                with connection:
                    connection.execute("BEGIN IMMEDIATE")
                    current_project = _require_project_revision(
                        connection, project, parent_revision
                    )
                    current = _require_project_plan_item(
                        connection, identifier, project, child_revision
                    )
                    target_state = current.state if state is None else state
                    if state is not None and target_state == current.state:
                        raise ArchiveConflictError(
                            "The Project plan item is already in that state."
                        )
                    target_note = state_note
                    if state is None and current.state in {"planned", "active"}:
                        if target_note is not None:
                            raise ArchiveValidationError(
                                "A planned or active Project plan item cannot retain a state note."
                            )
                    timestamp = _next_timestamp(
                        self._clock(), max(current_project.updated_at, current.updated_at)
                    )
                    target = ProjectPlanItemRecord(
                        current.identifier, current.project_id,
                        current.text if text is None else text,
                        target_state, target_note,
                        current.sort_order if sort_order is None else sort_order,
                        current.revision + 1, current.created_at, timestamp,
                    )
                    cursor = connection.execute(
                        "UPDATE project_plan_items SET text=?,state=?,state_note=?,"
                        "sort_order=?,revision=?,updated_at=? WHERE identifier=? "
                        "AND project_id=? AND revision=?",
                        (
                            target.text, target.state, target.state_note,
                            target.sort_order, target.revision, target.updated_at,
                            identifier, project, child_revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The Project plan item changed before it was saved."
                        )
                    revised_project = _advance_project_revision(
                        connection, current_project, timestamp
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_project_plan_item(identifier)
        if verified != target or self.get_project(project) != revised_project:
            raise ArchiveVerificationError(
                "The Project plan-item update could not be verified."
            )
        return revised_project, verified

    def _project_child_identifier_exists(self, table: str, identifier: str) -> bool:
        if table not in {
            "project_decisions", "project_questions", "project_plan_items",
            "project_links",
        }:
            raise ValueError("Unknown Project child table.")
        try:
            with closing(self._connect()) as connection:
                return connection.execute(
                    f"SELECT 1 FROM {table} WHERE identifier=?", (identifier,)
                ).fetchone() is not None
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc

    def update_project(
        self,
        identifier: str,
        *,
        expected_revision: int,
        title: str | None = None,
        objective: str | None = None,
        status: str | None = None,
    ) -> ProjectRecord:
        validated = validate_project_identifier(identifier)
        expected = _validate_revision(expected_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _PROJECT_SELECT + " WHERE identifier=?", (validated,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected Project was not found.")
                    current = _project_from_row(row)
                    if current.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The Project changed after it was loaded."
                        )
                    target_status = current.status if status is None else _validate_project_status(status)
                    if status is not None and target_status != current.status and (
                        current.status, target_status
                    ) not in {
                        ("active", "paused"), ("paused", "active"),
                        ("active", "completed"), ("paused", "completed"),
                        ("completed", "active"),
                    }:
                        raise ArchiveConflictError("That Project status transition is not allowed.")
                    target = ProjectRecord(
                        current.identifier,
                        current.title if title is None else _validate_project_text(title, "Project title", MAX_PROJECT_TITLE_LENGTH),
                        target_status,
                        current.objective if objective is None else _validate_project_text(objective, "Project objective", MAX_PROJECT_OBJECTIVE_LENGTH),
                        current.continuity_brief,
                        current.revision + 1,
                        current.created_at,
                        _next_timestamp(self._clock(), current.updated_at),
                    )
                    connection.execute(
                        "UPDATE projects SET title=?,status=?,objective=?,continuity_brief=?,"
                        "revision=?,updated_at=? WHERE identifier=? AND revision=?",
                        (target.title, target.status, target.objective, target.continuity_brief,
                         target.revision, target.updated_at, validated, expected),
                    )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_project(validated)
        if verified != target:
            raise ArchiveVerificationError("The Project update could not be verified.")
        return verified

    def associate_chat(
        self,
        chat_id: str,
        project_id: str | None,
        *,
        expected_revision: int,
    ) -> ArchivedChat:
        chat = validate_chat_identifier(chat_id)
        project = validate_project_identifier(project_id) if project_id is not None else None
        expected = _validate_revision(expected_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        "SELECT updated_at,project_id FROM chats WHERE identifier=? AND revision=?",
                        (chat, expected),
                    ).fetchone()
                    if row is None:
                        if connection.execute("SELECT 1 FROM chats WHERE identifier=?", (chat,)).fetchone() is None:
                            raise ArchiveNotFoundError("The selected chat was not found.")
                        raise ArchiveStaleRevisionError("The chat changed after it was loaded.")
                    if project is not None and connection.execute(
                        "SELECT 1 FROM projects WHERE identifier=?", (project,)
                    ).fetchone() is None:
                        raise ArchiveNotFoundError("The selected Project was not found.")
                    if row[1] != project:
                        timestamp = _next_timestamp(self._clock(), row[0])
                        connection.execute(
                            "UPDATE chats SET project_id=?,revision=revision+1,updated_at=? "
                            "WHERE identifier=? AND revision=?",
                            (project, timestamp, chat, expected),
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_chat(chat)
        if verified.metadata.project_id != project:
            raise ArchiveVerificationError("The Project association could not be verified.")
        return verified

    def delete_project(self, identifier: str, *, expected_revision: int) -> None:
        project = validate_project_identifier(identifier)
        expected = _validate_revision(expected_revision)
        detached_chat_ids: tuple[str, ...] = ()
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        "SELECT revision FROM projects WHERE identifier=?", (project,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected Project was not found.")
                    if row[0] != expected:
                        raise ArchiveStaleRevisionError("The Project changed after it was loaded.")
                    chats = connection.execute(
                        "SELECT identifier,updated_at FROM chats WHERE project_id=?", (project,)
                    ).fetchall()
                    detached_chat_ids = tuple(row[0] for row in chats)
                    for chat_id, updated_at in chats:
                        connection.execute(
                            "UPDATE chats SET project_id=NULL,revision=revision+1,updated_at=? "
                            "WHERE identifier=? AND project_id=?",
                            (_next_timestamp(self._clock(), updated_at), chat_id, project),
                        )
                    cursor = connection.execute(
                        "DELETE FROM projects WHERE identifier=? AND revision=?",
                        (project, expected),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError("The Project changed before deletion.")
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        try:
            self.get_project(project)
        except ArchiveNotFoundError:
            try:
                with closing(self._connect()) as connection:
                    remaining = sum(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {table} WHERE project_id=?",
                            (project,),
                        ).fetchone()[0]
                        for table in (
                            "project_state", "project_decisions", "project_questions",
                            "project_plan_items", "project_links",
                            "project_context_receipts",
                        )
                    )
                    attached = connection.execute(
                        "SELECT COUNT(*) FROM chats WHERE project_id=?", (project,)
                    ).fetchone()[0]
                    surviving = connection.execute(
                        "SELECT COUNT(*) FROM chats WHERE identifier IN ("
                        + ",".join("?" for _ in detached_chat_ids)
                        + ")",
                        detached_chat_ids,
                    ).fetchone()[0] if detached_chat_ids else 0
            except sqlite3.Error as exc:
                raise _database_error(exc) from exc
            if (
                remaining == 0
                and attached == 0
                and surviving == len(detached_chat_ids)
            ):
                return
            raise ArchiveVerificationError(
                "The Project deletion ownership boundary could not be verified."
            )
        raise ArchiveVerificationError("The Project deletion could not be verified.")

    def get_memory_extraction(
        self, extraction_id: str
    ) -> MemoryExtractionRecord | None:
        validated = _validate_extraction_identifier(extraction_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT extraction_id, source_chat_id, source_user_sequence, "
                    "source_assistant_sequence, source_archive_revision, provider_id, "
                    "model_id, provider_fingerprint, state, revision, claim_owner, "
                    "plan_json, proposal_json, safe_error_code, created_at, updated_at, "
                    "completed_at FROM memory_extractions WHERE extraction_id=?",
                    (validated,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return _memory_extraction_from_row(row) if row is not None else None

    def list_memory_extractions(self) -> tuple[MemoryExtractionRecord, ...]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT extraction_id, source_chat_id, source_user_sequence, "
                    "source_assistant_sequence, source_archive_revision, provider_id, "
                    "model_id, provider_fingerprint, state, revision, claim_owner, "
                    "plan_json, proposal_json, safe_error_code, created_at, updated_at, "
                    "completed_at FROM memory_extractions "
                    "ORDER BY created_at, extraction_id"
                ).fetchall()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return tuple(_memory_extraction_from_row(row) for row in rows)

    def claim_next_memory_extraction(
        self, process_incarnation: str
    ) -> MemoryExtractionRecord | None:
        owner = _validate_claim_owner(process_incarnation)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        "SELECT extraction_id, revision, updated_at FROM memory_extractions "
                        "WHERE state='pending' OR "
                        "(state IN ('running','planned') AND claim_owner<>?) "
                        "ORDER BY created_at, extraction_id LIMIT 1",
                        (owner,),
                    ).fetchone()
                    if row is None:
                        return None
                    timestamp = _next_timestamp(self._clock(), row[2])
                    cursor = connection.execute(
                        "UPDATE memory_extractions SET state='running', revision=revision+1, "
                        "claim_owner=?, updated_at=? WHERE extraction_id=? AND revision=?",
                        (owner, timestamp, row[0], row[1]),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The extraction claim changed; retry."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        return self.get_memory_extraction(row[0])

    def transition_memory_extraction(
        self,
        extraction_id: str,
        *,
        expected_revision: int,
        process_incarnation: str,
        state: str,
        plan_json: str | None = None,
        proposal_json: str | None = None,
        safe_error_code: str | None = None,
    ) -> MemoryExtractionRecord:
        validated = _validate_extraction_identifier(extraction_id)
        revision = _validate_revision(expected_revision)
        owner = _validate_claim_owner(process_incarnation)
        if state not in {
            "planned", "awaiting_confirmation", "completed", "failed", "cancelled"
        }:
            raise ArchiveValidationError("The extraction transition is invalid.")
        plan = _validate_bounded_json(plan_json, 24_000, "plan")
        proposal = _validate_bounded_json(proposal_json, 12_000, "proposal")
        error = _optional_safe_code(safe_error_code)
        terminal = state in {"completed", "failed", "cancelled"}
        try:
            with closing(self._connect()) as connection:
                with connection:
                    current = connection.execute(
                        "SELECT state, claim_owner, plan_json, proposal_json, updated_at "
                        "FROM memory_extractions WHERE extraction_id=? AND revision=?",
                        (validated, revision),
                    ).fetchone()
                    if current is None:
                        raise ArchiveStaleRevisionError(
                            "The extraction changed after it was loaded."
                        )
                    if current[1] != owner or current[0] not in {"running", "planned"}:
                        raise ArchiveStaleRevisionError(
                            "The extraction is not owned by this process incarnation."
                        )
                    retained_plan = plan if plan is not None else current[2]
                    retained_proposal = proposal if proposal is not None else current[3]
                    if state in {"planned", "awaiting_confirmation", "completed"} and retained_plan is None:
                        raise ArchiveValidationError(
                            "A planned extraction requires a durable plan."
                        )
                    timestamp = _next_timestamp(self._clock(), current[4])
                    cursor = connection.execute(
                        "UPDATE memory_extractions SET state=?, revision=revision+1, "
                        "plan_json=?, proposal_json=?, safe_error_code=?, updated_at=?, "
                        "completed_at=?, claim_owner=? WHERE extraction_id=? AND revision=?",
                        (
                            state, retained_plan, retained_proposal, error, timestamp,
                            timestamp if terminal else None,
                            None if terminal or state == "awaiting_confirmation" else owner,
                            validated, revision,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The extraction changed after it was loaded."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        result = self.get_memory_extraction(validated)
        if result is None:
            raise ArchiveVerificationError(
                "The extraction transition committed but could not be verified."
            )
        return result

    def claim_memory_confirmation(
        self,
        extraction_id: str,
        *,
        expected_revision: int,
        process_incarnation: str,
    ) -> MemoryExtractionRecord:
        validated = _validate_extraction_identifier(extraction_id)
        revision = _validate_revision(expected_revision)
        owner = _validate_claim_owner(process_incarnation)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    current = connection.execute(
                        "SELECT updated_at FROM memory_extractions "
                        "WHERE extraction_id=? AND revision=? "
                        "AND state='awaiting_confirmation'",
                        (validated, revision),
                    ).fetchone()
                    if current is None:
                        raise ArchiveStaleRevisionError(
                            "That memory proposal is stale or was already decided."
                        )
                    timestamp = _next_timestamp(self._clock(), current[0])
                    cursor = connection.execute(
                        "UPDATE memory_extractions SET state='planned', "
                        "revision=revision+1, claim_owner=?, updated_at=? "
                        "WHERE extraction_id=? AND revision=? "
                        "AND state='awaiting_confirmation'",
                        (owner, timestamp, validated, revision),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "That memory proposal is stale or was already decided."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        result = self.get_memory_extraction(validated)
        if result is None:
            raise ArchiveVerificationError(
                "The proposal claim committed but could not be verified."
            )
        return result

    def extraction_source_entries(
        self, record: MemoryExtractionRecord
    ) -> tuple[ArchiveEntry, ArchiveEntry] | None:
        if not isinstance(record, MemoryExtractionRecord):
            raise ArchiveValidationError("The extraction record is invalid.")
        try:
            chat = self.get_chat(record.source_chat_id)
        except ArchiveNotFoundError:
            return None
        if (
            record.source_user_sequence >= len(chat.entries)
            or record.source_assistant_sequence >= len(chat.entries)
        ):
            return None
        user = chat.entries[record.source_user_sequence]
        assistant = chat.entries[record.source_assistant_sequence]
        if not _eligible_extraction_source(
            user, assistant, record.provider_id, record.model_id
        ):
            return None
        return user, assistant

    def reconcile_chat(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
        provider: str | None = None,
        model: str | None = None,
        label: str | None = None,
        _scheduled_work_origin: bool = False,
        _project_origin: bool = False,
        _coding_work_origin: bool = False,
        _planning_origin: bool = False,
        memory_extraction: MemoryExtractionRequest | None = None,
        project_context_receipt: ProjectContextReceiptInput | None = None,
    ) -> ArchivedChat:
        """Reconcile a complete authoritative transcript without rewriting history."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        supplied = validate_archive_entries(
            entries, _allow_legacy_application_events=True
        )
        selected_provider = _optional_metadata(provider, "provider")
        selected_model = _optional_metadata(model, "model")
        if (selected_provider is None) != (selected_model is None):
            raise ArchiveValidationError(
                "Selected provider and model metadata must be supplied together."
            )
        supplied_label = _validate_label(label) if label is not None else None

        try:
            with closing(self._connect()) as connection:
                with connection:
                    chat_row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if chat_row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    current_metadata = _metadata_from_row(chat_row)
                    if current_metadata.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    current_rows = connection.execute(
                        """
                        SELECT sequence, role, text, sources_json, provider, model,
                               created_at, application_event_id, application_event_type,
                               context_json
                        FROM transcript_entries
                        WHERE chat_id = ? ORDER BY sequence ASC
                        """,
                        (validated_id,),
                    ).fetchall()
                    current_entries = _entries_from_rows(current_rows)
                    if len(supplied) < len(current_entries) or not all(
                        _entry_matches_assertion(asserted, stored)
                        for asserted, stored in zip(
                            supplied[: len(current_entries)], current_entries
                        )
                    ):
                        raise ArchiveDivergenceError(
                            "The supplied transcript diverges from the canonical chat."
                        )

                    suffix = supplied[len(current_entries) :]
                    if any(
                        item.application_event_type in LEGACY_APPLICATION_EVENT_TYPES
                        for item in suffix
                    ):
                        raise ArchiveValidationError(
                            "Retired application event types cannot be written to new entries."
                        )
                    extraction = (
                        _validate_memory_extraction_request(memory_extraction, supplied)
                        if memory_extraction is not None else None
                    )
                    if extraction is not None and (
                        extraction.user_sequence < len(current_entries)
                        or extraction.assistant_sequence >= len(supplied)
                    ):
                        raise ArchiveValidationError(
                            "Memory extraction must bind the newly appended model turn."
                        )
                    attributions = completed_model_attributions(supplied)
                    if not attributions:
                        if _coding_work_origin:
                            validate_coding_work_origin_suffix(suffix)
                        elif _planning_origin:
                            validate_planning_origin_suffix(suffix)
                        elif _project_origin:
                            validate_project_result_suffix(suffix)
                        elif _scheduled_work_origin:
                            validate_scheduled_work_origin_suffix(suffix)
                        else:
                            raise ArchiveValidationError(
                                "A chat requires a completed provider/model exchange."
                            )
                    elif _scheduled_work_origin:
                        validate_scheduled_work_origin_suffix(suffix)
                    target_selected_provider = (
                        selected_provider or current_metadata.selected_provider
                    )
                    target_selected_model = selected_model or current_metadata.selected_model
                    target_label = supplied_label or current_metadata.label
                    if (
                        supplied_label is None
                        and current_metadata.completed_turn_count < 2
                        and current_metadata.label in _PROVISIONAL_CHAT_LABELS
                        and current_metadata.label
                        == derive_chat_label(
                            current_entries, created_at=current_metadata.created_at
                        )
                    ):
                        refined_label = derive_chat_label(
                            supplied, created_at=current_metadata.created_at
                        )
                        if refined_label not in _PROVISIONAL_CHAT_LABELS:
                            target_label = refined_label
                    metadata_changed = (
                        target_selected_provider != current_metadata.selected_provider
                        or target_selected_model != current_metadata.selected_model
                        or target_label != current_metadata.label
                    )
                    if not suffix and not metadata_changed:
                        return ArchivedChat(current_metadata, current_entries)
                    prior_attributions = completed_model_attributions(current_entries)
                    new_model_turns = max(
                        0, len(attributions) - len(prior_attributions)
                    )
                    completed_turns = (
                        current_metadata.completed_turn_count + new_model_turns
                    )
                    first_provider = (
                        current_metadata.first_provider
                        if current_metadata.completed_turn_count > 0
                        else (attributions[0][0] if attributions else None)
                    )
                    first_model = (
                        current_metadata.first_model
                        if current_metadata.completed_turn_count > 0
                        else (attributions[0][1] if attributions else None)
                    )
                    latest_provider = attributions[-1][0] if attributions else None
                    latest_model = attributions[-1][1] if attributions else None
                    timestamp = _next_timestamp(self._clock(), current_metadata.updated_at)
                    stamped_suffix = _prepare_suffix_entries(
                        suffix,
                        previous_entry_timestamp=current_entries[-1].created_at,
                        updated_at=timestamp,
                    )
                    self._insert_entries(
                        connection, validated_id, len(current_entries), stamped_suffix
                    )
                    receipt = (
                        _prepare_project_context_receipt(
                            project_context_receipt,
                            chat_id=validated_id,
                            entries=supplied,
                            chat_project_id=current_metadata.project_id,
                            created_at=timestamp,
                            minimum_sequence=len(current_entries),
                        )
                        if project_context_receipt is not None else None
                    )
                    if receipt is not None:
                        self._insert_project_context_receipt(connection, receipt)
                    if extraction is not None:
                        self._insert_memory_extraction(
                            connection, validated_id, expected + 1,
                            extraction, timestamp,
                        )
                    cursor = connection.execute(
                        """
                        UPDATE chats SET label = ?, updated_at = ?, revision = ?,
                            first_provider = ?, first_model = ?, latest_provider = ?,
                            latest_model = ?, selected_provider = ?, selected_model = ?,
                            entry_count = ?, completed_turn_count = ?
                        WHERE identifier = ? AND revision = ?
                        """,
                        (
                            target_label,
                            timestamp,
                            expected + 1,
                            first_provider,
                            first_model,
                            latest_provider,
                            latest_model,
                            target_selected_provider,
                            target_selected_model,
                            len(supplied),
                            completed_turns,
                            validated_id,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc

        try:
            verified = self.get_chat(validated_id)
            verified_extraction = (
                self.get_memory_extraction(extraction.extraction_id)
                if extraction is not None else None
            )
            verified_receipt = (
                self.get_project_context_receipt(
                    validated_id, receipt.assistant_sequence
                )
                if receipt is not None else None
            )
        except ConversationArchiveError as exc:
            raise ArchiveVerificationError(
                "The chat reconciliation was committed but could not be verified."
            ) from exc
        expected_entries = (*current_entries, *stamped_suffix)
        if (
            verified.metadata.revision < expected + 1
            or verified.metadata.created_at != current_metadata.created_at
            or verified.metadata.updated_at < timestamp
            or len(verified.entries) < len(expected_entries)
            or verified.entries[: len(expected_entries)] != expected_entries
            or (
                verified.metadata.revision == expected + 1
                and (
                    verified.metadata.updated_at != timestamp
                    or len(verified.entries) != len(expected_entries)
                )
            )
            or (
                receipt is not None and verified_receipt != receipt
            )
            or (
                extraction is not None
                and (
                    verified_extraction is None
                    or verified_extraction.source_chat_id != validated_id
                    or verified_extraction.source_archive_revision != expected + 1
                    or verified_extraction.state != "pending"
                )
            )
        ):
            raise ArchiveVerificationError(
                "The chat reconciliation was committed but could not be verified."
            )
        return verified

    def reconcile_scheduled_work_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ArchivedChat:
        """Reconcile only the narrow confirmed Scheduled Work origin suffix."""

        reconciled = self.reconcile_chat(
            identifier,
            entries,
            expected_revision=expected_revision,
            _scheduled_work_origin=True,
        )
        self.set_active_chat(
            reconciled.metadata.identifier,
            expected_revision=reconciled.metadata.revision,
        )
        return self.get_chat(reconciled.metadata.identifier)

    def reconcile_project_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ArchivedChat:
        """Append only verified Project result events to a zero-turn origin."""

        return self.reconcile_chat(
            identifier,
            entries,
            expected_revision=expected_revision,
            _project_origin=True,
        )

    def reconcile_coding_work_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ArchivedChat:
        """Append one verified Coding Work proposal/result unit to a zero-turn chat."""

        return self.reconcile_chat(
            identifier,
            entries,
            expected_revision=expected_revision,
            _coding_work_origin=True,
        )

    def reconcile_planning_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ArchivedChat:
        """Append one verified Planning exchange/result to a zero-turn chat."""

        return self.reconcile_chat(
            identifier,
            entries,
            expected_revision=expected_revision,
            _planning_origin=True,
        )

    def select_chat_model(
        self,
        identifier: str,
        *,
        expected_revision: int,
        provider: str,
        model: str,
    ) -> ArchivedChat:
        """Change selected-model state without changing execution attribution."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        selected_provider = _required_metadata(provider, "provider")
        selected_model = _required_metadata(model, "model")
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    current = _metadata_from_row(row)
                    if current.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    if (
                        current.selected_provider == selected_provider
                        and current.selected_model == selected_model
                    ):
                        return self.get_chat(validated_id)
                    timestamp = _next_timestamp(self._clock(), current.updated_at)
                    cursor = connection.execute(
                        "UPDATE chats SET selected_provider=?,selected_model=?,"
                        "updated_at=?,revision=revision+1 WHERE identifier=? AND revision=?",
                        (
                            selected_provider,
                            selected_model,
                            timestamp,
                            validated_id,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_chat(validated_id)
        if (
            verified.metadata.revision != expected + 1
            or verified.metadata.selected_provider != selected_provider
            or verified.metadata.selected_model != selected_model
        ):
            raise ArchiveVerificationError(
                "The selected model was committed but could not be verified."
            )
        return verified

    def select_chat_context(
        self,
        identifier: str,
        *,
        expected_revision: int,
        policy: str,
    ) -> ArchivedChat:
        """Change selected context policy without changing transcript content."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        selected_policy = _validate_context_policy(policy)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    current = _metadata_from_row(row)
                    if current.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    if current.selected_context_policy == selected_policy:
                        return self.get_chat(validated_id)
                    timestamp = _next_timestamp(self._clock(), current.updated_at)
                    cursor = connection.execute(
                        "UPDATE chats SET selected_context_policy=?,updated_at=?,"
                        "revision=revision+1 WHERE identifier=? AND revision=?",
                        (selected_policy, timestamp, validated_id, expected),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_chat(validated_id)
        if (
            verified.metadata.revision != expected + 1
            or verified.metadata.selected_context_policy != selected_policy
        ):
            raise ArchiveVerificationError(
                "The selected context policy was committed but could not be verified."
            )
        return verified

    def select_chat_configuration(
        self,
        identifier: str,
        *,
        expected_revision: int,
        provider: str,
        model: str,
        policy: str,
    ) -> ArchivedChat:
        """Atomically change model identity and context policy only."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        selected_provider = _required_metadata(provider, "provider")
        selected_model = _required_metadata(model, "model")
        selected_policy = _validate_context_policy(policy)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    current = _metadata_from_row(row)
                    if current.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    if (
                        current.selected_provider == selected_provider
                        and current.selected_model == selected_model
                        and current.selected_context_policy == selected_policy
                    ):
                        return self.get_chat(validated_id)
                    timestamp = _next_timestamp(self._clock(), current.updated_at)
                    cursor = connection.execute(
                        "UPDATE chats SET selected_provider=?,selected_model=?,"
                        "selected_context_policy=?,updated_at=?,revision=revision+1 "
                        "WHERE identifier=? AND revision=?",
                        (
                            selected_provider,
                            selected_model,
                            selected_policy,
                            timestamp,
                            validated_id,
                            expected,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_chat(validated_id)
        if (
            verified.metadata.revision != expected + 1
            or verified.metadata.selected_provider != selected_provider
            or verified.metadata.selected_model != selected_model
            or verified.metadata.selected_context_policy != selected_policy
        ):
            raise ArchiveVerificationError(
                "The conversation configuration was committed but could not be verified."
            )
        return verified

    def get_active_chat_id(self) -> str | None:
        """Return the one canonical nullable active-chat pointer."""

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT active_chat_id FROM archive_state WHERE singleton = 1"
                ).fetchone()
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            raise ArchiveCorruptError("The conversation archive has invalid state.")
        if row[0] is None:
            return None
        return validate_chat_identifier(row[0])

    def append_application_event(
        self,
        chat_id: object,
        *,
        expected_revision: object,
        event_id: object,
        event_type: object,
        text: object,
    ) -> ArchivedChat:
        """Append one globally idempotent, application-authored assistant event."""

        validated_chat = validate_chat_identifier(chat_id)
        expected = _validate_revision(expected_revision)
        event_entry = validate_archive_entries((ArchiveEntry(
            "assistant",
            text,  # type: ignore[arg-type]
            application_event_id=event_id,  # type: ignore[arg-type]
            application_event_type=event_type,  # type: ignore[arg-type]
        ),))[0]
        assert event_entry.application_event_id is not None
        assert event_entry.application_event_type is not None
        try:
            with closing(self._connect()) as connection:
                with connection:
                    existing = self._event_row(
                        connection, event_entry.application_event_id
                    )
                    if existing is not None:
                        self._require_event_match(existing, validated_chat, event_entry)
                        return self.get_chat(validated_chat)
                    chat_row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_chat,)
                    ).fetchone()
                    if chat_row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    metadata = _metadata_from_row(chat_row)
                    if metadata.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    timestamp = _next_timestamp(self._clock(), metadata.updated_at)
                    stamped = ArchiveEntry(
                        event_entry.role, event_entry.text, (), None, None,
                        timestamp, None, event_entry.application_event_id,
                        event_entry.application_event_type,
                    )
                    self._require_special_origin_append(
                        connection, validated_chat, metadata, stamped
                    )
                    self._insert_entries(
                        connection, validated_chat, metadata.entry_count, (stamped,)
                    )
                    cursor = connection.execute(
                        """
                        UPDATE chats SET updated_at=?, revision=revision+1,
                            entry_count=entry_count+1
                        WHERE identifier=? AND revision=?
                        """,
                        (timestamp, validated_chat, expected),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
        except sqlite3.IntegrityError as exc:
            try:
                with closing(self._connect()) as retry_connection:
                    existing = self._event_row(
                        retry_connection, event_entry.application_event_id
                    )
                    if existing is None:
                        raise _database_error(exc) from exc
                    self._require_event_match(existing, validated_chat, event_entry)
            except ConversationArchiveError:
                raise
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        verified = self.get_chat(validated_chat)
        matches = [
            item for item in verified.entries
            if item.application_event_id == event_entry.application_event_id
        ]
        if len(matches) != 1 or not _application_event_matches(matches[0], event_entry):
            raise ArchiveVerificationError(
                "The application event was committed but could not be verified."
            )
        return verified

    def _require_special_origin_append(
        self,
        connection: sqlite3.Connection,
        chat_id: str,
        metadata: ChatMetadata,
        entry: ArchiveEntry,
    ) -> None:
        """Reject one append that would leave a special-origin chat invalid."""

        if metadata.completed_turn_count != 0:
            return
        rows = connection.execute(
            """
            SELECT sequence, role, text, sources_json, provider, model,
                   created_at, application_event_id, application_event_type,
                   context_json
            FROM transcript_entries WHERE chat_id=? ORDER BY sequence ASC
            """,
            (chat_id,),
        ).fetchall()
        existing = _entries_from_rows(rows)
        try:
            kind, length = validate_zero_turn_chat_entries(existing)
        except ArchiveValidationError as exc:
            raise ArchiveCorruptError(str(exc)) from exc
        if kind == "scheduled_work":
            return
        if kind == "terminal":
            raise ArchiveValidationError("An unresolved terminal origin cannot accept application events.")
        candidate = (*existing[length:], entry)
        try:
            if kind == "project":
                validate_project_event_sequence(candidate)
            elif kind == "coding_work":
                validate_coding_work_event_sequence(candidate)
            elif kind == "planning":
                validate_planning_event_sequence(candidate)
            else:
                _validate_legacy_research_event_sequence(candidate)
        except ArchiveValidationError as exc:
            raise ArchiveValidationError(
                "This conversation cannot accept that application event."
            ) from exc

    def get_application_event(self, event_id: object) -> ApplicationEventRecord | None:
        """Look up one exact application event without reading other entries."""

        if (
            not isinstance(event_id, str)
            or re.fullmatch(r"event-[0-9a-f]{32}", event_id) is None
        ):
            raise ArchiveValidationError("Application event identifiers are invalid.")
        try:
            with closing(self._connect()) as connection:
                row = self._event_row(connection, event_id)
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        if row is None:
            return None
        sources, web_search = _sources_from_json(row[4])
        entry = ArchiveEntry(
            row[2], row[3], sources, row[5], row[6], row[7], web_search,
            row[8], row[9], _context_from_json(row[10]),
        )
        try:
            validated = validate_archive_entries((entry,))[0]
        except ArchiveValidationError as exc:
            raise ArchiveCorruptError(
                "The conversation archive contains an invalid application event."
            ) from exc
        return ApplicationEventRecord(
            validate_chat_identifier(row[0]), int(row[1]), validated
        )

    @staticmethod
    def _event_row(
        connection: sqlite3.Connection, event_id: str
    ) -> sqlite3.Row | Sequence[object] | None:
        return connection.execute(
            """
            SELECT chat_id, sequence, role, text, sources_json, provider, model,
                   created_at, application_event_id, application_event_type,
                   context_json
            FROM transcript_entries WHERE application_event_id=?
            """,
            (event_id,),
        ).fetchone()

    @staticmethod
    def _require_event_match(
        row: Sequence[object], chat_id: str, asserted: ArchiveEntry
    ) -> None:
        sources, web_search = _sources_from_json(row[4])
        stored = ArchiveEntry(
            row[2], row[3], sources, row[5], row[6], row[7], web_search,
            row[8], row[9], _context_from_json(row[10]),
        )
        try:
            stored = validate_archive_entries((stored,))[0]
        except ArchiveValidationError as exc:
            raise ArchiveCorruptError(
                "The conversation archive contains an invalid application event."
            ) from exc
        if row[0] != chat_id or not _application_event_matches(stored, asserted):
            raise ArchiveConflictError(
                "That application event identifier already has different semantics."
            )

    def set_active_chat(
        self,
        identifier: str | None,
        *,
        expected_revision: int | None = None,
    ) -> str | None:
        """Set, replace, or clear the canonical active-chat pointer."""

        validated_id = (
            validate_chat_identifier(identifier) if identifier is not None else None
        )
        if expected_revision is not None:
            expected_revision = _validate_revision(expected_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    if validated_id is not None:
                        row = connection.execute(
                            "SELECT revision FROM chats WHERE identifier = ?",
                            (validated_id,),
                        ).fetchone()
                        if row is None:
                            raise ArchiveNotFoundError("The selected chat was not found.")
                        if expected_revision is not None and row[0] != expected_revision:
                            raise ArchiveStaleRevisionError(
                                "The chat changed after it was loaded; refresh and try again."
                            )
                    self._set_active(connection, validated_id)
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        try:
            active_id = self.get_active_chat_id()
        except ConversationArchiveError as exc:
            raise ArchiveVerificationError(
                "The active chat selection could not be verified."
            ) from exc
        if active_id != validated_id:
            raise ArchiveVerificationError(
                "The active chat selection could not be verified."
            )
        return validated_id

    def mark_chat_opened(
        self,
        identifier: str,
        *,
        expected_revision: int,
        select_active: bool = True,
    ) -> ArchivedChat:
        """Record an explicit open and optionally select the chat atomically."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    current = _metadata_from_row(row)
                    if current.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    timestamp = _next_timestamp(self._clock(), current.updated_at)
                    cursor = connection.execute(
                        """
                        UPDATE chats SET last_opened_at = ?, updated_at = ?, revision = ?
                        WHERE identifier = ? AND revision = ?
                        """,
                        (timestamp, timestamp, expected + 1, validated_id, expected),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; refresh and try again."
                        )
                    if select_active:
                        self._set_active(connection, validated_id)
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc
        try:
            verified = self.get_chat(validated_id)
            active_id = self.get_active_chat_id() if select_active else None
        except ConversationArchiveError as exc:
            raise ArchiveVerificationError(
                "The opened chat state could not be verified."
            ) from exc
        if (
            verified.metadata.revision != expected + 1
            or verified.metadata.last_opened_at != timestamp
            or verified.metadata.updated_at != timestamp
            or (select_active and active_id != validated_id)
        ):
            raise ArchiveVerificationError(
                "The opened chat state could not be verified."
            )
        return verified

    def delete_chat(
        self, identifier: str, *, expected_revision: int
    ) -> ChatMetadata:
        """Revision-bound deletion with fresh absence verification."""

        validated_id = validate_chat_identifier(identifier)
        expected = _validate_revision(expected_revision)
        try:
            with closing(self._connect()) as connection:
                with connection:
                    row = connection.execute(
                        _CHAT_SELECT + " WHERE identifier = ?", (validated_id,)
                    ).fetchone()
                    if row is None:
                        raise ArchiveNotFoundError("The selected chat was not found.")
                    metadata = _metadata_from_row(row)
                    if metadata.revision != expected:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; nothing was removed."
                        )
                    cursor = connection.execute(
                        "DELETE FROM chats WHERE identifier = ? AND revision = ?",
                        (validated_id, expected),
                    )
                    if cursor.rowcount != 1:
                        raise ArchiveStaleRevisionError(
                            "The chat changed after it was loaded; nothing was removed."
                        )
        except ConversationArchiveError:
            raise
        except sqlite3.Error as exc:
            raise _database_error(exc) from exc

        try:
            self.get_chat(validated_id)
        except ArchiveNotFoundError:
            pass
        except ConversationArchiveError as exc:
            raise ArchiveVerificationError(
                "The chat deletion could not be verified."
            ) from exc
        else:
            raise ArchiveVerificationError(
                "The chat deletion could not be verified."
            )
        try:
            listing = self.list_chats()
            active = self.get_active_chat_id()
        except ConversationArchiveError as exc:
            raise ArchiveVerificationError(
                "The chat deletion could not be verified."
            ) from exc
        if any(item.identifier == validated_id for item in listing):
            raise ArchiveVerificationError(
                "The deleted chat still appears in the archive listing."
            )
        if active == validated_id:
            raise ArchiveVerificationError(
                "The deleted chat remains selected."
            )
        return metadata

    def _connect(self) -> sqlite3.Connection:
        parent_descriptor: int | None = None
        database_descriptor: int | None = None
        connection: _ArchiveConnection | None = None
        initial_sidecars: dict[str, os.stat_result | None] = {}
        try:
            parent_descriptor, database_name = self._open_storage_parent(create=True)
            for suffix in ("-journal", "-wal", "-shm"):
                initial_sidecars[suffix] = _stat_at(
                    parent_descriptor, database_name + suffix
                )
            existing_stat = _stat_at(parent_descriptor, database_name)
            flags = os.O_RDWR | _no_follow_flag() | _close_on_exec_flag()
            if existing_stat is None:
                if any(item is not None for item in initial_sidecars.values()):
                    raise OSError("orphaned archive sidecar exists")
                self._initialize_then_publish(
                    parent_descriptor, database_name, flags
                )
                existing_stat = _stat_at(parent_descriptor, database_name)
            if existing_stat is None or not stat.S_ISREG(existing_stat.st_mode):
                raise OSError("unsafe archive database entry")
            database_descriptor = os.open(
                database_name, flags, dir_fd=parent_descriptor
            )
            if not _same_file(existing_stat, os.fstat(database_descriptor)):
                raise OSError("archive database changed during safe open")

            sqlite_path = f"/proc/self/fd/{parent_descriptor}/{database_name}"
            validation_uri = (
                "file:"
                + quote(sqlite_path, safe="/")
                + "?mode=ro&immutable=1"
            )
            validation_connection = sqlite3.connect(
                validation_uri,
                timeout=5.0,
                isolation_level="DEFERRED",
                factory=_ArchiveConnection,
                uri=True,
            )
            try:
                self._validate_schema(validation_connection)
            finally:
                validation_connection.close()
            connection = sqlite3.connect(
                sqlite_path,
                timeout=5.0,
                isolation_level="DEFERRED",
                factory=_ArchiveConnection,
            )
            current_stat = _stat_at(parent_descriptor, database_name)
            if current_stat is None or not _same_file(
                os.fstat(database_descriptor), current_stat
            ):
                raise OSError("archive database changed during SQLite open")

            self._validate_schema(connection)
            self._apply_settings(connection)
            connection.row_factory = sqlite3.Row
            connection._archive_descriptors = (
                parent_descriptor,
                database_descriptor,
            )
            return connection
        except ConversationArchiveError as exc:
            failure: BaseException = exc
        except sqlite3.DatabaseError as exc:
            failure = ArchiveCorruptError(
                "Tori's conversation archive is corrupt or unreadable; it was not replaced."
            )
        except (OSError, sqlite3.Error) as exc:
            failure = ArchiveUnavailableError(
                "Tori's conversation archive is unavailable."
            )

        if connection is not None:
            connection.close()
        for descriptor in (database_descriptor, parent_descriptor):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        raise failure

    def _initialize_then_publish(
        self, parent_descriptor: int, database_name: str, flags: int
    ) -> None:
        """Build away from the canonical name and publish without replacement."""

        temporary_name: str | None = None
        database_descriptor: int | None = None
        connection: sqlite3.Connection | None = None
        published = False
        try:
            for _attempt in range(MAX_INITIALIZATION_NAME_ATTEMPTS):
                candidate = (
                    f".{database_name}.incomplete-{secrets.token_hex(16)}"
                )
                try:
                    database_descriptor = os.open(
                        candidate,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_descriptor,
                    )
                except FileExistsError:
                    continue
                temporary_name = candidate
                break
            if temporary_name is None or database_descriptor is None:
                raise OSError("archive initialization name allocation failed")

            temporary_stat = os.fstat(database_descriptor)
            sqlite_path = (
                f"/proc/self/fd/{parent_descriptor}/{temporary_name}"
            )
            connection = sqlite3.connect(
                sqlite_path,
                timeout=5.0,
                isolation_level="DEFERRED",
                factory=_ArchiveConnection,
            )
            current = _stat_at(parent_descriptor, temporary_name)
            if current is None or not _same_file(temporary_stat, current):
                raise OSError("archive initialization entry changed during SQLite open")
            self._apply_settings(connection)
            self._create_schema(connection)
            self._validate_schema(connection)
            connection.close()
            connection = None

            for suffix in ("-journal", "-wal", "-shm"):
                if _stat_at(parent_descriptor, temporary_name + suffix) is not None:
                    raise OSError("incomplete archive initialization sidecar exists")
            current = _stat_at(parent_descriptor, temporary_name)
            if current is None or not _same_file(temporary_stat, current):
                raise OSError("archive initialization entry changed before publication")
            os.fsync(database_descriptor)
            _rename_without_replacement(
                parent_descriptor,
                temporary_name,
                database_name,
            )
            published = True
            os.fsync(parent_descriptor)
        except BaseException as exc:
            if published:
                raise
            artifact = temporary_name or "the allocated initialization entry"
            raise ArchiveUnavailableError(
                "Tori's conversation archive initialization failed; the isolated "
                f"artifact {artifact!r} was preserved for safe inspection."
            ) from exc
        finally:
            if connection is not None:
                connection.close()
            if database_descriptor is not None:
                os.close(database_descriptor)

    def _open_storage_parent(self, *, create: bool) -> tuple[int, str]:
        try:
            raw_path = os.fspath(self._path)
            if not isinstance(raw_path, str) or "\x00" in raw_path:
                raise ValueError("unsafe archive path")
            raw_parts = Path(raw_path).parts
            if ".." in raw_parts:
                raise ValueError("unsafe archive path")
            absolute_path = Path(os.path.abspath(os.path.normpath(raw_path)))
            database_name = absolute_path.name
            if not database_name or database_name in {".", ".."}:
                raise ValueError("unsafe archive path")
        except (OSError, TypeError, ValueError) as exc:
            raise ArchiveUnavailableError(
                "Tori's conversation archive path is unavailable or unsafe."
            ) from exc

        flags = os.O_RDONLY | _directory_flag() | _no_follow_flag() | _close_on_exec_flag()
        try:
            descriptor = os.open("/", flags)
        except OSError as exc:
            raise ArchiveUnavailableError(
                "Tori's conversation archive path is unavailable or unsafe."
            ) from exc
        try:
            for component in absolute_path.parent.parts[1:]:
                try:
                    child_descriptor = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child_descriptor = os.open(component, flags, dir_fd=descriptor)
                child_stat = os.fstat(child_descriptor)
                if not stat.S_ISDIR(child_stat.st_mode):
                    os.close(child_descriptor)
                    raise OSError("archive parent is not a directory")
                os.close(descriptor)
                descriptor = child_descriptor
            return descriptor, database_name
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _apply_settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("PRAGMA journal_mode = DELETE")

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute(_METADATA_SQL)
            connection.execute(_PROJECTS_SQL)
            connection.execute(_CHATS_SQL)
            connection.execute(_ENTRIES_SQL)
            connection.execute(_EVENT_INDEX_SQL)
            connection.execute(_STATE_SQL)
            connection.execute(_EXTRACTIONS_SQL)
            connection.execute(_EXTRACTIONS_FIFO_INDEX_SQL)
            _create_schema7_project_objects(connection)
            connection.execute(
                "INSERT INTO archive_metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(ARCHIVE_SCHEMA_VERSION)),
            )
            connection.execute(
                "INSERT INTO archive_state (singleton, active_chat_id) VALUES (1, NULL)"
            )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        metadata_table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='archive_metadata'"
        ).fetchone()
        if metadata_table is not None and isinstance(metadata_table[0], str) and (
            _normalize_schema_sql(metadata_table[0]) == _normalize_schema_sql(_METADATA_SQL)
        ):
            metadata_rows = connection.execute(
                "SELECT key, value FROM archive_metadata"
            ).fetchall()
            if (
                len(metadata_rows) == 1
                and metadata_rows[0][0] == "schema_version"
                and metadata_rows[0][1] == str(LEGACY_ARCHIVE_SCHEMA_VERSION)
                and _legacy_schema_objects_are_exact(connection)
            ):
                raise ArchiveVersionError(
                    "Tori's conversation archive uses schema version 2; "
                    "run the explicit 2-to-3 schema migration while Tori is stopped. "
                    "It was not modified."
                )
            if (
                len(metadata_rows) == 1
                and metadata_rows[0][0] == "schema_version"
                and metadata_rows[0][1] == str(SCHEMA3_ARCHIVE_SCHEMA_VERSION)
                and _schema3_objects_are_exact(connection)
            ):
                raise ArchiveVersionError(
                    "Tori's conversation archive uses schema version 3; "
                    "run the explicit 3-to-4 schema migration while Tori is stopped. "
                    "It was not modified."
                )
            if (
                len(metadata_rows) == 1
                and metadata_rows[0][0] == "schema_version"
                and metadata_rows[0][1] == str(SCHEMA4_ARCHIVE_SCHEMA_VERSION)
                and _schema4_objects_are_exact(connection)
            ):
                raise ArchiveVersionError(
                    "Tori's conversation archive uses schema version 4; "
                    "run the explicit 4-to-5 schema migration while Tori is stopped. "
                    "It was not modified."
                )
            if (
                len(metadata_rows) == 1
                and metadata_rows[0][0] == "schema_version"
                and metadata_rows[0][1] == str(SCHEMA5_ARCHIVE_SCHEMA_VERSION)
                and _schema5_objects_are_exact(connection)
            ):
                raise ArchiveVersionError(
                    "Tori's conversation archive uses schema version 5; "
                    "run the explicit 5-to-6 schema migration while Tori is stopped. "
                    "It was not modified."
                )
            if (
                len(metadata_rows) == 1
                and metadata_rows[0][0] == "schema_version"
                and metadata_rows[0][1] == str(PREVIOUS_ARCHIVE_SCHEMA_VERSION)
                and _schema6_objects_are_exact(connection)
            ):
                raise ArchiveVersionError(
                    "Tori's conversation archive uses schema version 6; "
                    "run the explicit 6-to-7 schema migration while Tori is stopped. "
                    "It was not modified."
                )
        expected_table_sql = {
            "archive_metadata": _METADATA_SQL,
            "projects": _PROJECTS_SQL,
            "chats": _CHATS_SQL,
            "transcript_entries": _ENTRIES_SQL,
            "archive_state": _STATE_SQL,
            "memory_extractions": _EXTRACTIONS_SQL,
            "project_state": _PROJECT_STATE_SQL,
            "project_decisions": _PROJECT_DECISIONS_SQL,
            "project_questions": _PROJECT_QUESTIONS_SQL,
            "project_plan_items": _PROJECT_PLAN_ITEMS_SQL,
            "project_links": _PROJECT_LINKS_SQL,
            "project_context_receipts": _PROJECT_CONTEXT_RECEIPTS_SQL,
        }
        expected_indexes = {
            "archive_metadata": {
                "sqlite_autoindex_archive_metadata_1": ("pk", ("key",)),
            },
            "projects": {
                "sqlite_autoindex_projects_1": ("pk", ("identifier",)),
            },
            "chats": {
                "sqlite_autoindex_chats_1": ("pk", ("identifier",)),
            },
            "transcript_entries": {
                "sqlite_autoindex_transcript_entries_1": (
                    "pk", ("chat_id", "sequence")
                ),
                "transcript_entries_application_event_id_index": (
                    "c", ("application_event_id",)
                ),
            },
            "archive_state": {
                "sqlite_autoindex_archive_state_1": ("u", ("active_chat_id",)),
            },
            "memory_extractions": {
                "sqlite_autoindex_memory_extractions_1": ("pk", ("extraction_id",)),
                "sqlite_autoindex_memory_extractions_2": (
                    "u", ("source_chat_id", "source_user_sequence", "source_assistant_sequence")
                ),
                "memory_extractions_fifo_index": (
                    "c", ("state", "created_at", "extraction_id")
                ),
            },
            "project_state": {
                "sqlite_autoindex_project_state_1": ("pk", ("project_id",)),
            },
            "project_decisions": {
                "sqlite_autoindex_project_decisions_1": ("pk", ("identifier",)),
                "sqlite_autoindex_project_decisions_2": (
                    "u", ("supersedes_decision_id",)
                ),
                "sqlite_autoindex_project_decisions_3": (
                    "u", ("project_id", "identifier")
                ),
                "project_decisions_state_index": (
                    "c", ("project_id", "state", "updated_at")
                ),
            },
            "project_questions": {
                "sqlite_autoindex_project_questions_1": ("pk", ("identifier",)),
                "project_questions_state_index": (
                    "c", ("project_id", "state", "updated_at")
                ),
            },
            "project_plan_items": {
                "sqlite_autoindex_project_plan_items_1": ("pk", ("identifier",)),
                "project_plan_items_state_index": (
                    "c", ("project_id", "state", "updated_at")
                ),
                "project_plan_items_order_index": (
                    "c", ("project_id", "sort_order", "identifier")
                ),
            },
            "project_links": {
                "sqlite_autoindex_project_links_1": ("pk", ("identifier",)),
                "sqlite_autoindex_project_links_2": (
                    "u", ("project_id", "target_type", "target_id")
                ),
            },
            "project_context_receipts": {
                "sqlite_autoindex_project_context_receipts_1": (
                    "pk", ("chat_id", "assistant_sequence")
                ),
                "project_context_receipts_project_index": ("c", ("project_id",)),
            },
        }
        explicit_index_sql = {
            "transcript_entries_application_event_id_index": _EVENT_INDEX_SQL,
            "memory_extractions_fifo_index": _EXTRACTIONS_FIFO_INDEX_SQL,
            "project_decisions_state_index": _PROJECT_DECISIONS_STATE_INDEX_SQL,
            "project_questions_state_index": _PROJECT_QUESTIONS_STATE_INDEX_SQL,
            "project_plan_items_state_index": _PROJECT_PLAN_ITEMS_STATE_INDEX_SQL,
            "project_plan_items_order_index": _PROJECT_PLAN_ITEMS_ORDER_INDEX_SQL,
            "project_context_receipts_project_index": (
                _PROJECT_CONTEXT_RECEIPTS_PROJECT_INDEX_SQL
            ),
        }
        expected_objects = {
            *(("table", name, name, _normalize_schema_sql(sql))
              for name, sql in expected_table_sql.items()),
            *((
                "index", index_name, table,
                (
                    _normalize_schema_sql(explicit_index_sql[index_name])
                    if index_name in explicit_index_sql else None
                ),
            ) for table, indexes in expected_indexes.items()
              for index_name in indexes),
        }
        expected_objects.add(
            (
                "trigger",
                "project_decisions_immutable_fields",
                "project_decisions",
                _normalize_schema_sql(_PROJECT_DECISIONS_IMMUTABILITY_TRIGGER_SQL),
            )
        )
        actual_objects = set()
        for object_type, name, table_name, sql in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
        ):
            normalized = (
                _normalize_schema_sql(sql) if isinstance(sql, str) else None
            )
            actual_objects.add((object_type, name, table_name, normalized))
        if actual_objects != expected_objects:
            raise ArchiveCorruptError(
                "Tori's conversation archive has an invalid schema; it was not replaced."
            )
        metadata_rows = connection.execute(
            "SELECT key, value FROM archive_metadata"
        ).fetchall()
        if len(metadata_rows) != 1 or metadata_rows[0][0] != "schema_version":
            raise ArchiveCorruptError(
                "Tori's conversation archive has invalid schema metadata."
            )
        if not isinstance(metadata_rows[0][1], str):
            raise ArchiveCorruptError(
                "Tori's conversation archive has an invalid schema version."
            )
        try:
            version = int(metadata_rows[0][1])
        except (TypeError, ValueError) as exc:
            raise ArchiveCorruptError(
                "Tori's conversation archive has an invalid schema version."
            ) from exc
        if version != ARCHIVE_SCHEMA_VERSION:
            raise ArchiveVersionError(
                f"Tori's conversation archive uses unsupported schema version {version}; "
                f"supported version is {ARCHIVE_SCHEMA_VERSION}. It was not modified."
            )
        if metadata_rows[0][1] != str(ARCHIVE_SCHEMA_VERSION):
            raise ArchiveCorruptError(
                "Tori's conversation archive has an invalid schema version."
            )

        expected_columns = {
            "archive_metadata": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
            "chats": (
                ("identifier", "TEXT", 0, 1), ("label", "TEXT", 1, 0),
                ("created_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
                ("last_opened_at", "TEXT", 0, 0), ("revision", "INTEGER", 1, 0),
                ("first_provider", "TEXT", 0, 0), ("first_model", "TEXT", 0, 0),
                ("latest_provider", "TEXT", 0, 0), ("latest_model", "TEXT", 0, 0),
                ("selected_provider", "TEXT", 1, 0),
                ("selected_model", "TEXT", 1, 0),
                ("entry_count", "INTEGER", 1, 0),
                ("completed_turn_count", "INTEGER", 1, 0),
                ("selected_context_policy", "TEXT", 1, 0),
                ("project_id", "TEXT", 0, 0),
            ),
            "projects": (
                ("identifier", "TEXT", 0, 1), ("title", "TEXT", 1, 0),
                ("status", "TEXT", 1, 0), ("objective", "TEXT", 1, 0),
                ("continuity_brief", "TEXT", 1, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
            ),
            "transcript_entries": (
                ("chat_id", "TEXT", 1, 1), ("sequence", "INTEGER", 1, 2),
                ("role", "TEXT", 1, 0), ("text", "TEXT", 1, 0),
                ("sources_json", "TEXT", 0, 0), ("provider", "TEXT", 0, 0),
                ("model", "TEXT", 0, 0), ("created_at", "TEXT", 1, 0),
                ("application_event_id", "TEXT", 0, 0),
                ("application_event_type", "TEXT", 0, 0),
                ("context_json", "TEXT", 0, 0),
            ),
            "archive_state": (
                ("singleton", "INTEGER", 0, 1), ("active_chat_id", "TEXT", 0, 0)
            ),
            "memory_extractions": (
                ("extraction_id", "TEXT", 0, 1),
                ("source_chat_id", "TEXT", 1, 0),
                ("source_user_sequence", "INTEGER", 1, 0),
                ("source_assistant_sequence", "INTEGER", 1, 0),
                ("source_archive_revision", "INTEGER", 1, 0),
                ("provider_id", "TEXT", 1, 0),
                ("model_id", "TEXT", 1, 0),
                ("provider_fingerprint", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0),
                ("revision", "INTEGER", 1, 0),
                ("claim_owner", "TEXT", 0, 0),
                ("plan_json", "TEXT", 0, 0),
                ("proposal_json", "TEXT", 0, 0),
                ("safe_error_code", "TEXT", 0, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
                ("completed_at", "TEXT", 0, 0),
            ),
            "project_state": (
                ("project_id", "TEXT", 1, 1),
                ("phase", "TEXT", 0, 0),
                ("current_focus", "TEXT", 0, 0),
                ("checkpoint", "TEXT", 0, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
            ),
            "project_decisions": (
                ("identifier", "TEXT", 1, 1),
                ("project_id", "TEXT", 1, 0),
                ("text", "TEXT", 1, 0),
                ("importance", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0),
                ("supersedes_decision_id", "TEXT", 0, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
            ),
            "project_questions": (
                ("identifier", "TEXT", 1, 1),
                ("project_id", "TEXT", 1, 0),
                ("text", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0),
                ("disposition_note", "TEXT", 0, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
            ),
            "project_plan_items": (
                ("identifier", "TEXT", 1, 1),
                ("project_id", "TEXT", 1, 0),
                ("text", "TEXT", 1, 0),
                ("state", "TEXT", 1, 0),
                ("state_note", "TEXT", 0, 0),
                ("sort_order", "INTEGER", 1, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
            ),
            "project_links": (
                ("identifier", "TEXT", 1, 1),
                ("project_id", "TEXT", 1, 0),
                ("target_type", "TEXT", 1, 0),
                ("target_id", "TEXT", 1, 0),
                ("revision", "INTEGER", 1, 0),
                ("created_at", "TEXT", 1, 0),
                ("updated_at", "TEXT", 1, 0),
            ),
            "project_context_receipts": (
                ("chat_id", "TEXT", 1, 1),
                ("assistant_sequence", "INTEGER", 1, 2),
                ("project_id", "TEXT", 1, 0),
                ("project_revision", "INTEGER", 1, 0),
                ("estimator_version", "TEXT", 1, 0),
                ("budget_tokens", "INTEGER", 1, 0),
                ("stable_json", "TEXT", 1, 0),
                ("working_json", "TEXT", 1, 0),
                ("historical_json", "TEXT", 1, 0),
                ("omitted_json", "TEXT", 1, 0),
                ("rendered_context", "TEXT", 1, 0),
                ("rendered_digest", "TEXT", 1, 0),
                ("created_at", "TEXT", 1, 0),
            ),
        }
        for table, expected in expected_columns.items():
            actual = tuple(
                (row[1], row[2].upper(), row[3], row[5])
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if actual != expected:
                raise ArchiveCorruptError(
                    "Tori's conversation archive has an invalid schema; it was not replaced."
                )
        for table, expected in expected_table_sql.items():
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if row is None or not isinstance(row[0], str) or (
                _normalize_schema_sql(row[0]) != _normalize_schema_sql(expected)
            ):
                raise ArchiveCorruptError(
                    "Tori's conversation archive has an invalid schema; it was not replaced."
                )
        for table, expected in expected_indexes.items():
            actual_index_list = {
                (row[1], row[2], row[3], row[4])
                for row in connection.execute(f"PRAGMA index_list({table})")
            }
            expected_index_list = {
                (
                    name,
                    1
                    if origin != "c"
                    or name == "transcript_entries_application_event_id_index"
                    else 0,
                    origin,
                    1 if name == "transcript_entries_application_event_id_index" else 0,
                )
                for name, (origin, _columns) in expected.items()
            }
            if actual_index_list != expected_index_list:
                raise ArchiveCorruptError(
                    "Tori's conversation archive has invalid indexes."
                )
            table_columns = {
                row[1]: row[0]
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            for name, (_origin, columns) in expected.items():
                expected_xinfo = tuple(
                    (offset, table_columns[column], column, 0, "BINARY", 1)
                    for offset, column in enumerate(columns)
                ) + ((len(columns), -1, None, 0, "BINARY", 0),)
                actual_xinfo = tuple(
                    connection.execute(f'PRAGMA index_xinfo("{name}")')
                )
                if actual_xinfo != expected_xinfo:
                    raise ArchiveCorruptError(
                        "Tori's conversation archive has invalid indexes."
                    )
                if name in explicit_index_sql:
                    sql_row = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                        (name,),
                    ).fetchone()
                    expected_sql = explicit_index_sql[name]
                    if sql_row is None or _normalize_schema_sql(sql_row[0]) != _normalize_schema_sql(expected_sql):
                        raise ArchiveCorruptError(
                            "Tori's conversation archive has invalid indexes."
                        )
        state_rows = connection.execute(
            "SELECT singleton, active_chat_id FROM archive_state"
        ).fetchall()
        if len(state_rows) != 1 or state_rows[0][0] != 1:
            raise ArchiveCorruptError(
                "Tori's conversation archive has invalid active-chat state."
            )
        foreign_keys = {
            (row[2], row[3], row[4], row[5], row[6], row[7])
            for table in (
                "chats", "transcript_entries", "archive_state", "memory_extractions",
                "project_state", "project_decisions", "project_questions",
                "project_plan_items", "project_links", "project_context_receipts",
            )
            for row in connection.execute(f"PRAGMA foreign_key_list({table})")
        }
        if foreign_keys != {
            ("projects", "project_id", "identifier", "NO ACTION", "SET NULL", "NONE"),
            ("chats", "chat_id", "identifier", "NO ACTION", "CASCADE", "NONE"),
            ("chats", "active_chat_id", "identifier", "NO ACTION", "SET NULL", "NONE"),
            ("chats", "source_chat_id", "identifier", "NO ACTION", "CASCADE", "NONE"),
            ("projects", "project_id", "identifier", "NO ACTION", "CASCADE", "NONE"),
            (
                "project_decisions", "project_id", "project_id",
                "NO ACTION", "NO ACTION", "NONE",
            ),
            (
                "project_decisions", "supersedes_decision_id", "identifier",
                "NO ACTION", "NO ACTION", "NONE",
            ),
            (
                "transcript_entries", "chat_id", "chat_id",
                "NO ACTION", "CASCADE", "NONE",
            ),
            (
                "transcript_entries", "assistant_sequence", "sequence",
                "NO ACTION", "CASCADE", "NONE",
            ),
        }:
            raise ArchiveCorruptError(
                "Tori's conversation archive has invalid foreign keys."
            )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ArchiveCorruptError(
                "Tori's conversation archive has invalid foreign-key data."
            )
        chat_rows = connection.execute(_CHAT_SELECT).fetchall()
        project_rows = connection.execute(_PROJECT_SELECT).fetchall()
        projects = {_project_from_row(row).identifier for row in project_rows}
        for chat_row in chat_rows:
            if chat_row[-1] is not None and chat_row[-1] not in projects:
                raise ArchiveCorruptError(
                    "Tori's conversation archive has an invalid Project association."
                )
            identifier = chat_row[0]
            entry_rows = connection.execute(
                """
                SELECT sequence, role, text, sources_json, provider, model,
                       created_at, application_event_id, application_event_type,
                       context_json
                FROM transcript_entries
                WHERE chat_id = ? ORDER BY sequence ASC
                """,
                (identifier,),
            ).fetchall()
            _chat_from_rows(chat_row, entry_rows)
        extraction_rows = connection.execute(
            "SELECT extraction_id, source_chat_id, source_user_sequence, "
            "source_assistant_sequence, source_archive_revision, provider_id, model_id, "
            "provider_fingerprint, state, revision, claim_owner, plan_json, proposal_json, "
            "safe_error_code, created_at, updated_at, completed_at "
            "FROM memory_extractions ORDER BY created_at, extraction_id"
        ).fetchall()
        for extraction_row in extraction_rows:
            record = _memory_extraction_from_row(extraction_row)
            source_rows = connection.execute(
                "SELECT role,text,provider,model,application_event_id "
                "FROM transcript_entries WHERE chat_id=? AND sequence IN (?,?) "
                "ORDER BY sequence",
                (
                    record.source_chat_id, record.source_user_sequence,
                    record.source_assistant_sequence,
                ),
            ).fetchall()
            if len(source_rows) != 2 or not (
                source_rows[0][0] == "user"
                and source_rows[1][0] == "assistant"
                and source_rows[1][2] == record.provider_id
                and source_rows[1][4] is None
            ):
                raise ArchiveCorruptError(
                    "Tori's conversation archive has an invalid extraction source."
                )
        _validate_project_owned_rows(connection, projects)
        active_id = state_rows[0][1]
        if active_id is not None:
            try:
                validate_chat_identifier(active_id)
            except ArchiveValidationError as exc:
                raise ArchiveCorruptError(
                    "Tori's conversation archive has invalid active-chat state."
                ) from exc
            if not any(row[0] == active_id for row in chat_rows):
                raise ArchiveCorruptError(
                    "Tori's conversation archive has invalid active-chat state."
                )

    @staticmethod
    def _insert_chat(connection: sqlite3.Connection, item: ChatMetadata) -> None:
        connection.execute(
            """
            INSERT INTO chats (
                identifier, label, created_at, updated_at, last_opened_at,
                revision, first_provider, first_model, latest_provider,
                latest_model, selected_provider, selected_model, entry_count,
                completed_turn_count, selected_context_policy, project_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.identifier, item.label, item.created_at, item.updated_at,
                item.last_opened_at, item.revision, item.first_provider,
                item.first_model, item.latest_provider, item.latest_model,
                item.selected_provider, item.selected_model,
                item.entry_count, item.completed_turn_count,
                item.selected_context_policy, item.project_id,
            ),
        )

    @staticmethod
    def _insert_project(connection: sqlite3.Connection, item: ProjectRecord) -> None:
        connection.execute(
            "INSERT INTO projects (identifier,title,status,objective,continuity_brief,"
            "revision,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (item.identifier, item.title, item.status, item.objective,
             item.continuity_brief, item.revision, item.created_at, item.updated_at),
        )

    @staticmethod
    def _insert_entries(
        connection: sqlite3.Connection,
        chat_id: str,
        start: int,
        entries: Sequence[ArchiveEntry],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO transcript_entries (
                chat_id, sequence, role, text, sources_json, provider, model,
                created_at, application_event_id, application_event_type,
                context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chat_id, start + offset, entry.role, entry.text,
                    _sources_json(entry.sources, entry.web_search), entry.provider, entry.model,
                    entry.created_at, entry.application_event_id,
                    entry.application_event_type, _context_json(entry.context),
                )
                for offset, entry in enumerate(entries)
            ],
        )

    @staticmethod
    def _insert_memory_extraction(
        connection: sqlite3.Connection,
        chat_id: str,
        archive_revision: int,
        request: MemoryExtractionRequest,
        timestamp: str,
    ) -> None:
        connection.execute(
            """INSERT INTO memory_extractions (
                extraction_id, source_chat_id, source_user_sequence,
                source_assistant_sequence, source_archive_revision, provider_id,
                model_id, provider_fingerprint, state, revision, claim_owner,
                plan_json, proposal_json, safe_error_code, created_at, updated_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, NULL, NULL, NULL,
                      NULL, ?, ?, NULL)""",
            (
                request.extraction_id, chat_id, request.user_sequence,
                request.assistant_sequence, archive_revision, request.provider_id,
                request.model_id, request.provider_fingerprint, timestamp, timestamp,
            ),
        )

    @staticmethod
    def _insert_project_context_receipt(
        connection: sqlite3.Connection, receipt: ProjectContextReceiptRecord
    ) -> None:
        project_row = connection.execute(
            "SELECT revision FROM projects WHERE identifier=?", (receipt.project_id,)
        ).fetchone()
        if project_row is None or receipt.project_revision > project_row[0]:
            raise ArchiveValidationError(
                "The Project context receipt has an invalid Project revision."
            )
        connection.execute(
            "INSERT INTO project_context_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                receipt.chat_id, receipt.assistant_sequence, receipt.project_id,
                receipt.project_revision, receipt.estimator_version,
                receipt.budget_tokens, receipt.stable_json, receipt.working_json,
                receipt.historical_json, receipt.omitted_json,
                receipt.rendered_context, receipt.rendered_digest,
                receipt.created_at,
            ),
        )

    @staticmethod
    def _set_active(connection: sqlite3.Connection, identifier: str | None) -> None:
        connection.execute(
            "UPDATE archive_state SET active_chat_id = ? WHERE singleton = 1",
            (identifier,),
        )

    def _identifier_exists(self, identifier: str) -> bool:
        try:
            self.get_chat(identifier)
        except ArchiveNotFoundError:
            return False
        return True

    def _project_identifier_exists(self, identifier: str) -> bool:
        try:
            self.get_project(identifier)
        except ArchiveNotFoundError:
            return False
        return True


_CHAT_SELECT = """
SELECT identifier, label, created_at, updated_at, last_opened_at, revision,
       first_provider, first_model, latest_provider, latest_model,
       selected_provider, selected_model, entry_count, completed_turn_count,
       selected_context_policy, project_id
FROM chats
"""

_PROJECT_SELECT = """
SELECT identifier,title,status,objective,continuity_brief,revision,created_at,updated_at
FROM projects
"""


def validate_chat_identifier(identifier: object) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ArchiveValidationError(
            "Chat identifiers must use chat- followed by 32 lowercase hexadecimal characters."
        )
    return identifier


def validate_project_identifier(identifier: object) -> str:
    if not isinstance(identifier, str) or not _PROJECT_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ArchiveValidationError(
            "Project identifiers must use project- followed by 32 lowercase hexadecimal characters."
        )
    return identifier


def validate_project_decision_identifier(identifier: object) -> str:
    return _validate_project_child_identifier(
        identifier, _PROJECT_DECISION_IDENTIFIER_PATTERN, "decision"
    )


def validate_project_question_identifier(identifier: object) -> str:
    return _validate_project_child_identifier(
        identifier, _PROJECT_QUESTION_IDENTIFIER_PATTERN, "question"
    )


def validate_project_plan_identifier(identifier: object) -> str:
    return _validate_project_child_identifier(
        identifier, _PROJECT_PLAN_ITEM_IDENTIFIER_PATTERN, "plan item"
    )


def validate_project_link_identifier(identifier: object) -> str:
    return _validate_project_child_identifier(
        identifier, _PROJECT_LINK_IDENTIFIER_PATTERN, "link"
    )


def validate_project_link_target(
    target_type: object, target_id: object
) -> tuple[str, str]:
    """Validate one approved source-owned stable identifier without reading it."""

    return _validate_project_link_target(target_type, target_id)


def _validate_application_event(
    event_id: object,
    event_type: object,
    *,
    allow_legacy: bool = False,
) -> tuple[str | None, str | None]:
    if event_id is None and event_type is None:
        return None, None
    if (
        not isinstance(event_id, str)
        or not re.fullmatch(r"event-[0-9a-f]{32}", event_id)
        or len(event_id) > MAX_APPLICATION_EVENT_ID_LENGTH
    ):
        raise ArchiveValidationError("Application event identifiers are invalid.")
    accepted_types = (
        APPLICATION_EVENT_TYPES | LEGACY_APPLICATION_EVENT_TYPES
        if allow_legacy else APPLICATION_EVENT_TYPES
    )
    if (
        not isinstance(event_type, str)
        or event_type not in accepted_types
        or len(event_type) > MAX_APPLICATION_EVENT_TYPE_LENGTH
    ):
        raise ArchiveValidationError("Application event types are invalid.")
    return event_id, event_type


def validate_archive_entries(
    entries: Sequence[ArchiveEntry],
    *,
    _allow_legacy_application_events: bool = False,
) -> tuple[ArchiveEntry, ...]:
    if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
        raise ArchiveValidationError("The authoritative transcript must be a sequence.")
    validated: list[ArchiveEntry] = []
    for item in entries:
        if not isinstance(item, ArchiveEntry):
            raise ArchiveValidationError("Every transcript entry must be an ArchiveEntry.")
        if item.role not in ARCHIVE_ROLES:
            raise ArchiveValidationError("The transcript contains an unsupported role.")
        if (
            not isinstance(item.text, str)
            or not item.text
            or "\x00" in item.text
            or len(item.text) > MAX_ARCHIVE_ENTRY_TEXT_LENGTH
        ):
            raise ArchiveValidationError("Transcript text has an invalid size.")
        sources = _validate_sources(item.sources)
        if sources and item.role != "assistant":
            raise ArchiveValidationError("Only assistant entries may contain source references.")
        provider = _optional_metadata(item.provider, "provider")
        model = _optional_metadata(item.model, "model")
        if (provider is None) != (model is None):
            raise ArchiveValidationError(
                "Assistant provider and model metadata must be supplied together."
            )
        if provider is not None and item.role != "assistant":
            raise ArchiveValidationError(
                "Only assistant entries may contain provider and model metadata."
            )
        created_at = (
            validate_archive_timestamp(item.created_at)
            if item.created_at is not None else None
        )
        web_search = _validate_web_search(item.web_search)
        if web_search is not None and item.role != "assistant":
            raise ArchiveValidationError("Only assistant entries may contain web-search attribution.")
        event_id, event_type = _validate_application_event(
            item.application_event_id,
            item.application_event_type,
            allow_legacy=_allow_legacy_application_events,
        )
        context = _validate_archive_context(item.context)
        if context is not None and (
            item.role != "assistant" or provider is None or event_id is not None
        ):
            raise ArchiveValidationError(
                "Context telemetry is allowed only on provider-generated assistant entries."
            )
        if event_id is not None and (
            item.role != "assistant" or sources or provider is not None
            or model is not None or web_search is not None
        ):
            raise ArchiveValidationError(
                "Application events must be unattributed assistant entries."
            )
        validated.append(
            ArchiveEntry(
                item.role, item.text, sources, provider, model, created_at,
                web_search, event_id, event_type, context,
            )
        )
    return tuple(validated)


def count_completed_turns(entries: Sequence[ArchiveEntry]) -> int:
    """Count completed provider/model exchanges only."""

    return len(completed_model_attributions(entries))


def completed_model_attributions(
    entries: Sequence[ArchiveEntry],
) -> tuple[tuple[str, str], ...]:
    """Return actual provider/model attribution for completed model turns."""

    pending_user = False
    completed: list[tuple[str, str]] = []
    for entry in entries:
        if entry.role == "user":
            pending_user = True
        elif entry.role == "assistant":
            if entry.application_event_id is not None:
                continue
            if entry.provider is None or entry.model is None:
                # Provider-free application presentation neither completes nor
                # consumes a pending model-facing user turn.
                continue
            if pending_user:
                completed.append((entry.provider, entry.model))
                pending_user = False
        elif entry.role == "error":
            pending_user = False
    return tuple(completed)


def _legacy_completed_turn_count(entries: Sequence[ArchiveEntry]) -> int:
    """Bound preserved schema-2 counts without reclassifying old entries."""

    pending_user = False
    completed = 0
    for entry in entries:
        if entry.role == "user":
            pending_user = True
        elif entry.role == "assistant":
            if entry.application_event_id is not None:
                continue
            if pending_user:
                completed += 1
                pending_user = False
        elif entry.role == "error":
            pending_user = False
    return completed


def validate_scheduled_work_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate the complete provider-free form allowed at confirmation."""

    validated = validate_archive_entries(entries)
    if len(validated) != 2:
        raise ArchiveValidationError(
            "A Scheduled Work origin requires one request and one proposal event."
        )
    validate_scheduled_work_origin_suffix(validated)
    if completed_model_attributions(validated):
        raise ArchiveValidationError(
            "A provider-free Scheduled Work origin cannot contain a model turn."
        )
    return validated


def validate_scheduled_work_origin_suffix(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ArchiveEntry]:
    """Validate the exact suffix established by a confirmed proposal."""

    validated = validate_archive_entries(entries)
    if len(validated) != 2:
        raise ArchiveValidationError(
            "Scheduled Work origin reconciliation requires one request and one proposal."
        )
    request, proposal = validated
    if (
        request.role != "user"
        or request.sources
        or request.provider is not None
        or request.model is not None
        or request.web_search is not None
        or request.application_event_id is not None
        or proposal.role != "assistant"
        or proposal.application_event_type != "scheduled_work_proposal"
        or proposal.application_event_id is None
    ):
        raise ArchiveValidationError(
            "The Scheduled Work origin contains unsupported continuity entries."
        )
    return request, proposal


def validate_project_proposal_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate a direct or conversationally clarified Project proposal."""

    validated = validate_archive_entries(entries)
    if len(validated) not in {2, 4}:
        raise ArchiveValidationError(
            "A Project proposal origin requires a direct or clarified proposal."
        )
    if len(validated) == 4:
        request, clarification, decision, proposal = validated
        if (
            request.role != "user"
            or request.application_event_id is not None
            or clarification.role != "assistant"
            or clarification.application_event_type != "project_intent_clarification"
            or clarification.application_event_id is None
            or decision.role != "user"
            or decision.application_event_id is not None
        ):
            raise ArchiveValidationError(
                "The clarified Project proposal origin is invalid."
            )
        request = decision
    else:
        request, proposal = validated
    if (
        request.role != "user"
        or request.sources
        or request.provider is not None
        or request.model is not None
        or request.web_search is not None
        or request.application_event_id is not None
        or proposal.role != "assistant"
        or proposal.application_event_type != "project_proposal"
        or proposal.application_event_id is None
        or completed_model_attributions(validated)
    ):
        raise ArchiveValidationError(
            "The Project proposal origin contains unsupported continuity entries."
        )
    return validated


def validate_coding_work_proposal_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one provider-free conversational Coding Work proposal."""

    validated = validate_archive_entries(entries)
    validate_coding_work_origin_suffix(validated)
    if completed_model_attributions(validated):
        raise ArchiveValidationError(
            "A provider-free Coding Work origin cannot contain a model turn."
        )
    return validated


TERMINAL_PROPOSAL_ORIGIN_TEXT = "Terminal proposal received for policy review."


def validate_terminal_proposal_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Only an application-owned receipt may establish a first-turn PTY chat."""

    validated = validate_archive_entries(entries)
    if len(validated) != 2:
        raise ArchiveValidationError("A terminal origin requires one user request and one internal receipt.")
    request, receipt = validated
    if (
        request.role != "user" or request.sources or request.provider is not None
        or request.model is not None or request.web_search is not None
        or request.application_event_id is not None
        or receipt.role != "assistant"
        or receipt.application_event_type != "terminal_proposal_origin"
        or receipt.application_event_id is None
        or receipt.text != TERMINAL_PROPOSAL_ORIGIN_TEXT
        or completed_model_attributions(validated)
    ):
        raise ArchiveValidationError("The first-turn terminal origin is invalid.")
    return validated


def validate_planning_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one provider-free calendar-information or Planning exchange."""

    validated = validate_archive_entries(entries)
    if len(validated) != 2:
        raise ArchiveValidationError(
            "A Planning origin requires one request and one application response."
        )
    request, response = validated
    if (
        request.role != "user"
        or request.sources
        or request.provider is not None
        or request.model is not None
        or request.web_search is not None
        or request.application_event_id is not None
        or response.role != "assistant"
        or response.application_event_type not in {
            "calendar_information", "planning_read", "planning_proposal",
        }
        or response.application_event_id is None
        or completed_model_attributions(validated)
    ):
        raise ArchiveValidationError(
            "The Planning origin contains unsupported continuity entries."
        )
    return validated


def validate_planning_origin_suffix(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one later Planning exchange or confirmed result event."""

    validated = validate_archive_entries(entries)
    if validated and all(
        item.role == "assistant"
        and item.application_event_type == "planning_result"
        and item.application_event_id is not None
        for item in validated
    ):
        return validated
    if len(validated) == 2:
        return validate_planning_origin_entries(validated)
    raise ArchiveValidationError("The Planning event sequence is incomplete.")


def _validate_legacy_research_origin_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one retired provider-free Deep Research admission."""

    validated = validate_archive_entries(
        entries, _allow_legacy_application_events=True
    )
    if len(validated) != 2:
        raise ArchiveValidationError(
            "A legacy Deep Research origin requires one request and one response."
        )
    request, response = validated
    if (
        request.role != "user"
        or request.sources
        or request.provider is not None
        or request.model is not None
        or request.web_search is not None
        or request.application_event_id is not None
        or response.role != "assistant"
        or response.application_event_type not in {
            "deep_research_started", "deep_research_clarification",
            "deep_research_control",
        }
        or response.application_event_id is None
        or completed_model_attributions(validated)
    ):
        raise ArchiveValidationError(
            "The legacy Deep Research origin contains unsupported continuity entries."
        )
    return validated


def _validate_legacy_research_event_sequence(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate retired research controls and terminal delivery events."""

    validated = validate_archive_entries(
        entries, _allow_legacy_application_events=True
    )
    index = 0
    while index < len(validated):
        entry = validated[index]
        if (
            entry.role == "assistant"
            and entry.application_event_type == "deep_research_result"
            and entry.application_event_id is not None
        ):
            index += 1
            continue
        if index + 1 >= len(validated):
            raise ArchiveValidationError(
                "The legacy Deep Research event sequence is incomplete."
            )
        _validate_legacy_research_origin_entries(validated[index:index + 2])
        index += 2
    return validated


def validate_planning_event_sequence(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate later calendar/Planning pairs and confirmed Planning results."""

    validated = validate_archive_entries(entries)
    index = 0
    while index < len(validated):
        item = validated[index]
        if (
            item.role == "assistant"
            and item.application_event_type == "planning_result"
            and item.application_event_id is not None
        ):
            index += 1
            continue
        if index + 2 <= len(validated):
            validate_planning_origin_entries(validated[index:index + 2])
            index += 2
            continue
        raise ArchiveValidationError("The Planning event sequence is incomplete.")
    return validated


def validate_coding_work_origin_suffix(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one Coding Work proposal pair or one application result event."""

    validated = validate_archive_entries(entries)
    result_only = bool(validated) and all(
        item.role == "assistant"
        and item.application_event_type in {"coding_work_result", "research_result"}
        and item.application_event_id is not None
        for item in validated
    )
    proposal = False
    if len(validated) == 2:
        request, response = validated
        proposal = (
            request.role == "user"
            and not request.sources
            and request.provider is None
            and request.model is None
            and request.web_search is None
            and request.application_event_id is None
            and response.role == "assistant"
            and response.application_event_type in {"coding_work_proposal", "research_proposal"}
            and response.application_event_id is not None
        )
    if not result_only and not proposal:
        raise ArchiveValidationError(
            "Coding Work origin reconciliation requires one proposal or result event."
        )
    return validated


def validate_coding_work_event_sequence(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate later Coding Work proposal/result units in one zero-turn chat."""

    validated = validate_archive_entries(entries)
    index = 0
    while index < len(validated):
        item = validated[index]
        if (
            item.role == "assistant"
            and item.application_event_type in {
                "coding_work_result", "research_result", "reminder_due"
            }
            and item.application_event_id is not None
        ):
            index += 1
            continue
        if index + 2 <= len(validated):
            validate_coding_work_proposal_origin_entries(validated[index:index + 2])
            index += 2
            continue
        raise ArchiveValidationError("The Coding Work event sequence is incomplete.")
    return validated


def validate_project_result_suffix(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate one provider-free Project proposal or result suffix."""

    validated = validate_archive_entries(entries)
    result_only = bool(validated) and all(
        item.role == "assistant"
        and item.application_event_type == "project_result"
        and item.application_event_id is not None
        for item in validated
    )
    proposal = False
    if len(validated) in {2, 4}:
        try:
            validate_project_proposal_origin_entries(validated)
            proposal = True
        except ArchiveValidationError:
            pass
    if not result_only and not proposal:
        raise ArchiveValidationError(
            "Project origin reconciliation requires one proposal or verified result event."
        )
    return validated


def validate_project_event_sequence(
    entries: Sequence[ArchiveEntry],
) -> tuple[ArchiveEntry, ...]:
    """Validate all later proposal/result units in a zero-turn Project chat."""

    validated = validate_archive_entries(entries)
    index = 0
    while index < len(validated):
        item = validated[index]
        if (
            item.role == "assistant"
            and item.application_event_type == "project_result"
            and item.application_event_id is not None
        ):
            index += 1
            continue
        if (
            index + 4 <= len(validated)
            and validated[index + 1].application_event_type
            == "project_intent_clarification"
        ):
            validate_project_proposal_origin_entries(validated[index:index + 4])
            index += 4
            continue
        if index + 2 <= len(validated):
            validate_project_proposal_origin_entries(validated[index:index + 2])
            index += 2
            continue
        raise ArchiveValidationError("The Project event sequence is incomplete.")
    return validated


_SYNTHETIC_APPLICATION_EVENT_ID = "event-" + "0" * 32


def _zero_turn_origin(entries: Sequence[ArchiveEntry]) -> tuple[str, int]:
    """Classify one zero-turn chat's special origin form.

    Returns the origin kind and the number of entries forming its origin
    prefix. Raises ArchiveValidationError when no supported origin matches.
    """

    try:
        validate_scheduled_work_origin_entries(entries[:2])
        return "scheduled_work", 2
    except ArchiveValidationError:
        pass
    project_candidate = entries[:4] if (
        len(entries) >= 4
        and entries[1].application_event_type == "project_intent_clarification"
    ) else entries[:2]
    try:
        validate_project_proposal_origin_entries(project_candidate)
        return "project", len(project_candidate)
    except ArchiveValidationError:
        pass
    try:
        validate_coding_work_proposal_origin_entries(entries[:2])
        return "coding_work", 2
    except ArchiveValidationError:
        pass
    try:
        validate_planning_origin_entries(entries[:2])
        return "planning", 2
    except ArchiveValidationError:
        pass
    try:
        validate_terminal_proposal_origin_entries(entries[:2])
        return "terminal", 2
    except ArchiveValidationError:
        pass
    try:
        _validate_legacy_research_origin_entries(entries[:2])
        return "legacy_research", 2
    except ArchiveValidationError as exc:
        raise ArchiveValidationError(
            "The conversation archive contains an unsupported zero-turn chat."
        ) from exc


def validate_zero_turn_chat_entries(
    entries: Sequence[ArchiveEntry],
) -> tuple[str, int]:
    """Validate one complete zero-turn chat against its special origin form."""

    kind, length = _zero_turn_origin(entries)
    if kind == "scheduled_work":
        if any(entry.application_event_id is None for entry in entries[2:]):
            raise ArchiveValidationError(
                "The conversation archive contains an unsupported zero-turn chat."
            )
        return kind, length
    suffix = entries[length:]
    if kind == "terminal":
        if suffix:
            raise ArchiveValidationError("An unresolved terminal origin cannot add application events.")
        return kind, length
    if not suffix:
        return kind, length
    try:
        if kind == "project":
            validate_project_event_sequence(suffix)
        elif kind == "coding_work":
            validate_coding_work_event_sequence(suffix)
        elif kind == "planning":
            validate_planning_event_sequence(suffix)
        else:
            _validate_legacy_research_event_sequence(suffix)
    except ArchiveValidationError as exc:
        messages = {
            "project": (
                "The conversation archive contains an unsupported Project origin."
            ),
            "coding_work": (
                "The conversation archive contains an unsupported Coding Work origin."
            ),
            "planning": (
                "The conversation archive contains an unsupported Planning origin."
            ),
        }
        raise ArchiveValidationError(
            messages.get(
                kind,
                "The conversation archive contains an unsupported legacy Deep Research origin.",
            )
        ) from exc
    return kind, length


def chat_accepts_application_event(
    completed_turn_count: int,
    entries: Sequence[ArchiveEntry],
    event_type: str,
) -> bool:
    """Report whether one application event may join this chat's origin form."""

    if completed_turn_count > 0:
        return True
    try:
        kind, length = _zero_turn_origin(entries)
    except ArchiveValidationError:
        return False
    if kind == "terminal":
        return False
    if kind == "scheduled_work":
        return all(entry.application_event_id is not None for entry in entries[2:])
    candidate = (*entries[length:], ArchiveEntry(
        "assistant",
        "application event",
        (),
        None,
        None,
        None,
        None,
        _SYNTHETIC_APPLICATION_EVENT_ID,
        event_type,  # type: ignore[arg-type]
    ))
    try:
        if kind == "project":
            validate_project_event_sequence(candidate)
        elif kind == "coding_work":
            validate_coding_work_event_sequence(candidate)
        elif kind == "planning":
            validate_planning_event_sequence(candidate)
        else:
            _validate_legacy_research_event_sequence(candidate)
    except ArchiveValidationError:
        return False
    return True


def derive_chat_label(
    entries: Sequence[ArchiveEntry], *, created_at: str | datetime
) -> str:
    """Derive a compact deterministic subject without changing transcript text."""

    validated = validate_archive_entries(entries)
    timestamp = (
        _format_timestamp(created_at)
        if isinstance(created_at, datetime)
        else validate_archive_timestamp(created_at)
    )
    saw_casual_opening = False
    for entry in validated:
        if entry.role != "user":
            continue
        for line in entry.text.splitlines():
            rendered = _render_label_line(line)
            if not rendered:
                continue
            without_greeting = _GREETING_PREFIX_PATTERN.sub("", rendered, count=1).strip()
            if without_greeting != rendered:
                saw_casual_opening = True
            if without_greeting.casefold() in {
                "i have a question", "i have another question",
                "i wanted to ask", "can you help me",
            }:
                saw_casual_opening = True
                continue
            candidate = _INTENT_PREFIX_PATTERN.sub("", without_greeting, count=1).strip()
            if not candidate or candidate.casefold() in {
                "a question", "another question", "question"
            }:
                saw_casual_opening = True
                continue
            return _subject_label(candidate)
    if saw_casual_opening:
        return "Just checking in"
    return f"Chat {timestamp}"


def is_provisional_chat_label(value: object) -> bool:
    """Return whether a title is reserved for bounded automatic refinement."""

    return isinstance(value, str) and value.strip() in _PROVISIONAL_CHAT_LABELS


def _subject_label(value: str) -> str:
    """Render one truthful deterministic title from user-supplied subject text."""

    lowered = value.casefold()
    if "tts" in lowered and any(word in lowered for word in ("compare", "comparison")):
        return "TTS engine comparison"
    if any(word in lowered for word in ("web ui", "frontend", "user interface")) and (
        "redesign" in lowered or "design" in lowered
    ):
        return "Tori UI redesign"
    if "memory" in lowered and "architecture" in lowered:
        return "Memory architecture discussion"
    if "scheduled backup" in lowered and any(
        word in lowered for word in ("create", "schedule", "new")
    ):
        return "Create a scheduled backup"
    if "schedule" in lowered and any(
        word in lowered for word in ("create", "new")
    ):
        return "Create a new schedule"

    compact = value.strip().rstrip(".!?;:")
    compact = re.sub(r"\s+", " ", compact)
    if not compact:
        return "Question"
    if compact.casefold().startswith("compare "):
        compact = f"Comparison: {compact[8:]}"
    elif compact.casefold().startswith("work on "):
        compact = compact[8:]
    compact = compact[0].upper() + compact[1:]
    if len(compact) <= MAX_CHAT_LABEL_LENGTH:
        return compact
    shortened = compact[:MAX_CHAT_LABEL_LENGTH + 1].rsplit(" ", 1)[0]
    return (shortened or compact[:MAX_CHAT_LABEL_LENGTH]).rstrip(" .,:;-")


def validate_archive_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise ArchiveValidationError("Archive timestamps must be UTC second timestamps.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ArchiveValidationError("Archive timestamp is invalid.") from exc
    if _format_timestamp(parsed) != value:
        raise ArchiveValidationError("Archive timestamp is invalid.")
    return value


def _validate_sources(values: object) -> tuple[ArchiveSource, ...]:
    if not isinstance(values, tuple):
        raise ArchiveValidationError("Source references must be an immutable tuple.")
    result: list[ArchiveSource] = []
    for source in values:
        if not isinstance(source, ArchiveSource):
            raise ArchiveValidationError("A source reference has an invalid shape.")
        filename = source.filename
        represented = _decode_ascii_escaped_display(filename)
        is_display = represented is not None
        if represented is None:
            represented = filename
        if _unsafe_source_filename(filename, allow_display_escapes=True) or (
            _unsafe_source_filename(
                represented,
                allow_display_escapes=False,
                allow_controls=is_display,
            )
        ):
            raise ArchiveValidationError("A source filename is unsafe.")
        if (
            isinstance(source.line_start, bool)
            or not isinstance(source.line_start, int)
            or isinstance(source.line_end, bool)
            or not isinstance(source.line_end, int)
            or source.line_start < 1
            or source.line_end < source.line_start
        ):
            raise ArchiveValidationError("A source line range is invalid.")
        result.append(ArchiveSource(filename, source.line_start, source.line_end))
    return tuple(result)


def _validate_web_search(value: object) -> ArchiveWebSearch | None:
    if value is None:
        return None
    if not isinstance(value, ArchiveWebSearch):
        raise ArchiveValidationError("Web-search attribution has an invalid shape.")
    query = _safe_web_text(value.query, MAX_WEB_QUERY_LENGTH, "query")
    if value.status != "completed":
        raise ArchiveValidationError("Web-search attribution has an invalid status.")
    if not isinstance(value.sources, tuple):
        raise ArchiveValidationError("Web-search sources must be an immutable tuple.")
    if len(value.sources) > 10:
        raise ArchiveValidationError("Web-search attribution contains too many sources.")
    sources: list[ArchiveWebSource] = []
    for source in value.sources:
        if not isinstance(source, ArchiveWebSource):
            raise ArchiveValidationError("A web-search source has an invalid shape.")
        title = _safe_web_text(source.title, MAX_WEB_TITLE_LENGTH, "title")
        url = _safe_web_text(source.url, MAX_WEB_URL_LENGTH, "URL")
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise ArchiveValidationError("A web-search source URL is unsafe.") from exc
        if (
            parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or "\\" in url
            or any(character.isspace() for character in url)
        ):
            raise ArchiveValidationError("A web-search source URL is unsafe.")
        sources.append(ArchiveWebSource(title, url))
    return ArchiveWebSearch(query, "completed", tuple(sources))


def _safe_web_text(value: object, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    ):
        raise ArchiveValidationError(f"A web-search {label} is unsafe.")
    return value


def _sources_json(
    sources: tuple[ArchiveSource, ...], web_search: ArchiveWebSearch | None
) -> str | None:
    if not sources and web_search is None:
        return None
    local_sources = [
            {"filename": item.filename, "line_start": item.line_start, "line_end": item.line_end}
            for item in sources
        ]
    document: object = local_sources
    if web_search is not None:
        document = {
            "sources": local_sources,
            "web_search": {
                "query": web_search.query,
                "status": web_search.status,
                "sources": [
                    {"title": source.title, "url": source.url}
                    for source in web_search.sources
                ],
            },
        }
    return json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _unsafe_source_filename(
    value: object,
    *,
    allow_display_escapes: bool,
    allow_controls: bool = False,
) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_SOURCE_FILENAME_LENGTH:
        return True
    if "\x00" in value or value in {".", ".."}:
        return True
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        return True
    if "/" in value or ("\\" in value and not allow_display_escapes):
        return True
    return not allow_controls and any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for character in value
    )


def _decode_ascii_escaped_display(value: object) -> str | None:
    """Decode only Tori's canonical fixed-width safe display escapes."""

    if (
        not isinstance(value, str)
        or len(value) < 2
        or value[0] not in {"'", '"'}
        or value[-1] != value[0]
    ):
        return None
    quote = value[0]
    result: list[str] = []
    index = 1
    end = len(value) - 1
    while index < end:
        character = value[index]
        if character != "\\":
            if character == quote:
                return None
            result.append(character)
            index += 1
            continue
        if index + 1 >= end:
            return None
        escape = value[index + 1]
        if escape in {"\\", quote}:
            result.append(escape)
            index += 2
            continue
        widths = {"x": 2, "u": 4, "U": 8}
        width = widths.get(escape)
        if width is None or index + 2 + width > end:
            return None
        digits = value[index + 2:index + 2 + width]
        if not re.fullmatch(r"[0-9a-fA-F]+", digits):
            return None
        codepoint = int(digits, 16)
        if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            return None
        result.append(chr(codepoint))
        index += 2 + width
    decoded = "".join(result)
    return decoded if ascii(decoded) == value else None


def _sources_from_json(
    value: object,
) -> tuple[tuple[ArchiveSource, ...], ArchiveWebSearch | None]:
    if value is None:
        return (), None
    if not isinstance(value, str):
        raise ArchiveCorruptError("The conversation archive contains an invalid record.")
    try:
        document = json.loads(value)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ArchiveCorruptError("The conversation archive contains an invalid record.") from exc
    web_search: ArchiveWebSearch | None = None
    if isinstance(document, Mapping):
        if set(document) != {"sources", "web_search"}:
            raise ArchiveCorruptError("The conversation archive contains an invalid record.")
        local_document = document["sources"]
        search_document = document["web_search"]
        if not isinstance(search_document, Mapping) or set(search_document) != {"query", "status", "sources"} or not isinstance(search_document["sources"], list):
            raise ArchiveCorruptError("The conversation archive contains an invalid record.")
        web_sources = []
        for item in search_document["sources"]:
            if not isinstance(item, Mapping) or set(item) != {"title", "url"}:
                raise ArchiveCorruptError("The conversation archive contains an invalid record.")
            web_sources.append(ArchiveWebSource(item["title"], item["url"]))
        try:
            web_search = _validate_web_search(ArchiveWebSearch(search_document["query"], search_document["status"], tuple(web_sources)))
        except ArchiveValidationError as exc:
            raise ArchiveCorruptError("The conversation archive contains an invalid record.") from exc
        document = local_document
    if not isinstance(document, list):
        raise ArchiveCorruptError("The conversation archive contains an invalid record.")
    sources: list[ArchiveSource] = []
    for item in document:
        if not isinstance(item, Mapping) or set(item) != {"filename", "line_start", "line_end"}:
            raise ArchiveCorruptError("The conversation archive contains an invalid record.")
        sources.append(ArchiveSource(item["filename"], item["line_start"], item["line_end"]))
    try:
        return _validate_sources(tuple(sources)), web_search
    except ArchiveValidationError as exc:
        raise ArchiveCorruptError("The conversation archive contains an invalid record.") from exc


def _validate_context_policy(value: object) -> str:
    if value == "auto":
        return "auto"
    if isinstance(value, str) and value.startswith("fixed:"):
        number = value.removeprefix("fixed:")
        if number.isdigit() and 4096 <= int(number) <= 1_048_576:
            return value
    raise ArchiveValidationError("The selected context policy is invalid.")


def _validate_archive_context(value: object) -> ArchiveContext | None:
    if value is None:
        return None
    if not isinstance(value, ArchiveContext):
        raise ArchiveValidationError("Context telemetry is invalid.")
    _validate_context_policy(value.requested_policy)
    if (
        not isinstance(value.estimator_version, str)
        or not value.estimator_version
        or len(value.estimator_version) > 64
        or any(ord(character) < 33 or ord(character) > 126 for character in value.estimator_version)
    ):
        raise ArchiveValidationError("Context telemetry estimator version is invalid.")
    required = (
        value.effective_budget, value.estimated_input_tokens,
        value.included_history_messages, value.omitted_history_messages,
    )
    if any(isinstance(number, bool) or not isinstance(number, int) or number < 0 for number in required) or not 4096 <= value.effective_budget <= 1_048_576:
        raise ArchiveValidationError("Context telemetry counts are invalid.")
    actual = (
        value.actual_prompt_tokens, value.actual_completion_tokens,
        value.actual_total_tokens,
    )
    if any(number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 0) for number in actual):
        raise ArchiveValidationError("Context telemetry actual usage is invalid.")
    if all(number is not None for number in actual) and value.actual_total_tokens != value.actual_prompt_tokens + value.actual_completion_tokens:  # type: ignore[operator]
        raise ArchiveValidationError("Context telemetry actual usage is inconsistent.")
    return value


def _context_json(value: ArchiveContext | None) -> str | None:
    if value is None:
        return None
    context = _validate_archive_context(value)
    assert context is not None
    document = {
        "requested_policy": context.requested_policy,
        "effective_budget": context.effective_budget,
        "estimator_version": context.estimator_version,
        "estimated_input_tokens": context.estimated_input_tokens,
        "included_history_messages": context.included_history_messages,
        "omitted_history_messages": context.omitted_history_messages,
        "actual_prompt_tokens": context.actual_prompt_tokens,
        "actual_completion_tokens": context.actual_completion_tokens,
        "actual_total_tokens": context.actual_total_tokens,
    }
    encoded = json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded) > MAX_CONTEXT_JSON_LENGTH:
        raise ArchiveValidationError("Context telemetry is oversized.")
    return encoded


def _context_from_json(value: object) -> ArchiveContext | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_CONTEXT_JSON_LENGTH:
        raise ArchiveCorruptError("The conversation archive contains invalid context telemetry.")
    try:
        document = json.loads(value)
        expected = {
            "requested_policy", "effective_budget", "estimator_version",
            "estimated_input_tokens", "included_history_messages",
            "omitted_history_messages", "actual_prompt_tokens",
            "actual_completion_tokens", "actual_total_tokens",
        }
        if not isinstance(document, dict) or set(document) != expected:
            raise ValueError("invalid fields")
        return _validate_archive_context(ArchiveContext(**document))
    except (TypeError, ValueError, json.JSONDecodeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError("The conversation archive contains invalid context telemetry.") from exc


def _metadata_from_row(row: sqlite3.Row | Sequence[object]) -> ChatMetadata:
    try:
        item = ChatMetadata(*row)
        validate_chat_identifier(item.identifier)
        _validate_label(item.label)
        validate_archive_timestamp(item.created_at)
        validate_archive_timestamp(item.updated_at)
        if item.last_opened_at is not None:
            validate_archive_timestamp(item.last_opened_at)
        _validate_revision(item.revision)
        _required_metadata(item.selected_provider, "provider")
        _required_metadata(item.selected_model, "model")
        _validate_context_policy(item.selected_context_policy)
        if item.project_id is not None:
            validate_project_identifier(item.project_id)
        summary = (
            item.first_provider,
            item.first_model,
            item.latest_provider,
            item.latest_model,
        )
        if item.completed_turn_count == 0:
            if any(value is not None for value in summary):
                raise ArchiveValidationError("invalid zero-turn attribution")
        else:
            _required_metadata(item.first_provider, "provider")
            _required_metadata(item.first_model, "model")
            _required_metadata(item.latest_provider, "provider")
            _required_metadata(item.latest_model, "model")
        if (
            isinstance(item.entry_count, bool) or not isinstance(item.entry_count, int)
            or item.entry_count < 2 or isinstance(item.completed_turn_count, bool)
            or not isinstance(item.completed_turn_count, int) or item.completed_turn_count < 0
            or item.updated_at < item.created_at
            or (
                item.last_opened_at is not None
                and not (item.created_at <= item.last_opened_at <= item.updated_at)
            )
        ):
            raise ArchiveValidationError("invalid counts")
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError("The conversation archive contains an invalid record.") from exc
    return item


def _project_from_row(row: sqlite3.Row | Sequence[object]) -> ProjectRecord:
    try:
        item = ProjectRecord(*row)
        validate_project_identifier(item.identifier)
        _validate_project_text(item.title, "Project title", MAX_PROJECT_TITLE_LENGTH)
        _validate_project_status(item.status)
        _validate_project_text(item.objective, "Project objective", MAX_PROJECT_OBJECTIVE_LENGTH)
        _validate_legacy_project_brief(item.continuity_brief)
        _validate_revision(item.revision)
        validate_archive_timestamp(item.created_at)
        validate_archive_timestamp(item.updated_at)
        if item.updated_at < item.created_at:
            raise ArchiveValidationError("invalid Project timestamps")
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project record."
        ) from exc
    return item


def _project_state_from_row(
    row: sqlite3.Row | Sequence[object],
) -> ProjectStateRecord:
    try:
        item = ProjectStateRecord(*row)
        validate_project_identifier(item.project_id)
        _validate_optional_project_text(item.phase, "Project phase", MAX_PROJECT_PHASE_LENGTH)
        _validate_optional_project_text(
            item.current_focus, "Project current focus", MAX_PROJECT_FOCUS_LENGTH
        )
        _validate_optional_project_text(
            item.checkpoint, "Project checkpoint", MAX_PROJECT_CHECKPOINT_LENGTH
        )
        if item.phase is None and item.current_focus is None and item.checkpoint is None:
            raise ArchiveValidationError("Project state must contain at least one value.")
        _validate_project_row_revision_and_timestamps(
            item.revision, item.created_at, item.updated_at
        )
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project state record."
        ) from exc
    return item


def _project_decision_from_row(
    row: sqlite3.Row | Sequence[object],
) -> ProjectDecisionRecord:
    try:
        item = ProjectDecisionRecord(*row)
        _validate_project_child_identifier(
            item.identifier, _PROJECT_DECISION_IDENTIFIER_PATTERN, "decision"
        )
        validate_project_identifier(item.project_id)
        _validate_project_text(item.text, "Project decision", MAX_PROJECT_DECISION_LENGTH)
        if item.importance not in {"normal", "important"}:
            raise ArchiveValidationError("Project decision importance is invalid.")
        if item.state not in {"active", "superseded"}:
            raise ArchiveValidationError("Project decision state is invalid.")
        if item.supersedes_decision_id is not None:
            _validate_project_child_identifier(
                item.supersedes_decision_id,
                _PROJECT_DECISION_IDENTIFIER_PATTERN,
                "decision",
            )
            if item.supersedes_decision_id == item.identifier:
                raise ArchiveValidationError("A Project decision cannot supersede itself.")
        _validate_project_row_revision_and_timestamps(
            item.revision, item.created_at, item.updated_at
        )
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project decision record."
        ) from exc
    return item


def _project_question_from_row(
    row: sqlite3.Row | Sequence[object],
) -> ProjectQuestionRecord:
    try:
        item = ProjectQuestionRecord(*row)
        _validate_project_child_identifier(
            item.identifier, _PROJECT_QUESTION_IDENTIFIER_PATTERN, "question"
        )
        validate_project_identifier(item.project_id)
        _validate_project_text(item.text, "Project question", MAX_PROJECT_QUESTION_LENGTH)
        if item.state not in {"open", "resolved", "deferred", "dismissed"}:
            raise ArchiveValidationError("Project question state is invalid.")
        _validate_optional_project_text(
            item.disposition_note,
            "Project question disposition",
            MAX_PROJECT_DISPOSITION_NOTE_LENGTH,
        )
        _validate_project_row_revision_and_timestamps(
            item.revision, item.created_at, item.updated_at
        )
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project question record."
        ) from exc
    return item


def _project_plan_item_from_row(
    row: sqlite3.Row | Sequence[object],
) -> ProjectPlanItemRecord:
    try:
        item = ProjectPlanItemRecord(*row)
        _validate_project_child_identifier(
            item.identifier, _PROJECT_PLAN_ITEM_IDENTIFIER_PATTERN, "plan item"
        )
        validate_project_identifier(item.project_id)
        _validate_project_text(item.text, "Project plan item", MAX_PROJECT_PLAN_ITEM_LENGTH)
        if item.state not in {"planned", "active", "blocked", "deferred", "completed"}:
            raise ArchiveValidationError("Project plan state is invalid.")
        _validate_optional_project_text(
            item.state_note, "Project plan note", MAX_PROJECT_PLAN_NOTE_LENGTH
        )
        if (
            isinstance(item.sort_order, bool)
            or not isinstance(item.sort_order, int)
            or item.sort_order < 0
        ):
            raise ArchiveValidationError("Project plan order is invalid.")
        _validate_project_row_revision_and_timestamps(
            item.revision, item.created_at, item.updated_at
        )
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project plan record."
        ) from exc
    return item


def _project_link_from_row(row: sqlite3.Row | Sequence[object]) -> ProjectLinkRecord:
    try:
        item = ProjectLinkRecord(*row)
        _validate_project_child_identifier(
            item.identifier, _PROJECT_LINK_IDENTIFIER_PATTERN, "link"
        )
        validate_project_identifier(item.project_id)
        if item.target_type not in {
            "night_owl_finding", "scheduled_work_definition", "knowledge_source",
        }:
            raise ArchiveValidationError("Project link type is invalid.")
        _validate_project_text(
            item.target_id, "Project link target", MAX_PROJECT_LINK_TARGET_ID_LENGTH
        )
        _validate_project_row_revision_and_timestamps(
            item.revision, item.created_at, item.updated_at
        )
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project link record."
        ) from exc
    return item


def _project_context_receipt_from_row(
    row: sqlite3.Row | Sequence[object],
) -> ProjectContextReceiptRecord:
    try:
        item = ProjectContextReceiptRecord(*row)
        validate_chat_identifier(item.chat_id)
        if (
            isinstance(item.assistant_sequence, bool)
            or not isinstance(item.assistant_sequence, int)
            or item.assistant_sequence < 0
        ):
            raise ArchiveValidationError("Project receipt sequence is invalid.")
        validate_project_identifier(item.project_id)
        _validate_revision(item.project_revision)
        _validate_project_text(item.estimator_version, "Estimator version", 64)
        if (
            isinstance(item.budget_tokens, bool)
            or not isinstance(item.budget_tokens, int)
            or item.budget_tokens < 1
        ):
            raise ArchiveValidationError("Project receipt budget is invalid.")
        for label, value in (
            ("Stable", item.stable_json),
            ("Working", item.working_json),
            ("Historical", item.historical_json),
            ("omitted", item.omitted_json),
        ):
            _validate_project_context_items_json(value, label)
        if (
            not isinstance(item.rendered_context, str)
            or not item.rendered_context
            or len(item.rendered_context) > MAX_PROJECT_CONTEXT_RENDERED_LENGTH
            or "\x00" in item.rendered_context
        ):
            raise ArchiveValidationError("Rendered Project context is invalid.")
        if (
            not isinstance(item.rendered_digest, str)
            or not _FINGERPRINT_PATTERN.fullmatch(item.rendered_digest)
            or hashlib.sha256(item.rendered_context.encode("utf-8")).hexdigest()
            != item.rendered_digest
        ):
            raise ArchiveValidationError("Rendered Project context digest is invalid.")
        if sum(len(value) for value in (
            item.stable_json, item.working_json, item.historical_json,
            item.omitted_json, item.rendered_context,
        )) > MAX_PROJECT_CONTEXT_RECEIPT_TOTAL_LENGTH:
            raise ArchiveValidationError("Project context receipt is too large.")
        validate_archive_timestamp(item.created_at)
    except (TypeError, ArchiveValidationError) as exc:
        raise ArchiveCorruptError(
            "The conversation archive contains an invalid Project context receipt."
        ) from exc
    return item


def _prepare_project_context_receipt(
    value: ProjectContextReceiptInput,
    *,
    chat_id: str,
    entries: Sequence[ArchiveEntry],
    chat_project_id: str | None,
    created_at: str,
    minimum_sequence: int = 0,
) -> ProjectContextReceiptRecord:
    if not isinstance(value, ProjectContextReceiptInput):
        raise ArchiveValidationError("The Project context receipt is invalid.")
    if value.project_id != chat_project_id:
        raise ArchiveValidationError(
            "Project context must match the conversation's Project association."
        )
    sequence = value.assistant_sequence
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < minimum_sequence
        or sequence >= len(entries)
    ):
        raise ArchiveValidationError(
            "The Project context receipt must bind one newly appended assistant turn."
        )
    source = entries[sequence]
    if not (
        source.role == "assistant"
        and source.provider is not None
        and source.model is not None
        and source.application_event_id is None
        and source.application_event_type is None
    ):
        raise ArchiveValidationError(
            "The Project context receipt must bind an ordinary assistant turn."
        )
    record = ProjectContextReceiptRecord(
        chat_id, sequence, value.project_id, value.project_revision,
        value.estimator_version, value.budget_tokens, value.stable_json,
        value.working_json, value.historical_json, value.omitted_json,
        value.rendered_context, value.rendered_digest, created_at,
    )
    try:
        return _project_context_receipt_from_row((
            record.chat_id, record.assistant_sequence, record.project_id,
            record.project_revision, record.estimator_version, record.budget_tokens,
            record.stable_json, record.working_json, record.historical_json,
            record.omitted_json, record.rendered_context, record.rendered_digest,
            record.created_at,
        ))
    except ArchiveCorruptError as exc:
        raise ArchiveValidationError(
            "The Project context receipt is invalid."
        ) from exc


def _validate_project_owned_rows(
    connection: sqlite3.Connection, projects: set[str]
) -> None:
    state_rows = connection.execute(
        "SELECT project_id,phase,current_focus,checkpoint,revision,created_at,updated_at "
        "FROM project_state ORDER BY project_id"
    ).fetchall()
    for row in state_rows:
        record = _project_state_from_row(row)
        if record.project_id not in projects:
            raise ArchiveCorruptError("Project state refers to a missing Project.")

    decision_rows = connection.execute(
        "SELECT identifier,project_id,text,importance,state,supersedes_decision_id,"
        "revision,created_at,updated_at FROM project_decisions ORDER BY identifier"
    ).fetchall()
    decisions = {
        record.identifier: record
        for record in (_project_decision_from_row(row) for row in decision_rows)
    }
    successor_predecessors = {
        record.supersedes_decision_id
        for record in decisions.values()
        if record.supersedes_decision_id is not None
    }
    for record in decisions.values():
        if record.project_id not in projects:
            raise ArchiveCorruptError("A decision refers to a missing Project.")
        if record.supersedes_decision_id is not None:
            predecessor = decisions.get(record.supersedes_decision_id)
            if predecessor is None or predecessor.project_id != record.project_id:
                raise ArchiveCorruptError("A decision has an invalid predecessor.")
        if (record.state == "superseded") != (record.identifier in successor_predecessors):
            raise ArchiveCorruptError("A decision chain has an invalid active state.")
        visited: set[str] = set()
        current: ProjectDecisionRecord | None = record
        while current is not None and current.supersedes_decision_id is not None:
            if current.identifier in visited:
                raise ArchiveCorruptError("A decision supersession cycle is invalid.")
            visited.add(current.identifier)
            current = decisions.get(current.supersedes_decision_id)

    for row in connection.execute(
        "SELECT identifier,project_id,text,state,disposition_note,revision,"
        "created_at,updated_at FROM project_questions ORDER BY identifier"
    ):
        if _project_question_from_row(row).project_id not in projects:
            raise ArchiveCorruptError("A question refers to a missing Project.")

    for row in connection.execute(
        "SELECT identifier,project_id,text,state,state_note,sort_order,revision,"
        "created_at,updated_at FROM project_plan_items ORDER BY identifier"
    ):
        if _project_plan_item_from_row(row).project_id not in projects:
            raise ArchiveCorruptError("A plan item refers to a missing Project.")

    for row in connection.execute(
        "SELECT identifier,project_id,target_type,target_id,revision,created_at,updated_at "
        "FROM project_links ORDER BY identifier"
    ):
        if _project_link_from_row(row).project_id not in projects:
            raise ArchiveCorruptError("A link refers to a missing Project.")

    project_revisions = dict(connection.execute("SELECT identifier,revision FROM projects"))
    receipt_rows = connection.execute(
        "SELECT chat_id,assistant_sequence,project_id,project_revision,"
        "estimator_version,budget_tokens,stable_json,working_json,historical_json,"
        "omitted_json,rendered_context,rendered_digest,created_at "
        "FROM project_context_receipts ORDER BY chat_id,assistant_sequence"
    ).fetchall()
    for row in receipt_rows:
        receipt = _project_context_receipt_from_row(row)
        if receipt.project_id not in projects or (
            receipt.project_revision > project_revisions[receipt.project_id]
        ):
            raise ArchiveCorruptError("A Project context receipt has an invalid Project revision.")
        source = connection.execute(
            "SELECT role,provider,model,application_event_id,application_event_type "
            "FROM transcript_entries WHERE chat_id=? AND sequence=?",
            (receipt.chat_id, receipt.assistant_sequence),
        ).fetchone()
        if source is None or not (
            source[0] == "assistant"
            and source[1] is not None
            and source[2] is not None
            and source[3] is None
            and source[4] is None
        ):
            raise ArchiveCorruptError(
                "A Project context receipt does not belong to an ordinary assistant turn."
            )


def _entries_from_rows(rows: Sequence[Sequence[object]]) -> tuple[ArchiveEntry, ...]:
    entries: list[ArchiveEntry] = []
    for expected_sequence, row in enumerate(rows):
        if (
            isinstance(row[0], bool)
            or not isinstance(row[0], int)
            or row[0] != expected_sequence
        ):
            raise ArchiveCorruptError("The conversation archive contains an invalid sequence.")
        sources, web_search = _sources_from_json(row[3])
        entries.append(
            ArchiveEntry(
                role=row[1], text=row[2], sources=sources,
                provider=row[4], model=row[5], created_at=row[6], web_search=web_search,
                application_event_id=row[7], application_event_type=row[8],
                context=_context_from_json(row[9]),
            )
        )
    try:
        return validate_archive_entries(
            tuple(entries), _allow_legacy_application_events=True
        )
    except ArchiveValidationError as exc:
        raise ArchiveCorruptError("The conversation archive contains an invalid record.") from exc


def _chat_from_rows(
    chat_row: sqlite3.Row | Sequence[object], entry_rows: Sequence[Sequence[object]]
) -> ArchivedChat:
    metadata = _metadata_from_row(chat_row)
    entries = _entries_from_rows(entry_rows)
    if (
        len(entries) != metadata.entry_count
        or len(completed_model_attributions(entries)) > metadata.completed_turn_count
        or metadata.completed_turn_count > _legacy_completed_turn_count(entries)
    ):
        raise ArchiveCorruptError("The conversation archive contains inconsistent counts.")
    if metadata.completed_turn_count == 0:
        try:
            validate_zero_turn_chat_entries(entries)
        except ArchiveValidationError as exc:
            raise ArchiveCorruptError(str(exc)) from exc
    previous_timestamp = metadata.created_at
    for entry in entries:
        assert entry.created_at is not None
        if (
            entry.created_at < previous_timestamp
            or entry.created_at > metadata.updated_at
        ):
            raise ArchiveCorruptError(
                "The conversation archive contains an invalid entry timestamp."
            )
        previous_timestamp = entry.created_at
    return ArchivedChat(metadata, entries)


def _stamp_entries(entries: Sequence[ArchiveEntry], timestamp: str) -> tuple[ArchiveEntry, ...]:
    return tuple(
        ArchiveEntry(
            item.role, item.text, item.sources, item.provider, item.model,
            timestamp, item.web_search, item.application_event_id,
            item.application_event_type, item.context,
        )
        for item in entries
    )


def _entry_matches_assertion(asserted: ArchiveEntry, stored: ArchiveEntry) -> bool:
    return (
        (asserted.role, asserted.text, asserted.sources, asserted.provider, asserted.model, asserted.web_search, asserted.application_event_id, asserted.application_event_type, asserted.context)
        == (stored.role, stored.text, stored.sources, stored.provider, stored.model, stored.web_search, stored.application_event_id, stored.application_event_type, stored.context)
        and (asserted.created_at is None or asserted.created_at == stored.created_at)
    )


def _application_event_matches(stored: ArchiveEntry, asserted: ArchiveEntry) -> bool:
    return (
        stored.role == asserted.role == "assistant"
        and stored.text == asserted.text
        and stored.sources == asserted.sources == ()
        and stored.provider is asserted.provider is None
        and stored.model is asserted.model is None
        and stored.web_search is asserted.web_search is None
        and stored.application_event_id == asserted.application_event_id
        and stored.application_event_type == asserted.application_event_type
        and stored.context is asserted.context is None
    )


def _prepare_suffix_entries(
    entries: Sequence[ArchiveEntry],
    *,
    previous_entry_timestamp: str | None,
    updated_at: str,
) -> tuple[ArchiveEntry, ...]:
    assert previous_entry_timestamp is not None
    previous = previous_entry_timestamp
    result: list[ArchiveEntry] = []
    for item in entries:
        timestamp = item.created_at if item.created_at is not None else updated_at
        if timestamp < previous or timestamp > updated_at:
            raise ArchiveValidationError(
                "A new transcript entry has an invalid timestamp order."
            )
        result.append(
            ArchiveEntry(
                item.role,
                item.text,
                item.sources,
                item.provider,
                item.model,
                timestamp,
                item.web_search,
                item.application_event_id,
                item.application_event_type,
                item.context,
            )
        )
        previous = timestamp
    return tuple(result)


def _validate_label(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_CHAT_LABEL_LENGTH:
        raise ArchiveValidationError("Chat labels must contain 1 to 80 characters.")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value):
        raise ArchiveValidationError("Chat labels cannot contain unsafe characters.")
    return value


def _validate_project_text(value: object, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str) or not value.strip() or value != value.strip()
        or len(value) > maximum or "\x00" in value
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value)
    ):
        raise ArchiveValidationError(f"{label} is invalid.")
    return value


def _validate_decision_importance(value: object) -> str:
    if value not in {"normal", "important"}:
        raise ArchiveValidationError("Project decision importance is invalid.")
    return value


def _validate_question_state(value: object) -> str:
    if value not in {"open", "resolved", "deferred", "dismissed"}:
        raise ArchiveValidationError("Project question state is invalid.")
    return value


def _validate_plan_state(value: object) -> str:
    if value not in {"planned", "active", "blocked", "deferred", "completed"}:
        raise ArchiveValidationError("Project plan state is invalid.")
    return value


def _validate_plan_order(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArchiveValidationError("Project plan order is invalid.")
    return value


def _validate_project_link_target(
    target_type: object, target_id: object
) -> tuple[str, str]:
    patterns = {
        "night_owl_finding": re.compile(r"^finding-[0-9a-f]{32}$"),
        "scheduled_work_definition": re.compile(r"^work-[0-9a-f]{32}$"),
        "knowledge_source": re.compile(r"^ksrc-[0-9a-f]{32}$"),
    }
    if not isinstance(target_type, str) or target_type not in patterns:
        raise ArchiveValidationError("Project link type is invalid.")
    target = _validate_project_text(
        target_id, "Project link target", MAX_PROJECT_LINK_TARGET_ID_LENGTH
    )
    if patterns[target_type].fullmatch(target) is None:
        raise ArchiveValidationError("Project link target identifier is invalid.")
    return target_type, target


def _require_project_revision(
    connection: sqlite3.Connection, identifier: str, expected_revision: int
) -> ProjectRecord:
    row = connection.execute(
        _PROJECT_SELECT + " WHERE identifier=?", (identifier,)
    ).fetchone()
    if row is None:
        raise ArchiveNotFoundError("The selected Project was not found.")
    project = _project_from_row(row)
    if project.revision != expected_revision:
        raise ArchiveStaleRevisionError("The Project changed after it was loaded.")
    return project


def _advance_project_revision(
    connection: sqlite3.Connection, current: ProjectRecord, timestamp: str
) -> ProjectRecord:
    updated_at = timestamp
    if updated_at <= current.updated_at:
        parsed = datetime.strptime(
            current.updated_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        updated_at = _format_timestamp(parsed + timedelta(seconds=1))
    target = ProjectRecord(
        current.identifier, current.title, current.status, current.objective,
        current.continuity_brief, current.revision + 1,
        current.created_at, updated_at,
    )
    cursor = connection.execute(
        "UPDATE projects SET revision=?,updated_at=? "
        "WHERE identifier=? AND revision=?",
        (target.revision, target.updated_at, current.identifier, current.revision),
    )
    if cursor.rowcount != 1:
        raise ArchiveStaleRevisionError(
            "The Project changed before the structured update was saved."
        )
    return target


def _require_project_decision(
    connection: sqlite3.Connection,
    identifier: str,
    project_id: str,
    expected_revision: int,
) -> ProjectDecisionRecord:
    row = connection.execute(
        "SELECT identifier,project_id,text,importance,state,"
        "supersedes_decision_id,revision,created_at,updated_at "
        "FROM project_decisions WHERE identifier=?",
        (identifier,),
    ).fetchone()
    if row is None:
        raise ArchiveNotFoundError("The selected Project decision was not found.")
    record = _project_decision_from_row(row)
    if record.project_id != project_id:
        raise ArchiveConflictError(
            "A decision cannot be mutated through another Project."
        )
    if record.revision != expected_revision:
        raise ArchiveStaleRevisionError(
            "The Project decision changed after it was loaded."
        )
    return record


def _require_project_question(
    connection: sqlite3.Connection,
    identifier: str,
    project_id: str,
    expected_revision: int,
) -> ProjectQuestionRecord:
    row = connection.execute(
        "SELECT identifier,project_id,text,state,disposition_note,revision,"
        "created_at,updated_at FROM project_questions WHERE identifier=?",
        (identifier,),
    ).fetchone()
    if row is None:
        raise ArchiveNotFoundError("The selected Project question was not found.")
    record = _project_question_from_row(row)
    if record.project_id != project_id:
        raise ArchiveConflictError(
            "A question cannot be mutated through another Project."
        )
    if record.revision != expected_revision:
        raise ArchiveStaleRevisionError(
            "The Project question changed after it was loaded."
        )
    return record


def _require_project_plan_item(
    connection: sqlite3.Connection,
    identifier: str,
    project_id: str,
    expected_revision: int,
) -> ProjectPlanItemRecord:
    row = connection.execute(
        "SELECT identifier,project_id,text,state,state_note,sort_order,revision,"
        "created_at,updated_at FROM project_plan_items WHERE identifier=?",
        (identifier,),
    ).fetchone()
    if row is None:
        raise ArchiveNotFoundError("The selected Project plan item was not found.")
    record = _project_plan_item_from_row(row)
    if record.project_id != project_id:
        raise ArchiveConflictError(
            "A plan item cannot be mutated through another Project."
        )
    if record.revision != expected_revision:
        raise ArchiveStaleRevisionError(
            "The Project plan item changed after it was loaded."
        )
    return record


def _require_project_link(
    connection: sqlite3.Connection,
    identifier: str,
    project_id: str,
    expected_revision: int,
) -> ProjectLinkRecord:
    row = connection.execute(
        "SELECT identifier,project_id,target_type,target_id,revision,"
        "created_at,updated_at FROM project_links WHERE identifier=?",
        (identifier,),
    ).fetchone()
    if row is None:
        raise ArchiveNotFoundError("The selected Project link was not found.")
    record = _project_link_from_row(row)
    if record.project_id != project_id:
        raise ArchiveConflictError("A link cannot be removed through another Project.")
    if record.revision != expected_revision:
        raise ArchiveStaleRevisionError("The Project link changed after it was loaded.")
    return record


def _decision_chain_contains(
    connection: sqlite3.Connection, start: str, candidate: str
) -> bool:
    current: str | None = start
    seen: set[str] = set()
    while current is not None:
        if current == candidate:
            return True
        if current in seen:
            raise ArchiveCorruptError(
                "The conversation archive contains a Project decision cycle."
            )
        seen.add(current)
        row = connection.execute(
            "SELECT supersedes_decision_id FROM project_decisions WHERE identifier=?",
            (current,),
        ).fetchone()
        current = None if row is None else row[0]
    return False


def _validate_optional_project_text(
    value: object, label: str, maximum: int
) -> str | None:
    if value is None:
        return None
    return _validate_project_text(value, label, maximum)


def _validate_project_child_identifier(
    value: object, pattern: re.Pattern[str], label: str
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ArchiveValidationError(f"The Project {label} identifier is invalid.")
    return value


def _validate_project_row_revision_and_timestamps(
    revision: object, created_at: object, updated_at: object
) -> None:
    _validate_revision(revision)
    validate_archive_timestamp(created_at)
    validate_archive_timestamp(updated_at)
    if not isinstance(created_at, str) or not isinstance(updated_at, str) or updated_at < created_at:
        raise ArchiveValidationError("Project record timestamps are invalid.")


def _validate_project_context_items_json(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not 2 <= len(value) <= MAX_PROJECT_CONTEXT_TIER_JSON_LENGTH
    ):
        raise ArchiveValidationError(f"Project context {label} JSON is invalid.")
    try:
        document = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveValidationError(
            f"Project context {label} JSON is invalid."
        ) from exc
    if not isinstance(document, list):
        raise ArchiveValidationError(f"Project context {label} JSON must be a list.")
    if label == "omitted":
        for item in document:
            if (
                not isinstance(item, dict)
                or not {"category", "provenance", "reason"}.issubset(item)
                or not set(item).issubset({
                    "category", "provenance", "reason", "source_id", "count",
                })
                or not isinstance(item["reason"], str)
                or item["reason"] not in {
                    "budget", "not_relevant", "source_not_loaded", "unavailable",
                }
                or not isinstance(item["category"], str)
                or item["category"] not in {
                    "stable", "working", "historical", "multiple",
                }
            ):
                raise ArchiveValidationError(
                    "Project context omission JSON has an invalid item."
                )
            _validate_project_text(
                item["provenance"], "Project context provenance", 255
            )
            if "source_id" in item:
                _validate_project_text(
                    item["source_id"], "Project context source", 255
                )
            if "count" in item and (
                isinstance(item["count"], bool)
                or not isinstance(item["count"], int)
                or item["count"] < 1
            ):
                raise ArchiveValidationError(
                    "Project context omission count is invalid."
                )
        return value
    for item in document:
        if (
            not isinstance(item, dict)
            or set(item) != {"key", "label", "value", "provenance", "source_id"}
        ):
            raise ArchiveValidationError(
                f"Project context {label} JSON has an invalid item."
            )
        _validate_project_text(item["key"], "Project context key", 64)
        _validate_project_text(item["label"], "Project context label", 255)
        _validate_project_context_value(item["value"])
        _validate_project_text(
            item["provenance"], "Project context provenance", 255
        )
        _validate_project_text(item["source_id"], "Project context source", 255)
    return value


def _validate_project_context_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 4_000
        or "\x00" in value
        or any(
            unicodedata.category(char) in {"Cs", "Zl", "Zp"}
            for char in value
        )
    ):
        raise ArchiveValidationError("Project context value is invalid.")
    return value


def _validate_legacy_project_brief(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_PROJECT_CONTINUITY_LENGTH
        or "\x00" in value
        or any(unicodedata.category(char) in {"Cs", "Zl", "Zp"} for char in value)
    ):
        raise ArchiveValidationError("Project continuity brief is invalid.")
    return value


def _validate_project_brief(value: object) -> str:
    if (
        not isinstance(value, str) or len(value) > MAX_PROJECT_CONTINUITY_LENGTH
        or "\x00" in value
        or any(unicodedata.category(char) in {"Cs", "Zl", "Zp"} for char in value)
    ):
        raise ArchiveValidationError("Project continuity brief is invalid.")
    if not value:
        return EMPTY_PROJECT_CONTINUITY_BRIEF
    if re.fullmatch(
        r"Current focus\n.+\n\nKey decisions\n.+\n\n"
        r"Open issues / blockers\n.+\n\nNext step\n.+",
        value,
        flags=re.DOTALL,
    ) is None:
        raise ArchiveValidationError(
            "Project continuity brief must contain the four required sections."
        )
    return value


def parse_project_continuity_brief(value: str) -> tuple[str, str, str, str]:
    """Return exactly one clean canonical continuity structure."""

    headings = (
        "Current focus", "Key decisions", "Open issues / blockers", "Next step",
    )
    lines = value.splitlines()
    positions: list[int] = []
    for heading in headings:
        matches = [index for index, line in enumerate(lines) if line == heading]
        if len(matches) != 1:
            raise ArchiveValidationError(
                "Project continuity brief must contain each required section exactly once."
            )
        positions.append(matches[0])
    if positions[0] != 0 or positions != sorted(positions):
        raise ArchiveValidationError("Project continuity brief sections are out of order.")
    sections: list[str] = []
    for index, position in enumerate(positions):
        end = positions[index + 1] if index + 1 < len(positions) else len(lines)
        content = "\n".join(lines[position + 1:end]).strip()
        if not content:
            raise ArchiveValidationError("Project continuity brief sections cannot be empty.")
        if any(
            line == "Recent conversation:"
            or re.match(r"^(?:user|assistant|system):(?:\s|$)", line, re.IGNORECASE)
            for line in content.splitlines()
        ):
            raise ArchiveValidationError(
                "Project continuity brief cannot contain transcript scaffolding."
            )
        sections.append(content)
    return tuple(sections)  # type: ignore[return-value]


def _validate_project_status(value: object) -> str:
    if value not in {"active", "paused", "completed"}:
        raise ArchiveValidationError("Project status is invalid.")
    assert isinstance(value, str)
    return value


def _required_metadata(value: object, field: str) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > MAX_METADATA_TEXT_LENGTH
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in value)
    ):
        raise ArchiveValidationError(f"Chat {field} metadata is invalid.")
    return value


def _optional_metadata(value: object, field: str) -> str | None:
    return None if value is None else _required_metadata(value, field)


def _validate_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ArchiveValidationError("Chat revisions must be positive integers.")
    return value


def _safe_label_character(character: str) -> str:
    category = unicodedata.category(character)
    if category in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
        codepoint = ord(character)
        if codepoint <= 0xFFFF:
            return f"\\u{codepoint:04X}"
        return f"\\U{codepoint:08X}"
    return character


def _render_label_line(line: str) -> str:
    tokens: list[str] = []
    pending_space = False
    length = 0
    for character in line:
        if character.isspace():
            pending_space = bool(tokens)
            continue
        token = _safe_label_character(character)
        separator = " " if pending_space else ""
        if length + len(separator) + len(token) > MAX_CHAT_LABEL_LENGTH:
            break
        if separator:
            tokens.append(separator)
            length += 1
        tokens.append(token)
        length += len(token)
        pending_space = False
    return "".join(tokens)


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ArchiveValidationError("Archive clocks must return timezone-aware datetimes.")
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _next_timestamp(clock_value: datetime, previous: str) -> str:
    candidate = _format_timestamp(clock_value)
    if candidate <= previous:
        parsed = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return _format_timestamp(parsed + timedelta(seconds=1))
    return candidate


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_identifier() -> str:
    return f"chat-{secrets.token_hex(16)}"


def _generate_project_identifier() -> str:
    return f"project-{secrets.token_hex(16)}"


def _generate_project_decision_identifier() -> str:
    return f"decision-{secrets.token_hex(16)}"


def _generate_project_question_identifier() -> str:
    return f"question-{secrets.token_hex(16)}"


def _generate_project_plan_identifier() -> str:
    return f"plan-item-{secrets.token_hex(16)}"


def _generate_project_link_identifier() -> str:
    return f"project-link-{secrets.token_hex(16)}"


def _legacy_schema_objects_are_exact(connection: sqlite3.Connection) -> bool:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "chats": _LEGACY_CHATS_SQL,
        "transcript_entries": _SCHEMA3_ENTRIES_SQL,
        "archive_state": _STATE_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql))
          for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        (
            "index",
            "transcript_entries_application_event_id_index",
            "transcript_entries",
            _normalize_schema_sql(_EVENT_INDEX_SQL),
        ),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
    }
    actual = {
        (
            object_type,
            name,
            table_name,
            _normalize_schema_sql(sql) if isinstance(sql, str) else None,
        )
        for object_type, name, table_name, sql in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
        )
    }
    return actual == expected


def _schema3_objects_are_exact(connection: sqlite3.Connection) -> bool:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "chats": _SCHEMA3_CHATS_SQL,
        "transcript_entries": _SCHEMA3_ENTRIES_SQL,
        "archive_state": _STATE_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql)) for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        (
            "index", "transcript_entries_application_event_id_index",
            "transcript_entries", _normalize_schema_sql(_EVENT_INDEX_SQL),
        ),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
    }
    actual = {
        (kind, name, table, _normalize_schema_sql(sql) if isinstance(sql, str) else None)
        for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    }
    return actual == expected


def _schema4_objects_are_exact(connection: sqlite3.Connection) -> bool:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "chats": _SCHEMA5_CHATS_SQL,
        "transcript_entries": _ENTRIES_SQL,
        "archive_state": _STATE_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql)) for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        (
            "index", "transcript_entries_application_event_id_index",
            "transcript_entries", _normalize_schema_sql(_EVENT_INDEX_SQL),
        ),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
    }
    actual = {
        (kind, name, table, _normalize_schema_sql(sql) if isinstance(sql, str) else None)
        for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    }
    return actual == expected


def _schema5_objects_are_exact(connection: sqlite3.Connection) -> bool:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "chats": _SCHEMA5_CHATS_SQL,
        "transcript_entries": _ENTRIES_SQL,
        "archive_state": _STATE_SQL,
        "memory_extractions": _EXTRACTIONS_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql)) for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        ("index", "transcript_entries_application_event_id_index", "transcript_entries", _normalize_schema_sql(_EVENT_INDEX_SQL)),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
        ("index", "sqlite_autoindex_memory_extractions_1", "memory_extractions", None),
        ("index", "sqlite_autoindex_memory_extractions_2", "memory_extractions", None),
        ("index", "memory_extractions_fifo_index", "memory_extractions", _normalize_schema_sql(_EXTRACTIONS_FIFO_INDEX_SQL)),
    }
    actual = {
        (kind, name, table, _normalize_schema_sql(sql) if isinstance(sql, str) else None)
        for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    }
    return actual == expected


def _schema6_objects_are_exact(connection: sqlite3.Connection) -> bool:
    expected_tables = {
        "archive_metadata": _METADATA_SQL,
        "projects": _PROJECTS_SQL,
        "chats": _CHATS_SQL,
        "transcript_entries": _ENTRIES_SQL,
        "archive_state": _STATE_SQL,
        "memory_extractions": _EXTRACTIONS_SQL,
    }
    expected = {
        *(("table", name, name, _normalize_schema_sql(sql))
          for name, sql in expected_tables.items()),
        ("index", "sqlite_autoindex_archive_metadata_1", "archive_metadata", None),
        ("index", "sqlite_autoindex_projects_1", "projects", None),
        ("index", "sqlite_autoindex_chats_1", "chats", None),
        ("index", "sqlite_autoindex_transcript_entries_1", "transcript_entries", None),
        (
            "index", "transcript_entries_application_event_id_index",
            "transcript_entries", _normalize_schema_sql(_EVENT_INDEX_SQL),
        ),
        ("index", "sqlite_autoindex_archive_state_1", "archive_state", None),
        ("index", "sqlite_autoindex_memory_extractions_1", "memory_extractions", None),
        ("index", "sqlite_autoindex_memory_extractions_2", "memory_extractions", None),
        (
            "index", "memory_extractions_fifo_index", "memory_extractions",
            _normalize_schema_sql(_EXTRACTIONS_FIFO_INDEX_SQL),
        ),
    }
    actual = {
        (kind, name, table, _normalize_schema_sql(sql) if isinstance(sql, str) else None)
        for kind, name, table, sql in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master"
        )
    }
    return actual == expected


def _create_schema7_project_objects(connection: sqlite3.Connection) -> None:
    """Create only the schema-7 Project-owned additions in dependency order."""

    for statement in (
        _PROJECT_STATE_SQL,
        _PROJECT_DECISIONS_SQL,
        _PROJECT_DECISIONS_IMMUTABILITY_TRIGGER_SQL,
        _PROJECT_DECISIONS_STATE_INDEX_SQL,
        _PROJECT_QUESTIONS_SQL,
        _PROJECT_QUESTIONS_STATE_INDEX_SQL,
        _PROJECT_PLAN_ITEMS_SQL,
        _PROJECT_PLAN_ITEMS_STATE_INDEX_SQL,
        _PROJECT_PLAN_ITEMS_ORDER_INDEX_SQL,
        _PROJECT_LINKS_SQL,
        _PROJECT_CONTEXT_RECEIPTS_SQL,
        _PROJECT_CONTEXT_RECEIPTS_PROJECT_INDEX_SQL,
    ):
        connection.execute(statement)


def _validate_extraction_identifier(value: object) -> str:
    if not isinstance(value, str) or not _EXTRACTION_IDENTIFIER_PATTERN.fullmatch(value):
        raise ArchiveValidationError("The memory extraction identifier is invalid.")
    return value


def _validate_claim_owner(value: object) -> str:
    if (
        not isinstance(value, str) or not value or len(value) > 128
        or "\x00" in value or any(ord(character) < 32 for character in value)
    ):
        raise ArchiveValidationError("The extraction process incarnation is invalid.")
    return value


def _validate_bounded_json(
    value: object, maximum: int, label: str
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 2 <= len(value) <= maximum:
        raise ArchiveValidationError(f"The extraction {label} is invalid.")
    try:
        document = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ArchiveValidationError(f"The extraction {label} is invalid.") from exc
    if not isinstance(document, (dict, list)):
        raise ArchiveValidationError(f"The extraction {label} is invalid.")
    canonical = json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if canonical != value:
        raise ArchiveValidationError(f"The extraction {label} is not canonical JSON.")
    return value


def _optional_safe_code(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str) or not 1 <= len(value) <= 64
        or not re.fullmatch(r"[a-z0-9_]+", value)
    ):
        raise ArchiveValidationError("The extraction error classification is invalid.")
    return value


def _eligible_extraction_source(
    user: ArchiveEntry,
    assistant: ArchiveEntry,
    provider_id: str,
    model_id: str,
) -> bool:
    return (
        user.role == "user"
        and user.application_event_id is None
        and assistant.role == "assistant"
        and assistant.application_event_id is None
        and assistant.provider == provider_id
        and assistant.model is not None
        and bool(user.text.strip())
        and bool(assistant.text.strip())
    )


def _validate_memory_extraction_request(
    value: object, entries: Sequence[ArchiveEntry]
) -> MemoryExtractionRequest:
    if not isinstance(value, MemoryExtractionRequest):
        raise ArchiveValidationError("The memory extraction request is invalid.")
    extraction_id = _validate_extraction_identifier(value.extraction_id)
    user_sequence = value.user_sequence
    assistant_sequence = value.assistant_sequence
    if (
        isinstance(user_sequence, bool) or not isinstance(user_sequence, int)
        or user_sequence < 0 or not isinstance(assistant_sequence, int)
        or assistant_sequence <= user_sequence
        or assistant_sequence >= len(entries)
    ):
        raise ArchiveValidationError("The memory extraction source sequence is invalid.")
    provider_id = _required_metadata(value.provider_id, "provider")
    model_id = _required_metadata(value.model_id, "model")
    if (
        not isinstance(value.provider_fingerprint, str)
        or not _FINGERPRINT_PATTERN.fullmatch(value.provider_fingerprint)
    ):
        raise ArchiveValidationError("The provider fingerprint is invalid.")
    if not _eligible_extraction_source(
        entries[user_sequence], entries[assistant_sequence], provider_id, model_id
    ):
        raise ArchiveValidationError(
            "Memory extraction requires one exact ordinary completed model turn."
        )
    if any(
        entry.role not in {"system", "warning"}
        for entry in entries[user_sequence + 1:assistant_sequence]
    ):
        raise ArchiveValidationError("The memory extraction turn boundary is invalid.")
    return MemoryExtractionRequest(
        extraction_id, user_sequence, assistant_sequence,
        provider_id, model_id, value.provider_fingerprint,
    )


def _memory_extraction_from_row(row: tuple[object, ...]) -> MemoryExtractionRecord:
    try:
        extraction_id = _validate_extraction_identifier(row[0])
        source_chat_id = validate_chat_identifier(row[1])
        user_sequence, assistant_sequence, archive_revision = row[2], row[3], row[4]
        if (
            isinstance(user_sequence, bool) or not isinstance(user_sequence, int)
            or user_sequence < 0 or not isinstance(assistant_sequence, int)
            or assistant_sequence <= user_sequence
        ):
            raise ValueError
        archive_revision = _validate_revision(archive_revision)
        provider_id = _required_metadata(row[5], "provider")
        model_id = _required_metadata(row[6], "model")
        if not isinstance(row[7], str) or not _FINGERPRINT_PATTERN.fullmatch(row[7]):
            raise ValueError
        state = row[8]
        if state not in {
            "pending", "running", "planned", "awaiting_confirmation",
            "completed", "failed", "cancelled",
        }:
            raise ValueError
        revision = _validate_revision(row[9])
        claim_owner = None if row[10] is None else _validate_claim_owner(row[10])
        plan_json = _validate_bounded_json(row[11], 24_000, "plan")
        proposal_json = _validate_bounded_json(row[12], 12_000, "proposal")
        safe_error_code = _optional_safe_code(row[13])
        created_at = validate_archive_timestamp(row[14])
        updated_at = validate_archive_timestamp(row[15])
        completed_at = None if row[16] is None else validate_archive_timestamp(row[16])
        if updated_at < created_at or (completed_at is not None and completed_at < updated_at):
            raise ValueError
    except (ArchiveValidationError, IndexError, TypeError, ValueError) as exc:
        raise ArchiveCorruptError(
            "Tori's conversation archive contains an invalid memory extraction record."
        ) from exc
    return MemoryExtractionRecord(
        extraction_id, source_chat_id, user_sequence, assistant_sequence,
        archive_revision, provider_id, model_id, row[7], state, revision,
        claim_owner, plan_json, proposal_json, safe_error_code,
        created_at, updated_at, completed_at,
    )


def _normalize_schema_sql(value: str) -> str:
    """Normalize formatting only outside SQL quoted regions."""

    result: list[str] = []
    index = 0
    quote: str | None = None
    closing = {"[": "]", "'": "'", '"': '"', "`": "`"}
    while index < len(value):
        character = value[index]
        if quote is None:
            if character in closing:
                quote = character
                result.append(character)
            elif not character.isspace():
                result.append(character.lower())
            index += 1
            continue
        result.append(character)
        delimiter = closing[quote]
        if character == delimiter:
            if quote != "[" and index + 1 < len(value) and value[index + 1] == delimiter:
                result.append(delimiter)
                index += 2
                continue
            quote = None
        index += 1
    normalized = "".join(result)
    return normalized[:-1] if normalized.endswith(";") else normalized


def _directory_flag() -> int:
    if not hasattr(os, "O_DIRECTORY"):
        raise ArchiveUnavailableError(
            "Tori's conversation archive path cannot be opened safely."
        )
    return os.O_DIRECTORY


def _no_follow_flag() -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ArchiveUnavailableError(
            "Tori's conversation archive path cannot be opened safely."
        )
    return os.O_NOFOLLOW


def _close_on_exec_flag() -> int:
    return getattr(os, "O_CLOEXEC", 0)


def _stat_at(descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _rename_without_replacement(
    parent_descriptor: int, source: str, destination: str
) -> None:
    """Atomically move one entry without ever replacing the destination."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise OSError(
            errno.ENOSYS,
            "renameat2 is required for safe archive initialization",
        ) from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        parent_descriptor,
        os.fsencode(source),
        parent_descriptor,
        os.fsencode(destination),
        1,  # RENAME_NOREPLACE
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _database_error(error: sqlite3.Error) -> ConversationArchiveError:
    message = str(error).lower()
    if isinstance(error, sqlite3.DatabaseError) and (
        "malformed" in message or "not a database" in message
    ):
        return ArchiveCorruptError(
            "Tori's conversation archive is corrupt or unreadable; it was not replaced."
        )
    return ArchiveUnavailableError("Tori's conversation archive is unavailable.")
