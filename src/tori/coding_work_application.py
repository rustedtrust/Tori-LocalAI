"""Presentation-neutral application use cases for concrete Coding Work."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import secrets

from .coding_work import (
    CodingWork,
    CodingWorkAuthority,
    CodingWorkConflictError,
    CodingWorkDirective,
    CodingWorkRun,
    SQLiteCodingWorkStore,
    TERMINAL_WORK_STATES,
)
from .coding_worker import (
    CodingWorkerAdapter,
    CodingWorkerBinding,
    CodingWorkerError,
    CodingWorkerReconnectRequest,
    CodingWorkerStartRequest,
)
from .coding_work_runtime import CodingWorkRuntimeOwnership


ProjectExists = Callable[[str], bool]


class OwnedCodingWorkApplicationService:
    """Require runtime ownership for every production Coding Work operation."""

    _OPERATIONS = frozenset({
        "create_work", "authorize", "start", "inspect", "observe",
        "submit_follow_up", "request_cancellation", "deliver_directives",
        "prepare_restart_reconciliation", "reconcile", "continue_work",
    })

    def __init__(
        self,
        service: "CodingWorkApplicationService",
        ownership: CodingWorkRuntimeOwnership,
    ) -> None:
        self._service = service
        self._ownership = ownership

    @property
    def adapter(self) -> CodingWorkerAdapter:
        return self._service.adapter

    def __getattr__(self, name: str) -> object:
        if name not in self._OPERATIONS:
            raise AttributeError(name)
        operation = getattr(self._service, name)

        def owned_operation(*args: object, **kwargs: object) -> object:
            with self._ownership.operation():
                return operation(*args, **kwargs)

        return owned_operation


class CodingWorkApplicationService:
    """Apply Tori-owned Coding Work rules through one replaceable adapter."""

    def __init__(
        self,
        store: SQLiteCodingWorkStore,
        adapter: CodingWorkerAdapter,
        *,
        project_exists: ProjectExists | None = None,
        correlation_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._project_exists = project_exists
        self._correlation_factory = correlation_factory or (
            lambda: "launch-" + secrets.token_hex(16)
        )

    @property
    def adapter(self) -> CodingWorkerAdapter:
        return self._adapter

    def create_work(
        self,
        *,
        objective: str,
        workspace_root: Path,
        acceptance_criteria: str | None = None,
        project_id: str | None = None,
        origin_chat_id: str | None = None,
        related_work_id: str | None = None,
    ) -> CodingWork:
        resolved = workspace_root.resolve(strict=True)
        if not resolved.is_dir():
            raise CodingWorkConflictError("The authorized Coding Work workspace is unavailable.")
        if (
            project_id is not None
            and self._project_exists is not None
            and not self._project_exists(project_id)
        ):
            raise CodingWorkConflictError("The selected Project is unavailable.")
        if related_work_id is not None:
            related = self._store.get_work(related_work_id)
            if related.project_id != project_id:
                raise CodingWorkConflictError(
                    "Related Coding Work must retain its Project association."
                )
        return self._store.create_work(
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            workspace_root=str(resolved),
            project_id=project_id,
            origin_chat_id=origin_chat_id,
            related_work_id=related_work_id,
        )

    def authorize(
        self,
        work_id: str,
        *,
        expected_revision: int,
        read_allowed: bool,
        modify_allowed: bool,
        sandboxed_execution_allowed: bool,
        confirmation_provenance: str,
    ) -> CodingWork:
        work = self._store.get_work(work_id)
        authority = CodingWorkAuthority(
            work.workspace_root,
            read_allowed,
            modify_allowed,
            sandboxed_execution_allowed,
        )
        revised, _authorization = self._store.authorize(
            work_id,
            expected_revision=expected_revision,
            authority=authority,
            confirmation_provenance=confirmation_provenance,
        )
        return revised

    def start(self, work_id: str, *, expected_revision: int) -> CodingWork:
        work, run = self._store.create_run(
            work_id,
            expected_revision=expected_revision,
            adapter_id=self._adapter.identifier,
            adapter_version=self._adapter.contract_version,
            launch_correlation_id=self._correlation_factory(),
        )
        authorization = self._store.get_authorization(run.authorization_id)
        authority = CodingWorkAuthority.from_document(authorization.authority)
        binding: CodingWorkerBinding | None = None
        try:
            binding = self._adapter.start(CodingWorkerStartRequest(
                work.identifier,
                run.identifier,
                work.objective,
                work.acceptance_criteria,
                authority,
                run.launch_correlation_id,
            ))
            observation = self._adapter.inspect(binding)
        except CodingWorkerError as exc:
            if binding is not None:
                try:
                    self._adapter.close(binding)
                except CodingWorkerError:
                    pass
            message = str(exc).strip()[:1_000] or "The Coding Work worker could not start."
            return self._store.transition_work(
                work.identifier,
                expected_revision=work.revision,
                target_state="failed",
                event_kind="failed",
                run_id=run.identifier,
                payload={"failure_code": exc.code, "failure_message": message},
                result={
                    "summary": message,
                    "changed_paths": [],
                    "verification": [],
                    "artifacts": [],
                },
                failure_code=exc.code,
                failure_message=message,
            )
        if observation.found and observation.session_id:
            run = self._store.bind_session(
                run.identifier,
                expected_revision=run.revision,
                harness_session_id=observation.session_id,
                event_cursor=observation.event_cursor,
                observed_state=(
                    "starting" if observation.state == "starting" else "running"
                ),
            )
        return self.observe(work.identifier)

    def inspect(self, work_id: str) -> CodingWork:
        work = self._store.get_work(work_id)
        if work.current_run_id is None:
            return work
        run = self._store.get_run(work.current_run_id)
        observation = self._adapter.inspect(self._binding(run))
        if not observation.found:
            return work
        return self.observe(work_id)

    def observe(self, work_id: str) -> CodingWork:
        work = self._store.get_work(work_id)
        if work.current_run_id is None:
            return work
        run = self._store.get_run(work.current_run_id)
        binding = self._binding(run)
        try:
            events = self._adapter.attach(
                binding, after_sequence=run.last_event_sequence
            )
        except CodingWorkerError as exc:
            if exc.code == "session_missing":
                return work
            raise
        for event in events:
            work = self._store.get_work(work_id)
            run = self._store.get_run(work.current_run_id or run.identifier)
            if event.kind == "progress":
                work = self._store.update_progress(
                    work.identifier,
                    expected_revision=work.revision,
                    run_id=run.identifier,
                    adapter_event_id=event.identifier,
                    adapter_sequence=event.sequence,
                    summary=event.payload.get("summary"),
                    changed_paths=event.payload.get("changed_paths", ()),  # type: ignore[arg-type]
                    verification=event.payload.get("verification"),
                    event_cursor=str(event.sequence),
                    occurred_at_utc=event.occurred_at_utc,
                )
                continue
            if event.kind not in {
                "session_confirmed", "waiting", "verification",
                "completed", "failed", "cancelled",
            }:
                raise CodingWorkerError(
                    "The worker emitted an unsupported semantic event.",
                    code="unsupported_event",
                )
            evidence = None
            if event.kind in TERMINAL_WORK_STATES:
                evidence = self._adapter.collect_evidence(binding).document()
            work = self._store.apply_adapter_event(
                work.identifier,
                run_id=run.identifier,
                adapter_event_id=event.identifier,
                adapter_sequence=event.sequence,
                kind=event.kind,
                payload=event.payload,
                event_cursor=str(event.sequence),
                occurred_at_utc=event.occurred_at_utc,
                result=evidence,
            )
        return self._store.get_work(work_id)

    def submit_follow_up(
        self,
        work_id: str,
        *,
        expected_revision: int,
        instruction: str,
        source_chat_id: str | None = None,
    ) -> CodingWorkDirective:
        _work, directive = self._store.queue_directive(
            work_id,
            expected_revision=expected_revision,
            kind="instruction",
            instruction=instruction,
            source_chat_id=source_chat_id,
        )
        return directive

    def request_cancellation(
        self,
        work_id: str,
        *,
        expected_revision: int,
        source_chat_id: str | None = None,
    ) -> CodingWorkDirective:
        _work, directive = self._store.queue_directive(
            work_id,
            expected_revision=expected_revision,
            kind="cancel",
            source_chat_id=source_chat_id,
        )
        return directive

    def deliver_directives(self, work_id: str) -> tuple[CodingWorkDirective, ...]:
        delivered: list[CodingWorkDirective] = []
        for pending in self._store.pending_directives(work_id):
            directive = self._store.claim_directive(pending.identifier)
            run = self._store.get_run(directive.run_id)
            binding = self._binding(run)
            try:
                receipt = (
                    self._adapter.cancel(binding, directive)
                    if directive.kind == "cancel"
                    else self._adapter.submit_directive(binding, directive)
                )
            except CodingWorkerError as exc:
                delivered.append(self._store.finish_directive(
                    directive.identifier,
                    expected_revision=directive.revision,
                    failure_code=exc.code,
                ))
            else:
                delivered.append(self._store.finish_directive(
                    directive.identifier,
                    expected_revision=directive.revision,
                    receipt=receipt.receipt,
                ))
        return tuple(delivered)

    def prepare_restart_reconciliation(self) -> tuple[CodingWork, ...]:
        self._store.mark_reconciling()
        # A prior startup can have durably marked work before an external
        # prerequisite failed.  Those rows still require reconciliation on the
        # next healthy start; limiting the pass to newly changed rows strands
        # them in ``reconciling`` forever.
        return self._store.list_work(("reconciling",))

    def reconcile(self, work_id: str) -> CodingWork:
        work = self._store.get_work(work_id)
        if work.state != "reconciling" or work.current_run_id is None:
            raise CodingWorkConflictError("The Coding Work item is not awaiting reconciliation.")
        run = self._store.get_run(work.current_run_id)
        legacy_completion = self._legacy_model_turn_completion(work, run)
        if legacy_completion is not None:
            return self._store.apply_adapter_event(
                work.identifier,
                run_id=run.identifier,
                adapter_event_id="reconciled-model-turn-complete",
                adapter_sequence=run.last_event_sequence + 1,
                kind="completed",
                payload={"evidence": legacy_completion},
                event_cursor=str(run.last_event_sequence + 1),
                occurred_at_utc=work.updated_at_utc,
                result=legacy_completion,
            )
        binding = self._binding(run)
        authorization = self._store.get_authorization(run.authorization_id)
        authority = CodingWorkAuthority.from_document(authorization.authority)
        try:
            workspace = Path(authority.workspace_root).resolve(strict=True)
        except OSError:
            workspace = None
        if workspace is None or not workspace.is_dir():
            return self._store.mark_session_missing(
                work.identifier,
                expected_revision=work.revision,
                run_id=run.identifier,
                failure_code="workspace_missing",
                failure_message=(
                    "The authorized Coding Work workspace no longer exists; "
                    "the prior run was not resumed."
                ),
            )
        observation = self._adapter.reconnect(
            CodingWorkerReconnectRequest(
                work.identifier,
                run.identifier,
                work.objective,
                work.acceptance_criteria,
                authority,
                run.last_event_sequence,
                run.reconciliation_prior_state,
            ),
            binding,
        )
        if not observation.found:
            return self._store.mark_session_missing(
                work.identifier,
                expected_revision=work.revision,
                run_id=run.identifier,
            )
        observed = self.observe(work.identifier)
        if observed.state != "reconciling":
            return observed
        if observation.session_id is None or observation.state is None:
            return self._store.mark_session_missing(
                work.identifier,
                expected_revision=work.revision,
                run_id=run.identifier,
            )
        return self._store.restore_observed_session(
            work.identifier,
            expected_revision=work.revision,
            run_id=run.identifier,
            harness_session_id=observation.session_id,
            observed_state=observation.state,
            event_cursor=observation.event_cursor,
        )

    def _legacy_model_turn_completion(
        self, work: CodingWork, run: CodingWorkRun
    ) -> dict[str, object] | None:
        """Recognize the exact pre-fix durable proof of an ended bounded turn."""

        if run.reconciliation_prior_state != "waiting" or work.progress is None:
            return None
        events = tuple(
            event for event in self._store.events(work.identifier)
            if event.run_id == run.identifier
        )
        if not events:
            return None
        turn_event = next(
            (event for event in reversed(events) if event.kind != "reconciling"),
            None,
        )
        progress = work.progress
        if (
            turn_event is None
            or turn_event.kind != "waiting"
            or turn_event.payload.get("reason") != "model_turn_complete"
            or progress.get("verification") != "workspace_snapshot_observed"
            or not isinstance(progress.get("summary"), str)
            or not progress.get("summary")
        ):
            return None
        changed_paths = progress.get("changed_paths", [])
        if not isinstance(changed_paths, list) or not all(
            isinstance(path, str) for path in changed_paths
        ):
            return None
        return {
            "summary": progress["summary"],
            "changed_paths": changed_paths,
            "verification": [{
                "kind": "legacy_model_turn",
                "status": "completed",
                "source": "durable_model_turn_complete",
            }],
            "artifacts": [],
        }

    def continue_work(
        self,
        work_id: str,
        *,
        expected_revision: int,
        read_allowed: bool,
        modify_allowed: bool,
        sandboxed_execution_allowed: bool,
        confirmation_provenance: str,
    ) -> CodingWork:
        continued = self._store.continue_terminal(
            work_id, expected_revision=expected_revision
        )
        authorized = self.authorize(
            continued.identifier,
            expected_revision=continued.revision,
            read_allowed=read_allowed,
            modify_allowed=modify_allowed,
            sandboxed_execution_allowed=sandboxed_execution_allowed,
            confirmation_provenance=confirmation_provenance,
        )
        return self.start(authorized.identifier, expected_revision=authorized.revision)

    @staticmethod
    def _binding(run: CodingWorkRun) -> CodingWorkerBinding:
        return CodingWorkerBinding(
            run.adapter_id,
            run.adapter_version,
            run.launch_correlation_id,
            run.harness_session_id,
        )
