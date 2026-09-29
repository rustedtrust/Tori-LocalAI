"""Verified, transactional disaster-recovery backups for Tori."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import threading
from typing import Any

from . import __version__
from .coding_work import SQLiteCodingWorkStore
from .coding_work_runtime import (
    CodingWorkRuntimeBusyError,
    CodingWorkRuntimeError,
    CodingWorkRuntimeUnsafeError,
    CodingWorkRuntimeLayout,
    CodingWorkRuntimeOwnership,
)
from .operator_observability import operator_failure


# Installation root is determined by the packaged source, not the developer's host.
PRODUCTION_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_BACKUP_ROOT = PRODUCTION_PROJECT_ROOT.parent / (PRODUCTION_PROJECT_ROOT.name + "_backups")
BACKUP_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
PAYLOAD_NAME = "project"
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_FINAL_NAME = re.compile(r"Tori_[0-9]{8}_[0-9]{6}_[0-9a-f]{16}\Z")
_BACKUP_EXCLUDED = frozenset(
    {
        "runtime/skills/quarantine",
        "runtime/skills/discovery",
        "runtime/skills/self_learning",
        "runtime/skills/secrets",
        "runtime/skills/tmp",
        # Per-attempt sockets/directories are supervised process state, not
        # durable Research evidence. The database/report/provenance remain in scope.
        "runtime/research/sessions",
    }
)
_REBUILDABLE_ENVIRONMENT_DIRECTORY = ".venv"


class BackupError(RuntimeError):
    """A safe application-owned backup failure."""

    code = "backup_failed"


class BackupBusyError(BackupError):
    code = "backup_in_progress"


class BackupSafetyError(BackupError):
    code = "backup_unsafe"


class BackupChangedError(BackupError):
    code = "source_changed"


class BackupVerificationError(BackupError):
    code = "verification_failed"


@dataclass(frozen=True, slots=True)
class BackupResult:
    identifier: str
    completed_at: str
    directory: str
    total_regular_bytes: int
    regular_file_count: int
    directory_count: int
    symlink_count: int
    verification: str = "verified"


@dataclass(frozen=True, slots=True)
class DiscoveredBackup:
    """Structurally checked publication metadata; payload not reverified."""

    result: BackupResult
    source_commit: str | None
    valid_source_commit: bool


@dataclass(frozen=True, slots=True)
class VerifiedBackup:
    """A fully reverified backup plus bounded restore identity."""

    result: BackupResult
    payload: Path
    manifest_sha256: str
    source_commit: str | None


@dataclass(frozen=True, slots=True)
class _SourceEntry:
    path: str
    kind: str
    mode: int
    size: int | None = None
    mtime_ns: int | None = None
    inode: int | None = None
    device: int | None = None
    link_target: str | None = None
    sqlite: bool = False


# Only exact, application-owned messages can be named in the operator console.
# Arbitrary exception text may be a path, command, URL, credential, or user data.
_SAFE_MAINTENANCE_MESSAGES = {
    "Coding Work maintenance is unavailable.": "coding_work_maintenance_unavailable",
    "Remote Chat is busy; backup was not published.": "remote_chat_busy",
    "Conversation is busy; backup was not published.": "conversation_busy",
    "Remote Chat has unfinished work; backup was not published.": "remote_chat_unfinished_work",
    "Remote Chat became enabled before backup quiescence.": "remote_chat_enabled",
    "Incomplete Agent Skill publication prevents a verified backup.": "skills_publication_incomplete",
    "An uninstalled Agent Skill still has managed package content.": "skills_uninstalled_package_present",
    "An installed Agent Skill is missing immutable package evidence.": "skills_package_missing",
}


def _safe_maintenance_message(error: BaseException) -> str:
    try:
        return _SAFE_MAINTENANCE_MESSAGES.get(str(error), "redacted")
    except Exception:
        return "redacted"


class _ObservedGuard:
    """Delegate a guard unchanged while attributing its entry and exit errors."""

    def __init__(
        self, name: str, factory: Callable[[], AbstractContextManager[None]],
        failures: list[tuple[str, BaseException]],
    ) -> None:
        self.name = name
        self.factory = factory
        self.failures = failures
        self.manager: AbstractContextManager[None] | None = None

    def __enter__(self) -> None:
        try:
            self.manager = self.factory()
            return self.manager.__enter__()
        except BaseException as exc:
            self.failures.append((f"backup_maintenance.guard_enter.{self.name}", exc))
            raise

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        assert self.manager is not None
        try:
            return self.manager.__exit__(exc_type, exc, tb)
        except BaseException as error:
            self.failures.append((f"backup_maintenance.guard_exit.{self.name}", error))
            raise


def _report_maintenance_failure(
    failures: list[tuple[str, BaseException]], default_stage: str, error: BaseException,
) -> None:
    stage, first_error = failures[0] if failures else (default_stage, error)
    fields = {"stage": stage, "message": _safe_maintenance_message(first_error)}
    if ".guard_" in stage:
        fields["guard"] = stage.rsplit(".", 1)[-1]
    if len(failures) > 1:
        last_stage, last_error = failures[-1]
        if last_stage != stage:
            fields["final_stage"] = last_stage
            fields["final_error_type"] = type(last_error).__name__
            fields["final_message"] = _safe_maintenance_message(last_error)
    operator_failure("backup.maintenance.failed", first_error, code="maintenance_failure", **fields)


class BackupService:
    """Create and discover complete verified Tori backups."""

    def __init__(
        self,
        *,
        project_root: Path = PRODUCTION_PROJECT_ROOT,
        backup_root: Path = PRODUCTION_BACKUP_ROOT,
        sqlite_paths: tuple[Path, ...] | None = None,
        clock: Callable[[], datetime] | None = None,
        token_hex: Callable[[int], str] | None = None,
        coding_work_guard: Callable[[], AbstractContextManager[None]] | None = None,
        research_guard: Callable[[], AbstractContextManager[None]] | None = None,
        remote_chat_guard: Callable[[], AbstractContextManager[None]] | None = None,
        skills_guard: Callable[[], AbstractContextManager[None]] | None = None,
        capability_growth_guard: Callable[[], AbstractContextManager[None]] | None = None,
        companion_initiative_guard: Callable[[], AbstractContextManager[None]] | None = None,
        night_owl_guard: Callable[[], AbstractContextManager[None]] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.backup_root = Path(backup_root)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_hex = token_hex or secrets.token_hex
        self._lock = threading.Lock()
        self._coding_work_guard = coding_work_guard
        self._research_guard = research_guard
        self._remote_chat_guard = remote_chat_guard
        self._skills_guard = skills_guard
        self._capability_growth_guard = capability_growth_guard
        self._companion_initiative_guard = companion_initiative_guard
        self._night_owl_guard = night_owl_guard
        default_sqlite = (
            Path("runtime/memory/tori_memory.db"),
            Path("runtime/conversations/tori_conversations.db"),
            Path("runtime/settings/tori_settings.db"),
            Path("runtime/model_providers/tori_model_providers.db"),
            Path("runtime/tasks/tori_tasks.db"),
            Path("runtime/scheduled_work/tori_scheduled_work.db"),
            Path("runtime/tts_profiles/tori_tts_profiles.db"),
            Path("runtime/coding_work/tori_coding_work.db"),
            Path("runtime/research/tori_research.db"),
            Path("runtime/remote_chat/tori_remote_chat.db"),
            Path("runtime/skills/registry.sqlite3"),
            Path("runtime/capability_growth/improvement_journal.sqlite3"),
            Path("runtime/companion_initiative/tori_companion_initiative.db"),
            Path("runtime/night_owl/tori_night_owl.db"),
            Path("runtime/supervised_terminal/tori_execution_policy.db"),
            Path("runtime/supervised_terminal/tori_terminal_receipts.db"),
        )
        selected_sqlite = default_sqlite if sqlite_paths is None else sqlite_paths
        self._sqlite_paths = frozenset(
            self._relative_path(item) for item in selected_sqlite
        )
        self._validate_configuration()

    def create_backup(self) -> BackupResult:
        if not self._lock.acquire(blocking=False):
            raise BackupBusyError("A backup is already in progress.")
        failures: list[tuple[str, BaseException]] = []
        stage = "backup_maintenance.entry"
        try:
            coding_root = self.project_root / "runtime/coding_work"
            if os.path.lexists(coding_root) and self._coding_work_guard is None:
                raise BackupBusyError(
                    "Coding Work state requires its coordinated backup guard."
                )
            research_root = self.project_root / "runtime/research"
            if os.path.lexists(research_root) and self._research_guard is None:
                raise BackupBusyError(
                    "Research state requires its coordinated backup guard."
                )
            remote_root = self.project_root / "runtime/remote_chat"
            if os.path.lexists(remote_root) and self._remote_chat_guard is None:
                raise BackupBusyError(
                    "Remote Chat state requires its coordinated backup guard."
                )
            skills_root = self.project_root / "runtime/skills"
            if os.path.lexists(skills_root) and self._skills_guard is None:
                raise BackupBusyError(
                    "Skills state requires its coordinated backup guard."
                )
            capability_growth_root = self.project_root / "runtime/capability_growth"
            if (
                os.path.lexists(capability_growth_root)
                and self._capability_growth_guard is None
            ):
                raise BackupBusyError(
                    "Capability Growth state requires its coordinated backup guard."
                )
            companion_initiative_root = self.project_root / "runtime/companion_initiative"
            if (
                os.path.lexists(companion_initiative_root)
                and self._companion_initiative_guard is None
            ):
                raise BackupBusyError(
                    "Companion Initiative state requires its coordinated backup guard."
                )
            night_owl_root = self.project_root / "runtime/night_owl"
            if os.path.lexists(night_owl_root) and self._night_owl_guard is None:
                raise BackupBusyError(
                    "Night Owl state requires its coordinated backup guard."
                )
            with ExitStack() as stack:
                if self._coding_work_guard is not None:
                    stack.enter_context(_ObservedGuard("coding_work", self._coding_work_guard, failures))
                if self._research_guard is not None:
                    stack.enter_context(_ObservedGuard("research", self._research_guard, failures))
                if self._remote_chat_guard is not None:
                    stack.enter_context(_ObservedGuard("remote_chat", self._remote_chat_guard, failures))
                if self._skills_guard is not None:
                    stack.enter_context(_ObservedGuard("skills", self._skills_guard, failures))
                if self._capability_growth_guard is not None:
                    stack.enter_context(_ObservedGuard("capability_growth", self._capability_growth_guard, failures))
                if self._companion_initiative_guard is not None:
                    stack.enter_context(_ObservedGuard("companion_initiative", self._companion_initiative_guard, failures))
                if self._night_owl_guard is not None:
                    stack.enter_context(_ObservedGuard("night_owl", self._night_owl_guard, failures))
                stage = "backup_maintenance.body"
                try:
                    result = self._create_backup_locked()
                except BaseException as exc:
                    failures.append((stage, exc))
                    raise
                stage = "backup_maintenance.completion"
                return result
        except CodingWorkRuntimeUnsafeError as exc:
            _report_maintenance_failure(failures, stage, exc)
            raise BackupSafetyError(
                "Coding Work private state is unsafe; no verified backup was published. "
                "Its runtime requires a separately authorized repair."
            ) from exc
        except CodingWorkRuntimeError as exc:
            _report_maintenance_failure(failures, stage, exc)
            raise BackupBusyError(
                "Coding Work could not enter coordinated maintenance; no verified backup was published."
            ) from exc
        except BackupError as exc:
            _report_maintenance_failure(failures, stage, exc)
            raise
        except RuntimeError as exc:
            _report_maintenance_failure(failures, stage, exc)
            raise BackupBusyError(
                "Tori could not enter coordinated maintenance; no verified backup was published."
            ) from exc
        except Exception as exc:
            _report_maintenance_failure(failures, stage, exc)
            raise
        finally:
            self._lock.release()

    @property
    def in_progress(self) -> bool:
        return self._lock.locked()

    def configure_skills_guard(
        self, guard: Callable[[], AbstractContextManager[None]]
    ) -> None:
        """Attach the one application-owned Skills consistency guard."""

        if not callable(guard) or self._skills_guard is not None or self.in_progress:
            raise BackupSafetyError("The Skills backup guard could not be configured safely.")
        self._skills_guard = guard

    def configure_remote_chat_guard(
        self, guard: Callable[[], AbstractContextManager[None]]
    ) -> None:
        """Attach the application-owned Remote Chat quiescence guard."""

        if (
            not callable(guard)
            or self._remote_chat_guard is not None
            or self.in_progress
        ):
            raise BackupSafetyError(
                "The Remote Chat backup guard could not be configured safely."
            )
        self._remote_chat_guard = guard

    def configure_capability_growth_guard(
        self, guard: Callable[[], AbstractContextManager[None]]
    ) -> None:
        """Attach the application-owned Improvement Journal consistency guard."""

        if (
            not callable(guard)
            or self._capability_growth_guard is not None
            or self.in_progress
        ):
            raise BackupSafetyError(
                "The Capability Growth backup guard could not be configured safely."
            )
        self._capability_growth_guard = guard

    def configure_companion_initiative_guard(
        self, guard: Callable[[], AbstractContextManager[None]]
    ) -> None:
        """Attach the application-owned Companion Initiative consistency guard."""

        if (
            not callable(guard)
            or self._companion_initiative_guard is not None
            or self.in_progress
        ):
            raise BackupSafetyError(
                "The Companion Initiative backup guard could not be configured safely."
            )
        self._companion_initiative_guard = guard

    def configure_night_owl_guard(
        self, guard: Callable[[], AbstractContextManager[None]]
    ) -> None:
        """Attach Night Owl's authoritative-state consistency guard."""
        if not callable(guard) or self._night_owl_guard is not None or self.in_progress:
            raise BackupSafetyError("The Night Owl backup guard could not be configured safely.")
        self._night_owl_guard = guard

    def verified_payload(self, identifier: str) -> Path:
        """Return a fully reverified immutable payload for bounded restore work."""

        if not isinstance(identifier, str) or _FINAL_NAME.fullmatch(identifier) is None:
            raise BackupVerificationError("That backup identifier is invalid.")
        if self._inspect_existing_root(create=False) is None:
            raise BackupVerificationError("That verified backup is unavailable.")
        directory = self.backup_root / identifier
        if directory.parent != self.backup_root:
            raise BackupVerificationError("That backup identifier is invalid.")
        discovered = self._read_discovered_manifest(directory)
        if discovered is None:
            raise BackupVerificationError("That backup manifest did not verify.")
        try:
            with open(directory / MANIFEST_NAME, "rb") as handle:
                document = json.loads(handle.read().decode("utf-8"))
            counts = self._verify_payload(document["entries"], directory / PAYLOAD_NAME)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BackupVerificationError("That backup payload did not verify.") from exc
        if counts != document.get("counts"):
            raise BackupVerificationError("That backup payload did not verify.")
        return directory / PAYLOAD_NAME

    def verified_backup(self, identifier: str) -> VerifiedBackup:
        """Fully reverify one backup and return only restore-safe identity."""

        payload = self.verified_payload(identifier)
        directory = payload.parent
        manifest_path = directory / MANIFEST_NAME
        try:
            encoded = manifest_path.read_bytes()
            document = json.loads(encoded.decode("utf-8"))
            git_document = document.get("git")
            source_commit = (
                git_document.get("head") if isinstance(git_document, dict) else None
            )
            if source_commit is not None and (
                not isinstance(source_commit, str)
                or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
            ):
                raise ValueError("invalid source commit")
            result = self._read_discovered_manifest(directory)
            if result is None:
                raise ValueError("invalid manifest")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise BackupVerificationError("That backup manifest did not verify.") from exc
        return VerifiedBackup(
            result=result,
            payload=payload,
            manifest_sha256=hashlib.sha256(encoded).hexdigest(),
            source_commit=source_commit,
        )

    def discovered_verified(self) -> tuple[BackupResult, ...]:
        """Return structurally discovered verified publications, oldest first."""

        return tuple(item.result for item in self.discovered_publications())

    def discovered_publications(self) -> tuple[DiscoveredBackup, ...]:
        """Inspect bounded manifest metadata without reverifying payload files."""

        if self._inspect_existing_root(create=False) is None:
            return ()
        candidates: list[DiscoveredBackup] = []
        try:
            children = sorted(os.scandir(self.backup_root), key=lambda item: item.name)
        except OSError as exc:
            raise BackupSafetyError(
                "The backup destination could not be inspected safely."
            ) from exc
        for child in children:
            if (
                _FINAL_NAME.fullmatch(child.name) is None
                or not child.is_dir(follow_symlinks=False)
            ):
                continue
            candidate = self._read_discovered_publication(Path(child.path))
            if candidate is not None:
                candidates.append(candidate)
        return tuple(sorted(candidates, key=lambda item: (item.result.completed_at, item.result.identifier)))

    def latest_verified(self) -> BackupResult | None:
        candidates = self.discovered_verified()
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.completed_at, item.identifier))

    def _create_backup_locked(self) -> BackupResult:
        self._inspect_existing_root(create=True)
        identifier, final_path, staging_path = self._allocate_paths()
        try:
            os.mkdir(staging_path, 0o700)
            os.mkdir(staging_path / PAYLOAD_NAME, 0o700)
        except OSError as exc:
            raise BackupSafetyError("Tori could not create a safe backup staging area.") from exc

        started = self._timestamp()
        try:
            before = self._inventory_source()
            manifest_entries = self._capture(before, staging_path / PAYLOAD_NAME)
            after = self._inventory_source()
            self._verify_source_stability(before, after)
            counts = self._verify_payload(manifest_entries, staging_path / PAYLOAD_NAME)
            completed = self._timestamp()
            manifest = {
                "schema_version": BACKUP_SCHEMA_VERSION,
                "backup_identifier": identifier,
                "source_project": str(self.project_root),
                "final_directory": str(final_path),
                "created_at": started,
                "completed_at": completed,
                "tori_version": __version__,
                "git": self._read_git_metadata(),
                "payload": PAYLOAD_NAME,
                "entries": manifest_entries,
                "counts": counts,
                "verification": {"result": "verified"},
            }
            self._write_manifest(staging_path, manifest)
            self._verify_manifest(staging_path, manifest)
            if os.path.lexists(final_path):
                raise BackupSafetyError("The final backup destination already exists.")
            try:
                _rename_no_replace(staging_path, final_path)
            except OSError as exc:
                raise BackupSafetyError("Tori could not publish the verified backup safely.") from exc
            return BackupResult(
                identifier=identifier,
                completed_at=completed,
                directory=str(final_path),
                total_regular_bytes=counts["total_regular_bytes"],
                regular_file_count=counts["regular_files"],
                directory_count=counts["directories"],
                symlink_count=counts["symlinks"],
            )
        except BackupError:
            raise
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            raise BackupError("Tori could not complete and verify the backup.") from exc

    def _validate_configuration(self) -> None:
        if not self.project_root.is_absolute() or not self.backup_root.is_absolute():
            raise ValueError("backup paths must be absolute")
        if self.project_root == PRODUCTION_PROJECT_ROOT and self.backup_root != PRODUCTION_BACKUP_ROOT:
            raise ValueError("the production backup root is fixed")
        try:
            if os.path.commonpath((self.project_root, self.backup_root)) == str(self.project_root):
                raise ValueError("the backup root must be outside the project")
        except ValueError as exc:
            raise ValueError("unsafe backup root") from exc

    def _inspect_existing_root(self, *, create: bool) -> os.stat_result | None:
        try:
            info = os.lstat(self.backup_root)
        except FileNotFoundError:
            if not create:
                return None
            parent = self.backup_root.parent
            try:
                parent_info = os.lstat(parent)
            except OSError as exc:
                raise BackupSafetyError("The backup destination is unavailable.") from exc
            if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
                raise BackupSafetyError("The backup destination is unsafe.")
            try:
                os.mkdir(self.backup_root, 0o700)
                info = os.lstat(self.backup_root)
            except OSError as exc:
                raise BackupSafetyError("The backup destination could not be created safely.") from exc
        except OSError as exc:
            raise BackupSafetyError("The backup destination is unavailable.") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BackupSafetyError("The backup destination is not a safe ordinary directory.")
        return info

    def _allocate_paths(self) -> tuple[str, Path, Path]:
        stamp = self._clock().astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
        for _ in range(16):
            unique = self._token_hex(8)
            if not isinstance(unique, str) or len(unique) != 16 or any(
                character not in "0123456789abcdef" for character in unique
            ):
                raise BackupSafetyError("Tori could not generate a safe backup identifier.")
            identifier = f"Tori_{stamp}_{unique}"
            final_path = self.backup_root / identifier
            staging_path = self.backup_root / f".{identifier}.incomplete"
            if not os.path.lexists(final_path) and not os.path.lexists(staging_path):
                return identifier, final_path, staging_path
        raise BackupSafetyError("Tori could not allocate a unique backup directory.")

    def _inventory_source(self) -> dict[str, _SourceEntry]:
        inventory: dict[str, _SourceEntry] = {}

        def visit(directory_fd: int, prefix: str = "") -> None:
            try:
                children = sorted(os.scandir(directory_fd), key=lambda item: item.name)
            except OSError as exc:
                raise BackupError("Tori could not read the complete project tree.") from exc
            for child in children:
                relative = f"{prefix}/{child.name}" if prefix else child.name
                self._validate_relative_text(relative)
                if any(
                    relative == excluded or relative.startswith(excluded + "/")
                    for excluded in _BACKUP_EXCLUDED
                ):
                    continue
                sqlite_sidecar = self._sqlite_sidecar_owner(relative)
                try:
                    info = child.stat(follow_symlinks=False)
                except FileNotFoundError as exc:
                    if sqlite_sidecar is not None:
                        continue
                    raise BackupChangedError(
                        "The project inventory changed while the backup was running; retry it."
                    ) from exc
                if sqlite_sidecar is not None:
                    if not relative.endswith("-journal"):
                        raise BackupSafetyError(
                            "An unexpected SQLite WAL sidecar prevents a verified backup."
                        )
                    if not stat.S_ISREG(info.st_mode):
                        raise BackupSafetyError(
                            "A SQLite sidecar has an unsafe filesystem type."
                        )
                    # The online snapshot incorporates committed database state
                    # and intentionally replaces transient journal/WAL mechanics.
                    continue
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    # Virtual environments are reproducible from the pinned
                    # deployment requirements.  Skip them wherever they occur
                    # in the project tree, while keeping adjacent deployment
                    # files and model assets in the verified payload.
                    if child.name == _REBUILDABLE_ENVIRONMENT_DIRECTORY:
                        continue
                    inventory[relative] = _SourceEntry(relative, "directory", mode)
                    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
                    child_fd = os.open(child.name, flags, dir_fd=directory_fd)
                    try:
                        visit(child_fd, relative)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(info.st_mode):
                    inventory[relative] = _SourceEntry(
                        relative, "file", mode, info.st_size, info.st_mtime_ns,
                        info.st_ino, info.st_dev, sqlite=relative in self._sqlite_paths,
                    )
                elif stat.S_ISLNK(info.st_mode):
                    if relative in self._sqlite_paths:
                        raise BackupSafetyError(
                            "A known Tori database is not an ordinary file."
                        )
                    inventory[relative] = _SourceEntry(
                        relative,
                        "symlink",
                        mode,
                        link_target=os.readlink(child.name, dir_fd=directory_fd),
                    )
                else:
                    raise BackupSafetyError(
                        "An unsupported filesystem object prevents a verified backup."
                    )

        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        try:
            root_fd = os.open(self.project_root, flags)
        except OSError as exc:
            raise BackupSafetyError("The Tori project root is unavailable or unsafe.") from exc
        try:
            visit(root_fd)
        finally:
            os.close(root_fd)
        return inventory

    def _capture(
        self, inventory: dict[str, _SourceEntry], payload: Path
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for relative, entry in inventory.items():
            source = self.project_root / relative
            destination = payload / relative
            record: dict[str, Any] = {
                "path": relative,
                "type": entry.kind,
                "mode": entry.mode,
            }
            if entry.kind == "directory":
                os.mkdir(destination, entry.mode)
                os.chmod(destination, entry.mode, follow_symlinks=False)
            elif entry.kind == "symlink":
                parent_fd, name = self._open_source_parent(relative)
                try:
                    target = os.readlink(name, dir_fd=parent_fd)
                    if target != entry.link_target:
                        raise BackupChangedError("The project changed while the backup was running; retry it.")
                    os.symlink(target, destination)
                    if os.readlink(name, dir_fd=parent_fd) != target:
                        raise BackupChangedError("The project changed while the backup was running; retry it.")
                finally:
                    os.close(parent_fd)
                record["target"] = target
            elif entry.sqlite:
                digest, size, integrity = self._snapshot_sqlite(source, destination, entry.mode)
                record.update({"size": size, "sha256": digest, "sqlite_integrity": integrity})
            else:
                digest, size = self._copy_regular(source, destination, entry)
                record.update({"size": size, "sha256": digest})
            records.append(record)
        return records

    def _copy_regular(
        self, source: Path, destination: Path, expected: _SourceEntry
    ) -> tuple[str, int]:
        parent_fd, name = self._open_source_parent(expected.path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        digest = hashlib.sha256()
        size = 0
        try:
            opened = os.fstat(descriptor)
            self._require_same_regular(opened, expected)
            with os.fdopen(descriptor, "rb", closefd=False) as source_file, open(destination, "xb") as target:
                while True:
                    block = source_file.read(1024 * 1024)
                    if not block:
                        break
                    target.write(block)
                    digest.update(block)
                    size += len(block)
                target.flush()
            closed = os.fstat(descriptor)
            self._require_same_regular(closed, expected)
        finally:
            os.close(descriptor)
        if size != expected.size:
            raise BackupChangedError("The project changed while the backup was running; retry it.")
        os.chmod(destination, expected.mode, follow_symlinks=False)
        return digest.hexdigest(), size

    @staticmethod
    def _require_same_regular(info: os.stat_result, expected: _SourceEntry) -> None:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != expected.size
            or info.st_mtime_ns != expected.mtime_ns
            or info.st_ino != expected.inode
            or info.st_dev != expected.device
            or stat.S_IMODE(info.st_mode) != expected.mode
        ):
            raise BackupChangedError("The project changed while the backup was running; retry it.")

    def _snapshot_sqlite(
        self, source: Path, destination: Path, mode: int
    ) -> tuple[str, int, str]:
        relative = source.relative_to(self.project_root).as_posix()
        parent_fd, name = self._open_source_parent(relative)
        for suffix in ("-wal", "-shm"):
            try:
                os.stat(name + suffix, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError:
                os.close(parent_fd)
                raise
            os.close(parent_fd)
            raise BackupSafetyError(
                "An unexpected SQLite WAL sidecar prevents a verified backup."
            )
        source_uri = f"file:/proc/self/fd/{parent_fd}/{name}?mode=ro"
        try:
            source_connection = sqlite3.connect(source_uri, uri=True, timeout=5.0)
        except Exception:
            os.close(parent_fd)
            raise
        try:
            destination_connection = sqlite3.connect(destination)
            try:
                source_connection.backup(destination_connection)
                destination_connection.commit()
            finally:
                destination_connection.close()
        finally:
            source_connection.close()
            os.close(parent_fd)
        os.chmod(destination, mode, follow_symlinks=False)
        check = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True)
        try:
            rows = check.execute("PRAGMA integrity_check").fetchall()
        finally:
            check.close()
        integrity = "ok" if rows == [("ok",)] else "failed"
        if integrity != "ok":
            raise BackupVerificationError("A database snapshot failed integrity verification.")
        digest, size = _hash_file(destination)
        return digest, size, integrity

    def _verify_source_stability(
        self, before: dict[str, _SourceEntry], after: dict[str, _SourceEntry]
    ) -> None:
        if before.keys() != after.keys():
            raise BackupChangedError("The project inventory changed while the backup was running; retry it.")
        for path, original in before.items():
            current = after[path]
            if original.kind != current.kind or original.mode != current.mode:
                raise BackupChangedError("The project changed while the backup was running; retry it.")
            if original.sqlite:
                continue
            if original != current:
                raise BackupChangedError("The project changed while the backup was running; retry it.")

    def _verify_payload(
        self, records: list[dict[str, Any]], payload: Path
    ) -> dict[str, int]:
        actual = self._inventory_destination(payload)
        expected_paths = {record["path"] for record in records}
        if set(actual) != expected_paths:
            raise BackupVerificationError("The staged backup inventory did not verify.")
        counts = {"regular_files": 0, "directories": 0, "symlinks": 0, "total_regular_bytes": 0}
        for record in records:
            relative = record["path"]
            info = actual[relative]
            if info.kind != record["type"] or info.mode != record["mode"]:
                raise BackupVerificationError("The staged backup metadata did not verify.")
            destination = payload / relative
            if info.kind == "file":
                digest, size = _hash_file(destination)
                if digest != record["sha256"] or size != record["size"]:
                    raise BackupVerificationError("A staged backup file did not verify.")
                if record.get("sqlite_integrity") == "ok":
                    connection = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro", uri=True)
                    try:
                        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                            raise BackupVerificationError("A database snapshot failed verification.")
                    finally:
                        connection.close()
                counts["regular_files"] += 1
                counts["total_regular_bytes"] += size
            elif info.kind == "directory":
                counts["directories"] += 1
            else:
                if os.readlink(destination) != record["target"]:
                    raise BackupVerificationError("A staged backup symlink did not verify.")
                counts["symlinks"] += 1
        return counts

    def _inventory_destination(self, root: Path) -> dict[str, _SourceEntry]:
        inventory: dict[str, _SourceEntry] = {}

        def visit(directory: Path, prefix: str = "") -> None:
            for child in sorted(os.scandir(directory), key=lambda item: item.name):
                relative = f"{prefix}/{child.name}" if prefix else child.name
                self._validate_relative_text(relative)
                info = child.stat(follow_symlinks=False)
                mode = stat.S_IMODE(info.st_mode)
                if stat.S_ISDIR(info.st_mode):
                    inventory[relative] = _SourceEntry(relative, "directory", mode)
                    visit(Path(child.path), relative)
                elif stat.S_ISREG(info.st_mode):
                    inventory[relative] = _SourceEntry(relative, "file", mode)
                elif stat.S_ISLNK(info.st_mode):
                    inventory[relative] = _SourceEntry(relative, "symlink", mode, link_target=os.readlink(child.path))
                else:
                    raise BackupVerificationError("The staged backup contains an unsupported object.")

        visit(root)
        return inventory

    def _write_manifest(self, staging: Path, manifest: dict[str, Any]) -> None:
        encoded = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise BackupVerificationError("The verified backup manifest is too large.")
        path = staging / MANIFEST_NAME
        with open(path, "xb") as handle:
            handle.write(encoded)
            handle.flush()
        os.chmod(path, 0o600, follow_symlinks=False)

    def _verify_manifest(self, staging: Path, expected: dict[str, Any]) -> None:
        path = staging / MANIFEST_NAME
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
            raise BackupVerificationError("The backup manifest did not verify.")
        with open(path, "rb") as handle:
            actual = json.loads(handle.read().decode("utf-8"))
        if actual != expected or actual.get("verification") != {"result": "verified"}:
            raise BackupVerificationError("The backup manifest did not verify.")
        if set(os.listdir(staging)) != {PAYLOAD_NAME, MANIFEST_NAME}:
            raise BackupVerificationError("The staged backup structure did not verify.")

    def _read_discovered_manifest(self, directory: Path) -> BackupResult | None:
        publication = self._read_discovered_publication(directory)
        return None if publication is None else publication.result

    def _read_discovered_publication(self, directory: Path) -> DiscoveredBackup | None:
        try:
            path = directory / MANIFEST_NAME
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size > MAX_MANIFEST_BYTES:
                return None
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_dev != info.st_dev or opened.st_ino != info.st_ino or opened.st_size != info.st_size:
                    return None
                document = json.loads(handle.read().decode("utf-8"))
            identifier = directory.name
            counts = document["counts"]
            payload_info = os.lstat(directory / PAYLOAD_NAME)
            if (
                document.get("schema_version") != BACKUP_SCHEMA_VERSION
                or document.get("backup_identifier") != identifier
                or document.get("final_directory") != str(directory)
                or document.get("source_project") != str(self.project_root)
                or document.get("payload") != PAYLOAD_NAME
                or document.get("verification") != {"result": "verified"}
                or not stat.S_ISDIR(payload_info.st_mode)
                or stat.S_ISLNK(payload_info.st_mode)
            ):
                return None
            completed = document["completed_at"]
            if not isinstance(completed, str):
                return None
            datetime.fromisoformat(completed.replace("Z", "+00:00"))
            values = tuple(counts[key] for key in ("total_regular_bytes", "regular_files", "directories", "symlinks"))
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
                return None
            entries = document.get("entries")
            if not isinstance(entries, list):
                return None
            discovered_counts = {"file": 0, "directory": 0, "symlink": 0}
            discovered_bytes = 0
            discovered_paths: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    return None
                relative = entry.get("path")
                kind = entry.get("type")
                mode = entry.get("mode")
                if not isinstance(relative, str) or relative in discovered_paths:
                    return None
                self._validate_relative_text(relative)
                if kind not in discovered_counts:
                    return None
                if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
                    return None
                if kind == "file":
                    size = entry.get("size")
                    digest = entry.get("sha256")
                    if (
                        isinstance(size, bool)
                        or not isinstance(size, int)
                        or size < 0
                        or not isinstance(digest, str)
                        or len(digest) != 64
                        or any(character not in "0123456789abcdef" for character in digest)
                    ):
                        return None
                    discovered_bytes += size
                elif kind == "symlink" and not isinstance(entry.get("target"), str):
                    return None
                discovered_paths.add(relative)
                discovered_counts[kind] += 1
            if (
                discovered_counts["file"] != counts["regular_files"]
                or discovered_counts["directory"] != counts["directories"]
                or discovered_counts["symlink"] != counts["symlinks"]
                or discovered_bytes != counts["total_regular_bytes"]
            ):
                return None
            git_document = document.get("git")
            source_commit = git_document.get("head") if isinstance(git_document, dict) else None
            valid_source_commit = source_commit is None or (
                isinstance(source_commit, str)
                and re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None
            )
            return DiscoveredBackup(
                BackupResult(identifier, completed, str(directory), *values),
                source_commit if valid_source_commit else None,
                valid_source_commit,
            )
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            BackupSafetyError,
        ):
            return None

    def _read_git_metadata(self) -> dict[str, str | None]:
        try:
            head = self._read_small_source_text(".git/HEAD").strip()
            if head.startswith("ref: "):
                reference = head[5:]
                if (
                    not reference.startswith("refs/")
                    or ".." in reference
                    or not all(
                        character.isalnum() or character in "/._-"
                        for character in reference
                    )
                ):
                    return {"head": None, "tree": None}
                head = self._read_small_source_text(f".git/{reference}").strip()
            if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
                head = None
        except (OSError, UnicodeError):
            head = None
        return {"head": head, "tree": None}

    def _read_small_source_text(self, relative: str) -> str:
        parent_fd, name = self._open_source_parent(relative)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
        try:
            data = os.read(descriptor, 257)
        finally:
            os.close(descriptor)
        if len(data) > 256:
            raise ValueError("Git metadata is too large")
        return data.decode("ascii")

    def _open_source_parent(self, relative: str) -> tuple[int, str]:
        self._validate_relative_text(relative)
        parts = Path(relative).parts
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.project_root, flags)
        try:
            for part in parts[:-1]:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor, parts[-1]
        except Exception:
            os.close(descriptor)
            raise

    def _sqlite_sidecar_owner(self, relative: str) -> str | None:
        for database in self._sqlite_paths:
            if any(relative == database + suffix for suffix in ("-journal", "-wal", "-shm")):
                return database
        return None

    def _timestamp(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _relative_path(path: Path) -> str:
        text = path.as_posix()
        BackupService._validate_relative_text(text)
        return text

    @staticmethod
    def _validate_relative_text(text: str) -> None:
        path = Path(text)
        if not text or text.startswith("/") or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise BackupSafetyError("An unsafe project-relative path was encountered.")


class CodingWorkBackupCoordinator:
    """Quiesce one owned Coding Work runtime for a coherent backup generation."""

    # A durable ``reconciling`` row can survive a process restart even when no
    # worker exists.  Ownership, the live-writer probe, and the provider-socket
    # check below distinguish that dormant historical state from active work.
    _ACTIVE_STATES = frozenset({"starting", "running", "cancelling"})

    def __init__(
        self,
        *,
        layout: CodingWorkRuntimeLayout,
        ownership: CodingWorkRuntimeOwnership,
        store: SQLiteCodingWorkStore,
        live_opencode_writer: Callable[[], bool],
    ) -> None:
        self.layout = layout
        self.ownership = ownership
        self.store = store
        self._live_opencode_writer = live_opencode_writer

    @contextmanager
    def snapshot_guard(self) -> Iterator[None]:
        try:
            with self.ownership.exclusive_maintenance():
                if self.store.list_work(tuple(self._ACTIVE_STATES)):
                    raise BackupBusyError(
                        "Coding Work is active; backup did not cancel or interrupt it."
                    )
                waiting = self.store.list_work(("waiting",))
                if self._live_opencode_writer():
                    reason = (
                        "A waiting OpenCode session is still live and was not copied."
                        if waiting
                        else "An OpenCode writer is still live and was not copied."
                    )
                    raise BackupBusyError(reason)
                if os.path.lexists(self.layout.provider_socket):
                    raise BackupBusyError(
                        "A provider socket is still present; Coding Work is not quiescent."
                    )
                # An already-held ownership lock does not prove worker output
                # still satisfies the private-state contract after execution.
                from .coding_work_runtime import validate_coding_work_layout

                validate_coding_work_layout(
                    self.layout, require_quiescent=True, require_empty=False
                )
                yield
        except CodingWorkRuntimeBusyError as exc:
            raise BackupBusyError("Coding Work maintenance is unavailable.") from exc


def result_document(result: BackupResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "identifier": result.identifier,
        "completed_at": result.completed_at,
        "directory": result.directory,
        "total_regular_bytes": result.total_regular_bytes,
        "regular_file_count": result.regular_file_count,
        "directory_count": result.directory_count,
        "symlink_count": result.symlink_count,
        "verification": result.verification,
    }


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                size += len(block)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), size


def _rename_no_replace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing any existing object."""

    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = library.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)
