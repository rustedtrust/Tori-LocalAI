"""Tori-owned planning domain and replaceable backend contract."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Protocol, runtime_checkable
import re


_UID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,254}$")


class PlanningError(RuntimeError):
    """A bounded planning operation failure."""

    code = "planning_error"


class PlanningUnavailableError(PlanningError):
    """The configured planning backend cannot currently be reached."""

    code = "unavailable"


class PlanningNotFoundError(PlanningError):
    """The requested planning object does not exist."""

    code = "not_found"


class PlanningConflictError(PlanningError):
    """The planning object changed since the caller read it."""

    code = "revision_conflict"


class PlanningDataError(PlanningError):
    """A planning value or remote representation is invalid."""

    code = "invalid_data"


class PlanningAvailability(str, Enum):
    DISABLED = "disabled"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PlanningStatus:
    availability: PlanningAvailability
    message: str


@dataclass(frozen=True, slots=True)
class PlanningRevision:
    """Opaque backend revision used for optimistic mutation checks."""

    token: str

    def __post_init__(self) -> None:
        if not isinstance(self.token, str) or not self.token.strip():
            raise PlanningDataError("Planning revisions require a token.")


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    """A standard RFC 5545 RRULE value, without a Tori-specific grammar."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip().upper()
        if not value.startswith("FREQ=") or "\n" in value or "\r" in value:
            raise PlanningDataError("Recurrence must be an RFC 5545 RRULE value.")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class PlanningReminder:
    """Portable relative DISPLAY alarm metadata."""

    trigger: timedelta
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.trigger, timedelta):
            raise PlanningDataError("A reminder requires a relative trigger.")
        _validate_text(self.description, "Reminder description", required=True)


@dataclass(frozen=True, slots=True)
class PlanningCollection:
    identifier: str
    name: str
    supports_tasks: bool
    supports_events: bool


@dataclass(frozen=True, slots=True)
class Task:
    uid: str
    title: str
    collection_id: str
    description: str = ""
    start: date | datetime | None = None
    due: date | datetime | None = None
    completed: bool = False
    completed_at: datetime | None = None
    priority: int | None = None
    recurrence: RecurrenceRule | None = None
    reminders: tuple[PlanningReminder, ...] = ()
    revision: PlanningRevision | None = None

    def __post_init__(self) -> None:
        _validate_common(self.uid, self.title, self.description, self.collection_id)
        _validate_temporal(self.start, "Task start")
        _validate_temporal(self.due, "Task due")
        _validate_datetime(self.completed_at, "Task completed timestamp")
        if self.priority is not None and not 0 <= self.priority <= 9:
            raise PlanningDataError("Task priority must be between 0 and 9.")
        if self.completed and self.completed_at is None:
            raise PlanningDataError("A completed task requires a completed timestamp.")
        if not self.completed and self.completed_at is not None:
            raise PlanningDataError("An open task cannot have a completed timestamp.")


@dataclass(frozen=True, slots=True)
class Event:
    uid: str
    title: str
    collection_id: str
    start: date | datetime
    end: date | datetime
    description: str = ""
    all_day: bool = False
    location: str = ""
    recurrence: RecurrenceRule | None = None
    reminders: tuple[PlanningReminder, ...] = ()
    revision: PlanningRevision | None = None

    def __post_init__(self) -> None:
        _validate_common(self.uid, self.title, self.description, self.collection_id)
        _validate_temporal(self.start, "Event start")
        _validate_temporal(self.end, "Event end")
        _validate_text(self.location, "Event location")
        if self.all_day != (type(self.start) is date and type(self.end) is date):
            raise PlanningDataError(
                "All-day events require date values; timed events require datetimes."
            )
        if type(self.start) is not type(self.end) or self.end <= self.start:
            raise PlanningDataError("Event end must be after its matching start value.")


@runtime_checkable
class PlanningPort(Protocol):
    """Replaceable boundary for durable portable planning objects."""

    def status(self) -> PlanningStatus: ...

    def list_collections(self) -> tuple[PlanningCollection, ...]: ...

    def create_task(self, task: Task) -> Task: ...

    def get_task(self, collection_id: str, uid: str) -> Task: ...

    def list_tasks(self, collection_id: str) -> tuple[Task, ...]: ...

    def update_task(self, task: Task, *, expected_revision: str) -> Task: ...

    def delete_task(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None: ...

    def create_event(self, event: Event) -> Event: ...

    def get_event(self, collection_id: str, uid: str) -> Event: ...

    def list_events(self, collection_id: str) -> tuple[Event, ...]: ...

    def update_event(self, event: Event, *, expected_revision: str) -> Event: ...

    def delete_event(
        self, collection_id: str, uid: str, *, expected_revision: str
    ) -> None: ...


class DisabledPlanningPort:
    """Truthful disabled implementation used when Planning is not configured."""

    def status(self) -> PlanningStatus:
        return PlanningStatus(PlanningAvailability.DISABLED, "Planning is disabled.")

    def __getattr__(self, name: str) -> object:
        if name.startswith(("list_", "create_", "get_", "update_", "delete_")):
            def unavailable(*args: object, **kwargs: object) -> object:
                raise PlanningUnavailableError("Planning is disabled.")
            return unavailable
        raise AttributeError(name)


class UnavailablePlanningPort(DisabledPlanningPort):
    """Configured implementation that could not be constructed safely."""

    def status(self) -> PlanningStatus:
        return PlanningStatus(
            PlanningAvailability.UNAVAILABLE,
            "Planning is configured but unavailable.",
        )

    def __getattr__(self, name: str) -> object:
        if name.startswith(("list_", "create_", "get_", "update_", "delete_")):
            def unavailable(*args: object, **kwargs: object) -> object:
                raise PlanningUnavailableError(
                    "Planning is configured but unavailable."
                )
            return unavailable
        raise AttributeError(name)


def completed_task(task: Task, when: datetime) -> Task:
    """Return the domain transition used by PlanningService completion."""

    _validate_datetime(when, "Task completed timestamp")
    return replace(task, completed=True, completed_at=when)


def _validate_common(uid: str, title: str, description: str, collection_id: str) -> None:
    if not isinstance(uid, str) or not _UID.fullmatch(uid):
        raise PlanningDataError("Planning UID is invalid.")
    _validate_text(title, "Planning title", required=True)
    _validate_text(description, "Planning description")
    _validate_text(collection_id, "Planning collection identity", required=True)


def _validate_text(value: str, label: str, *, required: bool = False) -> None:
    if not isinstance(value, str) or (required and not value.strip()):
        raise PlanningDataError(f"{label} is invalid.")
    if len(value) > 4096 or any(character in "\x00\r" for character in value):
        raise PlanningDataError(f"{label} is invalid.")


def _validate_temporal(value: date | datetime | None, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, date):
        raise PlanningDataError(f"{label} is invalid.")
    if isinstance(value, datetime):
        _validate_datetime(value, label)


def _validate_datetime(value: datetime | None, label: str) -> None:
    if value is not None and (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PlanningDataError(f"{label} must be timezone-aware.")
