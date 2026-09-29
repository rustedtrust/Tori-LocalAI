from __future__ import annotations

from datetime import datetime, timezone
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.coding_work import CodingWorkConflictError, SQLiteCodingWorkStore
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_work_conversation import (
    CodingWorkConversationError,
    CodingWorkConversationService,
    recognize_delegated_work_intent,
)
from tori.coding_work_integration import (
    ACTIVE_WORK_STATES,
    CodingWorkRuntime,
    CodingWorkStatus,
)
from tori.coding_worker import (
    CodingWorkerAdapter,
    CodingWorkerError,
    FakeCodingWorkerAdapter,
)
from tori.coding_work_supervisor import (
    CodingWorkProcessSupervisor,
    CodingWorkSandboxAvailability,
    CodingWorkSandboxPlan,
    sanitized_worker_environment,
)
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.model_catalog import ModelDescriptor
from tori.providers import ChatResponse, ModelProvider
from tori.project_application import ProjectApplicationService
from tori.web import (
    LOOPBACK_HOST,
    WebApplication,
    WebApplicationError,
    _encode_stream_event,
    create_web_server,
)


CHAT_ID = "chat-" + "a" * 32
PROCESS_FIXTURE = Path(__file__).parent / "fixtures" / "coding_work_process_fixture.py"


def identifier_factory():  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}

    def create(prefix: str) -> str:
        counts[prefix] = counts.get(prefix, 0) + 1
        return f"{prefix}-{counts[prefix]:032x}"

    return create


class RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[object] = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("ordinary conversation", "fake-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        yield "ordinary conversation"

    def list_models(self):  # type: ignore[no-untyped-def]
        return (ModelDescriptor("fake", "fake-model", "Fake model"),)


class RuntimeFacade:
    def __init__(self, application: CodingWorkApplicationService) -> None:
        self.application = application
        self.admission_open = True
        self.calls: list[str] = []

    def create_work(self, **arguments):  # type: ignore[no-untyped-def]
        self.calls.append("create")
        return self.application.create_work(**arguments)

    def authorize(self, work_id, **arguments):  # type: ignore[no-untyped-def]
        self.calls.append("authorize")
        return self.application.authorize(work_id, **arguments)

    def start_work(self, work_id, *, expected_revision):  # type: ignore[no-untyped-def]
        self.calls.append("start")
        return self.application.start(work_id, expected_revision=expected_revision)

    def status(self, work_id=None, *, project_id=None):  # type: ignore[no-untyped-def]
        store = self.application._store
        selected = (
            (store.get_work(work_id),) if work_id is not None else store.list_work()
        )
        if project_id is not None:
            selected = tuple(item for item in selected if item.project_id == project_id)
        projected = tuple(CodingWorkRuntime._project(store, item) for item in selected)
        current = next((item for item in selected if item.state in ACTIVE_WORK_STATES), None)
        return CodingWorkStatus(
            "available", "ready", "Ready.", True, False,
            current is not None,
            None if current is None else current.identifier,
            projected,
        )

    def cancel(
        self, work_id, *, expected_revision, source_chat_id=None  # type: ignore[no-untyped-def]
    ):
        self.calls.append("cancel")
        self.application.request_cancellation(
            work_id,
            expected_revision=expected_revision,
            source_chat_id=source_chat_id,
        )
        self.application.deliver_directives(work_id)
        self.application.observe(work_id)
        return self.status(work_id).work[0]


class FailingStartAdapter(FakeCodingWorkerAdapter):
    def start(self, request):  # type: ignore[no-untyped-def]
        raise CodingWorkerError("the fixture worker failed", code="fixture_start_failed")


class DirectProcessSandbox:
    """Process-only test boundary; it makes no isolation claim."""

    def availability(self, _authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxAvailability(
            True, "test-direct", "test-only process boundary"
        )

    def plan(self, worker_argv, authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxPlan(
            tuple(worker_argv),
            sanitized_worker_environment(),
            authority.workspace_root,
            "read_write",
            "not_tested_by_direct_boundary",
            "not_tested_by_direct_boundary",
            "test-only process boundary",
        )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOOPBACK_HOST, 0))
        return int(listener.getsockname()[1])


class CodingWorkConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.clock_value = 100.0
        self.now = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
        self.store = SQLiteCodingWorkStore(
            self.root / "coding" / "tori.db",
            clock=lambda: self.now,
            identifier_factory=identifier_factory(),
        )
        self.store.initialize()
        self.adapter = FakeCodingWorkerAdapter(clock=lambda: self.now)
        self.runtime = RuntimeFacade(
            CodingWorkApplicationService(self.store, self.adapter)
        )
        self.service = CodingWorkConversationService(
            self.runtime,
            clock=lambda: self.clock_value,
            utc_clock=lambda: self.now,
            identifier_factory=lambda: "coding-proposal-" + "b" * 32,
        )

    def request_text(self) -> str:
        return (
            f"Tori, create a startup script in {self.workspace}. "
            "Acceptance criteria: startup.sh exists."
        )

    def test_clear_request_proposes_exact_workspace_objective_and_authority(self) -> None:
        request = self.service.recognize(self.request_text())
        assert request is not None
        proposal = self.service.propose(
            request, origin_chat_id=CHAT_ID, origin_chat_revision=3
        )
        self.assertEqual(proposal.workspace_root, str(self.workspace))
        self.assertEqual(proposal.acceptance_criteria, "startup.sh exists.")
        self.assertEqual(proposal.origin_chat_id, CHAT_ID)
        self.assertEqual(proposal.requested_capability, "tori.coding.work")
        self.assertIn("General network access", " ".join(proposal.limitations))
        review = self.service.recognize(f"Review this code in {self.workspace}.")
        assert review is not None
        review_proposal = self.service.propose(
            review, origin_chat_id=CHAT_ID, origin_chat_revision=4
        )
        self.assertFalse(review_proposal.modify_allowed)
        self.assertNotIn("Modify files", " ".join(review_proposal.authority_summary))

    def test_explicit_read_only_requests_never_propose_modify_authority(self) -> None:
        requests = (
            f"Review this code in {self.workspace}. Do not modify files.",
            f"Review code in {self.workspace}; don't edit files.",
            f"Review code in {self.workspace}; do not edit or modify files.",
            f"Review code in {self.workspace}, not edit it.",
            f"Review code in {self.workspace}; do not try to modify files.",
            f"Audit code in {self.workspace} in read-only mode.",
            f"Review code in {self.workspace} without changing files.",
        )
        for text in requests:
            with self.subTest(text=text):
                request = self.service.recognize(text)
                assert request is not None
                self.assertFalse(request.modify_allowed)
                proposal = self.service.propose(
                    request, origin_chat_id=CHAT_ID, origin_chat_revision=3
                )
                self.assertEqual(
                    proposal.document()["workspace_access"],
                    {"read": True, "modify": False},
                )
                self.assertNotIn("Modify files", " ".join(proposal.authority_summary))
        self.assertEqual(self.store.list_work(), ())

    def test_affirmative_mutation_and_conflicting_read_only_language(self) -> None:
        for text in (
            f"Fix this bug and update the implementation in {self.workspace}.",
            f"Edit code in {self.workspace}.",
        ):
            with self.subTest(text=text):
                request = self.service.recognize(text)
                assert request is not None
                self.assertTrue(request.modify_allowed)
        self.assertIsNone(self.service.recognize(
            f"Fix this bug in {self.workspace}. Do not modify files."
        ))
        self.assertIsNone(self.service.recognize(
            f"Read-only review and update code in {self.workspace}."
        ))
        self.assertIsNone(self.service.recognize(
            f"Do not modify code in {self.workspace}."
        ))
        limited = self.service.recognize(
            f"Change acceptance.txt in {self.workspace}. Do not change anything else."
        )
        assert limited is not None
        self.assertTrue(limited.modify_allowed)
        self.assertIsNone(self.service.recognize(
            "Look at this issue and help me with it."
        ))
        self.assertEqual(self.store.list_work(), ())

    def test_ambiguous_or_pathless_requests_remain_conversation(self) -> None:
        self.assertIsNone(self.service.recognize("Can you fix this bug?"))
        self.assertIsNone(self.service.recognize(f"Tell me about {self.workspace}."))
        self.assertIsNone(
            self.service.recognize(
                f"Review code in {self.workspace} and /another/workspace."
            )
        )

    def test_bounded_status_cancel_and_follow_up_intents(self) -> None:
        self.assertEqual(
            recognize_delegated_work_intent("How is that fix going?").kind,
            "status",
        )
        self.assertEqual(
            recognize_delegated_work_intent("Stop that coding job.").kind,
            "cancel",
        )
        follow = recognize_delegated_work_intent(
            "Continue that work and fix the remaining test."
        )
        assert follow is not None
        self.assertEqual((follow.kind, follow.instruction), (
            "follow_up", "fix the remaining test",
        ))
        self.assertIsNone(recognize_delegated_work_intent("Stop the music."))
        self.assertIsNone(recognize_delegated_work_intent("Tell me about OpenCode."))

    def test_filename_subjects_preserve_conservative_recognition(self) -> None:
        changed = self.service.recognize(
            f"Change acceptance.txt from before to after in {self.workspace}."
        )
        assert changed is not None
        self.assertTrue(changed.modify_allowed)

        review = self.service.recognize(f"Review README.md in {self.workspace}.")
        assert review is not None
        self.assertFalse(review.modify_allowed)

        self.assertIsNone(
            self.service.recognize(
                f"I mentioned acceptance.txt while talking about {self.workspace}."
            )
        )
        self.assertIsNone(
            self.service.recognize("Change acceptance.txt from before to after.")
        )
        self.assertIsNone(
            self.service.recognize(
                f"Change acceptance.txt in {self.workspace} and /another/workspace."
            )
        )
        self.assertIsNone(
            self.service.recognize(f"Update version 1.2 in {self.workspace}.")
        )
        self.assertIsNone(
            self.service.recognize(f"Update https://example.com in {self.workspace}.")
        )
        self.assertIsNone(
            self.service.recognize(f"Update example.com in {self.workspace}.")
        )

    def test_missing_workspace_is_rejected_before_proposal(self) -> None:
        request = self.service.recognize(
            f"Create a script in {self.root / 'missing'}."
        )
        assert request is not None
        with self.assertRaises(CodingWorkConversationError) as caught:
            self.service.propose(request, origin_chat_id=CHAT_ID, origin_chat_revision=1)
        self.assertEqual(caught.exception.code, "coding_work_workspace_missing")
        self.assertEqual(self.store.list_work(), ())

    def test_confirmed_proposal_creates_authorizes_and_starts_through_runtime(self) -> None:
        request = self.service.recognize(self.request_text())
        assert request is not None
        proposal = self.service.propose(
            request, origin_chat_id=CHAT_ID, origin_chat_revision=1
        )
        work = self.service.apply(proposal)
        self.assertEqual(work.state, "running")
        self.assertEqual(self.runtime.calls, ["create", "authorize", "start"])
        self.assertEqual(work.origin_chat_id, CHAT_ID)
        authorization = self.store.get_authorization(work.current_authorization_id)
        self.assertEqual(
            authorization.confirmation_provenance,
            "explicit_conversation_confirmation:" + proposal.identifier,
        )

    def test_expired_proposal_creates_nothing(self) -> None:
        request = self.service.recognize(self.request_text())
        assert request is not None
        proposal = self.service.propose(
            request, origin_chat_id=CHAT_ID, origin_chat_revision=1
        )
        self.clock_value = proposal.expires_at + 1
        with self.assertRaises(CodingWorkConversationError) as expired:
            self.service.apply(proposal)
        self.assertEqual(expired.exception.code, "expired_confirmation")
        self.assertEqual(self.store.list_work(), ())

    def test_substituted_workspace_creates_nothing(self) -> None:
        request = self.service.recognize(self.request_text())
        assert request is not None
        proposal = self.service.propose(
            request, origin_chat_id=CHAT_ID, origin_chat_revision=1
        )
        original = self.root / "original-workspace"
        self.workspace.rename(original)
        self.workspace.mkdir()
        with self.assertRaises(CodingWorkConversationError) as substituted:
            self.service.apply(proposal)
        self.assertEqual(substituted.exception.code, "stale_confirmation")
        self.assertEqual(self.store.list_work(), ())

    def make_web_application(
        self,
        *,
        adapter: CodingWorkerAdapter | None = None,
        port: int = 8765,
    ) -> tuple[WebApplication, RuntimeFacade, RecordingProvider]:
        selected_adapter = adapter or self.adapter
        runtime = RuntimeFacade(CodingWorkApplicationService(self.store, selected_adapter))
        chats = ChatService(ConversationArchiveStore(
            self.root / "conversations" / "tori.db",
            clock=lambda: self.now,
            identifier_factory=lambda: CHAT_ID,
        ))
        provider = RecordingProvider()
        application = WebApplication(
            provider,
            port=port,
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "memory" / "tori.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "knowledge", working_directory=self.root
            ),
            provider_name="fake",
            model_name="fake-model",
            chat_service=chats,
            project_application=ProjectApplicationService(chats),
            coding_work_runtime=runtime,  # type: ignore[arg-type]
            clock=lambda: self.clock_value,
            utc_clock=lambda: self.now,
        )
        return application, runtime, provider

    def test_fresh_project_chat_coding_proposal_carries_organization_only(self) -> None:
        application, runtime, provider = self.make_web_application()
        _status, created = application.create_project({
            "title": "Project Alpha", "objective": "Organize related Coding Work",
        })
        project = created["project"]
        application.associate_active_project({"project_id": project["identifier"]})
        _status, proposed = application.submit(self.request_text())
        proposal = proposed["confirmation"]["proposal"]
        self.assertEqual(proposal["project"], {
            "identifier": project["identifier"], "title": "Project Alpha",
            "role": "organization_only_no_capability_authority",
        })
        self.assertEqual(runtime.calls, [])
        self.assertEqual(provider.requests, [])
        self.assertEqual(
            application._chat_service.get_chat(application._active_chat_id).metadata.project_id,
            project["identifier"],
        )
        application.confirm(proposed["confirmation"]["token"], "confirm")
        work = self.store.list_work()[0]
        self.assertEqual(work.project_id, project["identifier"])
        self.assertEqual(runtime.calls, ["create", "authorize", "start"])

    def test_project_chat_read_only_proposal_grants_no_authority(self) -> None:
        application, runtime, provider = self.make_web_application()
        _status, created = application.create_project({
            "title": "Project Alpha", "objective": "Organize related Coding Work",
        })
        project = created["project"]
        application.associate_active_project({"project_id": project["identifier"]})
        _status, proposed = application.submit(
            f"Review this code in {self.workspace}. Do not modify files."
        )
        proposal = proposed["confirmation"]["proposal"]
        self.assertEqual(proposal["project"]["identifier"], project["identifier"])
        self.assertEqual(proposal["project"]["role"],
                         "organization_only_no_capability_authority")
        self.assertEqual(proposal["workspace_access"], {"read": True, "modify": False})
        self.assertEqual(runtime.calls, [])
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_work(), ())

    def test_follow_up_rejects_conflicting_current_project(self) -> None:
        application, runtime, _provider = self.make_web_application()
        _status, first = application.create_project({
            "title": "Alpha", "objective": "Own Coding Work",
        })
        _status, second = application.create_project({
            "title": "Beta", "objective": "Different Project",
        })
        application.associate_active_project({"project_id": first["project"]["identifier"]})
        _status, proposed = application.submit(self.request_text())
        application.confirm(proposed["confirmation"]["token"], "confirm")
        original = self.store.list_work()[0]
        run = self.store.get_run(original.current_run_id)
        assert run.harness_session_id is not None
        self.adapter.complete(run.harness_session_id, summary="Done.")
        runtime.application.observe(original.identifier)
        application.associate_active_project({
            "project_id": second["project"]["identifier"],
            "expected_chat_revision": application._active_chat_revision,
        })
        with self.assertRaises(WebApplicationError) as conflict:
            application.submit("Continue that work and fix the remaining test.")
        self.assertEqual(conflict.exception.code, "coding_work_project_conflict")
        self.assertEqual(len(self.store.list_work()), 1)

    def test_coding_application_rejects_related_project_relabeling(self) -> None:
        original = self.store.create_work(
            objective="Original", workspace_root=str(self.workspace),
            project_id="project-" + "a" * 32,
        )
        with self.assertRaises(CodingWorkConflictError):
            self.runtime.application.create_work(
                objective="Follow-up", workspace_root=self.workspace,
                project_id="project-" + "b" * 32,
                related_work_id=original.identifier,
            )
        self.assertEqual(len(self.store.list_work()), 1)

    def test_web_confirmation_is_required_one_use_and_cancel_creates_nothing(self) -> None:
        application, runtime, provider = self.make_web_application()
        status, proposed = application.submit(self.request_text())
        self.assertEqual(status, 200)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(provider.requests, [])
        confirmation = proposed["confirmation"]
        self.assertEqual(confirmation["action"], "coding_work.authorize")
        self.assertEqual(
            confirmation["proposal"]["workspace"], str(self.workspace)
        )
        application.confirm(confirmation["token"], "cancel")
        self.assertEqual(self.store.list_work(), ())
        with self.assertRaises(WebApplicationError) as reused:
            application.confirm(confirmation["token"], "confirm")
        self.assertEqual(reused.exception.code, "unknown_confirmation")
        _status, reproposed = application.submit(self.request_text())
        self.assertEqual(
            reproposed["confirmation"]["action"], "coding_work.authorize"
        )

    def test_exact_filename_change_request_requires_confirmation_without_execution(self) -> None:
        application, runtime, provider = self.make_web_application()
        request_text = (
            f'Tori, in {self.workspace}, change acceptance.txt from "before" to '
            '"after". Do not change anything else.'
        )

        status, proposed = application.submit(request_text)

        self.assertEqual(status, 200)
        confirmation = proposed["confirmation"]
        self.assertEqual(confirmation["action"], "coding_work.authorize")
        proposal = confirmation["proposal"]
        self.assertEqual(proposal["workspace"], str(self.workspace))
        self.assertEqual(proposal["workspace_access"], {"read": True, "modify": True})
        self.assertTrue(proposal["sandboxed_execution"])
        self.assertEqual(proposal["requested_capability"], "tori.coding.work")
        self.assertEqual(runtime.calls, [])
        self.assertEqual(provider.requests, [])
        self.assertEqual(self.store.list_work(), ())

    def test_web_confirmation_starts_work_and_stream_shape_is_valid(self) -> None:
        application, runtime, provider = self.make_web_application()
        event = list(application.stream_submit(self.request_text()))[-1]
        _encode_stream_event(event)
        status, result = application.confirm(
            event["confirmation"]["token"], "confirm"
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["coding_work"]["state"], "running")
        self.assertEqual(runtime.calls, ["create", "authorize", "start"])
        self.assertEqual(provider.requests, [])
        self.assertEqual(len(self.store.list_work()), 1)

    def test_http_confirmation_thread_exits_while_parent_death_worker_survives(self) -> None:
        supervisor = CodingWorkProcessSupervisor(
            lambda _request: (
                sys.executable,
                str(PROCESS_FIXTURE),
                "parent-death-wait",
            ),
            sandbox=DirectProcessSandbox(),
        )
        self.addCleanup(supervisor.shutdown)
        caller_native_ids: list[int] = []
        original_start = supervisor.start

        def recording_start(request):  # type: ignore[no-untyped-def]
            caller_native_ids.append(threading.get_native_id())
            return original_start(request)

        supervisor.start = recording_start  # type: ignore[method-assign]
        application, runtime, _provider = self.make_web_application(
            adapter=supervisor,
            port=free_port(),
        )
        server = create_web_server(application)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()

        def stop_server() -> None:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

        self.addCleanup(stop_server)

        def post(path: str, document: dict[str, object]) -> tuple[int, dict[str, object]]:
            connection = HTTPConnection(LOOPBACK_HOST, application.port, timeout=3)
            payload = json.dumps(document).encode("utf-8")
            connection.request(
                "POST",
                path,
                body=payload,
                headers={
                    "Host": application.expected_host,
                    "Origin": application.expected_origin,
                    "X-Tori-CSRF": application.csrf_token,
                    "Content-Type": "application/json",
                    "Content-Length": str(len(payload)),
                },
            )
            response = connection.getresponse()
            result = response.status, json.loads(response.read())
            connection.close()
            return result

        status, proposed = post("/api/message", {"message": self.request_text()})
        self.assertEqual(status, 200)
        status, confirmed = post(
            "/api/confirm",
            {
                "token": proposed["confirmation"]["token"],  # type: ignore[index]
                "decision": "confirm",
            },
        )
        self.assertEqual(status, 201)
        self.assertIn(
            confirmed["coding_work"]["state"],  # type: ignore[index]
            {"starting", "running"},
        )
        self.assertEqual(len(caller_native_ids), 1)

        caller_task = Path(f"/proc/{os.getpid()}/task/{caller_native_ids[0]}")
        deadline = time.monotonic() + 2
        while caller_task.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(caller_task.exists())

        work = self.store.list_work()[0]
        deadline = time.monotonic() + 3
        while work.state != "waiting" and time.monotonic() < deadline:
            time.sleep(0.01)
            work = runtime.application.inspect(work.identifier)
        self.assertEqual(work.state, "waiting")
        run = self.store.get_run(work.current_run_id)
        session = supervisor._require(runtime.application._binding(run))
        self.assertIsNone(session.process.poll())
        self.assertNotEqual(
            supervisor._process_spawner.native_id,
            caller_native_ids[0],
        )

        supervisor.shutdown()
        self.assertIsNotNone(session.process.poll())
        self.assertFalse(supervisor._process_spawner.alive)

    def test_changed_conversation_rejects_stale_confirmation(self) -> None:
        application, _runtime, _provider = self.make_web_application()
        _status, proposed = application.submit(self.request_text())
        assert application._active_chat_revision is not None
        application._active_chat_revision += 1
        with self.assertRaises(WebApplicationError) as stale:
            application.confirm(proposed["confirmation"]["token"], "confirm")
        self.assertEqual(stale.exception.code, "stale_confirmation")
        self.assertEqual(self.store.list_work(), ())

    def test_failed_start_is_reported_truthfully_and_keeps_failed_work(self) -> None:
        application, runtime, _provider = self.make_web_application(
            adapter=FailingStartAdapter(clock=lambda: self.now)
        )
        _status, proposed = application.submit(self.request_text())
        status, result = application.confirm(
            proposed["confirmation"]["token"], "confirm"
        )
        self.assertEqual(status, 503)
        self.assertEqual(result["coding_work"]["state"], "failed")
        self.assertIn("could not start", result["transcript"][-1]["text"])
        self.assertEqual(runtime.calls, ["create", "authorize", "start"])

    def test_conversation_status_and_stop_use_authoritative_work_state(self) -> None:
        application, runtime, provider = self.make_web_application()
        _status, proposed = application.submit(self.request_text())
        application.confirm(proposed["confirmation"]["token"], "confirm")

        status, reported = application.submit("How is that fix going?")
        self.assertEqual(status, 200)
        self.assertIn("Delegated Work is running", reported["transcript"][-1]["text"])
        self.assertIn("Commit/push: not authorized", reported["transcript"][-1]["text"])
        self.assertEqual(provider.requests, [])

        status, stopped = application.submit("Stop that coding job.")
        self.assertEqual(status, 200)
        self.assertIn("requested cancellation", stopped["transcript"][-1]["text"])
        self.assertIn("cancel", runtime.calls)
        self.assertEqual(self.store.list_work()[0].state, "cancelled")

    def test_terminal_follow_up_requires_fresh_authorization_and_is_durably_related(self) -> None:
        application, runtime, provider = self.make_web_application()
        _status, proposed = application.submit(self.request_text())
        application.confirm(proposed["confirmation"]["token"], "confirm")
        original = self.store.list_work()[0]
        run = self.store.get_run(original.current_run_id)
        assert run.harness_session_id is not None
        self.adapter.complete(
            run.harness_session_id,
            summary="The startup script was created.",
            changed_paths=("startup.sh",),
            verification=({"kind": "tests", "status": "passed"},),
        )
        runtime.application.observe(original.identifier)
        receipt = application.coding_work_state()["work"][0]
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(receipt["changed_paths"], ["startup.sh"])
        self.assertEqual(
            receipt["verification"],
            [{"kind": "tests", "status": "passed"}],
        )
        self.assertEqual(
            receipt["acceptance_status"], "not_independently_verified"
        )

        status, follow_up = application.submit(
            "Continue that work and fix the remaining test."
        )
        self.assertEqual(status, 200)
        confirmation = follow_up["confirmation"]
        self.assertEqual(confirmation["action"], "coding_work.authorize")
        self.assertEqual(confirmation["proposal"]["related_work_id"], original.identifier)
        self.assertEqual(len(self.store.list_work()), 1)

        status, started = application.confirm(confirmation["token"], "confirm")
        self.assertEqual(status, 201)
        related = next(
            item for item in self.store.list_work() if item.identifier != original.identifier
        )
        self.assertEqual(related.objective, "fix the remaining test")
        created = self.store.events(related.identifier)[0]
        self.assertEqual(created.payload["related_work_id"], original.identifier)
        self.assertNotEqual(
            related.current_authorization_id,
            original.current_authorization_id,
        )
        self.assertEqual(provider.requests, [])
        self.assertEqual(started["coding_work"]["identifier"], related.identifier)


if __name__ == "__main__":
    unittest.main()
