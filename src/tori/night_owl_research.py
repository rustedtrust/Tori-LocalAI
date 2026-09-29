"""Bounded deterministic public-research runner for Night Owl V1.

External material enters only through narrow discovery/inspection ports and is
treated as data.  This module has no model, scheduler, execution, Skill
lifecycle, Capability Growth, or Companion Initiative dependency.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
import socket
import ssl
import threading
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .capabilities import CapabilityError
from .night_owl import (
    DEFAULT_BUDGETS, SOURCE_POLICY_VERSION, FindingDraft, FindingEnrichment,
    NightOwlConflictError,
    NightOwlRun, NightOwlValidationError, ResearchGrant, SQLiteNightOwlStore,
    SourceAttribution, budgets_for_categories, finding_identity,
    source_policy_allows,
)
from .night_owl_analysis import (
    AnalysisRequest, NightOwlAnalysisError, NightOwlAnalysisPort, PROMPT_VERSION,
)
from .operator_observability import operator_event
from .security_intel import SecurityAdvisoryResearch
from .source_retrieval import SourceRetrievalError
from .search_port import SearchPort
from .skills_sh import (
    SkillsShDiscoveryError, SkillsShDiscoveryNetworkError,
    SkillsShDiscoveryResponseError, SkillsShResearchDiscovery,
)


@dataclass(frozen=True, slots=True)
class QueryTemplate:
    identifier: str
    category: str
    query: str
    search_category: str
    use_skills_catalog: bool = False


QUERY_TEMPLATES = {
    "local_models": QueryTemplate("local_models_recent", "local_models", "github.com recent local self-hosted LLM runtime releases", "general"),
    "voice": QueryTemplate("voice_recent", "voice", "github.com recent local self-hosted TTS STT voice releases", "general"),
    "image_generation": QueryTemplate("image_generation_recent", "image_generation", "github.com recent local self-hosted image generation releases", "general"),
    "coding_agents": QueryTemplate("coding_agents_recent", "coding_agents", "github.com recent open source coding agent tooling releases", "general"),
    "mcp_infrastructure": QueryTemplate("mcp_infrastructure_recent", "mcp_infrastructure", "github.com recent Model Context Protocol MCP infrastructure releases", "general"),
    "skills_tori_tools": QueryTemplate("skills_tori_tools_recent", "skills_tori_tools", "github.com recent Tori AI assistant skills tools", "general", True),
    "security": QueryTemplate("security_kev", "security", "site:cisa.gov/news-events/alerts/ CISA adds Known Exploited Vulnerabilities Linux NVIDIA OpenSSH CVE", "general"),
}

# Three fixed discovery angles per category.  They remain application-owned and
# contain no transcript, filesystem, account, or model-generated text.
QUERY_TEMPLATE_ANGLES = {
    "local_models": (
        QUERY_TEMPLATES["local_models"],
        QueryTemplate("local_models_api", "local_models", "github.com local LLM inference OpenAI compatible API tooling", "general"),
        QueryTemplate("local_models_updates", "local_models", "github.com emerging open source local model runtime capability updates", "general"),
    ),
    "voice": (
        QUERY_TEMPLATES["voice"],
        QueryTemplate("voice_api", "voice", "github.com local TTS STT speech API tooling", "general"),
        QueryTemplate("voice_updates", "voice", "github.com emerging open source voice speech capability updates", "general"),
    ),
    "image_generation": (
        QUERY_TEMPLATES["image_generation"],
        QueryTemplate("image_generation_api", "image_generation", "github.com local image generation HTTP API tooling", "general"),
        QueryTemplate("image_generation_updates", "image_generation", "github.com emerging open source image generation capability updates", "general"),
    ),
    "coding_agents": (
        QUERY_TEMPLATES["coding_agents"],
        QueryTemplate("coding_agents_protocol", "coding_agents", "github.com open source coding agent MCP ACP tooling", "general"),
        QueryTemplate("coding_agents_updates", "coding_agents", "github.com emerging coding assistant agent tooling updates", "general"),
    ),
    "mcp_infrastructure": (
        QUERY_TEMPLATES["mcp_infrastructure"],
        QueryTemplate("mcp_infrastructure_servers", "mcp_infrastructure", "github.com Model Context Protocol MCP server infrastructure", "general"),
        QueryTemplate("mcp_infrastructure_updates", "mcp_infrastructure", "github.com emerging open source MCP infrastructure updates", "general"),
    ),
    "skills_tori_tools": (
        QUERY_TEMPLATES["skills_tori_tools"],
        QueryTemplate("skills_tori_tools_catalog", "skills_tori_tools", "github.com Tori AI assistant skills tooling integration", "general", True),
        QueryTemplate("skills_tori_tools_updates", "skills_tori_tools", "github.com open source AI assistant skills MCP capability updates", "general", True),
    ),
    "security": (
        QUERY_TEMPLATES["security"],
        QueryTemplate("security_ubuntu", "security", "site:ubuntu.com/security/notices/USN- Ubuntu Security Notice CVE", "general"),
        QueryTemplate("security_nvidia", "security", "site:nvidia.custhelp.com/app/answers/detail/a_id/ NVIDIA Security Bulletin CVE", "general"),
    ),
}

_CATEGORY_TERMS = {
    "local_models": ("llm", "inference", "ollama", "local model", "openai compatible"),
    "voice": ("tts", "stt", "speech", "voice", "whisper"),
    "image_generation": ("image generation", "diffusion", "comfyui", "stable diffusion"),
    "coding_agents": ("coding agent", "code assistant", "opencode", "developer tool"),
    "mcp_infrastructure": ("model context protocol", "mcp server", "mcp"),
    "skills_tori_tools": ("agent skill", "assistant skill", "mcp skill", "skills.sh", "automation tool"),
}
_LOCAL_TERMS = ("local", "self-hosted", "self hosted", "offline", "on-prem", "on prem")
_PROTOCOL_TERMS = ("openai compatible", "openai-compatible", "mcp", "websocket", "http api", "rest api")
_TORI_SUBSYSTEM_TERMS = {
    "local_models": ("openai compatible", "openai-compatible", "ollama", "llama.cpp"),
    "voice": ("openai compatible", "openai-compatible", "whisper", "kokoro", "speech api", "websocket"),
    "image_generation": ("openai compatible", "openai-compatible", "http api", "rest api"),
    "coding_agents": ("opencode", "agent client protocol", " acp ", "model context protocol", "mcp"),
    "mcp_infrastructure": ("model context protocol", "mcp server", "mcp"),
    "skills_tori_tools": ("agent skill", "assistant skill", "mcp skill", "skills.sh", "model context protocol", "mcp"),
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class NightOwlResearchError(RuntimeError):
    code = "night_owl_research_failed"


class NightOwlSourceError(NightOwlResearchError):
    code = "night_owl_source_failed"
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class NightOwlBudgetError(NightOwlResearchError):
    code = "night_owl_budget_exhausted"


class NightOwlInterruptedError(NightOwlResearchError):
    code = "night_owl_interrupted"


@dataclass(frozen=True, slots=True)
class DiscoveryLead:
    title: str
    url: str
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class InspectedProject:
    owner: str
    repository: str
    title: str
    description: str | None
    html_url: str
    repository_id: int
    default_branch: str
    head_commit: str | None
    latest_release_id: int | None
    latest_release_tag: str | None
    archived: bool
    private: bool
    license_spdx: str | None
    topics: tuple[str, ...]
    updated_at: str
    retrieved_characters: int

    @property
    def source_identity(self) -> str:
        return f"github:{self.owner.casefold()}/{self.repository.casefold()}"

    @property
    def version_identity(self) -> str:
        if self.latest_release_id is not None:
            return f"github-release:{self.latest_release_id}:{self.latest_release_tag or 'untagged'}"
        if self.head_commit is not None:
            return f"github-commit:{self.head_commit}"
        return f"github-repository:{self.repository_id}:{self.updated_at}"


class DiscoveryPort(Protocol):
    def discover(self, plan: QueryTemplate, *, limit: int) -> tuple[DiscoveryLead, ...]: ...


class GitHubInspectionPort(Protocol):
    def inspect(self, repository_url: str) -> InspectedProject: ...


class SkillsDiscoveryPort(Protocol):
    def discover(self, plan: QueryTemplate, *, limit: int) -> tuple[DiscoveryLead, ...]: ...


class SearXNGNightOwlDiscovery:
    """Use SearchPort only for a registry-owned plan; never interactive consent."""

    def __init__(self, search: SearchPort) -> None:
        self._search = search

    def discover(self, plan: QueryTemplate, *, limit: int) -> tuple[DiscoveryLead, ...]:
        _validate_plan(plan)
        if type(limit) is not int or not 1 <= limit <= DEFAULT_BUDGETS["search_results"]:
            raise NightOwlValidationError("Discovery limit is invalid.")
        if not self._search.available:
            raise NightOwlSourceError("Configured SearXNG is unavailable.")
        try:
            result = self._search.search(plan.query, category=plan.search_category)
        except CapabilityError as exc:
            raise NightOwlSourceError("Configured SearXNG discovery failed.") from exc
        leads: list[DiscoveryLead] = []
        # SearXNG is discovery only, but Night Owl's subsequent evidence gate is
        # deliberately GitHub-only.  Prefer already-approved lead shapes within
        # the bounded SearXNG response before applying the per-query limit.  We
        # retain original source order within each group and still pass every
        # chosen URL through the runner's policy/canonicalization fence.
        ranked_sources = sorted(
            enumerate(result.sources),
            key=lambda item: (
                0 if isinstance(item[1].url, str) and (
                    source_policy_allows("security_advisory", item[1].url)
                    if plan.category == "security" else _canonical_github_lead(item[1].url) is not None
                ) else 1,
                item[0],
            ),
        )
        inspected = tuple(source for _index, source in ranked_sources[:limit])
        unusable = 0
        for source in inspected:
            if not isinstance(source.title, str) or not isinstance(source.url, str):
                unusable += 1
                continue
            leads.append(DiscoveryLead(source.title[:200], source.url[:2048], None if source.snippet is None else source.snippet[:500]))
        operator_event(
            "night_owl.searxng.results",
            category=plan.category,
            result_count=len(inspected),
            usable_count=len(leads),
            unusable_count=unusable,
        )
        return tuple(leads)


class SkillsShNightOwlDiscovery:
    """Research-only catalog seam with no Skill lifecycle methods."""

    def __init__(self, discovery: SkillsShResearchDiscovery | None = None) -> None:
        self._discovery = discovery or SkillsShResearchDiscovery()

    def discover(self, plan: QueryTemplate, *, limit: int) -> tuple[DiscoveryLead, ...]:
        _validate_plan(plan)
        if not plan.use_skills_catalog:
            raise NightOwlValidationError("That query template does not admit skills.sh.")
        try:
            candidates = self._discovery.search(plan.query, limit=min(limit, 2))
        except SkillsShDiscoveryNetworkError as exc:
            raise NightOwlSourceError(
                "skills.sh discovery network failed.",
                code=exc.code.replace("skills_sh_discovery_", "skills_source_"),
            ) from exc
        except SkillsShDiscoveryResponseError as exc:
            raise NightOwlSourceError(
                "skills.sh discovery response was invalid.",
                code="skills_source_response_invalid",
            ) from exc
        except SkillsShDiscoveryError as exc:
            raise NightOwlSourceError(
                "skills.sh discovery failed.", code="skills_source_failed"
            ) from exc
        return tuple(
            DiscoveryLead(item.name[:200], item.github_url, item.description)
            for item in candidates
        )


class _GitHubRedirects(HTTPRedirectHandler):
    def __init__(self, owner: str, repository: str) -> None:
        self._prefix = f"/repos/{owner}/{repository}"

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (
            parsed.scheme != "https" or parsed.hostname != "api.github.com"
            or parsed.port is not None or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {self._prefix, self._prefix + "/releases/latest"}
            or parsed.query or parsed.fragment
        ):
            raise NightOwlSourceError(
                "GitHub attempted to leave the approved source scope.",
                code="github_source_policy_rejected",
            )
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class GitHubPublicInspector:
    """Read public repository metadata and release identity without cloning."""

    def __init__(self, *, timeout_seconds: float = 15.0, max_response_bytes: int = 512 * 1024) -> None:
        if not 0 < timeout_seconds <= 60 or not 1024 <= max_response_bytes <= 2 * 1024 * 1024:
            raise ValueError("GitHub inspection limits are invalid.")
        self._timeout = float(timeout_seconds)
        self._limit = max_response_bytes

    def inspect(self, repository_url: str) -> InspectedProject:
        owner, repository = _github_repository(repository_url)
        base = f"https://api.github.com/repos/{quote(owner)}/{quote(repository)}"
        repo, repo_size = self._get(owner, repository, base)
        if repo.get("private") is not False:
            raise NightOwlSourceError("Night Owl accepts public GitHub repositories only.")
        release = None
        release_size = 0
        try:
            release, release_size = self._get(owner, repository, base + "/releases/latest", allow_not_found=True)
        except NightOwlSourceError:
            raise
        html_url = repo.get("html_url")
        full_name = repo.get("full_name")
        repository_id = repo.get("id")
        default_branch = repo.get("default_branch")
        updated_at = repo.get("updated_at")
        try:
            html_identity = _github_repository(html_url) if isinstance(html_url, str) else None
        except NightOwlSourceError:
            html_identity = None
        if (
            html_identity != (owner, repository)
            or not isinstance(full_name, str) or full_name.casefold() != f"{owner}/{repository}".casefold()
            or type(repository_id) is not int or repository_id < 1
            or not isinstance(default_branch, str) or not default_branch
            or not isinstance(updated_at, str) or len(updated_at) > 40
        ):
            raise NightOwlSourceError("GitHub returned inconsistent repository identity.")
        topics = repo.get("topics", [])
        if not isinstance(topics, list): topics = []
        clean_topics = tuple(sorted(item.casefold() for item in topics if isinstance(item, str) and len(item) <= 80))[:20]
        license_doc = repo.get("license")
        license_spdx = license_doc.get("spdx_id") if isinstance(license_doc, Mapping) else None
        if not isinstance(license_spdx, str) or len(license_spdx) > 40: license_spdx = None
        release_id = release.get("id") if isinstance(release, Mapping) else None
        release_tag = release.get("tag_name") if isinstance(release, Mapping) else None
        target = release.get("target_commitish") if isinstance(release, Mapping) else None
        if type(release_id) is not int or release_id < 1: release_id = None
        if not isinstance(release_tag, str) or len(release_tag) > 100: release_tag = None
        if not isinstance(target, str) or _SHA.fullmatch(target) is None: target = None
        description = repo.get("description")
        if not isinstance(description, str) or len(description) > 500: description = None
        return InspectedProject(
            owner.casefold(), repository.casefold(), full_name, description, html_url,
            repository_id, default_branch, target, release_id, release_tag,
            repo.get("archived") is True, False, license_spdx, clean_topics,
            updated_at, repo_size + release_size,
        )

    def _get(self, owner: str, repository: str, url: str, *, allow_not_found: bool = False) -> tuple[Mapping[str, object] | None, int]:
        if not source_policy_allows("github_api", url):
            raise NightOwlSourceError(
                "GitHub resource is outside the Night Owl source policy.",
                code="github_source_policy_rejected",
            )
        opener = build_opener(ProxyHandler({}), _GitHubRedirects(owner, repository))
        request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Tori-Night-Owl/1", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with opener.open(request, timeout=self._timeout) as response:
                final = response.geturl()
                if not source_policy_allows("github_api", final):
                    raise NightOwlSourceError(
                        "GitHub response left the approved source policy.",
                        code="github_source_policy_rejected",
                    )
                raw = response.read(self._limit + 1)
        except HTTPError as exc:
            if allow_not_found and exc.code == 404: return None, 0
            code = _github_http_failure_code(exc)
            operator_event(
                "night_owl.github.http_failure",
                status=exc.code,
                code=code,
                rate_limit_remaining=(
                    None if exc.headers is None
                    else exc.headers.get("X-RateLimit-Remaining")
                ),
            )
            raise NightOwlSourceError(
                "Public GitHub inspection failed.",
                code=code,
            ) from exc
        except (NightOwlSourceError, URLError, OSError) as exc:
            if isinstance(exc, NightOwlSourceError): raise
            raise NightOwlSourceError(
                "Public GitHub inspection failed.",
                code=_network_failure_code("github_source", exc),
            ) from exc
        except ValueError as exc:
            raise NightOwlSourceError(
                "GitHub returned malformed metadata.",
                code="github_source_response_invalid",
            ) from exc
        if len(raw) > self._limit: raise NightOwlSourceError("GitHub response exceeded its bound.")
        try: document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise NightOwlSourceError("GitHub returned malformed JSON.") from exc
        if not isinstance(document, Mapping): raise NightOwlSourceError("GitHub returned malformed metadata.")
        return document, len(raw)


def _network_failure_code(prefix: str, error: BaseException) -> str:
    """Classify safe transport outcomes without persisting endpoint details."""

    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, socket.gaierror):
        return f"{prefix}_dns_resolution_failed"
    if isinstance(reason, ssl.SSLError):
        return f"{prefix}_tls_failed"
    return f"{prefix}_connect_failed"


@dataclass(slots=True)
class _Budget:
    limits: dict[str, int]
    used: dict[str, int]

    def spend(self, key: str, amount: int = 1) -> None:
        if key not in self.limits or type(amount) is not int or amount < 0:
            raise NightOwlValidationError("Research budget accounting is invalid.")
        if self.used.get(key, 0) + amount > self.limits[key]:
            raise NightOwlBudgetError(f"{key}_limit")
        self.used[key] = self.used.get(key, 0) + amount


@dataclass(frozen=True, slots=True)
class _ResearchCandidate:
    category: str
    plan: QueryTemplate
    repository_url: str
    priority: int


class NightOwlResearchRunner:
    """Run one explicit, bounded, deterministic research occurrence."""

    def __init__(
        self, store: SQLiteNightOwlStore, discovery: DiscoveryPort,
        github: GitHubInspectionPort, *, skills: SkillsDiscoveryPort | None = None,
        analysis: NightOwlAnalysisPort | None = None,
        analysis_ready: Callable[[], bool] = lambda: True,
        monotonic: Callable[[], float] = time.monotonic,
        security: SecurityAdvisoryResearch | None = None,
    ) -> None:
        self._store, self._discovery, self._github = store, discovery, github
        self._skills, self._analysis = skills, analysis
        self._analysis_ready, self._monotonic = analysis_ready, monotonic
        self._security = security
        self._interrupt = threading.Event()

    def request_interrupt(self) -> None:
        """Fence new external work during application shutdown."""
        self._interrupt.set()

    def run_now(
        self, grant: ResearchGrant, *, trigger: str = "manual",
        invocation_id: str | None = None,
    ) -> NightOwlRun:
        if not isinstance(grant, ResearchGrant):
            raise NightOwlValidationError("An active Night Owl grant is required.")
        if grant.source_policy_version != SOURCE_POLICY_VERSION:
            raise NightOwlConflictError("Night Owl source-policy authority is stale.")
        if dict(grant.budgets) != budgets_for_categories(grant.categories):
            raise NightOwlConflictError("Night Owl budget-policy authority is stale.")
        for category in grant.categories:
            self._store.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category=category, source_policy_version=SOURCE_POLICY_VERSION)
        try:
            run = self._store.create_run(
                trigger=trigger, grant=grant, invocation_id=invocation_id
            )
        except NightOwlConflictError:
            if trigger == "scheduled":
                current = self._store.active_grant()
                if current != grant:
                    raise
                return self._store.record_skipped_run(
                    trigger="scheduled", grant=grant, error_code="already_running",
                    invocation_id=invocation_id,
                )
            raise
        run = self._store.transition_run(run.identifier, "running", expected_revision=run.revision)
        budget = _Budget(dict(grant.budgets), {})
        errors: list[str] = []
        discoveries_ok = 0
        finding_changes = 0
        start = self._monotonic()
        try:
            candidates: dict[str, list[_ResearchCandidate]] = {
                category: [] for category in grant.categories
            }
            security_leads: dict[str, list[str]] = {
                plan.identifier: [] for plan in QUERY_TEMPLATE_ANGLES.get("security", ())
            }
            metrics = _run_metrics(grant.categories)
            for category in grant.categories:
                for plan in QUERY_TEMPLATE_ANGLES[category]:
                    self._admit(grant, category, plan, budget, start)
                    budget.spend("searches")
                    metrics[category]["searches_executed"] += 1
                    try:
                        category_remaining = 12 - metrics[category]["results_considered"]
                        remaining = budget.limits["search_results"] - budget.used.get("search_results", 0)
                        if category_remaining < 1:
                            raise NightOwlBudgetError("search_results_limit")
                        if remaining < 1:
                            raise NightOwlBudgetError("search_results_limit")
                        # Search-result consideration is deliberately bounded per
                        # category. Skills catalog candidates have their own budget
                        # and never borrow this SearXNG discovery allowance.
                        search_limit = min(4, category_remaining, remaining)
                        leads = list(self._discovery.discover(plan, limit=search_limit))[:search_limit]
                        discoveries_ok += 1
                    except NightOwlSourceError:
                        errors.append("searxng_unavailable")
                        leads = []
                    usable = 0
                    policy_rejected = 0
                    for lead in leads:
                        self._admit(grant, category, plan, budget, start)
                        budget.spend("search_results")
                        metrics[category]["results_considered"] += 1
                        if _github_hosted_lead(lead.url):
                            metrics[category]["github_hosted_results"] += 1
                        if category == "security":
                            if source_policy_allows("security_advisory", lead.url):
                                if lead.url not in security_leads[plan.identifier]:
                                    security_leads[plan.identifier].append(lead.url)
                                usable += 1
                                metrics[category]["usable_discovery_leads"] += 1
                            else:
                                policy_rejected += 1
                                metrics[category]["source_policy_rejected"] += 1
                            continue
                        repository_url = _canonical_github_lead(lead.url)
                        if repository_url is None:
                            policy_rejected += 1
                            metrics[category]["source_policy_rejected"] += 1
                            continue  # discovery-only hints never become findings
                        usable += 1
                        metrics[category]["usable_discovery_leads"] += 1
                        # This legacy metric is a canonical repository lead, not
                        # merely a result hosted somewhere on github.com.
                        metrics[category]["github_eligible_leads"] += 1
                        candidates[category].append(
                            _ResearchCandidate(category, plan, repository_url, _lead_priority(category, lead))
                        )
                    if plan.use_skills_catalog and self._skills is not None:
                        self._admit(grant, category, plan, budget, start)
                        metrics[category]["skills_catalog_attempts"] += 1
                        try:
                            skill_leads = list(self._skills.discover(plan, limit=2))[:2]
                            budget.spend("skills_inspections", len(skill_leads))
                            metrics[category]["skills_catalog_successes"] += 1
                            metrics[category]["skills_catalog_candidates"] += len(skill_leads)
                            for lead in skill_leads:
                                self._admit(grant, category, plan, budget, start)
                                if _github_hosted_lead(lead.url):
                                    metrics[category]["github_hosted_results"] += 1
                                repository_url = _canonical_github_lead(lead.url)
                                if repository_url is None:
                                    policy_rejected += 1
                                    metrics[category]["source_policy_rejected"] += 1
                                    continue
                                usable += 1
                                metrics[category]["usable_discovery_leads"] += 1
                                metrics[category]["github_eligible_leads"] += 1
                                candidates[category].append(
                                    _ResearchCandidate(category, plan, repository_url, _lead_priority(category, lead))
                                )
                        except NightOwlSourceError as exc:
                            metrics[category]["skills_catalog_failures"] += 1
                            errors.append(exc.code)
                        except NightOwlBudgetError as exc:
                            metrics[category]["skills_catalog_failures"] += 1
                            errors.append(str(exc))
                    operator_event("night_owl.discovery.category", category=category, result_count=len(leads), usable_count=usable, policy_rejected=policy_rejected)

            # A separate, source-fenced primary-advisory lane reuses this run's
            # grant, budgets, finding store, review lifecycle, and run receipts.
            # Neither search snippets nor retrieved instructions become commands.
            # Prefer one primary lead from each fixed angle before spending a
            # second fetch on the same publisher. Every URL still crosses the
            # identical allowlist and per-run source budget.
            selected_security: list[str] = []
            for index in range(4):
                for plan in QUERY_TEMPLATE_ANGLES.get("security", ()):
                    leads = security_leads[plan.identifier]
                    if index < len(leads) and leads[index] not in selected_security:
                        selected_security.append(leads[index])
            for url in selected_security[:3]:
                category = "security"
                self._admit(grant, category, QUERY_TEMPLATE_ANGLES[category][0], budget, start)
                if self._security is None:
                    errors.append("security_source_unavailable")
                    break
                try:
                    draft, characters = self._security.inspect(url)
                    budget.spend("retrieved_characters", characters)
                except SourceRetrievalError:
                    errors.append("security_source_unavailable")
                    continue
                if draft is None:
                    if not url.endswith("/known-exploited-vulnerabilities-catalog"):
                        self._store.withdraw_finding("security", url, "primary_advisory")
                    metrics[category]["relevance_rejected"] += 1
                    continue
                self._admit(grant, category, QUERY_TEMPLATE_ANGLES[category][0], budget, start)
                key = finding_identity(draft.category, draft.source_identity, draft.finding_kind)
                try:
                    prior = self._store.get_finding(key)
                    will_change = prior.current_fingerprint != draft.material_fingerprint
                except NightOwlConflictError:
                    will_change = True
                if will_change:
                    budget.spend("new_findings")
                _, changed = self._store.record_finding(draft, run_id=run.identifier)
                if changed:
                    finding_changes += 1
                    metrics[category]["findings_retained"] += 1

            selected, skipped = _fair_candidates(
                candidates,
                max_projects=(
                    budget.limits["github_fetches"]
                    - budget.used.get("github_fetches", 0)
                ) // 2,
                category_order=grant.categories,
            )
            # Count the actual de-duplicated queue, rather than every candidate
            # before cross-category de-duplication. This makes the funnel honest.
            for category in grant.categories:
                metrics[category]["canonical_repositories_queued"] = 0
            for candidate in (*selected, *skipped):
                metrics[candidate.category]["canonical_repositories_queued"] += 1
            if skipped:
                errors.append("github_fetches_limit")
            for category in grant.categories:
                category_skipped = sum(
                    item.category == category for item in skipped
                )
                if category_skipped:
                    metrics[category]["corroboration_budget_skipped"] += category_skipped
                    operator_event(
                        "night_owl.candidate.budget_skipped",
                        category=category,
                        count=category_skipped,
                    )

            for candidate in selected:
                category, plan = candidate.category, candidate.plan
                metrics[category]["repositories_selected"] += 1
                self._admit(grant, category, plan, budget, start)
                budget.spend("github_fetches", 2)
                try:
                    project = self._github.inspect(candidate.repository_url)
                except NightOwlSourceError as exc:
                    errors.append(exc.code)
                    metrics[category]["corroboration_failures"] += 1
                    operator_event(
                        "night_owl.candidate.corroboration_failed",
                        category=category,
                        count=1,
                    )
                    continue
                budget.spend("retrieved_characters", project.retrieved_characters)
                metrics[category]["repositories_inspected"] += 1
                self._admit(grant, category, plan, budget, start)
                draft = _finding(category, project)
                if draft is None:
                    withdrawn = self._store.withdraw_finding(
                        category, project.source_identity, "github_project"
                    )
                    metrics[category]["relevance_rejected"] += 1
                    operator_event(
                        "night_owl.candidate.relevance_rejected",
                        category=category,
                        count=1,
                    )
                    if withdrawn is not None and withdrawn.state == "stale":
                        operator_event(
                            "night_owl.finding.withdrawn",
                            category=category,
                            reason="current_policy_reassessment",
                        )
                    continue
                key = finding_identity(draft.category, draft.source_identity, draft.finding_kind)
                try:
                    prior = self._store.get_finding(key)
                    will_change = prior.current_fingerprint != draft.material_fingerprint
                except NightOwlConflictError:
                    will_change = True
                if will_change: budget.spend("new_findings")
                finding, changed = self._store.record_finding(
                    draft, run_id=run.identifier
                )
                if changed:
                    finding_changes += 1
                    metrics[category]["findings_retained"] += 1
                    if self._analysis is not None:
                        self._enrich(
                            grant, category, plan, budget, start,
                            finding.identifier, draft, errors,
                        )
            operator_event(
                "night_owl.research.summary",
                category_count=len(grant.categories),
                discovery_successes=discoveries_ok,
                findings_changed=finding_changes,
                github_fetches=budget.used.get("github_fetches", 0),
                search_results=budget.used.get("search_results", 0),
            )
            terminal = "completed"
            if errors and (discoveries_ok or finding_changes): terminal = "partial"
            elif errors and discoveries_ok == 0: terminal = "failed"
        except NightOwlInterruptedError as exc:
            errors.append(exc.code); terminal = "interrupted"
        except NightOwlBudgetError as exc:
            errors.append(str(exc)); terminal = "partial" if discoveries_ok or finding_changes else "failed"
        except Exception:
            errors.append("research_internal_failure"); terminal = "partial" if finding_changes else "failed"
        result = self._store.transition_run(run.identifier, terminal, expected_revision=run.revision, budget_used=budget.used, error_codes=tuple(dict.fromkeys(errors)))
        # Metrics are persisted only after terminal state so an interrupted
        # process can never claim a completed diagnostic record.
        self._store.record_run_metrics(
            result.identifier,
            aggregate={
                "discovery_successes": discoveries_ok,
                "findings_changed": finding_changes,
                "source_policy_rejected": sum(item["source_policy_rejected"] for item in metrics.values()),
                "relevance_rejected": sum(item["relevance_rejected"] for item in metrics.values()),
                "corroboration_failures": sum(item["corroboration_failures"] for item in metrics.values()),
                "corroboration_budget_skipped": sum(item["corroboration_budget_skipped"] for item in metrics.values()),
                "results_considered": sum(item["results_considered"] for item in metrics.values()),
                "github_hosted_results": sum(item["github_hosted_results"] for item in metrics.values()),
                "github_eligible_leads": sum(item["github_eligible_leads"] for item in metrics.values()),
                "canonical_repositories_queued": sum(item["canonical_repositories_queued"] for item in metrics.values()),
                "repositories_inspected": sum(item["repositories_inspected"] for item in metrics.values()),
                "skills_catalog_attempts": sum(item["skills_catalog_attempts"] for item in metrics.values()),
                "skills_catalog_successes": sum(item["skills_catalog_successes"] for item in metrics.values()),
                "skills_catalog_failures": sum(item["skills_catalog_failures"] for item in metrics.values()),
                "skills_catalog_candidates": sum(item["skills_catalog_candidates"] for item in metrics.values()),
            },
            categories=metrics,
            duration_millis=max(0, int((self._monotonic() - start) * 1000)),
        )
        return result

    def _admit(self, grant: ResearchGrant, category: str, plan: QueryTemplate, budget: _Budget, start: float) -> None:
        if self._interrupt.is_set():
            raise NightOwlInterruptedError("Night Owl was interrupted safely.")
        _validate_plan(plan)
        if plan.category != category or plan not in QUERY_TEMPLATE_ANGLES.get(category, ()):
            raise NightOwlValidationError("Only registered Night Owl query templates are admitted.")
        self._store.verify_grant(grant.identifier, revision=grant.revision, digest=grant.digest, category=category, source_policy_version=SOURCE_POLICY_VERSION)
        if self._monotonic() - start >= budget.limits["run_seconds"]:
            raise NightOwlBudgetError("run_seconds_limit")

    def _enrich(
        self,
        grant: ResearchGrant,
        category: str,
        plan: QueryTemplate,
        budget: _Budget,
        start: float,
        finding_id: str,
        draft: FindingDraft,
        errors: list[str],
    ) -> None:
        assert self._analysis is not None
        self._admit(grant, category, plan, budget, start)
        if self._analysis_ready() is not True:
            errors.append("enrichment_foreground_busy")
            return
        remaining_output = (
            budget.limits["model_output_tokens"]
            - budget.used.get("model_output_tokens", 0)
        )
        if remaining_output < 1:
            errors.append("model_output_tokens_limit")
            return
        request = AnalysisRequest.from_draft(
            draft, max_output_tokens=remaining_output
        )
        remaining_input = (
            budget.limits["model_input_tokens"]
            - budget.used.get("model_input_tokens", 0)
        )
        if request.conservative_input_tokens > remaining_input:
            errors.append("model_input_tokens_limit")
            return
        try:
            budget.spend("model_calls")
            budget.spend("model_input_tokens", request.conservative_input_tokens)
            result = self._analysis.analyze(request)
            if result.input_tokens > request.conservative_input_tokens:
                budget.spend(
                    "model_input_tokens",
                    result.input_tokens - request.conservative_input_tokens,
                )
            budget.spend("model_output_tokens", result.output_tokens)
            version = self._store.current_version(finding_id)
            self._store.record_enrichment(
                version.identifier,
                FindingEnrichment(
                    version.identifier, result.summary, result.why_it_matters,
                    result.risks, result.unknowns, result.next_step,
                    result.provider, result.model, request.input_digest,
                    PROMPT_VERSION,
                ),
            )
        except NightOwlBudgetError as exc:
            errors.append(str(exc))
        except NightOwlAnalysisError as exc:
            errors.append(exc.code)
        except (NightOwlConflictError, NightOwlValidationError):
            errors.append("enrichment_persistence_unavailable")


def _validate_plan(plan: QueryTemplate) -> None:
    if not isinstance(plan, QueryTemplate) or plan not in QUERY_TEMPLATE_ANGLES.get(plan.category, ()):
        raise NightOwlValidationError("Research query provenance is invalid.")


def _github_repository(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.port is not None or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise NightOwlSourceError("Only canonical public GitHub repositories are supported.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts):
        raise NightOwlSourceError("GitHub repository identity is invalid.")
    repository = parts[1].removesuffix(".git")
    if not repository: raise NightOwlSourceError("GitHub repository identity is invalid.")
    return parts[0].casefold(), repository.casefold()


def _canonical_github_lead(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.port is not None or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts[:2]): return None
        owner, repository = parts[0].casefold(), parts[1].removesuffix(".git").casefold()
        if not repository: return None
        tail = parts[2:]
        # Search leads establish only a repository subject.  These are the
        # public repository/release/commit/tree/blob forms Night Owl may reduce
        # to that subject for a separate API metadata/release corroboration.
        if tail:
            family = tail[0]
            if family == "releases":
                if len(tail) > 3 or (len(tail) > 1 and tail[1] not in {"tag", "latest"}):
                    return None
            elif family == "commit":
                if len(tail) != 2 or re.fullmatch(r"[0-9a-fA-F]{7,64}", tail[1]) is None:
                    return None
            elif family == "tree":
                if len(tail) < 2 or len(tail) > 202:
                    return None
            elif family == "blob":
                if len(tail) < 3 or len(tail) > 202:
                    return None
            else:
                return None
    except ValueError:
        return None
    return f"https://github.com/{owner}/{repository}"


def _github_hosted_lead(value: str) -> bool:
    """Classify a discovery hint for diagnostics without granting it authority."""

    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.hostname == "github.com"
    except ValueError:
        return False


def _lead_priority(category: str, lead: DiscoveryLead) -> int:
    """Rank untrusted hints only inside their already-authorized category."""

    text = f"{lead.title} {lead.snippet or ''}".casefold()
    return (
        4 * sum(term in text for term in _TORI_SUBSYSTEM_TERMS[category])
        + 2 * sum(term in text for term in _PROTOCOL_TERMS)
        + sum(term in text for term in _CATEGORY_TERMS[category])
        + sum(term in text for term in _LOCAL_TERMS)
    )


def _fair_candidates(
    candidates: Mapping[str, Sequence[_ResearchCandidate]],
    *,
    max_projects: int,
    category_order: Sequence[str],
) -> tuple[tuple[_ResearchCandidate, ...], tuple[_ResearchCandidate, ...]]:
    """Round-robin category queues after ranking, never by discovery order alone."""

    queues = {
        category: sorted(
            candidates.get(category, ()),
            key=lambda item: (-item.priority, item.repository_url),
        )
        for category in category_order
    }
    ordered = sorted(
        category_order,
        key=lambda category: (
            -(queues[category][0].priority if queues[category] else -1),
            category_order.index(category),
        ),
    )
    fair: list[_ResearchCandidate] = []
    seen_repositories: set[str] = set()
    while any(queues.values()):
        for category in ordered:
            if queues[category]:
                candidate = queues[category].pop(0)
                if candidate.repository_url in seen_repositories:
                    continue
                seen_repositories.add(candidate.repository_url)
                fair.append(candidate)
    return tuple(fair[:max_projects]), tuple(fair[max_projects:])


def _run_metrics(categories: Sequence[str]) -> dict[str, dict[str, int]]:
    return {
        category: {
            "searches_executed": 0,
            "results_considered": 0,
            "usable_discovery_leads": 0,
            "github_hosted_results": 0,
            "github_eligible_leads": 0,
            "canonical_repositories_queued": 0,
            "repositories_selected": 0,
            "repositories_inspected": 0,
            "source_policy_rejected": 0,
            "relevance_rejected": 0,
            "corroboration_failures": 0,
            "corroboration_budget_skipped": 0,
            "findings_retained": 0,
            "skills_catalog_attempts": 0,
            "skills_catalog_successes": 0,
            "skills_catalog_failures": 0,
            "skills_catalog_candidates": 0,
        }
        for category in categories
    }


def _finding(category: str, project: InspectedProject) -> FindingDraft | None:
    if project.private or project.archived: return None
    text = " ".join((project.title, project.description or "", *project.topics)).casefold()
    if not any(term in text for term in _CATEGORY_TERMS[category]): return None
    reasons = ["category_match"]
    if any(term in text for term in _LOCAL_TERMS): reasons.append("local_self_hosted")
    if any(term in text for term in _PROTOCOL_TERMS): reasons.append("protocol_fit")
    if any(term in text for term in _TORI_SUBSYSTEM_TERMS[category]):
        reasons.append("tori_subsystem_fit")
    if category == "skills_tori_tools" and "tori_subsystem_fit" in reasons:
        reasons.append("capability_gap")
    if not any(
        reason in reasons
        for reason in ("protocol_fit", "tori_subsystem_fit", "capability_gap")
    ):
        return None
    material = {
        "repository_id": project.repository_id, "version": project.version_identity,
        "archived": project.archived, "license": project.license_spdx,
        "topics": project.topics,
    }
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    unknowns = [] if project.license_spdx else ["license_unknown"]
    return FindingDraft(
        category, project.source_identity, "github_project", project.title[:200],
        _source_summary(category, project),
        tuple(reasons), (), tuple(unknowns),
        "Review compatibility and risks in a separate explicitly authorized workflow.",
        fingerprint, project.version_identity, "material_source_identity_changed",
        (SourceAttribution("github_page", project.html_url, project.title[:200], project.source_identity, project.version_identity),),
    )


def _source_summary(category: str, project: InspectedProject) -> str:
    """Return a bounded source-derived explanation, never provenance shorthand."""

    description = _safe_source_description(project.description)
    if description:
        return description[:1000]
    capability = {
        "local_models": "local model tooling",
        "voice": "voice, TTS, or STT tooling",
        "image_generation": "image-generation tooling",
        "coding_agents": "coding or agent tooling",
        "mcp_infrastructure": "MCP infrastructure",
        "skills_tori_tools": "agent Skills or tool-integration tooling",
    }[category]
    topics = ", ".join(project.topics[:3])
    suffix = f" Its published topics include {topics}." if topics else ""
    return f"{project.title} is a public GitHub project for {capability}.{suffix}"[:1000]


def _safe_source_description(value: str | None) -> str:
    """Keep short factual metadata while dropping instruction-shaped sentences."""

    if not isinstance(value, str):
        return ""
    forbidden = (
        "ignore previous", "run this command", "install", "download", "execute",
        "edit your configuration", "add this api key", "connect this mcp", "://",
    )
    safe = [
        sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", value.strip())
        if sentence.strip() and not any(term in sentence.casefold() for term in forbidden)
    ]
    return " ".join(safe)[:1000]


def _github_http_failure_code(error: HTTPError) -> str:
    """Classify public HTTP outcomes without persisting headers or response bodies."""

    headers = error.headers
    remaining = None if headers is None else headers.get("X-RateLimit-Remaining")
    retry_after = None if headers is None else headers.get("Retry-After")
    if error.code == 429 or (error.code == 403 and (remaining == "0" or retry_after)):
        return "github_source_rate_limited"
    if error.code == 404:
        return "github_source_not_found"
    if error.code == 403:
        return "github_source_forbidden"
    if 500 <= error.code <= 599:
        return "github_source_server_failed"
    return "github_source_http_failed"
