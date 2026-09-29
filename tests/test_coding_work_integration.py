from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from tori.backups import BackupService, BackupSafetyError

from tori.coding_work import (
    CodingWorkAuthority,
    CodingWorkConflictError,
    CodingWorkUnavailableError,
    SQLiteCodingWorkStore,
)
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_work_integration import (
    CodingWorkControlUnsupportedError,
    CodingWorkRuntime,
)
from tori.coding_work_runtime import (
    CodingWorkProductionSettings,
    CodingWorkReadiness,
    CodingWorkRuntimeInitializer,
    CodingWorkRuntimeOwnership,
)
from tori.coding_worker import CodingWorkerError, FakeCodingWorkerAdapter


class _ReadyEvaluator:
    def evaluate(self, *, work_states=()):  # type: ignore[no-untyped-def]
        if "reconciling" in work_states:
            return CodingWorkReadiness(
                "reconciling", "reconciliation_pending", "Reconciliation is pending."
            )
        return CodingWorkReadiness("available", "ready", "Ready.")


class _UnavailableEvaluator:
    def evaluate(self, *, work_states=()):  # type: ignore[no-untyped-def]
        return CodingWorkReadiness("unavailable", "probe_failed", "Not ready.")


class _ShutdownAdapter(FakeCodingWorkerAdapter):
    def __init__(self, on_shutdown=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.shutdown_called = False
        self.on_shutdown = on_shutdown

    def shutdown(self) -> None:
        self.shutdown_called = True
        if self.on_shutdown is not None:
            self.on_shutdown()


class _InterruptAwareAdapter(FakeCodingWorkerAdapter):
    def reconnect(self, request, binding):  # type: ignore[no-untyped-def]
        if request.prior_observed_state == "running" and binding.session_id is not None:
            self.fail(
                binding.session_id,
                code="interrupted_active_turn",
                message="The active turn was interrupted and was not replayed.",
            )
        return super().reconnect(request, binding)


class CodingWorkIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime_parent = self.root / "runtime"
        self.runtime_parent.mkdir(mode=0o700)
        self.layout = CodingWorkRuntimeInitializer(self.runtime_parent).initialize()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.settings = CodingWorkProductionSettings(
            self.layout.root,
            self.root / "opencode",
            "1.18.31",
            self.root / "bwrap",
            "http://127.0.0.1:11434/v1",
            "test-model",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _start(self, adapter=None, evaluator=_ReadyEvaluator):  # type: ignore[no-untyped-def]
        chosen = adapter or _ShutdownAdapter()
        runtime = CodingWorkRuntime.start(
            self.settings,
            adapter_factory=lambda _settings: chosen,
            readiness_factory=lambda _settings, _owner: evaluator(),
        )
        return runtime, chosen

    def test_not_configured_does_not_acquire_or_initialize(self) -> None:
        runtime = CodingWorkRuntime.start(None)
        self.assertEqual(runtime.status().availability, "not_configured")
        self.assertFalse(runtime.status().available)
        self.assertFalse(runtime.admission_open)
        runtime.shutdown()

    def test_configured_missing_runtime_is_uninitialized_without_creation(self) -> None:
        missing = CodingWorkProductionSettings(
            self.root / "missing-runtime" / "coding_work",
            self.root / "opencode",
            "1.18.31",
            self.root / "bwrap",
            "http://127.0.0.1:11434/v1",
            "test-model",
        )
        runtime = CodingWorkRuntime.start(missing)
        self.assertEqual(runtime.status().availability, "uninitialized")
        self.assertFalse(missing.runtime_root.exists())

    def test_quiescent_waiting_session_reconciles_before_admission(self) -> None:
        adapter = FakeCodingWorkerAdapter()
        store = SQLiteCodingWorkStore(self.layout.database)
        service = CodingWorkApplicationService(store, adapter)
        work = service.create_work(objective="Edit the fixture.", workspace_root=self.workspace)
        work = service.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        running = service.start(work.identifier, expected_revision=work.revision)
        self.assertEqual(running.state, "running")
        run = store.get_run(running.current_run_id)
        assert run.harness_session_id is not None
        adapter.wait(run.harness_session_id, "quiescent")
        waiting = service.observe(work.identifier)
        self.assertEqual(waiting.state, "waiting")

        runtime, _ = self._start(adapter)
        reconciled = runtime.status(work.identifier).work[0]
        self.assertTrue(runtime.admission_open)
        self.assertEqual(reconciled.state, "waiting")
        self.assertEqual(reconciled.worker_state, "waiting")
        runtime.shutdown()

    def test_interrupted_active_turn_fails_without_replay(self) -> None:
        adapter = _InterruptAwareAdapter()
        store = SQLiteCodingWorkStore(self.layout.database)
        service = CodingWorkApplicationService(store, adapter)
        work = service.create_work(objective="Edit the fixture.", workspace_root=self.workspace)
        work = service.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        running = service.start(work.identifier, expected_revision=work.revision)
        run_id = running.current_run_id
        runtime, _ = self._start(adapter)
        reconciled = SQLiteCodingWorkStore(self.layout.database).get_work(work.identifier)
        self.assertEqual(reconciled.state, "failed")
        self.assertEqual(reconciled.current_run_id, run_id)
        self.assertTrue(runtime.admission_open)
        runtime.shutdown()

    def test_preexisting_reconciling_work_is_not_stranded_on_restart(self) -> None:
        original = FakeCodingWorkerAdapter()
        store = SQLiteCodingWorkStore(self.layout.database)
        service = CodingWorkApplicationService(store, original)
        work = service.create_work(
            objective="Recover an interrupted synthetic run.",
            workspace_root=self.workspace,
        )
        work = service.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        service.start(work.identifier, expected_revision=work.revision)
        self.assertEqual(store.mark_reconciling()[0].state, "reconciling")

        runtime, _replacement = self._start(FakeCodingWorkerAdapter())

        recovered = store.get_work(work.identifier)
        self.assertEqual(recovered.state, "failed")
        self.assertEqual(store.get_run(recovered.current_run_id).connection_state, "missing")
        self.assertTrue(runtime.admission_open)
        runtime.shutdown()

    def test_preexisting_reconciling_work_with_missing_workspace_fails_truthfully(self) -> None:
        original = FakeCodingWorkerAdapter()
        store = SQLiteCodingWorkStore(self.layout.database)
        service = CodingWorkApplicationService(store, original)
        work = service.create_work(
            objective="Recover a removed synthetic workspace.",
            workspace_root=self.workspace,
        )
        work = service.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        service.start(work.identifier, expected_revision=work.revision)
        store.mark_reconciling()
        self.workspace.rmdir()

        runtime, _replacement = self._start(FakeCodingWorkerAdapter())

        recovered = store.get_work(work.identifier)
        run = store.get_run(recovered.current_run_id)
        self.assertEqual(recovered.state, "failed")
        self.assertEqual(run.connection_state, "missing")
        self.assertEqual(run.failure_code, "workspace_missing")
        self.assertIn("workspace no longer exists", run.failure_message)
        self.assertTrue(runtime.admission_open)
        runtime.shutdown()

    def test_ownership_failure_is_unavailable_and_nonmutating(self) -> None:
        first = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(first.acquire())
        try:
            runtime, adapter = self._start()
            self.assertEqual(
                runtime.status().code, "supervisor_ownership_unavailable"
            )
            self.assertFalse(runtime.admission_open)
            self.assertFalse(adapter.shutdown_called)
        finally:
            first.release()

    def test_readiness_failure_releases_ownership(self) -> None:
        runtime, _adapter = self._start(evaluator=_UnavailableEvaluator)
        self.assertEqual(runtime.status().code, "probe_failed")
        later = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(later.acquire())
        later.release()

    def test_unavailable_runtime_still_coordinates_preserved_state_backup(self) -> None:
        store = SQLiteCodingWorkStore(self.layout.database)
        work = store.create_work(
            objective="Synthetic prior work", workspace_root=str(self.workspace)
        )
        work, _ = store.authorize(
            work.identifier,
            expected_revision=work.revision,
            authority=CodingWorkAuthority(str(self.workspace), True, True, True),
            confirmation_provenance="synthetic",
        )
        store.create_run(
            work.identifier,
            expected_revision=work.revision,
            adapter_id="fake",
            adapter_version=1,
            launch_correlation_id="launch-preserved",
        )
        store.mark_reconciling()
        runtime, _adapter = self._start(evaluator=_UnavailableEvaluator)
        with runtime.backup_guard():
            self.assertEqual(store.get_work(work.identifier).state, "reconciling")
        contender = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(contender.acquire())
        contender.release()

    def test_unsafe_backup_guard_maps_safely_before_creation(self) -> None:
        for already_owned in (False, True):
            with self.subTest(already_owned=already_owned):
                runtime = CodingWorkRuntime(self.settings)
                if already_owned:
                    owner = CodingWorkRuntimeOwnership(self.layout)
                    self.assertTrue(owner.acquire())
                    runtime._ownership = owner
                bad = self.layout.opencode_root / "works/index"
                bad.write_bytes(b"synthetic snapshot"); bad.chmod(0o664)
                with TemporaryDirectory() as destination:
                    backups = Path(destination) / "backups"
                    service = BackupService(project_root=self.root, backup_root=backups,
                                            coding_work_guard=runtime.backup_guard)
                    try:
                        with patch.object(service, "_create_backup_locked") as create:
                            with self.assertRaises(BackupSafetyError) as captured:
                                service.create_backup()
                            self.assertEqual(captured.exception.code, "backup_unsafe")
                            self.assertIn("Coding Work private state is unsafe", str(captured.exception))
                            create.assert_not_called()
                        self.assertFalse(backups.exists())
                        self.assertFalse(service.in_progress)
                        self.assertEqual(bad.read_bytes(), b"synthetic snapshot")
                        self.assertEqual(bad.stat().st_mode & 0o777, 0o664)
                    finally:
                        if already_owned: owner.release()
                        bad.unlink()  # only this test's exact synthetic file

    def test_adapter_setup_failure_releases_ownership(self) -> None:
        runtime = CodingWorkRuntime.start(
            self.settings,
            adapter_factory=lambda _settings: (_ for _ in ()).throw(
                CodingWorkerError("setup failed", code="setup_failed")
            ),
            readiness_factory=lambda _settings, _owner: _ReadyEvaluator(),
        )
        self.assertEqual(runtime.status().code, "setup_failed")
        later = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(later.acquire())
        later.release()

    def test_store_open_failure_releases_ownership(self) -> None:
        runtime = CodingWorkRuntime.start(
            self.settings,
            store_factory=lambda _path: (_ for _ in ()).throw(
                CodingWorkUnavailableError("store failed")
            ),
            readiness_factory=lambda _settings, _owner: _ReadyEvaluator(),
        )
        self.assertEqual(runtime.status().code, "store_unavailable")
        later = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(later.acquire())
        later.release()

    def test_status_follow_up_cancel_and_bounded_projection(self) -> None:
        runtime, adapter = self._start()
        work = runtime.create_work(
            objective="Update one file.", workspace_root=self.workspace
        )
        work = runtime.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        work = runtime.start_work(work.identifier, expected_revision=work.revision)
        store = SQLiteCodingWorkStore(self.layout.database)
        run = store.get_run(work.current_run_id)
        assert run.harness_session_id is not None
        session_id = run.harness_session_id
        adapter.progress(session_id, "Editing the fixture.", changed_paths=("fixture.txt",))
        adapter.wait(session_id, "review")
        detail = runtime.refresh(work.identifier)
        self.assertEqual(detail.latest_activity, "review")
        self.assertEqual(detail.changed_paths, ("fixture.txt",))
        self.assertTrue(detail.can_follow_up)
        detail = runtime.follow_up(
            work.identifier,
            expected_revision=store.get_work(work.identifier).revision,
            instruction="Check it again.",
        )
        self.assertEqual(detail.state, "running")
        current = store.get_work(work.identifier)
        cancelled = runtime.cancel(work.identifier, expected_revision=current.revision)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertFalse(cancelled.can_cancel)
        prior_run_id = store.get_work(work.identifier).current_run_id
        continued = runtime.continue_work(
            work.identifier,
            expected_revision=store.get_work(work.identifier).revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test continuation",
        )
        self.assertEqual(continued.state, "running")
        self.assertNotEqual(continued.current_run_id, prior_run_id)
        runtime.shutdown()

    def test_pause_resume_are_not_faked(self) -> None:
        runtime, _adapter = self._start()
        with self.assertRaises(CodingWorkControlUnsupportedError):
            runtime.pause("coding-work-" + "0" * 32)
        with self.assertRaises(CodingWorkControlUnsupportedError):
            runtime.resume("coding-work-" + "0" * 32)
        runtime.shutdown()

    def test_status_projection_bounds_events_and_changed_paths(self) -> None:
        runtime, adapter = self._start()
        work = runtime.create_work(objective="Bound status.", workspace_root=self.workspace)
        work = runtime.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        work = runtime.start_work(work.identifier, expected_revision=work.revision)
        store = SQLiteCodingWorkStore(self.layout.database)
        run = store.get_run(work.current_run_id)
        assert run.harness_session_id is not None
        for index in range(12):
            adapter.progress(
                run.harness_session_id,
                f"Progress {index}",
                changed_paths=tuple(f"file-{item}.txt" for item in range(150)),
            )
        detail = runtime.refresh(work.identifier)
        self.assertEqual(len(detail.recent_activity), 10)
        self.assertEqual(len(detail.changed_paths), 100)
        self.assertFalse(hasattr(detail, "harness_session_id"))
        runtime.shutdown()

    def test_passive_status_reconciles_departed_worker_once(self) -> None:
        runtime, adapter = self._start()
        work = runtime.create_work(
            objective="Observe a departed worker.", workspace_root=self.workspace
        )
        work = runtime.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="test",
        )
        work = runtime.start_work(work.identifier, expected_revision=work.revision)
        store = SQLiteCodingWorkStore(self.layout.database)
        run = store.get_run(work.current_run_id)
        assert run.harness_session_id is not None
        adapter.fail(
            run.harness_session_id,
            code="synthetic_process_exit",
            message="The synthetic worker departed.",
        )

        first = runtime.status(work.identifier).work[0]
        terminal_events = tuple(
            event for event in store.events(work.identifier) if event.kind == "failed"
        )
        revision = store.revision()
        second = runtime.status(work.identifier).work[0]

        self.assertEqual(first.state, "failed")
        self.assertEqual(second.state, "failed")
        self.assertEqual(len(terminal_events), 1)
        self.assertEqual(
            tuple(event for event in store.events(work.identifier) if event.kind == "failed"),
            terminal_events,
        )
        self.assertEqual(store.revision(), revision)
        runtime.shutdown()

    def test_missing_workspace_remains_a_conflict(self) -> None:
        runtime, _adapter = self._start()
        with self.assertRaises((CodingWorkConflictError, FileNotFoundError)):
            runtime.create_work(
                objective="Create a project.", workspace_root=self.root / "missing"
            )
        runtime.shutdown()

    def test_shutdown_stops_adapter_and_releases_lock_last(self) -> None:
        ownership_seen_during_shutdown: list[bool] = []

        def inspect_lock() -> None:
            contender = CodingWorkRuntimeOwnership(self.layout)
            ownership_seen_during_shutdown.append(contender.acquire())
            contender.release()

        adapter = _ShutdownAdapter(on_shutdown=inspect_lock)
        runtime, _ = self._start(adapter)
        runtime.shutdown()
        self.assertTrue(adapter.shutdown_called)
        self.assertEqual(ownership_seen_during_shutdown, [False])
        self.assertFalse(runtime.admission_open)
        later = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(later.acquire())
        later.release()
        runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
