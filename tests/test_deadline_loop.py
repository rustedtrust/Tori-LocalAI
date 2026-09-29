from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
import unittest

from tori.deadline_loop import DeadlineLoop, _diagnostic


class BoundedError(RuntimeError):
    code = "bounded_failure"


class UnsafeCodeError(RuntimeError):
    code = "DROP TABLE users; -- /etc/passwd"


class NoCodeError(RuntimeError):
    pass


class IntegerCodeError(RuntimeError):
    code = 7


class DeadlineLoopDiagnosticTests(unittest.TestCase):
    def test_diagnostic_uses_class_and_safe_code(self) -> None:
        self.assertEqual(
            _diagnostic(BoundedError("secret detail")),
            "BoundedError bounded_failure",
        )

    def test_diagnostic_drops_unsafe_or_missing_codes(self) -> None:
        self.assertEqual(_diagnostic(UnsafeCodeError("x")), "UnsafeCodeError")
        self.assertEqual(_diagnostic(NoCodeError("y")), "NoCodeError")
        self.assertEqual(_diagnostic(IntegerCodeError()), "IntegerCodeError")

    def test_handled_error_logs_bounded_diagnostic_without_message(self) -> None:
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())  # noqa: E731
        logger = logging.getLogger("tori.deadline_loop")
        previous_level = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.ERROR)

        scans = 0

        def scan() -> None:
            nonlocal scans
            scans += 1
            if scans == 1:
                raise BoundedError("SELECT secret FROM /private/path")

        loop = DeadlineLoop(
            initialize=lambda: None,
            scan=scan,
            next_deadline=lambda: None,
            clock=lambda: datetime.now(timezone.utc),
            handled_error=BoundedError,
            name="tori-test-loop",
            failure_message="The test loop failed safely.",
            recheck_seconds=0.05,
        )
        try:
            loop.start()
            deadline = time.monotonic() + 2
            while not records and time.monotonic() < deadline:
                threading.Event().wait(0.01)
        finally:
            loop.stop(timeout=2)
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
        self.assertTrue(loop.failed)
        self.assertEqual(len(records), 1)
        self.assertIn("The test loop failed safely.", records[0])
        self.assertIn("BoundedError bounded_failure", records[0])
        self.assertNotIn("SELECT secret", records[0])
        self.assertNotIn("/private/path", records[0])


if __name__ == "__main__":
    unittest.main()
