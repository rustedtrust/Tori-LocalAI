"""Bounded Night Owl seams for Capability Growth and Companion Initiative."""

from __future__ import annotations

import threading

from .capability_growth import (
    CapabilityGrowthApplicationService,
    ExternalRecommendationProposal,
    ExternalResearchProvenance,
    ExternalSourceProvenance,
    ImprovementRecommendation,
)
from .night_owl import (
    AttentionCohort,
    NightOwlConflictError,
    SQLiteNightOwlStore,
)


_PROMOTION_POLICY = {
    "local_models": (
        "local_ai_integration", "needs_application_adapter",
        ("application_adapter", "user_decision"),
    ),
    "voice": (
        "communication", "needs_application_adapter",
        ("application_adapter", "user_decision"),
    ),
    "image_generation": (
        "images_media", "needs_application_adapter",
        ("application_adapter", "user_decision"),
    ),
    "coding_agents": (
        "coding", "needs_application_adapter",
        ("application_adapter", "user_decision"),
    ),
    "mcp_infrastructure": (
        "automation_integration", "needs_mcp_or_external_integration",
        ("mcp_integration", "user_decision"),
    ),
    "skills_tori_tools": (
        "automation_integration", "needs_skill_lifecycle_or_permission",
        ("skill_install", "skill_enable", "user_decision"),
    ),
}


def promotion_capability_area(category: str) -> str:
    """Return the fixed Capability Growth area for one Night Owl category."""

    try:
        return _PROMOTION_POLICY[category][0]
    except KeyError as exc:
        raise NightOwlConflictError("That Night Owl category cannot be promoted.") from exc


class NightOwlAttentionProvider:
    """Expose count/time/digest metadata only; no research prose or authority."""

    def __init__(self, store: SQLiteNightOwlStore) -> None:
        self._store = store

    def current(self) -> AttentionCohort | None:
        return self._store.attention_cohort()

    def still_exists(self, digest: str) -> bool:
        cohort = self.current()
        return cohort is not None and cohort.digest == digest


class NightOwlPromotionService:
    """Promote one selected, attributed finding without taking any action."""

    def __init__(
        self,
        store: SQLiteNightOwlStore,
        capability_growth: CapabilityGrowthApplicationService,
    ) -> None:
        self._store = store
        self._capability_growth = capability_growth
        self._lock = threading.RLock()

    def promote(
        self,
        finding_id: str,
        *,
        run_id: str,
        lane: str = "expand",
        promotion_reason: str,
        friction_finding_id: str | None = None,
    ) -> ImprovementRecommendation:
        with self._lock:
            return self._promote_locked(
                finding_id,
                run_id=run_id,
                lane=lane,
                promotion_reason=promotion_reason,
                friction_finding_id=friction_finding_id,
            )

    def _promote_locked(
        self,
        finding_id: str,
        *,
        run_id: str,
        lane: str,
        promotion_reason: str,
        friction_finding_id: str | None,
    ) -> ImprovementRecommendation:
        detail = self._store.get_finding_detail(finding_id)
        version = self._store.current_version(detail.identifier)
        run = self._store.get_run(run_id)
        if run.state not in {"completed", "partial"}:
            raise NightOwlConflictError(
                "Only a completed or partial Night Owl run can support promotion."
            )
        if not self._store.run_observed_version(run_id, version.identifier):
            raise NightOwlConflictError(
                "That Night Owl run did not observe the selected finding version."
            )
        sources = self._store.sources_for_version(version.identifier)
        if not sources:
            raise NightOwlConflictError("The selected finding has no source attribution.")
        try:
            analysis = self._store.get_enrichment(version.identifier)
        except NightOwlConflictError:
            analysis = None
        default_area, classification, authority = _PROMOTION_POLICY[detail.category]
        area = default_area
        rationale = (
            detail.summary if analysis is None
            else f"{analysis.summary} {analysis.why_it_matters}"
        )[:1_000]
        source_summary = (
            "Attributed external research only; not CapabilityEvidence. "
            + "; ".join(source.stable_identity for source in sources)
        )[:1_000]
        provenance = ExternalResearchProvenance(
            detail.identifier,
            version.identifier,
            detail.source_identity,
            run.identifier,
            tuple(
                ExternalSourceProvenance(
                    source.kind, source.url, source.stable_identity,
                    source.immutable_identity,
                )
                for source in sources
            ),
            promotion_reason,
            analysis is not None,
            friction_finding_id,
        )
        recommendation = self._capability_growth.promote_external(
            ExternalRecommendationProposal(
                lane,
                area,
                f"Review {detail.title}"[:200],
                rationale,
                source_summary,
                classification,
                authority,
                provenance,
            )
        )
        self._store.record_promotion(
            run_id=run.identifier,
            finding_id=detail.identifier,
            version_id=version.identifier,
            recommendation_id=recommendation.identifier,
        )
        return recommendation
