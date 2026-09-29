"""Bounded FFprobe-backed implementation of the ``media.inspect`` Skill.

This module is application-owned code.  It does not load executable code,
arguments, environment, or policy from a Skill package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePath
import re
import signal
import stat
import subprocess
import threading
import time

from .capabilities import CapabilityResult
from .request_origin import RequestOrigin
from .skills import (
    SkillAdapterResult,
    SkillApplicationService,
    SkillComponent,
    SkillComponentKind,
    SkillError,
    SkillFieldSchema,
    SkillIdentity,
    SkillImport,
    SkillInspection,
    SkillInvocation,
    SkillManifest,
    SkillObjectSchema,
    SkillOperation,
    SkillPermission,
    SkillRequirements,
    SkillSource,
    SkillUnavailableError,
    SkillValidationError,
    SkillVersionRef,
    digest_package_entries,
)


FFPROBE_PATH = Path("/usr/bin/ffprobe")
BWRAP_PATH = Path("/usr/bin/bwrap")
PRLIMIT_PATH = Path("/usr/bin/prlimit")
MEDIA_INSPECT_VERSION = "1.0.0"
MEDIA_INSPECT_COMPONENT = "media.inspect"
MEDIA_INSPECT_OPERATION = "inspect"
MAX_INPUT_BYTES = 4 * 1024 * 1024 * 1024
MAX_STDOUT_BYTES = 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
WALL_TIMEOUT_SECONDS = 15.0
CPU_LIMIT_SECONDS = 10
ADDRESS_SPACE_LIMIT_BYTES = 512 * 1024 * 1024
MAX_STREAMS = 256

_MINIMAL_ENV = {
    "HOME": "/tmp/tori-home",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PATH": "/usr/bin:/bin",
}
_MEDIA_CUE = re.compile(r"\b(?:codec|ffprobe|media|video|audio)\b", re.IGNORECASE)


class MediaInspectError(SkillUnavailableError):
    """Safe, bounded failure from the media adapter or selection boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExecutableIdentity:
    path: str
    version: str
    sha256: str
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class FileIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(slots=True)
class SelectedMediaFile:
    token: str
    descriptor: int
    identity: FileIdentity

    def close(self) -> None:
        descriptor, self.descriptor = self.descriptor, -1
        if descriptor >= 0:
            os.close(descriptor)


