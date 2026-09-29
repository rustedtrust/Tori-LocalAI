"""Production composition for Tori's first deliberately narrow MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .capabilities import CapabilityResult
from .capability_registry import CapabilityState
from .mcp import (
    MCPApplicationService,
    MCPError,
    MCPPermissionError,
    MCPServerDefinition,
    MCPServerRegistry,
    MCPStdioClient,
    MCPValidationError,
    executable_digest,
)
from .request_origin import RequestOrigin
from .skills import SkillPermission


TIME_SERVER_ID = "modelcontextprotocol.time.readonly"
TIME_TOOL = "get_current_time"
TIME_PACKAGE = "mcp-server-time"
TIME_PACKAGE_VERSION = "2026.8.18"
TIME_PACKAGE_SOURCE_DIGEST = (
    "sha256:f5ebffa4f2a9a0cf17e54caa6220b5f57062b5c917ee03cd46e771968ca41827"
)
MCP_SDK_PACKAGE = "mcp"
MCP_SDK_VERSION = "1.30.0"
MCP_SDK_SOURCE_DIGEST = (
    "sha256:7047a8f379335332a3b4f50e55decd1c9985e89595a5d97f4149b930327357b4"
)
TIME_SERVER_NAME = "mcp-time"
TIME_SERVER_INFO_VERSION = "1.30.0"
TIME_TOOL_SCHEMA_DIGEST = (
    "sha256:f3a11b4c49a2326a4d93fd4da437be913276dee8f824db07ca0eec24a6ed1205"
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIME_REQUESTS = (
    re.compile(
        r"(?is)^\s*use\s+(?:the\s+)?(?:mcp\s+)?time(?:\s+(?:capability|server|tool))?\s+"
        r"to\s+(?:get|check|tell\s+me)\s+(?:the\s+)?(?:current\s+)?time\s+in\s+(.+?)\s*[?.!]*\s*$"
    ),
    re.compile(
        r"(?is)^\s*what\s+time\s+is\s+it\s+in\s+(.+?)\s+using\s+(?:the\s+)?mcp(?:\s+time)?(?:\s+(?:capability|server|tool))?\s*[?.!]*\s*$"
    ),
)


@dataclass(frozen=True, slots=True)
class MCPTimeProductionSettings:
    enabled: bool = False
    executable: Path | None = None
    executable_digest: str | None = None
    package_version: str = TIME_PACKAGE_VERSION
    server_info_version: str = TIME_SERVER_INFO_VERSION
    approved_schema_digest: str = TIME_TOOL_SCHEMA_DIGEST
    bubblewrap_executable: Path | None = None
    bubblewrap_digest: str | None = None
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("MCP Time enabled state is invalid.")
        if not self.enabled:
            return
        for path, label in (
            (self.executable, "executable"),
            (self.bubblewrap_executable, "bubblewrap executable"),
        ):
            if path is None or not path.is_absolute() or ".." in path.parts:
                raise ValueError(f"MCP Time {label} must be an exact absolute path.")
        for digest, label in (
            (self.executable_digest, "executable digest"),
            (self.bubblewrap_digest, "bubblewrap digest"),
            (self.approved_schema_digest, "approved schema digest"),
        ):
            if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise ValueError(f"MCP Time {label} is invalid.")
        if self.package_version != TIME_PACKAGE_VERSION:
            raise ValueError("MCP Time package version is not the reviewed V1 version.")
        if self.server_info_version != TIME_SERVER_INFO_VERSION:
            raise ValueError("MCP Time protocol implementation version is not reviewed.")
        if self.approved_schema_digest != TIME_TOOL_SCHEMA_DIGEST:
            raise ValueError("MCP Time tool approval does not match the reviewed schema.")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("MCP Time timeout must be between zero and thirty seconds.")


class MCPRuntime:
    """Optional startup-owned MCP process, registry, and conversation adapter."""

    def __init__(
        self,
        registry: MCPServerRegistry | None = None,
        application: MCPApplicationService | None = None,
        *,
        configured: bool = False,
        startup_error: str | None = None,
    ) -> None:
        self.registry = registry
        self.application = application
        self.configured = configured
        self.startup_error = startup_error
        self.conversation = (
            None if application is None else MCPTimeConversationService(application)
        )

    @classmethod
    def start(cls, settings: MCPTimeProductionSettings | None) -> MCPRuntime:
        if settings is None or not settings.enabled:
            return cls(configured=False)
        assert settings.executable is not None
        assert settings.executable_digest is not None
        assert settings.bubblewrap_executable is not None
        assert settings.bubblewrap_digest is not None
        definition = MCPServerDefinition(
            server_id=TIME_SERVER_ID,
            executable=str(settings.executable),
            argv=("--local-timezone=UTC",),
            executable_digest=settings.executable_digest,
            server_version=settings.server_info_version,
            allowed_tools=(TIME_TOOL,),
            requested_permissions=(
                SkillPermission(
                    "process.execute.approved",
                    {"executable": str(settings.executable), "adapter": "mcp.time.readonly"},
                ),
            ),
            display_name="MCP Time",
            expected_server_name=TIME_SERVER_NAME,
            sandbox_executable=str(settings.bubblewrap_executable),
            sandbox_executable_digest=settings.bubblewrap_digest,
            read_only_roots=("/usr", "/lib", "/lib64", str(settings.executable.parents[1])),
            network_access=False,
        )
        registry = MCPServerRegistry()
        origin = RequestOrigin.local_web()
        registry.register(definition, origin=origin)
        client = MCPStdioClient(definition, timeout_seconds=settings.timeout_seconds)
        application = MCPApplicationService(registry, client)
        runtime = cls(registry, application, configured=True)
        try:
            _require_package_identity(settings.package_version)
            inspection = application.start_and_inspect(origin=origin)
            tool = next((item for item in inspection.tools if item.name == TIME_TOOL), None)
            if tool is None:
                raise MCPPermissionError("The approved MCP Time tool disappeared.")
            registry.approve_tool(
                TIME_SERVER_ID,
                TIME_TOOL,
                settings.approved_schema_digest,
                origin=origin,
            )
            registry.enable(
                TIME_SERVER_ID,
                definition.requested_permissions,
                origin=origin,
            )
        except Exception as exc:
            application.stop()
            registry.record_runtime(
                TIME_SERVER_ID,
                process_state="failed",
                ready=False,
                last_error=_public_error(exc),
            )
            runtime.startup_error = _public_error(exc)
        return runtime

    def close(self) -> None:
        if self.application is not None:
            self.application.stop()

    def refresh_status(self) -> None:
        """Project an unexpected child exit into Tori-owned status truth."""

        if self.application is None or self.registry is None:
            return
        status = self.registry.document(TIME_SERVER_ID)
        if (
            status.get("ready") is True
            and not self.application.client.ready
            and self.application.client.state == "failed"
        ):
            self.registry.record_runtime(
                TIME_SERVER_ID,
                process_state="failed",
                ready=False,
                last_error=(
                    self.application.client.failure_reason
                    or "The MCP server exited unexpectedly."
                ),
            )

    def capability_state(self) -> CapabilityState:
        self.refresh_status()
        if not self.configured:
            return CapabilityState("not_configured")
        if self.application is None or self.registry is None:
            return CapabilityState("unavailable", "MCP Time did not initialize")
        status = self.application.status()
        if status.get("ready") is True and status.get("enabled") is True:
            return CapabilityState("available", "bounded local MCP Time read is ready")
        return CapabilityState(
            "unavailable",
            str(status.get("last_error") or self.startup_error or "MCP Time is not ready"),
        )


class MCPTimeConversationService:
    """Closed natural-language route for the one approved read-only MCP tool."""

    def __init__(self, application: MCPApplicationService) -> None:
        self._application = application

    @property
    def available(self) -> bool:
        status = self._application.status()
        return status.get("ready") is True and status.get("enabled") is True

    def handle(self, text: str, *, origin: RequestOrigin) -> str | None:
        timezone = _time_request_timezone(text)
        if timezone is None:
            return None
        if not self.available:
            raise MCPError("MCP Time is configured but unavailable.", code="mcp_unavailable")
        normalized_timezone = _validate_timezone(timezone)
        result = self._application.call(
            TIME_TOOL, {"timezone": normalized_timezone}, origin=origin
        )
        structured = _normalize_time_result(
            result.metadata.get("untrusted_text"), expected_timezone=normalized_timezone
        )
        return (
            f"The MCP Time capability reports {structured['datetime']} "
            f"({structured['day_of_week']}) in {structured['timezone']}. "
            "This was a Tori-approved bounded read; server output was validated as data."
        )


def _require_package_identity(expected: str) -> None:
    try:
        actual = importlib.metadata.version(TIME_PACKAGE)
        sdk_actual = importlib.metadata.version(MCP_SDK_PACKAGE)
    except importlib.metadata.PackageNotFoundError as exc:
        raise MCPValidationError("A pinned MCP Time runtime package is not installed.") from exc
    if (
        actual != expected
        or sdk_actual != MCP_SDK_VERSION
        or _distribution_source_digest(TIME_PACKAGE, "mcp_server_time/")
        != TIME_PACKAGE_SOURCE_DIGEST
        or _distribution_source_digest(MCP_SDK_PACKAGE, "mcp/")
        != MCP_SDK_SOURCE_DIGEST
    ):
        raise MCPValidationError("The installed MCP Time runtime identity changed.")


def _distribution_source_digest(distribution_name: str, prefix: str) -> str:
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise MCPValidationError("A pinned MCP Time runtime package is not installed.") from exc
    names = sorted(
        str(item)
        for item in (distribution.files or ())
        if str(item).startswith(prefix) and str(item).endswith(".py")
    )
    if not names or len(names) > 512:
        raise MCPValidationError("The installed MCP Time runtime inventory is invalid.")
    digest = hashlib.sha256()
    for name in names:
        path = distribution.locate_file(name)
        try:
            descriptor = os.open(
                path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            )
        except OSError as exc:
            raise MCPValidationError("The installed MCP Time runtime is unreadable.") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise MCPValidationError("The installed MCP Time runtime is unsafe.")
            content = bytearray()
            while True:
                block = os.read(descriptor, 64 * 1024)
                if not block:
                    break
                content.extend(block)
                if len(content) > 2 * 1024 * 1024:
                    raise MCPValidationError("The installed MCP Time runtime is oversized.")
        finally:
            os.close(descriptor)
        encoded_name = name.encode("utf-8")
        digest.update(encoded_name + b"\0" + str(len(content)).encode("ascii") + b"\0")
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def _time_request_timezone(text: str) -> str | None:
    for pattern in _TIME_REQUESTS:
        match = pattern.fullmatch(text)
        if match is not None:
            return match.group(1).strip().rstrip("?.!")
    return None


def _validate_timezone(value: str) -> str:
    if (
        not value
        or len(value) > 128
        or re.fullmatch(r"[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+){0,3}", value) is None
    ):
        raise MCPValidationError("Use an exact IANA timezone such as America/Chicago.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise MCPValidationError("That IANA timezone is not available.") from exc
    return value


def _normalize_time_result(value: object, *, expected_timezone: str) -> Mapping[str, object]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 4096:
        raise MCPValidationError("The MCP Time result is invalid.")
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise MCPValidationError("The MCP Time result is not valid JSON data.") from exc
    if not isinstance(document, dict) or set(document) != {
        "timezone", "datetime", "day_of_week", "is_dst"
    }:
        raise MCPValidationError("The MCP Time result shape is invalid.")
    if document.get("timezone") != expected_timezone:
        raise MCPValidationError("The MCP Time result changed the requested timezone.")
    timestamp = document.get("datetime")
    weekday = document.get("day_of_week")
    if (
        not isinstance(timestamp, str)
        or len(timestamp) > 64
        or not isinstance(weekday, str)
        or weekday not in {
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        }
        or type(document.get("is_dst")) is not bool
    ):
        raise MCPValidationError("The MCP Time result fields are invalid.")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise MCPValidationError("The MCP Time timestamp is invalid.") from exc
    if parsed.tzinfo is None or parsed.strftime("%A") != weekday:
        raise MCPValidationError("The MCP Time timestamp is inconsistent.")
    expected = parsed.astimezone(ZoneInfo(expected_timezone))
    expected_dst = expected.dst()
    if (
        expected.utcoffset() != parsed.utcoffset()
        or bool(expected_dst and expected_dst.total_seconds()) != document.get("is_dst")
    ):
        raise MCPValidationError("The MCP Time timezone fields are inconsistent.")
    return document


def _public_error(exc: Exception) -> str:
    if isinstance(exc, MCPError):
        return str(exc)[:500]
    return "The configured MCP Time server could not start safely."


def local_executable_identity(path: Path) -> str:
    """Configuration helper used by tests and explicit setup documentation."""

    return executable_digest(path)
