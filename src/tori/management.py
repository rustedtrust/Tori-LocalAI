"""Typed local management operations shared by Tori's interfaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata

from .checkpoints import (
    CheckpointConflictError,
    CheckpointError,
    CheckpointFormatError,
    CheckpointMetadata,
    CheckpointNotFoundError,
    CheckpointStore,
    CheckpointVerificationError,
    CheckpointVersionError,
    ConversationCheckpoint,
)
from .knowledge import (
    InvalidRegistration,
    KnowledgeConflictError,
    KnowledgeError,
    KnowledgeFormatError,
    KnowledgeLimitError,
    KnowledgeNotFoundError,
    KnowledgeRegistry,
    KnowledgeSource,
    KnowledgeUnavailableError,
    KnowledgeValidationError,
    KnowledgeVerificationError,
    SourceStatus,
)
from .providers import validate_model_identity
from .memory import (
    MemoryConflictError,
    MemoryCorruptError,
    MemoryError,
    MemoryNotFoundError,
    MemoryPolicyError,
    MemoryRecord,
    MemoryStaleError,
    MemoryUnavailableError,
    MemoryValidationError,
    MemoryVerificationError,
    MemoryVersionError,
    SQLiteMemoryStore,
)
from .providers import ChatMessage


CHECKPOINT_REMOVE = "checkpoint_remove"
MEMORY_FORGET = "memory_forget"
KNOWLEDGE_REMOVE = "knowledge_remove"
_CHECKPOINT_IDENTIFIER_PATTERN = re.compile(
    r"^cp-\d{8}T\d{6}Z-[0-9a-f]{8}$"
)


class ManagementError(RuntimeError):
    """One safe, stable interface-independent management failure."""

    def __init__(self, message: str, *, code: str, subsystem: str) -> None:
        super().__init__(message)
        self.code = code
        self.subsystem = subsystem


@dataclass(frozen=True, slots=True)
class CheckpointItem:
    identifier: str
    display_name: str | None
    created_at: str
    provider: str
    model: str
    message_count: int


@dataclass(frozen=True, slots=True)
class MemoryItem:
    identifier: str
    text: str
    category: str
    sensitivity: str
    provenance: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class KnowledgeSourceItem:
    identifier: str
    filename: str
    display_path: str
    file_type: str
    registered_at: str
    availability: str
    byte_size: int | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class InvalidRegistrationItem:
    filename: str
    detail: str


@dataclass(frozen=True, slots=True)
class KnowledgeItems:
    sources: tuple[KnowledgeSourceItem, ...]
    invalid_registrations: tuple[InvalidRegistrationItem, ...]


@dataclass(frozen=True, slots=True)
class ConfirmationTarget:
    action: str
    identifier: str
    fingerprint: str
    summary: dict[str, object]


class ManagementService:
    """Coordinate only Tori's established explicit persistence stores."""

    def __init__(
        self,
        *,
        checkpoint_store: CheckpointStore,
        memory_store: SQLiteMemoryStore | None,
        knowledge_registry: KnowledgeRegistry | None,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._checkpoint_store = checkpoint_store
        self._memory_store = memory_store
        self._knowledge_registry = knowledge_registry
        self._provider_name = provider_name
        self._model_name = model_name

    def select_model(self, provider_name: str, model_name: str) -> None:
        """Update attribution used by later explicit checkpoint/memory writes."""

        identity = validate_model_identity(provider_name, model_name)
        self._provider_name = identity.provider
        self._model_name = identity.model

    @property
    def checkpoint_root(self) -> str:
        return safe_display(str(self._checkpoint_store.root))

    @property
    def knowledge_root(self) -> str:
        return safe_display(str(self._require_knowledge().root))

    def list_checkpoints(self) -> tuple[CheckpointItem, ...]:
        try:
            return tuple(
                _checkpoint_item(item)
                for item in self._checkpoint_store.list_checkpoints()
            )
        except CheckpointError as exc:
            raise _checkpoint_management_error(exc) from exc

    def save_checkpoint(
        self,
        history: Sequence[ChatMessage],
        *,
        display_name: str | None,
    ) -> CheckpointItem:
        try:
            metadata = self._checkpoint_store.save_checkpoint(
                history,
                display_name=display_name,
                provider=self._provider_name,
                model=self._model_name,
            )
            return _checkpoint_item(metadata)
        except CheckpointError as exc:
            raise _checkpoint_management_error(
                exc,
                caller_validation=True,
            ) from exc

    def checkpoint_removal_target(
        self, identifier: str
    ) -> ConfirmationTarget:
        if (
            not isinstance(identifier, str)
            or not _CHECKPOINT_IDENTIFIER_PATTERN.fullmatch(identifier)
        ):
            raise ManagementError(
                "Checkpoint identifier is invalid.",
                code="invalid_field",
                subsystem="checkpoint",
            )
        try:
            checkpoint = self._checkpoint_store.load_checkpoint(identifier)
        except CheckpointError as exc:
            raise _checkpoint_management_error(exc) from exc
        item = _checkpoint_item(checkpoint.metadata)
        return ConfirmationTarget(
            action=CHECKPOINT_REMOVE,
            identifier=item.identifier,
            fingerprint=_checkpoint_fingerprint(checkpoint),
            summary={
                "identifier": item.identifier,
                "display_name": item.display_name,
                "created_at": item.created_at,
                "message_count": item.message_count,
            },
        )

    def remove_checkpoint(self, target: ConfirmationTarget) -> CheckpointItem:
        _require_action(target, CHECKPOINT_REMOVE)
        try:
            current = self._checkpoint_store.load_checkpoint(target.identifier)
            if _checkpoint_fingerprint(current) != target.fingerprint:
                raise ManagementError(
                    "That checkpoint changed after confirmation; nothing was "
                    "removed.",
                    code="stale_target",
                    subsystem="checkpoint",
                )
            return _checkpoint_item(
                self._checkpoint_store.remove_checkpoint(target.identifier)
            )
        except ManagementError:
            raise
        except CheckpointError as exc:
            raise _checkpoint_management_error(exc) from exc

    def list_memories(self) -> tuple[MemoryItem, ...]:
        store = self._require_memory()
        try:
            return tuple(_memory_item(item) for item in sorted(
                store.list_memories(),
                key=lambda item: (item.created_at, item.identifier), reverse=True,
            ))
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def create_memory(self, text: str) -> MemoryItem:
        store = self._require_memory()
        try:
            return _memory_item(store.create(text))
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def update_memory(
        self,
        identifier: str,
        text: str,
        *,
        expected_updated_at: str,
    ) -> MemoryItem:
        store = self._require_memory()
        try:
            return _memory_item(
                store.update_if_current(
                    identifier,
                    text,
                    expected_updated_at=expected_updated_at,
                )
            )
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def update_memory_unconditionally(
        self, identifier: str, text: str
    ) -> MemoryItem:
        """Preserve the CLI's established direct update behavior."""

        store = self._require_memory()
        try:
            return _memory_item(store.update(identifier, text))
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def memory_forget_target(
        self,
        identifier: str,
        *,
        expected_updated_at: str | None = None,
    ) -> ConfirmationTarget:
        store = self._require_memory()
        try:
            record = store.get(identifier)
            if record is None:
                raise MemoryNotFoundError(f"Memory {identifier} was not found.")
            if (
                expected_updated_at is not None
                and record.updated_at != expected_updated_at
            ):
                raise MemoryStaleError(
                    f"Memory {record.identifier} changed after it was loaded; "
                    "refresh and try again."
                )
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc
        item = _memory_item(record)
        return ConfirmationTarget(
            action=MEMORY_FORGET,
            identifier=item.identifier,
            fingerprint=item.updated_at,
            summary={
                "identifier": item.identifier,
                "text": item.text,
                "updated_at": item.updated_at,
            },
        )

    def forget_memory(self, target: ConfirmationTarget) -> MemoryItem:
        _require_action(target, MEMORY_FORGET)
        store = self._require_memory()
        try:
            current = store.get(target.identifier)
            if current is None:
                raise MemoryNotFoundError(
                    f"Memory {target.identifier} was not found."
                )
            if current.updated_at != target.fingerprint:
                raise MemoryStaleError(
                    f"Memory {target.identifier} changed after confirmation; "
                    "nothing was removed."
                )
            store.delete_if_current(
                target.identifier,
                expected_updated_at=target.fingerprint,
            )
            return _memory_item(current)
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def remove_memory_unconditionally(self, identifier: str) -> MemoryItem:
        """Preserve the CLI's established exact-phrase confirmation flow."""

        store = self._require_memory()
        try:
            current = store.get(identifier)
            if current is None:
                raise MemoryNotFoundError(
                    f"Memory {identifier} was not found."
                )
            store.delete(current.identifier)
            return _memory_item(current)
        except MemoryError as exc:
            raise _management_error(exc, "memory") from exc

    def list_knowledge(self) -> KnowledgeItems:
        registry = self._require_knowledge()
        try:
            listing = registry.list_sources()
            return KnowledgeItems(
                sources=tuple(
                    _knowledge_source_item(status)
                    for status in listing.sources
                ),
                invalid_registrations=tuple(
                    _invalid_registration_item(record)
                    for record in listing.invalid_records
                ),
            )
        except KnowledgeError as exc:
            raise _management_error(exc, "knowledge") from exc

    def register_knowledge(self, path: str) -> KnowledgeSourceItem:
        registry = self._require_knowledge()
        try:
            source = registry.register(path)
            listing = registry.list_sources()
            for status in listing.sources:
                if status.source.identifier == source.identifier:
                    return _knowledge_source_item(status)
            raise KnowledgeVerificationError(
                f"Registration {source.identifier} could not be verified."
            )
        except KnowledgeError as exc:
            raise _management_error(exc, "knowledge") from exc

    def knowledge_removal_target(
        self, identifier: str
    ) -> ConfirmationTarget:
        registry = self._require_knowledge()
        try:
            source = registry.get(identifier)
            if source is None:
                raise KnowledgeNotFoundError(
                    f"Knowledge source {identifier} was not found."
                )
        except KnowledgeError as exc:
            raise _management_error(exc, "knowledge") from exc
        return ConfirmationTarget(
            action=KNOWLEDGE_REMOVE,
            identifier=source.identifier,
            fingerprint=_knowledge_fingerprint(source),
            summary={
                "identifier": source.identifier,
                "filename": safe_display(source.filename),
                "display_path": safe_display(source.path),
                "source_unchanged": True,
            },
        )

    def remove_knowledge(
        self, target: ConfirmationTarget
    ) -> KnowledgeSourceItem:
        _require_action(target, KNOWLEDGE_REMOVE)
        registry = self._require_knowledge()
        try:
            current = registry.get(target.identifier)
            if current is None:
                raise KnowledgeNotFoundError(
                    f"Knowledge source {target.identifier} was not found."
                )
            if _knowledge_fingerprint(current) != target.fingerprint:
                raise ManagementError(
                    "That knowledge registration changed after confirmation; "
                    "nothing was removed.",
                    code="stale_target",
                    subsystem="knowledge",
                )
            removed = registry.remove(target.identifier)
            return KnowledgeSourceItem(
                identifier=removed.identifier,
                filename=safe_display(removed.filename),
                display_path=safe_display(removed.path),
                file_type=removed.file_type,
                registered_at=removed.registered_at,
                availability="removed",
                byte_size=None,
                detail=None,
            )
        except ManagementError:
            raise
        except KnowledgeError as exc:
            raise _management_error(exc, "knowledge") from exc

    def remove_knowledge_unconditionally(
        self, identifier: str
    ) -> KnowledgeSourceItem:
        """Preserve the slash command's established direct removal behavior."""

        registry = self._require_knowledge()
        try:
            removed = registry.remove(identifier)
            return KnowledgeSourceItem(
                identifier=removed.identifier,
                filename=safe_display(removed.filename),
                display_path=safe_display(removed.path),
                file_type=removed.file_type,
                registered_at=removed.registered_at,
                availability="removed",
                byte_size=None,
                detail=None,
            )
        except KnowledgeError as exc:
            raise _management_error(exc, "knowledge") from exc

    def _require_memory(self) -> SQLiteMemoryStore:
        if self._memory_store is None:
            raise ManagementError(
                "Tori's canonical memory store is unavailable.",
                code="store_unavailable",
                subsystem="memory",
            )
        return self._memory_store

    def _require_knowledge(self) -> KnowledgeRegistry:
        if self._knowledge_registry is None:
            raise ManagementError(
                "Tori's local knowledge registry is unavailable.",
                code="store_unavailable",
                subsystem="knowledge",
            )
        return self._knowledge_registry


def safe_display(value: str) -> str:
    """Return filesystem-derived text safe for plain terminal and DOM display."""

    unsafe_categories = {"Cc", "Cf", "Cs", "Zl", "Zp"}
    if any(
        unicodedata.category(character) in unsafe_categories
        for character in value
    ):
        return ascii(value)
    return value


def _checkpoint_item(metadata: CheckpointMetadata) -> CheckpointItem:
    return CheckpointItem(
        identifier=metadata.identifier,
        display_name=metadata.display_name,
        created_at=metadata.created_at,
        provider=metadata.provider,
        model=metadata.model,
        message_count=metadata.message_count,
    )


def _memory_item(record: MemoryRecord) -> MemoryItem:
    return MemoryItem(
        identifier=record.identifier,
        text=record.text,
        category=record.category,
        sensitivity=record.sensitivity,
        provenance=record.provenance,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _knowledge_source_item(status: SourceStatus) -> KnowledgeSourceItem:
    return KnowledgeSourceItem(
        identifier=status.source.identifier,
        filename=safe_display(status.source.filename),
        display_path=safe_display(status.source.path),
        file_type=status.source.file_type,
        registered_at=status.source.registered_at,
        availability=status.availability,
        byte_size=status.byte_size,
        detail=safe_display(status.detail) if status.detail is not None else None,
    )


def _invalid_registration_item(
    record: InvalidRegistration,
) -> InvalidRegistrationItem:
    return InvalidRegistrationItem(
        filename=safe_display(record.filename),
        detail=safe_display(record.detail),
    )


def _checkpoint_fingerprint(checkpoint: ConversationCheckpoint) -> str:
    return _fingerprint(
        {
            "metadata": {
                "identifier": checkpoint.metadata.identifier,
                "display_name": checkpoint.metadata.display_name,
                "created_at": checkpoint.metadata.created_at,
                "provider": checkpoint.metadata.provider,
                "model": checkpoint.metadata.model,
                "message_count": checkpoint.metadata.message_count,
            },
            "messages": [
                {"role": message.role, "content": message.content}
                for message in checkpoint.messages
            ],
        }
    )


def _knowledge_fingerprint(source: KnowledgeSource) -> str:
    return _fingerprint(
        {
            "identifier": source.identifier,
            "path": source.path,
            "filename": source.filename,
            "file_type": source.file_type,
            "registered_at": source.registered_at,
        }
    )


def _fingerprint(document: object) -> str:
    encoded = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_action(target: ConfirmationTarget, action: str) -> None:
    if target.action != action:
        raise ManagementError(
            "That confirmation cannot be used for this action.",
            code="invalid_confirmation",
            subsystem="confirmation",
        )


def _management_error(error: Exception, subsystem: str) -> ManagementError:
    if isinstance(error, MemoryPolicyError):
        code = "policy_rejection"
    elif isinstance(
        error,
        (CheckpointNotFoundError, MemoryNotFoundError, KnowledgeNotFoundError),
    ):
        code = "not_found"
    elif isinstance(error, MemoryStaleError):
        code = "stale_target"
    elif isinstance(
        error,
        (
            CheckpointConflictError,
            MemoryConflictError,
            KnowledgeConflictError,
            KnowledgeLimitError,
        ),
    ):
        code = "conflict"
    elif isinstance(
        error,
        (
            CheckpointFormatError,
            MemoryValidationError,
            KnowledgeValidationError,
        ),
    ):
        code = "invalid_field"
    elif isinstance(
        error,
        (MemoryCorruptError, MemoryVersionError, KnowledgeFormatError),
    ):
        code = "store_corrupt"
    elif isinstance(
        error,
        (MemoryUnavailableError, KnowledgeUnavailableError),
    ):
        code = "store_unavailable"
    elif isinstance(
        error,
        (
            CheckpointVerificationError,
            MemoryVerificationError,
            KnowledgeVerificationError,
        ),
    ):
        code = "verification_failed"
    else:
        code = "store_error"
    return ManagementError(str(error), code=code, subsystem=subsystem)


def _checkpoint_management_error(
    error: CheckpointError,
    *,
    caller_validation: bool = False,
) -> ManagementError:
    """Convert checkpoint failures without exposing filesystem diagnostics."""

    if isinstance(error, CheckpointNotFoundError):
        code = "not_found"
        message = "The selected checkpoint was not found."
    elif isinstance(error, CheckpointVerificationError):
        code = "verification_failed"
        message = "The checkpoint change could not be verified."
    elif isinstance(error, CheckpointVersionError):
        code = "store_corrupt"
        message = (
            "Checkpoint storage contains an unsupported checkpoint record."
        )
    elif isinstance(error, CheckpointFormatError):
        if caller_validation:
            code = "invalid_field"
            # CheckpointStore's save-time validation messages are fixed,
            # content-free caller guidance. Persisted records never use this
            # branch.
            message = str(error)
        else:
            code = "store_corrupt"
            message = "Checkpoint storage contains an invalid checkpoint record."
    elif isinstance(error, CheckpointConflictError):
        code = "conflict"
        message = "A checkpoint with that identifier already exists."
    else:
        code = "store_unavailable"
        message = "Checkpoint storage is unavailable."
    return ManagementError(message, code=code, subsystem="checkpoint")
