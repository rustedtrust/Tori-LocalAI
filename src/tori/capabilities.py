"""Small provider-neutral contracts for explicitly authorized capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class CapabilityError(RuntimeError):
    """A safe user-facing capability failure."""

    def __init__(self, message: str, *, code: str = "capability_error") -> None:
        super().__init__(message)
        self.code = code


class CapabilityUnavailableError(CapabilityError):
    """A configured capability cannot currently execute."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="capability_unavailable")


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Objective availability information for one bounded capability."""

    identifier: str
    available: bool
    authorization: str


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One normalized external source record."""

    title: str
    url: str
    snippet: str | None = None
    metadata: Mapping[str, str | int | float] | None = None


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    """Structured output from one visible, authorized execution."""

    capability_id: str
    input_text: str
    status: str
    sources: tuple[SourceRecord, ...]
    metadata: Mapping[str, str | int | float | bool] | None = None
