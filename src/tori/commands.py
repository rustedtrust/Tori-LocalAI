"""Shared local slash-command behavior for Tori's presentation layers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re

from .checkpoints import CheckpointStore
from .knowledge import (
    KnowledgeListing,
    KnowledgePassage,
    KnowledgeRegistry,
)
from .management import (
    KnowledgeItems,
    ManagementError,
    ManagementService,
    safe_display,
)
from .memory import SQLiteMemoryStore
from .providers import ChatMessage


BROWSER_COMMAND_NAMES = (
    "/search",
    "/run",
    "/save",
    "/remember",
    "/memories",
    "/update-memory",
    "/forget",
    "/add-knowledge",
    "/knowledge",
    "/remove-knowledge",
    "/exit",
    "/quit",
    "/finance",
)
SUPPORTED_BROWSER_COMMANDS = frozenset(BROWSER_COMMAND_NAMES)
_COMMAND_SHAPED_PREFIX = re.compile(
    r"^/[A-Za-z]+(?:-[A-Za-z]+)*(?=\s|$)"
)


@dataclass(frozen=True, slots=True)
class ForgetConfirmation:
    """A validated memory target awaiting presentation-specific confirmation."""

    identifier: str
    prompt: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CommandResult:
    """One user-visible local command result."""

    text: str
    confirmation: ForgetConfirmation | None = None
    success: bool = True


@dataclass(frozen=True, slots=True)
class SourceReference:
    """Browser- and terminal-safe source transparency metadata."""

    filename: str
    line_start: int
    line_end: int


class LocalCommandService:
    """Execute local commands without involving a model or conversation history."""

    def __init__(
        self,
        *,
        checkpoint_store: CheckpointStore,
        memory_store: SQLiteMemoryStore | None,
        knowledge_registry: KnowledgeRegistry | None,
        provider_name: str,
        model_name: str,
    ) -> None:
        self._management = ManagementService(
            checkpoint_store=checkpoint_store,
            memory_store=memory_store,
            knowledge_registry=knowledge_registry,
            provider_name=provider_name,
            model_name=model_name,
        )

    def select_model(self, provider_name: str, model_name: str) -> None:
        self._management.select_model(provider_name, model_name)

    def handle(
        self,
        prompt: str,
        *,
        history: Sequence[ChatMessage],
    ) -> CommandResult | None:
        """Handle a supported slash command, or return ``None`` for conversation."""

        normalized = prompt.strip()
        from .capability_registry import explicit_memory_text
        memory_text = explicit_memory_text(normalized)
        if memory_text is not None:
            return self._handle_memory("/remember " + memory_text)
        parts = normalized.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        if command == "/save":
            display_name = parts[1] if len(parts) == 2 else None
            try:
                metadata = self._management.save_checkpoint(
                    history,
                    display_name=display_name,
                )
            except ManagementError as exc:
                return CommandResult(
                    f"Checkpoint save failed: {exc}",
                    success=False,
                )
            name = metadata.identifier
            if metadata.display_name is not None:
                name = f"{name} ({metadata.display_name})"
            return CommandResult(
                f"Saved checkpoint {name} in "
                f"{self._management.checkpoint_root}."
            )

        if command in {
            "/remember",
            "/memories",
            "/update-memory",
            "/forget",
        }:
            return self._handle_memory(normalized)

        if command in {
            "/add-knowledge",
            "/knowledge",
            "/remove-knowledge",
        }:
            return self._handle_knowledge(normalized)

        if command in {"/exit", "/quit"}:
            return CommandResult(
                f"Command failed: Usage: {command}",
                success=False,
            )

        if command == "/finance":
            return CommandResult(
                "Finance command failed: Finance commands are handled by the "
                "configured Finance service in the browser. Configure Finance "
                "before using /finance commands.",
                success=False,
            )

        unknown = command_shaped_token(normalized)
        if (
            unknown is not None
            and unknown.lower() not in SUPPORTED_BROWSER_COMMANDS
        ):
            return CommandResult(
                f"Unknown command: {unknown.lower()}. "
                "Open Commands to see the supported commands."
            )

        return None

    def confirm_forget(
        self,
        identifier: str,
        *,
        expected_updated_at: str | None = None,
    ) -> CommandResult:
        """Revalidate and delete exactly one previously selected memory."""

        try:
            if expected_updated_at is None:
                record = self._management.remove_memory_unconditionally(
                    identifier
                )
            else:
                target = self._management.memory_forget_target(
                    identifier,
                    expected_updated_at=expected_updated_at,
                )
                record = self._management.forget_memory(target)
        except ManagementError as exc:
            return CommandResult(
                f"Memory command failed: {exc}",
                success=False,
            )
        return CommandResult(
            f"Removed memory {record.identifier} from Tori's canonical "
            "memory store. Independent backups or storage snapshots outside "
            "Tori's control could still contain older copies."
        )

    def _handle_memory(self, prompt: str) -> CommandResult:
        command, separator, remainder = prompt.partition(" ")
        command = command.lower()
        try:
            if command == "/remember":
                if not separator or not remainder:
                    return CommandResult(
                        "Memory command failed: Usage: /remember TEXT",
                        success=False,
                    )
                record = self._management.create_memory(remainder)
                return CommandResult(
                    f"Saved memory {record.identifier} exactly as:\n{record.text}"
                )

            if command == "/memories":
                if remainder:
                    return CommandResult(
                        "Memory command failed: Usage: /memories",
                        success=False,
                    )
                records = self._management.list_memories()
                if not records:
                    return CommandResult("Tori has no canonical memories.")
                lines = ["Tori's current canonical memories:"]
                for record in records:
                    lines.append(
                        f"- ID: {record.identifier}\n"
                        f"  Category: {record.category}\n"
                        f"  Created: {record.created_at}\n"
                        f"  Updated: {record.updated_at}\n"
                        f"  Text: {record.text}"
                    )
                return CommandResult("\n".join(lines))

            if command == "/update-memory":
                identifier, text_separator, text = remainder.partition(" ")
                if not identifier or not text_separator or not text:
                    return CommandResult(
                        "Memory command failed: Usage: /update-memory "
                        "MEMORY_ID NEW_TEXT",
                        success=False,
                    )
                record = self._management.update_memory_unconditionally(
                    identifier, text
                )
                return CommandResult(
                    f"Updated memory {record.identifier}; its exact current "
                    f"value is:\n{record.text}"
                )

            if command == "/forget":
                if not remainder or " " in remainder:
                    return CommandResult(
                        "Memory command failed: Usage: /forget MEMORY_ID",
                        success=False,
                    )
                target = self._management.memory_forget_target(remainder)
                expected = f"FORGET {target.identifier}"
                return CommandResult(
                    f"Confirmation required before removing memory "
                    f"{target.identifier}.",
                    confirmation=ForgetConfirmation(
                        identifier=target.identifier,
                        prompt=f"Type {expected} to confirm: ",
                        updated_at=target.fingerprint,
                    ),
                )
        except ManagementError as exc:
            if exc.code == "policy_rejection":
                return CommandResult(
                    f"Memory rejected: {exc}",
                    success=False,
                )
            return CommandResult(
                f"Memory command failed: {exc}",
                success=False,
            )
        raise AssertionError("unreachable memory command")

    def _handle_knowledge(self, prompt: str) -> CommandResult:
        parts = prompt.split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        argument = parts[1].strip() if len(parts) == 2 else ""
        try:
            if command == "/add-knowledge":
                if not argument:
                    return CommandResult(
                        "Knowledge command failed: Usage: /add-knowledge PATH",
                        success=False,
                    )
                source = self._management.register_knowledge(argument)
                return CommandResult(
                    f"Registered knowledge source {source.identifier}.\n"
                    f"Filename: {source.filename}\n"
                    f"Path: {source.display_path}"
                )

            if command == "/knowledge":
                if argument:
                    return CommandResult(
                        "Knowledge command failed: Usage: /knowledge",
                        success=False,
                    )
                return CommandResult(
                    _format_managed_knowledge_listing(
                        self._management.list_knowledge(),
                        root=self._management.knowledge_root,
                    )
                )

            if command == "/remove-knowledge":
                if not argument or any(
                    character.isspace() for character in argument
                ):
                    return CommandResult(
                        "Knowledge command failed: Usage: "
                        "/remove-knowledge SOURCE_ID",
                        success=False,
                    )
                source = self._management.remove_knowledge_unconditionally(
                    argument
                )
                return CommandResult(
                    f"Removed registration {source.identifier} for "
                    f"{source.filename}. "
                    "The source document was not changed."
                )
        except ManagementError as exc:
            return CommandResult(
                f"Knowledge command failed: {exc}",
                success=False,
            )
        raise AssertionError("unreachable knowledge command")


def source_references(
    passages: tuple[KnowledgePassage, ...],
) -> tuple[SourceReference, ...]:
    """Return deduplicated safe source information for user presentation."""

    references: list[SourceReference] = []
    seen: set[tuple[str, int, int]] = set()
    for passage in passages:
        key = (passage.source_id, passage.line_start, passage.line_end)
        if key in seen:
            continue
        seen.add(key)
        references.append(
            SourceReference(
                filename=safe_filesystem_display(passage.filename),
                line_start=passage.line_start,
                line_end=passage.line_end,
            )
        )
    return tuple(references)


def command_shaped_token(prompt: str) -> str | None:
    """Return a narrow leading slash-command token, excluding path syntax."""

    match = _COMMAND_SHAPED_PREFIX.match(prompt.strip())
    return match.group(0) if match is not None else None


def safe_filesystem_display(value: str) -> str:
    """Render terminal-unsafe filesystem-derived text unambiguously."""

    return safe_display(value)


def _format_managed_knowledge_listing(
    listing: KnowledgeItems,
    *,
    root: str,
) -> str:
    if not listing.sources and not listing.invalid_registrations:
        return f"No knowledge sources are registered in {root}."
    lines = [f"Registered local knowledge sources in {root}:"]
    for status in listing.sources:
        size = (
            str(status.byte_size)
            if status.byte_size is not None
            else "unavailable"
        )
        lines.append(
            f"- {status.identifier} | filename: {status.filename} | path: "
            f"{status.display_path} | registered: {status.registered_at} | "
            f"status: {status.availability} | bytes: {size}"
        )
    for invalid in listing.invalid_registrations:
        lines.append(
            "- Invalid registration record: "
            f"{invalid.filename} | status: {invalid.detail}"
        )
    return "\n".join(lines)


def format_knowledge_listing(
    listing: KnowledgeListing,
    *,
    registry: KnowledgeRegistry,
) -> str:
    if not listing.sources and not listing.invalid_records:
        return (
            "No knowledge sources are registered in "
            f"{safe_filesystem_display(str(registry.root))}."
        )
    lines = [
        "Registered local knowledge sources in "
        f"{safe_filesystem_display(str(registry.root))}:"
    ]
    for status in listing.sources:
        size = (
            str(status.byte_size)
            if status.byte_size is not None
            else "unavailable"
        )
        lines.append(
            f"- {status.source.identifier} | filename: "
            f"{safe_filesystem_display(status.source.filename)} | path: "
            f"{safe_filesystem_display(status.source.path)} | registered: "
            f"{status.source.registered_at} | status: "
            f"{status.availability} | bytes: {size}"
        )
    for invalid in listing.invalid_records:
        lines.append(
            "- Invalid registration record: "
            f"{safe_filesystem_display(invalid.filename)} | status: "
            f"{safe_filesystem_display(invalid.detail)}"
        )
    return "\n".join(lines)
