"""Typed persistence and registry merging for human-managed model profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import threading
from urllib.parse import quote

from .config import ConfigError, KnownModel, ProviderProfile, validate_provider_endpoint
from .local_provider_settings import (
    LocalProviderSettingsConflictError,
    LocalProviderSettingsError,
    LocalProviderSettingsStore,
    LocalProviderSettingsValidationError,
)
from .model_catalog import ModelCatalogService
from .providers.base import (
    ModelDescriptor,
    ModelIdentity,
    ModelProvider,
    validate_model_identifier,
    validate_provider_identifier,
)


PROVIDER_PROFILE_SCHEMA_VERSION = 1
DEFAULT_PROVIDER_PROFILE_DATABASE = Path(
    "runtime/model_providers/tori_model_providers.db"
)
MAX_PROFILE_COUNT = 64
MAX_KNOWN_MODELS = 256
MAX_KNOWN_MODELS_JSON = 64 * 1024

_METADATA_SQL = """
CREATE TABLE provider_profile_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_PROFILES_SQL = """
CREATE TABLE provider_profiles (
    identifier TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    implementation TEXT NOT NULL CHECK (implementation = 'openai_compatible'),
    base_url TEXT NOT NULL,
    timeout_seconds REAL NOT NULL,
    authentication TEXT NOT NULL CHECK (authentication IN ('none', 'dummy_bearer')),
    structured_output TEXT NOT NULL CHECK (structured_output IN ('json_object', 'prompt_only')),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    known_models_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class ProviderProfileError(RuntimeError):
    """Base safe profile-management failure."""

    code = "provider_profiles_unavailable"


class ProviderProfileValidationError(ProviderProfileError):
    code = "invalid_provider_profile"


class ProviderProfileConflictError(ProviderProfileError):
    code = "provider_profile_conflict"


class ProviderProfileNotFoundError(ProviderProfileError):
    code = "provider_profile_not_found"


class ProviderProfileStoreUnavailableError(ProviderProfileError):
    code = "provider_profile_store_unavailable"


class ProviderProfileStoreCorruptError(ProviderProfileError):
    code = "provider_profile_store_corrupt"


@dataclass(frozen=True, slots=True)
class UserManagedProviderProfile:
    identifier: str
    display_name: str
    implementation: str
    base_url: str
    timeout_seconds: float
    authentication: str
    structured_output: str
    enabled: bool
    known_models: tuple[KnownModel, ...]
    revision: int
    created_at: str
    updated_at: str

    def configured(self) -> ProviderProfile:
        return ProviderProfile(
            identifier=self.identifier,
            display_name=self.display_name,
            implementation=self.implementation,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            authentication=self.authentication,
            structured_output=self.structured_output,
            known_models=self.known_models,
        )


class SQLiteProviderProfileStore:
    """Exact schema-1 store; initialization is always an explicit operation."""

    def __init__(self, path: Path = DEFAULT_PROVIDER_PROFILE_DATABASE) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._safe_path(require_existing=False) is not None

    def initialize(self) -> None:
        """Create a new empty schema-1 store; never replace an existing path."""
        with self._lock:
            if self._safe_path(require_existing=False) is not None:
                raise ProviderProfileConflictError(
                    "The model provider profile store already exists."
                )
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._safe_path(require_existing=False)
                connection = sqlite3.connect(self._path, timeout=5.0)
                self._settings(connection)
                with connection:
                    connection.execute(_METADATA_SQL)
                    connection.execute(_PROFILES_SQL)
                    connection.execute(
                        "INSERT INTO provider_profile_metadata (key, value) VALUES (?, ?)",
                        ("schema_version", str(PROVIDER_PROFILE_SCHEMA_VERSION)),
                    )
                self._validate_schema(connection)
                connection.close()
                os.chmod(self._path, 0o600)
            except ProviderProfileError:
                raise
            except (OSError, sqlite3.Error) as exc:
                raise ProviderProfileStoreUnavailableError(
                    "Tori could not initialize the model provider profile store."
                ) from exc

    def list_profiles(self) -> tuple[UserManagedProviderProfile, ...]:
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                rows = connection.execute(
                    "SELECT identifier, display_name, implementation, base_url, "
                    "timeout_seconds, authentication, structured_output, enabled, "
                    "known_models_json, revision, created_at, updated_at "
                    "FROM provider_profiles ORDER BY lower(display_name), identifier"
                ).fetchall()
                return tuple(_profile_from_row(row) for row in rows)
            finally:
                connection.close()

    def create(
        self,
        *,
        display_name: object,
        base_url: object,
        timeout_seconds: object,
        authentication: object,
        structured_output: object,
        known_models: object = (),
        identifier: object | None = None,
    ) -> UserManagedProviderProfile:
        profile = _validated_profile_input(
            identifier=(
                f"user-{secrets.token_hex(6)}" if identifier is None else identifier
            ),
            display_name=display_name,
            implementation="openai_compatible",
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            authentication=authentication,
            structured_output=structured_output,
            enabled=True,
            known_models=known_models,
            revision=1,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                count = connection.execute(
                    "SELECT count(*) FROM provider_profiles"
                ).fetchone()[0]
                if count >= MAX_PROFILE_COUNT:
                    raise ProviderProfileValidationError(
                        "The model provider profile limit has been reached."
                    )
                with connection:
                    connection.execute(
                        "INSERT INTO provider_profiles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _profile_row(profile),
                    )
            except sqlite3.IntegrityError as exc:
                raise ProviderProfileConflictError(
                    "A model provider profile with that stable identifier already exists."
                ) from exc
            finally:
                connection.close()
            return self.get(profile.identifier)

    def get(self, identifier: object) -> UserManagedProviderProfile:
        value = _identifier(identifier)
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                row = connection.execute(
                    "SELECT identifier, display_name, implementation, base_url, "
                    "timeout_seconds, authentication, structured_output, enabled, "
                    "known_models_json, revision, created_at, updated_at "
                    "FROM provider_profiles WHERE identifier = ?", (value,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            raise ProviderProfileNotFoundError("The model provider profile was not found.")
        return _profile_from_row(row)

    def update(
        self,
        identifier: object,
        *,
        expected_revision: object,
        display_name: object,
        base_url: object,
        timeout_seconds: object,
        authentication: object,
        structured_output: object,
        known_models: object,
    ) -> UserManagedProviderProfile:
        current = self.get(identifier)
        revision = _revision(expected_revision)
        if revision != current.revision:
            raise ProviderProfileConflictError(
                "The model provider profile changed; reload it before editing."
            )
        updated = _validated_profile_input(
            identifier=current.identifier,
            display_name=display_name,
            implementation=current.implementation,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            authentication=authentication,
            structured_output=structured_output,
            enabled=current.enabled,
            known_models=known_models,
            revision=current.revision + 1,
            created_at=current.created_at,
            updated_at=_utc_now(),
        )
        self._replace(current, updated)
        return self.get(current.identifier)

    def set_enabled(
        self, identifier: object, *, expected_revision: object, enabled: object
    ) -> UserManagedProviderProfile:
        current = self.get(identifier)
        revision = _revision(expected_revision)
        if revision != current.revision:
            raise ProviderProfileConflictError(
                "The model provider profile changed; reload it before editing."
            )
        if not isinstance(enabled, bool):
            raise ProviderProfileValidationError("enabled must be a boolean.")
        updated = replace(
            current, enabled=enabled, revision=current.revision + 1,
            updated_at=_utc_now(),
        )
        self._replace(current, updated)
        return self.get(current.identifier)

    def delete(self, identifier: object, *, expected_revision: object) -> None:
        current = self.get(identifier)
        if _revision(expected_revision) != current.revision:
            raise ProviderProfileConflictError(
                "The model provider profile changed; reload it before deleting."
            )
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    cursor = connection.execute(
                        "DELETE FROM provider_profiles WHERE identifier = ? AND revision = ?",
                        (current.identifier, current.revision),
                    )
                    if cursor.rowcount != 1:
                        raise ProviderProfileConflictError(
                            "The model provider profile changed; reload it before deleting."
                        )
            finally:
                connection.close()

    def _replace(
        self, current: UserManagedProviderProfile,
        updated: UserManagedProviderProfile,
    ) -> None:
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    cursor = connection.execute(
                        "UPDATE provider_profiles SET display_name=?, implementation=?, "
                        "base_url=?, timeout_seconds=?, authentication=?, structured_output=?, "
                        "enabled=?, known_models_json=?, revision=?, created_at=?, updated_at=? "
                        "WHERE identifier=? AND revision=?",
                        (*_profile_row(updated)[1:], current.identifier, current.revision),
                    )
                    if cursor.rowcount != 1:
                        raise ProviderProfileConflictError(
                            "The model provider profile changed; reload it before editing."
                        )
            finally:
                connection.close()

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        database = self._safe_path(require_existing=True)
        try:
            connection = sqlite3.connect(
                f"file:{quote(os.fspath(database), safe='/')}?mode={'ro' if readonly else 'rw'}",
                uri=True, timeout=5.0,
            )
            self._validate_schema(connection)
            if not readonly:
                self._settings(connection)
            return connection
        except ProviderProfileError:
            raise
        except sqlite3.DatabaseError as exc:
            raise ProviderProfileStoreCorruptError(
                "Tori's model provider profile store is malformed; it was not replaced."
            ) from exc
        except (OSError, sqlite3.Error) as exc:
            raise ProviderProfileStoreUnavailableError(
                "Tori's model provider profile store is unavailable."
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
                    raise ProviderProfileStoreUnavailableError(
                        "The model provider profile store has not been initialized."
                    )
                return None
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
                raise OSError("unsafe database")
            return database
        except ProviderProfileError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise ProviderProfileStoreUnavailableError(
                "Tori's model provider profile path is unavailable or unsafe."
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
            ("table", "provider_profile_metadata", "provider_profile_metadata", _normalize_sql(_METADATA_SQL)),
            ("index", "sqlite_autoindex_provider_profile_metadata_1", "provider_profile_metadata", None),
            ("table", "provider_profiles", "provider_profiles", _normalize_sql(_PROFILES_SQL)),
            ("index", "sqlite_autoindex_provider_profiles_1", "provider_profiles", None),
        }
        if actual != expected:
            raise ProviderProfileStoreCorruptError(
                "Tori's model provider profile store has an invalid schema; it was not replaced."
            )
        metadata = connection.execute(
            "SELECT key, value FROM provider_profile_metadata"
        ).fetchall()
        if metadata != [("schema_version", str(PROVIDER_PROFILE_SCHEMA_VERSION))]:
            raise ProviderProfileStoreCorruptError(
                "Tori's model provider profile store has invalid schema metadata."
            )


ProviderFactory = Callable[[ProviderProfile, str | None], ModelProvider]


class ModelProviderProfileController:
    """Merge config and user profiles, rejecting every stable-ID collision."""

    def __init__(
        self,
        *,
        configured_profiles: Sequence[ProviderProfile],
        configured_identity: ModelIdentity,
        provider_factory: ProviderFactory,
        store: SQLiteProviderProfileStore | None,
        local_settings: LocalProviderSettingsStore | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._configured_profiles = tuple(configured_profiles)
        self._configured_identity = configured_identity
        self._provider_factory = provider_factory
        self._store = store
        self._local_settings = local_settings
        self._environ = os.environ if environ is None else environ
        self._catalog: ModelCatalogService | None = None
        self._rebuild()

    @property
    def catalog(self) -> ModelCatalogService:
        assert self._catalog is not None
        return self._catalog

    @property
    def initialized(self) -> bool:
        return self._store is not None and self._store.exists

    def state(self) -> dict[str, object]:
        user = self._user_profiles()
        records = self._local_records()
        effective_configured = self._effective_configured_profiles(records)
        statuses = {
            item.identifier: item
            for item in self.catalog.profile_descriptors_snapshot_with(
                self._configured_identity
            )
        }
        configured = [
            {
                "identifier": item.identifier,
                "display_name": item.display_name,
                "implementation": item.implementation,
                "source": "configuration",
                "editable": self._local_settings is not None,
                "deletable": False,
                "enabled": True,
                "base_url": item.base_url,
                "timeout_seconds": item.timeout_seconds,
                "authentication": item.authentication,
                "structured_output": item.structured_output,
                "known_models": [_browser_known_model(model) for model in item.known_models],
                "revision": records[item.identifier].revision if item.identifier in records else 1,
                **self._credential_metadata(item, records),
                "catalog_status": _catalog_status(statuses.get(item.identifier)),
            }
            for item in effective_configured
        ]
        managed = [
            {
                **_browser_user_profile(item),
                "deletable": True,
                **self._credential_metadata(item.configured(), records),
                "catalog_status": _catalog_status(statuses.get(item.identifier)),
            }
            for item in user
        ]
        return {
            "ok": True,
            "initialized": self.initialized,
            "profiles": configured + managed,
        }

    def create(self, **values: object) -> UserManagedProviderProfile:
        store = self._require_store()
        requested = values.get("identifier")
        if requested is not None and requested in self._configured_identifiers:
            raise ProviderProfileConflictError(
                "That stable profile identifier belongs to configuration."
            )
        profile = store.create(**values)
        try:
            self._rebuild()
        except Exception:
            # This should only be reachable through a collision introduced by a
            # concurrent configuration change. Preserve the record and fail closed.
            raise ProviderProfileConflictError(
                "The saved profile conflicts with configured provider identity."
            )
        return profile

    def update(self, identifier: object, **values: object) -> UserManagedProviderProfile:
        normalized = _identifier(identifier)
        if normalized in self._configured_identifiers:
            self._update_configured(normalized, **values)
            self._rebuild()
            return self._configured_as_user_shape(normalized)
        self._require_user_identifier(normalized)
        profile = self._require_store().update(identifier, **values)
        self._rebuild()
        return profile

    def set_token(self, identifier: object, *, action: object, token: object = None) -> None:
        normalized = _identifier(identifier)
        profiles = {
            item.identifier: item
            for item in (*self._effective_configured_profiles(self._local_records()),
                         *(item.configured() for item in self._user_profiles()))
        }
        profile = profiles.get(normalized)
        if profile is None:
            raise ProviderProfileNotFoundError("The model provider profile was not found.")
        if profile.implementation != "openai_compatible":
            raise ProviderProfileValidationError(
                "Only OpenAI-compatible profiles accept a bearer token."
            )
        settings = self._require_local_settings()
        try:
            if action == "replace":
                settings.replace_token(normalized, token)
            elif action == "clear":
                settings.clear_token(normalized)
            else:
                raise ProviderProfileValidationError("The token action is invalid.")
        except LocalProviderSettingsValidationError as exc:
            raise ProviderProfileValidationError(str(exc)) from exc
        except LocalProviderSettingsError as exc:
            raise ProviderProfileStoreUnavailableError(str(exc)) from exc
        self._rebuild()

    def set_enabled(self, identifier: object, **values: object) -> UserManagedProviderProfile:
        self._require_user_identifier(identifier)
        profile = self._require_store().set_enabled(identifier, **values)
        self._rebuild()
        return profile

    def delete(self, identifier: object, **values: object) -> None:
        self._require_user_identifier(identifier)
        self._require_store().delete(identifier, **values)
        if self._local_settings is not None:
            try:
                self._local_settings.remove(_identifier(identifier))
            except LocalProviderSettingsError as exc:
                raise ProviderProfileStoreUnavailableError(str(exc)) from exc
        self._rebuild()

    @property
    def _configured_identifiers(self) -> frozenset[str]:
        return frozenset(item.identifier for item in self._configured_profiles)

    def _require_user_identifier(self, identifier: object) -> None:
        if _identifier(identifier) in self._configured_identifiers:
            raise ProviderProfileValidationError(
                "Configuration-managed provider profiles cannot be changed here."
            )

    def _require_store(self) -> SQLiteProviderProfileStore:
        if self._store is None or not self._store.exists:
            raise ProviderProfileStoreUnavailableError(
                "The model provider profile store has not been initialized."
            )
        return self._store

    def _user_profiles(self) -> tuple[UserManagedProviderProfile, ...]:
        if self._store is None or not self._store.exists:
            return ()
        return self._store.list_profiles()

    def _require_local_settings(self) -> LocalProviderSettingsStore:
        if self._local_settings is None:
            raise ProviderProfileStoreUnavailableError(
                "Local provider settings are unavailable."
            )
        return self._local_settings

    def _local_records(self):  # type: ignore[no-untyped-def]
        if self._local_settings is None:
            return {}
        try:
            return self._local_settings.records()
        except LocalProviderSettingsError as exc:
            raise ProviderProfileStoreUnavailableError(str(exc)) from exc

    def _effective_configured_profiles(self, records):  # type: ignore[no-untyped-def]
        result = []
        for profile in self._configured_profiles:
            record = records.get(profile.identifier)
            if record is None or record.override is None:
                result.append(profile)
                continue
            result.append(_configured_override(profile, record.override))
        return tuple(result)

    def _credential_metadata(self, profile: ProviderProfile, records):  # type: ignore[no-untyped-def]
        record = records.get(profile.identifier)
        if record is not None and record.token is not None:
            return {"token_configured": True, "token_source": "stored"}
        environment_name = profile.credential_environment
        environment_token = (
            self._environ.get(environment_name)
            if isinstance(environment_name, str)
            else None
        )
        if _usable_token(environment_token):
            return {"token_configured": True, "token_source": "environment"}
        return {"token_configured": False, "token_source": None}

    def _update_configured(self, identifier: str, **values: object) -> None:
        settings = self._require_local_settings()
        base = next(item for item in self._configured_profiles if item.identifier == identifier)
        override = _configured_override_document(base, values)
        try:
            settings.set_override(
                identifier,
                expected_revision=_revision(values["expected_revision"]),
                override=override,
            )
        except LocalProviderSettingsConflictError as exc:
            raise ProviderProfileConflictError(str(exc)) from exc
        except LocalProviderSettingsValidationError as exc:
            raise ProviderProfileValidationError(str(exc)) from exc
        except LocalProviderSettingsError as exc:
            raise ProviderProfileStoreUnavailableError(str(exc)) from exc

    def _configured_as_user_shape(self, identifier: str) -> UserManagedProviderProfile:
        records = self._local_records()
        profile = next(
            item for item in self._effective_configured_profiles(records)
            if item.identifier == identifier
        )
        revision = records[identifier].revision
        timestamp = _utc_now()
        return UserManagedProviderProfile(
            profile.identifier, profile.display_name, profile.implementation,
            profile.base_url, profile.timeout_seconds, profile.authentication,
            profile.structured_output, True, profile.known_models, revision,
            timestamp, timestamp,
        )

    def _rebuild(self) -> None:
        users = self._user_profiles()
        collisions = self._configured_identifiers & {
            item.identifier for item in users
        }
        if collisions:
            raise ProviderProfileConflictError(
                "Configured and user-managed model profiles contain a duplicate stable identifier."
            )
        records = self._local_records()
        profiles = (*self._effective_configured_profiles(records), *(item.configured() for item in users if item.enabled))
        providers = {
            item.identifier: self._provider_factory(
                item,
                records[item.identifier].token
                if item.identifier in records
                else None,
            )
            for item in profiles
        }
        known: dict[str, tuple[ModelDescriptor, ...]] = {
            item.identifier: tuple(
                ModelDescriptor(
                    item.identifier, model.model, model.display_name,
                    status="configured",
                    context_window_tokens=model.context_window_tokens,
                ) for model in item.known_models
            ) for item in profiles
        }
        names = {item.identifier: item.display_name for item in profiles}
        self._catalog = ModelCatalogService(
            providers,
            configured=self._configured_identity,
            configured_models=known,
            profile_display_names=names,
        )


def _browser_user_profile(profile: UserManagedProviderProfile) -> dict[str, object]:
    return {
        "identifier": profile.identifier,
        "display_name": profile.display_name,
        "implementation": profile.implementation,
        "source": "user",
        "editable": True,
        "enabled": profile.enabled,
        "base_url": profile.base_url,
        "timeout_seconds": profile.timeout_seconds,
        "authentication": profile.authentication,
        "structured_output": profile.structured_output,
        "known_models": [
            {
                "model": item.model,
                "display_name": item.display_name,
                "context_window_tokens": item.context_window_tokens,
            } for item in profile.known_models
        ],
        "revision": profile.revision,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _browser_known_model(model: KnownModel) -> dict[str, object]:
    return {
        "model": model.model,
        "display_name": model.display_name,
        "context_window_tokens": model.context_window_tokens,
    }


def _catalog_status(descriptor: object) -> dict[str, object]:
    if descriptor is None:
        return {"availability": "unresolved", "reason_code": None}
    return {
        "availability": getattr(descriptor, "status", "unresolved"),
        "reason_code": getattr(descriptor, "reason_code", None),
    }


def _configured_override_document(
    base: ProviderProfile, values: Mapping[str, object]
) -> dict[str, object]:
    document = {
        "display_name": values["display_name"],
        "base_url": values["base_url"],
        "timeout_seconds": values["timeout_seconds"],
        "authentication": values["authentication"],
        "structured_output": values["structured_output"],
        "known_models": values["known_models"],
    }
    effective = _configured_override(base, document)
    return {
        "display_name": effective.display_name,
        "base_url": effective.base_url,
        "timeout_seconds": effective.timeout_seconds,
        "authentication": effective.authentication,
        "structured_output": effective.structured_output,
        "known_models": [_browser_known_model(item) for item in effective.known_models],
    }


def _configured_override(
    base: ProviderProfile, document: Mapping[str, object]
) -> ProviderProfile:
    if set(document) != {
        "display_name", "base_url", "timeout_seconds", "authentication",
        "structured_output", "known_models",
    }:
        raise ProviderProfileValidationError(
            "The built-in provider override has an invalid shape."
        )
    display_name = _bounded_text(document["display_name"], "display_name", 80)
    try:
        base_url = validate_provider_endpoint(
            _bounded_text(document["base_url"], "base_url", 512),
            implementation=base.implementation,
        )
    except ConfigError as exc:
        raise ProviderProfileValidationError(str(exc)) from exc
    timeout = document["timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0.1 <= float(timeout) <= 3600
    ):
        raise ProviderProfileValidationError(
            "timeout_seconds must be between 0.1 and 3600."
        )
    authentication = document["authentication"]
    if base.implementation == "ollama":
        if authentication != "none":
            raise ProviderProfileValidationError(
                "Ollama profiles do not support authentication modes."
            )
        structured = "json_object"
        credential_environment = None
    else:
        if authentication not in {"none", "dummy_bearer", "environment_bearer"}:
            raise ProviderProfileValidationError("authentication is unsupported.")
        if authentication == "environment_bearer" and base.credential_environment != "LM_API_TOKEN":
            raise ProviderProfileValidationError(
                "This profile has no configured environment-token reference."
            )
        structured = document["structured_output"]
        if structured not in {"json_object", "prompt_only"}:
            raise ProviderProfileValidationError("structured_output is unsupported.")
        credential_environment = (
            base.credential_environment
            if authentication == "environment_bearer"
            else None
        )
    known = _known_models(document["known_models"])
    return ProviderProfile(
        identifier=base.identifier,
        display_name=display_name,
        implementation=base.implementation,
        base_url=base_url,
        timeout_seconds=float(timeout),
        keep_alive=base.keep_alive,
        authentication=authentication,
        credential_environment=credential_environment,
        structured_output=structured,
        known_models=known,
    )


def _usable_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 4096
        and "\r" not in value
        and "\n" not in value
        and "\x00" not in value
    )


def _validated_profile_input(**values: object) -> UserManagedProviderProfile:
    try:
        identifier = validate_provider_identifier(values["identifier"])
        base_url = validate_provider_endpoint(
            _bounded_text(values["base_url"], "base_url", 512),
            implementation="openai_compatible",
        )
    except (ValueError, ConfigError) as exc:
        raise ProviderProfileValidationError(str(exc)) from exc
    display_name = _bounded_text(values["display_name"], "display_name", 80)
    implementation = values["implementation"]
    if implementation != "openai_compatible":
        raise ProviderProfileValidationError(
            "User-managed profiles currently support only openai_compatible."
        )
    timeout = values["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= float(timeout) <= 3600:
        raise ProviderProfileValidationError("timeout_seconds must be between 0.1 and 3600.")
    authentication = values["authentication"]
    if authentication not in {"none", "dummy_bearer"}:
        raise ProviderProfileValidationError("authentication is unsupported.")
    structured = values["structured_output"]
    if structured not in {"json_object", "prompt_only"}:
        raise ProviderProfileValidationError("structured_output is unsupported.")
    enabled = values["enabled"]
    if not isinstance(enabled, bool):
        raise ProviderProfileValidationError("enabled must be a boolean.")
    known = _known_models(values["known_models"])
    return UserManagedProviderProfile(
        identifier, display_name, implementation, base_url, float(timeout),
        authentication, structured, enabled, known, _revision(values["revision"]),
        _timestamp(values["created_at"]), _timestamp(values["updated_at"]),
    )


def _known_models(value: object) -> tuple[KnownModel, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_KNOWN_MODELS:
        raise ProviderProfileValidationError("known_models must be a bounded list.")
    result: list[KnownModel] = []
    identifiers: set[str] = set()
    for item in value:
        if isinstance(item, KnownModel):
            model, display, capacity = item.model, item.display_name, item.context_window_tokens
        elif isinstance(item, Mapping) and set(item) == {"model", "display_name", "context_window_tokens"}:
            model, display, capacity = item["model"], item["display_name"], item["context_window_tokens"]
        else:
            raise ProviderProfileValidationError("Each known model has an invalid shape.")
        try:
            model_id = validate_model_identifier(model)
        except ValueError as exc:
            raise ProviderProfileValidationError(str(exc)) from exc
        if model_id in identifiers:
            raise ProviderProfileValidationError("Known model identifiers must be unique.")
        identifiers.add(model_id)
        display_name = _bounded_text(display, "known model display_name", 120)
        if capacity is not None and (
            isinstance(capacity, bool) or not isinstance(capacity, int) or not 1024 <= capacity <= 10_000_000
        ):
            raise ProviderProfileValidationError(
                "context_window_tokens must be null or an integer from 1024 to 10000000."
            )
        result.append(KnownModel(model_id, display_name, capacity))
    return tuple(result)


def _profile_row(profile: UserManagedProviderProfile) -> tuple[object, ...]:
    known = json.dumps(
        [{"model": item.model, "display_name": item.display_name,
          "context_window_tokens": item.context_window_tokens}
         for item in profile.known_models],
        separators=(",", ":"), sort_keys=True,
    )
    if len(known.encode("utf-8")) > MAX_KNOWN_MODELS_JSON:
        raise ProviderProfileValidationError("known_models is too large.")
    return (
        profile.identifier, profile.display_name, profile.implementation,
        profile.base_url, profile.timeout_seconds, profile.authentication,
        profile.structured_output, int(profile.enabled), known, profile.revision,
        profile.created_at, profile.updated_at,
    )


def _profile_from_row(row: Sequence[object]) -> UserManagedProviderProfile:
    try:
        raw = row[8]
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_KNOWN_MODELS_JSON:
            raise ValueError("invalid known models")
        known = json.loads(raw)
        if row[7] not in (0, 1):
            raise ValueError("invalid enabled")
        return _validated_profile_input(
            identifier=row[0], display_name=row[1], implementation=row[2],
            base_url=row[3], timeout_seconds=row[4], authentication=row[5],
            structured_output=row[6], enabled=bool(row[7]), known_models=known,
            revision=row[9], created_at=row[10], updated_at=row[11],
        )
    except (ValueError, TypeError, json.JSONDecodeError, ProviderProfileValidationError) as exc:
        raise ProviderProfileStoreCorruptError(
            "Tori's model provider profile store contains invalid data; it was not replaced."
        ) from exc


def _identifier(value: object) -> str:
    try:
        return validate_provider_identifier(value)
    except ValueError as exc:
        raise ProviderProfileValidationError(str(exc)) from exc


def _revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderProfileValidationError("expected_revision must be a positive integer.")
    return value


def _bounded_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ProviderProfileValidationError(
            f"{field} must be a non-empty string no longer than {limit} characters."
        )
    return value.strip()


def _timestamp(value: object) -> str:
    text = _bounded_text(value, "timestamp", 40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderProfileValidationError("timestamp is invalid.") from exc
    if parsed.tzinfo is None:
        raise ProviderProfileValidationError("timestamp must include a timezone.")
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_sql(value: str) -> str:
    return "".join(value.split()).lower()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly initialize Tori's model-provider profile store."
    )
    parser.add_argument("--initialize", action="store_true", required=True)
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    try:
        SQLiteProviderProfileStore(arguments.path).initialize()
    except ProviderProfileError as exc:
        print(f"Provider profile store initialization failed: {exc}")
        return 1
    print(
        "Initialized exact model-provider profile schema "
        f"{PROVIDER_PROFILE_SCHEMA_VERSION}: {arguments.path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
