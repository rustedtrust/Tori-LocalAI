"""Application-owned lifecycle and presentation boundary for Coding Work."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import http.client
import json
import logging
import os
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from .coding_work import (
    CodingWork,
    CodingWorkResumeMetadata,
    CodingWorkError,
    CodingWorkEvent,
    SQLiteCodingWorkStore,
    TERMINAL_WORK_STATES,
)
from .coding_work_application import (
    CodingWorkApplicationService,
    OwnedCodingWorkApplicationService,
)
from .coding_work_opencode import OpenCodeAdapterSettings, OpenCodeCodingWorkerAdapter
from .coding_work_provider_transport import OpenAICompatibleInferencePolicy
from .coding_work_runtime import (
    CodingWorkOwnershipUnavailableError,
    CodingWorkProductionSettings,
    CodingWorkReadiness,
    CodingWorkReadinessEvaluator,
    CodingWorkRuntimeError,
    CodingWorkRuntimeLayout,
    CodingWorkRuntimeOwnership,
)
from .coding_work_supervisor import BubblewrapCodingWorkSandbox
from .coding_worker import CodingWorkerAdapter, CodingWorkerError


LOGGER = logging.getLogger(__name__)
ACTIVE_WORK_STATES: Final = frozenset({
    "starting", "running", "waiting", "cancelling", "reconciling",
})
MAX_STATUS_ITEMS: Final = 100
MAX_STATUS_EVENTS: Final = 10
MAX_STATUS_CHANGED_PATHS: Final = 100
MAX_STATUS_TEXT: Final = 1_000


class CodingWorkIntegrationError(RuntimeError):
    """Safe application-integration failure."""


class CodingWorkControlUnsupportedError(CodingWorkIntegrationError):
    """Raised when a requested user control has no truthful domain meaning."""


@dataclass(frozen=True, slots=True)
class CodingWorkActivity:
    kind: str
    summary: str
    occurred_at_utc: str


@dataclass(frozen=True, slots=True)
class CodingWorkStatusItem:
    identifier: str
    revision: int
    project_id: str | None
    objective: str
    workspace_root: str
    state: str
    needs_authorization: bool
    worker_state: str
    started_at_utc: str | None
    updated_at_utc: str
    latest_activity: str | None
    latest_activity_at_utc: str | None
    changed_paths: tuple[str, ...]
    result_summary: str | None
    recent_activity: tuple[CodingWorkActivity, ...]
    can_follow_up: bool
    can_cancel: bool
    can_continue: bool
    can_pause: bool = False
    can_resume: bool = False
    origin_chat_id: str | None = None
    acceptance_criteria: str | None = None
    created_at_utc: str | None = None
    terminal_at_utc: str | None = None
    verification: tuple[Mapping[str, object], ...] = ()
    artifacts: tuple[Mapping[str, object], ...] = ()
    related_work_id: str | None = None
    acceptance_status: str = "not_specified"


@dataclass(frozen=True, slots=True)
class CodingWorkStatus:
    availability: str
    code: str
    reason: str
    available: bool
    reconciling: bool
    active: bool
    current_work_id: str | None
    work: tuple[CodingWorkStatusItem, ...]


AdapterFactory = Callable[[CodingWorkProductionSettings], CodingWorkerAdapter]
OwnershipFactory = Callable[[CodingWorkRuntimeLayout], CodingWorkRuntimeOwnership]
ReadinessFactory = Callable[
    [CodingWorkProductionSettings, CodingWorkRuntimeOwnership], CodingWorkReadinessEvaluator
]
StoreFactory = Callable[[Path], SQLiteCodingWorkStore]


class CodingWorkRuntime:
    """Own one process-local composition of the production Coding Work capability."""

    def __init__(self, settings: CodingWorkProductionSettings | None) -> None:
        self.settings = settings
        self._readiness = CodingWorkReadiness(
            "unavailable", "configuration_missing",
            "Coding Work is not administrator-configured.",
        )
        self._availability = "not_configured"
        self._ownership: CodingWorkRuntimeOwnership | None = None
        self._store: SQLiteCodingWorkStore | None = None
        self._service: OwnedCodingWorkApplicationService | None = None
        self._adapter: CodingWorkerAdapter | None = None
        self._admission_open = False
        self._closed = False

    @classmethod
    def start(
        cls,
        settings: CodingWorkProductionSettings | None,
        *,
        adapter_factory: AdapterFactory | None = None,
        ownership_factory: OwnershipFactory = CodingWorkRuntimeOwnership,
        readiness_factory: ReadinessFactory | None = None,
        provider_model_available: Callable[[CodingWorkProductionSettings], bool] | None = None,
        store_factory: StoreFactory = SQLiteCodingWorkStore,
    ) -> "CodingWorkRuntime":
        runtime = cls(settings)
        if settings is None:
            return runtime
        layout = CodingWorkRuntimeLayout(settings.runtime_root.parent)
        if not os.path.lexists(layout.root):
            runtime._readiness = CodingWorkReadiness(
                "uninitialized", "canonical_root_absent",
                "Canonical Coding Work state has not been initialized.",
            )
            runtime._availability = "uninitialized"
            return runtime
        ownership = ownership_factory(layout)
        runtime._ownership = ownership
        evaluator_factory = readiness_factory or (
            lambda configured, owner: CodingWorkReadinessEvaluator(
                configured,
                ownership=owner,
                provider_model_available=(
                    provider_model_available or _provider_model_available
                ),
            )
        )
        try:
            if not ownership.acquire():
                runtime._readiness = CodingWorkReadiness(
                    "unavailable", "supervisor_ownership_unavailable",
                    "Another Tori process owns Coding Work supervision.",
                )
                runtime._availability = "unavailable"
                return runtime
            evaluator = evaluator_factory(settings, ownership)
            readiness = evaluator.evaluate()
            if not readiness.available:
                runtime._readiness = readiness
                runtime._availability = readiness.state
                ownership.release()
                return runtime
            store = store_factory(layout.database)
            store.revision()
            runtime._store = store
            adapter = (adapter_factory or _production_adapter)(settings)
            runtime._adapter = adapter
            runtime._service = OwnedCodingWorkApplicationService(
                CodingWorkApplicationService(store, adapter), ownership
            )
            runtime._readiness = CodingWorkReadiness(
                "reconciling", "reconciliation_pending",
                "Coding Work restart reconciliation is in progress.",
            )
            runtime._availability = "reconciling"
            for work in runtime._service.prepare_restart_reconciliation():
                runtime._service.reconcile(work.identifier)
            work_states = tuple(item.state for item in store.list_work())
            readiness = evaluator.evaluate(work_states=work_states)
            if not readiness.available:
                runtime._readiness = readiness
                runtime._availability = readiness.state
                runtime._release_failed_startup()
                return runtime
            runtime._readiness = readiness
            runtime._availability = "available"
            runtime._admission_open = True
            return runtime
        except (CodingWorkRuntimeError, CodingWorkError, CodingWorkerError, OSError) as exc:
            LOGGER.error("Coding Work application startup failed safely: %s", exc)
            runtime._readiness = CodingWorkReadiness(
                "unavailable", getattr(exc, "code", "startup_failed"),
                "Coding Work could not start safely; other Tori capabilities remain available.",
            )
            runtime._availability = "unavailable"
            runtime._release_failed_startup()
            return runtime
        except BaseException:
            runtime._release_failed_startup()
            raise

    @property
    def readiness(self) -> CodingWorkReadiness:
        return self._readiness

    @property
    def admission_open(self) -> bool:
        return self._admission_open and not self._closed

    def resume_metadata(self) -> tuple[CodingWorkResumeMetadata, ...]:
        """Project only content-free waiting-work evidence."""

        return () if self._store is None else self._store.list_resume_metadata()

    def status(
        self, work_id: str | None = None, *, project_id: str | None = None
    ) -> CodingWorkStatus:
        store = self._store
        selected: tuple[CodingWork, ...] = ()
        if store is not None:
            if work_id is not None:
                candidate = store.get_work(work_id)
                selected = (candidate,)
            else:
                selected = store.list_work()[:MAX_STATUS_ITEMS]
            if project_id is not None:
                selected = tuple(item for item in selected if item.project_id == project_id)
            if self._service is not None and self.admission_open:
                refreshed: list[CodingWork] = []
                for item in selected:
                    refreshed.append(
                        self._service.inspect(item.identifier)
                        if item.state in ACTIVE_WORK_STATES
                        else item
                    )
                selected = tuple(refreshed)
        projected = tuple(self._project(store, item) for item in selected) if store else ()
        current = next(
            (item for item in selected if item.state in ACTIVE_WORK_STATES),
            None,
        )
        return CodingWorkStatus(
            self._availability,
            self._readiness.code,
            self._readiness.reason,
            self._readiness.available and self.admission_open,
            self._availability == "reconciling",
            current is not None,
            current.identifier if current is not None else None,
            projected,
        )

    def create_work(self, **arguments: object) -> CodingWork:
        return self._mutate("create_work", **arguments)  # type: ignore[return-value]

    def authorize(self, work_id: str, **arguments: object) -> CodingWork:
        return self._mutate("authorize", work_id, **arguments)  # type: ignore[return-value]

    def start_work(self, work_id: str, *, expected_revision: int) -> CodingWork:
        return self._mutate("start", work_id, expected_revision=expected_revision)  # type: ignore[return-value]

    def refresh(self, work_id: str) -> CodingWorkStatusItem:
        self._mutate("inspect", work_id)
        return self.status(work_id).work[0]

    def follow_up(
        self,
        work_id: str,
        *,
        expected_revision: int,
        instruction: str,
        source_chat_id: str | None = None,
    ) -> CodingWorkStatusItem:
        self._mutate(
            "submit_follow_up", work_id, expected_revision=expected_revision,
            instruction=instruction, source_chat_id=source_chat_id,
        )
        self._mutate("deliver_directives", work_id)
        return self.status(work_id).work[0]

    def cancel(
        self,
        work_id: str,
        *,
        expected_revision: int,
        source_chat_id: str | None = None,
    ) -> CodingWorkStatusItem:
        self._mutate(
            "request_cancellation", work_id, expected_revision=expected_revision,
            source_chat_id=source_chat_id,
        )
        self._mutate("deliver_directives", work_id)
        self._mutate("observe", work_id)
        return self.status(work_id).work[0]

    def continue_work(self, work_id: str, **arguments: object) -> CodingWork:
        return self._mutate("continue_work", work_id, **arguments)  # type: ignore[return-value]

    def pause(self, _work_id: str) -> None:
        raise CodingWorkControlUnsupportedError(
            "Coding Work pause is not supported: schema 1 has no durable paused state, "
            "and waiting or cancellation cannot truthfully substitute for pause."
        )

    def resume(self, _work_id: str) -> None:
        raise CodingWorkControlUnsupportedError(
            "Coding Work resume is not supported because schema 1 has no paused state."
        )

    def shutdown(self) -> None:
        if self._closed:
            return
        self._admission_open = False
        ownership = self._ownership
        adapter = self._adapter
        try:
            if ownership is not None and ownership.owned:
                ownership.shutdown(
                    stop_owned_workers=(
                        getattr(adapter, "shutdown") if adapter is not None
                        and callable(getattr(adapter, "shutdown", None)) else lambda: None
                    ),
                    release_provider_transport=lambda: None,
                )
            elif adapter is not None and callable(getattr(adapter, "shutdown", None)):
                getattr(adapter, "shutdown")()
        finally:
            self._closed = True
            self._service = None
            self._adapter = None
            if self._availability in {"available", "reconciling"}:
                self._availability = "unavailable"
                self._readiness = CodingWorkReadiness(
                    "unavailable", "runtime_stopped",
                    "Coding Work application ownership has stopped.",
                )

    @contextmanager
    def backup_guard(self, *, project_root: Path | None = None) -> Iterator[None]:
        """Quiesce configured or preserved Coding Work state for one backup."""

        from .backups import CodingWorkBackupCoordinator, BackupBusyError

        settings = self.settings
        if settings is not None:
            layout = CodingWorkRuntimeLayout(settings.runtime_root.parent)
        elif project_root is not None:
            layout = CodingWorkRuntimeLayout(Path(project_root) / "runtime")
        else:
            raise BackupBusyError(
                "Coding Work state cannot be coordinated without its project root."
            )
        if not os.path.lexists(layout.root):
            yield
            return

        ownership = self._ownership
        acquired_here = ownership is None or not ownership.owned
        if acquired_here:
            ownership = CodingWorkRuntimeOwnership(layout)
            if not ownership.acquire():
                raise BackupBusyError(
                    "Another Tori process owns Coding Work supervision."
                )
        assert ownership is not None
        try:
            store = self._store or SQLiteCodingWorkStore(layout.database)
            adapter = self._adapter

            def live_writer() -> bool:
                if adapter is None:
                    return False
                probe = getattr(adapter, "has_live_writer", None)
                return bool(probe()) if callable(probe) else True

            coordinator = CodingWorkBackupCoordinator(
                layout=layout,
                ownership=ownership,
                store=store,
                live_opencode_writer=live_writer,
            )
            with coordinator.snapshot_guard():
                yield
        finally:
            if acquired_here:
                ownership.release()

    def _mutate(self, operation: str, *args: object, **kwargs: object) -> object:
        if not self.admission_open or self._service is None:
            raise CodingWorkOwnershipUnavailableError(
                "Coding Work is not available for mutation in this Tori process."
            )
        return getattr(self._service, operation)(*args, **kwargs)

    def _release_failed_startup(self) -> None:
        self._admission_open = False
        adapter, ownership = self._adapter, self._ownership
        try:
            if adapter is not None and callable(getattr(adapter, "shutdown", None)):
                getattr(adapter, "shutdown")()
        finally:
            if ownership is not None:
                ownership.release()
        self._adapter = None
        self._service = None

    @staticmethod
    def _project(store: SQLiteCodingWorkStore, work: CodingWork) -> CodingWorkStatusItem:
        history = store.events(work.identifier)
        events = history[-MAX_STATUS_EVENTS:]
        activities = tuple(
            CodingWorkActivity(event.kind, _event_summary(event), event.occurred_at_utc)
            for event in events
        )
        progress = work.progress or {}
        result = work.result or {}
        paths = _changed_paths(progress, result)
        latest = activities[-1] if activities else None
        created = next((event for event in history if event.kind == "created"), None)
        related_work_id = (
            _coding_work_identifier(created.payload.get("related_work_id"))
            if created is not None else None
        )
        verification = _bounded_evidence(result.get("verification"), kind="verification")
        artifacts = _bounded_evidence(result.get("artifacts"), kind="artifact")
        acceptance_status = (
            "not_specified"
            if work.acceptance_criteria is None
            else "not_completed"
            if work.state in {"failed", "cancelled"}
            else "not_independently_verified"
            if work.state == "completed"
            else "pending"
        )
        needs_authority = work.state == "awaiting_authorization" or (
            latest is not None and latest.kind == "waiting"
            and latest.summary == "Authority is required."
        )
        return CodingWorkStatusItem(
            work.identifier,
            work.revision,
            work.project_id,
            work.objective,
            work.workspace_root,
            work.state,
            needs_authority,
            _worker_state(work.state),
            work.started_at_utc,
            work.updated_at_utc,
            latest.summary if latest else None,
            latest.occurred_at_utc if latest else None,
            paths,
            _bounded_text(result.get("summary")),
            activities,
            work.state in {"running", "waiting"},
            work.state in {"starting", "running", "waiting"},
            work.state in TERMINAL_WORK_STATES,
            origin_chat_id=work.origin_chat_id,
            acceptance_criteria=work.acceptance_criteria,
            created_at_utc=work.created_at_utc,
            terminal_at_utc=work.terminal_at_utc,
            verification=verification,
            artifacts=artifacts,
            related_work_id=related_work_id,
            acceptance_status=acceptance_status,
        )


def _production_adapter(settings: CodingWorkProductionSettings) -> CodingWorkerAdapter:
    try:
        policy = OpenAICompatibleInferencePolicy(
            settings.provider_host,
            settings.provider_port,
            settings.model,
            timeout_seconds=min(settings.model_turn_timeout_seconds, 15 * 60.0),
        )
        return OpenCodeCodingWorkerAdapter(
            OpenCodeAdapterSettings(
                settings.opencode_executable,
                settings.private_root,
                policy,
                control_timeout_seconds=settings.control_timeout_seconds,
                model_turn_timeout_seconds=settings.model_turn_timeout_seconds,
            ),
            sandbox=BubblewrapCodingWorkSandbox(
                str(settings.bubblewrap_executable),
                protected_runtime_root=settings.runtime_root.parent,
            ),
        )
    except ValueError as exc:
        raise CodingWorkerError(
            "The configured OpenCode adapter could not be prepared safely.",
            code="opencode_setup_failed",
        ) from exc


def _provider_model_available(settings: CodingWorkProductionSettings) -> bool:
    parsed = urlparse(settings.provider_upstream)
    connection = http.client.HTTPConnection(
        settings.provider_host,
        settings.provider_port,
        timeout=min(settings.control_timeout_seconds, 10.0),
    )
    try:
        connection.request("GET", (parsed.path.rstrip("/") or "/v1") + "/models")
        response = connection.getresponse()
        payload = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(payload) > 1024 * 1024:
            return False
        document = json.loads(payload)
        models = document.get("data") if isinstance(document, dict) else None
        return isinstance(models, list) and any(
            isinstance(item, dict) and item.get("id") == settings.model
            for item in models
        )
    except (OSError, http.client.HTTPException, UnicodeError, json.JSONDecodeError):
        return False
    finally:
        connection.close()


def _event_summary(event: CodingWorkEvent) -> str:
    payload: Mapping[str, object] = event.payload
    if payload.get("reason") == "authority_required":
        return "Authority is required."
    for key in ("summary", "reason", "failure_message", "status"):
        value = _bounded_text(payload.get(key))
        if value is not None:
            return value
    return {
        "created": "Coding Work was proposed.",
        "authorized": "Coding Work was authorized.",
        "queued": "Coding Work was queued.",
        "starting": "The coding worker is starting.",
        "session_confirmed": "The coding worker was confirmed.",
        "instruction_queued": "A follow-up instruction was queued.",
        "cancellation_requested": "Cancellation was requested.",
        "reconciling": "Coding Work is reconciling after restart.",
        "verification": "A verification operation completed.",
        "waiting": "Coding Work is waiting.",
        "completed": "Coding Work completed.",
        "failed": "Coding Work failed.",
        "cancelled": "Coding Work was cancelled.",
    }.get(event.kind, "Coding Work changed.")


def _changed_paths(
    progress: Mapping[str, object], result: Mapping[str, object]
) -> tuple[str, ...]:
    selected: list[str] = []
    for document in (progress, result):
        values = document.get("changed_paths")
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value not in selected:
                selected.append(value[:MAX_STATUS_TEXT])
                if len(selected) >= MAX_STATUS_CHANGED_PATHS:
                    return tuple(selected)
    return tuple(selected)


def _bounded_text(value: object) -> str | None:
    return value[:MAX_STATUS_TEXT] if isinstance(value, str) and value else None


def _coding_work_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) != 44 or not value.startswith("coding-work-"):
        return None
    return value if all(character in "0123456789abcdef" for character in value[12:]) else None


def _bounded_evidence(
    value: object, *, kind: str
) -> tuple[Mapping[str, object], ...]:
    """Project only bounded, user-useful receipt evidence."""

    if not isinstance(value, list):
        return ()
    allowed = {
        "kind", "status", "summary", "source", "command", "exit_code",
        "path", "name", "omitted_files", "oversized_files",
        "omitted_changed_paths", "hashed_bytes",
    }
    selected: list[Mapping[str, object]] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        projected: dict[str, object] = {}
        for key in allowed:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate:
                projected[key] = candidate[:MAX_STATUS_TEXT]
            elif isinstance(candidate, int) and not isinstance(candidate, bool):
                projected[key] = candidate
        if projected:
            projected.setdefault("kind", kind)
            selected.append(projected)
    return tuple(selected)


def _worker_state(state: str) -> str:
    return {
        "starting": "starting",
        "running": "running",
        "waiting": "waiting",
        "cancelling": "stopping",
        "reconciling": "reconciling",
    }.get(state, "not_running")
