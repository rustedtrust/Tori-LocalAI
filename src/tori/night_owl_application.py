"""User-facing Night Owl V1 application use cases.

This layer owns presentation-safe documents and explicit local user actions. It
does not accept research queries, URLs, prompts, source policy, or budgets.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import time as civil_time
import re
import threading
from typing import Callable

from .capability_growth import (
    CapabilityGrowthError,
    CapabilityGrowthApplicationService,
    SQLiteImprovementJournal,
)
from .night_owl import (
    CATEGORIES,
    FindingDetail,
    NightOwlConflictError,
    NightOwlError,
    NightOwlSettings,
    NightOwlValidationError,
    SQLiteNightOwlStore,
    budgets_for_categories,
)
from .night_owl_integration import (
    NightOwlPromotionService,
    promotion_capability_area,
)
from .night_owl_research import NightOwlResearchRunner
from .night_owl_scheduling import NIGHT_OWL_ACTION_ID, NightOwlScheduleService
from .operator_observability import operator_event, operator_failure
from .scheduled_work import ScheduledWorkError


_TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
_FINDINGS_REQUESTS = frozenset({
    "what did night owl find",
    "what did night owl find last night",
    "show me the latest night owl findings",
    "show me night owl findings",
    "show night owl findings",
})
_RUN_REQUESTS = frozenset({"run night owl", "run night owl now"})
_DETAIL_REQUEST = re.compile(
    r"^(?:tell me more about|give me more details on|give me details on|"
    r"tell me about|why does night owl think)\s*[:,-]?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_DETAIL_NUMBER = re.compile(r"^\s*\d{1,2}[.)]\s*")
_DETAIL_WORD = re.compile(r"[a-z0-9]+")
_DETAIL_STOP_WORDS = frozenset({
    "about", "details", "finding", "give", "me", "more", "night", "on",
    "owl", "please", "project", "tell", "the", "this", "why",
})
_RELEVANCE_LABELS = {
    "category_match": "it matches an enabled research category",
    "local_self_hosted": "it indicates local or self-hosted operation",
    "protocol_fit": "it mentions a protocol or API Tori can evaluate",
    "tori_subsystem_fit": "it fits an existing Tori capability area",
    "capability_gap": "it may address a bounded Capability Growth area",
    "operational_friction": "it links to recorded operational friction",
    "meaningful_improvement": "it may materially improve an existing tool",
    "watch_ubuntu": "it matches the Ubuntu family in Environment Watch (version unverified)",
    "watch_linux": "it mentions the Linux kernel in Environment Watch (version unverified)",
    "watch_nvidia": "it matches NVIDIA in Environment Watch (version unverified)",
    "watch_ssh": "it mentions OpenSSH in Environment Watch (version unverified)",
    "watch_firefox": "it mentions Firefox in Environment Watch (version unverified)",
    "watch_python": "it mentions Python in Environment Watch (version unverified)",
    "watch_ollama": "it mentions Ollama in Environment Watch (version unverified)",
    "security_general": "it is primary-source intelligence without a verified local product match",
    "kev_listed": "its CVE appears in the cited CISA KEV catalog",
}


def recognize_findings_request(text: object) -> bool:
    if not isinstance(text, str) or len(text) > 160:
        return False
    normalized = re.sub(r"[?.!]+\Z", "", " ".join(text.casefold().split()))
    return normalized in _FINDINGS_REQUESTS


def recognize_run_request(text: object) -> str | None:
    """Recognize the closed configured-run command, never a research subject."""

    if not isinstance(text, str) or len(text) > 160:
        return None
    normalized = re.sub(r"[?.!]+\Z", "", " ".join(text.casefold().split()))
    if normalized in _RUN_REQUESTS:
        return "run"
    if normalized.startswith("run night owl "):
        return "scope_rejected"
    return None


def _relevance_text(reasons: tuple[str, ...]) -> str:
    values = [_RELEVANCE_LABELS.get(reason, "it matched a bounded relevance rule") for reason in reasons]
    return "; ".join(values) + "."


def _active_finding(detail: FindingDetail) -> bool:
    """Only user-reviewable findings may surface as current Night Owl work."""

    return detail.state not in {"dismissed", "stale", "superseded"}


def _presentation_summary(detail: FindingDetail) -> str:
    """Avoid showing legacy material fingerprints as a user-facing summary."""

    legacy = "public github project with material identity "
    if detail.summary.casefold().startswith(legacy):
        return (
            f"{detail.title} is a public GitHub project in Night Owl's "
            f"{CATEGORIES[detail.category]} research category. A future successful "
            "rediscovery can add a fuller source-derived description."
        )
    return detail.summary


def _detail_subject(text: object) -> str | None:
    if not isinstance(text, str) or len(text) > 500:
        return None
    normalized = re.sub(r"[?.!]+\Z", "", " ".join(text.casefold().split()))
    match = _DETAIL_REQUEST.fullmatch(normalized)
    if match is None:
        return None
    subject = _DETAIL_NUMBER.sub("", match.group(1)).strip(" :,-.?!")
    return subject or None


def _detail_matches(subject: str, item: FindingDetail) -> bool:
    """Match one stored title/repository without treating generic chat as a lead."""

    compact_subject = " ".join(subject.casefold().split())
    title = " ".join(item.title.casefold().split())
    repository = item.source_identity.removeprefix("github:").casefold()
    if compact_subject in {title, repository}:
        return True
    subject_words = {
        word for word in _DETAIL_WORD.findall(compact_subject)
        if word not in _DETAIL_STOP_WORDS and len(word) >= 3
    }
    item_words = set(_DETAIL_WORD.findall(title)) | set(_DETAIL_WORD.findall(repository))
    # Natural references such as "the MCP skills finding" need at least two
    # concrete tokens, so ordinary "tell me more" never becomes a stored-find
    # request by accident.
    return len(subject_words) >= 2 and subject_words <= item_words


class NightOwlApplicationService:
    """Compose settings, review, scheduling, and explicit promotion safely."""

    def __init__(
        self,
        store: SQLiteNightOwlStore,
        runner: NightOwlResearchRunner,
        *,
        schedule: NightOwlScheduleService | None,
        improvement_journal: SQLiteImprovementJournal | None,
        timezone_name: str,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        self._store = store
        self._runner = runner
        self._schedule = schedule
        self._journal = improvement_journal
        self._promotion = (
            None
            if improvement_journal is None
            else NightOwlPromotionService(
                store, CapabilityGrowthApplicationService(improvement_journal)
            )
        )
        self._timezone_name = timezone_name
        self._thread_factory = thread_factory
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None

    def state(self) -> dict[str, object]:
        settings = self._store.settings()
        runs = self._store.list_runs(limit=10)
        findings = self._store.list_finding_details(limit=50)
        reviewable = tuple(item for item in findings if _active_finding(item))
        active = self._store.active_run()
        latest = None if not runs else runs[0]
        return {
            "available": True,
            "enabled": settings.enabled,
            "revision": settings.revision,
            "categories": list(settings.categories),
            "budget_profile": budgets_for_categories(settings.categories),
            "category_options": [
                {
                    "id": identifier,
                    "name": CATEGORIES[identifier],
                    "enabled": identifier in settings.categories,
                }
                for identifier in CATEGORIES
            ],
            "authorization": (
                "Off"
                if not settings.enabled
                else "Bounded public research authorized for selected categories"
            ),
            "timezone": self._timezone_name,
            "schedule": self._schedule_document(settings),
            "status": {
                "running": active is not None,
                "last_run_time": None if latest is None else latest.ended_at or latest.created_at,
                "last_run_outcome": None if latest is None else latest.run.state,
                "last_run_errors": [] if latest is None else list(latest.run.error_codes),
                "findings_count": len(findings),
                "reviewable_count": len(reviewable),
                "unseen_count": sum(item.state == "new" for item in reviewable),
            },
            "runs": [self._run_document(item) for item in runs],
            "findings": [self._finding_document(item) for item in reviewable],
        }

    def update_settings(
        self, *, expected_revision: int, enabled: bool, categories: object
    ) -> dict[str, object]:
        if type(enabled) is not bool or not isinstance(categories, list):
            raise NightOwlValidationError("Night Owl settings are invalid.")
        selected = tuple(sorted(categories))
        if (
            any(not isinstance(item, str) for item in categories)
            or len(selected) != len(categories)
            or any(item not in CATEGORIES for item in selected)
            or (enabled and not selected)
        ):
            raise NightOwlValidationError("Select at least one valid research category.")
        current = self._store.settings()
        if current.revision != expected_revision:
            raise NightOwlConflictError("Night Owl settings changed; refresh and try again.")
        profile_changed = dict(current.budgets) != budgets_for_categories(selected)
        if (
            current.enabled == enabled and current.categories == selected
            and not current.paused and not profile_changed
        ):
            return self.state()
        scheduled = self._current_schedule()
        if not enabled and scheduled is not None and scheduled.status == "active":
            assert self._schedule is not None
            self._schedule.transition(
                scheduled.identifier,
                expected_revision=scheduled.revision,
                action="pause",
            )
        revised = replace(
            current, enabled=enabled, paused=False, categories=selected
        )
        self._store.save_settings(revised, expected_revision=expected_revision)
        if enabled and scheduled is not None:
            assert self._schedule is not None
            grant = self._store.active_grant()
            assert grant is not None
            schedule = scheduled.schedule
            self._schedule.replace(
                scheduled.identifier,
                expected_revision=scheduled.revision,
                grant=grant,
                mode="nightly" if schedule.kind == "daily" else "weekly",
                timezone_name=schedule.timezone_name,
                local_time=civil_time.fromisoformat(schedule.local_time or "02:00"),
                weekday=6 if not schedule.weekdays else schedule.weekdays[0],
                confirmation_provenance="night_owl_settings",
            )
        operator_event(
            "night_owl.settings.changed",
            origin="local_web",
            enabled=enabled,
            category_count=len(selected),
        )
        return self.state()

    def start_run(self) -> dict[str, object]:
        with self._lock:
            settings = self._store.settings()
            grant = self._store.active_grant()
            if not settings.enabled or settings.paused or grant is None:
                raise NightOwlConflictError("Turn on Night Owl before starting a run.")
            if not settings.categories:
                raise NightOwlConflictError("Select at least one Night Owl category.")
            if self._store.active_run() is not None or (
                self._worker is not None and self._worker.is_alive()
            ):
                raise NightOwlConflictError("A Night Owl run is already active.")
            worker = self._thread_factory(
                target=self._run_worker,
                args=(grant,),
                name="tori-night-owl-manual",
                daemon=True,
            )
            self._worker = worker
            worker.start()
        operator_event(
            "night_owl.manual.requested",
            origin="local_web",
            category_count=len(grant.categories),
        )
        return self.state() | {"run_requested": True}

    def update_schedule(
        self, *, mode: str, local_time_text: str, weekday: int
    ) -> dict[str, object]:
        if self._schedule is None:
            raise NightOwlConflictError("Night Owl scheduling is unavailable.")
        current = self._current_schedule()
        if mode == "on_demand":
            if current is not None:
                self._schedule.transition(
                    current.identifier,
                    expected_revision=current.revision,
                    action="cancel",
                )
            return self.state()
        if (
            mode not in {"nightly", "weekly"}
            or _TIME.fullmatch(local_time_text) is None
        ):
            raise NightOwlValidationError("Night Owl schedule settings are invalid.")
        if type(weekday) is not int or not 0 <= weekday <= 6:
            raise NightOwlValidationError("Night Owl weekly day is invalid.")
        grant = self._store.active_grant()
        if grant is None:
            raise NightOwlConflictError("Turn on Night Owl before scheduling it.")
        hour, minute = map(int, local_time_text.split(":"))
        if current is None:
            self._schedule.create(
                grant,
                mode=mode,
                timezone_name=self._timezone_name,
                local_time=civil_time(hour, minute),
                weekday=weekday,
                confirmation_provenance="night_owl_settings",
            )
        else:
            self._schedule.replace(
                current.identifier,
                expected_revision=current.revision,
                grant=grant,
                mode=mode,
                timezone_name=self._timezone_name,
                local_time=civil_time(hour, minute),
                weekday=weekday,
                confirmation_provenance="night_owl_settings",
            )
        return self.state()

    def schedule_action(self, action: str) -> dict[str, object]:
        if self._schedule is None or action not in {"pause", "resume", "cancel"}:
            raise NightOwlValidationError("Night Owl schedule action is invalid.")
        current = self._current_schedule()
        if current is None:
            raise NightOwlConflictError("Night Owl has no active or paused schedule.")
        self._schedule.transition(
            current.identifier, expected_revision=current.revision, action=action
        )
        return self.state()

    def mark_finding(
        self, finding_id: str, *, expected_revision: int, action: str
    ) -> dict[str, object]:
        if action not in {"reviewed", "dismissed"}:
            raise NightOwlValidationError("Night Owl review action is invalid.")
        detail = self._store.get_finding_detail(finding_id)
        self._store.mark_finding(
            detail.identity_key,
            "seen" if action == "reviewed" else "dismissed",
            expected_revision=expected_revision,
        )
        return self.state()

    def promote(
        self,
        finding_id: str,
        *,
        lane: str,
        friction_finding_id: str | None,
    ) -> dict[str, object]:
        if self._promotion is None:
            raise NightOwlConflictError("Capability Growth promotion is unavailable.")
        if lane not in {"expand", "improve"}:
            raise NightOwlValidationError("Night Owl promotions may be EXPAND or IMPROVE.")
        detail = self._store.get_finding_detail(finding_id)
        if detail.category == "security":
            raise NightOwlConflictError("Security intelligence cannot be promoted to Capability Growth.")
        if detail.state == "dismissed":
            raise NightOwlConflictError(
                "Dismissed Night Owl findings are not eligible for promotion."
            )
        version = self._store.current_version(finding_id)
        run = self._store.latest_run_for_version(version.identifier)
        if run is None:
            raise NightOwlConflictError("No completed Night Owl run supports this finding.")
        recommendation = self._promotion.promote(
            finding_id,
            run_id=run.identifier,
            lane=lane,
            promotion_reason="Explicit local user promotion from Night Owl review.",
            friction_finding_id=friction_finding_id,
        )
        operator_event(
            "night_owl.finding.promoted",
            origin="local_web",
            lane=lane,
            category=detail.category,
        )
        return self.state() | {
            "promotion": {
                "recommendation_id": recommendation.identifier,
                "lane": recommendation.lane.upper(),
                "status": recommendation.status,
            }
        }

    def conversation_summary(self) -> str:
        findings = tuple(
            item for item in self._store.list_finding_details(limit=50)
            if _active_finding(item)
        )[:5]
        if not findings:
            return (
                "Night Owl has no reviewable stored findings yet. This only checks "
                "stored results; it did not start research or use interactive Search."
            )
        lines = [
            f"Night Owl has {len(findings)} recent stored finding"
            f"{'s' if len(findings) != 1 else ''}:"
        ]
        for index, detail in enumerate(findings, 1):
            version = self._store.current_version(detail.identifier)
            sources = self._store.sources_for_version(version.identifier)
            source = sources[0] if sources else None
            lines.append(
                f"{index}. {detail.title} — {_presentation_summary(detail)}"
                + ("" if source is None else f" Source: {source.title} ({source.url})")
            )
        lines.append(
            "These are advisory research findings, not accepted recommendations or "
            "permission to install, enable, or run anything. This read stored "
            "findings only and did not start research or use interactive Search."
        )
        return "\n\n".join(lines)

    def conversation_finding_detail(self, text: str) -> str | None:
        """Resolve a deliberately narrow request against stored findings only."""

        subject = _detail_subject(text)
        if subject is None:
            return None
        findings = tuple(
            item for item in self._store.list_finding_details(limit=50)
            if _active_finding(item)
        )
        matches = [item for item in findings if _detail_matches(subject, item)]
        if not matches:
            return None
        if len(matches) != 1:
            return (
                "Tell me which stored Night Owl finding you mean by naming its "
                "project. I can only describe findings already stored by Night Owl; "
                "I will not start new research."
            )
        detail = matches[0]
        version = self._store.current_version(detail.identifier)
        sources = self._store.sources_for_version(version.identifier)
        lines = [
            f"{detail.title} — Source-derived facts: {_presentation_summary(detail)}",
            "Why it may matter to Tori: " + _relevance_text(detail.relevance_reasons),
        ]
        if detail.risks:
            lines.append("Source-derived risks: " + "; ".join(detail.risks) + ".")
        if detail.unknowns:
            lines.append("Source-derived unknowns: " + "; ".join(detail.unknowns) + ".")
        try:
            enrichment = self._store.get_enrichment(version.identifier)
        except NightOwlError:
            enrichment = None
        if enrichment is not None:
            lines.append(
                "Model-assisted interpretation (not source evidence): "
                + enrichment.summary
            )
        if sources:
            lines.append(f"Source: {sources[0].title} ({sources[0].url})")
        lines.append("This is advisory stored research; no new research or interactive Search was started.")
        return "\n\n".join(lines)

    def _run_worker(self, grant) -> None:  # type: ignore[no-untyped-def]
        try:
            result = self._runner.run_now(grant, trigger="manual")
            operator_event(
                "night_owl.manual.finished",
                origin="local_application",
                state=result.state,
            )
        except Exception as exc:
            operator_failure(
                "night_owl.manual.failed",
                exc,
                code=getattr(exc, "code", "night_owl_failed"),
                origin="local_application",
            )

    def _current_schedule(self):  # type: ignore[no-untyped-def]
        if self._schedule is None:
            return None
        values = tuple(
            item for item in self._schedule.scheduled_work.list_definitions()
            if item.capability_id == NIGHT_OWL_ACTION_ID
            and item.status in {"active", "paused"}
        )
        return None if not values else values[0]

    def _schedule_document(self, settings: NightOwlSettings) -> dict[str, object]:
        item = self._current_schedule()
        if item is None:
            return {
                "mode": "on_demand",
                "status": "disabled",
                "local_time": "02:00",
                "weekday": 6,
                "next_run": None,
                "reauthorization_required": False,
            }
        schedule = item.schedule
        grant = self._store.active_grant()
        current_arguments = None if grant is None else {
            "grant_id": grant.identifier,
            "grant_revision": grant.revision,
            "grant_digest": grant.digest,
        }
        scheduled_arguments = item.arguments
        stale = current_arguments is None or any(
            scheduled_arguments.get(key) != value
            for key, value in current_arguments.items()
        )
        return {
            "mode": "nightly" if schedule.kind == "daily" else "weekly",
            "status": item.status,
            "local_time": schedule.local_time or "02:00",
            "weekday": 6 if not schedule.weekdays else schedule.weekdays[0],
            "next_run": item.next_occurrence_utc,
            "reauthorization_required": stale,
        }

    @staticmethod
    def _run_document(item) -> dict[str, object]:  # type: ignore[no-untyped-def]
        metrics = item.metrics
        return {
            "trigger": item.run.trigger,
            "state": item.run.state,
            "budget_used": dict(item.run.budget_used),
            "error_codes": list(item.run.error_codes),
            "created_at": item.created_at,
            "started_at": item.started_at,
            "ended_at": item.ended_at,
            "details": None if metrics is None else {
                "duration_millis": metrics.duration_millis,
                "aggregate": dict(metrics.aggregate),
                "categories": {
                    category: dict(values) for category, values in metrics.categories
                },
            },
        }

    def _finding_document(self, detail: FindingDetail) -> dict[str, object]:
        version = self._store.current_version(detail.identifier)
        sources = self._store.sources_for_version(version.identifier)
        try:
            enrichment = self._store.get_enrichment(version.identifier)
        except NightOwlError:
            enrichment_document = None
        else:
            enrichment_document = {
                "summary": enrichment.summary,
                "why_it_matters": enrichment.why_it_matters,
                "risks": list(enrichment.risks),
                "unknowns": list(enrichment.unknowns),
                "next_step": enrichment.next_step,
                "label": "Model-assisted interpretation",
            }
        receipt = self._store.promotion_for_finding(detail.identifier)
        current_promotion = (
            receipt is not None and receipt.version_id == version.identifier
        )
        friction = []
        if self._journal is not None and detail.category != "security":
            area = promotion_capability_area(detail.category)
            try:
                growth_findings = self._journal.list_findings(
                    statuses=("open", "monitoring")
                )
            except CapabilityGrowthError:
                growth_findings = ()
            friction = [
                {
                    "id": item.identifier,
                    "label": f"{item.evidence_kind}: {item.capability_id} / {item.operation_id}",
                }
                for item in growth_findings
                if item.capability_area == area
                and item.evidence_kind in {"friction", "workaround", "opportunity"}
            ]
        return {
            "id": detail.identifier,
            "revision": detail.revision,
            "category": detail.category,
            "category_name": CATEGORIES[detail.category],
            "title": detail.title,
            "source_description": _presentation_summary(detail),
            "relevance_reasons": list(detail.relevance_reasons),
            "risks": list(detail.risks),
            "unknowns": list(detail.unknowns),
            "suggested_next_step": detail.next_step,
            "state": "reviewed" if detail.state == "seen" else detail.state,
            "first_observed": detail.first_seen_at,
            "last_observed": detail.last_seen_at,
            "version": version.version_identity,
            "change_reason": version.change_reason,
            "sources": [
                {"kind": source.kind, "url": source.url, "title": source.title}
                for source in sources
            ],
            "analysis": enrichment_document,
            "promotion": (
                None
                if not current_promotion
                else {"recommendation_id": receipt.recommendation_id}
            ),
            "improve_options": friction,
        }
