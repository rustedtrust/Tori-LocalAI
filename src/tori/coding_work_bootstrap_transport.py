"""Fixed-destination raw TLS transport for explicit OpenCode bootstrap.

The sandbox-facing process can reach only one Unix socket through a loopback
listener in its private network namespace.  The host relay always selects the
single compiled destination below; no protocol field or caller argument can
choose another host or port.  TLS remains end-to-end between OpenCode and the
fixed upstream.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
from typing import Final, Sequence


BOOTSTRAP_UPSTREAM_HOST: Final = "models.opencode.ai"
BOOTSTRAP_UPSTREAM_PORT: Final = 443
BOOTSTRAP_LOOPBACK_ADDRESS: Final = "127.0.0.1"
BOOTSTRAP_LOOPBACK_PORT: Final = 11_443
BOOTSTRAP_MODELS_URL: Final = (
    f"https://{BOOTSTRAP_UPSTREAM_HOST}:{BOOTSTRAP_LOOPBACK_PORT}"
)


class BootstrapEgressError(RuntimeError):
    """Bounded, payload-free bootstrap transport failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class BootstrapEgressBounds:
    max_connections: int = 8
    max_concurrent_connections: int = 2
    max_bytes_each_direction: int = 32 * 1024 * 1024
    connection_timeout_seconds: float = 30.0
    relay_lifetime_seconds: float = 120.0
    audit_entries: int = 16

    def __post_init__(self) -> None:
        integer_values = (
            self.max_connections,
            self.max_concurrent_connections,
            self.max_bytes_each_direction,
            self.audit_entries,
        )
        if any(isinstance(value, bool) or value < 1 for value in integer_values):
            raise ValueError("Bootstrap egress bounds must be positive integers.")
        if self.max_concurrent_connections > self.max_connections:
            raise ValueError("Bootstrap egress concurrency exceeds its connection bound.")
        if self.connection_timeout_seconds <= 0 or self.relay_lifetime_seconds <= 0:
            raise ValueError("Bootstrap egress time bounds must be positive.")


@dataclass(frozen=True, slots=True)
class BootstrapEgressAudit:
    destination_host: str
    destination_port: int
    inbound_bytes: int
    outbound_bytes: int
    outcome: str


