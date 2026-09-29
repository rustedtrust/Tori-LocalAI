"""Privacy-preserving, console-oriented operational events."""

from __future__ import annotations

import logging
import re
import threading
from types import TracebackType


LOGGER = logging.getLogger("tori.operator")
LOGGER.addHandler(logging.NullHandler())
_EVENT = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_VALUE = re.compile(r"^[A-Za-z0-9_.:/-]{1,96}$")
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY_ENABLED = True


def set_operator_activity_enabled(enabled: bool) -> None:
    """Apply the durable informational-event preference for this process."""

    if not isinstance(enabled, bool):
        raise TypeError("Operator Activity Log state must be boolean.")
    global _ACTIVITY_ENABLED
    with _ACTIVITY_LOCK:
        _ACTIVITY_ENABLED = enabled


def operator_activity_enabled() -> bool:
    with _ACTIVITY_LOCK:
        return _ACTIVITY_ENABLED


def operator_event(name: str, **fields: object) -> None:
    """Emit one bounded event without accepting conversational free text."""

    if not operator_activity_enabled():
        return
    if not _EVENT.fullmatch(name):
        raise ValueError("Operator event name is invalid.")
    rendered = [name]
    for key in sorted(fields):
        if not _FIELD.fullmatch(key):
            raise ValueError("Operator event field name is invalid.")
        rendered.append(f"{key}={_safe_value(fields[key])}")
    LOGGER.info(" ".join(rendered))


def operator_failure(
    name: str,
    error: BaseException,
    *,
    code: str,
    traceback: bool = False,
    **fields: object,
) -> None:
    """Report safe failure metadata, optionally retaining a sanitized traceback."""

    safe_fields = {**fields, "code": code, "error_type": type(error).__name__}
    if not traceback:
        LOGGER.error(_render(name, safe_fields))
        return
    message = _render(name, safe_fields)
    safe_error = RuntimeError(f"{type(error).__name__}:{code}")
    LOGGER.error(
        message,
        exc_info=(RuntimeError, safe_error, _traceback(error)),
    )


def operator_error(name: str, *, code: str, **fields: object) -> None:
    """Emit serious safe runtime metadata regardless of activity preference."""

    LOGGER.error(_render(name, {**fields, "code": code}))


def _render(name: str, fields: dict[str, object]) -> str:
    if not _EVENT.fullmatch(name):
        raise ValueError("Operator event name is invalid.")
    rendered = [name]
    for key in sorted(fields):
        if not _FIELD.fullmatch(key):
            raise ValueError("Operator event field name is invalid.")
        rendered.append(f"{key}={_safe_value(fields[key])}")
    return " ".join(rendered)


def _safe_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(max(0, value))
    if isinstance(value, str) and _VALUE.fullmatch(value):
        return value
    return "redacted"


def _traceback(error: BaseException) -> TracebackType | None:
    return error.__traceback__
