from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import signal
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from tori.coding_work import CodingWorkAuthority, CodingWorkDirective, SQLiteCodingWorkStore
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_work_supervisor import (
    BubblewrapCodingWorkSandbox,
    CodingWorkProcessSupervisor,
    CodingWorkSandboxAvailability,
    CodingWorkSandboxPlan,
    CodingWorkSupervisorBounds,
    MAX_SUPERVISOR_EVENTS,
    sanitized_worker_environment,
)
from tori.coding_worker import CodingWorkerDirectiveReceipt, CodingWorkerError
from tori.time_context import FakeClock


FIXTURE = Path(__file__).parent / "fixtures" / "coding_work_process_fixture.py"


def identifier_factory():  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}

    def create(prefix: str) -> str:
        counts[prefix] = counts.get(prefix, 0) + 1
        return f"{prefix}-{counts[prefix]:032x}"

    return create


class DirectFixtureSandbox:
    """Process-only test boundary; it makes no security-isolation claim."""

    def availability(self, authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxAvailability(True, "test-direct", "test-only process boundary")

    def plan(self, worker_argv, authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxPlan(
            tuple(worker_argv),
            sanitized_worker_environment(),
            authority.workspace_root,
            "read_write" if authority.modify_allowed else "read_only",
            "not_tested_by_direct_boundary",
            "not_tested_by_direct_boundary",
            "test-only process boundary",
        )


class UnavailableSandbox(DirectFixtureSandbox):
    def availability(self, authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxAvailability(
            False, "unavailable", "disabled", "Synthetic isolation failure."
        )


class CodingWorkSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.clock = FakeClock(datetime(2026, 8, 23, 12, tzinfo=timezone.utc))
        self.store = SQLiteCodingWorkStore(
            self.root / "state" / "coding-work.db",
            clock=self.clock,
            identifier_factory=identifier_factory(),
        )
        self.store.initialize()
        self._correlations = iter(f"launch-{item}" for item in range(1, 50))
        self.supervisors: list[CodingWorkProcessSupervisor] = []
        self.addCleanup(self._shutdown_supervisors)

    def _shutdown_supervisors(self) -> None:
        for supervisor in self.supervisors:
            supervisor.shutdown()

    def application(
        self,
        mode: str,
        *,
        sandbox=None,  # type: ignore[no-untyped-def]
        grace: float = 0.15,
        session_prefix: str = "session",
    ) -> tuple[CodingWorkApplicationService, CodingWorkProcessSupervisor]:
        counter = iter(range(1, 20))
        supervisor = CodingWorkProcessSupervisor(
            lambda _request: (sys.executable, str(FIXTURE), mode),
            sandbox=sandbox or DirectFixtureSandbox(),
            bounds=CodingWorkSupervisorBounds(
                stdout_bytes=4_096,
                stderr_bytes=64,
                termination_grace_seconds=grace,
            ),
            clock=self.clock,
            session_factory=lambda: f"{session_prefix}-{next(counter)}",
        )
        self.supervisors.append(supervisor)
        return CodingWorkApplicationService(
            self.store,
            supervisor,
            correlation_factory=lambda: next(self._correlations),
        ), supervisor

    def create_authorized(
        self,
        application: CodingWorkApplicationService,
        *,
        workspace: Path | None = None,
        read: bool = True,
        modify: bool = True,
        execute: bool = True,
    ):
        work = application.create_work(
            objective="Exercise the supervised fixture",
            workspace_root=workspace or self.workspace,
        )
        return application.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=read,
            modify_allowed=modify,
            sandboxed_execution_allowed=execute,
            confirmation_provenance="explicit_test_confirmation",
        )

    def wait_for_state(
        self,
        application: CodingWorkApplicationService,
        work_id: str,
        states: set[str],
        *,
        timeout: float = 3,
    ):
        deadline = time.monotonic() + timeout
        latest = self.store.get_work(work_id)
        while time.monotonic() < deadline:
            latest = application.observe(work_id)
            if latest.state in states:
                return latest
            time.sleep(0.01)
        self.fail(f"Coding Work remained {latest.state}; expected {states}")

    def test_launch_requires_execution_and_read_authority_and_fails_closed(self) -> None:
        application, _supervisor = self.application("complete")
        denied = self.create_authorized(application, execute=False)
        denied_result = application.start(denied.identifier, expected_revision=denied.revision)
        self.assertEqual(denied_result.state, "failed")
        self.assertEqual(self.store.get_run(denied_result.current_run_id).failure_code, "authority_denied")

        unreadable = self.create_authorized(application, read=False, modify=False)
        unreadable_result = application.start(
            unreadable.identifier, expected_revision=unreadable.revision
        )
        self.assertEqual(
            self.store.get_run(unreadable_result.current_run_id).failure_code,
            "authority_denied",
        )

        other_store = SQLiteCodingWorkStore(
            self.root / "unavailable" / "coding-work.db",
            clock=self.clock,
            identifier_factory=identifier_factory(),
        )
        other_store.initialize()
        supervisor = CodingWorkProcessSupervisor(
            lambda _request: (sys.executable, str(FIXTURE), "complete"),
            sandbox=UnavailableSandbox(),
            clock=self.clock,
        )
        self.supervisors.append(supervisor)
        unavailable = CodingWorkApplicationService(other_store, supervisor)
        work = self.create_authorized(unavailable)
        unavailable_result = unavailable.start(work.identifier, expected_revision=work.revision)
        self.assertEqual(unavailable_result.state, "failed")
        self.assertEqual(
            other_store.get_run(unavailable_result.current_run_id).failure_code,
            "isolation_unavailable",
        )

    def test_completion_crash_bounded_diagnostics_and_terminal_idempotency(self) -> None:
        application, supervisor = self.application("complete")
        queued = self.create_authorized(application)
        started = application.start(queued.identifier, expected_revision=queued.revision)
        completed = self.wait_for_state(application, started.identifier, {"completed"})
        self.assertEqual(completed.result["summary"], "The fixture completed.")
        self.assertEqual(completed.result["changed_paths"], ["fixture-output.txt"])
        repeated = application.observe(completed.identifier)
        self.assertEqual(repeated.revision, completed.revision)
        run = self.store.get_run(completed.current_run_id)
        diagnostics = supervisor.diagnostics(application._binding(run))
        self.assertLessEqual(len(diagnostics.stdout.encode()), 4_096)

        crash_application, crash_supervisor = self.application(
            "crash", session_prefix="crash-session"
        )
        crashed_work = self.create_authorized(crash_application)
        started_crash = crash_application.start(
            crashed_work.identifier, expected_revision=crashed_work.revision
        )
        failed = self.wait_for_state(crash_application, started_crash.identifier, {"failed"})
        self.assertEqual(failed.result["summary"], "The supervised worker process stopped unexpectedly.")
        crash_run = self.store.get_run(failed.current_run_id)
        crash_diagnostics = crash_supervisor.diagnostics(crash_application._binding(crash_run))
        self.assertIn("synthetic fixture crash", crash_diagnostics.stderr)
        self.assertTrue(crash_diagnostics.stderr_truncated)
        self.assertEqual(len(crash_diagnostics.stderr.encode()), 64)
        self.assertEqual(crash_diagnostics.exit_code, 7)

    def test_project_local_dependency_artifacts_are_reported_workspace_changes(self) -> None:
        application, _supervisor = self.application("project-dependency-artifacts")
        work = self.create_authorized(application)
        work = application.start(work.identifier, expected_revision=work.revision)
        completed = self.wait_for_state(application, work.identifier, {"completed"})
        self.assertEqual(
            completed.result["changed_paths"],
            [".venv/fixture-package", "node_modules/fixture/package.json"],
        )

    def test_one_active_worker_per_workspace(self) -> None:
        application, _supervisor = self.application("wait")
        first = self.create_authorized(application)
        first = application.start(first.identifier, expected_revision=first.revision)
        self.wait_for_state(application, first.identifier, {"running", "waiting"})
        second = self.create_authorized(application)
        blocked = application.start(second.identifier, expected_revision=second.revision)
        self.assertEqual(blocked.state, "failed")
        self.assertEqual(self.store.get_run(blocked.current_run_id).failure_code, "workspace_busy")
        current = self.store.get_work(first.identifier)
        directive = application.request_cancellation(
            current.identifier, expected_revision=current.revision
        )
        application.deliver_directives(current.identifier)
        self.assertEqual(
            self.wait_for_state(application, current.identifier, {"cancelled"}).state,
            "cancelled",
        )
        self.assertEqual(self.store.get_directive(directive.identifier).status, "delivered")

    def test_durable_process_owner_survives_transient_start_thread_and_shutdown(self) -> None:
        application, supervisor = self.application("parent-death-wait")
        authorized = self.create_authorized(application)
        outcome: dict[str, object] = {}

        def start_from_transient_thread() -> None:
            try:
                outcome["caller_native_id"] = threading.get_native_id()
                started = application.start(
                    authorized.identifier, expected_revision=authorized.revision
                )
                outcome["work"] = self.wait_for_state(
                    application, started.identifier, {"waiting"}
                )
            except BaseException as exc:
                outcome["error"] = exc

        caller = threading.Thread(target=start_from_transient_thread)
        caller.start()
        caller.join(timeout=5)
        self.assertFalse(caller.is_alive())
        if "error" in outcome:
            raise outcome["error"]  # type: ignore[misc]

        waiting = outcome["work"]
        self.assertEqual(waiting.state, "waiting")  # type: ignore[union-attr]
        run = self.store.get_run(waiting.current_run_id)  # type: ignore[union-attr]
        session = supervisor._require(application._binding(run))
        time.sleep(0.05)
        self.assertIsNone(session.process.poll())
        owner_native_id = supervisor._process_spawner.native_id
        self.assertIsNotNone(owner_native_id)
        self.assertNotEqual(owner_native_id, outcome["caller_native_id"])
        children = Path(
            f"/proc/{os.getpid()}/task/{owner_native_id}/children"
        ).read_text(encoding="ascii").split()
        self.assertIn(str(session.process.pid), children)

        supervisor.shutdown()
        self.assertIsNotNone(session.process.poll())
        self.assertFalse(supervisor._process_spawner.alive)

    def test_cancellation_escalates_and_cleans_child_process_group(self) -> None:
        delayed_application, delayed_supervisor = self.application("delay-cancel")
        delayed = self.create_authorized(delayed_application)
        delayed = delayed_application.start(delayed.identifier, expected_revision=delayed.revision)
        delayed = self.wait_for_state(delayed_application, delayed.identifier, {"waiting"})
        delayed_application.request_cancellation(
            delayed.identifier, expected_revision=delayed.revision
        )
        started = time.monotonic()
        delayed_application.deliver_directives(delayed.identifier)
        cancelled = self.wait_for_state(delayed_application, delayed.identifier, {"cancelled"})
        self.assertLess(time.monotonic() - started, 2)
        run = self.store.get_run(cancelled.current_run_id)
        diagnostics = delayed_supervisor.diagnostics(delayed_application._binding(run))
        self.assertEqual(diagnostics.exit_code, -signal.SIGKILL)
        self.assertEqual(diagnostics.termination, "cancelled_by_user")
        self.assertTrue(diagnostics.termination_signal_sent)
        self.assertTrue(diagnostics.forced_kill_sent)

        child_application, _child_supervisor = self.application(
            "spawn-child", session_prefix="child-session"
        )
        child_work = self.create_authorized(child_application)
        child_work = child_application.start(
            child_work.identifier, expected_revision=child_work.revision
        )
        child_work = self.wait_for_state(child_application, child_work.identifier, {"completed"})
        child_pid = int(child_work.progress["verification"])
        for _attempt in range(100):
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            stat_path = Path(f"/proc/{child_pid}/stat")
            if stat_path.exists() and stat_path.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        else:
            self.fail("The fixture child survived parent completion.")

    def test_restart_refuses_pid_only_attachment_and_never_restarts(self) -> None:
        application, first_supervisor = self.application("wait")
        work = self.create_authorized(application)
        work = application.start(work.identifier, expected_revision=work.revision)
        work = self.wait_for_state(application, work.identifier, {"waiting"})
        original_run = self.store.get_run(work.current_run_id)
        application.prepare_restart_reconciliation()

        second_supervisor = CodingWorkProcessSupervisor(
            lambda _request: (sys.executable, str(FIXTURE), "wait"),
            sandbox=DirectFixtureSandbox(),
            clock=self.clock,
            session_factory=lambda: "replacement-session",
        )
        self.supervisors.append(second_supervisor)
        restarted = CodingWorkApplicationService(self.store, second_supervisor)
        failed = restarted.reconcile(work.identifier)
        self.assertEqual(failed.state, "failed")
        self.assertEqual(len(self.store.list_runs(work.identifier)), 1)
        self.assertEqual(self.store.list_runs(work.identifier)[0].identifier, original_run.identifier)
        first_supervisor.shutdown()

    def test_durable_directive_claim_recovers_and_delivery_is_idempotent(self) -> None:
        application, supervisor = self.application("wait")
        work = self.create_authorized(application)
        work = application.start(work.identifier, expected_revision=work.revision)
        work = self.wait_for_state(application, work.identifier, {"waiting"})
        directive = application.submit_follow_up(
            work.identifier,
            expected_revision=work.revision,
            instruction="Run the focused verification again.",
        )
        claimed = self.store.claim_directive(directive.identifier)
        self.assertEqual(claimed.status, "delivering")
        delivered = application.deliver_directives(work.identifier)[0]
        self.assertEqual(delivered.status, "delivered")
        run = self.store.get_run(work.current_run_id)
        receipt = supervisor.submit_directive(application._binding(run), delivered)
        self.assertTrue(receipt.duplicate)
        self.wait_for_state(application, work.identifier, {"running"})

    def test_in_memory_event_history_is_bounded_and_reports_a_gap(self) -> None:
        application, supervisor = self.application("wait")
        work = self.create_authorized(application)
        work = application.start(work.identifier, expected_revision=work.revision)
        work = self.wait_for_state(application, work.identifier, {"waiting"})
        directive = application.submit_follow_up(
            work.identifier,
            expected_revision=work.revision,
            instruction="EMIT_MANY",
        )
        application.deliver_directives(work.identifier)
        run = self.store.get_run(work.current_run_id)
        binding = application._binding(run)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            observation = supervisor.inspect(binding)
            if int(observation.event_cursor or "0") >= 600:
                break
            time.sleep(0.01)
        else:
            self.fail("The bounded-event fixture did not finish emitting")
        observed = supervisor.attach(binding, after_sequence=0)
        self.assertEqual(observed[0].payload["verification"], "history_truncated")
        self.assertEqual(observed[-1].kind, "waiting")
        internal = supervisor._require(binding)
        self.assertEqual(len(internal.events), MAX_SUPERVISOR_EVENTS)
        self.assertGreater(internal.events[0].sequence, 1)
        internal.directives = {
            f"coding-directive-{index:032x}": CodingWorkerDirectiveReceipt(
                f"coding-directive-{index:032x}", f"receipt-{index}"
            )
            for index in range(512)
        }
        overflow = CodingWorkDirective(
            "coding-directive-" + "f" * 32,
            work.identifier,
            run.identifier,
            run.authorization_id,
            "instruction",
            "One more instruction",
            None,
            "pending",
            None,
            None,
            1,
            "2000-01-01T00:00:00Z",
            "2000-01-01T00:00:00Z",
            None,
        )
        with self.assertRaises(CodingWorkerError) as receipt_limit:
            supervisor.submit_directive(binding, overflow)
        self.assertEqual(receipt_limit.exception.code, "directive_receipt_limit")


class CodingWorkSandboxPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / ".git").mkdir()
        (self.workspace / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (self.workspace / "runtime").mkdir()
        self.outside = self.root / "outside-secret"
        self.outside.write_text("must-not-read\n", encoding="utf-8")
        (self.workspace / "escape").symlink_to(self.outside)
        self.sandbox = BubblewrapCodingWorkSandbox(
            "/usr/bin/bwrap",
            protected_runtime_root=self.workspace / "runtime",
            project_collection_root=self.root / "project-collection",
        )

    def authority(self, *, modify: bool = True) -> CodingWorkAuthority:
        return CodingWorkAuthority(str(self.workspace), True, modify, True)

    def test_plan_protects_git_runtime_network_home_and_environment(self) -> None:
        with patch.dict(os.environ, {
            "TORI_SYNTHETIC_SECRET": "must-not-leak",
            "SSH_AUTH_SOCK": "/tmp/synthetic-agent.sock",
            "DOCKER_HOST": "unix:///tmp/synthetic-docker.sock",
        }):
            plan = self.sandbox.plan(("/usr/bin/python3", "worker.py"), self.authority())
        arguments = plan.argv
        self.assertIn("--unshare-all", arguments)
        self.assertIn("--die-with-parent", arguments)
        self.assertIn("--new-session", arguments)
        self.assertIn(str(self.workspace), arguments)
        self.assertIn("/workspace", arguments)
        git_index = arguments.index(str(self.workspace / ".git"))
        self.assertEqual(arguments[git_index - 1], "--ro-bind")
        self.assertEqual(arguments[git_index + 1], "/workspace/.git")
        runtime_index = arguments.index("/workspace/runtime")
        self.assertEqual(arguments[runtime_index - 1], "--tmpfs")
        self.assertIn("--remount-ro", arguments)
        rendered = " ".join(arguments)
        self.assertNotIn(str(self.outside), rendered)
        self.assertNotIn(str(self.root / "sibling"), rendered)
        self.assertNotIn("docker.sock", rendered)
        self.assertEqual(plan.environment["HOME"], "/tmp/tori-worker-home")
        self.assertNotIn("TORI_SYNTHETIC_SECRET", plan.environment)
        self.assertNotIn("SSH_AUTH_SOCK", plan.environment)
        self.assertNotIn("DOCKER_HOST", plan.environment)
        self.assertNotIn("HTTP_PROXY", plan.environment)

    def test_read_only_workspace_and_unsafe_git_or_broad_workspace_refuse(self) -> None:
        read_only = self.sandbox.plan(("/bin/true",), self.authority(modify=False))
        workspace_index = read_only.argv.index(str(self.workspace))
        self.assertEqual(read_only.argv[workspace_index - 1], "--ro-bind")

        shutil.rmtree(self.workspace / ".git")
        (self.workspace / ".git").symlink_to(self.root / "outside-git")
        with self.assertRaises(CodingWorkerError) as unsafe:
            self.sandbox.plan(("/bin/true",), self.authority())
        self.assertEqual(unsafe.exception.code, "unsafe_git_control_state")

        (self.workspace / ".git").unlink()
        (self.workspace / ".git").write_text(
            "gitdir: /outside/authoritative-control\n", encoding="utf-8"
        )
        with self.assertRaises(CodingWorkerError) as linked_worktree:
            self.sandbox.plan(("/bin/true",), self.authority())
        self.assertEqual(linked_worktree.exception.code, "unsupported_git_layout")

        collection = self.root / "collection"
        collection.mkdir()
        broad = BubblewrapCodingWorkSandbox(
            "/usr/bin/bwrap",
            protected_runtime_root=self.root / "protected-runtime",
            project_collection_root=collection,
        )
        with self.assertRaises(CodingWorkerError) as broad_error:
            broad.plan(
                ("/bin/true",),
                CodingWorkAuthority(str(self.root), True, True, True),
            )
        self.assertEqual(broad_error.exception.code, "workspace_too_broad")

    def test_native_fixture_security_probe_runs_only_when_namespaces_are_available(self) -> None:
        availability = self.sandbox.availability(self.authority())
        if not availability.available:
            self.skipTest(availability.reason or "Bubblewrap unavailable")
        fixture = self.workspace / "fixture.py"
        shutil.copyfile(FIXTURE, fixture)
        (self.workspace / "fixture-readable.txt").write_text("readable\n", encoding="utf-8")
        runtime_secret = self.workspace / "runtime" / "canonical-secret"
        runtime_secret.write_text("must-not-read\n", encoding="utf-8")
        home = self.root / "home-secret"
        home.write_text("must-not-read\n", encoding="utf-8")
        plan = self.sandbox.plan(
            (
                "/usr/bin/python3", "/workspace/fixture.py", "security-probe",
                str(self.outside), str(runtime_secret), str(home),
            ),
            self.authority(),
        )
        completed = __import__("subprocess").run(
            plan.argv,
            cwd=self.workspace,
            env=dict(plan.environment),
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        output = completed.stdout.decode("utf-8")
        self.assertIn('"outside_visible": false', output)
        self.assertIn('"runtime_visible": false', output)
        self.assertIn('"home_secret_visible": false', output)
        self.assertIn('"symlink_escape_visible": false', output)
        self.assertIn('"git_head_readable": true', output)
        self.assertIn('"git_control_writable": false', output)
        self.assertIn('"network_available": false', output)
        self.assertIn('"synthetic_secret": "unset"', output)


if __name__ == "__main__":
    unittest.main()
