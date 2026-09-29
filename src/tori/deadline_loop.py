"""Domain-neutral application-owned deadline wake/recheck lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import re
import threading


LOGGER = logging.getLogger(__name__)

_SAFE_DIAGNOSTIC_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _diagnostic(exc: BaseException) -> str:
    parts = [type(exc).__name__]
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _SAFE_DIAGNOSTIC_CODE.fullmatch(code):
        parts.append(code)
    return " ".join(parts)


class DeadlineLoop:
    """Run one bounded scan callback and wait for its next UTC deadline."""

    def __init__(
        self,
        *,
        initialize: Callable[[], None],
        scan: Callable[[], None],
        next_deadline: Callable[[], datetime | None],
        clock: Callable[[], datetime],
        handled_error: type[BaseException] | tuple[type[BaseException], ...],
        name: str,
        failure_message: str,
        recheck_seconds: float = 30.0,
    ) -> None:
        if (
            not isinstance(recheck_seconds, (int, float))
            or isinstance(recheck_seconds, bool)
            or not 0.05 <= float(recheck_seconds) <= 300
        ):
            raise ValueError("Scheduler recheck must be between 0.05 and 300 seconds.")
        self._initialize = initialize
        self._scan = scan
        self._next_deadline = next_deadline
        self._clock = clock
        self._handled_error = handled_error
        self._name = name
        self._failure_message = failure_message
        self._recheck_seconds = float(recheck_seconds)
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._failed = False

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def failed(self) -> bool:
        return self._failed

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            self._initialize()
            self._stopping.clear()
            self._wake.clear()
            self._failed = False
            self._thread = threading.Thread(
                target=self._run, name=self._name, daemon=False
            )
            self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, *, timeout: float = 5.0) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stopping.set()
            self._wake.set()
        thread.join(timeout)
        if thread.is_alive():
            raise RuntimeError(f"The {self._name} did not stop cleanly.")
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self._scan()
                next_deadline = self._next_deadline()
            except self._handled_error as exc:
                self._failed = True
                LOGGER.error("%s [%s]", self._failure_message, _diagnostic(exc))
                self._wait(self._recheck_seconds)
                continue
            timeout = self._recheck_seconds
            if next_deadline is not None:
                if not isinstance(next_deadline, datetime) or next_deadline.tzinfo is None:
                    self._failed = True
                    LOGGER.error("The %s clock/deadline state was invalid.", self._name)
                else:
                    now = self._clock()
                    if not isinstance(now, datetime) or now.tzinfo is None:
                        self._failed = True
                        LOGGER.error("The %s clock returned invalid state.", self._name)
                    else:
                        remaining = (
                            next_deadline.astimezone(timezone.utc)
                            - now.astimezone(timezone.utc)
                        ).total_seconds()
                        timeout = max(0.0, min(self._recheck_seconds, remaining))
            self._wait(timeout)

    def _wait(self, timeout: float) -> None:
        self._wake.wait(timeout)
        self._wake.clear()
