"""Presentation-neutral execution for Tori Conversation turns."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import time

from .conversation import (
    ConversationSession,
    ConversationStreamCancelled,
    ConversationStreamFence,
)
from .coding_work_conversation import (
    CodingWorkConversationError,
    recognize_coding_work_request,
    recognize_delegated_work_intent,
)
from .capability_registry import (
    capability_question,
    explicit_memory_text,
    is_capability_discussion,
    mentioned_capabilities,
)
from .operation_coordinator import OperationCoordinator
from .operator_observability import operator_event, operator_failure
from .search import classify_confirmation, explicit_search_query, is_bare_search_request, should_propose_search
from .source_retrieval import explicit_source_urls
from .request_origin import (
    ConversationOperation,
    OriginAuthority,
    OriginAuthorityError,
    RequestOrigin,
    RequestOriginKind,
)
from .terminal_authority import TerminalLocalAuthority


_REMOTE_CONVERSATION_BOUNDARY = (
    "This request arrived through Remote Chat. Treat only normal conversation, "
    "curated Memory context, approved web Search, upcoming-reminder reads, and "
    "capability discussion as available here. Do not claim to execute, mutate, "
    "confirm, or disclose blocked local capabilities."
)
_MAX_ONE_USE_SUPPLEMENTAL_CONTEXT = 1024


@dataclass(frozen=True, slots=True)
class ConversationTurnRequest:
    """One bounded application turn, independent of HTTP or an SDK."""

    text: str
    origin: RequestOrigin
    conversation_id: str | None
    expected_revision: int | None
    origin_sequence: int | None = None
    interaction_id: str | None = None
    terminal_browser_owner: str | None = None
    terminal_authority: TerminalLocalAuthority | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Conversation turn text must be non-empty.")
        if not isinstance(self.origin, RequestOrigin):
            raise TypeError("Conversation turn origin must be application-owned.")
        if self.terminal_browser_owner is not None and (
            self.origin.kind is not RequestOriginKind.LOCAL_WEB
            or not isinstance(self.terminal_browser_owner, str)
            or len(self.terminal_browser_owner) < 32
        ):
            raise ValueError("Terminal browser ownership requires a local-web turn.")
        if self.terminal_authority is not None and (
            self.terminal_browser_owner is None
            or not self.terminal_authority.permits(self.terminal_browser_owner)
        ):
            raise ValueError("Terminal authority must bind to the local browser owner.")
        if self.conversation_id is not None and (
            not isinstance(self.conversation_id, str) or not self.conversation_id
        ):
            raise ValueError("Conversation identifier must be non-empty when supplied.")
        if self.expected_revision is not None and (
            isinstance(self.expected_revision, bool)
            or not isinstance(self.expected_revision, int)
            or self.expected_revision < 0
        ):
            raise ValueError("Conversation revision must be a non-negative integer.")
        if self.origin_sequence is not None and (
            isinstance(self.origin_sequence, bool)
            or not isinstance(self.origin_sequence, int)
            or self.origin_sequence < 1
        ):
            raise ValueError("Origin turn sequence must be a positive integer.")
        if self.interaction_id is not None and (
            not isinstance(self.interaction_id, str)
            or not self.interaction_id
            or len(self.interaction_id) > 200
            or any(character.isspace() or ord(character) < 32 for character in self.interaction_id)
        ):
            raise ValueError("Interaction identity must be a bounded opaque identifier.")


class ConversationTurnService:
    """Own ordinary Tori Conversation execution and process-wide admission.

    The service owns the real provider-facing ``ConversationSession`` call. A
    caller cannot supply either an operation label or an execution callback.
    Local capability handlers may share the same admitted foreground boundary,
    but a future client can complete an ordinary Tori turn without importing a
    presentation adapter.
    """

    def __init__(
        self,
        coordinator: OperationCoordinator,
        authority: OriginAuthority | None = None,
        remote_handlers: Mapping[
            ConversationOperation, Callable[[ConversationTurnRequest, ConversationSession], str]
        ] | None = None,
        activity_signal: Callable[[str, str], None] | None = None,
        initiative_reply_context: (
            Callable[[ConversationTurnRequest], str | None] | None
        ) = None,
    ) -> None:
        self._coordinator = coordinator
        self._sessions: dict[
            tuple[RequestOriginKind, str | None], ConversationSession
        ] = {}
        self._authority = authority or OriginAuthority()
        self._remote_handlers = dict(remote_handlers or {})
        self._activity_signal = activity_signal
        self._initiative_reply_context = initiative_reply_context
        self._admitted_initiative_context: str | None = None
        if set(self._remote_handlers) - {
            ConversationOperation.SEARCH_READ,
            ConversationOperation.REMINDERS_UPCOMING_READ,
            ConversationOperation.REMOTE_CHAT_TERMINATE_SELF,
        }:
            raise ValueError("Only approved Remote handlers may be registered.")

    @property
    def coordinator(self) -> OperationCoordinator:
        return self._coordinator

    def require_operation(
        self,
        request: ConversationTurnRequest,
        operation: ConversationOperation,
    ) -> None:
        self._authority.require(request.origin, operation)

    def acquire(
        self,
        request: ConversationTurnRequest,
    ) -> bool:
        """Authorize and admit a foreground application turn."""

        self.require_operation(request, ConversationOperation.CONVERSATION_REPLY)
        admitted = self._coordinator.acquire_foreground()
        if admitted:
            self._admitted_initiative_context = self._claim_initiative_context(
                request
            )
            operator_event(
                "conversation.turn.admitted", origin=request.origin.kind.value
            )
            self._record_meaningful_activity(request)
        return admitted

    def release(self) -> None:
        self._admitted_initiative_context = None
        self._coordinator.release_foreground()

    def configure_initiative_reply_context(
        self,
        provider: Callable[[ConversationTurnRequest], str | None] | None,
    ) -> None:
        """Bind the application-owned one-use context provider during composition."""

        self._initiative_reply_context = provider

    def attach_session(
        self,
        session: ConversationSession,
        *,
        origin_kind: RequestOriginKind,
        conversation_id: str | None,
    ) -> None:
        """Bind one client origin to its authoritative Conversation session.

        Each origin kind has one current Conversation binding. Rebinding local
        Web never replaces a future dedicated Remote Chat session.
        """

        if not isinstance(session, ConversationSession):
            raise TypeError("Conversation execution requires a Tori session.")
        if not isinstance(origin_kind, RequestOriginKind):
            raise TypeError("Conversation session origin must be application-owned.")
        if conversation_id is not None and (
            not isinstance(conversation_id, str) or not conversation_id
        ):
            raise ValueError("Conversation identifier must be non-empty when supplied.")
        for key in tuple(self._sessions):
            if key[0] is origin_kind:
                self._sessions.pop(key)
        self._sessions[(origin_kind, conversation_id)] = session

    def complete(
        self,
        request: ConversationTurnRequest,
        *,
        supplemental_system: str | None = None,
        response_transform: Callable[[str], str] | None = None,
        allow_external_knowledge_advisory: bool | None = None,
    ) -> str:
        """Complete one real ordinary turn without presentation machinery."""

        if not self.acquire(request):
            raise ConversationOperationBusyError(
                "Tori is already handling a foreground request."
            )
        try:
            return self.complete_admitted(
                request,
                supplemental_system=supplemental_system,
                response_transform=response_transform,
                allow_external_knowledge_advisory=(
                    allow_external_knowledge_advisory
                ),
            )
        finally:
            self.release()

    def complete_admitted(
        self,
        request: ConversationTurnRequest,
        *,
        supplemental_system: str | None = None,
        response_transform: Callable[[str], str] | None = None,
        model_action_handler: Callable[[str], str | None] | None = None,
        allow_external_knowledge_advisory: bool | None = None,
    ) -> str:
        """Complete a turn already admitted by the shared coordinator."""

        self._require_model_action_origin(request, model_action_handler)
        started = time.monotonic()
        origin = request.origin.kind.value
        operator_event("conversation.turn.started", origin=origin)
        try:
            operation = self._authorize_routed_turn(request)
            session = self._require_session(request)
            session.set_operator_origin(origin)
            handler = self._remote_handlers.get(operation)
            if (
                request.origin.kind is RequestOriginKind.DISCORD_REMOTE
                and handler is not None
            ):
                result = handler(request, session)
            else:
                supplemental_system = self._origin_context(
                    request,
                    _combine_supplemental(
                        supplemental_system,
                        self._take_initiative_context(),
                    ),
                )
                result = session.send(
                    request.text,
                    supplemental_system=supplemental_system,
                    response_transform=response_transform,
                    model_action_handler=model_action_handler,
                    allow_external_knowledge_advisory=allow_external_knowledge_advisory,
                    retrieve_memory=self._authority.permits(
                        request.origin, ConversationOperation.MEMORY_CONTEXT_RETRIEVE
                    ),
                    retrieve_knowledge=self._authority.permits(
                        request.origin, ConversationOperation.KNOWLEDGE_READ
                    ),
                )
        except OriginAuthorityError:
            raise
        except Exception as exc:
            operator_failure(
                "conversation.turn.failed",
                exc,
                code=getattr(exc, "code", "conversation_error"),
                origin=origin,
                traceback=True,
            )
            raise
        operator_event(
            "conversation.turn.completed",
            origin=origin,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    def stream(
        self,
        request: ConversationTurnRequest,
        *,
        supplemental_system: str | None = None,
        response_transform: Callable[[str], str] | None = None,
        allow_external_knowledge_advisory: bool | None = None,
    ) -> Iterator[str]:
        """Stream one real ordinary turn without presentation machinery."""

        if not self.acquire(request):
            raise ConversationOperationBusyError(
                "Tori is already handling a foreground request."
            )
        try:
            yield from self.stream_admitted(
                request,
                supplemental_system=supplemental_system,
                response_transform=response_transform,
                allow_external_knowledge_advisory=(
                    allow_external_knowledge_advisory
                ),
            )
        finally:
            self.release()

    def stream_admitted(
        self,
        request: ConversationTurnRequest,
        *,
        supplemental_system: str | None = None,
        response_transform: Callable[[str], str] | None = None,
        model_action_handler: Callable[[str], str | None] | None = None,
        allow_external_knowledge_advisory: bool | None = None,
        cancellation: ConversationStreamFence | None = None,
    ) -> Iterator[str]:
        """Stream a turn already admitted by the shared coordinator."""

        self._require_model_action_origin(request, model_action_handler)
        started = time.monotonic()
        origin = request.origin.kind.value
        operator_event("conversation.turn.started", origin=origin)
        try:
            operation = self._authorize_routed_turn(request)
            session = self._require_session(request)
            session.set_operator_origin(origin)
            handler = self._remote_handlers.get(operation)
            if (
                request.origin.kind is RequestOriginKind.DISCORD_REMOTE
                and handler is not None
            ):
                yield handler(request, session)
            else:
                supplemental_system = self._origin_context(
                    request,
                    _combine_supplemental(
                        supplemental_system,
                        self._take_initiative_context(),
                    ),
                )
                yield from session.stream(
                    request.text,
                    supplemental_system=supplemental_system,
                    response_transform=response_transform,
                    model_action_handler=model_action_handler,
                    allow_external_knowledge_advisory=allow_external_knowledge_advisory,
                    retrieve_memory=self._authority.permits(
                        request.origin, ConversationOperation.MEMORY_CONTEXT_RETRIEVE
                    ),
                    retrieve_knowledge=self._authority.permits(
                        request.origin, ConversationOperation.KNOWLEDGE_READ
                    ),
                    cancellation=cancellation,
                )
        except OriginAuthorityError:
            raise
        except ConversationStreamCancelled:
            operator_event("conversation.turn.cancelled", origin=origin)
            raise
        except Exception as exc:
            operator_failure(
                "conversation.turn.failed",
                exc,
                code=getattr(exc, "code", "conversation_error"),
                origin=origin,
                traceback=True,
            )
            raise
        operator_event(
            "conversation.turn.completed",
            origin=origin,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _origin_context(
        request: ConversationTurnRequest, supplemental_system: str | None
    ) -> str | None:
        if request.origin.kind is not RequestOriginKind.DISCORD_REMOTE:
            return supplemental_system
        if supplemental_system is None:
            return _REMOTE_CONVERSATION_BOUNDARY
        return supplemental_system.strip() + "\n\n" + _REMOTE_CONVERSATION_BOUNDARY

    def _require_session(
        self, request: ConversationTurnRequest
    ) -> ConversationSession:
        session = self._sessions.get(
            (request.origin.kind, request.conversation_id)
        )
        if session is None:
            raise ConversationApplicationUnavailableError(
                "Tori's Conversation session is not bound to this request."
            )
        return session

    def _record_meaningful_activity(self, request: ConversationTurnRequest) -> None:
        recorder = self._activity_signal
        if recorder is None:
            return
        if request.origin.kind is RequestOriginKind.DISCORD_REMOTE:
            assert request.origin.connector_id is not None
            assert request.origin.external_message_id is not None
            kind = "remote_turn"
            identity = (
                f"discord:{request.origin.connector_id}:"
                f"{request.origin.external_message_id}"
            )
        else:
            if request.interaction_id is None:
                return
            kind = "local_turn"
            identity = f"local:{request.interaction_id}"
        try:
            recorder(kind, identity)
        except Exception as exc:
            operator_failure(
                "companion_initiative.activity.failed",
                exc,
                code=getattr(exc, "code", "activity_unavailable"),
                origin=request.origin.kind.value,
            )

    def _claim_initiative_context(
        self, request: ConversationTurnRequest
    ) -> str | None:
        provider = self._initiative_reply_context
        if provider is None:
            return None
        try:
            result = provider(request)
            if result is None:
                return None
            if (
                not isinstance(result, str)
                or not result.strip()
                or len(result) > _MAX_ONE_USE_SUPPLEMENTAL_CONTEXT
                or "\x00" in result
            ):
                raise ValueError("Initiative reply context is malformed.")
            return result
        except Exception as exc:
            operator_failure(
                "companion_initiative.reply_context.failed",
                exc,
                code=getattr(exc, "code", "reply_context_unavailable"),
                origin=request.origin.kind.value,
            )
            return None

    def _take_initiative_context(self) -> str | None:
        result = self._admitted_initiative_context
        self._admitted_initiative_context = None
        return result

    @staticmethod
    def _require_model_action_origin(
        request: ConversationTurnRequest,
        handler: Callable[[str], str | None] | None,
    ) -> None:
        if handler is not None and (
            request.origin.kind is not RequestOriginKind.LOCAL_WEB
            or request.terminal_authority is None
            or request.terminal_browser_owner is None
            or not request.terminal_authority.permits(request.terminal_browser_owner)
        ):
            raise OriginAuthorityError(
                "A structured model terminal action requires this local browser turn."
            )

    def _authorize_routed_turn(self, request: ConversationTurnRequest) -> ConversationOperation:
        """Resolve the actual bounded operation before provider execution.

        This resolver can only reduce authority. Domain handlers remain
        responsible for recognizing and validating their own inputs; no result
        here authorizes mutation or execution.
        """

        operation = conversation_operation_for_text(request.text)
        search = self._remote_handlers.get(ConversationOperation.SEARCH_READ)
        accepts = getattr(search, "accepts_continuation", None)
        if (
            request.origin.kind is RequestOriginKind.DISCORD_REMOTE
            and accepts is not None
            and accepts(request)
        ):
            operation = ConversationOperation.SEARCH_READ
        if (
            request.origin.kind is RequestOriginKind.DISCORD_REMOTE
            and classify_confirmation(request.text) in {"affirmative", "negative"}
            and operation is not ConversationOperation.SEARCH_READ
        ):
            operation = ConversationOperation.LOCAL_PROPOSAL_CONFIRM
        try:
            self.require_operation(request, operation)
        except OriginAuthorityError as exc:
            operator_failure(
                "conversation.operation.denied",
                exc,
                code="origin_authority_denied",
                origin=request.origin.kind.value,
                category=operation.value,
            )
            raise
        if request.origin.kind is RequestOriginKind.DISCORD_REMOTE and operation in {
            ConversationOperation.SEARCH_READ,
            ConversationOperation.REMINDERS_UPCOMING_READ,
            ConversationOperation.REMOTE_CHAT_TERMINATE_SELF,
        } and operation not in self._remote_handlers:
            raise ConversationApplicationUnavailableError(
                "That remote Conversation operation is not implemented yet."
            )
        return operation


def conversation_operation_for_text(text: str) -> ConversationOperation:
    """Conservatively identify operations already owned by Tori domains.

    The function reuses current application recognizers and grants no
    authority. Unrecognized text is ordinary Conversation; because this
    service owns no mutation/execution handler, that fallback cannot execute a
    privileged operation.
    """

    normalized = text.strip()
    if is_remote_self_termination_command(normalized):
        return ConversationOperation.REMOTE_CHAT_TERMINATE_SELF
    if normalized.startswith("/") or "/run " in normalized.casefold():
        return ConversationOperation.LOCAL_COMMAND
    if capability_question(normalized) is not None or is_capability_discussion(
        normalized
    ):
        return ConversationOperation.CAPABILITIES_DESCRIBE_REMOTE
    if explicit_memory_text(normalized) is not None:
        return ConversationOperation.MEMORY_MUTATE
    sensitive = _sensitive_remote_operation(normalized)
    if sensitive is not None:
        return sensitive
    if _non_action_capability_discussion(normalized):
        return ConversationOperation.CONVERSATION_REPLY
    if (
        explicit_search_query(normalized) is not None
        or explicit_source_urls(normalized)
        or is_bare_search_request(normalized)
        or should_propose_search(normalized)
    ):
        return ConversationOperation.SEARCH_READ
    if _upcoming_reminder_read(normalized):
        return ConversationOperation.REMINDERS_UPCOMING_READ
    try:
        if (
            recognize_coding_work_request(normalized) is not None
            or recognize_delegated_work_intent(normalized) is not None
        ):
            return ConversationOperation.CODING_WORK_EXECUTE
    except CodingWorkConversationError:
        return ConversationOperation.CODING_WORK_EXECUTE
    mentioned = mentioned_capabilities(normalized)
    if not mentioned:
        return ConversationOperation.CONVERSATION_REPLY
    operation_by_capability = {
        "memory": ConversationOperation.MEMORY_MUTATE,
        "knowledge": ConversationOperation.KNOWLEDGE_READ,
        "search": ConversationOperation.SEARCH_READ,
        "finance": ConversationOperation.FINANCE_READ,
        "planning": ConversationOperation.PLANNING_READ,
        "tasks": ConversationOperation.REMINDER_MUTATE,
        "scheduled_work": ConversationOperation.SCHEDULED_WORK_MUTATE,
        "projects": ConversationOperation.PROJECT_READ,
        "host": ConversationOperation.HOST_READ,
        "coding_work": ConversationOperation.CODING_WORK_EXECUTE,
        "run": ConversationOperation.COMMAND_EXECUTE,
        "services": ConversationOperation.SERVICE_CONTROL,
        "backup": ConversationOperation.BACKUP_CREATE,
        "applications": ConversationOperation.APPLICATION_OPEN,
        "tts": ConversationOperation.SETTINGS_MUTATE,
    }
    return operation_by_capability.get(
        mentioned[0], ConversationOperation.CONVERSATION_REPLY
    )


def is_remote_self_termination_command(text: str) -> bool:
    """Recognize only the deliberately published owner-DM command phrase."""

    return " ".join(text.strip().casefold().split()) == (
        "terminate discord connection now"
    )


def _upcoming_reminder_read(text: str) -> bool:
    lowered = " ".join(text.casefold().replace("?", " ").replace(".", " ").split())
    asks_for_reminders = any(
        phrase in lowered
        for phrase in ("my reminders", "upcoming reminders", "reminders coming up", "what reminders")
    )
    mutation_words = {
        "add", "create", "set", "change", "edit", "delete", "remove",
        "cancel", "complete", "dismiss", "delay", "snooze", "move",
    }
    return asks_for_reminders and not mutation_words.intersection(lowered.split())


def _sensitive_remote_operation(text: str) -> ConversationOperation | None:
    """Conservatively reduce authority for concrete local/sensitive requests.

    Exact typed origin policy remains the security boundary. This parser never
    grants an operation and intentionally classifies broad imperative shapes as
    blocked even when the named target is unknown.
    """

    words = " ".join(
        text.casefold().replace("?", " ").replace(".", " ").replace(",", " ").split()
    ).split()
    if not words:
        return None
    service_actions = {"start", "stop", "restart", "enable", "disable"}
    launch_actions = {"open", "launch"}
    request_leads = {"can", "could", "would", "will", "please", "tori", "i"}
    if (
        words[0] in service_actions
        or (
            words[0] in request_leads
            and any(word in service_actions for word in words[:6])
        )
    ):
        return ConversationOperation.SERVICE_CONTROL
    if (
        words[0] in launch_actions
        or (
            words[0] in request_leads
            and any(word in launch_actions for word in words[:6])
        )
    ):
        return ConversationOperation.APPLICATION_OPEN
    host_terms = {
        "ip", "hostname", "cpu", "processor", "ram", "vram", "gpu",
        "uptime", "filesystem", "disk", "temperature",
    }
    if host_terms.intersection(words):
        return ConversationOperation.HOST_READ
    return None


def _non_action_capability_discussion(text: str) -> bool:
    tokens = " ".join(
        text.casefold().replace("?", " ").replace(".", " ").replace(",", " ").split()
    ).split()
    words = set(tokens)
    benign_action_indexes: set[int] = set()
    for index in range(len(tokens) - 1):
        if tokens[index:index + 2] == ["restart", "behavior"]:
            benign_action_indexes.add(index)
    for index in range(len(tokens) - 2):
        if tokens[index:index + 3] == ["should", "start", "with"]:
            benign_action_indexes.add(index + 1)
    dangerous_indexes = {
        index for index, token in enumerate(tokens)
        if token in {
            "start", "stop", "restart", "enable", "disable", "open", "launch",
            "create", "delete", "remove", "change", "edit", "run", "execute",
        }
    }
    return (
        not (dangerous_indexes - benign_action_indexes)
        and bool(words.intersection({
            "idea", "ideas", "architecture", "discussion", "behavior", "interesting",
        }))
    )


def _combine_supplemental(first: str | None, second: str | None) -> str | None:
    parts = tuple(item.strip() for item in (first, second) if item is not None)
    return "\n\n".join(parts) or None


class ConversationOperationBusyError(RuntimeError):
    """The shared foreground boundary is already owned."""

    code = "busy"


class ConversationApplicationUnavailableError(RuntimeError):
    """The application Conversation session has not been composed."""

    code = "conversation_unavailable"
