from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest

from caldav import DAVClient

from tori.planning import (
    Event, PlanningAvailability, PlanningConflictError, PlanningReminder,
    RecurrenceRule, Task,
)
from tori.planning_application import PlanningService
from tori.planning_caldav import CalDAVPlanningAdapter


UTC = timezone.utc


@unittest.skipUnless(
    os.environ.get("TORI_RUN_RADICALE_INTEGRATION") == "1",
    "real Radicale integration is an explicit separate gate",
)
class RadicalePlanningIntegrationTests(unittest.TestCase):
    def test_real_task_event_recurrence_alarm_revision_and_cleanup_round_trip(self) -> None:
        with TemporaryDirectory(prefix="tori-planning-radicale-") as directory:
            root = Path(directory)
            self.assertFalse(str(root.resolve()).startswith("/workspaces/Tori/runtime/"))
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
            try:
                _wait_for_server(base_url, process)
                bootstrap = DAVClient(
                    base_url, username="tori", password="", require_tls=False
                )
                calendar = bootstrap.principal().make_calendar(
                    name="Tori disposable integration",
                    cal_id="tori-disposable-integration",
                )
                collection_id = str(calendar.url)
                adapter = CalDAVPlanningAdapter(base_url, username="tori")
                service = PlanningService(adapter)
                try:
                    self.assertEqual(
                        service.status().availability, PlanningAvailability.AVAILABLE
                    )
                    collections = service.list_collections()
                    self.assertTrue(any(
                        item.identifier == collection_id
                        and item.supports_tasks
                        and item.supports_events
                        for item in collections
                    ))
                    task = service.create_task(Task(
                        "tori-integration-task",
                        "Review the weekly plan",
                        collection_id,
                        description="Disposable Radicale integration task",
                        due=datetime(2026, 8, 27, 15, tzinfo=UTC),
                        priority=2,
                        recurrence=RecurrenceRule("FREQ=WEEKLY;COUNT=4"),
                        reminders=(PlanningReminder(
                            timedelta(minutes=-30), "Review the weekly plan"
                        ),),
                    ))
                    read_task = service.get_task(collection_id, task.uid)
                    self.assertEqual(read_task.recurrence.value, "FREQ=WEEKLY;COUNT=4")
                    self.assertEqual(read_task.reminders[0].trigger, timedelta(minutes=-30))
                    task = service.update_task(
                        replace(read_task, title="Review the updated weekly plan"),
                        expected_revision=read_task.revision.token,
                    )
                    task = service.complete_task(
                        task,
                        when=datetime(2026, 8, 27, 16, tzinfo=UTC),
                        expected_revision=task.revision.token,
                    )
                    self.assertTrue(service.get_task(collection_id, task.uid).completed)

                    event = service.create_event(Event(
                        "tori-integration-event",
                        "Planning review",
                        collection_id,
                        datetime(2026, 8, 28, 15, tzinfo=UTC),
                        datetime(2026, 8, 28, 16, tzinfo=UTC),
                        description="Disposable Radicale integration event",
                        location="Local desk",
                        recurrence=RecurrenceRule("FREQ=DAILY;COUNT=3"),
                        reminders=(PlanningReminder(
                            timedelta(minutes=-30), "Planning review"
                        ),),
                    ))
                    read_event = service.get_event(collection_id, event.uid)
                    self.assertEqual(read_event.recurrence.value, "FREQ=DAILY;COUNT=3")
                    self.assertEqual(read_event.reminders[0].trigger, timedelta(minutes=-30))
                    event = service.update_event(
                        replace(read_event, title="Updated planning review"),
                        expected_revision=read_event.revision.token,
                    )

                    external = calendar.event_by_uid(event.uid)
                    external.icalendar_component["SUMMARY"] = "External client edit"
                    external.save()
                    with self.assertRaises(PlanningConflictError):
                        service.update_event(
                            replace(event, title="Stale Tori edit"),
                            expected_revision=event.revision.token,
                        )
                    event = service.get_event(collection_id, event.uid)
                    self.assertEqual(event.title, "External client edit")

                    service.delete_event(
                        collection_id, event.uid,
                        expected_revision=event.revision.token,
                    )
                    service.delete_task(
                        collection_id, task.uid,
                        expected_revision=task.revision.token,
                    )
                    self.assertEqual(service.list_events(collection_id), ())
                    self.assertEqual(service.list_tasks(collection_id), ())
                    print("Radicale task: create/read/update/complete/read/delete PASS")
                    print("Radicale event: create/read/update/external-edit/read/delete PASS")
                    print("RRULE: FREQ=WEEKLY;COUNT=4 and FREQ=DAILY;COUNT=3 PASS")
                    print("VALARM: DISPLAY TRIGGER:-PT30M PASS")
                    print("ETag stale-write rejection and disposable cleanup PASS")
                finally:
                    adapter.close()
                    calendar.delete()
                    bootstrap.close()
            finally:
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
