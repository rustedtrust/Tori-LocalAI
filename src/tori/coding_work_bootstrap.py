"""Explicit offline-bootstrap provisioning for the OpenCode Coding Work adapter.

This operation is never invoked by normal startup or worker launch.  A caller
must provide the exact destination and explicitly authorize any network-bearing
subprocess execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile
import threading
from typing import Final, Protocol

from .coding_work import CodingWorkAuthority
from .coding_work_bootstrap_transport import (
    BootstrapEgressAudit,
    BootstrapEgressError,
    BOOTSTRAP_MODELS_URL,
    FixedOpenCodeBootstrapRelay,
)
from .coding_work_opencode import _configuration
from .coding_work_runtime import (
    OFFLINE_BOOTSTRAP_MANIFEST,
    OFFLINE_BOOTSTRAP_PROVENANCE,
    OPENCODE_PROVIDER_PACKAGE,
    OPENCODE_TARGET_VERSION,
    CodingWorkRuntimeError,
    CodingWorkRuntimeUnsafeError,
    _create_regular_file,
    _fsync_directory_tree,
    _open_directory_no_follow,
    _rename_no_replace,
    _require_directory,
    _require_executable,
    offline_bootstrap_inventory,
)


BOOTSTRAP_STAGING_PREFIX: Final = ".opencode-bootstrap.initialize-"
RECEIPT_STAGING_PREFIX: Final = ".offline-bootstrap.initialize-"
MAX_BOOTSTRAP_DIAGNOSTIC_BYTES: Final = 64 * 1024
BOOTSTRAP_TIMEOUT_SECONDS: Final = 120.0


class OpenCodeBootstrapError(RuntimeError):
    code = "opencode_bootstrap_failed"


class OpenCodeBootstrapConflictError(OpenCodeBootstrapError):
    code = "opencode_bootstrap_conflict"


class OpenCodeBootstrapNetworkAuthorizationRequired(OpenCodeBootstrapError):
    code = "bootstrap_network_authorization_required"


class BootstrapCompletedProcess(Protocol):
    returncode: int
    stdout: bytes
    stderr: bytes


BootstrapRunner = Callable[
    [Sequence[str], Path, Mapping[str, str]], BootstrapCompletedProcess
]


@dataclass(frozen=True, slots=True)
class OpenCodeBootstrapResult:
    prepared_root: Path
    receipt: Path
    cache_digest: str
    cache_file_count: int
    cache_total_bytes: int
    prepared_at_utc: str
    egress_audit: tuple[BootstrapEgressAudit, ...]


class OpenCodeOfflineBootstrapper:
    """Prepare and publish one immutable regenerable OpenCode cache generation."""

    def __init__(
        self,
        *,
        destination: Path,
        opencode_executable: Path,
        opencode_version: str,
        model: str,
        bubblewrap_executable: Path | None = None,
        runner: BootstrapRunner | None = None,
        clock: Callable[[], datetime] | None = None,
        token_hex: Callable[[int], str] | None = None,
    ) -> None:
        self.destination = Path(destination)
        self.opencode_executable = Path(opencode_executable)
        self.opencode_version = opencode_version
        self.model = model
        self.bubblewrap_executable = (
            Path(bubblewrap_executable) if bubblewrap_executable is not None else None
        )
        self._runner = runner
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_hex = token_hex or secrets.token_hex
        if not self.destination.is_absolute() or self.destination.name != "bootstrap-cache":
            raise ValueError("The OpenCode bootstrap destination must be an absolute bootstrap-cache root.")
        if not self.opencode_executable.is_absolute():
            raise ValueError("The OpenCode executable path must be absolute.")
        if self.opencode_version != OPENCODE_TARGET_VERSION:
            raise ValueError(f"OpenCode {OPENCODE_TARGET_VERSION} is required.")
        if not self.model or len(self.model) > 200 or "\x00" in self.model:
            raise ValueError("The OpenCode bootstrap model identity is invalid.")
        if self.bubblewrap_executable is not None and not self.bubblewrap_executable.is_absolute():
            raise ValueError("The Bubblewrap executable path must be absolute.")

    @property
    def receipt(self) -> Path:
        return self.destination.parent / OFFLINE_BOOTSTRAP_MANIFEST

    def prepare(self, *, network_authorized: bool = False) -> OpenCodeBootstrapResult:
        """Execute one explicit bootstrap, preserving all failed staging state."""

        if self._runner is None and not network_authorized:
            raise OpenCodeBootstrapNetworkAuthorizationRequired(
                "OpenCode package bootstrap may use the network; explicit provisioning authority is required."
            )
        self._validate_empty_destination()
        _require_executable(self.opencode_executable)
        if self._runner is None:
            if self.bubblewrap_executable is None:
                raise OpenCodeBootstrapError(
                    "An exact Bubblewrap executable is required for OpenCode bootstrap."
                )
            _require_executable(self.bubblewrap_executable)
        token = self._token()
        stage = self.destination / (BOOTSTRAP_STAGING_PREFIX + token)
        receipt_stage = self.destination.parent / (
            RECEIPT_STAGING_PREFIX + token + ".json"
        )
        os.mkdir(stage, 0o700)
        for name in ("data", "cache", "state"):
            os.mkdir(stage / name, 0o700)
        try:
            egress_audit = self._run_bootstrap(stage)
            self._validate_prepared_roots(stage)
            digest, count, total = offline_bootstrap_inventory(stage)
            prepared_at = self._timestamp()
            receipt_document = {
                "schema": 1,
                "opencode_version": self.opencode_version,
                "provider_package": OPENCODE_PROVIDER_PACKAGE,
                "status": "prepared_offline",
                "cache_digest": digest,
                "cache_file_count": count,
                "cache_total_bytes": total,
                "prepared_at_utc": prepared_at,
                "provenance": OFFLINE_BOOTSTRAP_PROVENANCE,
            }
            receipt_bytes = json.dumps(
                receipt_document, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
            if len(receipt_bytes) > 4096:
                raise OpenCodeBootstrapError("The OpenCode bootstrap receipt is too large.")
            _create_regular_file(receipt_stage, receipt_bytes)
            _fsync_directory_tree(stage)
            _fsync_directory(self.destination)
            _fsync_directory(self.destination.parent)
            destination_fd = _open_directory_no_follow(self.destination)
            try:
                _rename_no_replace(
                    destination_fd, stage.name, "prepared"
                )
                os.fsync(destination_fd)
            finally:
                os.close(destination_fd)
            parent_fd = _open_directory_no_follow(self.destination.parent)
            try:
                _rename_no_replace(
                    parent_fd, receipt_stage.name, self.receipt.name
                )
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            return OpenCodeBootstrapResult(
                self.destination / "prepared", self.receipt,
                digest, count, total, prepared_at, egress_audit,
            )
        except OpenCodeBootstrapError:
            raise
        except (
            BootstrapEgressError,
            CodingWorkRuntimeError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as exc:
            raise OpenCodeBootstrapError(
                "OpenCode offline bootstrap failed; staging was preserved without retry."
            ) from exc

    def _validate_empty_destination(self) -> None:
        _require_directory(self.destination, exact_mode=0o700)
        _require_directory(self.destination.parent, exact_mode=0o700)
        if os.path.lexists(self.receipt):
            raise OpenCodeBootstrapConflictError(
                "The OpenCode offline-bootstrap receipt already exists."
            )
        with os.scandir(self.destination) as entries:
            if next(entries, None) is not None:
                raise OpenCodeBootstrapConflictError(
                    "The OpenCode bootstrap destination is not empty; no merge or repair was attempted."
                )
        with os.scandir(self.destination.parent) as entries:
            abandoned = sorted(
                entry.name for entry in entries
                if entry.name.startswith(RECEIPT_STAGING_PREFIX)
            )
        if abandoned:
            raise OpenCodeBootstrapConflictError(
                f"An abandoned OpenCode bootstrap receipt exists: {abandoned[0]!r}."
            )

    def _run_bootstrap(self, stage: Path) -> tuple[BootstrapEgressAudit, ...]:
        with tempfile.TemporaryDirectory(prefix="tori-opencode-bootstrap-") as temporary:
            isolated = Path(temporary)
            for name in ("home", "config", "tmp", "workspace"):
                (isolated / name).mkdir(mode=0o700)
            config_root = isolated / "config/opencode"
            config_root.mkdir(mode=0o700)
            authority = CodingWorkAuthority(
                str(isolated / "workspace"), True, False, False
            )
            config = _configuration(authority, self.model).encode("utf-8")
            _create_regular_file(config_root / "opencode.json", config)
            environment = {
                "HOME": str(isolated / "home"),
                "XDG_CONFIG_HOME": str(isolated / "config"),
                "XDG_DATA_HOME": str(stage / "data"),
                "XDG_CACHE_HOME": str(stage / "cache"),
                "XDG_STATE_HOME": str(stage / "state"),
                "TMPDIR": str(isolated / "tmp"),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "OPENCODE_DISABLE_AUTOUPDATE": "true",
                "OPENCODE_MODELS_URL": BOOTSTRAP_MODELS_URL,
            }
            if self._runner is None:
                return self._run_isolated_bootstrap(stage, isolated, environment)
            runner = self._runner
            version = runner(
                (str(self.opencode_executable), "--version"),
                isolated / "workspace", environment,
            )
            self._validate_process(version, "version check")
            observed = version.stdout.decode("utf-8", errors="replace").strip()
            if observed != self.opencode_version:
                raise OpenCodeBootstrapError(
                    f"OpenCode {self.opencode_version} is required; the isolated executable reported {observed or 'unknown'}."
                )
            completed = runner(
                (str(self.opencode_executable), "debug", "config", "--pure"),
                isolated / "workspace", environment,
            )
            self._validate_process(completed, "package bootstrap")
            return ()

    def _run_isolated_bootstrap(
        self, stage: Path, isolated: Path, environment: Mapping[str, str]
    ) -> tuple[BootstrapEgressAudit, ...]:
        assert self.bubblewrap_executable is not None
        ipc = isolated / "ipc"
        ipc.mkdir(mode=0o700)
        socket_path = ipc / "bootstrap-egress.sock"
        hosts = isolated / "hosts"
        hosts.write_text("127.0.0.1 models.opencode.ai\n", encoding="ascii")
        os.chmod(hosts, 0o600)
        resolv = isolated / "resolv.conf"
        resolv.write_bytes(b"")
        os.chmod(resolv, 0o600)
        nsswitch = isolated / "nsswitch.conf"
        nsswitch.write_text("hosts: files\n", encoding="ascii")
        os.chmod(nsswitch, 0o600)
        bridge_source = Path(__file__).with_name("coding_work_bootstrap_transport.py")
        _require_regular_security_source(bridge_source)
        relay = FixedOpenCodeBootstrapRelay(socket_path)
        relay.start()
        try:
            version = self._subprocess_runner(
                _bootstrap_sandbox_argv(
                    self.bubblewrap_executable,
                    self.opencode_executable,
                    bridge_source,
                    socket_path,
                    hosts,
                    resolv,
                    nsswitch,
                    stage,
                    isolated,
                    ("/harness/opencode", "--version"),
                ),
                isolated / "workspace",
                environment,
            )
            self._validate_process(version, "version check")
            observed = version.stdout.decode("utf-8", errors="replace").strip()
            if observed != self.opencode_version:
                raise OpenCodeBootstrapError(
                    f"OpenCode {self.opencode_version} is required; the isolated executable reported {observed or 'unknown'}."
                )
            completed = self._subprocess_runner(
                _bootstrap_sandbox_argv(
                    self.bubblewrap_executable,
                    self.opencode_executable,
                    bridge_source,
                    socket_path,
                    hosts,
                    resolv,
                    nsswitch,
                    stage,
                    isolated,
                    ("/harness/opencode", "debug", "config", "--pure"),
                ),
                isolated / "workspace",
                environment,
            )
            self._validate_process(completed, "package bootstrap")
        finally:
            relay.close()
        return relay.audit

    @staticmethod
    def _subprocess_runner(
        command: Sequence[str], cwd: Path, environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        process = subprocess.Popen(
            tuple(command), cwd=cwd, env=dict(environment),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True, umask=0o077,
        )
        stdout = bytearray()
        stderr = bytearray()
        overflow = threading.Event()

        def drain(stream, target: bytearray) -> None:  # type: ignore[no-untyped-def]
            while chunk := stream.read(8192):
                remaining = MAX_BOOTSTRAP_DIAGNOSTIC_BYTES + 1 - len(target)
                if remaining > 0:
                    target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()

        threads = (
            threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
        )
        for thread in threads:
            thread.start()
        try:
            returncode = process.wait(timeout=BOOTSTRAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, 15)
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, 9)
                except OSError:
                    pass
                process.wait()
            raise
        finally:
            for thread in threads:
                thread.join(timeout=2)
        if overflow.is_set():
            return subprocess.CompletedProcess(
                tuple(command), returncode,
                bytes(stdout[: MAX_BOOTSTRAP_DIAGNOSTIC_BYTES + 1]),
                bytes(stderr[: MAX_BOOTSTRAP_DIAGNOSTIC_BYTES + 1]),
            )
        return subprocess.CompletedProcess(tuple(command), returncode, bytes(stdout), bytes(stderr))

    @staticmethod
    def _validate_process(completed: BootstrapCompletedProcess, label: str) -> None:
        if (
            len(completed.stdout) > MAX_BOOTSTRAP_DIAGNOSTIC_BYTES
            or len(completed.stderr) > MAX_BOOTSTRAP_DIAGNOSTIC_BYTES
        ):
            raise OpenCodeBootstrapError(f"The OpenCode {label} diagnostics exceeded their bound.")
        if completed.returncode != 0:
            stdout = completed.stdout.decode("utf-8", errors="replace")
            stderr = completed.stderr.decode("utf-8", errors="replace")
            raise OpenCodeBootstrapError(
                f"The isolated OpenCode {label} failed. "
                f"Return code: {completed.returncode}; "
                f"captured stdout: {stdout!r}; captured stderr: {stderr!r}."
            )

    @staticmethod
    def _validate_prepared_roots(stage: Path) -> None:
        with os.scandir(stage) as entries:
            names = {entry.name for entry in entries}
        if names != {"data", "cache", "state"}:
            raise CodingWorkRuntimeUnsafeError(
                "OpenCode bootstrap produced an unexpected state-root layout."
            )
        for name in names:
            _require_directory(stage / name, exact_mode=0o700)

    def _token(self) -> str:
        token = self._token_hex(16)
        if (
            not isinstance(token, str) or len(token) != 32
            or any(character not in "0123456789abcdef" for character in token)
        ):
            raise OpenCodeBootstrapError("A safe OpenCode bootstrap identity could not be generated.")
        return token

    def _timestamp(self) -> str:
        value = self._clock().astimezone(timezone.utc)
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = _open_directory_no_follow(path)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_regular_security_source(path: Path) -> None:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
    ):
        raise OpenCodeBootstrapError("A bootstrap security source is unsafe.")


def _bootstrap_sandbox_argv(
    bubblewrap: Path,
    opencode: Path,
    bridge_source: Path,
    socket_path: Path,
    hosts: Path,
    resolv: Path,
    nsswitch: Path,
    stage: Path,
    isolated: Path,
    child_command: Sequence[str],
) -> tuple[str, ...]:
    """Build the fail-closed, fixed-egress OpenCode bootstrap sandbox."""

    if not child_command:
        raise OpenCodeBootstrapError("The OpenCode bootstrap command is empty.")
    for directory in (
        stage / "data", stage / "cache", stage / "state",
        isolated / "home", isolated / "config", isolated / "tmp",
        isolated / "workspace", socket_path.parent,
    ):
        _require_directory(directory, exact_mode=0o700)
    for source in (opencode, bridge_source, hosts, resolv, nsswitch):
        _require_regular_security_source(source)
    arguments: list[str] = [
        str(bubblewrap),
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/lib", "/lib",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/home",
        "--bind", str(isolated / "home"), "/home/tori-bootstrap",
        "--bind", str(isolated / "config"), "/config",
        "--bind", str(stage / "data"), "/state/data",
        "--bind", str(stage / "cache"), "/state/cache",
        "--bind", str(stage / "state"), "/state/state",
        "--bind", str(isolated / "tmp"), "/bootstrap-tmp",
        "--ro-bind", str(isolated / "workspace"), "/workspace",
        "--dir", "/harness",
        "--ro-bind", str(opencode), "/harness/opencode",
        "--ro-bind", str(bridge_source), "/harness/bootstrap_transport.py",
        "--ro-bind", str(socket_path.parent), "/harness/ipc",
        "--dir", "/etc",
        "--ro-bind", str(hosts), "/etc/hosts",
        "--ro-bind", str(resolv), "/etc/resolv.conf",
        "--ro-bind", str(nsswitch), "/etc/nsswitch.conf",
        "--setenv", "HOME", "/home/tori-bootstrap",
        "--setenv", "XDG_CONFIG_HOME", "/config",
        "--setenv", "XDG_DATA_HOME", "/state/data",
        "--setenv", "XDG_CACHE_HOME", "/state/cache",
        "--setenv", "XDG_STATE_HOME", "/state/state",
        "--setenv", "TMPDIR", "/bootstrap-tmp",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--setenv", "OPENCODE_DISABLE_AUTOUPDATE", "true",
        "--setenv", "OPENCODE_MODELS_URL", BOOTSTRAP_MODELS_URL,
    ]
    if Path("/usr/lib64").exists():
        arguments.extend(("--symlink", "usr/lib64", "/lib64"))
    ca_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    if not ca_bundle.is_file() or ca_bundle.is_symlink():
        raise OpenCodeBootstrapError("The host TLS trust bundle is unavailable or unsafe.")
    arguments.extend((
        "--dir", "/etc/ssl",
        "--dir", "/etc/ssl/certs",
        "--ro-bind", str(ca_bundle), "/etc/ssl/certs/ca-certificates.crt",
        "--chdir", "/workspace",
        "--",
        "/usr/bin/python3", "/harness/bootstrap_transport.py",
        "--unix-socket", "/harness/ipc/bootstrap-egress.sock",
        "--",
        *child_command,
    ))
    return tuple(arguments)
