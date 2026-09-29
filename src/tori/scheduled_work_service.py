"""Explicit proposal boundary for narrow scheduled-work authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import re
from typing import Mapping

from .actions import ActionDefinition, BACKUP_ACTION_ID
from .scheduled_work import (
    ScheduleSpec,
    ScheduledCapabilityCatalog,
    ScheduledWorkDefinition,
    ScheduledWorkValidationError,
    one_shot_schedule,
)
from .time_context import TimeContext, TimeContextError


_BACKUP_CLOCK = (
    r"(?P<hour>0?[1-9]|1[0-2])(?::(?P<minute>[0-5]\d))?\s*"
    r"(?P<period>[ap])\.?m\.?"
)
_BACKUP_REQUESTS = (
    re.compile(
        r"(?is)^\s*(?:schedule\s+(?:a\s+)?tori\s+backup(?:\s+for)?|"
        r"back\s+up\s+tori)\s+(?P<day>today|tomorrow)\s+at\s+"
        + _BACKUP_CLOCK + r"\s*[.!?]?\s*$"
    ),
    re.compile(
        r"(?is)^\s*schedule\s+(?:a\s+)?tori\s+backup\s+for\s+"
        + _BACKUP_CLOCK + r"\s+(?P<day>today|tomorrow)\s*[.!?]?\s*$"
    ),
)
_BACKUP_RECURRENCE = re.compile(
    r"(?is)\b(?:back\s*up|backup)\b.*\b(?:every|daily|weekly|recurr(?:ing|ence)?)\b"
    r"|\b(?:every|daily|weekly|recurr(?:ing|ence)?)\b.*\b(?:back\s*up|backup)\b"
)
_BACKUP_SCHEDULE_CANDIDATE = re.compile(
    r"(?is)^\s*schedule\s+(?:a\s+)?tori\s+backup\b"
)


@dataclass(frozen=True, slots=True)
class ScheduledWorkDraft:
    title: str
    capability_id: str
    capability_contract_version: int
    arguments: Mapping[str, object]
    schedule: ScheduleSpec
    missed_policy: str
    existing_job_id: str | None = None
    expected_revision: int | None = None

    @property
    def editing(self) -> bool:
        return self.existing_job_id is not None

    def summary(self) -> dict[str, object]:
        return {
            "operation": "edit" if self.editing else "create",
            "title": self.title,
            "capability_id": self.capability_id,
            "capability_contract_version": self.capability_contract_version,
            "arguments": dict(self.arguments),
            "schedule": self.schedule.document(),
            "scheduled_mode": self.schedule.mode,
            "missed_policy": self.missed_policy,
            "persistent_permission": True,
            "dst_policy": (
                "Recurring gaps are skipped; overlaps run once at the first occurrence."
                if self.schedule.mode == "recurring" else None
            ),
            "application_lifetime": (
                "Runs only while Tori's application process exists; startup recovery applies after downtime."
            ),
        }


@dataclass(frozen=True, slots=True)
class ScheduledWorkInterpretation:
    handled: bool
    draft: ScheduledWorkDraft | None = None
    message: str | None = None


class ScheduledWorkService:
    """Map narrow user intent to an inert, reviewable scheduled-work draft."""

    def __init__(self, catalog: ScheduledCapabilityCatalog) -> None:
        self._catalog = catalog

    def interpret_backup_request(
        self, text: str, *, time_context: TimeContext
    ) -> ScheduledWorkInterpretation:
        if not isinstance(text, str):
            return ScheduledWorkInterpretation(False)
        if _BACKUP_RECURRENCE.search(text):
            return ScheduledWorkInterpretation(
                True,
                message=(
                    "Recurring Tori backups are not authorized because backup retention "
                    "and pruning are not available. Nothing was scheduled."
                ),
            )
        match = next(
            (match for candidate in _BACKUP_REQUESTS
             if (match := candidate.fullmatch(text)) is not None),
            None,
        )
        if match is None:
            if _BACKUP_SCHEDULE_CANDIDATE.search(text):
                return ScheduledWorkInterpretation(
                    True,
                    message=(
                        "Please give one exact future time today or tomorrow for the "
                        "Tori backup. Nothing was scheduled."
                    ),
                )
            return ScheduledWorkInterpretation(False)
        local_date = time_context.civil_date(match.group("day"))
        hour = int(match.group("hour")) % 12
        if match.group("period").casefold() == "p":
            hour += 12
        minute = int(match.group("minute") or "0")
        try:
            instant = time_context.resolve_civil(local_date, time(hour, minute))
        except TimeContextError as exc:
            return ScheduledWorkInterpretation(
                True, message=f"{exc} Nothing was scheduled."
            )
        if instant <= time_context.captured_utc:
            return ScheduledWorkInterpretation(
                True,
                message="That time is not in the future. Nothing was scheduled.",
            )
        draft = self.backup_draft(
            title="Back up Tori",
            schedule=one_shot_schedule(instant, time_context.timezone_name),
            missed_policy="run_when_available",
        )
        return ScheduledWorkInterpretation(True, draft=draft)

    def backup_draft(
        self,
        *,
        title: str,
        schedule: ScheduleSpec,
        missed_policy: str,
        existing: ScheduledWorkDefinition | None = None,
    ) -> ScheduledWorkDraft:
        definition, arguments = self._catalog.validate(
            BACKUP_ACTION_ID, 1, {}, schedule.mode
        )
        if schedule.mode != "one_shot":
            raise ScheduledWorkValidationError(
                "Recurring Tori backups are not authorized."
            )
        return ScheduledWorkDraft(
            title=title,
            capability_id=definition.identifier,
            capability_contract_version=definition.contract_version,
            arguments=arguments,
            schedule=schedule,
            missed_policy=missed_policy,
            existing_job_id=None if existing is None else existing.identifier,
            expected_revision=None if existing is None else existing.revision,
        )

    def definition_for(self, draft: ScheduledWorkDraft) -> ActionDefinition:
        definition, canonical = self._catalog.validate(
            draft.capability_id,
            draft.capability_contract_version,
            draft.arguments,
            draft.schedule.mode,
        )
        if dict(canonical) != dict(draft.arguments):
            raise ScheduledWorkValidationError(
                "The scheduled arguments changed before confirmation."
            )
        return definition


def local_one_shot_backup_schedule(
    *,
    local_date: object,
    local_time: object,
    context: TimeContext,
) -> ScheduleSpec:
    if not isinstance(local_date, str) or not isinstance(local_time, str):
        raise ScheduledWorkValidationError("A local date and time are required.")
    try:
        selected_date = date.fromisoformat(local_date)
        selected_time = time.fromisoformat(local_time)
    except ValueError as exc:
        raise ScheduledWorkValidationError("The local date or time is invalid.") from exc
    try:
        instant = context.resolve_civil(selected_date, selected_time)
    except TimeContextError as exc:
        raise ScheduledWorkValidationError(str(exc)) from exc
    if instant <= context.captured_utc:
        raise ScheduledWorkValidationError("Scheduled work must be in the future.")
    return one_shot_schedule(instant, context.timezone_name)
