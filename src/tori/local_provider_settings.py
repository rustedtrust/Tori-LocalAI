"""Owner-private operational overrides and secrets for local model providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import stat
import threading


FORMAT_VERSION = 1
MAX_FILE_BYTES = 256 * 1024
MAX_PROFILE_COUNT = 64
MAX_TOKEN_LENGTH = 4096


class LocalProviderSettingsError(RuntimeError):
    """The owner-private provider settings cannot be used safely."""


class LocalProviderSettingsConflictError(LocalProviderSettingsError):
    """A requested revision no longer matches the stored override."""


class LocalProviderSettingsValidationError(LocalProviderSettingsError):
    """A requested override or token is invalid."""


@dataclass(frozen=True, slots=True)
class LocalProviderSettingsRecord:
    identifier: str
    revision: int
    override: Mapping[str, object] | None
    token: str | None


def default_local_provider_settings_path(
    environ: Mapping[str, str] | None = None,
) -> Path:
    source = os.environ if environ is None else environ
    configured = source.get("XDG_CONFIG_HOME")
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            raise LocalProviderSettingsError(
                "XDG_CONFIG_HOME must be an absolute path for local provider settings."
            )
    else:
        root = Path.home() / ".config"
    return root / "tori" / "local-model-providers.json"


class LocalProviderSettingsStore:
    """Persist small provider overrides and bearer tokens outside the repository."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else default_local_provider_settings_path()
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def records(self) -> dict[str, LocalProviderSettingsRecord]:
        with self._lock:
            return self._read()

    def record(self, identifier: str) -> LocalProviderSettingsRecord | None:
        return self.records().get(identifier)

    def set_override(
        self,
        identifier: str,
        *,
        expected_revision: int,
        override: Mapping[str, object],
    ) -> LocalProviderSettingsRecord:
        with self._lock:
            records = self._read()
            current = records.get(identifier)
            actual_revision = 1 if current is None else current.revision
            if expected_revision != actual_revision:
                raise LocalProviderSettingsConflictError(
                    "The local provider settings changed; reload them before editing."
                )
            records[identifier] = LocalProviderSettingsRecord(
                identifier=identifier,
                revision=actual_revision + 1,
                override=dict(override),
                token=None if current is None else current.token,
            )
            self._write(records)
            return self._verified(identifier)

    def replace_token(self, identifier: str, token: object) -> LocalProviderSettingsRecord:
        value = _token(token)
        with self._lock:
            records = self._read()
            current = records.get(identifier)
            records[identifier] = LocalProviderSettingsRecord(
                identifier=identifier,
                revision=2 if current is None else current.revision + 1,
                override=None if current is None else current.override,
                token=value,
            )
            self._write(records)
            return self._verified(identifier)

    def clear_token(self, identifier: str) -> LocalProviderSettingsRecord | None:
        with self._lock:
            records = self._read()
            current = records.get(identifier)
            if current is None or current.token is None:
                return current
            if current.override is None:
                records.pop(identifier)
            else:
                records[identifier] = LocalProviderSettingsRecord(
                    identifier=identifier,
                    revision=current.revision + 1,
                    override=current.override,
                    token=None,
                )
            self._write(records)
            return self._read().get(identifier)

    def remove(self, identifier: str) -> None:
        """Remove settings for a deleted user-owned provider only."""

        with self._lock:
            records = self._read()
            if identifier not in records:
                return
            records.pop(identifier)
            self._write(records)

    def _verified(self, identifier: str) -> LocalProviderSettingsRecord:
        record = self._read().get(identifier)
        if record is None:
            raise LocalProviderSettingsError(
                "The local provider setting was saved but could not be verified."
            )
        return record

    def _read(self) -> dict[str, LocalProviderSettingsRecord]:
        descriptor = self._open_parent(create=False)
        if descriptor is None:
            return {}
        try:
            try:
                file_descriptor = os.open(
                    self._path.name,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                return {}
            except OSError as exc:
                raise LocalProviderSettingsError(
                    "The local provider settings file is unavailable or unsafe."
                ) from exc
            try:
                metadata = os.fstat(file_descriptor)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_uid != os.geteuid()
                    or metadata.st_size > MAX_FILE_BYTES
                ):
                    raise LocalProviderSettingsError(
                        "The local provider settings file is unavailable or unsafe."
                    )
                body = bytearray()
                while chunk := os.read(file_descriptor, 64 * 1024):
                    body.extend(chunk)
                    if len(body) > MAX_FILE_BYTES:
                        raise LocalProviderSettingsError(
                            "The local provider settings file is too large."
                        )
            finally:
                os.close(file_descriptor)
        finally:
            os.close(descriptor)
        try:
            document = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LocalProviderSettingsError(
                "The local provider settings file is malformed; it was not replaced."
            ) from exc
        return _records(document)

    def _write(self, records: Mapping[str, LocalProviderSettingsRecord]) -> None:
        document = {
            "format": FORMAT_VERSION,
            "profiles": {
                identifier: {
                    "revision": record.revision,
                    "override": record.override,
                    "token": record.token,
                }
                for identifier, record in sorted(records.items())
            },
        }
        payload = json.dumps(
            document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            raise LocalProviderSettingsValidationError(
                "The local provider settings are too large."
            )
        descriptor = self._open_parent(create=True)
        assert descriptor is not None
        temporary = f".{self._path.name}.{secrets.token_hex(12)}.tmp"
        temporary_descriptor: int | None = None
        try:
            temporary_descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
            written = 0
            while written < len(payload):
                written += os.write(temporary_descriptor, payload[written:])
            os.fsync(temporary_descriptor)
            os.close(temporary_descriptor)
            temporary_descriptor = None
            self._validate_destination(descriptor)
            os.replace(
                temporary,
                self._path.name,
                src_dir_fd=descriptor,
                dst_dir_fd=descriptor,
            )
            os.fsync(descriptor)
        except LocalProviderSettingsError:
            raise
        except OSError as exc:
            raise LocalProviderSettingsError(
                "Tori could not save the local provider settings safely."
            ) from exc
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
            os.close(descriptor)

    def _open_parent(self, *, create: bool) -> int | None:
        parent = self._path.parent
        try:
            if not self._path.is_absolute() or ".." in self._path.parts:
                raise OSError("unsafe path")
            # Walk existing ancestors without following symlinks before any
            # mkdir/open operation.  The final directory is checked for
            # owner-private permissions below; shared system ancestors (for
            # example /tmp) need not be owned by the current user.
            current = Path(parent.anchor)
            for component in parent.parts[1:]:
                current /= component
                try:
                    ancestor = os.lstat(current)
                except FileNotFoundError:
                    break
                if stat.S_ISLNK(ancestor.st_mode) or not stat.S_ISDIR(ancestor.st_mode):
                    raise OSError("unsafe parent")
            if create:
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            elif not parent.exists():
                return None
            metadata = os.lstat(parent)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
            ):
                raise OSError("unsafe parent")
            if create and stat.S_IMODE(metadata.st_mode) & 0o077:
                raise OSError("provider settings directory is not private")
            return os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LocalProviderSettingsError(
                "The local provider settings path is unavailable or unsafe."
            ) from exc

    def _validate_destination(self, parent_descriptor: int) -> None:
        try:
            metadata = os.stat(
                self._path.name, dir_fd=parent_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            return
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise LocalProviderSettingsError(
                "The local provider settings file is unavailable or unsafe."
            )


def _records(document: object) -> dict[str, LocalProviderSettingsRecord]:
    if (
        not isinstance(document, dict)
        or set(document) != {"format", "profiles"}
        or document.get("format") != FORMAT_VERSION
        or not isinstance(document.get("profiles"), dict)
        or len(document["profiles"]) > MAX_PROFILE_COUNT
    ):
        raise LocalProviderSettingsError(
            "The local provider settings file has an unsupported format."
        )
    result: dict[str, LocalProviderSettingsRecord] = {}
    for identifier, value in document["profiles"].items():
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(value, dict)
            or set(value) != {"revision", "override", "token"}
            or isinstance(value["revision"], bool)
            or not isinstance(value["revision"], int)
            or value["revision"] < 2
            or (value["override"] is not None and not isinstance(value["override"], dict))
            or (value["token"] is not None and not _valid_token(value["token"]))
        ):
            raise LocalProviderSettingsError(
                "The local provider settings file contains invalid data."
            )
        result[identifier] = LocalProviderSettingsRecord(
            identifier, value["revision"], value["override"], value["token"]
        )
    return result


def _token(value: object) -> str:
    if not _valid_token(value):
        raise LocalProviderSettingsValidationError(
            "The local provider token must be a non-empty value no longer than 4096 characters."
        )
    assert isinstance(value, str)
    return value


def _valid_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= MAX_TOKEN_LENGTH
        and "\r" not in value
        and "\n" not in value
        and "\x00" not in value
    )
