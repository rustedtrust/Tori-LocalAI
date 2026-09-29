from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "start-tori.sh"


class StartToriScriptTests(unittest.TestCase):
    def _project(self, temporary: Path, *, with_python: bool) -> tuple[Path, Path]:
        project = temporary / "Tori project with spaces"
        project.mkdir()
        shutil.copy2(START_SCRIPT, project / "start-tori.sh")
        os.chmod(project / "start-tori.sh", 0o755)
        (project / "src").mkdir()
        log = temporary / "start.log"
        if with_python:
            python = project / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "printf 'cwd=%s\\n' \"$PWD\" >\"$TORI_START_TEST_LOG\"\n"
                "printf 'pythonpath=%s\\n' \"$PYTHONPATH\" >>\"$TORI_START_TEST_LOG\"\n"
                "printf 'args=' >>\"$TORI_START_TEST_LOG\"\n"
                "printf ' <%s>' \"$@\" >>\"$TORI_START_TEST_LOG\"\n"
                "printf '\\n' >>\"$TORI_START_TEST_LOG\"\n",
                encoding="utf-8",
            )
            os.chmod(python, 0o755)
        return project, log

    def test_shell_syntax_is_valid(self) -> None:
        completed = subprocess.run(
            ("bash", "-n", str(START_SCRIPT)),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_missing_environment_fails_with_installer_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, log = self._project(Path(temporary), with_python=False)
            completed = subprocess.run(
                (str(project / "start-tori.sh"),),
                cwd=Path(temporary),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Run ./install.sh", completed.stderr)
            self.assertFalse(log.exists())

    def test_resolves_root_and_executes_canonical_web_command_from_other_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, log = self._project(root, with_python=True)
            elsewhere = root / "somewhere else"
            elsewhere.mkdir()
            environment = os.environ.copy()
            environment["TORI_START_TEST_LOG"] = str(log)
            environment["PYTHONPATH"] = "/untrusted/inherited/path"
            completed = subprocess.run(
                (str(project / "start-tori.sh"),),
                cwd=elsewhere,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Starting Tori's web interface", completed.stdout)
            self.assertIn("Press Ctrl+C", completed.stdout)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(),
                [
                    f"cwd={project}",
                    f"pythonpath={project / 'src'}",
                    "args= <-m> <tori> <--web>",
                ],
            )

    def test_script_has_no_privilege_service_or_background_behavior(self) -> None:
        text = START_SCRIPT.read_text(encoding="utf-8")
        lowered = text.lower()
        for forbidden in ("sudo", "systemctl", "nohup", "daemon", "&>"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)
        self.assertIn('exec "$VENV_PYTHON" -m tori --web', text)


if __name__ == "__main__":
    unittest.main()
