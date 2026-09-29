"""Narrow provider transport for a network-isolated coding worker.

This is intentionally not a general HTTP proxy.  A sandbox may submit one
OpenAI-compatible chat-completions operation through a Unix socket.  The host
side always selects the configured upstream and never forwards sandbox
credentials or destination headers.
"""

from __future__ import annotations

from collections import deque
import argparse
from dataclasses import dataclass
import http.client
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import subprocess
import tempfile
import threading
from typing import Final


CHAT_COMPLETIONS_PATH: Final = "/v1/chat/completions"
MAX_HEADER_BYTES: Final = 32 * 1024
MAX_HEADER_LINE_BYTES: Final = 8 * 1024
DEFAULT_MAX_CONCURRENT_REQUESTS: Final = 2


class ProviderTransportError(RuntimeError):
    """Safe, bounded provider-transport failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OpenAICompatibleInferencePolicy:
    """Immutable fixed-upstream policy for one approved model."""

    upstream_host: str
    upstream_port: int
    model: str
    max_request_bytes: int = 2 * 1024 * 1024
    max_response_bytes: int = 16 * 1024 * 1024
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.upstream_host not in {"127.0.0.1", "::1"}:
            raise ValueError("The first provider relay proof requires a loopback upstream.")
        if isinstance(self.upstream_port, bool) or not 1 <= self.upstream_port <= 65535:
            raise ValueError("The provider upstream port is invalid.")
        if not self.model or len(self.model) > 200:
            raise ValueError("The approved provider model is invalid.")
        if self.max_request_bytes < 1 or self.max_response_bytes < 1:
            raise ValueError("Provider relay byte limits must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("The provider relay timeout must be positive.")


@dataclass(frozen=True, slots=True)
class ProviderRelayAudit:
    method: str
    path: str
    outcome: str
    request_bytes: int
    response_bytes: int


class _RejectedRequest(Exception):
    def __init__(self, status: int, code: str, method: str = "", path: str = "") -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.method = method
        self.path = path


class NarrowOpenAIProviderRelay:
    """Fixed-destination Unix-socket relay for chat completions only."""

    def __init__(
        self,
        socket_path: Path,
        policy: OpenAICompatibleInferencePolicy,
        *,
        audit_limit: int = 128,
        ownership_token: str | None = None,
        max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
    ) -> None:
        if audit_limit < 1:
            raise ValueError("The provider relay audit bound must be positive.")
        if ownership_token is not None and (
            not isinstance(ownership_token, str)
            or not 16 <= len(ownership_token) <= 256
            or any(character not in "0123456789abcdef" for character in ownership_token)
        ):
            raise ValueError("The provider relay ownership token is invalid.")
        if (
            isinstance(max_concurrent_requests, bool)
            or not isinstance(max_concurrent_requests, int)
            or max_concurrent_requests < 1
        ):
            raise ValueError("The provider relay concurrency bound is invalid.")
        self.socket_path = socket_path
        self.policy = policy
        self._ownership_token = ownership_token
        self._owner_path = socket_path.with_name(socket_path.name + ".owner")
        self._admission = threading.BoundedSemaphore(max_concurrent_requests)
        self._active_condition = threading.Condition()
        self._active_requests = 0
        self._audit: deque[ProviderRelayAudit] = deque(maxlen=audit_limit)
        self._audit_lock = threading.Lock()
        self._server: _ProviderUnixServer | None = None
        self._thread: threading.Thread | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._parent_identity: tuple[int, int] | None = None
        self._owner_identity: tuple[int, int] | None = None

    @property
    def audit(self) -> tuple[ProviderRelayAudit, ...]:
        with self._audit_lock:
            return tuple(self._audit)

    def start(self) -> None:
        if self._server is not None:
            raise ProviderTransportError("The provider relay is already running.", code="already_running")
        parent_stat = self._safe_parent_metadata()
        self._ensure_owner_marker()
        self._recover_owned_stale_socket()
        current_parent = self._safe_parent_metadata()
        if (current_parent.st_dev, current_parent.st_ino) != (
            parent_stat.st_dev, parent_stat.st_ino
        ):
            raise ProviderTransportError(
                "The provider relay socket parent changed.", code="unsafe_socket_path"
            )
        server = _ProviderUnixServer(str(self.socket_path), _ProviderUnixHandler)
        server.relay = self
        socket_stat = os.lstat(self.socket_path)
        if not stat.S_ISSOCK(socket_stat.st_mode):
            server.server_close()
            raise ProviderTransportError("The provider relay socket is unsafe.", code="unsafe_socket_path")
        os.chmod(self.socket_path, 0o600)
        socket_stat = os.lstat(self.socket_path)
        current_parent = self._safe_parent_metadata()
        if (current_parent.st_dev, current_parent.st_ino) != (
            parent_stat.st_dev, parent_stat.st_ino
        ):
            server.server_close()
            raise ProviderTransportError(
                "The provider relay socket parent changed.", code="unsafe_socket_path"
            )
        self._parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        if self._ownership_token is not None:
            owner_stat, owner_token = _read_owner_marker(self._owner_path)
            if owner_stat.st_uid != os.geteuid() or owner_token != self._ownership_token:
                server.server_close()
                raise ProviderTransportError(
                    "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
                )
            self._owner_identity = (owner_stat.st_dev, owner_stat.st_ino)
        self._socket_identity = (socket_stat.st_dev, socket_stat.st_ino)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="tori-provider-relay",
            daemon=True,
        )
        self._thread.start()

    def recover_stale(self) -> None:
        """Remove only a proven stale socket created by this Tori instance."""

        self._safe_parent_metadata()
        self._recover_owned_stale_socket()

    def _safe_parent_metadata(self) -> os.stat_result:
        try:
            parent_stat = os.lstat(self.socket_path.parent)
        except FileNotFoundError as exc:
            raise ProviderTransportError(
                "The provider relay socket parent is unavailable.", code="unsafe_socket_path"
            ) from exc
        if (
            stat.S_ISLNK(parent_stat.st_mode)
            or not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) & 0o077
        ):
            raise ProviderTransportError(
                "The provider relay socket parent is unsafe.", code="unsafe_socket_path"
            )
        return parent_stat

    def _ensure_owner_marker(self) -> None:
        if self._ownership_token is None:
            return
        try:
            _metadata, token = _read_owner_marker(self._owner_path)
        except ProviderTransportError:
            try:
                existing = os.lstat(self._owner_path)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                raise
            payload = json.dumps(
                {"schema": 1, "token": self._ownership_token},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            try:
                descriptor = os.open(
                    self._owner_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise ProviderTransportError(
                    "The provider relay socket provenance could not be created.",
                    code="unsafe_socket_path",
                ) from exc
            return
        if token != self._ownership_token:
            raise ProviderTransportError(
                "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
            )

    def _recover_owned_stale_socket(self) -> None:
        try:
            socket_stat = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        if (
            self._ownership_token is None
            or not stat.S_ISSOCK(socket_stat.st_mode)
            or socket_stat.st_uid != os.geteuid()
            or stat.S_IMODE(socket_stat.st_mode) != 0o600
            or socket_stat.st_nlink != 1
        ):
            raise ProviderTransportError(
                "The provider relay socket path already exists.", code="unsafe_socket_path"
            )
        marker_stat, marker_token = _read_owner_marker(self._owner_path)
        if marker_stat.st_uid != os.geteuid() or marker_token != self._ownership_token:
            raise ProviderTransportError(
                "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
            )
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            probe.connect(str(self.socket_path))
        except (ConnectionRefusedError, FileNotFoundError):
            pass
        except OSError as exc:
            raise ProviderTransportError(
                "The provider relay socket could not be proven stale.", code="unsafe_socket_path"
            ) from exc
        else:
            raise ProviderTransportError(
                "The provider relay socket is already active.", code="already_running"
            )
        finally:
            probe.close()
        current_socket = os.lstat(self.socket_path)
        current_marker = os.lstat(self._owner_path)
        if (
            (current_socket.st_dev, current_socket.st_ino)
            != (socket_stat.st_dev, socket_stat.st_ino)
            or (current_marker.st_dev, current_marker.st_ino)
            != (marker_stat.st_dev, marker_stat.st_ino)
        ):
            raise ProviderTransportError(
                "The provider relay socket changed during recovery.", code="unsafe_socket_path"
            )
        self.socket_path.unlink()

    def close(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise ProviderTransportError(
                    "The provider relay did not stop safely.", code="provider_shutdown_failed"
                )
        with self._active_condition:
            if not self._active_condition.wait_for(
                lambda: self._active_requests == 0, timeout=5
            ):
                raise ProviderTransportError(
                    "A provider request did not stop safely.", code="provider_shutdown_failed"
                )
        self._remove_owned_socket()

    def __enter__(self) -> "NarrowOpenAIProviderRelay":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _remove_owned_socket(self) -> None:
        identity = self._socket_identity
        if identity is None:
            return
        try:
            current = os.lstat(self.socket_path)
        except FileNotFoundError:
            self._socket_identity = None
            self._parent_identity = None
            self._owner_identity = None
            return
        parent = self._safe_parent_metadata()
        owner_identity = self._owner_identity
        owner_safe = True
        if self._ownership_token is not None:
            owner_stat, owner_token = _read_owner_marker(self._owner_path)
            owner_safe = (
                owner_identity is not None
                and (owner_stat.st_dev, owner_stat.st_ino) == owner_identity
                and owner_stat.st_uid == os.geteuid()
                and owner_token == self._ownership_token
            )
        if (
            self._parent_identity is None
            or (parent.st_dev, parent.st_ino) != self._parent_identity
            or (current.st_dev, current.st_ino) != identity
            or not stat.S_ISSOCK(current.st_mode)
            or current.st_uid != os.geteuid()
            or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_nlink != 1
            or not owner_safe
        ):
            raise ProviderTransportError(
                "The provider relay socket changed before cleanup.", code="unsafe_socket_path"
            )
        self.socket_path.unlink()
        self._socket_identity = None
        self._parent_identity = None
        self._owner_identity = None

    def _record(self, item: ProviderRelayAudit) -> None:
        with self._audit_lock:
            self._audit.append(item)

    def _handle(self, client: socket.socket) -> None:
        if not self._admission.acquire(blocking=False):
            _write_error(client, 503, "concurrency_limit")
            self._record(ProviderRelayAudit("", "", "rejected:concurrency_limit", 0, 0))
            return
        with self._active_condition:
            self._active_requests += 1
        try:
            self._handle_admitted(client)
        finally:
            with self._active_condition:
                self._active_requests -= 1
                self._active_condition.notify_all()
            self._admission.release()

    def _handle_admitted(self, client: socket.socket) -> None:
        client.settimeout(self.policy.timeout_seconds)
        method = ""
        path = ""
        request_size = 0
        try:
            method, path, headers, body, request_size = _read_request(
                client, self.policy.max_request_bytes
            )
            _validate_request(method, path, headers, body, self.policy)
            response_size = self._forward(client, body)
            self._record(
                ProviderRelayAudit(method, path, "allowed", request_size, response_size)
            )
        except _RejectedRequest as error:
            method = error.method or method
            path = error.path or path
            _write_error(client, error.status, error.code)
            self._record(
                ProviderRelayAudit(method, path, "rejected:" + error.code, request_size, 0)
            )
        except (OSError, http.client.HTTPException, TimeoutError):
            _write_error(client, 502, "upstream_unavailable")
            self._record(
                ProviderRelayAudit(method, path, "failed:upstream_unavailable", request_size, 0)
            )

    def _forward(self, client: socket.socket, body: bytes) -> int:
        connection = http.client.HTTPConnection(
            self.policy.upstream_host,
            self.policy.upstream_port,
            timeout=self.policy.timeout_seconds,
        )
        response_bytes = 0
        try:
            connection.request(
                "POST",
                CHAT_COMPLETIONS_PATH,
                body=body,
                headers={
                    "Accept": "text/event-stream, application/json",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            content_type = response.getheader("Content-Type", "application/json")
            if "\r" in content_type or "\n" in content_type or len(content_type) > 200:
                content_type = "application/octet-stream"
            with tempfile.SpooledTemporaryFile(max_size=min(self.policy.max_response_bytes, 1024 * 1024)) as buffered:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    response_bytes += len(chunk)
                    if response_bytes > self.policy.max_response_bytes:
                        raise _RejectedRequest(
                            502, "response_too_large", "POST", CHAT_COMPLETIONS_PATH
                        )
                    buffered.write(chunk)
                status_line = f"HTTP/1.1 {response.status} {response.reason}\r\n"
                client.sendall(
                    status_line.encode("ascii", errors="replace")
                    + (
                        f"Content-Type: {content_type}\r\n"
                        f"Content-Length: {response_bytes}\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                )
                buffered.seek(0)
                while True:
                    chunk = buffered.read(64 * 1024)
                    if not chunk:
                        break
                    client.sendall(chunk)
            return response_bytes
        finally:
            connection.close()


class _ProviderUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False
    relay: NarrowOpenAIProviderRelay


class _ProviderUnixHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.server.relay._handle(self.request)  # type: ignore[attr-defined]


def _read_request(
    client: socket.socket, max_request_bytes: int
) -> tuple[str, str, dict[str, str], bytes, int]:
    stream = client.makefile("rb", buffering=0)
    request_line = stream.readline(MAX_HEADER_LINE_BYTES + 1)
    if not request_line or len(request_line) > MAX_HEADER_LINE_BYTES:
        raise _RejectedRequest(400, "malformed_request")
    try:
        method, path, version = request_line.decode("ascii").strip().split(" ")
    except (UnicodeDecodeError, ValueError):
        raise _RejectedRequest(400, "malformed_request") from None
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise _RejectedRequest(400, "unsupported_http_version", method, path)
    header_bytes = len(request_line)
    headers: dict[str, str] = {}
    while True:
        line = stream.readline(MAX_HEADER_LINE_BYTES + 1)
        header_bytes += len(line)
        if len(line) > MAX_HEADER_LINE_BYTES or header_bytes > MAX_HEADER_BYTES:
            raise _RejectedRequest(431, "headers_too_large", method, path)
        if line in {b"\r\n", b"\n"}:
            break
        if not line or b":" not in line:
            raise _RejectedRequest(400, "malformed_headers", method, path)
        name, value = line.split(b":", 1)
        try:
            key = name.decode("ascii").strip().lower()
            text = value.decode("ascii").strip()
        except UnicodeDecodeError:
            raise _RejectedRequest(400, "malformed_headers", method, path) from None
        if key in headers:
            raise _RejectedRequest(400, "duplicate_header", method, path)
        headers[key] = text
    if method != "POST":
        raise _RejectedRequest(405, "method_denied", method, path)
    if path != CHAT_COMPLETIONS_PATH:
        raise _RejectedRequest(403, "path_denied", method, path)
    if "transfer-encoding" in headers:
        raise _RejectedRequest(400, "transfer_encoding_denied", method, path)
    try:
        content_length = int(headers.get("content-length", "-1"))
    except ValueError:
        raise _RejectedRequest(400, "invalid_content_length", method, path) from None
    if content_length < 0:
        raise _RejectedRequest(411, "content_length_required", method, path)
    if content_length > max_request_bytes:
        raise _RejectedRequest(413, "request_too_large", method, path)
    chunks = bytearray()
    while len(chunks) < content_length:
        chunk = stream.read(content_length - len(chunks))
        if not chunk:
            raise _RejectedRequest(400, "incomplete_body", method, path)
        chunks.extend(chunk)
    body = bytes(chunks)
    return method, path, headers, body, header_bytes + len(body)


def _validate_request(
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    policy: OpenAICompatibleInferencePolicy,
) -> None:
    if method != "POST":
        raise _RejectedRequest(405, "method_denied", method, path)
    if path != CHAT_COMPLETIONS_PATH:
        raise _RejectedRequest(403, "path_denied", method, path)
    content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise _RejectedRequest(415, "content_type_denied", method, path)
    try:
        document = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _RejectedRequest(400, "invalid_json", method, path) from None
    if not isinstance(document, dict):
        raise _RejectedRequest(400, "invalid_document", method, path)
    if document.get("model") != policy.model:
        raise _RejectedRequest(403, "model_denied", method, path)
    if not isinstance(document.get("messages"), list):
        raise _RejectedRequest(400, "messages_required", method, path)


def _write_error(client: socket.socket, status: int, code: str) -> None:
    reasons = {400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed", 411: "Length Required", 413: "Payload Too Large", 415: "Unsupported Media Type", 431: "Request Header Fields Too Large", 502: "Bad Gateway", 503: "Service Unavailable"}
    body = json.dumps({"error": {"code": code}}, separators=(",", ":")).encode()
    response = (
        f"HTTP/1.1 {status} {reasons.get(status, 'Rejected')}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    try:
        client.sendall(response)
    except OSError:
        pass


def _read_owner_marker(path: Path) -> tuple[os.stat_result, str]:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError as exc:
        raise ProviderTransportError(
            "The provider relay socket provenance is missing.", code="unsafe_socket_path"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise ProviderTransportError(
            "The provider relay socket provenance is unsafe.", code="unsafe_socket_path"
        )
    if (
        metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise ProviderTransportError(
            "The provider relay socket provenance has the wrong owner.",
            code="unsafe_socket_path",
        )
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            payload = stream.read(1025)
    except OSError as exc:
        raise ProviderTransportError(
            "The provider relay socket provenance is unreadable.", code="unsafe_socket_path"
        ) from exc
    if len(payload) > 1024:
        raise ProviderTransportError(
            "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
        )
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderTransportError(
            "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
        ) from exc
    if not isinstance(document, dict) or set(document) != {"schema", "token"}:
        raise ProviderTransportError(
            "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
        )
    token = document.get("token")
    if document.get("schema") != 1 or not isinstance(token, str):
        raise ProviderTransportError(
            "The provider relay socket provenance is invalid.", code="unsafe_socket_path"
        )
    return metadata, token


class ProviderLoopbackBridge:
    """Expose one sandbox-loopback port and forward it only to a Unix socket."""

    def __init__(self, unix_socket: Path, *, port: int = 0) -> None:
        if isinstance(port, bool) or not 0 <= port <= 65535:
            raise ValueError("The provider loopback port is invalid.")
        self.unix_socket = unix_socket
        self._server = _LoopbackServer(("127.0.0.1", port), _LoopbackHandler)
        self._server.unix_socket = str(unix_socket)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._thread is not None:
            raise ProviderTransportError("The loopback bridge is already running.", code="already_running")
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="tori-provider-loopback",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        thread = self._thread
        self._thread = None
        self._server.shutdown()
        self._server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def __enter__(self) -> "ProviderLoopbackBridge":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _LoopbackServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False
    unix_socket: str


class _LoopbackHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.settimeout(130)
        try:
            upstream.connect(self.server.unix_socket)  # type: ignore[attr-defined]
            thread = threading.Thread(
                target=_copy_stream,
                args=(self.request, upstream),
                daemon=True,
            )
            thread.start()
            _copy_stream(upstream, self.request)
            thread.join(timeout=1)
        finally:
            upstream.close()


def _copy_stream(source: socket.socket, destination: socket.socket) -> None:
    try:
        while True:
            chunk = source.recv(64 * 1024)
            if not chunk:
                break
            destination.sendall(chunk)
    except OSError:
        pass
    try:
        destination.shutdown(socket.SHUT_WR)
    except OSError:
        pass


def run_loopback_bridge_command(
    unix_socket: Path, port: int, command: tuple[str, ...]
) -> int:
    """Run one worker command while its namespace-local provider bridge is live."""

    if not command:
        raise ValueError("A sandbox worker command is required.")
    with ProviderLoopbackBridge(unix_socket, port=port):
        if os.environ.get("TORI_PROVIDER_SECURITY_PROBE") == "1":
            _assert_sandbox_boundary(port)
        process = subprocess.Popen(command, umask=0o077)
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                return process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                return process.wait(timeout=5)


def _assert_sandbox_boundary(provider_port: int) -> None:
    for path in (Path(__file__).resolve().parents[2].parent, Path("/home")):
        if path.exists():
            raise ProviderTransportError(
                "The provider bridge can see a prohibited host path.",
                code="filesystem_isolation_failed",
            )
    forbidden_names = {
        "ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "SSH_AUTH_SOCK", "DOCKER_HOST", "OPENCODE_API_KEY",
    }
    for name in os.environ:
        upper = name.upper()
        if name in forbidden_names or any(token in upper for token in ("API_KEY", "SECRET", "TOKEN", "PASSWORD")):
            raise ProviderTransportError(
                "The provider bridge inherited a prohibited environment value.",
                code="environment_isolation_failed",
            )
    git_probe = Path("/workspace/.git/tori-provider-security-probe")
    try:
        descriptor = os.open(git_probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        pass
    else:
        os.close(descriptor)
        git_probe.unlink(missing_ok=True)
        raise ProviderTransportError(
            "The authoritative Git control state is writable.",
            code="git_isolation_failed",
        )
    host_port_text = os.environ.get("TORI_PROBE_HOST_PORT")
    if host_port_text:
        _require_unreachable("127.0.0.1", int(host_port_text))
    _require_unreachable("1.1.1.1", 80)
    connection = http.client.HTTPConnection("127.0.0.1", provider_port, timeout=2)
    try:
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        body = response.read(4096)
    finally:
        connection.close()
    if response.status != 405 or b"method_denied" not in body:
        raise ProviderTransportError(
            "The provider relay did not reject an administrative operation.",
            code="provider_allowlist_failed",
        )


def _require_unreachable(host: str, port: int) -> None:
    try:
        connection = socket.create_connection((host, port), timeout=0.3)
    except OSError:
        return
    connection.close()
    raise ProviderTransportError(
        "The provider bridge reached a prohibited network destination.",
        code="network_isolation_failed",
    )
def _main() -> int:
    parser = argparse.ArgumentParser(description="Tori narrow provider loopback bridge")
    parser.add_argument("--unix-socket", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = tuple(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    return run_loopback_bridge_command(arguments.unix_socket, arguments.port, command)


if __name__ == "__main__":
    raise SystemExit(_main())
