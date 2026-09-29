from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.time_context import (
    AmbiguousCivilTimeError,
    FakeClock,
    NonexistentCivilTimeError,
    TimeContext,
    TimeContextError,
    discover_timezone,
    format_utc_timestamp,
)


class TimeContextTests(unittest.TestCase):
    def test_utc_local_offset_relative_and_year_boundary(self) -> None:
        context = TimeContext(datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc), "America/Chicago")
        self.assertEqual(context.local_date, date(2026, 12, 31))
        self.assertEqual(format_utc_timestamp(context.elapsed(timedelta(minutes=45))), "2027-01-01T00:15:00Z")
        self.assertEqual(context.civil_date("tomorrow"), date(2027, 1, 1))
        self.assertIn("America/Chicago", context.provider_context())
        self.assertIn("UTC offset=-06:00", context.provider_context())

    def test_dst_gap_and_overlap_are_rejected_without_guessing(self) -> None:
        context = TimeContext(datetime(2026, 1, 1, tzinfo=timezone.utc), "America/Chicago")
        with self.assertRaises(NonexistentCivilTimeError):
            context.resolve_civil(date(2026, 3, 8), time(2, 30))
        with self.assertRaises(AmbiguousCivilTimeError):
            context.resolve_civil(date(2026, 11, 1), time(1, 30))
        first = context.resolve_civil(date(2026, 11, 1), time(1, 30), fold=0)
        second = context.resolve_civil(date(2026, 11, 1), time(1, 30), fold=1)
        self.assertEqual(second - first, timedelta(hours=1))

    def test_timezone_precedence_and_abbreviation_rejection(self) -> None:
        self.assertEqual(discover_timezone("America/New_York", environ={"TORI_TIMEZONE": "America/Chicago"}), "America/New_York")
        self.assertEqual(discover_timezone(None, environ={"TORI_TIMEZONE": "America/Denver"}), "America/Denver")
        with self.assertRaises(TimeContextError):
            discover_timezone("CST", environ={})

    def test_fake_clock_has_no_wall_clock_dependency(self) -> None:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        clock.advance(timedelta(days=1))
        self.assertEqual(clock(), datetime(2026, 1, 2, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
