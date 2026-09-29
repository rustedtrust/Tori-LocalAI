"""Adversarial policy and durable one-use authority tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tori.actions import COMMAND_ACTION_ID, ActionDispatcher, InvocationSource
from tori.command_execution import CommandExecutionError, CommandExecutionService, SandboxAvailability
from tori.execution_policy import (
    ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyClass,
    PolicyError,
)


class _TemporarySandbox:
    def availability(self, _workspace: Path) -> SandboxAvailability:
        return SandboxAvailability(True, "test", "isolated test workspace")

    def argv(self, command: str, _workspace: Path) -> tuple[str, ...]:
        return ("/bin/sh", "-c", command)


class ExecutionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.other = self.root / "other"
        self.other.mkdir()
        self.path = self.root / "runtime" / "supervised_terminal" / "tori_execution_policy.db"
        self.now = 1000.0
        self.policy = ExecutionPolicyService(self.path, clock=lambda: self.now)

    def request(self, command: str = "git status", *, cwd: Path | None = None,
                scope: ExecutionScope = ExecutionScope.PROJECT_SANDBOX,
                origin: str = "tori") -> ExecutionRequest:
        return ExecutionRequest.create(command, cwd or self.cwd, scope, origin=origin)

    def test_absent_store_is_read_only_and_unknown_requires_approval(self) -> None:
        decision = self.policy.evaluate(self.request("unknown-command --flag"))
        self.assertEqual(decision.outcome, PolicyClass.DEFAULT_ASK)
        self.assertIsNone(decision.rule_id)
        self.assertFalse(self.path.exists())
        with self.assertRaises(PolicyError):
            self.policy.issue_grant(self.request("unknown-command --flag"), "chat-1")
        self.assertFalse(self.path.exists())

    def test_precedence_and_explanations_even_with_conflicting_rows(self) -> None:
        request = self.request()
        white = self.policy.create_rule(request, PolicyClass.WHITELIST)
        self.assertEqual(self.policy.evaluate(request).rule_id, white.identifier)
        self.assertEqual(self.policy.evaluate(request).outcome, PolicyClass.WHITELIST)
        ask = self.policy.create_rule(request, PolicyClass.ALWAYS_ASK)
        decision = self.policy.evaluate(request)
        self.assertEqual((decision.outcome, decision.rule_id), (PolicyClass.ALWAYS_ASK, ask.identifier))
        black = self.policy.create_rule(request, PolicyClass.BLACKLIST)
        decision = self.policy.evaluate(request)
        self.assertEqual((decision.outcome, decision.rule_id), (PolicyClass.BLACKLIST, black.identifier))
        self.assertIn("BLACKLIST", decision.reason)

    def test_always_ask_rejects_whitelist_create_and_update(self) -> None:
        request = self.request()
        self.policy.create_rule(request, PolicyClass.ALWAYS_ASK)
        self.policy.create_rule(request, PolicyClass.BLACKLIST)
        with self.assertRaisesRegex(PolicyError, "cannot be whitelisted"):
            self.policy.create_rule(request, PolicyClass.WHITELIST)
        other = self.policy.create_rule(self.request("printf safe"), PolicyClass.WHITELIST)
        with self.assertRaisesRegex(PolicyError, "cannot be whitelisted"):
            self.policy.update_rule(other.identifier, request, PolicyClass.WHITELIST)

    def test_exact_whitelist_does_not_expand_to_arguments_or_shell(self) -> None:
        self.policy.create_rule(self.request("git status"), PolicyClass.WHITELIST)
        self.assertEqual(self.policy.evaluate(self.request("git status --short")).outcome, PolicyClass.DEFAULT_ASK)
        self.assertEqual(self.policy.evaluate(self.request("git status; rm -rf .")).outcome, PolicyClass.ALWAYS_ASK)
        self.assertEqual(self.policy.evaluate(self.request("printf nvidia-smi")).outcome, PolicyClass.DEFAULT_ASK)
        self.assertEqual(self.policy.evaluate(self.request("git status", cwd=self.other)).outcome, PolicyClass.DEFAULT_ASK)

    def test_high_risk_is_always_ask_and_cannot_be_whitelisted(self) -> None:
        commands = (
            "sudo id", "su root", "sh -c 'id'", "bash -c id", "python -c 'print(1)'",
            "node -e 'console.log(1)'", "perl -e 'print 1'", "rm -rf old",
            "dd if=/dev/zero of=/dev/sdb", "printf x | sh", "echo $(id)",
            "env sudo id", "xargs sh", "MODE=fast sudo id", "command sudo id",
            "eval 'sudo id'", ". script.sh", "! sudo id",
            "apt install example", "systemctl restart foo",
        )
        for command in commands:
            with self.subTest(command=command):
                request = self.request(command)
                decision = self.policy.evaluate(request)
                self.assertEqual(decision.outcome, PolicyClass.ALWAYS_ASK)
                self.assertEqual(decision.rule_id, "application.high_risk")
                with self.assertRaises(PolicyError):
                    self.policy.create_rule(request, PolicyClass.WHITELIST)

    def test_persisted_malformed_matching_row_blocks(self) -> None:
        request = self.request()
        rule = self.policy.create_rule(request, PolicyClass.WHITELIST)
        with sqlite3.connect(self.path) as connection:
            connection.execute("UPDATE policy_rules SET matcher_json='{}' WHERE identifier=?", (rule.identifier,))
        decision = self.policy.evaluate(request)
        self.assertEqual(decision.outcome, PolicyClass.BLACKLIST)
        self.assertEqual(decision.source, "corrupt")

    def test_corrupt_rule_digest_cannot_make_a_blacklist_disappear(self) -> None:
        request = self.request()
        self.policy.create_rule(request, PolicyClass.WHITELIST)
        blocked = self.policy.create_rule(self.request("printf other"), PolicyClass.BLACKLIST)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE policy_rules SET matcher_digest=? WHERE identifier=?",
                ("0" * 64, blocked.identifier),
            )
        decision = self.policy.evaluate(request)
        self.assertEqual(decision.outcome, PolicyClass.BLACKLIST)
        self.assertEqual(decision.source, "corrupt")

    def test_rule_lifecycle_and_reopen(self) -> None:
        request = self.request()
        rule = self.policy.create_rule(request, PolicyClass.BLACKLIST)
        self.assertEqual(len(ExecutionPolicyService(self.path).list_rules()), 1)
        disabled = self.policy.update_rule(rule.identifier, request, PolicyClass.BLACKLIST, enabled=False)
        self.assertFalse(disabled.enabled)
        self.assertEqual(self.policy.evaluate(request).outcome, PolicyClass.DEFAULT_ASK)
        self.policy.remove_rule(rule.identifier)
        self.assertEqual(self.policy.list_rules(), ())

    def test_unsafe_or_incompatible_store_fails_closed_without_repair(self) -> None:
        self.path.parent.mkdir(parents=True)
        target = self.root / "target.db"
        target.write_bytes(b"preserve")
        os.symlink(target, self.path)
        with self.assertRaises(PolicyError):
            self.policy.evaluate(self.request())
        self.assertEqual(target.read_bytes(), b"preserve")
        self.path.unlink()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE policy_metadata(key TEXT,value TEXT)")
            connection.execute("INSERT INTO policy_metadata VALUES('schema_version','99')")
        before = self.path.read_bytes()
        with self.assertRaises(PolicyError):
            self.policy.evaluate(self.request())
        self.assertEqual(self.path.read_bytes(), before)

    def test_grant_replay_expiration_and_all_material_bindings(self) -> None:
        request = self.request("printf safe")
        grant = self.policy.issue_grant(request, "chat-1", approved=True, lifetime_seconds=10)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT token_digest FROM execution_grants").fetchone()
        self.assertNotEqual(row[0], grant.token)
        self.assertTrue(self.policy.consume_grant(grant.token, request, "chat-1"))
        self.assertFalse(self.policy.consume_grant(grant.token, request, "chat-1"))
        variants = (
            (self.request("printf changed"), "chat-1"),
            (self.request("printf safe", cwd=self.other), "chat-1"),
            (self.request("printf safe", scope=ExecutionScope.HOST_USER), "chat-1"),
            (request, "chat-2"),
        )
        for altered, owner in variants:
            with self.subTest(altered=altered, owner=owner):
                fresh = self.policy.issue_grant(request, "chat-1", approved=True)
                self.assertFalse(self.policy.consume_grant(fresh.token, altered, owner))
                self.assertFalse(self.policy.consume_grant(fresh.token, request, "chat-1"))
        expired = self.policy.issue_grant(request, "chat-1", approved=True, lifetime_seconds=10)
        self.now += 11
        self.assertFalse(self.policy.consume_grant(expired.token, request, "chat-1"))

    def test_environment_changes_identity_without_storing_values(self) -> None:
        first = ExecutionRequest.create("env", self.cwd, ExecutionScope.HOST_USER, environment={"MODE": "one"})
        second = ExecutionRequest.create("env", self.cwd, ExecutionScope.HOST_USER, environment={"MODE": "two"})
        self.assertNotEqual(first.identity_digest, second.identity_digest)
        grant = self.policy.issue_grant(first, "chat-1", approved=True)
        self.assertFalse(self.policy.consume_grant(grant.token, second, "chat-1"))
        self.assertNotIn("one", self.path.read_bytes().decode("latin1"))

    def test_policy_edit_revokes_prior_whitelist_grant(self) -> None:
        request = self.request()
        self.policy.create_rule(request, PolicyClass.WHITELIST)
        grant = self.policy.issue_grant(request, "chat-1")
        self.policy.create_rule(request, PolicyClass.ALWAYS_ASK)
        self.assertFalse(self.policy.consume_grant(grant.token, request, "chat-1"))

    def test_legacy_exact_rule_preserves_bounded_command_only(self) -> None:
        safe = self.request(
            "nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu "
            "--format=csv,noheader,nounits"
        )
        rule = self.policy.create_rule(safe, PolicyClass.WHITELIST, source="legacy")
        self.assertEqual(self.policy.evaluate(safe).rule_id, rule.identifier)
        self.assertEqual(self.policy.evaluate(self.request("nvidia-smi")).outcome, PolicyClass.DEFAULT_ASK)

    def test_shell_metadata_preserves_control_syntax(self) -> None:
        request = self.request("git status && echo done")
        self.assertIn("&&", request.shell_operators)
        self.assertIn("git status && echo done", request.matcher["command"])
        self.assertEqual(self.policy.evaluate(request).outcome, PolicyClass.ALWAYS_ASK)
        newline = self.request("git status\nrm -rf old")
        self.assertIn("newline", newline.shell_operators)
        self.assertEqual(self.policy.evaluate(newline).outcome, PolicyClass.ALWAYS_ASK)
        with self.assertRaises(PolicyError):
            replace(request, shell_operators=())

    def test_adversarial_shell_forms_never_inherit_an_exact_whitelist(self) -> None:
        safe = self.request("/bin/echo safe")
        self.policy.create_rule(safe, PolicyClass.WHITELIST)
        high_risk = (
            "/bin/echo safe; id", "/bin/echo safe && id",
            "/bin/echo safe || id", "/bin/echo safe | id",
            "/bin/echo safe > output", "/bin/echo safe 2>> output",
            "/bin/echo $(id)", "/bin/echo `id`",
            "/bin/echo safe\nid", "/bin/sh -c 'echo safe'",
            "/usr/bin/python3 -c 'print(1)'", "/usr/bin/node -e 'console.log(1)'",
        )
        for command in high_risk:
            with self.subTest(command=command):
                request = self.request(command)
                self.assertNotEqual(request.identity_digest, safe.identity_digest)
                self.assertEqual(self.policy.evaluate(request).outcome, PolicyClass.ALWAYS_ASK)
                with self.assertRaises(PolicyError):
                    self.policy.create_rule(request, PolicyClass.WHITELIST)
        # A quoted operator is data for a directly executed argv, but it is
        # still a distinct exact request and receives no inherited authority.
        quoted = self.request("/bin/echo 'safe; id'")
        self.assertEqual(quoted.shell_operators, ())
        self.assertEqual(self.policy.evaluate(quoted).outcome, PolicyClass.DEFAULT_ASK)
        self.assertEqual(self.policy.evaluate(self.request("/bin/echo safe changed")).outcome,
                         PolicyClass.DEFAULT_ASK)

    def test_output_and_human_input_have_no_tori_grant_authority(self) -> None:
        for origin in ("untrusted_output", "human_terminal"):
            request = self.request("echo injected", origin=origin)
            with self.assertRaises(PolicyError):
                self.policy.evaluate(request)
            with self.assertRaises(PolicyError):
                self.policy.issue_grant(request, "chat-1", approved=True)

    def test_legacy_run_action_is_not_a_second_general_command_authority(self) -> None:
        service = CommandExecutionService(self.cwd, sandbox=_TemporarySandbox(), policy=self.policy)
        dispatcher = ActionDispatcher(command_service=service)
        command = "touch protected"
        arguments = {"command": command, "workspace": str(self.cwd)}
        with self.assertRaisesRegex(Exception, "retired"):
            dispatcher.authorize(COMMAND_ACTION_ID, arguments, source=InvocationSource.CONVERSATION)
        self.policy.create_rule(self.request(command), PolicyClass.BLACKLIST)
        self.assertFalse((self.cwd / "protected").exists())
        with self.assertRaisesRegex(Exception, "retired"):
            dispatcher.authorize(COMMAND_ACTION_ID, arguments, source=InvocationSource.CONVERSATION)

    def test_configured_legacy_runner_is_retired_even_with_a_grant(self) -> None:
        service = CommandExecutionService(self.cwd, sandbox=_TemporarySandbox(), policy=self.policy)
        with self.assertRaises(CommandExecutionError) as raised:
            service.execute("touch direct-bypass", str(self.cwd), "direct")
        self.assertEqual(raised.exception.code, "legacy_command_retired")
        self.assertFalse((self.cwd / "direct-bypass").exists())
        dispatcher = ActionDispatcher(command_service=service)
        with self.assertRaisesRegex(Exception, "retired"):
            dispatcher.authorize(COMMAND_ACTION_ID,
                                 {"command": "touch confirmed", "workspace": str(self.cwd)},
                                 source=InvocationSource.CONVERSATION)
        request = self.request("touch confirmed")
        grant = self.policy.issue_grant(request, "legacy-owner", approved=True)
        with self.assertRaises(CommandExecutionError) as raised:
            service.execute("touch confirmed", str(self.cwd), "legacy",
                            grant_token=grant.token, grant_owner="legacy-owner")
        self.assertEqual(raised.exception.code, "legacy_command_retired")
        self.assertFalse((self.cwd / "confirmed").exists())
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(connection.execute("SELECT state FROM execution_grants").fetchone(), ("pending",))


if __name__ == "__main__":
    unittest.main()
