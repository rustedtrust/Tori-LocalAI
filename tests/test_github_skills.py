from __future__ import annotations

from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.agent_skills import (
    AgentInstructionSkillAdapter,
    AgentSkillAdministration,
    AgentSkillImporter,
    AgentSkillPackageStore,
)
from tori.github_skills import (
    GitHubSkillAcquisitionService,
    GitHubHTTPTransport,
    GitHubSkillLifecycleService,
    GitHubSkillNetworkError,
    GitHubSkillProposalError,
    GitHubSkillSourceError,
    parse_github_skill_url,
)
from tori.media_inspect import (
    ExecutableIdentity,
    MediaInspectAdapter,
    MediaSelectionRegistry,
    build_media_inspect_manifest,
    media_inspect_permissions,
)
from tori.request_origin import OriginAuthorityError, RequestOrigin
from tori.skills import (
    SQLiteSkillRegistry,
    SkillApplicationService,
    SkillComponentKind,
)
from tori.skills_management import skills_management_document


COMMIT = "1" * 40
SKILL_MD = b"""---
name: concise-writing
description: Helps revise prose into clear, concise writing.
license: MIT
---
# Concise writing

Prefer concrete words and remove repetition.
"""


class FakeTransport:
    def __init__(self, content: dict[str, bytes] | None = None) -> None:
        self.content = content or {"SKILL.md": SKILL_MD}
        self.sources = []
        self.downloads = []

    def resolve_commit(self, source):
        self.sources.append(source)
        return COMMIT

    def download_package(self, source, commit):
        self.downloads.append((source, commit))
        return self.content


class FailingTransport(FakeTransport):
    def resolve_commit(self, source):
        raise GitHubSkillNetworkError()


class GitHubSkillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.registry = SQLiteSkillRegistry(
            root / "registry.sqlite3",
            clock=lambda: datetime(2026, 9, 5, tzinfo=timezone.utc),
        )
        self.packages = AgentSkillPackageStore(root / "packages")
        self.application = SkillApplicationService(
            self.registry,
            {SkillComponentKind.INSTRUCTION_ONLY: AgentInstructionSkillAdapter(self.packages)},
        )
        self.admin = AgentSkillAdministration(self.application, self.packages)
        self.transport = FakeTransport()
        self.acquisition = GitHubSkillAcquisitionService(
            AgentSkillImporter(clock=lambda: datetime(2026, 9, 5, tzinfo=timezone.utc)),
            transport=self.transport,
            quarantine_parent=root,
        )
        self.lifecycle = GitHubSkillLifecycleService(
            self.acquisition,
            self.admin,
            clock=lambda: 100.0,
            token_factory=iter(("install-token", "enable-token")).__next__,
        )
        self.origin = RequestOrigin.local_web()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_url_normalization_and_mutable_revision_pinning(self) -> None:
        source = parse_github_skill_url(
            "https://github.com/Owner/Repository/tree/main/skills/concise-writing"
        )
        self.assertEqual(source.repository_url, "https://github.com/owner/repository")
        self.assertEqual(source.revision, "main")
        self.assertEqual(source.package_path, "skills/concise-writing")
        summary = self.lifecycle.inspect(
            "https://github.com/Owner/Repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        self.assertEqual(summary.commit, COMMIT)
        self.assertEqual(summary.repository, source.repository_url)
        self.assertEqual(summary.license, "MIT")
        self.assertEqual(summary.compatibility, "compatible_instruction_only")
        self.assertEqual(len(self.transport.downloads), 1)
        self.assertFalse(any(Path(self.temporary.name).glob("tori-github-skill-*")))

    def test_install_is_one_use_disabled_then_separately_enabled(self) -> None:
        proposal = self.lifecycle.propose_install(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        self.assertFalse(self.registry.exists)
        self.assertEqual(proposal.summary.commit, COMMIT)
        entry = self.lifecycle.decide_install(proposal.token, "confirm", origin=self.origin)
        assert entry is not None
        self.assertEqual(entry.state, "installed_disabled")
        with self.assertRaises(GitHubSkillProposalError):
            self.lifecycle.decide_install(proposal.token, "confirm", origin=self.origin)
        enable = self.lifecycle.propose_enable(entry.manifest.version_ref, origin=self.origin)
        self.assertEqual(self.registry.get(entry.manifest.version_ref).state, "installed_disabled")
        enabled = self.lifecycle.decide_enable(enable.token, "confirm", origin=self.origin)
        assert enabled is not None
        self.assertEqual(enabled.state, "enabled")
        result = self.application.invoke(
            enabled.manifest.version_ref,
            "apply",
            {"request": "Please make this paragraph concise."},
            origin=self.origin,
        )
        self.assertEqual(result.status, "succeeded")
        self.assertIn("remove repetition", result.metadata["guidance"])

    def test_builtin_enable_proposal_uses_registered_adapter_compatibility(self) -> None:
        identity = ExecutableIdentity(
            "/usr/bin/ffprobe", "ffprobe version acceptance", "sha256:" + "c" * 64,
            1, 2, 3, 4,
        )
        selections = MediaSelectionRegistry()
        registry = SQLiteSkillRegistry(Path(self.temporary.name) / "builtin.sqlite3")
        registry.initialize()
        application = SkillApplicationService(
            registry,
            {SkillComponentKind.BOUNDED_EXECUTABLE: MediaInspectAdapter(
                selections, executable_inspector=lambda: identity
            )},
        )
        administration = AgentSkillAdministration(application, self.packages)
        lifecycle = GitHubSkillLifecycleService(self.acquisition, administration)
        manifest = build_media_inspect_manifest(
            identity, inspected_at=datetime(2026, 9, 5, tzinfo=timezone.utc)
        )
        installed = application.install(manifest, origin=self.origin)
        enabled = application.enable(
            manifest.version_ref,
            expected_revision=installed.revision,
            granted_permissions=media_inspect_permissions(),
            origin=self.origin,
        )
        application.disable(
            manifest.version_ref,
            expected_revision=enabled.revision,
            origin=self.origin,
        )

        proposal = lifecycle.propose_enable(manifest.version_ref, origin=self.origin)

        self.assertEqual(proposal.compatibility, "compatible")
        restored = lifecycle.decide_enable(proposal.token, "confirm", origin=self.origin)
        self.assertIsNotNone(restored)
        document = skills_management_document(application, origin=self.origin)["skills"][0]
        self.assertEqual(document["compatibility"], "compatible")
        self.assertEqual(document["health"], "available")

    def test_tampered_quarantine_invalidates_install(self) -> None:
        proposal = self.lifecycle.propose_install(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        quarantine = next(Path(self.temporary.name).glob("tori-github-skill-*"))
        skill_md = quarantine / "concise-writing" / "SKILL.md"
        skill_md.write_bytes(SKILL_MD + b"changed")
        with self.assertRaisesRegex(GitHubSkillProposalError, "changed") as caught:
            self.lifecycle.decide_install(proposal.token, "confirm", origin=self.origin)
        self.assertEqual(caught.exception.code, "stale_confirmation")
        self.assertFalse(self.registry.exists)
        self.assertFalse(quarantine.exists())

    def test_cancel_leaves_nothing_installed(self) -> None:
        proposal = self.lifecycle.propose_install(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        self.assertIsNone(self.lifecycle.decide_install(proposal.token, "cancel", origin=self.origin))
        self.assertFalse(self.registry.exists)
        self.assertFalse(any(Path(self.temporary.name).glob("tori-github-skill-*")))

    def test_expired_and_registry_changed_proposals_fail_closed(self) -> None:
        now = [100.0]
        lifecycle = GitHubSkillLifecycleService(
            self.acquisition, self.admin, clock=lambda: now[0]
        )
        expired = lifecycle.propose_install(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        now[0] = 401.0
        with self.assertRaises(GitHubSkillProposalError) as caught:
            lifecycle.decide_install(expired.token, "confirm", origin=self.origin)
        self.assertEqual(caught.exception.code, "expired_confirmation")
        self.assertFalse(any(Path(self.temporary.name).glob("tori-github-skill-*")))

        now[0] = 100.0
        stale = lifecycle.propose_install(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        self.registry.initialize()
        local = Path(self.temporary.name) / "local" / "other-skill"
        local.mkdir(parents=True)
        (local / "SKILL.md").write_text(
            "---\nname: other-skill\ndescription: A separate test Skill.\n---\nBody.\n",
            encoding="utf-8",
        )
        inspected = AgentSkillImporter().inspect_local(local, publisher="tests")
        self.admin.install(inspected, origin=self.origin)
        with self.assertRaises(GitHubSkillProposalError) as caught:
            lifecycle.decide_install(stale.token, "confirm", origin=self.origin)
        self.assertEqual(caught.exception.code, "stale_confirmation")
        self.assertEqual(len(self.registry.list_entries()), 1)

    def test_remote_origin_is_rejected_before_network(self) -> None:
        remote = RequestOrigin.discord_remote(
            connector_id="discord", external_message_id="m", external_actor_id="a",
            external_conversation_id="c",
        )
        with self.assertRaises(OriginAuthorityError):
            self.lifecycle.inspect(
                "https://github.com/owner/repository/tree/main/skills/concise-writing",
                origin=remote,
            )
        self.assertEqual(self.transport.sources, [])

    def test_network_and_unsafe_archive_fail_without_registry(self) -> None:
        failed = GitHubSkillLifecycleService(
            GitHubSkillAcquisitionService(
                AgentSkillImporter(), transport=FailingTransport(),
                quarantine_parent=Path(self.temporary.name),
            ), self.admin,
        )
        with self.assertRaises(GitHubSkillNetworkError):
            failed.inspect(
                "https://github.com/owner/repository/tree/main/skills/concise-writing",
                origin=self.origin,
            )
        unsafe = GitHubSkillLifecycleService(
            GitHubSkillAcquisitionService(
                AgentSkillImporter(), transport=FakeTransport({"SKILL.md": SKILL_MD, "../escape": b"x"}),
                quarantine_parent=Path(self.temporary.name),
            ), self.admin,
        )
        with self.assertRaises(GitHubSkillSourceError):
            unsafe.inspect(
                "https://github.com/owner/repository/tree/main/skills/concise-writing",
                origin=self.origin,
            )
        self.assertFalse(self.registry.exists)

    def test_downloaded_script_is_inventoried_but_never_executed(self) -> None:
        marker = Path(self.temporary.name) / "must-not-exist"
        script = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n".encode()
        transport = FakeTransport({"SKILL.md": SKILL_MD, "scripts/evil.py": script})
        lifecycle = GitHubSkillLifecycleService(
            GitHubSkillAcquisitionService(
                AgentSkillImporter(), transport=transport,
                quarantine_parent=Path(self.temporary.name),
            ), self.admin,
        )
        summary = lifecycle.inspect(
            "https://github.com/owner/repository/tree/main/skills/concise-writing",
            origin=self.origin,
        )
        self.assertEqual(summary.compatibility, "partially_compatible")
        self.assertIn("scripts", summary.unsupported_components)
        self.assertFalse(marker.exists())

    def test_selective_git_tree_acquires_only_requested_monorepo_subtree(self) -> None:
        blobs = {
            "SKILL.md": SKILL_MD,
            "references/guide.md": b"# Guide\nBounded reference.\n",
        }
        blob_shas = {
            name: hashlib.sha1(
                f"blob {len(content)}\0".encode("ascii") + content,
                usedforsecurity=False,
            ).hexdigest()
            for name, content in blobs.items()
        }
        root_sha, skills_sha, package_sha, references_sha = (
            character * 40 for character in "2345"
        )

        class SelectiveTransport(GitHubHTTPTransport):
            def __init__(self):
                super().__init__()
                self.urls = []

            def _read(self, source, url, limit, *, commit):
                self.urls.append(url)
                if "/commits/main?per_page=1" in url:
                    value = {"sha": COMMIT}
                elif f"/git/commits/{COMMIT}" in url:
                    value = {"tree": {"sha": root_sha}}
                elif f"/git/trees/{root_sha}" in url:
                    value = {"truncated": False, "tree": [
                        {"path": "skills", "mode": "040000", "type": "tree", "sha": skills_sha},
                        {"path": "oversized-unrelated-content", "mode": "040000", "type": "tree", "sha": "9" * 40},
                    ]}
                elif f"/git/trees/{skills_sha}" in url:
                    value = {"truncated": False, "tree": [
                        {"path": "documentation-writer", "mode": "040000", "type": "tree", "sha": package_sha},
                        *[
                            {"path": f"unrelated-{index}", "mode": "040000", "type": "tree", "sha": f"{index:040x}"}
                            for index in range(1, 100)
                        ],
                    ]}
                elif f"/git/trees/{package_sha}" in url:
                    value = {"truncated": False, "tree": [
                        {"path": "SKILL.md", "mode": "100644", "type": "blob", "sha": blob_shas["SKILL.md"], "size": len(blobs["SKILL.md"])},
                        {"path": "references", "mode": "040000", "type": "tree", "sha": references_sha},
                    ]}
                elif f"/git/trees/{references_sha}" in url:
                    value = {"truncated": False, "tree": [
                        {"path": "guide.md", "mode": "100644", "type": "blob", "sha": blob_shas["references/guide.md"], "size": len(blobs["references/guide.md"])},
                    ]}
                elif "/git/blobs/" in url:
                    sha = url.rsplit("/", 1)[-1]
                    name = next(name for name, value_sha in blob_shas.items() if value_sha == sha)
                    encoded = base64.b64encode(blobs[name]).decode("ascii")
                    value = {"sha": sha, "encoding": "base64", "content": encoded[:12] + "\n" + encoded[12:]}
                else:
                    raise AssertionError(f"unexpected GitHub request: {url}")
                return json.dumps(value).encode()

        transport = SelectiveTransport()
        source = parse_github_skill_url(
            "https://github.com/github/awesome-copilot/tree/main/skills/documentation-writer"
        )
        commit = transport.resolve_commit(source)
        package = transport.download_package(source, commit)

        self.assertEqual(dict(package), blobs)
        self.assertFalse(any("tarball" in url or "codeload" in url for url in transport.urls))
        self.assertFalse(any(("9" * 40) in url for url in transport.urls))
        self.assertEqual(commit, COMMIT)

    def test_malformed_and_non_github_urls_fail_closed(self) -> None:
        bad = (
            "http://github.com/o/r/tree/main/skills/x",
            "https://evil.example/o/r/tree/main/skills/x",
            "https://github.com/o/r/blob/main/skills/x",
            "https://user@github.com/o/r/tree/main/skills/x",
            "https://github.com/o/r/tree/main/../x",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(GitHubSkillSourceError):
                parse_github_skill_url(value)


if __name__ == "__main__":
    unittest.main()
