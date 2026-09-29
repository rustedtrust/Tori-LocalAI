from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tori.night_owl import (
    DEFAULT_BUDGETS, FindingDraft, NightOwlConflictError, NightOwlCorruptError, NightOwlSettings,
    SQLiteNightOwlStore, SourceAttribution, canonical_source_identity,
    finding_identity, source_policy_allows,
)


NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


class NightOwlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        counter = iter(range(1, 1000))
        self.store = SQLiteNightOwlStore(Path(self.temp.name) / "runtime/night_owl/state.db", clock=lambda: NOW, token_hex=lambda _: f"{next(counter):032x}")

    def enabled(self):
        return self.store.save_settings(NightOwlSettings(enabled=True, categories=("local_models",)), expected_revision=0)

    def draft(self, fingerprint="1" * 64):
        return FindingDraft("local_models", "github:Example/Tool.git", "project", "Tool", "Local model tool", ("category_match", "local_self_hosted"), ("license_unknown",), ("compatibility_unverified",), "Review it.", fingerprint, "release:1", "new release", (SourceAttribution("github_page", "https://github.com/Example/Tool", "Tool", "github:example/tool"),))

    def test_default_off_absent_noncreating(self):
        self.assertFalse(self.store.settings().enabled); self.assertFalse(self.store.exists); self.assertIsNone(self.store.active_grant())

    def test_settings_grant_revision_and_revocation(self):
        settings = self.enabled(); grant = self.store.active_grant(); assert grant
        self.assertEqual(grant.revision, settings.revision); self.store.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category="local_models", source_policy_version=grant.source_policy_version)
        disabled = self.store.save_settings(NightOwlSettings(), expected_revision=settings.revision)
        self.assertFalse(disabled.enabled); self.assertIsNone(self.store.active_grant())
        with self.assertRaises(NightOwlConflictError): self.store.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category="local_models", source_policy_version=grant.source_policy_version)

    def test_policy_identity_and_source_rejection(self):
        self.assertEqual(canonical_source_identity("github:Example/Tool.git"), "github:example/tool")
        self.assertEqual(finding_identity("local_models", "github:example/tool", "project"), finding_identity("local_models", "github:example/tool", "project"))
        self.assertTrue(source_policy_allows("github_page", "https://github.com/Example/Tool"))
        self.assertFalse(source_policy_allows("github_page", "https://example.com/Tool")); self.assertFalse(source_policy_allows("github_page", "https://github.com/Example/Tool", authenticated=True))

    def test_run_lifecycle_budget_and_recovery(self):
        self.enabled(); grant = self.store.active_grant(); assert grant
        run = self.store.create_run(trigger="manual", grant=grant)
        with self.assertRaises(NightOwlConflictError): self.store.create_run(trigger="manual", grant=grant)
        run = self.store.transition_run(run.identifier, "running", expected_revision=run.revision)
        with self.assertRaises(Exception): self.store.transition_run(run.identifier, "completed", expected_revision=run.revision, budget_used={"searches": DEFAULT_BUDGETS["searches"] + 1})
        recovered = self.store.recover_startup(); self.assertEqual(recovered[0].state, "interrupted")

    def test_findings_deduplicate_change_and_suppression(self):
        self.enabled()
        first, changed = self.store.record_finding(self.draft()); self.assertTrue(changed)
        duplicate, changed = self.store.record_finding(self.draft()); self.assertFalse(changed)
        seen = self.store.mark_finding(first.identity_key, "seen", expected_revision=duplicate.revision); self.assertEqual(seen.state, "seen")
        updated, changed = self.store.record_finding(self.draft("2" * 64)); self.assertTrue(changed); self.assertEqual(updated.state, "new")

    def test_unchanged_observation_refreshes_presentation_without_new_version(self):
        self.enabled()
        first, changed = self.store.record_finding(self.draft())
        self.assertTrue(changed)
        refreshed_draft = FindingDraft(
            "local_models", "github:Example/Tool.git", "project", "Example Tool",
            "A local inference service with an OpenAI-compatible API.",
            ("category_match", "protocol_fit"), (), (), "Review compatibility.",
            "1" * 64, "release:1", "new release",
            (SourceAttribution("github_page", "https://github.com/Example/Tool", "Tool", "github:example/tool"),),
        )
        refreshed, changed = self.store.record_finding(refreshed_draft)
        self.assertFalse(changed)
        self.assertEqual(refreshed.state, "new")
        self.assertEqual(
            self.store.get_finding_detail(first.identifier).summary,
            "A local inference service with an OpenAI-compatible API.",
        )
        with sqlite3.connect(self.store.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM night_owl_finding_versions").fetchone(), (1,))

    def test_current_policy_withdrawal_preserves_history_without_dismissal(self):
        self.enabled()
        first, _ = self.store.record_finding(self.draft())
        withdrawn = self.store.withdraw_finding(
            "local_models", "github:example/tool", "project"
        )
        self.assertIsNotNone(withdrawn)
        assert withdrawn is not None
        self.assertEqual(withdrawn.state, "stale")
        self.assertEqual(self.store.get_finding(first.identity_key).state, "stale")

    def test_corrupt_store_fails_closed(self):
        self.enabled(); path = self.store.path
        import sqlite3
        with sqlite3.connect(path) as c: c.execute("DROP INDEX night_owl_runs_state")
        with self.assertRaises(NightOwlCorruptError): self.store.settings()
