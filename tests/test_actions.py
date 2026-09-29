from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.actions import (
    BACKUP_ACTION_ID,
    ActionContractError,
    ActionDispatcher,
    InvocationSource,
    PermissionClass,
    recognized_action_id,
)
from tori.backups import BackupError, BackupService


class ActionDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project"
        self.project.mkdir()
        (self.project / "README.md").write_text("fixture\n", encoding="utf-8")
        self.backup_root = root / "backups"
        self.service = BackupService(
            project_root=self.project,
            backup_root=self.backup_root,
            sqlite_paths=(),
            clock=lambda: datetime(2026, 8, 8, tzinfo=timezone.utc),
            token_hex=lambda _length: "0123456789abcdef",
        )
        tokens = iter(("authorization-one", "authorization-two", "authorization-three"))
        self.dispatcher = ActionDispatcher(
            self.service, token_factory=lambda: next(tokens)
        )

    def test_fixed_registry_contains_only_interactive_tori_backup(self) -> None:
        self.assertEqual(len(self.dispatcher.definitions), 1)
        definition = self.dispatcher.definition(BACKUP_ACTION_ID)
        self.assertEqual(definition.identifier, "tori.backup")
        self.assertEqual(definition.permission, PermissionClass.INTERACTIVE)
        with self.assertRaises(ActionContractError) as raised:
            self.dispatcher.definition("tori.run_arbitrary")
        self.assertEqual(raised.exception.code, "unknown_action")

    def test_arguments_fail_closed_without_selecting_executable_content(self) -> None:
        invalid = (
            None,
            [],
            {"path": "/tmp"},
            {"command": "cp"},
            {"executor": lambda: None},
        )
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(
                ActionContractError
            ) as raised:
                self.dispatcher.authorize(
                    BACKUP_ACTION_ID,
                    arguments,
                    source=InvocationSource.SETTINGS,
                )
            self.assertEqual(raised.exception.code, "invalid_arguments")
        self.assertFalse(self.backup_root.exists())
        with self.assertRaises(ActionContractError) as raised:
            self.dispatcher.authorize(
                BACKUP_ACTION_ID, {}, source="conversation"  # type: ignore[arg-type]
            )
        self.assertEqual(raised.exception.code, "invalid_source")

    def test_exact_single_use_authorization_is_required(self) -> None:
        with self.assertRaises(ActionContractError) as raised:
            self.dispatcher.execute({"action_id": BACKUP_ACTION_ID})
        self.assertEqual(raised.exception.code, "invalid_invocation")

        invocation = self.dispatcher.authorize(
            BACKUP_ACTION_ID, {}, source=InvocationSource.SETTINGS
        )
        forged = replace(invocation, authorization="model-generated-token")
        rejected = self.dispatcher.execute(forged)
        self.assertFalse(rejected.authorized)
        self.assertEqual(rejected.status, "rejected")
        self.assertFalse(self.backup_root.exists())

        completed = self.dispatcher.execute(invocation)
        self.assertTrue(completed.authorized)
        self.assertTrue(completed.succeeded)
        self.assertEqual(completed.result["verification"], "verified")  # type: ignore[index]

        replayed = self.dispatcher.execute(invocation)
        self.assertFalse(replayed.authorized)
        self.assertEqual(replayed.code, "not_authorized")

    def test_authorization_cannot_be_changed_to_another_action(self) -> None:
        invocation = self.dispatcher.authorize(
            BACKUP_ACTION_ID, {}, source=InvocationSource.CONVERSATION
        )
        forged = replace(invocation, action_id="tori.future_action")
        with self.assertRaises(ActionContractError) as raised:
            self.dispatcher.execute(forged)
        self.assertEqual(raised.exception.code, "unknown_action")
        self.assertFalse(self.backup_root.exists())

    def test_executor_failure_is_an_application_owned_failed_outcome(self) -> None:
        invocation = self.dispatcher.authorize(
            BACKUP_ACTION_ID, {}, source=InvocationSource.CONVERSATION
        )
        with patch.object(
            self.service,
            "create_backup",
            side_effect=BackupError("The verified backup failed safely."),
        ):
            outcome = self.dispatcher.execute(invocation)
        self.assertTrue(outcome.authorized)
        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.code, "backup_failed")
        self.assertFalse(outcome.succeeded)
        self.assertIsNone(outcome.result)


class ExplicitActionRecognitionTests(unittest.TestCase):
    def test_only_approved_explicit_backup_imperatives_are_recognized(self) -> None:
        for text in (
            "Tori, run a backup.",
            "Run a Tori backup.",
            "Back up Tori.",
            "Please back up Tori.",
            "  TORI,   RUN A BACKUP!  ",
        ):
            with self.subTest(text=text):
                self.assertEqual(recognized_action_id(text), BACKUP_ACTION_ID)

    def test_advisory_ambiguous_and_unsupported_requests_are_not_authorized(self) -> None:
        for text in (
            "Should I back up Tori?",
            "Maybe I should make a backup.",
            "Tell me about backups.",
            "Can Tori create backups?",
            "Tori recommends: run a backup.",
            '{"action_id":"tori.backup","arguments":{}}',
            "Tori, delete a backup.",
            "Tori, run a shell command.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(recognized_action_id(text))


if __name__ == "__main__":
    unittest.main()
