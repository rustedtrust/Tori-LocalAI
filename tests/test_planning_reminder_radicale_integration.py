from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest

from caldav import DAVClient
from icalendar.prop import vDDDTypes

from tori.planning import Event, PlanningAvailability, PlanningReminder, RecurrenceRule
from tori.planning_application import PlanningService
from tori.planning_caldav import CalDAVPlanningAdapter
from tori.planning_reminder_bridge import PlanningReminderBridge, planning_reminder_catalog
from tori.scheduled_work import ScheduledWorkExecutor, SQLiteScheduledWorkStore
from tori.scheduled_work_application import ScheduledWorkApplicationService


UTC = timezone.utc


@unittest.skipUnless(
    os.environ.get("TORI_RUN_RADICALE_INTEGRATION") == "1",
    "real Radicale integration is an explicit separate gate",
)
class RadicalePlanningReminderIntegrationTests(unittest.TestCase):
    def test_real_radicale_bridge_reconcile_and_delivery_round_trip(self) -> None:
        with TemporaryDirectory(prefix="tori-planning-reminder-radicale-") as directory:
            root = Path(directory)
            self.assertFalse(str(root.resolve()).startswith("/workspaces/Tori/runtime/"))
            now = datetime(2026, 8, 26, 14, tzinfo=UTC)
            port = _unused_loopback_port()
            base_url = f"http://127.0.0.1:{port}/"
            process = subprocess.Popen(
                [
                    str(Path(".venv/bin/radicale").resolve()),
                    "-H", f"127.0.0.1:{port}",
                    "--auth-type", "none",
                    "--storage-filesystem-folder", str(root / "storage"),
                    "--logging-level", "warning",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            bootstrap = None
            calendar = None
            adapter = None
            try:
                _wait_for_server(base_url, process)
                bootstrap = DAVClient(base_url, username="tori", password="", require_tls=False)
                calendar = bootstrap.principal().make_calendar(
                    name="Tori disposable reminder bridge",
                    cal_id="tori-disposable-reminder-bridge",
                )
                collection_id = str(calendar.url)
                adapter = CalDAVPlanningAdapter(base_url, username="tori")
                planning = PlanningService(adapter)
                store = SQLiteScheduledWorkStore(
                    root / "scheduled.db", clock=lambda: now
                )
                store.initialize()
                scheduled = ScheduledWorkApplicationService(store)
                bridge = PlanningReminderBridge(planning, scheduled, clock=lambda: now)
                event = planning.create_event(Event(
                    "radicale-bridge-event",
                    "External planning review",
                    collection_id,
                    datetime(2026, 8, 26, 15, tzinfo=UTC),
                    datetime(2026, 8, 26, 16, tzinfo=UTC),
                    recurrence=RecurrenceRule("FREQ=DAILY;COUNT=3"),
                    reminders=(PlanningReminder(timedelta(minutes=-30), "Review"),),
                ))

                created = bridge.reconcile()
                self.assertTrue(created.available)
                self.assertEqual(len(created.created), 1)
                self.assertEqual(len(scheduled.list_definitions()), 1)
                unchanged = bridge.reconcile()
                self.assertEqual(unchanged.unchanged, created.created)

                external = calendar.event_by_uid(event.uid)
                external.icalendar_component["DTSTART"] = vDDDTypes(
                    datetime(2026, 8, 26, 16, tzinfo=UTC)
                )
                external.icalendar_component["DTEND"] = vDDDTypes(
                    datetime(2026, 8, 26, 17, tzinfo=UTC)
                )
                external.save()
                moved = bridge.reconcile()
                self.assertEqual(moved.replaced, created.created)
                self.assertEqual(
                    scheduled.list_definitions()[0].schedule.occurrence_utc,
                    "2026-08-26T15:30:00Z",
                )

                now = datetime(2026, 8, 26, 16, tzinfo=UTC)
                store.claim_due(now)
                run = ScheduledWorkExecutor(
                    store, planning_reminder_catalog()
                ).execute_next()
                self.assertIsNotNone(run)
                self.assertEqual(store.pending_notifications()[0].run_id, run.identifier)

                next_pending = bridge.reconcile()
                self.assertEqual(len(next_pending.created), 1)

                external = calendar.event_by_uid(event.uid)
                external.icalendar_component.subcomponents = [
                    component for component in external.icalendar_component.subcomponents
                    if component.name != "VALARM"
                ]
                external.save()
                removed = bridge.reconcile()
                self.assertEqual(removed.cancelled, next_pending.created)
                self.assertFalse([
                    item for item in scheduled.list_definitions() if item.status == "active"
                ])
                self.assertEqual(planning.get_event(collection_id, event.uid).reminders, ())
                print("Radicale reminder bridge: create/no-op/external-time-edit/delivery/alarm-removal PASS")
                print("Radicale reminder bridge: disposable Scheduled Work state and cleanup PASS")
            finally:
                if adapter is not None:
                    adapter.close()
                if calendar is not None:
                    calendar.delete()
                if bootstrap is not None:
                    bootstrap.close()
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_server(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Radicale exited before becoming reachable.")
        adapter = CalDAVPlanningAdapter(base_url, username="tori", timeout_seconds=1)
        try:
            if adapter.status().availability == PlanningAvailability.AVAILABLE:
                return
        finally:
            adapter.close()
        time.sleep(0.05)
    raise AssertionError("Radicale did not become reachable within 10 seconds.")
