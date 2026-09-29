from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tori.app import _backup_root_for_project
from tori.backups import PRODUCTION_BACKUP_ROOT, PRODUCTION_PROJECT_ROOT


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"
PROJECT_PYTHON = Path(os.environ.get("TORI_TEST_PROJECT_PYTHON", sys.executable))


class PortableInstallerTests(unittest.TestCase):
    maxDiff = None

    def test_clone_backup_root_cannot_borrow_canonical_backups(self) -> None:
        self.assertEqual(_backup_root_for_project(PRODUCTION_PROJECT_ROOT), PRODUCTION_BACKUP_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            clone = Path(temporary) / "Tori"
            self.assertEqual(_backup_root_for_project(clone), clone.parent / "Tori_backups")
            self.assertNotEqual(_backup_root_for_project(clone), PRODUCTION_BACKUP_ROOT)

    def _project(
        self, root: Path, *, include_local_config: bool = True
    ) -> tuple[Path, Path, Path]:
        project = root / "Tori"
        project.mkdir()
        shutil.copy2(INSTALLER, project / "install.sh")
        os.chmod(project / "install.sh", 0o755)
        shutil.copy2(ROOT / "start-tori.sh", project / "start-tori.sh")
        os.chmod(project / "start-tori.sh", 0o755)
        if include_local_config:
            shutil.copy2(ROOT / "deploy/portable/tori.toml", project / "tori.toml")
        shutil.copy2(ROOT / "requirements.txt", project / "requirements.txt")
        shutil.copytree(ROOT / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "deploy", project / "deploy", ignore=shutil.ignore_patterns(".venv", "__pycache__"))

        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        log = root / "commands.log"
        self._write_executable(
            fake_bin / "python3",
            f"""#!/usr/bin/env bash
set -eu
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "venv" ]]; then
    destination=$3
    mkdir -p "$destination/bin"
    printf '%s\n' 'fixture venv' >"$destination/pyvenv.cfg"
    cat >"$destination/bin/python" <<'WRAPPER'
#!/usr/bin/env bash
set -eu
if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "pip" ]]; then
    if [[ "${{3:-}}" == "--version" ]]; then
        printf '%s\n' 'pip fixture'
    else
        printf 'pip' >>"${{TORI_INSTALLER_TEST_LOG}}"
        printf ' %q' "$@" >>"${{TORI_INSTALLER_TEST_LOG}}"
        printf '\n' >>"${{TORI_INSTALLER_TEST_LOG}}"
    fi
    exit 0
fi
if [[ "${{1:-}}" == "-" && "${{2:-}}" == "127.0.0.1" ]]; then
    case ",${{TORI_INSTALLER_TEST_READY_PORTS:-}}," in
        *",${{3:-}},"*) exit 0 ;;
        *) exit 1 ;;
    esac
fi
exec {PROJECT_PYTHON} "$@"
WRAPPER
    chmod 0755 "$destination/bin/python"
    exit 0
fi
exec {PROJECT_PYTHON} "$@"
""",
        )
        self._write_executable(fake_bin / "ollama", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            fake_bin / "opencode", "#!/bin/sh\nprintf '%s\\n' '1.18.31'\n"
        )
        self._write_executable(fake_bin / "bwrap", "#!/bin/sh\nexit 0\n")
        self._write_executable(
            fake_bin / "sudo",
            "#!/bin/sh\nprintf 'sudo %s\\n' \"$*\" >>\"$TORI_INSTALLER_TEST_LOG\"\n",
        )
        self._write_executable(fake_bin / "visudo", "#!/bin/sh\nexit 0\n")
        return project, fake_bin, log

    @staticmethod
    def _write_executable(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o755)

    def _run(
        self,
        project: Path,
        fake_bin: Path,
        log: Path,
        *arguments: str,
        input_text: str = "",
        python_command: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{fake_bin}:/usr/sbin:/usr/bin:/sbin:/bin",
                "TORI_INSTALLER_PYTHON": python_command or str(fake_bin / "python3"),
                "TORI_INSTALLER_TEST_LOG": str(log),
                "PYTHONDONTWRITEBYTECODE": "1",
                "XDG_CONFIG_HOME": str(project.parent / "xdg-config"),
                "XDG_DATA_HOME": str(project.parent / "xdg-data"),
                "XDG_CACHE_HOME": str(project.parent / "xdg-cache"),
            }
        )
        return subprocess.run(
            (str(project / "install.sh"), *arguments),
            cwd=project,
            env=environment,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_missing_local_config_is_created_from_exact_validated_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(
                Path(temporary), include_local_config=False
            )
            template = (project / "deploy/portable/tori.toml").read_bytes()

            completed = self._run(project, fake_bin, log, "--non-interactive")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((project / "tori.toml").read_bytes(), template)
            self.assertIn(
                "Created local tori.toml from deploy/portable/tori.toml.",
                completed.stdout,
            )
            validation = subprocess.run(
                (
                    str(PROJECT_PYTHON),
                    "-c",
                    "from pathlib import Path; from tori.config import load_settings; "
                    "load_settings(Path('tori.toml'), environ={})",
                ),
                cwd=project,
                env={**os.environ, "PYTHONPATH": str(project / "src")},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            generic = template.decode("utf-8")
            self.assertNotRegex(
                generic,
                re.compile(r"http://(?!127\.0\.0\.1)(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)"),
            )
            self.assertNotIn("data_root =", generic)
            self.assertNotIn("[coding_work]", generic)
            for section in ("search", "tts", "planning", "finance"):
                self.assertRegex(generic, rf"\[{section}\]\nenabled = false")

    def test_existing_local_config_is_preserved_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            config = project / "tori.toml"
            before = config.read_bytes()

            completed = self._run(project, fake_bin, log, "--non-interactive")

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(config.read_bytes(), before)
            self.assertIn("Preserving the existing local tori.toml", completed.stdout)

    def test_symlink_or_nonregular_local_config_is_rejected(self) -> None:
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                project, fake_bin, log = self._project(
                    Path(temporary), include_local_config=False
                )
                config = project / "tori.toml"
                if kind == "symlink":
                    target = project / "outside-config"
                    target.write_bytes(b"do not follow")
                    config.symlink_to(target)
                else:
                    config.mkdir()

                completed = self._run(project, fake_bin, log, "--non-interactive")

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("not a safe regular file", completed.stderr)
                self.assertFalse((project / ".venv").exists())
                if kind == "symlink":
                    self.assertEqual(target.read_bytes(), b"do not follow")
                    self.assertTrue(config.is_symlink())
                else:
                    self.assertTrue(config.is_dir())

    def test_creation_collision_never_overwrites_race_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(
                Path(temporary), include_local_config=False
            )
            winner = b"race winner\n"
            self._write_executable(
                fake_bin / "ln",
                """#!/usr/bin/env bash
set -eu
printf '%s' "$TORI_INSTALLER_TEST_RACE_WINNER" >"$TORI_INSTALLER_TEST_RACE_PATH"
exec /usr/bin/ln "$@"
""",
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:/usr/sbin:/usr/bin:/sbin:/bin",
                    "TORI_INSTALLER_PYTHON": str(fake_bin / "python3"),
                    "TORI_INSTALLER_TEST_LOG": str(log),
                    "TORI_INSTALLER_TEST_READY_PORTS": "",
                    "TORI_INSTALLER_TEST_RACE_PATH": str(project / "tori.toml"),
                    "TORI_INSTALLER_TEST_RACE_WINNER": winner.decode("utf-8"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )

            completed = subprocess.run(
                (str(project / "install.sh"), "--non-interactive"),
                cwd=project,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("appeared during configuration setup", completed.stderr)
            self.assertEqual((project / "tori.toml").read_bytes(), winner)
            self.assertFalse(any(project.glob(".tori.toml.install.*")))
            self.assertFalse((project / ".venv").exists())

    def test_invalid_template_does_not_publish_local_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(
                Path(temporary), include_local_config=False
            )
            (project / "deploy/portable/tori.toml").write_text(
                "[model\ninvalid", encoding="utf-8"
            )

            completed = self._run(project, fake_bin, log, "--non-interactive")

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("did not pass Tori validation", completed.stderr)
            self.assertFalse((project / "tori.toml").exists())
            self.assertFalse(any(project.glob(".tori.toml.install.*")))
            self.assertFalse((project / ".venv").exists())

    def test_help_exits_without_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            before = (project / "tori.toml").read_bytes()
            completed = self._run(project, fake_bin, log, "--help")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("--non-interactive", completed.stdout)
            self.assertFalse((project / ".venv").exists())
            self.assertEqual((project / "tori.toml").read_bytes(), before)

    def test_noninteractive_fresh_core_install_skips_optional_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            before = (project / "tori.toml").read_bytes()
            completed = self._run(
                project, fake_bin, log, "--non-interactive"
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Tori core installation complete.", completed.stdout)
            self.assertIn("./start-tori.sh", completed.stdout)
            self.assertNotIn("[y/N]", completed.stdout)
            self.assertNotIn("Would you like to set up", completed.stdout)
            self.assertIn("Configure model providers and other external services later", completed.stdout)
            self.assertTrue((project / ".venv/pyvenv.cfg").is_file())
            self.assertIn("requirements.txt", log.read_text(encoding="utf-8"))
            self.assertEqual((project / "tori.toml").read_bytes(), before)
            self.assertFalse((project / "runtime").exists())

    def test_existing_runtime_is_refused_without_inspection_or_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            runtime = project / "runtime"
            runtime.mkdir()
            marker = runtime / "valuable.bin"
            marker.write_bytes(b"preserve exactly")
            completed = self._run(
                project, fake_bin, log, "--non-interactive"
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("runtime already exists", completed.stderr)
            self.assertEqual(marker.read_bytes(), b"preserve exactly")
            self.assertFalse((project / ".venv").exists())
            self.assertFalse(log.exists())

    def test_invalid_existing_venv_is_not_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            venv = project / ".venv"
            venv.mkdir()
            marker = venv / "owner-file"
            marker.write_text("keep\n", encoding="utf-8")
            completed = self._run(
                project, fake_bin, log, "--non-interactive"
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("not a valid reusable virtual environment", completed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_valid_venv_is_rerunnable_before_first_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            first = self._run(project, fake_bin, log, "--non-interactive")
            second = self._run(project, fake_bin, log, "--non-interactive")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Reusing the existing valid .venv", second.stdout)
            self.assertFalse((project / "runtime").exists())

    def test_start_helper_uses_its_own_root_and_clears_pythonhome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            completed = self._run(project, fake_bin, log, "--non-interactive")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self._write_executable(
                project / ".venv/bin/python",
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$PWD|$PYTHONPATH|${PYTHONHOME-unset}|$*\"\n",
            )
            result = subprocess.run(
                (str(project / "start-tori.sh"),), cwd=project.parent,
                env={**os.environ, "PYTHONHOME": "/another/project", "PYTHONPATH": "/another/project"},
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"{project}|{project / 'src'}|unset|-m tori --web", result.stdout)

    def test_missing_python_fails_without_package_or_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            completed = self._run(
                project,
                fake_bin,
                log,
                "--non-interactive",
                python_command="/definitely/missing/tori-python",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("python3 is missing", completed.stderr)
            self.assertFalse((project / ".venv").exists())
            self.assertFalse(log.exists())

    def test_interactive_does_not_probe_or_onboard_external_providers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            completed = self._run(
                project,
                fake_bin,
                log,
                input_text="y\ny\ny\n",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            config = (project / "tori.toml").read_text(encoding="utf-8")
            self.assertIn("[search]\nenabled = false", config)
            self.assertIn("[tts]\nenabled = false", config)
            self.assertIn("[planning]\nenabled = false", config)
            self.assertNotIn("[y/N]", completed.stdout)
            self.assertNotIn("sudo ", completed.stdout)
            self.assertFalse((project / "runtime").exists())
            self.assertNotIn("sudo ", log.read_text(encoding="utf-8"))

    def test_optional_component_flags_fail_before_any_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary))
            for flag in ("--with-voice", "--with-research"):
                with self.subTest(flag=flag):
                    completed = self._run(project, fake_bin, log, "--non-interactive", flag)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("unsupported installer argument", completed.stderr)
                    self.assertFalse((project / ".venv").exists())
                    self.assertFalse(log.exists())

    def test_owner_xdg_and_python_paths_are_not_used_by_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, fake_bin, log = self._project(Path(temporary), include_local_config=False)
            owner = Path(temporary) / "owner"
            (owner / "tori").mkdir(parents=True)
            sentinel = owner / "tori/local-model-providers.json"
            sentinel.write_bytes(b"owner-private-sentinel")
            previous = os.environ.copy()
            os.environ.update({"XDG_CONFIG_HOME": str(owner), "PYTHONPATH": str(owner), "PYTHONHOME": str(owner)})
            try:
                result = self._run(project, fake_bin, log, "--non-interactive")
            finally:
                os.environ.clear()
                os.environ.update(previous)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sentinel.read_bytes(), b"owner-private-sentinel")
            self.assertNotIn("owner-private-sentinel", (project / "tori.toml").read_text())
            self.assertIn("check", log.read_text(encoding="utf-8"))

    def test_installer_contains_no_upgrade_gpu_service_or_canonical_runtime_actions(self) -> None:
        text = INSTALLER.read_text(encoding="utf-8")
        lowered = text.lower()
        for forbidden in (
            "apt full-upgrade",
            "apt-get upgrade",
            "nvidia-driver",
            "cuda-toolkit",
            "rocm-dev",
            "systemctl enable",
            "systemctl daemon-reload",
            "/etc/systemd/system",
            "/workspaces/tori/runtime",
            "eval ",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)
        self.assertIn("runtime already exists", text)
        self.assertIn("--non-interactive", text)


if __name__ == "__main__":
    unittest.main()
