from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.actions import ActionDefinition, PermissionClass
from tori.scheduled_work import (
    ScheduledCapabilityCatalog,
    ScheduledWorkConflictError,
    ScheduledWorkExecutor,
    ScheduledWorkNotFoundError,
    ScheduledWorkStaleRevisionError,
    ScheduledWorkValidationError,
    SQLiteScheduledWorkStore,
    one_shot_schedule,
)
from tori.scheduled_work_application import ScheduledWorkApplicationService
from tori.scheduled_work_service import ScheduledWorkDraft
from tori.time_context import FakeClock


class ScheduledWorkApplicationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = FakeClock(datetime(2026, 8, 21, 12, tzinfo=timezone.utc))
        counts = {"work": 0, "authorization": 0, "run": 0, "event": 0}

        def identifier(prefix: str) -> str:
            counts[prefix] += 1
            marker = {
                "work": "1",
                "authorization": "2",
                "run": "3",
                "event": "4",
            }[prefix]
            return f"{prefix}-" + marker * 31 + str(counts[prefix])

        self.store = SQLiteScheduledWorkStore(
            Path(self.temporary.name) / "scheduled.db",
            clock=self.clock,
            identifier_factory=identifier,
        )
        self.definition = ActionDefinition(
            "test.scheduled.application",
            "Test scheduled application",
            "Test-only deterministic scheduled capability.",
            PermissionClass.PERSISTENT,
            lambda arguments: dict(arguments),
            lambda arguments, _invocation: dict(arguments),
            scheduled_one_shot_eligible=True,
        )
        self.application = ScheduledWorkApplicationService(self.store)

    def draft(
        self,
        *,
        title: str = "Scheduled application test",
        existing_job_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ScheduledWorkDraft:
        return ScheduledWorkDraft(
            title=title,
            capability_id=self.definition.identifier,
            capability_contract_version=self.definition.contract_version,
            arguments={"label": "alpha"},
            schedule=one_shot_schedule(
                self.clock() + timedelta(hours=1), "America/Chicago"
            ),
            missed_policy="run_when_available",
            existing_job_id=existing_job_id,
            expected_revision=expected_revision,
        )

    def create(self):  # type: ignore[no-untyped-def]
        return self.application.apply_draft(
            self.draft(),
            definition=self.definition,
            confirmation_provenance="explicit_test_confirmation",
            origin_chat_id="chat-" + "a" * 32,
        )

    def test_create_list_get_and_authorization_preserve_canonical_facts(self) -> None:
        created, authorization = self.create()
        self.assertEqual(self.application.revision(), 2)
        self.assertEqual(self.application.list_definitions(), (created,))
        self.assertEqual(self.application.list_runs(), ())
        self.assertEqual(self.application.get_definition(created.identifier), created)
        self.assertEqual(
            self.application.get_authorization(authorization.identifier),
            authorization,
        )
        self.assertEqual(created.origin_chat_id, "chat-" + "a" * 32)

    def test_replace_is_revision_safe_and_preserves_immutable_origin(self) -> None:
        created, original_authorization = self.create()
        draft = self.draft(
            title="Revised scheduled application test",
            existing_job_id=created.identifier,
            expected_revision=created.revision,
        )
        replaced, authorization = self.application.apply_draft(
            draft,
            definition=self.definition,
            confirmation_provenance="explicit_test_edit_confirmation",
        )
        self.assertEqual(replaced.revision, created.revision + 1)
        self.assertEqual(replaced.origin_chat_id, created.origin_chat_id)
        self.assertNotEqual(authorization.identifier, original_authorization.identifier)
        with self.assertRaises(ScheduledWorkStaleRevisionError):
            self.application.apply_draft(
                draft,
                definition=self.definition,
                confirmation_provenance="explicit_stale_confirmation",
            )

    def test_lifecycle_transitions_preserve_store_rules_and_stale_failures(self) -> None:
        created, _authorization = self.create()
        paused = self.application.transition_definition(
            created.identifier,
            expected_revision=created.revision,
            action="pause",
        )
        with self.assertRaises(ScheduledWorkStaleRevisionError):
            self.application.transition_definition(
                created.identifier,
                expected_revision=created.revision,
                action="resume",
            )
        resumed = self.application.transition_definition(
            paused.identifier,
            expected_revision=paused.revision,
            action="resume",
        )
        cancelled = self.application.transition_definition(
            resumed.identifier,
            expected_revision=resumed.revision,
            action="cancel",
        )
        self.assertEqual(cancelled.status, "cancelled")
        with self.assertRaises(ScheduledWorkValidationError):
            self.application.transition_definition(
                cancelled.identifier,
                expected_revision=cancelled.revision,
                action="invalid",  # type: ignore[arg-type]
            )

    def test_history_deletion_preserves_definition_run_ordering(self) -> None:
        created, _authorization = self.create()
        self.clock.advance(timedelta(hours=1))
        run = self.store.claim_due(self.clock())[0]
        result = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((self.definition,))
        ).execute_next()
        self.assertEqual(result.identifier, run.identifier)
        current = self.application.get_definition(created.identifier)
        with self.assertRaises(ScheduledWorkConflictError):
            self.application.delete_definition_history(
                current.identifier, expected_revision=current.revision
            )
        terminal_run = self.application.get_run(run.identifier)
        self.application.delete_run_history(
            terminal_run.identifier, expected_revision=terminal_run.revision
        )
        self.application.delete_definition_history(
            current.identifier, expected_revision=current.revision
        )
        with self.assertRaises(ScheduledWorkNotFoundError):
            self.application.get_definition(current.identifier)

    def test_inconsistent_draft_fails_before_canonical_mutation(self) -> None:
        with self.assertRaises(ScheduledWorkValidationError):
            self.application.apply_draft(
                self.draft(expected_revision=1),
                definition=self.definition,
                confirmation_provenance="invalid_test_confirmation",
            )
        self.assertEqual(self.application.list_definitions(), ())


class ScheduledWorkApplicationArchitectureTests(unittest.TestCase):
    def test_module_has_no_presentation_execution_or_unrelated_domain_dependency(self) -> None:
        path = (
            Path(__file__).parents[1]
            / "src"
            / "tori"
            / "scheduled_work_application.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module or ""
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
        }
        forbidden = {
            "http",
            "tori.web",
            "tori.providers",
            "tori.conversation",
            "tori.conversation_archive",
            "tori.actions",
            "tori.memory_extraction",
            "tori.projects",
            "tori.search_application",
            "tori.tasks",
            "tori.scheduled_work_executor",
            "tori.scheduled_work_service",
        }
        self.assertTrue(imported.isdisjoint(forbidden), imported & forbidden)


if __name__ == "__main__":
    unittest.main()
