"""Application-level foreground and quiet-operation coordination."""

from __future__ import annotations

import threading


class OperationCoordinator:
    """Serialize foreground work and quiet reconciliation coherently.

    Only foreground work publishes the user-visible working state.  Quiet
    delivery reconciliation participates in exclusion without making Tori
    appear busy.  The raw acquire/release methods remain available for
    application maintenance and compatibility callers.
    """

    def __init__(self, working: threading.Event | None = None) -> None:
        self._condition = threading.Condition()
        self._owner: str | None = None
        self._working = working or threading.Event()

    def acquire(self, blocking: bool = True) -> bool:
        """Acquire the raw application boundary for maintenance callers."""

        with self._condition:
            if not blocking and self._owner is not None:
                return False
            while self._owner is not None:
                self._condition.wait()
            self._owner = "external"
            return True

    def acquire_quiet(self) -> bool:
        """Try to acquire non-user-visible delivery reconciliation."""

        with self._condition:
            if self._owner is not None:
                return False
            self._owner = "quiet"
            return True

    def acquire_foreground(self) -> bool:
        """Admit one foreground request, waiting only for quiet housekeeping."""

        with self._condition:
            if self._working.is_set():
                return False
            while self._owner == "quiet":
                self._condition.wait()
                if self._working.is_set():
                    return False
            if self._owner is not None:
                return False
            self._owner = "foreground"
            self._working.set()
            return True

    def release(self) -> None:
        """Release a quiet or raw maintenance owner."""

        with self._condition:
            if self._owner not in {"quiet", "external"}:
                raise RuntimeError(
                    "The operation coordinator is not held for reconciliation."
                )
            self._owner = None
            self._condition.notify_all()

    def release_foreground(self) -> None:
        """Publish idle and release foreground admission atomically."""

        with self._condition:
            if self._owner != "foreground":
                raise RuntimeError(
                    "The foreground operation coordinator is not held."
                )
            self._owner = None
            self._working.clear()
            self._condition.notify_all()

    def foreground_busy(self) -> bool:
        with self._condition:
            return self._working.is_set()

    def locked(self) -> bool:
        with self._condition:
            return self._owner is not None
