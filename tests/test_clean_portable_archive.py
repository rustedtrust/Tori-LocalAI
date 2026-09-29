from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/create-clean-portable-archive"
ROOT = SCRIPT.parents[1]


class PublicSnapshotArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.disposable = tempfile.TemporaryDirectory()
        self.addCleanup(self.disposable.cleanup)
        self.root = Path(self.disposable.name)
        self.project = self.root / "source"
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "deploy/portable").mkdir(parents=True)
        (self.project / "docs").mkdir()
        shutil.copyfile(SCRIPT, self.project / "scripts/create-clean-portable-archive")
        os.chmod(self.project / "scripts/create-clean-portable-archive", 0o755)
        (self.project / "deploy/portable/tori.toml").write_text(
            '[model]\ndefault_model = "synthetic"\n', encoding="utf-8"
        )
        (self.project / "README.md").write_text("Public candidate\n", encoding="utf-8")
        (self.project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.project / "THIRD_PARTY_NOTICES.md").write_text("Fixture notices\n", encoding="utf-8")
        (self.project / "SECURITY.md").write_text("Fixture security\n", encoding="utf-8")
        (self.project / "PUBLIC_SNAPSHOT_MANIFEST.md").write_text("Fixture policy\n", encoding="utf-8")
        (self.project / "docs/guide.md").write_text("Public guide\n", encoding="utf-8")
        self.entries = sorted((
            "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md",
            "PUBLIC_SNAPSHOT_MANIFEST.md", "PUBLIC_SNAPSHOT_FILES.txt", "deploy/portable/tori.toml",
            "docs/guide.md", "scripts/create-clean-portable-archive",
        ))
        self._manifest()

    def _manifest(self) -> None:
        (self.project / "PUBLIC_SNAPSHOT_FILES.txt").write_text(
            "\n".join(self.entries) + "\n", encoding="utf-8"
        )

    def _run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (str(self.project / "scripts/create-clean-portable-archive"),
             str(self.root / "public.zip")),
            capture_output=True, text=True, check=False,
        )

    def test_only_manifested_files_and_generic_config_are_included(self) -> None:
        (self.project / "runtime").mkdir()
        (self.project / "runtime/user.db").write_text("private interaction")
        (self.project / "tori.toml").write_text("private host settings")
        (self.project / ".git").mkdir()
        (self.project / ".git/config").write_text("private origin")
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.root / "public.zip") as package:
            self.assertEqual(set(package.namelist()),
                             {"Tori/" + item for item in self.entries} | {"Tori/tori.toml"})
            self.assertEqual(package.read("Tori/tori.toml"),
                             (self.project / "deploy/portable/tori.toml").read_bytes())
            self.assertEqual((package.getinfo("Tori/tori.toml").external_attr >> 16) & 0o777, 0o644)
            self.assertEqual((package.getinfo("Tori/scripts/create-clean-portable-archive").external_attr >> 16) & 0o777, 0o755)
            self.assertEqual((package.getinfo("Tori/README.md").external_attr >> 16) & 0o777, 0o644)
            payload = b"".join(package.read(n) for n in package.namelist())
            for marker in (b"private interaction", b"private host settings", b"private origin"):
                self.assertNotIn(marker, payload)

    def test_unreviewed_document_blocks_archive(self) -> None:
        (self.project / "docs/private-acceptance.md").write_text("private")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "public.zip").exists())

    def test_manifest_cannot_include_database_or_private_path(self) -> None:
        (self.project / "runtime").mkdir()
        (self.project / "runtime/user.db").write_text("private")
        self.entries = sorted((*self.entries, "runtime/user.db"))
        self._manifest()
        self.assertNotEqual(self._run().returncode, 0)

    def test_public_symlink_is_refused(self) -> None:
        (self.project / "docs/guide.md").unlink()
        (self.project / "docs/guide.md").symlink_to(self.root / "outside")
        self.assertNotEqual(self._run().returncode, 0)

    def test_license_and_security_policy_must_be_listed(self) -> None:
        for missing in ("LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"):
            with self.subTest(missing=missing):
                self.entries.remove(missing)
                self._manifest()
                self.assertNotEqual(self._run().returncode, 0)
                self.entries.append(missing)
                self.entries.sort()

    def test_vendored_frontend_requires_both_license_files(self) -> None:
        vendor = self.project / "src/tori/web_assets/vendor/xterm"
        vendor.mkdir(parents=True)
        (vendor / "xterm.js").write_text("synthetic asset\n", encoding="utf-8")
        self.entries.append("src/tori/web_assets/vendor/xterm/xterm.js")
        self.entries.sort()
        self._manifest()
        self.assertNotEqual(self._run().returncode, 0)

    def test_real_candidate_retains_complete_upstream_licenses(self) -> None:
        root = ROOT
        listed = set((root / "PUBLIC_SNAPSHOT_FILES.txt").read_text().splitlines())
        for name in (
            "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md",
            "src/tori/web_assets/vendor/xterm/LICENSE-xterm",
            "src/tori/web_assets/vendor/xterm/LICENSE-addon-fit",
            "deploy/voice/NOTICE.md",
        ):
            self.assertIn(name, listed)
        for name in (
            "src/tori/web_assets/vendor/xterm/LICENSE-xterm",
            "src/tori/web_assets/vendor/xterm/LICENSE-addon-fit",
            "deploy/voice/NOTICE.md",
        ):
            text = (root / name).read_text(encoding="utf-8")
            self.assertIn("Permission is hereby granted", text)
            self.assertIn("Copyright", text)


if __name__ == "__main__":
    unittest.main()
