"""Provider-neutral chat domain service over the canonical archive store."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import os

from .conversation_archive import (
    ApplicationEventRecord,
    ArchiveConflictError,
    ArchiveCorruptError,
    ArchiveDivergenceError,
    ArchiveEntry,
    ArchivedChat,
    ArchiveNotFoundError,
    ArchiveStaleRevisionError,
    ArchiveUnavailableError,
    ArchiveValidationError,
    ArchiveVerificationError,
    ArchiveVersionError,
    ChatMetadata,
    ConversationArchiveError,
    ConversationArchiveStore,
    MemoryExtractionRecord,
    MemoryExtractionRequest,
    ProjectDecisionRecord,
    ProjectContextReceiptInput,
    ProjectContextReceiptRecord,
    ProjectLinkRecord,
    ProjectPlanItemRecord,
    ProjectQuestionRecord,
    ProjectRecord,
    ProjectResumeMetadata,
    ProjectStateRecord,
    is_provisional_chat_label,
)
from .providers import ChatMessage
from .context import ContextPolicy
from .model_catalog import ModelCatalogError, ModelIdentity, validate_model_identity
from .response_normalization import contains_tori_control_data
from .user_settings import SEARCH_DISABLED_MESSAGE, SETTINGS_FAILURE_MESSAGE


_TRANSIENT_APPLICATION_ASSISTANT_NOTICES = frozenset(
    (SEARCH_DISABLED_MESSAGE, SETTINGS_FAILURE_MESSAGE)
)


class ChatServiceError(RuntimeError):
    """Stable, safe application-domain archive failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ChatItem:
    """Immutable list-safe chat metadata with no transcript preview."""

    identifier: str
    label: str
    created_at: str
    updated_at: str
    last_opened_at: str | None
    revision: int
    first_provider: str | None
    first_model: str | None
    latest_provider: str | None
    latest_model: str | None
    selected_provider_name: str
    selected_model_name: str
    entry_count: int
    completed_turn_count: int
    selected_context_policy: str = "auto"
    project_id: str | None = None

    @property
    def selected_model(self) -> ModelIdentity:
        """Return the durable selection independently of execution attribution."""

        try:
            return validate_model_identity(
                self.selected_provider_name, self.selected_model_name
            )
        except ModelCatalogError as exc:
            raise ChatServiceError(
                "The archived conversation has invalid model metadata.",
                code="invalid_record",
            ) from exc

    @property
    def context_policy(self) -> ContextPolicy:
        try:
            return ContextPolicy.parse(self.selected_context_policy)
        except ValueError as exc:
            raise ChatServiceError(
                "The archived conversation has invalid context metadata.",
                code="invalid_record",
            ) from exc


@dataclass(frozen=True, slots=True)
class ChatDetail:
    """One complete immutable application-domain chat."""

    metadata: ChatItem
    entries: tuple[ArchiveEntry, ...]


def completed_model_history(
    entries: Sequence[ArchiveEntry],
    *,
    max_messages: int | None = None,
) -> tuple[ChatMessage, ...]:
    """Derive the latest complete ordinary exchanges from visible archive data."""

    if max_messages is not None and (
        max_messages < 2 or max_messages % 2 != 0
    ):
        raise ValueError("max_messages must be an even number of at least 2.")
    completed: list[ChatMessage] = []
    pending_user: str | None = None
    for entry in entries:
        if not isinstance(entry, ArchiveEntry):
            raise ValueError("Every archived transcript item must be an ArchiveEntry.")
        if entry.role == "user":
            pending_user = entry.text if isinstance(entry.text, str) and entry.text.strip() else None
        elif entry.role == "assistant":
            if entry.application_event_id is not None:
                # Application-authored presentation neither completes nor
                # consumes an ordinary pending user turn.
                continue
            if (
                pending_user is not None
                and isinstance(entry.text, str)
                and entry.text.strip()
                and not contains_tori_control_data(entry.text)
                and not (
                    entry.provider is None
                    and entry.model is None
                    and entry.text in _TRANSIENT_APPLICATION_ASSISTANT_NOTICES
                )
            ):
                completed.extend(
                    (
                        ChatMessage(role="user", content=pending_user),
                        ChatMessage(role="assistant", content=entry.text),
                    )
                )
            pending_user = None
        elif entry.role == "error":
            pending_user = None
        elif entry.role not in {"system", "warning"}:
            raise ValueError("The archived transcript contains an unsupported role.")
    return (
        tuple(completed)
        if max_messages is None
        else tuple(completed[-max_messages:])
    )


