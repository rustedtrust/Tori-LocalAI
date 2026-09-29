"""Bounded conversational proposals and receipts for Research Worker V1."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time

from .research import ACTIVE_RESEARCH_STATES, ResearchJob, ResearchLimits
from .research_application import ResearchApplicationService


RESEARCH_CONFIRMATION_SECONDS = 10 * 60
_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:do\s+)?(?:deep\s+research|research|investigate)\s+(?:on\s+)?(?P<objective>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ResearchIntent:
    kind: str
    objective: str | None = None


@dataclass(frozen=True, slots=True)
class ResearchProposal:
    job_id: str
    job_revision: int
    objective: str
    origin_chat_id: str
    origin_chat_revision: int
    expires_at: float
    limits: ResearchLimits

    def document(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_revision": self.job_revision,
            "objective": self.objective,
            "sources": (
                "Unauthenticated GitHub and Hugging Face primary discovery, "
                "with SearXNG broad-web secondary discovery"
            ),
            "private_tori_data": "Not shared",
            "network": "Public HTTP/HTTPS through Tori's isolated egress broker",
            "limits": self.limits.document(),
        }


class ResearchConversationService:
    def __init__(self, application: ResearchApplicationService, *, clock=time.monotonic) -> None:
        self.application = application
        self.clock = clock

    def recognize(self, text: str) -> ResearchIntent | None:
        normalized = " ".join(text.lower().split())
        if normalized in {
            "how is the research going?", "how is the research going",
            "research status", "what has the research found so far?",
            "what has the research found so far", "how many sources has it checked?",
        }:
            return ResearchIntent("status")
        if normalized in {"stop the research", "cancel the research", "cancel research", "stop research"}:
            return ResearchIntent("cancel")
        match = _REQUEST.fullmatch(text)
        if match is None:
            return None
        objective = match.group("objective").strip()
        if len(objective) < 12:
            return None
        return ResearchIntent("request", objective)

    def propose(
        self, objective: str, *, origin_chat_id: str,
        origin_chat_revision: int, project_id: str | None = None,
    ) -> ResearchProposal:
        limits = ResearchLimits()
        job = self.application.propose(
            objective, limits=limits, origin_chat_id=origin_chat_id,
            origin_chat_revision=origin_chat_revision, project_id=project_id,
        )
        return ResearchProposal(
            job.identifier, job.revision, job.objective, origin_chat_id,
            origin_chat_revision, self.clock() + RESEARCH_CONFIRMATION_SECONDS, limits,
        )

    def status_message(self, *, origin_chat_id: str | None) -> str:
        job = self.application.current_for_chat(origin_chat_id)
        if job is None:
            recent = [
                item for item in self.application.store.list_jobs(limit=20)
                if item.origin_chat_id == origin_chat_id
            ]
            if not recent:
                return "There is no Research Job for this conversation."
            job = recent[0]
        sources = self.application.store.sources(job.identifier)
        primary = sum(1 for source in sources if source.source_type == "primary")
        if job.state in ACTIVE_RESEARCH_STATES:
            detail = job.progress_message or "The worker has not reported progress yet."
            return (
                f"Research is {job.state}. Current phase: {job.phase or 'starting'}. "
                f"It has recorded {len(sources)} sources, including {primary} primary sources. {detail}"
            )
        if job.state in {"completed", "completed_with_limits"}:
            qualifier = " within its limits" if job.state == "completed" else " with limitations"
            return f"Research completed{qualifier} with {len(sources)} sources, including {primary} primary sources."
        return f"Research ended as {job.state}. {job.failure_message or job.progress_message or ''}".strip()

    def result_message(self, job: ResearchJob) -> str:
        if job.state in {"queued", "starting", "running"}:
            return (
                "The bounded Research Job is authorized and has started. "
                "Only the public objective is disclosed; private Tori data is not shared."
            )
        return self.status_message(origin_chat_id=job.origin_chat_id)


def proposal_message(proposal: ResearchProposal) -> str:
    limits = proposal.limits
    return (
        "I can run a deeper research job on that.\n\n"
        f"Objective:\n{proposal.objective}\n\n"
        "Sources:\nUnauthenticated GitHub and Hugging Face primary discovery, "
        "with SearXNG broad-web secondary discovery.\n\n"
        "Private Tori data:\nNot shared.\n\n"
        "Network:\nPublic HTTP/HTTPS through Tori's isolated egress broker; local Ollama only.\n\n"
        f"Limits:\nUp to {limits.maximum_duration_seconds // 60} minutes, "
        f"{limits.maximum_search_queries} searches, and {limits.maximum_sources_fetched} fetched sources."
    )
