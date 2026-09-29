"""Read-only authoritative source projections for Companion Attention V2."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from typing import Protocol

from .companion_initiative import AttentionSignal
from .operator_observability import operator_failure


class ResearchSource(Protocol):
    def status(self) -> object: ...


class CodingSource(Protocol):
    def status(self, work_id: str | None = None, *, project_id: str | None = None) -> object: ...


class NightOwlSource(Protocol):
    def list_finding_details(self, *, limit: int = 50) -> tuple[object, ...]: ...


class ScheduledSource(Protocol):
    def list_definitions(self) -> tuple[object, ...]: ...
    def list_runs(self, *, limit: int = 100) -> tuple[object, ...]: ...


class ProjectSource(Protocol):
    def list_projects(self) -> tuple[object, ...]: ...


class CompanionAttentionSources:
    """Convert bounded source-owned lifecycle state into deterministic signals."""

    def __init__(
        self,
        *,
        research: ResearchSource | None = None,
        coding: CodingSource | None = None,
        night_owl: NightOwlSource | None = None,
        scheduled: ScheduledSource | None = None,
        projects: ProjectSource | None = None,
    ) -> None:
        self._research = research
        self._coding = coding
        self._night_owl = night_owl
        self._scheduled = scheduled
        self._projects = projects

    def snapshots(self) -> tuple[tuple[str, tuple[AttentionSignal, ...]], ...]:
        try:
            projects = self._active_projects()
        except Exception as exc:
            operator_failure(
                "companion_attention.projects.failed", exc,
                code=getattr(exc, "code", "attention_source_unavailable"),
                origin="local_application", category="projects",
            )
            projects = {}
        readers: tuple[tuple[str, Callable[[dict[str, str]], tuple[AttentionSignal, ...]]], ...] = (
            ("research", self._research_signals),
            ("coding_work", self._coding_signals),
            ("night_owl", self._night_owl_signals),
            ("scheduled_work", self._scheduled_signals),
        )
        result = []
        for source, reader in readers:
            if getattr(self, f"_{'coding' if source == 'coding_work' else 'scheduled' if source == 'scheduled_work' else source}") is None:
                continue
            try:
                result.append((source, reader(projects)))
            except Exception as exc:
                operator_failure(
                    "companion_attention.source.failed", exc,
                    code=getattr(exc, "code", "attention_source_unavailable"),
                    origin="local_application", category=source,
                )
        return tuple(result)

    def _active_projects(self) -> dict[str, str]:
        if self._projects is None:
            return {}
        return {
            item.identifier: item.title
            for item in self._projects.list_projects()
            if item.status == "active"
        }

    def _research_signals(self, projects: dict[str, str]) -> tuple[AttentionSignal, ...]:
        assert self._research is not None
        status = self._research.status()
        sources = getattr(status, "sources", {})
        result = []
        for job in status.jobs:
            if job.state not in {"completed", "completed_with_limits", "failed", "interrupted"}:
                continue
            source_count = len(sources.get(job.identifier, ()))
            if job.state in {"failed", "interrupted"}:
                attention_class, delivery = "needs_attention", "conversational"
                summary = "Requested research did not complete and may need a decision."
            elif job.state == "completed_with_limits":
                attention_class, delivery = "worth_reviewing", "gentle"
                summary = f"Research completed with limits using {source_count} source{'s' if source_count != 1 else ''}."
            else:
                attention_class, delivery = "worth_reviewing", "silent"
                summary = f"Research completed using {source_count} source{'s' if source_count != 1 else ''}."
            summary, delivery = _project_context(summary, delivery, job.project_id, projects)
            material = _material(job.state, source_count, job.failure_code, job.project_id)
            result.append(AttentionSignal(
                "research", job.identifier, f"research_{job.state}",
                _bounded(job.objective, 200), _bounded(summary, 500), attention_class,
                delivery, job.revision, material, _timestamp(job.updated_at_utc),
                job.project_id,
            ))
        return tuple(result)

    def _coding_signals(self, projects: dict[str, str]) -> tuple[AttentionSignal, ...]:
        assert self._coding is not None
        result = []
        for work in self._coding.status().work:
            if work.state not in {"completed", "failed", "waiting"}:
                continue
            if work.state == "failed":
                attention_class, delivery = "needs_attention", "conversational"
                summary = work.result_summary or "Delegated Work failed and may need a decision."
            elif work.state == "waiting" and work.needs_authorization:
                attention_class, delivery = "needs_attention", "conversational"
                summary = "Delegated Work is waiting for a user decision."
            elif work.state == "waiting":
                attention_class, delivery = "worth_reviewing", "gentle"
                summary = work.latest_activity or "Delegated Work is waiting for follow-up."
            else:
                attention_class, delivery = "worth_reviewing", "silent"
                summary = work.result_summary or "Delegated Work completed and is ready to review."
            summary, delivery = _project_context(summary, delivery, work.project_id, projects)
            material = _material(
                work.state, work.needs_authorization, work.result_summary,
                work.acceptance_status, work.project_id,
            )
            result.append(AttentionSignal(
                "coding_work", work.identifier, f"coding_{work.state}",
                _bounded(work.objective, 200), _bounded(summary, 500), attention_class,
                delivery, work.revision, material, _timestamp(work.updated_at_utc),
                work.project_id,
            ))
        return tuple(result)

    def _night_owl_signals(self, projects: dict[str, str]) -> tuple[AttentionSignal, ...]:
        del projects
        assert self._night_owl is not None
        result = []
        for finding in self._night_owl.list_finding_details(limit=50):
            if finding.state != "new":
                continue
            result.append(AttentionSignal(
                "night_owl", finding.identifier, "night_owl_finding",
                _bounded(finding.title, 200), _bounded(finding.summary, 500),
                "worth_reviewing", "gentle", finding.revision,
                finding.current_fingerprint, _timestamp(finding.last_seen_at), None,
            ))
        return tuple(result)

    def _scheduled_signals(self, projects: dict[str, str]) -> tuple[AttentionSignal, ...]:
        del projects
        assert self._scheduled is not None
        definitions = {item.identifier: item for item in self._scheduled.list_definitions()}
        result = []
        for run in self._scheduled.list_runs(limit=100):
            if run.status not in {"failed", "interrupted", "skipped"}:
                continue
            if run.status == "skipped" and run.missed_occurrence_count < 1:
                continue
            title = getattr(definitions.get(run.job_id), "title", "Scheduled work")
            attention_class = "needs_attention"
            delivery = "conversational" if run.status in {"failed", "interrupted"} else "gentle"
            summary = (
                "Scheduled work was interrupted and its outcome is uncertain."
                if run.status == "interrupted"
                else "Scheduled work failed and may need a decision."
                if run.status == "failed"
                else f"Scheduled work missed {run.missed_occurrence_count} occurrence{'s' if run.missed_occurrence_count != 1 else ''}."
            )
            result.append(AttentionSignal(
                "scheduled_work", run.identifier, f"scheduled_{run.status}",
                _bounded(title, 200), summary, attention_class, delivery,
                run.revision, _material(run.status, run.failure_code,
                                        run.missed_occurrence_count,
                                        run.missed_first_key, run.missed_last_key),
                _timestamp(run.finished_at_utc or run.claim_at_utc), None,
            ))
        return tuple(result)


def _project_context(
    summary: str, delivery: str, project_id: str | None, projects: dict[str, str]
) -> tuple[str, str]:
    title = projects.get(project_id or "")
    if title is None:
        return summary, delivery
    elevated = "gentle" if delivery == "silent" else delivery
    return f"{summary} Related to active Project {title}.", elevated


def _material(*values: object) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Attention source timestamp is invalid.")
    return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)


def _bounded(value: str, maximum: int) -> str:
    text = " ".join(str(value).split())
    return text[:maximum].rstrip() or "Attention item"
