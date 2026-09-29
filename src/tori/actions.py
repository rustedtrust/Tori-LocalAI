"""Application-owned contracts for Tori's bounded interactive actions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
import secrets
import threading
from types import MappingProxyType
from typing import Any

from .backups import BackupBusyError, BackupError, BackupService, result_document
from .command_execution import (
    MAX_COMMAND_CHARACTERS,
    CommandExecutionService,
)


BACKUP_ACTION_ID = "tori.backup"
COMMAND_ACTION_ID = "tori.command.execute"


class PermissionClass(str, Enum):
    """Tori's conceptual permission levels."""

    INFORMATIONAL = "informational"
    ADVISORY = "advisory"
    INTERACTIVE = "interactive"
    PERSISTENT = "persistent"


class InvocationSource(str, Enum):
    """Application-owned origins supported by the first bounded action."""

    SETTINGS = "settings"
    CONVERSATION = "conversation"


class ActionContractError(ValueError):
    """A fail-closed action validation or authorization error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CapabilityAvailability:
    """Application-owned preflight state for one bounded capability."""

    available: bool
    code: str = "available"
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """One fixed bounded capability definition shared by dispatch paths."""

    identifier: str
    name: str
    description: str
    permission: PermissionClass
    _validate_arguments: Callable[[object], Mapping[str, Any]]
    _executor: Callable[[Mapping[str, Any], str], Mapping[str, Any]]
    contract_version: int = 1
    interactive_eligible: bool = False
    scheduled_one_shot_eligible: bool = False
    scheduled_recurring_eligible: bool = False
    system_derived_one_shot_eligible: bool = False
    _validate_result: Callable[[object], Mapping[str, Any]] | None = None
    _availability: Callable[[], CapabilityAvailability] | None = None

    def validate_arguments(self, arguments: object) -> Mapping[str, Any]:
        """Return one immutable canonical argument mapping."""

        return MappingProxyType(dict(self._validate_arguments(arguments)))

    def validate_result(self, result: object) -> Mapping[str, Any]:
        """Return one immutable bounded result mapping."""

        validator = self._validate_result or _validate_mapping_result
        return MappingProxyType(dict(validator(result)))

    def execute(
        self, arguments: Mapping[str, Any], invocation_id: str
    ) -> Mapping[str, Any]:
        return self.validate_result(self._executor(arguments, invocation_id))

    def availability(self) -> CapabilityAvailability:
        if self._availability is None:
            return CapabilityAvailability(True)
        state = self._availability()
        if not isinstance(state, CapabilityAvailability):
            raise ActionContractError(
                "The capability availability check returned invalid state.",
                code="capability_unavailable",
            )
        return state


@dataclass(frozen=True, slots=True)
class ActionInvocation:
    """One validated and specifically authorized action invocation."""

    identifier: str
    action_id: str
    arguments: Mapping[str, Any]
    source: InvocationSource
    authorization: str


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Application-determined result of one attempted invocation."""

    invocation_id: str
    action_id: str
    source: InvocationSource
    permission: PermissionClass
    authorized: bool
    status: str
    code: str
    message: str
    result: Mapping[str, Any] | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    def document(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "action_id": self.action_id,
            "source": self.source.value,
            "permission": self.permission.value,
            "authorized": self.authorized,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "result": dict(self.result) if self.result is not None else None,
        }


@dataclass(frozen=True, slots=True)
class _AuthorizationGrant:
    invocation_id: str
    action_id: str
    arguments: Mapping[str, Any]
    source: InvocationSource


