"""Read-only, bounded cross-capability Project continuity projections.

Source stores own every record. This module holds no execution or mutation port.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re

from .conversation_archive import ProjectLinkRecord


_UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_SOURCES = (
    "research", "coding_work", "attention", "night_owl",
    "scheduled_work", "knowledge",
)
_LINK_TYPES = {
    "night_owl_finding": "night_owl",
    "scheduled_work_definition": "scheduled_work",
    "knowledge_source": "knowledge",
}


@dataclass(frozen=True, slots=True)
class ProjectRelatedItem:
    source_type: str
    identifier: str
    title: str
    state: str
    revision: int | None
    updated_at: str
    summary: str | None = None
    link_id: str | None = None
    availability: str = "available"


@dataclass(frozen=True, slots=True)
class ProjectRelatedActivity:
    source_type: str
    identifier: str
    state: str
    occurred_at: str
    projection_only: bool = True


@dataclass(frozen=True, slots=True)
class ProjectRelatedWork:
    research: tuple[ProjectRelatedItem, ...]
    coding_work: tuple[ProjectRelatedItem, ...]
    attention: tuple[ProjectRelatedItem, ...]
    night_owl: tuple[ProjectRelatedItem, ...]
    scheduled_work: tuple[ProjectRelatedItem, ...]
    knowledge: tuple[ProjectRelatedItem, ...]
    recent_activity: tuple[ProjectRelatedActivity, ...]
    unavailable_sources: tuple[str, ...]
    unavailable_details: tuple[ProjectRelatedUnavailable, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class ProjectRelatedUnavailable:
    source_type: str
    reason: str


class ProjectRelatedSources:
    """Injected source-owned readers; ``None`` means unavailable, never empty."""

    def __init__(
        self,
        *,
        research: Callable[[str], Sequence[object]] | None = None,
        coding_work: Callable[[str], Sequence[object]] | None = None,
        attention: Callable[[str], Sequence[object]] | None = None,
        night_owl: Callable[[str], object | None] | None = None,
        scheduled_work: Callable[[str], object | None] | None = None,
        scheduled_runs: Callable[[str], Sequence[object]] | None = None,
        knowledge: Callable[[str], object | None] | None = None,
    ) -> None:
        self._readers = {
            "research": research, "coding_work": coding_work,
            "attention": attention, "night_owl": night_owl,
            "scheduled_work": scheduled_work, "knowledge": knowledge,
        }
        self._scheduled_runs = scheduled_runs

    def verify_link(self, target_type: str, target_id: str) -> bool:
        """Fail closed against the exact source owner; no Project authority."""

        source = _LINK_TYPES.get(target_type)
        reader = None if source is None else self._readers[source]
        if reader is None:
            return False
        try:
            record = reader(target_id)
            return record is not None and getattr(record, "identifier", None) == target_id
        except Exception:
            return False

    def project(self, project_id: str, links: Sequence[ProjectLinkRecord]) -> ProjectRelatedWork:
        sections: dict[str, tuple[ProjectRelatedItem, ...]] = {}
        unavailable: list[str] = []
        unavailable_details: list[ProjectRelatedUnavailable] = []
        for source in _SOURCES:
            reader = self._readers[source]
            if reader is None:
                sections[source] = ()
                unavailable.append(source)
                unavailable_details.append(ProjectRelatedUnavailable(
                    source, "Source is not configured."
                ))
                continue
            try:
                if source in {"research", "coding_work", "attention"}:
                    raw = reader(project_id)
                    if not isinstance(raw, (tuple, list)) or len(raw) > 50:
                        raise ValueError("Source result is not bounded.")
                    items = tuple(_native_item(source, row, project_id) for row in raw)
                else:
                    selected = tuple(
                        link for link in links
                        if _LINK_TYPES.get(link.target_type) == source
                    )
                    if len(selected) > 50:
                        raise ValueError("Source links are not bounded.")
                    linked: list[ProjectRelatedItem] = []
                    for link in selected:
                        record = reader(link.target_id)
                        latest_run = None
                        if source == "scheduled_work" and record is not None and self._scheduled_runs is not None:
                            runs = self._scheduled_runs(link.target_id)
                            if not isinstance(runs, (tuple, list)) or len(runs) > 1:
                                raise ValueError("Scheduled run summary is not bounded.")
                            latest_run = runs[0] if runs else None
                        linked.append(_linked_item(source, link, record, latest_run))
                    items = tuple(linked)
                # A malformed timestamp invalidates this section, not the whole Home.
                for item in items:
                    _timestamp(item.updated_at)
                sections[source] = tuple(sorted(items, key=_item_sort_key))
            except Exception:
                sections[source] = ()
                unavailable.append(source)
                unavailable_details.append(ProjectRelatedUnavailable(
                    source, "Source could not be read safely."
                ))
        activity = tuple(
            ProjectRelatedActivity(item.source_type, item.identifier, item.state, item.updated_at)
            for section in _SOURCES for item in sections[section]
            if item.availability != "missing"
        )
        activity = tuple(sorted(activity, key=_activity_sort_key))[:30]
        return ProjectRelatedWork(
            *(sections[source] for source in _SOURCES),
            recent_activity=activity,
            unavailable_sources=tuple(unavailable),
            unavailable_details=tuple(unavailable_details),
            complete=not unavailable,
        )


def merge_project_activity(
    related: ProjectRelatedWork, records: Sequence[tuple[str, object]],
) -> ProjectRelatedWork:
    """Merge canonical Project-owned row facts, not a fabricated event log."""

    owned = tuple(
        ProjectRelatedActivity(
            source_type, str(getattr(record, "identifier", getattr(record, "project_id", ""))),
            str(getattr(record, "state", "updated")),
            str(getattr(record, "updated_at")),
        )
        for source_type, record in records
    )
    for item in owned:
        _timestamp(item.occurred_at)
    return replace(
        related,
        recent_activity=tuple(sorted(
            (*related.recent_activity, *owned), key=_activity_sort_key
        ))[:30],
    )


def _native_item(source: str, row: object, project_id: str) -> ProjectRelatedItem:
    if getattr(row, "project_id") != project_id:
        raise ValueError("Source Project association does not match.")
    identifier = str(getattr(row, "identifier"))
    if source == "research":
        return ProjectRelatedItem(
            source, identifier, str(getattr(row, "objective"))[:500],
            str(getattr(row, "state")), int(getattr(row, "revision")),
            str(getattr(row, "updated_at_utc")),
            _safe_summary(getattr(row, "progress_message")),
        )
    if source == "coding_work":
        return ProjectRelatedItem(
            source, identifier, str(getattr(row, "objective"))[:500],
            str(getattr(row, "state")), int(getattr(row, "revision")),
            str(getattr(row, "updated_at_utc")),
        )
    return ProjectRelatedItem(
        source, identifier, str(getattr(row, "title"))[:500],
        str(getattr(row, "state")), int(getattr(row, "revision")),
        getattr(row, "updated_at_utc").isoformat().replace("+00:00", "Z"),
        _safe_summary(getattr(row, "summary")),
    )


def _linked_item(
    source: str, link: ProjectLinkRecord, row: object | None,
    latest_run: object | None = None,
) -> ProjectRelatedItem:
    if row is None:
        return ProjectRelatedItem(
            source, link.target_id, "Source record no longer exists", "missing",
            None, link.updated_at, link_id=link.identifier, availability="missing",
        )
    if getattr(row, "identifier") != link.target_id:
        raise ValueError("Source identity does not match the explicit link.")
    if source == "night_owl":
        return ProjectRelatedItem(
            source, str(getattr(row, "identifier")), str(getattr(row, "title"))[:500],
            str(getattr(row, "state")), int(getattr(row, "revision")),
            str(getattr(row, "last_seen_at")), _safe_summary(getattr(row, "summary")),
            link_id=link.identifier,
        )
    if source == "scheduled_work":
        return ProjectRelatedItem(
            source, str(getattr(row, "identifier")), str(getattr(row, "title"))[:500],
            str(getattr(row, "status")), int(getattr(row, "revision")),
            str(getattr(row, "updated_at_utc")),
            summary=(
                None if latest_run is None else "Latest run: " + str(getattr(latest_run, "status"))
            ),
            link_id=link.identifier,
        )
    return ProjectRelatedItem(
        source, str(getattr(row, "identifier")), str(getattr(row, "filename"))[:500],
        "registered", None, str(getattr(row, "registered_at")),
        str(getattr(row, "file_type")), link_id=link.identifier,
        availability="not_checked",
    )


def _safe_summary(value: object) -> str | None:
    return value[:500] if isinstance(value, str) and value else None


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or _UTC_STAMP.fullmatch(value) is None:
        raise ValueError("Source timestamp is not canonical UTC.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Source timestamp is not UTC.")
    return parsed


def _item_sort_key(item: ProjectRelatedItem) -> tuple[int, str, str]:
    return (-_utc_microseconds(item.updated_at), item.source_type, item.identifier)


def _activity_sort_key(item: ProjectRelatedActivity) -> tuple[int, str, str]:
    return (-_utc_microseconds(item.occurred_at), item.source_type, item.identifier)


def _utc_microseconds(value: str) -> int:
    delta = _timestamp(value) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
