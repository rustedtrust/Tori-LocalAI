"""Content-minimal source projections for Companion Initiative resume policy."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .companion_initiative import (
    InitiativeActivity,
    InitiativeSettings,
    RESUME_EXPIRY,
    ResumeAnchor,
    resume_window,
)
from .operator_observability import operator_failure


class CodingWorkResumeSource(Protocol):
    def resume_metadata(self) -> tuple[object, ...]: ...


class ConversationResumeSource(Protocol):
    def list_chats(self) -> tuple[object, ...]: ...
    def list_project_resume_metadata(self) -> tuple[object, ...]: ...


class StructuredResumeAnchorProvider:
    """Select one truthful anchor without reading work or conversation bodies."""

    def __init__(
        self,
        *,
        coding_work: CodingWorkResumeSource | None,
        conversations: ConversationResumeSource | None,
    ) -> None:
        self._coding_work = coding_work
        self._conversations = conversations

    def current(
        self,
        settings: InitiativeSettings,
        activity: InitiativeActivity,
        *,
        at: datetime,
    ) -> ResumeAnchor | None:
        if not settings.master_enabled or not settings.resume_enabled:
            return None
        now = _utc(at)
        try:
            chat_ids = set()
            project_rows: tuple[object, ...] = ()
            if self._conversations is not None:
                chat_ids = {
                    item.identifier for item in self._conversations.list_chats()
                }
                project_rows = self._conversations.list_project_resume_metadata()

            waiting: list[ResumeAnchor] = []
            if self._coding_work is not None:
                project_titles = {
                    item.project_id: item.title for item in project_rows
                }
                for item in self._coding_work.resume_metadata():
                    if item.origin_chat_id is None or item.origin_chat_id not in chat_ids:
                        continue
                    stamp = _timestamp(item.updated_at_utc)
                    if stamp > now or now - stamp >= RESUME_EXPIRY:
                        continue
                    waiting.append(ResumeAnchor(
                        "coding_work",
                        item.identifier,
                        item.revision,
                        project_titles.get(item.project_id),
                        stamp,
                        item.origin_chat_id,
                        item.project_id,
                    ))
            projects = []
            for item in project_rows:
                stamp = _timestamp(item.last_active_at_utc)
                if stamp > now or now - stamp >= RESUME_EXPIRY:
                    continue
                projects.append(ResumeAnchor(
                    "project_chat",
                    item.project_id,
                    item.exchange_revision,
                    item.title,
                    stamp,
                    item.chat_id,
                    item.project_id,
                ))
            candidates = waiting + projects
            if not candidates:
                return None
            anchor = max(
                candidates,
                key=lambda item: (
                    item.last_active_at_utc,
                    item.kind,
                    item.identifier,
                ),
            )
            # Activity changes the quiet-period baseline, but never changes or
            # fabricates the source-owned anchor identity.
            return anchor if resume_window(anchor, activity).expires_at_utc > now else None
        except Exception as exc:
            operator_failure(
                "companion_initiative.resume_anchor.failed",
                exc,
                code=getattr(exc, "code", "anchor_unavailable"),
                origin="local_application",
            )
            return None


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Resume metadata timestamp is invalid.")
    return _utc(datetime.fromisoformat(value[:-1] + "+00:00"))


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Resume policy requires an aware timestamp.")
    return value.astimezone(timezone.utc)
