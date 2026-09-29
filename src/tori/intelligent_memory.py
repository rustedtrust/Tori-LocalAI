"""Bounded, advisory extraction and application-owned curated-memory policy."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import secrets
import time
import unicodedata
from collections.abc import Callable

from .memory import (
    AUTOMATIC_DIRECT,
    CONFIRMED_INFERRED,
    CONFIRMED_UPDATE,
    MAX_MEMORY_TEXT_LENGTH,
    MEMORY_SCHEMA_VERSION,
    MEMORY_CATEGORIES,
    MemoryConflictError,
    MemoryError,
    MemoryRecord,
    MemoryVersionError,
    SQLiteMemoryStore,
    enforce_ordinary_memory_policy,
    validate_memory_category,
    validate_memory_identifier,
    validate_memory_text,
    validate_memory_timestamp,
)
from .providers import ChatMessage, ModelProvider, ProviderError


MAX_CANDIDATES_PER_TURN = 3
MAX_EXTRACTION_RESPONSE = 8_000
MAX_EVIDENCE_LENGTH = 1_000
PROPOSAL_LIFETIME_SECONDS = 300.0
_CANDIDATE_KEYS = frozenset({"text", "category", "evidence", "origin"})
_ORIGINS = frozenset({"direct", "inferred"})
_PLAN_ACTIONS = frozenset({
    "reject", "duplicate", "automatic_create", "confirm_create", "confirm_update"
})
_CANDIDATE_IDENTIFIER = re.compile(r"^candidate-[0-9a-f]{32}$")
_RELATIONSHIPS = frozenset({"independent", "duplicate", "update", "contradiction", "uncertain"})
_TEMPORARY = re.compile(r"(?i)\b(?:today|tonight|right now|currently|this (?:morning|afternoon|evening)|for now|temporary|temporarily)\b")
_SCHEDULER = re.compile(
    r"(?i)\b(?:remind me|reminder|appointment|calendar|alarm|to-?do|task|due (?:at|on|tomorrow)|snooze|notify me|every (?:day|week|month)|tomorrow at|at \d{1,2}(?::\d{2})?\s*(?:am|pm))\b"
)
_DURABLE_INFERENCE = re.compile(
    r"(?i)\b(?:for (?:the )?(?:last |past )?(?:few |several |many )?years|"
    r"over (?:the )?(?:last |past )?(?:few |several |many )?years|"
    r"whenever|consistently|regularly|usually|often|habitually|"
    r"long-standing|longstanding|stable habit|tend to)\b"
)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    identifier: str
    text: str
    category: str
    evidence: str
    origin: str


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    token: str
    action: str
    candidate: MemoryCandidate
    source_chat_id: str
    source_user_sequence: int
    provider: str
    model: str
    expires_at: float
    target_identifier: str | None = None
    target_updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryTurnResult:
    remembered: tuple[MemoryRecord, ...] = ()
    proposals: tuple[MemoryProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedMemoryEffect:
    candidate: MemoryCandidate
    action: str
    target_identifier: str | None = None
    target_updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryTurnPlan:
    """Validated application policy plan with no authority to mutate memory."""

    effects: tuple[PlannedMemoryEffect, ...] = ()


class IntelligentMemoryService:
    """Extract advisory candidates, then apply deterministic Tori policy."""

    def __init__(
        self,
        store: SQLiteMemoryStore,
        provider: ModelProvider | None,
        *,
        provider_name: str,
        model_name: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._provider = provider
        self._provider_name = provider_name
        self._model_name = model_name
        self._clock = clock
        self._pending: dict[str, MemoryProposal] = {}

    def process_completed_turn(
        self,
        user_text: str,
        *,
        chat_id: str,
        user_sequence: int,
    ) -> MemoryTurnResult:
        """Run only after authoritative archive persistence; failures are nonfatal."""

        plan = self.evaluate_completed_turn(user_text)
        return self.apply_planned_turn(
            plan, chat_id=chat_id, user_sequence=user_sequence
        )

    def evaluate_completed_turn(
        self, user_text: str, *, suppress_failures: bool = True
    ) -> MemoryTurnPlan:
        """Validate bounded advisory provider output without mutating memory."""

        try:
            if self._store.schema_version() != MEMORY_SCHEMA_VERSION:
                return MemoryTurnPlan()
            candidates = self._extract(user_text)
            existing = self._store.list_memories()
            effects: list[PlannedMemoryEffect] = []
            for candidate in candidates:
                try:
                    disposition, target = self._disposition(candidate, existing)
                except (MemoryError, ValueError):
                    disposition, target = "reject", None
                action = {
                    "create": "automatic_create",
                    "confirm_create": "confirm_create",
                    "confirm_update": "confirm_update",
                }.get(disposition, disposition)
                effects.append(PlannedMemoryEffect(
                    candidate,
                    action,
                    target.identifier if target is not None else None,
                    target.updated_at if target is not None else None,
                ))
            return MemoryTurnPlan(tuple(effects))
        except (MemoryError, ProviderError, ValueError, TypeError, json.JSONDecodeError):
            if suppress_failures:
                return MemoryTurnPlan()
            raise

    def apply_planned_turn(
        self,
        plan: MemoryTurnPlan,
        *,
        chat_id: str,
        user_sequence: int,
    ) -> MemoryTurnResult:
        """Apply application-owned M20 policy to one validated candidate plan."""

        if not isinstance(plan, MemoryTurnPlan):
            return MemoryTurnResult()
        try:
            if self._store.schema_version() != MEMORY_SCHEMA_VERSION:
                return MemoryTurnResult()
            existing = self._store.list_memories()
        except MemoryError:
            return MemoryTurnResult()
        remembered: list[MemoryRecord] = []
        proposals: list[MemoryProposal] = []
        for effect in plan.effects:
            candidate = effect.candidate
            try:
                if effect.action in {"reject", "duplicate"}:
                    continue
                if effect.action == "automatic_create":
                    if any(
                        _comparison_text(record.text) == _comparison_text(candidate.text)
                        for record in existing
                    ):
                        continue
                    record = self._store.create_derived(
                        candidate.text,
                        category=candidate.category,
                        provenance=AUTOMATIC_DIRECT,
                        source_chat_id=chat_id,
                        source_user_sequence=user_sequence,
                        extraction_provider=self._provider_name,
                        extraction_model=self._model_name,
                        user_confirmed=False,
                    )
                    remembered.append(record)
                    existing = (*existing, record)
                    continue
                target = (
                    self._store.get(effect.target_identifier)
                    if effect.target_identifier is not None else None
                )
                if (
                    effect.action == "confirm_update"
                    and (
                        target is None
                        or target.updated_at != effect.target_updated_at
                    )
                ):
                    continue
                proposal = self._proposal(candidate, chat_id, user_sequence, target)
                self._pending[proposal.token] = proposal
                proposals.append(proposal)
            except (MemoryError, ValueError):
                continue
        return MemoryTurnResult(tuple(remembered), tuple(proposals))

    def select_model(self, provider: ModelProvider | None, *, provider_name: str, model_name: str) -> None:
        """Change the extractor selection and invalidate lower-context proposals."""
        self._provider = provider
        self._provider_name = provider_name
        self._model_name = model_name
        self._pending.clear()

    def confirm(self, token: str, *, chat_id: str) -> MemoryRecord | None:
        proposal = self._consume(token, chat_id=chat_id)
        if proposal is None:
            return None
        enforce_ordinary_memory_policy(proposal.candidate.text)
        if proposal.action == "create":
            return self._store.create_derived(
                proposal.candidate.text,
                category=proposal.candidate.category,
                provenance=CONFIRMED_INFERRED,
                source_chat_id=proposal.source_chat_id,
                source_user_sequence=proposal.source_user_sequence,
                extraction_provider=proposal.provider,
                extraction_model=proposal.model,
                user_confirmed=True,
            )
        assert proposal.target_identifier and proposal.target_updated_at
        current = self._store.get(proposal.target_identifier)
        if current is None:
            return None
        # Canonical mutation remains an exact application-owned conditional update.
        updated = self._store.update_derived_if_current(
            current.identifier,
            proposal.candidate.text,
            expected_updated_at=proposal.target_updated_at,
            source_chat_id=proposal.source_chat_id,
            source_user_sequence=proposal.source_user_sequence,
            extraction_provider=proposal.provider,
            extraction_model=proposal.model,
        )
        return updated

    def dismiss(self, token: str, *, chat_id: str) -> bool:
        return self._consume(token, chat_id=chat_id) is not None

    def _extract(self, user_text: str) -> tuple[MemoryCandidate, ...]:
        if self._provider is None:
            return ()
        response = self._provider.extract_memory_candidates(
            (
                ChatMessage("system", _extraction_contract()),
                ChatMessage("user", json.dumps({"user_text": user_text}, ensure_ascii=True)),
            ),
            model=self._model_name,
        )
        if len(response.content) > MAX_EXTRACTION_RESPONSE:
            return ()
        document = json.loads(response.content)
        if not isinstance(document, dict) or set(document) != {"candidates"}:
            return ()
        values = document["candidates"]
        if not isinstance(values, list) or len(values) > MAX_CANDIDATES_PER_TURN:
            return ()
        result: list[MemoryCandidate] = []
        for value in values:
            if not isinstance(value, dict) or set(value) != _CANDIDATE_KEYS:
                continue
            text = validate_memory_text(value["text"])
            category = validate_memory_category(value["category"])
            evidence = value["evidence"]
            origin = value["origin"]
            if (
                not isinstance(evidence, str) or not evidence
                or len(evidence) > MAX_EVIDENCE_LENGTH
                or evidence not in user_text
                or origin not in _ORIGINS
            ):
                continue
            enforce_ordinary_memory_policy(text)
            enforce_ordinary_memory_policy(evidence)
            explicit_preference = bool(
                re.search(
                    r"(?i)\b(?:prefer|preference|like|dislike|favou?rite)\b",
                    evidence,
                )
            )
            if (
                origin == "inferred"
                and not _DURABLE_INFERENCE.search(evidence)
                and not (category == "preference" and explicit_preference)
            ):
                continue
            if (
                origin == "direct"
                and category == "preference"
                and not explicit_preference
            ):
                continue
            # Direct canonical memory retains the user's exact anchored words;
            # a model-authored restatement never silently becomes user truth.
            canonical_text = evidence if origin == "direct" else text
            result.append(MemoryCandidate(
                f"candidate-{secrets.token_hex(16)}",
                canonical_text,
                category,
                evidence,
                origin,
            ))
        return tuple(result)

    def _disposition(
        self, candidate: MemoryCandidate, existing: tuple[MemoryRecord, ...]
    ) -> tuple[str, MemoryRecord | None]:
        if _TEMPORARY.search(candidate.evidence) or _SCHEDULER.search(candidate.evidence):
            return "reject", None
        # Automatic acceptance is limited to exact/trivially normalized user text.
        # Model-authored paraphrases remain useful proposals but require consent.
        effectively_inferred = (
            candidate.origin == "inferred"
            or _comparison_text(candidate.text) != _comparison_text(candidate.evidence)
        )
        normalized = _comparison_text(candidate.text)
        for record in existing:
            if _comparison_text(record.text) == normalized:
                return "duplicate", record
        related = [record for record in existing if _related(candidate.text, record.text)]
        if related:
            relationship, target = self._relationship(candidate, tuple(related[:3]))
            if relationship == "duplicate":
                return "duplicate", target
            if relationship == "independent":
                return ("confirm_create", None) if effectively_inferred else ("create", None)
            if relationship in {"update", "contradiction"} and target is not None:
                return "confirm_update", target
            # Uncertainty or invalid classifier output never acquires a
            # destructive replacement target. Exact duplicates were already
            # suppressed above; the conservative fallback is a confirmation-
            # bound additive proposal that preserves existing canonical truth.
            return "confirm_create", None
        if effectively_inferred:
            return "confirm_create", None
        return "create", None

    def _relationship(
        self, candidate: MemoryCandidate, related: tuple[MemoryRecord, ...]
    ) -> tuple[str, MemoryRecord | None]:
        references = {f"related-{index}": record for index, record in enumerate(related)}
        payload = {
            "candidate": candidate.text,
            "related": [
                {"reference": reference, "text": record.text}
                for reference, record in references.items()
            ],
        }
        try:
            response = self._provider.assess_memory_relationship(
                (
                    ChatMessage(
                        "system",
                        "Classify semantic relationship, not broad topic similarity, between the "
                        "candidate and supplied memories. Return only JSON with relationship and "
                        "target. independent means both can coexist, even within one topic or project. "
                        "duplicate means materially the same durable proposition with trivial wording "
                        "variation. update means the candidate revises the same underlying attribute, "
                        "preference dimension, fact, goal, routine, or constraint. contradiction means "
                        "both cannot simultaneously be true on that same dimension. uncertain means "
                        "the same dimension cannot be established confidently; topical overlap alone "
                        "is uncertain or independent, never update. relationship is independent, "
                        "duplicate, update, contradiction, or uncertain. target must be null for "
                        "independent or uncertain, and one supplied opaque reference for duplicate, "
                        "update, or contradiction. The reference grants no mutation authority.",
                    ),
                    ChatMessage("user", json.dumps(payload, ensure_ascii=True)),
                ),
                model=self._model_name,
            )
            if len(response.content) > 2_000:
                return "uncertain", None
            document = json.loads(response.content)
            if not isinstance(document, dict) or set(document) != {"relationship", "target"}:
                return "uncertain", None
            relationship = document["relationship"]
            target_reference = document["target"]
            if relationship not in _RELATIONSHIPS:
                return "uncertain", None
            if relationship in {"independent", "uncertain"}:
                return (
                    (relationship, None)
                    if target_reference is None
                    else ("uncertain", None)
                )
            if not isinstance(target_reference, str) or target_reference not in references:
                return "uncertain", None
            return relationship, references[target_reference]
        except (ProviderError, ValueError, TypeError, json.JSONDecodeError):
            return "uncertain", None

    def _proposal(
        self,
        candidate: MemoryCandidate,
        chat_id: str,
        user_sequence: int,
        target: MemoryRecord | None,
    ) -> MemoryProposal:
        return MemoryProposal(
            token=secrets.token_urlsafe(32),
            action="update" if target is not None else "create",
            candidate=candidate,
            source_chat_id=chat_id,
            source_user_sequence=user_sequence,
            provider=self._provider_name,
            model=self._model_name,
            expires_at=self._clock() + PROPOSAL_LIFETIME_SECONDS,
            target_identifier=target.identifier if target else None,
            target_updated_at=target.updated_at if target else None,
        )

    def _consume(self, token: str, *, chat_id: str) -> MemoryProposal | None:
        if not isinstance(token, str):
            return None
        proposal = self._pending.get(token)
        if proposal is None or proposal.source_chat_id != chat_id:
            return None
        self._pending.pop(token, None)
        if self._clock() > proposal.expires_at:
            return None
        return proposal


def _comparison_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def memory_plan_json(plan: MemoryTurnPlan) -> str:
    """Serialize one bounded validated plan canonically for durable recovery."""

    if not isinstance(plan, MemoryTurnPlan) or len(plan.effects) > MAX_CANDIDATES_PER_TURN:
        raise ValueError("The memory plan is invalid.")
    document = {
        "effects": [
            {
                "action": effect.action,
                "candidate": {
                    "category": effect.candidate.category,
                    "evidence": effect.candidate.evidence,
                    "id": effect.candidate.identifier,
                    "origin": effect.candidate.origin,
                    "text": effect.candidate.text,
                },
                "target_id": effect.target_identifier,
                "target_updated_at": effect.target_updated_at,
            }
            for effect in plan.effects
        ]
    }
    rendered = json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(rendered) > 24_000:
        raise ValueError("The memory plan is too large.")
    memory_plan_from_json(rendered)
    return rendered


def memory_plan_from_json(value: str) -> MemoryTurnPlan:
    """Validate and restore exactly the application-owned durable plan schema."""

    if not isinstance(value, str) or not 2 <= len(value) <= 24_000:
        raise ValueError("The memory plan is invalid.")
    document = json.loads(value)
    if not isinstance(document, dict) or set(document) != {"effects"}:
        raise ValueError("The memory plan is invalid.")
    values = document["effects"]
    if not isinstance(values, list) or len(values) > MAX_CANDIDATES_PER_TURN:
        raise ValueError("The memory plan is invalid.")
    effects: list[PlannedMemoryEffect] = []
    for item in values:
        if not isinstance(item, dict) or set(item) != {
            "action", "candidate", "target_id", "target_updated_at"
        }:
            raise ValueError("The memory plan is invalid.")
        candidate_value = item["candidate"]
        if not isinstance(candidate_value, dict) or set(candidate_value) != {
            "category", "evidence", "id", "origin", "text"
        }:
            raise ValueError("The memory plan is invalid.")
        identifier = candidate_value["id"]
        if not isinstance(identifier, str) or not _CANDIDATE_IDENTIFIER.fullmatch(identifier):
            raise ValueError("The memory candidate identifier is invalid.")
        text = validate_memory_text(candidate_value["text"])
        category = validate_memory_category(candidate_value["category"])
        evidence, origin = candidate_value["evidence"], candidate_value["origin"]
        if (
            not isinstance(evidence, str) or not evidence
            or len(evidence) > MAX_EVIDENCE_LENGTH or origin not in _ORIGINS
        ):
            raise ValueError("The memory candidate is invalid.")
        enforce_ordinary_memory_policy(text)
        enforce_ordinary_memory_policy(evidence)
        action = item["action"]
        if action not in _PLAN_ACTIONS:
            raise ValueError("The memory plan action is invalid.")
        target_id, target_updated_at = item["target_id"], item["target_updated_at"]
        if action == "confirm_update":
            if not isinstance(target_id, str) or not isinstance(target_updated_at, str):
                raise ValueError("The memory update plan is invalid.")
            validate_memory_identifier(target_id)
            validate_memory_timestamp(target_updated_at)
        elif target_id is not None or target_updated_at is not None:
            raise ValueError("The memory plan has an unauthorized target.")
        effects.append(PlannedMemoryEffect(
            MemoryCandidate(identifier, text, category, evidence, origin),
            action, target_id, target_updated_at,
        ))
    plan = MemoryTurnPlan(tuple(effects))
    canonical = json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if canonical != value:
        raise ValueError("The memory plan is not canonical JSON.")
    return plan


def _related(left: str, right: str) -> bool:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.casefold()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.casefold()))
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) >= 0.6


def _extraction_contract() -> str:
    return (
        "Extract at most three selective durable memory candidates from only user_text. "
        "Return only the requested JSON. Each candidate has exactly text, category, evidence, "
        "origin. evidence must copy an exact complete contiguous sentence or clause from "
        "user_text and never be an isolated noun phrase. ORIGIN RULE: direct means evidence "
        "literally says the same memory, such as 'I prefer local tools.' inferred means the "
        "candidate is a conclusion from behavior, such as 'For years I consistently choose "
        "local tools' implying 'I prefer local tools.' Consistently choosing something, repeated "
        "behavior, or a long-standing pattern MUST use inferred unless evidence itself explicitly "
        "states the preference, fact, goal, routine, or constraint. Strong multi-year duration "
        "plus repeated whenever-patterns or consistent choices should produce an inferred "
        "candidate; a one-off action should produce none. text may concisely state the grounded "
        "implication. Categories: preference for likes, dislikes, choices, or statements using "
        "prefer; project for durable project facts that are not preferences; goal for intended "
        "outcomes; routine for recurring habits; constraint for durable limits; general "
        "otherwise. A preference about a project is preference. Use only those categories and "
        "direct or inferred. Exclude temporary state, reminders, appointments, tasks, secrets, "
        "medical data, and financial data. An empty candidates array is valid."
    )
