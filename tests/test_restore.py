from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tori.backups import BackupError, BackupService
from tori.operation_coordinator import OperationCoordinator
from tori.restore import (
    RestoreCompatibilityError,
    RestoreConfirmationError,
    RestoreHandoffError,
    RestoreService,
    TRUSTED_TORI_ORIGIN,
    TrustedSourceResolver,
)


TEST_ORIGIN = "https://example.invalid/Tori.git"


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class RestoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.project = self.base / "Tori"
        self.project.mkdir()
        (self.project / ".gitignore").write_text(
            "/tori.toml\n/runtime/\n/.venv/\n/models/\n/artifacts/\n", encoding="utf-8"
        )
        (self.project / "requirements.txt").write_text("", encoding="utf-8")
        (self.project / "start-tori.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(self.project / "start-tori.sh", 0o755)
        (self.project / "scripts").mkdir()
        shutil.copyfile(Path(__file__).parents[1] / "scripts/tori-restore", self.project / "scripts/tori-restore")
        os.chmod(self.project / "scripts/tori-restore", 0o755)
        git(self.project, "init", "-b", "main")
        git(self.project, "config", "user.name", "Tori Tests")
        git(self.project, "config", "user.email", "tori-tests@example.invalid")
        git(self.project, "add", ".")
        git(self.project, "commit", "-m", "test source")
        git(self.project, "remote", "add", "origin", TEST_ORIGIN)
        git(self.project, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.commit = git(self.project, "rev-parse", "HEAD")
        (self.project / "tori.toml").write_text("[logging]\nlevel = \"INFO\"\n", encoding="utf-8")
        (self.project / "runtime").mkdir()
        (self.project / "runtime/state.txt").write_text("selected-state\n", encoding="utf-8")
        self.backup_root = self.base / "backups"
        self.backups = BackupService(
            project_root=self.project,
            backup_root=self.backup_root,
            sqlite_paths=(),
            clock=lambda: datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        )
        self.selected = self.backups.create_backup()
        self.launched: list[tuple[list[str], Path]] = []
        self.service = RestoreService(
            self.backups,
            OperationCoordinator(),
            project_root=self.project,
            web_port=8765,
            origin=TEST_ORIGIN,
            helper_source=self.project / "scripts/tori-restore",
            launcher=lambda args, root: self.launched.append((args, root)),
            process_id=99999999,
        )

    def tearDown(self) -> None:
        for _, handoff in self.launched:
            shutil.rmtree(handoff, ignore_errors=True)

    def _voice_backup(self):
        voice = self.project / "models/voice"
        (voice / "small.en").mkdir(parents=True)
        (voice / "small.en/model.bin").write_bytes(b"verified voice weights")
        (voice / "silero_vad.onnx").write_bytes(b"verified VAD")
        (voice / "skills").mkdir()
        (voice / "skills/extra.txt").write_bytes(b"additional snapshot asset")
        for directory in (self.project / "models", voice, voice / "small.en", voice / "skills"):
            os.chmod(directory, 0o700)
        for path in (voice / "small.en/model.bin", voice / "silero_vad.onnx", voice / "skills/extra.txt"):
            os.chmod(path, 0o600)
        (self.project / "deploy/voice/.venv/bin").mkdir(parents=True)
        (self.project / "deploy/voice/.venv/bin/python").write_bytes(b"prepared elsewhere")
        (self.project / "artifacts/visual-browser").mkdir(parents=True)
        (self.project / "artifacts/visual-browser/smoke.png").write_bytes(b"development evidence")
        return self.backups.create_backup()

    def test_verified_voice_assets_are_staged_without_environments_or_unrelated_artifacts(self) -> None:
        selected = self._voice_backup()
        payload = Path(selected.directory) / "project"
        manifest = json.loads((Path(selected.directory) / "manifest.json").read_bytes())
        records = {entry["path"]: entry for entry in manifest["entries"]}
        self.assertIn("models/voice/small.en/model.bin", records)
        self.assertFalse((payload / "deploy/voice/.venv").exists())
        self.assertTrue((payload / "artifacts/visual-browser/smoke.png").is_file())

        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[-1][1] / "restore-plan.json").read_bytes())
        candidate = Path(plan["candidate_path"])
        for relative in ("small.en/model.bin", "silero_vad.onnx", "skills/extra.txt"):
            backed = payload / "models/voice" / relative
            staged = candidate / "models/voice" / relative
            self.assertEqual(staged.read_bytes(), backed.read_bytes())
            self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(),
                             records[f"models/voice/{relative}"]["sha256"])
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode) & 0o022, 0)
        self.assertFalse((candidate / "deploy/voice/.venv").exists())
        self.assertFalse((candidate / "artifacts").exists())
        self.assertEqual((candidate / "start-tori.sh").read_bytes(),
                         (self.project / "start-tori.sh").read_bytes())
        self.assertEqual(git(candidate, "status", "--porcelain"), "")

    def test_helper_activation_publishes_backed_voice_assets_and_preserves_only_main_venv(self) -> None:
        selected = self._voice_backup()
        (self.project / ".venv").mkdir()
        (self.project / ".venv/marker").write_bytes(b"main environment")
        (self.project / "models/voice/small.en/model.bin").write_bytes(b"newer local weights")
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        helper = runpy.run_path(str(Path(__file__).parents[1] / "scripts/tori-restore"))
        helper["_validate"].__globals__["TRUSTED_ORIGIN"] = TEST_ORIGIN
        plan_path = self.launched[-1][1] / "restore-plan.json"
        plan = helper["_validate"](helper["_load_plan"](plan_path))
        process = Mock()
        process.poll.return_value = None
        with patch.dict(helper["_activate"].__globals__, {
            "_start": Mock(return_value=process), "_healthy": Mock(return_value=True),
        }):
            result = helper["_activate"](plan)
        self.assertTrue(result["ok"])
        self.assertEqual((self.project / "models/voice/small.en/model.bin").read_bytes(),
                         b"verified voice weights")
        self.assertEqual((self.project / ".venv/marker").read_bytes(), b"main environment")
        self.assertFalse((self.project / "deploy/voice/.venv").exists())
        self.assertTrue((plan["rollback"] / "deploy/voice/.venv/bin/python").is_file())
        self.assertFalse((self.project / "artifacts").exists())

    def test_restore_without_voice_assets_does_not_create_model_root(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[-1][1] / "restore-plan.json").read_bytes())
        self.assertFalse((Path(plan["candidate_path"]) / "models").exists())

    def test_corrupt_voice_model_fails_verification_before_staging(self) -> None:
        selected = self._voice_backup()
        (Path(selected.directory) / "project/models/voice/small.en/model.bin").write_bytes(b"corrupt")
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        with patch.object(self.service.resolver, "stage_source", side_effect=AssertionError("unverified source staged")):
            with self.assertRaisesRegex(RestoreHandoffError, "before activation"):
                self.service.confirm(token, "restore")
        self.assertFalse(self.launched)

    def test_voice_asset_symlinks_and_traversal_fail_closed(self) -> None:
        selected = self._voice_backup()
        target = self.base / "external-data"
        target.write_bytes(b"external data stays untouched")
        model = self.project / "models/voice/small.en/model.bin"
        model.unlink()
        model.symlink_to(target)
        unsafe = self.backups.create_backup()
        token = self.service.propose(unsafe.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "unsafe object"):
            self.service.confirm(token, "restore")
        self.assertEqual(target.read_bytes(), b"external data stays untouched")
        self.assertFalse(self.launched)

        manifest_path = Path(selected.directory) / "manifest.json"
        document = json.loads(manifest_path.read_bytes())
        record = next(item for item in document["entries"]
                      if item["path"] == "models/voice/small.en/model.bin")
        record["path"] = "models/voice/../src/app.py"
        manifest_path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(RestoreCompatibilityError):
            self.service.propose(selected.identifier)

    def test_voice_root_symlink_cannot_reach_external_data(self) -> None:
        external = self.base / "external-models"
        external.mkdir()
        (external / "model.bin").write_bytes(b"private")
        (self.project / "models").mkdir()
        os.chmod(self.project / "models", 0o700)
        (self.project / "models/voice").symlink_to(external, target_is_directory=True)
        selected = self.backups.create_backup()
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "not a safe directory"):
            self.service.confirm(token, "restore")
        self.assertEqual((external / "model.bin").read_bytes(), b"private")
        self.assertFalse(self.launched)

    def test_unsafe_voice_permissions_fail_before_activation(self) -> None:
        self._voice_backup()
        model = self.project / "models/voice/small.en/model.bin"
        os.chmod(model, 0o666)
        selected = self.backups.create_backup()
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "unsafe permissions"):
            self.service.confirm(token, "restore")
        self.assertFalse(self.launched)

    def test_voice_copy_is_checked_against_verified_manifest_before_handoff(self) -> None:
        selected = self._voice_backup()
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        from tori import restore as restore_module

        original = restore_module._copy_runtime

        def corrupt_staged_asset(source, destination, **options):
            original(source, destination, **options)
            if options.get("private_assets"):
                (destination / "small.en/model.bin").write_bytes(b"corrupt staged asset")

        with patch("tori.restore._copy_runtime", side_effect=corrupt_staged_asset):
            with self.assertRaisesRegex(RestoreCompatibilityError, "did not match"):
                self.service.confirm(token, "restore")
        self.assertEqual((self.project / "models/voice/small.en/model.bin").read_bytes(),
                         b"verified voice weights")
        self.assertFalse(self.launched)

    def test_voice_restore_leaves_external_data_outside_backup_and_activation(self) -> None:
        markers = []
        for kind in ("finance", "knowledge", "radicale", "research_worker"):
            outside = self.base / kind
            outside.mkdir()
            marker = outside / "private-data"
            marker.write_bytes(b"unchanged")
            markers.append(marker)
        selected = self._voice_backup()
        payload = Path(selected.directory) / "project"
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[-1][1] / "restore-plan.json").read_bytes())
        candidate = Path(plan["candidate_path"])
        for marker in markers:
            self.assertFalse((payload / marker.parent.name).exists())
            self.assertFalse((candidate / marker.parent.name).exists())
            self.assertEqual(marker.read_bytes(), b"unchanged")

    def test_trusted_source_voice_root_cannot_be_overwritten_by_backup_assets(self) -> None:
        tracked = self.project / "models/voice/trusted.py"
        tracked.parent.mkdir(parents=True)
        os.chmod(self.project / "models", 0o700)
        os.chmod(tracked.parent, 0o700)
        tracked.write_bytes(b"trusted source")
        git(self.project, "add", "-f", "models/voice/trusted.py")
        git(self.project, "commit", "-m", "trusted Voice source")
        git(self.project, "update-ref", "refs/remotes/origin/main", "HEAD")
        (tracked.parent / "model.bin").write_bytes(b"untracked model")
        selected = self.backups.create_backup()
        token = self.service.propose(selected.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "Trusted source already occupies"):
            self.service.confirm(token, "restore")
        self.assertEqual(tracked.read_bytes(), b"trusted source")
        self.assertFalse(self.launched)

    def test_published_backup_is_eligible_but_not_reverified_by_catalog(self) -> None:
        record = self.service.catalog()["backups"][0]
        self.assertEqual(record["compatibility"], "Eligible for verification")
        self.assertEqual(record["verification"], "not_rechecked")
        self.assertTrue(record["selectable"])
        self.assertEqual(record["source_commit"], self.commit)

    def test_catalog_reads_publication_metadata_without_hashing_any_payload(self) -> None:
        with (
            patch.object(self.backups, "verified_backup", side_effect=AssertionError("full verification in list")),
            patch.object(self.backups, "_verify_payload", side_effect=AssertionError("payload walk in list")),
            patch("tori.backups._hash_file", side_effect=AssertionError("payload hash in list")),
        ):
            records = self.service.catalog()["backups"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["verification"], "not_rechecked")

    def test_malformed_manifest_and_commit_fail_closed_in_catalog(self) -> None:
        path = Path(self.selected.directory) / "manifest.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["counts"]["regular_files"] += 1
        path.write_text(json.dumps(document), encoding="utf-8")
        record = self.service.catalog()["backups"][0]
        self.assertEqual(record["compatibility"], "Invalid")
        self.assertFalse(record["selectable"])

        document["counts"]["regular_files"] -= 1
        document["git"]["head"] = "not-a-commit"
        path.write_text(json.dumps(document), encoding="utf-8")
        record = self.service.catalog()["backups"][0]
        self.assertEqual(record["compatibility"], "Invalid")
        self.assertFalse(record["selectable"])

    def test_manifest_swapped_to_symlink_during_catalog_open_is_rejected(self) -> None:
        path = Path(self.selected.directory) / "manifest.json"
        original_open = os.open
        swapped = False

        def swap_at_open(target, flags, *args, **kwargs):
            nonlocal swapped
            if os.fspath(target) == str(path) and not swapped:
                swapped = True
                path.unlink()
                path.symlink_to(self.project / "tori.toml")
            return original_open(target, flags, *args, **kwargs)

        with patch("tori.backups.os.open", side_effect=swap_at_open):
            record = self.service.catalog()["backups"][0]
        self.assertTrue(swapped)
        self.assertEqual(record["compatibility"], "Invalid")
        self.assertFalse(record["selectable"])

    def test_old_publication_without_source_commit_needs_manual_recovery(self) -> None:
        path = Path(self.selected.directory) / "manifest.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["git"]["head"] = None
        path.write_text(json.dumps(document), encoding="utf-8")
        with patch.object(self.backups, "verified_backup", side_effect=AssertionError("full verification in list")):
            record = self.service.catalog()["backups"][0]
        self.assertEqual(record["compatibility"], "Legacy/manual recovery")
        self.assertEqual(record["verification"], "not_rechecked")
        self.assertFalse(record["selectable"])

    def test_payload_corruption_is_not_misreported_as_verified_and_cannot_restore(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        payload = Path(self.selected.directory) / "project/runtime/state.txt"
        payload.write_text("corrupt after publication\n", encoding="utf-8")
        record = self.service.catalog()["backups"][0]
        self.assertEqual(record["verification"], "not_rechecked")
        self.assertTrue(record["selectable"], "catalog eligibility is not payload verification")
        with patch.object(self.service, "_prepare", side_effect=AssertionError("unsafe staging")) as prepare:
            with self.assertRaisesRegex(RestoreHandoffError, "before activation"):
                self.service.confirm(token, "restore")
        prepare.assert_not_called()
        self.assertFalse(self.service.pending)
        self.assertFalse(self.service.coordinator.locked())
        self.assertFalse(self.launched)
        with self.assertRaises(RestoreConfirmationError):
            self.service.confirm(token, "restore")

    def test_invalid_and_incomplete_backups_are_not_selectable(self) -> None:
        invalid = self.backup_root / "Tori_20260907_120001_aaaaaaaaaaaaaaaa"
        invalid.mkdir()
        incomplete = self.backup_root / ".Tori_20260907_120002_bbbbbbbbbbbbbbbb.incomplete"
        incomplete.mkdir()
        records = {item["identifier"]: item for item in self.service.catalog()["backups"]}
        self.assertEqual(records[invalid.name]["compatibility"], "Invalid")
        self.assertEqual(records[incomplete.name]["compatibility"], "Incomplete")
        self.assertFalse(records[invalid.name]["selectable"])

    def test_legacy_source_fails_closed_and_remains_manual(self) -> None:
        manifest_path = Path(self.selected.directory) / "manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["git"]["head"] = "f" * 40
        manifest_path.write_text(json.dumps(document), encoding="utf-8")
        record = self.service.catalog()["backups"][0]
        self.assertEqual(record["compatibility"], "Legacy/manual recovery")
        with self.assertRaisesRegex(RestoreCompatibilityError, "manual recovery"):
            self.service.propose(self.selected.identifier)

    def test_confirmation_is_exact_one_use_and_contains_boundaries(self) -> None:
        proposal = self.service.propose(self.selected.identifier)["confirmation"]
        message = proposal["message"]
        for text in ("stop temporarily", "tori.toml", "Finance", "Radicale", "Knowledge", "safety backup"):
            self.assertIn(text, message)
        status, response = self.service.confirm(proposal["token"], "cancel")
        self.assertEqual(status, 200)
        self.assertTrue(response["cancelled"])
        with self.assertRaises(RestoreConfirmationError):
            self.service.confirm(proposal["token"], "restore")

    def test_wrong_confirmation_consumes_proposal(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        with self.assertRaises(RestoreConfirmationError):
            self.service.confirm(token + "x", "restore")
        with self.assertRaises(RestoreConfirmationError):
            self.service.confirm(token, "restore")

    def test_safety_backup_failure_aborts_before_handoff(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        with patch.object(self.backups, "create_backup", side_effect=BackupError("failed")):
            with self.assertRaises(RestoreHandoffError):
                self.service.confirm(token, "restore")
        self.assertFalse(self.service.pending)
        self.assertFalse(self.launched)

    def test_prepare_reverifies_selected_and_safety_backups_and_launches_helper(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        with (
            patch.object(self.backups, "verified_backup", wraps=self.backups.verified_backup) as verify,
            patch("tori.restore.restore_skills_from_backup", return_value=Mock()) as restore_skills,
        ):
            status, response = self.service.confirm(token, "restore")
        self.assertEqual(status, 202)
        self.assertTrue(response["handoff"])
        verified_ids = [call.args[0] for call in verify.call_args_list]
        self.assertGreaterEqual(verified_ids.count(self.selected.identifier), 2)
        self.assertIn(response["safety_backup_identifier"], verified_ids)
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(restore_skills.call_args.args[1], self.selected.identifier)
        self.assertEqual(restore_skills.call_args.kwargs["destination"].name, "skills")

    def test_candidate_tampering_is_rejected_by_external_plan_validation(self) -> None:
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan_path = self.launched[0][1] / "restore-plan.json"
        helper = runpy.run_path(str(Path(__file__).parents[1] / "scripts/tori-restore"))
        helper["_validate"].__globals__["TRUSTED_ORIGIN"] = TEST_ORIGIN
        document = helper["_load_plan"](plan_path)
        helper["_validate"](document)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        (Path(plan["candidate_path"]) / "runtime/state.txt").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "candidate changed"):
            helper["_validate"](helper["_load_plan"](plan_path))

    def test_candidate_restores_runtime_but_preserves_current_config(self) -> None:
        (self.project / "tori.toml").write_text("[logging]\nlevel = \"WARNING\"\n", encoding="utf-8")
        current = (self.project / "tori.toml").read_bytes()
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[0][1] / "restore-plan.json").read_text(encoding="utf-8"))
        candidate = Path(plan["candidate_path"])
        self.assertEqual((candidate / "tori.toml").read_bytes(), current)
        self.assertEqual((candidate / "runtime/state.txt").read_text(encoding="utf-8"), "selected-state\n")
        self.assertFalse((candidate / ".venv").exists())
        self.assertEqual(git(candidate, "rev-parse", "HEAD"), self.commit)
        self.assertEqual(git(candidate, "remote", "get-url", "origin"), TEST_ORIGIN)

    def test_backup_git_and_configuration_are_not_restore_inputs(self) -> None:
        (self.project / "tori.toml").write_text("[logging]\nlevel = \"ERROR\"\n", encoding="utf-8")
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[0][1] / "restore-plan.json").read_text(encoding="utf-8"))
        candidate = Path(plan["candidate_path"])
        self.assertEqual((candidate / "tori.toml").read_text(encoding="utf-8"), "[logging]\nlevel = \"ERROR\"\n")
        self.assertNotEqual(
            (candidate / ".git/HEAD").read_bytes(),
            (Path(self.selected.directory) / "project/.git/HEAD").read_bytes() + b"impossible",
        )
        self.assertEqual(git(candidate, "rev-parse", "--is-inside-work-tree"), "true")

    def test_dependency_mismatch_fails_before_handoff(self) -> None:
        (self.project / "requirements.txt").write_text("changed-after-commit\n", encoding="utf-8")
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "different dependency"):
            self.service.confirm(token, "restore")
        self.assertFalse(self.launched)

    def test_runtime_symlink_is_rejected(self) -> None:
        (self.project / "runtime/link").symlink_to("state.txt")
        unsafe = self.backups.create_backup()
        token = self.service.propose(unsafe.identifier)["confirmation"]["token"]
        with self.assertRaisesRegex(RestoreCompatibilityError, "unsafe object"):
            self.service.confirm(token, "restore")
        self.assertFalse(self.launched)

    def test_candidate_is_sibling_and_external_data_is_untouched(self) -> None:
        external = self.base / "finance"
        external.mkdir()
        marker = external / "ledger.txt"
        marker.write_text("private\n", encoding="utf-8")
        before = marker.read_bytes()
        token = self.service.propose(self.selected.identifier)["confirmation"]["token"]
        self.service.confirm(token, "restore")
        plan = json.loads((self.launched[0][1] / "restore-plan.json").read_text(encoding="utf-8"))
        candidate = Path(plan["candidate_path"])
        self.assertEqual(candidate.parent, self.project.parent)
        self.assertNotEqual(candidate, self.project)
        self.assertEqual(marker.read_bytes(), before)

    def test_source_resolver_rejects_untrusted_origin_and_unknown_commit(self) -> None:
        resolver = TrustedSourceResolver(self.project)
        self.assertEqual(TRUSTED_TORI_ORIGIN, "https://github.com/rustedtrust/Tori-LocalAI.git")
        self.assertFalse(resolver.source_is_trusted(self.commit))
        resolver = TrustedSourceResolver(self.project, origin=TEST_ORIGIN)
        self.assertFalse(resolver.source_is_trusted("f" * 40))
        git(self.project, "remote", "set-url", "origin", "https://example.com/not-tori.git")
        self.assertFalse(resolver.source_is_trusted(self.commit))

    def test_canonical_public_origin_is_exact_and_also_pinned_in_helper(self) -> None:
        self.assertEqual(
            runpy.run_path(str(self.project / "scripts/tori-restore"))["TRUSTED_ORIGIN"],
            TRUSTED_TORI_ORIGIN,
        )
        resolver = TrustedSourceResolver(self.project)
        self.assertFalse(resolver.source_is_trusted(self.commit))  # fixture origin is not public
        git(self.project, "remote", "set-url", "origin", TRUSTED_TORI_ORIGIN)
        self.assertTrue(resolver.source_is_trusted(self.commit))
        self.assertFalse(resolver.source_is_trusted("f" * 40))
        for wrong in (
            "https://github.com/other/Tori-LocalAI.git",  # wrong owner
            "https://github.com/rustedtrust/Tori-Other.git",  # wrong repository
            TRUSTED_TORI_ORIGIN.rsplit("/", 1)[0] + "/Tori.git",  # private development repository
            "https://example.invalid/unrelated.git",  # arbitrary remote
            "https://github.com/rustedtrust/Tori-LocalAI",  # different spelling is not implicitly trusted
        ):
            with self.subTest(wrong_origin=wrong):
                git(self.project, "remote", "set-url", "origin", wrong)
                self.assertFalse(resolver.source_is_trusted(self.commit))
        git(self.project, "remote", "remove", "origin")
        self.assertFalse(resolver.source_is_trusted(self.commit))
        self.assertFalse(TrustedSourceResolver(self.project, origin=None).source_is_trusted(self.commit))
        self.assertFalse(TrustedSourceResolver(self.project, origin="").source_is_trusted(self.commit))

    def test_noncanonical_fixture_origin_never_marks_a_backup_eligible(self) -> None:
        default_public = RestoreService(
            self.backups, OperationCoordinator(), project_root=self.project,
            web_port=8765, helper_source=self.project / "scripts/tori-restore",
            launcher=lambda *_: self.fail("wrong-origin restore attempted launch"),
        )
        item = next(record for record in default_public.catalog()["backups"]
                    if record["identifier"] == self.selected.identifier)
        self.assertFalse(item["selectable"])
        self.assertEqual(item["compatibility"], "Legacy/manual recovery")

    def test_native_helper_requires_matching_public_plan_and_verified_source(self) -> None:
        git(self.project, "remote", "set-url", "origin", TRUSTED_TORI_ORIGIN)
        prepared = RestoreService(
            self.backups, OperationCoordinator(), project_root=self.project,
            web_port=8765, helper_source=self.project / "scripts/tori-restore",
            launcher=lambda args, root: self.launched.append((args, root)),
            process_id=99999999,
        )
        token = prepared.propose(self.selected.identifier)["confirmation"]["token"]
        status, _result = prepared.confirm(token, "restore")
        self.assertEqual(status, 202)
        plan_path = self.launched[-1][1] / "restore-plan.json"
        helper = runpy.run_path(str(self.project / "scripts/tori-restore"))
        plan = helper["_load_plan"](plan_path)
        self.assertEqual(plan["trusted_origin"], TRUSTED_TORI_ORIGIN)
        helper["_validate"](plan)
        for wrong in (None, "", TRUSTED_TORI_ORIGIN.rsplit("/", 1)[0] + "/Tori.git", TEST_ORIGIN):
            with self.subTest(plan_origin=wrong), self.assertRaisesRegex(Exception, "invalid bounded values"):
                helper["_validate"]({**plan, "trusted_origin": wrong})


class RestoreHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.helper = runpy.run_path(str(Path(__file__).parents[1] / "scripts/tori-restore"))
        assert cls.helper["_validate"].__globals__["TRUSTED_ORIGIN"] == TRUSTED_TORI_ORIGIN

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _activation_plan(self, *, reuse_venv: bool = True) -> dict[str, object]:
        live = self.root / "Tori"
        candidate = self.root / (".Tori.restore-" + "a" * 32)
        rollback = self.root / (".Tori.rollback-" + "a" * 32)
        evidence = self.root / (".Tori.restore-evidence-" + "a" * 32)
        live.mkdir()
        candidate.mkdir()
        (live / "old.txt").write_text("old", encoding="utf-8")
        (candidate / "new.txt").write_text("new", encoding="utf-8")
        (live / "tori.toml").write_text("local", encoding="utf-8")
        (candidate / "tori.toml").write_text("local", encoding="utf-8")
        if reuse_venv:
            (live / ".venv").mkdir()
            (live / ".venv/marker").write_text("venv", encoding="utf-8")
        return {
            "live": live, "candidate": candidate, "rollback": rollback,
            "evidence": evidence, "reuse_venv": reuse_venv,
            "restart_argv": [str(live / "start-tori.sh")],
            "log": self.root / "restore.log", "health_url": "http://127.0.0.1:8765/api/session",
            "config_sha256": hashlib.sha256(b"local").hexdigest(),
            "operation_id": "a" * 32, "target_commit": "b" * 40,
            "safety_backup_identifier": "Tori_20260907_120000_aaaaaaaaaaaaaaaa",
        }

    def test_helper_refuses_while_originating_process_is_active(self) -> None:
        with self.assertRaisesRegex(Exception, "did not exit"):
            self.helper["_wait_for_exit"](os.getpid(), timeout=0.01)

    def test_successful_activation_uses_rename_and_preserves_venv(self) -> None:
        plan = self._activation_plan()
        process = Mock()
        process.poll.return_value = None
        with patch.dict(self.helper["_activate"].__globals__, {"_start": Mock(return_value=process), "_healthy": Mock(return_value=True)}):
            result = self.helper["_activate"](plan)
        self.assertTrue(result["ok"])
        self.assertTrue((plan["live"] / "new.txt").exists())
        self.assertTrue((plan["live"] / ".venv/marker").exists())
        self.assertTrue((plan["rollback"] / "old.txt").exists())

    def test_startup_failure_triggers_exactly_one_successful_rollback(self) -> None:
        plan = self._activation_plan()
        process = Mock()
        process.poll.return_value = 1
        healthy = Mock(side_effect=[False, True])
        start = Mock(return_value=process)
        with patch.dict(self.helper["_activate"].__globals__, {"_start": start, "_healthy": healthy, "_stop": Mock()}):
            with self.assertRaisesRegex(Exception, "rollback succeeded"):
                self.helper["_activate"](plan)
        self.assertEqual(start.call_count, 2)
        self.assertTrue((plan["live"] / "old.txt").exists())
        self.assertTrue((plan["live"] / ".venv/marker").exists())
        self.assertTrue((plan["evidence"] / "new.txt").exists())

    def test_activation_rename_failure_returns_venv_before_rollback(self) -> None:
        plan = self._activation_plan()
        process = Mock()
        process.poll.return_value = None
        original_rename = os.rename

        def fail_candidate_activation(source, destination):  # type: ignore[no-untyped-def]
            if Path(source) == plan["candidate"] and Path(destination) == plan["live"]:
                raise OSError("synthetic activation collision")
            return original_rename(source, destination)

        with (
            patch("os.rename", side_effect=fail_candidate_activation),
            patch.dict(self.helper["_activate"].__globals__, {"_start": Mock(return_value=process), "_healthy": Mock(return_value=True)}),
        ):
            with self.assertRaisesRegex(Exception, "rollback succeeded"):
                self.helper["_activate"](plan)
        self.assertTrue((plan["live"] / "old.txt").exists())
        self.assertTrue((plan["live"] / ".venv/marker").exists())

    def test_rollback_failure_preserves_evidence_and_stops(self) -> None:
        plan = self._activation_plan()
        process = Mock()
        process.poll.return_value = 1
        start = Mock(return_value=process)
        with patch.dict(self.helper["_activate"].__globals__, {"_start": start, "_healthy": Mock(side_effect=[False, False]), "_stop": Mock()}):
            with self.assertRaisesRegex(Exception, "also failed.*Evidence"):
                self.helper["_activate"](plan)
        self.assertEqual(start.call_count, 2)
        self.assertTrue(plan["evidence"].exists())

    def test_malformed_plan_and_path_escape_are_rejected(self) -> None:
        plan = self.root / "plan.json"
        plan.write_text("{}", encoding="utf-8")
        os.chmod(plan, 0o400)
        with self.assertRaisesRegex(Exception, "unsupported shape"):
            self.helper["_load_plan"](plan)

    def test_plan_symlink_is_rejected(self) -> None:
        target = self.root / "target"
        target.write_text("{}", encoding="utf-8")
        link = self.root / "plan"
        link.symlink_to(target)
        with self.assertRaisesRegex(Exception, "unsafe"):
            self.helper["_load_plan"](link)

    def test_disposable_end_to_end_swap_restart_and_health(self) -> None:
        live = self.root / "Tori"
        live.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        pid_file = self.root / "health.pid"
        health_source = (
            "import http.server,json,os,sys\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            " def do_GET(self):\n"
            "  body=b'{\"ok\":true}'\n"
            "  self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)\n"
            " def log_message(self,*args): pass\n"
            "open(sys.argv[2],'w').write(str(os.getpid()))\n"
            "http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()\n"
        )
        (live / "health.py").write_text(health_source, encoding="utf-8")
        (live / "start-tori.sh").write_text(
            f"#!/bin/sh\nexec {sys.executable} \"$(dirname \"$0\")/health.py\" {port} {pid_file}\n",
            encoding="utf-8",
        )
        os.chmod(live / "start-tori.sh", 0o755)
        (live / ".gitignore").write_text("/runtime/\n/tori.toml\n/.venv/\n", encoding="utf-8")
        git(live, "init", "-b", "main")
        git(live, "config", "user.name", "Tori Tests")
        git(live, "config", "user.email", "tori-tests@example.invalid")
        git(live, "add", ".")
        git(live, "commit", "-m", "source")
        git(live, "remote", "add", "origin", TEST_ORIGIN)
        commit = git(live, "rev-parse", "HEAD")
        (live / "tori.toml").write_text("preserved-config", encoding="utf-8")
        (live / "runtime").mkdir()
        (live / "runtime/state").write_text("before", encoding="utf-8")
        (live / ".venv").mkdir()
        (live / ".venv/marker").write_text("environment", encoding="utf-8")
        operation = "c" * 32
        candidate = self.root / f".Tori.restore-{operation}"
        git(self.root, "clone", "--no-hardlinks", "--no-checkout", str(live), str(candidate))
        git(candidate, "checkout", "-B", "main", commit)
        git(candidate, "remote", "set-url", "origin", TEST_ORIGIN)
        (candidate / "tori.toml").write_text("preserved-config", encoding="utf-8")
        (candidate / "runtime").mkdir()
        (candidate / "runtime/state").write_text("restored", encoding="utf-8")
        backups = self.root / "backups"
        selected_id = "Tori_20260907_120000_aaaaaaaaaaaaaaaa"
        safety_id = "Tori_20260907_120001_bbbbbbbbbbbbbbbb"
        for identifier in (selected_id, safety_id):
            directory = backups / identifier
            directory.mkdir(parents=True)
            (directory / "manifest.json").write_text(identifier, encoding="utf-8")
        handoff = self.root / "handoff"
        handoff.mkdir(mode=0o700)
        plan_path = handoff / "restore-plan.json"
        log_path = handoff / "restore.log"
        result_path = handoff / "result.json"
        document = {
            "schema_version": 1,
            "operation_id": operation,
            "created_at": "2026-09-07T12:00:00Z",
            "selected_backup_identifier": selected_id,
            "selected_backup_directory": str(backups / selected_id),
            "selected_manifest_sha256": hashlib.sha256(selected_id.encode()).hexdigest(),
            "safety_backup_identifier": safety_id,
            "safety_backup_directory": str(backups / safety_id),
            "safety_manifest_sha256": hashlib.sha256(safety_id.encode()).hexdigest(),
            "expected_current_commit": commit,
            "target_commit": commit,
            "trusted_origin": TEST_ORIGIN,
            "config_sha256": hashlib.sha256(b"preserved-config").hexdigest(),
            "candidate_identity_sha256": self.helper["_tree_identity"](candidate),
            "live_project": str(live),
            "candidate_path": str(candidate),
            "rollback_path": str(self.root / f".Tori.rollback-{operation}"),
            "evidence_path": str(self.root / f".Tori.restore-evidence-{operation}"),
            "originating_pid": 99999999,
            "expected_uid": os.geteuid(),
            "expected_gid": os.getegid(),
            "reuse_venv": True,
            "restart_argv": [str(live / "start-tori.sh")],
            "health_url": f"http://127.0.0.1:{port}/api/session",
            "log_path": str(log_path),
            "result_path": str(result_path),
        }
        plan_path.write_text(json.dumps(document), encoding="utf-8")
        os.chmod(plan_path, 0o400)
        # Rewrite only a disposable fixture helper for the synthetic repository;
        # the production helper must remain pinned to the public origin.
        source = (Path(__file__).parents[1] / "scripts/tori-restore").read_text(encoding="utf-8")
        expected = f"TRUSTED_ORIGIN = {json.dumps(TRUSTED_TORI_ORIGIN)}"
        assert source.count(expected) == 1
        fixture_helper = self.root / "fixture-restore"
        fixture_helper.write_text(source.replace(expected, f"TRUSTED_ORIGIN = {TEST_ORIGIN!r}"), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(fixture_helper), str(plan_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        try:
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((live / "runtime/state").read_text(encoding="utf-8"), "restored")
            self.assertEqual((live / "tori.toml").read_text(encoding="utf-8"), "preserved-config")
            self.assertEqual((live / ".venv/marker").read_text(encoding="utf-8"), "environment")
            self.assertEqual(
                (self.root / f".Tori.rollback-{operation}/runtime/state").read_text(encoding="utf-8"),
                "before",
            )
            self.assertTrue(json.loads(result_path.read_text(encoding="utf-8"))["ok"])
        finally:
            if pid_file.exists():
                try:
                    os.killpg(int(pid_file.read_text(encoding="utf-8")), signal.SIGTERM)
                except (OSError, ValueError):
                    pass


if __name__ == "__main__":
    unittest.main()