# A descriptive alias for later integration call sites.
derive_completed_model_history = completed_model_history


class ChatService:
    """Expose narrow chat-domain operations without transport or provider routing."""

    def __init__(self, store: ConversationArchiveStore) -> None:
        self._store = store

    def initialize(self) -> None:
        self._call(self._store.initialize)

    def list_chats(self) -> tuple[ChatItem, ...]:
        return tuple(
            _chat_item(item)
            for item in self._call(self._store.list_chats)
        )

    def list_project_chats(self, project_id: str) -> tuple[ChatItem, ...]:
        """Return deterministic metadata only for chats associated to a Project."""

        return tuple(
            _chat_item(item)
            for item in self._project_call(
                self._store.list_project_chats, project_id
            )
        )

    def active_chat_metadata(self) -> ChatItem | None:
        item = self._call(self._store.get_active_chat_metadata)
        return None if item is None else _chat_item(item)

    def get_chat(self, identifier: str) -> ChatDetail:
        return _chat_detail(self._call(self._store.get_chat, identifier))

    def create_chat(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        provider: str,
        model: str,
        identifier: str | None = None,
        label: str | None = None,
        select_active: bool = True,
        context_policy: ContextPolicy = ContextPolicy(),
        project_id: str | None = None,
        memory_extraction: MemoryExtractionRequest | None = None,
        project_context_receipt: ProjectContextReceiptInput | None = None,
    ) -> ChatDetail:
        chat = self._call(
            self._store.create_chat,
            entries,
            provider=provider,
            model=model,
            identifier=identifier,
            label=label,
            select_active=select_active,
            context_policy=context_policy.canonical,
            project_id=project_id,
            memory_extraction=memory_extraction,
            project_context_receipt=project_context_receipt,
        )
        return _chat_detail(chat)

    def establish_scheduled_work_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        identifier: str | None = None,
        expected_revision: int | None = None,
    ) -> ChatDetail:
        """Create or reconcile the narrow confirmed Scheduled Work origin."""

        if identifier is None:
            if expected_revision is not None:
                raise ChatServiceError(
                    "A new Scheduled Work origin cannot have a prior revision.",
                    code="invalid_record",
                )
            chat = self._call(
                self._store.create_scheduled_work_origin,
                entries,
                selected_provider=selected_provider,
                selected_model=selected_model,
            )
        else:
            if expected_revision is None:
                raise ChatServiceError(
                    "An existing Scheduled Work origin requires its revision.",
                    code="invalid_record",
                )
            chat = self._call(
                self._store.reconcile_scheduled_work_origin,
                identifier,
                entries,
                expected_revision=expected_revision,
            )
        detail = _chat_detail(chat)
        selected = self.active_chat_id()
        if selected != detail.metadata.identifier:
            raise ChatServiceError(
                "The Scheduled Work origin could not be selected durably.",
                code="verification_failed",
            )
        return detail

    def create_project_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
    ) -> ChatDetail:
        chat = self._call(
            self._store.create_project_proposal_origin,
            entries,
            selected_provider=selected_provider,
            selected_model=selected_model,
        )
        return _chat_detail(chat)

    def create_coding_work_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        project_id: str | None = None,
    ) -> ChatDetail:
        chat = self._call(
            self._store.create_coding_work_proposal_origin,
            entries,
            selected_provider=selected_provider,
            selected_model=selected_model,
            project_id=project_id,
        )
        return _chat_detail(chat)

    def create_terminal_proposal_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
        project_id: str | None = None,
        context_policy: ContextPolicy = ContextPolicy(),
    ) -> ChatDetail:
        chat = self._call(
            self._store.create_terminal_proposal_origin,
            entries,
            selected_provider=selected_provider,
            selected_model=selected_model,
            project_id=project_id,
            context_policy=context_policy.canonical,
        )
        return _chat_detail(chat)

    def create_planning_origin(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        selected_provider: str,
        selected_model: str,
    ) -> ChatDetail:
        chat = self._call(
            self._store.create_planning_origin,
            entries,
            selected_provider=selected_provider,
            selected_model=selected_model,
        )
        return _chat_detail(chat)

    def reconcile_project_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ChatDetail:
        return _chat_detail(self._call(
            self._store.reconcile_project_origin,
            identifier,
            entries,
            expected_revision=expected_revision,
        ))

    def reconcile_coding_work_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ChatDetail:
        return _chat_detail(self._call(
            self._store.reconcile_coding_work_origin,
            identifier,
            entries,
            expected_revision=expected_revision,
        ))

    def reconcile_planning_origin(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
    ) -> ChatDetail:
        return _chat_detail(self._call(
            self._store.reconcile_planning_origin,
            identifier,
            entries,
            expected_revision=expected_revision,
        ))

    def reconcile_chat(
        self,
        identifier: str,
        entries: Sequence[ArchiveEntry],
        *,
        expected_revision: int,
        provider: str | None = None,
        model: str | None = None,
        label: str | None = None,
        memory_extraction: MemoryExtractionRequest | None = None,
        project_context_receipt: ProjectContextReceiptInput | None = None,
    ) -> ChatDetail:
        chat = self._call(
            self._store.reconcile_chat,
            identifier,
            entries,
            expected_revision=expected_revision,
            provider=provider,
            model=model,
            label=label,
            memory_extraction=memory_extraction,
            project_context_receipt=project_context_receipt,
        )
        return _chat_detail(chat)

    def get_memory_extraction(self, identifier: str) -> MemoryExtractionRecord | None:
        return self._call(self._store.get_memory_extraction, identifier)

    def create_project(self, **values: object) -> ProjectRecord:
        return self._project_call(self._store.create_project, **values)

    def get_project(self, identifier: str) -> ProjectRecord:
        return self._call(self._store.get_project, identifier)

    def list_project_context_receipts(
        self, chat_id: str
    ) -> tuple[ProjectContextReceiptRecord, ...]:
        return self._call(self._store.list_project_context_receipts, chat_id)

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        return self._call(self._store.list_projects)

    def list_project_resume_metadata(self) -> tuple[ProjectResumeMetadata, ...]:
        return self._call(self._store.list_project_resume_metadata)

    def get_project_state(self, project_id: str) -> ProjectStateRecord | None:
        return self._project_call(self._store.get_project_state, project_id)

    def update_project_state(
        self, project_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectStateRecord]:
        return self._project_call(self._store.update_project_state, project_id, **values)

    def list_project_decisions(
        self, project_id: str, *, active_only: bool = False
    ) -> tuple[ProjectDecisionRecord, ...]:
        operation = (
            self._store.list_active_project_decisions
            if active_only else self._store.list_project_decisions
        )
        return self._project_call(operation, project_id)

    def add_project_decision(
        self, project_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        return self._project_call(self._store.add_project_decision, project_id, **values)

    def mark_project_decision_important(
        self, project_id: str, decision_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        return self._project_call(
            self._store.mark_project_decision_important,
            project_id,
            decision_id,
            **values,
        )

    def supersede_project_decision(
        self, project_id: str, predecessor_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectDecisionRecord]:
        return self._project_call(
            self._store.supersede_project_decision,
            project_id,
            predecessor_id,
            **values,
        )

    def list_project_questions(
        self, project_id: str, *, active_only: bool = False
    ) -> tuple[ProjectQuestionRecord, ...]:
        operation = (
            self._store.list_active_project_questions
            if active_only else self._store.list_project_questions
        )
        return self._project_call(operation, project_id)

    def add_project_question(
        self, project_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectQuestionRecord]:
        return self._project_call(self._store.add_project_question, project_id, **values)

    def transition_project_question(
        self, project_id: str, question_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectQuestionRecord]:
        return self._project_call(
            self._store.transition_project_question,
            project_id,
            question_id,
            **values,
        )

    def list_project_plan_items(
        self, project_id: str
    ) -> tuple[ProjectPlanItemRecord, ...]:
        return self._project_call(self._store.list_project_plan_items, project_id)

    def add_project_plan_item(
        self, project_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        return self._project_call(self._store.add_project_plan_item, project_id, **values)

    def update_project_plan_item(
        self, project_id: str, plan_item_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        return self._project_call(
            self._store.update_project_plan_item,
            project_id,
            plan_item_id,
            **values,
        )

    def transition_project_plan_item(
        self, project_id: str, plan_item_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectPlanItemRecord]:
        return self._project_call(
            self._store.transition_project_plan_item,
            project_id,
            plan_item_id,
            **values,
        )

    def list_project_links(self, project_id: str) -> tuple[ProjectLinkRecord, ...]:
        return self._project_call(self._store.list_project_links, project_id)

    def add_project_link(
        self, project_id: str, **values: object
    ) -> tuple[ProjectRecord, ProjectLinkRecord]:
        return self._project_call(self._store.add_project_link, project_id, **values)

    def remove_project_link(
        self, project_id: str, link_id: str, **values: object
    ) -> ProjectRecord:
        return self._project_call(
            self._store.remove_project_link, project_id, link_id, **values
        )

    def update_project(self, identifier: str, **values: object) -> ProjectRecord:
        return self._project_call(self._store.update_project, identifier, **values)

    def associate_project(
        self, chat_id: str, project_id: str | None, *, expected_revision: int
    ) -> ChatDetail:
        return _chat_detail(self._call(
            self._store.associate_chat,
            chat_id,
            project_id,
            expected_revision=expected_revision,
        ))

    def delete_project(self, identifier: str, *, expected_revision: int) -> None:
        self._call(
            self._store.delete_project, identifier, expected_revision=expected_revision
        )

    def list_memory_extractions(self) -> tuple[MemoryExtractionRecord, ...]:
        return self._call(self._store.list_memory_extractions)

    def claim_next_memory_extraction(
        self, process_incarnation: str
    ) -> MemoryExtractionRecord | None:
        return self._call(
            self._store.claim_next_memory_extraction, process_incarnation
        )

    def transition_memory_extraction(
        self, identifier: str, **values: object
    ) -> MemoryExtractionRecord:
        return self._call(
            self._store.transition_memory_extraction, identifier, **values
        )

    def claim_memory_confirmation(
        self, identifier: str, **values: object
    ) -> MemoryExtractionRecord:
        return self._call(
            self._store.claim_memory_confirmation, identifier, **values
        )

    def extraction_source_entries(
        self, record: MemoryExtractionRecord
    ) -> tuple[ArchiveEntry, ArchiveEntry] | None:
        return self._call(self._store.extraction_source_entries, record)

    def append_application_event(
        self,
        identifier: str,
        *,
        expected_revision: int,
        event_id: str,
        event_type: str,
        text: str,
    ) -> ChatDetail:
        return _chat_detail(self._call(
            self._store.append_application_event,
            identifier,
            expected_revision=expected_revision,
            event_id=event_id,
            event_type=event_type,
            text=text,
        ))

    def get_application_event(self, event_id: str) -> ApplicationEventRecord | None:
        return self._call(self._store.get_application_event, event_id)

    def open_chat(self, identifier: str, *, expected_revision: int) -> ChatDetail:
        return _chat_detail(
            self._call(
                self._store.mark_chat_opened,
                identifier,
                expected_revision=expected_revision,
                select_active=True,
            )
        )

    def active_chat_id(self) -> str | None:
        return self._call(self._store.get_active_chat_id)

    def select_chat(
        self, identifier: str, *, expected_revision: int | None = None
    ) -> str:
        result = self._call(
            self._store.set_active_chat,
            identifier,
            expected_revision=expected_revision,
        )
        assert result is not None
        return result

    def select_model(
        self,
        identifier: str,
        *,
        expected_revision: int,
        provider: str,
        model: str,
    ) -> ChatDetail:
        """Durably change selection without modifying transcript entries."""

        try:
            identity = validate_model_identity(provider, model)
        except ModelCatalogError as exc:
            raise ChatServiceError(
                "The selected model identity is invalid.", code="invalid_record"
            ) from exc
        current = self.get_chat(identifier)
        if current.metadata.revision != expected_revision:
            raise ChatServiceError(
                "The chat changed after it was loaded; refresh and try again.",
                code="stale_revision",
            )
        return _chat_detail(self._call(
            self._store.select_chat_model,
            identifier,
            expected_revision=expected_revision,
            provider=identity.provider,
            model=identity.model,
        ))

    def select_context(
        self,
        identifier: str,
        *,
        expected_revision: int,
        policy: ContextPolicy,
    ) -> ChatDetail:
        current = self.get_chat(identifier)
        if current.metadata.revision != expected_revision:
            raise ChatServiceError(
                "The chat changed after it was loaded; refresh and try again.",
                code="stale_revision",
            )
        return _chat_detail(self._call(
            self._store.select_chat_context,
            identifier,
            expected_revision=expected_revision,
            policy=policy.canonical,
        ))

    def select_configuration(
        self,
        identifier: str,
        *,
        expected_revision: int,
        provider: str,
        model: str,
        policy: ContextPolicy,
    ) -> ChatDetail:
        """Atomically persist the browser's model and context selection."""

        try:
            identity = validate_model_identity(provider, model)
        except ModelCatalogError as exc:
            raise ChatServiceError(
                "The selected model identity is invalid.", code="invalid_record"
            ) from exc
        current = self.get_chat(identifier)
        if current.metadata.revision != expected_revision:
            raise ChatServiceError(
                "The chat changed after it was loaded; refresh and try again.",
                code="stale_revision",
            )
        return _chat_detail(self._call(
            self._store.select_chat_configuration,
            identifier,
            expected_revision=expected_revision,
            provider=identity.provider,
            model=identity.model,
            policy=policy.canonical,
        ))

    def new_session(self) -> None:
        """Clear selection without deleting or persisting an empty chat."""

        if not os.path.lexists(self._store.path):
            return
        self._call(self._store.set_active_chat, None)

    def clear_active_chat(self) -> None:
        self.new_session()

    def delete_chat(self, identifier: str, *, expected_revision: int) -> ChatItem:
        return _chat_item(
            self._call(
                self._store.delete_chat,
                identifier,
                expected_revision=expected_revision,
            )
        )

    def rename_chat(
        self, identifier: str, *, expected_revision: int, label: str
    ) -> ChatDetail:
        """Revision-safely apply one user-owned display title."""

        if is_provisional_chat_label(label):
            raise ChatServiceError(
                "Choose a more specific conversation title.",
                code="invalid_record",
            )
        current = self.get_chat(identifier)
        if current.metadata.revision != expected_revision:
            raise ChatServiceError(
                "The chat changed after it was loaded; refresh and try again.",
                code="stale_revision",
            )
        return self.reconcile_chat(
            current.metadata.identifier,
            current.entries,
            expected_revision=expected_revision,
            label=label,
        )

    def model_history(self, identifier: str) -> tuple[ChatMessage, ...]:
        return completed_model_history(self.get_chat(identifier).entries)

    @staticmethod
    def _call(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return function(*args, **kwargs)
        except ConversationArchiveError as exc:
            raise _service_error(exc) from exc

    @staticmethod
    def _project_call(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return function(*args, **kwargs)
        except ArchiveValidationError as exc:
            # Project field validation messages are fixed application text and
            # safe to preserve.  Relabeling them as invalid chat data obscures
            # the actual user-correctable Project form error.
            raise ChatServiceError(str(exc), code="invalid_record") from exc
        except ConversationArchiveError as exc:
            raise _service_error(exc) from exc


def _chat_item(item: ChatMetadata) -> ChatItem:
    return ChatItem(
        identifier=item.identifier,
        label=item.label,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_opened_at=item.last_opened_at,
        revision=item.revision,
        first_provider=item.first_provider,
        first_model=item.first_model,
        latest_provider=item.latest_provider,
        latest_model=item.latest_model,
        selected_provider_name=item.selected_provider,
        selected_model_name=item.selected_model,
        entry_count=item.entry_count,
        completed_turn_count=item.completed_turn_count,
        selected_context_policy=item.selected_context_policy,
        project_id=item.project_id,
    )


def _chat_detail(item: ArchivedChat) -> ChatDetail:
    return ChatDetail(metadata=_chat_item(item.metadata), entries=item.entries)


def _service_error(error: ConversationArchiveError) -> ChatServiceError:
    if isinstance(error, ArchiveNotFoundError):
        return ChatServiceError("The selected chat was not found.", code="not_found")
    if isinstance(error, ArchiveStaleRevisionError):
        return ChatServiceError(
            "The chat changed after it was loaded; refresh and try again.",
            code="stale_revision",
        )
    if isinstance(error, ArchiveDivergenceError):
        return ChatServiceError(
            "The supplied conversation no longer matches the archived chat.",
            code="transcript_diverged",
        )
    if isinstance(error, ArchiveValidationError):
        return ChatServiceError("The chat data is invalid.", code="invalid_record")
    if isinstance(error, ArchiveVersionError):
        return ChatServiceError(
            "The conversation archive uses an unsupported version.",
            code="unsupported_version",
        )
    if isinstance(error, ArchiveCorruptError):
        return ChatServiceError(
            "The conversation archive is invalid or corrupt.", code="store_corrupt"
        )
    if isinstance(error, ArchiveVerificationError):
        return ChatServiceError(
            "The conversation archive change could not be verified.",
            code="verification_failed",
        )
    if isinstance(error, ArchiveConflictError):
        return ChatServiceError("The chat change conflicts with current data.", code="conflict")
    if isinstance(error, ArchiveUnavailableError):
        return ChatServiceError(
            "The conversation archive is unavailable.", code="store_unavailable"
        )
    return ChatServiceError("The conversation archive operation failed.", code="store_error")
