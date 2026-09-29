"""Application-owned task/reminder policy and structured interpretation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
import json
import logging
import re
from typing import Any

from .providers import ChatMessage, ModelProvider, ProviderError
from .capability_registry import is_capability_discussion
from .tasks import (
    OperationalError,
    OperationalStaleRevisionError,
    ReminderRecord,
    SQLiteOperationalStore,
    TaskRecord,
)
from .time_context import (
    AmbiguousCivilTimeError,
    NonexistentCivilTimeError,
    TimeContext,
    TimeContextError,
    format_utc_timestamp,
)


INTENTS = frozenset({
    "create_task", "create_reminder", "create_task_with_reminder",
    "list_tasks", "list_reminders", "complete_task", "complete_reminder", "dismiss_reminder",
    "delay_reminder", "modify_task", "modify_reminder", "cancel_task",
    "cancel_reminder", "discuss", "clarify", "none",
})
_DOCUMENT_KEYS = frozenset({
    "intent", "task_text", "reminder_text", "target", "schedule", "clarification"
})
_SCHEDULE_KEYS = frozenset({
    "kind", "date", "time", "end_date", "end_time", "minutes"
})
_LIKELY_OPERATIONAL = re.compile(
    r"(?i)\b(?:remember|remind|reminders?|tasks?|to-?do|to do|done|dismiss|delay|snooze|complete|cancel)\b"
)
_AUTHORITATIVE_RESULT_CLAIM = re.compile(
    r"(?i)\b(?:add(?:ed)?|sav(?:e|ed)|chang(?:e|ed)|delay(?:ed)?|"
    r"complet(?:e|ed)|dismiss(?:ed)?|schedul(?:e|ed)|cancel(?:led)?|"
    r"will remind|(?:i|we)['’]?ll remind)\b"
)
_ELAPSED_DURATION = (
    r"(?:(?P<minutes>[1-9]\d{0,5})\s+minutes?"
    r"|(?P<hour>a|an|one|1)\s+hour)"
)
_DIRECT_ELAPSED_REMINDERS = (
    re.compile(
        r"(?is)^\s*remind\s+me\s+in\s+" + _ELAPSED_DURATION
        + r"\s+to\s+(?P<text>.+?)\s*[.!?]?\s*$"
    ),
    re.compile(
        r"(?is)^\s*remind\s+me\s+to\s+(?P<text>.+?)\s+in\s+"
        + _ELAPSED_DURATION + r"\s*[.!?]?\s*$"
    ),
)
_DIRECT_ELAPSED_CANDIDATE = re.compile(
    r"(?is)^\s*remind\s+me(?:\s+in\b|\s+to\b.*\s+in\b)"
)
_DIRECT_EXISTING_TASK_ELAPSED_REMINDER = re.compile(
    r"(?is)^\s*add\s+a\s+reminder\s+to\s+my\s+existing\s+task\s+"
    r"(?:\"(?P<straight>[^\"\r\n]+)\"|“(?P<curly>[^”\r\n]+)”)\s+for\s+"
    r"(?:(?P<minutes>[1-9]\d{0,5})\s+minutes?|(?P<hour>a|an|one)\s+hour)"
    r"\s+from\s+now\s*[.!?]?\s*$"
)
_CIVIL_CLOCK = (
    r"(?P<{prefix}_hour>0?[1-9]|1[0-2])"
    r"(?::(?P<{prefix}_minute>[0-5]\d))?\s*"
    r"(?P<{prefix}_period>[AaPp])\.?[Mm]\.?(?=\s|$)"
)
_DIRECT_CIVIL_WINDOW_REMINDERS = (
    re.compile(
        r"(?is)^\s*remind\s+me\s+to\s+(?P<text>.+?)\s+between\s+"
        + _CIVIL_CLOCK.format(prefix="start")
        + r"\s+and\s+"
        + _CIVIL_CLOCK.format(prefix="end")
        + r"\s+(?P<day>today|tomorrow)\s*[.!?]?\s*$"
    ),
    re.compile(
        r"(?is)^\s*remind\s+me\s+between\s+"
        + _CIVIL_CLOCK.format(prefix="start")
        + r"\s+and\s+"
        + _CIVIL_CLOCK.format(prefix="end")
        + r"\s+(?P<day>today|tomorrow)\s+to\s+(?P<text>.+?)\s*[.!?]?\s*$"
    ),
)
_DIRECT_CIVIL_POINT_REMINDERS = (
    re.compile(
        r"(?is)^\s*remind\s+me\s+(?P<day>today|tomorrow)\s+at\s+"
        + _CIVIL_CLOCK.format(prefix="start")
        + r"\s+to\s+(?P<text>.+?)\s*[.!?]?\s*$"
    ),
    re.compile(
        r"(?is)^\s*(?:remind\s+me|set\s+a\s+reminder|remember)\s+to\s+(?P<text>.+?)\s+"
        r"(?P<day>today|tomorrow)\s+at\s+"
        + _CIVIL_CLOCK.format(prefix="start")
        + r"\s*[.!?]?\s*$"
    ),
    re.compile(
        r"(?is)^\s*(?:remind\s+me|set\s+a\s+reminder|remember)\s+to\s+(?P<text>.+?)\s+at\s+"
        + _CIVIL_CLOCK.format(prefix="start")
        + r"\s+(?P<day>today|tomorrow)\s*[.!?]?\s*$"
    ),
)
_DIRECT_REMEMBER_TO_CANDIDATE = re.compile(
    r"(?is)^\s*remember\s+to\s+.+?\s+at\s+\d{1,2}(?::\d{2})?\s*"
    r"(?:a\.?m\.?|p\.?m\.?)\s*[.!?]?\s*$"
)
_DIRECT_UNDATED_REMEMBER_TO = re.compile(
    r"(?is)^\s*remember\s+to\s+(?P<text>.+?)\s+at\s+"
    + _CIVIL_CLOCK.format(prefix="start")
    + r"\s*[.!?]?\s*$"
)
_DIRECT_WINDOW_CANDIDATE = re.compile(r"(?is)^\s*remind\s+me\b.*\bbetween\b")
_TASK_OR_RECURRENCE = re.compile(
    r"(?i)\b(?:tasks?|to-?dos?|every|daily|weekly|monthly|recurr(?:ing|ence)?)\b"
)
_EXPLICIT_WINDOW = re.compile(r"(?is)\bbetween\b.+?\band\b")


class ScheduleResolutionError(ValueError):
    """A model-proposed schedule cannot be resolved without user correction."""


@dataclass(frozen=True, slots=True)
class TaskTurnResult:
    handled: bool
    text: str | None = None
    intent: str = "none"
    task: TaskRecord | None = None
    reminder: ReminderRecord | None = None
    discuss_context: str | None = None
    mutated: bool = False


class TaskService:
    """Keep model interpretation advisory and canonical mutation authoritative."""

    def __init__(
        self,
        store: SQLiteOperationalStore,
        provider: ModelProvider | None,
        *,
        model_name: str,
    ) -> None:
        self._store = store
        self._provider = provider
        self._model_name = model_name
        self._pending_reminder_days: dict[str, tuple[str, time]] = {}

    @property
    def store(self) -> SQLiteOperationalStore:
        return self._store

    def select_model(self, provider: ModelProvider | None, *, model_name: str) -> None:
        self._provider = provider
        self._model_name = model_name

    def likely_operational(self, text: str, *, conversation_id: str | None = None) -> bool:
        if not isinstance(text, str) or is_capability_discussion(text):
            return False
        if self._pending_key(conversation_id) in self._pending_reminder_days:
            return True
        # A topic word is not a command. Require an interrogative read or an
        # explicit operational speech act before asking the model for arguments.
        return bool(_LIKELY_OPERATIONAL.search(text) and re.match(
            r"(?is)^\s*(?:(?:please|can you|could you|would you)\s+)?"
            r"(?:remember|remind|add|create|set|schedule|show|list|what|when|which|"
            r"complete|mark|cancel|remove|delete|dismiss|delay|snooze|modify|change|"
            r"i (?:need|want|have|finished|completed)|i['’]m done|done)\b", text
        ))

    def interpret_and_apply(
        self,
        user_text: str,
        *,
        time_context: TimeContext,
        conversation_id: str | None = None,
    ) -> TaskTurnResult:
        if not isinstance(user_text, str) or not user_text.strip():
            return TaskTurnResult(False)
        if is_capability_discussion(user_text):
            return TaskTurnResult(False)
        pending_key = self._pending_key(conversation_id)
        pending = self._pending_reminder_days.pop(pending_key, None)
        if pending is not None:
            day_reply = " ".join(user_text.casefold().rstrip(".!? ").split())
            if day_reply in {"today", "tonight", "tomorrow"}:
                reminder_text, local_time = pending
                return self._create_civil_point_reminder(
                    reminder_text,
                    local_time,
                    "tomorrow" if day_reply == "tomorrow" else "today",
                    time_context,
                )
            # A pending clarification applies to one immediate reply only.
            # Unrelated or ambiguous text cannot mutate the preserved draft.
            if not self.likely_operational(
                user_text, conversation_id=conversation_id
            ):
                return TaskTurnResult(False)
        direct_point = _direct_civil_point_reminder(user_text)
        if direct_point is not None:
            reminder_text, local_time, day_relation = direct_point
            return self._create_civil_point_reminder(
                reminder_text, local_time, day_relation, time_context
            )
        direct_window = _direct_civil_window_reminder(user_text)
        if direct_window is not None:
            reminder_text, start_time, end_time, day_relation = direct_window
            local_date = time_context.civil_date(day_relation)
            try:
                start = time_context.resolve_civil(local_date, start_time)
                end = time_context.resolve_civil(local_date, end_time)
            except NonexistentCivilTimeError as exc:
                return TaskTurnResult(
                    True,
                    f"{exc} Please choose another local time. Nothing changed.",
                    "clarify",
                )
            except AmbiguousCivilTimeError as exc:
                return TaskTurnResult(
                    True,
                    f"{exc} Please say which occurrence you mean. Nothing changed.",
                    "clarify",
                )
            if end < start:
                return TaskTurnResult(
                    True,
                    "The end of that reminder window is before its start. Please give me a same-day end time at or after the start. Nothing changed.",
                    "clarify",
                )
            try:
                reminder = self._store.create_reminder(
                    reminder_text,
                    scheduled_start_utc=format_utc_timestamp(start),
                    scheduled_end_utc=format_utc_timestamp(end),
                    scheduled_timezone=time_context.timezone_name,
                )
            except (OperationalError, TimeContextError, ValueError, TypeError):
                return TaskTurnResult(
                    True,
                    "I couldn't save that change, so your tasks and reminders were not changed.",
                    "create_reminder",
                )
            return TaskTurnResult(
                True,
                _scheduled_wording(reminder, time_context),
                "create_reminder",
                reminder=reminder,
                mutated=True,
            )
        if _direct_window_candidate(user_text):
            return TaskTurnResult(
                True,
                "Please give me one start time, one end time, and either today or tomorrow for that reminder window. Nothing changed.",
                "clarify",
            )
        if _DIRECT_REMEMBER_TO_CANDIDATE.fullmatch(user_text):
            draft = _direct_undated_remember_to(user_text)
            if draft is not None:
                self._pending_reminder_days[pending_key] = draft
            return TaskTurnResult(
                True,
                "Please say whether that reminder is for today or tomorrow. Nothing changed.",
                "clarify",
            )
        existing_task_direct = _direct_existing_task_elapsed_reminder(user_text)
        if existing_task_direct is not None:
            task_description, minutes = existing_task_direct
            try:
                matches = tuple(
                    task for task in self._store.list_tasks(("open",))
                    if _normalized_description(task.description) == _normalized_description(task_description)
                )
            except OperationalError:
                return TaskTurnResult(
                    True,
                    "I couldn't safely look up that existing task, so nothing changed.",
                    "clarify",
                )
            if not matches:
                return TaskTurnResult(
                    True,
                    f"I couldn't find an open task named “{task_description}”. Nothing changed.",
                    "clarify",
                )
            if len(matches) != 1:
                return TaskTurnResult(
                    True,
                    f"I found multiple open tasks named “{task_description}”. Which one do you mean? Nothing changed.",
                    "clarify",
                )
            task = matches[0]
            try:
                reminder = self._store.create_reminder(
                    task.description,
                    task_id=task.identifier,
                    scheduled_start_utc=format_utc_timestamp(
                        time_context.elapsed(timedelta(minutes=minutes))
                    ),
                    scheduled_timezone=time_context.timezone_name,
                )
            except (OperationalError, TimeContextError, ValueError, TypeError):
                return TaskTurnResult(
                    True,
                    "I couldn't save that change, so your tasks and reminders were not changed.",
                    "create_reminder",
                )
            return TaskTurnResult(
                True,
                _scheduled_wording(reminder, time_context, about=task.description),
                "create_reminder",
                task=task,
                reminder=reminder,
                mutated=True,
            )
        direct = _direct_elapsed_reminder(user_text)
        if direct is not None:
            reminder_text, minutes = direct
            try:
                reminder = self._store.create_reminder(
                    reminder_text,
                    scheduled_start_utc=format_utc_timestamp(
                        time_context.elapsed(timedelta(minutes=minutes))
                    ),
                    scheduled_timezone=time_context.timezone_name,
                )
            except (OperationalError, TimeContextError, ValueError, TypeError):
                return TaskTurnResult(
                    True,
                    "I couldn't save that change, so your tasks and reminders were not changed.",
                    "create_reminder",
                )
            return TaskTurnResult(
                True,
                _scheduled_wording(reminder, time_context),
                "create_reminder",
                reminder=reminder,
                mutated=True,
            )
        if _direct_elapsed_candidate(user_text):
            return TaskTurnResult(
                True,
                "Please give me a supported duration in minutes or one hour, and tell me what to remind you about. Nothing changed.",
                "clarify",
            )
        tasks = self._store.list_tasks(("open", "completed", "cancelled"))[:20]
        reminders = self._store.list_reminders(
            ("scheduled", "due", "dismissed", "completed", "cancelled")
        )[:20]
        targets: dict[str, TaskRecord | ReminderRecord] = {
            item.identifier: item for item in (*tasks, *reminders)
        }
        payload = {
            "user_text": user_text,
            "authoritative_time": time_context.provider_context(),
            "candidate_targets": [
                {
                    "target": item.identifier,
                    "kind": "task" if isinstance(item, TaskRecord) else "reminder",
                    "text": item.description if isinstance(item, TaskRecord) else item.reminder_text,
                    "status": item.status,
                    "revision": item.revision,
                }
                for item in targets.values()
            ],
        }
        if self._provider is None:
            return TaskTurnResult(
                True,
                "I couldn't safely interpret that task or reminder request because the selected model provider is unavailable, so nothing changed. Please include the description and any reminder date/time together.",
                "clarify",
            )
        try:
            response = self._provider.interpret_task_intent(
                (
                    ChatMessage("system", _interpretation_contract()),
                    ChatMessage("user", json.dumps(payload, ensure_ascii=True)),
                ),
                model=self._model_name,
            )
            document = _parse_document(response.content)
            _validate_window_interpretation(user_text, document)
        except (ProviderError, ValueError, TypeError, json.JSONDecodeError, OperationalError) as exc:
            # Deliberately omit exception text, prompts, and model output.
            logging.getLogger(__name__).warning(
                "Task interpretation failed: %s",
                "provider_failure" if isinstance(exc, ProviderError) else "invalid_interpretation",
            )
            return TaskTurnResult(
                True,
                "I couldn't safely interpret that task or reminder request, so nothing changed. Please include the description and any reminder date/time together.",
                "clarify",
            )
        intent = document["intent"]
        if intent == "none":
            return TaskTurnResult(False)
        if intent == "clarify":
            wording = _optional_text(document["clarification"], 500)
            return TaskTurnResult(
                True,
                _safe_clarification(wording),
                intent,
            )
        if intent not in {"list_tasks", "list_reminders", "discuss"} and not _explicit_mutation_request(user_text, intent):
            return TaskTurnResult(
                True,
                "I need an explicit request for that task or reminder change. Nothing changed.",
                "clarify",
            )
        try:
            return self._apply(document, targets, time_context)
        except NonexistentCivilTimeError as exc:
            return TaskTurnResult(
                True,
                f"{exc} Please choose another local time. Nothing changed.",
                "clarify",
            )
        except AmbiguousCivilTimeError as exc:
            return TaskTurnResult(
                True,
                f"{exc} Please say which occurrence you mean. Nothing changed.",
                "clarify",
            )
        except (OperationalStaleRevisionError, TimeContextError) as exc:
            return TaskTurnResult(True, str(exc), "clarify")
        except ScheduleResolutionError as exc:
            return TaskTurnResult(True, f"{exc} Nothing changed.", "clarify")
        except (OperationalError, ValueError, TypeError):
            return TaskTurnResult(
                True,
                "I couldn't save that change, so your tasks and reminders were not changed.",
                intent,
            )

    @staticmethod
    def _pending_key(conversation_id: str | None) -> str:
        return conversation_id if conversation_id is not None else "__default__"

    def _create_civil_point_reminder(
        self,
        reminder_text: str,
        local_time: time,
        day_relation: str,
        time_context: TimeContext,
    ) -> TaskTurnResult:
        try:
            start = time_context.resolve_civil(
                time_context.civil_date(day_relation), local_time
            )
        except NonexistentCivilTimeError as exc:
            return TaskTurnResult(
                True,
                f"{exc} Please choose another local time. Nothing changed.",
                "clarify",
            )
        except AmbiguousCivilTimeError as exc:
            return TaskTurnResult(
                True,
                f"{exc} Please say which occurrence you mean. Nothing changed.",
                "clarify",
            )
        try:
            reminder = self._store.create_reminder(
                reminder_text,
                scheduled_start_utc=format_utc_timestamp(start),
                scheduled_timezone=time_context.timezone_name,
            )
        except (OperationalError, TimeContextError, ValueError, TypeError):
            return TaskTurnResult(
                True,
                "I couldn't save that change, so your tasks and reminders were not changed.",
                "create_reminder",
            )
        return TaskTurnResult(
            True,
            _scheduled_wording(reminder, time_context),
            "create_reminder",
            reminder=reminder,
            mutated=True,
        )

    def _apply(
        self,
        document: dict[str, Any],
        targets: dict[str, TaskRecord | ReminderRecord],
        context: TimeContext,
    ) -> TaskTurnResult:
        intent = document["intent"]
        task_text = _optional_text(document["task_text"], 4_000)
        reminder_text = _optional_text(document["reminder_text"], 4_000)
        target = document["target"]
        selected = None
        if target is not None:
            if not isinstance(target, str) or target not in targets:
                raise ValueError("The proposed target is not application-supplied.")
            selected = targets[target]
        start, end = _resolve_schedule(document["schedule"], context)

        if intent == "create_task":
            if task_text is None:
                raise ValueError("Task text is required.")
            task = self._store.create_task(
                task_text,
                due_start_utc=start,
                due_end_utc=end,
                due_timezone=context.timezone_name if start else None,
            )
            return TaskTurnResult(True, f"Added “{task.description}” to your tasks.", intent, task=task, mutated=True)
        if intent == "create_reminder":
            if reminder_text is None:
                raise ValueError("Reminder text is required.")
            if start is None:
                return TaskTurnResult(True, "When should I remind you?", "clarify")
            reminder = self._store.create_reminder(
                reminder_text,
                scheduled_start_utc=start,
                scheduled_end_utc=end,
                scheduled_timezone=context.timezone_name,
            )
            return TaskTurnResult(True, _scheduled_wording(reminder, context), intent, reminder=reminder, mutated=True)
        if intent == "create_task_with_reminder":
            if task_text is None or reminder_text is None:
                raise ValueError("Task and reminder text are required.")
            if start is None:
                return TaskTurnResult(True, "When should I remind you?", "clarify")
            task, reminder = self._store.create_task_with_reminder(
                task_text,
                reminder_text,
                scheduled_start_utc=start,
                scheduled_end_utc=end,
                scheduled_timezone=context.timezone_name,
            )
            return TaskTurnResult(
                True,
                f"Added “{task.description}” to your tasks. {_scheduled_wording(reminder, context)}",
                intent,
                task=task,
                reminder=reminder,
                mutated=True,
            )
        if intent == "list_tasks":
            open_tasks = self._store.list_tasks(("open",))
            text = "You have no open tasks." if not open_tasks else "Open tasks:\n" + "\n".join(
                f"- {item.description}" for item in open_tasks[:20]
            )
            return TaskTurnResult(True, text, intent)
        if intent == "list_reminders":
            current = self._store.list_reminders(("scheduled", "due"))
            text = "You have no scheduled or due reminders." if not current else "Reminders:\n" + "\n".join(
                f"- {item.reminder_text} — {item.status}" for item in current[:20]
            )
            return TaskTurnResult(True, text, intent)
        if intent in {"complete_task", "modify_task", "cancel_task"}:
            if not isinstance(selected, TaskRecord):
                raise ValueError("A supplied task target is required.")
            if intent == "complete_task":
                task = self._store.complete_task(selected.identifier, expected_revision=selected.revision)
                wording = f"Completed “{task.description}”."
            elif intent == "cancel_task":
                task = self._store.cancel_task(selected.identifier, expected_revision=selected.revision)
                wording = f"Cancelled “{task.description}”."
            else:
                if task_text is None and document["schedule"] is None:
                    raise ValueError("A task modification requires changed details.")
                task = self._store.update_task(
                    selected.identifier,
                    expected_revision=selected.revision,
                    description=task_text or selected.description,
                    due_start_utc=start if document["schedule"] is not None else selected.due_start_utc,
                    due_end_utc=end if document["schedule"] is not None else selected.due_end_utc,
                    due_timezone=context.timezone_name if document["schedule"] is not None else selected.due_timezone,
                )
                wording = (
                    f"Changed the task to “{task.description}”."
                    if task.revision != selected.revision
                    else "That task already has those details. Nothing changed."
                )
            return TaskTurnResult(
                True,
                wording,
                intent,
                task=task,
                mutated=task.revision != selected.revision,
            )
        if intent in {"complete_reminder", "dismiss_reminder", "delay_reminder", "modify_reminder", "cancel_reminder"}:
            if not isinstance(selected, ReminderRecord):
                raise ValueError("A supplied reminder target is required.")
            if intent == "complete_reminder":
                reminder = self._store.done_reminder(
                    selected.identifier, expected_revision=selected.revision
                )
                wording = f"Completed “{reminder.reminder_text}”."
            elif intent == "dismiss_reminder":
                reminder = self._store.dismiss_reminder(selected.identifier, expected_revision=selected.revision)
                wording = f"Dismissed “{reminder.reminder_text}”."
            elif intent == "cancel_reminder":
                reminder = self._store.cancel_reminder(selected.identifier, expected_revision=selected.revision)
                wording = f"Cancelled the reminder “{reminder.reminder_text}”."
            elif intent == "delay_reminder":
                if start is None:
                    return TaskTurnResult(True, "How long should I delay it?", "clarify")
                reminder = self._store.delay_reminder(
                    selected.identifier,
                    expected_revision=selected.revision,
                    scheduled_start_utc=start,
                    scheduled_end_utc=end,
                    scheduled_timezone=context.timezone_name,
                )
                wording = f"Delayed “{reminder.reminder_text}”. {_scheduled_wording(reminder, context)}"
            else:
                if reminder_text is None and document["schedule"] is None:
                    raise ValueError("A reminder modification requires changed details.")
                reminder = self._store.update_reminder(
                    selected.identifier,
                    expected_revision=selected.revision,
                    reminder_text=reminder_text or selected.reminder_text,
                    scheduled_start_utc=start or selected.scheduled_start_utc,
                    scheduled_end_utc=end if document["schedule"] is not None else selected.scheduled_end_utc,
                    scheduled_timezone=context.timezone_name if document["schedule"] is not None else selected.scheduled_timezone,
                )
                wording = (
                    f"Changed the reminder to “{reminder.reminder_text}”."
                    if reminder.revision != selected.revision
                    else "That reminder already has those details. Nothing changed."
                )
            return TaskTurnResult(
                True,
                wording,
                intent,
                reminder=reminder,
                mutated=reminder.revision != selected.revision,
            )
        if intent == "discuss":
            if selected is None:
                raise ValueError("A supplied discussion target is required.")
            context_text = json.dumps(
                {
                    "kind": "task" if isinstance(selected, TaskRecord) else "reminder",
                    "identifier": selected.identifier,
                    "status": selected.status,
                    "text": selected.description if isinstance(selected, TaskRecord) else selected.reminder_text,
                    "revision": selected.revision,
                },
                ensure_ascii=True,
                separators=(",", ":"),
            )
            return TaskTurnResult(
                True,
                "I’m ready to discuss that in our main conversation.",
                intent,
                task=selected if isinstance(selected, TaskRecord) else None,
                reminder=selected if isinstance(selected, ReminderRecord) else None,
                discuss_context="Selected operational context (no mutation authority): " + context_text,
            )
        raise ValueError("Unsupported intent.")


def _parse_document(content: object) -> dict[str, Any]:
    if not isinstance(content, str) or not content or len(content) > 8_000:
        raise ValueError("Interpretation response is invalid.")
    document = json.loads(content)
    if not isinstance(document, dict) or set(document) != _DOCUMENT_KEYS:
        raise ValueError("Interpretation shape is invalid.")
    if document["intent"] not in INTENTS:
        raise ValueError("Interpretation intent is invalid.")
    for name in ("task_text", "reminder_text", "target", "clarification"):
        if document[name] is not None and not isinstance(document[name], str):
            raise ValueError("Interpretation field is invalid.")
    schedule = document["schedule"]
    if schedule is not None and (not isinstance(schedule, dict) or set(schedule) != _SCHEDULE_KEYS):
        raise ValueError("Interpretation schedule is invalid.")
    return document


def _resolve_schedule(value: object, context: TimeContext) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict) or set(value) != _SCHEDULE_KEYS:
        raise ValueError("Schedule is invalid.")
    kind = value["kind"]
    if kind == "elapsed":
        minutes = value["minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 525_600:
            raise ScheduleResolutionError("Please give me a valid elapsed duration.")
        if any(value[name] is not None for name in ("date", "time", "end_date", "end_time")):
            raise ScheduleResolutionError(
                "I can't safely mix elapsed and local civil time in one schedule."
            )
        return format_utc_timestamp(context.elapsed(timedelta(minutes=minutes))), None
    if kind != "civil" or value["minutes"] is not None:
        raise ScheduleResolutionError("Please give me one clear kind of schedule.")
    try:
        local_date = date.fromisoformat(value["date"])
        local_time = time.fromisoformat(value["time"])
    except (TypeError, ValueError) as exc:
        raise ScheduleResolutionError(
            "Please give me a valid local date and start time."
        ) from exc
    start = context.resolve_civil(local_date, local_time)
    if (value["end_date"] is None) != (value["end_time"] is None):
        raise ScheduleResolutionError(
            "Please give me both the date and time for the end of that reminder window."
        )
    end = None
    if value["end_date"] is not None:
        try:
            end = context.resolve_civil(
                date.fromisoformat(value["end_date"]),
                time.fromisoformat(value["end_time"]),
            )
        except (TypeError, ValueError) as exc:
            raise ScheduleResolutionError(
                "Please give me a valid end for that reminder window."
            ) from exc
        if end < start:
            raise ScheduleResolutionError(
                "The end of that reminder window is before its start. Please clarify the bounds."
            )
    return format_utc_timestamp(start), None if end is None else format_utc_timestamp(end)


def _optional_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError("Text is invalid.")
    return value


def _safe_clarification(value: str | None) -> str:
    if value is not None and not _AUTHORITATIVE_RESULT_CLAIM.search(value):
        return value
    return "I need a little more detail before I can do that. Nothing changed."


def _direct_elapsed_reminder(value: str) -> tuple[str, int] | None:
    if _TASK_OR_RECURRENCE.search(value):
        return None
    for pattern in _DIRECT_ELAPSED_REMINDERS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        minutes = 60 if match.group("hour") is not None else int(match.group("minutes"))
        if not 1 <= minutes <= 525_600:
            return None
        text = match.group("text").rstrip(".!? ")
        try:
            validated = _optional_text(text, 4_000)
        except ValueError:
            return None
        assert validated is not None
        return validated, minutes
    return None


def _direct_elapsed_candidate(value: str) -> bool:
    return bool(
        _DIRECT_ELAPSED_CANDIDATE.search(value)
        and not _TASK_OR_RECURRENCE.search(value)
    )


def _direct_existing_task_elapsed_reminder(value: str) -> tuple[str, int] | None:
    match = _DIRECT_EXISTING_TASK_ELAPSED_REMINDER.fullmatch(value)
    if match is None:
        return None
    minutes = 60 if match.group("hour") is not None else int(match.group("minutes"))
    if not 1 <= minutes <= 525_600:
        return None
    description = (match.group("straight") or match.group("curly")).strip()
    try:
        validated = _optional_text(description, 4_000)
    except ValueError:
        return None
    assert validated is not None
    return validated, minutes


def _direct_civil_window_reminder(
    value: str,
) -> tuple[str, time, time, str] | None:
    if _TASK_OR_RECURRENCE.search(value):
        return None
    for pattern in _DIRECT_CIVIL_WINDOW_REMINDERS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        text_value = match.group("text").rstrip(".!? ")
        try:
            reminder_text = _optional_text(text_value, 4_000)
        except ValueError:
            return None
        assert reminder_text is not None
        return (
            reminder_text,
            _twelve_hour_time(match, "start"),
            _twelve_hour_time(match, "end"),
            match.group("day").lower(),
        )
    return None


def _direct_civil_point_reminder(
    value: str,
) -> tuple[str, time, str] | None:
    if _TASK_OR_RECURRENCE.search(value):
        return None
    for pattern in _DIRECT_CIVIL_POINT_REMINDERS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        text_value = match.group("text").rstrip(".!? ")
        try:
            reminder_text = _optional_text(text_value, 4_000)
        except ValueError:
            return None
        assert reminder_text is not None
        return (
            reminder_text,
            _twelve_hour_time(match, "start"),
            match.group("day").lower(),
        )
    return None


def _direct_undated_remember_to(value: str) -> tuple[str, time] | None:
    """Return one bounded reminder draft that is missing only its day."""

    if _TASK_OR_RECURRENCE.search(value):
        return None
    match = _DIRECT_UNDATED_REMEMBER_TO.fullmatch(value)
    if match is None:
        return None
    text_value = match.group("text").rstrip(".!? ")
    try:
        reminder_text = _optional_text(text_value, 4_000)
    except ValueError:
        return None
    assert reminder_text is not None
    return reminder_text, _twelve_hour_time(match, "start")


def _direct_window_candidate(value: str) -> bool:
    return bool(
        _DIRECT_WINDOW_CANDIDATE.search(value)
        and not _TASK_OR_RECURRENCE.search(value)
    )


def _twelve_hour_time(match: re.Match[str], prefix: str) -> time:
    hour = int(match.group(f"{prefix}_hour"))
    minute_value = match.group(f"{prefix}_minute")
    minute = 0 if minute_value is None else int(minute_value)
    period = match.group(f"{prefix}_period").casefold()
    return time((hour % 12) + (12 if period == "p" else 0), minute)


def _validate_window_interpretation(
    user_text: str, document: dict[str, Any]
) -> None:
    if not _EXPLICIT_WINDOW.search(user_text):
        return
    schedule = document["schedule"]
    if document["intent"] in {"create_reminder", "create_task_with_reminder"}:
        if not isinstance(schedule, dict) or schedule.get("kind") != "civil":
            raise ValueError("An explicit civil window must remain a civil window.")
        if schedule.get("end_date") is None or schedule.get("end_time") is None:
            raise ValueError("An explicit time window must preserve its end bound.")


def _normalized_description(value: str) -> str:
    return " ".join(value.split()).casefold()


def _scheduled_wording(
    reminder: ReminderRecord,
    context: TimeContext,
    *,
    about: str | None = None,
) -> str:
    from .time_context import parse_utc_timestamp
    local = parse_utc_timestamp(reminder.scheduled_start_utc).astimezone(context.zone)
    zone = local.tzname() or context.timezone_name
    lead = "I’ll remind you" if about is None else f"I’ll remind you about “{about}”"
    if reminder.scheduled_end_utc is None:
        return f"{lead} at {local.strftime('%-I:%M %p')} {zone} on {local.strftime('%B %-d, %Y')}."
    end = parse_utc_timestamp(reminder.scheduled_end_utc).astimezone(context.zone)
    return (
        f"{lead} at the start of the window, {local.strftime('%-I:%M %p')}–"
        f"{end.strftime('%-I:%M %p')} {zone} on {local.strftime('%B %-d, %Y')}."
    )


def _explicit_mutation_request(text: str, intent: str) -> bool:
    """Independent authority gate: a model cannot turn a read into a write.

    This checks operation families, not model-supplied arguments. Target/revision,
    schedule and schema validation remain in the application before persistence.
    Ambiguous wording must be clarified instead of expanding model authority.
    """
    value = re.sub(r"(?is)^\s*(?:(?:can|could|would) you\s+)?(?:please\s+)?", "", text)
    verbs = {
        "create_task": r"add|create|set|schedule",
        "create_reminder": r"remind|add|create|set|schedule",
        "create_task_with_reminder": r"add|create|set|schedule",
        "complete_task": r"complete|mark|done|i (?:finished|completed)|i['’]m done",
        "complete_reminder": r"complete|mark|done|i (?:finished|completed)|i['’]m done",
        "cancel_task": r"cancel|remove|delete",
        "cancel_reminder": r"cancel|remove|delete",
        "dismiss_reminder": r"dismiss",
        "delay_reminder": r"delay|snooze",
        "modify_task": r"modify|change|update|keep",
        "modify_reminder": r"modify|change|update|keep",
    }.get(intent)
    return verbs is not None and bool(re.match(r"(?is)^(?:" + verbs + r")\b", value))


def _interpretation_contract() -> str:
    return (
        "Interpret only the user's task/reminder intent. Return exactly the required JSON schema. "
        "Use none for ordinary conversation. Explicit task/to-do wording strongly means create_task. "
        "A reminder may be standalone; use create_task_with_reminder only for durable work plus attention. "
        "A clear 'Remind me in N minutes to ...' or 'Remind me to ... in N minutes' request is a "
        "standalone create_reminder unless the user "
        "also explicitly asks for a task or to-do item. Creation intents must use target null. "
        "Never invent now, IDs, revisions, dates, or times. Select target only from candidate_targets. "
        "For civil schedules supply exact YYYY-MM-DD and HH:MM local components. For elapsed durations "
        "supply integer minutes and set all civil fields null. Preserve both bounds of a time window. Missing or ambiguous schedules "
        "must use clarify. Recurring schedules are unsupported and must use clarify. Do not claim success."
    )
