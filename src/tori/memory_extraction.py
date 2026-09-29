"""Narrow durable coordinator for exact-turn intelligent-memory completion."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import hashlib
import json
import secrets
import threading
from typing import Any

from .chats import ChatService, ChatServiceError
from .conversation_archive import MemoryExtractionRecord
from .intelligent_memory import (
    IntelligentMemoryService,
    MemoryTurnPlan,
    memory_plan_from_json,
    memory_plan_json,
)
from .memory import (
    AUTOMATIC_DIRECT,
    CONFIRMED_INFERRED,
    MemoryError,
    SQLiteMemoryStore,
)
from .providers import ModelProvider, ProviderError


ProviderResolver = Callable[[str, str], ModelProvider | None]
ForegroundBusy = Callable[[], bool]


def provider_definition_fingerprint(
    provider: ModelProvider, provider_id: str, model_id: str
) -> str:
    """Hash the exact non-secret provider definition used for deferred work."""

    explicit = getattr(provider, "configuration_fingerprint", None)
    if callable(explicit):
        value = explicit()
        if isinstance(value, str) and len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        ):
            return value
    attributes: dict[str, object] = {}
    for name in (
        "_profile_id", "_endpoint", "_catalog_endpoint", "_chat_endpoint",
        "_models_endpoint", "_timeout_seconds", "_keep_alive",
        "_authentication", "_structured_output",
    ):
        value = getattr(provider, name, None)
        if isinstance(value, (str, int, float, bool)) or value is None:
            attributes[name] = value
    payload = {
        "class": f"{type(provider).__module__}.{type(provider).__qualname__}",
        "provider": provider_id,
        "model": model_id,
        "definition": attributes,
    }
    rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def new_extraction_id() -> str:
    return "extract-" + secrets.token_hex(16)


class MemoryExtractionCoordinator:
    """Process one durable FIFO outbox without participating in foreground busy."""

    def __init__(
        self,
        chats: ChatService,
        memory: SQLiteMemoryStore,
        provider_resolver: ProviderResolver,
        *,
        foreground_busy: ForegroundBusy = lambda: False,
        process_incarnation: str | None = None,
    ) -> None:
        self._chats = chats
        self._memory = memory
        self._provider_resolver = provider_resolver
        self._foreground_busy = foreground_busy
        self._incarnation = process_incarnation or (
            "process-" + secrets.token_hex(16)
        )
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._effect_lock = threading.Lock()

    @property
    def process_incarnation(self) -> str:
        return self._incarnation

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="tori-memory-extraction", daemon=True
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            self._thread = None

    @contextmanager
    def source_mutation_guard(self):  # type: ignore[no-untyped-def]
        """Serialize source deletion with the final memory-effect boundary."""

        with self._effect_lock:
            yield

    def process_one(self) -> bool:
        """Process at most one claim; exposed for deterministic recovery tests."""

        if self._stop.is_set() or self._foreground_busy():
            return False
        record = self._chats.claim_next_memory_extraction(self._incarnation)
        if record is None:
            return False
        self._process(record)
        return True

    def attention_for_chat(self, chat_id: str | None) -> dict[str, object] | None:
        """Return the first safe durable proposal for exactly the active chat."""

        if chat_id is None:
            return None
        for record in self._chats.list_memory_extractions():
            if (
                record.source_chat_id != chat_id
                or record.state != "awaiting_confirmation"
                or record.proposal_json is None
            ):
                continue
            proposals = _proposal_values(record.proposal_json)
            if not proposals:
                continue
            proposal = proposals[0]
            return {
                "extraction_id": record.extraction_id,
                "revision": record.revision,
                "token": proposal["token"],
                "action": "memory.proposal." + (
                    "update" if proposal["action"] == "confirm_update" else "create"
                ),
                "message": proposal["message"],
            }
        return None

    def decide(
        self,
        extraction_id: str,
        *,
        expected_revision: int,
        chat_id: str,
        token: str,
        decision: str,
    ) -> str:
        """Apply one revision-bound durable proposal decision exactly once."""

        if decision not in {"confirm", "cancel"} or not isinstance(token, str):
            raise ChatServiceError("The memory proposal decision is invalid.", code="invalid_record")
        record = self._chats.get_memory_extraction(extraction_id)
        if (
            record is None or record.source_chat_id != chat_id
            or record.state != "awaiting_confirmation"
            or record.revision != expected_revision
            or record.proposal_json is None
        ):
            raise ChatServiceError(
                "That memory proposal is stale or belongs to another chat.",
                code="stale_revision",
            )
        proposals = _proposal_values(record.proposal_json)
        selected = next((item for item in proposals if item["token"] == token), None)
        if selected is None:
            raise ChatServiceError(
                "That memory proposal is stale or belongs to another chat.",
                code="stale_revision",
            )
        claimed = self._chats.claim_memory_confirmation(
            extraction_id,
            expected_revision=expected_revision,
            process_incarnation=self._incarnation,
        )
        status = "Memory proposal dismissed."
        if decision == "confirm":
            index = selected["candidate_index"]
            if selected["action"] == "confirm_update":
                effect = self._memory.apply_extraction_update(
                    effect_id=selected["effect_id"],
                    extraction_id=claimed.extraction_id,
                    candidate_index=index,
                    target_identifier=selected["target_id"],
                    expected_updated_at=selected["target_updated_at"],
                    text=selected["text"],
                    source_chat_id=claimed.source_chat_id,
                    source_user_sequence=claimed.source_user_sequence,
                    extraction_provider=claimed.provider_id,
                    extraction_model=claimed.model_id,
                )
            else:
                effect = self._memory.apply_extraction_create(
                    effect_id=selected["effect_id"],
                    extraction_id=claimed.extraction_id,
                    candidate_index=index,
                    action="confirmed_create",
                    text=selected["text"],
                    category=selected["category"],
                    provenance=CONFIRMED_INFERRED,
                    source_chat_id=claimed.source_chat_id,
                    source_user_sequence=claimed.source_user_sequence,
                    extraction_provider=claimed.provider_id,
                    extraction_model=claimed.model_id,
                    user_confirmed=True,
                )
            status = (
                "Remembered: " + selected["text"]
                if effect.outcome in {"created", "updated", "duplicate"}
                else "Memory proposal was stale or could not be saved."
            )
        remaining = [item for item in proposals if item["token"] != token]
        if remaining:
            proposal_json = json.dumps(
                {"proposals": remaining}, ensure_ascii=True,
                separators=(",", ":"), sort_keys=True,
            )
            self._chats.transition_memory_extraction(
                claimed.extraction_id,
                expected_revision=claimed.revision,
                process_incarnation=self._incarnation,
                state="awaiting_confirmation",
                proposal_json=proposal_json,
            )
        else:
            self._chats.transition_memory_extraction(
                claimed.extraction_id,
                expected_revision=claimed.revision,
                process_incarnation=self._incarnation,
                state="completed",
            )
        return status

    def _run(self) -> None:
        while not self._stop.is_set():
            progressed = False
            try:
                progressed = self.process_one()
            except (ChatServiceError, MemoryError):
                progressed = False
            if not progressed:
                self._wake.wait(timeout=1.0)
                self._wake.clear()

    def _process(self, record: MemoryExtractionRecord) -> None:
        source = self._chats.extraction_source_entries(record)
        if source is None:
            self._terminal(record, "cancelled", "source_unavailable")
            return
        provider = self._provider_resolver(record.provider_id, record.model_id)
        if provider is None:
            self._terminal(record, "failed", "provider_unavailable")
            return
        if provider_definition_fingerprint(
            provider, record.provider_id, record.model_id
        ) != record.provider_fingerprint:
            self._terminal(record, "failed", "provider_definition_changed")
            return

        current = record
        try:
            if current.plan_json is None:
                service = IntelligentMemoryService(
                    self._memory,
                    provider,
                    provider_name=current.provider_id,
                    model_name=current.model_id,
                )
                plan = service.evaluate_completed_turn(
                    source[0].text, suppress_failures=False
                )
                rendered = memory_plan_json(plan)
                current = self._chats.transition_memory_extraction(
                    current.extraction_id,
                    expected_revision=current.revision,
                    process_incarnation=self._incarnation,
                    state="planned",
                    plan_json=rendered,
                )
            else:
                plan = memory_plan_from_json(current.plan_json)
            if any(
                effect.candidate.evidence not in source[0].text
                for effect in plan.effects
            ):
                raise ValueError("The durable memory plan lost its evidence binding.")
        except ChatServiceError:
            return
        except (ProviderError, ValueError, TypeError, json.JSONDecodeError):
            self._terminal(current, "failed", "provider_or_plan_failure")
            return

        with self._effect_lock:
            self._apply_plan(current, plan)

    def _apply_plan(
        self, current: MemoryExtractionRecord, plan: MemoryTurnPlan
    ) -> None:
        # Chat deletion or source divergence after provider evaluation cancels
        # authority before any canonical memory effect is attempted.
        fresh = self._chats.get_memory_extraction(current.extraction_id)
        if fresh is None or self._chats.extraction_source_entries(fresh) is None:
            return
        current = fresh
        proposals: list[dict[str, Any]] = []
        for index, effect in enumerate(plan.effects):
            if effect.action in {"reject", "duplicate"}:
                continue
            effect_id = _effect_id(current.extraction_id, index, effect.action)
            if effect.action == "automatic_create":
                self._memory.apply_extraction_create(
                    effect_id=effect_id,
                    extraction_id=current.extraction_id,
                    candidate_index=index,
                    action="automatic_create",
                    text=effect.candidate.text,
                    category=effect.candidate.category,
                    provenance=AUTOMATIC_DIRECT,
                    source_chat_id=current.source_chat_id,
                    source_user_sequence=current.source_user_sequence,
                    extraction_provider=current.provider_id,
                    extraction_model=current.model_id,
                    user_confirmed=False,
                )
                continue
            # A confirmation may have committed its receipt immediately before
            # the process stopped.  Recovery terminalizes that already-effective
            # decision instead of presenting a second actionable proposal.
            if self._memory.get_extraction_effect(effect_id) is not None:
                continue
            proposals.append({
                "action": effect.action,
                "candidate_index": index,
                "category": effect.candidate.category,
                "effect_id": effect_id,
                "message": (
                    "Replace the related memory with: "
                    if effect.action == "confirm_update"
                    else "Remember this proposed understanding: "
                ) + effect.candidate.text,
                "target_id": effect.target_identifier,
                "target_updated_at": effect.target_updated_at,
                "text": effect.candidate.text,
                "token": secrets.token_urlsafe(32),
            })
        if proposals:
            proposal_json = json.dumps(
                {"proposals": proposals},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            self._chats.transition_memory_extraction(
                current.extraction_id,
                expected_revision=current.revision,
                process_incarnation=self._incarnation,
                state="awaiting_confirmation",
                proposal_json=proposal_json,
            )
        else:
            self._chats.transition_memory_extraction(
                current.extraction_id,
                expected_revision=current.revision,
                process_incarnation=self._incarnation,
                state="completed",
            )

    def _terminal(
        self, record: MemoryExtractionRecord, state: str, error: str
    ) -> None:
        try:
            self._chats.transition_memory_extraction(
                record.extraction_id,
                expected_revision=record.revision,
                process_incarnation=self._incarnation,
                state=state,
                safe_error_code=error,
            )
        except ChatServiceError:
            # Deleting the source chat is an authorized cancellation and may
            # cascade the claim before a returning provider result is handled.
            pass


def _effect_id(extraction_id: str, index: int, action: str) -> str:
    value = f"{extraction_id}:{index}:{action}".encode("ascii")
    return "effect-" + hashlib.sha256(value).hexdigest()[:32]


def _proposal_values(value: str) -> list[dict[str, Any]]:
    document = json.loads(value)
    if not isinstance(document, dict) or set(document) != {"proposals"}:
        raise ChatServiceError("The durable memory proposal is invalid.", code="invalid_record")
    proposals = document["proposals"]
    if not isinstance(proposals, list) or not proposals:
        raise ChatServiceError("The durable memory proposal is invalid.", code="invalid_record")
    return proposals
