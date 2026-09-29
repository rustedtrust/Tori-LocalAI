"""Read-only skills.sh catalog discovery for locally administered Skills.

The public local-client endpoint was verified on 2026-09-06 as
``GET https://skills.sh/api/search?q=<query>&limit=<limit>``.  Its legacy
response supplies catalog identity, name, install count, source, and skill ID,
but neither an immutable Git revision nor an authoritative package tree.  This
module deliberately treats every field as untrusted discovery evidence.  It
has no install, enable, invocation, or permission-grant operation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
import socket
import ssl
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .request_origin import ConversationOperation, OriginAuthority, RequestOrigin
from .skills import SkillError


SKILLS_SH_DISCOVERY_VERSION = "0.1.0"
SKILLS_SH_API_HOST = "skills.sh"
MAX_QUERY_CHARS = 160
MAX_RESULTS = 5
MAX_RESPONSE_BYTES = 512 * 1024
REQUEST_TIMEOUT_SECONDS = 15.0
_SOURCE = re.compile(
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?)/"
    r"(?P<repository>[A-Za-z0-9_.-]{1,100})\Z"
)
_SKILL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")


class SkillsShDiscoveryError(SkillError):
    """A bounded catalog-discovery failure without any lifecycle effect."""


class SkillsShDiscoveryInputError(SkillsShDiscoveryError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="skills_sh_discovery_input_invalid")


class SkillsShDiscoveryNetworkError(SkillsShDiscoveryError):
    def __init__(
        self, message: str = "skills.sh discovery is temporarily unavailable.",
        *, code: str = "skills_sh_discovery_network_failed",
    ) -> None:
        super().__init__(message, code=code)


class SkillsShDiscoveryResponseError(SkillsShDiscoveryError):
    def __init__(self, message: str = "skills.sh returned an invalid discovery response.") -> None:
        super().__init__(message, code="skills_sh_discovery_response_invalid")


class SkillsShTransport(Protocol):
    def search(self, query: str, limit: int) -> bytes: ...


class _SkillsShRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (
            parsed.scheme != "https"
            or parsed.hostname != SKILLS_SH_API_HOST
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or not parsed.path.startswith("/api/")
        ):
            raise SkillsShDiscoveryNetworkError(
                "skills.sh attempted to leave the approved discovery endpoint."
            )
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class SkillsShHTTPTransport:
    """Minimal fixed-host HTTPS transport; catalog URLs are never followed."""

    def __init__(self, *, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> None:
        if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 60:
            raise ValueError("skills.sh timeout must be between zero and sixty seconds.")
        self._timeout = float(timeout_seconds)

    def search(self, query: str, limit: int) -> bytes:
        parameters = urlencode({"q": query, "limit": str(limit)})
        url = f"https://{SKILLS_SH_API_HOST}/api/search?{parameters}"
        opener = build_opener(ProxyHandler({}), _SkillsShRedirects())
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"Tori-Skills/{SKILLS_SH_DISCOVERY_VERSION}",
            },
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                final = urlsplit(response.geturl())
                if (
                    final.scheme != "https"
                    or final.hostname != SKILLS_SH_API_HOST
                    or final.port is not None
                    or not final.path.startswith("/api/")
                ):
                    raise SkillsShDiscoveryNetworkError(
                        "skills.sh discovery left its approved network scope."
                    )
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > MAX_RESPONSE_BYTES:
                    raise SkillsShDiscoveryNetworkError(
                        "The skills.sh discovery response exceeds its limit."
                    )
                result = response.read(MAX_RESPONSE_BYTES + 1)
        except SkillsShDiscoveryError:
            raise
        except HTTPError as exc:
            raise SkillsShDiscoveryNetworkError(
                code="skills_sh_discovery_http_failed"
            ) from exc
        except (URLError, OSError) as exc:
            raise SkillsShDiscoveryNetworkError(
                code=_network_failure_code("skills_sh_discovery", exc)
            ) from exc
        except ValueError as exc:
            raise SkillsShDiscoveryResponseError() from exc
        if len(result) > MAX_RESPONSE_BYTES:
            raise SkillsShDiscoveryNetworkError(
                "The skills.sh discovery response exceeds its limit."
            )
        return result


def _network_failure_code(prefix: str, error: BaseException) -> str:
    """Classify bounded transport failures without retaining network details."""

    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return f"{prefix}_dns_resolution_failed"
    if isinstance(reason, ssl.SSLError):
        return f"{prefix}_tls_failed"
    return f"{prefix}_connect_failed"


@dataclass(frozen=True, slots=True)
class SkillsShCandidate:
    """Normalized, untrusted catalog evidence for one optionally selectable item."""

    catalog_id: str
    name: str
    description: str | None
    source: str
    skill_id: str
    installs: int | None
    catalog_url: str
    github_url: str
    path_mapping: str
    is_duplicate: bool
    untrusted_metadata: Mapping[str, object]

    def document(self) -> dict[str, object]:
        return {
            "catalog_id": self.catalog_id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "skill_path": f"skills/{self.skill_id}",
            "github_source_input": self.github_url,
            "path_mapping": self.path_mapping,
            "installs": self.installs,
            "catalog_url": self.catalog_url,
            "is_duplicate": self.is_duplicate,
            "untrusted_metadata": dict(self.untrusted_metadata),
            "notice": (
                "Catalog data is untrusted discovery evidence only. Selecting this "
                "candidate still requires GitHub commit pinning, quarantine, "
                "inspection, and separate install/enable confirmation."
            ),
        }


@dataclass(frozen=True, slots=True)
class SkillsShDiscoveryResult:
    provider: str
    query: str
    retrieved_at: str
    search_type: str | None
    candidates: tuple[SkillsShCandidate, ...]

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "query": self.query,
            "retrieved_at": self.retrieved_at,
            "search_type": self.search_type,
            "candidates": [item.document() for item in self.candidates],
            "notice": "Discovery is read-only and cannot install, enable, or execute a Skill.",
        }

    def select(self, index: int) -> SkillsShCandidate:
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= len(self.candidates):
            raise SkillsShDiscoveryInputError("Choose a listed Skill number.")
        return self.candidates[index - 1]


class SkillsShDiscoveryService:
    """Application-owned, local-only discovery with no lifecycle authority."""

    def __init__(
        self,
        *,
        transport: SkillsShTransport | None = None,
        origin_authority: OriginAuthority | None = None,
        utc_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or SkillsShHTTPTransport()
        self._origin_authority = origin_authority or OriginAuthority()
        self._utc_clock = utc_clock or (lambda: datetime.now(UTC))

    def search(
        self, query: object, *, limit: object = MAX_RESULTS, origin: RequestOrigin
    ) -> SkillsShDiscoveryResult:
        self._origin_authority.require(origin, ConversationOperation.SKILL_ADMINISTER)
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        raw = self._transport.search(normalized_query, normalized_limit)
        document = _parse_response(raw)
        items = document.get("skills")
        if not isinstance(items, list):
            raise SkillsShDiscoveryResponseError()
        candidates: list[SkillsShCandidate] = []
        for item in items:
            candidate = _normalize_candidate(item)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) == normalized_limit:
                break
        search_type = document.get("searchType")
        if not isinstance(search_type, str) or len(search_type) > 80:
            search_type = None
        timestamp = self._utc_clock()
        if not isinstance(timestamp, datetime):
            raise TypeError("skills.sh clock must return a datetime.")
        return SkillsShDiscoveryResult(
            provider="skills.sh",
            query=normalized_query,
            retrieved_at=timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            search_type=search_type,
            candidates=tuple(candidates),
        )


class SkillsShResearchDiscovery:
    """Narrow background-research seam with no lifecycle or origin authority.

    Query authority is supplied and validated by Night Owl's fixed registry;
    this class only normalizes the same exact-host catalog response.
    """

    def __init__(self, *, transport: SkillsShTransport | None = None) -> None:
        self._transport = transport or SkillsShHTTPTransport()

    def search(self, query: object, *, limit: object = MAX_RESULTS) -> tuple[SkillsShCandidate, ...]:
        normalized_query = normalize_query(query)
        normalized_limit = normalize_limit(limit)
        document = _parse_response(self._transport.search(normalized_query, normalized_limit))
        items = document.get("skills")
        if not isinstance(items, list):
            raise SkillsShDiscoveryResponseError()
        candidates: list[SkillsShCandidate] = []
        for item in items:
            candidate = _normalize_candidate(item)
            if candidate is not None:
                candidates.append(candidate)
            if len(candidates) == normalized_limit:
                break
        return tuple(candidates)


def normalize_query(value: object) -> str:
    if not isinstance(value, str):
        raise SkillsShDiscoveryInputError("A short Skill search query is required.")
    normalized = " ".join(value.split())
    if not 2 <= len(normalized) <= MAX_QUERY_CHARS or any(ord(char) < 32 for char in normalized):
        raise SkillsShDiscoveryInputError(
            "A Skill search query must contain 2 to 160 printable characters."
        )
    return normalized


def normalize_limit(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_RESULTS:
        raise SkillsShDiscoveryInputError(f"Skill search limit must be between 1 and {MAX_RESULTS}.")
    return value


def _parse_response(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise SkillsShDiscoveryResponseError()
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillsShDiscoveryResponseError() from exc
    if not isinstance(document, dict):
        raise SkillsShDiscoveryResponseError()
    return MappingProxyType(document)


def _normalize_candidate(value: object) -> SkillsShCandidate | None:
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    skill_id = value.get("skillId", value.get("slug"))
    name = value.get("name")
    if (
        not isinstance(source, str)
        or _SOURCE.fullmatch(source) is None
        or not isinstance(skill_id, str)
        or _SKILL_ID.fullmatch(skill_id) is None
        or not isinstance(name, str)
        or not 1 <= len(name) <= 160
    ):
        return None
    catalog_id = value.get("id")
    if not isinstance(catalog_id, str) or catalog_id != f"{source}/{skill_id}" or len(catalog_id) > 256:
        return None
    description = _bounded_text(value.get("description"), 600)
    installs = value.get("installs")
    if not isinstance(installs, int) or isinstance(installs, bool) or not 0 <= installs <= 2**63 - 1:
        installs = None
    is_duplicate = value.get("isDuplicate") is True
    metadata = {
        key: item
        for key, item in value.items()
        if key in {"sourceType", "url", "installUrl", "hash", "audit"}
        and _metadata_value_is_safe(item)
    }
    # The legacy public endpoint has no package path.  The catalog's current
    # GitHub Agent Skills convention is source repo + skills/<skillId>.  This
    # remains a mutable source *input* only; GitHub acquisition resolves HEAD
    # to a commit, quarantines the selected directory, and rejects a mismatch.
    return SkillsShCandidate(
        catalog_id=catalog_id,
        name=_bounded_text(name, 160) or skill_id,
        description=description,
        source=source.casefold(),
        skill_id=skill_id,
        installs=installs,
        catalog_url=f"https://{SKILLS_SH_API_HOST}/{source}/{skill_id}",
        github_url=f"https://github.com/{source}/tree/HEAD/skills/{skill_id}",
        path_mapping="catalog GitHub Agent Skills convention: skills/<skillId> (unverified until inspection)",
        is_duplicate=is_duplicate,
        untrusted_metadata=MappingProxyType(metadata),
    )


def _bounded_text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        return None
    return normalized


def _metadata_value_is_safe(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return 0 <= value <= 2**63 - 1
    return isinstance(value, str) and len(value) <= 600 and not any(ord(char) < 32 for char in value)
