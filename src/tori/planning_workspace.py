"""Bounded server-owned Planning projection for the compact Workspace UI."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import Any

from .planning import Event, PlanningAvailability, PlanningError, Task
from .planning_application import PlanningService
from .planning_conversation import (
    _event_occurrences, _format_temporal,
    _is_overdue, _task_occurrences,
    _recurrence_label,
)
from .time_context import TimeContext


class PlanningWorkspaceProjection:
    """Read fresh canonical Planning state and publish presentation-only values."""

    def __init__(self, planning: PlanningService) -> None:
        self._planning = planning

    def document(self, context: TimeContext) -> dict[str, Any]:
        status = self._planning.status()
        if status.availability is not PlanningAvailability.AVAILABLE:
            return {"available": False, "message": "Planning is currently unavailable."}
        try:
            tasks, events, collections = self._snapshot()
        except PlanningError:
            return {"available": False, "message": "Planning is currently unavailable."}
        local_today = context.local_date
        start = context.resolve_civil(local_today, datetime.min.time())
        end = start + timedelta(days=8)
        calendar_start = start - timedelta(days=3)
        calendar_end = start + timedelta(days=11)

        projected_tasks = [self._task(item, context, collections) for item in tasks]
        projected_tasks.sort(key=lambda item: (item["completed"], item["sort_at"], item["title"].casefold()))
        occurrences: list[dict[str, Any]] = []
        for occurrence in _event_occurrences(
            events, calendar_start.date(), (calendar_end - timedelta(days=1)).date(), context
        ):
            occurrences.append(self._event(occurrence, context, collections))
        occurrences.sort(key=lambda item: (item["sort_at"], item["title"].casefold()))

        today_events = [item for item in occurrences if item["date"] == local_today.isoformat()]
        due_today = [item for item in projected_tasks if not item["completed"] and item["due_date"] == local_today.isoformat()]
        overdue = [item for item in projected_tasks if item["overdue"]]
        today_overdue = [item for item in overdue if item["due_date"] != local_today.isoformat()]
        upcoming_tasks: list[dict[str, Any]] = []
        for task in _task_occurrences(tasks, local_today, (end - timedelta(days=1)).date(), context):
            if task.completed:
                continue
            projected = self._task(task, context, collections)
            if projected["due_date"] is not None and projected["due_date"] >= local_today.isoformat():
                upcoming_tasks.append(projected)
        last_upcoming_date = (local_today + timedelta(days=6)).isoformat()
        upcoming = [
            item for item in occurrences
            if local_today.isoformat() <= item["date"] <= last_upcoming_date
        ]
        upcoming.extend(upcoming_tasks)
        upcoming.sort(key=lambda item: (item["sort_at"], item["kind"], item["title"].casefold()))
        return {
            "available": True,
            "timezone": context.timezone_name,
            "generated_at_utc": context.captured_utc.isoformat().replace("+00:00", "Z"),
            "today": {"date": local_today.isoformat(), "events": today_events,
                      "due_tasks": due_today, "overdue_tasks": today_overdue},
            "upcoming": {"days": 7, "items": upcoming},
            "tasks": {
                "open": [item for item in projected_tasks if not item["completed"]],
                "due": [item for item in projected_tasks if not item["completed"] and item["due"]],
                "overdue": overdue,
                "completed": [item for item in projected_tasks if item["completed"]],
            },
            "calendar": {"start": (local_today - timedelta(days=3)).isoformat(),
                         "days": 14, "events": occurrences},
        }

    def _snapshot(self) -> tuple[tuple[Task, ...], tuple[Event, ...], dict[str, str]]:
        tasks: list[Task] = []
        events: list[Event] = []
        names: dict[str, str] = {}
        for collection in self._planning.list_collections():
            names[collection.identifier] = collection.name
            if collection.supports_tasks:
                tasks.extend(self._planning.list_tasks(collection.identifier))
            if collection.supports_events:
                events.extend(self._planning.list_events(collection.identifier))
        return tuple(tasks), tuple(events), names

    def _task(self, task: Task, context: TimeContext, names: dict[str, str]) -> dict[str, Any]:
        due = task.due
        return {
            "kind": "task", "key": _key("task", task.collection_id, task.uid),
            "title": task.title, "notes": task.description[:240],
            "due": None if due is None else _iso(due),
            "due_date": None if due is None else _local_date(due, context).isoformat(),
            "due_label": None if due is None else _format_temporal(due, context),
            "sort_at": _sort_value(due, context), "overdue": _is_overdue(task, context),
            "completed": task.completed, "priority": task.priority,
            "recurrence": _recurrence_label(task.recurrence),
            "reminders": [_reminder(item.trigger) for item in task.reminders],
            "list": names.get(task.collection_id, "Tasks"),
        }

    def _event(self, event: Event, context: TimeContext, names: dict[str, str]) -> dict[str, Any]:
        return {
            "kind": "event", "key": _key("event", event.collection_id, event.uid),
            "title": event.title, "notes": event.description[:240],
            "date": _local_date(event.start, context).isoformat(),
            "start": _iso(event.start), "end": _iso(event.end), "sort_at": _sort_value(event.start, context),
            "start_label": "All day" if event.all_day else _format_temporal(event.start, context, time_only=True),
            "end_label": None if event.all_day else _format_temporal(event.end, context, time_only=True),
            "all_day": event.all_day, "location": event.location,
            "recurrence": _recurrence_label(event.recurrence),
            "reminders": [_reminder(item.trigger) for item in event.reminders],
            "calendar": names.get(event.collection_id, "Calendar"),
        }


def _key(kind: str, collection: str, uid: str) -> str:
    return sha256(f"{kind}\0{collection}\0{uid}".encode()).hexdigest()[:24]


def _iso(value: date | datetime) -> str:
    return value.isoformat()


def _local_date(value: date | datetime, context: TimeContext) -> date:
    return value.astimezone(context.zone).date() if isinstance(value, datetime) else value


def _sort_value(value: date | datetime | None, context: TimeContext) -> str:
    if value is None:
        return "9999-12-31T23:59:59+00:00"
    if isinstance(value, datetime):
        return value.isoformat()
    return context.resolve_civil(value, datetime.min.time()).isoformat()


def _reminder(trigger: timedelta) -> str:
    seconds = int(trigger.total_seconds())
    if seconds == 0:
        return "At due time"
    minutes = abs(seconds) // 60
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''} before"
    return f"{minutes} min before"
