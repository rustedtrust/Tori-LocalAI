from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

from tori.agent_skills import (
    AgentInstructionSkillAdapter,
    AgentSkillAdministration,
    AgentSkillImporter,
    AgentSkillPackageStore,
    restore_skills_from_backup,
)
from tori.backups import (
    BackupBusyError,
    BackupChangedError,
    BackupError,
    BackupSafetyError,
    BackupService,
    BackupVerificationError,
)
from tori.operator_observability import (
    operator_activity_enabled,
    set_operator_activity_enabled,
)
from tori.request_origin import RequestOrigin
from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyClass
from tori.terminal_receipts import TerminalReceiptStore
from tori.research import ResearchLimits, SQLiteResearchStore
from tori.research_application import ResearchApplicationService
from tori.research_worker import FakeResearchWorker
from tori.skills import SQLiteSkillRegistry, SkillApplicationService, SkillComponentKind


NOW = datetime(2026, 8, 8, 17, 30, 45, tzinfo=timezone.utc)


class BackupServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.project = base / "Tori"
        self.backups = base / "backups"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "src" / "app.py").write_text("print('Tori')\n", encoding="utf-8")
        (self.project / ".hidden").write_bytes(b"hidden\x00data")
        (self.project / ".git" / "refs" / "heads").mkdir(parents=True)
        head = "a" * 40
        (self.project / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        (self.project / ".git" / "refs" / "heads" / "main").write_text(head + "\n", encoding="ascii")
        (self.project / ".venv" / "empty").mkdir(parents=True)
        (self.project / "deploy" / "voice" / ".venv" / "bin").mkdir(parents=True)
        (self.project / "deploy" / "voice" / ".venv" / "bin" / "python").write_text(
            "rebuildable environment\n", encoding="utf-8"
        )
        (self.project / "deploy" / "voice" / "runtime.py").write_text(
            "voice runtime\n", encoding="utf-8"
        )
        (self.project / "deploy" / "voice" / ".venvs").mkdir(parents=True)
        (self.project / "deploy" / "voice" / ".venvs" / "marker").write_text(
            "ordinary directory\n", encoding="utf-8"
        )
        (self.project / "deploy" / "voice" / "venv").mkdir(parents=True)
        (self.project / "deploy" / "voice" / "venv" / "marker").write_text(
            "ordinary directory\n", encoding="utf-8"
        )
        (self.project / "models" / "voice" / "small.en").mkdir(parents=True)
        (self.project / "models" / "voice" / "small.en" / "model.bin").write_bytes(
            b"voice model"
        )
        (self.project / "runtime" / "other").mkdir(parents=True)
        (self.project / "runtime" / "other" / "note.txt").write_text("runtime", encoding="utf-8")
        os.chmod(self.project / "src" / "app.py", 0o640)
        os.symlink("src/app.py", self.project / "app-link")

    def service(self, **overrides: object) -> BackupService:
        values = {
            "project_root": self.project,
            "backup_root": self.backups,
            "clock": lambda: NOW,
            "token_hex": lambda _length: "0123456789abcdef",
        }
        values.update(overrides)
        return BackupService(**values)

    def add_sqlite(self, relative: str, values: int = 3) -> Path:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE facts (value INTEGER NOT NULL)")
            connection.executemany("INSERT INTO facts VALUES (?)", ((index,) for index in range(values)))
            connection.commit()
        finally:
            connection.close()
        return path

    def test_maintenance_entry_failure_attributes_guard_and_unwinds_prior_guards(self) -> None:
        events = []
        secret = "PRIVATE_MARKER_TOKEN_123456"

        @contextmanager
        def coding():
            events.append("coding_enter")
            try:
                yield
            finally:
                events.append("coding_exit")

        @contextmanager
        def research():
            events.append("research_enter")
            raise RuntimeError(secret)
            yield

        @contextmanager
        def later():
            events.append("later_enter")
            yield

        service = self.service(coding_work_guard=coding, research_guard=research, skills_guard=later)
        enabled = operator_activity_enabled()
        self.addCleanup(set_operator_activity_enabled, enabled)
        set_operator_activity_enabled(False)  # Serious errors still reach the operator.
        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            with self.assertRaises(BackupBusyError) as failure:
                service.create_backup()
        output = "\n".join(captured.output)
        self.assertEqual(str(failure.exception),
                         "Tori could not enter coordinated maintenance; no verified backup was published.")
        self.assertEqual(events, ["coding_enter", "research_enter", "coding_exit"])
        self.assertIsInstance(failure.exception.__cause__, RuntimeError)
        self.assertIn("stage=backup_maintenance.guard_enter.research", output)
        self.assertIn("guard=research", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertIn("message=redacted", output)
        self.assertEqual(len(captured.output), 1)
        self.assertNotIn(secret, output)
        self.assertNotIn("SECRET", output)
        self.assertFalse(self.backups.exists())
        self.assertFalse(service.in_progress)

    def test_missing_required_guard_is_attributed_to_overall_entry(self) -> None:
        (self.project / "runtime/skills").mkdir(parents=True)
        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            with self.assertRaises(BackupBusyError):
                self.service().create_backup()
        self.assertEqual(len(captured.output), 1)
        self.assertIn("stage=backup_maintenance.entry", captured.output[0])
        self.assertIn("error_type=BackupBusyError", captured.output[0])
        self.assertNotIn("guard=", captured.output[0])
        self.assertFalse(self.backups.exists())

    def test_maintenance_body_failure_attributes_body_and_unwinds_all_guards(self) -> None:
        names = ("coding_work", "research", "remote_chat", "skills", "capability_growth",
                 "companion_initiative", "night_owl")
        events = []

        def guard(name):
            @contextmanager
            def enter():
                events.append(("enter", name))
                try:
                    yield
                finally:
                    events.append(("exit", name))
            return enter

        service = self.service(**{f"{name}_guard": guard(name) for name in names})
        secret = "Private terminal input: /home/user/secret.txt"
        with patch.object(service, "_create_backup_locked", side_effect=RuntimeError(secret)):
            with self.assertLogs("tori.operator", logging.ERROR) as captured:
                with self.assertRaises(BackupBusyError) as failure:
                    service.create_backup()
        self.assertEqual(events, [("enter", name) for name in names]
                         + [("exit", name) for name in reversed(names)])
        output = "\n".join(captured.output)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("stage=backup_maintenance.body", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertIn("message=redacted", output)
        self.assertNotIn("guard=", output)
        self.assertNotIn(secret, output)
        self.assertIsInstance(failure.exception.__cause__, RuntimeError)
        self.assertFalse(self.backups.exists())
        self.assertFalse(service.in_progress)

    def test_maintenance_exit_failure_attributes_guard_and_preserves_publication_order(self) -> None:
        events = []

        @contextmanager
        def coding():
            events.append("coding_enter")
            try:
                yield
            finally:
                events.append("coding_exit")

        @contextmanager
        def research():
            events.append("research_enter")
            try:
                yield
            finally:
                events.append("research_exit")
                raise RuntimeError("private exit detail /home/user/secret")

        service = self.service(coding_work_guard=coding, research_guard=research)
        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            with self.assertRaises(BackupBusyError) as failure:
                service.create_backup()
        output = "\n".join(captured.output)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("stage=backup_maintenance.guard_exit.research", output)
        self.assertIn("guard=research", output)
        self.assertIn("error_type=RuntimeError", output)
        self.assertIn("message=redacted", output)
        self.assertNotIn("/home/user/secret", output)
        self.assertEqual(events, ["coding_enter", "research_enter", "research_exit", "coding_exit"])
        self.assertIsInstance(failure.exception.__cause__, RuntimeError)
        # Existing behavior: publication precedes ExitStack cleanup. Do not alter it here.
        self.assertEqual(len(service.discovered_verified()), 1)
        self.assertFalse(service.in_progress)

    def test_maintenance_multiple_failures_preserve_precedence_and_single_diagnostic(self) -> None:
        @contextmanager
        def coding():
            try:
                yield
            finally:
                raise RuntimeError("private cleanup failure")

        @contextmanager
        def research():
            raise RuntimeError("private entry failure")
            yield

        service = self.service(coding_work_guard=coding, research_guard=research)
        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            with self.assertRaises(BackupBusyError) as failure:
                service.create_backup()
        output = "\n".join(captured.output)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("stage=backup_maintenance.guard_enter.research", output)
        self.assertIn("final_stage=backup_maintenance.guard_exit.coding_work", output)
        self.assertIn("final_error_type=RuntimeError", output)
        self.assertIn("final_message=redacted", output)
        self.assertEqual(str(failure.exception.__cause__), "private cleanup failure")
        self.assertNotIn("private", output)
        self.assertFalse(self.backups.exists())

    def test_maintenance_body_and_exit_failures_report_both_without_publication(self) -> None:
        @contextmanager
        def research():
            try:
                yield
            finally:
                raise RuntimeError("private cleanup marker")

        service = self.service(research_guard=research)
        with patch.object(service, "_create_backup_locked",
                          side_effect=RuntimeError("private body marker")):
            with self.assertLogs("tori.operator", logging.ERROR) as captured:
                with self.assertRaises(BackupBusyError) as failure:
                    service.create_backup()
        self.assertEqual(len(captured.output), 1)
        self.assertIn("stage=backup_maintenance.body", captured.output[0])
        self.assertIn("final_stage=backup_maintenance.guard_exit.research", captured.output[0])
        self.assertIn("final_error_type=RuntimeError", captured.output[0])
        self.assertNotIn("private", captured.output[0])
        self.assertEqual(str(failure.exception.__cause__), "private cleanup marker")
        self.assertFalse(self.backups.exists())

    def test_maintenance_known_static_message_is_labeled_without_raw_text(self) -> None:
        @contextmanager
        def remote():
            raise RuntimeError("Conversation is busy; backup was not published.")
            yield

        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            with self.assertRaises(BackupBusyError):
                self.service(remote_chat_guard=remote).create_backup()
        self.assertIn("message=conversation_busy", captured.output[0])
        self.assertNotIn("Conversation is busy", captured.output[0])

    def test_maintenance_success_is_quiet_and_retains_verified_publication(self) -> None:
        names = ("coding_work", "research", "remote_chat", "skills", "capability_growth",
                 "companion_initiative", "night_owl")
        events = []

        def guard(name):
            @contextmanager
            def enter():
                events.append(("enter", name))
                try:
                    yield
                finally:
                    events.append(("exit", name))
            return enter

        service = self.service(**{f"{name}_guard": guard(name) for name in names})
        with patch("tori.backups.operator_failure") as private_error:
            result = service.create_backup()
        private_error.assert_not_called()
        self.assertEqual(events, [("enter", name) for name in names]
                         + [("exit", name) for name in reversed(names)])
        self.assertEqual(result.verification, "verified")
        self.assertEqual(len(service.discovered_verified()), 1)
        self.assertFalse(service.in_progress)

    def test_complete_tree_is_verified_and_atomically_published(self) -> None:
        database = self.add_sqlite("runtime/memory/tori_memory.db")
        source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        service = self.service(sqlite_paths=(Path("runtime/memory/tori_memory.db"),))

        result = service.create_backup()

        final = Path(result.directory)
        self.assertEqual(final.name, "Tori_20260808_173045_0123456789abcdef")
        self.assertEqual(set(path.name for path in self.backups.iterdir()), {final.name})
        payload = final / "project"
        self.assertEqual((payload / ".hidden").read_bytes(), b"hidden\x00data")
        self.assertFalse((payload / ".venv").exists())
        self.assertFalse((payload / "deploy" / "voice" / ".venv").exists())
        self.assertEqual(
            (payload / "deploy" / "voice" / "runtime.py").read_text(encoding="utf-8"),
            "voice runtime\n",
        )
        self.assertEqual(
            (payload / "models" / "voice" / "small.en" / "model.bin").read_bytes(),
            b"voice model",
        )
        self.assertTrue((payload / "deploy" / "voice" / ".venvs" / "marker").is_file())
        self.assertTrue((payload / "deploy" / "voice" / "venv" / "marker").is_file())
        self.assertEqual((payload / "runtime" / "other" / "note.txt").read_text(), "runtime")
        self.assertTrue((payload / "app-link").is_symlink())
        self.assertEqual(os.readlink(payload / "app-link"), "src/app.py")
        self.assertEqual(stat.S_IMODE(os.lstat(payload / "src" / "app.py").st_mode), 0o640)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), source_hash)
        backup_db = sqlite3.connect(payload / "runtime/memory/tori_memory.db")
        try:
            self.assertEqual(backup_db.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(backup_db.execute("SELECT count(*) FROM facts").fetchone(), (3,))
        finally:
            backup_db.close()
        manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["verification"], {"result": "verified"})
        self.assertEqual(manifest["git"]["head"], "a" * 40)
        self.assertEqual(manifest["tori_version"], "0.9.0-public.1")
        paths = {entry["path"] for entry in manifest["entries"]}
        self.assertIn(".git/HEAD", paths)
        self.assertNotIn(".venv", paths)
        self.assertFalse(any(path.startswith(".venv/") for path in paths))
        self.assertFalse(any(path.startswith("deploy/voice/.venv/") for path in paths))
        self.assertIn("deploy/voice/runtime.py", paths)
        self.assertIn("models/voice/small.en/model.bin", paths)
        self.assertIn("deploy/voice/.venvs/marker", paths)
        self.assertIn("deploy/voice/venv/marker", paths)
        database_record = next(item for item in manifest["entries"] if item["path"] == "runtime/memory/tori_memory.db")
        self.assertEqual(database_record["sqlite_integrity"], "ok")

    def test_default_canonical_sqlite_coverage_includes_operational_store(self) -> None:
        database = self.add_sqlite("runtime/tasks/tori_tasks.db", values=2)
        source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        result = self.service().create_backup()
        copied = Path(result.directory) / "project" / "runtime/tasks/tori_tasks.db"
        connection = sqlite3.connect(copied)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 2)
        finally:
            connection.close()
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), source_hash)

    def test_execution_policy_store_is_backed_up_as_sqlite(self) -> None:
        database = self.project / "runtime/supervised_terminal/tori_execution_policy.db"
        store = ExecutionPolicyService(database)
        request = ExecutionRequest.create("git status", self.project, ExecutionScope.PROJECT_SANDBOX)
        rule = store.create_rule(request, PolicyClass.WHITELIST)
        result = self.service().create_backup()
        copied = Path(result.directory) / "project/runtime/supervised_terminal/tori_execution_policy.db"
        with sqlite3.connect(copied) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT identifier FROM policy_rules").fetchone(), (rule.identifier,))
        self.assertEqual(ExecutionPolicyService(copied).evaluate(request).outcome, PolicyClass.WHITELIST)

    def test_terminal_receipts_are_backed_up_without_transcript(self) -> None:
        database = self.project / "runtime/supervised_terminal/tori_terminal_receipts.db"
        store = TerminalReceiptStore(database)
        store.start("term-test", "a" * 64, "b" * 64, "c" * 64, "HOST_USER", str(self.project), 123.0,
                    "chat-test", "turn-test")
        store.mark_running("term-test")
        store.finish("term-test", state="exited", ended_at=124.0, exit_code=0, reason=None)
        result = self.service().create_backup()
        copied = Path(result.directory) / "project/runtime/supervised_terminal/tori_terminal_receipts.db"
        with sqlite3.connect(copied) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("SELECT state,exit_code FROM terminal_receipts").fetchone(), ("exited", 0))
        self.assertNotIn(b"terminal-output", copied.read_bytes())

    def test_default_canonical_sqlite_coverage_includes_scheduled_work_store(self) -> None:
        database = self.add_sqlite(
            "runtime/scheduled_work/tori_scheduled_work.db", values=3
        )
        source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        result = self.service().create_backup()
        copied = (
            Path(result.directory)
            / "project/runtime/scheduled_work/tori_scheduled_work.db"
        )
        with sqlite3.connect(copied) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 3)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), source_hash)

    def test_default_canonical_sqlite_coverage_includes_tts_profile_store(self) -> None:
        database = self.add_sqlite(
            "runtime/tts_profiles/tori_tts_profiles.db", values=4
        )
        source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        result = self.service().create_backup()
        copied = (
            Path(result.directory)
            / "project/runtime/tts_profiles/tori_tts_profiles.db"
        )
        with sqlite3.connect(copied) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)]
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 4
            )
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), source_hash)

    def test_default_canonical_sqlite_coverage_includes_research_store(self) -> None:
        database = self.add_sqlite(
            "runtime/research/tori_research.db", values=5
        )
        source_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        sessions = database.parent / "sessions" / "research-attempt-test"
        sessions.mkdir(parents=True)
        (sessions / "transient.txt").write_text("not durable evidence")
        result = self.service(research_guard=nullcontext).create_backup()
        copied = (
            Path(result.directory)
            / "project/runtime/research/tori_research.db"
        )
        with sqlite3.connect(copied) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchall(), [("ok",)])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 5)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), source_hash)
        self.assertFalse((Path(result.directory) / "project/runtime/research/sessions").exists())

    def test_research_claim_evidence_and_legacy_report_survive_backup_restore(self) -> None:
        database = self.project / "runtime/research/tori_research.db"
        store = SQLiteResearchStore(database)
        worker = FakeResearchWorker()
        application = ResearchApplicationService(store, worker)
        legacy = store.create_proposal("Historical research", limits=ResearchLimits(),
                                       origin_chat_id=None, origin_chat_revision=None)
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE research_jobs SET state='completed',report='Historical report.' WHERE identifier=?",
                               (legacy.identifier,))
        proposal = application.propose("Research public documentation", origin_chat_id=None,
                                       origin_chat_revision=None)
        started = application.authorize_and_start(proposal.identifier, expected_revision=proposal.revision)
        worker.emit(started.identifier, "source", url="https://example.org/docs", title="Documentation",
                    source_type="primary", authority_reason="public documentation", used_in_report=True)
        worker.emit(started.identifier, "completed", report="The project runs locally.",
                    sources=[{"url": "https://example.org/docs", "used_in_report": True,
                              "relevant_extracts": ["The project runs locally."]}],
                    validation=[{"claim": "The project runs locally.", "status": "supported",
                                 "source_urls": ["https://example.org/docs"],
                                 "report_location": "line 1", "finalization": "kept"}],
                    validation_summary={"supported": 1, "unsupported_presented_as_fact": 0},
                    validation_gate_passed=True, objective_fidelity={"status": "preserved"})
        self.assertEqual(store.get(started.identifier).state, "completed")
        result = self.service(research_guard=nullcontext).create_backup()
        copied = Path(result.directory) / "project/runtime/research/tori_research.db"
        restored = self.project.parent / "restored/research/tori_research.db"
        restored.parent.mkdir(parents=True)
        shutil.copy2(copied, restored)
        reopened = SQLiteResearchStore(restored)
        self.assertEqual(reopened.get(legacy.identifier).report, "Historical report.")
        self.assertEqual(reopened.ledger_status(legacy.identifier), "legacy_report_only")
        self.assertEqual(reopened.ledger_status(started.identifier), "evidence_gated")
        self.assertIn("[SUPPORTED — worker-classified", reopened.get(started.identifier).report)
        self.assertEqual(reopened.claims(started.identifier)[0].support_state, "SUPPORTED")
        self.assertEqual(reopened.evidence_for_claim(started.identifier, 1)[0].source.url,
                         "https://example.org/docs")

    def test_absent_skills_runtime_remains_absent_after_backup(self) -> None:
        skills = self.project / "runtime" / "skills"
        self.assertFalse(skills.exists())
        service = self.service()
        result = service.create_backup()
        self.assertFalse(skills.exists())
        destination = Path(self.temporary.name) / "restore-empty" / "runtime/skills"
        restored = restore_skills_from_backup(
            service, result.identifier, destination=destination
        )
        self.assertFalse(restored.restored)
        self.assertFalse(destination.exists())

    def test_skills_generation_is_guarded_backed_up_without_secrets_and_restored_disabled(self) -> None:
        skills_root = self.project / "runtime" / "skills"
        registry = SQLiteSkillRegistry(skills_root / "registry.sqlite3")
        registry.initialize()
        packages = AgentSkillPackageStore(skills_root / "packages")
        application = SkillApplicationService(
            registry,
            {SkillComponentKind.INSTRUCTION_ONLY: AgentInstructionSkillAdapter(packages)},
        )
        administration = AgentSkillAdministration(application, packages)
        source = Path(self.temporary.name) / "source" / "backup-guide"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: backup-guide\ndescription: A restore fixture.\n---\n\nUse bounded guidance.\n",
            encoding="utf-8",
        )
        origin = RequestOrigin.local_web()
        installed = administration.install(
            AgentSkillImporter(clock=lambda: NOW).inspect_local(
                source, publisher="tests", source_locator="user-selected:backup"
            ),
            origin=origin,
        )
        application.enable(
            installed.manifest.version_ref,
            expected_revision=installed.revision,
            granted_permissions=(),
            origin=origin,
        )
        secret = skills_root / "secrets" / "github.pat"
        secret.parent.mkdir(mode=0o700)
        secret.write_text("TOKEN_MUST_NOT_BE_BACKED_UP", encoding="utf-8")
        result = self.service(skills_guard=administration.backup_guard).create_backup()
        restore_service = self.service(skills_guard=administration.backup_guard)
        payload = restore_service.verified_payload(result.identifier)
        self.assertTrue((payload / "runtime/skills/registry.sqlite3").is_file())
        self.assertFalse((payload / "runtime/skills/secrets").exists())
        self.assertNotIn(
            b"TOKEN_MUST_NOT_BE_BACKED_UP",
            b"".join(
                path.read_bytes() for path in (payload / "runtime/skills").rglob("*")
                if path.is_file()
            ),
        )

        restored_root = Path(self.temporary.name) / "restored" / "runtime" / "skills"
        restored = restore_skills_from_backup(
            restore_service, result.identifier, destination=restored_root
        )
        self.assertTrue(restored.restored)
        self.assertEqual(restored.disabled_count, 1)
        reopened = SQLiteSkillRegistry(restored_root / "registry.sqlite3")
        entry = reopened.get(installed.manifest.version_ref)
        self.assertEqual(entry.state, "disabled")
        AgentSkillPackageStore(restored_root / "packages").verify(
            installed.manifest.version_ref
        )
        backed_skill = next((payload / "runtime/skills/packages").rglob("SKILL.md"))
        os.chmod(backed_skill, 0o600)
        backed_skill.write_text("tampered", encoding="utf-8")
        with self.assertRaises(BackupVerificationError):
            restore_skills_from_backup(
                restore_service,
                result.identifier,
                destination=Path(self.temporary.name) / "rejected" / "runtime/skills",
            )

    def test_skills_runtime_requires_consistency_guard(self) -> None:
        path = self.project / "runtime/skills/registry.sqlite3"
        SQLiteSkillRegistry(path).initialize()
        with self.assertRaises(BackupBusyError):
            self.service().create_backup()

    def test_skills_backup_guard_rejects_missing_managed_package(self) -> None:
        skills_root = self.project / "runtime" / "skills"
        registry = SQLiteSkillRegistry(skills_root / "registry.sqlite3")
        registry.initialize()
        packages = AgentSkillPackageStore(skills_root / "packages")
        application = SkillApplicationService(registry)
        administration = AgentSkillAdministration(application, packages)
        source = Path(self.temporary.name) / "missing-package" / "orphan-guide"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: orphan-guide\ndescription: Missing evidence fixture.\n---\n\nGuide.\n",
            encoding="utf-8",
        )
        inspected = AgentSkillImporter(clock=lambda: NOW).inspect_local(
            source, publisher="tests", source_locator="user-selected:orphan"
        )
        application.install(inspected.manifest, origin=RequestOrigin.local_web())
        with self.assertRaises(BackupBusyError):
            self.service(skills_guard=administration.backup_guard).create_backup()

    def test_symlink_is_not_traversed(self) -> None:
        outside = Path(self.temporary.name) / "outside-secret"
        outside.write_text("do not copy", encoding="utf-8")
        os.symlink(outside, self.project / "outside-link")
        result = self.service().create_backup()
        copied = Path(result.directory) / "project" / "outside-link"
        self.assertTrue(copied.is_symlink())
        self.assertEqual(os.readlink(copied), str(outside))

    def test_parent_swapped_to_symlink_is_never_traversed(self) -> None:
        outside = Path(self.temporary.name) / "outside-directory"
        outside.mkdir()
        (outside / "app.py").write_text("secret outside content", encoding="utf-8")
        original = self.project / "src"
        displaced = Path(self.temporary.name) / "displaced-src"
        service = self.service()
        original_capture = service._capture

        def swap_then_capture(inventory, payload):
            original.rename(displaced)
            os.symlink(outside, original)
            return original_capture(inventory, payload)

        with patch.object(service, "_capture", side_effect=swap_then_capture):
            with self.assertRaises(BackupError):
                service.create_backup()
        self.assertFalse(any(path.name.startswith("Tori_") for path in self.backups.iterdir()))

    def test_absent_root_discovery_is_read_only(self) -> None:
        service = self.service()
        self.assertIsNone(service.latest_verified())
        self.assertFalse(self.backups.exists())

    def test_discovery_ignores_malformed_and_selects_newest_valid(self) -> None:
        first = self.service().create_backup()
        malformed = self.backups / "Tori_99999999_999999_badbadbadbadbadb"
        malformed.mkdir()
        (malformed / "manifest.json").write_text("not json", encoding="utf-8")
        unrelated = self.backups / "other"
        unrelated.mkdir()
        later = datetime(2026, 8, 9, tzinfo=timezone.utc)
        second_service = self.service(
            clock=lambda: later,
            token_hex=lambda _length: "fedcba9876543210",
        )
        second = second_service.create_backup()
        before = sorted(str(path) for path in self.backups.rglob("*"))
        latest = second_service.latest_verified()
        after = sorted(str(path) for path in self.backups.rglob("*"))
        self.assertEqual(latest.identifier, second.identifier)
        self.assertNotEqual(latest.identifier, first.identifier)
        self.assertEqual(after, before)

    def test_existing_root_symlink_and_file_are_rejected(self) -> None:
        destination = Path(self.temporary.name) / "elsewhere"
        destination.mkdir()
        os.symlink(destination, self.backups)
        with self.assertRaises(BackupSafetyError):
            self.service().create_backup()
        with self.assertRaises(BackupSafetyError):
            self.service().latest_verified()
        os.unlink(self.backups)
        self.backups.write_text("unsafe", encoding="utf-8")
        with self.assertRaises(BackupSafetyError):
            self.service().create_backup()

    def test_special_object_fails_and_staging_remains_nonfinal(self) -> None:
        fifo = self.project / "runtime" / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(BackupSafetyError):
            self.service().create_backup()
        names = [path.name for path in self.backups.iterdir()]
        self.assertEqual(names, [".Tori_20260808_173045_0123456789abcdef.incomplete"])

    def test_malformed_known_sqlite_fails_without_source_change(self) -> None:
        path = self.project / "runtime" / "memory" / "tori_memory.db"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"not sqlite")
        before = path.read_bytes()
        with self.assertRaises(BackupError):
            self.service(sqlite_paths=(Path("runtime/memory/tori_memory.db"),)).create_backup()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(any(item.name.startswith("Tori_") for item in self.backups.iterdir()))

    def test_known_database_sidecars_never_mutate_source_or_publish_false_success(self) -> None:
        database = self.add_sqlite("runtime/memory/tori_memory.db")
        sidecar = Path(str(database) + "-journal")
        sidecar.write_bytes(b"ambiguous")
        service = self.service(sqlite_paths=(Path("runtime/memory/tori_memory.db"),))
        with self.assertRaises(BackupError):
            service.create_backup()
        self.assertEqual(sidecar.read_bytes(), b"ambiguous")
        sidecar.unlink()
        unsafe_sidecar = Path(str(database) + "-wal")
        unsafe_sidecar.mkdir()
        unsafe_service = self.service(
            sqlite_paths=(Path("runtime/memory/tori_memory.db"),),
            token_hex=lambda _length: "1111111111111111",
        )
        with self.assertRaises(BackupSafetyError):
            unsafe_service.create_backup()
        unsafe_sidecar.rmdir()
        database.unlink()
        os.symlink("../../other/note.txt", database)
        retry = self.service(
            sqlite_paths=(Path("runtime/memory/tori_memory.db"),),
            token_hex=lambda _length: "2222222222222222",
        )
        with self.assertRaises(BackupSafetyError):
            retry.create_backup()

    def test_changed_inventory_and_verification_failure_never_publish(self) -> None:
        service = self.service()
        original_inventory = service._inventory_source
        calls = 0

        def changed_inventory():
            nonlocal calls
            calls += 1
            result = original_inventory()
            if calls == 2:
                (self.project / "appeared").write_text("late", encoding="utf-8")
                result = original_inventory()
            return result

        with patch.object(service, "_inventory_source", side_effect=changed_inventory):
            with self.assertRaises(BackupChangedError):
                service.create_backup()
        self.assertFalse(any(path.name.startswith("Tori_") for path in self.backups.iterdir()))

        second = self.service(token_hex=lambda _length: "1111111111111111")
        with patch.object(second, "_verify_payload", side_effect=BackupVerificationError("mismatch")):
            with self.assertRaises(BackupVerificationError):
                second.create_backup()
        self.assertFalse(any(path.name.startswith("Tori_") for path in self.backups.iterdir()))

    def test_existing_completed_backup_survives_later_failure(self) -> None:
        first = self.service().create_backup()
        first_manifest = (Path(first.directory) / "manifest.json").read_bytes()
        failing = self.service(token_hex=lambda _length: "1111111111111111")
        with patch.object(failing, "_write_manifest", side_effect=OSError("full")):
            with self.assertRaises(BackupError):
                failing.create_backup()
        self.assertEqual((Path(first.directory) / "manifest.json").read_bytes(), first_manifest)

    def test_final_name_is_absent_until_manifest_verification_finishes(self) -> None:
        service = self.service()
        original = service._verify_manifest

        def inspect_then_verify(staging, manifest):
            self.assertTrue(Path(staging).name.endswith(".incomplete"))
            self.assertFalse((self.backups / manifest["backup_identifier"]).exists())
            original(staging, manifest)

        with patch.object(service, "_verify_manifest", side_effect=inspect_then_verify):
            result = service.create_backup()
        self.assertTrue(Path(result.directory).is_dir())

    def test_destination_collision_never_overwrites(self) -> None:
        final = self.backups / "Tori_20260808_173045_0123456789abcdef"
        final.parent.mkdir()
        final.write_text("existing", encoding="utf-8")
        with self.assertRaises(BackupSafetyError):
            self.service().create_backup()
        self.assertEqual(final.read_text(encoding="utf-8"), "existing")

    def test_one_backup_at_a_time_and_retry_after_failure(self) -> None:
        tokens = iter(("0123456789abcdef", "1111111111111111"))
        service = self.service(token_hex=lambda _length: next(tokens))
        entered = threading.Event()
        release = threading.Event()
        original_capture = service._capture

        def blocked_capture(*args):
            entered.set()
            release.wait(5)
            return original_capture(*args)

        errors: list[Exception] = []
        with patch.object(service, "_capture", side_effect=blocked_capture):
            worker = threading.Thread(target=lambda: self._run_backup(service, errors))
            worker.start()
            self.assertTrue(entered.wait(2))
            self.assertTrue(service.in_progress)
            with self.assertRaises(BackupBusyError):
                service.create_backup()
            release.set()
            worker.join(5)
        self.assertFalse(errors)
        self.assertFalse(service.in_progress)
        self.assertTrue(Path(service.create_backup().directory).is_dir())

    def test_sqlite_writer_activity_produces_an_integral_snapshot(self) -> None:
        database = self.add_sqlite("runtime/memory/tori_memory.db", values=100)
        stop = threading.Event()
        started = threading.Event()

        def write_rows() -> None:
            connection = sqlite3.connect(database, timeout=2)
            try:
                index = 100
                while not stop.is_set():
                    connection.execute("INSERT INTO facts VALUES (?)", (index,))
                    connection.commit()
                    index += 1
                    started.set()
                    time.sleep(0.001)
            finally:
                connection.close()

        writer = threading.Thread(target=write_rows)
        writer.start()
        self.assertTrue(started.wait(2))
        try:
            result = self.service(
                sqlite_paths=(Path("runtime/memory/tori_memory.db"),)
            ).create_backup()
        finally:
            stop.set()
            writer.join(2)
        backup_database = Path(result.directory) / "project/runtime/memory/tori_memory.db"
        connection = sqlite3.connect(backup_database)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            captured = connection.execute("SELECT count(*) FROM facts").fetchone()[0]
        finally:
            connection.close()
        self.assertGreaterEqual(captured, 100)

    @staticmethod
    def _run_backup(service: BackupService, errors: list[Exception]) -> None:
        try:
            service.create_backup()
        except Exception as exc:  # pragma: no cover - assertion transport
            errors.append(exc)


if __name__ == "__main__":
    unittest.main()
