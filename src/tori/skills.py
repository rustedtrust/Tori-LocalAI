"""Tori-owned Skills V1 models, lifecycle storage, and invocation boundary.

External Skill text is data.  It never supplies an adapter, permission grant,
origin, provider choice, or execution policy through this module.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import sqlite3
import stat
import threading
from types import MappingProxyType
from typing import Protocol
from urllib.parse import quote

from .capabilities import CapabilityResult, SourceRecord
from .capability_registry import Capability
from .request_origin import ConversationOperation, OriginAuthority, RequestOrigin


SKILL_MANIFEST_SCHEMA_VERSION = 0
SKILL_STORE_SCHEMA_VERSION = 1
DEFAULT_SKILL_DATABASE = Path("runtime/skills/registry.sqlite3")
MAX_TEXT = 4_000
MAX_INSTRUCTIONS = 32_000
MAX_ITEMS = 64

PERMISSION_KINDS = frozenset(
    {
        "file.read.selected",
        "file.write.new",
        "process.execute.approved",
        "network.connect.exact",
        "secret.use.named",
        "tori.read.operation",
    }
)

_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_STATES = frozenset({"installed_disabled", "enabled", "disabled", "uninstalled"})


class SkillError(RuntimeError):
    """A bounded application-owned Skill failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class SkillValidationError(SkillError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="skill_invalid")


class SkillStoreUnavailableError(SkillError):
    def __init__(self, message: str = "Tori's Skill registry is unavailable.") -> None:
        super().__init__(message, code="skill_store_unavailable")


class SkillStoreCorruptError(SkillError):
    def __init__(self, message: str = "Tori's Skill registry is invalid; it was not repaired.") -> None:
        super().__init__(message, code="skill_store_corrupt")


class SkillStoreVersionError(SkillStoreCorruptError):
    def __init__(self) -> None:
        super().__init__("Tori's Skill registry uses an unsupported schema version.")
        self.code = "skill_store_version"


class SkillConflictError(SkillError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="skill_conflict")


class SkillNotFoundError(SkillError):
    def __init__(self) -> None:
        super().__init__("That immutable Skill version was not found.", code="skill_not_found")


class SkillStateError(SkillError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="skill_state_invalid")


class SkillPermissionError(SkillError):
    def __init__(self, message: str = "That Skill operation is not authorized.") -> None:
        super().__init__(message, code="skill_permission_denied")


class SkillUnavailableError(SkillError):
    def __init__(self, message: str = "That Skill operation is unavailable.") -> None:
        super().__init__(message, code="skill_unavailable")


class SkillComponentKind(str, Enum):
    INSTRUCTION_ONLY = "instruction_only"
    MCP = "mcp"
    BOUNDED_EXECUTABLE = "bounded_executable"


@dataclass(frozen=True, slots=True)
class SkillIdentity:
    source_namespace: str
    publisher: str
    package_name: str

    def __post_init__(self) -> None:
        for name, value in (
            ("source namespace", self.source_namespace),
            ("publisher", self.publisher),
            ("package name", self.package_name),
        ):
            _require_slug(value, name)
        if self.source_namespace == "tori" or self.source_namespace.startswith("tori."):
            raise SkillValidationError("Imported Skills cannot use a Tori-reserved namespace.")

    @property
    def canonical_id(self) -> str:
        return f"{self.source_namespace}/{self.publisher}/{self.package_name}"

    def document(self) -> dict[str, str]:
        return {
            "source_namespace": self.source_namespace,
            "publisher": self.publisher,
            "package_name": self.package_name,
        }

    @classmethod
    def from_document(cls, value: object) -> SkillIdentity:
        item = _exact_mapping(value, {"source_namespace", "publisher", "package_name"}, "Skill identity")
        return cls(*(_text(item[key], key, 128) for key in ("source_namespace", "publisher", "package_name")))


@dataclass(frozen=True, slots=True)
class SkillSource:
    kind: str
    locator: str
    pinned_revision: str | None
    publisher_verified: bool

    def __post_init__(self) -> None:
        if self.kind not in {"local", "git"}:
            raise SkillValidationError("Skill source kind must be local or git.")
        _text(self.locator, "source locator", MAX_TEXT)
        if self.kind == "git":
            if not isinstance(self.pinned_revision, str) or _GIT_REVISION.fullmatch(self.pinned_revision) is None:
                raise SkillValidationError("Git Skill sources require an exact lowercase commit revision.")
        elif self.pinned_revision is not None:
            raise SkillValidationError("Local Skill sources cannot carry a Git revision.")
        if type(self.publisher_verified) is not bool:
            raise SkillValidationError("Publisher verification must be boolean.")

    def document(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "pinned_revision": self.pinned_revision,
            "publisher_verified": self.publisher_verified,
        }

    @classmethod
    def from_document(cls, value: object) -> SkillSource:
        item = _exact_mapping(value, {"kind", "locator", "pinned_revision", "publisher_verified"}, "Skill source")
        revision = item["pinned_revision"]
        if revision is not None:
            revision = _text(revision, "pinned revision", 40)
        return cls(
            _text(item["kind"], "source kind", 16),
            _text(item["locator"], "source locator", MAX_TEXT),
            revision,
            item["publisher_verified"],
        )


@dataclass(frozen=True, slots=True)
class SkillImport:
    format: str
    importer_version: str
    specification_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("import format", self.format),
            ("importer version", self.importer_version),
            ("specification version", self.specification_version),
        ):
            _require_slug(value, name)

    def document(self) -> dict[str, str]:
        return {
            "format": self.format,
            "importer_version": self.importer_version,
            "specification_version": self.specification_version,
        }

    @classmethod
    def from_document(cls, value: object) -> SkillImport:
        item = _exact_mapping(value, {"format", "importer_version", "specification_version"}, "Skill import")
        return cls(*(_text(item[key], key, 128) for key in ("format", "importer_version", "specification_version")))


@dataclass(frozen=True, slots=True)
class SkillInspection:
    inspected_at: str
    inspector_version: str
    findings: tuple[str, ...]

    def __post_init__(self) -> None:
        _timestamp(self.inspected_at)
        _require_slug(self.inspector_version, "inspector version")
        _bounded_text_tuple(self.findings, "inspection findings", MAX_ITEMS, MAX_TEXT)

    def document(self) -> dict[str, object]:
        return {
            "inspected_at": self.inspected_at,
            "inspector_version": self.inspector_version,
            "findings": list(self.findings),
        }

    @classmethod
    def from_document(cls, value: object) -> SkillInspection:
        item = _exact_mapping(value, {"inspected_at", "inspector_version", "findings"}, "Skill inspection")
        return cls(
            _text(item["inspected_at"], "inspection timestamp", 40),
            _text(item["inspector_version"], "inspector version", 128),
            _text_tuple(item["findings"], "inspection findings", MAX_ITEMS, MAX_TEXT),
        )


