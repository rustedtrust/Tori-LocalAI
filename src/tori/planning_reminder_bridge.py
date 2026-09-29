"""Deterministic bridge from canonical Planning alarms to Scheduled Work."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from itertools import islice
import threading
from typing import Any

from dateutil.rrule import rrulestr

from .actions import (
    ActionContractError,
    ActionDefinition,
    CapabilityAvailability,
    PermissionClass,
)
from .planning import (
    Event,
    PlanningAvailability,
    PlanningError,
    PlanningReminder,
    PlanningUnavailableError,
    Task,
)
from .planning_application import PlanningService
from .scheduled_work import (
    ScheduledCapabilityCatalog,
    ScheduledWorkDefinition,
    ScheduledWorkError,
    ScheduledWorkNotFoundError,
    one_shot_schedule,
)
from .scheduled_work_application import ScheduledWorkApplicationService
from .time_context import format_utc_timestamp


PLANNING_REMINDER_ACTION_ID = "tori.planning.reminder"
MAX_RECURRENCE_LOOKAHEAD = timedelta(days=366)
MAX_TITLE_LENGTH = 4_000
MAX_UNRESOLVED_ITEMS = 100
MAX_RECURRENCE_STEPS = 4_096


@dataclass(frozen=True, slots=True)
class PlanningReminderOccurrence:
    """One concrete future alarm occurrence derived from a Planning object."""

    source_key: str
    object_key: str
    alarm_key: str
    kind: str
    uid: str
    title: str
    collection_id: str
    instance_start: datetime
    trigger_at: datetime
    revision: str | None


@dataclass(frozen=True, slots=True)
class ReminderBridgeResult:
    """Bounded reconciliation result suitable for application diagnostics."""

    available: bool
    reason: str | None = None
    created: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    cancelled: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.created or self.replaced or self.cancelled)


@dataclass(frozen=True, slots=True)
class ReminderDeliveryObservation:
    """A read-only observation of a derived Scheduled Work run."""

    run_id: str
    source_key: str
    status: str


def planning_reminder_definition() -> ActionDefinition:
    """Return the non-interactive capability used only by the bridge."""

    return ActionDefinition(
        identifier=PLANNING_REMINDER_ACTION_ID,
        name="Planning reminder delivery",
        description="Deliver one derived reminder attention event for a CalDAV object.",
        permission=PermissionClass.INFORMATIONAL,
        _validate_arguments=_validate_delivery_arguments,
        _executor=_deliver_reminder,
        interactive_eligible=False,
        scheduled_one_shot_eligible=False,
        scheduled_recurring_eligible=False,
        system_derived_one_shot_eligible=True,
        _availability=lambda: CapabilityAvailability(True),
    )


def planning_reminder_catalog(
    definitions: Sequence[ActionDefinition] = (),
) -> ScheduledCapabilityCatalog:
    """Compose an executor catalog without making the bridge interactive."""

    return ScheduledCapabilityCatalog((*definitions, planning_reminder_definition()))


class PlanningReminderBridge:
    """Reconcile canonical Planning alarms into derived one-shot work.

    The bridge has no persistence of its own.  The source key and the small
    object/alarm identity fields in Scheduled Work arguments are sufficient to
    find derived definitions across restarts; full task/event content remains
    in CalDAV.
    """

    def __init__(
        self,
        planning: PlanningService,
        scheduled_work: ScheduledWorkApplicationService,
        *,
        clock: Any | None = None,
        origin_chat_id: str | None = None,
    ) -> None:
        self._planning = planning
        self._scheduled_work = scheduled_work
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._origin_chat_id = origin_chat_id
        self._definition = planning_reminder_definition()
        self._lock = threading.Lock()

    @property
    def definition(self) -> ActionDefinition:
        return self._definition

    def reconcile(self) -> ReminderBridgeResult:
        """Reconcile all supported collections and preserve state on outages."""
        with self._lock:
            try:
                status = self._planning.status()
            except PlanningError as exc:
                return ReminderBridgeResult(False, "Planning status is unavailable.", failures=(str(exc),))
            if status.availability is not PlanningAvailability.AVAILABLE:
                return ReminderBridgeResult(False, status.message)
            try:
                collections = self._planning.list_collections()
                items: list[Task | Event] = []
                for collection in collections:
                    if collection.supports_tasks:
                        items.extend(self._planning.list_tasks(collection.identifier))
                    if collection.supports_events:
                        items.extend(self._planning.list_events(collection.identifier))
            except PlanningUnavailableError as exc:
                return ReminderBridgeResult(False, "Planning is unavailable; derived delivery was preserved.", failures=(str(exc),))
            except PlanningError as exc:
                return ReminderBridgeResult(False, "Planning could not be reconciled; derived delivery was preserved.", failures=(str(exc),))
            return self._reconcile_items(items)

    def reconcile_object(self, item: Task | Event) -> ReminderBridgeResult:
        """Reconcile one already-read canonical object without backend access."""

        if not isinstance(item, (Task, Event)):
            return ReminderBridgeResult(True, failures=("The Planning object is invalid.",))
        return self._reconcile_items([item], restrict_object_key=_object_key(item))

    def observe_delivery_result(self, run_id: str) -> ReminderDeliveryObservation:
        """Observe a derived run without changing canonical Planning state."""

        run = self._scheduled_work.get_run(run_id)
        definition = self._scheduled_work.get_definition(run.job_id)
        if definition.capability_id != PLANNING_REMINDER_ACTION_ID:
            raise ScheduledWorkError("The run is not a Planning reminder delivery.")
        arguments = _delivery_arguments(definition.arguments)
        return ReminderDeliveryObservation(run.identifier, arguments["source_key"], run.status)

    def _reconcile_items(
        self,
        items: Iterable[Task | Event],
        *,
        restrict_object_key: str | None = None,
    ) -> ReminderBridgeResult:
        now = _aware_utc(self._clock()).replace(microsecond=0)
        desired: list[PlanningReminderOccurrence] = []
        unresolved: list[str] = []
        unresolved_object_keys: set[str] = set()
        for item in items:
            if restrict_object_key is not None and _object_key(item) != restrict_object_key:
                continue
            occurrences, unresolved_item = _next_occurrences(item, now)
            desired.extend(occurrences)
            if unresolved_item:
                unresolved.append(unresolved_item)
                unresolved_object_keys.add(_object_key(item))
            if len(unresolved) >= MAX_UNRESOLVED_ITEMS:
                break
        desired_by_key = {item.source_key: item for item in desired}
        try:
            definitions = self._scheduled_work.list_definitions()
        except ScheduledWorkError as exc:
            return ReminderBridgeResult(True, failures=("Scheduled Work is unavailable; derived delivery was preserved.", str(exc)))
        existing = [
            item for item in definitions
            if item.capability_id == PLANNING_REMINDER_ACTION_ID
            and item.status in {"active", "paused"}
            and _safe_bridge_arguments(item.arguments) is not None
            and (restrict_object_key is None
                 or _safe_bridge_arguments(item.arguments)["object_key"] == restrict_object_key)
        ]
        created: list[str] = []
        replaced: list[str] = []
        cancelled: list[str] = []
        unchanged: list[str] = []
        failures: list[str] = []
        consumed: set[str] = set()

        for occurrence in sorted(desired_by_key.values(), key=lambda value: value.source_key):
            same_source = [
                item for item in existing
                if item.identifier not in consumed
                and _safe_bridge_arguments(item.arguments)["source_key"] == occurrence.source_key
            ]
            candidate = same_source[0] if same_source else None
            if candidate is not None:
                consumed.add(candidate.identifier)
                if _definition_matches(candidate, occurrence):
                    unchanged.append(candidate.identifier)
                    for duplicate in same_source[1:]:
                        if self._cancel(duplicate, cancelled, failures):
                            consumed.add(duplicate.identifier)
                    continue
                try:
                    updated, _ = self._scheduled_work.replace_derived_one_shot(
                        candidate.identifier,
                        expected_revision=candidate.revision,
                        title=_delivery_title(occurrence.title),
                        definition=self._definition,
                        arguments=_arguments_for(occurrence),
                        schedule=one_shot_schedule(occurrence.trigger_at, _timezone_name(occurrence.trigger_at)),
                    )
                    replaced.append(updated.identifier)
                    for duplicate in same_source[1:]:
                        if self._cancel(duplicate, cancelled, failures):
                            consumed.add(duplicate.identifier)
                except ScheduledWorkError as exc:
                    failures.append(str(exc))
                continue

            # A changed trigger/time has a different source key.  Replace one
            # active definition for the same object/alarm; this preserves the
            # application-level cancellation/revision semantics and prevents
            # the old queued occurrence from firing.
            same_alarm = [
                item for item in existing
                if item.identifier not in consumed
                and _safe_bridge_arguments(item.arguments)["object_key"] == occurrence.object_key
                and _safe_bridge_arguments(item.arguments)["alarm_key"] == occurrence.alarm_key
            ]
            candidate = same_alarm[0] if same_alarm else None
            try:
                if candidate is None:
                    created_item, _ = self._scheduled_work.create_derived_one_shot(
                        title=_delivery_title(occurrence.title),
                        definition=self._definition,
                        arguments=_arguments_for(occurrence),
                        schedule=one_shot_schedule(occurrence.trigger_at, _timezone_name(occurrence.trigger_at)),
                        origin_chat_id=self._origin_chat_id,
                    )
                    created.append(created_item.identifier)
                else:
                    updated, _ = self._scheduled_work.replace_derived_one_shot(
                        candidate.identifier,
                        expected_revision=candidate.revision,
                        title=_delivery_title(occurrence.title),
                        definition=self._definition,
                        arguments=_arguments_for(occurrence),
                        schedule=one_shot_schedule(occurrence.trigger_at, _timezone_name(occurrence.trigger_at)),
                    )
                    consumed.add(candidate.identifier)
                    replaced.append(updated.identifier)
            except ScheduledWorkError as exc:
                failures.append(str(exc))

        for item in existing:
            if item.identifier in consumed:
                continue
            arguments = _safe_bridge_arguments(item.arguments)
            if arguments is None:
                continue
            if arguments["source_key"] in desired_by_key:
                continue
            # An unresolved source is preserved conservatively; an available
            # source with no current alarm is authoritative and is cancelled.
            if arguments["object_key"] in unresolved_object_keys:
                continue
            self._cancel(item, cancelled, failures)

        return ReminderBridgeResult(
            True,
            created=tuple(created),
            replaced=tuple(replaced),
            cancelled=tuple(cancelled),
            unchanged=tuple(unchanged),
            unresolved=tuple(unresolved),
            failures=tuple(failures),
        )

    def _cancel(
        self,
        item: ScheduledWorkDefinition,
        cancelled: list[str],
        failures: list[str],
    ) -> bool:
        try:
            self._scheduled_work.cancel_derived_one_shot(
                item.identifier, expected_revision=item.revision
            )
        except ScheduledWorkNotFoundError:
            return False
        except ScheduledWorkError as exc:
            failures.append(str(exc))
            return False
        cancelled.append(item.identifier)
        return True


def _next_occurrences(
    item: Task | Event, now: datetime
) -> tuple[tuple[PlanningReminderOccurrence, ...], str | None]:
    if isinstance(item, Task):
        if item.completed:
            return (), None
        # A DATE start is not a resolvable alarm reference, but a timed due
        # value can still resolve a VTODO alarm. Prefer a timed start and fall
        # back to the timed due value without inventing a time for DATE data.
        base = item.start if isinstance(item.start, datetime) else item.due
        kind = "task"
    else:
        base = item.start
        kind = "event"
    if not isinstance(base, datetime) or base.tzinfo is None or base.utcoffset() is None:
        return (), f"{kind}:{item.uid}:reminder reference time is unavailable"
    base = base.astimezone(timezone.utc)
    reminders = tuple(item.reminders)
    if not reminders:
        return (), None
    alarm_keys = _alarm_keys(reminders)
    result: list[PlanningReminderOccurrence] = []
    for reminder, alarm_key in zip(reminders, alarm_keys):
        trigger = _next_trigger(base, item.recurrence.value if item.recurrence else None, reminder.trigger, now)
        if trigger is None:
            continue
        instance_start, trigger_at = trigger
        if trigger_at > now + MAX_RECURRENCE_LOOKAHEAD:
            continue
        object_key = _object_key(item)
        source_key = _digest(
            "\0".join((object_key, alarm_key, instance_start.isoformat(), trigger_at.isoformat()))
        )
        result.append(PlanningReminderOccurrence(
            source_key=source_key,
            object_key=object_key,
            alarm_key=alarm_key,
            kind=kind,
            uid=item.uid,
            title=item.title,
            collection_id=item.collection_id,
            instance_start=instance_start,
            trigger_at=trigger_at,
            revision=None if item.revision is None else item.revision.token,
        ))
    return tuple(result), None


def _next_trigger(
    base: datetime,
    recurrence: str | None,
    offset: timedelta,
    now: datetime,
) -> tuple[datetime, datetime] | None:
    search_start = now - offset
    if recurrence is None:
        trigger_at = base + offset
        return (base, trigger_at) if trigger_at >= now else None
    try:
        rule = rrulestr(recurrence, dtstart=base)
        upper = now + MAX_RECURRENCE_LOOKAHEAD
        instance = None
        for candidate in islice(rule.xafter(search_start, inc=True), MAX_RECURRENCE_STEPS):
            if not isinstance(candidate, datetime):
                continue
            if candidate > upper:
                break
            candidate_trigger = candidate.astimezone(timezone.utc) + offset
            if candidate_trigger >= now:
                instance = candidate
                break
    except (TypeError, ValueError, OverflowError):
        return None
    if not isinstance(instance, datetime) or instance.tzinfo is None:
        return None
    trigger_at = instance.astimezone(timezone.utc) + offset
    return (instance.astimezone(timezone.utc), trigger_at) if trigger_at >= now else None


def _object_key(item: Task | Event) -> str:
    kind = "task" if isinstance(item, Task) else "event"
    return _digest("\0".join((kind, item.collection_id, item.uid)))


def _alarm_keys(reminders: Sequence[PlanningReminder]) -> tuple[str, ...]:
    ordered = sorted(
        enumerate(reminders),
        key=lambda value: (value[1].description, value[0]),
    )
    counts: dict[str, int] = {}
    keys: dict[int, str] = {}
    for index, reminder in ordered:
        # RFC 5545 VALARM has no required UID.  Description plus a stable
        # ordinal distinguishes repeated alarms while keeping the identity
        # stable when an alarm's trigger time moves.
        fingerprint = f"DISPLAY\0{reminder.description}"
        ordinal = counts.get(fingerprint, 0)
        counts[fingerprint] = ordinal + 1
        keys[index] = _digest(f"{fingerprint}\0{ordinal}")
    return tuple(keys[index] for index in range(len(reminders)))


def _arguments_for(occurrence: PlanningReminderOccurrence) -> dict[str, str]:
    return {
        "source_key": occurrence.source_key,
        "object_key": occurrence.object_key,
        "alarm_key": occurrence.alarm_key,
        "kind": occurrence.kind,
        "uid": occurrence.uid,
        "occurrence_utc": occurrence.instance_start.isoformat(),
        "trigger_utc": occurrence.trigger_at.isoformat(),
    }


def _validate_delivery_arguments(arguments: object) -> Mapping[str, Any]:
    if not isinstance(arguments, Mapping) or set(arguments) != {
        "source_key", "object_key", "alarm_key", "kind", "uid",
        "occurrence_utc", "trigger_utc",
    }:
        raise ActionContractError(
            "Planning reminder arguments are invalid.", code="invalid_arguments"
        )
    values = {key: arguments[key] for key in arguments}
    if values["kind"] not in {"task", "event"}:
        raise ActionContractError(
            "Planning reminder kind is invalid.", code="invalid_arguments"
        )
    for key in values:
        if not isinstance(values[key], str) or not values[key] or len(values[key]) > 512:
            raise ActionContractError(
                "Planning reminder arguments are invalid.", code="invalid_arguments"
            )
    return values


def _deliver_reminder(arguments: Mapping[str, Any], _invocation_id: str) -> Mapping[str, Any]:
    return {
        "source_key": arguments["source_key"],
        "planning_kind": arguments["kind"],
        "planning_uid": arguments["uid"],
        "occurrence_utc": arguments["occurrence_utc"],
        "trigger_utc": arguments["trigger_utc"],
    }


def _delivery_arguments(arguments: Mapping[str, object]) -> Mapping[str, str]:
    return _validate_delivery_arguments(arguments)  # type: ignore[return-value]


def _safe_bridge_arguments(arguments: Mapping[str, object]) -> Mapping[str, str] | None:
    try:
        return _delivery_arguments(arguments)
    except (TypeError, ValueError):
        return None


def _definition_matches(
    definition: ScheduledWorkDefinition,
    occurrence: PlanningReminderOccurrence,
) -> bool:
    arguments = _safe_bridge_arguments(definition.arguments)
    if arguments is None:
        return False
    return (
        definition.title == _delivery_title(occurrence.title)
        and arguments == _arguments_for(occurrence)
        and definition.schedule.kind == "one_shot"
        and definition.schedule.occurrence_utc == _format_utc(occurrence.trigger_at)
    )


def _delivery_title(title: str) -> str:
    return f"Planning reminder: {title}"[:MAX_TITLE_LENGTH]


def _timezone_name(value: datetime) -> str:
    key = getattr(value.tzinfo, "key", None)
    return key if isinstance(key, str) and "/" in key else "Etc/UTC"


def _format_utc(value: datetime) -> str:
    return format_utc_timestamp(value)


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("The bridge clock must return an aware datetime.")
    return value.astimezone(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