class FixedOpenCodeBootstrapRelay:
    """Host Unix-socket relay with one non-configurable HTTPS destination."""

    def __init__(
        self,
        socket_path: Path,
        *,
        bounds: BootstrapEgressBounds = BootstrapEgressBounds(),
    ) -> None:
        self.socket_path = Path(socket_path)
        self.bounds = bounds
        self._admission = threading.BoundedSemaphore(bounds.max_concurrent_connections)
        self._audit: deque[BootstrapEgressAudit] = deque(maxlen=bounds.audit_entries)
        self._lock = threading.Lock()
        self._accepted = 0
        self._started_at = 0.0
        self._server: _BootstrapUnixServer | None = None
        self._thread: threading.Thread | None = None
        self._socket_identity: tuple[int, int] | None = None

    @property
    def destination(self) -> tuple[str, int]:
        return BOOTSTRAP_UPSTREAM_HOST, BOOTSTRAP_UPSTREAM_PORT

    @property
    def audit(self) -> tuple[BootstrapEgressAudit, ...]:
        with self._lock:
            return tuple(self._audit)

    def start(self) -> None:
        if self._server is not None:
            raise BootstrapEgressError(
                "The OpenCode bootstrap relay is already running.", code="already_running"
            )
        _validate_socket_parent(self.socket_path.parent)
        if os.path.lexists(self.socket_path):
            raise BootstrapEgressError(
                "The OpenCode bootstrap relay socket path already exists.",
                code="unsafe_socket_path",
            )
        try:
            preflight = self._connect_fixed_upstream()
        except (OSError, TimeoutError) as exc:
            raise BootstrapEgressError(
                "The fixed OpenCode bootstrap destination is unavailable.",
                code="upstream_unavailable",
            ) from exc
        else:
            preflight.close()
            self._record(0, 0, "preflight_success")
        created_identity: tuple[int, int] | None = None
        try:
            server = _BootstrapUnixServer(str(self.socket_path), _BootstrapUnixHandler)
            server.relay = self
            metadata = os.lstat(self.socket_path)
            created_identity = (metadata.st_dev, metadata.st_ino)
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise BootstrapEgressError(
                    "The OpenCode bootstrap relay socket is unsafe.",
                    code="unsafe_socket_path",
                )
            os.chmod(self.socket_path, 0o600)
        except Exception:
            if "server" in locals():
                server.server_close()
            if created_identity is not None:
                try:
                    current = os.lstat(self.socket_path)
                except FileNotFoundError:
                    current = None
                if (
                    current is not None
                    and stat.S_ISSOCK(current.st_mode)
                    and (current.st_dev, current.st_ino) == created_identity
                ):
                    self.socket_path.unlink()
            raise
        identity = (metadata.st_dev, metadata.st_ino)
        thread = threading.Thread(
            target=server.serve_forever,
            name="tori-opencode-bootstrap-relay",
            daemon=True,
        )
        started_at = time.monotonic()
        self._started_at = started_at
        try:
            thread.start()
        except RuntimeError as exc:
            server.server_close()
            current = os.lstat(self.socket_path)
            if stat.S_ISSOCK(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                self.socket_path.unlink()
            raise BootstrapEgressError(
                "The OpenCode bootstrap relay could not start.", code="start_failed"
            ) from exc
        self._socket_identity = identity
        self._server = server
        self._thread = thread

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        identity = self._socket_identity
        self._socket_identity = None
        if identity is not None:
            try:
                metadata = os.lstat(self.socket_path)
            except FileNotFoundError:
                return
            if stat.S_ISSOCK(metadata.st_mode) and (metadata.st_dev, metadata.st_ino) == identity:
                self.socket_path.unlink()

    def __enter__(self) -> "FixedOpenCodeBootstrapRelay":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _connect_fixed_upstream(self) -> socket.socket:
        return socket.create_connection(
            (BOOTSTRAP_UPSTREAM_HOST, BOOTSTRAP_UPSTREAM_PORT),
            timeout=self.bounds.connection_timeout_seconds,
        )

    def _handle(self, client: socket.socket) -> None:
        with self._lock:
            lifetime_expired = (
                time.monotonic() - self._started_at
                >= self.bounds.relay_lifetime_seconds
            )
            if lifetime_expired or self._accepted >= self.bounds.max_connections:
                outcome = "rejected:lifetime" if lifetime_expired else "rejected:connection_limit"
                self._audit.append(self._audit_item(0, 0, outcome))
                return
            self._accepted += 1
        if not self._admission.acquire(blocking=False):
            self._record(0, 0, "rejected:concurrency_limit")
            return
        upstream: socket.socket | None = None
        try:
            upstream = self._connect_fixed_upstream()
            inbound, outbound, outcome = _relay_raw(
                client,
                upstream,
                byte_limit=self.bounds.max_bytes_each_direction,
                timeout_seconds=self.bounds.connection_timeout_seconds,
            )
            self._record(inbound, outbound, outcome)
        except (OSError, TimeoutError):
            self._record(0, 0, "failed:upstream_unavailable")
        finally:
            if upstream is not None:
                upstream.close()
            self._admission.release()

    def _audit_item(self, inbound: int, outbound: int, outcome: str) -> BootstrapEgressAudit:
        return BootstrapEgressAudit(
            BOOTSTRAP_UPSTREAM_HOST,
            BOOTSTRAP_UPSTREAM_PORT,
            inbound,
            outbound,
            outcome,
        )

    def _record(self, inbound: int, outbound: int, outcome: str) -> None:
        with self._lock:
            self._audit.append(self._audit_item(inbound, outbound, outcome))


class _BootstrapUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False
    relay: FixedOpenCodeBootstrapRelay


class _BootstrapUnixHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.relay._handle(self.request)  # type: ignore[attr-defined]


class BootstrapLoopbackBridge:
    """Sandbox-local fixed-port bridge to the protected Unix socket."""

    def __init__(self, unix_socket: Path, *, _test_port: int | None = None) -> None:
        self.unix_socket = Path(unix_socket)
        port = BOOTSTRAP_LOOPBACK_PORT if _test_port is None else _test_port
        if isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("The bootstrap loopback test port is invalid.")
        self._server = _BootstrapLoopbackServer(
            (BOOTSTRAP_LOOPBACK_ADDRESS, port), _BootstrapLoopbackHandler
        )
        self._server.unix_socket = str(self.unix_socket)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._thread is not None:
            raise BootstrapEgressError(
                "The OpenCode bootstrap loopback bridge is already running.",
                code="already_running",
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="tori-opencode-bootstrap-loopback",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None:
            self._server.shutdown()
        self._server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def __enter__(self) -> "BootstrapLoopbackBridge":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _BootstrapLoopbackServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False
    unix_socket: str


class _BootstrapLoopbackHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.settimeout(30.0)
            upstream.connect(self.server.unix_socket)  # type: ignore[attr-defined]
            _relay_raw(self.request, upstream, byte_limit=32 * 1024 * 1024, timeout_seconds=30.0)
        except OSError:
            return
        finally:
            upstream.close()


def _relay_raw(
    first: socket.socket,
    second: socket.socket,
    *,
    byte_limit: int,
    timeout_seconds: float,
) -> tuple[int, int, str]:
    """Copy bytes in both directions without retaining payload content."""

    deadline = time.monotonic() + timeout_seconds
    stop = threading.Event()
    counts = [0, 0]
    failures: list[str] = []
    lock = threading.Lock()

    def copy(source: socket.socket, destination: socket.socket, index: int) -> None:
        source.settimeout(min(0.5, timeout_seconds))
        try:
            while not stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError
                try:
                    chunk = source.recv(64 * 1024)
                except socket.timeout:
                    continue
                if not chunk:
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    return
                with lock:
                    counts[index] += len(chunk)
                    if counts[index] > byte_limit:
                        failures.append("byte_limit")
                        stop.set()
                        return
                destination.sendall(chunk)
        except TimeoutError:
            with lock:
                failures.append("timeout")
            stop.set()
        except OSError:
            with lock:
                failures.append("transport_error")
            stop.set()

    threads = (
        threading.Thread(target=copy, args=(first, second, 0), daemon=True),
        threading.Thread(target=copy, args=(second, first, 1), daemon=True),
    )
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()) + 0.1)
    if any(thread.is_alive() for thread in threads):
        failures.append("timeout")
        stop.set()
        for connection in (first, second):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in threads:
            thread.join(timeout=1)
    outcome = "success" if not failures else "failed:" + failures[0]
    return counts[0], counts[1], outcome


def _validate_socket_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
    except FileNotFoundError as exc:
        raise BootstrapEgressError(
            "The OpenCode bootstrap relay parent is unavailable.",
            code="unsafe_socket_path",
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise BootstrapEgressError(
            "The OpenCode bootstrap relay parent is unsafe.", code="unsafe_socket_path"
        )


def run_bootstrap_bridge_command(unix_socket: Path, command: Sequence[str]) -> int:
    if not command:
        raise ValueError("A bootstrap child command is required.")
    with BootstrapLoopbackBridge(unix_socket):
        completed = subprocess.run(tuple(command), check=False)
    return completed.returncode


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unix-socket", required=True, type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = list(arguments.command)
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a child command is required after --")
    return run_bootstrap_bridge_command(arguments.unix_socket, command)


if __name__ == "__main__":
    sys.exit(_main())
