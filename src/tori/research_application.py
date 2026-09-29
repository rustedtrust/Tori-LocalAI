"""Application service joining Tori-owned Research state to a replaceable worker."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from collections.abc import Callable

from .research import (
    ACTIVE_RESEARCH_STATES,
    MAX_REPORT_LENGTH,
    ResearchAuthority,
    ResearchConflictError,
    ResearchJob,
    ResearchLimits,
    ResearchSource,
    ResearchClaim,
    ResearchEvidence,
    ResearchValidationError,
    SQLiteResearchStore,
)
from .research_worker import (
    ResearchWorkerBinding,
    ResearchWorkerError,
    ResearchWorkerEvent,
    ResearchWorkerPort,
    ResearchWorkerStartRequest,
)


@dataclass(frozen=True, slots=True)
class ResearchWorkspaceStatus:
    availability: str
    code: str
    reason: str
    available: bool
    active: bool
    jobs: tuple[ResearchJob, ...]
    sources: dict[str, tuple[ResearchSource, ...]]
    ledger_status: dict[str, str] = field(default_factory=dict)


class ResearchApplicationService:
    """Own authorization, durable lifecycle, and worker supervision truth."""

    def __init__(self, store: SQLiteResearchStore, worker: ResearchWorkerPort) -> None:
        self.store = store
        self.worker = worker
        self._bindings: dict[str, ResearchWorkerBinding] = {}
        self._lock = threading.RLock()
        self._terminal_observer: Callable[[ResearchJob], None] | None = None

    def set_terminal_observer(self, observer: Callable[[ResearchJob], None] | None) -> None:
        self._terminal_observer = observer

    def recover_startup(self) -> tuple[ResearchJob, ...]:
        """Never claim a pre-restart process survived Tori's ownership boundary."""

        reconciled = []
        for job in self.store.active_jobs():
            reconciled.append(self.store.mark_interrupted(
                job.identifier,
                reason="Tori restarted while the supervised Research Worker was active; the job was not resumed.",
            ))
        return tuple(reconciled)

    def propose(
        self, objective: str, *, limits: ResearchLimits | None = None,
        origin_chat_id: str | None, origin_chat_revision: int | None,
        project_id: str | None = None,
    ) -> ResearchJob:
        return self.store.create_proposal(
            objective, limits=limits or ResearchLimits(), origin_chat_id=origin_chat_id,
            origin_chat_revision=origin_chat_revision, project_id=project_id,
        )

    def authorize_and_start(
        self, job_id: str, *, expected_revision: int,
        confirmation_provenance: str = "explicit_conversation_confirmation",
    ) -> ResearchJob:
        with self._lock:
            readiness = self.worker.readiness()
            if not readiness.available:
                raise ResearchWorkerError(
                    readiness.reason or "The Research Worker is unavailable.", code="worker_unavailable"
                )
            authorized = self.store.authorize(
                job_id, expected_revision=expected_revision, authority=ResearchAuthority(),
                confirmation_provenance=confirmation_provenance,
            )
            starting = self.store.mark_starting(
                job_id, expected_revision=authorized.revision, worker_type=self.worker.identifier
            )
            assert starting.attempt_id is not None
            limits = ResearchLimits(**{key: int(value) for key, value in starting.limits.items()})
            request = ResearchWorkerStartRequest(
                starting.identifier, starting.attempt_id, starting.objective, limits, ResearchAuthority()
            )
            try:
                binding = self.worker.start(request, self._observe)
            except Exception as exc:
                return self.store.record_worker_event(job_id, "failed", {
                    "code": getattr(exc, "code", "worker_start_failed"),
                    "message": "The supervised Research Worker could not be started.",
                })
            self._bindings[job_id] = binding
            # A very small job may finish on the durable owner before this
            # request thread stores its handle. Never retain a stale binding.
            if self.store.get(job_id).state not in ACTIVE_RESEARCH_STATES:
                self._bindings.pop(job_id, None)
        return self.store.get(job_id)

    def cancel(self, job_id: str, *, expected_revision: int) -> ResearchJob:
        with self._lock:
            cancelling = self.store.request_cancel(job_id, expected_revision=expected_revision)
            binding = self._bindings.get(job_id)
            if binding is None:
                return self.store.mark_interrupted(
                    job_id, reason="The Research Worker process was no longer owned by this Tori process."
                )
            try:
                self.worker.cancel(binding)
            except ResearchWorkerError as exc:
                if exc.code == "session_unavailable":
                    # The supervised process is already gone. Cancellation
                    # was recorded first, so no late result may replace it.
                    cancelled = self.store.record_worker_event(job_id, "cancelled", {
                        "code": "cancelled",
                        "message": "Research was cancelled after the supervised session ended.",
                    })
                    if cancelled.state == "cancelled":
                        self.worker.confirm_cancelled(binding)
                        self._bindings.pop(job_id, None)
                    return cancelled
                return self.store.mark_interrupted(
                    job_id, reason="Research cancellation could not reach the supervised worker."
                )
            return cancelling

    def status(self, *, limit: int = 20) -> ResearchWorkspaceStatus:
        readiness = self.worker.readiness()
        jobs = self.store.list_jobs(limit=limit)
        sources = {job.identifier: self.store.sources(job.identifier) for job in jobs}
        return ResearchWorkspaceStatus(
            availability="available" if readiness.available else "unavailable",
            code="ready" if readiness.available else "worker_unavailable",
            reason=("Research Worker is ready." if readiness.available else
                    readiness.reason or "Research Worker is unavailable."),
            available=readiness.available,
            active=any(job.state in ACTIVE_RESEARCH_STATES for job in jobs),
            jobs=jobs,
            sources=sources,
            ledger_status={job.identifier: self.store.ledger_status(job.identifier) for job in jobs},
        )

    def claims(self, job_id: str) -> tuple[ResearchClaim, ...]:
        return self.store.claims(job_id)

    def evidence_for_claim(self, job_id: str, claim_sequence: int) -> tuple[ResearchEvidence, ...]:
        return self.store.evidence_for_claim(job_id, claim_sequence)

    def current_for_chat(self, chat_id: str | None) -> ResearchJob | None:
        candidates = [
            job for job in self.store.list_jobs(limit=100)
            if job.origin_chat_id == chat_id and job.state in ACTIVE_RESEARCH_STATES
        ]
        return candidates[0] if candidates else None

    def _observe(self, event: ResearchWorkerEvent) -> None:
        completion_origin = event.type in {"completed", "completed_with_limits"}
        if event.type == "error":
            event = ResearchWorkerEvent("failed", event.job_id, {
                "code": event.payload.get("code", "worker_error"),
                "message": event.payload.get("message", "The Research Worker reported an error."),
            })
        if event.type in {"completed", "completed_with_limits"}:
            try:
                failure = self._completion_failure(event)
            except Exception:
                # The terminal observer must never let hostile worker JSON
                # escape into the supervisor callback before durable failure.
                failure = "The worker terminal result was malformed."
            if failure is not None:
                event = ResearchWorkerEvent("failed", event.job_id, {
                    "code": "semantic_validation_failed", "message": failure,
                })
            elif event.type == "completed" and any(
                claim["status"] != "supported" for claim in event.payload["validation"]
            ):
                event = ResearchWorkerEvent("completed_with_limits", event.job_id, event.payload)
        job = None
        try:
            job = self.store.record_worker_event(
                event.job_id, event.type, event.payload,
                completion_origin=completion_origin,
            )
        except Exception:
            try:
                preserved = self.store.mark_interrupted(
                    event.job_id,
                    reason="Tori rejected unsafe or malformed Research Worker output.",
                    completion_origin=completion_origin,
                )
                if completion_origin and preserved.state == "cancelling":
                    return
            except Exception:
                pass
        if job is not None and job.state == "cancelling" and event.type in {
            "completed", "completed_with_limits", "failed", "error",
        }:
            return
        if event.type in {"completed", "completed_with_limits", "cancelled", "failed"}:
            with self._lock:
                self._bindings.pop(event.job_id, None)
            observer = self._terminal_observer
            if observer is not None and job is not None:
                try:
                    observer(job)
                except Exception:
                    # Completion truth is already durable. Conversation hand-back
                    # is best-effort presentation and cannot reverse it.
                    pass

    def _completion_failure(self, event: ResearchWorkerEvent) -> str | None:
        payload = event.payload
        report = payload.get("report")
        validation = payload.get("validation_summary")
        if report is not None and (not isinstance(report, str) or len(report) > MAX_REPORT_LENGTH):
            return "The worker narrative is invalid or exceeds its bound."
        if not isinstance(validation, dict) or payload.get("validation_gate_passed") is not True:
            return "The worker did not prove that claim validation governed finalization."
        if "unsupported_presented_as_fact" not in validation:
            return "The worker omitted the unsupported-fact finalization count."
        unsafe = validation["unsupported_presented_as_fact"]
        if isinstance(unsafe, bool) or not isinstance(unsafe, int) or unsafe != 0:
            return "The worker reported unsupported claims presented as established fact."
        fidelity = payload.get("objective_fidelity")
        if (
            not isinstance(fidelity, dict)
            or not isinstance(fidelity.get("status"), str)
            or fidelity["status"] not in {"preserved", "insufficient_evidence"}
        ):
            return "The worker did not prove that the authorized objective remained authoritative."
        recorded = {source.url for source in self.store.sources(event.job_id)}
        used = payload.get("sources")
        if not isinstance(used, list):
            return "The worker did not provide exact source usage provenance."
        for source in used:
            if (
                not isinstance(source, dict)
                or not isinstance(source.get("url"), str)
                or not isinstance(source.get("used_in_report"), bool)
            ):
                return "The worker source usage provenance is malformed."
            if source.get("used_in_report") is True and source["url"] not in recorded:
                return "The report cites a source that Tori did not observe being collected."
        try:
            self.store.validate_terminal_ledger(event.job_id, payload)
        except ResearchValidationError:
            return "The worker did not provide a valid bounded claim/evidence ledger."
        return None

    def close(self) -> None:
        self.worker.close()