@dataclass(frozen=True, slots=True)
class SkillRequirements:
    executables: tuple[str, ...] = ()
    network_destinations: tuple[str, ...] = ()
    secret_handles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text_tuple(self.executables, "executables", MAX_ITEMS, MAX_TEXT)
        _bounded_text_tuple(self.network_destinations, "network destinations", MAX_ITEMS, MAX_TEXT)
        _bounded_text_tuple(self.secret_handles, "secret handles", MAX_ITEMS, 128)

    def document(self) -> dict[str, object]:
        return {
            "executables": list(self.executables),
            "network_destinations": list(self.network_destinations),
            "secret_handles": list(self.secret_handles),
        }

    @classmethod
    def from_document(cls, value: object) -> SkillRequirements:
        item = _exact_mapping(value, {"executables", "network_destinations", "secret_handles"}, "Skill requirements")
        return cls(
            _text_tuple(item["executables"], "executables", MAX_ITEMS, MAX_TEXT),
            _text_tuple(item["network_destinations"], "network destinations", MAX_ITEMS, MAX_TEXT),
            _text_tuple(item["secret_handles"], "secret handles", MAX_ITEMS, 128),
        )


@dataclass(frozen=True, slots=True)
class SkillPermission:
    kind: str
    scope: Mapping[str, str | int]

    def __post_init__(self) -> None:
        if self.kind not in PERMISSION_KINDS:
            raise SkillValidationError("Unknown Skill permission kind.")
        normalized = _permission_scope(self.kind, self.scope)
        object.__setattr__(self, "scope", MappingProxyType(normalized))

    @property
    def key(self) -> str:
        return _canonical_json(self.document())

    def document(self) -> dict[str, object]:
        return {"kind": self.kind, "scope": dict(self.scope)}

    @classmethod
    def from_document(cls, value: object) -> SkillPermission:
        item = _exact_mapping(value, {"kind", "scope"}, "Skill permission")
        kind = _text(item["kind"], "permission kind", 128)
        scope = item["scope"]
        if not isinstance(scope, Mapping):
            raise SkillValidationError("Skill permission scope must be an object.")
        return cls(kind, dict(scope))


@dataclass(frozen=True, slots=True)
class SkillFieldSchema:
    kind: str
    min_length: int | None = None
    max_length: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"string", "integer", "number", "boolean"}:
            raise SkillValidationError("Skill schema field type is unsupported.")
        if self.kind != "string" and (self.min_length is not None or self.max_length is not None):
            raise SkillValidationError("Only string fields accept length limits.")
        if self.kind == "string":
            if self.min_length is not None and (type(self.min_length) is not int or self.min_length < 0):
                raise SkillValidationError("String minimum length is invalid.")
            if self.max_length is None or type(self.max_length) is not int or not 1 <= self.max_length <= MAX_INSTRUCTIONS:
                raise SkillValidationError("String fields require a bounded maximum length.")
            if self.min_length is not None and self.min_length > self.max_length:
                raise SkillValidationError("String field length limits are inconsistent.")

    def document(self) -> dict[str, object]:
        result: dict[str, object] = {"type": self.kind}
        if self.min_length is not None:
            result["minLength"] = self.min_length
        if self.max_length is not None:
            result["maxLength"] = self.max_length
        return result

    @classmethod
    def from_document(cls, value: object) -> SkillFieldSchema:
        if not isinstance(value, Mapping):
            raise SkillValidationError("Skill schema field must be an object.")
        allowed = {"type", "minLength", "maxLength"}
        if set(value) - allowed or "type" not in value:
            raise SkillValidationError("Skill schema field has unknown or missing fields.")
        return cls(value["type"], value.get("minLength"), value.get("maxLength"))


