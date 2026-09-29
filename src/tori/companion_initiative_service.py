"""Deterministic Companion Initiative eligibility and local archive delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
import secrets
from typing import Protocol
from zoneinfo import ZoneInfo

from .chats import ChatItem, ChatService, ChatServiceError
from .companion_initiative import (
    AttentionItem,
    CompanionInitiativeConflictError,
    InitiativeActivity,
    InitiativeCandidate,
    InitiativeReplyContext,
    InitiativeSettings,
    MAX_LEASE,
    ResumeAnchor,
    SQLiteCompanionInitiativeStore,
    evaluate_policy,
    morning_candidate_key,
    resume_candidate_key,
    resume_window,
    silence_candidate_key,
)
from .companion_initiative_context import StructuredResumeAnchorProvider
from .conversation_application import ConversationTurnRequest
from .operation_coordinator import OperationCoordinator
from .operator_observability import operator_event, operator_failure
from .request_origin import RequestOriginKind


class NightOwlAttention(Protocol):
    count: int
    digest: str
    oldest_at: str
    newest_at: str


class NightOwlAttentionPort(Protocol):
    def current(self) -> NightOwlAttention | None: ...


class AttentionSourcesPort(Protocol):
    def snapshots(self) -> tuple[tuple[str, tuple[object, ...]], ...]: ...


MORNING_WORDING = (
    "Good morning. Want to ease into the day, review what’s ahead, or just talk?"
)
RESUME_GENERIC_WORDING = (
    "Want to pick up the work we left waiting, or leave it for later?"
)
LONG_SILENCE_WORDING = (
    "Hey—just checking in. No need to respond; I’m here if you feel like "
    "talking or working through something."
)
NIGHT_OWL_WORDING_SINGULAR = (
    "I found one local-AI development that may be useful for Tori. Want to see it?"
)
APPLICATION_EVENT_TYPE = "companion_initiative"
REPLY_CONTEXT_LIMIT = 1024


@dataclass(frozen=True, slots=True)
class InitiativeEvaluation:
    outcome: str
    candidate: InitiativeCandidate | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _CandidateSpec:
    initiative_type: str
    dedupe_key: str
    eligible_at: datetime
    expires_at: datetime | None
    wording: str
    anchor_kind: str | None = None
    anchor_id: str | None = None
    anchor_revision: int | None = None
    attention_ids: tuple[str, ...] = ()


class CompanionInitiativeService:
    """Own eligibility, claims, recovery, and one local application event."""

    def __init__(
        self,
        *,
        store: SQLiteCompanionInitiativeStore,
        chats: ChatService,
        anchors: StructuredResumeAnchorProvider,
        coordinator: OperationCoordinator,
        timezone_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        readiness: Callable[[], bool] = lambda: True,
        night_owl_attention: NightOwlAttentionPort | None = None,
        attention_sources: AttentionSourcesPort | None = None,
        owner: str | None = None,
    ) -> None:
        self._store = store
        self._chats = chats
        self._anchors = anchors
        self._coordinator = coordinator
        self._timezone_name = ZoneInfo(timezone_name).key
        self._clock = clock
        self._readiness = readiness
        self._night_owl_attention = night_owl_attention
        self._attention_sources = attention_sources
        self._owner = owner or f"initiative-{secrets.token_hex(16)}"

    def evaluate(self) -> InitiativeEvaluation:
        """Evaluate and possibly append one local check-in."""

        if not self._coordinator.acquire_quiet():
            return InitiativeEvaluation("suppressed", reasons=("busy",))
        try:
            return self._evaluate_locked(self._utc_now())
        except Exception as exc:
            operator_failure(
                "companion_initiative.evaluate.failed",
                exc,
                code=getattr(exc, "code", "initiative_unavailable"),
                origin="local_application",
            )
            return InitiativeEvaluation("suppressed", reasons=("unavailable",))
        finally:
            self._coordinator.release()

    def recover_startup(self) -> tuple[InitiativeCandidate, ...]:
        """Reconcile expired delivery leases without creating new messages."""

        if not self._store.exists or not self._coordinator.acquire_quiet():
            return ()
        try:
            return self._recover_stale(self._utc_now())
        except Exception as exc:
            operator_failure(
                "companion_initiative.recovery.failed",
                exc,
                code=getattr(exc, "code", "recovery_unavailable"),
                origin="local_application",
            )
            return ()
        finally:
            self._coordinator.release()

    def reply_context(self, request: ConversationTurnRequest) -> str | None:
        """Consume the exact delivered check-in for one local same-chat turn."""

        if (
            request.origin.kind is not RequestOriginKind.LOCAL_WEB
            or request.conversation_id is None
        ):
            return None
        context = self._store.claim_reply_context(
            request.conversation_id, at=self._utc_now()
        )
        return None if context is None else _reply_context_text(context)

    def dismiss(self, application_event_id: str) -> InitiativeCandidate:
        """Idempotently resolve the exact delivered local check-in."""

        candidate = self._store.candidate_for_event(application_event_id)
        if candidate is None:
            raise CompanionInitiativeConflictError(
                "Companion Initiative event is unavailable."
            )
        if candidate.state in {"dismissed", "acknowledged"}:
            return candidate
        if candidate.state != "delivered":
            raise CompanionInitiativeConflictError(
                "Companion Initiative event is not dismissible."
            )
        return self._store.transition_candidate(
            candidate.identifier,
            "dismissed",
            expected_revision=candidate.revision,
            reason="user_dismissed",
            at=self._utc_now(),
        )

    def _evaluate_locked(self, now: datetime) -> InitiativeEvaluation:
        if not self._store.exists:
            return InitiativeEvaluation("suppressed", reasons=("master_off",))
        self._recover_stale(now)
        self.reconcile_attention()
        settings = self._store.settings()
        activity = self._store.activity()
        history = self._store.delivery_history()
        if not settings.master_enabled or not any((
            settings.morning_enabled,
            settings.resume_enabled,
            settings.long_silence_enabled,
            settings.night_owl_findings_enabled,
        )):
            self._retire_stale_pending(settings, activity, None, now)
            return InitiativeEvaluation(
                "suppressed",
                reasons=("master_off",) if not settings.master_enabled else ("type_off",),
            )

        unresolved = tuple(
            item
            for item in self._store.list_candidates()
            if item.state in {"delivering", "delivered"}
        )
        if unresolved:
            return InitiativeEvaluation(
                "suppressed", unresolved[0], ("unresolved_initiative",)
            )
        try:
            ready = self._readiness()
        except Exception:
            ready = False
        if ready is not True:
            return InitiativeEvaluation("suppressed", reasons=("busy",))
        active = self._chats.active_chat_metadata()
        if active is None:
            return InitiativeEvaluation("suppressed", reasons=("no_active_chat",))
        anchor = self._anchors.current(settings, activity, at=now)
        self._retire_stale_pending(settings, activity, anchor, now)

        reasons: list[str] = []
        initiative_types = (
            ("resume", "night_owl_findings", "morning", "long_silence")
            if self._attention_sources is None
            else ("attention", "morning", "resume")
        )
        for initiative_type in initiative_types:
            spec = self._spec(initiative_type, settings, activity, anchor, now)
            policy_type = "resume" if initiative_type == "attention" else initiative_type
            decision = evaluate_policy(
                policy_type,
                now=now,
                timezone_name=self._timezone_name,
                settings=settings,
                activity=activity,
                delivered_history=history,
                type_ready=spec is not None,
            )
            if not decision.eligible:
                reasons.extend(decision.reasons)
                continue
            assert spec is not None
            candidate = self._store.create_candidate(
                initiative_type=(
                    "resume" if spec.initiative_type == "attention"
                    else spec.initiative_type
                ),
                dedupe_key=spec.dedupe_key,
                eligible_at=spec.eligible_at,
                expires_at=spec.expires_at,
                wording=spec.wording,
                anchor_kind=spec.anchor_kind,
                anchor_id=spec.anchor_id,
                anchor_revision=spec.anchor_revision,
                attention_ids=spec.attention_ids,
            )
            if candidate.state != "pending":
                reasons.append("logical_initiative_already_used")
                continue
            if not self._still_current(spec, settings, activity, active, now):
                return InitiativeEvaluation("suppressed", candidate, ("state_changed",))
            claimed = self._store.claim(
                candidate.identifier,
                expected_revision=candidate.revision,
                owner=self._owner,
                target_chat_id=active.identifier,
                target_chat_revision=active.revision,
                lease_until=now + MAX_LEASE,
            )
            if not self._still_current(spec, settings, activity, active, now):
                released = self._store.release_claim(
                    claimed.identifier,
                    expected_revision=claimed.revision,
                    owner=self._owner,
                    disposition="superseded",
                    reason="source_or_policy_changed",
                )
                return InitiativeEvaluation("suppressed", released, ("state_changed",))
            return self._deliver(claimed, active, now)
        return InitiativeEvaluation("suppressed", reasons=tuple(dict.fromkeys(reasons)))

    def reconcile_attention(self) -> tuple[AttentionItem, ...]:
        if self._attention_sources is None or not self._store.exists:
            return self._store.list_attention(include_resolved=False) if self._store.exists else ()
        try:
            snapshots = self._attention_sources.snapshots()
        except Exception as exc:
            operator_failure(
                "companion_attention.sources.failed", exc,
                code=getattr(exc, "code", "attention_source_unavailable"),
                origin="local_application", category="attention_sources",
            )
            return self._store.list_attention(include_resolved=False)
        for source, signals in snapshots:
            try:
                self._store.reconcile_attention(source, signals)  # type: ignore[arg-type]
            except Exception as exc:
                operator_failure(
                    "companion_attention.reconcile.failed", exc,
                    code=getattr(exc, "code", "attention_source_unavailable"),
                    origin="local_application", category=source,
                )
        return self._store.list_attention(include_resolved=False)

    def _deliver(
        self, candidate: InitiativeCandidate, active: ChatItem, now: datetime
    ) -> InitiativeEvaluation:
        try:
            self._chats.append_application_event(
                active.identifier,
                expected_revision=active.revision,
                event_id=candidate.application_event_id,
                event_type=APPLICATION_EVENT_TYPE,
                text=candidate.wording,
            )
        except ChatServiceError as exc:
            if exc.code == "stale_revision":
                observation = self._observe_event(candidate)
                if observation == "absent":
                    released = self._store.release_claim(
                        candidate.identifier,
                        expected_revision=candidate.revision,
                        owner=self._owner,
                        disposition="pending",
                    )
                    return InitiativeEvaluation(
                        "suppressed", released, ("chat_revision_changed",)
                    )
            raise
        if self._observe_event(candidate) != "matching":
            return InitiativeEvaluation(
                "uncertain", candidate, ("event_verification_uncertain",)
            )
        try:
            delivered = self._store.mark_delivered(
                candidate.identifier,
                expected_revision=candidate.revision,
                owner=self._owner,
                delivered_at=now,
            )
        except Exception:
            # The fixed archive event is already durable. Preserve the claim so
            # lease recovery can observe and finalize it without another append.
            raise
        operator_event(
            "companion_initiative.delivered",
            origin="local_application",
            category=delivered.type,
        )
        return InitiativeEvaluation("delivered", delivered)

    def _recover_stale(self, now: datetime) -> tuple[InitiativeCandidate, ...]:
        recovered: list[InitiativeCandidate] = []
        for candidate in self._store.stale_claims(at=now):
            try:
                observation = self._observe_event(candidate)
                recovered.append(self._store.reconcile_stale_claim(
                    candidate.identifier,
                    expected_revision=candidate.revision,
                    observation=observation,
                    observed_at=now,
                ))
            except Exception as exc:
                operator_failure(
                    "companion_initiative.recovery_item.failed",
                    exc,
                    code=getattr(exc, "code", "recovery_uncertain"),
                    origin="local_application",
                    category=candidate.type,
                )
        return tuple(recovered)

    def _observe_event(self, candidate: InitiativeCandidate) -> str:
        record = self._chats.get_application_event(candidate.application_event_id)
        if record is None:
            return "absent"
        entry = record.entry
        if (
            candidate.target_chat_id == record.chat_id
            and entry.role == "assistant"
            and entry.text == candidate.wording
            and entry.application_event_id == candidate.application_event_id
            and entry.application_event_type == APPLICATION_EVENT_TYPE
            and entry.provider is None
            and entry.model is None
            and not entry.sources
            and entry.web_search is None
            and entry.context is None
        ):
            return "matching"
        return "conflict"

    def _still_current(
        self,
        spec: _CandidateSpec,
        settings: InitiativeSettings,
        activity: InitiativeActivity,
        active: ChatItem,
        now: datetime,
    ) -> bool:
        current_settings = self._store.settings()
        current_activity = self._store.activity()
        current_active = self._chats.active_chat_metadata()
        if (
            current_settings.revision != settings.revision
            or current_activity.revision != activity.revision
            or current_active is None
            or current_active.identifier != active.identifier
            or current_active.revision != active.revision
        ):
            return False
        if self._readiness() is not True:
            return False
        current_anchor = self._anchors.current(
            current_settings, current_activity, at=now
        )
        current_spec = self._spec(
            spec.initiative_type,
            current_settings,
            current_activity,
            current_anchor,
            now,
        )
        if current_spec != spec:
            return False
        return evaluate_policy(
            "resume" if spec.initiative_type == "attention" else spec.initiative_type,
            now=now,
            timezone_name=self._timezone_name,
            settings=current_settings,
            activity=current_activity,
            delivered_history=self._store.delivery_history(),
            type_ready=True,
        ).eligible

    def _retire_stale_pending(
        self,
        settings: InitiativeSettings,
        activity: InitiativeActivity,
        anchor: ResumeAnchor | None,
        now: datetime,
    ) -> None:
        current_keys = {
            "morning": morning_candidate_key(
                self._timezone_name, now.astimezone(ZoneInfo(self._timezone_name)).date()
            ),
            "long_silence": silence_candidate_key(activity.revision),
            "resume": (
                None
                if anchor is None
                else resume_candidate_key(anchor.kind, anchor.identifier, anchor.revision)
            ),
            "night_owl_findings": self._night_owl_candidate_key(settings),
        }
        enabled = {
            "morning": settings.morning_enabled,
            "resume": settings.resume_enabled,
            "long_silence": settings.long_silence_enabled,
            "night_owl_findings": settings.night_owl_findings_enabled,
        }
        for candidate in self._store.list_candidates():
            if candidate.state != "pending":
                continue
            state = reason = None
            if candidate.expires_at_utc is not None and candidate.expires_at_utc <= now:
                state, reason = "expired", "eligibility_expired"
            elif not settings.master_enabled or not enabled[candidate.type]:
                state, reason = "superseded", "type_disabled"
            elif candidate.dedupe_key != current_keys[candidate.type]:
                state, reason = "superseded", "source_or_window_changed"
            if state is not None:
                try:
                    self._store.transition_candidate(
                        candidate.identifier,
                        state,
                        expected_revision=candidate.revision,
                        reason=reason,
                        at=now,
                    )
                except Exception:
                    # A concurrent transition wins; the next scan re-reads it.
                    continue

    def _spec(
        self,
        initiative_type: str,
        settings: InitiativeSettings,
        activity: InitiativeActivity,
        anchor: ResumeAnchor | None,
        now: datetime,
    ) -> _CandidateSpec | None:
        if initiative_type == "attention":
            items = tuple(
                item for item in self._store.eligible_attention(at=now)
                if item.delivery_level == "conversational"
                and (
                    settings.night_owl_findings_enabled
                    if item.source == "night_owl"
                    else settings.resume_enabled
                )
            )
            if not items:
                return None
            item = items[0]
            return _CandidateSpec(
                "attention",
                resume_candidate_key("attention", item.identifier, item.revision),
                now,
                None,
                _attention_wording((item,)),
                "attention",
                item.identifier,
                item.revision,
                (item.identifier,),
            )
        if initiative_type == "night_owl_findings":
            if not settings.night_owl_findings_enabled or self._night_owl_attention is None:
                return None
            cohort = self._night_owl_attention.current()
            if cohort is None or cohort.count < 1:
                return None
            wording = (
                NIGHT_OWL_WORDING_SINGULAR
                if cohort.count == 1
                else f"I found {cohort.count} local-AI developments that may be useful for Tori. Want to see them?"
            )
            try:
                eligible_at = datetime.fromisoformat(
                    cohort.newest_at.removesuffix("Z") + "+00:00"
                ).astimezone(timezone.utc)
            except (TypeError, ValueError) as exc:
                raise ValueError("Night Owl attention time is invalid.") from exc
            return _CandidateSpec(
                "night_owl_findings",
                f"night-owl:{cohort.digest}",
                eligible_at,
                None,
                wording,
            )
        if initiative_type == "morning":
            zone = ZoneInfo(self._timezone_name)
            local_date = now.astimezone(zone).date()
            start = _civil_boundary(local_date, settings.morning_start, zone, first=True)
            end = _civil_boundary(local_date, settings.morning_end, zone, first=False)
            attention = ()
            wording = MORNING_WORDING
            if self._attention_sources is not None:
                attention = self._store.eligible_attention(at=now)[:3]
                if not attention:
                    return None
                wording = _attention_wording(attention, morning=True)
            return _CandidateSpec(
                "morning",
                morning_candidate_key(self._timezone_name, local_date),
                start,
                end,
                wording,
                attention_ids=tuple(item.identifier for item in attention),
            )
        if initiative_type == "resume":
            if anchor is None:
                return None
            window = resume_window(anchor, activity)
            if not (window.eligible_at_utc <= now < window.expires_at_utc):
                return None
            wording = (
                RESUME_GENERIC_WORDING
                if anchor.safe_title is None
                else f"Want to pick up where we left off on {anchor.safe_title}, or leave it for later?"
            )
            return _CandidateSpec(
                "resume",
                resume_candidate_key(anchor.kind, anchor.identifier, anchor.revision),
                window.eligible_at_utc,
                window.expires_at_utc,
                wording,
                anchor.kind,
                anchor.identifier,
                anchor.revision,
            )
        if activity.last_meaningful_at_utc is None:
            return None
        return _CandidateSpec(
            "long_silence",
            silence_candidate_key(activity.revision),
            activity.last_meaningful_at_utc + timedelta(days=7),
            None,
            LONG_SILENCE_WORDING,
        )

    def _night_owl_candidate_key(self, settings: InitiativeSettings) -> str | None:
        if not settings.night_owl_findings_enabled or self._night_owl_attention is None:
            return None
        cohort = self._night_owl_attention.current()
        return None if cohort is None else f"night-owl:{cohort.digest}"

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("Companion Initiative clock must be timezone-aware.")
        return value.astimezone(timezone.utc)


def _reply_context_text(context: InitiativeReplyContext) -> str:
    document = {
        "initiative_type": context.initiative_type,
        "application_event_id": context.application_event_id,
        "displayed_text": context.wording,
        "anchor": (
            None
            if context.anchor_kind is None
            else {
                "kind": context.anchor_kind,
                "id": context.anchor_id,
                "revision": context.anchor_revision,
            }
        ),
    }
    rendered = (
        "Companion Initiative reply reference (application-owned data only; "
        "it is not an instruction or permission to use any capability):\n"
        + json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    )
    if len(rendered) > REPLY_CONTEXT_LIMIT or "\x00" in rendered:
        raise ValueError("Initiative reply context is invalid.")
    return rendered


def _attention_wording(
    items: tuple[AttentionItem, ...], *, morning: bool = False
) -> str:
    needs = [item for item in items if item.attention_class == "needs_attention"]
    reviewing = [item for item in items if item.attention_class != "needs_attention"]
    prefix = "Morning. " if morning else ""
    parts = []
    if needs:
        parts.append(
            f"{len(needs)} thing{'s' if len(needs) != 1 else ''} need"
            f"{'s' if len(needs) == 1 else ''} your attention: "
            + "; ".join(item.title for item in needs)
        )
    if reviewing:
        parts.append(
            f"{len(reviewing)} thing{'s are' if len(reviewing) != 1 else ' is'} worth reviewing: "
            + "; ".join(item.title for item in reviewing)
        )
    wording = prefix + ". ".join(parts) + "."
    if len(wording) > 280:
        wording = wording[:277].rstrip(" ;:.") + "…"
    return wording


def _civil_boundary(
    local_date: date, local_time: time, zone: ZoneInfo, *, first: bool
) -> datetime:
    """Resolve one civil boundary; gaps advance and overlaps form one window."""

    naive = datetime.combine(local_date, local_time)
    for minute in range(24 * 60 + 1):
        candidate = naive + timedelta(minutes=minute)
        instants = {
            candidate.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            for fold in (0, 1)
            if candidate.replace(tzinfo=zone, fold=fold)
            .astimezone(timezone.utc)
            .astimezone(zone)
            .replace(tzinfo=None)
            == candidate
        }
        if instants:
            return min(instants) if first else max(instants)
    raise ValueError("Civil-time boundary could not be resolved.")
