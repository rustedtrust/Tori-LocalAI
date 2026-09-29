"""Bounded conversational reads and confirmed mutations for Planning."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import re
import secrets
from typing import Callable, Literal

from dateutil.rrule import rrulestr

from .planning import (
    Event,
    PlanningAvailability,
    PlanningError,
    PlanningNotFoundError,
    PlanningReminder,
    RecurrenceRule,
    Task,
)
from .planning_application import PlanningService
from .planning_reminder_bridge import PlanningReminderBridge, ReminderBridgeResult
from .time_context import TimeContext, TimeContextError
from .capability_registry import is_capability_discussion


PlanningKind = Literal["task", "event"]
PlanningOperation = Literal[
    "create_task", "create_event", "update_task", "update_event",
    "complete_task", "delete_task", "delete_event",
]

_WEEKDAYS = {
    "monday": (0, "MO"), "tuesday": (1, "TU"),
    "wednesday": (2, "WE"), "thursday": (3, "TH"),
    "friday": (4, "FR"), "saturday": (5, "SA"), "sunday": (6, "SU"),
}
_MONTHS = {
    name.casefold(): number for number, name in enumerate(
        (
            "", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        )
    ) if name
}
_READ_HINT = re.compile(
    r"(?i)^(?:what\b|what's\b|what\s+is\b|what\s+do\s+i\s+have\b|"
    r"show\s+(?:me|my)\b|list\b|do\s+i\s+have\b|are\s+there\b|"
    r"anything\s+scheduled\b|what(?:'s|\s+is)\s+happening\b)"
)
_PLANNING_NOUN = re.compile(
    r"(?i)\b(?:calendar|schedule|events?|appointments?|tasks?|to-?do|todos|"
    r"due|overdue|upcoming|coming up|today|tomorrow|this week)\b"
)
_WEATHER_NOUN = re.compile(r"(?i)\b(?:weather|forecast|temperature)\b")
_CREATE_TASK = re.compile(
    r"(?is)^(?:add|create)\s+(?:a\s+)?(?:task|to-?do)(?:\s+to)?\s+(.+?)\s*[.!?]?$"
)
_TODO_LIST = re.compile(
    r"(?is)^add\s+(.+?)\s+to\s+my\s+(?:to-?do|task)\s+list\s*[.!?]?$"
)
_NEED_TASK = re.compile(
    r"(?is)^i\s+need\s+to\s+(.+?)\s*[.!?]?$"
)
_RECURRING_TASK_PREFIX = re.compile(
    r"(?is)^(?:add|create)\s+(?:a\s+)?(?:task|to-?do)\s+"
    r"(?P<repeat>every\s+.+?)\s+to\s+(?P<title>.+?)\s*[.!?]?$"
)
_CREATE_EVENT = re.compile(
    r"(?is)^(?:add|put|schedule)\s+(?:an?\s+)?(?P<body>.+?)\s*[.!?]?$"
)
_STANDALONE_REMINDER = (
    re.compile(r"(?is)^remind\s+me\s+(?P<when>.+?)\s+to\s+(?P<title>.+?)\s*[.!?]?$"),
    re.compile(r"(?is)^remind\s+me\s+to\s+(?P<title>.+?)\s+(?P<when>(?:today|tomorrow|(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)).+?)\s*[.!?]?$"),
)
_BEFORE_REMINDER = re.compile(
    r"(?is)^remind\s+me\s+(?P<amount>\d+\s+(?:minutes?|hours?))\s+before\s+"
    r"(?:my\s+|the\s+)?(?P<target>.+?)\s*[.!?]?$"
)
_COMPLETE = re.compile(
    r"(?is)^(?:mark\s+|complete\s+)(?:the\s+)?(?P<target>.+?)"
    r"(?:\s+(?:done|complete|completed))?\s*[.!?]?$"
)
_DELETE = re.compile(
    r"(?is)^(?P<verb>delete|cancel|remove)\s+(?:the\s+)?(?P<target>.+?)\s*[.!?]?$"
)
_MOVE = re.compile(
    r"(?is)^(?:move|reschedule)\s+(?:the\s+)?(?P<target>.+?)\s+to\s+(?P<when>.+?)\s*[.!?]?$"
)
_MAKE_DUE = re.compile(
    r"(?is)^make\s+(?P<target>.+?)\s+due\s+(?P<when>.+?)(?:\s+instead)?\s*[.!?]?$"
)
_CHANGE_REMINDER = re.compile(
    r"(?is)^change\s+(?:my\s+|the\s+|that\s+)?reminder\s+to\s+(?P<when>.+?)\s*[.!?]?$"
)
_CHANGE_RECURRENCE = re.compile(
    r"(?is)^change\s+(?P<target>it|that|that\s+(?:task|event|appointment)|.+?)\s+to\s+"
    r"(?P<repeat>(?:every|daily|weekly).+?)\s*[.!?]?$"
)
_RELATIVE_REMINDER = re.compile(
    r"(?i)(?P<number>\d+)\s*(?P<unit>minutes?|hours?)\s+before"
)
_PRIORITY = re.compile(r"(?i)\b(?P<level>high|medium|normal|low)\s+priority\b")
_DATE_TOKEN = re.compile(
    r"(?i)\b(today|tomorrow|(?:next\s+)?(?:monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|(?:january|february|march|april|may|june|july|"
    r"august|september|october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?)\b"
)
_CLOCK_TOKEN = re.compile(
    r"(?i)\b(noon|midnight|(?:0?[1-9]|1[0-2])(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?|"
    r"(?:1[3-9]|2[0-3]|[01]?\d):[0-5]\d)\b"
)
_REFERENCE_WORDS = frozenset({
    "it", "that", "that task", "that event", "that appointment", "that reminder",
    "my reminder", "the reminder",
})
_MAX_RESULTS = 30
_MAX_RECURRENCE_INSTANCES = 256


class PlanningConversationError(RuntimeError):
    """A bounded conversational Planning failure."""

    def __init__(self, message: str, *, code: str = "planning_conversation_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlanningReference:
    kind: PlanningKind
    collection_id: str
    uid: str
    title: str


@dataclass(frozen=True, slots=True)
class PlanningMutation:
    operation: PlanningOperation
    kind: PlanningKind
    before: Task | Event | None
    after: Task | Event | None
    expected_revision: str | None
    presentation: str

    @property
    def reference(self) -> PlanningReference | None:
        item = self.after or self.before
        if item is None:
            return None
        return PlanningReference(self.kind, item.collection_id, item.uid, item.title)

    def document(self) -> dict[str, object]:
        item = self.after or self.before
        return {
            "action": self.operation.replace("_", " "),
            "kind": self.kind,
            "title": None if item is None else item.title,
            "review": self.presentation,
        }


@dataclass(frozen=True, slots=True)
class PlanningConversationTurn:
    handled: bool
    text: str | None = None
    mutation: PlanningMutation | None = None
    reference: PlanningReference | None = None


@dataclass(frozen=True, slots=True)
class PlanningMutationResult:
    text: str
    reference: PlanningReference | None
    bridge: ReminderBridgeResult | None


class PlanningConversationService:
    """Interpret only bounded Planning language; authorize no mutation itself."""

    def __init__(
        self,
        planning: PlanningService,
        *,
        reminder_bridge: PlanningReminderBridge | None = None,
        default_task_list: str | None = None,
        default_calendar: str | None = None,
        uid_factory: Callable[[], str] | None = None,
    ) -> None:
        self._planning = planning
        self._bridge = reminder_bridge
        self._default_task_list = default_task_list
        self._default_calendar = default_calendar
        self._uid_factory = uid_factory or (lambda: f"tori-{secrets.token_hex(16)}")

    def interpret(
        self,
        text: str,
        *,
        time_context: TimeContext,
        recent: PlanningReference | None = None,
    ) -> PlanningConversationTurn:
        normalized = " ".join(text.strip().split())
        if is_capability_discussion(normalized):
            return PlanningConversationTurn(False)
        if not _likely_planning(normalized):
            return PlanningConversationTurn(False)
        try:
            read = self._read_turn(normalized, time_context)
            if read is not None:
                return read
            return self._mutation_turn(normalized, time_context, recent)
        except PlanningConversationError:
            raise
        except PlanningError as exc:
            raise PlanningConversationError(
                "Planning is unavailable right now, so nothing was changed.",
                code="planning_unavailable",
            ) from exc
        except TimeContextError as exc:
            raise PlanningConversationError(str(exc), code="invalid_time") from exc

    def apply(self, mutation: PlanningMutation, *, completed_at: datetime) -> PlanningMutationResult:
        try:
            current = self._current_target(mutation)
            if mutation.operation == "create_task":
                assert isinstance(mutation.after, Task)
                changed: Task | Event = self._planning.create_task(mutation.after)
                text = f"Created task “{changed.title}”."
            elif mutation.operation == "create_event":
                assert isinstance(mutation.after, Event)
                changed = self._planning.create_event(mutation.after)
                text = f"Created event “{changed.title}”."
            elif mutation.operation == "update_task":
                assert isinstance(current, Task) and isinstance(mutation.after, Task)
                changed = self._planning.update_task(
                    replace(mutation.after, revision=current.revision),
                    expected_revision=mutation.expected_revision or "",
                )
                text = f"Updated task “{changed.title}”."
            elif mutation.operation == "update_event":
                assert isinstance(current, Event) and isinstance(mutation.after, Event)
                changed = self._planning.update_event(
                    replace(mutation.after, revision=current.revision),
                    expected_revision=mutation.expected_revision or "",
                )
                text = f"Updated event “{changed.title}”."
            elif mutation.operation == "complete_task":
                assert isinstance(current, Task)
                changed = self._planning.complete_task(
                    current,
                    when=completed_at,
                    expected_revision=mutation.expected_revision or "",
                )
                text = f"Completed task “{changed.title}”."
            elif mutation.operation == "delete_task":
                assert isinstance(current, Task)
                self._planning.delete_task(
                    current.collection_id, current.uid,
                    expected_revision=mutation.expected_revision or "",
                )
                changed = current
                text = f"Deleted task “{current.title}”."
            elif mutation.operation == "delete_event":
                assert isinstance(current, Event)
                self._planning.delete_event(
                    current.collection_id, current.uid,
                    expected_revision=mutation.expected_revision or "",
                )
                changed = current
                text = f"Cancelled event “{current.title}”."
            else:  # pragma: no cover - closed literal guarded by construction
                raise PlanningConversationError("The Planning operation is invalid.")
        except PlanningNotFoundError as exc:
            raise PlanningConversationError(
                "That Planning item changed or was removed before confirmation. Nothing was overwritten.",
                code="stale_confirmation",
            ) from exc
        except PlanningError as exc:
            if getattr(exc, "code", None) == "revision_conflict":
                raise PlanningConversationError(
                    "That Planning item changed before confirmation. Nothing was overwritten.",
                    code="stale_confirmation",
                ) from exc
            raise PlanningConversationError(
                "Planning is unavailable right now, so the change was not applied.",
                code="planning_unavailable",
            ) from exc

        bridge = None
        if self._bridge is not None:
            bridge = (
                self._bridge.reconcile()
                if mutation.operation in {"delete_task", "delete_event"}
                else self._bridge.reconcile_object(changed)
            )
            if bridge.failures or not bridge.available:
                text += " The Planning change succeeded, but reminder delivery will reconcile later."
        reference = None if mutation.operation.startswith("delete_") else PlanningReference(
            mutation.kind, changed.collection_id, changed.uid, changed.title
        )
        return PlanningMutationResult(text, reference, bridge)

    def _current_target(self, mutation: PlanningMutation) -> Task | Event | None:
        if mutation.before is None:
            return None
        before = mutation.before
        current: Task | Event = (
            self._planning.get_task(before.collection_id, before.uid)
            if mutation.kind == "task"
            else self._planning.get_event(before.collection_id, before.uid)
        )
        current_revision = None if current.revision is None else current.revision.token
        if current_revision != mutation.expected_revision:
            raise PlanningConversationError(
                "That Planning item changed before confirmation. Nothing was overwritten.",
                code="stale_confirmation",
            )
        return current

    def _read_turn(self, text: str, context: TimeContext) -> PlanningConversationTurn | None:
        lowered = text.casefold()
        if not _planning_read_request(text):
            return None
        tasks, events = self._snapshot()
        task_only = bool(re.search(r"(?i)\b(?:tasks?|to-?do|todos|due|overdue)\b", text))
        event_only = bool(re.search(r"(?i)\b(?:calendar|events?|appointments?)\b", text))
        if "overdue" in lowered:
            selected_tasks = [item for item in tasks if not item.completed and _is_overdue(item, context)]
            return _formatted_turn("Overdue tasks", selected_tasks, (), context)
        if "completed" in lowered and task_only:
            return _formatted_turn("Completed tasks", [item for item in tasks if item.completed], (), context)
        if task_only and not any(word in lowered for word in ("today", "tomorrow", "week")):
            selected = [item for item in tasks if not item.completed]
            if "due" in lowered:
                selected = [item for item in selected if item.due is not None]
            return _formatted_turn("Open tasks", selected, (), context)

        start_date, end_date, label, afternoon = _query_range(text, context)
        selected_tasks = [] if event_only else [
            item for item in _task_occurrences(tasks, start_date, end_date, context)
            if not item.completed and _task_in_range(item, start_date, end_date, context)
        ]
        selected_events = [] if task_only else list(
            _event_occurrences(events, start_date, end_date, context)
        )
        if afternoon:
            selected_events = [
                item for item in selected_events
                if isinstance(item.start, datetime)
                and 12 <= item.start.astimezone(context.zone).hour < 17
            ]
        return _formatted_turn(label, selected_tasks, selected_events, context)

    def _mutation_turn(
        self,
        text: str,
        context: TimeContext,
        recent: PlanningReference | None,
    ) -> PlanningConversationTurn:
        before_alarm = _BEFORE_REMINDER.fullmatch(text)
        if before_alarm is not None:
            target_text = _strip_target_kind(before_alarm.group("target"))
            target = self._resolve_target(target_text, recent, kind="event")
            offset = -_duration(before_alarm.group("amount"))
            assert isinstance(target, Event)
            reminder = PlanningReminder(offset, target.title)
            if reminder in target.reminders:
                return PlanningConversationTurn(True, f"“{target.title}” already has that reminder.", reference=_reference(target))
            revised = replace(target, reminders=(*target.reminders, reminder))
            return _proposal_turn("update_event", target, revised, context, "Add reminder")

        for pattern in _STANDALONE_REMINDER:
            match = pattern.fullmatch(text)
            if match is not None:
                when = _resolve_datetime(match.group("when"), context, require_time=True)
                title = _clean_title(match.group("title"))
                collection = self._collection("task")
                task = Task(
                    self._uid_factory(), title, collection,
                    due=when, reminders=(PlanningReminder(timedelta(0), title),),
                )
                return _proposal_turn("create_task", None, task, context, "Create reminder")

        recurring_task = _RECURRING_TASK_PREFIX.fullmatch(text)
        if recurring_task is not None:
            recurrence, first = _parse_recurrence(recurring_task.group("repeat"), context)
            if recurrence is None or first is None:
                return _clarify("Please give the recurring task a supported weekday or interval and an exact time.")
            task = Task(
                self._uid_factory(), _clean_title(recurring_task.group("title")),
                self._collection("task"), due=first, recurrence=recurrence,
            )
            return _proposal_turn("create_task", None, task, context, "Create recurring task")

        task_match = _CREATE_TASK.fullmatch(text) or _TODO_LIST.fullmatch(text) or _NEED_TASK.fullmatch(text)
        if task_match is not None:
            body = task_match.group(1)
            if task_match.re is _NEED_TASK and _DATE_TOKEN.search(body) is None:
                return PlanningConversationTurn(False)
            parsed = _parse_task_body(body, context)
            if parsed is None:
                return _clarify("I need a clearer task title or due date before I can propose that.")
            title, due, recurrence, reminders, priority = parsed
            task = Task(
                self._uid_factory(), title, self._collection("task"), due=due,
                priority=priority, recurrence=recurrence, reminders=reminders,
            )
            return _proposal_turn("create_task", None, task, context, "Create task")

        complete = _COMPLETE.fullmatch(text)
        if complete is not None and re.search(r"(?i)\b(?:done|complete|completed)\b", text):
            target = self._resolve_target(complete.group("target"), recent, kind="task")
            assert isinstance(target, Task)
            return _proposal_turn("complete_task", target, target, context, "Complete task")

        move = _MOVE.fullmatch(text)
        if move is not None:
            target = self._resolve_target(_strip_target_kind(move.group("target")), recent)
            revised = _move_item(target, move.group("when"), context)
            return _proposal_turn(
                "update_task" if isinstance(target, Task) else "update_event",
                target, revised, context, "Reschedule",
            )

        due = _MAKE_DUE.fullmatch(text)
        if due is not None:
            target = self._resolve_target(due.group("target"), recent, kind="task")
            assert isinstance(target, Task)
            revised = replace(target, due=_resolve_date_or_datetime(due.group("when"), context))
            return _proposal_turn("update_task", target, revised, context, "Change task due date")

        recurrence = _CHANGE_RECURRENCE.fullmatch(text)
        if recurrence is not None:
            target = self._resolve_target(recurrence.group("target"), recent)
            rule, first = _parse_recurrence(recurrence.group("repeat"), context, existing=target)
            if rule is None:
                return _clarify("That recurrence is not supported clearly enough to change anything.")
            revised = replace(target, recurrence=rule)
            if first is not None:
                if isinstance(revised, Task):
                    revised = replace(revised, due=first)
                elif isinstance(revised.start, datetime):
                    duration = revised.end - revised.start
                    revised = replace(revised, start=first, end=first + duration)
            return _proposal_turn(
                "update_task" if isinstance(target, Task) else "update_event",
                target, revised, context, "Change recurrence",
            )

        changed_reminder = _CHANGE_REMINDER.fullmatch(text)
        if changed_reminder is not None:
            target = self._resolve_target("that reminder", recent)
            if isinstance(target, Task):
                supplied = changed_reminder.group("when")
                if _DATE_TOKEN.search(supplied) is not None:
                    new_when = _resolve_datetime(supplied, context, require_time=True)
                else:
                    clock = _CLOCK_TOKEN.search(supplied)
                    if clock is None or target.due is None:
                        return _clarify("Please give the reminder one clear date and time.")
                    due_date = (
                        target.due.astimezone(context.zone).date()
                        if isinstance(target.due, datetime) else target.due
                    )
                    reference_time = (
                        target.due.astimezone(context.zone).time().replace(tzinfo=None)
                        if isinstance(target.due, datetime) else None
                    )
                    new_when = context.resolve_civil(
                        due_date, _parse_clock(clock.group(1), reference=reference_time)
                    )
                revised = replace(
                    target, due=new_when,
                    reminders=target.reminders or (PlanningReminder(timedelta(0), target.title),),
                )
                return _proposal_turn("update_task", target, revised, context, "Reschedule reminder")
            return _clarify("Please identify a standalone reminder or say how long before the event to remind you.")

        deletion = _DELETE.fullmatch(text)
        if deletion is not None:
            raw = deletion.group("target")
            target = self._resolve_target(_strip_target_kind(raw), recent)
            remove_only_alarm = (
                deletion.group("verb").casefold() == "remove"
                and "reminder" in raw.casefold()
                and isinstance(target, Event)
            )
            if remove_only_alarm:
                revised = replace(target, reminders=())
                return _proposal_turn("update_event", target, revised, context, "Remove reminder")
            operation: PlanningOperation = "delete_task" if isinstance(target, Task) else "delete_event"
            return _proposal_turn(operation, target, None, context, "Delete" if isinstance(target, Task) else "Cancel")

        event_match = _CREATE_EVENT.fullmatch(text)
        if event_match is not None:
            body = event_match.group("body")
            if re.match(r"(?i)^(?:task|to-?do)\b", body):
                return PlanningConversationTurn(False)
            parsed_event = _parse_event_body(body, context)
            if parsed_event is None:
                if _DATE_TOKEN.search(body) is not None:
                    return _clarify("Please give the event one clear date and time. Nothing changed.")
                return PlanningConversationTurn(False)
            title, start, end, all_day, recurrence, reminders, location = parsed_event
            event = Event(
                self._uid_factory(), title, self._collection("event"), start, end,
                all_day=all_day, recurrence=recurrence, reminders=reminders,
                location=location,
            )
            return _proposal_turn("create_event", None, event, context, "Create event")

        return PlanningConversationTurn(False)

    def _snapshot(self) -> tuple[tuple[Task, ...], tuple[Event, ...]]:
        status = self._planning.status()
        if status.availability is not PlanningAvailability.AVAILABLE:
            raise PlanningConversationError(
                "Planning is unavailable right now.", code="planning_unavailable"
            )
        tasks: list[Task] = []
        events: list[Event] = []
        for collection in self._planning.list_collections():
            if collection.supports_tasks:
                tasks.extend(self._planning.list_tasks(collection.identifier))
            if collection.supports_events:
                events.extend(self._planning.list_events(collection.identifier))
        return tuple(tasks), tuple(events)

    def _collection(self, kind: PlanningKind) -> str:
        status = self._planning.status()
        if status.availability is not PlanningAvailability.AVAILABLE:
            raise PlanningConversationError(
                "Planning is unavailable right now, so no proposal was created.",
                code="planning_unavailable",
            )
        collections = self._planning.list_collections()
        configured = self._default_task_list if kind == "task" else self._default_calendar
        supported = [
            item for item in collections
            if (item.supports_tasks if kind == "task" else item.supports_events)
        ]
        if configured is not None:
            for item in supported:
                if item.identifier == configured:
                    return configured
            raise PlanningConversationError(
                f"The configured default {kind} collection is unavailable.",
                code="planning_unavailable",
            )
        if len(supported) == 1:
            return supported[0].identifier
        if not supported:
            raise PlanningConversationError(
                f"No writable {kind} collection is available.", code="planning_unavailable"
            )
        raise PlanningConversationError(
            f"Please configure a default {kind} collection before creating items.",
            code="planning_collection_ambiguous",
        )

    def _resolve_target(
        self,
        value: str,
        recent: PlanningReference | None,
        *,
        kind: PlanningKind | None = None,
    ) -> Task | Event:
        tasks, events = self._snapshot()
        candidates: list[Task | Event] = [
            *([] if kind == "event" else list(tasks)),
            *([] if kind == "task" else events),
        ]
        query = _normalized_title(_strip_target_kind(value))
        if query in _REFERENCE_WORDS or query == "":
            if recent is None or (kind is not None and recent.kind != kind):
                raise PlanningConversationError(
                    "I’m not sure which Planning item you mean. Nothing changed.",
                    code="ambiguous_reference",
                )
            matches = [
                item for item in candidates
                if item.uid == recent.uid and item.collection_id == recent.collection_id
            ]
        else:
            exact = [item for item in candidates if _normalized_title(item.title) == query]
            matches = exact or [
                item for item in candidates
                if query in _normalized_title(item.title)
                or _normalized_title(item.title) in query
            ]
        if not matches:
            raise PlanningConversationError(
                f"I couldn’t find a matching Planning item for “{_strip_target_kind(value)}”. Nothing changed.",
                code="not_found",
            )
        if len(matches) > 1:
            options = "; ".join(_candidate_label(item) for item in matches[:5])
            raise PlanningConversationError(
                f"I found multiple possible matches: {options}. Which one do you mean? Nothing changed.",
                code="ambiguous_reference",
            )
        return matches[0]


def _likely_planning(text: str) -> bool:
    if _planning_read_request(text):
        return True
    return any(pattern.fullmatch(text) for pattern in (
        _CREATE_TASK, _TODO_LIST, _NEED_TASK, _RECURRING_TASK_PREFIX,
        *_STANDALONE_REMINDER, _BEFORE_REMINDER, _COMPLETE, _DELETE,
        _MOVE, _MAKE_DUE, _CHANGE_REMINDER, _CHANGE_RECURRENCE,
    )) or bool(_CREATE_EVENT.fullmatch(text) and _DATE_TOKEN.search(text))


def _planning_read_request(text: str) -> bool:
    if _WEATHER_NOUN.search(text):
        return False
    return bool(
        _READ_HINT.search(text)
        and (_PLANNING_NOUN.search(text) or _DATE_TOKEN.search(text))
    )


def _proposal_turn(
    operation: PlanningOperation,
    before: Task | Event | None,
    after: Task | Event | None,
    context: TimeContext,
    label: str,
) -> PlanningConversationTurn:
    item = after or before
    assert item is not None
    if before is not None and before.revision is None:
        raise PlanningConversationError(
            "That Planning item has no revision that can be safely confirmed. Nothing was changed.",
            code="stale_confirmation",
        )
    kind: PlanningKind = "task" if isinstance(item, Task) else "event"
    expected = None if before is None or before.revision is None else before.revision.token
    presentation = _proposal_message(label, before, after, context)
    return PlanningConversationTurn(
        True,
        presentation,
        PlanningMutation(operation, kind, before, after, expected, presentation),
        _reference(item),
    )


def _clarify(text: str) -> PlanningConversationTurn:
    return PlanningConversationTurn(True, text)


def _proposal_message(
    label: str,
    before: Task | Event | None,
    after: Task | Event | None,
    context: TimeContext,
) -> str:
    item = after or before
    assert item is not None
    lines = ["Planning proposal", f"Action: {label}", f"Title: {item.title}"]
    if before is not None and after is not None and _when(before, context) != _when(after, context):
        lines.extend((f"From: {_when(before, context)}", f"To: {_when(after, context)}"))
    else:
        lines.append(f"When: {_when(item, context)}")
    lines.append(f"Recurrence: {_recurrence_label(item.recurrence)}")
    lines.append(f"Reminder: {_reminder_label(item.reminders)}")
    lines.append("Confirm to apply this exact Planning change.")
    return "\n".join(lines)


def _formatted_turn(
    label: str,
    tasks: list[Task],
    events: list[Event],
    context: TimeContext,
) -> PlanningConversationTurn:
    entries: list[tuple[datetime, str, PlanningReference]] = []
    for event in events:
        local = _item_datetime(event.start, context, end_of_day=False)
        text = (
            f"{local.strftime('%-I:%M %p')} — {event.title}"
            if isinstance(event.start, datetime)
            else f"All day — {event.title}"
        )
        entries.append((local, text, _reference(event)))
    for task in tasks:
        local = _item_datetime(task.due, context, end_of_day=True)
        suffix = "" if task.due is None else (
            f" — due {local.strftime('%-I:%M %p')}"
            if isinstance(task.due, datetime)
            else f" — due {local.strftime('%B %-d')}"
        )
        entries.append((local, f"{task.title}{suffix}", _reference(task)))
    entries.sort(key=lambda value: (value[0], value[1].casefold()))
    if not entries:
        return PlanningConversationTurn(True, f"{label}\n- Nothing scheduled.")
    selected = entries[:_MAX_RESULTS]
    text = label + "\n" + "\n".join(f"- {item[1]}" for item in selected)
    reference = selected[0][2] if len(selected) == 1 else None
    return PlanningConversationTurn(True, text, reference=reference)


def _query_range(text: str, context: TimeContext) -> tuple[date, date, str, bool]:
    lowered = text.casefold()
    afternoon = "afternoon" in lowered
    if "today" in lowered:
        return context.local_date, context.local_date, "Today", afternoon
    if "tomorrow" in lowered:
        selected = context.local_date + timedelta(days=1)
        return selected, selected, "Tomorrow", afternoon
    if "this week" in lowered:
        start = context.local_date
        return start, start + timedelta(days=6), "Upcoming — next 7 days", afternoon
    match_days = re.search(r"(?i)next\s+(\d{1,2})\s+days", text)
    if match_days is not None:
        days = max(1, min(31, int(match_days.group(1))))
        return context.local_date, context.local_date + timedelta(days=days - 1), f"Upcoming — next {days} days", afternoon
    token = _DATE_TOKEN.search(text)
    if token is not None:
        selected = _parse_date_token(token.group(1), context)
        return selected, selected, selected.strftime("%A, %B %-d"), afternoon
    if "upcoming" in lowered or "coming up" in lowered:
        return context.local_date, context.local_date + timedelta(days=6), "Upcoming — next 7 days", afternoon
    return context.local_date, context.local_date, "Today", afternoon


def _parse_task_body(
    body: str, context: TimeContext
) -> tuple[str, date | datetime | None, RecurrenceRule | None, tuple[PlanningReminder, ...], int | None] | None:
    text = body.strip().rstrip(".!?")
    priority = None
    priority_match = _PRIORITY.search(text)
    if priority_match is not None:
        priority = {"high": 1, "medium": 5, "normal": 5, "low": 9}[priority_match.group("level").casefold()]
        text = (text[:priority_match.start()] + text[priority_match.end():]).strip()
    reminder_offset = None
    reminder_match = _RELATIVE_REMINDER.search(text)
    if reminder_match is not None:
        reminder_offset = -_duration(reminder_match.group(0).removesuffix("before").strip())
        text = (text[:reminder_match.start()] + text[reminder_match.end():]).strip()
    recurrence, first = _parse_recurrence(text, context)
    if recurrence is not None:
        repeat = re.search(r"(?i)\b(?:every|daily|weekly)\b", text)
        if repeat is not None:
            text = text[:repeat.start()].strip()
    due: date | datetime | None = first
    date_match = _DATE_TOKEN.search(text)
    if date_match is not None:
        tail = text[date_match.start():]
        due = _resolve_date_or_datetime(tail, context)
        text = text[:date_match.start()].strip()
    text = re.sub(r"(?i)^(?:to\s+)", "", text).strip()
    title = _clean_title(text)
    if not title:
        return None
    reminders: tuple[PlanningReminder, ...] = ()
    if reminder_offset is not None:
        if not isinstance(due, datetime):
            return None
        reminders = (PlanningReminder(reminder_offset, title),)
    return title, due, recurrence, reminders, priority


def _parse_event_body(
    body: str, context: TimeContext
) -> tuple[str, date | datetime, date | datetime, bool, RecurrenceRule | None, tuple[PlanningReminder, ...], str] | None:
    text = body.strip().rstrip(".!?")
    text = re.sub(r"(?i)^(?:event|appointment)\s+", "", text).strip()
    reminder_offset = None
    reminder_match = _RELATIVE_REMINDER.search(text)
    if reminder_match is not None:
        reminder_offset = -_duration(reminder_match.group(0).removesuffix("before").strip())
        text = (text[:reminder_match.start()] + text[reminder_match.end():]).strip()
    date_match = _DATE_TOKEN.search(text)
    if date_match is None:
        return None
    selected_date = _parse_date_token(date_match.group(1), context)
    title = _clean_title(text[:date_match.start()])
    tail = text[date_match.end():].strip()
    if not title:
        return None
    if re.search(r"(?i)\ball[ -]?day\b", text):
        title = re.sub(r"(?i)\ball[ -]?day\b", "", title).strip()
        return _clean_title(title), selected_date, selected_date + timedelta(days=1), True, None, (), ""
    clocks = list(_CLOCK_TOKEN.finditer(tail))
    if not clocks:
        return None
    start_time = _parse_clock(clocks[0].group(1))
    start = context.resolve_civil(selected_date, start_time)
    duration = timedelta(hours=1)
    if len(clocks) >= 2 and re.search(r"(?i)\b(?:to|until|-)\b", tail[clocks[0].end():clocks[1].start()]):
        end_time = _parse_clock(clocks[1].group(1), reference=start_time)
        end = context.resolve_civil(selected_date, end_time)
        if end <= start:
            end += timedelta(days=1)
    else:
        duration_match = re.search(r"(?i)for\s+(?:(\d+)\s+)?(minutes?|hours?|an?\s+hour)", tail)
        if duration_match is not None:
            unit = duration_match.group(2).casefold()
            amount = 1 if duration_match.group(1) is None else int(duration_match.group(1))
            duration = timedelta(minutes=amount if unit.startswith("minute") else amount * 60)
        end = start + duration
    recurrence, recurring_start = _parse_recurrence(text, context)
    if recurring_start is not None:
        duration = end - start
        start, end = recurring_start, recurring_start + duration
    location = ""
    location_match = re.search(r"(?i)\bat\s+(.+)$", tail[clocks[-1].end():])
    if location_match is not None:
        location = location_match.group(1).strip()
    reminders = () if reminder_offset is None else (PlanningReminder(reminder_offset, title),)
    return title, start, end, False, recurrence, reminders, location


def _parse_recurrence(
    text: str,
    context: TimeContext,
    *,
    existing: Task | Event | None = None,
) -> tuple[RecurrenceRule | None, datetime | None]:
    match = re.search(
        r"(?i)\b(?:(daily|weekly)|every\s+(?:(\d+)|other)?\s*(day|days|week|weeks|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
        text,
    )
    if match is None:
        return None, None
    direct, number, unit = match.groups()
    unit = None if unit is None else unit.casefold()
    interval = 1
    if number:
        interval = int(number)
    elif "other" in match.group(0).casefold():
        interval = 2
    if not 1 <= interval <= 365:
        return None, None
    parts: list[str]
    weekday = None
    if direct == "daily" or unit in {"day", "days"}:
        parts = ["FREQ=DAILY"]
    else:
        parts = ["FREQ=WEEKLY"]
        if unit in _WEEKDAYS:
            weekday = _WEEKDAYS[unit][0]
            parts.append(f"BYDAY={_WEEKDAYS[unit][1]}")
    if interval != 1:
        parts.append(f"INTERVAL={interval}")
    count = re.search(r"(?i)\bfor\s+(\d{1,4})\s+(?:days?|times?|occurrences?)\b", text)
    if count is not None:
        value = int(count.group(1))
        if not 1 <= value <= 9999:
            return None, None
        parts.append(f"COUNT={value}")
    until = re.search(
        r"(?i)\buntil\s+((?:january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?)\b",
        text,
    )
    until_date = None if until is None else _parse_date_token(until.group(1), context)
    clock_match = _CLOCK_TOKEN.search(text)
    first = None
    if clock_match is not None:
        local_time = _parse_clock(clock_match.group(1))
        first_date = (
            context.civil_date("weekday", weekday=weekday)
            if weekday is not None else context.local_date
        )
        first = context.resolve_civil(first_date, local_time)
        if first <= context.captured_utc:
            step = 1 if direct == "daily" or unit in {"day", "days"} else 7
            first = context.resolve_civil(first_date + timedelta(days=step), local_time)
    elif existing is not None:
        value = existing.due if isinstance(existing, Task) else existing.start
        first = value if isinstance(value, datetime) else None
    if until_date is not None:
        if clock_match is not None:
            until_time = _parse_clock(clock_match.group(1))
        elif first is not None:
            until_time = first.astimezone(context.zone).time().replace(tzinfo=None)
        else:
            until_time = time(23, 59, 59)
        until_utc = context.resolve_civil(until_date, until_time)
        parts.append("UNTIL=" + until_utc.strftime("%Y%m%dT%H%M%SZ"))
    return RecurrenceRule(";".join(parts)), first


def _resolve_date_or_datetime(value: str, context: TimeContext) -> date | datetime:
    date_match = _DATE_TOKEN.search(value)
    if date_match is None:
        raise PlanningConversationError("Please give one clear date. Nothing changed.", code="invalid_time")
    selected_date = _parse_date_token(date_match.group(1), context)
    clock = _CLOCK_TOKEN.search(value[date_match.end():])
    if clock is None:
        return selected_date
    return context.resolve_civil(selected_date, _parse_clock(clock.group(1)))


def _resolve_datetime(value: str, context: TimeContext, *, require_time: bool) -> datetime:
    resolved = _resolve_date_or_datetime(value, context)
    if not isinstance(resolved, datetime):
        if require_time:
            raise PlanningConversationError(
                "Please give one exact reminder time. Nothing changed.", code="invalid_time"
            )
        return context.resolve_civil(resolved, time(9))
    return resolved


def _move_item(item: Task | Event, value: str, context: TimeContext) -> Task | Event:
    date_match = _DATE_TOKEN.search(value)
    clock_match = _CLOCK_TOKEN.search(value)
    if isinstance(item, Event):
        if not isinstance(item.start, datetime) or not isinstance(item.end, datetime):
            raise PlanningConversationError("All-day events require an explicit new date.", code="invalid_time")
        local_start = item.start.astimezone(context.zone)
        selected_date = _parse_date_token(date_match.group(1), context) if date_match else local_start.date()
        selected_time = _parse_clock(clock_match.group(1), reference=local_start.time()) if clock_match else local_start.time().replace(tzinfo=None)
        start = context.resolve_civil(selected_date, selected_time)
        return replace(item, start=start, end=start + (item.end - item.start))
    local_due = item.due.astimezone(context.zone) if isinstance(item.due, datetime) else None
    if date_match is None and local_due is None:
        raise PlanningConversationError("Please give one clear date for that task.", code="invalid_time")
    selected_date = _parse_date_token(date_match.group(1), context) if date_match else local_due.date()
    if clock_match is None:
        return replace(item, due=selected_date)
    reference = None if local_due is None else local_due.time()
    return replace(item, due=context.resolve_civil(selected_date, _parse_clock(clock_match.group(1), reference=reference)))


def _parse_date_token(value: str, context: TimeContext) -> date:
    normalized = value.casefold().replace(",", " ")
    if normalized == "today":
        return context.local_date
    if normalized == "tomorrow":
        return context.local_date + timedelta(days=1)
    weekday = normalized.removeprefix("next ")
    if weekday in _WEEKDAYS:
        return context.civil_date("weekday", weekday=_WEEKDAYS[weekday][0])
    parts = normalized.split()
    if len(parts) in {2, 3} and parts[0] in _MONTHS:
        year = context.local_date.year if len(parts) == 2 else int(parts[2])
        selected = date(year, _MONTHS[parts[0]], int(parts[1]))
        if len(parts) == 2 and selected < context.local_date:
            selected = date(year + 1, selected.month, selected.day)
        return selected
    raise PlanningConversationError("That date is not supported clearly enough. Nothing changed.", code="invalid_time")


def _parse_clock(value: str, *, reference: time | None = None) -> time:
    normalized = value.casefold().replace(".", "").replace(" ", "")
    if normalized == "noon":
        return time(12)
    if normalized == "midnight":
        return time(0)
    period = normalized[-2:] if normalized.endswith(("am", "pm")) else None
    clock = normalized[:-2] if period else normalized
    hour_text, _, minute_text = clock.partition(":")
    hour = int(hour_text)
    minute = int(minute_text or "0")
    if period:
        hour = hour % 12 + (12 if period == "pm" else 0)
    elif hour <= 12 and reference is not None:
        candidate = hour % 12 + (12 if reference.hour >= 12 else 0)
        hour = candidate
    elif hour <= 6:
        # Clear Planning requests commonly omit PM for afternoon appointments;
        # the proposal exposes the resolved time before authority is granted.
        hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise PlanningConversationError("That clock time is invalid. Nothing changed.", code="invalid_time")
    return time(hour, minute)


def _duration(value: str) -> timedelta:
    match = re.search(r"(?i)(\d+)\s*(minutes?|hours?)", value)
    if match is None:
        raise PlanningConversationError("That reminder offset is invalid.", code="invalid_time")
    amount = int(match.group(1))
    return timedelta(minutes=amount if match.group(2).casefold().startswith("minute") else amount * 60)


def _event_occurrences(
    events: tuple[Event, ...], start: date, end: date, context: TimeContext
) -> tuple[Event, ...]:
    result: list[Event] = []
    range_start = context.resolve_civil(start, time.min)
    range_end = context.resolve_civil(end + timedelta(days=1), time.min)
    for event in events:
        if event.recurrence is None:
            if _event_overlaps(event, range_start, range_end, context):
                result.append(event)
            continue
        if not isinstance(event.start, datetime) or not isinstance(event.end, datetime):
            continue
        try:
            rule = rrulestr(event.recurrence.value, dtstart=event.start)
            duration = event.end - event.start
            for instance in rule.between(range_start - duration, range_end, inc=True)[:_MAX_RECURRENCE_INSTANCES]:
                occurrence = replace(event, start=instance, end=instance + duration)
                if _event_overlaps(occurrence, range_start, range_end, context):
                    result.append(occurrence)
        except (TypeError, ValueError, OverflowError):
            continue
    return tuple(result)


def _task_occurrences(
    tasks: tuple[Task, ...], start: date, end: date, context: TimeContext
) -> tuple[Task, ...]:
    result: list[Task] = []
    range_start = context.resolve_civil(start, time.min)
    range_end = context.resolve_civil(end + timedelta(days=1), time.min)
    for task in tasks:
        base = task.due or task.start
        if task.recurrence is None or base is None:
            result.append(task)
            continue
        dtstart = (
            base if isinstance(base, datetime)
            else context.resolve_civil(base, time.min)
        )
        try:
            rule = rrulestr(task.recurrence.value, dtstart=dtstart)
            for instance in rule.between(range_start, range_end, inc=True)[:_MAX_RECURRENCE_INSTANCES]:
                result.append(replace(task, due=instance))
        except (TypeError, ValueError, OverflowError):
            continue
    return tuple(result)


def _event_overlaps(event: Event, start: datetime, end: datetime, context: TimeContext) -> bool:
    event_start = _item_datetime(event.start, context, end_of_day=False)
    event_end = _item_datetime(event.end, context, end_of_day=True)
    return event_start < end and event_end > start


def _task_in_range(task: Task, start: date, end: date, context: TimeContext) -> bool:
    value = task.due or task.start
    if value is None:
        return False
    local_date = value.astimezone(context.zone).date() if isinstance(value, datetime) else value
    return start <= local_date <= end


def _is_overdue(task: Task, context: TimeContext) -> bool:
    if task.due is None:
        return False
    if isinstance(task.due, datetime):
        return task.due.astimezone(timezone.utc) < context.captured_utc
    return task.due < context.local_date


def _item_datetime(value: date | datetime | None, context: TimeContext, *, end_of_day: bool) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(context.zone)
    selected = context.local_date if value is None else value
    return context.resolve_civil(selected, time.max.replace(microsecond=0) if end_of_day else time.min).astimezone(context.zone)


def _when(item: Task | Event, context: TimeContext) -> str:
    if isinstance(item, Task):
        if item.due is None:
            return "No due date"
        return "Due " + _format_temporal(item.due, context)
    return f"{_format_temporal(item.start, context)}–{_format_temporal(item.end, context, time_only=True)}"


def _format_temporal(value: date | datetime, context: TimeContext, *, time_only: bool = False) -> str:
    if isinstance(value, datetime):
        local = value.astimezone(context.zone)
        return local.strftime("%-I:%M %p" if time_only else "%B %-d, %Y at %-I:%M %p")
    return value.strftime("%B %-d, %Y")


def _recurrence_label(value: RecurrenceRule | None) -> str:
    if value is None:
        return "None"
    fields = {}
    for part in value.value.split(";"):
        key, separator, selected = part.partition("=")
        if separator:
            fields[key] = selected
    frequency = fields.get("FREQ")
    interval = int(fields.get("INTERVAL", "1"))
    byday = fields.get("BYDAY")
    day_names = {
        "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday",
        "TH": "Thursday", "FR": "Friday", "SA": "Saturday", "SU": "Sunday",
    }
    if frequency == "DAILY":
        label = "Daily" if interval == 1 else f"Every {interval} days"
    elif frequency == "WEEKLY":
        label = "Weekly" if interval == 1 else f"Every {interval} weeks"
        if byday:
            names = [day_names.get(item, item) for item in byday.split(",")]
            label += " on " + ", ".join(names)
    else:
        return "Supported calendar recurrence"
    if "COUNT" in fields:
        label += f", {fields['COUNT']} occurrences"
    if "UNTIL" in fields:
        try:
            until = datetime.strptime(fields["UNTIL"], "%Y%m%dT%H%M%SZ")
            label += " until " + until.strftime("%B %-d, %Y")
        except ValueError:
            label += " until its configured end"
    return label


def _reminder_label(values: tuple[PlanningReminder, ...]) -> str:
    if not values:
        return "None"
    rendered = []
    for value in values:
        seconds = int(value.trigger.total_seconds())
        if seconds == 0:
            rendered.append("At due/start time")
        elif seconds < 0 and seconds % 3600 == 0:
            rendered.append(f"{-seconds // 3600} hour(s) before")
        elif seconds < 0 and seconds % 60 == 0:
            rendered.append(f"{-seconds // 60} minute(s) before")
        else:
            rendered.append(f"{seconds} seconds relative")
    return ", ".join(rendered)


def _reference(item: Task | Event) -> PlanningReference:
    return PlanningReference(
        "task" if isinstance(item, Task) else "event",
        item.collection_id, item.uid, item.title,
    )


def _candidate_label(item: Task | Event) -> str:
    kind = "task" if isinstance(item, Task) else "event"
    return f"{kind} “{item.title}”"


def _clean_title(value: str) -> str:
    result = value.strip().strip('"“”').rstrip(".!?").strip()
    result = re.sub(r"(?i)^(?:a\s+|an\s+|the\s+)", "", result)
    if not result or len(result) > 4096:
        raise PlanningConversationError("The Planning title is invalid.", code="invalid_request")
    return result[0].upper() + result[1:]


def _strip_target_kind(value: str) -> str:
    result = value.strip().rstrip(".!?")
    result = re.sub(r"(?i)^(?:my\s+|the\s+)", "", result)
    result = re.sub(r"(?i)\s+(?:task|event|appointment)$", "", result)
    return result.strip()


def _normalized_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())
