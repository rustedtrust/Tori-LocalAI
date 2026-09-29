"""Process-local application workflow for explicit management removals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import secrets
import time
from typing import Literal

from .management import (
    CHECKPOINT_REMOVE,
    KNOWLEDGE_REMOVE,
    MEMORY_FORGET,
    CheckpointItem,
    ConfirmationTarget,
    KnowledgeSourceItem,
    ManagementService,
    MemoryItem,
)


RemovalAction = Literal[
    "checkpoint_remove",
    "memory_forget",
    "knowledge_remove",
]
RemovalDecision = Literal["confirm", "cancel"]
RemovalOrigin = Literal["management_action", "conversation_command"]
RemovedItem = CheckpointItem | MemoryItem | KnowledgeSourceItem

SUPPORTED_REMOVAL_ACTIONS: tuple[RemovalAction, ...] = (
    CHECKPOINT_REMOVE,
    MEMORY_FORGET,
    KNOWLEDGE_REMOVE,
)
_SUPPORTED_ORIGINS: tuple[RemovalOrigin, ...] = (
    "management_action",
    "conversation_command",
)
DEFAULT_REMOVAL_LIFETIME_SECONDS = 300.0


class ManagementRemovalError(RuntimeError):
    """A safe process-local removal-workflow failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RemovalProposal:
    token: str
    action: RemovalAction
    target: ConfirmationTarget
    origin: RemovalOrigin
    expires_at: float


@dataclass(frozen=True, slots=True)
class RemovalOutcome:
    action: RemovalAction
    target: ConfirmationTarget
    origin: RemovalOrigin
    cancelled: bool
    removed: RemovedItem | None


class ManagementRemovalWorkflow:
    """Own only checkpoint, curated-memory, and knowledge removal proposals."""

    def __init__(
        self,
        management: ManagementService,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        lifetime_seconds: float = DEFAULT_REMOVAL_LIFETIME_SECONDS,
    ) -> None:
        self._management = management
        self._clock = clock
        self._token_factory = token_factory
        self._lifetime_seconds = lifetime_seconds
        self._proposals: dict[str, RemovalProposal] = {}

    def propose_checkpoint(
        self,
        identifier: str,
        *,
        origin: RemovalOrigin = "management_action",
    ) -> RemovalProposal:
        target = self._management.checkpoint_removal_target(identifier)
        return self._store(CHECKPOINT_REMOVE, target, origin)

    def propose_memory(
        self,
        identifier: str,
        *,
        expected_updated_at: str | None = None,
        origin: RemovalOrigin = "management_action",
    ) -> RemovalProposal:
        target = self._management.memory_forget_target(
            identifier,
            expected_updated_at=expected_updated_at,
        )
        return self._store(MEMORY_FORGET, target, origin)

    def propose_knowledge(
        self,
        identifier: str,
        *,
        origin: RemovalOrigin = "management_action",
    ) -> RemovalProposal:
        target = self._management.knowledge_removal_target(identifier)
        return self._store(KNOWLEDGE_REMOVE, target, origin)

    def proposal(self, token: str) -> RemovalProposal | None:
        """Return presentation facts without transferring lifecycle ownership."""

        return self._proposals.get(token)

    def decide(self, token: str, decision: str) -> RemovalOutcome:
        if decision not in {"confirm", "cancel"}:
            raise ManagementRemovalError(
                "The confirmation decision must be confirm or cancel.",
                code="invalid_decision",
            )
        proposal = self._proposals.pop(token, None)
        if proposal is None:
            raise ManagementRemovalError(
                "That confirmation is invalid or has already been used.",
                code="unknown_confirmation",
            )
        if self._clock() > proposal.expires_at:
            raise ManagementRemovalError(
                "That confirmation has expired.",
                code="expired_confirmation",
            )
        if decision == "cancel":
            return RemovalOutcome(
                action=proposal.action,
                target=proposal.target,
                origin=proposal.origin,
                cancelled=True,
                removed=None,
            )

        if proposal.action == CHECKPOINT_REMOVE:
            removed: RemovedItem = self._management.remove_checkpoint(
                proposal.target
            )
        elif proposal.action == MEMORY_FORGET:
            removed = self._management.forget_memory(proposal.target)
        elif proposal.action == KNOWLEDGE_REMOVE:
            removed = self._management.remove_knowledge(proposal.target)
        else:  # pragma: no cover - proposals are created only by explicit methods.
            raise ManagementRemovalError(
                "That confirmation action is invalid.",
                code="invalid_confirmation",
            )
        return RemovalOutcome(
            action=proposal.action,
            target=proposal.target,
            origin=proposal.origin,
            cancelled=False,
            removed=removed,
        )

    def clear(self) -> None:
        self._proposals.clear()

    def _store(
        self,
        action: RemovalAction,
        target: ConfirmationTarget,
        origin: RemovalOrigin,
    ) -> RemovalProposal:
        if origin not in _SUPPORTED_ORIGINS:
            raise ManagementRemovalError(
                "That management-removal origin is invalid.",
                code="invalid_origin",
            )
        if target.action != action:
            raise ManagementRemovalError(
                "That confirmation target has an invalid action.",
                code="invalid_confirmation",
            )
        token = self._token_factory()
        if not isinstance(token, str) or not token or token in self._proposals:
            raise ManagementRemovalError(
                "A unique management-removal token could not be created.",
                code="token_unavailable",
            )
        proposal = RemovalProposal(
            token=token,
            action=action,
            target=target,
            origin=origin,
            expires_at=self._clock() + self._lifetime_seconds,
        )
        self._proposals[token] = proposal
        return proposal
