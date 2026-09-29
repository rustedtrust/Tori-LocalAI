"""Tori-facing contract for replaceable search execution."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .capabilities import CapabilityResult


@runtime_checkable
class SearchPort(Protocol):
    """Execute an authorized query and return normalized capability facts."""

    @property
    def available(self) -> bool:
        """Whether this configured implementation can accept search requests."""

    def search(self, query: str, *, category: str = "general") -> CapabilityResult:
        """Execute one authorized query or raise an explicit capability error."""
