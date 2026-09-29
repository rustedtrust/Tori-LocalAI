from __future__ import annotations

import json
from dataclasses import replace
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

import tori.coding_work_runtime as coding_work_runtime

from tori.backups import (
    BackupBusyError,
    BackupService,
    CodingWorkBackupCoordinator,
)
from tori.coding_work import CodingWorkAuthority, SQLiteCodingWorkStore
from tori.coding_work_application import (
    CodingWorkApplicationService,
    OwnedCodingWorkApplicationService,
)
from tori.coding_worker import FakeCodingWorkerAdapter
from tori.coding_work_runtime import (
    INITIALIZER_PREFIX,
    CodingWorkOwnershipUnavailableError,
    CodingWorkProductionSettings,
    CodingWorkReadinessEvaluator,
    CodingWorkRuntimeConflictError,
    CodingWorkRuntimeInitializer,
    CodingWorkRuntimeLayout,
    CodingWorkRuntimeOwnership,
    CodingWorkRuntimeUnsafeError,
    offline_bootstrap_ready,
    offline_bootstrap_inventory,
    OFFLINE_BOOTSTRAP_PROVENANCE,
    validate_coding_work_layout,
)


class CodingWorkRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "runtime"
        self.runtime.mkdir(mode=0o700)

    def initialize(self) -> CodingWorkRuntimeLayout:
        return CodingWorkRuntimeInitializer(self.runtime).initialize()

    def settings(self, layout: CodingWorkRuntimeLayout) -> CodingWorkProductionSettings:
        executable_root = self.base / "executables"
        executable_root.mkdir(mode=0o700, exist_ok=True)
        opencode = executable_root / "opencode"
        bubblewrap = executable_root / "bwrap"
        for executable in (opencode, bubblewrap):
            if not executable.exists():
                executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
                os.chmod(executable, 0o700)
        return CodingWorkProductionSettings(
            runtime_root=layout.root,
            opencode_executable=opencode,
            opencode_version="1.18.31",
            bubblewrap_executable=bubblewrap,
            provider_upstream="http://127.0.0.1:11434/v1",
            model="qwen3.8:latest",
        )

    def test_exact_worker_version_rejects_previous_and_arbitrary_versions(self) -> None:
        settings = self.settings(CodingWorkRuntimeLayout(self.runtime))
        self.assertEqual(settings.opencode_version, "1.18.31")
        for version in ("1.18.21", "1.18.32", "latest"):
            with self.subTest(version=version), self.assertRaisesRegex(
                ValueError, "requires version 1.18.31"
            ):
                replace(settings, opencode_version=version)

    def test_initializer_publishes_exact_schema_layout_and_modes(self) -> None:
        layout = self.initialize()
        validate_coding_work_layout(layout, require_quiescent=True, require_empty=True)
        for path in (layout.root, layout.opencode_root, layout.opencode_works,
                     layout.opencode_ipc, layout.opencode_bootstrap_cache):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for path in (layout.database, layout.supervisor_lock, layout.opencode_instance):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(SQLiteCodingWorkStore(layout.database).revision(), 1)
        self.assertEqual(set(item.name for item in self.runtime.iterdir()), {"coding_work"})

    def test_initializer_refuses_existing_and_abandoned_layouts(self) -> None:
        self.initialize()
        with self.assertRaises(CodingWorkRuntimeConflictError):
            CodingWorkRuntimeInitializer(self.runtime).initialize()
        other = self.base / "other-runtime"
        other.mkdir(mode=0o700)
        (other / (INITIALIZER_PREFIX + "abandoned")).mkdir(mode=0o700)
        with self.assertRaises(CodingWorkRuntimeConflictError):
            CodingWorkRuntimeInitializer(other).initialize()

    def test_initializer_refuses_unsafe_parent_and_preserves_halfway_failure(self) -> None:
        unsafe = self.base / "unsafe"
        unsafe.mkdir(mode=0o702)
        os.chmod(unsafe, 0o702)
        with self.assertRaises(CodingWorkRuntimeUnsafeError):
            CodingWorkRuntimeInitializer(unsafe).initialize()
        initializer = CodingWorkRuntimeInitializer(
            self.runtime, token_hex=lambda length: "a" * (length * 2)
        )
        with patch.object(
            initializer, "_create_staged_layout", side_effect=OSError("synthetic")
        ), self.assertRaises(CodingWorkRuntimeUnsafeError):
            initializer.initialize()
        self.assertFalse((self.runtime / "coding_work").exists())
        self.assertEqual(
            [item.name for item in self.runtime.iterdir()],
            [INITIALIZER_PREFIX + "a" * 32],
        )

    def test_publication_is_no_replace_under_a_destination_race(self) -> None:
        original = coding_work_runtime._rename_no_replace

        def race(parent: int, source: str, destination: str) -> None:
            os.mkdir(destination, 0o700, dir_fd=parent)
            original(parent, source, destination)

        with patch.object(coding_work_runtime, "_rename_no_replace", side_effect=race):
            with self.assertRaises(CodingWorkRuntimeUnsafeError):
                CodingWorkRuntimeInitializer(self.runtime).initialize()
        self.assertEqual(tuple((self.runtime / "coding_work").iterdir()), ())
        self.assertTrue(any(
            item.name.startswith(INITIALIZER_PREFIX) for item in self.runtime.iterdir()
        ))

    def test_reopen_rejects_unsafe_mode_without_repair(self) -> None:
        layout = self.initialize()
        os.chmod(layout.supervisor_lock, 0o644)
        with self.assertRaises(CodingWorkRuntimeUnsafeError):
            validate_coding_work_layout(layout, require_quiescent=True)
        self.assertEqual(stat.S_IMODE(layout.supervisor_lock.stat().st_mode), 0o644)

    def test_kernel_ownership_is_exclusive_and_pid_contents_are_irrelevant(self) -> None:
        layout = self.initialize()
        layout.supervisor_lock.write_text("999999\n", encoding="ascii")
        os.chmod(layout.supervisor_lock, 0o600)
        first = CodingWorkRuntimeOwnership(layout)
        second = CodingWorkRuntimeOwnership(layout)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_shutdown_releases_workers_and_transport_before_kernel_lock(self) -> None:
        layout = self.initialize()
        owner = CodingWorkRuntimeOwnership(layout)
        competitor = CodingWorkRuntimeOwnership(layout)
        owner.acquire()
        order: list[str] = []

        def stop_workers() -> None:
            self.assertTrue(owner.owned)
            self.assertFalse(competitor.acquire())
            order.append("workers")

        def release_transport() -> None:
            self.assertTrue(owner.owned)
            order.append("transport")

        owner.shutdown(
            stop_owned_workers=stop_workers,
            release_provider_transport=release_transport,
        )
        self.assertEqual(order, ["workers", "transport"])
        self.assertTrue(competitor.acquire())
        competitor.release()

    def test_backup_maintenance_fails_fast_during_an_application_operation(self) -> None:
        layout = self.initialize()
        owner = CodingWorkRuntimeOwnership(layout)
        owner.acquire()
        self.addCleanup(owner.release)
        entered = threading.Event()
        release = threading.Event()

        def hold_operation() -> None:
            with owner.operation():
                entered.set()
                release.wait(2)

        thread = threading.Thread(target=hold_operation)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.assertTrue(entered.wait(1))
        coordinator = CodingWorkBackupCoordinator(
            layout=layout, ownership=owner,
            store=SQLiteCodingWorkStore(layout.database),
            live_opencode_writer=lambda: False,
        )
        try:
            with self.assertRaises(BackupBusyError):
                with coordinator.snapshot_guard():
                    self.fail("maintenance should not start")
        finally:
            release.set()
            thread.join(2)

    def test_unowned_operation_cannot_mutate(self) -> None:
        layout = self.initialize()
        owner = CodingWorkRuntimeOwnership(layout)
        with self.assertRaises(CodingWorkOwnershipUnavailableError):
            with owner.operation():
                self.fail("operation should not start")
        service = OwnedCodingWorkApplicationService(
            CodingWorkApplicationService(
                SQLiteCodingWorkStore(layout.database), FakeCodingWorkerAdapter()
            ),
            owner,
        )
        workspace = self.base / "owned-workspace"
        workspace.mkdir()
        with self.assertRaises(CodingWorkOwnershipUnavailableError):
            service.create_work(objective="x", workspace_root=workspace)
        self.assertEqual(SQLiteCodingWorkStore(layout.database).list_work(), ())
        owner.acquire()
        self.addCleanup(owner.release)
        created = service.create_work(objective="x", workspace_root=workspace)
        self.assertEqual(created.objective, "x")

    def test_readiness_has_no_fallback_and_requires_offline_receipt(self) -> None:
        layout = self.initialize()
        owner = CodingWorkRuntimeOwnership(layout)
        self.assertTrue(owner.acquire())
        self.addCleanup(owner.release)
        settings = self.settings(layout)
        evaluator = CodingWorkReadinessEvaluator(
            settings,
            ownership=owner,
            provider_model_available=lambda _settings: True,
            opencode_version_probe=lambda _settings: True,
            bubblewrap_probe=lambda _settings: True,
        )
        self.assertEqual(evaluator.evaluate().code, "offline_bootstrap_missing")
        payload = {
            "schema": 1, "opencode_version": "1.18.31",
            "provider_package": "@ai-sdk/openai-compatible",
            "status": "prepared_offline",
        }
        package = layout.opencode_bootstrap_cache / "provider.package"
        package.write_bytes(b"synthetic offline package material")
        os.chmod(package, 0o600)
        prepared = layout.opencode_bootstrap_cache / "prepared"
        prepared.mkdir(mode=0o700)
        for name in ("data", "cache", "state"):
            (prepared / name).mkdir(mode=0o700)
        package.rename(prepared / "cache/provider.package")
        digest, count, total = offline_bootstrap_inventory(prepared)
        payload.update(
            cache_digest=digest, cache_file_count=count,
            cache_total_bytes=total,
            prepared_at_utc="2026-08-24T12:00:00Z",
            provenance=OFFLINE_BOOTSTRAP_PROVENANCE,
        )
        layout.bootstrap_manifest.write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
        os.chmod(layout.bootstrap_manifest, 0o600)
        self.assertTrue(offline_bootstrap_ready(layout, settings))
        self.assertEqual(evaluator.evaluate().state, "available")
        self.assertEqual(evaluator.evaluate(work_states=("reconciling",)).state, "reconciling")

    def test_readiness_reports_each_missing_prerequisite(self) -> None:
        layout = CodingWorkRuntimeLayout(self.runtime)
        self.assertEqual(CodingWorkReadinessEvaluator(None).evaluate().code, "configuration_missing")
        settings = self.settings(layout)
        self.assertEqual(CodingWorkReadinessEvaluator(settings).evaluate().state, "uninitialized")
        self.initialize()
        owner = CodingWorkRuntimeOwnership(layout)
        self.assertEqual(CodingWorkReadinessEvaluator(settings, ownership=owner).evaluate().code,
                         "supervisor_ownership_unavailable")
        owner.acquire()
        self.addCleanup(owner.release)
        settings.opencode_executable.unlink()
        self.assertEqual(CodingWorkReadinessEvaluator(
            settings, ownership=owner
        ).evaluate().code, "opencode_missing")
        settings = self.settings(layout)
        self.assertEqual(CodingWorkReadinessEvaluator(
            settings, ownership=owner, opencode_version_probe=lambda _s: False
        ).evaluate().code, "opencode_wrong_version")
        settings.bubblewrap_executable.unlink()
        self.assertEqual(CodingWorkReadinessEvaluator(
            settings, ownership=owner, opencode_version_probe=lambda _s: True
        ).evaluate().code, "bubblewrap_missing")
        settings = self.settings(layout)
        self.assertEqual(CodingWorkReadinessEvaluator(
            settings, ownership=owner, opencode_version_probe=lambda _s: True,
            bubblewrap_probe=lambda _s: False
        ).evaluate().code, "bubblewrap_unavailable")
        self.assertEqual(CodingWorkReadinessEvaluator(
            settings, ownership=owner, opencode_version_probe=lambda _s: True,
            bubblewrap_probe=lambda _s: True
        ).evaluate().code, "provider_model_unavailable")

    def _backup_project(self) -> tuple[Path, Path, CodingWorkRuntimeLayout]:
        project = self.base / "Tori"
        (project / ".git/refs/heads").mkdir(parents=True)
        (project / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        (project / ".git/refs/heads/main").write_text("a" * 40 + "\n", encoding="ascii")
        runtime = project / "runtime"
        runtime.mkdir(mode=0o700)
        return project, self.base / "backups", CodingWorkRuntimeInitializer(runtime).initialize()

    def test_coordinated_backup_snapshots_database_and_private_state_together(self) -> None:
        project, destination, layout = self._backup_project()
        private = layout.opencode_works / "work-a"
        private.mkdir(mode=0o700)
        (private / "session.db").write_bytes(b"durable synthetic session")
        os.chmod(private / "session.db", 0o600)
        owner = CodingWorkRuntimeOwnership(layout)
        owner.acquire()
        self.addCleanup(owner.release)
        coordinator = CodingWorkBackupCoordinator(
            layout=layout, ownership=owner,
            store=SQLiteCodingWorkStore(layout.database),
            live_opencode_writer=lambda: False,
        )
        result = BackupService(
            project_root=project, backup_root=destination,
            coding_work_guard=coordinator.snapshot_guard,
            token_hex=lambda _length: "0123456789abcdef",
        ).create_backup()
        payload = Path(result.directory) / "project/runtime/coding_work"
        self.assertTrue((payload / "tori_coding_work.db").is_file())
        self.assertEqual(
            (payload / "opencode/works/work-a/session.db").read_bytes(),
            b"durable synthetic session",
        )

    def test_backup_refuses_active_work_live_writer_and_provider_socket(self) -> None:
        project, destination, layout = self._backup_project()
        store = SQLiteCodingWorkStore(layout.database)
        workspace = self.base / "workspace"
        workspace.mkdir()
        work = store.create_work(objective="x", workspace_root=str(workspace))
        work, _ = store.authorize(
            work.identifier, expected_revision=work.revision,
            authority=CodingWorkAuthority(str(workspace), True, True, True),
            confirmation_provenance="synthetic",
        )
        store.create_run(
            work.identifier, expected_revision=work.revision,
            adapter_id="fake", adapter_version=1,
            launch_correlation_id="launch-synthetic",
        )
        owner = CodingWorkRuntimeOwnership(layout)
        owner.acquire()
        self.addCleanup(owner.release)
        coordinator = CodingWorkBackupCoordinator(
            layout=layout, ownership=owner, store=store,
            live_opencode_writer=lambda: False,
        )
        service = BackupService(
            project_root=project, backup_root=destination,
            coding_work_guard=coordinator.snapshot_guard,
        )
        with self.assertRaises(BackupBusyError):
            service.create_backup()

        empty_project, empty_destination, empty_layout = self._backup_project_for_suffix("empty")
        empty_owner = CodingWorkRuntimeOwnership(empty_layout)
        empty_owner.acquire()
        self.addCleanup(empty_owner.release)
        live = CodingWorkBackupCoordinator(
            layout=empty_layout, ownership=empty_owner,
            store=SQLiteCodingWorkStore(empty_layout.database),
            live_opencode_writer=lambda: True,
        )
        with self.assertRaises(BackupBusyError):
            BackupService(project_root=empty_project, backup_root=empty_destination,
                          coding_work_guard=live.snapshot_guard).create_backup()
        probe = socket.socket(socket.AF_UNIX)
        probe.bind(str(empty_layout.provider_socket))
        self.addCleanup(probe.close)
        socket_guard = CodingWorkBackupCoordinator(
            layout=empty_layout, ownership=empty_owner,
            store=SQLiteCodingWorkStore(empty_layout.database),
            live_opencode_writer=lambda: False,
        )
        with self.assertRaises(BackupBusyError):
            BackupService(project_root=empty_project, backup_root=empty_destination,
                          coding_work_guard=socket_guard.snapshot_guard).create_backup()

    def test_backup_allows_dormant_reconciling_state_under_exclusive_guard(self) -> None:
        project, destination, layout = self._backup_project_for_suffix("dormant")
        store = SQLiteCodingWorkStore(layout.database)
        workspace = self.base / "dormant-workspace"
        workspace.mkdir()
        work = store.create_work(objective="Synthetic prior work", workspace_root=str(workspace))
        work, _ = store.authorize(
            work.identifier,
            expected_revision=work.revision,
            authority=CodingWorkAuthority(str(workspace), True, True, True),
            confirmation_provenance="synthetic",
        )
        store.create_run(
            work.identifier,
            expected_revision=work.revision,
            adapter_id="fake",
            adapter_version=1,
            launch_correlation_id="launch-dormant",
        )
        self.assertEqual(store.mark_reconciling()[0].state, "reconciling")
        owner = CodingWorkRuntimeOwnership(layout)
        owner.acquire()
        self.addCleanup(owner.release)
        coordinator = CodingWorkBackupCoordinator(
            layout=layout,
            ownership=owner,
            store=store,
            live_opencode_writer=lambda: False,
        )

        result = BackupService(
            project_root=project,
            backup_root=destination,
            coding_work_guard=coordinator.snapshot_guard,
        ).create_backup()

        self.assertEqual(result.verification, "verified")
        self.assertEqual(store.get_work(work.identifier).state, "reconciling")

    def _backup_project_for_suffix(self, suffix: str) -> tuple[Path, Path, CodingWorkRuntimeLayout]:
        project = self.base / ("Tori-" + suffix)
        (project / ".git/refs/heads").mkdir(parents=True)
        (project / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        (project / ".git/refs/heads/main").write_text("a" * 40 + "\n", encoding="ascii")
        runtime = project / "runtime"
        runtime.mkdir(mode=0o700)
        return project, self.base / ("backups-" + suffix), CodingWorkRuntimeInitializer(runtime).initialize()


if __name__ == "__main__":
    unittest.main()
