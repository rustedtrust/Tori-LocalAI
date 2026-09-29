"""Bounded supervision for one explicitly authorized local command."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
from pathlib import Path
import secrets
import shutil
import shlex
import signal
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from .execution_policy import (
    ExecutionPolicyService, ExecutionRequest, ExecutionScope, PolicyError,
)


MAX_COMMAND_CHARACTERS = 2_000
MAX_OUTPUT_BYTES = 64 * 1024
COMMAND_TIMEOUT_SECONDS = 30.0
TERMINATION_GRACE_SECONDS = 1.0
SANITIZED_PATH = "/usr/local/bin:/usr/bin:/bin"


class CommandStatus(str, Enum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    STOPPED = "stopped"
    REJECTED = "rejected"


class CommandExecutionError(RuntimeError):
    """A safe command-service failure with a stable application code."""

    def __init__(self, message: str, *, code: str = "command_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CommandBounds:
    timeout_seconds: float = COMMAND_TIMEOUT_SECONDS
    stdout_bytes: int = MAX_OUTPUT_BYTES
    stderr_bytes: int = MAX_OUTPUT_BYTES


@dataclass(frozen=True, slots=True)
class SandboxAvailability:
    available: bool
    name: str
    isolation: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    invocation_id: str
    command: str
    workspace: str
    status: str
    exit_code: int | None
    termination_reason: str | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_seconds: float
    isolation: str
    timeout_seconds: float
    stdout_limit_bytes: int
    stderr_limit_bytes: int

    def document(self) -> dict[str, object]:
        return asdict(self)


class CommandSandbox(Protocol):
    """Internal command-launch boundary; never supplied through action arguments."""

    def availability(self, workspace: Path) -> SandboxAvailability: ...

    def argv(self, command: str, workspace: Path) -> Sequence[str]: ...


class BubblewrapSandbox:
    """Native Bubblewrap boundary with a private network and process namespace."""

    name = "bubblewrap"

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or shutil.which("bwrap")

    def availability(self, workspace: Path) -> SandboxAvailability:
        if self._executable is None:
            return SandboxAvailability(
                False, self.name, "disabled", "Bubblewrap is not installed."
            )
        try:
            with TemporaryDirectory(prefix="tori-command-probe-") as temporary:
                probe_root = Path(temporary)
                probe_workspace = probe_root / "workspace"
                probe_workspace.mkdir()
                (probe_workspace / "inside-sentinel").write_text(
                    "inside-only\n", encoding="utf-8"
                )
                outside = probe_root / "outside-sentinel"
                outside.write_text("must-not-be-visible\n", encoding="utf-8")
                probe = " && ".join((
                    "test \"$(cat /workspace/inside-sentinel)\" = inside-only",
                    f"test ! -e {shlex.quote(str(outside))}",
                    f"test ! -e {shlex.quote(str(Path(__file__).resolve().parents[2].parent))}",
                    "test ! -e /var/run/docker.sock",
                    "test ! -e /run/docker.sock",
                ))
                completed = subprocess.run(
                    self.argv(probe, probe_workspace),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    env=sanitized_environment(),
                    timeout=5,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError):
            return SandboxAvailability(
                False, self.name, "disabled", "Bubblewrap could not be started safely."
            )
        if completed.returncode != 0:
            return SandboxAvailability(
                False,
                self.name,
                "disabled",
                "Native namespace isolation is unavailable to this process.",
            )
        return SandboxAvailability(
            True,
            self.name,
            "Bubblewrap: private filesystem, PID, IPC, UTS, cgroup, and network namespaces",
        )

    def argv(self, command: str, workspace: Path) -> Sequence[str]:
        if self._executable is None:
            raise CommandExecutionError(
                "Command execution is disabled because Bubblewrap is unavailable.",
                code="isolation_unavailable",
            )
        workspace = workspace.resolve(strict=True)
        arguments = [
            self._executable,
            "--die-with-parent",
            "--unshare-all",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--dir", "/tmp/tori-home",
            "--bind", str(workspace), "/workspace",
        ]
        if Path("/usr/lib64").exists():
            arguments.extend(("--symlink", "usr/lib64", "/lib64"))
        # Canonical Tori runtime is never the command's real runtime tree.
        runtime_path = workspace / "runtime"
        if runtime_path.is_symlink() or (
            runtime_path.exists() and not runtime_path.is_dir()
        ):
            raise CommandExecutionError(
                "The protected runtime mount point is unsafe.",
                code="isolation_unavailable",
            )
        if runtime_path.exists():
            arguments.extend(("--tmpfs", "/workspace/runtime"))
        arguments.extend(("--chdir", "/workspace", "/bin/sh", "-c", command))
        return arguments


def sanitized_environment() -> Mapping[str, str]:
    """Return the complete fixed environment inherited by a command process."""

    return MappingProxyType({
        "HOME": "/tmp/tori-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": SANITIZED_PATH,
        "SHELL": "/bin/sh",
        "TMPDIR": "/tmp",
    })


class _BoundedCapture:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._data = bytearray()
        self.truncated = False

    def drain(self, stream: object) -> None:
        read = getattr(stream, "read")
        while True:
            chunk = read(8192)
            if not chunk:
                return
            remaining = self._limit - len(self._data)
            if remaining > 0:
                self._data.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True

    def text(self) -> str:
        return self._data.decode("utf-8", errors="replace")


@dataclass(slots=True)
class _ActiveProcess:
    invocation_id: str
    process: subprocess.Popen[bytes]
    stop_requested: bool = False


class CommandExecutionService:
    """Own, supervise, bound, and stop at most one Tori command process group."""

    def __init__(
        self,
        workspace: Path,
        *,
        sandbox: CommandSandbox | None = None,
        bounds: CommandBounds = CommandBounds(),
        policy: ExecutionPolicyService | None = None,
    ) -> None:
        resolved = workspace.resolve(strict=True)
        if not resolved.is_dir():
            raise CommandExecutionError("The authorized workspace is unavailable.")
        self.workspace = resolved
        self.bounds = bounds
        self.policy = policy
        self._sandbox = sandbox or BubblewrapSandbox()
        self.availability = self._sandbox.availability(resolved)
        self._lock = threading.Lock()
        self._active: _ActiveProcess | None = None
        self._state: dict[str, object] | None = None

    def proposal(self, command: str, invocation_id: str) -> dict[str, object]:
        return {
            "invocation_id": invocation_id,
            "command": command,
            "workspace": str(self.workspace),
            "status": CommandStatus.PROPOSED.value,
            "environment": "sanitized application-owned environment",
            "isolation": self.availability.isolation,
            "isolation_available": self.availability.available,
            "isolation_reason": self.availability.reason,
            "timeout_seconds": self.bounds.timeout_seconds,
            "stdout_limit_bytes": self.bounds.stdout_bytes,
            "stderr_limit_bytes": self.bounds.stderr_bytes,
        }

    def state(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._state) if self._state is not None else None

    def execute(
        self, command: str, workspace: str, invocation_id: str, *,
        grant_token: str | None = None, grant_owner: str | None = None,
    ) -> Mapping[str, object]:
        """Retired general runner: only the local terminal broker may launch."""
        raise CommandExecutionError(
            "The legacy general command runner is retired; use the local terminal broker.",
            code="legacy_command_retired",
        )

    def stop(self, invocation_id: str | None = None) -> bool:
        with self._lock:
            active = self._active
            if active is None or (
                invocation_id is not None
                and not secrets.compare_digest(active.invocation_id, invocation_id)
            ):
                return False
            active.stop_requested = True
            process = active.process
        self._terminate_group(process)
        return True

    @staticmethod
    def _terminate_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass
