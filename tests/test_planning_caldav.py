from __future__ import annotations

import unittest

from tori.planning import PlanningAvailability, PlanningDataError, PlanningUnavailableError
from tori.planning_caldav import CalDAVPlanningAdapter


class CalDAVPlanningAdapterTests(unittest.TestCase):
    def test_endpoint_is_bounded_to_numeric_loopback(self) -> None:
        for url in (
            "http://localhost:5232/", "http://192.168.1.2:5232/",
            "http://user@127.0.0.1:5232/", "file:///tmp/radicale",
        ):
            with self.subTest(url=url), self.assertRaises(PlanningDataError):
                CalDAVPlanningAdapter(url)

    def test_unavailable_backend_status_and_operation_are_bounded(self) -> None:
        adapter = CalDAVPlanningAdapter("http://127.0.0.1:9/", timeout_seconds=1)
        self.addCleanup(adapter.close)
        self.assertEqual(adapter.status().availability, PlanningAvailability.UNAVAILABLE)
        with self.assertRaises(PlanningUnavailableError) as raised:
            adapter.list_collections()
        self.assertNotIn("niquests", str(raised.exception))
