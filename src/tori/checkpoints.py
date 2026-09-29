"""Explicit local conversation checkpoints for Tori.

Checkpoints are user-approved saved conversations. They are not Tori's
long-term memory system and are never created automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from .providers import ChatMessage


CHECKPOINT_SCHEMA_VERSION = 1
DEFAULT_CHECKPOINT_DIRECTORY = Path("runtime/checkpoints")
MAX_CHECKPOINT_MESSAGES = 20
MAX_DISPLAY_NAME_LENGTH = 80

_IDENTIFIER_PATTERN = re.compile(
    r"^cp-\d{8}T\d{6}Z-[0-9a-f]{8}$"
)
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)

Clock = Callable[[], datetime]
IdentifierFactory = Callable[[], str]


class CheckpointError(RuntimeError):
    """Base exception for conversation-checkpoint failures."""


class CheckpointNotFoundError(CheckpointError):
    """Raised when a requested checkpoint does not exist."""


class CheckpointFormatError(CheckpointError):
    """Raised when checkpoint content or an identifier is invalid."""


class CheckpointVersionError(CheckpointFormatError):
    """Raised when a checkpoint uses an unsupported schema version."""


class CheckpointConflictError(CheckpointError):
    """Raised when saving would overwrite an existing checkpoint."""


class CheckpointVerificationError(CheckpointError):
    """Raised when a checkpoint mutation cannot be verified freshly."""


@dataclass(frozen=True, slots=True)
class CheckpointMetadata:
    """Non-transcript information suitable for checkpoint listings."""

    identifier: str
    display_name: str | None
    created_at: str
    provider: str
    model: str
    message_count: int


@dataclass(frozen=True, slots=True)
class ConversationCheckpoint:
    """One fully validated saved conversation."""

    metadata: CheckpointMetadata
    messages: tuple[ChatMessage, ...]


class CheckpointStore:
    """Save and retrieve explicit conversation checkpoints beneath one root."""

    def __init__(
        self,
        root: Path = DEFAULT_CHECKPOINT_DIRECTORY,
        *,
        clock: Clock | None = None,
        identifier_factory: IdentifierFactory | None = None,
    ) -> None:
        self._root = Path(root)
        self._clock = clock or _utc_now
        self._identifier_factory = identifier_factory or _generate_identifier

    @property
    def root(self) -> Path:
        """Return the configured checkpoint storage directory."""

        return self._root

    def save_checkpoint(
        self,
        messages: Sequence[ChatMessage],
        *,
        display_name: str | None,
        provider: str,
        model: str,
    ) -> CheckpointMetadata:
        """Create one new checkpoint without overwriting an existing one."""

        validated_messages = _validate_messages(messages)
        normalized_name = _normalize_display_name(display_name)
        normalized_provider = _required_metadata_text(provider, "provider")
        normalized_model = _required_metadata_text(model, "model")

        identifier = _validate_identifier(self._identifier_factory())
        created_at = _format_timestamp(self._clock())
        path = self._path_for(identifier)

        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CheckpointError(
                f"Could not create checkpoint directory {self._root}: {exc}"
            ) from exc

        if path.exists():
            raise CheckpointConflictError(
                f"Checkpoint {identifier} already exists; it was not overwritten."
            )

        metadata = CheckpointMetadata(
            identifier=identifier,
            display_name=normalized_name,
            created_at=created_at,
            provider=normalized_provider,
            model=normalized_model,
            message_count=len(validated_messages),
        )
        document = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "identifier": metadata.identifier,
            "display_name": metadata.display_name,
            "created_at": metadata.created_at,
            "provider": metadata.provider,
            "model": metadata.model,
            "message_count": metadata.message_count,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in validated_messages
            ],
        }

        self._write_atomically(path, document)
        try:
            verified = self._load_path(path)
        except CheckpointError as exc:
            raise CheckpointVerificationError(
                f"Checkpoint {identifier} was saved but could not be verified."
            ) from exc
        if (
            verified.metadata != metadata
            or verified.messages != validated_messages
        ):
            raise CheckpointVerificationError(
                f"Checkpoint {identifier} was saved but could not be verified."
            )
        return verified.metadata

    def list_checkpoints(self) -> tuple[CheckpointMetadata, ...]:
        """Return validated checkpoint metadata without transcript content."""

        if not self._root.exists():
            return ()

        try:
            paths = tuple(self._root.glob("*.json"))
        except OSError as exc:
            raise CheckpointError(
                f"Could not inspect checkpoint directory {self._root}: {exc}"
            ) from exc

        metadata = [
            self._load_path(path).metadata
            for path in paths
        ]
        metadata.sort(
            key=lambda item: (item.created_at, item.identifier),
            reverse=True,
        )
        return tuple(metadata)

    def load_checkpoint(self, identifier: str) -> ConversationCheckpoint:
        """Load and fully validate one checkpoint."""

        return self._load_path(self._path_for(identifier))

    def remove_checkpoint(self, identifier: str) -> CheckpointMetadata:
        """Remove only the selected, fully validated checkpoint."""

        path = self._path_for(identifier)
        checkpoint = self._load_path(path)

        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise CheckpointNotFoundError(
                f"Checkpoint {checkpoint.metadata.identifier} was not found."
            ) from exc
        except OSError as exc:
            raise CheckpointError(
                f"Could not remove checkpoint "
                f"{checkpoint.metadata.identifier}: {exc}"
            ) from exc

        try:
            self._load_path(path)
        except CheckpointNotFoundError:
            pass
        except CheckpointError as exc:
            raise CheckpointVerificationError(
                f"Removal of checkpoint "
                f"{checkpoint.metadata.identifier} could not be verified."
            ) from exc
        else:
            raise CheckpointVerificationError(
                f"Removal of checkpoint "
                f"{checkpoint.metadata.identifier} could not be verified."
            )

        return checkpoint.metadata

    def _path_for(self, identifier: str) -> Path:
        validated_identifier = _validate_identifier(identifier)
        return self._root / f"{validated_identifier}.json"

    def _load_path(self, path: Path) -> ConversationCheckpoint:
        expected_identifier = _validate_identifier(path.stem)

        try:
            with path.open("r", encoding="utf-8") as checkpoint_file:
                document = json.load(checkpoint_file)
        except FileNotFoundError as exc:
            raise CheckpointNotFoundError(
                f"Checkpoint {expected_identifier} was not found."
            ) from exc
        except json.JSONDecodeError as exc:
            raise CheckpointFormatError(
                f"Checkpoint {expected_identifier} is not valid JSON."
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise CheckpointError(
                f"Could not read checkpoint {expected_identifier}: {exc}"
            ) from exc

        return _validate_document(
            document,
            expected_identifier=expected_identifier,
        )

    def _write_atomically(self, path: Path, document: object) -> None:
        temporary_path: Path | None = None

        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=self._root,
            )
            temporary_path = Path(temporary_name)

            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
            ) as temporary_file:
                json.dump(
                    document,
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            if path.exists():
                raise CheckpointConflictError(
                    f"Checkpoint {path.stem} already exists; "
                    "it was not overwritten."
                )

            os.replace(temporary_path, path)
            temporary_path = None
        except CheckpointConflictError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise CheckpointError(
                f"Could not save checkpoint {path.stem}: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_identifier() -> str:
    timestamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"cp-{timestamp}-{secrets.token_hex(4)}"


def _validate_identifier(identifier: object) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER_PATTERN.fullmatch(
        identifier
    ):
        raise CheckpointFormatError(
            "Checkpoint identifiers must use the form "
            "cp-YYYYMMDDTHHMMSSZ-xxxxxxxx."
        )
    return identifier


def _normalize_display_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CheckpointFormatError(
            "Checkpoint display_name must be text or null."
        )

    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_DISPLAY_NAME_LENGTH:
        raise CheckpointFormatError(
            f"Checkpoint display_name cannot exceed "
            f"{MAX_DISPLAY_NAME_LENGTH} characters."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise CheckpointFormatError(
            "Checkpoint display_name cannot contain control characters."
        )
    return normalized


def _required_metadata_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointFormatError(
            f"Checkpoint {field_name} must be non-empty text."
        )
    return value.strip()


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CheckpointError(
            "Checkpoint timestamps require timezone-aware datetimes."
        )

    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise CheckpointFormatError(
            "Checkpoint created_at must be a UTC timestamp such as "
            "2026-07-25T06:48:10Z."
        )

    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CheckpointFormatError(
            "Checkpoint created_at is not a valid date and time."
        ) from exc

    return value


def _validate_messages(
    messages: Sequence[ChatMessage],
) -> tuple[ChatMessage, ...]:
    validated = tuple(messages)

    if not validated:
        raise CheckpointFormatError(
            "There is no completed conversation to save."
        )
    if len(validated) > MAX_CHECKPOINT_MESSAGES:
        raise CheckpointFormatError(
            f"A version 1 checkpoint cannot contain more than "
            f"{MAX_CHECKPOINT_MESSAGES} messages."
        )
    if len(validated) % 2 != 0:
        raise CheckpointFormatError(
            "Checkpoint messages must contain complete user/assistant exchanges."
        )

    for index, message in enumerate(validated):
        if not isinstance(message, ChatMessage):
            raise CheckpointFormatError(
                "Every checkpoint message must be a ChatMessage."
            )

        expected_role = "user" if index % 2 == 0 else "assistant"
        if message.role != expected_role:
            raise CheckpointFormatError(
                "Checkpoint messages must alternate user and assistant roles, "
                "beginning with user."
            )
        if not isinstance(message.content, str) or not message.content.strip():
            raise CheckpointFormatError(
                "Checkpoint message content must be non-empty text."
            )

    return validated


def _validate_document(
    document: object,
    *,
    expected_identifier: str,
) -> ConversationCheckpoint:
    if not isinstance(document, dict):
        raise CheckpointFormatError(
            f"Checkpoint {expected_identifier} must contain a JSON object."
        )

    required_fields = {
        "schema_version",
        "identifier",
        "display_name",
        "created_at",
        "provider",
        "model",
        "message_count",
        "messages",
    }
    actual_fields = set(document)

    if actual_fields != required_fields:
        missing = sorted(required_fields - actual_fields)
        unexpected = sorted(actual_fields - required_fields)
        details: list[str] = []

        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected fields: {', '.join(unexpected)}")

        raise CheckpointFormatError(
            f"Checkpoint {expected_identifier} has an invalid schema "
            f"({'; '.join(details)})."
        )

    schema_version = document["schema_version"]
    if type(schema_version) is not int:
        raise CheckpointFormatError(
            f"Checkpoint {expected_identifier} schema_version must be an integer."
        )
    if schema_version != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointVersionError(
            f"Checkpoint {expected_identifier} uses unsupported schema "
            f"version {schema_version}; supported version is "
            f"{CHECKPOINT_SCHEMA_VERSION}."
        )

    document_identifier = _validate_identifier(document["identifier"])
    if document_identifier != expected_identifier:
        raise CheckpointFormatError(
            f"Checkpoint filename and identifier do not match for "
            f"{expected_identifier}."
        )

    raw_messages = document["messages"]
    if not isinstance(raw_messages, list):
        raise CheckpointFormatError(
            f"Checkpoint {expected_identifier} messages must be a list."
        )

    messages: list[ChatMessage] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            raise CheckpointFormatError(
                f"Checkpoint {expected_identifier} contains an invalid message."
            )
        if set(raw_message) != {"role", "content"}:
            raise CheckpointFormatError(
                f"Checkpoint {expected_identifier} message fields are invalid."
            )

        role = raw_message["role"]
        content = raw_message["content"]
        if role not in {"user", "assistant"}:
            raise CheckpointFormatError(
                f"Checkpoint {expected_identifier} contains an invalid role."
            )
        if not isinstance(content, str):
            raise CheckpointFormatError(
                f"Checkpoint {expected_identifier} message content must be text."
            )

        messages.append(ChatMessage(role=role, content=content))

    validated_messages = _validate_messages(messages)

    message_count = document["message_count"]
    if type(message_count) is not int or message_count != len(validated_messages):
        raise CheckpointFormatError(
            f"Checkpoint {expected_identifier} message_count does not match "
            "its messages."
        )

    metadata = CheckpointMetadata(
        identifier=document_identifier,
        display_name=_normalize_display_name(document["display_name"]),
        created_at=_validate_timestamp(document["created_at"]),
        provider=_required_metadata_text(document["provider"], "provider"),
        model=_required_metadata_text(document["model"], "model"),
        message_count=message_count,
    )
    return ConversationCheckpoint(
        metadata=metadata,
        messages=validated_messages,
    )
