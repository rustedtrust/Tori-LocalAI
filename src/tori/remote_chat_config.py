"""Owner-private, CLI-administered Remote Chat configuration and secret."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Iterator


REMOTE_CONFIG_SCHEMA_VERSION = 1
MAX_REMOTE_CONFIG_BYTES = 16 * 1024
REMOTE_CONFIG_DIRECTORY = "remote-chat"
REMOTE_CONFIG_FILE = "connector.json"
REMOTE_CONFIG_LOCK_FILE = "connector.lock"
REMOTE_RUNTIME_STATUS_FILE = "runtime-status.json"
REMOTE_RUNTIME_STATUS_LOCK_FILE = "runtime-status.lock"
REMOTE_RUNTIME_STATUS_SCHEMA_VERSION = 1
_REMOTE_RUNTIME_STATES = frozenset(
    {
        "disabled",
        "connecting",
        "connected_ready",
        "configured_disconnected",
        "authentication_configuration_error",
        "runtime_error",
        "stopping",
    }
)


class RemoteConfigError(RuntimeError):
    """The private Remote Chat configuration is absent or unsafe."""

    code = "remote_config_unsafe"


@dataclass(frozen=True, slots=True)
class RemoteChatConfiguration:
    schema_version: int = REMOTE_CONFIG_SCHEMA_VERSION
    revision: int = 1
    generation: int = 1
    administrator_permitted: bool = False
    enabled: bool = False
    connector_id: str | None = None
    application_id: str | None = None
    bot_user_id: str | None = None
    installation_id: str | None = None
    owner_user_id: str | None = None
    dm_channel_id: str | None = None
    token: str | None = field(default=None, repr=False)

    @property
    def complete(self) -> bool:
        return all((
            self.connector_id,
            self.application_id,
            self.bot_user_id,
            self.installation_id,
            self.owner_user_id,
            self.token,
        ))

    @property
    def effective_enabled(self) -> bool:
        return self.administrator_permitted and self.enabled and self.complete

    def redacted(self) -> dict[str, object]:
        document = asdict(self)
        document.pop("token")
        document["token_configured"] = self.token is not None
        document["complete"] = self.complete
        document["effective_enabled"] = self.effective_enabled
        return document


class RemoteChatConfigStore:
    """Atomic private record with exact ownership, mode, and link checks."""

    def __init__(self, directory: Path | None = None) -> None:
        if directory is None:
            base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            directory = base / "tori" / REMOTE_CONFIG_DIRECTORY
        self.directory = Path(directory)
        self.path = self.directory / REMOTE_CONFIG_FILE
        if not self.directory.is_absolute():
            raise ValueError("Remote Chat configuration path must be absolute.")

    def initialize(self) -> RemoteChatConfiguration:
        self._ensure_directory()
        if os.path.lexists(self.path):
            return self.load()
        initial = RemoteChatConfiguration()
        self._write(initial, expected_revision=None)
        return self.load()

    def load(self) -> RemoteChatConfiguration:
        with self.generation_guard() as configuration:
            return configuration

    def load_if_present(self) -> RemoteChatConfiguration | None:
        """Load an existing private record without creating default-off state."""

        if not os.path.lexists(self.directory):
            return None
        directory_fd = self._open_directory()
        try:
            if _stat_at(directory_fd, REMOTE_CONFIG_FILE) is None:
                return None
            lock = _stat_at(directory_fd, REMOTE_CONFIG_LOCK_FILE)
            if lock is None:
                raise RemoteConfigError(
                    "Remote Chat configuration lock is unavailable or unsafe."
                )
            self._require_private_file(lock)
        finally:
            os.close(directory_fd)
        return self.load()

    @contextmanager
    def generation_guard(
        self, expected_generation: int | None = None
    ) -> Iterator[RemoteChatConfiguration]:
        """Hold a cross-process read fence while configuration authority is used."""

        directory_fd, lock_fd = self._acquire_lock(exclusive=False)
        try:
            configuration = self._load_from_directory(directory_fd)
            if (
                expected_generation is not None
                and configuration.generation != expected_generation
            ):
                raise RemoteConfigError("Remote Chat configuration generation changed.")
            yield configuration
        finally:
            os.close(lock_fd)
            os.close(directory_fd)

    def _load_from_directory(self, directory_fd: int) -> RemoteChatConfiguration:
        descriptor = -1
        try:
            descriptor = os.open(
                REMOTE_CONFIG_FILE,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            info = os.fstat(descriptor)
            self._require_private_file(info)
            data = os.read(descriptor, MAX_REMOTE_CONFIG_BYTES + 1)
            if len(data) > MAX_REMOTE_CONFIG_BYTES:
                raise RemoteConfigError("Remote Chat configuration exceeds its size limit.")
        except (OSError, ValueError) as exc:
            if isinstance(exc, RemoteConfigError):
                raise
            raise RemoteConfigError("Remote Chat configuration is unavailable or unsafe.") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteConfigError("Remote Chat configuration is malformed.") from exc
        return _configuration_from_document(document)

    def status(self) -> dict[str, object]:
        return self.load().redacted()

    def combined_status(self) -> dict[str, object]:
        """Return redacted configuration plus the live connector state, if any."""

        configuration = self.load_if_present()
        if configuration is None:
            document = RemoteChatConfiguration().redacted()
            document["configured"] = False
            document["runtime_state"] = "disabled"
            return document
        document = configuration.redacted()
        document["configured"] = True
        if not configuration.effective_enabled:
            document["runtime_state"] = "disabled"
            return document
        document.update(self._read_live_runtime_status())
        return document

    def runtime_status_publisher(self) -> "RemoteChatRuntimeStatusPublisher":
        return RemoteChatRuntimeStatusPublisher(self)

    def _read_live_runtime_status(self) -> dict[str, object]:
        """Read only status published by the process holding the runtime lock."""

        directory_fd = self._open_directory()
        lock_fd = -1
        try:
            try:
                lock_fd = os.open(
                    REMOTE_RUNTIME_STATUS_LOCK_FILE,
                    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                return {"runtime_state": "disabled"}
            self._require_private_file(os.fstat(lock_fd))
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return self._load_runtime_status_from_directory(directory_fd)
            # No publisher means no running process has enabled this session.
            return {"runtime_state": "disabled"}
        except OSError as exc:
            raise RemoteConfigError(
                "Remote Chat runtime status is unavailable or unsafe."
            ) from exc
        finally:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(directory_fd)

    def _load_runtime_status_from_directory(
        self, directory_fd: int
    ) -> dict[str, object]:
        descriptor = -1
        try:
            descriptor = os.open(
                REMOTE_RUNTIME_STATUS_FILE,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            self._require_private_file(os.fstat(descriptor))
            data = os.read(descriptor, MAX_REMOTE_CONFIG_BYTES + 1)
            if len(data) > MAX_REMOTE_CONFIG_BYTES:
                raise RemoteConfigError("Remote Chat runtime status exceeds its size limit.")
        except (OSError, ValueError) as exc:
            if isinstance(exc, RemoteConfigError):
                raise
            raise RemoteConfigError(
                "Remote Chat runtime status is unavailable or unsafe."
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteConfigError("Remote Chat runtime status is malformed.") from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"schema_version", "runtime_state"}
            or document.get("schema_version") != REMOTE_RUNTIME_STATUS_SCHEMA_VERSION
            or document.get("runtime_state") not in _REMOTE_RUNTIME_STATES
        ):
            raise RemoteConfigError("Remote Chat runtime status schema is invalid.")
        return {"runtime_state": document["runtime_state"]}

    def configure_identity(
        self,
        *,
        connector_id: str,
        application_id: str,
        bot_user_id: str,
        installation_id: str,
        owner_user_id: str,
        dm_channel_id: str | None = None,
    ) -> RemoteChatConfiguration:
        current = self.initialize()
        changed = replace(
            current,
            revision=current.revision + 1,
            generation=current.generation + 1,
            enabled=False,
            connector_id=_identifier(connector_id, "connector ID"),
            application_id=_identifier(application_id, "application ID"),
            bot_user_id=_identifier(bot_user_id, "bot user ID"),
            installation_id=_identifier(installation_id, "installation ID"),
            owner_user_id=_identifier(owner_user_id, "owner user ID"),
            dm_channel_id=(
                None if dm_channel_id is None else _identifier(dm_channel_id, "DM channel ID")
            ),
        )
        self._write(changed, expected_revision=current.revision)
        return self.load()

    def set_token(self, token: str) -> RemoteChatConfiguration:
        current = self.initialize()
        normalized = _token(token)
        changed = replace(
            current,
            revision=current.revision + 1,
            generation=current.generation + 1,
            enabled=False,
            token=normalized,
        )
        self._write(changed, expected_revision=current.revision)
        return self.load()

    def clear_token(self) -> RemoteChatConfiguration:
        current = self.initialize()
        changed = replace(
            current,
            revision=current.revision + 1,
            generation=current.generation + 1,
            enabled=False,
            token=None,
        )
        self._write(changed, expected_revision=current.revision)
        return self.load()

    def set_administrator_ceiling(self, permitted: bool) -> RemoteChatConfiguration:
        if not isinstance(permitted, bool):
            raise TypeError("Administrator ceiling must be boolean.")
        current = self.initialize()
        changed = replace(
            current,
            revision=current.revision + 1,
            generation=current.generation + (not permitted),
            administrator_permitted=permitted,
            enabled=current.enabled if permitted else False,
        )
        self._write(changed, expected_revision=current.revision)
        return self.load()

    def set_enabled(self, enabled: bool) -> RemoteChatConfiguration:
        if not isinstance(enabled, bool):
            raise TypeError("Remote Chat enablement must be boolean.")
        current = self.initialize()
        if enabled and (not current.administrator_permitted or not current.complete):
            raise RemoteConfigError(
                "Remote Chat cannot be enabled without its ceiling and complete private configuration."
            )
        changed = replace(
            current,
            revision=current.revision + 1,
            generation=current.generation + (not enabled),
            enabled=enabled,
        )
        self._write(changed, expected_revision=current.revision)
        return self.load()

    def _ensure_directory(self) -> None:
        descriptor = self._open_directory_path(create=True)
        os.close(descriptor)

    def _open_directory(self) -> int:
        return self._open_directory_path(create=False)

    def _open_directory_path(self, *, create: bool) -> int:
        raw = os.fspath(self.directory)
        if not isinstance(raw, str) or "\x00" in raw or ".." in Path(raw).parts:
            raise RemoteConfigError("Remote Chat configuration directory is unsafe.")
        absolute = Path(os.path.abspath(os.path.normpath(raw)))
        flags = (
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            descriptor = os.open("/", flags)
        except OSError as exc:
            raise RemoteConfigError("Remote Chat configuration directory is unsafe.") from exc
        try:
            parts = absolute.parts[1:]
            for index, part in enumerate(parts):
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=descriptor)
                info = os.fstat(child)
                is_leaf = index == len(parts) - 1
                if not stat.S_ISDIR(info.st_mode) or (
                    is_leaf
                    and (
                        info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o700
                    )
                ):
                    os.close(child)
                    raise OSError("unsafe Remote Chat configuration directory")
                os.close(descriptor)
                descriptor = child
            return descriptor
        except (OSError, ValueError) as exc:
            os.close(descriptor)
            raise RemoteConfigError(
                "Remote Chat configuration directory is unavailable or unsafe."
            ) from exc

    def _write(
        self, configuration: RemoteChatConfiguration, *, expected_revision: int | None
    ) -> None:
        self._ensure_directory()
        _configuration_from_document(asdict(configuration))
        payload = json.dumps(
            asdict(configuration), sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        if len(payload) > MAX_REMOTE_CONFIG_BYTES:
            raise RemoteConfigError("Remote Chat configuration exceeds its size limit.")
        directory_fd, lock_fd = self._acquire_lock(exclusive=True)
        temporary = f".{REMOTE_CONFIG_FILE}.{secrets.token_hex(8)}"
        descriptor = -1
        try:
            exists = _stat_at(directory_fd, REMOTE_CONFIG_FILE)
            if expected_revision is None:
                if exists is not None:
                    raise RemoteConfigError(
                        "Remote Chat configuration changed concurrently."
                    )
            else:
                current = self._load_from_directory(directory_fd)
                if current.revision != expected_revision:
                    raise RemoteConfigError(
                        "Remote Chat configuration changed concurrently."
                    )
                self._require_monotonic_transition(current, configuration)
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("short Remote Chat configuration write")
                offset += written
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, REMOTE_CONFIG_FILE, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
            if self._load_from_directory(directory_fd) != configuration:
                raise RemoteConfigError(
                    "Remote Chat configuration publication could not be verified."
                )
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise RemoteConfigError("Remote Chat configuration could not be replaced safely.") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(lock_fd)
            os.close(directory_fd)

    @staticmethod
    def _require_private_file(info: os.stat_result) -> None:
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise RemoteConfigError("Remote Chat configuration file is unsafe.")

    def _acquire_lock(self, *, exclusive: bool) -> tuple[int, int]:
        self._ensure_directory()
        directory_fd = self._open_directory()
        descriptor = -1
        try:
            descriptor = os.open(
                REMOTE_CONFIG_LOCK_FILE,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            self._require_private_file(os.fstat(descriptor))
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            self._require_private_file(os.fstat(descriptor))
            return directory_fd, descriptor
        except (OSError, RemoteConfigError) as exc:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_fd)
            if isinstance(exc, RemoteConfigError):
                raise
            raise RemoteConfigError(
                "Remote Chat configuration lock is unavailable or unsafe."
            ) from exc

    @staticmethod
    def _require_monotonic_transition(
        current: RemoteChatConfiguration,
        changed: RemoteChatConfiguration,
    ) -> None:
        if changed.revision != current.revision + 1:
            raise RemoteConfigError("Remote Chat configuration revision is not monotonic.")
        if changed.generation < current.generation:
            raise RemoteConfigError("Remote Chat connector generation cannot move backward.")
        authority_reduced = (
            (current.enabled and not changed.enabled)
            or (current.administrator_permitted and not changed.administrator_permitted)
            or current.token != changed.token
            or any(
                getattr(current, name) != getattr(changed, name)
                for name in (
                    "connector_id", "application_id", "bot_user_id",
                    "installation_id", "owner_user_id", "dm_channel_id",
                )
            )
        )
        if authority_reduced and changed.generation <= current.generation:
            raise RemoteConfigError(
                "Remote Chat authority reduction must advance connector generation."
            )


class RemoteChatRuntimeStatusPublisher:
    """Publish secret-free live status while exclusively owning the connector."""

    def __init__(self, store: RemoteChatConfigStore) -> None:
        self._store = store
        self._directory_fd = -1
        self._lock_fd = -1
        store._ensure_directory()
        directory_fd = store._open_directory()
        lock_fd = -1
        try:
            lock_fd = os.open(
                REMOTE_RUNTIME_STATUS_LOCK_FILE,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            store._require_private_file(os.fstat(lock_fd))
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RemoteConfigError(
                    "Another Remote Chat connector process is already active."
                ) from exc
            self._directory_fd = directory_fd
            self._lock_fd = lock_fd
            self.publish("connecting")
        except BaseException:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(directory_fd)
            raise

    def publish(self, runtime_state: str) -> None:
        if runtime_state not in _REMOTE_RUNTIME_STATES:
            raise ValueError("Remote Chat runtime status is invalid.")
        if self._directory_fd < 0 or self._lock_fd < 0:
            raise RemoteConfigError("Remote Chat runtime status publisher is closed.")
        document = {
            "schema_version": REMOTE_RUNTIME_STATUS_SCHEMA_VERSION,
            "runtime_state": runtime_state,
        }
        payload = json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        temporary = f".{REMOTE_RUNTIME_STATUS_FILE}.{secrets.token_hex(8)}"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=self._directory_fd,
            )
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("short Remote Chat runtime status write")
                offset += written
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary,
                REMOTE_RUNTIME_STATUS_FILE,
                src_dir_fd=self._directory_fd,
                dst_dir_fd=self._directory_fd,
            )
            os.fsync(self._directory_fd)
            if self._store._load_runtime_status_from_directory(
                self._directory_fd
            ).get("runtime_state") != runtime_state:
                raise RemoteConfigError(
                    "Remote Chat runtime status publication could not be verified."
                )
        except OSError as exc:
            try:
                os.unlink(temporary, dir_fd=self._directory_fd)
            except OSError:
                pass
            raise RemoteConfigError(
                "Remote Chat runtime status could not be replaced safely."
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def close(self) -> None:
        if self._lock_fd >= 0:
            os.close(self._lock_fd)
            self._lock_fd = -1
        if self._directory_fd >= 0:
            os.close(self._directory_fd)
            self._directory_fd = -1

    def __enter__(self) -> "RemoteChatRuntimeStatusPublisher":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _configuration_from_document(document: object) -> RemoteChatConfiguration:
    if not isinstance(document, dict):
        raise RemoteConfigError("Remote Chat configuration must be an object.")
    fields = set(RemoteChatConfiguration.__dataclass_fields__)
    if set(document) != fields:
        raise RemoteConfigError("Remote Chat configuration schema is invalid.")
    try:
        value = RemoteChatConfiguration(**document)
    except TypeError as exc:
        raise RemoteConfigError("Remote Chat configuration schema is invalid.") from exc
    if value.schema_version != REMOTE_CONFIG_SCHEMA_VERSION:
        raise RemoteConfigError("Remote Chat configuration version is unsupported.")
    if isinstance(value.revision, bool) or not isinstance(value.revision, int) or value.revision < 1:
        raise RemoteConfigError("Remote Chat configuration revision is invalid.")
    if isinstance(value.generation, bool) or not isinstance(value.generation, int) or value.generation < 1:
        raise RemoteConfigError("Remote Chat connector generation is invalid.")
    if not isinstance(value.administrator_permitted, bool) or not isinstance(value.enabled, bool):
        raise RemoteConfigError("Remote Chat gates are invalid.")
    for name in (
        "connector_id", "application_id", "bot_user_id", "installation_id",
        "owner_user_id", "dm_channel_id",
    ):
        item = getattr(value, name)
        if item is not None:
            _identifier(item, name)
    if value.token is not None:
        _token(value.token)
    if value.enabled and (not value.administrator_permitted or not value.complete):
        raise RemoteConfigError("Remote Chat configuration has unsafe effective enablement.")
    return value


def _stat_at(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise RemoteConfigError(f"Remote Chat {label} is invalid.")
    return value


def _token(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 16 <= len(value) <= 4_096
        or any(ord(character) < 33 or ord(character) == 127 for character in value)
    ):
        raise RemoteConfigError("Remote Chat token is invalid.")
    return value