@dataclass(frozen=True, slots=True)
class SkillObjectSchema:
    properties: Mapping[str, SkillFieldSchema]
    required: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.properties, Mapping) or len(self.properties) > MAX_ITEMS:
            raise SkillValidationError("Skill object schema properties are invalid.")
        normalized: dict[str, SkillFieldSchema] = {}
        for name, field in self.properties.items():
            _require_slug(name, "schema property")
            if not isinstance(field, SkillFieldSchema):
                raise SkillValidationError("Skill object schema field is invalid.")
            normalized[name] = field
        if not isinstance(self.required, tuple) or len(set(self.required)) != len(self.required):
            raise SkillValidationError("Skill schema required fields are invalid.")
        if any(name not in normalized for name in self.required):
            raise SkillValidationError("Skill schema requires an unknown property.")
        object.__setattr__(self, "properties", MappingProxyType(normalized))

    def document(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {name: field.document() for name, field in self.properties.items()},
            "required": list(self.required),
            "additionalProperties": False,
        }

    @classmethod
    def from_document(cls, value: object) -> SkillObjectSchema:
        item = _exact_mapping(value, {"type", "properties", "required", "additionalProperties"}, "Skill object schema")
        if item["type"] != "object" or item["additionalProperties"] is not False:
            raise SkillValidationError("Skill operation schemas must be closed objects.")
        properties = item["properties"]
        if not isinstance(properties, Mapping):
            raise SkillValidationError("Skill schema properties must be an object.")
        required = item["required"]
        if not isinstance(required, list):
            raise SkillValidationError("Skill schema required must be a list.")
        return cls(
            {name: SkillFieldSchema.from_document(field) for name, field in properties.items()},
            tuple(_text(name, "required property", 128) for name in required),
        )

    def validate(self, value: object) -> Mapping[str, str | int | float | bool]:
        if not isinstance(value, Mapping) or set(value) - set(self.properties):
            raise SkillValidationError("Skill operation input or output has unknown fields.")
        if any(name not in value for name in self.required):
            raise SkillValidationError("Skill operation input or output is missing a required field.")
        result: dict[str, str | int | float | bool] = {}
        for name, item in value.items():
            field = self.properties[name]
            if field.kind == "string":
                if not isinstance(item, str):
                    raise SkillValidationError("Skill operation field type is invalid.")
                if field.min_length is not None and len(item) < field.min_length:
                    raise SkillValidationError("Skill operation string is too short.")
                assert field.max_length is not None
                if len(item) > field.max_length or any(ord(character) < 32 and character not in "\t\n" for character in item):
                    raise SkillValidationError("Skill operation string is invalid or too long.")
            elif field.kind == "integer":
                if type(item) is not int:
                    raise SkillValidationError("Skill operation field type is invalid.")
            elif field.kind == "number":
                if type(item) not in {int, float} or not math.isfinite(item):
                    raise SkillValidationError("Skill operation field type is invalid.")
            elif field.kind == "boolean" and type(item) is not bool:
                raise SkillValidationError("Skill operation field type is invalid.")
            result[name] = item
        return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class SkillComponent:
    identifier: str
    kind: SkillComponentKind
    instructions: str

    def __post_init__(self) -> None:
        _require_slug(self.identifier, "component identifier")
        if not isinstance(self.kind, SkillComponentKind):
            raise SkillValidationError("Skill component kind is invalid.")
        _text(self.instructions, "Skill instructions", MAX_INSTRUCTIONS, allow_empty=True)

    def document(self) -> dict[str, str]:
        return {"id": self.identifier, "kind": self.kind.value, "instructions": self.instructions}

    @classmethod
    def from_document(cls, value: object) -> SkillComponent:
        item = _exact_mapping(value, {"id", "kind", "instructions"}, "Skill component")
        try:
            kind = SkillComponentKind(item["kind"])
        except (TypeError, ValueError) as exc:
            raise SkillValidationError("Skill component kind is invalid.") from exc
        return cls(
            _text(item["id"], "component identifier", 128),
            kind,
            _text(item["instructions"], "Skill instructions", MAX_INSTRUCTIONS, allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class SkillOperation:
    identifier: str
    component_id: str
    summary: str
    input_schema: SkillObjectSchema
    output_schema: SkillObjectSchema
    required_permissions: tuple[SkillPermission, ...]

    def __post_init__(self) -> None:
        _require_slug(self.identifier, "operation identifier")
        _require_slug(self.component_id, "component identifier")
        _text(self.summary, "operation summary", MAX_TEXT)
        if not isinstance(self.input_schema, SkillObjectSchema) or not isinstance(self.output_schema, SkillObjectSchema):
            raise SkillValidationError("Skill operation schema is invalid.")
        _permission_tuple(self.required_permissions)

    def document(self) -> dict[str, object]:
        return {
            "id": self.identifier,
            "component_id": self.component_id,
            "summary": self.summary,
            "input_schema": self.input_schema.document(),
            "output_schema": self.output_schema.document(),
            "required_permissions": [item.document() for item in self.required_permissions],
        }

    @classmethod
    def from_document(cls, value: object) -> SkillOperation:
        item = _exact_mapping(
            value,
            {"id", "component_id", "summary", "input_schema", "output_schema", "required_permissions"},
            "Skill operation",
        )
        permissions = item["required_permissions"]
        if not isinstance(permissions, list):
            raise SkillValidationError("Skill operation permissions must be a list.")
        return cls(
            _text(item["id"], "operation identifier", 128),
            _text(item["component_id"], "component identifier", 128),
            _text(item["summary"], "operation summary", MAX_TEXT),
            SkillObjectSchema.from_document(item["input_schema"]),
            SkillObjectSchema.from_document(item["output_schema"]),
            tuple(SkillPermission.from_document(permission) for permission in permissions),
        )


@dataclass(frozen=True, slots=True)
class SkillManifest:
    identity: SkillIdentity
    display_name: str
    version: str
    source: SkillSource
    content_digest: str
    import_metadata: SkillImport
    description: str
    components: tuple[SkillComponent, ...]
    operations: tuple[SkillOperation, ...]
    requested_permissions: tuple[SkillPermission, ...]
    requirements: SkillRequirements
    inspection: SkillInspection
    skill_contract_version: int = 0
    platforms: tuple[str, ...] = ("linux",)
    schema_version: int = SKILL_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SKILL_MANIFEST_SCHEMA_VERSION:
            raise SkillValidationError("Skill manifest schema version is unsupported.")
        if not isinstance(self.identity, SkillIdentity) or not isinstance(self.source, SkillSource):
            raise SkillValidationError("Skill identity or source is invalid.")
        _text(self.display_name, "display name", 128)
        _text(self.version, "Skill version", 128)
        if _DIGEST.fullmatch(self.content_digest) is None:
            raise SkillValidationError("Skill content digest must be a lowercase SHA-256 digest.")
        if not isinstance(self.import_metadata, SkillImport) or not isinstance(self.inspection, SkillInspection):
            raise SkillValidationError("Skill import or inspection evidence is invalid.")
        _text(self.description, "Skill description", MAX_TEXT, allow_empty=True)
        _bounded_object_tuple(self.components, SkillComponent, "Skill components")
        _bounded_object_tuple(self.operations, SkillOperation, "Skill operations")
        _permission_tuple(self.requested_permissions)
        if not isinstance(self.requirements, SkillRequirements):
            raise SkillValidationError("Skill requirements are invalid.")
        if type(self.skill_contract_version) is not int or self.skill_contract_version != 0:
            raise SkillValidationError("Skill contract version is unsupported.")
        _bounded_text_tuple(self.platforms, "Skill platforms", 8, 32)
        component_ids = [item.identifier for item in self.components]
        operation_ids = [item.identifier for item in self.operations]
        if len(set(component_ids)) != len(component_ids) or len(set(operation_ids)) != len(operation_ids):
            raise SkillValidationError("Skill component and operation identifiers must be unique.")
        if any(item.component_id not in component_ids for item in self.operations):
            raise SkillValidationError("Skill operation references an unknown component.")
        requested = {item.key for item in self.requested_permissions}
        if any(permission.key not in requested for operation in self.operations for permission in operation.required_permissions):
            raise SkillValidationError("Skill operation requires an undeclared permission.")

    @property
    def version_ref(self) -> SkillVersionRef:
        return SkillVersionRef(self.identity.canonical_id, self.version, self.content_digest)

    def component(self, identifier: str) -> SkillComponent:
        return next(item for item in self.components if item.identifier == identifier)

    def operation(self, identifier: str) -> SkillOperation:
        try:
            return next(item for item in self.operations if item.identifier == identifier)
        except StopIteration as exc:
            raise SkillNotFoundError() from exc

    def document(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.document(),
            "display_name": self.display_name,
            "version": self.version,
            "source": self.source.document(),
            "content_digest": self.content_digest,
            "import": self.import_metadata.document(),
            "description": self.description,
            "components": [item.document() for item in self.components],
            "operations": [item.document() for item in self.operations],
            "requested_permissions": [item.document() for item in self.requested_permissions],
            "requirements": self.requirements.document(),
            "inspection": self.inspection.document(),
            "compatibility": {
                "skill_contract_version": self.skill_contract_version,
                "platforms": list(self.platforms),
            },
        }

    @classmethod
    def from_document(cls, value: object) -> SkillManifest:
        item = _exact_mapping(
            value,
            {
                "schema_version", "identity", "display_name", "version", "source",
                "content_digest", "import", "description", "components", "operations",
                "requested_permissions", "requirements", "inspection", "compatibility",
            },
            "Skill manifest",
        )
        components = item["components"]
        operations = item["operations"]
        permissions = item["requested_permissions"]
        if not all(isinstance(value, list) for value in (components, operations, permissions)):
            raise SkillValidationError("Skill components, operations, and permissions must be lists.")
        compatibility = _exact_mapping(item["compatibility"], {"skill_contract_version", "platforms"}, "Skill compatibility")
        platforms = compatibility["platforms"]
        if not isinstance(platforms, list):
            raise SkillValidationError("Skill platforms must be a list.")
        return cls(
            identity=SkillIdentity.from_document(item["identity"]),
            display_name=_text(item["display_name"], "display name", 128),
            version=_text(item["version"], "Skill version", 128),
            source=SkillSource.from_document(item["source"]),
            content_digest=_text(item["content_digest"], "content digest", 71),
            import_metadata=SkillImport.from_document(item["import"]),
            description=_text(item["description"], "Skill description", MAX_TEXT, allow_empty=True),
            components=tuple(SkillComponent.from_document(component) for component in components),
            operations=tuple(SkillOperation.from_document(operation) for operation in operations),
            requested_permissions=tuple(SkillPermission.from_document(permission) for permission in permissions),
            requirements=SkillRequirements.from_document(item["requirements"]),
            inspection=SkillInspection.from_document(item["inspection"]),
            skill_contract_version=compatibility["skill_contract_version"],
            platforms=tuple(_text(platform, "Skill platform", 32) for platform in platforms),
            schema_version=item["schema_version"],
        )


@dataclass(frozen=True, slots=True)
class SkillVersionRef:
    skill_id: str
    version: str
    content_digest: str

    def __post_init__(self) -> None:
        parts = self.skill_id.split("/") if isinstance(self.skill_id, str) else []
        if len(parts) != 3:
            raise SkillValidationError("Canonical Skill identity is invalid.")
        SkillIdentity(*parts)
        _text(self.version, "Skill version", 128)
        if not isinstance(self.content_digest, str) or _DIGEST.fullmatch(self.content_digest) is None:
            raise SkillValidationError("Skill content digest is invalid.")


@dataclass(frozen=True, slots=True)
class SkillRegistryEntry:
    manifest: SkillManifest
    state: str
    granted_permissions: tuple[SkillPermission, ...]
    revision: int
    installed_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, SkillManifest):
            raise SkillStoreCorruptError()
        if self.state not in _STATES:
            raise SkillStoreCorruptError()
        _permission_tuple(self.granted_permissions)
        if type(self.revision) is not int or self.revision < 1:
            raise SkillStoreCorruptError()
        _timestamp(self.installed_at)
        _timestamp(self.updated_at)
        requested = {item.key for item in self.manifest.requested_permissions}
        if any(item.key not in requested for item in self.granted_permissions):
            raise SkillStoreCorruptError()
        if self.state in {"installed_disabled", "uninstalled"} and self.granted_permissions:
            raise SkillStoreCorruptError()


class SQLiteSkillRegistry:
    """Exact schema-1 durable lifecycle state for immutable Skill versions."""

    def __init__(
        self,
        path: Path = DEFAULT_SKILL_DATABASE,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def exists(self) -> bool:
        return self._safe_path(require_existing=False) is not None

    def initialize(self) -> None:
        with self._lock:
            if self.exists:
                raise SkillConflictError("The Skill registry already exists.")
            self._initialize_atomic()

    def install(self, manifest: SkillManifest) -> SkillRegistryEntry:
        if not isinstance(manifest, SkillManifest):
            raise SkillValidationError("A normalized Skill manifest is required.")
        with self._lock:
            connection = self._connect(readonly=False)
            now = _clock_timestamp(self._clock)
            document = _canonical_json(manifest.document())
            reference = manifest.version_ref
            try:
                with connection:
                    connection.execute(
                        "INSERT INTO skill_versions VALUES (?, ?, ?, ?)",
                        (reference.skill_id, reference.version, reference.content_digest, document),
                    )
                    connection.execute(
                        "INSERT INTO skill_registry VALUES (?, ?, ?, 'installed_disabled', '[]', 1, ?, ?)",
                        (reference.skill_id, reference.version, reference.content_digest, now, now),
                    )
            except sqlite3.IntegrityError as exc:
                raise SkillConflictError("That immutable Skill version is already registered.") from exc
            except sqlite3.Error as exc:
                raise SkillStoreUnavailableError() from exc
            finally:
                connection.close()
            return self.get(reference)

    def get(self, reference: SkillVersionRef) -> SkillRegistryEntry:
        if not isinstance(reference, SkillVersionRef):
            raise SkillValidationError("An exact Skill version reference is required.")
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                row = connection.execute(
                    "SELECT v.manifest_json, r.state, r.grants_json, r.revision, "
                    "r.installed_at, r.updated_at FROM skill_versions v JOIN skill_registry r "
                    "USING (skill_id, version, content_digest) WHERE skill_id=? AND version=? AND content_digest=?",
                    (reference.skill_id, reference.version, reference.content_digest),
                ).fetchone()
            except sqlite3.Error as exc:
                raise SkillStoreUnavailableError() from exc
            finally:
                connection.close()
        if row is None:
            raise SkillNotFoundError()
        return _entry_from_row(row)

    def list_entries(self) -> tuple[SkillRegistryEntry, ...]:
        if not self.exists:
            return ()
        with self._lock:
            connection = self._connect(readonly=True)
            try:
                rows = connection.execute(
                    "SELECT v.manifest_json, r.state, r.grants_json, r.revision, "
                    "r.installed_at, r.updated_at FROM skill_versions v JOIN skill_registry r "
                    "USING (skill_id, version, content_digest) "
                    "ORDER BY r.skill_id, r.version, r.content_digest"
                ).fetchall()
            except sqlite3.Error as exc:
                raise SkillStoreUnavailableError() from exc
            finally:
                connection.close()
        return tuple(_entry_from_row(row) for row in rows)

    @contextmanager
    def maintenance_guard(self) -> Iterator[None]:
        """Hold lifecycle state stable for a coordinated package snapshot."""

        with self._lock:
            if self.exists:
                connection = self._connect(readonly=True)
                connection.close()
            yield

    def disable_enabled_for_restore(self) -> int:
        """Fence restored authority while retaining grants for local review."""

        if not self.exists:
            return 0
        now = _clock_timestamp(self._clock)
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE skill_registry SET state='disabled', revision=revision+1, updated_at=? "
                        "WHERE state='enabled'",
                        (now,),
                    ).rowcount
            except sqlite3.Error as exc:
                raise SkillStoreUnavailableError() from exc
            finally:
                connection.close()
        return changed

    def enable(
        self,
        reference: SkillVersionRef,
        *,
        expected_revision: int,
        granted_permissions: Sequence[SkillPermission],
    ) -> SkillRegistryEntry:
        current = self.get(reference)
        revision = _revision(expected_revision)
        if current.revision != revision:
            raise SkillConflictError("The Skill lifecycle state changed; review it again.")
        if current.state not in {"installed_disabled", "disabled"}:
            raise SkillStateError("Only an installed-disabled or disabled Skill can be enabled.")
        grants = tuple(granted_permissions)
        _permission_tuple(grants)
        requested = {item.key for item in current.manifest.requested_permissions}
        if any(item.key not in requested for item in grants):
            raise SkillPermissionError("Tori cannot grant a permission the inspected Skill did not request.")
        return self._transition(current, "enabled", grants)

    def disable(self, reference: SkillVersionRef, *, expected_revision: int) -> SkillRegistryEntry:
        current = self.get(reference)
        if current.revision != _revision(expected_revision):
            raise SkillConflictError("The Skill lifecycle state changed; review it again.")
        if current.state != "enabled":
            raise SkillStateError("Only an enabled Skill can be disabled.")
        return self._transition(current, "disabled", current.granted_permissions)

    def uninstall(self, reference: SkillVersionRef, *, expected_revision: int) -> SkillRegistryEntry:
        current = self.get(reference)
        if current.revision != _revision(expected_revision):
            raise SkillConflictError("The Skill lifecycle state changed; review it again.")
        if current.state == "enabled":
            raise SkillStateError("Disable the Skill before uninstalling it.")
        if current.state == "uninstalled":
            raise SkillStateError("That Skill version is already uninstalled.")
        return self._transition(current, "uninstalled", ())

    def _transition(
        self,
        current: SkillRegistryEntry,
        state: str,
        grants: tuple[SkillPermission, ...],
    ) -> SkillRegistryEntry:
        reference = current.manifest.version_ref
        now = _clock_timestamp(self._clock)
        encoded = _canonical_json([item.document() for item in grants])
        with self._lock:
            connection = self._connect(readonly=False)
            try:
                with connection:
                    changed = connection.execute(
                        "UPDATE skill_registry SET state=?, grants_json=?, revision=revision+1, updated_at=? "
                        "WHERE skill_id=? AND version=? AND content_digest=? AND revision=?",
                        (state, encoded, now, reference.skill_id, reference.version,
                         reference.content_digest, current.revision),
                    ).rowcount
                if changed != 1:
                    raise SkillConflictError("The Skill lifecycle state changed; review it again.")
            except sqlite3.IntegrityError as exc:
                raise SkillConflictError("Another version of that Skill is already enabled.") from exc
            except SkillError:
                raise
            except sqlite3.Error as exc:
                raise SkillStoreUnavailableError() from exc
            finally:
                connection.close()
        return self.get(reference)

    def _initialize_atomic(self) -> None:
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._safe_parent()
            temporary = self._path.with_name(f".{self._path.name}.incomplete-{secrets.token_hex(16)}")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            connection = sqlite3.connect(temporary, timeout=5.0)
            try:
                _settings(connection)
                with connection:
                    connection.execute(
                        "CREATE TABLE skill_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    connection.execute(
                        "CREATE TABLE skill_versions ("
                        "skill_id TEXT NOT NULL, version TEXT NOT NULL, content_digest TEXT NOT NULL, "
                        "manifest_json TEXT NOT NULL, PRIMARY KEY(skill_id, version, content_digest))"
                    )
                    connection.execute(
                        "CREATE TABLE skill_registry ("
                        "skill_id TEXT NOT NULL, version TEXT NOT NULL, content_digest TEXT NOT NULL, "
                        "state TEXT NOT NULL CHECK(state IN ('installed_disabled','enabled','disabled','uninstalled')), "
                        "grants_json TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision >= 1), "
                        "installed_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                        "PRIMARY KEY(skill_id, version, content_digest), "
                        "FOREIGN KEY(skill_id, version, content_digest) REFERENCES skill_versions(skill_id, version, content_digest))"
                    )
                    connection.execute(
                        "CREATE UNIQUE INDEX one_enabled_skill_version ON skill_registry(skill_id) WHERE state='enabled'"
                    )
                    connection.execute(
                        "INSERT INTO skill_metadata VALUES ('schema_version', ?)",
                        (str(SKILL_STORE_SCHEMA_VERSION),),
                    )
                self._validate_schema(connection)
            finally:
                connection.close()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, self._path)
            temporary.unlink()
            temporary = None
            descriptor = os.open(self._path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._safe_path(require_existing=True)
        except FileExistsError as exc:
            raise SkillConflictError("The Skill registry already exists.") from exc
        except SkillError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SkillStoreUnavailableError("Tori could not initialize the Skill registry.") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        path = self._safe_path(require_existing=True)
        assert path is not None
        connection: sqlite3.Connection | None = None
        retain_connection = False
        try:
            if readonly:
                uri = f"file:{quote(os.fspath(path), safe='/')}?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            else:
                connection = sqlite3.connect(path, timeout=5.0, isolation_level="DEFERRED")
            connection.execute("PRAGMA foreign_keys = ON")
            self._validate_schema(connection)
            if not readonly:
                connection.execute("PRAGMA secure_delete = ON")
                connection.execute("PRAGMA journal_mode = DELETE")
            retain_connection = True
            return connection
        except SkillError:
            raise
        except sqlite3.DatabaseError as exc:
            raise SkillStoreCorruptError() from exc
        except (OSError, sqlite3.Error) as exc:
            raise SkillStoreUnavailableError() from exc
        finally:
            if connection is not None and not retain_connection:
                connection.close()

    def _safe_parent(self) -> Path:
        path = Path(os.path.abspath(os.path.normpath(os.fspath(self._path))))
        parent = path.parent
        current = Path(parent.anchor)
        missing = False
        for component in parent.parts[1:]:
            current /= component
            if missing:
                continue
            try:
                item = os.lstat(current)
            except FileNotFoundError:
                missing = True
                continue
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
                raise SkillStoreUnavailableError("The Skill registry parent path is unsafe.")
        if not missing:
            item = os.lstat(parent)
            if item.st_uid != os.geteuid() or item.st_mode & 0o022:
                raise SkillStoreUnavailableError("The Skill registry parent is not owner-controlled.")
        return path

    def _safe_path(self, *, require_existing: bool) -> Path | None:
        try:
            raw = os.fspath(self._path)
            if not isinstance(raw, str) or not raw or "\x00" in raw or ".." in Path(raw).parts:
                raise ValueError("unsafe Skill registry path")
            path = self._safe_parent()
            try:
                item = os.lstat(path)
            except FileNotFoundError:
                if require_existing:
                    raise SkillStoreUnavailableError()
                return None
            if (
                not stat.S_ISREG(item.st_mode)
                or stat.S_ISLNK(item.st_mode)
                or item.st_uid != os.geteuid()
                or stat.S_IMODE(item.st_mode) != 0o600
                or item.st_nlink != 1
            ):
                raise SkillStoreUnavailableError("The Skill registry file is unsafe.")
            return path
        except SkillError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise SkillStoreUnavailableError("The Skill registry path is unavailable or unsafe.") from exc

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise SkillStoreCorruptError()
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            indexes = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if tables != {"skill_metadata", "skill_versions", "skill_registry"} or indexes != {"one_enabled_skill_version"}:
                raise SkillStoreCorruptError()
            expected_columns = {
                "skill_metadata": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
                "skill_versions": (
                    ("skill_id", "TEXT", 1, 1), ("version", "TEXT", 1, 2),
                    ("content_digest", "TEXT", 1, 3), ("manifest_json", "TEXT", 1, 0),
                ),
                "skill_registry": (
                    ("skill_id", "TEXT", 1, 1), ("version", "TEXT", 1, 2),
                    ("content_digest", "TEXT", 1, 3), ("state", "TEXT", 1, 0),
                    ("grants_json", "TEXT", 1, 0), ("revision", "INTEGER", 1, 0),
                    ("installed_at", "TEXT", 1, 0), ("updated_at", "TEXT", 1, 0),
                ),
            }
            for table, expected in expected_columns.items():
                actual = tuple(
                    (row[1], row[2], row[3], row[5])
                    for row in connection.execute(f"PRAGMA table_info({table})")
                )
                if actual != expected:
                    raise SkillStoreCorruptError()
            foreign_keys = connection.execute("PRAGMA foreign_key_list(skill_registry)").fetchall()
            expected_foreign_keys = {
                ("skill_versions", "skill_id", "skill_id"),
                ("skill_versions", "version", "version"),
                ("skill_versions", "content_digest", "content_digest"),
            }
            if len(foreign_keys) != 3 or {(row[2], row[3], row[4]) for row in foreign_keys} != expected_foreign_keys:
                raise SkillStoreCorruptError()
            index_rows = connection.execute("PRAGMA index_list(skill_registry)").fetchall()
            custom_indexes = [row for row in index_rows if row[1] == "one_enabled_skill_version"]
            if len(custom_indexes) != 1 or custom_indexes[0][2] != 1 or custom_indexes[0][4] != 1:
                raise SkillStoreCorruptError()
            index_columns = connection.execute("PRAGMA index_info(one_enabled_skill_version)").fetchall()
            if [(row[1], row[2]) for row in index_columns] != [(0, "skill_id")]:
                raise SkillStoreCorruptError()
            index_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND name='one_enabled_skill_version'"
            ).fetchone()
            if index_sql != (
                "CREATE UNIQUE INDEX one_enabled_skill_version ON skill_registry(skill_id) WHERE state='enabled'",
            ):
                raise SkillStoreCorruptError()
            metadata = connection.execute("SELECT key, value FROM skill_metadata").fetchall()
            if metadata != [("schema_version", str(SKILL_STORE_SCHEMA_VERSION))]:
                if len(metadata) == 1 and metadata[0][0] == "schema_version":
                    raise SkillStoreVersionError()
                raise SkillStoreCorruptError()
        except SkillError:
            raise
        except sqlite3.DatabaseError as exc:
            raise SkillStoreCorruptError() from exc


