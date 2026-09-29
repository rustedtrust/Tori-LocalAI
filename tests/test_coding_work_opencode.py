from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import stat
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
import threading
from unittest.mock import patch
from tori.coding_work_private_state import SnapshotImport

from tori.coding_work import CodingWorkAuthority, CodingWorkDirective, SQLiteCodingWorkStore
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_work_opencode import (
    ACPJSONRPCClient,
    OpenCodeAdapterError,
    OpenCodeAdapterSettings,
    OpenCodeCodingWorkerAdapter,
    _OpenCodeSandbox,
    _OpenCodeSandboxResources,
    _configuration,
    _evidence_document,
    _initial_prompt,
    _workspace_snapshot,
    _ensure_private_directory,
    _seed_offline_bootstrap_state,
)
from tori.coding_work_runtime import CodingWorkRuntimeUnsafeError, _validate_private_tree
from tori.coding_work_provider_transport import OpenAICompatibleInferencePolicy
from tori.coding_work_supervisor import (
    BubblewrapCodingWorkSandbox,
    CodingWorkProcessSupervisor,
    CodingWorkProcessSandbox,
    CodingWorkSandboxAvailability,
    CodingWorkSandboxPlan,
)
from tori.coding_worker import (
    CodingWorkerBinding,
    CodingWorkerError,
    CodingWorkerReconnectRequest,
    CodingWorkerStartRequest,
)


FIXTURE = Path(__file__).parent / "fixtures/opencode_acp_fixture.py"


class _DirectSandbox(CodingWorkProcessSandbox):
    def availability(self, authority: CodingWorkAuthority) -> CodingWorkSandboxAvailability:
        return CodingWorkSandboxAvailability(True, "test", "test-only direct process")

    def plan(self, worker_argv, authority):  # type: ignore[no-untyped-def]
        return CodingWorkSandboxPlan(
            tuple(worker_argv),
            {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent"},
            authority.workspace_root,
            "read_write" if authority.modify_allowed else "read_only",
            "test_only",
            "test_only",
            "test-only direct process; no isolation claim",
        )


class OpenCodeCodingWorkerAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="tori-opencode-adapter-test-")
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "input.txt").write_text("before\n", encoding="utf-8")
        self.private = self.root / "private"
        self.adapters: list[OpenCodeCodingWorkerAdapter] = []

    def tearDown(self) -> None:
        for adapter in reversed(self.adapters):
            adapter.shutdown()
        self.temporary.cleanup()

    def adapter(self) -> OpenCodeCodingWorkerAdapter:
        adapter = OpenCodeCodingWorkerAdapter(
            OpenCodeAdapterSettings(
                Path("/not-used-in-fixture"),
                self.private,
                OpenAICompatibleInferencePolicy("127.0.0.1", 11434, "qwen3.8:latest"),
                control_timeout_seconds=2,
                model_turn_timeout_seconds=3,
            ),
            process_sandbox=_DirectSandbox(),
            worker_command=lambda request: (
                sys.executable, "-u", str(FIXTURE), str(self.fixture_state(request.work_id))
            ),
        )
        self.adapters.append(adapter)
        return adapter

    def fixture_state(self, work_id: str) -> Path:
        return self.private / "works" / work_id / "state/fixture-sessions.json"

    def request(
        self,
        objective: str = "Make the synthetic edit.",
        *,
        work_digit: str = "1",
        run_digit: str = "2",
        launch_digit: str = "3",
        workspace: Path | None = None,
    ) -> CodingWorkerStartRequest:
        return CodingWorkerStartRequest(
            "coding-work-" + work_digit * 32,
            "coding-run-" + run_digit * 32,
            objective,
            "adapter-output.txt exists",
            CodingWorkAuthority(str(workspace or self.workspace), True, True, True),
            "launch-" + launch_digit * 32,
        )

    def wait_for_event(
        self,
        adapter: OpenCodeCodingWorkerAdapter,
        binding: CodingWorkerBinding,
        kinds: set[str],
    ) -> tuple[object, ...]:
        deadline = time.monotonic() + 5
        events = ()
        while time.monotonic() < deadline:
            events = adapter.attach(binding, after_sequence=0)
            if any(event.kind in kinds for event in events):
                return events
            time.sleep(0.02)
        self.fail("OpenCode fixture did not emit the expected event")

    def directive(
        self,
        request: CodingWorkerStartRequest,
        *,
        kind: str = "instruction",
        instruction: str = "Update the synthetic output again.",
    ) -> CodingWorkDirective:
        return CodingWorkDirective(
            identifier="coding-directive-" + "4" * 32,
            work_id=request.work_id,
            run_id=request.run_id,
            authorization_id="coding-auth-" + "5" * 32,
            kind=kind,
            instruction=instruction if kind == "instruction" else None,
            source_chat_id=None,
            status="pending",
            delivery_receipt=None,
            failure_code=None,
            revision=1,
            created_at_utc="2000-01-01T00:00:00Z",
            updated_at_utc="2000-01-01T00:00:00Z",
            delivered_at_utc=None,
        )

    def test_new_session_initial_prompt_and_filtered_bounded_evidence(self) -> None:
        adapter = self.adapter()
        request = self.request()
        binding = adapter.start(request)
        self.assertRegex(binding.session_id or "", r"^ses_")
        self.assertEqual(
            self.private.joinpath(
                "works", request.work_id, "runs", request.run_id,
                "config/opencode/.gitignore"
            ).read_bytes(),
            b"node_modules\npackage.json\npackage-lock.json\nbun.lock\n.gitignore",
        )
        for path in self.private.rglob("*"):
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o700 if path.is_dir() else 0o600)
        events = self.wait_for_event(adapter, binding, {"completed"})
        kinds = [event.kind for event in events]
        self.assertIn("session_confirmed", kinds)
        self.assertIn("progress", kinds)
        self.assertIn("verification", kinds)
        self.assertEqual(kinds[-1], "completed")
        self.assertNotIn("waiting", kinds)
        self.assertFalse(adapter.has_live_writer())
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))
        _validate_private_tree(self.private, require_quiescent=True)
        encoded = json.dumps([event.payload for event in events])
        self.assertNotIn("private reasoning", encoded)
        self.assertNotIn("usage_update", encoded)
        self.assertNotIn("available_commands_update", encoded)
        progress = [event for event in events if event.kind == "progress"][-1]
        self.assertEqual(progress.payload["changed_paths"], ["adapter-output.txt"])
        self.assertEqual(progress.payload["verification"], "workspace_snapshot_observed")

    def test_initial_prompt_mediates_exact_host_workspace_to_sandbox_root(self) -> None:
        adapter = self.adapter()
        request = self.request(
            f'Tori, in {self.workspace}, change acceptance.txt from "before" to '
            '"after". Do not change anything else.'
        )

        binding = adapter.start(request)
        self.wait_for_event(adapter, binding, {"completed"})
        state = json.loads(
            self.fixture_state(request.work_id).read_text(encoding="utf-8")
        )
        prompt = state["sessions"][binding.session_id]["prompts"][0]

        self.assertNotIn(str(self.workspace), prompt)
        self.assertIn("in /workspace, change acceptance.txt", prompt)
        self.assertIn("Use /workspace for every workspace file operation", prompt)
        self.assertIn("identity metadata only", prompt)
        self.assertEqual(request.authority.workspace_root, str(self.workspace))
        self.assertIn(str(self.workspace), request.objective)

    def test_initial_prompt_mediates_host_paths_in_acceptance_criteria(self) -> None:
        request = CodingWorkerStartRequest(
            "coding-work-" + "6" * 32,
            "coding-run-" + "7" * 32,
            f"Update {self.workspace}/input.txt.",
            f"Verify {self.workspace}/input.txt and not /tmp/unrelated.txt.",
            CodingWorkAuthority(str(self.workspace), True, True, True),
            "launch-" + "8" * 32,
        )

        prompt = _initial_prompt(request)

        self.assertNotIn(str(self.workspace), prompt)
        self.assertIn("Update /workspace/input.txt.", prompt)
        self.assertIn("Verify /workspace/input.txt", prompt)
        self.assertIn("/tmp/unrelated.txt", prompt)

    def test_follow_up_directive_uses_sandbox_workspace_path(self) -> None:
        adapter = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        binding = adapter.start(request)
        self.wait_for_event(adapter, binding, {"waiting"})

        adapter.submit_directive(
            binding,
            self.directive(
                request,
                instruction=f"Update {self.workspace}/input.txt again.",
            ),
        )
        state = json.loads(
            self.fixture_state(request.work_id).read_text(encoding="utf-8")
        )
        prompt = state["sessions"][binding.session_id]["prompts"][-1]

        self.assertNotIn(str(self.workspace), prompt)
        self.assertIn("Update /workspace/input.txt again.", prompt)

    def test_session_reload_follow_up_and_duplicate_receipt(self) -> None:
        first = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        binding = first.start(request)
        self.wait_for_event(first, binding, {"waiting"})
        last_sequence = max(
            event.sequence for event in first.attach(binding, after_sequence=0)
        )
        session_id = binding.session_id
        first.shutdown()

        second = self.adapter()
        observation = second.reconnect(
            CodingWorkerReconnectRequest(
                request.work_id,
                request.run_id,
                request.objective,
                request.acceptance_criteria,
                request.authority,
                last_sequence,
                "waiting",
            ),
            binding,
        )
        self.assertTrue(observation.found)
        self.assertEqual(observation.session_id, session_id)
        self.assertEqual(observation.state, "waiting")
        directive = self.directive(request)
        receipt = second.submit_directive(binding, directive)
        self.assertFalse(receipt.duplicate)
        follow_up_events = second.attach(binding, after_sequence=last_sequence)
        self.assertTrue(follow_up_events)
        self.assertTrue(all(event.sequence > last_sequence for event in follow_up_events))
        self.wait_for_event(second, binding, {"completed"})
        duplicate = second.submit_directive(binding, directive)
        self.assertTrue(duplicate.duplicate)
        state = json.loads(self.fixture_state(request.work_id).read_text(encoding="utf-8"))
        prompts = state["sessions"][session_id]["prompts"]
        self.assertEqual(sum(directive.identifier in item for item in prompts), 1)

    def test_private_session_state_is_isolated_per_coding_work(self) -> None:
        first = self.adapter()
        work_a = self.request("BROADER_AUTHORITY")
        binding_a = first.start(work_a)
        self.wait_for_event(first, binding_a, {"waiting"})
        session_a = binding_a.session_id
        first.shutdown()

        workspace_b = self.root / "workspace-b"
        workspace_b.mkdir()
        second = self.adapter()
        work_b1 = self.request(
            work_digit="6", run_digit="7", launch_digit="8", workspace=workspace_b
        )
        binding_b1 = second.start(work_b1)
        self.wait_for_event(second, binding_b1, {"completed"})
        second.close(binding_b1)
        work_b2 = self.request(
            work_digit="6", run_digit="9", launch_digit="a", workspace=workspace_b
        )
        binding_b2 = second.start(work_b2)
        self.wait_for_event(second, binding_b2, {"completed"})
        session_b2 = binding_b2.session_id
        self.assertNotEqual(session_a, session_b2)
        second.shutdown()

        third = self.adapter()
        foreign = CodingWorkerBinding(
            third.identifier,
            third.contract_version,
            work_a.launch_correlation_id,
            session_b2,
        )
        missing = third.reconnect(
            CodingWorkerReconnectRequest(
                work_a.work_id, work_a.run_id, work_a.objective,
                work_a.acceptance_criteria, work_a.authority, 0, "waiting",
            ),
            foreign,
        )
        self.assertFalse(missing.found)
        restored = third.reconnect(
            CodingWorkerReconnectRequest(
                work_a.work_id, work_a.run_id, work_a.objective,
                work_a.acceptance_criteria, work_a.authority, 0, "waiting",
            ),
            binding_a,
        )
        self.assertTrue(restored.found)
        self.assertEqual(restored.session_id, session_a)
        self.assertTrue(self.fixture_state(work_a.work_id).is_file())
        self.assertTrue(self.fixture_state(work_b1.work_id).is_file())

    def test_offline_bootstrap_cache_is_copied_into_each_isolated_work(self) -> None:
        bootstrap = self.private / "bootstrap-cache/prepared"
        bootstrap.mkdir(parents=True, mode=0o700)
        os.chmod(self.private, 0o700)
        os.chmod(self.private / "bootstrap-cache", 0o700)
        for name in ("data", "cache", "state"):
            (bootstrap / name).mkdir(mode=0o700)
        package = bootstrap / "cache/provider.package"
        package.write_bytes(b"prepared")
        os.chmod(package, 0o600)
        adapter = self.adapter()
        first = self.request(work_digit="a", run_digit="b", launch_digit="c")
        second_workspace = self.root / "workspace-two"
        second_workspace.mkdir()
        second = self.request(
            work_digit="d", run_digit="e", launch_digit="f",
            workspace=second_workspace,
        )
        adapter.start(first)
        first_cache = self.private / "works" / first.work_id / "state/cache/provider.package"
        self.assertEqual(first_cache.read_bytes(), b"prepared")
        first_cache.write_bytes(b"changed by first work")
        adapter.start(second)
        second_cache = self.private / "works" / second.work_id / "state/cache/provider.package"
        self.assertEqual(second_cache.read_bytes(), b"prepared")
        self.assertEqual(package.read_bytes(), b"prepared")

    def test_git_shaped_bootstrap_copy_is_private_without_changing_source(self) -> None:
        source = _ensure_private_directory(self.private / "bootstrap-cache/prepared")
        state = _ensure_private_directory(self.private / "works/synthetic/state")
        for name in ("data", "cache", "state"):
            _ensure_private_directory(source / name)
            _ensure_private_directory(state / name)
        relative = Path("data/opencode/snapshot") / ("a" * 40) / ("b" * 40)
        snapshot = _ensure_private_directory(source / relative)
        hooks = _ensure_private_directory(snapshot / "hooks")
        names = (
            "applypatch-msg", "commit-msg", "fsmonitor-watchman", "post-update",
            "pre-applypatch", "pre-commit", "pre-merge-commit", "pre-push",
            "pre-rebase", "pre-receive", "prepare-commit-msg", "push-to-checkout",
            "sendemail-validate", "update",
        )
        for name in names:
            hook = hooks / (name + ".sample")
            hook.write_bytes(b"synthetic unused hook\n")
            hook.chmod(0o700)
        index = snapshot / "index"
        index.write_bytes(b"synthetic index\n")
        index.chmod(0o600)
        before = {p.relative_to(source): (p.read_bytes(), p.stat().st_mode)
                  for p in source.rglob("*") if p.is_file()}
        _seed_offline_bootstrap_state(source, state)
        for relative_file, (content, original_mode) in before.items():
            self.assertEqual((source / relative_file).stat().st_mode, original_mode)
            self.assertEqual((source / relative_file).read_bytes(), content)
            copied = state / relative_file
            self.assertEqual(copied.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
            self.assertEqual(copied.stat().st_nlink, 1)
        _validate_private_tree(state, require_quiescent=True)
        # Rerunning preparation must not rewrite existing per-work state.
        copied_index = state / relative / "index"
        copied_index.write_bytes(b"changed only in synthetic work")
        _seed_offline_bootstrap_state(source, state)
        self.assertEqual(copied_index.read_bytes(), b"changed only in synthetic work")

    def test_bootstrap_copy_still_rejects_broad_permissions_and_links(self) -> None:
        for kind in ("broad", "symlink", "hardlink"):
            with self.subTest(kind=kind):
                source = _ensure_private_directory(self.root / kind / "prepared/data")
                state = _ensure_private_directory(self.root / kind / "destination")
                for name in ("data", "cache", "state"):
                    _ensure_private_directory(state / name)
                external = self.root / (kind + "-outside")
                external.write_bytes(b"must not change")
                external.chmod(0o700)
                bad = source / "bad"
                if kind == "symlink":
                    bad.symlink_to(external)
                elif kind == "hardlink":
                    os.link(external, bad)
                else:
                    bad.write_bytes(b"not private")
                    bad.chmod(0o664)
                with self.assertRaises(OpenCodeAdapterError):
                    _seed_offline_bootstrap_state(source.parent, state)
                self.assertEqual(external.read_bytes(), b"must not change")
                self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o700)
                self.assertFalse((state / "data/bad").exists())

    @unittest.skipUnless(shutil.which("git"), "Git is needed for permission lifecycle reproduction")
    def test_git_snapshot_creation_requires_stopped_import_boundary(self) -> None:
        # Reproduce Git's native modes before passing the quiescent generated
        # tree through the same one-use import boundary used by the adapter.
        (self.workspace / "synthetic.txt").write_text("synthetic content\n")
        for mask, expected_index in ((0o077, 0o600), (0o002, 0o664)):
            import_root = _ensure_private_directory(
                self.root / str(mask) / "state/data/opencode/snapshot"
            )
            scope = SnapshotImport(import_root)
            self.addCleanup(scope.close)
            snapshot = import_root / "repository"
            environment = {
                "PATH": "/usr/bin:/bin", "HOME": str(self.root),
                "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            }
            for command in (("init",), ("add", "synthetic.txt")):
                subprocess.run(
                    (shutil.which("git"), "--git-dir", str(snapshot),
                     "--work-tree", str(self.workspace), *command),
                    cwd=self.workspace, env=environment, umask=mask,
                    check=True, capture_output=True, timeout=10,
                )
            self.assertEqual(stat.S_IMODE((snapshot / "index").stat().st_mode), expected_index)
            with self.assertRaises(CodingWorkRuntimeUnsafeError):
                _validate_private_tree(snapshot, require_quiescent=True)
            if mask == 0o077:
                hooks = list((snapshot / "hooks").glob("*.sample"))
                self.assertTrue(hooks)
                self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o700 for p in hooks))
                objects = [p for p in (snapshot / "objects").rglob("*") if p.is_file()]
                self.assertTrue(objects)
                self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o400 for p in objects))
                before = {p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()}
                scope.finish()
                _validate_private_tree(import_root, require_quiescent=True)
                self.assertEqual(before, {p.relative_to(snapshot): p.read_bytes() for p in snapshot.rglob("*") if p.is_file()})
            else:
                # Broad directories are not legitimized by the import layer.
                with self.assertRaises(CodingWorkerError): scope.finish()

    def test_owned_close_finalizes_snapshot_but_never_workspace_files(self) -> None:
        adapter = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        binding = adapter.start(request)
        self.wait_for_event(adapter, binding, {"waiting"})
        snapshot = self.private / "works" / request.work_id / "state/data/opencode/snapshot"
        files = []
        for name, mode in (("index", 0o664), ("hook.sample", 0o700), ("object", 0o400)):
            path = snapshot / name
            path.write_bytes(b"synthetic unchanged bytes"); path.chmod(mode)
            files.append(path)
        outside = self.workspace / "executable"
        outside.write_bytes(b"synthetic workspace executable"); outside.chmod(0o755)
        adapter.close(binding)
        self.assertFalse(adapter.has_live_writer())
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))
        _validate_private_tree(snapshot, require_quiescent=True)
        self.assertTrue(all(p.read_bytes() == b"synthetic unchanged bytes" for p in files))
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)

    def test_completed_is_published_only_after_snapshot_import_finishes(self) -> None:
        adapter = self.adapter(); request = self.request()
        entered = threading.Event(); release = threading.Event()
        original = SnapshotImport.finish
        def delayed(scope):
            entered.set()
            if not release.wait(5): raise AssertionError("test did not release import")
            original(scope)
        with patch.object(SnapshotImport, "finish", delayed):
            binding = adapter.start(request)
            try:
                self.assertTrue(entered.wait(4))
                self.assertTrue(adapter.has_live_writer())
                self.assertNotIn(
                    "completed",
                    {event.kind for event in adapter.attach(binding, after_sequence=0)},
                )
            finally:
                release.set()
        events = self.wait_for_event(adapter, binding, {"completed"})
        self.assertEqual(events[-1].kind, "completed")
        self.assertFalse(adapter.has_live_writer())
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))

    def test_completed_is_not_published_before_provider_relay_cleanup(self) -> None:
        adapter = self.adapter()
        request = self.request()
        entered = threading.Event()
        release = threading.Event()
        original = adapter._relay.close

        def delayed_close() -> None:
            entered.set()
            if not release.wait(5):
                raise AssertionError("test did not release provider cleanup")
            original()

        with patch.object(adapter._relay, "close", delayed_close):
            binding = adapter.start(request)
            try:
                self.assertTrue(entered.wait(4))
                self.assertTrue(os.path.lexists(self.private / "ipc/provider.sock"))
                self.assertNotIn(
                    "completed",
                    {event.kind for event in adapter.attach(binding, after_sequence=0)},
                )
            finally:
                release.set()
        events = self.wait_for_event(adapter, binding, {"completed"})
        self.assertEqual(events[-1].kind, "completed")
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))

    def test_adapter_startup_recovers_only_owned_stale_provider_socket(self) -> None:
        first = self.adapter()
        binding = first.start(self.request())
        self.wait_for_event(first, binding, {"completed"})
        path = self.private / "ipc/provider.sock"
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        path.chmod(0o600)

        second = self.adapter()

        self.assertFalse(os.path.lexists(path))
        self.assertFalse(second.has_live_writer())

    def test_shared_relay_remains_until_the_last_concurrent_work_is_quiescent(self) -> None:
        adapter = self.adapter()
        waiting_request = self.request("BROADER_AUTHORITY")
        waiting_binding = adapter.start(waiting_request)
        self.wait_for_event(adapter, waiting_binding, {"waiting"})
        waiting_internal = adapter._internal_binding(waiting_binding)
        second_workspace = self.root / "second-workspace"
        second_workspace.mkdir()
        completed_request = self.request(
            work_digit="6",
            run_digit="7",
            launch_digit="8",
            workspace=second_workspace,
        )
        completed_binding = adapter.start(completed_request)
        self.wait_for_event(adapter, completed_binding, {"completed"})
        self.assertTrue(os.path.lexists(self.private / "ipc/provider.sock"))

        CodingWorkProcessSupervisor.cancel(
            adapter,
            waiting_internal,
            self.directive(waiting_request, kind="cancel"),
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            events = CodingWorkProcessSupervisor.attach(
                adapter, waiting_internal, after_sequence=0
            )
            if any(event.kind == "cancelled" for event in events):
                break
            time.sleep(0.01)
        else:
            self.fail("the retained concurrent work was not cancelled")
        deadline = time.monotonic() + 3
        while (
            os.path.lexists(self.private / "ipc/provider.sock")
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))

    def test_failed_snapshot_import_never_publishes_terminal_success(self) -> None:
        adapter = self.adapter(); request = self.request()
        with patch.object(
            SnapshotImport,
            "finish",
            side_effect=CodingWorkerError(
                "Synthetic unsafe private state.", code="private_state_import_unsafe"
            ),
        ):
            binding = adapter.start(request)
            events = self.wait_for_event(adapter, binding, {"failed"})
        self.assertEqual(events[-1].kind, "failed")
        self.assertEqual(events[-1].payload["failure_code"], "private_state_import_unsafe")
        self.assertNotIn("completed", {event.kind for event in events})
        self.assertTrue(adapter.has_live_writer())
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))

    def test_unsafe_worker_output_stays_failed_and_blocks_backup(self) -> None:
        adapter = self.adapter(); request = self.request("BROADER_AUTHORITY")
        binding = adapter.start(request)
        self.wait_for_event(adapter, binding, {"waiting"})
        snapshot = self.private / "works" / request.work_id / "state/data/opencode/snapshot"
        outside = self.workspace / "protected"
        outside.write_bytes(b"untouched"); outside.chmod(0o755)
        (snapshot / "bad-link").symlink_to(outside)
        adapter.close(binding)
        self.assertTrue(adapter.has_live_writer())
        self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
        self.assertTrue(any(s.finalization_failed for s in adapter._sessions.values()))

    def test_restart_during_active_turn_fails_without_replay_or_false_waiting(self) -> None:
        first = self.adapter()
        request = self.request("SLEEP_UNTIL_CANCELLED")
        binding = first.start(request)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = json.loads(
                self.fixture_state(request.work_id).read_text(encoding="utf-8")
            )
            if state["prompt_count"] == 1:
                break
            time.sleep(0.02)
        else:
            self.fail("The active-turn fixture did not receive its prompt")
        first.shutdown()
        second = self.adapter()
        observation = second.reconnect(
            CodingWorkerReconnectRequest(
                request.work_id, request.run_id, request.objective,
                request.acceptance_criteria, request.authority, 0, "running",
            ),
            binding,
        )
        self.assertTrue(observation.found)
        self.assertEqual(observation.state, "failed")
        events = second.attach(binding, after_sequence=0)
        self.assertEqual(events[-1].kind, "failed")
        self.assertEqual(events[-1].payload["failure_code"], "interrupted_active_turn")
        state = json.loads(
            self.fixture_state(request.work_id).read_text(encoding="utf-8")
        )
        self.assertEqual(state["prompt_count"], 1)

    def test_application_service_same_run_restart_and_follow_up(self) -> None:
        store = SQLiteCodingWorkStore(self.root / "coding-work/coding-work.db")
        store.initialize()
        first = self.adapter()
        application = CodingWorkApplicationService(store, first)
        proposed = application.create_work(
            objective="BROADER_AUTHORITY", workspace_root=self.workspace
        )
        authorized = application.authorize(
            proposed.identifier,
            expected_revision=proposed.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        current = application.start(
            authorized.identifier, expected_revision=authorized.revision
        )
        deadline = time.monotonic() + 5
        while current.state != "waiting" and time.monotonic() < deadline:
            time.sleep(0.02)
            current = application.inspect(current.identifier)
        self.assertEqual(current.state, "waiting")
        run = store.get_run(current.current_run_id)
        original_session = run.harness_session_id
        original_sequence = run.last_event_sequence
        self.assertRegex(original_session or "", r"^ses_")

        first.shutdown()
        application.prepare_restart_reconciliation()
        second = self.adapter()
        restarted = CodingWorkApplicationService(store, second)
        reloaded = restarted.reconcile(current.identifier)
        self.assertEqual(reloaded.state, "waiting")
        self.assertEqual(reloaded.current_run_id, run.identifier)
        self.assertEqual(store.get_run(run.identifier).harness_session_id, original_session)
        self.assertGreater(store.get_run(run.identifier).last_event_sequence, original_sequence)

        directive = restarted.submit_follow_up(
            reloaded.identifier,
            expected_revision=reloaded.revision,
            instruction="Update the synthetic output again.",
        )
        delivered = restarted.deliver_directives(reloaded.identifier)
        self.assertEqual([item.identifier for item in delivered], [directive.identifier])
        followed = restarted.inspect(reloaded.identifier)
        deadline = time.monotonic() + 5
        while followed.state != "completed" and time.monotonic() < deadline:
            time.sleep(0.02)
            followed = restarted.inspect(reloaded.identifier)
        self.assertEqual(followed.state, "completed")
        self.assertEqual(store.get_directive(directive.identifier).status, "delivered")
        self.assertEqual(store.get_run(run.identifier).harness_session_id, original_session)
        self.assertGreater(store.get_run(run.identifier).last_event_sequence, original_sequence)

    def test_restored_waiting_session_cancels_and_releases_workspace(self) -> None:
        store = SQLiteCodingWorkStore(self.root / "coding-work/coding-work.db")
        store.initialize()
        first = self.adapter()
        application = CodingWorkApplicationService(store, first)
        proposed = application.create_work(
            objective="BROADER_AUTHORITY", workspace_root=self.workspace
        )
        authorized = application.authorize(
            proposed.identifier,
            expected_revision=proposed.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        current = application.start(
            authorized.identifier, expected_revision=authorized.revision
        )
        deadline = time.monotonic() + 5
        while current.state != "waiting" and time.monotonic() < deadline:
            time.sleep(0.02)
            current = application.inspect(current.identifier)
        self.assertEqual(current.state, "waiting")

        first.shutdown()
        application.prepare_restart_reconciliation()
        second = self.adapter()
        restarted = CodingWorkApplicationService(store, second)
        restored = restarted.reconcile(current.identifier)
        self.assertEqual(restored.state, "waiting")

        directive = restarted.request_cancellation(
            restored.identifier, expected_revision=restored.revision
        )
        restarted.deliver_directives(restored.identifier)
        deadline = time.monotonic() + 5
        cancelled = store.get_work(restored.identifier)
        while cancelled.state != "cancelled" and time.monotonic() < deadline:
            time.sleep(0.02)
            cancelled = restarted.inspect(restored.identifier)
        self.assertEqual(cancelled.state, "cancelled")
        self.assertEqual(store.get_directive(directive.identifier).status, "delivered")

        replacement = restarted.create_work(
            objective="BROADER_AUTHORITY",
            workspace_root=self.workspace,
        )
        replacement = restarted.authorize(
            replacement.identifier,
            expected_revision=replacement.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_replacement_confirmation",
        )
        replacement = restarted.start(
            replacement.identifier, expected_revision=replacement.revision
        )
        deadline = time.monotonic() + 5
        while replacement.state != "waiting" and time.monotonic() < deadline:
            time.sleep(0.02)
            replacement = restarted.inspect(replacement.identifier)
        self.assertEqual(replacement.state, "waiting")

    def test_cancellation_uses_supervisor_containment_and_waits_for_process_exit(self) -> None:
        adapter = self.adapter()
        request = self.request("SLEEP_UNTIL_CANCELLED")
        binding = adapter.start(request)
        cancellation = self.directive(request, kind="cancel")
        receipt = adapter.cancel(binding, cancellation)
        self.assertFalse(receipt.duplicate)
        events = self.wait_for_event(adapter, binding, {"cancelled"})
        self.assertEqual(events[-1].kind, "cancelled")
        observation = adapter.inspect(binding)
        self.assertEqual(observation.state, "cancelled")
        deadline = time.monotonic() + 3
        while os.path.lexists(self.private / "ipc/provider.sock") and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))

    def test_ambiguous_directive_after_crash_fails_closed_without_duplicate_prompt(self) -> None:
        first = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        binding = first.start(request)
        self.wait_for_event(first, binding, {"waiting"})
        last_sequence = max(
            event.sequence for event in first.attach(binding, after_sequence=0)
        )
        first.shutdown()
        directive = self.directive(request)
        receipt = (
            self.private / "works" / request.work_id / "receipts"
            / (directive.identifier + ".json")
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text('{"status":"inflight"}', encoding="utf-8")
        os.chmod(receipt, 0o600)
        before = json.loads(
            self.fixture_state(request.work_id).read_text(encoding="utf-8")
        )["prompt_count"]

        second = self.adapter()
        observation = second.reconnect(
            CodingWorkerReconnectRequest(
                request.work_id, request.run_id, request.objective,
                request.acceptance_criteria, request.authority, last_sequence,
                "waiting",
            ),
            binding,
        )
        self.assertTrue(observation.found)
        with self.assertRaises(CodingWorkerError) as captured:
            second.submit_directive(binding, directive)
        self.assertEqual(captured.exception.code, "directive_delivery_uncertain")
        after = json.loads(
            self.fixture_state(request.work_id).read_text(encoding="utf-8")
        )["prompt_count"]
        self.assertEqual(after, before)

    def test_missing_session_is_honest_and_does_not_start_replacement(self) -> None:
        adapter = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        missing = CodingWorkerBinding(
            adapter.identifier, adapter.contract_version,
            request.launch_correlation_id, "ses_missing",
        )
        observation = adapter.reconnect(
            CodingWorkerReconnectRequest(
                request.work_id, request.run_id, request.objective,
                request.acceptance_criteria, request.authority, 0,
            ),
            missing,
        )
        self.assertFalse(observation.found)
        self.assertFalse(self.fixture_state(request.work_id).exists())

    def test_broader_permission_becomes_waiting_and_is_not_granted(self) -> None:
        adapter = self.adapter()
        binding = adapter.start(self.request("BROADER_AUTHORITY"))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = adapter.attach(binding, after_sequence=0)
            waiting = [event for event in events if event.kind == "waiting"]
            if waiting:
                break
            time.sleep(0.02)
        else:
            self.fail("OpenCode permission request was not normalized")
        self.assertEqual(waiting[-1].payload["reason"], "authority_required")
        self.assertFalse(any(event.kind == "completed" for event in events))

    def test_crash_and_eof_are_normalized_to_failure(self) -> None:
        adapter = self.adapter()
        binding = adapter.start(self.request("CRASH_PROCESS"))
        events = self.wait_for_event(adapter, binding, {"failed"})
        failed = [event for event in events if event.kind == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn(failed[0].payload["failure_code"], {"transport_eof", "worker_process_crashed"})
        deadline = time.monotonic() + 3
        while os.path.lexists(self.private / "ipc/provider.sock") and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(os.path.lexists(self.private / "ipc/provider.sock"))
        self.assertEqual(failed[0].payload["exit_code"], 9)
        self.assertIn("synthetic OpenCode crash", failed[0].payload["stderr_summary"])
        verification = failed[0].payload["evidence"]["verification"]
        process_exit = [item for item in verification if item.get("kind") == "process_exit"]
        self.assertEqual(len(process_exit), 1)
        self.assertEqual(process_exit[0]["exit_code"], 9)

    def test_signal_exit_classification_and_unknown_origin_are_preserved(self) -> None:
        adapter = self.adapter()
        store = SQLiteCodingWorkStore(self.root / "signal-state/coding-work.db")
        store.initialize()
        application = CodingWorkApplicationService(store, adapter)
        work = application.create_work(
            objective="SIGNAL_PROCESS", workspace_root=self.workspace
        )
        work = application.authorize(
            work.identifier,
            expected_revision=work.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        work = application.start(work.identifier, expected_revision=work.revision)
        deadline = time.monotonic() + 5
        while work.state != "failed" and time.monotonic() < deadline:
            time.sleep(0.02)
            work = application.observe(work.identifier)

        self.assertEqual(work.state, "failed")
        run = store.get_run(work.current_run_id)
        binding = application._binding(run)
        internal_binding = adapter._internal_binding(binding)
        adapter._terminate_session_process(
            adapter._require(internal_binding), "adapter_close"
        )
        process_diagnostics = CodingWorkProcessSupervisor.diagnostics(
            adapter, internal_binding
        )
        self.assertIn(process_diagnostics.termination, {None, "process_exit"})
        self.assertFalse(process_diagnostics.termination_signal_sent)
        self.assertFalse(process_diagnostics.forced_kill_sent)
        failed = [event for event in store.events(work.identifier) if event.kind == "failed"]
        self.assertEqual(len(failed), 1)
        diagnostic = failed[0].payload
        self.assertEqual(diagnostic["exit_code"], -signal.SIGKILL)
        self.assertEqual(diagnostic["signal"], signal.SIGKILL)
        self.assertEqual(diagnostic["termination"], "signal_exit")
        self.assertEqual(diagnostic["signal_origin"], "unknown")
        self.assertNotIn("termination_reason", diagnostic)
        self.assertNotIn("termination_origin", diagnostic)
        verification = diagnostic["evidence"]["verification"]
        self.assertIn(
            {
                "kind": "process_exit",
                "status": "observed",
                "exit_code": -signal.SIGKILL,
                "signal": signal.SIGKILL,
                "signal_origin": "unknown",
                "stderr_truncated": False,
                "termination": "signal_exit",
            },
            verification,
        )
        self.assertIn(verification[0], work.result["verification"])

    def test_oversized_workspace_file_is_not_hashed_and_is_reported_partial(self) -> None:
        with (self.workspace / "oversized.bin").open("wb") as stream:
            stream.truncate(9 * 1024 * 1024)
        snapshot = _workspace_snapshot(self.workspace)
        self.assertEqual(snapshot.entries["oversized.bin"][2], "oversized")
        evidence = _evidence_document(
            SimpleNamespace(
                baseline=snapshot,
                omitted_changed_paths=0,
                changed_paths=set(),
                verifications=[],
            ),
            "Bounded oversized-file evidence",
        )
        verification = evidence["verification"][-1]
        self.assertEqual(verification["status"], "partial")
        self.assertEqual(verification["oversized_files"], 1)
        self.assertLessEqual(verification["hashed_bytes"], 64 * 1024 * 1024)

    def test_changed_path_accumulation_and_receipt_history_are_bounded(self) -> None:
        adapter = self.adapter()
        request = self.request("BROADER_AUTHORITY")
        binding = adapter.start(request)
        self.wait_for_event(adapter, binding, {"waiting"})
        internal = adapter._internal_binding(binding)
        supervised = adapter._require(internal)
        adapter._notification(supervised, {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {"update": {
                "sessionUpdate": "tool_call",
                "title": "Synthetic bulk location report",
                "locations": [
                    {"path": f"generated/path-{index}.txt"}
                    for index in range(700)
                ],
            }},
        })
        session = adapter._open_session(internal)
        evidence = _evidence_document(session, "Bounded evidence")
        self.assertEqual(len(evidence["changed_paths"]), 500)
        snapshot = evidence["verification"][-1]
        self.assertEqual(snapshot["status"], "partial")
        self.assertGreaterEqual(snapshot["omitted_changed_paths"], 200)

        receipts = self.private / "works" / request.work_id / "receipts"
        for index in range(512):
            receipt_path = receipts.joinpath(f"old-{index:04d}.json")
            receipt_path.write_text(
                '{"status":"delivered"}', encoding="utf-8"
            )
            os.chmod(receipt_path, 0o600)
        directive = self.directive(request)
        adapter.submit_directive(binding, directive)
        self.assertLessEqual(len(tuple(receipts.glob("*.json"))), 512)

    def test_private_root_symlink_and_operational_relay_failure_fail_closed(self) -> None:
        target = self.root / "private-target"
        target.mkdir()
        self.private.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OpenCodeAdapterError) as unsafe:
            self.adapter()
        self.assertEqual(unsafe.exception.code, "private_state_unsafe")
        self.private.unlink()

        adapter = self.adapter()
        (self.private / "ipc/provider.sock").write_text("hostile", encoding="utf-8")
        store = SQLiteCodingWorkStore(self.root / "operational/coding-work.db")
        store.initialize()
        application = CodingWorkApplicationService(store, adapter)
        proposed = application.create_work(
            objective="Exercise setup failure", workspace_root=self.workspace
        )
        queued = application.authorize(
            proposed.identifier,
            expected_revision=proposed.revision,
            read_allowed=True,
            modify_allowed=True,
            sandboxed_execution_allowed=True,
            confirmation_provenance="explicit_test_confirmation",
        )
        failed = application.start(queued.identifier, expected_revision=queued.revision)
        self.assertEqual(failed.state, "failed")
        run = store.get_run(failed.current_run_id)
        self.assertEqual(run.failure_code, "unsafe_socket_path")

    def test_per_work_private_state_rejects_symlink_substitution(self) -> None:
        adapter = self.adapter()
        request = self.request()
        works = self.private / "works"
        works.mkdir()
        outside = self.root / "outside-private-state"
        outside.mkdir()
        (works / request.work_id).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OpenCodeAdapterError) as captured:
            adapter.start(request)
        self.assertEqual(captured.exception.code, "private_state_unsafe")
        self.assertEqual(list(outside.iterdir()), [])

    def test_restrictive_configuration_tracks_authority_without_provider_credentials(self) -> None:
        authority = CodingWorkAuthority(str(self.workspace), True, False, False)
        document = json.loads(_configuration(authority, "qwen3.8:latest"))
        permission = document["permission"]
        self.assertEqual(permission["read"], "allow")
        self.assertEqual(permission["edit"], "deny")
        self.assertEqual(permission["bash"], "deny")
        self.assertEqual(permission["external_directory"], "deny")
        self.assertEqual(permission["webfetch"], "deny")
        self.assertEqual(permission["websearch"], "deny")
        self.assertNotIn("11434/api", json.dumps(document))
        self.assertNotIn("credential", json.dumps(document).lower())

    def test_production_sandbox_composition_mounts_only_private_harness_resources(self) -> None:
        executable = self.root / "opencode"
        provider = self.root / "provider.py"
        executable.write_text("fixture", encoding="utf-8")
        provider.write_text("fixture", encoding="utf-8")
        config = self.root / "config"
        state = self.root / "state"
        ipc = self.root / "ipc"
        for path in (config, state, ipc, self.root / "protected-runtime"):
            path.mkdir(exist_ok=True)
        sandbox = _OpenCodeSandbox(
            BubblewrapCodingWorkSandbox(
                "/usr/bin/bwrap",
                protected_runtime_root=self.root / "protected-runtime",
                project_collection_root=self.root / "collection",
            ),
            executable,
            provider,
            lambda _authority: _OpenCodeSandboxResources(config, state, ipc),
        )
        plan = sandbox.plan(("/harness/opencode", "acp"), self.request().authority)
        command = list(plan.argv)
        self.assertIn("--unshare-all", command)
        self.assertIn(str(executable), command)
        self.assertIn("/harness/opencode", command)
        self.assertIn(str(provider), command)
        self.assertIn("/harness/provider.py", command)
        self.assertIn(str(config), command)
        self.assertIn(str(state), command)
        self.assertIn(str(ipc), command)
        self.assertEqual(plan.environment["HOME"], "/harness/state/home")
        self.assertEqual(plan.environment["OPENCODE_DISABLE_AUTOUPDATE"], "true")
        self.assertNotIn("HTTP_PROXY", plan.environment)
        self.assertNotIn("SSH_AUTH_SOCK", plan.environment)

    def test_acp_notifications_do_not_consume_deadline_and_malformed_data_fails(self) -> None:
        code = (
            "import json,sys\n"
            "request=json.loads(sys.stdin.readline())\n"
            "for _ in range(300):\n"
            " print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{}}),flush=True)\n"
            "print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{}}),flush=True)\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        client = ACPJSONRPCClient(
            process, notification=lambda _item: None,
            request=lambda _method, _params: {}, raw_output=lambda _raw: None,
        )
        reader = __import__("threading").Thread(target=client.read_loop, daemon=True)
        reader.start()
        self.assertEqual(client.call("test", {}, timeout_seconds=2), {})
        process.terminate()
        process.wait(timeout=2)
        client.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

        malformed = subprocess.Popen(
            [sys.executable, "-u", "-c", "print('not-json',flush=True);import time;time.sleep(1)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        broken = ACPJSONRPCClient(
            malformed, notification=lambda _item: None,
            request=lambda _method, _params: {}, raw_output=lambda _raw: None,
        )
        broken_reader = __import__("threading").Thread(target=broken.read_loop, daemon=True)
        broken_reader.start()
        with self.assertRaises(OpenCodeAdapterError) as captured:
            broken.call("test", {}, timeout_seconds=2)
        self.assertEqual(captured.exception.code, "invalid_acp_message")
        malformed.terminate()
        malformed.wait(timeout=2)
        broken.close()
        for stream in (malformed.stdin, malformed.stdout, malformed.stderr):
            if stream is not None:
                stream.close()

    def test_acp_callback_failure_wakes_pending_call_and_boolean_id_is_rejected(self) -> None:
        notification_code = (
            "import json,sys,time\n"
            "json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{}}),flush=True)\n"
            "time.sleep(30)\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", notification_code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        client = ACPJSONRPCClient(
            process,
            notification=lambda _item: (_ for _ in ()).throw(RuntimeError("callback")),
            request=lambda _method, _params: {},
            raw_output=lambda _raw: None,
        )
        reader = __import__("threading").Thread(target=client.read_loop, daemon=True)
        reader.start()
        started = time.monotonic()
        with self.assertRaises(OpenCodeAdapterError) as captured:
            client.call("test", {}, timeout_seconds=2)
        self.assertEqual(captured.exception.code, "acp_handler_failed")
        self.assertLess(time.monotonic() - started, 1)
        process.terminate()
        process.wait(timeout=2)
        client.close()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

        boolean_code = (
            "import json,sys,time\n"
            "json.loads(sys.stdin.readline())\n"
            "print(json.dumps({'jsonrpc':'2.0','id':True,'result':{}}),flush=True)\n"
            "time.sleep(30)\n"
        )
        boolean_process = subprocess.Popen(
            [sys.executable, "-u", "-c", boolean_code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        boolean_client = ACPJSONRPCClient(
            boolean_process,
            notification=lambda _item: None,
            request=lambda _method, _params: {},
            raw_output=lambda _raw: None,
        )
        boolean_reader = __import__("threading").Thread(
            target=boolean_client.read_loop, daemon=True
        )
        boolean_reader.start()
        with self.assertRaises(OpenCodeAdapterError) as invalid:
            boolean_client.call("test", {}, timeout_seconds=2)
        self.assertEqual(invalid.exception.code, "invalid_acp_message")
        boolean_process.terminate()
        boolean_process.wait(timeout=2)
        boolean_client.close()
        for stream in (
            boolean_process.stdin, boolean_process.stdout, boolean_process.stderr,
        ):
            if stream is not None:
                stream.close()


if __name__ == "__main__":
    unittest.main()