class MediaSelectionRegistry:
    """Process-local opaque bindings to exact, already-open regular files."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bindings: dict[str, SelectedMediaFile] = {}

    def select(self, value: str) -> str:
        descriptor = _open_exact_regular_file(value)
        try:
            identity = _file_identity(os.fstat(descriptor))
            if identity.size > MAX_INPUT_BYTES:
                raise MediaInspectError(
                    "The selected media file exceeds the 4 GiB inspection limit.",
                    code="media_input_too_large",
                )
            token = os.urandom(24).hex()
            binding = SelectedMediaFile(token, descriptor, identity)
            with self._lock:
                self._bindings[token] = binding
            descriptor = -1
            return token
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def consume(self, token: object) -> SelectedMediaFile:
        if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{48}", token) is None:
            raise MediaInspectError(
                "The selected-file binding is invalid or expired.",
                code="media_selection_invalid",
            )
        with self._lock:
            binding = self._bindings.pop(token, None)
        if binding is None:
            raise MediaInspectError(
                "The selected-file binding is invalid or expired.",
                code="media_selection_invalid",
            )
        return binding

    def revoke(self, token: str) -> None:
        with self._lock:
            binding = self._bindings.pop(token, None)
        if binding is not None:
            binding.close()


@dataclass(frozen=True, slots=True)
class FFprobeRunResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    containment_failed: bool = False


class FFprobeRunner:
    """Fixed Bubblewrap runner; its only variable is an open input fd."""

    def __init__(self, *, timeout: float = WALL_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    @staticmethod
    def argv(descriptor: int) -> tuple[str, ...]:
        if type(descriptor) is not int or descriptor < 0:
            raise MediaInspectError("The selected-file descriptor is invalid.", code="media_selection_invalid")
        return (
            str(BWRAP_PATH),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--unshare-user",
            "--disable-userns",
            "--cap-drop", "ALL",
            "--clearenv",
            "--setenv", "HOME", "/tmp/tori-home",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "LC_ALL", "C.UTF-8",
            "--setenv", "PATH", "/usr/bin:/bin",
            "--ro-bind", "/usr", "/usr",
            "--dir", "/etc",
            "--ro-bind", "/etc/alternatives", "/etc/alternatives",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64",
            "--proc", "/proc",
            "--dir", "/dev",
            "--tmpfs", "/tmp",
            "--dir", "/tmp/tori-home",
            "--dir", "/input",
            "--ro-bind-fd", str(descriptor), "/input/media",
            "--chdir", "/tmp",
            "--",
            str(PRLIMIT_PATH),
            f"--cpu={CPU_LIMIT_SECONDS}",
            f"--as={ADDRESS_SPACE_LIMIT_BYTES}",
            "--nofile=64",
            "--nproc=32",
            "--",
            str(FFPROBE_PATH),
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            "/input/media",
        )

    def run(self, descriptor: int) -> FFprobeRunResult:
        for helper in (BWRAP_PATH, PRLIMIT_PATH):
            _validate_root_executable(helper)
        process = subprocess.Popen(
            self.argv(descriptor),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_MINIMAL_ENV,
            cwd="/",
            shell=False,
            close_fds=True,
            pass_fds=(descriptor,),
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        stdout = _BoundedReader(process.stdout, MAX_STDOUT_BYTES)
        stderr = _BoundedReader(process.stderr, MAX_STDERR_BYTES)
        stdout.start()
        stderr.start()
        deadline = time.monotonic() + self._timeout
        timed_out = False
        while process.poll() is None:
            if stdout.truncated or stderr.truncated:
                _terminate_process_group(process)
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process_group(process)
                break
            time.sleep(0.01)
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            process.wait()
        stdout.join(timeout=1.0)
        stderr.join(timeout=1.0)
        captured_stderr = bytes(stderr.content)
        return FFprobeRunResult(
            process.returncode,
            bytes(stdout.content),
            captured_stderr,
            timed_out=timed_out,
            stdout_truncated=stdout.truncated,
            stderr_truncated=stderr.truncated,
            containment_failed=(
                process.returncode != 0
                and not stdout.content
                and captured_stderr.startswith(b"bwrap:")
            ),
        )


class _BoundedReader(threading.Thread):
    def __init__(self, stream: object, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.content = bytearray()
        self.truncated = False

    def run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65_536)  # type: ignore[attr-defined]
                if not chunk:
                    return
                remaining = self._limit - len(self.content)
                if remaining > 0:
                    self.content.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    self.truncated = True
                    return
        except OSError:
            return


class MediaInspectAdapter:
    """The single reviewed bounded-executable adapter for ``media.inspect``."""

    def __init__(
        self,
        selections: MediaSelectionRegistry,
        *,
        runner: FFprobeRunner | object | None = None,
        executable_inspector: Callable[[], ExecutableIdentity] | None = None,
    ) -> None:
        self._selections = selections
        self._runner = runner or FFprobeRunner()
        self._executable_inspector = executable_inspector or inspect_ffprobe_executable

    def supports(self, manifest: SkillManifest, operation: SkillOperation, component: SkillComponent) -> bool:
        permissions = media_inspect_permissions()
        return (
            manifest.identity.canonical_id == "builtin/tori/media.inspect"
            and manifest.version == MEDIA_INSPECT_VERSION
            and manifest.source == SkillSource("local", "builtin:tori:media.inspect", None, True)
            and operation.identifier == MEDIA_INSPECT_OPERATION
            and operation.component_id == MEDIA_INSPECT_COMPONENT
            and operation.required_permissions == permissions
            and manifest.requested_permissions == permissions
            and manifest.requirements.network_destinations == ()
            and manifest.requirements.secret_handles == ()
            and component.identifier == MEDIA_INSPECT_COMPONENT
            and component.kind is SkillComponentKind.BOUNDED_EXECUTABLE
            and component.instructions == ""
        )

    def available(
        self,
        manifest: SkillManifest,
        operation: SkillOperation,
        component: SkillComponent,
    ) -> bool:
        """Revalidate immutable executable evidence and required host helpers."""

        if not self.supports(manifest, operation, component):
            return False
        try:
            inspected_at = datetime.fromisoformat(
                manifest.inspection.inspected_at.removesuffix("Z") + "+00:00"
            )
            current = self._executable_inspector()
            expected = build_media_inspect_manifest(current, inspected_at=inspected_at)
            for helper in (BWRAP_PATH, PRLIMIT_PATH):
                _validate_root_executable(helper)
        except (MediaInspectError, TypeError, ValueError):
            return False
        return manifest.document() == expected.document()

    def invoke(self, request: SkillInvocation) -> SkillAdapterResult:
        component = request.manifest.component(request.operation.component_id)
        if not self.supports(request.manifest, request.operation, component):
            raise MediaInspectError(
                "The bounded media adapter cannot serve that Skill operation.",
                code="media_adapter_mismatch",
            )
        current_identity = self._executable_inspector()
        try:
            inspected_at = datetime.fromisoformat(
                request.manifest.inspection.inspected_at.removesuffix("Z") + "+00:00"
            )
            expected_manifest = build_media_inspect_manifest(
                current_identity, inspected_at=inspected_at
            )
        except (TypeError, ValueError) as exc:
            raise MediaInspectError(
                "The installed media Skill evidence is invalid.",
                code="media_manifest_invalid",
            ) from exc
        if request.manifest.document() != expected_manifest.document():
            raise MediaInspectError(
                "The media Skill contract or FFprobe identity changed; review and install a new immutable Skill version.",
                code="media_executable_changed",
            )
        binding = self._selections.consume(request.inputs.get("selection"))
        try:
            before = _file_identity(os.fstat(binding.descriptor))
            if before != binding.identity or not stat.S_ISREG(os.fstat(binding.descriptor).st_mode):
                return _failure("media_input_changed", "The selected file changed before inspection.")
            result = self._runner.run(binding.descriptor)  # type: ignore[attr-defined]
            after = _file_identity(os.fstat(binding.descriptor))
            if after != binding.identity:
                return _failure("media_input_changed", "The selected file changed during inspection.")
        finally:
            binding.close()
        if result.timed_out:
            return _failure("media_timeout", "FFprobe exceeded the 15 second inspection limit.")
        if result.stdout_truncated or result.stderr_truncated:
            return _failure("media_output_limit", "FFprobe exceeded a bounded output limit.")
        if result.containment_failed:
            return _failure(
                "media_isolation_unavailable",
                "The required local media isolation boundary is unavailable; FFprobe was not admitted.",
            )
        if result.returncode != 0:
            return _failure("media_probe_failed", "FFprobe could not inspect the selected file.")
        try:
            metadata = normalize_ffprobe_json(result.stdout)
        except MediaInspectError as exc:
            return _failure(exc.code, str(exc))
        metadata["outcome"] = "succeeded"
        return SkillAdapterResult("succeeded", metadata=metadata)


class MediaInspectConversationService:
    """Narrow local Conversation bridge into the generic Skill service."""

    def __init__(
        self,
        skills: SkillApplicationService,
        reference: SkillVersionRef | None,
        selections: MediaSelectionRegistry,
        *,
        outcome_recorder: Callable[[CapabilityResult], None] | None = None,
    ) -> None:
        self._skills = skills
        self._reference = reference
        self._selections = selections
        self._outcome_recorder = outcome_recorder

    def _installed_reference(self) -> SkillVersionRef | None:
        if self._reference is not None:
            return self._reference
        candidates = [
            entry
            for entry in self._skills.registry.list_entries()
            if entry.manifest.identity.canonical_id == "builtin/tori/media.inspect"
            and entry.state != "uninstalled"
        ]
        enabled = next((entry for entry in candidates if entry.state == "enabled"), None)
        selected = enabled or (candidates[-1] if candidates else None)
        return None if selected is None else selected.manifest.version_ref

    def handle(self, text: str, *, origin: RequestOrigin) -> str | None:
        path, requested = media_path_from_text(text)
        if not requested:
            return None
        if path is None:
            return (
                "Select one exact local file by giving its absolute path, for example "
                "`/media-inspect /path/to/video.mp4`. Nothing was inspected."
            )
        token: str | None = None
        try:
            reference = self._installed_reference()
            if reference is None:
                return "I could not inspect the selected file: Media inspection is not installed."
            token = self._selections.select(path)
            result = self._skills.invoke(
                reference,
                MEDIA_INSPECT_OPERATION,
                {"selection": token},
                origin=origin,
            )
            message = media_result_message(result)
            if self._outcome_recorder is not None:
                try:
                    self._outcome_recorder(result)
                except Exception:
                    message += (
                        " Tori could not record this normalized outcome in the "
                        "Improvement Journal; the inspection result itself is unchanged."
                    )
            return message
        except SkillError as exc:
            return f"I could not inspect the selected file: {exc}"
        finally:
            if token is not None:
                self._selections.revoke(token)


def inspect_ffprobe_executable() -> ExecutableIdentity:
    descriptor, details = _open_root_executable(FFPROBE_PATH)
    try:
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
    finally:
        os.close(descriptor)
    try:
        completed = subprocess.run(
            (str(FFPROBE_PATH), "-version"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_MINIMAL_ENV,
            cwd="/",
            shell=False,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MediaInspectError("FFprobe version validation failed.", code="media_executable_invalid") from exc
    if completed.returncode != 0 or len(completed.stdout) > MAX_STDERR_BYTES:
        raise MediaInspectError("FFprobe version validation failed.", code="media_executable_invalid")
    first_line = completed.stdout.decode("utf-8", "strict").splitlines()[0:1]
    if not first_line or not first_line[0].startswith("ffprobe version "):
        raise MediaInspectError("FFprobe returned an invalid version identity.", code="media_executable_invalid")
    return ExecutableIdentity(
        str(FFPROBE_PATH), first_line[0][:512], "sha256:" + digest.hexdigest(),
        details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns,
    )


def media_inspect_content_digest(identity: ExecutableIdentity) -> str:
    evidence = json.dumps(
        {
            "adapter": "media.inspect-v1",
            "executable": identity.path,
            "sha256": identity.sha256,
            "version": identity.version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return digest_package_entries(
        {
            "builtin/adapter-contract.json": evidence,
            "builtin/manifest-version": b"media.inspect/1.0.0\n",
        }
    )


def build_media_inspect_manifest(
    identity: ExecutableIdentity | None = None,
    *,
    inspected_at: datetime | None = None,
) -> SkillManifest:
    executable = identity or inspect_ffprobe_executable()
    moment = inspected_at or datetime.now(timezone.utc)
    timestamp = moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    file_permission = SkillPermission("file.read.selected", {})
    process_permission = SkillPermission(
        "process.execute.approved",
        {"executable": str(FFPROBE_PATH), "adapter": MEDIA_INSPECT_COMPONENT},
    )
    output_fields = {
        "outcome": SkillFieldSchema("string", max_length=16),
        "error_code": SkillFieldSchema("string", max_length=64),
        "message": SkillFieldSchema("string", max_length=512),
        "format": SkillFieldSchema("string", max_length=256),
        "format_long_name": SkillFieldSchema("string", max_length=256),
        "duration_seconds": SkillFieldSchema("number"),
        "bitrate_bps": SkillFieldSchema("integer"),
        "stream_count": SkillFieldSchema("integer"),
        "video_codec": SkillFieldSchema("string", max_length=128),
        "width": SkillFieldSchema("integer"),
        "height": SkillFieldSchema("integer"),
        "frame_rate_fps": SkillFieldSchema("number"),
        "audio_codec": SkillFieldSchema("string", max_length=128),
        "audio_channels": SkillFieldSchema("integer"),
        "audio_channel_layout": SkillFieldSchema("string", max_length=128),
        "audio_sample_rate_hz": SkillFieldSchema("integer"),
        "metadata_title": SkillFieldSchema("string", max_length=256),
        "metadata_artist": SkillFieldSchema("string", max_length=256),
        "metadata_album": SkillFieldSchema("string", max_length=256),
        "metadata_encoder": SkillFieldSchema("string", max_length=256),
    }
    return SkillManifest(
        identity=SkillIdentity("builtin", "tori", "media.inspect"),
        display_name="Media inspection",
        version=MEDIA_INSPECT_VERSION,
        source=SkillSource("local", "builtin:tori:media.inspect", None, True),
        content_digest=media_inspect_content_digest(executable),
        import_metadata=SkillImport("tori-builtin", "1.0.0", "0"),
        description="Read normalized media properties from one selected local file.",
        components=(SkillComponent(MEDIA_INSPECT_COMPONENT, SkillComponentKind.BOUNDED_EXECUTABLE, ""),),
        operations=(
            SkillOperation(
                MEDIA_INSPECT_OPERATION,
                MEDIA_INSPECT_COMPONENT,
                "Inspect one opaque selected-file binding with Tori's fixed FFprobe adapter.",
                SkillObjectSchema(
                    {"selection": SkillFieldSchema("string", min_length=48, max_length=48)},
                    ("selection",),
                ),
                SkillObjectSchema(output_fields, ("outcome",)),
                (file_permission, process_permission),
            ),
        ),
        requested_permissions=(file_permission, process_permission),
        requirements=SkillRequirements(
            executables=(
                f"{executable.path} {executable.version} {executable.sha256}",
                str(BWRAP_PATH),
                str(PRLIMIT_PATH),
            )
        ),
        inspection=SkillInspection(
            timestamp,
            "1.0.0",
            (
                "Built-in bounded adapter; fixed argv, no shell, network, secrets, or writes.",
                f"FFprobe identity {executable.sha256}; {executable.version}",
            ),
        ),
    )


def media_inspect_permissions() -> tuple[SkillPermission, SkillPermission]:
    return (
        SkillPermission("file.read.selected", {}),
        SkillPermission(
            "process.execute.approved",
            {"executable": str(FFPROBE_PATH), "adapter": MEDIA_INSPECT_COMPONENT},
        ),
    )


def normalize_ffprobe_json(value: bytes) -> dict[str, str | int | float | bool]:
    if not isinstance(value, bytes) or len(value) > MAX_STDOUT_BYTES:
        raise MediaInspectError("FFprobe output exceeded its validation limit.", code="media_output_invalid")
    try:
        decoded = value.decode("utf-8", "strict")
        document = json.loads(
            decoded,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise MediaInspectError("FFprobe returned malformed structured output.", code="media_output_invalid") from exc
    if not isinstance(document, Mapping):
        raise MediaInspectError("FFprobe returned an invalid result object.", code="media_output_invalid")
    _validate_json_shape(document)
    streams = document.get("streams", [])
    format_item = document.get("format", {})
    if not isinstance(streams, list) or len(streams) > MAX_STREAMS or any(not isinstance(item, Mapping) for item in streams):
        raise MediaInspectError("FFprobe returned an invalid stream list.", code="media_output_invalid")
    if not isinstance(format_item, Mapping):
        raise MediaInspectError("FFprobe returned an invalid format object.", code="media_output_invalid")
    result: dict[str, str | int | float | bool] = {"stream_count": len(streams)}
    _put_text(result, "format", format_item.get("format_name"), 256)
    _put_text(result, "format_long_name", format_item.get("format_long_name"), 256)
    _put_number(result, "duration_seconds", format_item.get("duration"), minimum=0, maximum=3_155_760_000)
    _put_integer(result, "bitrate_bps", format_item.get("bit_rate"), minimum=0, maximum=1_000_000_000_000)
    tags = format_item.get("tags", {})
    if tags is not None and not isinstance(tags, Mapping):
        raise MediaInspectError("FFprobe returned invalid metadata tags.", code="media_output_invalid")
    if isinstance(tags, Mapping):
        lowered = {str(key).lower(): item for key, item in tags.items() if isinstance(key, str)}
        for source, target in (
            ("title", "metadata_title"), ("artist", "metadata_artist"),
            ("album", "metadata_album"), ("encoder", "metadata_encoder"),
        ):
            _put_text(result, target, lowered.get(source), 256)
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is not None:
        _put_text(result, "video_codec", video.get("codec_name"), 128)
        _put_integer(result, "width", video.get("width"), minimum=1, maximum=131_072)
        _put_integer(result, "height", video.get("height"), minimum=1, maximum=131_072)
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
        parsed_rate = _rational(rate)
        if parsed_rate is not None:
            result["frame_rate_fps"] = parsed_rate
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if audio is not None:
        _put_text(result, "audio_codec", audio.get("codec_name"), 128)
        _put_integer(result, "audio_channels", audio.get("channels"), minimum=1, maximum=1_024)
        _put_text(result, "audio_channel_layout", audio.get("channel_layout"), 128)
        _put_integer(result, "audio_sample_rate_hz", audio.get("sample_rate"), minimum=1, maximum=1_000_000)
    return result


def media_path_from_text(text: str) -> tuple[str | None, bool]:
    if not isinstance(text, str):
        return None, False
    if text.lower() == "/media-inspect" or text.lower().startswith("/media-inspect "):
        remainder = text[len("/media-inspect"):].strip()
        return (_strip_matching_quotes(remainder) if remainder else None), True
    if _MEDIA_CUE.search(text) is None:
        return None, False
    quoted = re.search(r"(?P<quote>['\"])(?P<path>/[^\r\n]*?)(?P=quote)", text)
    if quoted is not None:
        return quoted.group("path"), True
    unquoted = re.search(r"(?<![\w])(/[^\s]+)\s*$", text)
    return (unquoted.group(1) if unquoted is not None else None), True


def media_result_message(result: CapabilityResult) -> str:
    metadata = dict(result.metadata or {})
    if result.status != "succeeded" or metadata.get("outcome") != "succeeded":
        return "I could not inspect the selected file: " + str(metadata.get("message", "FFprobe did not return a validated result."))
    facts: list[str] = []
    if metadata.get("format"):
        facts.append(f"format {metadata['format']}")
    if metadata.get("duration_seconds") is not None:
        facts.append(f"duration {float(metadata['duration_seconds']):.3f} seconds")
    if metadata.get("video_codec"):
        resolution = ""
        if metadata.get("width") and metadata.get("height"):
            resolution = f" at {metadata['width']}×{metadata['height']}"
        facts.append(f"video {metadata['video_codec']}{resolution}")
    if metadata.get("audio_codec"):
        facts.append(f"audio {metadata['audio_codec']}")
    facts.append(f"{metadata.get('stream_count', 0)} stream(s)")
    absent: list[str] = []
    for label, key in (("duration", "duration_seconds"), ("bitrate", "bitrate_bps")):
        if key not in metadata:
            absent.append(label)
    suffix = f" FFprobe did not report {', '.join(absent)}." if absent else ""
    return "I inspected the selected file: " + "; ".join(facts) + "." + suffix


def _failure(code: str, message: str) -> SkillAdapterResult:
    return SkillAdapterResult("failed", metadata={"outcome": "failed", "error_code": code, "message": message})


def _open_exact_regular_file(value: object) -> int:
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 4096:
        raise MediaInspectError("Select one valid absolute local file path.", code="media_selection_invalid")
    path = PurePath(value)
    if not path.is_absolute() or ".." in path.parts or str(path) != value:
        raise MediaInspectError("Select one normalized absolute local file path without traversal.", code="media_selection_invalid")
    parts = path.parts[1:]
    if not parts:
        raise MediaInspectError("The selected path is not a regular file.", code="media_selection_invalid")
    if parts[0] in {"dev", "proc", "sys"}:
        raise MediaInspectError("Pseudo-filesystem inputs cannot be selected as media.", code="media_selection_invalid")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for component in parts[:-1]:
            next_directory = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
    except (OSError, ValueError) as exc:
        raise MediaInspectError("The selected file does not exist or cannot be opened safely.", code="media_selection_invalid") from exc
    finally:
        os.close(directory)
    details = os.fstat(descriptor)
    if not stat.S_ISREG(details.st_mode):
        os.close(descriptor)
        raise MediaInspectError("The selected path is not a regular file.", code="media_selection_invalid")
    return descriptor


def _file_identity(details: os.stat_result) -> FileIdentity:
    return FileIdentity(details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)


def _open_root_executable(path: Path) -> tuple[int, os.stat_result]:
    try:
        details = path.lstat()
        # User-namespace mounts may map the system image owner to the owner
        # reported for /usr rather than numeric uid 0.
        system_owner = Path("/usr").stat().st_uid
        if not stat.S_ISREG(details.st_mode) or details.st_uid not in {0, system_owner}:
            raise OSError("unsafe type or owner")
        if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or not details.st_mode & 0o111:
            raise OSError("unsafe permissions")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (details.st_dev, details.st_ino, details.st_mode):
            os.close(descriptor)
            raise OSError("identity changed")
        return descriptor, opened
    except OSError as exc:
        raise MediaInspectError(f"Required executable {path} failed safety validation.", code="media_executable_invalid") from exc


def _validate_root_executable(path: Path) -> None:
    descriptor, _details = _open_root_executable(path)
    os.close(descriptor)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _put_text(result: dict[str, str | int | float | bool], key: str, value: object, maximum: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise MediaInspectError("FFprobe returned an invalid text field.", code="media_output_invalid")
    result[key] = value


def _put_integer(
    result: dict[str, str | int | float | bool], key: str, value: object, *, minimum: int, maximum: int
) -> None:
    if value is None or value == "N/A":
        return
    try:
        parsed = int(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is None or not minimum <= parsed <= maximum:
        raise MediaInspectError("FFprobe returned an invalid numeric field.", code="media_output_invalid")
    result[key] = parsed


def _put_number(
    result: dict[str, str | int | float | bool], key: str, value: object, *, minimum: float, maximum: float
) -> None:
    if value is None or value == "N/A":
        return
    try:
        parsed = float(value) if not isinstance(value, bool) else float("nan")
    except (TypeError, ValueError):
        parsed = float("nan")
    if not minimum <= parsed <= maximum:
        raise MediaInspectError("FFprobe returned an invalid numeric field.", code="media_output_invalid")
    result[key] = parsed


def _rational(value: object) -> float | None:
    if value in {None, "0/0", "N/A"}:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise MediaInspectError("FFprobe returned an invalid frame rate.", code="media_output_invalid")
    match = re.fullmatch(r"([0-9]{1,12})/([0-9]{1,12})", value)
    if match is None or int(match.group(2)) == 0:
        raise MediaInspectError("FFprobe returned an invalid frame rate.", code="media_output_invalid")
    rate = int(match.group(1)) / int(match.group(2))
    if not 0 < rate <= 100_000:
        raise MediaInspectError("FFprobe returned an invalid frame rate.", code="media_output_invalid")
    return round(rate, 6)


def _validate_json_shape(value: object, *, depth: int = 0, budget: list[int] | None = None) -> None:
    remaining = [4096] if budget is None else budget
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 8:
        raise MediaInspectError("FFprobe returned overly complex structured output.", code="media_output_invalid")
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise MediaInspectError("FFprobe returned overly complex structured output.", code="media_output_invalid")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 256:
                raise MediaInspectError("FFprobe returned an invalid object key.", code="media_output_invalid")
            _validate_json_shape(item, depth=depth + 1, budget=remaining)
    elif isinstance(value, list):
        if len(value) > 512:
            raise MediaInspectError("FFprobe returned overly complex structured output.", code="media_output_invalid")
        for item in value:
            _validate_json_shape(item, depth=depth + 1, budget=remaining)
    elif value is not None:
        if not isinstance(value, (str, int, float, bool)):
            raise MediaInspectError("FFprobe returned an unsupported JSON value.", code="media_output_invalid")
        if isinstance(value, float) and not math.isfinite(value):
            raise MediaInspectError("FFprobe returned a non-finite number.", code="media_output_invalid")


def _reject_json_constant(value: str) -> object:
    raise ValueError(value)


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
