"""Optional application-owned lifecycle for configured Planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .config import PlanningSettings
from .planning import DisabledPlanningPort, PlanningDataError, UnavailablePlanningPort
from .planning_application import PlanningService
from .planning_caldav import CalDAVPlanningAdapter


@dataclass(slots=True)
class PlanningRuntime:
    service: PlanningService
    _adapter: CalDAVPlanningAdapter | None = None

    @classmethod
    def start(
        cls, settings: PlanningSettings, *, environ: Mapping[str, str]
    ) -> "PlanningRuntime":
        if not settings.enabled:
            return cls(PlanningService(DisabledPlanningPort()))
        password = None
        if settings.credential_environment is not None:
            password = environ.get(settings.credential_environment)
            if password is None:
                return cls(PlanningService(UnavailablePlanningPort()))
        try:
            adapter = CalDAVPlanningAdapter(
                settings.url,
                username=settings.username,
                password=password,
                timeout_seconds=settings.timeout_seconds,
            )
        except PlanningDataError:
            return cls(PlanningService(UnavailablePlanningPort()))
        return cls(PlanningService(adapter), adapter)

    def close(self) -> None:
        if self._adapter is not None:
            self._adapter.close()
