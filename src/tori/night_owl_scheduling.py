"""Narrow Scheduled Work bridge for authorized Night Owl research."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time
import hashlib
import json
import re
from typing import Callable

from .actions import ActionContractError, ActionDefinition, PermissionClass
from .night_owl import (
    BUDGET_POLICY_VERSION,
    CATEGORIES,
    SOURCE_POLICY_VERSION,
    NightOwlConflictError,
    ResearchGrant,
    SQLiteNightOwlStore,
)
from .night_owl_research import NightOwlResearchRunner
from .operator_observability import operator_event
from .scheduled_work import (
    ScheduledCapabilityError,
    ScheduledWorkDefinition,
    ScheduledWorkValidationError,
    daily_schedule,
    weekly_schedule,
)
from .scheduled_work_application import ScheduledWorkApplicationService
from .scheduled_work_service import ScheduledWorkDraft


NIGHT_OWL_ACTION_ID = "tori.night_owl.research"
NIGHT_OWL_ACTION_VERSION = 1
NIGHT_OWL_DEFAULT_TIME = time(2, 0)
NIGHT_OWL_DEFAULT_WEEKDAY = 6  # Sunday; datetime.weekday() uses Monday=0.
_GRANT_ID = re.compile(r"grant-[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SNAPSHOT_KEYS = frozenset({
    "grant_id", "grant_revision", "grant_digest", "categories",
    "category_digest", "source_policy_version", "budget_policy_version",
})


def category_digest(categories: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(categories, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def authorization_snapshot(grant: ResearchGrant) -> dict[str, object]:
    if not isinstance(grant, ResearchGrant):
        raise ScheduledWorkValidationError("An active Night Owl grant is required.")
    return {
        "grant_id": grant.identifier,
        "grant_revision": grant.revision,
        "grant_digest": grant.digest,
        "categories": list(grant.categories),
        "category_digest": category_digest(grant.categories),
        "source_policy_version": grant.source_policy_version,
        "budget_policy_version": BUDGET_POLICY_VERSION,
    }


def _validate_snapshot(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_KEYS:
        raise ActionContractError(
            "The Night Owl authorization snapshot is invalid.",
            code="invalid_night_owl_authorization",
        )
    grant_id = value.get("grant_id")
    revision = value.get("grant_revision")
    grant_digest = value.get("grant_digest")
    categories = value.get("categories")
    supplied_category_digest = value.get("category_digest")
    source_policy = value.get("source_policy_version")
    budget_policy = value.get("budget_policy_version")
    if (
        not isinstance(grant_id, str) or _GRANT_ID.fullmatch(grant_id) is None
        or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        or not isinstance(grant_digest, str) or _DIGEST.fullmatch(grant_digest) is None
        or not isinstance(categories, list) or not categories
        or any(not isinstance(item, str) for item in categories)
        or tuple(sorted(set(categories))) != tuple(categories)
        or any(item not in CATEGORIES for item in categories)
        or not isinstance(supplied_category_digest, str)
        or _DIGEST.fullmatch(supplied_category_digest) is None
        or supplied_category_digest != category_digest(tuple(categories))
        or source_policy != SOURCE_POLICY_VERSION
        or budget_policy != BUDGET_POLICY_VERSION
    ):
        raise ActionContractError(
            "The Night Owl authorization snapshot is invalid.",
            code="invalid_night_owl_authorization",
        )
    return {
        "grant_id": grant_id,
        "grant_revision": revision,
        "grant_digest": grant_digest,
        "categories": list(categories),
        "category_digest": supplied_category_digest,
        "source_policy_version": source_policy,
        "budget_policy_version": budget_policy,
    }


def _validate_result(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "night_owl_run_id", "night_owl_state", "budget_used", "error_codes"
    }:
        raise ActionContractError("Night Owl returned an invalid result.", code="invalid_result")
    run_id = value.get("night_owl_run_id")
    state = value.get("night_owl_state")
    budget = value.get("budget_used")
    errors = value.get("error_codes")
    if (
        not isinstance(run_id, str) or re.fullmatch(r"run-[0-9a-f]{32}", run_id) is None
        or state not in {"completed", "partial", "skipped"}
        or not isinstance(budget, dict)
        or any(not isinstance(key, str) or isinstance(amount, bool) or not isinstance(amount, int) or amount < 0 for key, amount in budget.items())
        or not isinstance(errors, list)
        or any(not isinstance(item, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", item) for item in errors)
    ):
        raise ActionContractError("Night Owl returned an invalid result.", code="invalid_result")
    return dict(value)


def night_owl_scheduled_definition(
    store: SQLiteNightOwlStore, runner: NightOwlResearchRunner
) -> ActionDefinition:
    """Build the recurring-only capability with no query or URL arguments."""

    def execute(arguments: Mapping[str, object], invocation_id: str) -> Mapping[str, object]:
        try:
            grant = store.active_grant()
            if grant is None:
                raise NightOwlConflictError("Night Owl research authority is inactive.")
            expected = authorization_snapshot(grant)
            if dict(arguments) != expected:
                raise NightOwlConflictError("Night Owl schedule authority is stale.")
            for category in grant.categories:
                store.verify_grant(
                    grant.identifier,
                    revision=grant.revision,
                    digest=grant.digest,
                    category=category,
                    source_policy_version=grant.source_policy_version,
                )
        except NightOwlConflictError as exc:
            operator_event(
                "night_owl.scheduled.authorization_rejected",
                invocation=invocation_id,
                code="night_owl_authorization_stale",
            )
            raise ScheduledCapabilityError(
                "The Night Owl authorization changed; reauthorize the schedule.",
                code="night_owl_authorization_stale",
            ) from exc
        operator_event(
            "night_owl.scheduled.authorization_validated",
            invocation=invocation_id,
            grant_revision=grant.revision,
        )
        operator_event(
            "night_owl.scheduled.run_started",
            invocation=invocation_id,
            category_count=len(grant.categories),
        )
        result = runner.run_now(
            grant, trigger="scheduled", invocation_id=invocation_id
        )
        operator_event(
            "night_owl.scheduled.run_finished",
            invocation=invocation_id,
            state=result.state,
            budget_limited=any(code.endswith("_limit") for code in result.error_codes),
        )
        if result.state == "interrupted":
            raise ScheduledCapabilityError(
                "Night Owl research was interrupted safely.", code="night_owl_interrupted"
            )
        if result.state == "failed":
            raise ScheduledCapabilityError(
                "Night Owl research failed safely.", code="night_owl_research_failed"
            )
        return {
            "night_owl_run_id": result.identifier,
            "night_owl_state": result.state,
            "budget_used": dict(result.budget_used),
            "error_codes": list(result.error_codes),
        }

    return ActionDefinition(
        identifier=NIGHT_OWL_ACTION_ID,
        name="Run Night Owl research review",
        description="Run one bounded review under an exact Night Owl authorization snapshot.",
        permission=PermissionClass.PERSISTENT,
        _validate_arguments=_validate_snapshot,
        _executor=execute,
        contract_version=NIGHT_OWL_ACTION_VERSION,
        interactive_eligible=False,
        scheduled_one_shot_eligible=False,
        scheduled_recurring_eligible=True,
        _validate_result=_validate_result,
    )


@dataclass(slots=True)
class NightOwlScheduleService:
    """Backend-only owner seam for one explicit Night Owl recurring schedule."""

    scheduled_work: ScheduledWorkApplicationService
    night_owl: SQLiteNightOwlStore
    definition: ActionDefinition
    clock_date: Callable[[], date]

    def create(
        self,
        grant: ResearchGrant,
        *,
        mode: str,
        timezone_name: str,
        local_time: time = NIGHT_OWL_DEFAULT_TIME,
        weekday: int = NIGHT_OWL_DEFAULT_WEEKDAY,
        confirmation_provenance: str,
    ):
        if any(
            item.capability_id == NIGHT_OWL_ACTION_ID
            and item.status in {"active", "paused"}
            for item in self.scheduled_work.list_definitions()
        ):
            raise ScheduledWorkValidationError("Night Owl already has a schedule.")
        draft = self._draft(
            grant, mode=mode, timezone_name=timezone_name,
            local_time=local_time, weekday=weekday,
        )
        return self.scheduled_work.apply_draft(
            draft, definition=self.definition,
            confirmation_provenance=confirmation_provenance,
        )

    def replace(
        self,
        identifier: str,
        *,
        expected_revision: int,
        grant: ResearchGrant,
        mode: str,
        timezone_name: str,
        local_time: time = NIGHT_OWL_DEFAULT_TIME,
        weekday: int = NIGHT_OWL_DEFAULT_WEEKDAY,
        confirmation_provenance: str,
    ):
        current_definition = self.scheduled_work.get_definition(identifier)
        if current_definition.capability_id != NIGHT_OWL_ACTION_ID:
            raise ScheduledWorkValidationError("The schedule is not owned by Night Owl.")
        draft = self._draft(
            grant, mode=mode, timezone_name=timezone_name,
            local_time=local_time, weekday=weekday,
            existing_job_id=identifier, expected_revision=expected_revision,
        )
        return self.scheduled_work.apply_draft(
            draft, definition=self.definition,
            confirmation_provenance=confirmation_provenance,
        )

    def transition(self, identifier: str, *, expected_revision: int, action: str) -> ScheduledWorkDefinition:
        if action == "resume":
            current = self.scheduled_work.get_definition(identifier)
            if current.capability_id != NIGHT_OWL_ACTION_ID:
                raise ScheduledWorkValidationError("The schedule is not owned by Night Owl.")
            grant = self._active_grant()
            if dict(current.arguments) != authorization_snapshot(grant):
                raise ScheduledWorkValidationError(
                    "Night Owl authority changed; replace and reauthorize the schedule."
                )
        return self.scheduled_work.transition_definition(
            identifier, expected_revision=expected_revision, action=action
        )

    def delete(self, identifier: str, *, expected_revision: int) -> None:
        current = self.scheduled_work.get_definition(identifier)
        if current.capability_id != NIGHT_OWL_ACTION_ID:
            raise ScheduledWorkValidationError("The schedule is not owned by Night Owl.")
        self.scheduled_work.delete_definition_history(
            identifier, expected_revision=expected_revision
        )

    def _active_grant(self) -> ResearchGrant:
        grant = self.night_owl.active_grant()
        if grant is None:
            raise ScheduledWorkValidationError("Night Owl authority is inactive.")
        return grant

    def _draft(
        self,
        grant: ResearchGrant,
        *,
        mode: str,
        timezone_name: str,
        local_time: time,
        weekday: int,
        existing_job_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ScheduledWorkDraft:
        current = self._active_grant()
        if grant != current:
            raise ScheduledWorkValidationError("Night Owl authority changed; refresh and reauthorize.")
        if mode == "nightly":
            schedule = daily_schedule(self.clock_date(), local_time, timezone_name)
        elif mode == "weekly":
            schedule = weekly_schedule(
                self.clock_date(), local_time, timezone_name, (weekday,)
            )
        else:
            raise ScheduledWorkValidationError("Night Owl schedule mode is invalid.")
        return ScheduledWorkDraft(
            title="Night Owl research review",
            capability_id=NIGHT_OWL_ACTION_ID,
            capability_contract_version=NIGHT_OWL_ACTION_VERSION,
            arguments=authorization_snapshot(grant),
            schedule=schedule,
            missed_policy="skip_if_missed",
            existing_job_id=existing_job_id,
            expected_revision=expected_revision,
        )