class ActionDispatcher:
    """Validate, authorize, and execute Tori's fixed action set."""

    def __init__(
        self,
        backup_service: BackupService | None = None,
        *,
        command_service: CommandExecutionService | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        definitions: dict[str, ActionDefinition] = {}
        if backup_service is not None:
            backup = ActionDefinition(
                identifier=BACKUP_ACTION_ID,
                name="Back up Tori",
                description="Create and verify one fixed-policy Tori project backup.",
                permission=PermissionClass.INTERACTIVE,
                _validate_arguments=_validate_no_arguments,
                _executor=lambda _arguments, _invocation_id: _execute_backup(backup_service),
                interactive_eligible=True,
                scheduled_one_shot_eligible=True,
                _validate_result=_validate_backup_result,
                _availability=lambda: _backup_availability(backup_service),
            )
            definitions[backup.identifier] = backup
        self._definitions = MappingProxyType(definitions)
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._grants: dict[str, _AuthorizationGrant] = {}
        self._grant_lock = threading.Lock()

    @property
    def definitions(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._definitions.values())

    def definition(self, action_id: object) -> ActionDefinition:
        if not isinstance(action_id, str) or action_id not in self._definitions:
            raise ActionContractError(
                "The requested action is not supported.", code="unknown_action"
            )
        return self._definitions[action_id]

    def authorize(
        self,
        action_id: object,
        arguments: object,
        *,
        source: InvocationSource,
    ) -> ActionInvocation:
        """Create one application-owned, single-use invocation grant."""

        if action_id == COMMAND_ACTION_ID:
            raise ActionContractError(
                "The legacy general command action is retired; use the local terminal authority.",
                code="legacy_command_retired",
            )
        definition = self.definition(action_id)
        if not isinstance(source, InvocationSource):
            raise ActionContractError(
                "The action invocation source is invalid.", code="invalid_source"
            )
        if not definition.interactive_eligible:
            raise ActionContractError(
                "The requested capability is not eligible for interactive execution.",
                code="interactive_not_allowed",
            )
        validated = definition.validate_arguments(arguments)
        authorization = self._token_factory()
        if not isinstance(authorization, str) or not authorization:
            raise ActionContractError(
                "The action could not be authorized safely.",
                code="authorization_failed",
            )
        invocation_id = secrets.token_hex(16)
        grant = _AuthorizationGrant(
            invocation_id=invocation_id,
            action_id=definition.identifier,
            arguments=validated,
            source=source,
        )
        with self._grant_lock:
            if authorization in self._grants:
                raise ActionContractError(
                    "The action could not be authorized safely.",
                    code="authorization_failed",
                )
            self._grants[authorization] = grant
        return ActionInvocation(
            identifier=invocation_id,
            action_id=definition.identifier,
            arguments=validated,
            source=source,
            authorization=authorization,
        )

    def execute(self, invocation: object) -> ActionOutcome:
        """Consume one exact authorization and return an application outcome."""

        if not isinstance(invocation, ActionInvocation):
            raise ActionContractError(
                "A validated action invocation is required.",
                code="invalid_invocation",
            )
        definition = self.definition(invocation.action_id)
        with self._grant_lock:
            grant = self._grants.pop(invocation.authorization, None)
        if grant is None or not _grant_matches(grant, invocation):
            return ActionOutcome(
                invocation_id=invocation.identifier,
                action_id=invocation.action_id,
                source=invocation.source,
                permission=definition.permission,
                authorized=False,
                status="rejected",
                code="not_authorized",
                message="This action invocation is not authorized.",
            )
        try:
            result = MappingProxyType(
                dict(definition.execute(grant.arguments, invocation.identifier))
            )
        except (BackupError, ActionContractError) as exc:
            policy_rejected = exc.code == "policy_denied"
            return ActionOutcome(
                invocation_id=invocation.identifier,
                action_id=definition.identifier,
                source=invocation.source,
                permission=definition.permission,
                authorized=not policy_rejected,
                status="rejected" if policy_rejected else "failed",
                code=exc.code,
                message=str(exc),
            )
        return ActionOutcome(
            invocation_id=invocation.identifier,
            action_id=definition.identifier,
            source=invocation.source,
            permission=definition.permission,
            authorized=True,
            status="succeeded",
            code="completed",
            message="The backup completed and was verified.",
            result=result,
        )

    def decline(self, invocation: object) -> bool:
        """Consume an exact authorization without executing its action."""

        if not isinstance(invocation, ActionInvocation):
            return False
        with self._grant_lock:
            grant = self._grants.pop(invocation.authorization, None)
        return grant is not None and _grant_matches(grant, invocation)


def recognized_action_id(text: object) -> str | None:
    """Recognize only the approved unmistakable backup imperatives."""

    if not isinstance(text, str):
        return None
    normalized = " ".join(text.strip().casefold().split())
    if normalized.endswith((".", "!")):
        normalized = normalized[:-1].rstrip()
    if normalized in {
        "tori, run a backup",
        "run a tori backup",
        "back up tori",
        "please back up tori",
    }:
        return BACKUP_ACTION_ID
    return None


def parse_run_command(text: object) -> str | None:
    """Recognize only the exact application-owned ``/run COMMAND`` path."""

    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped == "/run":
        raise ActionContractError(
            "The /run command requires an exact command to propose.",
            code="empty_command",
        )
    if not stripped.startswith("/run"):
        return None
    if len(stripped) > 4 and not stripped[4].isspace():
        return None
    command = stripped[4:].strip()
    if not command:
        raise ActionContractError(
            "The /run command requires an exact command to propose.",
            code="empty_command",
        )
    if "\x00" in command or len(command) > MAX_COMMAND_CHARACTERS:
        raise ActionContractError(
            f"The command cannot exceed {MAX_COMMAND_CHARACTERS} characters.",
            code="invalid_arguments",
        )
    return command


def _validate_no_arguments(arguments: object) -> Mapping[str, Any]:
    if not isinstance(arguments, Mapping) or arguments:
        raise ActionContractError(
            "This action accepts no arguments.", code="invalid_arguments"
        )
    return {}


def _validate_mapping_result(result: object) -> Mapping[str, Any]:
    if not isinstance(result, Mapping):
        raise ActionContractError(
            "The capability returned an invalid result.", code="invalid_result"
        )
    return dict(result)


def _validate_backup_result(result: object) -> Mapping[str, Any]:
    if not isinstance(result, Mapping) or set(result) != {
        "identifier", "completed_at", "directory", "total_regular_bytes",
        "regular_file_count", "directory_count", "symlink_count", "verification",
    }:
        raise ActionContractError(
            "The backup returned an invalid result.", code="invalid_result"
        )
    if (
        not all(isinstance(result[key], str) and result[key] for key in (
            "identifier", "completed_at", "directory",
        ))
        or result["verification"] != "verified"
        or any(
            isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 0
            for key in (
                "total_regular_bytes", "regular_file_count", "directory_count", "symlink_count"
            )
        )
    ):
        raise ActionContractError(
            "The backup returned an invalid result.", code="invalid_result"
        )
    return dict(result)


def _backup_availability(service: BackupService) -> CapabilityAvailability:
    if service.in_progress:
        return CapabilityAvailability(
            False, BackupBusyError.code, "A backup is already in progress."
        )
    return CapabilityAvailability(True)


def _execute_backup(service: BackupService) -> Mapping[str, Any]:
    result = result_document(service.create_backup())
    assert result is not None
    return result


def _grant_matches(
    grant: _AuthorizationGrant, invocation: ActionInvocation
) -> bool:
    return (
        grant.invocation_id == invocation.identifier
        and grant.action_id == invocation.action_id
        and grant.source is invocation.source
        and dict(grant.arguments) == dict(invocation.arguments)
    )
