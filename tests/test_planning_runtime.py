from __future__ import annotations

import unittest

from tori.config import PlanningSettings
from tori.planning import PlanningAvailability
from tori.planning_runtime import PlanningRuntime


class PlanningRuntimeTests(unittest.TestCase):
    def test_disabled_and_missing_credential_do_not_break_application_lifecycle(self) -> None:
        disabled = PlanningRuntime.start(PlanningSettings(), environ={})
        self.addCleanup(disabled.close)
        self.assertEqual(
            disabled.service.status().availability, PlanningAvailability.DISABLED
        )

        missing = PlanningRuntime.start(
            PlanningSettings(
                enabled=True,
                username="tori",
                credential_environment="TORI_CALDAV_PASSWORD",
            ),
            environ={},
        )
        self.addCleanup(missing.close)
        self.assertEqual(
            missing.service.status().availability, PlanningAvailability.UNAVAILABLE
        )