@dataclass(frozen=True, slots=True)
class SkillInvocation:
    manifest: SkillManifest
    operation: SkillOperation
    inputs: Mapping[str, str | int | float | bool]
    untrusted_instructions: str


@dataclass(frozen=True, slots=True)
class SkillAdapterResult:
    status: str
    sources: tuple[SourceRecord, ...] = ()
    metadata: Mapping[str, str | int | float | bool] | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise SkillValidationError("Skill adapter status is invalid.")
        if not isinstance(self.sources, tuple) or any(not isinstance(item, SourceRecord) for item in self.sources):
            raise SkillValidationError("Skill adapter sources are invalid.")


class SkillOperationAdapter(Protocol):
    """Application-registered adapter; never loaded from a Skill package."""

    def supports(
        self,
        manifest: SkillManifest,
        operation: SkillOperation,
        component: SkillComponent,
    ) -> bool: ...

    def invoke(self, request: SkillInvocation) -> SkillAdapterResult: ...


class SkillApplicationService:
    """Own origin, grant, lifecycle, adapter selection, and result validation."""

    def __init__(
        self,
        registry: SQLiteSkillRegistry,
        adapters: Mapping[SkillComponentKind, SkillOperationAdapter] = (),
        *,
        origin_authority: OriginAuthority | None = None,
    ) -> None:
        self._registry = registry
        self._adapters = dict(adapters)
        if any(not isinstance(kind, SkillComponentKind) for kind in self._adapters):
            raise SkillValidationError("Skill adapters must be registered by component class.")
        self._origin_authority = origin_authority or OriginAuthority()

    @property
    def registry(self) -> SQLiteSkillRegistry:
        """Expose lifecycle inventory to trusted local administration services."""

        return self._registry

    def require_administration(self, origin: RequestOrigin) -> None:
        """Authorize a trusted facade before it stages durable Skill evidence."""

        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)

    def install(self, manifest: SkillManifest, *, origin: RequestOrigin) -> SkillRegistryEntry:
        self.require_administration(origin)
        return self._registry.install(manifest)

    def enable(
        self,
        reference: SkillVersionRef,
        *,
        expected_revision: int,
        granted_permissions: Sequence[SkillPermission],
        origin: RequestOrigin,
    ) -> SkillRegistryEntry:
        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        return self._registry.enable(
            reference,
            expected_revision=expected_revision,
            granted_permissions=granted_permissions,
        )

    def disable(
        self,
        reference: SkillVersionRef,
        *,
        expected_revision: int,
        origin: RequestOrigin,
    ) -> SkillRegistryEntry:
        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        return self._registry.disable(reference, expected_revision=expected_revision)

    def uninstall(
        self,
        reference: SkillVersionRef,
        *,
        expected_revision: int,
        origin: RequestOrigin,
    ) -> SkillRegistryEntry:
        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        return self._registry.uninstall(reference, expected_revision=expected_revision)

    def invoke(
        self,
        reference: SkillVersionRef,
        operation_id: str,
        inputs: object,
        *,
        origin: RequestOrigin,
    ) -> CapabilityResult:
        self._origin_authority.require(origin, ConversationOperation.SKILL_INVOKE)
        entry, operation, component, adapter = self._eligible(reference, operation_id)
        normalized_inputs = operation.input_schema.validate(inputs)
        request = SkillInvocation(
            manifest=entry.manifest,
            operation=operation,
            inputs=normalized_inputs,
            untrusted_instructions=component.instructions,
        )
        try:
            result = adapter.invoke(request)
        except SkillError:
            raise
        except Exception as exc:
            raise SkillUnavailableError("The approved Skill adapter failed.") from exc
        if not isinstance(result, SkillAdapterResult):
            raise SkillUnavailableError("The Skill adapter returned an invalid result.")
        metadata = operation.output_schema.validate(result.metadata or {})
        return CapabilityResult(
            capability_id=_capability_id(reference, operation.identifier),
            input_text=_canonical_json(dict(normalized_inputs)),
            status=result.status,
            sources=result.sources,
            metadata=metadata,
        )

    def eligible_capabilities(self, *, origin: RequestOrigin) -> tuple[Capability, ...]:
        if not self._origin_authority.permits(origin, ConversationOperation.SKILL_INVOKE):
            return ()
        result: list[Capability] = []
        for entry in self._registry.list_entries():
            if entry.state != "enabled":
                continue
            for operation in entry.manifest.operations:
                component = entry.manifest.component(operation.component_id)
                adapter = self._adapters.get(component.kind)
                if (
                    adapter is None
                    or not _adapter_supports(adapter, entry.manifest, operation, component)
                    or not _adapter_available(adapter, entry.manifest, operation, component)
                    or not _permissions_cover(entry, operation)
                ):
                    continue
                result.append(
                    Capability(
                        identifier=_capability_id(entry.manifest.version_ref, operation.identifier),
                        name=f"Skill {entry.manifest.identity.canonical_id}/{operation.identifier}",
                        terms=(),
                        scope="approved local Skill operation",
                        boundary="Tori-owned lifecycle, origin and permission checks apply",
                    )
                )
                if len(result) >= MAX_ITEMS:
                    return tuple(result)
        return tuple(result)

    def compatibility_status(self, manifest: SkillManifest) -> str:
        """Return format compatibility from Tori-owned adapter support.

        External importer findings refine instruction-Skill compatibility only
        after an application adapter admits every declared operation. They do
        not determine whether a built-in or other component class is supported.
        """

        if not isinstance(manifest, SkillManifest) or manifest.skill_contract_version != 0:
            return "unsupported"
        for operation in manifest.operations:
            component = manifest.component(operation.component_id)
            adapter = self._adapters.get(component.kind)
            if adapter is None or not _adapter_supports(
                adapter, manifest, operation, component
            ):
                return "unsupported"
        if manifest.import_metadata.format != "agent-skills":
            return "compatible"
        prefix = "compatibility_status="
        reported = next(
            (
                item[len(prefix):]
                for item in manifest.inspection.findings
                if item.startswith(prefix)
            ),
            None,
        )
        if reported in {
            "compatible",
            "compatible_instruction_only",
            "partially_compatible",
        }:
            return reported
        return "compatible_instruction_only"

    def eligible_operations(
        self, reference: SkillVersionRef, *, origin: RequestOrigin
    ) -> tuple[str, ...]:
        """Return operation ids currently admitted by the same invocation gate."""

        if not self._origin_authority.permits(origin, ConversationOperation.SKILL_INVOKE):
            return ()
        try:
            entry = self._registry.get(reference)
        except SkillError:
            return ()
        result: list[str] = []
        for operation in entry.manifest.operations:
            try:
                self._eligible(reference, operation.identifier)
            except SkillError:
                continue
            result.append(operation.identifier)
        return tuple(result)

    def _eligible(
        self, reference: SkillVersionRef, operation_id: str
    ) -> tuple[SkillRegistryEntry, SkillOperation, SkillComponent, SkillOperationAdapter]:
        entry = self._registry.get(reference)
        if entry.state != "enabled":
            raise SkillUnavailableError("That Skill version is not enabled.")
        operation = entry.manifest.operation(_text(operation_id, "operation identifier", 128))
        component = entry.manifest.component(operation.component_id)
        adapter = self._adapters.get(component.kind)
        if adapter is None:
            raise SkillUnavailableError("That Skill component class has no approved adapter.")
        if not _adapter_supports(adapter, entry.manifest, operation, component):
            raise SkillUnavailableError("No approved adapter admits that exact Skill operation.")
        if not _adapter_available(adapter, entry.manifest, operation, component):
            raise SkillUnavailableError("That approved Skill adapter is unavailable on this host.")
        if not _permissions_cover(entry, operation):
            raise SkillPermissionError()
        return entry, operation, component, adapter


