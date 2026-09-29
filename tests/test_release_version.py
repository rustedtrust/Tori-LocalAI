"""Public product version is independent of storage and protocol schemas."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tori import __version__


ROOT = Path(__file__).resolve().parents[1]


class PublicReleaseVersionTests(unittest.TestCase):
    def test_runtime_and_cli_report_the_approved_public_prerelease(self) -> None:
        self.assertEqual(__version__, "0.9.0-public.1")
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                (sys.executable, "-B", "-m", "tori", "--version"),
                cwd=ROOT,
                env={
                    "HOME": temporary,
                    "XDG_CONFIG_HOME": str(Path(temporary) / "config"),
                    "XDG_DATA_HOME": str(Path(temporary) / "data"),
                    "XDG_CACHE_HOME": str(Path(temporary) / "cache"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": str(ROOT / "src"),
                    "PATH": os.defpath,
                },
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "Tori 0.9.0-public.1")
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
