"""Provider-neutral contracts and policy helpers for temporary web evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from .capabilities import CapabilityResult, SourceRecord


MAX_RETRIEVAL_SOURCES = 3
MAX_DIRECT_URLS = 2
MAX_SOURCE_BODY_BYTES = 1_048_576
MAX_SOURCE_TEXT_CHARACTERS = 24_000
MAX_TOTAL_EVIDENCE_CHARACTERS = 48_000
MAX_SOURCE_REDIRECTS = 3
SOURCE_RETRIEVAL_TIMEOUT_SECONDS = 8.0
MAX_PUBLIC_URL_LENGTH = 4_096


class SourceRetrievalError(RuntimeError):
    """A safe source-retrieval failure."""

    def __init__(self, message: str, *, code: str = "retrieval_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceTarget:
    """One already-authorized public source candidate."""

    title: str
    url: str
    relationship: Literal["search_result", "direct_url"]


@dataclass(frozen=True, slots=True)
class SourceRetrievalRequest:
    """One bounded current-turn retrieval request."""

    targets: tuple[SourceTarget, ...]
    maximum_body_bytes: int = MAX_SOURCE_BODY_BYTES
    maximum_text_characters: int = MAX_SOURCE_TEXT_CHARACTERS
    maximum_total_characters: int = MAX_TOTAL_EVIDENCE_CHARACTERS
    timeout_seconds: float = SOURCE_RETRIEVAL_TIMEOUT_SECONDS
    maximum_redirects: int = MAX_SOURCE_REDIRECTS


@dataclass(frozen=True, slots=True)
class RetrievedSource:
    """Normalized untrusted evidence from one source."""

    original_url: str
    final_url: str
    title: str
    text: str
    content_type: str
    relationship: Literal["search_result", "direct_url"]


@dataclass(frozen=True, slots=True)
class SourceRetrievalFailure:
    """A safe source-bound failure without response or transport details."""

    original_url: str
    title: str
    code: str


@dataclass(frozen=True, slots=True)
class SourceRetrievalResult:
    """Bounded successes and failures for one current-turn request."""

    sources: tuple[RetrievedSource, ...]
    failures: tuple[SourceRetrievalFailure, ...]


@runtime_checkable
class SourceRetrievalPort(Protocol):
    """Retrieve bounded public source evidence or fail safely per source."""

    def retrieve(self, request: SourceRetrievalRequest) -> SourceRetrievalResult:
        """Retrieve only the explicitly supplied authorized targets."""


class SourceRetrievalService:
    """Tori-owned validation and cumulative limits around any retriever."""

    def __init__(self, provider: SourceRetrievalPort) -> None:
        self._provider = provider

    def retrieve(self, request: SourceRetrievalRequest) -> SourceRetrievalResult:
        if not 1 <= len(request.targets) <= MAX_RETRIEVAL_SOURCES:
            raise SourceRetrievalError(
                "A source request has an invalid source count.", code="invalid_request"
            )
        if (
            not 1 <= request.maximum_body_bytes <= MAX_SOURCE_BODY_BYTES
            or not 1 <= request.maximum_text_characters <= MAX_SOURCE_TEXT_CHARACTERS
            or not 1 <= request.maximum_total_characters <= MAX_TOTAL_EVIDENCE_CHARACTERS
            or not 0 < request.timeout_seconds <= SOURCE_RETRIEVAL_TIMEOUT_SECONDS
            or not 0 <= request.maximum_redirects <= MAX_SOURCE_REDIRECTS
        ):
            raise SourceRetrievalError(
                "A source request has invalid safety limits.", code="invalid_request"
            )
        result = self._provider.retrieve(request)
        requested = {target.url: target for target in request.targets}
        if len(result.sources) + len(result.failures) > len(request.targets):
            raise SourceRetrievalError(
                "The source provider returned too many results.", code="invalid_response"
            )
        observed: set[str] = set()
        total = 0
        for source in result.sources:
            target = requested.get(source.original_url)
            if (
                target is None
                or source.original_url in observed
                or not source.text
                or len(source.text) > request.maximum_text_characters
                or source.relationship != target.relationship
                or not _portable_public_url(source.final_url)
                or not source.title
                or len(source.title) > 500
                or len(source.content_type) > 100
                or _has_unsafe_controls(source.title)
                or _has_unsafe_controls(source.text, allow_layout=True)
                or _has_unsafe_controls(source.content_type)
            ):
                raise SourceRetrievalError(
                    "The source provider returned invalid evidence.",
                    code="invalid_response",
                )
            observed.add(source.original_url)
            total += len(source.text)
        for failure in result.failures:
            if (
                failure.original_url not in requested
                or failure.original_url in observed
                or not failure.code
                or len(failure.code) > 100
                or _has_unsafe_controls(failure.code)
            ):
                raise SourceRetrievalError(
                    "The source provider returned an invalid failure record.",
                    code="invalid_response",
                )
            observed.add(failure.original_url)
        if observed != set(requested):
            raise SourceRetrievalError(
                "The source provider omitted a source result.",
                code="invalid_response",
            )
        if total > request.maximum_total_characters:
            raise SourceRetrievalError(
                "The source provider exceeded Tori's evidence limit.",
                code="response_too_large",
            )
        return result


_URL_TOKEN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+")
_DIRECT_INTENT = re.compile(
    r"(?is)^\s*(?:(?:hi|hey)\s+tori\s*,?\s*|tori\s*,\s*)?"
    r"(?:(?:please\s+)|(?:can|could|would|will)\s+you\s+(?:please\s+)?|"
    r"i\s+(?:want|need|would\s+like)\s+you\s+to\s+)?"
    r"(?:read|review|open|look\s+at|inspect|summari[sz]e|explain|"
    r"analy[sz]e|compare|check)\b"
)


def explicit_source_urls(text: str) -> tuple[str, ...]:
    """Return URLs from an explicit current-request instruction to read them."""

    if not _DIRECT_INTENT.search(text):
        return ()
    tokens = tuple(match.group(0).rstrip(".,;:!?)]}") for match in _URL_TOKEN.finditer(text))
    if not tokens:
        return ()
    if len(tokens) > MAX_DIRECT_URLS:
        raise ValueError(
            f"A direct source request can include at most {MAX_DIRECT_URLS} URLs."
        )
    normalized: list[str] = []
    for token in tokens:
        try:
            parsed = urlsplit(token)
            parsed.port
        except ValueError as exc:
            raise ValueError("The requested source URL is invalid.") from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or len(token) > MAX_PUBLIC_URL_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in token)
        ):
            raise ValueError(
                "Tori can directly retrieve only public HTTP or HTTPS URLs without embedded credentials."
            )
        normalized.append(urlunsplit((
            parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""
        )))
    return tuple(dict.fromkeys(normalized))


def _portable_public_url(value: str) -> bool:
    if (
        not value
        or len(value) > MAX_PUBLIC_URL_LENGTH
        or _has_unsafe_controls(value)
        or any(character.isspace() for character in value)
        or "\\" in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
    )


def _has_unsafe_controls(value: str, *, allow_layout: bool = False) -> bool:
    return any(
        (ord(character) < 32 and not (
            allow_layout and character in {"\t", "\n", "\r"}
        ))
        or ord(character) == 127
        for character in value
    )


def retrieve_search_evidence(
    result: CapabilityResult,
    retriever: SourceRetrievalPort,
) -> CapabilityResult:
    """Replace search snippets with retrieved evidence where safely available."""

    selected = result.sources[:MAX_RETRIEVAL_SOURCES]
    retrievable = tuple(
        source for source in selected
        if (source.metadata or {}).get("evidence_kind") != "searxng_structured"
    )
    if retrievable:
        request = SourceRetrievalRequest(tuple(
            SourceTarget(source.title, source.url, "search_result") for source in retrievable
        ))
        try:
            retrieved = retriever.retrieve(request)
        except SourceRetrievalError as exc:
            retrieved = SourceRetrievalResult((), tuple(
                SourceRetrievalFailure(source.url, source.title, exc.code)
                for source in retrievable
            ))
    else:
        retrieved = SourceRetrievalResult((), ())
    by_original = {source.original_url: source for source in retrieved.sources}
    failure_by_original = {
        failure.original_url: failure for failure in retrieved.failures
    }
    sources: list[SourceRecord] = []
    for candidate in selected:
        if candidate not in retrievable:
            sources.append(candidate)
            continue
        evidence = by_original.get(candidate.url)
        if evidence is not None:
            sources.append(SourceRecord(
                evidence.title,
                evidence.final_url,
                evidence.text,
                {
                    "evidence_kind": "retrieved_page",
                    "relationship": evidence.relationship,
                    "original_url": evidence.original_url,
                    "content_type": evidence.content_type,
                },
            ))
            continue
        failure = failure_by_original.get(candidate.url)
        metadata = dict(candidate.metadata or {})
        metadata.update({
            "evidence_kind": "search_snippet",
            "relationship": "search_result",
            "retrieval_status": "failed",
            "retrieval_failure": (
                failure.code if failure is not None else "not_retrieved"
            ),
        })
        sources.append(SourceRecord(
            candidate.title, candidate.url, candidate.snippet, metadata
        ))
    return CapabilityResult(
        result.capability_id,
        result.input_text,
        result.status,
        tuple(sources),
        {
            **dict(result.metadata or {}),
            "retrieved_source_count": len(retrieved.sources),
            "failed_source_count": len(retrieved.failures),
        },
    )


def retrieve_direct_url_evidence(
    user_request: str,
    urls: tuple[str, ...],
    retriever: SourceRetrievalPort,
) -> CapabilityResult:
    """Retrieve explicitly supplied URLs without routing them through Search."""

    request = SourceRetrievalRequest(tuple(
        SourceTarget(url, url, "direct_url") for url in urls
    ))
    try:
        retrieved = retriever.retrieve(request)
    except SourceRetrievalError as exc:
        retrieved = SourceRetrievalResult((), tuple(
            SourceRetrievalFailure(url, url, exc.code) for url in urls
        ))
    by_original = {source.original_url: source for source in retrieved.sources}
    ordered_sources = tuple(
        by_original[url] for url in urls if url in by_original
    )
    return CapabilityResult(
        "web_source_retrieval",
        user_request,
        "completed",
        tuple(SourceRecord(
            source.title,
            source.final_url,
            source.text,
            {
                "evidence_kind": "retrieved_page",
                "relationship": source.relationship,
                "original_url": source.original_url,
                "content_type": source.content_type,
            },
        ) for source in ordered_sources),
        {
            "retrieved_source_count": len(retrieved.sources),
            "failed_source_count": len(retrieved.failures),
        },
    )
