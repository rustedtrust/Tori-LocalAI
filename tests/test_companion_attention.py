from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tori.companion_attention import CompanionAttentionSources
from tori.companion_initiative import (
    AttentionSignal,
    InitiativeSettings,
    SQLiteCompanionInitiativeStore,
)


UTC = timezone.utc
NOW = datetime(2026, 9, 21, 15, 0, tzinfo=UTC)
STAMP = "2026-09-21T15:00:00.000000Z"


class _Research:
    def __init__(self, jobs=(), sources=None):
        self._status = SimpleNamespace(jobs=jobs, sources=sources or {})

    def status(self):
        return self._status


class _BrokenResearch:
    def status(self):
        raise RuntimeError("controlled source failure")


class _Coding:
    def __init__(self, work=()):
        self._status = SimpleNamespace(work=work)

    def status(self, work_id=None, *, project_id=None):
        return self._status


class _NightOwl:
    def __init__(self, findings=()):
        self.findings = findings

    def list_finding_details(self, *, limit=50):
        return self.findings[:limit]


class _Scheduled:
    def __init__(self, definitions=(), runs=()):
        self.definitions = definitions
        self.runs = runs

    def list_definitions(self):
        return self.definitions

    def list_runs(self, *, limit=100):
        return self.runs[:limit]


class _Projects:
    def __init__(self, projects=()):
        self.projects = projects

    def list_projects(self):
        return self.projects


class CompanionAttentionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.now = NOW
        self.store = SQLiteCompanionInitiativeStore(
            Path(temporary.name) / "runtime/companion_initiative/attention.db",
            clock=lambda: self.now,
        )
        self.store.save_settings(
            InitiativeSettings(master_enabled=True, resume_enabled=True,
                               morning_enabled=True,
                               night_owl_findings_enabled=True),
            expected_revision=0,
        )

    def signal(self, *, material="one", updated=NOW, source="research"):
        return AttentionSignal(
            source, f"{source}-object", "completed", "Useful result",
            "A bounded source-owned summary.", "worth_reviewing", "silent", 1,
            material, updated, None,
        )

    def test_anti_nagging_survives_unchanged_reconciliation_and_material_change(self):
        item = self.store.reconcile_attention("research", (self.signal(),))[0]
        dismissed = self.store.update_attention(
            item.identifier, "dismiss", expected_revision=item.revision
        )
        later_timestamp = self.signal(updated=NOW + timedelta(hours=1))
        unchanged = self.store.reconcile_attention("research", (later_timestamp,))[0]
        self.assertEqual(unchanged.state, "dismissed")
        self.assertEqual(unchanged.material_key, dismissed.material_key)
        self.assertEqual(unchanged.revision, dismissed.revision)

        changed = self.store.reconcile_attention(
            "research", (self.signal(material="meaningfully-new"),)
        )[0]
        self.assertEqual(changed.state, "open")
        self.assertIsNone(changed.surfaced_material_key)

    def test_defer_review_and_source_resolution_are_durable(self):
        item = self.store.reconcile_attention("research", (self.signal(),))[0]
        deferred = self.store.update_attention(
            item.identifier, "defer", expected_revision=item.revision,
            defer_until=NOW + timedelta(days=1),
        )
        self.assertEqual(self.store.eligible_attention(at=NOW), ())
        self.assertEqual(
            self.store.eligible_attention(at=NOW + timedelta(days=1))[0].identifier,
            deferred.identifier,
        )
        reviewed = self.store.update_attention(
            deferred.identifier, "review", expected_revision=deferred.revision
        )
        self.assertEqual(reviewed.state, "reviewed")
        self.assertEqual(self.store.eligible_attention(at=NOW + timedelta(days=2)), ())

        reopened = self.store.reconcile_attention(
            "research", (self.signal(material="two"),)
        )[0]
        self.assertEqual(reopened.state, "open")
        resolved = self.store.reconcile_attention("research", ())[0]
        self.assertEqual(resolved.state, "resolved")

    def test_delivery_marks_exact_material_surfaced_once(self):
        signal = replace(self.signal(), delivery_level="conversational")
        item = self.store.reconcile_attention("research", (signal,))[0]
        candidate = self.store.create_candidate(
            initiative_type="resume", dedupe_key=f"resume:attention:{item.identifier}:1",
            eligible_at=NOW, expires_at=None, wording="This result needs your attention.",
            anchor_kind="attention", anchor_id=item.identifier,
            anchor_revision=item.revision, attention_ids=(item.identifier,),
        )
        claimed = self.store.claim(
            candidate.identifier, expected_revision=candidate.revision,
            owner="test-owner", target_chat_id="a" * 64, target_chat_revision=1,
            lease_until=NOW + timedelta(minutes=1),
        )
        self.store.mark_delivered(
            claimed.identifier, expected_revision=claimed.revision,
            owner="test-owner", delivered_at=NOW,
        )
        surfaced = self.store.get_attention(item.identifier)
        self.assertEqual(surfaced.surfaced_material_key, item.material_key)
        self.assertEqual(self.store.eligible_attention(at=NOW), ())

    def test_authoritative_sources_cover_terminal_states_and_skip_routine_success(self):
        project = SimpleNamespace(identifier="project-" + "a" * 32,
                                  title="Voice", status="active")
        research_states = ("completed", "failed", "interrupted", "completed_with_limits")
        jobs = tuple(SimpleNamespace(
            identifier=f"research-{index:032x}", objective=f"Research {state}",
            state=state, revision=2, failure_code=("failed" if state == "failed" else None),
            project_id=(project.identifier if state == "completed" else None),
            updated_at_utc=STAMP,
        ) for index, state in enumerate(research_states, 1))
        coding = (
            SimpleNamespace(identifier="coding-work-" + "1" * 32, objective="Done",
                            state="completed", needs_authorization=False,
                            result_summary="Finished", latest_activity=None,
                            acceptance_status="not_independently_verified",
                            project_id=None, revision=3, updated_at_utc=STAMP),
            SimpleNamespace(identifier="coding-work-" + "2" * 32, objective="Decision",
                            state="waiting", needs_authorization=True,
                            result_summary=None, latest_activity="Authority is required.",
                            acceptance_status="pending", project_id=None,
                            revision=4, updated_at_utc=STAMP),
            SimpleNamespace(identifier="coding-work-" + "3" * 32, objective="Failed",
                            state="failed", needs_authorization=False,
                            result_summary="Tests failed", latest_activity=None,
                            acceptance_status="not_completed", project_id=None,
                            revision=5, updated_at_utc=STAMP),
        )
        finding = SimpleNamespace(
            identifier="finding-" + "4" * 32, title="New STT", summary="Relevant release",
            state="new", revision=2, current_fingerprint="f" * 64,
            last_seen_at=STAMP,
        )
        definition = SimpleNamespace(identifier="work-" + "5" * 32, title="Backup")
        runs = (
            SimpleNamespace(identifier="run-" + "6" * 32, job_id=definition.identifier,
                            status="failed", revision=2, failure_code="capability_failed",
                            missed_occurrence_count=0, missed_first_key=None,
                            missed_last_key=None, finished_at_utc=STAMP, claim_at_utc=STAMP),
            SimpleNamespace(identifier="run-" + "7" * 32, job_id=definition.identifier,
                            status="succeeded", revision=2, failure_code=None,
                            missed_occurrence_count=0, missed_first_key=None,
                            missed_last_key=None, finished_at_utc=STAMP, claim_at_utc=STAMP),
            SimpleNamespace(identifier="run-" + "8" * 32, job_id=definition.identifier,
                            status="skipped", revision=2, failure_code=None,
                            missed_occurrence_count=2, missed_first_key="2026-09-19",
                            missed_last_key="2026-09-20", finished_at_utc=STAMP,
                            claim_at_utc=STAMP),
        )
        snapshots = dict(CompanionAttentionSources(
            research=_Research(jobs, {job.identifier: () for job in jobs}),
            coding=_Coding(coding), night_owl=_NightOwl((finding,)),
            scheduled=_Scheduled((definition,), runs), projects=_Projects((project,)),
        ).snapshots())
        self.assertEqual(len(snapshots["research"]), 4)
        self.assertEqual(len(snapshots["coding_work"]), 3)
        self.assertEqual(len(snapshots["night_owl"]), 1)
        self.assertEqual(len(snapshots["scheduled_work"]), 2)
        self.assertEqual(
            {signal.kind for signal in snapshots["scheduled_work"]},
            {"scheduled_failed", "scheduled_skipped"},
        )
        self.assertEqual(snapshots["research"][0].delivery_level, "gentle")
        self.assertIn("active Project Voice", snapshots["research"][0].summary)
        self.assertTrue(all(signal.source != "project" for rows in snapshots.values() for signal in rows))

    def test_source_specific_dispositions_and_material_change(self):
        research_job = SimpleNamespace(
            identifier="research-" + "a" * 32, objective="Reviewed research",
            state="completed", revision=2, failure_code=None, project_id=None,
            updated_at_utc=STAMP,
        )
        coding_work = SimpleNamespace(
            identifier="coding-work-" + "b" * 32, objective="Reviewed coding",
            state="completed", needs_authorization=False,
            result_summary="Completed", latest_activity=None,
            acceptance_status="not_independently_verified", project_id=None,
            revision=2, updated_at_utc=STAMP,
        )
        finding = SimpleNamespace(
            identifier="finding-" + "c" * 32, title="Dismissed finding",
            summary="Stored finding", state="new", revision=2,
            current_fingerprint="1" * 64, last_seen_at=STAMP,
        )
        sources = CompanionAttentionSources(
            research=_Research((research_job,), {research_job.identifier: (1,)}),
            coding=_Coding((coding_work,)), night_owl=_NightOwl((finding,)),
        )
        snapshots = dict(sources.snapshots())
        for source in ("research", "coding_work"):
            item = self.store.reconcile_attention(source, snapshots[source])[0]
            reviewed = self.store.update_attention(
                item.identifier, "review", expected_revision=item.revision
            )
            unchanged = self.store.reconcile_attention(source, snapshots[source])[0]
            self.assertEqual(unchanged.state, "reviewed")
            self.assertEqual(unchanged.revision, reviewed.revision)

        night = self.store.reconcile_attention(
            "night_owl", snapshots["night_owl"]
        )[0]
        dismissed = self.store.update_attention(
            night.identifier, "dismiss", expected_revision=night.revision
        )
        unchanged = self.store.reconcile_attention(
            "night_owl", snapshots["night_owl"]
        )[0]
        self.assertEqual(unchanged.state, "dismissed")
        self.assertEqual(unchanged.revision, dismissed.revision)

        changed_finding = SimpleNamespace(**{
            **finding.__dict__, "revision": 3, "current_fingerprint": "2" * 64,
        })
        changed_signal = dict(CompanionAttentionSources(
            night_owl=_NightOwl((changed_finding,))
        ).snapshots())["night_owl"]
        reopened = self.store.reconcile_attention("night_owl", changed_signal)[0]
        self.assertEqual(reopened.state, "open")
        dismissed_source = dict(CompanionAttentionSources(
            night_owl=_NightOwl((SimpleNamespace(**{
                **changed_finding.__dict__, "state": "dismissed",
            }),))
        ).snapshots())["night_owl"]
        self.assertEqual(dismissed_source, ())

    def test_one_unavailable_source_does_not_erase_or_block_other_sources(self):
        prior = self.store.reconcile_attention("research", (self.signal(),))[0]
        coding_work = SimpleNamespace(
            identifier="coding-work-" + "d" * 32, objective="Available coding",
            state="completed", needs_authorization=False,
            result_summary="Completed", latest_activity=None,
            acceptance_status="not_independently_verified", project_id=None,
            revision=2, updated_at_utc=STAMP,
        )
        snapshots = dict(CompanionAttentionSources(
            research=_BrokenResearch(), coding=_Coding((coding_work,))
        ).snapshots())
        self.assertNotIn("research", snapshots)
        self.assertEqual(len(snapshots["coding_work"]), 1)
        self.store.reconcile_attention("coding_work", snapshots["coding_work"])
        self.assertEqual(self.store.get_attention(prior.identifier).state, "open")


if __name__ == "__main__":
    unittest.main()
