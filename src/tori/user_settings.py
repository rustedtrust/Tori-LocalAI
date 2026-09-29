"""Typed durable user preferences for administrator-permitted capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
from urllib.parse import quote

from .providers.base import ModelIdentity, validate_model_identity


SETTINGS_SCHEMA_VERSION = 3
DEFAULT_SETTINGS_DATABASE = Path("runtime/settings/tori_settings.db")
SEARCH_DISABLED_MESSAGE = "Web Search is disabled in Settings."
SETTINGS_FAILURE_MESSAGE = (
    "Capability settings are unavailable, so optional capabilities remain disabled."
)

_METADATA_SQL = """
CREATE TABLE settings_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_SETTINGS_SQL = """
CREATE TABLE user_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    web_search_enabled INTEGER CHECK (web_search_enabled IN (0, 1)),
    speech_output_enabled INTEGER CHECK (speech_output_enabled IN (0, 1)),
    operator_activity_log_enabled INTEGER CHECK (operator_activity_log_enabled IN (0, 1)),
    last_selected_provider TEXT,
    last_selected_model TEXT,
    CHECK ((last_selected_provider IS NULL AND last_selected_model IS NULL)
        OR (last_selected_provider IS NOT NULL AND last_selected_model IS NOT NULL))
)
"""

_SETTINGS_SQL_V2 = """
CREATE TABLE user_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    web_search_enabled INTEGER CHECK (web_search_enabled IN (0, 1)),
    speech_output_enabled INTEGER CHECK (speech_output_enabled IN (0, 1)),
    operator_activity_log_enabled INTEGER CHECK (operator_activity_log_enabled IN (0, 1))
)
"""

_SETTINGS_SQL_V1 = """
CREATE TABLE user_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    web_search_enabled INTEGER CHECK (web_search_enabled IN (0, 1)),
    speech_output_enabled INTEGER CHECK (speech_output_enabled IN (0, 1))
)
"""


class UserSettingsError(RuntimeError):
    """Base error for the durable user-settings boundary."""


class UserSettingsValidationError(UserSettingsError):
    """A requested typed settings value is invalid."""


class UserSettingsPermissionError(UserSettingsValidationError):
    """Administrator configuration does not permit a requested enable."""


class UserSettingsUnavailableError(UserSettingsError):
    """The configured settings storage cannot be accessed safely."""


class UserSettingsCorruptError(UserSettingsError):
    """An existing settings database is malformed or unreadable."""


class UserSettingsVersionError(UserSettingsError):
    """An existing settings database uses an unsupported schema version."""


class UserSettingsVerificationError(UserSettingsError):
    """A committed preference could not be verified by a fresh read."""


@dataclass(frozen=True, slots=True)
class UserSettingsOverrides:
    """Optional durable overrides; ``None`` preserves legacy behavior."""

    web_search_enabled: bool | None = None
    speech_output_enabled: bool | None = None
    operator_activity_log_enabled: bool | None = None
    last_selected_model: ModelIdentity | None = None


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """Administrator, user, and effective state for one capability."""

    administrator_permitted: bool
    user_enabled: bool
    effective_enabled: bool
    override_stored: bool


@dataclass(frozen=True, slots=True)
class CapabilitySettingsState:
    """The complete bounded user-settings state."""

    web_search: CapabilityState
    speech_output: CapabilityState
    operator_activity_log: CapabilityState


