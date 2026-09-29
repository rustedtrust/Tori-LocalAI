"""Bounded local-stdio MCP interoperability behind Tori-owned authority.

This is deliberately a small client subset, not a general MCP framework.  It
implements the 2025-11-25 initialization path plus tools/list and tools/call,
which current MCP servers continue to support.  Server metadata is untrusted;
only application-registered definitions and explicitly approved schema
snapshots can become provider projections or invocations.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import stat
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Protocol

from .capabilities import CapabilityResult
from .request_origin import ConversationOperation, OriginAuthority, RequestOrigin
from .skills import SkillPermission


MCP_CLIENT_VERSION = "0.1.0"
MCP_PROTOCOL_VERSION = "2025-11-25"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024
MAX_STDERR_BYTES = 64 * 1024
MAX_TOOLS = 64
MAX_TEXT = 64 * 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_TOOL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:-]{0,126}[A-Za-z0-9])?\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class MCPError(RuntimeError):
    def __init__(self, message: str, *, code: str = "mcp_error") -> None:
        super().__init__(message)
        self.code = code


class MCPValidationError(MCPError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="mcp_invalid")


class MCPUnavailableError(MCPError):
    def __init__(self, message: str = "The approved MCP server is unavailable.") -> None:
        super().__init__(message, code="mcp_unavailable")


class MCPPermissionError(MCPError):
    def __init__(self, message: str = "That MCP tool is not approved.") -> None:
        super().__init__(message, code="mcp_permission_denied")


class MCPTimeoutError(MCPError):
    def __init__(self) -> None:
        super().__init__("The MCP operation timed out and the server was stopped.", code="mcp_timeout")


class MCPSecretProvider(Protocol):
    def resolve(self, handle: str) -> str: ...


@dataclass(frozen=True, slots=True)
class MCPServerDefinition:
    """Application-owned exact local launch and requested authority record."""

    server_id: str
    executable: str
    argv: tuple[str, ...]
    executable_digest: str
    server_version: str
    allowed_tools: tuple[str, ...]
    requested_permissions: tuple[SkillPermission, ...]
    credential_handle: str | None = None
    credential_environment: str | None = None
    transport: str = "stdio"
    display_name: str = "MCP server"
    expected_server_name: str | None = None
    sandbox_executable: str | None = None
    sandbox_executable_digest: str | None = None
    read_only_roots: tuple[str, ...] = ()
    network_access: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.server_id, str) or _ID.fullmatch(self.server_id) is None:
            raise MCPValidationError("MCP server identity is invalid.")
        path = Path(self.executable)
        if not path.is_absolute() or ".." in path.parts or str(path) != self.executable:
            raise MCPValidationError("MCP executable must be an exact absolute path.")
        if self.transport != "stdio":
            raise MCPValidationError("Only local stdio MCP transport is supported.")
        if not isinstance(self.argv, tuple) or len(self.argv) > 32:
            raise MCPValidationError("MCP fixed arguments are invalid.")
        for value in self.argv:
            _bounded_string(value, 1, 512, "MCP argument")
            if "\x00" in value:
                raise MCPValidationError("MCP fixed arguments are invalid.")
        if not isinstance(self.executable_digest, str) or _DIGEST.fullmatch(self.executable_digest) is None:
            raise MCPValidationError("MCP executable digest is invalid.")
        _bounded_string(self.server_version, 1, 128, "MCP server version")
        if (
            not isinstance(self.allowed_tools, tuple)
            or not self.allowed_tools
            or len(self.allowed_tools) > MAX_TOOLS
            or len(set(self.allowed_tools)) != len(self.allowed_tools)
            or any(not isinstance(name, str) or _TOOL.fullmatch(name) is None for name in self.allowed_tools)
        ):
            raise MCPValidationError("MCP tool allowlist is invalid.")
        if not isinstance(self.requested_permissions, tuple) or any(
            not isinstance(item, SkillPermission) for item in self.requested_permissions
        ):
            raise MCPValidationError("MCP requested permissions are invalid.")
        if (self.credential_handle is None) != (self.credential_environment is None):
            raise MCPValidationError("MCP credential binding is incomplete.")
        if self.credential_handle is not None:
            if _ID.fullmatch(self.credential_handle) is None:
                raise MCPValidationError("MCP credential handle is invalid.")
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", self.credential_environment or "") is None:
                raise MCPValidationError("MCP credential environment name is invalid.")
        _bounded_string(self.display_name, 1, 128, "MCP display name")
        if self.expected_server_name is not None:
            _bounded_string(self.expected_server_name, 1, 256, "MCP implementation name")
        if (self.sandbox_executable is None) != (self.sandbox_executable_digest is None):
            raise MCPValidationError("MCP sandbox identity is incomplete.")
        if self.sandbox_executable is not None:
            sandbox = Path(self.sandbox_executable)
            if not sandbox.is_absolute() or ".." in sandbox.parts or str(sandbox) != self.sandbox_executable:
                raise MCPValidationError("MCP sandbox executable must be an exact absolute path.")
            if _DIGEST.fullmatch(self.sandbox_executable_digest or "") is None:
                raise MCPValidationError("MCP sandbox executable digest is invalid.")
            if not self.read_only_roots:
                raise MCPValidationError("A sandboxed MCP server requires explicit read-only roots.")
        if not isinstance(self.read_only_roots, tuple) or len(self.read_only_roots) > 16:
            raise MCPValidationError("MCP read-only roots are invalid.")
        for root in self.read_only_roots:
            path = Path(root)
            if not path.is_absolute() or ".." in path.parts or str(path) != root:
                raise MCPValidationError("MCP read-only roots must be exact absolute paths.")
        if type(self.network_access) is not bool:
            raise MCPValidationError("MCP network policy is invalid.")

    @property
    def configuration_digest(self) -> str:
        return _digest({
            "server_id": self.server_id,
            "transport": self.transport,
            "executable": self.executable,
            "argv": list(self.argv),
            "executable_digest": self.executable_digest,
            "server_version": self.server_version,
            "allowed_tools": list(self.allowed_tools),
            "requested_permissions": [item.document() for item in self.requested_permissions],
            "credential_handle": self.credential_handle,
            "credential_environment": self.credential_environment,
            "display_name": self.display_name,
            "expected_server_name": self.expected_server_name,
            "sandbox_executable": self.sandbox_executable,
            "sandbox_executable_digest": self.sandbox_executable_digest,
            "read_only_roots": list(self.read_only_roots),
            "network_access": self.network_access,
        })


@dataclass(frozen=True, slots=True)
class MCPToolSnapshot:
    server_id: str
    name: str
    description: str
    input_schema: Mapping[str, object]
    output_schema: Mapping[str, object] | None
    annotations: Mapping[str, object]
    schema_digest: str

    def document(self) -> dict[str, object]:
        return {
            "server_id": self.server_id,
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_schema": None if self.output_schema is None else dict(self.output_schema),
            "annotations": dict(self.annotations),
            "schema_digest": self.schema_digest,
            "notice": "Server descriptions and annotations are untrusted claims.",
        }


@dataclass(frozen=True, slots=True)
class MCPInspection:
    server_id: str
    server_protocol_version: str
    server_name: str
    server_version: str
    tools: tuple[MCPToolSnapshot, ...]


@dataclass(frozen=True, slots=True)
class MCPProviderTool:
    name: str
    description: str
    input_schema: Mapping[str, object]
    server_id: str
    tool_name: str
    schema_digest: str

    def document(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.input_schema),
            },
        }


@dataclass(slots=True)
class _ServerRecord:
    definition: MCPServerDefinition
    enabled: bool = False
    granted_permissions: tuple[SkillPermission, ...] = ()
    latest_tools: dict[str, MCPToolSnapshot] = field(default_factory=dict)
    approved_digests: dict[str, str] = field(default_factory=dict)
    process_state: str = "stopped"
    ready: bool = False
    protocol_version: str | None = None
    observed_server_name: str | None = None
    observed_server_version: str | None = None
    last_error: str | None = None


class MCPServerRegistry:
    """Tori-owned state; discovery never mutates approval or enablement."""

    def __init__(self, *, origin_authority: OriginAuthority | None = None) -> None:
        self._authority = origin_authority or OriginAuthority()
        self._records: dict[str, _ServerRecord] = {}
        self._lock = threading.Lock()

    def register(self, definition: MCPServerDefinition, *, origin: RequestOrigin) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        with self._lock:
            if definition.server_id in self._records:
                raise MCPValidationError("That MCP server identity is already registered.")
            self._records[definition.server_id] = _ServerRecord(definition)

    def require_administration(self, origin: RequestOrigin) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)

    def require_invocation(self, origin: RequestOrigin) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_INVOKE)

    def record_inspection(self, inspection: MCPInspection) -> None:
        with self._lock:
            record = self._record(inspection.server_id)
            record.latest_tools = {item.name: item for item in inspection.tools}
            record.protocol_version = inspection.server_protocol_version
            record.observed_server_name = inspection.server_name
            record.observed_server_version = inspection.server_version

    def record_runtime(
        self, server_id: str, *, process_state: str, ready: bool,
        last_error: str | None = None,
    ) -> None:
        if process_state not in {"stopped", "starting", "ready", "failed"}:
            raise MCPValidationError("MCP process state is invalid.")
        if type(ready) is not bool:
            raise MCPValidationError("MCP readiness is invalid.")
        if last_error is not None:
            last_error = _bounded_string(last_error, 1, 500, "MCP error")
        with self._lock:
            record = self._record(server_id)
            record.process_state = process_state
            record.ready = ready
            record.last_error = last_error

    def approve_tool(
        self, server_id: str, tool_name: str, schema_digest: str, *, origin: RequestOrigin
    ) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        with self._lock:
            record = self._record(server_id)
            tool = record.latest_tools.get(tool_name)
            if tool is None or tool_name not in record.definition.allowed_tools:
                raise MCPPermissionError("Only an inspected, configured tool may be approved.")
            if not isinstance(schema_digest, str) or not _constant_equal(tool.schema_digest, schema_digest):
                raise MCPValidationError("The MCP schema approval is stale.")
            record.approved_digests[tool_name] = tool.schema_digest

    def enable(
        self, server_id: str, granted_permissions: Sequence[SkillPermission], *, origin: RequestOrigin
    ) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        grants = tuple(granted_permissions)
        with self._lock:
            record = self._record(server_id)
            if not record.approved_digests:
                raise MCPPermissionError("Approve at least one inspected tool before enabling MCP.")
            requested = {item.key for item in record.definition.requested_permissions}
            if {item.key for item in grants} != requested:
                raise MCPPermissionError("MCP grants must exactly match Tori's configured request.")
            record.granted_permissions = grants
            record.enabled = True

    def disable(self, server_id: str, *, origin: RequestOrigin) -> None:
        self._authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        with self._lock:
            self._record(server_id).enabled = False

    def eligible(self, server_id: str, tool_name: str, *, origin: RequestOrigin) -> MCPToolSnapshot:
        self._authority.require(origin, ConversationOperation.SKILL_INVOKE)
        with self._lock:
            record = self._record(server_id)
            tool = record.latest_tools.get(tool_name)
            approved = record.approved_digests.get(tool_name)
            if not record.enabled or tool is None or approved is None:
                raise MCPPermissionError()
            if not _constant_equal(tool.schema_digest, approved):
                raise MCPPermissionError("The approved MCP tool schema changed; reinspection is required.")
            requested = {item.key for item in record.definition.requested_permissions}
            if {item.key for item in record.granted_permissions} != requested:
                raise MCPPermissionError("The MCP server's configured grants are inactive.")
            return tool

    def projections(self, server_id: str, *, origin: RequestOrigin) -> tuple[MCPProviderTool, ...]:
        if not self._authority.permits(origin, ConversationOperation.SKILL_INVOKE):
            return ()
        with self._lock:
            record = self._record(server_id)
            names = tuple(record.approved_digests)
        result = []
        for name in names:
            try:
                tool = self.eligible(server_id, name, origin=origin)
            except (MCPError, PermissionError):
                continue
            suffix = hashlib.sha256(f"{server_id}\0{name}".encode()).hexdigest()[:12]
            result.append(MCPProviderTool(
                name=f"mcp_{suffix}_{re.sub('[^a-zA-Z0-9_]', '_', name)[:40]}",
                description=f"Approved Tori MCP operation {server_id}/{name}.",
                input_schema=tool.input_schema,
                server_id=server_id,
                tool_name=name,
                schema_digest=tool.schema_digest,
            ))
        return tuple(result)

    def definition(self, server_id: str) -> MCPServerDefinition:
        with self._lock:
            return self._record(server_id).definition

    def server_ids(self) -> tuple[str, ...]:
        """List application-registered server identities without exposing records."""

        with self._lock:
            return tuple(sorted(self._records))

    def document(self, server_id: str) -> dict[str, object]:
        with self._lock:
            record = self._record(server_id)
            return {
                "server_id": record.definition.server_id,
                "display_name": record.definition.display_name,
                "transport": record.definition.transport,
                "executable": record.definition.executable,
                "fixed_argv": list(record.definition.argv),
                "executable_digest": record.definition.executable_digest,
                "server_version": record.definition.server_version,
                "configuration_digest": record.definition.configuration_digest,
                "enabled": record.enabled,
                "allowed_tools": list(record.definition.allowed_tools),
                "approved_tools": dict(record.approved_digests),
                "schema_snapshots": {
                    name: item.document() for name, item in record.latest_tools.items()
                },
                "requested_permissions": [
                    item.document() for item in record.definition.requested_permissions
                ],
                "granted_permissions": [
                    item.document() for item in record.granted_permissions
                ],
                "credential_handle": record.definition.credential_handle,
                "process_state": record.process_state,
                "ready": record.ready,
                "protocol_version": record.protocol_version,
                "observed_server_name": record.observed_server_name,
                "observed_server_version": record.observed_server_version,
                "last_error": record.last_error,
                "network_access": record.definition.network_access,
                "filesystem_scope": list(record.definition.read_only_roots),
                "sandboxed": record.definition.sandbox_executable is not None,
            }

    def _record(self, server_id: str) -> _ServerRecord:
        record = self._records.get(server_id)
        if record is None:
            raise MCPValidationError("That MCP server is not registered.")
        return record


class _BoundedStderr:
    def __init__(self) -> None:
        self.data = bytearray()

    def drain(self, stream) -> None:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            remaining = MAX_STDERR_BYTES - len(self.data)
            if remaining > 0:
                self.data.extend(chunk[:remaining])


class MCPStdioClient:
    """One serial, bounded, process-owned stdio MCP session."""

    def __init__(
        self,
        definition: MCPServerDefinition,
        *,
        secret_provider: MCPSecretProvider | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not 0 < timeout_seconds <= 60:
            raise ValueError("MCP timeout must be between zero and sixty seconds.")
        self.definition = definition
        self._secret_provider = secret_provider
        self._timeout = float(timeout_seconds)
        self._process: subprocess.Popen[bytes] | None = None
        self._responses: queue.Queue[object] = queue.Queue()
        self._request_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr = _BoundedStderr()
        self.server_protocol_version = ""
        self.server_name = ""
        self.server_version = ""
        self.state = "stopped"
        self.failure_reason: str | None = None

    @property
    def ready(self) -> bool:
        return (
            self.state == "ready"
            and self._process is not None
            and self._process.poll() is None
            and bool(self.server_protocol_version)
        )

    def start(self) -> None:
        if self.ready:
            return
        if self._process is not None:
            self.stop()
        self._responses = queue.Queue()
        self._next_id = 1
        self._stderr = _BoundedStderr()
        self.state = "starting"
        self.failure_reason = None
        try:
            self._validate_executable()
            environment = self._launch_environment()
            process = subprocess.Popen(
                self._launch_vector(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                cwd="/tmp",
                start_new_session=True,
            )
        except OSError as exc:
            self.state = "failed"
            raise MCPUnavailableError("The configured MCP server could not be started.") from exc
        except BaseException:
            self.state = "failed"
            raise
        self._process = process
        assert process.stdout is not None and process.stderr is not None
        self._reader = threading.Thread(target=self._read_messages, args=(process,), daemon=True)
        self._stderr_reader = threading.Thread(target=self._stderr.drain, args=(process.stderr,), daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        try:
            result = self._request("initialize", {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tori", "version": MCP_CLIENT_VERSION},
            })
            protocol = result.get("protocolVersion")
            server = result.get("serverInfo")
            if not isinstance(protocol, str) or not isinstance(server, dict):
                raise MCPValidationError("The MCP initialization response is invalid.")
            self.server_protocol_version = _bounded_string(protocol, 1, 64, "MCP protocol")
            self.server_name = _bounded_string(server.get("name"), 1, 256, "MCP server name")
            self.server_version = _bounded_string(server.get("version", "unknown"), 1, 128, "MCP server version")
            if protocol != MCP_PROTOCOL_VERSION:
                raise MCPUnavailableError("The MCP server negotiated an unsupported protocol version.")
            if (
                self.definition.expected_server_name is not None
                and not _constant_equal(self.server_name, self.definition.expected_server_name)
            ):
                raise MCPUnavailableError("The MCP server implementation identity changed.")
            if not _constant_equal(self.server_version, self.definition.server_version):
                raise MCPUnavailableError("The MCP server implementation version changed.")
            self._notification("notifications/initialized", {})
            self.state = "ready"
        except BaseException:
            self.state = "failed"
            self.stop()
            self.state = "failed"
            raise

    def list_tools(self) -> MCPInspection:
        self._require_ready()
        tools: list[MCPToolSnapshot] = []
        cursor: str | None = None
        while True:
            result = self._request("tools/list", {} if cursor is None else {"cursor": cursor})
            values = result.get("tools")
            if not isinstance(values, list):
                raise MCPValidationError("The MCP tool catalog is invalid.")
            for value in values:
                tools.append(_tool_snapshot(self.definition.server_id, value))
                if len(tools) > MAX_TOOLS:
                    raise MCPValidationError("The MCP tool catalog exceeds its limit.")
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                break
            cursor = _bounded_string(next_cursor, 1, 512, "MCP catalog cursor")
        if len({item.name for item in tools}) != len(tools):
            raise MCPValidationError("The MCP tool catalog contains duplicate names.")
        return MCPInspection(
            self.definition.server_id,
            self.server_protocol_version,
            self.server_name,
            self.server_version,
            tuple(tools),
        )

    def call_tool(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        self._require_ready()
        if not isinstance(name, str) or _TOOL.fullmatch(name) is None:
            raise MCPValidationError("MCP tool name is invalid.")
        result = self._request("tools/call", {"name": name, "arguments": dict(arguments)})
        encoded = _canonical_json(result).encode()
        if len(encoded) > MAX_RESULT_BYTES:
            raise MCPValidationError("The MCP tool result exceeds its limit.")
        is_error = result.get("isError", False)
        if type(is_error) is not bool:
            raise MCPValidationError("The MCP tool result error state is invalid.")
        content = result.get("content", [])
        if not isinstance(content, list) or len(content) > 64:
            raise MCPValidationError("The MCP tool result content is invalid.")
        text: list[str] = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or set(item) - {"type", "text", "annotations", "_meta"}:
                continue
            value = item.get("text")
            if isinstance(value, str) and len(value) <= MAX_TEXT:
                text.append(value)
        structured = result.get("structuredContent")
        if structured is not None and not isinstance(structured, dict):
            raise MCPValidationError("The MCP structured result is invalid.")
        return {
            "is_error": is_error,
            "text": "\n".join(text)[:MAX_TEXT],
            "structured": structured,
        }

    def stop(self) -> None:
        process = self._process
        self._process = None
        self.server_protocol_version = ""
        self.state = "stopped"
        self.failure_reason = None
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        for thread in (self._reader, self._stderr_reader):
            if thread is not None:
                thread.join(timeout=0.5)

    def _request(self, method: str, params: Mapping[str, object]) -> dict[str, object]:
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
            try:
                response = self._responses.get(timeout=self._timeout)
            except queue.Empty as exc:
                try:
                    self._notification("notifications/cancelled", {"requestId": request_id, "reason": "timeout"})
                finally:
                    self.stop()
                    self.state = "failed"
                    self.failure_reason = "The MCP server stopped after an invocation timeout."
                raise MCPTimeoutError() from exc
            if isinstance(response, BaseException):
                raise MCPUnavailableError() from response
            if not isinstance(response, dict) or response.get("id") != request_id:
                raise MCPValidationError("The MCP response identity is invalid.")
            if "error" in response:
                error = response["error"]
                message = error.get("message") if isinstance(error, dict) else None
                raise MCPError(
                    "The MCP server reported an error" + (f": {_bounded_string(message, 1, 500, 'MCP error')}" if isinstance(message, str) else "."),
                    code="mcp_server_error",
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise MCPValidationError("The MCP response result is invalid.")
            return result

    def _notification(self, method: str, params: Mapping[str, object]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _write(self, document: Mapping[str, object]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise MCPUnavailableError()
        payload = _canonical_json(document).encode() + b"\n"
        if len(payload) > MAX_MESSAGE_BYTES:
            raise MCPValidationError("The MCP request exceeds its limit.")
        try:
            with self._write_lock:
                process.stdin.write(payload)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPUnavailableError() from exc

    def _read_messages(self, process: subprocess.Popen[bytes]) -> None:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                if self._process is process:
                    self.state = "failed"
                    self.failure_reason = "The MCP server exited unexpectedly."
                self._responses.put(MCPUnavailableError())
                return
            if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                self._fail_reader_process(process, "The MCP server emitted an oversized protocol message.")
                self._responses.put(MCPValidationError("The MCP response exceeds its limit."))
                return
            try:
                message = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._fail_reader_process(process, "The MCP server emitted malformed JSON.")
                self._responses.put(MCPValidationError("The MCP response is not valid JSON."))
                return
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                self._fail_reader_process(process, "The MCP server emitted an invalid protocol envelope.")
                self._responses.put(MCPValidationError("The MCP response envelope is invalid."))
                return
            if "id" in message and ("result" in message or "error" in message):
                self._responses.put(message)
            elif "id" in message and "method" in message:
                # V1 does not delegate elicitation/sampling authority to a
                # server. Reject server-initiated requests out of band.
                try:
                    self._write({
                        "jsonrpc": "2.0", "id": message["id"],
                        "error": {"code": -32601, "message": "Unsupported server request"},
                    })
                except MCPError:
                    return

    def _fail_reader_process(
        self, process: subprocess.Popen[bytes], reason: str
    ) -> None:
        if self._process is not process:
            return
        self.state = "failed"
        self.failure_reason = reason
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _require_ready(self) -> None:
        if not self.ready:
            raise MCPUnavailableError()

    def _validate_executable(self) -> None:
        digest = _hash_executable(Path(self.definition.executable))
        if not _constant_equal(digest, self.definition.executable_digest):
            raise MCPUnavailableError("The configured MCP executable changed and requires reinspection.")
        if self.definition.sandbox_executable is not None:
            sandbox_digest = _hash_executable(Path(self.definition.sandbox_executable))
            if not _constant_equal(
                sandbox_digest, self.definition.sandbox_executable_digest or ""
            ):
                raise MCPUnavailableError("The configured MCP sandbox changed and requires reinspection.")

    def _launch_vector(self) -> tuple[str, ...]:
        sandbox = self.definition.sandbox_executable
        if sandbox is None:
            return (self.definition.executable, *self.definition.argv)
        vector = [
            sandbox,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--dir", "/nonexistent",
        ]
        if self.definition.network_access:
            vector.append("--share-net")
        created: set[str] = {"/", "/tmp", "/nonexistent"}
        for root in self.definition.read_only_roots:
            parent = Path(root).parent
            missing = []
            while str(parent) not in created and str(parent) != "/":
                missing.append(str(parent))
                parent = parent.parent
            for directory in reversed(missing):
                vector.extend(("--dir", directory))
                created.add(directory)
            vector.extend(("--ro-bind", root, root))
            created.add(root)
        vector.extend(("--chdir", "/tmp", "--", self.definition.executable, *self.definition.argv))
        return tuple(vector)

    def _launch_environment(self) -> dict[str, str]:
        environment = {
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
            "TMPDIR": "/tmp",
            "TZ": "UTC",
        }
        if self.definition.credential_handle is not None:
            if self._secret_provider is None:
                raise MCPUnavailableError("The configured MCP secret handle is unavailable.")
            secret = self._secret_provider.resolve(self.definition.credential_handle)
            if not isinstance(secret, str) or not secret or "\x00" in secret:
                raise MCPUnavailableError("The configured MCP secret handle is unavailable.")
            environment[self.definition.credential_environment or ""] = secret
        return environment


class MCPApplicationService:
    """Combines lifecycle, drift, projection, invocation, and normalized truth."""

    def __init__(self, registry: MCPServerRegistry, client: MCPStdioClient) -> None:
        self.registry = registry
        self.client = client
        if registry.definition(client.definition.server_id) != client.definition:
            raise MCPValidationError("MCP client does not match its registered definition.")

    def start_and_inspect(self, *, origin: RequestOrigin) -> MCPInspection:
        # Inspection is administration and therefore local-only.
        self.registry.require_administration(origin)
        try:
            self.registry.record_runtime(
                self.client.definition.server_id, process_state="starting", ready=False
            )
            self.client.start()
            inspection = self.client.list_tools()
            self.registry.record_inspection(inspection)
            self.registry.record_runtime(
                self.client.definition.server_id, process_state="ready", ready=True
            )
            return inspection
        except Exception as exc:
            self.registry.record_runtime(
                self.client.definition.server_id,
                process_state="failed",
                ready=False,
                last_error=str(exc)[:500] or "MCP startup failed.",
            )
            raise

    def provider_tools(self, *, origin: RequestOrigin) -> tuple[MCPProviderTool, ...]:
        if not self.client.ready:
            return ()
        return self.registry.projections(self.client.definition.server_id, origin=origin)

    def call(
        self, tool_name: str, arguments: Mapping[str, object], *, origin: RequestOrigin
    ) -> CapabilityResult:
        self.registry.require_invocation(origin)
        if not self.client.ready:
            raise MCPUnavailableError()
        # Reject unknown, disabled, unapproved, or already-drifted calls before
        # any server interaction, then refresh the catalog and check again.
        self.registry.eligible(self.client.definition.server_id, tool_name, origin=origin)
        # Re-list immediately before use. Changed/removed approved records fail
        # closed; newly added tools remain unapproved and invisible.
        inspection = self.client.list_tools()
        self.registry.record_inspection(inspection)
        tool = self.registry.eligible(self.client.definition.server_id, tool_name, origin=origin)
        normalized = _validate_arguments(tool.input_schema, arguments)
        started = time.monotonic()
        result = self.client.call_tool(tool_name, normalized)
        if result["is_error"] is True:
            raise MCPError("The MCP tool reported failure.", code="mcp_tool_failed")
        structured = result["structured"]
        if tool.output_schema is not None:
            if structured is None:
                raise MCPValidationError("The MCP tool omitted its approved structured result.")
            _validate_arguments(tool.output_schema, structured)
        receipt = _digest({
            "server": self.client.definition.configuration_digest,
            "tool": tool.name,
            "schema": tool.schema_digest,
            "input": normalized,
            "result": result,
        })
        return CapabilityResult(
            capability_id=f"mcp.{self.client.definition.server_id}.{tool.name}",
            input_text=_canonical_json(normalized),
            status="succeeded",
            sources=(),
            metadata={
                "untrusted_text": str(result["text"]),
                "structured_json": "" if structured is None else _canonical_json(structured),
                "receipt": receipt,
                "duration_seconds": round(time.monotonic() - started, 3),
            },
        )

    def stop(self) -> None:
        self.client.stop()
        self.registry.record_runtime(
            self.client.definition.server_id, process_state="stopped", ready=False
        )

    def cancel(self) -> None:
        """Bound cancellation terminates the complete owned server process group."""

        self.client.stop()

    def restart_and_inspect(self, *, origin: RequestOrigin) -> MCPInspection:
        self.client.stop()
        return self.start_and_inspect(origin=origin)

    def status(self) -> dict[str, object]:
        server_id = self.client.definition.server_id
        status = self.registry.document(server_id)
        if status.get("ready") is True and not self.client.ready:
            failed = self.client.state == "failed"
            self.registry.record_runtime(
                server_id,
                process_state="failed" if failed else "stopped",
                ready=False,
                last_error=(
                    self.client.failure_reason
                    or "The MCP server exited or stopped after a protocol failure."
                    if failed else None
                ),
            )
            status = self.registry.document(server_id)
        return status


def executable_digest(path: Path) -> str:
    return _hash_executable(path)


def github_mcp_definition(executable: Path, *, version: str, digest: str) -> MCPServerDefinition:
    """Reviewed GitHub profile: OAuth, read-only, exact stable tools, no dynamic features."""

    return MCPServerDefinition(
        server_id="github.official.readonly",
        executable=str(executable),
        argv=(
            "stdio", "--read-only",
            "--tools=get_me,get_file_contents,issue_read,pull_request_read",
            "--oauth-scopes=public_repo,read:org",
        ),
        executable_digest=digest,
        server_version=version,
        allowed_tools=("get_me", "get_file_contents", "issue_read", "pull_request_read"),
        requested_permissions=(
            SkillPermission("process.execute.approved", {
                "executable": str(executable), "adapter": "mcp.github.readonly",
            }),
            SkillPermission("network.connect.exact", {
                "scheme": "https", "host": "api.github.com", "port": 443,
            }),
            SkillPermission("network.connect.exact", {
                "scheme": "https", "host": "github.com", "port": 443,
            }),
        ),
    )


def _tool_snapshot(server_id: str, value: object) -> MCPToolSnapshot:
    if not isinstance(value, dict):
        raise MCPValidationError("The MCP tool record is invalid.")
    name = value.get("name")
    if not isinstance(name, str) or _TOOL.fullmatch(name) is None:
        raise MCPValidationError("The MCP tool name is invalid.")
    description = value.get("description", "")
    if not isinstance(description, str) or len(description) > 16_000:
        raise MCPValidationError("The MCP tool description is invalid.")
    input_schema = _normalize_schema(value.get("inputSchema"), "input")
    output_raw = value.get("outputSchema")
    output_schema = None if output_raw is None else _normalize_schema(output_raw, "output")
    annotations = value.get("annotations", {})
    if not isinstance(annotations, dict) or len(_canonical_json(annotations).encode()) > 16_000:
        raise MCPValidationError("The MCP tool annotations are invalid.")
    evidence = {
        "name": name,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": output_schema,
        "annotations": annotations,
    }
    return MCPToolSnapshot(
        server_id, name, description,
        MappingProxyType(input_schema),
        None if output_schema is None else MappingProxyType(output_schema),
        MappingProxyType(dict(annotations)), _digest(evidence),
    )


def _normalize_schema(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or len(_canonical_json(value).encode()) > 64 * 1024:
        raise MCPValidationError(f"The MCP {label} schema is invalid or oversized.")
    if value.get("type") != "object" or not isinstance(value.get("properties", {}), dict):
        raise MCPValidationError(f"The MCP {label} schema must describe an object.")
    result = json.loads(_canonical_json(value))
    result["additionalProperties"] = False
    required = result.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise MCPValidationError(f"The MCP {label} schema required list is invalid.")
    if len(set(required)) != len(required) or any(item not in result["properties"] for item in required):
        raise MCPValidationError(f"The MCP {label} schema required list is invalid.")
    _validate_schema_node(result, depth=0)
    return result


def _validate_schema_node(value: object, *, depth: int) -> None:
    if depth > 8 or not isinstance(value, dict):
        raise MCPValidationError("The MCP schema exceeds supported bounds.")
    kind = value.get("type")
    if kind == "object":
        properties = value.get("properties", {})
        if not isinstance(properties, dict) or len(properties) > 64 or value.get("additionalProperties") is not False:
            raise MCPValidationError("The MCP object schema is not closed or bounded.")
        for name, child in properties.items():
            if not isinstance(name, str) or len(name) > 128:
                raise MCPValidationError("The MCP schema property is invalid.")
            _validate_schema_node(child, depth=depth + 1)
    elif kind == "array":
        _validate_schema_node(value.get("items"), depth=depth + 1)
    elif kind not in {"string", "integer", "number", "boolean", "null"}:
        raise MCPValidationError("The MCP schema uses an unsupported type.")


def _validate_arguments(schema: Mapping[str, object], value: object, *, depth: int = 0) -> dict[str, object]:
    if depth > 8 or not isinstance(value, Mapping):
        raise MCPValidationError("MCP tool arguments must be a bounded object.")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise MCPValidationError("The approved MCP schema is invalid.")
    if set(value) - set(properties) or any(name not in value for name in required):
        raise MCPValidationError("MCP tool arguments do not match the approved schema.")
    normalized = json.loads(_canonical_json(dict(value)))
    if len(_canonical_json(normalized).encode()) > MAX_MESSAGE_BYTES // 2:
        raise MCPValidationError("MCP tool arguments exceed their limit.")
    for name, item in normalized.items():
        _validate_value(properties[name], item, depth=depth + 1)
    return normalized


def _validate_value(schema: object, value: object, *, depth: int) -> None:
    if not isinstance(schema, Mapping) or depth > 8:
        raise MCPValidationError("MCP argument schema is invalid.")
    kind = schema.get("type")
    valid = (
        kind == "string" and isinstance(value, str)
        or kind == "integer" and type(value) is int
        or kind == "number" and type(value) in {int, float} and math.isfinite(value)
        or kind == "boolean" and type(value) is bool
        or kind == "null" and value is None
        or kind == "object" and isinstance(value, dict)
        or kind == "array" and isinstance(value, list)
    )
    if not valid:
        raise MCPValidationError("MCP tool argument type is invalid.")
    if kind == "string" and len(value) > 64 * 1024:
        raise MCPValidationError("MCP string argument exceeds its limit.")
    if kind == "object":
        _validate_arguments(schema, value, depth=depth)
    if kind == "array":
        if len(value) > 256:
            raise MCPValidationError("MCP array argument exceeds its limit.")
        for item in value:
            _validate_value(schema.get("items"), item, depth=depth + 1)


def _bounded_string(value: object, minimum: int, maximum: int, label: str) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or "\x00" in value:
        raise MCPValidationError(f"{label} is invalid.")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise MCPValidationError("MCP data is not bounded JSON.") from exc


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _constant_equal(left: str, right: str) -> bool:
    return isinstance(left, str) and isinstance(right, str) and secrets.compare_digest(left, right)


def _hash_executable(path: Path) -> str:
    """Hash one no-follow regular executable through its validated descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MCPUnavailableError("The configured MCP executable is unavailable.") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022
            or info.st_size > MAX_EXECUTABLE_BYTES
            or not info.st_mode & 0o111
        ):
            raise MCPUnavailableError("The configured MCP executable identity is unsafe.")
        digest = hashlib.sha256()
        remaining = MAX_EXECUTABLE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
        if remaining == 0 and os.read(descriptor, 1):
            raise MCPUnavailableError("The configured MCP executable identity is unsafe.")
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)
