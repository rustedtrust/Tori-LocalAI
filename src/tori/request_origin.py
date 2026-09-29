"""Immutable application-owned request origins and origin authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RequestOriginKind(str, Enum):
    """Presentation origins that currently or concretely need distinction."""

    LOCAL_WEB = "local_web"
    LOCAL_CLI = "local_cli"
    DISCORD_REMOTE = "discord_remote"


@dataclass(frozen=True, slots=True)
class RequestOrigin:
    """Verified request metadata supplied by an application boundary.

    External identifiers are deliberately opaque strings.  They are never
    prompt text and no transport SDK type crosses this boundary.
    """

    kind: RequestOriginKind
    connector_id: str | None = None
    external_message_id: str | None = None
    external_actor_id: str | None = None
    external_conversation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RequestOriginKind):
            raise TypeError("Request origin kind must be application-owned.")
        external = (
            self.connector_id,
            self.external_message_id,
            self.external_actor_id,
            self.external_conversation_id,
        )
        if self.kind is RequestOriginKind.DISCORD_REMOTE:
            if any(not _valid_identifier(value) for value in external):
                raise ValueError(
                    "Remote request origins require bounded verified identifiers."
                )
        elif any(value is not None for value in external):
            raise ValueError("Local request origins cannot carry remote metadata.")

    @classmethod
    def local_web(cls) -> RequestOrigin:
        return cls(RequestOriginKind.LOCAL_WEB)

    @classmethod
    def local_cli(cls) -> RequestOrigin:
        return cls(RequestOriginKind.LOCAL_CLI)

    @classmethod
    def discord_remote(
        cls,
        *,
        connector_id: str,
        external_message_id: str,
        external_actor_id: str,
        external_conversation_id: str,
    ) -> RequestOrigin:
        return cls(
            RequestOriginKind.DISCORD_REMOTE,
            connector_id=connector_id,
            external_message_id=external_message_id,
            external_actor_id=external_actor_id,
            external_conversation_id=external_conversation_id,
        )


class ConversationOperation(str, Enum):
    """Typed application operations relevant to Conversation authority."""

    CONVERSATION_REPLY = "conversation.reply"
    CONVERSATION_CONTEXT_READ = "conversation.context.read_own"
    MEMORY_CONTEXT_RETRIEVE = "memory.context.retrieve"
    SEARCH_READ = "search.read"
    REMINDERS_UPCOMING_READ = "reminders.upcoming.read"
    CAPABILITIES_DESCRIBE_REMOTE = "capabilities.describe_remote"
    REMOTE_CHAT_TERMINATE_SELF = "remote_chat.terminate_self"

    MEMORY_MUTATE = "memory.mutate"
    KNOWLEDGE_READ = "knowledge.read"
    KNOWLEDGE_MUTATE = "knowledge.mutate"
    FINANCE_READ = "finance.read"
    FINANCE_MUTATE = "finance.mutate"
    PLANNING_READ = "planning.read"
    PLANNING_MUTATE = "planning.mutate"
    REMINDER_MUTATE = "reminders.mutate"
    SCHEDULED_WORK_MUTATE = "scheduled_work.mutate"
    PROJECT_READ = "projects.read"
    PROJECT_MUTATE = "projects.mutate"
    HOST_READ = "host.read"
    COMMAND_EXECUTE = "command.execute"
    CODING_WORK_EXECUTE = "coding_work.execute"
    SERVICE_CONTROL = "services.control"
    BACKUP_CREATE = "backup.create"
    SETTINGS_MUTATE = "settings.mutate"
    LOCAL_COMMAND = "conversation.local_command"
    APPLICATION_OPEN = "applications.open"
    LOCAL_PROPOSAL_CONFIRM = "proposal.confirm_local"
    SKILL_ADMINISTER = "skills.administer"
    SKILL_INVOKE = "skills.invoke"


REMOTE_CHAT_V1_OPERATIONS = frozenset(
    {
        ConversationOperation.CONVERSATION_REPLY,
        ConversationOperation.CONVERSATION_CONTEXT_READ,
        ConversationOperation.MEMORY_CONTEXT_RETRIEVE,
        ConversationOperation.SEARCH_READ,
        ConversationOperation.REMINDERS_UPCOMING_READ,
        ConversationOperation.CAPABILITIES_DESCRIBE_REMOTE,
        ConversationOperation.REMOTE_CHAT_TERMINATE_SELF,
    }
)


class OriginAuthorityError(PermissionError):
    """A typed operation is not authorized from this request origin."""

    code = "origin_not_authorized"


class OriginAuthority:
    """Application-owned, wording-independent origin policy."""

    def permits(
        self, origin: RequestOrigin, operation: ConversationOperation
    ) -> bool:
        if not isinstance(origin, RequestOrigin):
            return False
        if not isinstance(operation, ConversationOperation):
            return False
        if operation is ConversationOperation.REMOTE_CHAT_TERMINATE_SELF:
            return origin.kind is RequestOriginKind.DISCORD_REMOTE
        if origin.kind in {
            RequestOriginKind.LOCAL_WEB,
            RequestOriginKind.LOCAL_CLI,
        }:
            return True
        if origin.kind is RequestOriginKind.DISCORD_REMOTE:
            return operation in REMOTE_CHAT_V1_OPERATIONS
        return False

    def require(
        self, origin: RequestOrigin, operation: ConversationOperation
    ) -> None:
        if not self.permits(origin, operation):
            operation_name = (
                operation.value
                if isinstance(operation, ConversationOperation)
                else "invalid_operation"
            )
            origin_name = (
                origin.kind.value
                if isinstance(origin, RequestOrigin)
                and isinstance(origin.kind, RequestOriginKind)
                else "invalid_origin"
            )
            raise OriginAuthorityError(
                f"{operation_name} is not authorized from {origin_name}."
            )


def _valid_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 256
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )
