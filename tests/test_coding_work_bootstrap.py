from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from tori.coding_work import SQLiteCodingWorkStore
from tori.coding_work_bootstrap import (
    OpenCodeBootstrapConflictError,
    OpenCodeBootstrapError,
    OpenCodeBootstrapNetworkAuthorizationRequired,
    OpenCodeOfflineBootstrapper,
)
from tori.coding_work_bootstrap_transport import BootstrapEgressError
from tori.coding_work_runtime import (
    CodingWorkProductionSettings,
    CodingWorkReadinessEvaluator,
    CodingWorkRuntimeInitializer,
    CodingWorkRuntimeOwnership,
    offline_bootstrap_inventory,
    offline_bootstrap_ready,
)


NOW = datetime(2026, 8, 24, 18, 30, tzinfo=timezone.utc)


class FakeBootstrapRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []
        self.fail = fail

    def __call__(self, command, cwd, environment):  # type: ignore[no-untyped-def]
        command = tuple(command)
        env = dict(environment)
        self.calls.append((command, Path(cwd), env))
        allowed = {
            "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
            "XDG_STATE_HOME", "TMPDIR", "PATH", "OPENCODE_DISABLE_AUTOUPDATE",
            "OPENCODE_MODELS_URL",
        }
        if set(env) != allowed:
            raise AssertionError("bootstrap inherited an unexpected environment value")
        if command[-1] == "--version":
            return SimpleNamespace(returncode=0, stdout=b"1.18.31\n", stderr=b"")
        if command[-3:] != ("debug", "config", "--pure"):
            raise AssertionError(f"unexpected bootstrap command: {command}")
        cache = Path(env["XDG_CACHE_HOME"])
        data = Path(env["XDG_DATA_HOME"])
        package = cache / "packages/provider.package"
        package.parent.mkdir(mode=0o700)
        package.write_bytes(b"synthetic regenerable provider package")
        os.chmod(package, 0o600)
        metadata = data / "provider-metadata.json"
        metadata.write_text('{"provider":"openai-compatible"}', encoding="utf-8")
        os.chmod(metadata, 0o600)
        return SimpleNamespace(
            returncode=1 if self.fail else 0,
            stdout=b"synthetic stdout\n" if self.fail else b"",
            stderr=b"synthetic failure" if self.fail else b"",
        )


class OpenCodeOfflineBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        runtime = self.root / "runtime"
        runtime.mkdir(mode=0o700)
        self.layout = CodingWorkRuntimeInitializer(runtime).initialize()
        self.executable = self.root / "opencode"
        self.executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        os.chmod(self.executable, 0o700)
        self.bwrap = self.root / "bwrap"
        self.bwrap.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        os.chmod(self.bwrap, 0o700)

    def bootstrapper(self, runner=None):  # type: ignore[no-untyped-def]
        return OpenCodeOfflineBootstrapper(
            destination=self.layout.opencode_bootstrap_cache,
            opencode_executable=self.executable,
            opencode_version="1.18.31",
            model="qwen3.8:latest",
            runner=runner,
            clock=lambda: NOW,
            token_hex=lambda _length: "0123456789abcdef0123456789abcdef",
        )

    def settings(self) -> CodingWorkProductionSettings:
        return CodingWorkProductionSettings(
            runtime_root=self.layout.root,
            opencode_executable=self.executable,
            opencode_version="1.18.31",
            bubblewrap_executable=self.bwrap,
            provider_upstream="http://127.0.0.1:11434/v1",
            model="qwen3.8:latest",
        )

    def prepare(self):  # type: ignore[no-untyped-def]
        runner = FakeBootstrapRunner()
        result = self.bootstrapper(runner).prepare()
        return result, runner

    def test_explicit_bootstrap_stages_publishes_and_is_ready(self) -> None:
        result, runner = self.prepare()
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(runner.calls[1][0][-3:], ("debug", "config", "--pure"))
        for _command, cwd, environment in runner.calls:
            self.assertNotEqual(cwd, Path("/workspaces/Tori"))
            self.assertTrue(cwd.name == "workspace")
            self.assertNotIn("SSH_AUTH_SOCK", environment)
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn(str(Path.home()), set(environment.values()))
        self.assertTrue(result.prepared_root.is_dir())
        self.assertTrue(result.receipt.is_file())
        self.assertEqual(oct(result.prepared_root.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct(result.receipt.stat().st_mode & 0o777), "0o600")
        digest, count, total = offline_bootstrap_inventory(result.prepared_root)
        self.assertEqual((digest, count, total), (
            result.cache_digest, result.cache_file_count, result.cache_total_bytes
        ))
        owner = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(owner.acquire())
        self.addCleanup(owner.release)
        evaluator = CodingWorkReadinessEvaluator(
            self.settings(), ownership=owner,
            provider_model_available=lambda _settings: True,
            opencode_version_probe=lambda _settings: True,
            bubblewrap_probe=lambda _settings: True,
        )
        self.assertEqual(evaluator.evaluate().state, "available")
        store = SQLiteCodingWorkStore(self.layout.database)
        self.assertEqual(store.list_work(), ())
        self.assertFalse(any(self.layout.opencode_works.iterdir()))
        self.assertFalse(any("acp" in " ".join(call[0]) for call in runner.calls))

    def test_receipt_is_canonical_bounded_and_contains_no_sensitive_content(self) -> None:
        result, _runner = self.prepare()
        raw = result.receipt.read_bytes()
        self.assertLessEqual(len(raw), 4096)
        document = json.loads(raw)
        self.assertEqual(list(document), sorted(document))
        self.assertEqual(document["schema"], 1)
        self.assertEqual(document["opencode_version"], "1.18.31")
        self.assertEqual(document["provider_package"], "@ai-sdk/openai-compatible")
        self.assertEqual(document["prepared_at_utc"], "2026-08-24T18:30:00Z")
        self.assertEqual(document["provenance"], "explicit_tori_opencode_offline_bootstrap")
        lowered = raw.lower()
        for forbidden in (b"prompt", b"response", b"api_key", b"credential", b"password"):
            self.assertNotIn(forbidden, lowered)
        self.assertEqual(
            offline_bootstrap_inventory(result.prepared_root),
            offline_bootstrap_inventory(result.prepared_root),
        )

    def test_published_sqlite_validation_is_immutable_and_rejects_sessions(self) -> None:
        result, _runner = self.prepare()
        database = result.prepared_root / "data/opencode/opencode.db"
        database.parent.mkdir(mode=0o700, parents=True)
        connection = sqlite3.connect(database)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("CREATE TABLE session (id TEXT PRIMARY KEY)")
        connection.commit()

        def secure_sqlite_files() -> None:
            for name in ("opencode.db", "opencode.db-wal", "opencode.db-shm"):
                path = database.parent / name
                if path.exists():
                    os.chmod(path, 0o600)

        secure_sqlite_files()

        def refresh_receipt() -> None:
            digest, count, total = offline_bootstrap_inventory(result.prepared_root)
            document = json.loads(result.receipt.read_bytes())
            document.update(
                cache_digest=digest,
                cache_file_count=count,
                cache_total_bytes=total,
            )
            result.receipt.write_text(
                json.dumps(document, sort_keys=True, separators=(",", ":")),
                encoding="ascii",
            )
            os.chmod(result.receipt, 0o600)

        refresh_receipt()
        before = offline_bootstrap_inventory(result.prepared_root)
        self.assertTrue(offline_bootstrap_ready(self.layout, self.settings()))
        owner = CodingWorkRuntimeOwnership(self.layout)
        self.assertTrue(owner.acquire())
        self.addCleanup(owner.release)
        evaluator = CodingWorkReadinessEvaluator(
            self.settings(), ownership=owner,
            provider_model_available=lambda _settings: True,
            opencode_version_probe=lambda _settings: True,
            bubblewrap_probe=lambda _settings: True,
        )
        self.assertEqual(evaluator.evaluate().state, "available")
        self.assertEqual(offline_bootstrap_inventory(result.prepared_root), before)

        connection.execute("INSERT INTO session(id) VALUES ('ses_forbidden')")
        connection.commit()
        secure_sqlite_files()
        refresh_receipt()
        before_nonempty = offline_bootstrap_inventory(result.prepared_root)
        self.assertFalse(offline_bootstrap_ready(self.layout, self.settings()))
        self.assertEqual(
            offline_bootstrap_inventory(result.prepared_root), before_nonempty
        )

    def test_default_operation_requires_explicit_network_authority(self) -> None:
        with self.assertRaises(OpenCodeBootstrapNetworkAuthorizationRequired):
            self.bootstrapper().prepare()
        self.assertEqual(tuple(self.layout.opencode_bootstrap_cache.iterdir()), ())
        self.assertFalse(self.layout.bootstrap_manifest.exists())
        prepared = self.layout.bootstrap_prepared
        prepared.mkdir(mode=0o700)
        for name in ("data", "cache", "state"):
            (prepared / name).mkdir(mode=0o700)
        self.layout.bootstrap_manifest.write_text("{}", encoding="ascii")
        os.chmod(self.layout.bootstrap_manifest, 0o600)
        self.assertFalse(offline_bootstrap_ready(self.layout, self.settings()))

    def test_network_authority_uses_fixed_sandbox_transport_not_ambient_runner(self) -> None:
        lifecycle: list[str] = []
        commands: list[tuple[str, ...]] = []

        class FakeRelay:
            def __init__(self, path) -> None:  # type: ignore[no-untyped-def]
                self.path = Path(path)

            def start(self) -> None:
                lifecycle.append("relay_started")

            def close(self) -> None:
                lifecycle.append("relay_closed")

            @property
            def audit(self):  # type: ignore[no-untyped-def]
                return ()

        def isolated_runner(command, cwd, environment):  # type: ignore[no-untyped-def]
            self.assertEqual(lifecycle, ["relay_started"])
            command = tuple(command)
            commands.append(command)
            self.assertIn("--unshare-all", command)
            self.assertNotIn("--share-net", command)
            self.assertIn("--clearenv", command)
            if command[-1] == "--version":
                return SimpleNamespace(returncode=0, stdout=b"1.18.31\n", stderr=b"")
            self.assertEqual(command[-3:], ("debug", "config", "--pure"))
            cache = Path(environment["XDG_CACHE_HOME"])
            package = cache / "packages/provider.package"
            package.parent.mkdir(mode=0o700)
            package.write_bytes(b"synthetic regenerable provider package")
            os.chmod(package, 0o600)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        bootstrapper = OpenCodeOfflineBootstrapper(
            destination=self.layout.opencode_bootstrap_cache,
            opencode_executable=self.executable,
            bubblewrap_executable=self.bwrap,
            opencode_version="1.18.31",
            model="qwen3.8:latest",
            clock=lambda: NOW,
            token_hex=lambda _length: "b" * 32,
        )
        with (
            patch("tori.coding_work_bootstrap.FixedOpenCodeBootstrapRelay", FakeRelay),
            patch.object(
                OpenCodeOfflineBootstrapper,
                "_subprocess_runner",
                side_effect=isolated_runner,
            ),
        ):
            result = bootstrapper.prepare(network_authorized=True)
        self.assertEqual(lifecycle, ["relay_started", "relay_closed"])
        self.assertEqual(len(commands), 2)
        self.assertTrue(result.prepared_root.is_dir())
        self.assertEqual(result.egress_audit, ())

    def test_fixed_transport_failure_occurs_before_opencode_and_preserves_stage(self) -> None:
        class FailingRelay:
            def __init__(self, _path) -> None:  # type: ignore[no-untyped-def]
                pass

            def start(self) -> None:
                raise BootstrapEgressError("synthetic unavailable", code="upstream_unavailable")

            def close(self) -> None:
                raise AssertionError("an unstarted relay must not be closed")

        bootstrapper = OpenCodeOfflineBootstrapper(
            destination=self.layout.opencode_bootstrap_cache,
            opencode_executable=self.executable,
            bubblewrap_executable=self.bwrap,
            opencode_version="1.18.31",
            model="qwen3.8:latest",
            clock=lambda: NOW,
            token_hex=lambda _length: "c" * 32,
        )
        with (
            patch("tori.coding_work_bootstrap.FixedOpenCodeBootstrapRelay", FailingRelay),
            patch.object(OpenCodeOfflineBootstrapper, "_subprocess_runner") as runner,
        ):
            with self.assertRaises(OpenCodeBootstrapError):
                bootstrapper.prepare(network_authorized=True)
        runner.assert_not_called()
        staged = tuple(self.layout.opencode_bootstrap_cache.iterdir())
        self.assertEqual(len(staged), 1)
        self.assertTrue(staged[0].name.startswith(".opencode-bootstrap.initialize-"))
        self.assertFalse(self.layout.bootstrap_manifest.exists())

    def test_existing_destination_and_failed_stage_are_never_merged_or_cleaned(self) -> None:
        hostile = self.layout.opencode_bootstrap_cache / "hostile"
        hostile.write_text("preserve", encoding="utf-8")
        os.chmod(hostile, 0o600)
        with self.assertRaises(OpenCodeBootstrapConflictError):
            self.bootstrapper(FakeBootstrapRunner()).prepare()
        self.assertEqual(hostile.read_text(encoding="utf-8"), "preserve")

        second_runtime = self.root / "second-runtime"
        second_runtime.mkdir(mode=0o700)
        second = CodingWorkRuntimeInitializer(second_runtime).initialize()
        failing = OpenCodeOfflineBootstrapper(
            destination=second.opencode_bootstrap_cache,
            opencode_executable=self.executable,
            opencode_version="1.18.31", model="qwen3.8:latest",
            runner=FakeBootstrapRunner(fail=True), clock=lambda: NOW,
            token_hex=lambda _length: "a" * 32,
        )
        with self.assertRaises(OpenCodeBootstrapError) as captured:
            failing.prepare()
        message = str(captured.exception)
        self.assertIn("The isolated OpenCode package bootstrap failed.", message)
        self.assertIn("Return code: 1", message)
        self.assertIn("captured stdout: 'synthetic stdout\\n'", message)
        self.assertIn("captured stderr: 'synthetic failure'", message)
        staged = tuple(second.opencode_bootstrap_cache.iterdir())
        self.assertEqual(len(staged), 1)
        self.assertTrue(staged[0].name.startswith(".opencode-bootstrap.initialize-"))
        self.assertFalse(second.bootstrap_manifest.exists())

    def test_readiness_rejects_receipt_and_cache_tampering(self) -> None:
        result, _runner = self.prepare()
        settings = self.settings()
        self.assertTrue(offline_bootstrap_ready(self.layout, settings))
        original_receipt = result.receipt.read_bytes()
        package = result.prepared_root / "cache/packages/provider.package"

        cases = (
            ("wrong_version", lambda document: document.update(opencode_version="1.18.20")),
            ("wrong_package", lambda document: document.update(provider_package="other")),
            ("wrong_digest", lambda document: document.update(cache_digest="0" * 64)),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                document = json.loads(original_receipt)
                mutate(document)
                result.receipt.write_text(
                    json.dumps(document, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        result.receipt.unlink()
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        result.receipt.write_bytes(original_receipt)
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        os.chmod(result.receipt, 0o600)
        self.assertTrue(offline_bootstrap_ready(self.layout, settings))

        package.write_bytes(b"changed")
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        package.write_bytes(b"synthetic regenerable provider package")
        added = result.prepared_root / "cache/added"
        added.write_bytes(b"added")
        os.chmod(added, 0o600)
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        added.unlink()
        package.unlink()
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))

    def test_readiness_rejects_unsafe_modes_symlinks_and_budgets(self) -> None:
        result, _runner = self.prepare()
        settings = self.settings()
        package = result.prepared_root / "cache/packages/provider.package"
        os.chmod(package, 0o644)
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        os.chmod(package, 0o600)
        package.unlink()
        package.symlink_to("/tmp/hostile")
        self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        package.unlink()
        package.write_bytes(b"synthetic regenerable provider package")
        os.chmod(package, 0o600)
        with patch("tori.coding_work_runtime.MAX_OFFLINE_BOOTSTRAP_FILES", 1):
            self.assertFalse(offline_bootstrap_ready(self.layout, settings))
        with patch("tori.coding_work_runtime.MAX_OFFLINE_BOOTSTRAP_BYTES", 1):
            self.assertFalse(offline_bootstrap_ready(self.layout, settings))


if __name__ == "__main__":
    unittest.main()
