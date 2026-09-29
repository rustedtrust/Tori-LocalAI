"""Canonical revision-safe persistence for user-controlled TTS profiles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
from urllib.parse import quote
import sqlite3
import stat
import threading


TTS_PROFILE_SCHEMA_VERSION = 1
DEFAULT_TTS_PROFILE_DATABASE = Path("runtime/tts_profiles/tori_tts_profiles.db")
MAX_TTS_PROFILE_COUNT = 32

_METADATA_SQL = """
CREATE TABLE tts_profile_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_PROFILES_SQL = """
CREATE TABLE tts_profiles (
    identifier TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    model TEXT,
    voice TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    connect_timeout_seconds REAL NOT NULL,
    read_timeout_seconds REAL NOT NULL,
    authentication_mode TEXT NOT NULL CHECK (authentication_mode = 'none'),
    provider_options_json TEXT NOT NULL CHECK (provider_options_json = '{}'),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""
_SELECTION_SQL = """
CREATE TABLE tts_profile_selection (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    profile_identifier TEXT REFERENCES tts_profiles(identifier) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at TEXT NOT NULL
)
"""


class TTSProfileError(RuntimeError):
    """Base browser-safe profile foundation failure."""

    code = "tts_profiles_unavailable"


class TTSProfileValidationError(TTSProfileError):
    code = "invalid_tts_profile"


class TTSProfileConflictError(TTSProfileError):
    code = "tts_profile_conflict"


class TTSProfileStaleRevisionError(TTSProfileConflictError):
    code = "stale_revision"


class TTSProfileNotFoundError(TTSProfileError):
    code = "tts_profile_not_found"


class TTSProfileStoreUnavailableError(TTSProfileError):
    code = "tts_profile_store_unavailable"


class TTSProfileStoreCorruptError(TTSProfileError):
    code = "tts_profile_store_corrupt"


@dataclass(frozen=True, slots=True)
class TTSProfile:
    identifier: str
    display_name: str
    provider_type: str
    endpoint: str
    model: str | None
    voice: str
    enabled: bool
    connect_timeout_seconds: float
    read_timeout_seconds: float
    authentication_mode: str
    provider_options: tuple[tuple[str, object], ...]
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class TTSProfileSelection:
    profile_identifier: str | None
    revision: int
    updated_at: str


class SQLiteTTSProfileStore:
    """Exact schema-1 repository; initialization is always explicit."""

    def __init__(self, path: Path = DEFAULT_TTS_PROFILE_DATABASE) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._safe_path(require_existing=False) is not None

    def initialize(
        self,
        *,
        initial_selection_timestamp: str,
        initial_profile: TTSProfile | None = None,
    ) -> None:
        """Create one store, optionally with one atomic compatibility profile."""
        _validate_timestamp(initial_selection_timestamp)
        with self._lock:
            if self._safe_path(require_existing=False) is not None:
                raise TTSProfileConflictError("The TTS profile store already exists.")
            connection: sqlite3.Connection | None = None
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._safe_path(require_existing=False)
                connection = sqlite3.connect(self._path, timeout=5.0)
                self._settings(connection)
                with connection:
                    connection.execute(_METADATA_SQL)
                    connection.execute(_PROFILES_SQL)
                    connection.execute(_SELECTION_SQL)
                    connection.execute(
                        "INSERT INTO tts_profile_metadata (key, value) VALUES (?, ?)",
                        ("schema_version", str(TTS_PROFILE_SCHEMA_VERSION)),
                    )
                    if initial_profile is not None:
                        connection.execute(
                            "INSERT INTO tts_profiles VALUES "
                            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            _profile_row(initial_profile),
                        )
                    connection.execute(
                        "INSERT INTO tts_profile_selection "
                        "(singleton, profile_identifier, revision, updated_at) "
                        "VALUES (1, ?, 1, ?)",
                        (
                            initial_profile.identifier
                            if initial_profile is not None
                            else None,
                            initial_selection_timestamp,
                        ),
                    )
                self._validate_schema(connection)
                connection.close()
                connection = None
                os.chmod(self._path, 0o600)
            except TTSProfileError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise TTSProfileStoreUnavailableError(
                    "Tori could not initialize the TTS profile store."
                ) from exc
            finally:
                if connection is not None:
                    connection.close()

    def list_profiles(self) -> tuple[TTSProfile, ...]:
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                rows = connection.execute(
                    "SELECT identifier, display_name, provider_type, endpoint, model, "
                    "voice, enabled, connect_timeout_seconds, read_timeout_seconds, "
                    "authentication_mode, provider_options_json, revision, created_at, "
                    "updated_at FROM tts_profiles "
                    "ORDER BY lower(display_name), identifier"
                ).fetchall()
                return tuple(_profile_from_row(row) for row in rows)
            finally:
                connection.close()

    def get_profile(self, identifier: str) -> TTSProfile:
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                row = connection.execute(
                    "SELECT identifier, display_name, provider_type, endpoint, model, "
                    "voice, enabled, connect_timeout_seconds, read_timeout_seconds, "
                    "authentication_mode, provider_options_json, revision, created_at, "
                    "updated_at FROM tts_profiles WHERE identifier = ?",
                    (identifier,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise TTSProfileNotFoundError("The TTS profile was not found.")
        return _profile_from_row(row)

    def create_profile(self, profile: TTSProfile) -> TTSProfile:
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    count = connection.execute(
                        "SELECT count(*) FROM tts_profiles"
                    ).fetchone()[0]
                    if count >= MAX_TTS_PROFILE_COUNT:
                        raise TTSProfileValidationError(
                            "The TTS profile limit has been reached."
                        )
                    connection.execute(
                        "INSERT INTO tts_profiles VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _profile_row(profile),
                    )
            except sqlite3.IntegrityError as exc:
                raise TTSProfileConflictError(
                    "A TTS profile with that stable identifier already exists."
                ) from exc
            finally:
                connection.close()
        return self.get_profile(profile.identifier)

    def update_profile(
        self, profile: TTSProfile, *, expected_revision: int
    ) -> TTSProfile:
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    if not profile.enabled:
                        selected = connection.execute(
                            "SELECT profile_identifier FROM tts_profile_selection "
                            "WHERE singleton = 1"
                        ).fetchone()
                        if selected is None:
                            raise TTSProfileStoreCorruptError(
                                "Tori's TTS profile selection is missing."
                            )
                        if selected[0] == profile.identifier:
                            raise TTSProfileConflictError(
                                "Select another profile or disable speech before disabling the active profile."
                            )
                    cursor = connection.execute(
                        "UPDATE tts_profiles SET display_name=?, endpoint=?, model=?, "
                        "voice=?, enabled=?, connect_timeout_seconds=?, "
                        "read_timeout_seconds=?, authentication_mode=?, "
                        "provider_options_json=?, revision=?, updated_at=? "
                        "WHERE identifier=? AND revision=? AND provider_type=?",
                        (
                            profile.display_name,
                            profile.endpoint,
                            profile.model,
                            profile.voice,
                            int(profile.enabled),
                            profile.connect_timeout_seconds,
                            profile.read_timeout_seconds,
                            profile.authentication_mode,
                            _options_json(profile.provider_options),
                            profile.revision,
                            profile.updated_at,
                            profile.identifier,
                            expected_revision,
                            profile.provider_type,
                        ),
                    )
                    if cursor.rowcount != 1:
                        if connection.execute(
                            "SELECT 1 FROM tts_profiles WHERE identifier = ?",
                            (profile.identifier,),
                        ).fetchone() is None:
                            raise TTSProfileNotFoundError("The TTS profile was not found.")
                        raise TTSProfileStaleRevisionError(
                            "The TTS profile changed; reload it before editing."
                        )
            finally:
                connection.close()
        return self.get_profile(profile.identifier)

    def delete_profile(self, identifier: str, *, expected_revision: int) -> None:
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    selected = connection.execute(
                        "SELECT profile_identifier FROM tts_profile_selection "
                        "WHERE singleton = 1"
                    ).fetchone()
                    if selected is None:
                        raise TTSProfileStoreCorruptError(
                            "Tori's TTS profile selection is missing."
                        )
                    if selected[0] == identifier:
                        raise TTSProfileConflictError(
                            "The active TTS profile cannot be deleted."
                        )
                    cursor = connection.execute(
                        "DELETE FROM tts_profiles WHERE identifier = ? AND revision = ?",
                        (identifier, expected_revision),
                    )
                    if cursor.rowcount != 1:
                        if connection.execute(
                            "SELECT 1 FROM tts_profiles WHERE identifier = ?",
                            (identifier,),
                        ).fetchone() is None:
                            raise TTSProfileNotFoundError("The TTS profile was not found.")
                        raise TTSProfileStaleRevisionError(
                            "The TTS profile changed; reload it before deleting."
                        )
            finally:
                connection.close()

    def get_selection(self) -> TTSProfileSelection:
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                row = connection.execute(
                    "SELECT profile_identifier, revision, updated_at "
                    "FROM tts_profile_selection WHERE singleton = 1"
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise TTSProfileStoreCorruptError(
                "Tori's TTS profile selection is missing."
            )
        if (
            row[0] is not None and not isinstance(row[0], str)
            or not isinstance(row[1], int)
            or row[1] < 1
            or not isinstance(row[2], str)
        ):
            raise TTSProfileStoreCorruptError(
                "Tori's TTS profile selection is invalid."
            )
        _validate_stored_timestamp(row[2])
        return TTSProfileSelection(row[0], row[1], row[2])

    def select_profile(
        self,
        identifier: str,
        *,
        expected_revision: int,
        updated_at: str,
    ) -> TTSProfileSelection:
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    profile = connection.execute(
                        "SELECT enabled FROM tts_profiles WHERE identifier = ?",
                        (identifier,),
                    ).fetchone()
                    if profile is None:
                        raise TTSProfileNotFoundError("The TTS profile was not found.")
                    if profile[0] != 1:
                        raise TTSProfileConflictError(
                            "A disabled TTS profile cannot be selected."
                        )
                    current = connection.execute(
                        "SELECT profile_identifier, revision FROM tts_profile_selection "
                        "WHERE singleton = 1"
                    ).fetchone()
                    if current is None:
                        raise TTSProfileStoreCorruptError(
                            "Tori's TTS profile selection is missing."
                        )
                    if current[1] != expected_revision:
                        raise TTSProfileStaleRevisionError(
                            "The active TTS profile changed; reload before selecting."
                        )
                    if current[0] == identifier:
                        return self.get_selection()
                    cursor = connection.execute(
                        "UPDATE tts_profile_selection SET profile_identifier=?, "
                        "revision=revision+1, updated_at=? "
                        "WHERE singleton=1 AND revision=?",
                        (identifier, updated_at, expected_revision),
                    )
                    if cursor.rowcount != 1:
                        raise TTSProfileStaleRevisionError(
                            "The active TTS profile changed; reload before selecting."
                        )
            finally:
                connection.close()
        return self.get_selection()

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        database = self._safe_path(require_existing=True)
        try:
            connection = sqlite3.connect(
                f"file:{quote(os.fspath(database), safe='/')}?mode={'ro' if readonly else 'rw'}",
                uri=True,
                timeout=5.0,
            )
            self._validate_schema(connection)
            if not readonly:
                self._settings(connection)
            return connection
        except TTSProfileError:
            raise
        except sqlite3.DatabaseError as exc:
            raise TTSProfileStoreCorruptError(
                "Tori's TTS profile store is malformed; it was not replaced."
            ) from exc
        except (OSError, sqlite3.Error) as exc:
            raise TTSProfileStoreUnavailableError(
                "Tori's TTS profile store is unavailable."
            ) from exc

    def _safe_path(self, *, require_existing: bool) -> Path | None:
        try:
            raw = os.fspath(self._path)
            if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
                raise OSError("unsafe path")
            database = Path(os.path.abspath(os.path.normpath(raw)))
            current = Path(database.anchor)
            for component in database.parent.parts[1:]:
                current /= component
                try:
                    item = os.lstat(current)
                except FileNotFoundError:
                    break
                if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
                    raise OSError("unsafe parent")
            try:
                item = os.lstat(database)
            except FileNotFoundError:
                if require_existing:
                    raise TTSProfileStoreUnavailableError(
                        "The TTS profile store has not been initialized."
                    )
                return None
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
                raise OSError("unsafe database")
            return database
        except TTSProfileError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise TTSProfileStoreUnavailableError(
                "Tori's TTS profile path is unavailable or unsafe."
            ) from exc

    @staticmethod
    def _settings(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA secure_delete = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        actual = {
            (kind, name, table, _normalize_sql(sql) if isinstance(sql, str) else None)
            for kind, name, table, sql in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master"
            )
        }
        expected = {
            ("table", "tts_profile_metadata", "tts_profile_metadata", _normalize_sql(_METADATA_SQL)),
            ("index", "sqlite_autoindex_tts_profile_metadata_1", "tts_profile_metadata", None),
            ("table", "tts_profiles", "tts_profiles", _normalize_sql(_PROFILES_SQL)),
            ("index", "sqlite_autoindex_tts_profiles_1", "tts_profiles", None),
            ("table", "tts_profile_selection", "tts_profile_selection", _normalize_sql(_SELECTION_SQL)),
        }
        if actual != expected:
            raise TTSProfileStoreCorruptError(
                "Tori's TTS profile store has an invalid schema; it was not replaced."
            )
        metadata = connection.execute(
            "SELECT key, value FROM tts_profile_metadata"
        ).fetchall()
        if metadata != [("schema_version", str(TTS_PROFILE_SCHEMA_VERSION))]:
            raise TTSProfileStoreCorruptError(
                "Tori's TTS profile store has invalid schema metadata."
            )


def _profile_from_row(row: tuple[object, ...]) -> TTSProfile:
    try:
        options = json.loads(row[10])
        if options != {}:
            raise ValueError("unsupported options")
        profile = TTSProfile(
            identifier=row[0],
            display_name=row[1],
            provider_type=row[2],
            endpoint=row[3],
            model=row[4],
            voice=row[5],
            enabled=bool(row[6]),
            connect_timeout_seconds=row[7],
            read_timeout_seconds=row[8],
            authentication_mode=row[9],
            provider_options=(),
            revision=row[11],
            created_at=row[12],
            updated_at=row[13],
        )
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TTSProfileStoreCorruptError(
            "Tori's TTS profile store contains an invalid profile."
        ) from exc
    if (
        not isinstance(profile.identifier, str)
        or not isinstance(profile.display_name, str)
        or not isinstance(profile.provider_type, str)
        or not isinstance(profile.endpoint, str)
        or profile.model is not None and not isinstance(profile.model, str)
        or not isinstance(profile.voice, str)
        or row[6] not in {0, 1}
        or not isinstance(profile.connect_timeout_seconds, (int, float))
        or isinstance(profile.connect_timeout_seconds, bool)
        or not math.isfinite(profile.connect_timeout_seconds)
        or not 0 < profile.connect_timeout_seconds <= 10
        or not isinstance(profile.read_timeout_seconds, (int, float))
        or isinstance(profile.read_timeout_seconds, bool)
        or not math.isfinite(profile.read_timeout_seconds)
        or not 0 < profile.read_timeout_seconds <= 120
        or profile.authentication_mode != "none"
        or not isinstance(profile.revision, int)
        or profile.revision < 1
        or not isinstance(profile.created_at, str)
        or not isinstance(profile.updated_at, str)
    ):
        raise TTSProfileStoreCorruptError(
            "Tori's TTS profile store contains an invalid profile."
        )
    _validate_stored_timestamp(profile.created_at)
    _validate_stored_timestamp(profile.updated_at)
    return profile


def _profile_row(profile: TTSProfile) -> tuple[object, ...]:
    return (
        profile.identifier,
        profile.display_name,
        profile.provider_type,
        profile.endpoint,
        profile.model,
        profile.voice,
        int(profile.enabled),
        profile.connect_timeout_seconds,
        profile.read_timeout_seconds,
        profile.authentication_mode,
        _options_json(profile.provider_options),
        profile.revision,
        profile.created_at,
        profile.updated_at,
    )


def _options_json(options: tuple[tuple[str, object], ...]) -> str:
    if options:
        raise TTSProfileValidationError(
            "Provider-specific TTS options are not available yet."
        )
    return "{}"


def _normalize_sql(value: str) -> str:
    return " ".join(value.split()).casefold()


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TTSProfileValidationError("The TTS profile timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise TTSProfileValidationError(
            "The TTS profile timestamp is invalid."
        ) from exc
    if parsed.utcoffset() is None:
        raise TTSProfileValidationError("The TTS profile timestamp is invalid.")
    return value


def _validate_stored_timestamp(value: object) -> None:
    try:
        _validate_timestamp(value)
    except TTSProfileValidationError as exc:
        raise TTSProfileStoreCorruptError(
            "Tori's TTS profile store contains an invalid timestamp."
        ) from exc


__all__ = [
    "DEFAULT_TTS_PROFILE_DATABASE",
    "MAX_TTS_PROFILE_COUNT",
    "SQLiteTTSProfileStore",
    "TTSProfile",
    "TTSProfileConflictError",
    "TTSProfileError",
    "TTSProfileNotFoundError",
    "TTSProfileSelection",
    "TTSProfileStaleRevisionError",
    "TTSProfileStoreCorruptError",
    "TTSProfileStoreUnavailableError",
    "TTSProfileValidationError",
]
