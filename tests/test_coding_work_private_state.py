import hashlib
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.coding_work_private_state import SnapshotImport
from tori.coding_work_runtime import _validate_private_tree
from tori.coding_worker import CodingWorkerError


class SnapshotImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="tori-snapshot-import-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "state/data/opencode/snapshot"
        self.root.mkdir(parents=True, mode=0o700)

    def file(self, name, mode=0o600):
        path = self.root / name
        path.parent.mkdir(mode=0o700, exist_ok=True)
        path.write_bytes(b"synthetic unchanged snapshot content")
        path.chmod(mode)
        return path

    def test_all_proven_git_modes_import_with_identical_bytes(self):
        existing = self.file("existing")
        original = existing.stat()
        scope = SnapshotImport(self.root)
        modes = (0o400, 0o444, 0o600, 0o644, 0o664, 0o700)
        files = [self.file("file-" + str(mode), mode) for mode in modes]
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        scope.finish()
        self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in files])
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in files))
        self.assertEqual(existing.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(existing.stat().st_ctime_ns, original.st_ctime_ns)
        _validate_private_tree(self.root, require_quiescent=True)
        with self.assertRaises(CodingWorkerError):
            scope.finish()

    def test_cannot_arm_on_existing_unsafe_runtime(self):
        path = self.file("index", 0o664)
        with self.assertRaises(CodingWorkerError):
            SnapshotImport(self.root)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o664)

    def test_no_changes_when_any_incoming_entry_is_unsafe(self):
        for kind in ("symlink", "hardlink", "fifo", "mode", "owner", "directory"):
            with self.subTest(kind=kind), TemporaryDirectory() as temp:
                root = Path(temp) / "state/data/opencode/snapshot"
                root.mkdir(parents=True, mode=0o700)
                scope = SnapshotImport(root)
                allowed = root / "a-index"
                allowed.write_bytes(b"synthetic"); allowed.chmod(0o664)
                outside = Path(temp) / "outside"
                outside.write_bytes(b"outside unchanged"); outside.chmod(0o755)
                bad = root / "z-bad"
                if kind == "symlink": bad.symlink_to(outside)
                elif kind == "hardlink": os.link(outside, bad)
                elif kind == "fifo": os.mkfifo(bad, 0o600)
                elif kind == "directory": bad.mkdir(mode=0o755)
                else:
                    bad.write_bytes(b"bad")
                    bad.chmod(0o777 if kind == "mode" else 0o600)
                if kind == "owner":
                    with patch("tori.coding_work_private_state.os.geteuid", return_value=os.geteuid()+1):
                        with self.assertRaises(CodingWorkerError): scope.finish()
                else:
                    with self.assertRaises(CodingWorkerError): scope.finish()
                self.assertEqual(stat.S_IMODE(allowed.stat().st_mode), 0o664)
                self.assertEqual(outside.read_bytes(), b"outside unchanged")
                self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)

    def test_replaced_or_symlinked_root_is_not_authority(self):
        for linked in (False, True):
            with self.subTest(linked=linked), TemporaryDirectory() as temp:
                root = Path(temp) / "state/data/opencode/snapshot"
                root.mkdir(parents=True, mode=0o700)
                scope = SnapshotImport(root)
                moved = root.with_name("moved")
                root.rename(moved)
                if linked: root.symlink_to(moved, target_is_directory=True)
                else: root.mkdir(mode=0o700)
                with self.assertRaises(CodingWorkerError): scope.finish()

    def test_file_identity_race_is_rejected_before_chmod(self):
        scope = SnapshotImport(self.root)
        target = self.file("index", 0o664)
        real_open = os.open
        def replaced(path, flags, *args, **kwargs):
            if path == "index":
                target.rename(self.root / "old-index")
                self.file("index", 0o644)
            return real_open(path, flags, *args, **kwargs)
        with patch("tori.coding_work_private_state.os.open", side_effect=replaced):
            with self.assertRaises(CodingWorkerError): scope.finish()
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((self.root / "old-index").stat().st_mode), 0o664)
