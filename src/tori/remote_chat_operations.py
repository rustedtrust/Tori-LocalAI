"""Approved Remote Chat V1 read handlers at the shared Conversation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from .capabilities import CapabilityResult
from .conversation import ConversationSession
from .conversation_application import ConversationTurnRequest
from .operator_observability import operator_event, operator_failure
from .request_origin import ConversationOperation
from .search import (
    BARE_SEARCH_CLARIFICATION_MESSAGE,
    EXTERNAL_KNOWLEDGE_PROPOSAL_MESSAGE,
    FRESHNESS_SEARCH_PROPOSAL_MESSAGE,
    SEARCH_UNAVAILABLE_MESSAGE,
    SearchError,
    SearchConsent,
    classify_confirmation,
    build_search_context,
    format_search_answer,
    search_category_for_query,
)
from .search_application import SearchApplicationPolicy
from .search_port import SearchPort
from .source_retrieval import (
    SourceRetrievalPort,
    retrieve_direct_url_evidence,
    retrieve_search_evidence,
)
from .task_reminder_application import TaskReminderApplicationService
from .user_settings import CapabilitySettingsController, SEARCH_DISABLED_MESSAGE, SETTINGS_FAILURE_MESSAGE


REMOTE_SEARCH_LOCATION_CLARIFICATION = (
    "Which city or location should I use for that weather request?"
)
REMOTE_SELF_TERMINATION_MESSAGE = (
    "Discord Remote Chat is disabled. Disconnecting now."
)


class RemoteSearchHandler:
    """Current Search policy with consent fenced to exact verified Remote identity."""

    def __init__(
        self,
        web_search: SearchPort | None,
        source_retrieval: SourceRetrievalPort | None,
        capability_settings: CapabilitySettingsController | None,
        *,
        clock,
    ) -> None:  # type: ignore[no-untyped-def]
        self._web_search = web_search
        self._source_retrieval = source_retrieval
        self._policy = SearchApplicationPolicy(
            SearchConsent(clock=clock),
            implementation_available=lambda: (
                self._web_search is not None and self._web_search.available
            ),
            capability_settings=capability_settings,
            source_retrieval_available=lambda: self._source_retrieval is not None,
        )
        self._pending_origin: tuple[str, str, tuple[str, int]] | None = None

    def accepts_continuation(self, request: ConversationTurnRequest) -> bool:
        pending = self._pending_origin
        return (
            pending is not None
            and pending[0] == self._scope(request)
            and request.origin.external_message_id != pending[1]
            and self._sequence(request)[0] == pending[2][0]
            and self._sequence(request)[1] == pending[2][1] + 1
        )

    def __call__(
        self, request: ConversationTurnRequest, session: ConversationSession
    ) -> str:
        scope = self._scope(request)
        decision = self._policy.evaluate(request.text, conversation_id=scope)
        if decision.disposition in {"proposal", "weather_location_clarification"}:
            assert request.origin.external_message_id is not None
            self._pending_origin = (
                scope, request.origin.external_message_id, self._sequence(request)
            )
            operator_event(
                "remote_chat.search.continuation_created",
                origin="discord_remote",
            )
        if decision.disposition == "proposal":
            return (
                EXTERNAL_KNOWLEDGE_PROPOSAL_MESSAGE
                if decision.source == "external_knowledge"
                else FRESHNESS_SEARCH_PROPOSAL_MESSAGE
            )
        if decision.disposition != "weather_location_clarification":
            self._pending_origin = None
        fixed = {
            "declined": "Okay. I won't search for that.",
            "clarification": BARE_SEARCH_CLARIFICATION_MESSAGE,
            "weather_location_clarification": REMOTE_SEARCH_LOCATION_CLARIFICATION,
            "disabled": SEARCH_DISABLED_MESSAGE,
            "unavailable": SEARCH_UNAVAILABLE_MESSAGE,
            "settings_failure": SETTINGS_FAILURE_MESSAGE,
        }.get(decision.disposition)
        if fixed is not None:
            return fixed
        if (
            decision.disposition == "normal"
            and classify_confirmation(request.text) in {"affirmative", "negative"}
        ):
            return "That Remote Search confirmation is no longer pending. Nothing was searched."
        if decision.disposition != "authorized":
            return session.send(
                request.text,
                supplemental_system=_remote_boundary(),
                retrieve_memory=True,
                retrieve_knowledge=False,
            )
        try:
            result = self._retrieve(
                request.text, decision.query, decision.source_urls
            )
        except SearchError as exc:
            operator_failure(
                "remote_chat.search.failed",
                exc,
                code="search_unavailable",
                origin="discord_remote",
            )
            # Consent has already been consumed. A bounded Search failure must
            # still produce a safe Remote reply rather than disappearing at the
            # transport-neutral worker boundary.
            return SEARCH_UNAVAILABLE_MESSAGE
        operator_event(
            "remote_chat.search.retrieval_completed",
            origin="discord_remote",
            result_count=len(result.sources),
        )
        if not result.sources:
            return format_search_answer(
                "", (), direct_source=result.capability_id == "web_source_retrieval"
            )
        # A consent reply grants authority but is not the question to answer.
        # SearchDecision.query retains the validated original request, unlike
        # the transport event text (for example, "Yes, please.").
        synthesis_request = (
            decision.query if decision.source == "consent" else request.text
        )
        assert synthesis_request is not None
        operator_event(
            "remote_chat.search.synthesis_started",
            origin="discord_remote",
        )
        try:
            answer = session.send(
                synthesis_request,
                supplemental_system=(
                    build_search_context(result) + "\n\n" + _remote_boundary()
                ),
                response_transform=lambda answer: format_search_answer(
                    answer,
                    result.sources,
                    direct_source=result.capability_id == "web_source_retrieval",
                    failed_source_count=int(
                        (result.metadata or {}).get("failed_source_count", 0)
                    ),
                ),
                allow_external_knowledge_advisory=False,
                retrieve_memory=True,
                retrieve_knowledge=False,
            )
        except Exception as exc:
            operator_failure(
                "remote_chat.search.synthesis_failed",
                exc,
                code=getattr(exc, "code", "synthesis_error"),
                origin="discord_remote",
            )
            raise
        operator_event(
            "remote_chat.search.synthesis_completed",
            origin="discord_remote",
        )
        return answer

    def clear(self) -> None:
        self._pending_origin = None
        self._policy.clear()

    def _retrieve(
        self, original: str, query: str | None, source_urls: tuple[str, ...]
    ) -> CapabilityResult:
        if source_urls:
            assert self._source_retrieval is not None
            return retrieve_direct_url_evidence(original, source_urls, self._source_retrieval)
        assert query is not None and self._web_search is not None
        result = self._web_search.search(
            query, category=search_category_for_query(query)
        )
        if self._source_retrieval is not None:
            result = retrieve_search_evidence(result, self._source_retrieval)
        return result

    @staticmethod
    def _scope(request: ConversationTurnRequest) -> str:
        origin = request.origin
        return "\x1f".join((
            request.conversation_id or "",
            origin.kind.value,
            origin.connector_id or "",
            origin.external_actor_id or "",
            origin.external_conversation_id or "",
        ))

    @staticmethod
    def _sequence(request: ConversationTurnRequest) -> tuple[str, int]:
        if request.origin_sequence is not None:
            return "origin", request.origin_sequence
        if request.expected_revision is None:
            return "archive", 0
        return "archive", request.expected_revision


@dataclass(slots=True)
class RemoteUpcomingReminderHandler:
    """Read-only bounded projection; no mutating service method is reachable."""

    application: TaskReminderApplicationService

    def __call__(
        self, request: ConversationTurnRequest, session: ConversationSession
    ) -> str:
        current = tuple(
            item for item in self.application.list_reminders()
            if item.status in {"scheduled", "due"}
        )[:20]
        if not current:
            projection = "There are no scheduled or due reminders."
        else:
            lines = ["Upcoming reminders (read-only):"]
            lines.extend(
                f"- {item.reminder_text} — {item.scheduled_start_utc} ({item.status})"
                for item in current
            )
            projection = "\n".join(lines)
        return session.send(
            request.text,
            supplemental_system=(
                projection
                + "\nAnswer only from this reminder projection. Do not claim any reminder change.\n\n"
                + _remote_boundary()
            ),
            retrieve_memory=True,
            retrieve_knowledge=False,
        )


@dataclass(slots=True)
class RemoteSelfTerminationHandler:
    """Invoke only the application-owned authority-reducing connector fence."""

    terminate: Callable[[ConversationTurnRequest], None]

    def __call__(
        self, request: ConversationTurnRequest, _session: ConversationSession
    ) -> str:
        self.terminate(request)
        # The durable generation fence normally suppresses this best-effort
        # acknowledgement before physical send entry. It remains useful if a
        # future transport can prove a safe pre-disconnect acknowledgement.
        return REMOTE_SELF_TERMINATION_MESSAGE


def remote_handlers(
    *,
    search: RemoteSearchHandler | None = None,
    reminders: RemoteUpcomingReminderHandler | None = None,
    terminate_self: RemoteSelfTerminationHandler | None = None,
) -> dict[ConversationOperation, object]:
    handlers: dict[ConversationOperation, object] = {}
    if search is not None:
        handlers[ConversationOperation.SEARCH_READ] = search
    if reminders is not None:
        handlers[ConversationOperation.REMINDERS_UPCOMING_READ] = reminders
    if terminate_self is not None:
        handlers[ConversationOperation.REMOTE_CHAT_TERMINATE_SELF] = terminate_self
    return handlers


def _remote_boundary() -> str:
    return (
        "This is Remote Chat. Only ordinary conversation, curated Memory context, "
        "approved Search, upcoming-reminder reads, and non-sensitive capability "
        "discussion are available. Never claim local execution, mutation, or access."
    )
