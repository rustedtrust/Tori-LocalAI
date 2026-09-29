"""Focused tests for Capability Growth / Self-Improvement V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import os
import sqlite3
import unittest
from unittest.mock import patch

from tori.backups import BackupBusyError, BackupService
from tori.capabilities import CapabilityResult
from tori.capability_growth import (
    CapabilityEvidence,
    CapabilityGrowthValidationError,
    CapabilityInventory,
    CandidateProvenance,
    ImprovementJournalConflictError,
    ImprovementJournalCorruptError,
    SQLiteImprovementJournal,
    SkillsReviewIntent,
    SkillsReviewService,
    capability_growth_document,
    format_skills_review,
    recognize_skills_review,
)
from tori.capability_registry import CapabilityRegistry, CapabilityState
from tori.github_skills import GitHubSkillNetworkError
from tori.request_origin import OriginAuthorityError, RequestOrigin
from tori.restore import _copy_runtime, _verify_runtime_sqlite
from tori.skills_sh import (
    SkillsShCandidate,
    SkillsShDiscoveryNetworkError,
    SkillsShDiscoveryResult,
)


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, days: int) -> None:
        self.value += timedelta(days=days)


class _Discovery:
    def __init__(self, candidates: tuple[SkillsShCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[tuple[str, int, RequestOrigin]] = []

    def search(self, query: object, *, limit: object, origin: RequestOrigin) -> SkillsShDiscoveryResult:
        assert isinstance(query, str)
        assert isinstance(limit, int)
        self.calls.append((query, limit, origin))
        return SkillsShDiscoveryResult(
            provider="skills.sh",
            query=query,
            retrieved_at="2026-09-07T12:00:00Z",
            search_type="search",
            candidates=self.candidates[:limit],
        )


class _GitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect(self, url: object, *, origin: RequestOrigin) -> object:
        assert isinstance(url, str)
        self.calls.append(url)
        candidate = url.rsplit("/", 1)[-1]
        return SimpleNamespace(
            skill_id=f"github/example/{candidate}",
            name=candidate.replace("-", " ").title(),
            repository="https://github.com/example/skills",
            commit="a" * 40,
            package_path=f"skills/{candidate}",
            version="1.0.0",
            digest="sha256:" + "b" * 64,
            compatibility="compatible_instruction_only",
            unsupported_components=(),
        )


class _FailingGitHub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def inspect(self, url: object, *, origin: RequestOrigin) -> object:
        assert isinstance(url, str)
        self.calls.append(url)
        raise GitHubSkillNetworkError()


class _FailingDiscovery:
    def search(self, query: object, *, limit: object, origin: RequestOrigin) -> object:
        raise SkillsShDiscoveryNetworkError()


class CapabilityGrowthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.clock = _Clock()
        self.path = Path(self.temporary.name) / "growth" / "journal.sqlite3"
        self.store = SQLiteImprovementJournal(self.path, clock=self.clock)
        self.local = RequestOrigin.local_web()

    def evidence(self, outcome: str, **changes: object) -> CapabilityEvidence:
        values: dict[str, object] = {
            "capability_area": "documents",
            "capability_id": "pdf.extract",
            "operation_id": "extract",
            "outcome": outcome,
            "component_id": "builtin.pdf",
            "component_version": "1.0.0",
            "component_digest": "sha256:" + "1" * 64,
        }
        values.update(changes)
        return CapabilityEvidence(**values)  # type: ignore[arg-type]

    def test_exact_schema_owner_private_lifecycle_and_reopen(self) -> None:
        self.store.initialize()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        finding = self.store.record(self.evidence("friction"))[0]
        self.assertEqual((finding.lane, finding.status, finding.revision), ("improve", "open", 1))
        monitored = self.store.update_finding_status(
            finding.identifier, "monitoring", expected_revision=finding.revision
        )
        self.assertEqual((monitored.status, monitored.revision), ("monitoring", 2))
        reopened = SQLiteImprovementJournal(self.path, clock=self.clock)
        self.assertEqual(reopened.list_findings()[0].status, "monitoring")

    def test_successes_consolidate_and_known_good_baseline_tracks_recent_failures(self) -> None:
        for _ in range(17):
            self.store.record(self.evidence("success"))
        findings = self.store.list_findings()
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].count, 17)
        baseline = self.store.known_good_baselines()[0]
        self.assertEqual(baseline["verified_successes"], 17)
        self.assertEqual(baseline["recent_failures"], 0)

    def test_failure_accumulation_regression_and_priority_ordering(self) -> None:
        self.store.record(self.evidence("success"))
        self.clock.advance(1)
        self.store.record(self.evidence("failure", error_code="timeout"))
        self.store.record(self.evidence("failure", error_code="timeout"))
        self.store.record(self.evidence("friction"))
        self.store.record(self.evidence("opportunity"))
        findings = self.store.list_findings()
        kinds = [item.evidence_kind for item in findings]
        self.assertEqual(kinds[:2], ["regression", "failure"])
        failure = next(item for item in findings if item.evidence_kind == "failure")
        self.assertEqual(failure.count, 2)
        self.assertGreater(failure.priority, next(item.priority for item in findings if item.evidence_kind == "friction"))
        self.assertGreater(next(item.priority for item in findings if item.evidence_kind == "friction"), next(item.priority for item in findings if item.evidence_kind == "opportunity"))
        self.assertEqual(self.store.known_good_baselines()[0]["recent_failures"], 2)

    def test_evidence_privacy_rejects_model_grades_raw_text_and_unverified_claims(self) -> None:
        with self.assertRaises(TypeError):
            CapabilityEvidence(  # type: ignore[call-arg]
                capability_area="documents", capability_id="pdf", operation_id="read",
                outcome="success", raw_conversation="private transcript",
            )
        with self.assertRaises(CapabilityGrowthValidationError):
            self.store.record(self.evidence("success", verified=False))
        with self.assertRaises(CapabilityGrowthValidationError):
            self.store.record(self.evidence("failure", error_code="secret token leaked"))

    def test_schema_tampering_fails_closed_without_repair(self) -> None:
        self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE unexpected(value TEXT)")
        with self.assertRaises(ImprovementJournalCorruptError):
            SQLiteImprovementJournal(self.path).list_findings()

    def test_exact_schema_rejects_an_unexpected_view_or_trigger(self) -> None:
        self.store.initialize()
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE VIEW unexpected_view AS SELECT id FROM findings")
        with self.assertRaises(ImprovementJournalCorruptError):
            SQLiteImprovementJournal(self.path).list_findings()

    def test_normalized_capability_result_records_only_deterministic_outcome(self) -> None:
        result = CapabilityResult(
            "skill.example.read", "private input is not stored", "succeeded", ()
        )
        self.store.record_result(
            result,
            capability_area="documents",
            operation_id="read",
            component_id="skill.example",
            component_version="1.0",
        )
        finding = self.store.list_findings()[0]
        self.assertEqual(finding.capability_id, "skill.example.read")
        with sqlite3.connect(self.path) as connection:
            encoded = " ".join(str(value) for row in connection.iterdump() for value in [row])
        self.assertNotIn("private input", encoded)

    def test_bounded_store_evicts_only_terminal_rows_and_refuses_active_loss(self) -> None:
        with patch("tori.capability_growth.MAX_FINDINGS", 2):
            first = self.store.record(self.evidence(
                "friction", capability_id="pdf.one"
            ))[0]
            self.store.record(self.evidence("friction", capability_id="pdf.two"))
            with self.assertRaises(ImprovementJournalConflictError):
                self.store.record(self.evidence("friction", capability_id="pdf.three"))
            self.store.update_finding_status(
                first.identifier, "resolved", expected_revision=first.revision
            )
            self.store.record(self.evidence("friction", capability_id="pdf.three"))
            self.assertEqual(len(self.store.list_findings()), 2)

    def test_recommendation_classification_lifecycle_and_cooldown(self) -> None:
        candidate = CandidateProvenance(
            "example/skills/image", "image", "Image helper",
            "https://github.com/example/skills", "a" * 40, "skills/image",
            "1.0", "sha256:" + "b" * 64, "compatible_instruction_only", True,
        )
        recommendation = self.store.recommend(
            lane="expand", capability_area="images_media", title="Review Image helper",
            rationale="Tori lacks an approved image-generation adapter.",
            evidence="Immutable package bytes were inspected.",
            classification="needs_mcp_or_external_integration",
            required_authority=("external_integration", "user_decision"),
            candidate=candidate,
        )
        dismissed = self.store.update_recommendation_status(
            recommendation.identifier, "dismissed", expected_revision=1
        )
        unchanged = self.store.recommend(
            lane="expand", capability_area="images_media", title="Review Image helper",
            rationale="Tori lacks an approved image-generation adapter.",
            evidence="Immutable package bytes were inspected.",
            classification="needs_mcp_or_external_integration",
            required_authority=("external_integration", "user_decision"),
            candidate=candidate,
        )
        self.assertEqual(unchanged.status, "dismissed")
        self.clock.advance(31)
        reopened = self.store.recommend(
            lane="expand", capability_area="images_media", title="Review Image helper",
            rationale="Tori lacks an approved image-generation adapter.",
            evidence="Immutable package bytes were inspected.",
            classification="needs_mcp_or_external_integration",
            required_authority=("external_integration", "user_decision"),
            candidate=candidate,
        )
        self.assertEqual(reopened.status, "open")
        self.assertGreater(reopened.revision, dismissed.revision)

    def test_inventory_includes_native_state_without_model_claims(self) -> None:
        registry = CapabilityRegistry({
            "knowledge": lambda: CapabilityState("available"),
            "search": lambda: CapabilityState("disabled", "user preference is off"),
        })
        inventory = CapabilityInventory(registry, origin=self.local)
        document = inventory.document()
        by_id = {item["identifier"]: item for item in document["items"]}
        self.assertEqual(by_id["knowledge"]["state"], "available")
        self.assertEqual(by_id["search"]["state"], "disabled")
        self.assertFalse(inventory.has_markers(("image.generate",)))

    def test_review_recognizer_covers_general_and_user_directed_requests(self) -> None:
        for text in (
            "Run a Skills Review.",
            "Look for useful Skills we don't have yet.",
            "What capabilities are you missing?",
        ):
            with self.subTest(text=text):
                self.assertEqual(recognize_skills_review(text).scope, "general")  # type: ignore[union-attr]
        self.assertEqual(recognize_skills_review("Find a Skill for Excel files.").capability_area, "spreadsheets_data")  # type: ignore[union-attr]
        self.assertEqual(recognize_skills_review("Look for image-generation Skills.").capability_area, "images_media")  # type: ignore[union-attr]
        self.assertEqual(recognize_skills_review("Find something useful for Discord.").capability_area, "communication")  # type: ignore[union-attr]
        directed = recognize_skills_review(
            "Find a Skill that could help you work with Discord."
        )
        self.assertIsNotNone(directed)
        self.assertEqual(directed.scope, "user_directed")  # type: ignore[union-attr]
        self.assertEqual(directed.capability_area, "communication")  # type: ignore[union-attr]
        self.assertEqual(directed.search_query, "Discord")  # type: ignore[union-attr]
        self.assertEqual(recognize_skills_review("Is there a Skill for this?").capability_area, "unspecified")  # type: ignore[union-attr]

    def test_directed_review_is_bounded_inspects_and_never_installs_or_enables(self) -> None:
        candidates = tuple(
            SkillsShCandidate(
                catalog_id=f"example/skills/image-{index}",
                skill_id=f"image-{index}",
                name=f"Image {index}",
                description="untrusted",
                source="example/skills",
                installs=index,
                is_duplicate=False,
                catalog_url=f"https://skills.sh/example/skills/image-{index}",
                github_url=f"https://github.com/example/skills/tree/HEAD/skills/image-{index}",
                path_mapping="unverified",
                untrusted_metadata={},
            )
            for index in range(5)
        )
        discovery = _Discovery(candidates)
        github = _GitHub()
        inventory = CapabilityInventory(CapabilityRegistry(), origin=self.local)
        service = SkillsReviewService(
            self.store, inventory, discovery, github=github  # type: ignore[arg-type]
        )
        result = service.run(
            SkillsReviewIntent("user_directed", "images_media", "image generation"),
            origin=self.local,
        )
        self.assertEqual(len(discovery.calls), 1)
        self.assertEqual(discovery.calls[0][1], 3)
        self.assertEqual(len(github.calls), 2)
        self.assertEqual(result.review.searches, 1)
        self.assertEqual(result.review.inspections, 2)
        self.assertEqual(result.successful_inspections, 2)
        self.assertEqual(result.failed_inspections, 0)
        self.assertIn(
            "2 immutable inspection attempt(s): 2 successful and 0 failed.",
            format_skills_review(result),
        )
        self.assertTrue(all(item.lane == "expand" for item in result.recommendations))
        self.assertTrue(any(item.classification == "needs_mcp_or_external_integration" for item in result.recommendations))
        self.assertNotIn("install", github.__dict__)
        self.assertNotIn("enable", github.__dict__)

    def test_failed_inspections_still_consume_the_global_attempt_cap(self) -> None:
        candidates = tuple(
            SkillsShCandidate(
                catalog_id=f"example/skills/tool-{index}", skill_id=f"tool-{index}",
                name=f"Tool {index}", description="untrusted", source="example/skills",
                installs=index, is_duplicate=False,
                catalog_url=f"https://skills.sh/example/skills/tool-{index}",
                github_url=f"https://github.com/example/skills/tree/HEAD/skills/tool-{index}",
                path_mapping="unverified", untrusted_metadata={},
            )
            for index in range(3)
        )
        github = _FailingGitHub()
        result = SkillsReviewService(
            self.store,
            CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _Discovery(candidates),  # type: ignore[arg-type]
            github=github,  # type: ignore[arg-type]
        ).run(
            SkillsReviewIntent("user_directed", "coding", "developer tools"),
            origin=self.local,
        )
        self.assertEqual(len(github.calls), 2)
        self.assertEqual(result.review.inspections, 2)
        self.assertEqual(result.successful_inspections, 0)
        self.assertEqual(result.failed_inspections, 2)
        self.assertIn(
            "2 immutable inspection attempt(s): 0 successful and 2 failed.",
            format_skills_review(result),
        )
        self.assertNotIn("2 immutable inspection(s)", format_skills_review(result))

    def test_success_only_baselines_do_not_create_improve_recommendations(self) -> None:
        discovery = _Discovery(())
        service = SkillsReviewService(
            self.store,
            CapabilityInventory(CapabilityRegistry(), origin=self.local),
            discovery,  # type: ignore[arg-type]
        )
        first = service.run(SkillsReviewIntent("general", "all", None), origin=self.local)
        second = service.run(SkillsReviewIntent("general", "all", None), origin=self.local)
        self.assertEqual((first.review.status, second.review.status), ("completed", "completed"))
        self.assertEqual(second.review.candidates, 0)
        self.assertEqual(second.recommendations, ())
        self.assertIn("Skills Review completed with no new candidates", format_skills_review(second))
        self.assertNotIn("Review success evidence for skills.sh", format_skills_review(second))
        baselines = self.store.known_good_baselines()
        self.assertEqual(len(baselines), 1)
        self.assertEqual(baselines[0]["verified_successes"], 6)

    def test_research_failure_is_partial_not_false_completed_or_failed(self) -> None:
        result = SkillsReviewService(
            self.store,
            CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _FailingDiscovery(),  # type: ignore[arg-type]
        ).run(SkillsReviewIntent("general", "all", None), origin=self.local)
        self.assertEqual(result.review.status, "partial")
        self.assertEqual(result.review.candidates, 0)
        self.assertIn("skills_sh_discovery_network_failed", result.review.error_codes)
        self.assertIn("Skills Review partial", format_skills_review(result))

    def test_friction_still_creates_improve_and_failure_still_creates_fix(self) -> None:
        self.store.record(self.evidence("friction"))
        self.store.record(self.evidence("failure", error_code="timeout"))
        result = SkillsReviewService(
            self.store,
            CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _Discovery(()),  # type: ignore[arg-type]
        ).run(SkillsReviewIntent("general", "all", None), origin=self.local)
        lanes = {item.lane for item in result.recommendations}
        self.assertIn("improve", lanes)
        self.assertIn("fix", lanes)

    def test_general_review_obsoletes_open_success_only_recommendation_but_keeps_baseline(self) -> None:
        self.store.record(self.evidence("success", capability_id="skills.sh"))
        stale = self.store.recommend(
            lane="improve", capability_area="skill_research",
            title="Review success evidence for skills.sh",
            rationale="Earlier policy treated successful discovery as improvement evidence.",
            evidence="Component skills.sh v1; priority 103; error none.",
            classification="ready_existing_authority", required_authority=("user_decision",),
        )
        baseline_before = self.store.known_good_baselines()[0]["verified_successes"]
        SkillsReviewService(
            self.store, CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _Discovery(()),  # type: ignore[arg-type]
        ).run(SkillsReviewIntent("general", "all", None), origin=self.local)
        self.assertEqual(self.store.get_recommendation(stale.identifier).status, "obsolete")
        self.assertGreaterEqual(
            self.store.known_good_baselines()[0]["verified_successes"], baseline_before
        )

    def test_regression_recommendation_supersedes_only_matching_failure(self) -> None:
        self.store.record(self.evidence("success"))
        self.store.record(self.evidence("failure", error_code="timeout"))
        duplicate = self.store.recommend(
            lane="fix", capability_area="documents", title="Review failure evidence for pdf.extract",
            rationale="Tori recorded 1 verified failure outcome for extract.",
            evidence="Component builtin.pdf 1.0.0; priority 400; error timeout.",
            classification="ready_existing_authority", required_authority=("user_decision",),
        )
        self.store.record(self.evidence(
            "failure", capability_id="pdf.other", error_code="timeout"
        ))
        result = SkillsReviewService(
            self.store, CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _Discovery(()),  # type: ignore[arg-type]
        ).run(SkillsReviewIntent("general", "all", None), origin=self.local)
        active_titles = {item.title for item in result.recommendations}
        self.assertIn("Investigate regression in pdf.extract", active_titles)
        self.assertIn("Review failure evidence for pdf.other", active_titles)
        self.assertNotIn("Review failure evidence for pdf.extract", active_titles)
        self.assertEqual(self.store.get_recommendation(duplicate.identifier).status, "obsolete")
        kinds = {item.evidence_kind for item in self.store.list_findings()}
        self.assertIn("failure", kinds)
        self.assertIn("regression", kinds)

    def test_reconciliation_preserves_terminal_recommendation_history(self) -> None:
        terminal_statuses = ("accepted", "dismissed", "resolved")
        records = []
        for index, status in enumerate(terminal_statuses):
            self.store.record(self.evidence("success", capability_id=f"skills.{index}"))
            recommendation = self.store.recommend(
                lane="improve", capability_area="skill_research",
                title=f"Review success evidence for skills.{index}",
                rationale="Earlier policy treated successful discovery as improvement evidence.",
                evidence="Component skills.sh v1; priority 103; error none.",
                classification="ready_existing_authority", required_authority=("user_decision",),
            )
            records.append(self.store.update_recommendation_status(
                recommendation.identifier, status, expected_revision=recommendation.revision
            ))
        SkillsReviewService(
            self.store, CapabilityInventory(CapabilityRegistry(), origin=self.local),
            _Discovery(()),  # type: ignore[arg-type]
        ).run(SkillsReviewIntent("general", "all", None), origin=self.local)
        self.assertEqual(
            tuple(self.store.get_recommendation(item.identifier).status for item in records),
            terminal_statuses,
        )

    def test_general_review_examines_fix_improve_expand_and_remote_is_denied(self) -> None:
        self.store.record(self.evidence("failure", error_code="timeout"))
        self.store.record(self.evidence("friction"))
        discovery = _Discovery(())
        service = SkillsReviewService(
            self.store,
            CapabilityInventory(CapabilityRegistry(), origin=self.local),
            discovery,  # type: ignore[arg-type]
        )
        result = service.run(
            SkillsReviewIntent("general", "all", None), origin=self.local
        )
        self.assertLessEqual(result.review.searches, 3)
        lanes = {item.lane for item in result.recommendations}
        self.assertIn("fix", lanes)
        self.assertIn("improve", lanes)
        remote = RequestOrigin.discord_remote(
            connector_id="discord", external_message_id="message",
            external_actor_id="actor", external_conversation_id="channel",
        )
        with self.assertRaises(OriginAuthorityError):
            service.run(SkillsReviewIntent("general", "all", None), origin=remote)

    def test_management_projection_separates_memory_and_history(self) -> None:
        inventory = CapabilityInventory(CapabilityRegistry(), origin=self.local)
        self.store.record(self.evidence("success"))
        document = capability_growth_document(self.store, inventory)
        self.assertTrue(document["available"])
        self.assertIn("baselines", document)
        self.assertEqual(document["findings"], [])
        self.assertNotIn("memory", document)

    def test_verified_backup_and_restore_preserve_the_journal(self) -> None:
        root = Path(self.temporary.name) / "project"
        backups = Path(self.temporary.name) / "backups"
        root.mkdir(mode=0o700)
        journal = SQLiteImprovementJournal(
            root / "runtime/capability_growth/improvement_journal.sqlite3",
            clock=self.clock,
        )
        journal.record(self.evidence("success"))
        with self.assertRaises(BackupBusyError):
            BackupService(project_root=root, backup_root=backups).create_backup()
        service = BackupService(
            project_root=root,
            backup_root=backups,
            capability_growth_guard=journal.maintenance_guard,
        )
        result = service.create_backup()
        payload = service.verified_payload(result.identifier)
        restored_root = Path(self.temporary.name) / "restored-runtime"
        _copy_runtime(payload / "runtime", restored_root)
        _verify_runtime_sqlite(restored_root)
        restored = SQLiteImprovementJournal(
            restored_root / "capability_growth/improvement_journal.sqlite3"
        )
        self.assertEqual(restored.list_findings()[0].evidence_kind, "success")


if __name__ == "__main__":
    unittest.main()
