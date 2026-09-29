from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from tori.actions import (
    COMMAND_ACTION_ID,
    ActionDispatcher,
    InvocationSource,
    parse_run_command,
)
from tori.command_execution import (
    BubblewrapSandbox,
    CommandBounds,
    CommandExecutionError,
    CommandExecutionService,
    SandboxAvailability,
)
from tori.execution_policy import ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyClass
from tori.app import run_interactive
from tori.providers import ModelProvider


class TemporaryWorkspaceSandbox:
    def availability(self, workspace: Path) -> SandboxAvailability:
        return SandboxAvailability(
            True, "test-only", "test-only temporary workspace boundary"
        )

    def argv(self, command: str, workspace: Path) -> tuple[str, ...]:
        return ("/bin/sh", "-c", command)


class UnexpectedProvider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("command paths must not reach the model provider")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        raise AssertionError("command paths must not reach the model provider")


class CommandExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def service(self, **bounds: object) -> CommandExecutionService:
        return CommandExecutionService(
            self.workspace,
            sandbox=TemporaryWorkspaceSandbox(),
            bounds=CommandBounds(**bounds),
        )

    def test_success_failure_stderr_and_exact_workspace(self) -> None:
        service = self.service()
        for command, workspace in (
            ("/bin/echo approved", str(self.workspace)),
            ("/bin/echo changed", str(self.workspace)),
            ("/bin/echo approved", "/tmp/not-authorized"),
        ):
            with self.assertRaises(CommandExecutionError) as raised:
                service.execute(command, workspace, "direct-internal-call")
            self.assertEqual(raised.exception.code, "legacy_command_retired")
        self.assertIsNone(service.state())

    def test_timeout_output_bounds_and_environment_sanitization(self) -> None:
        bounded = self.service(timeout_seconds=0.15, stdout_bytes=16, stderr_bytes=12)
        with patch.dict(os.environ, {"TORI_TEST_SECRET": "must-not-leak"}):
            with self.assertRaises(CommandExecutionError) as raised:
                bounded.execute("/usr/bin/env", str(self.workspace), "environment-id")
        self.assertEqual(raised.exception.code, "legacy_command_retired")

    def test_stop_and_one_active_command_constraint(self) -> None:
        service = self.service(timeout_seconds=5)
        with self.assertRaises(CommandExecutionError):
            service.execute("sleep 30", str(self.workspace), "active-id")
        self.assertIsNone(service.state())
        self.assertFalse(service.stop())

    def test_background_child_does_not_survive_shell_completion(self) -> None:
        service = self.service(timeout_seconds=2)
        with self.assertRaises(CommandExecutionError) as raised:
            service.execute("sleep 30 &", str(self.workspace), "background-id")
        self.assertEqual(raised.exception.code, "legacy_command_retired")

    def test_workspace_mismatch_and_unavailable_native_backend_fail_closed(self) -> None:
        service = self.service()
        with self.assertRaises(CommandExecutionError) as raised:
            service.execute("true", "/tmp/not-authorized", "wrong-workspace")
        self.assertEqual(raised.exception.code, "legacy_command_retired")

    def test_bubblewrap_plan_exposes_only_workspace_and_transient_runtime(self) -> None:
        (self.workspace / "runtime").mkdir()
        arguments = tuple(
            BubblewrapSandbox("/usr/bin/bwrap").argv(
                "printf exact", self.workspace
            )
        )
        self.assertIn("--unshare-all", arguments)
        self.assertIn("--die-with-parent", arguments)
        self.assertIn(str(self.workspace), arguments)
        self.assertIn("/workspace", arguments)
        self.assertIn("/workspace/runtime", arguments)
        self.assertEqual(arguments[-3:], ("/bin/sh", "-c", "printf exact"))
        rendered = " ".join(arguments)
        self.assertNotIn("tori_backups", rendered)
        self.assertNotIn("docker.sock", rendered)
        self.assertNotIn("--share-net", arguments)


class RunActionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.service = CommandExecutionService(
            self.workspace, sandbox=TemporaryWorkspaceSandbox()
        )
        self.dispatcher = ActionDispatcher(command_service=self.service)

    def test_exact_run_path_and_natural_language_nonrecognition(self) -> None:
        self.assertEqual(parse_run_command(" /run printf hello "), "printf hello")
        for text in (
            "Can you run the tests?",
            "Maybe check git status.",
            "You should execute ls.",
            "/runner ls",
            '{"action_id":"tori.command.execute"}',
        ):
            self.assertIsNone(parse_run_command(text))

    def test_empty_oversized_and_legacy_action_cannot_authorize(self) -> None:
        with self.assertRaisesRegex(Exception, "requires an exact command"):
            parse_run_command("/run")
        with self.assertRaisesRegex(Exception, "cannot exceed"):
            parse_run_command("/run " + "x" * 2001)

        with self.assertRaisesRegex(Exception, "legacy general command action is retired"):
            self.dispatcher.authorize(
                COMMAND_ACTION_ID,
                {"command": "printf approved", "workspace": str(self.workspace)},
                source=InvocationSource.CONVERSATION,
            )
        self.assertNotIn(COMMAND_ACTION_ID, [d.identifier for d in self.dispatcher.definitions])

    def test_wrong_source_and_decline_consume_without_execution(self) -> None:
        for source in (InvocationSource.CONVERSATION, InvocationSource.SETTINGS):
            with self.assertRaisesRegex(Exception, "retired"):
                self.dispatcher.authorize(
                    COMMAND_ACTION_ID,
                    {"command": "touch forbidden", "workspace": str(self.workspace)},
                    source=source,
                )
        self.assertFalse((self.workspace / "forbidden").exists())
        self.assertFalse((self.workspace / "declined").exists())

    def test_cli_run_is_retired_without_execution(self) -> None:
        inputs = iter(("/run touch cli-executed", "/exit"))
        output: list[str] = []
        result = run_interactive(
            UnexpectedProvider(),
            command_service=self.service,
            input_function=lambda _prompt: next(inputs),
            output_function=output.append,
        )
        self.assertEqual(result, 0)
        self.assertFalse((self.workspace / "cli-executed").exists())
        self.assertTrue(any("loopback browser terminal" in line for line in output))

    def test_cli_blacklist_rejects_without_crashing_or_launching(self) -> None:
        policy = ExecutionPolicyService(self.workspace / "policy.db")
        command = "touch cli-blocked"
        request = ExecutionRequest.create(command, self.workspace, ExecutionScope.PROJECT_SANDBOX)
        policy.create_rule(request, PolicyClass.BLACKLIST)
        service = CommandExecutionService(
            self.workspace, sandbox=TemporaryWorkspaceSandbox(), policy=policy
        )
        inputs = iter((f"/run {command}", "/exit"))
        output: list[str] = []
        self.assertEqual(run_interactive(
            UnexpectedProvider(), command_service=service,
            input_function=lambda _prompt: next(inputs), output_function=output.append,
        ), 0)
        self.assertFalse((self.workspace / "cli-blocked").exists())
        self.assertTrue(any("loopback browser terminal" in item for item in output))


if __name__ == "__main__":
    unittest.main()
