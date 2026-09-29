"""Presentation-neutral application use cases for canonical Projects."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar

from .chats import ChatDetail, ChatItem, ChatService, ChatServiceError
from .conversation_archive import (
    ArchiveValidationError,
    ProjectDecisionRecord,
    ProjectLinkRecord,
    ProjectPlanItemRecord,
    ProjectQuestionRecord,
    ProjectRecord,
    ProjectStateRecord,
    validate_project_link_target,
)
from .project_related import (
    ProjectRelatedSources, ProjectRelatedWork, merge_project_activity,
)


ProjectStatus = Literal["active", "paused", "completed"]
ProjectQuestionState = Literal["open", "resolved", "deferred", "dismissed"]
ProjectPlanState = Literal["planned", "active", "blocked", "deferred", "completed"]
ProjectLinkTargetType = Literal[
    "night_owl_finding", "scheduled_work_definition", "knowledge_source"
]
ProjectChild = TypeVar(
    "ProjectChild",
    ProjectStateRecord,
    ProjectDecisionRecord,
    ProjectQuestionRecord,
    ProjectPlanItemRecord,
    ProjectLinkRecord,
)
ProjectLinkTargetVerifier = Callable[[str, str], bool]
PROJECT_STATE_NOT_RECORDED = "Not yet recorded"
WHERE_WE_ARE_OPEN_QUESTION_LIMIT = 5


@dataclass(frozen=True, slots=True)
class ProjectMutationResult(Generic[ProjectChild]):
    """One verified aggregate revision and the exact child result it owns."""

    project: ProjectRecord
    record: ProjectChild


@dataclass(frozen=True, slots=True)
class ProjectLegacyContinuity:
    """Exact legacy compatibility data kept separate from structured truth."""

    present: bool
    text: str


@dataclass(frozen=True, slots=True)
class ProjectHomeFreshness:
    """Canonical revision and timestamp evidence used by one home projection."""

    project_revision: int
    project_updated_at: str
    structured_updated_at: str | None
    conversations_updated_at: str | None


@dataclass(frozen=True, slots=True)
class ProjectWhereWeAre:
    """Deterministic current-state projection containing no model inference."""

    objective: str
    status: str
    phase: str
    current_focus: str
    checkpoint: str
    structured_state_present: bool
    next_planned_step: ProjectPlanItemRecord | None
    active_plan_items: tuple[ProjectPlanItemRecord, ...]
    blocked_plan_items: tuple[ProjectPlanItemRecord, ...]
    open_questions: tuple[ProjectQuestionRecord, ...]
    open_question_count: int
    deferred_question_count: int
    last_updated_at: str


@dataclass(frozen=True, slots=True)
class ProjectHome:
    """Presentation-neutral Project continuity view over canonical records."""

    project: ProjectRecord
    workspace_state: ProjectStateRecord | None
    where_we_are: ProjectWhereWeAre
    active_decisions: tuple[ProjectDecisionRecord, ...]
    superseded_decisions: tuple[ProjectDecisionRecord, ...]
    active_questions: tuple[ProjectQuestionRecord, ...]
    closed_questions: tuple[ProjectQuestionRecord, ...]
    plan_items: tuple[ProjectPlanItemRecord, ...]
    conversations: tuple[ChatItem, ...]
    legacy_continuity: ProjectLegacyContinuity
    freshness: ProjectHomeFreshness
    related_work: ProjectRelatedWork | None = None
    links: tuple[ProjectLinkRecord, ...] = ()


class ProjectApplicationService:
    """Coordinate explicit Project use cases through the existing chat domain."""

    def __init__(
        self,
        chats: ChatService,
        *,
        link_target_verifier: ProjectLinkTargetVerifier | None = None,
        related_sources: ProjectRelatedSources | None = None,
    ) -> None:
        self._chats = chats
        self._related_sources = related_sources
        self._link_target_verifier = (
            link_target_verifier if link_target_verifier is not None
            else related_sources.verify_link if related_sources is not None else None
        )

    def list_projects(self) -> tuple[ProjectRecord, ...]:
        return self._chats.list_projects()

    def get_project(self, project_id: str) -> ProjectRecord:
        return self._chats.get_project(project_id)

    def list_project_conversations(
        self, project_id: str
    ) -> tuple[ChatItem, ...]:
        self.get_project(project_id)
        return self._chats.list_project_chats(project_id)

    def get_project_home(self, project_id: str) -> ProjectHome:
        """Assemble one read-only Project view from authoritative archive rows."""

        project = self.get_project(project_id)
        state = self._chats.get_project_state(project_id)
        decisions = self._chats.list_project_decisions(project_id)
        active_decisions = self._chats.list_project_decisions(
            project_id, active_only=True
        )
        questions = self._chats.list_project_questions(project_id)
        active_questions = self._chats.list_project_questions(
            project_id, active_only=True
        )
        plan_items = self._chats.list_project_plan_items(project_id)
        conversations = self._chats.list_project_chats(project_id)
        links = self._chats.list_project_links(project_id)

        # Every structured mutation advances the aggregate revision. Refuse a
        # mixed Project-owned view if one occurred while this projection read.
        if self.get_project(project_id) != project:
            raise ChatServiceError(
                "The Project changed while its home was loading; refresh and try again.",
                code="stale_revision",
            )

        structured_records: tuple[object, ...] = (
            (() if state is None else (state,))
            + decisions
            + questions
            + plan_items
        )
        structured_updated_at = _newest_updated_at(structured_records)
        conversations_updated_at = _newest_updated_at(conversations)
        where_we_are = _where_we_are(
            project,
            state=state,
            decisions=decisions,
            questions=questions,
            active_questions=active_questions,
            plan_items=plan_items,
        )
        related_work = (
            None if self._related_sources is None
            else self._related_sources.project(project_id, links)
        )
        if related_work is not None:
            related_work = merge_project_activity(related_work, (
                *(('decision', item) for item in decisions),
                *(('question', item) for item in questions),
                *(('plan_item', item) for item in plan_items),
                *(('conversation', item) for item in conversations),
                *((('project_state', state),) if state is not None else ()),
            ))
        if self.get_project(project_id) != project:
            raise ChatServiceError(
                "The Project changed while its home was loading; refresh and try again.",
                code="stale_revision",
            )
        return ProjectHome(
            project=project,
            workspace_state=state,
            where_we_are=where_we_are,
            active_decisions=active_decisions,
            superseded_decisions=tuple(
                item for item in decisions if item.state == "superseded"
            ),
            active_questions=active_questions,
            closed_questions=tuple(
                item for item in questions if item.state in {"resolved", "dismissed"}
            ),
            plan_items=plan_items,
            conversations=conversations,
            legacy_continuity=ProjectLegacyContinuity(
                present=bool(project.continuity_brief),
                text=project.continuity_brief,
            ),
            freshness=ProjectHomeFreshness(
                project_revision=project.revision,
                project_updated_at=project.updated_at,
                structured_updated_at=structured_updated_at,
                conversations_updated_at=conversations_updated_at,
            ),
            related_work=related_work,
            links=links,
        )

    def prepare_new_project_chat(
        self, project_id: str, *, expected_project_revision: int
    ) -> ProjectRecord:
        """Validate one inert pending Project selection for a fresh chat."""

        if (
            type(expected_project_revision) is not int
            or expected_project_revision < 1
        ):
            raise ChatServiceError(
                "The Project revision is invalid.", code="invalid_record"
            )
        project = self.get_project(project_id)
        if project.revision != expected_project_revision:
            raise ChatServiceError(
                "The Project changed after it was loaded; refresh and try again.",
                code="stale_revision",
            )
        return project

    def project_for_conversation(
        self, conversation_id: str
    ) -> ProjectRecord | None:
        project_id = self._chats.get_chat(conversation_id).metadata.project_id
        return None if project_id is None else self._chats.get_project(project_id)

    def create_project(
        self,
        *,
        title: str,
        objective: str,
        conversation_id: str | None = None,
        expected_conversation_revision: int | None = None,
    ) -> ProjectRecord:
        return self._chats.create_project(
            title=title,
            objective=objective,
            continuity_brief="",
            chat_id=conversation_id,
            expected_chat_revision=expected_conversation_revision,
        )

    def update_project(
        self,
        project_id: str,
        *,
        expected_revision: int,
        title: str | None = None,
        objective: str | None = None,
    ) -> ProjectRecord:
        return self._chats.update_project(
            project_id,
            expected_revision=expected_revision,
            title=title,
            objective=objective,
        )

    def get_project_state(self, project_id: str) -> ProjectStateRecord | None:
        self.get_project(project_id)
        return self._chats.get_project_state(project_id)

    def update_project_state(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        expected_state_revision: int | None,
        phase: str | None,
        current_focus: str | None,
        checkpoint: str | None,
    ) -> ProjectMutationResult[ProjectStateRecord]:
        project, state = self._chats.update_project_state(
            project_id,
            expected_project_revision=expected_project_revision,
            expected_state_revision=expected_state_revision,
            phase=phase,
            current_focus=current_focus,
            checkpoint=checkpoint,
        )
        return ProjectMutationResult(project, state)

    def list_decisions(
        self, project_id: str, *, active_only: bool = False
    ) -> tuple[ProjectDecisionRecord, ...]:
        self.get_project(project_id)
        return self._chats.list_project_decisions(
            project_id, active_only=active_only
        )

    def add_decision(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
        importance: Literal["normal", "important"] = "normal",
    ) -> ProjectMutationResult[ProjectDecisionRecord]:
        project, decision = self._chats.add_project_decision(
            project_id,
            expected_project_revision=expected_project_revision,
            text=text,
            importance=importance,
        )
        return ProjectMutationResult(project, decision)

    def mark_decision_important(
        self,
        project_id: str,
        decision_id: str,
        *,
        expected_project_revision: int,
        expected_decision_revision: int,
    ) -> ProjectMutationResult[ProjectDecisionRecord]:
        project, decision = self._chats.mark_project_decision_important(
            project_id,
            decision_id,
            expected_project_revision=expected_project_revision,
            expected_decision_revision=expected_decision_revision,
        )
        return ProjectMutationResult(project, decision)

    def supersede_decision(
        self,
        project_id: str,
        predecessor_id: str,
        *,
        expected_project_revision: int,
        expected_predecessor_revision: int,
        text: str,
        importance: Literal["normal", "important"] = "normal",
    ) -> ProjectMutationResult[ProjectDecisionRecord]:
        project, decision = self._chats.supersede_project_decision(
            project_id,
            predecessor_id,
            expected_project_revision=expected_project_revision,
            expected_predecessor_revision=expected_predecessor_revision,
            text=text,
            importance=importance,
        )
        return ProjectMutationResult(project, decision)

    def list_questions(
        self, project_id: str, *, active_only: bool = False
    ) -> tuple[ProjectQuestionRecord, ...]:
        self.get_project(project_id)
        return self._chats.list_project_questions(
            project_id, active_only=active_only
        )

    def add_question(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
    ) -> ProjectMutationResult[ProjectQuestionRecord]:
        project, question = self._chats.add_project_question(
            project_id,
            expected_project_revision=expected_project_revision,
            text=text,
        )
        return ProjectMutationResult(project, question)

    def transition_question(
        self,
        project_id: str,
        question_id: str,
        *,
        expected_project_revision: int,
        expected_question_revision: int,
        state: ProjectQuestionState,
        disposition_note: str | None = None,
    ) -> ProjectMutationResult[ProjectQuestionRecord]:
        project, question = self._chats.transition_project_question(
            project_id,
            question_id,
            expected_project_revision=expected_project_revision,
            expected_question_revision=expected_question_revision,
            state=state,
            disposition_note=disposition_note,
        )
        return ProjectMutationResult(project, question)

    def list_plan_items(self, project_id: str) -> tuple[ProjectPlanItemRecord, ...]:
        self.get_project(project_id)
        return self._chats.list_project_plan_items(project_id)

    def add_plan_item(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        text: str,
        sort_order: int,
    ) -> ProjectMutationResult[ProjectPlanItemRecord]:
        project, item = self._chats.add_project_plan_item(
            project_id,
            expected_project_revision=expected_project_revision,
            text=text,
            sort_order=sort_order,
        )
        return ProjectMutationResult(project, item)

    def update_plan_item(
        self,
        project_id: str,
        plan_item_id: str,
        *,
        expected_project_revision: int,
        expected_plan_item_revision: int,
        text: str,
        state_note: str | None,
        sort_order: int,
    ) -> ProjectMutationResult[ProjectPlanItemRecord]:
        project, item = self._chats.update_project_plan_item(
            project_id,
            plan_item_id,
            expected_project_revision=expected_project_revision,
            expected_plan_item_revision=expected_plan_item_revision,
            text=text,
            state_note=state_note,
            sort_order=sort_order,
        )
        return ProjectMutationResult(project, item)

    def transition_plan_item(
        self,
        project_id: str,
        plan_item_id: str,
        *,
        expected_project_revision: int,
        expected_plan_item_revision: int,
        state: ProjectPlanState,
        state_note: str | None = None,
    ) -> ProjectMutationResult[ProjectPlanItemRecord]:
        project, item = self._chats.transition_project_plan_item(
            project_id,
            plan_item_id,
            expected_project_revision=expected_project_revision,
            expected_plan_item_revision=expected_plan_item_revision,
            state=state,
            state_note=state_note,
        )
        return ProjectMutationResult(project, item)

    def list_links(self, project_id: str) -> tuple[ProjectLinkRecord, ...]:
        self.get_project(project_id)
        return self._chats.list_project_links(project_id)

    def link_resource(
        self,
        project_id: str,
        *,
        expected_project_revision: int,
        target_type: ProjectLinkTargetType,
        target_id: str,
    ) -> ProjectMutationResult[ProjectLinkRecord]:
        try:
            validated_type, validated_id = validate_project_link_target(
                target_type, target_id
            )
        except ArchiveValidationError as exc:
            raise ChatServiceError(str(exc), code="invalid_record") from exc
        verifier = self._link_target_verifier
        try:
            verified = (
                verifier is not None
                and verifier(validated_type, validated_id) is True
            )
        except Exception as exc:
            raise ChatServiceError(
                "The linked resource could not be verified.",
                code="link_target_unavailable",
            ) from exc
        if not verified:
            raise ChatServiceError(
                "The linked resource could not be verified.",
                code="link_target_unavailable",
            )
        project, link = self._chats.add_project_link(
            project_id,
            expected_project_revision=expected_project_revision,
            target_type=validated_type,
            target_id=validated_id,
        )
        return ProjectMutationResult(project, link)

    def unlink_resource(
        self,
        project_id: str,
        link_id: str,
        *,
        expected_project_revision: int,
        expected_link_revision: int,
    ) -> ProjectRecord:
        return self._chats.remove_project_link(
            project_id,
            link_id,
            expected_project_revision=expected_project_revision,
            expected_link_revision=expected_link_revision,
        )

    def transition_project(
        self,
        project_id: str,
        *,
        expected_revision: int,
        status: ProjectStatus,
    ) -> ProjectRecord:
        return self._chats.update_project(
            project_id,
            expected_revision=expected_revision,
            status=status,
        )

    def associate_conversation(
        self,
        conversation_id: str,
        project_id: str,
        *,
        expected_conversation_revision: int,
    ) -> ChatDetail:
        return self._chats.associate_project(
            conversation_id,
            project_id,
            expected_revision=expected_conversation_revision,
        )

    def detach_conversation(
        self,
        conversation_id: str,
        *,
        expected_conversation_revision: int,
    ) -> ChatDetail:
        return self._chats.associate_project(
            conversation_id,
            None,
            expected_revision=expected_conversation_revision,
        )

    def delete_project(self, project_id: str, *, expected_revision: int) -> None:
        self._chats.delete_project(project_id, expected_revision=expected_revision)


def _where_we_are(
    project: ProjectRecord,
    *,
    state: ProjectStateRecord | None,
    decisions: tuple[ProjectDecisionRecord, ...],
    questions: tuple[ProjectQuestionRecord, ...],
    active_questions: tuple[ProjectQuestionRecord, ...],
    plan_items: tuple[ProjectPlanItemRecord, ...],
) -> ProjectWhereWeAre:
    open_questions = tuple(
        item for item in active_questions if item.state == "open"
    )
    active_plan_items = tuple(
        item for item in plan_items if item.state == "active"
    )
    blocked_plan_items = tuple(
        item for item in plan_items if item.state == "blocked"
    )
    planned_items = tuple(
        item for item in plan_items if item.state == "planned"
    )
    next_planned_step = (
        active_plan_items[0]
        if active_plan_items
        else planned_items[0]
        if planned_items
        else None
    )
    updated_at = _newest_updated_at(
        (
            project,
            *(() if state is None else (state,)),
            *decisions,
            *questions,
            *plan_items,
        )
    )
    assert updated_at is not None
    return ProjectWhereWeAre(
        objective=project.objective,
        status=project.status,
        phase=(
            state.phase
            if state is not None and state.phase is not None
            else PROJECT_STATE_NOT_RECORDED
        ),
        current_focus=(
            state.current_focus
            if state is not None and state.current_focus is not None
            else PROJECT_STATE_NOT_RECORDED
        ),
        checkpoint=(
            state.checkpoint
            if state is not None and state.checkpoint is not None
            else PROJECT_STATE_NOT_RECORDED
        ),
        structured_state_present=bool(state or decisions or questions or plan_items),
        next_planned_step=next_planned_step,
        active_plan_items=active_plan_items,
        blocked_plan_items=blocked_plan_items,
        open_questions=open_questions[:WHERE_WE_ARE_OPEN_QUESTION_LIMIT],
        open_question_count=len(open_questions),
        deferred_question_count=sum(
            item.state == "deferred" for item in active_questions
        ),
        last_updated_at=updated_at,
    )


def _newest_updated_at(records: tuple[object, ...]) -> str | None:
    newest: tuple[datetime, str] | None = None
    for record in records:
        value = getattr(record, "updated_at", None)
        if not isinstance(value, str):
            raise ChatServiceError(
                "Project freshness metadata is invalid.", code="invalid_record"
            )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ChatServiceError(
                "Project freshness metadata is invalid.", code="invalid_record"
            ) from exc
        if parsed.tzinfo is None:
            raise ChatServiceError(
                "Project freshness metadata is invalid.", code="invalid_record"
            )
        candidate = (parsed.astimezone(timezone.utc), value)
        if newest is None or candidate > newest:
            newest = candidate
    return None if newest is None else newest[1]
