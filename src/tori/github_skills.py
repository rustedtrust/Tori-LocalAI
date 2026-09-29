"""GitHub-only acquisition and confirmation for instruction Agent Skills.

Downloaded archives are untrusted evidence.  This module resolves an explicit
public GitHub source to a commit, extracts only the selected package into a
private disposable quarantine, and delegates package validation to the Agent
Skills importer.  It never executes repository or package content.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import tempfile
import threading
import time
from types import MappingProxyType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .agent_skills import (
    AgentSkillAdministration,
    AgentSkillFile,
    AgentSkillImporter,
    AgentSkillInspectionResult,
    MAX_FILE_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_PACKAGE_FILES,
)
from .request_origin import RequestOrigin
from .skills import (
    SKILL_MANIFEST_SCHEMA_VERSION,
    SkillError,
    SkillPermission,
    SkillRegistryEntry,
    SkillValidationError,
    SkillVersionRef,
)


GITHUB_ACQUISITION_VERSION = "0.2.0"
PROPOSAL_LIFETIME_SECONDS = 300
MAX_GITHUB_JSON_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_TREE_ENTRIES = 512
MAX_PACKAGE_TREE_DEPTH = 32
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?\Z")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}\Z")


class GitHubSkillError(SkillError):
    """Bounded acquisition/proposal failure with an application error code."""


class GitHubSkillSourceError(GitHubSkillError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="github_skill_source_invalid")


class GitHubSkillNetworkError(GitHubSkillError):
    def __init__(self, message: str = "The public GitHub Skill source could not be retrieved.") -> None:
        super().__init__(message, code="github_skill_network_failed")


class GitHubSkillProposalError(GitHubSkillError):
    def __init__(self, message: str, *, code: str = "skill_proposal_invalid") -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True, slots=True)
class GitHubSkillSource:
    owner: str
    repository_name: str
    revision: str
    package_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.owner, str) or _OWNER.fullmatch(self.owner) is None:
            raise GitHubSkillSourceError("The GitHub repository owner is invalid.")
        if (
            not isinstance(self.repository_name, str)
            or _REPOSITORY.fullmatch(self.repository_name) is None
            or self.repository_name in {".", ".."}
        ):
            raise GitHubSkillSourceError("The GitHub repository name is invalid.")
        if not isinstance(self.revision, str) or _REVISION.fullmatch(self.revision) is None:
            raise GitHubSkillSourceError("The GitHub revision is invalid.")
        _package_parts(self.package_path)
        object.__setattr__(self, "owner", self.owner.casefold())
        object.__setattr__(self, "repository_name", self.repository_name.casefold())

    @property
    def repository_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repository_name}"


def parse_github_skill_url(value: object) -> GitHubSkillSource:
    """Parse one common GitHub tree URL without accepting alternate hosts."""

    if not isinstance(value, str) or not value or len(value) > 2_048:
        raise GitHubSkillSourceError("A bounded public GitHub Skill URL is required.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GitHubSkillSourceError("Only plain HTTPS github.com Skill tree URLs are supported.")
    try:
        parts = tuple(unquote(part) for part in parsed.path.split("/") if part)
    except UnicodeError as exc:
        raise GitHubSkillSourceError("The GitHub Skill URL path is invalid.") from exc
    if len(parts) < 5 or parts[2] != "tree":
        raise GitHubSkillSourceError(
            "Use https://github.com/OWNER/REPO/tree/REV/path/to/skill."
        )
    if any("/" in part or "\\" in part or part in {".", ".."} for part in parts):
        raise GitHubSkillSourceError("The GitHub Skill URL path is invalid.")
    repository = parts[1]
    if repository.endswith(".git"):
        repository = repository[:-4]
    return GitHubSkillSource(parts[0], repository, parts[3], "/".join(parts[4:]))


class GitHubSkillTransport(Protocol):
    def resolve_commit(self, source: GitHubSkillSource) -> str: ...
    def download_package(
        self, source: GitHubSkillSource, commit: str
    ) -> Mapping[str, bytes]: ...


class _GitHubRedirects(HTTPRedirectHandler):
    def __init__(self, source: GitHubSkillSource, commit: str | None) -> None:
        self._source = source
        self._commit = commit

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        allowed = parsed.scheme == "https" and parsed.hostname == "api.github.com"
        if parsed.port is not None or parsed.username is not None or parsed.password is not None:
            allowed = False
        prefix = f"/repos/{self._source.owner}/{self._source.repository_name}/"
        allowed = allowed and parsed.path.startswith(prefix)
        if not allowed:
            raise GitHubSkillNetworkError("GitHub returned an unsafe redirect; acquisition stopped.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class GitHubHTTPTransport:
    """Retrieve one immutable Git tree subtree without downloading its repository."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 60:
            raise ValueError("GitHub timeout must be between zero and sixty seconds.")
        self._timeout = float(timeout_seconds)

    def resolve_commit(self, source: GitHubSkillSource) -> str:
        revision = quote(source.revision, safe="")
        url = (
            f"https://api.github.com/repos/{source.owner}/{source.repository_name}"
            f"/commits/{revision}?per_page=1"
        )
        raw = self._read(source, url, MAX_GITHUB_JSON_BYTES, commit=None)
        try:
            document = json.loads(raw)
            commit = document["sha"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise GitHubSkillNetworkError("GitHub returned an invalid commit response.") from exc
        if not isinstance(commit, str) or _SHA.fullmatch(commit) is None:
            raise GitHubSkillNetworkError("GitHub did not resolve the revision to an exact commit.")
        return commit

    def download_package(
        self, source: GitHubSkillSource, commit: str
    ) -> Mapping[str, bytes]:
        if _SHA.fullmatch(commit) is None:
            raise GitHubSkillSourceError("Package acquisition requires an exact Git commit.")
        commit_document = self._json(
            source,
            f"https://api.github.com/repos/{source.owner}/{source.repository_name}/git/commits/{commit}",
            MAX_GITHUB_JSON_BYTES,
            commit=commit,
        )
        tree_value = commit_document.get("tree")
        if not isinstance(tree_value, Mapping) or not _valid_git_sha(tree_value.get("sha")):
            raise GitHubSkillNetworkError("GitHub returned an invalid immutable commit tree.")
        tree_sha = str(tree_value["sha"])
        for component in _package_parts(source.package_path):
            entries = self._tree(source, commit, tree_sha)
            match = next((item for item in entries if item.get("path") == component), None)
            if match is None or match.get("type") != "tree" or match.get("mode") != "040000":
                raise GitHubSkillSourceError("The selected GitHub Skill path is not a directory.")
            sha = match.get("sha")
            if not _valid_git_sha(sha):
                raise GitHubSkillNetworkError("GitHub returned invalid Skill tree identity.")
            tree_sha = str(sha)

        collected: dict[str, bytes] = {}
        counters = {"entries": 0, "bytes": 0}
        self._collect_tree(
            source, commit, tree_sha, (), collected, counters, depth=0
        )
        if "SKILL.md" not in collected:
            raise GitHubSkillSourceError(
                "The selected GitHub path does not contain SKILL.md."
            )
        return MappingProxyType(collected)

    def _collect_tree(
        self,
        source: GitHubSkillSource,
        commit: str,
        tree_sha: str,
        prefix: tuple[str, ...],
        collected: dict[str, bytes],
        counters: dict[str, int],
        *,
        depth: int,
    ) -> None:
        if depth > MAX_PACKAGE_TREE_DEPTH:
            raise GitHubSkillSourceError("The selected Skill package tree is too deep.")
        for item in self._tree(source, commit, tree_sha):
            counters["entries"] += 1
            if counters["entries"] > MAX_PACKAGE_TREE_ENTRIES:
                raise GitHubSkillSourceError("The selected Skill package tree has excessive entries.")
            name = item.get("path")
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise GitHubSkillSourceError("GitHub returned an unsafe Skill package path.")
            _package_parts(name)
            kind, mode, sha = item.get("type"), item.get("mode"), item.get("sha")
            if not _valid_git_sha(sha):
                raise GitHubSkillNetworkError("GitHub returned invalid Skill content identity.")
            relative_parts = (*prefix, name)
            if kind == "tree" and mode == "040000":
                self._collect_tree(
                    source, commit, str(sha), relative_parts, collected, counters,
                    depth=depth + 1,
                )
                continue
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise GitHubSkillSourceError(
                    "The selected Skill package contains a link, submodule, or special entry."
                )
            if len(collected) >= MAX_PACKAGE_FILES:
                raise GitHubSkillSourceError("The selected Skill package has excessive files.")
            size = item.get("size")
            if type(size) is not int or size < 0 or size > MAX_FILE_BYTES:
                raise GitHubSkillSourceError("A selected Skill package file exceeds the size limit.")
            counters["bytes"] += size
            if counters["bytes"] > MAX_PACKAGE_BYTES:
                raise GitHubSkillSourceError("The selected Skill package exceeds the size limit.")
            relative = "/".join(relative_parts)
            if relative in collected:
                raise GitHubSkillSourceError("The selected Skill package contains a duplicate path.")
            collected[relative] = self._blob(source, commit, str(sha), size)

    def _tree(
        self, source: GitHubSkillSource, commit: str, tree_sha: str
    ) -> tuple[Mapping[str, object], ...]:
        document = self._json(
            source,
            f"https://api.github.com/repos/{source.owner}/{source.repository_name}/git/trees/{tree_sha}",
            MAX_GITHUB_JSON_BYTES,
            commit=commit,
        )
        if document.get("truncated") is True:
            raise GitHubSkillSourceError("GitHub truncated the selected Skill tree.")
        value = document.get("tree")
        if not isinstance(value, list) or len(value) > MAX_PACKAGE_TREE_ENTRIES:
            raise GitHubSkillSourceError("GitHub returned an invalid or excessive Skill tree.")
        if any(not isinstance(item, Mapping) for item in value):
            raise GitHubSkillNetworkError("GitHub returned invalid Skill tree entries.")
        return tuple(value)

    def _blob(
        self, source: GitHubSkillSource, commit: str, sha: str, expected_size: int
    ) -> bytes:
        document = self._json(
            source,
            f"https://api.github.com/repos/{source.owner}/{source.repository_name}/git/blobs/{sha}",
            2 * MAX_FILE_BYTES,
            commit=commit,
        )
        if document.get("encoding") != "base64" or document.get("sha") != sha:
            raise GitHubSkillNetworkError("GitHub returned invalid Skill file content.")
        encoded = document.get("content")
        if not isinstance(encoded, str):
            raise GitHubSkillNetworkError("GitHub returned invalid Skill file encoding.")
        compact = encoded.replace("\n", "").replace("\r", "")
        try:
            content = base64.b64decode(compact, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GitHubSkillNetworkError("GitHub returned invalid Skill file encoding.") from exc
        identity = hashlib.sha1(
            f"blob {len(content)}\0".encode("ascii") + content,
            usedforsecurity=False,
        ).hexdigest()
        if len(content) != expected_size or len(content) > MAX_FILE_BYTES or identity != sha:
            raise GitHubSkillNetworkError("GitHub Skill file identity did not verify.")
        if content.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise GitHubSkillSourceError("Git LFS pointer content is unsupported for Skill packages.")
        return content

    def _json(
        self,
        source: GitHubSkillSource,
        url: str,
        limit: int,
        *,
        commit: str | None,
    ) -> Mapping[str, object]:
        raw = self._read(source, url, limit, commit=commit)
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise GitHubSkillNetworkError("GitHub returned invalid JSON.") from exc
        if not isinstance(document, Mapping):
            raise GitHubSkillNetworkError("GitHub returned an invalid response object.")
        return document

    def _read(
        self, source: GitHubSkillSource, url: str, limit: int, *, commit: str | None
    ) -> bytes:
        opener = build_opener(ProxyHandler({}), _GitHubRedirects(source, commit))
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"Tori-Skills/{GITHUB_ACQUISITION_VERSION}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with opener.open(request, timeout=self._timeout) as response:
                final = urlsplit(response.geturl())
                if final.scheme != "https" or final.hostname != "api.github.com":
                    raise GitHubSkillNetworkError("GitHub acquisition left its approved network scope.")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) > limit:
                    raise GitHubSkillNetworkError("The GitHub response exceeds the acquisition limit.")
                result = response.read(limit + 1)
        except GitHubSkillError:
            raise
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise GitHubSkillNetworkError() from exc
        if len(result) > limit:
            raise GitHubSkillNetworkError("The GitHub response exceeds the acquisition limit.")
        return result


@dataclass(frozen=True, slots=True)
class SkillInspectionSummary:
    skill_id: str
    name: str
    repository: str
    commit: str
    package_path: str
    version: str
    digest: str
    compatibility: str
    license: str | None
    files: tuple[AgentSkillFile, ...]
    requested_permissions: tuple[Mapping[str, object], ...]
    unsupported_components: tuple[str, ...]
    risk_notes: tuple[str, ...]

    def document(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for item in self.files:
            counts[item.component] = counts.get(item.component, 0) + 1
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "repository": self.repository,
            "commit": self.commit,
            "package_path": self.package_path,
            "version": self.version,
            "digest": self.digest,
            "compatibility": self.compatibility,
            "license": self.license,
            "inventory": counts,
            "files": [
                {"path": item.path, "size": item.size, "digest": item.digest, "component": item.component}
                for item in self.files
            ],
            "requested_permissions": [dict(item) for item in self.requested_permissions],
            "unsupported_components": list(self.unsupported_components),
            "risk_notes": list(self.risk_notes),
        }


@dataclass(frozen=True, slots=True)
class SkillInstallProposal:
    token: str
    expires_at: float
    origin: RequestOrigin
    summary: SkillInspectionSummary
    manifest_schema_version: int
    registry_revision: str


@dataclass(frozen=True, slots=True)
class SkillEnableProposal:
    token: str
    expires_at: float
    origin: RequestOrigin
    reference: SkillVersionRef
    entry_revision: int
    registry_revision: str
    compatibility: str
    granted_permissions: tuple[SkillPermission, ...]
    inert_components: tuple[str, ...]


@dataclass(slots=True)
class _AcquiredSkill:
    source: GitHubSkillSource
    commit: str
    quarantine: Path
    package_root: Path
    inspected: AgentSkillInspectionResult


class GitHubSkillAcquisitionService:
    """Resolve, quarantine, and inspect one explicitly supplied public source."""

    def __init__(
        self,
        importer: AgentSkillImporter,
        *,
        transport: GitHubSkillTransport | None = None,
        quarantine_parent: Path | None = None,
    ) -> None:
        self._importer = importer
        self._transport = transport or GitHubHTTPTransport()
        self._quarantine_parent = quarantine_parent

    def acquire(self, url: object, *, origin: RequestOrigin, administration: AgentSkillAdministration) -> _AcquiredSkill:
        administration.application.require_administration(origin)
        source = parse_github_skill_url(url)
        commit = self._transport.resolve_commit(source)
        if _SHA.fullmatch(commit) is None:
            raise GitHubSkillNetworkError("The revision did not resolve to an immutable commit.")
        entries = self._transport.download_package(source, commit)
        quarantine = Path(
            tempfile.mkdtemp(
                prefix="tori-github-skill-",
                dir=None if self._quarantine_parent is None else self._quarantine_parent,
            )
        )
        os.chmod(quarantine, 0o700)
        package_root = quarantine / PurePosixPath(source.package_path).name
        try:
            _publish_selected_package(entries, package_root)
            inspected = self._importer.inspect_pinned_git_snapshot(
                package_root,
                repository=source.repository_url,
                commit=commit,
                package_path=source.package_path,
                publisher=source.owner.casefold(),
                source_namespace="github",
                publisher_verified=False,
            )
            return _AcquiredSkill(source, commit, quarantine, package_root, inspected)
        except Exception:
            _remove_quarantine(quarantine)
            raise

    @staticmethod
    def release(acquired: _AcquiredSkill) -> None:
        _remove_quarantine(acquired.quarantine)

    def reinspect(self, acquired: _AcquiredSkill) -> AgentSkillInspectionResult:
        return self._importer.inspect_pinned_git_snapshot(
            acquired.package_root,
            repository=acquired.source.repository_url,
            commit=acquired.commit,
            package_path=acquired.source.package_path,
            publisher=acquired.source.owner,
            source_namespace="github",
            publisher_verified=False,
        )


class GitHubSkillLifecycleService:
    """One-use install/enable proposals owned by trusted local Tori code."""

    def __init__(
        self,
        acquisition: GitHubSkillAcquisitionService,
        administration: AgentSkillAdministration,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
    ) -> None:
        self.acquisition = acquisition
        self.administration = administration
        self._clock = clock
        self._token_factory = token_factory
        self._installs: dict[str, tuple[SkillInstallProposal, _AcquiredSkill]] = {}
        self._enables: dict[str, SkillEnableProposal] = {}
        self._lock = threading.RLock()

    def inspect(self, url: object, *, origin: RequestOrigin) -> SkillInspectionSummary:
        acquired = self.acquisition.acquire(url, origin=origin, administration=self.administration)
        try:
            return _summary(acquired)
        finally:
            self.acquisition.release(acquired)

    def propose_install(self, url: object, *, origin: RequestOrigin) -> SkillInstallProposal:
        acquired = self.acquisition.acquire(url, origin=origin, administration=self.administration)
        try:
            proposal = SkillInstallProposal(
                self._new_token(), self._clock() + PROPOSAL_LIFETIME_SECONDS, origin,
                _summary(acquired), SKILL_MANIFEST_SCHEMA_VERSION, self.registry_revision(),
            )
            with self._lock:
                self._installs[proposal.token] = (proposal, acquired)
            return proposal
        except Exception:
            self.acquisition.release(acquired)
            raise

    def decide_install(
        self, token: object, decision: object, *, origin: RequestOrigin
    ) -> SkillRegistryEntry | None:
        proposal, acquired = self._claim_install(token, origin)
        try:
            if self._clock() > proposal.expires_at:
                raise GitHubSkillProposalError("That Skill installation proposal expired.", code="expired_confirmation")
            if decision == "cancel":
                return None
            if decision != "confirm":
                raise GitHubSkillProposalError("The Skill proposal decision must be confirm or cancel.")
            if self.registry_revision() != proposal.registry_revision:
                raise GitHubSkillProposalError("The Skill registry changed before confirmation.", code="stale_confirmation")
            current = self.administration.application.registry
            try:
                reinspected = self.acquisition.reinspect(acquired)
            except SkillError as exc:
                raise GitHubSkillProposalError(
                    "The inspected Skill bytes changed before confirmation.",
                    code="stale_confirmation",
                ) from exc
            if _inspection_binding(reinspected) != _inspection_binding(acquired.inspected):
                raise GitHubSkillProposalError("The inspected Skill bytes changed before confirmation.", code="stale_confirmation")
            if not current.exists:
                current.initialize()
            return self.administration.install(reinspected, origin=origin)
        finally:
            self.acquisition.release(acquired)

    def propose_enable(
        self,
        reference: SkillVersionRef,
        *,
        origin: RequestOrigin,
        granted_permissions: Sequence[SkillPermission] | None = None,
    ) -> SkillEnableProposal:
        self.administration.application.require_administration(origin)
        entry = self.administration.application.registry.get(reference)
        if entry.state not in {"installed_disabled", "disabled"}:
            raise GitHubSkillProposalError("That exact Skill version is not disabled.")
        grants = tuple(entry.manifest.requested_permissions if granted_permissions is None else granted_permissions)
        requested = {item.key for item in entry.manifest.requested_permissions}
        if any(not isinstance(item, SkillPermission) or item.key not in requested for item in grants):
            raise GitHubSkillProposalError("Enablement grants must be an exact subset of requested permissions.")
        compatibility = self.administration.application.compatibility_status(entry.manifest)
        component_types = _finding(entry.manifest.inspection.findings, "component_types") or ""
        inert = tuple(
            item for item in component_types.split(",")
            if item in {"scripts", "references", "assets", "other"}
        )
        proposal = SkillEnableProposal(
            self._new_token(), self._clock() + PROPOSAL_LIFETIME_SECONDS, origin,
            reference, entry.revision, self.registry_revision(), compatibility, grants, inert,
        )
        with self._lock:
            self._enables[proposal.token] = proposal
        return proposal

    def decide_enable(
        self, token: object, decision: object, *, origin: RequestOrigin
    ) -> SkillRegistryEntry | None:
        proposal = self._claim_enable(token, origin)
        if self._clock() > proposal.expires_at:
            raise GitHubSkillProposalError("That Skill enablement proposal expired.", code="expired_confirmation")
        if decision == "cancel":
            return None
        if decision != "confirm":
            raise GitHubSkillProposalError("The Skill proposal decision must be confirm or cancel.")
        if self.registry_revision() != proposal.registry_revision:
            raise GitHubSkillProposalError("The Skill registry changed before confirmation.", code="stale_confirmation")
        return self.administration.application.enable(
            proposal.reference,
            expected_revision=proposal.entry_revision,
            granted_permissions=proposal.granted_permissions,
            origin=origin,
        )

    def registry_revision(self) -> str:
        entries = self.administration.application.registry.list_entries()
        document = [
            {
                "reference": {
                    "skill_id": item.manifest.identity.canonical_id,
                    "version": item.manifest.version,
                    "digest": item.manifest.content_digest,
                },
                "state": item.state,
                "revision": item.revision,
                "grants": [permission.document() for permission in item.granted_permissions],
            }
            for item in entries
        ]
        return "sha256:" + hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _claim_install(self, token: object, origin: RequestOrigin) -> tuple[SkillInstallProposal, _AcquiredSkill]:
        if not isinstance(token, str) or not token:
            raise GitHubSkillProposalError("A valid Skill proposal token is required.")
        with self._lock:
            value = self._installs.pop(token, None)
        if value is None:
            raise GitHubSkillProposalError("That Skill installation proposal is invalid or already used.")
        if value[0].origin != origin:
            self.acquisition.release(value[1])
            raise GitHubSkillProposalError("That Skill proposal belongs to another origin.")
        return value

    def _claim_enable(self, token: object, origin: RequestOrigin) -> SkillEnableProposal:
        if not isinstance(token, str) or not token:
            raise GitHubSkillProposalError("A valid Skill proposal token is required.")
        with self._lock:
            value = self._enables.pop(token, None)
        if value is None:
            raise GitHubSkillProposalError("That Skill enablement proposal is invalid or already used.")
        if value.origin != origin:
            raise GitHubSkillProposalError("That Skill proposal belongs to another origin.")
        return value

    def _new_token(self) -> str:
        token = self._token_factory()
        if not isinstance(token, str) or not token or len(token) > 256:
            raise GitHubSkillProposalError("A safe Skill proposal token could not be created.")
        return token


def _summary(acquired: _AcquiredSkill) -> SkillInspectionSummary:
    inspected = acquired.inspected
    manifest = inspected.manifest
    license_value = inspected.external_metadata.get("license")
    unsupported = tuple(sorted({
        item.component for item in inspected.files if item.component in {"scripts", "other"}
    }))
    risks = [
        "SKILL.md guidance and all external metadata are untrusted data",
        *inspected.compatibility_reasons,
    ]
    if any(item.component == "scripts" for item in inspected.files):
        risks.append("bundled scripts are present but remain inert")
    if any(item.component in {"references", "assets"} for item in inspected.files):
        risks.append("references and assets are preserved but are not automatically loaded")
    if inspected.compatibility != "compatible_instruction_only":
        risks.append("compatibility limitations require review before enablement")
    return SkillInspectionSummary(
        manifest.identity.canonical_id,
        manifest.display_name,
        acquired.source.repository_url,
        acquired.commit,
        acquired.source.package_path,
        manifest.version,
        manifest.content_digest,
        inspected.compatibility,
        license_value,
        inspected.files,
        tuple(MappingProxyType(item.document()) for item in manifest.requested_permissions),
        unsupported,
        tuple(risks),
    )


def _inspection_binding(value: AgentSkillInspectionResult) -> str:
    """Bind proposal-relevant bytes/schema while excluding a fresh inspection time."""

    document = value.manifest.document()
    inspection = dict(document["inspection"])
    inspection.pop("inspected_at", None)
    document["inspection"] = inspection
    binding = {
        "manifest": document,
        "skill_md_digest": value.skill_md_digest,
        "files": [
            {"path": item.path, "size": item.size, "digest": item.digest, "component": item.component}
            for item in value.files
        ],
        "compatibility": value.compatibility,
        "compatibility_reasons": list(value.compatibility_reasons),
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _publish_selected_package(entries: Mapping[str, bytes], destination: Path) -> None:
    if not isinstance(entries, Mapping) or not entries or len(entries) > MAX_PACKAGE_FILES:
        raise GitHubSkillSourceError("The selected GitHub Skill package is empty or excessive.")
    total = 0
    normalized: dict[str, bytes] = {}
    for relative, content in entries.items():
        parts = _package_parts(relative)
        if not isinstance(content, bytes) or len(content) > MAX_FILE_BYTES:
            raise GitHubSkillSourceError("A selected Skill package file exceeds the size limit.")
        name = "/".join(parts)
        if name in normalized:
            raise GitHubSkillSourceError("The selected Skill package contains a duplicate path.")
        total += len(content)
        if total > MAX_PACKAGE_BYTES:
            raise GitHubSkillSourceError("The selected Skill package exceeds the size limit.")
        normalized[name] = content
    if "SKILL.md" not in normalized:
        raise GitHubSkillSourceError("The selected GitHub path does not contain SKILL.md.")
    destination.mkdir(mode=0o700)
    for relative, content in sorted(normalized.items()):
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise


def _valid_git_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _package_parts(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 1_024 or "\\" in value:
        raise GitHubSkillSourceError("The GitHub Skill package path is invalid.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise GitHubSkillSourceError("The GitHub Skill package path is invalid.")
    if any(len(part) > 255 or any(ord(character) < 32 for character in part) for part in path.parts):
        raise GitHubSkillSourceError("The GitHub Skill package path is invalid.")
    return path.parts


def _finding(findings: Sequence[str], name: str) -> str | None:
    prefix = name + "="
    for value in findings:
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _remove_quarantine(root: Path) -> None:
    try:
        info = root.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise SkillValidationError("Skill quarantine cleanup target is unsafe.")
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        for name in files:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                raise SkillValidationError("Skill quarantine changed before cleanup.")
            path.unlink()
        for name in directories:
            path = Path(current) / name
            if path.is_symlink() or not path.is_dir():
                raise SkillValidationError("Skill quarantine changed before cleanup.")
            path.rmdir()
    root.rmdir()
