"""Tori-owned conversational proposal boundary for concrete Coding Work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
from typing import Callable, Protocol

from .coding_work import CODING_WORK_CAPABILITY, CodingWork, CodingWorkError
from .coding_work_runtime import CodingWorkRuntimeError
from .capability_registry import is_capability_discussion


MAX_PROPOSAL_OBJECTIVE = 8_000
MAX_PROPOSAL_ACCEPTANCE = 8_000
CODING_WORK_CONFIRMATION_SECONDS = 10 * 60.0

_ABSOLUTE_PATH = re.compile(r"(?<!\S)(/[^\s\"'<>]+)")
_CODING_ACTION = re.compile(
    r"\b(?:audit|build|change|create|edit|fix|implement|make|modify|refactor|review|update|write)\b",
    re.IGNORECASE,
)
_MUTATING_ACTION = re.compile(
    r"\b(?:build|change|create|edit|fix|implement|make|modify|refactor|update|write)\b",
    re.IGNORECASE,
)
_NEGATED_MUTATING_ACTION = re.compile(
    r"\b(?:do\s+not|don['’]t|never|must\s+not|should\s+not|not)\s+"
    r"(?:ever\s+)?(?:(?:attempt|try)\s+to\s+)?"
    r"(?P<actions>(?:build|change|create|edit|fix|implement|make|"
    r"modify|refactor|update|write)\b(?:\s*(?:,|or|and)\s*"
    r"(?:build|change|create|edit|fix|implement|make|modify|refactor|update|write)\b)*)",
    re.IGNORECASE,
)
_READ_ONLY_RESTRICTION = re.compile(
    r"\bread[\s-]+only\b|\bwithout\s+(?:making\s+)?changes\b|"
    r"\bwithout\s+(?:modifying|editing|changing|writing)\b|"
    r"\bno\s+(?:file|code|workspace)\s+changes\b",
    re.IGNORECASE,
)
_LIMITED_NEGATED_SCOPE = re.compile(
    r"\s+(?:anything\s+else|any\s+other\s+(?:files?|code)|"
    r"other\s+(?:files?|code)|unrelated\s+(?:files?|code))\b",
    re.IGNORECASE,
)
_CODING_SUBJECT = re.compile(
    r"\b(?:opencode|bug|code|file|project|repo(?:sitory)?|script|startup|test(?:s|ing)?)\b",
    re.IGNORECASE,
)
_FILENAME_SUBJECT = re.compile(
    r"(?<![A-Za-z0-9_./:@-])"
    r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*"
    r"\.(?!(?:co|com|edu|gov|int|io|mil|net|org)(?![A-Za-z0-9_-]))"
    r"[A-Za-z][A-Za-z0-9_-]{0,11}"
    r"(?![A-Za-z0-9_./:@-])"
)
_ACCEPTANCE = re.compile(
    r"\b(?:acceptance\s+criteria|done\s+when)\s*:\s*", re.IGNORECASE
)
_DELEGATED_REFERENCE = re.compile(
    r"\b(?:coding work|delegated work|coding job|opencode)\b", re.IGNORECASE
)
_STATUS_LANGUAGE = re.compile(
    r"\b(?:status|progress|going|finished|done|complete|completed|change(?:d|s)?|"
    r"tests? pass(?:ed)?|result|verification)\b",
    re.IGNORECASE,
)
_CANCEL_DELEGATED = re.compile(
    r"^(?:please\s+)?(?:stop|cancel)\s+(?:that|the|current|my)?\s*"
    r"(?:coding work|delegated work|coding job|opencode(?: job| work)?)\s*[.!?]*$",
    re.IGNORECASE,
)
_FOLLOW_UP = re.compile(
    r"^(?:please\s+)?(?:have\s+(?:it|opencode)|tell\s+opencode\s+to|"
    r"continue\s+that\s+work\s+and)\s+(.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_ACTIVE_STATES = frozenset({"starting", "running", "waiting", "cancelling", "reconciling"})


class CodingWorkConversationError(RuntimeError):
    """Safe conversational proposal or application failure."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CodingWorkRuntimePort(Protocol):
    """Only the Tori-owned runtime operations Conversation may use."""

    @property
    def admission_open(self) -> bool: ...

    def create_work(self, **arguments: object) -> CodingWork: ...

    def authorize(self, work_id: str, **arguments: object) -> CodingWork: ...

    def start_work(self, work_id: str, *, expected_revision: int) -> CodingWork: ...

    def status(self, work_id: str | None = None, *, project_id: str | None = None) -> object: ...

    def cancel(
        self, work_id: str, *, expected_revision: int,
        source_chat_id: str | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class CodingWorkRequest:
    objective: str
    requested_workspace: Path
    acceptance_criteria: str | None
    modify_allowed: bool


@dataclass(frozen=True, slots=True)
class CodingWorkConversationIntent:
    kind: str
    instruction: str | None = None


@dataclass(frozen=True, slots=True)
class CodingWorkProposal:
    identifier: str
    origin_chat_id: str
    origin_chat_revision: int
    objective: str
    workspace_root: str
    acceptance_criteria: str | None
    requested_capability: str
    read_allowed: bool
    modify_allowed: bool
    sandboxed_execution_allowed: bool
    authority_summary: tuple[str, ...]
    limitations: tuple[str, ...]
    created_at_utc: str
    expires_at: float
    workspace_device: int
    workspace_inode: int
    project_id: str | None = None
    related_work_id: str | None = None
    project_title: str | None = None

    def document(self) -> dict[str, object]:
        """Return the complete bounded human-reviewable proposal."""

        return {
            "proposal_id": self.identifier,
            "origin_chat_id": self.origin_chat_id,
            "objective": self.objective,
            "workspace": self.workspace_root,
            "acceptance_criteria": self.acceptance_criteria,
            "requested_capability": self.requested_capability,
            "workspace_access": {
                "read": self.read_allowed,
                "modify": self.modify_allowed,
            },
            "sandboxed_execution": self.sandboxed_execution_allowed,
            "authority": list(self.authority_summary),
            "limitations": list(self.limitations),
            "created_at_utc": self.created_at_utc,
            "origin_chat_revision": self.origin_chat_revision,
            "related_work_id": self.related_work_id,
            "project": (
                None if self.project_id is None else {
                    "identifier": self.project_id,
                    "title": self.project_title,
                    "role": "organization_only_no_capability_authority",
                }
            ),
        }


def recognize_delegated_work_intent(text: str) -> CodingWorkConversationIntent | None:
    """Recognize only narrow status, stop, and related-follow-up language."""

    normalized = " ".join(text.strip().split())
    if not normalized:
        return None
    if _CANCEL_DELEGATED.fullmatch(normalized):
        return CodingWorkConversationIntent("cancel")
    follow_up = _FOLLOW_UP.fullmatch(normalized)
    if follow_up is not None:
        instruction = follow_up.group(1).strip()
        if not instruction or len(instruction) > MAX_PROPOSAL_OBJECTIVE:
            return None
        return CodingWorkConversationIntent("follow_up", instruction)
    lowered = normalized.casefold().rstrip(".?!")
    contextual_status = lowered in {
        "how is that fix going",
        "what did it change",
        "did the tests pass",
        "is that work done",
    }
    if contextual_status or (
        _DELEGATED_REFERENCE.search(normalized)
        and _STATUS_LANGUAGE.search(normalized)
    ):
        return CodingWorkConversationIntent("status")
    if is_capability_discussion(normalized):
        return None
    return None


def recognize_coding_work_request(text: str) -> CodingWorkRequest | None:
    """Recognize a bounded Coding Work request without touching runtime state."""

    normalized = " ".join(text.strip().split())
    if is_capability_discussion(normalized):
        return None
    negated_actions = tuple(_NEGATED_MUTATING_ACTION.finditer(normalized))
    negated_spans = tuple(
        (action.start() + match.start("actions"), action.end() + match.start("actions"))
        for match in negated_actions
        for action in _MUTATING_ACTION.finditer(match.group("actions"))
    )
    broad_read_only = bool(_READ_ONLY_RESTRICTION.search(normalized)) or any(
        _LIMITED_NEGATED_SCOPE.match(normalized[match.end("actions"):]) is None
        for match in negated_actions
    )

    def affirmative(matches: re.Pattern[str]) -> tuple[re.Match[str], ...]:
        return tuple(
            match for match in matches.finditer(normalized)
            if match.span() not in negated_spans
        )

    if not normalized or not affirmative(_CODING_ACTION):
        return None
    # Workspace path components are context, not an instruction's coding subject.
    subject_text = _ABSOLUTE_PATH.sub(" ", normalized)
    if not (
        _CODING_SUBJECT.search(subject_text)
        or _FILENAME_SUBJECT.search(subject_text)
    ):
        return None
    raw_paths = [
        match.group(1).rstrip(".,;:!?)]}")
        for match in _ABSOLUTE_PATH.finditer(normalized)
    ]
    paths = tuple(dict.fromkeys(item for item in raw_paths if item))
    if len(paths) != 1:
        return None
    acceptance_match = _ACCEPTANCE.search(normalized)
    acceptance = None
    objective = normalized
    if acceptance_match is not None:
        objective = normalized[: acceptance_match.start()].strip(" ;,.—-")
        acceptance = normalized[acceptance_match.end() :].strip()
        if not objective or not acceptance:
            return None
    if len(objective) > MAX_PROPOSAL_OBJECTIVE or (
        acceptance is not None and len(acceptance) > MAX_PROPOSAL_ACCEPTANCE
    ):
        raise CodingWorkConversationError(
            "The Coding Work request is too large to propose safely.",
            code="coding_work_request_too_large",
        )
    mutating_actions = affirmative(_MUTATING_ACTION)
    if mutating_actions and broad_read_only:
        # Conflicting authority language needs clarification, not a broad grant.
        return None
    return CodingWorkRequest(
        objective,
        Path(paths[0]),
        acceptance,
        bool(mutating_actions),
    )


class CodingWorkConversationService:
    """Recognize and apply one explicitly confirmed Coding Work proposal."""

    def __init__(
        self,
        runtime: CodingWorkRuntimePort,
        *,
        clock: Callable[[], float],
        utc_clock: Callable[[], datetime],
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        self._runtime = runtime
        self._clock = clock
        self._utc_clock = utc_clock
        self._identifier_factory = identifier_factory or (
            lambda: "coding-proposal-" + secrets.token_hex(16)
        )

    def recognize(self, text: str) -> CodingWorkRequest | None:
        """Recognize only a clear coding action with one explicit absolute path."""

        return recognize_coding_work_request(text)

    def recognize_intent(self, text: str) -> CodingWorkConversationIntent | None:
        return recognize_delegated_work_intent(text)

    def status_message(self, *, origin_chat_id: str | None) -> str:
        item = self._select_work(
            origin_chat_id=origin_chat_id,
            active_only=False,
        )
        if item is None:
            return "I do not have any Delegated Work to report yet."
        return delegated_work_status_message(item)

    def cancel_current(self, *, origin_chat_id: str | None) -> tuple[object, str]:
        item = self._select_work(origin_chat_id=origin_chat_id, active_only=True)
        if item is None:
            return None, "There is no active Delegated Work to stop."
        try:
            cancelled = self._runtime.cancel(
                item.identifier,
                expected_revision=item.revision,
                source_chat_id=origin_chat_id,
            )
        except (CodingWorkError, CodingWorkRuntimeError, OSError) as exc:
            raise CodingWorkConversationError(
                "I could not stop that Delegated Work safely.",
                code=getattr(exc, "code", "coding_work_cancel_failed"),
            ) from exc
        return cancelled, (
            "I requested cancellation for the active Delegated Work. "
            f"Current state: {getattr(cancelled, 'state', 'cancelling')}."
        )

    def follow_up_request(
        self, instruction: str, *, origin_chat_id: str | None
    ) -> tuple[CodingWorkRequest, object]:
        item = self._select_work(
            origin_chat_id=origin_chat_id,
            active_only=False,
            require_unambiguous=True,
        )
        if item is None:
            raise CodingWorkConversationError(
                "I could not identify prior Delegated Work to continue.",
                code="coding_work_not_found",
            )
        if getattr(item, "state", None) not in {"completed", "failed", "cancelled"}:
            raise CodingWorkConversationError(
                "That Delegated Work is still active. Ask for its status or stop it first.",
                code="coding_work_active",
            )
        return (
            CodingWorkRequest(
                instruction,
                Path(item.workspace_root),
                None,
                bool(_MUTATING_ACTION.search(instruction)),
            ),
            item,
        )

    def _select_work(
        self, *, origin_chat_id: str | None, active_only: bool,
        require_unambiguous: bool = False,
    ) -> object | None:
        status = self._runtime.status()
        items = list(getattr(status, "work", ()))
        if active_only:
            items = [item for item in items if getattr(item, "state", None) in _ACTIVE_STATES]
        scoped = [
            item for item in items
            if origin_chat_id is not None
            and getattr(item, "origin_chat_id", None) == origin_chat_id
        ]
        candidates = scoped or items
        if not candidates:
            return None
        if (active_only or require_unambiguous) and len(candidates) > 1:
            raise CodingWorkConversationError(
                "More than one Delegated Work item matches; use the Workspace details to choose one.",
                code="coding_work_ambiguous",
            )
        return candidates[0]

    def validate_request(self, request: CodingWorkRequest) -> tuple[Path, os.stat_result]:
        """Resolve the exact existing directory before presenting authority."""

        if not self._runtime.admission_open:
            raise CodingWorkConversationError(
                "Coding Work is not currently available.",
                code="coding_work_unavailable",
            )
        try:
            workspace = request.requested_workspace.resolve(strict=True)
            metadata = workspace.stat()
        except (OSError, RuntimeError) as exc:
            raise CodingWorkConversationError(
                "That workspace does not exist. Workspace preparation is not available yet.",
                code="coding_work_workspace_missing",
            ) from exc
        if not workspace.is_dir():
            raise CodingWorkConversationError(
                "Coding Work requires one existing workspace directory.",
                code="coding_work_workspace_missing",
            )
        return workspace, metadata

    def propose(
        self,
        request: CodingWorkRequest,
        *,
        origin_chat_id: str,
        origin_chat_revision: int,
        project_id: str | None = None,
        related_work_id: str | None = None,
        project_title: str | None = None,
    ) -> CodingWorkProposal:
        workspace, metadata = self.validate_request(request)
        created = self._utc_clock()
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created_utc = (
            created.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        return CodingWorkProposal(
            self._identifier_factory(),
            origin_chat_id,
            origin_chat_revision,
            request.objective,
            str(workspace),
            request.acceptance_criteria,
            CODING_WORK_CAPABILITY,
            True,
            request.modify_allowed,
            True,
            tuple(
                item for item in (
                    "Read the exact workspace.",
                    (
                        "Modify files inside the exact workspace."
                        if request.modify_allowed else None
                    ),
                    "Use sandboxed command and coding tools inside that workspace.",
                )
                if item is not None
            ),
            (
                "Everything outside the workspace remains unavailable.",
                "The repository's existing Git control state is read-only.",
                "General network access, host credentials, and remote Git operations "
                "are unavailable.",
                "Workspace creation and package acquisition are not included.",
            ),
            created_utc,
            self._clock() + CODING_WORK_CONFIRMATION_SECONDS,
            metadata.st_dev,
            metadata.st_ino,
            project_id,
            related_work_id,
            project_title,
        )

    def apply(self, proposal: CodingWorkProposal) -> CodingWork:
        """Create, authorize, and start exactly the stored confirmed proposal."""

        if self._clock() > proposal.expires_at:
            raise CodingWorkConversationError(
                "That Coding Work proposal has expired.", code="expired_confirmation"
            )
        if not self._runtime.admission_open:
            raise CodingWorkConversationError(
                "Coding Work is not currently available.",
                code="coding_work_unavailable",
            )
        try:
            workspace = Path(proposal.workspace_root).resolve(strict=True)
            metadata = workspace.stat()
        except (OSError, RuntimeError) as exc:
            raise CodingWorkConversationError(
                "The proposed workspace is no longer available.",
                code="stale_confirmation",
            ) from exc
        if (
            str(workspace) != proposal.workspace_root
            or not workspace.is_dir()
            or metadata.st_dev != proposal.workspace_device
            or metadata.st_ino != proposal.workspace_inode
        ):
            raise CodingWorkConversationError(
                "The proposed workspace changed before confirmation.",
                code="stale_confirmation",
            )
        try:
            work = self._runtime.create_work(
                objective=proposal.objective,
                workspace_root=workspace,
                acceptance_criteria=proposal.acceptance_criteria,
                project_id=proposal.project_id,
                origin_chat_id=proposal.origin_chat_id,
                related_work_id=proposal.related_work_id,
            )
            authorized = self._runtime.authorize(
                work.identifier,
                expected_revision=work.revision,
                read_allowed=proposal.read_allowed,
                modify_allowed=proposal.modify_allowed,
                sandboxed_execution_allowed=proposal.sandboxed_execution_allowed,
                confirmation_provenance=(
                    "explicit_conversation_confirmation:" + proposal.identifier
                ),
            )
            return self._runtime.start_work(
                authorized.identifier, expected_revision=authorized.revision
            )
        except (CodingWorkError, CodingWorkRuntimeError, OSError) as exc:
            # Runtime/domain exceptions are intentionally converted at this boundary;
            # no adapter or process diagnostic is exposed to Conversation.
            raise CodingWorkConversationError(
                "I could not create and start the Coding Work safely.",
                code=getattr(exc, "code", "coding_work_start_failed"),
            ) from exc


def proposal_message(request: CodingWorkRequest, workspace_root: Path) -> str:
    acceptance = (
        "\nAcceptance criteria: " + request.acceptance_criteria
        if request.acceptance_criteria is not None
        else ""
    )
    return (
        "I can delegate that coding work to OpenCode, but I need your approval first.\n"
        f"Objective: {request.objective}\n"
        f"Workspace: {workspace_root}{acceptance}\n"
        "Authority: "
        + (
            "read and modify this workspace"
            if request.modify_allowed
            else "read this workspace without modifying it"
        )
        + ", with sandboxed coding tools.\n"
        "Limits: no access outside the workspace, no general network, no host credentials, "
        "and no changes to the repository's existing Git control state. "
        "No commit, push, release, deploy, or publish authority is included."
    )


def result_message(work: CodingWork) -> str:
    if work.state == "failed":
        result = work.result or {}
        detail = result.get("summary")
        if not isinstance(detail, str) or not detail:
            detail = "the worker could not start safely"
        return f"I created the Delegated Work, but could not start it because {detail}."
    if work.state in {"starting", "running", "waiting"}:
        return f"I created the Delegated Work and started OpenCode. Current state: {work.state}."
    return f"I created the Delegated Work. Its current state is {work.state}."


def delegated_work_status_message(item: object) -> str:
    """Render one concise receipt from Tori-owned structured state."""

    state = str(getattr(item, "state", "unknown"))
    objective = str(getattr(item, "objective", "Unknown objective"))
    workspace = str(getattr(item, "workspace_root", "Unknown workspace"))
    latest = getattr(item, "latest_activity", None)
    summary = getattr(item, "result_summary", None)
    paths = tuple(getattr(item, "changed_paths", ()))
    verification = tuple(getattr(item, "verification", ()))
    acceptance = getattr(item, "acceptance_status", "not_specified")
    lines = [f"Delegated Work is {state}.", f"Objective: {objective}", f"Workspace: {workspace}"]
    if isinstance(summary, str) and summary:
        lines.append("Result: " + summary)
    elif isinstance(latest, str) and latest:
        lines.append("Latest activity: " + latest)
    lines.append(
        "Changed files: " + (", ".join(paths[:20]) if paths else "none recorded")
    )
    if verification:
        rendered = []
        for evidence in verification[:10]:
            kind = evidence.get("kind", "verification")
            status = evidence.get("status", "recorded")
            rendered.append(f"{kind}: {status}")
        lines.append("Verification evidence: " + "; ".join(rendered))
    else:
        lines.append("Verification evidence: none recorded")
    lines.append({
        "not_specified": "Acceptance criteria: none were specified.",
        "pending": "Acceptance criteria: evaluation is still pending.",
        "not_completed": "Acceptance criteria: not completed.",
        "not_independently_verified": (
            "Acceptance criteria: completion was reported, but Tori has no separate "
            "structured proof that every criterion was met."
        ),
    }.get(str(acceptance), "Acceptance criteria: status is unavailable."))
    lines.append("Commit/push: not authorized by Delegated Work.")
    return "\n".join(lines)
