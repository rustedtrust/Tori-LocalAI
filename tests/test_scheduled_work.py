from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import os
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest

from tori.actions import (
    ActionContractError,
    ActionDefinition,
    ActionDispatcher,
    CapabilityAvailability,
    PermissionClass,
)
from tori.backups import BackupService
from tori.command_execution import CommandExecutionService, SandboxAvailability
from tori.scheduled_work import (
    ScheduledCapabilityCatalog,
    ScheduledCapabilityError,
    ScheduledWorkConflictError,
    ScheduledWorkCoordinator,
    ScheduledWorkCorruptError,
    ScheduledWorkExecutor,
    ScheduledWorkNotFoundError,
    ScheduledWorkStaleRevisionError,
    ScheduledWorkUnavailableError,
    ScheduledWorkValidationError,
    ScheduledWorkVersionError,
    SQLiteScheduledWorkStore,
    daily_schedule,
    one_shot_schedule,
    weekly_schedule,
)
from tori.time_context import FakeClock


class Recorder:
    def __init__(self) -> None:
        self.values: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self.block = threading.Event()
        self.block.set()
        self.fail = False

    def execute(self, arguments, invocation_id):  # type: ignore[no-untyped-def]
        self.block.wait(2)
        if self.fail:
            raise SyntheticCapabilityError("Synthetic scheduled failure.")
        with self.lock:
            self.values.append((invocation_id, arguments["label"]))
        return {"label": arguments["label"], "recorded": True}


class SyntheticCapabilityError(RuntimeError):
    code = "synthetic_failure"


def record_definition(recorder: Recorder) -> ActionDefinition:
    def validate(arguments):  # type: ignore[no-untyped-def]
        if (
            not isinstance(arguments, dict)
            or set(arguments) != {"label"}
            or not isinstance(arguments["label"], str)
            or not 1 <= len(arguments["label"]) <= 40
        ):
            raise ActionContractError("The test label is invalid.", code="invalid_arguments")
        return {"label": arguments["label"]}

    def validate_result(result):  # type: ignore[no-untyped-def]
        if not isinstance(result, dict) or set(result) != {"label", "recorded"}:
            raise ActionContractError("The test result is invalid.", code="invalid_result")
        return result

    return ActionDefinition(
        "test.scheduled.record",
        "Record a deterministic test event",
        "Test-only injected scheduled capability.",
        PermissionClass.PERSISTENT,
        validate,
        recorder.execute,
        scheduled_one_shot_eligible=True,
        scheduled_recurring_eligible=True,
        _validate_result=validate_result,
    )


class _UnavailableSandbox:
    def availability(self, workspace):  # type: ignore[no-untyped-def]
        return SandboxAvailability(False, "test", "disabled", "unavailable")

    def argv(self, command, workspace):  # type: ignore[no-untyped-def]
        raise AssertionError("must not execute")


class ScheduledWorkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.clock = FakeClock(datetime(2026, 8, 11, 12, tzinfo=timezone.utc))
        self.store = SQLiteScheduledWorkStore(
            self.root / "runtime" / "scheduled_work" / "scheduled.db",
            clock=self.clock,
        )
        self.recorder = Recorder()
        self.definition = record_definition(self.recorder)
        self.catalog = ScheduledCapabilityCatalog((self.definition,))

    def create(
        self,
        *,
        schedule=None,  # type: ignore[no-untyped-def]
        policy: str = "run_when_available",
        title: str = "Record test event",
        origin_chat_id: str | None = None,
    ):
        return self.store.create_definition(
            title=title,
            definition=self.definition,
            arguments={"label": "alpha"},
            schedule=schedule or one_shot_schedule(
                self.clock() + timedelta(minutes=1), "America/Chicago"
            ),
            missed_policy=policy,
            confirmation_provenance="explicit_test_confirmation",
            origin_chat_id=origin_chat_id,
        )

    def test_exact_schema_modes_and_unexpected_schema_refusal(self) -> None:
        self.store.initialize()
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.store.path.parent).st_mode & 0o777, 0o700)
        with sqlite3.connect(self.store.path) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertEqual(tables, {
                "scheduled_work_metadata", "scheduled_work_state",
                "scheduled_work_definitions", "scheduled_authorizations",
                "scheduled_runs", "scheduled_notifications",
            })
            definition_columns = [
                row[1] for row in connection.execute(
                    "PRAGMA table_info(scheduled_work_definitions)"
                )
            ]
            notification_columns = [
                row[1] for row in connection.execute(
                    "PRAGMA table_info(scheduled_notifications)"
                )
            ]
            self.assertEqual(definition_columns[-1], "origin_chat_id")
            self.assertEqual(notification_columns[-1], "origin_chat_id")
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaises(ScheduledWorkCorruptError):
            self.store.initialize()

    def test_future_schema_and_storage_symlink_fail_closed(self) -> None:
        self.store.initialize()
        with sqlite3.connect(self.store.path) as connection:
            connection.execute(
                "UPDATE scheduled_work_metadata SET value='99' WHERE key='schema_version'"
            )
        with self.assertRaises(ScheduledWorkVersionError):
            self.store.initialize()

        unsafe = self.root / "unsafe.db"
        unsafe.symlink_to(self.store.path)
        with self.assertRaises(ScheduledWorkUnavailableError):
            SQLiteScheduledWorkStore(unsafe).initialize()

    def test_catalog_defaults_and_production_eligibility(self) -> None:
        inert = ActionDefinition(
            "test.inert", "Inert", "Inert", PermissionClass.INTERACTIVE,
            lambda arguments: {}, lambda arguments, invocation: {},
        )
        catalog = ScheduledCapabilityCatalog((inert,))
        for mode in ("one_shot", "recurring"):
            with self.subTest(mode=mode), self.assertRaises(ScheduledCapabilityError):
                catalog.validate("test.inert", 1, {}, mode)

        project = self.root / "project"
        project.mkdir()
        (project / "README.md").write_text("test\n", encoding="utf-8")
        backup = BackupService(
            project_root=project, backup_root=self.root / "backups", sqlite_paths=()
        )
        command = CommandExecutionService(project, sandbox=_UnavailableSandbox())
        dispatcher = ActionDispatcher(backup, command_service=command)
        backup_definition = dispatcher.definition("tori.backup")
        self.assertTrue(backup_definition.interactive_eligible)
        self.assertTrue(backup_definition.scheduled_one_shot_eligible)
        self.assertFalse(backup_definition.scheduled_recurring_eligible)
        with self.assertRaises(ActionContractError):
            dispatcher.definition("tori.command.execute")
        self.assertNotIn("tori.command.execute", [item.identifier for item in dispatcher.definitions])
        with self.assertRaises(ScheduledCapabilityError):
            ScheduledCapabilityCatalog((backup_definition,)).validate(
                "tori.backup", 1, {}, "recurring"
            )
        with self.assertRaises(ScheduledCapabilityError):
            ScheduledCapabilityCatalog(dispatcher.definitions).validate(
                "tori.command.execute", 1,
                {"command": "true", "workspace": str(project)}, "one_shot"
            )
        self.assertEqual(self.store.list_definitions(), ())

    def test_immutable_authorization_and_material_edit(self) -> None:
        origin = "chat-" + "a" * 32
        job, original = self.create(origin_chat_id=origin)
        replacement_schedule = one_shot_schedule(
            self.clock() + timedelta(hours=2), "America/Chicago"
        )
        changed, replacement = self.store.replace_definition(
            job.identifier,
            expected_revision=job.revision,
            title="Changed scheduled work",
            definition=self.definition,
            arguments={"label": "beta"},
            schedule=replacement_schedule,
            missed_policy="skip_if_missed",
            confirmation_provenance="explicit_edit_confirmation",
        )
        self.assertEqual(changed.revision, 2)
        self.assertNotEqual(replacement.identifier, original.identifier)
        self.assertEqual(self.store.get_authorization(original.identifier).status, "superseded")
        self.assertEqual(self.store.get_authorization(original.identifier).arguments_json, original.arguments_json)
        self.assertEqual(replacement.job_revision, 2)
        self.assertEqual(replacement.missed_policy, "skip_if_missed")
        self.assertEqual(changed.origin_chat_id, origin)
        with self.assertRaises(ScheduledWorkStaleRevisionError):
            self.store.replace_definition(
                job.identifier, expected_revision=1, title="stale",
                definition=self.definition, arguments={"label": "x"},
                schedule=replacement_schedule, missed_policy="run_when_available",
                confirmation_provenance="stale_confirmation",
            )

    def test_origin_is_opaque_immutable_and_snapshotted_to_notification(self) -> None:
        origin = "chat-" + "b" * 32
        job, _authorization = self.create(origin_chat_id=origin)
        self.assertEqual(job.origin_chat_id, origin)
        self.clock.advance(timedelta(minutes=1))
        self.store.claim_due(self.clock())
        result = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertIsNotNone(result)
        notification = self.store.pending_notifications()[0]
        self.assertEqual(notification.origin_chat_id, origin)
        with self.assertRaises(ScheduledWorkConflictError):
            self.store.mark_notification_archived(
                result.identifier,  # type: ignore[union-attr]
                notification.event_identifier,
                chat_id="chat-" + "c" * 32,
            )
        archived = self.store.mark_notification_archived(
            result.identifier,  # type: ignore[union-attr]
            notification.event_identifier,
            chat_id=origin,
        )
        self.assertEqual(archived.origin_chat_id, origin)
        self.assertEqual(archived.chat_id, origin)

    def test_management_origin_defaults_null_and_invalid_origin_is_rejected(self) -> None:
        created, _authorization = self.create()
        self.assertIsNone(created.origin_chat_id)
        with self.assertRaisesRegex(ScheduledWorkValidationError, "origin chat"):
            self.create(origin_chat_id="chat-user-selected")
        self.assertEqual(len(self.store.list_definitions()), 1)

    def test_pause_resume_cancel_preserve_origin(self) -> None:
        origin = "chat-" + "d" * 32
        job, _authorization = self.create(origin_chat_id=origin)
        paused = self.store.pause_definition(
            job.identifier, expected_revision=job.revision
        )
        resumed = self.store.resume_definition(
            paused.identifier, expected_revision=paused.revision
        )
        cancelled = self.store.cancel_definition(
            resumed.identifier, expected_revision=resumed.revision
        )
        self.assertEqual(
            {paused.origin_chat_id, resumed.origin_chat_id, cancelled.origin_chat_id},
            {origin},
        )

    def test_one_shot_claim_executes_once_and_exhausts(self) -> None:
        job, authorization = self.create()
        self.clock.advance(timedelta(minutes=1))
        first = self.store.claim_due(self.clock())
        second = self.store.claim_due(self.clock())
        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertEqual(self.store.get_definition(job.identifier).status, "completed")
        self.assertEqual(self.store.get_authorization(authorization.identifier).status, "exhausted")
        result = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.result, {"label": "alpha", "recorded": True})
        self.assertEqual(len(self.recorder.values), 1)
        self.assertEqual(len(self.store.pending_notifications()), 1)

    def test_simultaneous_scans_have_one_occurrence_winner(self) -> None:
        self.create()
        self.clock.advance(timedelta(minutes=1))
        second_store = SQLiteScheduledWorkStore(self.store.path, clock=self.clock)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda store: store.claim_due(self.clock()), (
                self.store, second_store,
            )))
        self.assertEqual(sum(len(result) for result in results), 1)
        self.assertEqual(len(self.store.list_runs()), 1)

    def test_daily_weekly_recurrence_and_failure_preserve_parent(self) -> None:
        daily, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(7, 1), "America/Chicago"
        ))
        weekly, _ = self.create(schedule=weekly_schedule(
            date(2026, 8, 11), time(7, 1), "America/Chicago", (1, 4)
        ), title="Weekly")
        self.clock.set(datetime(2026, 8, 11, 12, 1, tzinfo=timezone.utc))
        runs = self.store.claim_due(self.clock())
        self.assertEqual(len(runs), 2)
        self.recorder.fail = True
        executor = ScheduledWorkExecutor(self.store, self.catalog)
        self.assertEqual(executor.execute_next().status, "failed")
        self.assertEqual(executor.execute_next().status, "failed")
        self.assertEqual(self.store.get_definition(daily.identifier).status, "active")
        self.assertEqual(self.store.get_definition(weekly.identifier).status, "active")
        self.assertGreater(self.store.get_definition(daily.identifier).next_occurrence_utc, runs[0].scheduled_occurrence_utc)

    def _due_recurring(self):
        job, authorization = self.create(
            schedule=daily_schedule(date(2026, 8, 11), time(7, 1), "America/Chicago")
        )
        self.clock.set(datetime(2026, 8, 12, 13, tzinfo=timezone.utc))
        return job, authorization

    def test_recurring_advancement_preserves_unchanged_authorization(self) -> None:
        job, original = self._due_recurring()
        first = self.store.claim_due(self.clock())
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].definition_revision, 1)
        advanced = self.store.get_definition(job.identifier)
        authorization = self.store.get_authorization(original.identifier)
        self.assertEqual(advanced.revision, 2)
        self.assertEqual(authorization.job_revision, 1)
        self.assertEqual(authorization.status, "active")
        self.assertEqual(authorization.arguments_json, original.arguments_json)
        self.assertEqual(authorization.schedule_json, original.schedule_json)
        self.assertGreater(advanced.next_occurrence_utc, first[0].scheduled_occurrence_utc)
        second = self.store.claim_due(self.clock())
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].status, "queued")
        self.assertEqual(second[0].definition_revision, 2)
        recovered = self.store.recover_startup(
            self.clock() + timedelta(days=2)
        )
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].job_id, job.identifier)
        self.assertEqual(recovered[0].definition_revision, 3)
        final = self.store.get_definition(job.identifier)
        final_authorization = self.store.get_authorization(original.identifier)
        self.assertEqual(final.revision, 4)
        self.assertEqual(final_authorization.job_revision, 1)
        self.assertEqual(final_authorization.status, "active")

    def test_recurring_execution_after_operational_advancement(self) -> None:
        job, _original = self._due_recurring()
        first = self.store.claim_due(self.clock())[0]
        result = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertEqual(result.identifier, first.identifier)
        self.assertEqual(result.status, "succeeded")
        second = self.store.claim_due(self.clock())
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].definition_revision, 2)
        result = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertEqual(result.identifier, second[0].identifier)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(self.recorder.values), 2)
        self.assertEqual(
            self.store.get_authorization(job.current_authorization_id).job_revision, 1
        )

    def test_pause_resume_preserves_authorization_binding(self) -> None:
        job, original = self.create(
            schedule=daily_schedule(date(2026, 8, 11), time(7, 1), "America/Chicago")
        )
        paused = self.store.pause_definition(job.identifier, expected_revision=job.revision)
        resumed = self.store.resume_definition(
            paused.identifier, expected_revision=paused.revision
        )
        authorization = self.store.get_authorization(original.identifier)
        self.assertEqual(authorization.job_revision, 1)
        self.assertGreater(resumed.revision, authorization.job_revision)
        self.clock.set(datetime(2026, 8, 13, 13, tzinfo=timezone.utc))
        claimed = self.store.claim_due(self.clock())
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].job_id, job.identifier)

    def test_material_changes_and_future_revision_fail_closed(self) -> None:
        due = datetime(2026, 8, 12, 13, tzinfo=timezone.utc)
        cases = (
            ("arguments",
             "UPDATE scheduled_work_definitions SET arguments_json=? WHERE identifier=?",
             ('{"label":"tampered"}',)),
            ("schedule",
             "UPDATE scheduled_work_definitions SET schedule_json=? WHERE identifier=?",
             ('{"kind":"daily","timezone":"America/Chicago",'
               '"start_date":"2026-08-11","local_time":"07:02:00"}',)),
            ("capability",
             "UPDATE scheduled_work_definitions SET capability_id=?,capability_contract_version=? "
             "WHERE identifier=?",
             ("test.scheduled.other", 9)),
            ("missed_policy",
             "UPDATE scheduled_work_definitions SET missed_policy='skip_if_missed' "
             "WHERE identifier=?",
             ()),
            ("future_revision",
             "UPDATE scheduled_authorizations SET job_revision=2 WHERE job_id=?",
             ()),
        )
        for index, (name, sql, params) in enumerate(cases):
            with self.subTest(case=name):
                self.clock.set(datetime(2026, 8, 11, 12, tzinfo=timezone.utc))
                store = SQLiteScheduledWorkStore(
                    self.root / "runtime" / f"tamper-{index}.db", clock=self.clock,
                )
                job, _authorization = store.create_definition(
                    title="Tamper target",
                    definition=self.definition,
                    arguments={"label": "alpha"},
                    schedule=daily_schedule(
                        date(2026, 8, 11), time(7, 1), "America/Chicago"
                    ),
                    missed_policy="run_when_available",
                    confirmation_provenance="explicit_test_confirmation",
                )
                self.clock.set(due)
                with sqlite3.connect(store.path) as connection:
                    connection.execute(sql, params + (job.identifier,))
                with self.assertRaises(ScheduledWorkConflictError):
                    store.claim_due(self.clock())

    def test_startup_missed_policies_are_bounded(self) -> None:
        run_job, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(8), "America/Chicago"
        ))
        skip_job, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(8), "America/Chicago"
        ), policy="skip_if_missed", title="Skip")
        self.clock.set(datetime(2036, 8, 11, 18, tzinfo=timezone.utc))
        recovered = self.store.recover_startup(self.clock())
        self.assertEqual(len(recovered), 2)
        by_job = {run.job_id: run for run in recovered}
        self.assertEqual(by_job[run_job.identifier].status, "queued")
        self.assertEqual(by_job[skip_job.identifier].status, "skipped")
        self.assertGreater(by_job[run_job.identifier].missed_occurrence_count, 3000)
        self.assertEqual(len(self.store.list_runs()), 2)
        self.assertGreater(
            self.store.get_definition(run_job.identifier).next_occurrence_utc,
            self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def test_one_shot_startup_missed_policies_are_truthful_and_unique(self) -> None:
        run_job, _ = self.create()
        skip_job, _ = self.create(policy="skip_if_missed", title="Skip one shot")
        self.clock.advance(timedelta(days=1))
        recovered = self.store.recover_startup(self.clock())
        by_job = {run.job_id: run for run in recovered}
        self.assertEqual(by_job[run_job.identifier].status, "queued")
        self.assertEqual(by_job[skip_job.identifier].status, "skipped")
        self.assertEqual(by_job[run_job.identifier].missed_occurrence_count, 1)
        self.assertEqual(self.store.recover_startup(self.clock()), ())
        self.assertEqual(len(self.store.list_runs()), 2)
        self.assertEqual(self.store.get_definition(run_job.identifier).status, "completed")
        self.assertEqual(self.store.get_definition(skip_job.identifier).status, "completed")

    def test_queued_restart_executes_once_if_authority_remains_valid(self) -> None:
        self.create()
        self.clock.advance(timedelta(minutes=1))
        queued = self.store.claim_due(self.clock())[0]
        self.assertEqual(self.store.recover_startup(self.clock()), ())
        result = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertEqual(result.identifier, queued.identifier)
        self.assertEqual(result.status, "succeeded")
        self.assertIsNone(ScheduledWorkExecutor(self.store, self.catalog).execute_next())

    def test_unavailable_or_unknown_capability_fails_before_work_starts(self) -> None:
        unavailable = ActionDefinition(
            "test.scheduled.unavailable", "Unavailable", "test only",
            PermissionClass.PERSISTENT, lambda arguments: {},
            lambda arguments, invocation: self.fail("executor must not run"),
            scheduled_one_shot_eligible=True,
            _availability=lambda: CapabilityAvailability(
                False, "administrator_disabled", "The test capability is disabled."
            ),
        )
        job, _ = self.store.create_definition(
            title="Unavailable", definition=unavailable, arguments={},
            schedule=one_shot_schedule(self.clock(), "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="explicit_test_confirmation",
        )
        self.store.claim_due(self.clock())
        failed = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog((unavailable,))
        ).execute_next()
        self.assertEqual(failed.status, "failed")
        self.assertFalse(failed.work_started)
        self.assertEqual(failed.failure_code, "administrator_disabled")
        self.assertEqual(self.store.get_definition(job.identifier).status, "completed")

        other, _ = self.create(title="Missing catalog capability")
        self.clock.advance(timedelta(minutes=1))
        self.store.claim_due(self.clock())
        missing = ScheduledWorkExecutor(
            self.store, ScheduledCapabilityCatalog(())
        ).execute_next()
        self.assertEqual(missing.status, "failed")
        self.assertFalse(missing.work_started)
        self.assertEqual(missing.failure_code, "unknown_capability")

    def test_scheduled_backup_busy_is_a_truthful_nonstarted_failure(self) -> None:
        project = self.root / "backup-project"
        project.mkdir()
        backup = BackupService(
            project_root=project, backup_root=self.root / "backup-output",
            sqlite_paths=(), clock=self.clock,
        )
        definition = ActionDispatcher(backup).definition("tori.backup")
        job, _ = self.store.create_definition(
            title="Back up Tori", definition=definition, arguments={},
            schedule=one_shot_schedule(self.clock(), "America/Chicago"),
            missed_policy="run_when_available",
            confirmation_provenance="explicit_test_confirmation",
        )
        self.store.claim_due(self.clock())
        self.assertTrue(backup._lock.acquire(blocking=False))
        try:
            failed = ScheduledWorkExecutor(
                self.store, ScheduledCapabilityCatalog((definition,))
            ).execute_next()
        finally:
            backup._lock.release()
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.failure_code, "backup_in_progress")
        self.assertFalse(failed.work_started)
        self.assertEqual(self.store.get_definition(job.identifier).status, "completed")

    def test_paused_interval_never_catches_up(self) -> None:
        job, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(8), "America/Chicago"
        ))
        paused = self.store.pause_definition(job.identifier, expected_revision=1)
        self.clock.advance(timedelta(days=30))
        self.assertEqual(self.store.recover_startup(self.clock()), ())
        resumed = self.store.resume_definition(
            job.identifier, expected_revision=paused.revision
        )
        self.assertEqual(resumed.status, "active")
        self.assertGreater(resumed.next_occurrence_utc, self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.assertEqual(self.store.list_runs(), ())

    def test_spring_gap_skips_and_fall_overlap_uses_first_occurrence(self) -> None:
        self.clock.set(datetime(2026, 3, 7, 12, tzinfo=timezone.utc))
        spring, _ = self.create(schedule=daily_schedule(
            date(2026, 3, 8), time(2, 30), "America/Chicago"
        ))
        self.assertEqual(self.store.get_definition(spring.identifier).next_occurrence_utc, "2026-03-08T08:00:00Z")
        self.clock.set(datetime(2026, 3, 8, 8, tzinfo=timezone.utc))
        skipped = self.store.claim_due(self.clock())[0]
        self.assertEqual(skipped.status, "skipped")
        self.assertEqual(skipped.failure_code, "dst_nonexistent_local_time")

        self.clock.set(datetime(2026, 10, 31, 12, tzinfo=timezone.utc))
        fall, _ = self.create(schedule=daily_schedule(
            date(2026, 11, 1), time(1, 30), "America/Chicago"
        ), title="Fall overlap")
        self.assertEqual(self.store.get_definition(fall.identifier).next_occurrence_utc, "2026-11-01T06:30:00Z")

    def test_running_recovery_is_interrupted_and_never_retried(self) -> None:
        self.create()
        self.clock.advance(timedelta(minutes=1))
        run = self.store.claim_due(self.clock())[0]
        run = self.store.start_run(run.identifier)
        run = self.store.mark_work_started(run.identifier, expected_revision=run.revision)
        self.clock.advance(timedelta(minutes=2))
        self.assertEqual(self.store.recover_startup(self.clock()), ())
        interrupted = self.store.get_run(run.identifier)
        self.assertEqual(interrupted.status, "interrupted")
        self.assertTrue(interrupted.work_started)
        self.assertIsNone(ScheduledWorkExecutor(self.store, self.catalog).execute_next())
        self.assertEqual(self.recorder.values, [])

    def test_pause_cancel_and_edit_cancel_unstarted_runs(self) -> None:
        job, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(7, 1), "America/Chicago"
        ))
        self.clock.set(datetime(2026, 8, 11, 12, 1, tzinfo=timezone.utc))
        run = self.store.claim_due(self.clock())[0]
        current = self.store.get_definition(job.identifier)
        paused = self.store.pause_definition(job.identifier, expected_revision=current.revision)
        self.assertEqual(self.store.get_run(run.identifier).status, "cancelled_before_start")
        resumed = self.store.resume_definition(job.identifier, expected_revision=paused.revision)
        cancelled = self.store.cancel_definition(job.identifier, expected_revision=resumed.revision)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(self.store.get_authorization(cancelled.current_authorization_id).status, "revoked")

    def test_history_deletion_is_dependency_safe(self) -> None:
        job, _ = self.create()
        self.clock.advance(timedelta(minutes=1))
        run = self.store.claim_due(self.clock())[0]
        with self.assertRaises(ScheduledWorkConflictError):
            self.store.delete_terminal_run(run.identifier, expected_revision=run.revision)
        terminal = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        with self.assertRaises(ScheduledWorkStaleRevisionError):
            self.store.delete_terminal_run(terminal.identifier, expected_revision=1)
        with self.assertRaises(ScheduledWorkConflictError):
            self.store.delete_resolved_definition(
                job.identifier,
                expected_revision=self.store.get_definition(job.identifier).revision,
            )
        self.store.delete_terminal_run(
            terminal.identifier, expected_revision=terminal.revision
        )
        with self.assertRaises(ScheduledWorkNotFoundError):
            self.store.get_run(terminal.identifier)
        resolved = self.store.get_definition(job.identifier)
        self.store.delete_resolved_definition(
            job.identifier, expected_revision=resolved.revision
        )
        with self.assertRaises(ScheduledWorkNotFoundError):
            self.store.get_authorization(resolved.current_authorization_id)

    def test_history_deletion_refuses_live_definitions_and_removes_pending_delivery(self) -> None:
        recurring, _ = self.create(schedule=daily_schedule(
            date(2026, 8, 11), time(7, 1), "America/Chicago"
        ))
        with self.assertRaises(ScheduledWorkConflictError):
            self.store.delete_resolved_definition(
                recurring.identifier, expected_revision=recurring.revision
            )
        paused = self.store.pause_definition(
            recurring.identifier, expected_revision=recurring.revision
        )
        with self.assertRaises(ScheduledWorkConflictError):
            self.store.delete_resolved_definition(
                paused.identifier, expected_revision=paused.revision
            )

        one_shot, _ = self.create()
        self.clock.advance(timedelta(minutes=1))
        self.store.claim_due(self.clock())
        terminal = ScheduledWorkExecutor(self.store, self.catalog).execute_next()
        self.assertEqual(len(self.store.pending_notifications()), 1)
        self.store.delete_terminal_run(
            terminal.identifier, expected_revision=terminal.revision
        )
        self.assertEqual(self.store.pending_notifications(), ())
        self.assertEqual(self.store.get_definition(one_shot.identifier).status, "completed")

    def test_coordinator_wakes_executes_and_stops_cleanly(self) -> None:
        self.create()
        coordinator = ScheduledWorkCoordinator(
            self.store, self.catalog, clock=self.clock, recheck_seconds=0.1
        )
        coordinator.start()
        self.clock.advance(timedelta(minutes=1))
        coordinator.notify_schedule_changed()
        deadline = datetime.now().timestamp() + 2
        while datetime.now().timestamp() < deadline and not self.recorder.values:
            threading.Event().wait(0.01)
        coordinator.stop()
        self.assertEqual(len(self.recorder.values), 1)
        self.assertFalse(coordinator.running)
        self.assertFalse(coordinator.worker_running)


if __name__ == "__main__":
    unittest.main()
