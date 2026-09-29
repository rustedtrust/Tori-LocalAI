from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest

from caldav import DAVClient
from icalendar.prop import vDDDTypes

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.planning import PlanningAvailability
from tori.planning_application import PlanningService
from tori.planning_caldav import CalDAVPlanningAdapter
from tori.providers import ChatResponse, ModelProvider
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.web import WebApplication


UTC = timezone.utc


class _Provider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("deterministic Planning integration must not invoke the model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("deterministic Planning integration must not invoke the model")
        yield "unreachable"


@unittest.skipUnless(
    os.environ.get("TORI_RUN_RADICALE_INTEGRATION") == "1",
    "real Radicale integration is an explicit separate gate",
)
class RadicalePlanningConversationIntegrationTests(unittest.TestCase):
    def test_real_conversation_authority_external_stale_and_bridge_round_trip(self) -> None:
        with TemporaryDirectory(prefix="tori-planning-conversation-radicale-") as directory:
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
            bootstrap = calendar = adapter = None
            try:
                _wait_for_server(base_url, process)
                bootstrap = DAVClient(base_url, username="tori", password="", require_tls=False)
                calendar = bootstrap.principal().make_calendar(
                    name="Tori disposable conversation",
                    cal_id="tori-disposable-conversation",
                )
                collection_id = str(calendar.url)
                adapter = CalDAVPlanningAdapter(base_url, username="tori")
                planning = PlanningService(adapter)
                scheduled = SQLiteScheduledWorkStore(root / "scheduled.db", clock=lambda: now)
                scheduled.initialize()
                chats = ChatService(ConversationArchiveStore(root / "archive.db", clock=lambda: now))
                application = WebApplication(
                    _Provider(),
                    port=8765,
                    checkpoint_store=CheckpointStore(root / "checkpoints"),
                    memory_store=SQLiteMemoryStore(root / "memory.db"),
                    knowledge_registry=KnowledgeRegistry(root / "knowledge", working_directory=root),
                    provider_name="fake", model_name="model", chat_service=chats,
                    scheduled_work_store=scheduled, planning_service=planning,
                    planning_default_task_list=collection_id,
                    planning_default_calendar=collection_id,
                    timezone_name="America/Chicago", utc_clock=lambda: now,
                )

                _status, task_proposal = application.submit("Add a task to call Mom tomorrow.")
                self.assertEqual(planning.list_tasks(collection_id), ())
                application.confirm(task_proposal["confirmation"]["token"], "confirm")
                task = planning.list_tasks(collection_id)[0]
                self.assertIn("Call Mom", repr(application.planning_workspace_state()["tasks"]["open"]))
                _status, task_read = application.submit("Show my todo list.")
                self.assertIn("Call Mom", task_read["transcript"][-1]["text"])
                _status, completion = application.submit("Mark call Mom done.")
                application.confirm(completion["confirmation"]["token"], "confirm")
                self.assertTrue(planning.get_task(collection_id, task.uid).completed)
                self.assertIn("Call Mom", repr(application.planning_workspace_state()["tasks"]["completed"]))

                _status, event_proposal = application.submit(
                    "Add dentist Thursday at 2 with a reminder 30 minutes before."
                )
                application.confirm(event_proposal["confirmation"]["token"], "confirm")
                event = planning.list_events(collection_id)[0]
                active = [item for item in scheduled.list_definitions() if item.status == "active"]
                self.assertEqual(len(active), 1)
                self.assertIn("Dentist", repr(application.planning_workspace_state()["upcoming"]["items"]))
                derived_id = active[0].identifier
                _status, upcoming = application.submit("What's coming up this week?")
                self.assertIn("Dentist", upcoming["transcript"][-1]["text"])

                _status, moved = application.submit("Move the dentist appointment to 3.")
                application.confirm(moved["confirmation"]["token"], "confirm")
                revised_event = planning.get_event(collection_id, event.uid)
                self.assertEqual(revised_event.start.hour, 20)
                current_derived = [item for item in scheduled.list_definitions() if item.status == "active"]
                self.assertEqual([item.identifier for item in current_derived], [derived_id])
                self.assertEqual(current_derived[0].schedule.occurrence_utc, "2026-08-27T19:30:00Z")

                _status, stale = application.submit("Move the dentist appointment to 4.")
                external = calendar.event_by_uid(event.uid)
                external.icalendar_component["DTSTART"] = vDDDTypes(
                    datetime(2026, 8, 27, 22, tzinfo=UTC)
                )
                external.icalendar_component["DTEND"] = vDDDTypes(
                    datetime(2026, 8, 27, 23, tzinfo=UTC)
                )
                external.save()
                stale_status, stale_result = application.confirm(
                    stale["confirmation"]["token"], "confirm"
                )
                self.assertEqual(stale_status, 409)
                self.assertEqual(stale_result["code"], "stale_confirmation")
                self.assertEqual(planning.get_event(collection_id, event.uid).start.hour, 22)
                self.assertIn("5:00 PM", repr(application.planning_workspace_state()["calendar"]["events"]))

                _status, fresh_read = application.submit("What's on my calendar Thursday?")
                self.assertIn("5:00 PM", fresh_read["transcript"][-1]["text"])
                _status, cancel = application.submit("Cancel the dentist appointment.")
                application.confirm(cancel["confirmation"]["token"], "confirm")
                self.assertEqual(planning.list_events(collection_id), ())
                self.assertFalse([
                    item for item in scheduled.list_definitions() if item.status == "active"
                ])
                _status, delete_task = application.submit("Delete the call Mom task.")
                application.confirm(delete_task["confirmation"]["token"], "confirm")
                self.assertEqual(planning.list_tasks(collection_id), ())
                print("Radicale conversational Planning: task create/read/complete/delete PASS")
                print("Radicale conversational Planning: event/reminder/read/reschedule/bridge PASS")
                print("Radicale conversational Planning: external stale rejection and cleanup PASS")
                print("Radicale Planning workspace projection: Today/Tasks/Upcoming/Calendar PASS")
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


if __name__ == "__main__":
    unittest.main()
