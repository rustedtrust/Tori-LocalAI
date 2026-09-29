"""Local browser proposal/approval adapter for the single execution policy."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import threading
import time

from .execution_policy import (ExecutionPolicyService, ExecutionRequest,
                               ExecutionScope, PolicyClass, PolicyError)
from .terminal_authority import TerminalLocalAuthority
from .terminal_broker import TerminalBroker, TerminalError


PROPOSAL_TTL_SECONDS = 60
MAX_PROPOSALS = 128


class TerminalLaunchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Proposal:
    request: ExecutionRequest
    owner_digest: str
    conversation_id: str
    turn_id: str
    expires_at: float


class TerminalLaunchService:
    """One local interaction source; no model, worker or remote-chat adapter."""

    def __init__(self, policy: ExecutionPolicyService, broker: TerminalBroker,
                 *, monotonic=time.monotonic) -> None:
        self._policy = policy
        self._broker = broker
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._proposals: dict[str, _Proposal] = {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _require(authority: TerminalLocalAuthority) -> str:
        if (not isinstance(authority, TerminalLocalAuthority)
                or not authority.permits(authority.browser_owner)):
            raise TerminalLaunchError("A direct local browser interaction is required.")
        return authority.browser_owner

    def request(self, command: str, cwd: str, scope: str,
                authority: TerminalLocalAuthority, *, conversation_id: str,
                turn_id: str) -> dict[str, object]:
        owner = self._require(authority)
        if not conversation_id or not turn_id:
            raise TerminalLaunchError("An active conversation and turn are required.")
        try:
            request = ExecutionRequest.create(command, cwd, ExecutionScope(scope))
            decision = self._policy.evaluate(request)
        except (PolicyError, ValueError, TypeError) as exc:
            raise TerminalLaunchError("The terminal execution request is invalid or unavailable.") from exc
        response: dict[str, object] = {
            "command": request.command, "cwd": request.cwd, "scope": request.scope.value,
            "policy": decision.outcome.value, "reason": decision.reason,
            "rule_id": decision.rule_id, "source": decision.source,
        }
        if decision.outcome is PolicyClass.BLACKLIST:
            return response
        if decision.outcome is PolicyClass.WHITELIST:
            return response | {"session_id": self._launch(request, authority, conversation_id,
                                                           turn_id, approved=False)}
        with self._lock:
            self._proposals = {digest: value for digest, value in self._proposals.items()
                               if value.expires_at > self._monotonic()}
            if len(self._proposals) >= MAX_PROPOSALS:
                raise TerminalLaunchError("Too many pending terminal proposals.")
            token = secrets.token_urlsafe(32)
            self._proposals[self._digest(token)] = _Proposal(
                request, self._digest(owner), conversation_id, turn_id,
                self._monotonic() + PROPOSAL_TTL_SECONDS)
        return response | {"proposal_token": token, "expires_in_seconds": PROPOSAL_TTL_SECONDS}

    def decide(self, token: str, decision: str,
               authority: TerminalLocalAuthority, *, conversation_id: str) -> dict[str, object]:
        owner = self._require(authority)
        if not isinstance(token, str) or decision not in {"approve", "cancel", "whitelist"}:
            raise TerminalLaunchError("The terminal approval is invalid.")
        with self._lock:
            digest = self._digest(token)
            proposal = self._proposals.get(digest)
            if (proposal is None or proposal.owner_digest != self._digest(owner)
                    or proposal.conversation_id != conversation_id
                    or proposal.expires_at <= self._monotonic()):
                raise TerminalLaunchError("The terminal proposal is invalid or expired.")
            del self._proposals[digest]
        if decision == "cancel":
            return {"cancelled": True}
        if decision == "whitelist":
            try:
                if self._policy.evaluate(proposal.request).outcome is not PolicyClass.DEFAULT_ASK:
                    raise TerminalLaunchError("Only a Default Ask request may be whitelisted here.")
                self._policy.create_rule(proposal.request, PolicyClass.WHITELIST)
            except PolicyError as exc:
                raise TerminalLaunchError("The exact request could not be whitelisted.") from exc
            return {"session_id": self._launch(proposal.request, authority,
                                                proposal.conversation_id, proposal.turn_id,
                                                approved=False)}
        return {"session_id": self._launch(proposal.request, authority,
                                            proposal.conversation_id, proposal.turn_id,
                                            approved=True)}

    def _launch(self, request: ExecutionRequest, authority: TerminalLocalAuthority,
                conversation_id: str, turn_id: str, *, approved: bool) -> str:
        owner = self._require(authority)
        grant_owner = "terminal:" + self._digest(owner + "\0" + conversation_id + "\0" + turn_id)
        try:
            grant = self._policy.issue_grant(
                request, grant_owner, approved=approved,
                provenance="local_browser_approval" if approved else "local_browser_whitelist")
            return self._broker.launch(
                request, grant_token=grant.token, grant_owner=grant_owner,
                browser_owner=owner, authority=authority,
                conversation_id=conversation_id, turn_id=turn_id)
        except (PolicyError, TerminalError) as exc:
            raise TerminalLaunchError("The terminal request could not be authorized or started.") from exc
