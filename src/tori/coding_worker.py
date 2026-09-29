"""Portable Coding Work adapter contract and deterministic test adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol, Sequence

from .coding_work import CodingWorkAuthority, CodingWorkDirective
from .time_context import format_utc_timestamp


class CodingWorkerError(RuntimeError):
    """Safe adapter-boundary failure."""

    code = "coding_worker_error"

    def __init__(self, message: str, *, code: str = "coding_worker_error") -> None:
        super().__init__(message)
        self.code = code


class CodingWorkerUnsupportedError(CodingWorkerError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            f"The coding worker adapter does not support {capability}.",
            code="unsupported_adapter_capability",
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerCapabilities:
    follow_up_directives: bool
    cancellation: bool
    durable_sessions: bool
    semantic_events: bool
    optional_capabilities: frozenset[str] = frozenset()

    def require_optional(self, name: str) -> None:
        if name not in self.optional_capabilities:
            raise CodingWorkerUnsupportedError(name)


@dataclass(frozen=True, slots=True)
class CodingWorkerStartRequest:
    work_id: str
    run_id: str
    objective: str
    acceptance_criteria: str | None
    authority: CodingWorkAuthority
    launch_correlation_id: str


@dataclass(frozen=True, slots=True)
class CodingWorkerReconnectRequest:
    """Authoritative Tori context required to reconnect a durable session."""

    work_id: str
    run_id: str
    objective: str
    acceptance_criteria: str | None
    authority: CodingWorkAuthority
    after_sequence: int
    prior_observed_state: str | None = None


@dataclass(frozen=True, slots=True)
class CodingWorkerBinding:
    adapter_id: str
    adapter_version: int
    launch_correlation_id: str
    session_id: str | None


@dataclass(frozen=True, slots=True)
class CodingWorkerObservation:
    found: bool
    state: str | None
    session_id: str | None
    event_cursor: str | None


@dataclass(frozen=True, slots=True)
class CodingWorkerEvent:
    identifier: str
    sequence: int
    kind: str
    occurred_at_utc: str
    payload: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CodingWorkerDirectiveReceipt:
    directive_id: str
    receipt: str
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class CodingWorkerEvidence:
    summary: str
    changed_paths: tuple[str, ...] = ()
    verification: tuple[Mapping[str, object], ...] = ()
    artifacts: tuple[Mapping[str, object], ...] = ()

    def document(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "changed_paths": list(self.changed_paths),
            "verification": [dict(item) for item in self.verification],
            "artifacts": [dict(item) for item in self.artifacts],
        }


class CodingWorkerAdapter(Protocol):
    """Narrow replaceable worker boundary required by the first slice."""

    @property
    def identifier(self) -> str: ...

    @property
    def contract_version(self) -> int: ...

    def describe_capabilities(self) -> CodingWorkerCapabilities: ...

    def start(self, request: CodingWorkerStartRequest) -> CodingWorkerBinding: ...

    def inspect(self, binding: CodingWorkerBinding) -> CodingWorkerObservation: ...

    def reconnect(
        self,
        request: CodingWorkerReconnectRequest,
        binding: CodingWorkerBinding,
    ) -> CodingWorkerObservation: ...

    def attach(
        self, binding: CodingWorkerBinding, *, after_sequence: int
    ) -> tuple[CodingWorkerEvent, ...]: ...

    def submit_directive(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt: ...

    def cancel(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt: ...

    def collect_evidence(self, binding: CodingWorkerBinding) -> CodingWorkerEvidence: ...

    def close(self, binding: CodingWorkerBinding) -> None: ...


@dataclass(slots=True)
class _FakeSession:
    session_id: str
    launch_correlation_id: str
    state: str = "starting"
    events: list[CodingWorkerEvent] = field(default_factory=list)
    directives: dict[str, CodingWorkerDirectiveReceipt] = field(default_factory=dict)
    evidence: CodingWorkerEvidence = field(
        default_factory=lambda: CodingWorkerEvidence("No terminal evidence is available.")
    )
    cancel_pending: bool = False
    closed: bool = False


class FakeCodingWorkerAdapter:
    """Deterministic in-memory worker used only to prove Tori semantics."""

    identifier = "fake.coding.worker"
    contract_version = 1

    def __init__(
        self,
        *,
        auto_confirm_start: bool = True,
        delayed_cancellation: bool = False,
        clock=None,  # type: ignore[no-untyped-def]
    ) -> None:
        self._auto_confirm_start = auto_confirm_start
        self._delayed_cancellation = delayed_cancellation
        self._clock = clock or (
            lambda: datetime(2000, 1, 1, tzinfo=timezone.utc)
        )
        self._sessions: dict[str, _FakeSession] = {}
        self._correlations: dict[str, str] = {}
        self._session_counter = 0
        self._event_counter = 0

    def describe_capabilities(self) -> CodingWorkerCapabilities:
        return CodingWorkerCapabilities(True, True, True, True)

    def start(self, request: CodingWorkerStartRequest) -> CodingWorkerBinding:
        existing = self._correlations.get(request.launch_correlation_id)
        if existing is not None:
            return self._binding(self._sessions[existing])
        self._session_counter += 1
        session_id = f"fake-session-{self._session_counter}"
        session = _FakeSession(session_id, request.launch_correlation_id)
        self._sessions[session_id] = session
        self._correlations[request.launch_correlation_id] = session_id
        if self._auto_confirm_start:
            session.state = "running"
            self._emit(session, "session_confirmed", {})
        return self._binding(session)

    def inspect(self, binding: CodingWorkerBinding) -> CodingWorkerObservation:
        session = self._find(binding)
        if session is None or session.closed:
            return CodingWorkerObservation(False, None, None, None)
        return CodingWorkerObservation(
            True, session.state, session.session_id, str(len(session.events))
        )

    def reconnect(
        self,
        request: CodingWorkerReconnectRequest,
        binding: CodingWorkerBinding,
    ) -> CodingWorkerObservation:
        if request.work_id == "" or request.run_id == "":
            raise CodingWorkerError("The reconnect request is invalid.", code="invalid_reconnect")
        if request.after_sequence < 0:
            raise CodingWorkerError("The reconnect event sequence is invalid.", code="invalid_reconnect")
        request.authority.document()
        return self.inspect(binding)

    def attach(
        self, binding: CodingWorkerBinding, *, after_sequence: int
    ) -> tuple[CodingWorkerEvent, ...]:
        session = self._require(binding)
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise CodingWorkerError("The worker event cursor is invalid.", code="invalid_cursor")
        return tuple(item for item in session.events if item.sequence > after_sequence)

    def submit_directive(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        session = self._require(binding)
        if directive.kind != "instruction":
            raise CodingWorkerError("An instruction directive is required.", code="invalid_directive")
        existing = session.directives.get(directive.identifier)
        if existing is not None:
            return CodingWorkerDirectiveReceipt(
                existing.directive_id, existing.receipt, duplicate=True
            )
        receipt = CodingWorkerDirectiveReceipt(
            directive.identifier, "fake-receipt-" + directive.identifier
        )
        session.directives[directive.identifier] = receipt
        if session.state == "waiting":
            session.state = "running"
            self._emit(session, "session_confirmed", {"reason": "follow_up"})
        return receipt

    def cancel(
        self, binding: CodingWorkerBinding, directive: CodingWorkDirective
    ) -> CodingWorkerDirectiveReceipt:
        session = self._require(binding)
        if directive.kind != "cancel":
            raise CodingWorkerError("A cancellation directive is required.", code="invalid_directive")
        existing = session.directives.get(directive.identifier)
        if existing is not None:
            return CodingWorkerDirectiveReceipt(
                existing.directive_id, existing.receipt, duplicate=True
            )
        receipt = CodingWorkerDirectiveReceipt(
            directive.identifier, "fake-receipt-" + directive.identifier
        )
        session.directives[directive.identifier] = receipt
        if self._delayed_cancellation:
            session.cancel_pending = True
        else:
            self.acknowledge_cancellation(session.session_id)
        return receipt

    def collect_evidence(self, binding: CodingWorkerBinding) -> CodingWorkerEvidence:
        return self._require(binding).evidence

    def close(self, binding: CodingWorkerBinding) -> None:
        session = self._require(binding)
        session.closed = True

    def confirm_start(self, session_id: str) -> None:
        session = self._session(session_id)
        if session.state == "starting":
            session.state = "running"
            self._emit(session, "session_confirmed", {})

    def progress(
        self,
        session_id: str,
        summary: str,
        *,
        changed_paths: Sequence[str] = (),
        verification: str | None = None,
        identifier: str | None = None,
    ) -> CodingWorkerEvent:
        session = self._session(session_id)
        return self._emit(
            session,
            "progress",
            {
                "summary": summary,
                "changed_paths": list(changed_paths),
                "verification": verification,
            },
            identifier=identifier,
        )

    def wait(self, session_id: str, reason: str) -> CodingWorkerEvent:
        session = self._session(session_id)
        session.state = "waiting"
        return self._emit(session, "waiting", {"reason": reason})

    def verify(
        self, session_id: str, command: str, status: str
    ) -> CodingWorkerEvent:
        session = self._session(session_id)
        return self._emit(
            session, "verification", {"command": command, "status": status}
        )

    def complete(
        self,
        session_id: str,
        *,
        summary: str = "The fake coding work completed.",
        changed_paths: Sequence[str] = (),
        verification: Sequence[Mapping[str, object]] = (),
        identifier: str | None = None,
    ) -> CodingWorkerEvent:
        session = self._session(session_id)
        session.state = "completed"
        session.evidence = CodingWorkerEvidence(
            summary, tuple(changed_paths), tuple(dict(item) for item in verification)
        )
        return self._emit(session, "completed", {}, identifier=identifier)

    def fail(
        self,
        session_id: str,
        *,
        code: str = "fake_failure",
        message: str = "The fake worker failed.",
        identifier: str | None = None,
    ) -> CodingWorkerEvent:
        session = self._session(session_id)
        session.state = "failed"
        session.evidence = CodingWorkerEvidence(message)
        return self._emit(
            session, "failed", {"failure_code": code, "failure_message": message},
            identifier=identifier,
        )

    def acknowledge_cancellation(self, session_id: str) -> CodingWorkerEvent:
        session = self._session(session_id)
        session.cancel_pending = False
        session.state = "cancelled"
        session.evidence = CodingWorkerEvidence("The fake coding work was cancelled.")
        return self._emit(session, "cancelled", {})

    def lose_session(self, session_id: str) -> None:
        session = self._session(session_id)
        session.closed = True

    def duplicate_event(self, session_id: str, event: CodingWorkerEvent) -> None:
        """Append an exact duplicate for replay/idempotency tests."""

        self._session(session_id).events.append(event)

    def unsupported(self, capability: str) -> None:
        self.describe_capabilities().require_optional(capability)

    def binding_for_session(self, session_id: str) -> CodingWorkerBinding:
        return self._binding(self._session(session_id))

    def delivered_directive_ids(self, session_id: str) -> tuple[str, ...]:
        return tuple(self._session(session_id).directives)

    def _binding(self, session: _FakeSession) -> CodingWorkerBinding:
        return CodingWorkerBinding(
            self.identifier, self.contract_version,
            session.launch_correlation_id, session.session_id,
        )

    def _find(self, binding: CodingWorkerBinding) -> _FakeSession | None:
        if binding.adapter_id != self.identifier or binding.adapter_version != self.contract_version:
            raise CodingWorkerError("The worker binding targets another adapter.", code="adapter_mismatch")
        session_id = binding.session_id or self._correlations.get(binding.launch_correlation_id)
        return None if session_id is None else self._sessions.get(session_id)

    def _require(self, binding: CodingWorkerBinding) -> _FakeSession:
        session = self._find(binding)
        if session is None or session.closed:
            raise CodingWorkerError("The worker session is missing.", code="session_missing")
        return session

    def _session(self, session_id: str) -> _FakeSession:
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise CodingWorkerError("The fake worker session is missing.", code="session_missing") from exc
        if session.closed:
            raise CodingWorkerError("The fake worker session is missing.", code="session_missing")
        return session

    def _emit(
        self,
        session: _FakeSession,
        kind: str,
        payload: Mapping[str, object],
        *,
        identifier: str | None = None,
    ) -> CodingWorkerEvent:
        self._event_counter += 1
        event = CodingWorkerEvent(
            identifier or f"fake-event-{self._event_counter}",
            len(session.events) + 1,
            kind,
            format_utc_timestamp(self._clock().astimezone(timezone.utc)),
            dict(payload),
        )
        session.events.append(event)
        return event
