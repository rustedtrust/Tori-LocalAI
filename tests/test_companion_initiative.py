from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tori.backups import BackupBusyError, BackupService
from tori.companion_initiative import (
    AttentionSignal,
    CompanionInitiativeConflictError,
    CompanionInitiativeCorruptError,
    GLOBAL_COOLDOWN,
    InitiativeSettings,
    LONG_SILENCE_COOLDOWN,
    SQLiteCompanionInitiativeStore,
    cooldown_active,
    evaluate_policy,
    in_local_window,
    morning_candidate_key,
    resume_candidate_key,
    rolling_cap_reached,
    silence_candidate_key,
)


UTC = timezone.utc
NOW = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)


class CompanionInitiativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now = NOW
        self.store = SQLiteCompanionInitiativeStore(
            self.root / "runtime/companion_initiative/tori_companion_initiative.db",
            clock=lambda: self.now,
        )

    def configure(self, **changes: object) -> InitiativeSettings:
        value = replace(InitiativeSettings(), **changes)
        return self.store.save_settings(value, expected_revision=0)

    def candidate(self, *, expires: datetime | None = None):
        return self.store.create_candidate(
            initiative_type="morning",
            dedupe_key=morning_candidate_key("America/Chicago", date(2026, 3, 10)),
            eligible_at=self.now,
            expires_at=expires or self.now + timedelta(hours=2),
            wording="Good morning. How are you doing?",
        )

    def test_absent_store_reads_default_off_without_creation(self) -> None:
        settings = self.store.settings()
        self.assertFalse(settings.master_enabled)
        self.assertFalse(settings.morning_enabled)
        self.assertFalse(settings.resume_enabled)
        self.assertFalse(settings.long_silence_enabled)
        self.assertFalse(settings.night_owl_findings_enabled)
        self.assertEqual((settings.quiet_start, settings.quiet_end), (time(22), time(8)))
        self.assertFalse(self.store.exists)

    def test_settings_activity_snooze_and_pause_persist_across_restart(self) -> None:
        settings = self.configure(master_enabled=True, morning_enabled=True)
        self.assertEqual(self.store.activity().kind, "settings_change")
        until = self.now + timedelta(days=7)
        saved = self.store.snooze(until, expected_revision=settings.revision)
        reopened = SQLiteCompanionInitiativeStore(self.store.path)
        self.assertEqual(reopened.settings().snoozed_until_utc, until)
        self.assertEqual(reopened.settings().revision, saved.revision)
        self.assertEqual(reopened.activity().revision, 2)

    def test_meaningful_interaction_is_content_free_revisioned_and_monotonic(self) -> None:
        self.configure(master_enabled=True)
        activity = self.store.record_meaningful_interaction("local_turn", occurred_at=self.now + timedelta(minutes=1))
        self.assertEqual((activity.revision, activity.kind), (2, "local_turn"))
        with self.assertRaises(CompanionInitiativeConflictError):
            self.store.record_meaningful_interaction("mutation", occurred_at=self.now)
        self.assertEqual(self.store.activity(), activity)

    def test_quiet_hours_and_morning_window_use_local_civil_time(self) -> None:
        settings = InitiativeSettings(master_enabled=True, morning_enabled=True)
        at_0730 = datetime(2026, 3, 10, 12, 30, tzinfo=UTC)  # CDT
        at_0830 = datetime(2026, 3, 10, 13, 30, tzinfo=UTC)
        at_2230 = datetime(2026, 3, 11, 3, 30, tzinfo=UTC)
        self.assertTrue(in_local_window(at_0730, "America/Chicago", settings.quiet_start, settings.quiet_end))
        self.assertTrue(in_local_window(at_0830, "America/Chicago", settings.morning_start, settings.morning_end))
        self.assertTrue(in_local_window(at_2230, "America/Chicago", settings.quiet_start, settings.quiet_end))

    def test_dst_gap_and_overlap_are_one_civil_window(self) -> None:
        # 02:30 is nonexistent on spring-forward day; 03:00 is within the
        # civil window after the boundary advances. Both overlap instants map
        # to the same date and therefore the same deterministic candidate key.
        self.assertTrue(in_local_window(datetime(2026, 3, 8, 8, 0, tzinfo=UTC), "America/Chicago", time(2, 30), time(4)))
        first = datetime(2026, 11, 1, 6, 30, tzinfo=UTC).astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        second = datetime(2026, 11, 1, 7, 30, tzinfo=UTC).astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
        self.assertNotEqual(first.utcoffset(), second.utcoffset())
        self.assertEqual(morning_candidate_key("America/Chicago", first.date()), morning_candidate_key("America/Chicago", second.date()))

    def test_cooldown_backward_clock_and_rolling_caps_fail_closed(self) -> None:
        self.assertTrue(cooldown_active(self.now, self.now + timedelta(minutes=1), GLOBAL_COOLDOWN))
        self.assertTrue(cooldown_active(self.now, self.now - timedelta(hours=23), GLOBAL_COOLDOWN))
        history = [self.now - timedelta(days=1), self.now - timedelta(days=2), self.now - timedelta(days=6)]
        self.assertTrue(rolling_cap_reached(self.now, history, window=timedelta(days=7), maximum=3))
        self.assertFalse(rolling_cap_reached(self.now, history, window=timedelta(days=30), maximum=8))
        self.assertTrue(rolling_cap_reached(self.now, [self.now + timedelta(seconds=1)], window=timedelta(days=7), maximum=3))

    def test_policy_enforces_defaults_snooze_activity_caps_and_type_cooldown(self) -> None:
        decision = evaluate_policy("morning", now=self.now, timezone_name="America/Chicago", settings=InitiativeSettings(), activity=self.store.activity())
        self.assertIn("master_off", decision.reasons)
        self.assertIn("type_off", decision.reasons)
        settings = InitiativeSettings(master_enabled=True, long_silence_enabled=True, snoozed_until_utc=self.now + timedelta(hours=1))
        activity = replace(self.store.activity(), last_meaningful_at_utc=self.now - timedelta(days=8))
        history = (("long_silence", self.now - LONG_SILENCE_COOLDOWN + timedelta(hours=1)),)
        decision = evaluate_policy("long_silence", now=self.now, timezone_name="America/Chicago", settings=settings, activity=activity, delivered_history=history)
        self.assertIn("snoozed", decision.reasons)
        self.assertIn("type_cooldown", decision.reasons)

    def test_deterministic_candidate_identity_and_duplicate_attempt(self) -> None:
        self.configure(master_enabled=True, morning_enabled=True)
        first = self.candidate()
        second = self.candidate()
        self.assertEqual(first.identifier, second.identifier)
        self.assertEqual(first.application_event_id, second.application_event_id)
        self.assertEqual(len(self.store.list_candidates()), 1)
        with self.assertRaises(CompanionInitiativeConflictError):
            self.store.create_candidate(initiative_type="morning", dedupe_key=first.dedupe_key, eligible_at=self.now, expires_at=self.now + timedelta(hours=2), wording="Different wording")
        self.assertEqual(self.store.get_candidate(first.identifier).wording, first.wording)

    def test_key_shapes_are_stable(self) -> None:
        self.assertEqual(morning_candidate_key("America/Chicago", date(2026, 1, 2)), "morning:America/Chicago:2026-01-02")
        self.assertEqual(resume_candidate_key("coding_work", "work-1", 4), "resume:coding_work:work-1:4")
        self.assertEqual(silence_candidate_key(9), "silence:9")

    def test_claim_is_unique_revision_fenced_and_transactional(self) -> None:
        self.configure(master_enabled=True, morning_enabled=True)
        first = self.candidate()
        second = self.store.create_candidate(initiative_type="long_silence", dedupe_key=silence_candidate_key(1), eligible_at=self.now, expires_at=None, wording="Hi. How are things going?")
        claimed = self.store.claim(first.identifier, expected_revision=first.revision, owner="process-1", target_chat_id="a" * 64, target_chat_revision=2, lease_until=self.now + timedelta(minutes=5))
        with self.assertRaises(CompanionInitiativeConflictError):
            self.store.claim(first.identifier, expected_revision=first.revision, owner="process-2", target_chat_id="a" * 64, target_chat_revision=2, lease_until=self.now + timedelta(minutes=5))
        with self.assertRaises(CompanionInitiativeConflictError):
            self.store.claim(second.identifier, expected_revision=second.revision, owner="process-2", target_chat_id="a" * 64, target_chat_revision=2, lease_until=self.now + timedelta(minutes=5))
        self.assertEqual(self.store.get_candidate(second.identifier).state, "pending")
        self.assertEqual(claimed.state, "delivering")

    def test_stale_claim_requires_observation_and_recovers_matching_absent_conflict(self) -> None:
        for index, observation in enumerate(("matching", "absent", "conflict")):
            path = self.root / f"store-{index}.db"
            clock = [self.now]
            store = SQLiteCompanionInitiativeStore(path, clock=lambda: clock[0])
            store.save_settings(InitiativeSettings(master_enabled=True, morning_enabled=True), expected_revision=0)
            candidate = store.create_candidate(initiative_type="morning", dedupe_key=f"morning:UTC:2026-03-{10+index:02d}", eligible_at=self.now, expires_at=self.now + timedelta(hours=3), wording="Good morning. How are you doing?")
            claimed = store.claim(candidate.identifier, expected_revision=1, owner="process-1", target_chat_id="a" * 64, target_chat_revision=1, lease_until=self.now + timedelta(minutes=1))
            clock[0] += timedelta(minutes=2)
            self.assertEqual(store.recover_startup(None), (store.get_candidate(candidate.identifier),))
            recovered = store.recover_startup(lambda _: observation)[0]
            self.assertEqual(recovered.state, {"matching": "delivered", "absent": "pending", "conflict": "failed"}[observation])
            self.assertGreater(recovered.revision, claimed.revision)

    def test_expired_absent_claim_becomes_terminal(self) -> None:
        self.configure(master_enabled=True, morning_enabled=True)
        item = self.candidate(expires=self.now + timedelta(minutes=1))
        item = self.store.claim(item.identifier, expected_revision=1, owner="process-1", target_chat_id="a" * 64, target_chat_revision=1, lease_until=self.now + timedelta(minutes=1))
        self.now += timedelta(minutes=2)
        recovered = self.store.reconcile_stale_claim(item.identifier, expected_revision=item.revision, observation="absent")
        self.assertEqual((recovered.state, recovered.terminal_reason), ("expired", "eligibility_expired"))

    def test_meaningful_activity_does_not_acknowledge_and_exact_reply_survives_restart(self) -> None:
        self.configure(master_enabled=True, morning_enabled=True)
        item = self.candidate()
        item = self.store.claim(item.identifier, expected_revision=1, owner="process-1", target_chat_id="a" * 64, target_chat_revision=1, lease_until=self.now + timedelta(minutes=5))
        item = self.store.mark_delivered(item.identifier, expected_revision=item.revision, owner="process-1")
        self.assertEqual(self.store.delivery_history(), (("morning", self.now),))
        activity = self.store.record_meaningful_interaction("mutation")
        reopened = SQLiteCompanionInitiativeStore(self.store.path)
        self.assertEqual(reopened.get_candidate(item.identifier).state, "delivered")
        self.assertEqual(reopened.activity().revision, activity.revision)
        context = reopened.claim_reply_context("a" * 64, at=self.now)
        self.assertIsNotNone(context)
        self.assertEqual(reopened.get_candidate(item.identifier).state, "acknowledged")

    def test_event_bound_pause_is_exact_and_rolls_back_on_stale_event(self) -> None:
        settings = self.configure(master_enabled=True, morning_enabled=True)
        item = self.candidate()
        item = self.store.claim(
            item.identifier,
            expected_revision=item.revision,
            owner="process-1",
            target_chat_id="a" * 64,
            target_chat_revision=1,
            lease_until=self.now + timedelta(minutes=5),
        )
        item = self.store.mark_delivered(
            item.identifier,
            expected_revision=item.revision,
            owner="process-1",
        )
        before_activity = self.store.activity()

        with self.assertRaises(CompanionInitiativeConflictError):
            self.store.snooze(
                self.now + timedelta(days=1),
                expected_revision=settings.revision,
                acknowledge_event_id="event-" + "0" * 32,
            )
        self.assertEqual(self.store.settings(), settings)
        self.assertEqual(self.store.activity(), before_activity)
        self.assertEqual(self.store.get_candidate(item.identifier), item)

        paused = self.store.snooze(
            self.now + timedelta(days=1),
            expected_revision=settings.revision,
            acknowledge_event_id=item.application_event_id,
        )
        self.assertEqual(paused.snoozed_until_utc, self.now + timedelta(days=1))
        acknowledged = self.store.get_candidate(item.identifier)
        self.assertEqual(acknowledged.state, "acknowledged")
        self.assertEqual(acknowledged.terminal_reason, "user_paused")

    def test_master_off_supersedes_pending_in_same_transaction(self) -> None:
        settings = self.configure(master_enabled=True, morning_enabled=True)
        item = self.candidate()
        self.store.save_settings(replace(settings, master_enabled=False), expected_revision=settings.revision)
        self.assertEqual(self.store.get_candidate(item.identifier).state, "superseded")

    def test_malformed_and_incompatible_schema_fail_without_repair(self) -> None:
        path = self.root / "bad.db"
        path.write_bytes(b"not sqlite")
        os.chmod(path, 0o600)
        with self.assertRaises(CompanionInitiativeCorruptError):
            SQLiteCompanionInitiativeStore(path).settings()
        self.assertEqual(path.read_bytes(), b"not sqlite")
        path.unlink()
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE unknown(value TEXT)"); connection.commit(); connection.close()
        os.chmod(path, 0o600)
        with self.assertRaises(CompanionInitiativeCorruptError):
            SQLiteCompanionInitiativeStore(path).settings()

    def test_verified_backup_requires_guard_and_restores_authoritative_store(self) -> None:
        project = self.root / "project"; project.mkdir()
        store = SQLiteCompanionInitiativeStore(project / "runtime/companion_initiative/tori_companion_initiative.db", clock=lambda: self.now)
        store.save_settings(InitiativeSettings(master_enabled=True, morning_enabled=True), expected_revision=0)
        attention = store.reconcile_attention("research", (AttentionSignal(
            "research", "research-" + "8" * 32, "research_completed",
            "Backup-preserved result", "Research completed and is ready to review.",
            "worth_reviewing", "silent", 2, "material-backup", self.now, None,
        ),))[0]
        store.update_attention(
            attention.identifier, "dismiss", expected_revision=attention.revision
        )
        backups = self.root / "backups"
        with self.assertRaises(BackupBusyError):
            BackupService(project_root=project, backup_root=backups).create_backup()
        service = BackupService(project_root=project, backup_root=backups, companion_initiative_guard=store.maintenance_guard, clock=lambda: self.now, token_hex=lambda _: "1" * 16)
        result = service.create_backup()
        restored = SQLiteCompanionInitiativeStore(Path(result.directory) / "project/runtime/companion_initiative/tori_companion_initiative.db")
        self.assertTrue(restored.settings().master_enabled)
        self.assertTrue(restored.settings().morning_enabled)
        restored_attention = restored.list_attention()
        self.assertEqual(len(restored_attention), 1)
        self.assertEqual(restored_attention[0].state, "dismissed")
        self.assertEqual(restored_attention[0].material_key, "material-backup")


if __name__ == "__main__":
    unittest.main()
