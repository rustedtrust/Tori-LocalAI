"""Standard iCalendar mapping for Tori planning domain objects."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from icalendar import Alarm, Calendar, Event as ICalendarEvent, Todo, vRecur

from .planning import (
    Event, PlanningDataError, PlanningReminder, PlanningRevision, RecurrenceRule,
    Task,
)


def serialize_task(task: Task) -> str:
    calendar = _calendar()
    component = Todo()
    _write_common(component, task.uid, task.title, task.description)
    if task.start is not None:
        component.add("dtstart", task.start)
    if task.due is not None:
        component.add("due", task.due)
    if task.priority is not None:
        component.add("priority", task.priority)
    if task.completed:
        component.add("status", "COMPLETED")
        component.add("percent-complete", 100)
        component.add("completed", task.completed_at.astimezone(timezone.utc))
    else:
        component.add("status", "NEEDS-ACTION")
    _write_recurrence_and_reminders(component, task.recurrence, task.reminders)
    calendar.add_component(component)
    return calendar.to_ical().decode("utf-8")


def deserialize_task(
    data: str | bytes, *, collection_id: str, revision: str | None = None
) -> Task:
    component = _component(data, "VTODO")
    completed_at = _decoded(component, "COMPLETED")
    completed = str(component.get("STATUS", "")).upper() == "COMPLETED"
    if completed and not isinstance(completed_at, datetime):
        raise PlanningDataError("Completed VTODO is missing a valid COMPLETED value.")
    return Task(
        uid=_text(component, "UID", required=True),
        title=_text(component, "SUMMARY", required=True),
        collection_id=collection_id,
        description=_text(component, "DESCRIPTION"),
        start=_decoded(component, "DTSTART"),
        due=_decoded(component, "DUE"),
        completed=completed,
        completed_at=completed_at if completed else None,
        priority=_integer(component, "PRIORITY"),
        recurrence=_recurrence(component),
        reminders=_reminders(component),
        revision=PlanningRevision(revision) if revision else None,
    )


def serialize_event(event: Event) -> str:
    calendar = _calendar()
    component = ICalendarEvent()
    _write_common(component, event.uid, event.title, event.description)
    component.add("dtstart", event.start)
    component.add("dtend", event.end)
    if event.location:
        component.add("location", event.location)
    _write_recurrence_and_reminders(component, event.recurrence, event.reminders)
    calendar.add_component(component)
    return calendar.to_ical().decode("utf-8")


def deserialize_event(
    data: str | bytes, *, collection_id: str, revision: str | None = None
) -> Event:
    component = _component(data, "VEVENT")
    start = _decoded(component, "DTSTART")
    end = _decoded(component, "DTEND")
    if not isinstance(start, date) or not isinstance(end, date):
        raise PlanningDataError("VEVENT requires valid DTSTART and DTEND values.")
    return Event(
        uid=_text(component, "UID", required=True),
        title=_text(component, "SUMMARY", required=True),
        collection_id=collection_id,
        start=start,
        end=end,
        description=_text(component, "DESCRIPTION"),
        all_day=type(start) is date,
        location=_text(component, "LOCATION"),
        recurrence=_recurrence(component),
        reminders=_reminders(component),
        revision=PlanningRevision(revision) if revision else None,
    )


def _calendar() -> Calendar:
    value = Calendar()
    value.add("prodid", "-//Tori Planning//EN")
    value.add("version", "2.0")
    value.add("calscale", "GREGORIAN")
    return value


def _write_common(component: object, uid: str, title: str, description: str) -> None:
    component.add("uid", uid)
    component.add("dtstamp", datetime.now(timezone.utc))
    component.add("summary", title)
    if description:
        component.add("description", description)


def _write_recurrence_and_reminders(
    component: object,
    recurrence: RecurrenceRule | None,
    reminders: tuple[PlanningReminder, ...],
) -> None:
    if recurrence is not None:
        try:
            component.add("rrule", vRecur.from_ical(recurrence.value))
        except (TypeError, ValueError) as exc:
            raise PlanningDataError("Recurrence is not a valid RRULE value.") from exc
    for reminder in reminders:
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("trigger", reminder.trigger)
        alarm.add("description", reminder.description)
        component.add_component(alarm)


def _component(data: str | bytes, name: str) -> object:
    try:
        calendar = Calendar.from_ical(data)
        matches = [item for item in calendar.walk(name) if item.name == name]
    except (TypeError, ValueError) as exc:
        raise PlanningDataError("The backend returned invalid iCalendar data.") from exc
    if len(matches) != 1:
        raise PlanningDataError(f"Expected exactly one {name} component.")
    return matches[0]


def _text(component: object, key: str, *, required: bool = False) -> str:
    value = component.get(key)
    text = "" if value is None else str(value)
    if required and not text.strip():
        raise PlanningDataError(f"{key} is required.")
    return text


def _decoded(component: object, key: str) -> date | datetime | None:
    value = component.get(key)
    if value is None:
        return None
    try:
        return value.dt
    except AttributeError as exc:
        raise PlanningDataError(f"{key} has an invalid value.") from exc


def _integer(component: object, key: str) -> int | None:
    value = component.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlanningDataError(f"{key} has an invalid value.") from exc


def _recurrence(component: object) -> RecurrenceRule | None:
    value = component.get("RRULE")
    if value is None:
        return None
    return RecurrenceRule(value.to_ical().decode("ascii"))


def _reminders(component: object) -> tuple[PlanningReminder, ...]:
    result: list[PlanningReminder] = []
    for alarm in component.subcomponents:
        if alarm.name != "VALARM":
            continue
        action = _text(alarm, "ACTION", required=True).upper()
        trigger = _decoded(alarm, "TRIGGER")
        if action != "DISPLAY" or not isinstance(trigger, timedelta):
            raise PlanningDataError("Only relative DISPLAY alarms are supported.")
        result.append(PlanningReminder(trigger, _text(alarm, "DESCRIPTION", required=True)))
    return tuple(result)
