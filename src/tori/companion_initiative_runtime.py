"""Process-local timing for Companion Initiative eligibility scans."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from .companion_initiative_service import (
    CompanionInitiativeService,
    InitiativeEvaluation,
)
from .deadline_loop import DeadlineLoop


DEFAULT_RECHECK_SECONDS = 30.0


class CompanionInitiativeEvaluator:
    """Give application-owned policy a bounded opportunity while Tori runs.

    This is process-local timing only. It owns no durable schedule, eligibility
    rule, destination, or delivery state; those remain in
    ``CompanionInitiativeService`` and its exact-schema store.
    """

    def __init__(
        self,
        service: CompanionInitiativeService,
        *,
        recheck_seconds: float = DEFAULT_RECHECK_SECONDS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._service = service
        self._loop = DeadlineLoop(
            initialize=lambda: None,
            scan=self.scan_once,
            next_deadline=lambda: None,
            clock=clock,
            handled_error=Exception,
            name="tori-companion-initiative-evaluator",
            failure_message=(
                "The Companion Initiative evaluator failed safely; "
                "ordinary Tori operation continues."
            ),
            recheck_seconds=recheck_seconds,
        )

    @property
    def running(self) -> bool:
        return self._loop.running

    @property
    def failed(self) -> bool:
        return self._loop.failed

    def start(self) -> None:
        self._loop.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._loop.stop(timeout=timeout)

    def scan_once(self) -> InitiativeEvaluation:
        """Evaluate once without adding timing, policy, or delivery authority."""

        return self._service.evaluate()
