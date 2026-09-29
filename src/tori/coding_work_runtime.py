"""Production runtime layout, ownership, and readiness for Coding Work.

This module does not wire Coding Work into application startup.  It provides
the fail-closed boundary that a later startup composition must use before it
opens or mutates canonical Coding Work state.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import threading
from typing import Final
from urllib.parse import urlparse

from .coding_work import SQLiteCodingWorkStore


CODING_WORK_DATABASE_NAME: Final = "tori_coding_work.db"
CODING_WORK_LOCK_NAME: Final = "supervisor.lock"
OPENCODE_DIRECTORY_NAME: Final = "opencode"
OPENCODE_INSTANCE_NAME: Final = "instance.json"
OPENCODE_TARGET_VERSION: Final = "1.18.31"
OPENCODE_PROVIDER_PACKAGE: Final = "@ai-sdk/openai-compatible"
OFFLINE_BOOTSTRAP_MANIFEST: Final = "offline-bootstrap.json"
OFFLINE_BOOTSTRAP_PROVENANCE: Final = "explicit_tori_opencode_offline_bootstrap"
INITIALIZER_PREFIX: Final = ".coding_work.initialize-"
MAX_OFFLINE_BOOTSTRAP_FILES: Final = 50_000
MAX_OFFLINE_BOOTSTRAP_BYTES: Final = 2 * 1024 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]+\Z")


class CodingWorkRuntimeError(RuntimeError):
    """A safe Coding Work runtime-boundary failure."""

    code = "coding_work_runtime_error"


class CodingWorkRuntimeUnsafeError(CodingWorkRuntimeError):
    code = "unsafe_runtime_layout"


class CodingWorkRuntimeConflictError(CodingWorkRuntimeError):
    code = "runtime_already_initialized"


class CodingWorkOwnershipUnavailableError(CodingWorkRuntimeError):
    code = "supervisor_ownership_unavailable"


class CodingWorkRuntimeBusyError(CodingWorkRuntimeError):
    code = "coding_work_busy"


@dataclass(frozen=True, slots=True)
class CodingWorkRuntimeLayout:
    """Exact production-compatible paths rooted beneath one runtime parent."""

    runtime_parent: Path
    root_name: str = "coding_work"

    def __post_init__(self) -> None:
        if (
            not self.root_name
            or self.root_name in {".", ".."}
            or "/" in self.root_name
            or "\x00" in self.root_name
        ):
            raise ValueError("The Coding Work runtime directory name is invalid.")

    @property
    def root(self) -> Path:
        return self.runtime_parent / self.root_name

    @property
    def database(self) -> Path:
        return self.root / CODING_WORK_DATABASE_NAME

    @property
    def supervisor_lock(self) -> Path:
        return self.root / CODING_WORK_LOCK_NAME

    @property
    def opencode_root(self) -> Path:
        return self.root / OPENCODE_DIRECTORY_NAME

    @property
    def opencode_instance(self) -> Path:
        return self.opencode_root / OPENCODE_INSTANCE_NAME

    @property
    def opencode_works(self) -> Path:
        return self.opencode_root / "works"

    @property
    def opencode_ipc(self) -> Path:
        return self.opencode_root / "ipc"

    @property
    def opencode_bootstrap_cache(self) -> Path:
        return self.opencode_root / "bootstrap-cache"

    @property
    def provider_socket(self) -> Path:
        return self.opencode_ipc / "provider.sock"

    @property
    def bootstrap_manifest(self) -> Path:
        return self.opencode_root / OFFLINE_BOOTSTRAP_MANIFEST

    @property
    def bootstrap_prepared(self) -> Path:
        return self.opencode_bootstrap_cache / "prepared"


@dataclass(frozen=True, slots=True)
class CodingWorkProductionSettings:
    """Narrow administrator configuration for the first production adapter."""

    runtime_root: Path
    opencode_executable: Path
    opencode_version: str
    bubblewrap_executable: Path
    provider_upstream: str
    model: str
    control_timeout_seconds: float = 30.0
    model_turn_timeout_seconds: float = 15 * 60.0

    def __post_init__(self) -> None:
        for value, label in (
            (self.runtime_root, "Coding Work runtime root"),
            (self.opencode_executable, "OpenCode executable"),
            (self.bubblewrap_executable, "Bubblewrap executable"),
        ):
            if not Path(value).is_absolute():
                raise ValueError(f"The {label} must be an absolute path.")
        if self.runtime_root.name != "coding_work":
            raise ValueError("The Coding Work runtime root must end in coding_work.")
        if self.opencode_version != OPENCODE_TARGET_VERSION:
            raise ValueError(
                f"The first OpenCode adapter requires version {OPENCODE_TARGET_VERSION}."
            )
        parsed = urlparse(self.provider_upstream)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path.rstrip("/") != "/v1"
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "The Coding Work provider must be one exact loopback OpenAI-compatible /v1 root."
            )
        if not self.model or len(self.model) > 200 or "\x00" in self.model:
            raise ValueError("The Coding Work model is invalid.")
        if self.control_timeout_seconds <= 0 or self.model_turn_timeout_seconds <= 0:
            raise ValueError("Coding Work timeouts must be positive.")

    @property
    def private_root(self) -> Path:
        return self.runtime_root / OPENCODE_DIRECTORY_NAME

    @property
    def provider_host(self) -> str:
        value = urlparse(self.provider_upstream).hostname
        assert value is not None
        return value

    @property
    def provider_port(self) -> int:
        value = urlparse(self.provider_upstream).port
        assert value is not None
        return value


@dataclass(frozen=True, slots=True)
class CodingWorkReadiness:
    state: str
    code: str
    reason: str

    @property
    def available(self) -> bool:
        return self.state == "available"


class CodingWorkRuntimeInitializer:
    """Create and publish one complete Coding Work layout exactly once."""

    def __init__(
        self,
        runtime_parent: Path,
        *,
        token_hex: Callable[[int], str] | None = None,
    ) -> None:
        self.layout = CodingWorkRuntimeLayout(Path(runtime_parent))
        self._token_hex = token_hex or secrets.token_hex

    def initialize(self) -> CodingWorkRuntimeLayout:
        parent_fd = _open_runtime_parent(self.layout.runtime_parent)
        staging_name: str | None = None
        try:
            if _stat_at(parent_fd, "coding_work") is not None:
                raise CodingWorkRuntimeConflictError(
                    "The canonical Coding Work runtime path already exists."
                )
            abandoned = sorted(
                item.name
                for item in os.scandir(parent_fd)
                if item.name.startswith(INITIALIZER_PREFIX)
            )
            if abandoned:
                raise CodingWorkRuntimeConflictError(
                    f"An abandoned Coding Work initializer exists: {abandoned[0]!r}."
                )
            staging_name = INITIALIZER_PREFIX + self._token(16)
            os.mkdir(staging_name, 0o700, dir_fd=parent_fd)
            staging = self.layout.runtime_parent / staging_name
            self._create_staged_layout(staging)
            validate_coding_work_layout(
                CodingWorkRuntimeLayout(staging.parent, staging.name),
                require_quiescent=True,
                require_empty=True,
            )
            _fsync_directory_tree(staging)
            _rename_no_replace(parent_fd, staging_name, "coding_work")
            os.fsync(parent_fd)
        except CodingWorkRuntimeError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            detail = " before a staging directory was created"
            if staging_name is not None:
                detail = f"; preserved staging directory {staging_name!r}"
            raise CodingWorkRuntimeUnsafeError(
                "Coding Work initialization failed" + detail + "."
            ) from exc
        finally:
            os.close(parent_fd)
        validate_coding_work_layout(
            self.layout, require_quiescent=True, require_empty=True
        )
        return self.layout

    def _create_staged_layout(self, root: Path) -> None:
        SQLiteCodingWorkStore(root / CODING_WORK_DATABASE_NAME).initialize()
        _create_regular_file(root / CODING_WORK_LOCK_NAME, b"")
        opencode = root / OPENCODE_DIRECTORY_NAME
        os.mkdir(opencode, 0o700)
        os.mkdir(opencode / "works", 0o700)
        os.mkdir(opencode / "ipc", 0o700)
        os.mkdir(opencode / "bootstrap-cache", 0o700)
        instance = json.dumps(
            {"schema": 1, "token": self._token(32)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        _create_regular_file(opencode / OPENCODE_INSTANCE_NAME, instance)

    def _token(self, length: int) -> str:
        value = self._token_hex(length)
        if (
            not isinstance(value, str)
            or len(value) != length * 2
            or _HEX.fullmatch(value) is None
        ):
            raise CodingWorkRuntimeUnsafeError(
                "A safe Coding Work initialization identity could not be generated."
            )
        return value


def validate_coding_work_layout(
    layout: CodingWorkRuntimeLayout,
    *,
    require_quiescent: bool,
    require_empty: bool = False,
) -> None:
    """Validate a complete published or staged layout without repairing it."""

    _require_directory(layout.root, exact_mode=0o700)
    root_names = {item.name for item in os.scandir(layout.root)}
    if root_names != {
        CODING_WORK_DATABASE_NAME,
        CODING_WORK_LOCK_NAME,
        OPENCODE_DIRECTORY_NAME,
    }:
        raise CodingWorkRuntimeUnsafeError(
            "The Coding Work runtime root has an unexpected layout."
        )
    _require_regular(layout.database, exact_mode=0o600)
    _require_regular(layout.supervisor_lock, exact_mode=0o600)
    try:
        SQLiteCodingWorkStore(layout.database).revision()
    except Exception as exc:
        raise CodingWorkRuntimeUnsafeError(
            "The Coding Work database is unavailable or has an unsupported schema."
        ) from exc

    _require_directory(layout.opencode_root, exact_mode=0o700)
    names = {item.name for item in os.scandir(layout.opencode_root)}
    required = {OPENCODE_INSTANCE_NAME, "works", "ipc", "bootstrap-cache"}
    allowed = required | {"version-check", OFFLINE_BOOTSTRAP_MANIFEST}
    if not required.issubset(names) or not names.issubset(allowed):
        raise CodingWorkRuntimeUnsafeError(
            "The OpenCode private-state root has an unexpected layout."
        )
    _require_regular(layout.opencode_instance, exact_mode=0o600)
    _validate_instance(layout.opencode_instance)
    for directory in (
        layout.opencode_works,
        layout.opencode_ipc,
        layout.opencode_bootstrap_cache,
    ):
        _require_directory(directory, exact_mode=0o700)
    if require_empty and (
        any(os.scandir(layout.opencode_works))
        or any(os.scandir(layout.opencode_ipc))
        or any(os.scandir(layout.opencode_bootstrap_cache))
    ):
        raise CodingWorkRuntimeUnsafeError(
            "A newly initialized OpenCode private-state root is not empty."
        )
    _validate_private_tree(layout.opencode_root, require_quiescent=require_quiescent)


class CodingWorkRuntimeOwnership:
    """One kernel-enforced mutation/supervision owner for a runtime."""

    def __init__(self, layout: CodingWorkRuntimeLayout) -> None:
        self.layout = layout
        self._descriptor: int | None = None
        self._gate = threading.RLock()
        self._admissions_stopped = False
        self._maintenance = False

    @property
    def owned(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> bool:
        with self._gate:
            if self._descriptor is not None:
                return True
            validate_coding_work_layout(
                self.layout, require_quiescent=False, require_empty=False
            )
            descriptor = os.open(
                self.layout.supervisor_lock,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                _require_open_regular(descriptor, exact_mode=0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                    return False
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
            self._descriptor = descriptor
            self._admissions_stopped = False
            return True

    def require_owned(self) -> None:
        if self._descriptor is None:
            raise CodingWorkOwnershipUnavailableError(
                "This Tori process does not own Coding Work supervision."
            )

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._gate:
            self.require_owned()
            if self._admissions_stopped or self._maintenance:
                raise CodingWorkRuntimeBusyError(
                    "Coding Work mutation is temporarily unavailable."
                )
            yield

    @contextmanager
    def exclusive_maintenance(self) -> Iterator[None]:
        if not self._gate.acquire(blocking=False):
            raise CodingWorkRuntimeBusyError(
                "A Coding Work operation is already in progress."
            )
        try:
            self.require_owned()
            if self._maintenance:
                raise CodingWorkRuntimeBusyError(
                    "Coding Work maintenance is already active."
                )
            self._maintenance = True
            try:
                yield
            finally:
                self._maintenance = False
        finally:
            self._gate.release()

    def stop_admissions(self) -> None:
        with self._gate:
            self.require_owned()
            self._admissions_stopped = True

    def release(self) -> None:
        with self._gate:
            descriptor, self._descriptor = self._descriptor, None
            self._admissions_stopped = True
            if descriptor is None:
                return
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def shutdown(
        self,
        *,
        stop_owned_workers: Callable[[], None],
        release_provider_transport: Callable[[], None],
    ) -> None:
        """Stop admissions and contained processes, releasing the lock last."""

        self.stop_admissions()
        try:
            stop_owned_workers()
        finally:
            try:
                release_provider_transport()
            finally:
                self.release()

    def __enter__(self) -> "CodingWorkRuntimeOwnership":
        if not self.acquire():
            raise CodingWorkOwnershipUnavailableError(
                "Another Tori process owns Coding Work supervision."
            )
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class CodingWorkReadinessEvaluator:
    """Evaluate production prerequisites without fallback or canonical creation."""

    def __init__(
        self,
        settings: CodingWorkProductionSettings | None,
        *,
        ownership: CodingWorkRuntimeOwnership | None = None,
        provider_model_available: Callable[[CodingWorkProductionSettings], bool] | None = None,
        opencode_version_probe: Callable[[CodingWorkProductionSettings], bool] | None = None,
        bubblewrap_probe: Callable[[CodingWorkProductionSettings], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.ownership = ownership
        self._provider_model_available = provider_model_available
        self._opencode_version_probe = opencode_version_probe or _probe_opencode_version
        self._bubblewrap_probe = bubblewrap_probe or _probe_bubblewrap

    def evaluate(self, *, work_states: tuple[str, ...] = ()) -> CodingWorkReadiness:
        settings = self.settings
        if settings is None:
            return CodingWorkReadiness(
                "unavailable", "configuration_missing",
                "Coding Work production configuration is missing.",
            )
        layout = CodingWorkRuntimeLayout(settings.runtime_root.parent)
        if not os.path.lexists(layout.root):
            return CodingWorkReadiness(
                "uninitialized", "canonical_root_absent",
                "Canonical Coding Work state has not been initialized.",
            )
        try:
            validate_coding_work_layout(
                layout, require_quiescent=False, require_empty=False
            )
        except CodingWorkRuntimeError:
            return CodingWorkReadiness(
                "unavailable", "unsafe_runtime_layout",
                "Canonical Coding Work state is unsafe or invalid.",
            )
        if self.ownership is None or not self.ownership.owned:
            return CodingWorkReadiness(
                "unavailable", "supervisor_ownership_unavailable",
                "This Tori process does not own Coding Work supervision.",
            )
        if not _executable_available(settings.opencode_executable):
            return CodingWorkReadiness(
                "unavailable", "opencode_missing", "The configured OpenCode executable is missing or unsafe."
            )
        if not _executable_available(settings.bubblewrap_executable):
            return CodingWorkReadiness(
                "unavailable", "bubblewrap_missing", "The configured Bubblewrap executable is missing or unsafe."
            )
        try:
            if not self._opencode_version_probe(settings):
                return CodingWorkReadiness(
                    "unavailable", "opencode_wrong_version",
                    f"OpenCode is not the required version {settings.opencode_version}.",
                )
            if not self._bubblewrap_probe(settings):
                return CodingWorkReadiness(
                    "unavailable", "bubblewrap_unavailable",
                    "Bubblewrap isolation is unavailable.",
                )
        except (OSError, subprocess.SubprocessError, ValueError):
            return CodingWorkReadiness(
                "unavailable", "prerequisite_probe_failed",
                "A Coding Work executable prerequisite could not be verified safely.",
            )
        if self._provider_model_available is None or not self._provider_model_available(settings):
            return CodingWorkReadiness(
                "unavailable", "provider_model_unavailable",
                "The exact Coding Work provider/model is unavailable; no fallback was used.",
            )
        if not offline_bootstrap_ready(layout, settings):
            return CodingWorkReadiness(
                "unavailable", "offline_bootstrap_missing",
                "OpenCode offline bootstrap material has not been explicitly prepared.",
            )
        if "reconciling" in work_states:
            return CodingWorkReadiness(
                "reconciling", "reconciliation_pending",
                "Coding Work restart reconciliation is still in progress.",
            )
        return CodingWorkReadiness(
            "available", "ready", "Coding Work production prerequisites are ready."
        )


def offline_bootstrap_ready(
    layout: CodingWorkRuntimeLayout,
    settings: CodingWorkProductionSettings,
) -> bool:
    """Validate an explicit future bootstrap receipt; never bootstrap implicitly."""

    path = layout.bootstrap_manifest
    try:
        _require_regular(path, exact_mode=0o600)
        descriptor = _open_immutable_read(path)
        try:
            payload = os.read(descriptor, 4097)
        finally:
            os.close(descriptor)
        if len(payload) > 4096:
            return False
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, CodingWorkRuntimeError):
        return False
    try:
        digest, count, total = offline_bootstrap_inventory(layout.bootstrap_prepared)
    except CodingWorkRuntimeError:
        return False
    if not isinstance(document, dict) or set(document) != {
        "schema", "opencode_version", "provider_package", "status",
        "cache_digest", "cache_file_count", "cache_total_bytes",
        "prepared_at_utc", "provenance",
    }:
        return False
    prepared_at = document.get("prepared_at_utc")
    try:
        parsed = datetime.fromisoformat(str(prepared_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return False
    expected = {
        "schema": 1,
        "opencode_version": settings.opencode_version,
        "provider_package": OPENCODE_PROVIDER_PACKAGE,
        "status": "prepared_offline",
        "cache_digest": digest,
        "cache_file_count": count,
        "cache_total_bytes": total,
        "prepared_at_utc": prepared_at,
        "provenance": OFFLINE_BOOTSTRAP_PROVENANCE,
    }
    return (
        document == expected
        and _prepared_opencode_has_no_sessions(layout.bootstrap_prepared)
    )


def offline_bootstrap_inventory(root: Path) -> tuple[str, int, int]:
    """Digest a bounded, no-follow owner-only bootstrap cache tree."""

    _require_directory(root, exact_mode=0o700)
    digest = hashlib.sha256()
    count = 0
    total = 0
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        _require_directory(current, exact_mode=0o700)
        names.sort()
        files.sort()
        for name in names:
            child = current / name
            if child.is_symlink():
                raise CodingWorkRuntimeUnsafeError("The offline bootstrap cache is unsafe.")
        for name in files:
            child = current / name
            metadata = child.lstat()
            mode = stat.S_IMODE(metadata.st_mode)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_gid != os.getegid()
                or metadata.st_nlink != 1
                or mode not in {0o600, 0o700}
            ):
                raise CodingWorkRuntimeUnsafeError("The offline bootstrap cache is unsafe.")
            count += 1
            total += metadata.st_size
            if count > MAX_OFFLINE_BOOTSTRAP_FILES or total > MAX_OFFLINE_BOOTSTRAP_BYTES:
                raise CodingWorkRuntimeUnsafeError("The offline bootstrap cache exceeds its budget.")
            relative = child.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(mode.to_bytes(2, "big"))
            descriptor = _open_immutable_read(child)
            try:
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
            finally:
                os.close(descriptor)
    if count == 0:
        raise CodingWorkRuntimeUnsafeError("The offline bootstrap cache is empty.")
    return digest.hexdigest(), count, total


def _prepared_opencode_has_no_sessions(root: Path) -> bool:
    """Inspect captured OpenCode SQLite state only through a disposable copy."""

    source = root / "data" / "opencode" / "opencode.db"
    if not os.path.lexists(source):
        return True
    names = ("opencode.db", "opencode.db-wal", "opencode.db-shm", "opencode.db-journal")
    try:
        with tempfile.TemporaryDirectory(prefix="tori-opencode-bootstrap-validation-") as temporary:
            destination_root = Path(temporary)
            for name in names:
                candidate = source.parent / name
                if not os.path.lexists(candidate):
                    continue
                _copy_immutable_regular(candidate, destination_root / name)
            database = destination_root / "opencode.db"
            connection = sqlite3.connect(
                f"file:{database.as_posix()}?mode=ro", uri=True, timeout=5.0
            )
            try:
                connection.execute("PRAGMA query_only = ON")
                present = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'session'"
                ).fetchone()
                if present is None:
                    return False
                return connection.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 0
            finally:
                connection.close()
    except (OSError, sqlite3.Error, CodingWorkRuntimeError):
        return False


def _open_immutable_read(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NOATIME", 0)
    return os.open(path, flags)


def _copy_immutable_regular(source: Path, destination: Path) -> None:
    _require_regular(source, exact_mode=0o600)
    source_descriptor = _open_immutable_read(source)
    try:
        destination_descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            while chunk := os.read(source_descriptor, 1024 * 1024):
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_descriptor, view)
                    view = view[written:]
        finally:
            os.close(destination_descriptor)
    finally:
        os.close(source_descriptor)


def _probe_opencode_version(settings: CodingWorkProductionSettings) -> bool:
    _require_executable(settings.opencode_executable)
    with tempfile.TemporaryDirectory(prefix="tori-coding-readiness-") as temporary:
        root = Path(temporary)
        environment = {
            "HOME": str(root / "home"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "XDG_STATE_HOME": str(root / "state"),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
        }
        for value in environment.values():
            if value.startswith(str(root)):
                Path(value).mkdir(mode=0o700)
        completed = subprocess.run(
            (str(settings.opencode_executable), "--version"),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            umask=0o077,
        )
    return (
        completed.returncode == 0
        and completed.stdout.decode("utf-8", errors="replace").strip()
        == settings.opencode_version
    )


def _probe_bubblewrap(settings: CodingWorkProductionSettings) -> bool:
    _require_executable(settings.bubblewrap_executable)
    completed = subprocess.run(
        (str(settings.bubblewrap_executable), "--version"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
        check=False,
        umask=0o077,
    )
    return completed.returncode == 0


def _require_executable(path: Path) -> None:
    metadata = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o111 == 0:
        raise ValueError("A Coding Work executable is unavailable.")


def _executable_available(path: Path) -> bool:
    try:
        _require_executable(path)
    except (OSError, ValueError):
        return False
    return True


def _open_runtime_parent(path: Path) -> int:
    descriptor = _open_directory_no_follow(path)
    metadata = os.fstat(descriptor)
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) & 0o002
    ):
        os.close(descriptor)
        raise CodingWorkRuntimeUnsafeError(
            "The runtime parent has unsafe ownership or permissions."
        )
    return descriptor


def _open_directory_no_follow(path: Path) -> int:
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
        raise CodingWorkRuntimeUnsafeError("A Coding Work runtime path is unsafe.")
    absolute = Path(os.path.abspath(os.path.normpath(raw)))
    flags = (
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _require_directory(path: Path, *, exact_mode: int) -> None:
    descriptor = _open_directory_no_follow(path)
    try:
        metadata = os.fstat(descriptor)
        if (
            metadata.st_uid != os.geteuid()
            or metadata.st_gid != os.getegid()
            or stat.S_IMODE(metadata.st_mode) != exact_mode
        ):
            raise CodingWorkRuntimeUnsafeError(
                "A Coding Work private directory has unsafe ownership or permissions."
            )
    finally:
        os.close(descriptor)


def _require_regular(path: Path, *, exact_mode: int) -> None:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        _require_open_regular(descriptor, exact_mode=exact_mode)
    finally:
        os.close(descriptor)


def _require_open_regular(descriptor: int, *, exact_mode: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) != exact_mode
    ):
        raise CodingWorkRuntimeUnsafeError(
            "A Coding Work private file has unsafe ownership or permissions."
        )


def _validate_private_tree(root: Path, *, require_quiescent: bool) -> None:
    for directory, names, files in os.walk(root, followlinks=False):
        current = Path(directory)
        _require_directory(current, exact_mode=0o700)
        for name in names:
            child = current / name
            metadata = child.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise CodingWorkRuntimeUnsafeError(
                    "The OpenCode private-state tree contains an unsafe object."
                )
        for name in files:
            child = current / name
            metadata = child.lstat()
            if stat.S_ISSOCK(metadata.st_mode) and child == root / "ipc/provider.sock":
                if require_quiescent or stat.S_IMODE(metadata.st_mode) != 0o600:
                    raise CodingWorkRuntimeUnsafeError(
                        "The provider socket is active or unsafe."
                    )
                continue
            mode = stat.S_IMODE(metadata.st_mode)
            in_bootstrap_cache = (
                current == root / "bootstrap-cache"
                or root / "bootstrap-cache" in current.parents
            )
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or metadata.st_gid != os.getegid()
                or metadata.st_nlink != 1
                or (mode not in {0o600, 0o700} if in_bootstrap_cache else mode != 0o600)
            ):
                raise CodingWorkRuntimeUnsafeError(
                    "The OpenCode private-state tree contains an unsafe file."
                )


def _validate_instance(path: Path) -> None:
    try:
        with open(path, "rb") as stream:
            payload = stream.read(1025)
        document = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodingWorkRuntimeUnsafeError(
            "The OpenCode private instance identity is invalid."
        ) from exc
    token = document.get("token") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "token"}
        or document.get("schema") != 1
        or not isinstance(token, str)
        or len(token) != 64
        or _HEX.fullmatch(token) is None
    ):
        raise CodingWorkRuntimeUnsafeError(
            "The OpenCode private instance identity is invalid."
        )


def _create_regular_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _fsync_directory_tree(root: Path) -> None:
    directories = [root]
    for directory, names, _files in os.walk(root, followlinks=False):
        current = Path(directory)
        directories.extend(current / name for name in names)
    for directory in reversed(directories):
        descriptor = os.open(
            directory,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _stat_at(descriptor: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _rename_no_replace(parent: int, source: str, destination: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = library.renameat2
    except AttributeError as exc:
        raise OSError(errno.ENOSYS, "atomic no-replace rename is unavailable") from exc
    renameat2.argtypes = (
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        parent, os.fsencode(source), parent, os.fsencode(destination), 1
    ) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)
