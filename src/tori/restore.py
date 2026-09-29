"""Bounded verified restore planning for Tori-owned source and runtime state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from .agent_skills import restore_skills_from_backup
from .backups import BackupError, BackupService, BackupVerificationError, MANIFEST_NAME, MAX_MANIFEST_BYTES
from .config import ConfigError, load_settings
from .operation_coordinator import OperationCoordinator
from .skills import SkillError


# Pin the independently reviewed public source identity. A backup's embedded
# remote, local Git configuration, or user-controlled setting cannot change it.
TRUSTED_TORI_ORIGIN = "https://github.com/rustedtrust/Tori-LocalAI.git"
RESTORE_PLAN_SCHEMA = 1
RESTORE_CONFIRMATION_SECONDS = 300
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_BACKUP = re.compile(r"Tori_[0-9]{8}_[0-9]{6}_[0-9a-f]{16}\Z")
_INCOMPLETE = re.compile(r"\.Tori_[0-9]{8}_[0-9]{6}_[0-9a-f]{16}\.incomplete\Z")


class RestoreError(RuntimeError):
    """A safe, user-presentable restore lifecycle failure."""

    code = "restore_failed"


class RestoreBusyError(RestoreError):
    code = "restore_busy"


class RestoreConfirmationError(RestoreError):
    code = "restore_confirmation_invalid"


class RestoreCompatibilityError(RestoreError):
    code = "restore_incompatible"


class RestoreHandoffError(RestoreError):
    code = "restore_handoff_failed"


@dataclass(frozen=True, slots=True)
class RestoreProposal:
    token: str
    backup_identifier: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class PreparedRestore:
    operation_id: str
    candidate_path: Path
    rollback_path: Path
    evidence_path: Path
    handoff_path: Path
    plan_path: Path
    helper_path: Path
    safety_backup_identifier: str
    target_commit: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)
    finally:
        os.close(descriptor)


def _tree_identity(root: Path) -> str:
    """Hash candidate paths, modes, and bytes, excluding Git metadata and .venv."""

    digest = hashlib.sha256()
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_root = current_path.relative_to(root)
        if relative_root == Path("."):
            directories[:] = [name for name in sorted(directories) if name not in {".git", ".venv"}]
        else:
            directories[:] = sorted(directories)
        for name in directories:
            child = current_path / name
            info = os.lstat(child)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RestoreCompatibilityError("The restore candidate contains an unsafe object.")
            relative = child.relative_to(root).as_posix()
            digest.update(f"D\0{relative}\0{stat.S_IMODE(info.st_mode):04o}\0".encode("utf-8"))
        for name in sorted(files):
            child = current_path / name
            info = os.lstat(child)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RestoreCompatibilityError("The restore candidate contains an unsafe object.")
            relative = child.relative_to(root).as_posix()
            digest.update(f"F\0{relative}\0{stat.S_IMODE(info.st_mode):04o}\0{info.st_size}\0".encode("utf-8"))
            digest.update(bytes.fromhex(_sha256(child)))
    return digest.hexdigest()


def _regular_file(path: Path, description: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RestoreCompatibilityError(f"{description} is unavailable.") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RestoreCompatibilityError(f"{description} is not a safe regular file.")
    return info


def _ordinary_directory(path: Path, description: str) -> os.stat_result:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RestoreCompatibilityError(f"{description} is unavailable.") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RestoreCompatibilityError(f"{description} is not a safe directory.")
    return info


class TrustedSourceResolver:
    """Resolve restore source only through the configured sanitized history."""

    def __init__(self, project_root: Path, *, origin: str | None = TRUSTED_TORI_ORIGIN) -> None:
        self.project_root = Path(project_root).resolve()
        self.origin = origin

    def current_commit(self) -> str:
        value = self._git("rev-parse", "HEAD").strip()
        if _COMMIT.fullmatch(value) is None:
            raise RestoreCompatibilityError("The current source identity is invalid.")
        return value

    def source_is_trusted(self, commit: str | None) -> bool:
        if not self.origin or commit is None or _COMMIT.fullmatch(commit) is None:
            return False
        try:
            if self._git("remote", "get-url", "origin").strip() != self.origin:
                return False
            self._git("cat-file", "-e", f"{commit}^{{commit}}")
            self._git("show-ref", "--verify", "refs/remotes/origin/main")
            completed = subprocess.run(
                ["git", "-C", str(self.project_root), "merge-base", "--is-ancestor", commit, "refs/remotes/origin/main"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return completed.returncode == 0
        except RestoreCompatibilityError:
            return False

    def stage_source(self, commit: str, destination: Path) -> None:
        if not self.source_is_trusted(commit):
            raise RestoreCompatibilityError(
                "The backup source version is not available in Tori's trusted sanitized history."
            )
        if os.path.lexists(destination):
            raise RestoreCompatibilityError("The restore candidate path already exists.")
        self._run(
            "clone", "--no-hardlinks", "--no-checkout", "--", str(self.project_root), str(destination)
        )
        try:
            self._run_at(destination, "checkout", "-B", "main", commit)
            self._run_at(destination, "remote", "set-url", "origin", self.origin)
            self._run_at(destination, "branch", "--set-upstream-to=origin/main", "main")
            if self._git_at(destination, "rev-parse", "HEAD").strip() != commit:
                raise RestoreCompatibilityError("The staged source identity did not verify.")
            if self._git_at(destination, "remote", "get-url", "origin").strip() != self.origin:
                raise RestoreCompatibilityError("The staged trusted origin did not verify.")
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            raise

    def _git(self, *arguments: str) -> str:
        return self._git_at(self.project_root, *arguments)

    @staticmethod
    def _git_at(root: Path, *arguments: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RestoreCompatibilityError("Tori could not verify trusted source history.") from exc

    def _run(self, *arguments: str) -> None:
        self._run_at(self.project_root, *arguments)

    @staticmethod
    def _run_at(root: Path, *arguments: str) -> None:
        try:
            subprocess.run(
                ["git", "-C", str(root), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RestoreCompatibilityError("Tori could not stage trusted source history.") from exc


def _copy_runtime(
    source: Path, destination: Path, *, exclude_skills: bool = True,
    private_assets: bool = False,
) -> None:
    """Copy one verified regular tree without following unsafe objects."""

    if not os.path.lexists(source):
        return
    label = "The backed-up Voice assets" if private_assets else "The backed-up runtime"
    root_info = _ordinary_directory(source, label)
    if private_assets and (root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022):
        raise RestoreCompatibilityError("The backed-up Voice assets have unsafe permissions.")
    destination.mkdir(mode=0o700)
    for current, directories, files in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_root = destination / relative
        directories[:] = sorted(directories)
        if relative == Path(".") and exclude_skills:
            directories[:] = [name for name in directories if name != "skills"]
        for name in directories:
            child = current_path / name
            info = os.lstat(child)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RestoreCompatibilityError(f"{label} contains an unsafe object.")
            if private_assets and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
                raise RestoreCompatibilityError("The backed-up Voice assets have unsafe permissions.")
            target = target_root / name
            target.mkdir(mode=stat.S_IMODE(info.st_mode))
        for name in sorted(files):
            child = current_path / name
            info = os.lstat(child)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise RestoreCompatibilityError(f"{label} contains an unsafe object.")
            if private_assets and (info.st_uid != os.geteuid() or info.st_mode & 0o022):
                raise RestoreCompatibilityError("The backed-up Voice assets have unsafe permissions.")
            target = target_root / name
            source_fd = os.open(child, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            target_fd = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                stat.S_IMODE(info.st_mode),
            )
            try:
                while True:
                    block = os.read(source_fd, 1024 * 1024)
                    if not block:
                        break
                    os.write(target_fd, block)
                os.fsync(target_fd)
            finally:
                os.close(source_fd)
                os.close(target_fd)
            os.chmod(target, stat.S_IMODE(info.st_mode), follow_symlinks=False)


def _copy_voice_assets(payload: Path, candidate: Path, manifest_sha256: str) -> None:
    """Recover only Tori's verified project-local Voice model root."""

    models = payload / "models"
    if not os.path.lexists(models):
        return
    parent_info = _ordinary_directory(models, "The backed-up model directory")
    voice = models / "voice"
    if not os.path.lexists(voice):
        return
    _ordinary_directory(voice, "The backed-up Voice model directory")
    if parent_info.st_uid != os.geteuid() or parent_info.st_mode & 0o022:
        raise RestoreCompatibilityError("The backed-up Voice assets have unsafe permissions.")
    try:
        descriptor = os.open(
            payload.parent / MANIFEST_NAME,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as handle:
            encoded = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(encoded) > MAX_MANIFEST_BYTES or hashlib.sha256(encoded).hexdigest() != manifest_sha256:
            raise RestoreCompatibilityError("The selected Voice asset manifest changed.")
        entries = json.loads(encoded)["entries"]
        expected = {
            entry["path"]: entry for entry in entries
            if entry["path"] == "models/voice" or entry["path"].startswith("models/voice/")
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RestoreCompatibilityError("The selected Voice asset manifest is unsafe.") from exc
    if expected.get("models/voice", {}).get("type") != "directory":
        raise RestoreCompatibilityError("The backed-up Voice asset root is not verified.")
    destination = candidate / "models"
    if os.path.lexists(destination):
        target_info = _ordinary_directory(destination, "The trusted model directory")
        if target_info.st_uid != os.geteuid() or target_info.st_mode & 0o002:
            raise RestoreCompatibilityError("The trusted model directory is unsafe.")
    else:
        destination.mkdir(mode=stat.S_IMODE(parent_info.st_mode))
    if os.path.lexists(destination / "voice"):
        raise RestoreCompatibilityError("Trusted source already occupies the Voice model root.")
    _copy_runtime(voice, destination / "voice", exclude_skills=False, private_assets=True)
    actual: set[str] = set()
    for root, directories, files in os.walk(destination / "voice", followlinks=False):
        names = [*directories, *files]
        if Path(root) == destination / "voice":
            names.insert(0, ".")
        for name in names:
            path = Path(root) if name == "." else Path(root) / name
            relative = path.relative_to(candidate).as_posix()
            record = expected.get(relative)
            info = os.lstat(path)
            if record is None or info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise RestoreCompatibilityError("The restored Voice asset tree did not verify.")
            kind = "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else None
            if kind != record["type"] or stat.S_IMODE(info.st_mode) & ~record["mode"]:
                raise RestoreCompatibilityError("The restored Voice asset tree did not verify.")
            if kind == "file" and (info.st_size != record["size"] or _sha256(path) != record["sha256"]):
                raise RestoreCompatibilityError("A restored Voice asset did not match its verified backup.")
            actual.add(relative)
    if actual != set(expected):
        raise RestoreCompatibilityError("The restored Voice asset inventory did not verify.")


def _verify_runtime_sqlite(runtime: Path) -> None:
    if not runtime.exists():
        return
    for path in runtime.rglob("*"):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
        ):
            raise RestoreCompatibilityError("The restored runtime contains an unsafe object.")
        if stat.S_ISREG(info.st_mode) and path.suffix in {".db", ".sqlite", ".sqlite3"}:
            try:
                with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
            except sqlite3.Error as exc:
                raise RestoreCompatibilityError("A restored runtime database failed integrity verification.") from exc
            if result != ("ok",):
                raise RestoreCompatibilityError("A restored runtime database failed integrity verification.")


class RestoreService:
    """Own UI proposals, safety backup, staging, and external handoff."""

    confirmation_message = (
        "Tori will create and verify a fresh safety backup, then fully reverify the selected "
        "backup. If verification fails, restore stops before staging. If it succeeds, Tori will "
        "stop temporarily and replace current Tori runtime/state. This machine's current "
        "tori.toml will be preserved. Finance, Radicale, and Knowledge source data are not "
        "restored. Continue with this one restore?"
    )

    def __init__(
        self,
        backup_service: BackupService,
        operation_coordinator: OperationCoordinator,
        *,
        project_root: Path,
        web_port: int,
        helper_source: Path | None = None,
        origin: str | None = TRUSTED_TORI_ORIGIN,
        monotonic: Callable[[], float] = time.monotonic,
        launcher: Callable[[list[str], Path], object] | None = None,
        process_id: int | None = None,
    ) -> None:
        self.backups = backup_service
        self.coordinator = operation_coordinator
        self.project_root = Path(project_root).resolve()
        self.web_port = web_port
        self.resolver = TrustedSourceResolver(self.project_root, origin=origin)
        self.helper_source = helper_source or self.project_root / "scripts/tori-restore"
        self._monotonic = monotonic
        self._launcher = launcher or self._launch
        self._process_id = os.getpid() if process_id is None else process_id
        self._proposal: RestoreProposal | None = None
        self._pending = False

    @property
    def pending(self) -> bool:
        return self._pending

    def catalog(self) -> dict[str, Any]:
        # Publication metadata is not proof that the payload still matches it.
        discovered = {item.result.identifier: item for item in self.backups.discovered_publications()}
        records: list[dict[str, Any]] = []
        if not self.backups.backup_root.exists():
            return {"ok": True, "backups": records, "restore_pending": self._pending}
        try:
            children = sorted(os.scandir(self.backups.backup_root), key=lambda item: item.name, reverse=True)
        except OSError as exc:
            raise RestoreError("Tori could not inspect restore backups safely.") from exc
        for child in children:
            if not child.is_dir(follow_symlinks=False):
                continue
            if _INCOMPLETE.fullmatch(child.name):
                records.append(self._record(child.name, "Incomplete", None, None, None))
                continue
            if _BACKUP.fullmatch(child.name) is None:
                continue
            publication = discovered.get(child.name)
            if publication is None:
                records.append(self._record(child.name, "Invalid", None, None, None))
                continue
            result = publication.result
            if not publication.valid_source_commit:
                records.append(self._record(child.name, "Invalid", result.completed_at, result.total_regular_bytes, None))
                continue
            source_commit = publication.source_commit
            compatibility = "Eligible for verification" if self.resolver.source_is_trusted(source_commit) else "Legacy/manual recovery"
            records.append(self._record(child.name, compatibility, result.completed_at, result.total_regular_bytes, source_commit))
        return {"ok": True, "backups": records, "restore_pending": self._pending}

    @staticmethod
    def _record(identifier: str, compatibility: str, completed_at: str | None, size: int | None, source_commit: str | None) -> dict[str, Any]:
        return {
            "identifier": identifier,
            "completed_at": completed_at,
            "source_commit": source_commit,
            "total_regular_bytes": size,
            "verification": "not_rechecked" if compatibility in {"Eligible for verification", "Legacy/manual recovery"} else compatibility.lower(),
            "compatibility": compatibility,
            "selectable": compatibility == "Eligible for verification",
        }

    def propose(self, identifier: object) -> dict[str, Any]:
        if self._pending or self._proposal is not None:
            raise RestoreBusyError("A restore decision or handoff is already pending.")
        if not isinstance(identifier, str) or _BACKUP.fullmatch(identifier) is None:
            raise RestoreConfirmationError("A valid listed backup identifier is required.")
        record = next((item for item in self.catalog()["backups"] if item["identifier"] == identifier), None)
        if record is None or not record["selectable"]:
            if record is not None and record["compatibility"] == "Legacy/manual recovery":
                raise RestoreCompatibilityError(
                    "This backup predates Tori's current source-history boundary and cannot be automatically restored. It remains available for manual recovery."
                )
            raise RestoreCompatibilityError("That backup is not eligible for automatic restore.")
        proposal = RestoreProposal(
            token=secrets.token_urlsafe(32),
            backup_identifier=identifier,
            expires_at=self._monotonic() + RESTORE_CONFIRMATION_SECONDS,
        )
        self._proposal = proposal
        return {
            "ok": True,
            "confirmation": {
                "token": proposal.token,
                "backup_identifier": identifier,
                "message": self.confirmation_message,
                "expires_in_seconds": RESTORE_CONFIRMATION_SECONDS,
            },
        }

    def confirm(self, token: object, decision: object) -> tuple[int, dict[str, Any]]:
        proposal = self._proposal
        self._proposal = None
        if (
            proposal is None
            or not isinstance(token, str)
            or not secrets.compare_digest(token, proposal.token)
            or self._monotonic() > proposal.expires_at
        ):
            raise RestoreConfirmationError("That one-use restore confirmation is invalid or expired.")
        if decision == "cancel":
            return 200, {"ok": True, "cancelled": True}
        if decision != "restore":
            raise RestoreConfirmationError("The restore decision must be restore or cancel.")
        if not self.coordinator.acquire(blocking=False):
            raise RestoreBusyError("Tori is busy; restore did not begin.")
        self._pending = True
        try:
            safety = self.backups.create_backup()
            safety_verified = self.backups.verified_backup(safety.identifier)
            selected = self.backups.verified_backup(proposal.backup_identifier)
            target_commit = selected.source_commit
            if not self.resolver.source_is_trusted(target_commit):
                raise RestoreCompatibilityError(
                    "The selected backup source is not available in Tori's trusted sanitized history."
                )
            assert target_commit is not None
            prepared = self._prepare(
                selected_identifier=proposal.backup_identifier,
                selected_manifest_sha256=selected.manifest_sha256,
                selected_payload=selected.payload,
                safety_identifier=safety.identifier,
                safety_manifest_sha256=safety_verified.manifest_sha256,
                target_commit=target_commit,
            )
            # The handoff uses a second full verification, after candidate construction.
            current_selected = self.backups.verified_backup(proposal.backup_identifier)
            if current_selected.manifest_sha256 != selected.manifest_sha256:
                raise RestoreCompatibilityError("The selected backup changed before restore handoff.")
            self._launcher([sys.executable, str(prepared.helper_path), str(prepared.plan_path)], prepared.handoff_path)
            return 202, {
                "ok": True,
                "handoff": True,
                "message": "Restore is prepared. Tori is shutting down for verified activation.",
                "operation_id": prepared.operation_id,
                "safety_backup_identifier": prepared.safety_backup_identifier,
            }
        except (BackupError, ConfigError, SkillError, OSError, RestoreError) as exc:
            self._pending = False
            self.coordinator.release()
            if isinstance(exc, RestoreError):
                raise
            raise RestoreHandoffError("Restore preparation failed safely before activation.") from exc

    def _prepare(
        self,
        *,
        selected_identifier: str,
        selected_manifest_sha256: str,
        selected_payload: Path,
        safety_identifier: str,
        safety_manifest_sha256: str,
        target_commit: str,
    ) -> PreparedRestore:
        root_info = _ordinary_directory(self.project_root, "The live Tori project")
        if root_info.st_uid != os.geteuid():
            raise RestoreCompatibilityError("The live Tori project is not owned by this user.")
        config = self.project_root / "tori.toml"
        config_info = _regular_file(config, "The current machine configuration")
        if config_info.st_uid != os.geteuid():
            raise RestoreCompatibilityError("The current machine configuration is not owner-controlled.")
        config_digest = _sha256(config)
        operation_id = secrets.token_hex(16)
        parent = self.project_root.parent
        candidate = parent / f".{self.project_root.name}.restore-{operation_id}"
        rollback = parent / f".{self.project_root.name}.rollback-{operation_id}"
        evidence = parent / f".{self.project_root.name}.restore-evidence-{operation_id}"
        for path in (candidate, rollback, evidence):
            if os.path.lexists(path):
                raise RestoreCompatibilityError("A restore staging path collision was refused.")
        self.resolver.stage_source(target_commit, candidate)
        try:
            candidate_requirements = candidate / "requirements.txt"
            live_requirements = self.project_root / "requirements.txt"
            _regular_file(candidate_requirements, "The staged dependency lock")
            _regular_file(live_requirements, "The current dependency lock")
            if _sha256(candidate_requirements) != _sha256(live_requirements):
                raise RestoreCompatibilityError(
                    "This source version needs a different dependency environment; automatic Restore V1 stopped before activation."
                )
            if os.path.lexists(self.project_root / ".venv"):
                _ordinary_directory(self.project_root / ".venv", "The current Python environment")
            shutil.copyfile(config, candidate / "tori.toml", follow_symlinks=False)
            os.chmod(candidate / "tori.toml", stat.S_IMODE(config_info.st_mode), follow_symlinks=False)
            if _sha256(candidate / "tori.toml") != config_digest:
                raise RestoreCompatibilityError("The staged machine configuration did not verify.")
            load_settings(candidate / "tori.toml", environ={})
            _copy_runtime(selected_payload / "runtime", candidate / "runtime")
            _copy_voice_assets(selected_payload, candidate, selected_manifest_sha256)
            restore_skills_from_backup(
                self.backups, selected_identifier, destination=candidate / "runtime" / "skills"
            )
            _verify_runtime_sqlite(candidate / "runtime")
            if self.resolver._git_at(candidate, "status", "--porcelain").strip():
                # Only ignored local state is permitted; porcelain excludes it by default.
                raise RestoreCompatibilityError("The staged source tree did not remain clean.")
        except Exception:
            if candidate.exists():
                shutil.rmtree(candidate)
            raise
        handoff = Path(tempfile.mkdtemp(prefix="tori-restore-", dir="/tmp"))
        os.chmod(handoff, 0o700)
        helper = handoff / "tori-restore"
        plan = handoff / "restore-plan.json"
        log = handoff / "restore.log"
        result = handoff / "result.json"
        try:
            _regular_file(self.helper_source, "The restore helper")
            shutil.copyfile(self.helper_source, helper, follow_symlinks=False)
            os.chmod(helper, 0o700, follow_symlinks=False)
            document = {
                "schema_version": RESTORE_PLAN_SCHEMA,
                "operation_id": operation_id,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "selected_backup_identifier": selected_identifier,
                "selected_backup_directory": str(self.backups.backup_root / selected_identifier),
                "selected_manifest_sha256": selected_manifest_sha256,
                "safety_backup_identifier": safety_identifier,
                "safety_backup_directory": str(self.backups.backup_root / safety_identifier),
                "safety_manifest_sha256": safety_manifest_sha256,
                "expected_current_commit": self.resolver.current_commit(),
                "target_commit": target_commit,
                "trusted_origin": self.resolver.origin,
                "config_sha256": config_digest,
                "candidate_identity_sha256": _tree_identity(candidate),
                "live_project": str(self.project_root),
                "candidate_path": str(candidate),
                "rollback_path": str(rollback),
                "evidence_path": str(evidence),
                "originating_pid": self._process_id,
                "expected_uid": os.geteuid(),
                "expected_gid": os.getegid(),
                "reuse_venv": os.path.lexists(self.project_root / ".venv"),
                "restart_argv": [str(self.project_root / "start-tori.sh")],
                "health_url": f"http://127.0.0.1:{self.web_port}/api/session",
                "log_path": str(log),
                "result_path": str(result),
            }
            encoded = (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            descriptor = os.open(plan, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o400)
            try:
                os.write(descriptor, encoded)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except Exception:
            shutil.rmtree(handoff)
            shutil.rmtree(candidate)
            raise
        return PreparedRestore(operation_id, candidate, rollback, evidence, handoff, plan, helper, safety_identifier, target_commit)

    @staticmethod
    def _launch(arguments: list[str], handoff_path: Path) -> object:
        log_path = handoff_path / "launcher.log"
        log_handle = open(log_path, "ab", buffering=0)
        try:
            return subprocess.Popen(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            log_handle.close()
