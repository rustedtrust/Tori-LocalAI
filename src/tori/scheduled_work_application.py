"""Presentation-neutral deterministic Scheduled Work application use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from .scheduled_work import (
    ScheduleSpec,
    ScheduledAuthorization,
    ScheduledRun,
    ScheduledWorkDefinition,
    ScheduledWorkValidationError,
    SQLiteScheduledWorkStore,
)

if TYPE_CHECKING:
    from .actions import ActionDefinition
    from .scheduled_work_service import ScheduledWorkDraft


ScheduledWorkTransition = Literal["pause", "resume", "cancel"]


class ScheduledWorkApplicationService:
    """Apply explicit Scheduled Work use cases through the canonical store."""

    def __init__(self, store: SQLiteScheduledWorkStore) -> None:
        self._store = store

    def revision(self) -> int:
        return self._store.revision()

    def list_definitions(self) -> tuple[ScheduledWorkDefinition, ...]:
        return self._store.list_definitions()

    def list_runs(self, *, limit: int = 100) -> tuple[ScheduledRun, ...]:
        return self._store.list_runs(limit=limit)

    def get_definition(self, identifier: str) -> ScheduledWorkDefinition:
        return self._store.get_definition(identifier)

    def get_authorization(self, identifier: str) -> ScheduledAuthorization:
        return self._store.get_authorization(identifier)

    def get_run(self, identifier: str) -> ScheduledRun:
        return self._store.get_run(identifier)

    def apply_draft(
        self,
        draft: ScheduledWorkDraft,
        *,
        definition: ActionDefinition,
        confirmation_provenance: str,
        origin_chat_id: str | None = None,
    ) -> tuple[ScheduledWorkDefinition, ScheduledAuthorization]:
        if draft.editing:
            if draft.existing_job_id is None or draft.expected_revision is None:
                raise ScheduledWorkValidationError(
                    "Editing scheduled work requires an exact target revision."
                )
            return self._store.replace_definition(
                draft.existing_job_id,
                expected_revision=draft.expected_revision,
                title=draft.title,
                definition=definition,
                arguments=draft.arguments,
                schedule=draft.schedule,
                missed_policy=draft.missed_policy,
                confirmation_provenance=confirmation_provenance,
            )
        if draft.expected_revision is not None:
            raise ScheduledWorkValidationError(
                "New scheduled work cannot carry an existing revision."
            )
        return self._store.create_definition(
            title=draft.title,
            definition=definition,
            arguments=draft.arguments,
            schedule=draft.schedule,
            missed_policy=draft.missed_policy,
            confirmation_provenance=confirmation_provenance,
            origin_chat_id=origin_chat_id,
        )

    def create_derived_one_shot(
        self,
        *,
        title: str,
        definition: ActionDefinition,
        arguments: Mapping[str, object],
        schedule: ScheduleSpec,
        origin_chat_id: str | None = None,
    ) -> tuple[ScheduledWorkDefinition, ScheduledAuthorization]:
        """Create system-derived one-shot work through the canonical store.

        This narrow boundary is intentionally separate from ``apply_draft``:
        derived work has no conversational proposal or model authorization.
        The caller remains responsible for supplying a non-interactive,
        bridge-owned capability definition and deterministic arguments.
        """

        if schedule.kind != "one_shot":
            raise ScheduledWorkValidationError(
                "Derived reminder delivery must be one-shot work."
            )
        if (
            definition.interactive_eligible
            or not definition.system_derived_one_shot_eligible
        ):
            raise ScheduledWorkValidationError(
                "The supplied capability is not bridge-derived work."
            )
        return self._store.create_definition(
            title=title,
            definition=definition,
            arguments=arguments,
            schedule=schedule,
            missed_policy="run_when_available",
            confirmation_provenance="planning_reminder_bridge",
            origin_chat_id=origin_chat_id,
            system_derived=True,
        )

    def replace_derived_one_shot(
        self,
        identifier: str,
        *,
        expected_revision: int,
        title: str,
        definition: ActionDefinition,
        arguments: Mapping[str, object],
        schedule: ScheduleSpec,
    ) -> tuple[ScheduledWorkDefinition, ScheduledAuthorization]:
        """Replace one bridge-derived one-shot without bypassing revisions."""

        if schedule.kind != "one_shot":
            raise ScheduledWorkValidationError(
                "Derived reminder delivery must be one-shot work."
            )
        if (
            definition.interactive_eligible
            or not definition.system_derived_one_shot_eligible
        ):
            raise ScheduledWorkValidationError(
                "The supplied capability is not bridge-derived work."
            )
        return self._store.replace_definition(
            identifier,
            expected_revision=expected_revision,
            title=title,
            definition=definition,
            arguments=arguments,
            schedule=schedule,
            missed_policy="run_when_available",
            confirmation_provenance="planning_reminder_bridge",
            system_derived=True,
        )

    def cancel_derived_one_shot(
        self, identifier: str, *, expected_revision: int
    ) -> ScheduledWorkDefinition:
        """Cancel a bridge-derived pending delivery revision-safely."""

        return self._store.cancel_definition(
            identifier, expected_revision=expected_revision
        )

    def transition_definition(
        self,
        identifier: str,
        *,
        expected_revision: int,
        action: ScheduledWorkTransition,
    ) -> ScheduledWorkDefinition:
        transitions = {
            "pause": self._store.pause_definition,
            "resume": self._store.resume_definition,
            "cancel": self._store.cancel_definition,
        }
        function = transitions.get(action)
        if function is None:
            raise ScheduledWorkValidationError(
                "The scheduled-work transition is invalid."
            )
        return function(identifier, expected_revision=expected_revision)

    def delete_run_history(
        self, identifier: str, *, expected_revision: int
    ) -> None:
        self._store.delete_terminal_run(
            identifier, expected_revision=expected_revision
        )

    def delete_definition_history(
        self, identifier: str, *, expected_revision: int
    ) -> None:
        self._store.delete_resolved_definition(
            identifier, expected_revision=expected_revision
        )
