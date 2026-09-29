"""Advisory, conversation-driven capability-gap recognition for Skills V1.

This module can identify only a small closed set of concrete capability gaps.
It has no discovery transport, lifecycle operation, persistence, execution, or
permission-grant surface.  External catalog text may affect presentation only;
it cannot create a gap or authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from .request_origin import ConversationOperation, OriginAuthority, RequestOrigin
from .skills_sh import SkillsShCandidate, SkillsShDiscoveryResult


MAX_GAP_REQUEST_CHARS = 2_000
MAX_SELF_LEARNING_RESULTS = 3


@dataclass(frozen=True, slots=True)
class CapabilityGap:
    """One application-validated missing capability class."""

    identifier: str
    label: str
    search_query: str
    existing_markers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _GapRule:
    gap: CapabilityGap
    patterns: tuple[re.Pattern[str], ...]


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_RULES = (
    _GapRule(
        CapabilityGap(
            "document.convert",
            "document format conversion",
            "document format conversion",
            ("convert", "converter", "conversion", "pandoc", "transcode"),
        ),
        _patterns(
            r"\b(?:convert|transform|change)\b.{0,80}\b(?:document|file|spreadsheet|presentation)\b.{0,80}(?:\bformat\b|\bto\b)",
            r"\b(?:document|file|spreadsheet|presentation)\b.{0,80}\b(?:convert|conversion|converter)\b",
        ),
    ),
    _GapRule(
        CapabilityGap(
            "pdf.modify",
            "PDF manipulation",
            "pdf merge split compress",
            ("pdf", "merge_pdf", "split_pdf", "pdf_tools"),
        ),
        _patterns(
            r"\b(?:merge|split|compress|rotate|reorder)\b.{0,60}\bpdfs?\b",
            r"\bpdfs?\b.{0,60}\b(?:merge|split|compress|rotate|reorder)\b",
        ),
    ),
    _GapRule(
        CapabilityGap(
            "image.transform",
            "image transformation",
            "image resize crop conversion",
            ("image_resize", "image_convert", "imagemagick", "background_remove"),
        ),
        _patterns(
            r"\b(?:resize|crop|convert)\b.{0,60}\b(?:image|photo|picture)s?\b",
            r"\bremove\b.{0,20}\bbackground\b.{0,40}\b(?:image|photo|picture)s?\b",
        ),
    ),
    _GapRule(
        CapabilityGap(
            "archive.manage",
            "archive creation or extraction",
            "archive zip tar extraction",
            ("archive", "zip", "unpack", "extract_archive"),
        ),
        _patterns(
            r"\b(?:create|extract|unpack|compress)\b.{0,60}\b(?:zip|archive|tar(?:ball)?)\b",
            r"\b(?:zip|archive|tar(?:ball)?)\b.{0,60}\b(?:create|extract|unpack|compress)\b",
        ),
    ),
)

_SECURITY_OR_POLICY = re.compile(
    r"\b(?:sudo|root access|privilege escalation|bypass(?:ing)?|disable security|"
    r"evade policy|arbitrary shell|unrestricted (?:filesystem|file system|network)|"
    r"extract (?:a )?(?:secret|token|password)|reveal (?:a )?(?:secret|token|password)|"
    r"rewrite (?:your|tori(?:'s)?) (?:identity|personality|memory)|"
    r"grant (?:yourself|itself) permissions?|remote restrictions?)\b",
    re.IGNORECASE,
)
_INFORMATION_OR_SEARCH = re.compile(
    r"^\s*(?:what|why|how|which|where|when|who|explain|tell me about|"
    r"search|find|look up|research)\b",
    re.IGNORECASE,
)


class CapabilityGapAdvisor:
    """Tori-owned recognizer; never delegates gap declaration to a model."""

    def __init__(self, *, origin_authority: OriginAuthority | None = None) -> None:
        self._origin_authority = origin_authority or OriginAuthority()

    def detect(
        self,
        text: object,
        *,
        origin: RequestOrigin,
        existing_capability_ids: Sequence[str] = (),
    ) -> CapabilityGap | None:
        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_GAP_REQUEST_CHARS:
            return None
        normalized = " ".join(text.split())
        if _SECURITY_OR_POLICY.search(normalized) or _INFORMATION_OR_SEARCH.match(normalized):
            return None
        for rule in _RULES:
            if not any(pattern.search(normalized) for pattern in rule.patterns):
                continue
            if _existing_capability_matches(rule.gap, existing_capability_ids):
                return None
            return rule.gap
        return None


def rank_gap_candidates(
    gap: CapabilityGap,
    result: SkillsShDiscoveryResult,
    *,
    limit: int = MAX_SELF_LEARNING_RESULTS,
) -> tuple[SkillsShCandidate, ...]:
    """Rank bounded untrusted catalog candidates without granting authority."""

    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_SELF_LEARNING_RESULTS:
        raise ValueError("Self-learning candidate limit must be between one and three.")
    query_terms = frozenset(re.findall(r"[a-z0-9]+", result.query.casefold()))

    def key(candidate: SkillsShCandidate) -> tuple[int, bool, int, str]:
        identity_terms = set(re.findall(
            r"[a-z0-9]+",
            f"{candidate.name} {candidate.skill_id} {candidate.source}".casefold(),
        ))
        relevance = len(query_terms & identity_terms)
        installs = candidate.installs if candidate.installs is not None else -1
        return (-relevance, candidate.is_duplicate, -installs, candidate.catalog_id)

    return tuple(sorted(result.candidates, key=key)[:limit])


def _existing_capability_matches(
    gap: CapabilityGap, existing_capability_ids: Sequence[str]
) -> bool:
    normalized = tuple(
        re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
        for value in existing_capability_ids
        if isinstance(value, str)
    )
    return any(
        marker in identifier
        for identifier in normalized
        for marker in gap.existing_markers
    )
