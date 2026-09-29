"""Tori-owned contract for replaceable knowledge retrieval."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .knowledge import KnowledgeRetrieval


@runtime_checkable
class KnowledgeRetrievalPort(Protocol):
    """Retrieve bounded optional context without owning Tori's context policy."""

    def retrieve(self, query: str) -> KnowledgeRetrieval:
        """Return normalized passages and safe retrieval warnings."""