class SQLiteUserSettingsStore:
    """Persist the bounded current non-secret user preferences."""

    def __init__(self, path: Path = DEFAULT_SETTINGS_DATABASE) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> UserSettingsOverrides:
        """Read preferences without creating an absent path or database."""

        with self._lock:
            return self._read()

    def _read(self) -> UserSettingsOverrides:

        database = self._safe_database_path(require_existing=False)
        if database is None:
            return UserSettingsOverrides()
        try:
            uri = f"file:{quote(os.fspath(database), safe='/')}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        except sqlite3.DatabaseError as exc:
            raise UserSettingsCorruptError(
                "Tori's user settings database is corrupt or unreadable; it was not replaced."
            ) from exc
        except (OSError, sqlite3.Error) as exc:
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            ) from exc
        try:
            version = self._validate_schema(connection)
            row = connection.execute(
                "SELECT web_search_enabled, speech_output_enabled"
                + (
                    ", operator_activity_log_enabled "
                    if version >= 2
                    else " "
                )
                + (
                    ", last_selected_provider, last_selected_model "
                    if version >= 3
                    else " "
                )
                + "FROM user_settings WHERE singleton = 1"
            ).fetchone()
        except UserSettingsError:
            raise
        except sqlite3.DatabaseError as exc:
            raise UserSettingsCorruptError(
                "Tori's user settings database is corrupt or unreadable; it was not replaced."
            ) from exc
        except sqlite3.Error as exc:
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            ) from exc
        finally:
            connection.close()
        if row is None:
            raise UserSettingsCorruptError(
                "Tori's user settings database has no settings record; it was not replaced."
            )
        return UserSettingsOverrides(
            web_search_enabled=_stored_boolean(row[0]),
            speech_output_enabled=_stored_boolean(row[1]),
            operator_activity_log_enabled=(
                _stored_boolean(row[2]) if version >= 2 else None
            ),
            last_selected_model=(
                _stored_model_identity(row[3], row[4]) if version >= 3 else None
            ),
        )

    def set_web_search_enabled(self, enabled: object) -> UserSettingsOverrides:
        return self._set("web_search_enabled", enabled)

    def set_speech_output_enabled(self, enabled: object) -> UserSettingsOverrides:
        return self._set("speech_output_enabled", enabled)

    def set_operator_activity_log_enabled(
        self, enabled: object
    ) -> UserSettingsOverrides:
        return self._set("operator_activity_log_enabled", enabled)

    def set_last_selected_model(
        self, provider: object, model: object
    ) -> UserSettingsOverrides:
        """Persist one explicit application-level provider/model selection."""

        try:
            identity = validate_model_identity(provider, model)
        except ValueError as exc:
            raise UserSettingsValidationError(
                "The selected provider or model identity is invalid."
            ) from exc
        with self._lock:
            connection = self._connect_for_mutation()
            try:
                with connection:
                    connection.execute(
                        "UPDATE user_settings SET last_selected_provider = ?, "
                        "last_selected_model = ? WHERE singleton = 1",
                        (identity.provider, identity.model),
                    )
            except sqlite3.Error as exc:
                raise UserSettingsUnavailableError(
                    "Tori could not save the selected model preference."
                ) from exc
            finally:
                connection.close()
            current = self._read()
            if current.last_selected_model != identity:
                raise UserSettingsVerificationError(
                    "The selected model preference was saved but could not be verified."
                )
            return current

    def _set(self, column: str, enabled: object) -> UserSettingsOverrides:
        value = _requested_boolean(enabled)
        with self._lock:
            connection = self._connect_for_mutation()
            try:
                with connection:
                    connection.execute(
                        f"UPDATE user_settings SET {column} = ? WHERE singleton = 1",
                        (int(value),),
                    )
            except sqlite3.Error as exc:
                raise UserSettingsUnavailableError(
                    "Tori could not save the user setting."
                ) from exc
            finally:
                connection.close()
            current = self._read()
            if getattr(current, column) is not value:
                raise UserSettingsVerificationError(
                    "The user setting was saved but could not be verified."
                )
            return current

    def _connect_for_mutation(self) -> sqlite3.Connection:
        existing = self._safe_database_path(require_existing=False)
        try:
            if existing is None:
                self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._safe_database_path(require_existing=False)
            connection = sqlite3.connect(
                self._path,
                timeout=5.0,
                isolation_level="DEFERRED",
            )
        except (OSError, sqlite3.Error) as exc:
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            ) from exc
        try:
            if existing is None:
                self._apply_settings(connection)
                self._create_schema(connection)
            else:
                self._apply_settings(connection)
                version = self._validate_schema(connection)
                if version == 1:
                    self._migrate_v1_to_v2(connection)
                    version = 2
                if version == 2:
                    self._migrate_v2_to_v3(connection)
            self._validate_schema(connection)
            return connection
        except UserSettingsError:
            connection.close()
            raise
        except sqlite3.DatabaseError as exc:
            connection.close()
            raise UserSettingsCorruptError(
                "Tori's user settings database is corrupt or unreadable; it was not replaced."
            ) from exc
        except sqlite3.Error as exc:
            connection.close()
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            ) from exc

    def _safe_database_path(self, *, require_existing: bool) -> Path | None:
        try:
            raw = os.fspath(self._path)
            if not isinstance(raw, str) or not raw or "\x00" in raw:
                raise ValueError("unsafe settings path")
            if ".." in Path(raw).parts:
                raise ValueError("unsafe settings path")
            database = Path(os.path.abspath(os.path.normpath(raw)))
            if not database.name:
                raise ValueError("unsafe settings path")
            current = Path(database.anchor)
            for component in database.parent.parts[1:]:
                current /= component
                try:
                    item = os.lstat(current)
                except FileNotFoundError:
                    break
                if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
                    raise OSError("unsafe settings parent")
            try:
                item = os.lstat(database)
            except FileNotFoundError:
                if require_existing:
                    raise
                return None
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
                raise OSError("unsafe settings database")
            return database
        except FileNotFoundError as exc:
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise UserSettingsUnavailableError(
                "Tori's user settings path is unavailable or unsafe."
            ) from exc

    @staticmethod
    def _apply_settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("PRAGMA journal_mode = DELETE")

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        with connection:
            connection.execute(_METADATA_SQL)
            connection.execute(_SETTINGS_SQL)
            connection.execute(
                "INSERT INTO settings_metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SETTINGS_SCHEMA_VERSION)),
            )
            connection.execute(
                "INSERT INTO user_settings ("
                "singleton, web_search_enabled, speech_output_enabled, "
                "operator_activity_log_enabled, last_selected_provider, "
                "last_selected_model"
                ") VALUES (1, NULL, NULL, NULL, NULL, NULL)"
            )

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        """Add the non-secret preference only during an explicit settings write."""

        with connection:
            connection.execute(
                "ALTER TABLE user_settings RENAME TO user_settings_v1"
            )
            connection.execute(_SETTINGS_SQL_V2)
            connection.execute(
                "INSERT INTO user_settings (singleton, web_search_enabled, "
                "speech_output_enabled, operator_activity_log_enabled) "
                "SELECT singleton, web_search_enabled, speech_output_enabled, NULL "
                "FROM user_settings_v1"
            )
            connection.execute("DROP TABLE user_settings_v1")
            connection.execute(
                "UPDATE settings_metadata SET value = ? WHERE key = 'schema_version'",
                ("2",),
            )

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        """Add the application-level selection only during an explicit write."""

        with connection:
            connection.execute(
                "ALTER TABLE user_settings RENAME TO user_settings_v2"
            )
            connection.execute(_SETTINGS_SQL)
            connection.execute(
                "INSERT INTO user_settings (singleton, web_search_enabled, "
                "speech_output_enabled, operator_activity_log_enabled, "
                "last_selected_provider, last_selected_model) "
                "SELECT singleton, web_search_enabled, speech_output_enabled, "
                "operator_activity_log_enabled, NULL, NULL FROM user_settings_v2"
            )
            connection.execute("DROP TABLE user_settings_v2")
            connection.execute(
                "UPDATE settings_metadata SET value = ? WHERE key = 'schema_version'",
                (str(SETTINGS_SCHEMA_VERSION),),
            )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> int:
        metadata = connection.execute(
            "SELECT key, value FROM settings_metadata"
        ).fetchall()
        if len(metadata) != 1 or metadata[0][0] != "schema_version":
            raise UserSettingsCorruptError(
                "Tori's user settings database has invalid metadata; it was not replaced."
            )
        try:
            version = int(metadata[0][1])
        except (TypeError, ValueError) as exc:
            raise UserSettingsCorruptError(
                "Tori's user settings database has an invalid schema version."
            ) from exc
        if version not in {1, 2, SETTINGS_SCHEMA_VERSION}:
            raise UserSettingsVersionError(
                "Tori's user settings database uses unsupported schema "
                f"version {version}; it was not modified."
            )
        settings_sql = (
            _SETTINGS_SQL_V1
            if version == 1
            else _SETTINGS_SQL_V2
            if version == 2
            else _SETTINGS_SQL
        )
        expected_objects = {
            (
                "table",
                "settings_metadata",
                "settings_metadata",
                _normalize_schema_sql(_METADATA_SQL),
            ),
            (
                "index",
                "sqlite_autoindex_settings_metadata_1",
                "settings_metadata",
                None,
            ),
            (
                "table",
                "user_settings",
                "user_settings",
                _normalize_schema_sql(settings_sql),
            ),
        }
        actual_objects = {
            (
                object_type,
                name,
                table,
                _normalize_schema_sql(sql) if isinstance(sql, str) else None,
            )
            for object_type, name, table, sql in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master"
            )
        }
        if actual_objects != expected_objects:
            raise UserSettingsCorruptError(
                "Tori's user settings database has an invalid schema; it was not replaced."
            )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != {"settings_metadata", "user_settings"}:
            raise UserSettingsCorruptError(
                "Tori's user settings database has an invalid schema; it was not replaced."
            )
        expected_columns = {
            "settings_metadata": (
                ("key", "TEXT", 0, 1),
                ("value", "TEXT", 1, 0),
            ),
            "user_settings": (
                ("singleton", "INTEGER", 0, 1),
                ("web_search_enabled", "INTEGER", 0, 0),
                ("speech_output_enabled", "INTEGER", 0, 0),
            ) + (
                (("operator_activity_log_enabled", "INTEGER", 0, 0),)
                if version >= 2
                else ()
            ) + (
                (
                    ("last_selected_provider", "TEXT", 0, 0),
                    ("last_selected_model", "TEXT", 0, 0),
                )
                if version >= 3
                else ()
            ),
        }
        for table, expected in expected_columns.items():
            columns = tuple(
                (row[1], row[2].upper(), row[3], row[5])
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if columns != expected:
                raise UserSettingsCorruptError(
                    "Tori's user settings database has an invalid schema; it was not replaced."
                )
        row = connection.execute(
            "SELECT singleton, web_search_enabled, speech_output_enabled"
            + (
                ", operator_activity_log_enabled " if version >= 2 else " "
            )
            + (
                ", last_selected_provider, last_selected_model "
                if version >= 3
                else " "
            )
            + "FROM user_settings"
        ).fetchall()
        if len(row) != 1 or row[0][0] != 1:
            raise UserSettingsCorruptError(
                "Tori's user settings database has an invalid settings record; it was not replaced."
            )
        _stored_boolean(row[0][1])
        _stored_boolean(row[0][2])
        if version >= 2:
            _stored_boolean(row[0][3])
        if version >= 3:
            _stored_model_identity(row[0][4], row[0][5])
        return version


class CapabilitySettingsController:
    """Combine administrator permission with the two durable preferences."""

    def __init__(
        self,
        *,
        administrator_web_search: bool,
        administrator_speech_output: bool,
        store: SQLiteUserSettingsStore | None,
    ) -> None:
        self._administrator_web_search = bool(administrator_web_search)
        self._administrator_speech_output = bool(administrator_speech_output)
        self._store = store

    def state(self) -> CapabilitySettingsState:
        overrides = (
            self._store.read() if self._store is not None else UserSettingsOverrides()
        )
        return CapabilitySettingsState(
            web_search=_capability_state(
                self._administrator_web_search, overrides.web_search_enabled
            ),
            speech_output=_capability_state(
                self._administrator_speech_output, overrides.speech_output_enabled
            ),
            operator_activity_log=_capability_state(
                True, overrides.operator_activity_log_enabled
            ),
        )

    def set_web_search_enabled(self, enabled: object) -> CapabilitySettingsState:
        value = _requested_boolean(enabled)
        self._require_user_enable_allowed(
            value, self._administrator_web_search, "Web Search"
        )
        self._require_store().set_web_search_enabled(value)
        return self.state()

    def set_speech_output_enabled(self, enabled: object) -> CapabilitySettingsState:
        value = _requested_boolean(enabled)
        self._require_user_enable_allowed(
            value, self._administrator_speech_output, "Speech Output"
        )
        self._require_store().set_speech_output_enabled(value)
        return self.state()

    def set_operator_activity_log_enabled(
        self, enabled: object
    ) -> CapabilitySettingsState:
        value = _requested_boolean(enabled)
        self._require_store().set_operator_activity_log_enabled(value)
        return self.state()

    def _require_store(self) -> SQLiteUserSettingsStore:
        if self._store is None:
            raise UserSettingsUnavailableError(
                "Tori's user settings store is unavailable."
            )
        return self._store

    @staticmethod
    def _require_user_enable_allowed(
        enabled: bool, administrator_permitted: bool, label: str
    ) -> None:
        if enabled and not administrator_permitted:
            raise UserSettingsPermissionError(
                f"{label} is not permitted by administrator configuration."
            )


def _requested_boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise UserSettingsValidationError("The setting value must be true or false.")
    return value


def _stored_boolean(value: object) -> bool | None:
    if value is None:
        return None
    if value == 0:
        return False
    if value == 1:
        return True
    raise UserSettingsCorruptError(
        "Tori's user settings database contains an invalid boolean; it was not replaced."
    )


def _stored_model_identity(
    provider: object, model: object
) -> ModelIdentity | None:
    if provider is None and model is None:
        return None
    if not isinstance(provider, str) or not isinstance(model, str):
        raise UserSettingsCorruptError(
            "Tori's user settings database contains an invalid model preference; "
            "it was not replaced."
        )
    try:
        return validate_model_identity(provider, model)
    except ValueError as exc:
        raise UserSettingsCorruptError(
            "Tori's user settings database contains an invalid model preference; "
            "it was not replaced."
        ) from exc


def _capability_state(
    administrator_permitted: bool, override: bool | None
) -> CapabilityState:
    user_enabled = True if override is None else override
    return CapabilityState(
        administrator_permitted=administrator_permitted,
        user_enabled=user_enabled,
        effective_enabled=administrator_permitted and user_enabled,
        override_stored=override is not None,
    )


def state_document(state: CapabilitySettingsState) -> dict[str, object]:
    """Return the fixed browser-safe representation of capability settings."""

    def capability(value: CapabilityState) -> dict[str, bool]:
        return {
            "administrator_permitted": value.administrator_permitted,
            "user_enabled": value.user_enabled,
            "effective_enabled": value.effective_enabled,
            "override_stored": value.override_stored,
        }

    return {
        "web_search": capability(state.web_search),
        "speech_output": capability(state.speech_output),
        "operator_activity_log": capability(state.operator_activity_log),
    }


def _normalize_schema_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()
