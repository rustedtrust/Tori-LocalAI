from __future__ import annotations

from dataclasses import replace
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import threading
import unittest

from tori.checkpoints import CheckpointStore
from tori.coding_work import CodingWorkStaleRevisionError
from tori.coding_work_integration import (
    CodingWorkActivity,
    CodingWorkStatus,
    CodingWorkStatusItem,
)
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.web import LOOPBACK_HOST, WebApplication, create_web_server


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOOPBACK_HOST, 0))
        return int(listener.getsockname()[1])


def status_item(index: int = 0) -> CodingWorkStatusItem:
    suffix = f"{index:032x}"
    activities = tuple(
        CodingWorkActivity(
            "progress", f"Meaningful activity {number}",
            f"2026-08-24T12:{number:02d}:00Z",
        )
        for number in range(10)
    )
    return CodingWorkStatusItem(
        identifier=f"coding-work-{suffix}",
        revision=index + 3,
        project_id=None,
        objective="Create a startup script",
        workspace_root=f"/temporary/project-{index}",
        state="running",
        needs_authorization=False,
        worker_state="owned_running",
        started_at_utc="2026-08-24T12:00:00Z",
        updated_at_utc="2026-08-24T12:10:00Z",
        latest_activity="Analyzing project structure",
        latest_activity_at_utc="2026-08-24T12:10:00Z",
        changed_paths=tuple(f"file-{number}.txt" for number in range(20)),
        result_summary=None,
        recent_activity=activities,
        can_follow_up=True,
        can_cancel=True,
        can_continue=False,
        origin_chat_id="chat-" + "a" * 32,
        acceptance_criteria="startup.sh exists",
        created_at_utc="2026-08-24T12:00:00Z",
        verification=({"kind": "tests", "status": "passed"},),
        artifacts=({"kind": "file", "path": "startup.sh"},),
        acceptance_status="pending",
    )


class RecordingRuntime:
    def __init__(self, status: CodingWorkStatus) -> None:
        self.current_status = status
        self.admission_open = True
        self.cancel_calls: list[tuple[str, int, str | None]] = []
        self.cancel_error: Exception | None = None

    def status(self) -> CodingWorkStatus:
        return self.current_status

    def cancel(
        self, identifier: str, *, expected_revision: int,
        source_chat_id: str | None,
    ) -> CodingWorkStatusItem:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancel_calls.append((identifier, expected_revision, source_chat_id))
        item = self.current_status.work[0]
        updated = replace(
            item,
            revision=item.revision + 1,
            state="cancelling",
            latest_activity="Cancellation requested.",
            can_cancel=False,
        )
        self.current_status = replace(
            self.current_status, active=True, work=(updated,)
        )
        return updated


class CodingWorkWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.runtime = RecordingRuntime(CodingWorkStatus(
            availability="available",
            code="ready",
            reason="Coding Work is available.",
            available=True,
            reconciling=False,
            active=True,
            current_work_id=status_item().identifier,
            work=tuple(status_item(index) for index in range(12)),
        ))
        self.application = WebApplication(
            None,
            port=free_port(),
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory" / "tori.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake",
            model_name="fake",
            coding_work_runtime=self.runtime,  # type: ignore[arg-type]
        )
        self.server = create_web_server(self.application)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self, method: str, path: str, document: dict[str, object] | None = None
    ) -> tuple[int, dict[str, object]]:
        body = None if document is None else json.dumps(document).encode("utf-8")
        headers = {"Host": self.application.expected_host}
        if body is not None:
            headers.update({
                "Content-Type": "application/json",
                "Origin": self.application.expected_origin,
                "X-Tori-CSRF": self.application.csrf_token,
            })
        connection = HTTPConnection(
            LOOPBACK_HOST, self.application.port, timeout=2
        )
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_status_route_is_bounded_and_hides_worker_internals(self) -> None:
        status, document = self.request("GET", "/api/coding-work")
        self.assertEqual(status, 200)
        self.assertEqual(len(document["work"]), 10)
        first = document["work"][0]
        self.assertEqual(len(first["changed_paths"]), 8)
        self.assertEqual(len(first["recent_activity"]), 5)
        self.assertEqual(first["revision"], 3)
        self.assertEqual(
            set(first),
            {
                "identifier", "revision", "objective", "workspace", "state",
                "needs_authorization", "worker_state", "started_at_utc",
                "updated_at_utc", "latest_activity", "latest_activity_at_utc",
                "changed_paths", "result_summary", "recent_activity", "can_cancel",
                "acceptance_criteria", "acceptance_status", "created_at_utc",
                "terminal_at_utc", "related_work_id", "verification", "artifacts",
                "can_follow_up", "can_continue",
            },
        )
        self.assertEqual(first["verification"], [{"kind": "tests", "status": "passed"}])
        self.assertEqual(first["acceptance_status"], "pending")
        serialized = json.dumps(document).casefold()
        for hidden in (
            "session_id", "process_id", "provider", "socket", "stderr",
            "reasoning", "token_stream", "acp",
        ):
            self.assertNotIn(hidden, serialized)

    def test_empty_and_repeated_browser_reads_follow_runtime_status(self) -> None:
        self.runtime.current_status = replace(
            self.runtime.current_status,
            active=False,
            current_work_id=None,
            work=(),
        )
        first_status, first = self.request("GET", "/api/coding-work")
        self.assertEqual(first_status, 200)
        self.assertEqual(first["work"], [])

        item = status_item()
        self.runtime.current_status = replace(
            self.runtime.current_status,
            active=True,
            current_work_id=item.identifier,
            work=(item,),
        )
        second_status, second = self.request("GET", "/api/coding-work")
        third_status, third = self.request("GET", "/api/coding-work")
        self.assertEqual((second_status, third_status), (200, 200))
        self.assertEqual(second, third)
        self.assertEqual(second["work"][0]["identifier"], item.identifier)

    def test_terminal_work_remains_inspectable_after_active_work_clears(self) -> None:
        for state in ("completed", "failed", "cancelled"):
            with self.subTest(state=state):
                item = replace(
                    status_item(),
                    state=state,
                    worker_state="not_running",
                    result_summary="A bounded terminal result.",
                    can_follow_up=False,
                    can_cancel=False,
                    can_continue=state != "completed",
                )
                self.runtime.current_status = replace(
                    self.runtime.current_status,
                    active=False,
                    current_work_id=None,
                    work=(item,),
                )
                first_status, first = self.request("GET", "/api/coding-work")
                second_status, second = self.request("GET", "/api/coding-work")
                self.assertEqual((first_status, second_status), (200, 200))
                self.assertEqual(first, second)
                self.assertFalse(first["active"])
                self.assertIsNone(first["current_work_id"])
                self.assertEqual(first["work"][0]["state"], state)
                self.assertEqual(
                    first["work"][0]["result_summary"],
                    "A bounded terminal result.",
                )

    def test_cancel_route_delegates_revision_bound_control_to_runtime(self) -> None:
        item = self.runtime.current_status.work[0]
        status, document = self.request("POST", "/api/coding-work/cancel", {
            "identifier": item.identifier,
            "expected_revision": item.revision,
        })
        self.assertEqual(status, 202)
        self.assertEqual(
            self.runtime.cancel_calls,
            [(item.identifier, item.revision, None)],
        )
        self.assertEqual(document["work"][0]["state"], "cancelling")
        self.assertFalse(document["work"][0]["can_cancel"])

    def test_stale_cancel_is_a_truthful_conflict(self) -> None:
        item = self.runtime.current_status.work[0]
        self.runtime.cancel_error = CodingWorkStaleRevisionError("changed")
        status, document = self.request("POST", "/api/coding-work/cancel", {
            "identifier": item.identifier,
            "expected_revision": item.revision,
        })
        self.assertEqual(status, 409)
        self.assertEqual(document["code"], "stale_revision")

    def test_workspace_assets_present_active_attention_and_recent_receipts(self) -> None:
        assets = Path(__file__).parents[1] / "src/tori/web_assets"
        markup = (assets / "index.html").read_text(encoding="utf-8")
        script = (assets / "utility.js").read_text(encoding="utf-8")
        self.assertIn("Delegated Work", markup)
        self.assertIn('id="utility-coding-work-overview"', markup)
        self.assertIn('id="utility-coding-work-verification"', markup)
        self.assertIn('id="utility-coding-work-acceptance"', markup)
        for label in ("Needs attention", "Active", "Recent"):
            self.assertIn(label, script)
        self.assertIn("workItems[0]", script)
        self.assertIn("item.related_work_id", script)


if __name__ == "__main__":
    unittest.main()