def digest_package_entries(entries: Mapping[str, bytes]) -> str:
    """Hash a bounded, path-sorted, in-memory package fixture without execution."""

    if not isinstance(entries, Mapping) or not entries or len(entries) > MAX_ITEMS:
        raise SkillValidationError("Skill package entries are invalid or empty.")
    digest = hashlib.sha256()
    total = 0
    for path in sorted(entries):
        if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
            raise SkillValidationError("Skill package path is invalid.")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or ".." in parsed.parts or "." in parsed.parts:
            raise SkillValidationError("Skill package path escapes its package root.")
        content = entries[path]
        if not isinstance(content, bytes):
            raise SkillValidationError("Skill package content must be bytes.")
        total += len(content)
        if total > 4 * 1024 * 1024:
            raise SkillValidationError("Skill package fixture is too large.")
        encoded = path.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def _entry_from_row(row: Sequence[object]) -> SkillRegistryEntry:
    try:
        manifest_value = json.loads(row[0])
        grants_value = json.loads(row[2])
        if not isinstance(grants_value, list):
            raise ValueError("invalid grants")
        return SkillRegistryEntry(
            manifest=SkillManifest.from_document(manifest_value),
            state=row[1],
            granted_permissions=tuple(SkillPermission.from_document(item) for item in grants_value),
            revision=row[3],
            installed_at=row[4],
            updated_at=row[5],
        )
    except SkillStoreCorruptError:
        raise
    except (SkillError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SkillStoreCorruptError() from exc


def _permissions_cover(entry: SkillRegistryEntry, operation: SkillOperation) -> bool:
    granted = {item.key for item in entry.granted_permissions}
    return all(item.key in granted for item in operation.required_permissions)


def _adapter_supports(
    adapter: SkillOperationAdapter,
    manifest: SkillManifest,
    operation: SkillOperation,
    component: SkillComponent,
) -> bool:
    try:
        return adapter.supports(manifest, operation, component) is True
    except Exception:
        return False


def _adapter_available(
    adapter: SkillOperationAdapter,
    manifest: SkillManifest,
    operation: SkillOperation,
    component: SkillComponent,
) -> bool:
    check = getattr(adapter, "available", None)
    if check is None:
        return True
    try:
        return check(manifest, operation, component) is True
    except Exception:
        return False


def _capability_id(reference: SkillVersionRef, operation_id: str) -> str:
    identity = reference.skill_id.replace("/", ".")
    exact_version = hashlib.sha256(
        f"{reference.version}\0{reference.content_digest}".encode("utf-8")
    ).hexdigest()[:12]
    return f"skill.{identity}.{operation_id}.{exact_version}"


def _permission_scope(kind: str, value: object) -> dict[str, str | int]:
    if not isinstance(value, Mapping):
        raise SkillValidationError("Skill permission scope must be an object.")
    expected: dict[str, type] = {
        "file.read.selected": {},
        "file.write.new": {},
        "process.execute.approved": {"executable": str, "adapter": str},
        "network.connect.exact": {"scheme": str, "host": str, "port": int},
        "secret.use.named": {"handle": str, "audience": str},
        "tori.read.operation": {"operation": str},
    }[kind]
    if set(value) != set(expected):
        raise SkillValidationError("Skill permission scope has unknown or missing fields.")
    result: dict[str, str | int] = {}
    for name, expected_type in expected.items():
        item = value[name]
        if expected_type is int:
            if type(item) is not int or not 1 <= item <= 65535:
                raise SkillValidationError("Skill network port is invalid.")
        else:
            item = _text(item, f"permission {name}", MAX_TEXT)
        result[name] = item
    if kind == "process.execute.approved":
        executable = str(result["executable"])
        parsed = PurePosixPath(executable)
        if not parsed.is_absolute() or ".." in parsed.parts or os.path.normpath(executable) != executable:
            raise SkillValidationError("Approved Skill executable must be absolute.")
        _require_slug(str(result["adapter"]), "executable adapter")
    elif kind == "network.connect.exact":
        if result["scheme"] not in {"http", "https"}:
            raise SkillValidationError("Skill network scheme is invalid.")
        host = str(result["host"]).lower()
        try:
            ipaddress.ip_address(host)
            valid_host = True
        except ValueError:
            labels = host.rstrip(".").split(".")
            valid_host = (
                len(host) <= 253
                and all(
                    1 <= len(label) <= 63
                    and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is not None
                    for label in labels
                )
            )
        if not valid_host:
            raise SkillValidationError("Skill network host is invalid.")
        result["host"] = host
    elif kind == "secret.use.named":
        _require_slug(str(result["handle"]), "secret handle")
        _require_slug(str(result["audience"]), "secret audience")
    elif kind == "tori.read.operation":
        _require_slug(str(result["operation"]), "Tori read operation")
    return result


def _exact_mapping(value: object, fields: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise SkillValidationError(f"{label} has unknown or missing fields.")
    return value


def _text(value: object, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty) or len(value) > maximum or "\x00" in value:
        raise SkillValidationError(f"{label} is invalid or too long.")
    if any(ord(character) < 32 and character not in "\t\n" for character in value):
        raise SkillValidationError(f"{label} contains unsupported control characters.")
    return value


def _require_slug(value: object, label: str) -> str:
    text = _text(value, label, 128)
    if _SLUG.fullmatch(text) is None:
        raise SkillValidationError(f"{label} must be a lowercase stable identifier.")
    return text


def _text_tuple(value: object, label: str, maximum_items: int, maximum_text: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise SkillValidationError(f"{label} must be a bounded list.")
    result = tuple(_text(item, label, maximum_text) for item in value)
    if len(set(result)) != len(result):
        raise SkillValidationError(f"{label} contains duplicates.")
    return result


def _bounded_text_tuple(value: object, label: str, maximum_items: int, maximum_text: int) -> None:
    if not isinstance(value, tuple) or len(value) > maximum_items:
        raise SkillValidationError(f"{label} must be a bounded tuple.")
    normalized = tuple(_text(item, label, maximum_text) for item in value)
    if len(set(normalized)) != len(normalized):
        raise SkillValidationError(f"{label} contains duplicates.")


def _bounded_object_tuple(value: object, expected: type, label: str) -> None:
    if not isinstance(value, tuple) or not value or len(value) > MAX_ITEMS or any(not isinstance(item, expected) for item in value):
        raise SkillValidationError(f"{label} must be a non-empty bounded tuple.")


def _permission_tuple(value: object) -> None:
    if not isinstance(value, tuple) or len(value) > MAX_ITEMS or any(not isinstance(item, SkillPermission) for item in value):
        raise SkillValidationError("Skill permissions must be a bounded tuple.")
    keys = tuple(item.key for item in value)
    if len(set(keys)) != len(keys):
        raise SkillValidationError("Skill permissions contain duplicates.")


def _timestamp(value: object) -> str:
    text = _text(value, "timestamp", 40)
    if _UTC_TIMESTAMP.fullmatch(text) is None:
        raise SkillValidationError("Skill timestamp must be UTC RFC 3339 text.")
    try:
        datetime.fromisoformat(text.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise SkillValidationError("Skill timestamp is invalid.") from exc
    return text


def _clock_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SkillStoreUnavailableError("The Skill registry clock is invalid.")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _revision(value: object) -> int:
    if type(value) is not int or value < 1:
        raise SkillValidationError("Skill lifecycle revision is invalid.")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SkillValidationError("Skill data is not canonical JSON.") from exc


def _settings(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA secure_delete = ON")
    connection.execute("PRAGMA journal_mode = DELETE")
