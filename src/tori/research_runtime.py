"""Production composition and safe readiness for Research Worker V1."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from urllib.parse import urlparse

from .research import ResearchError, ResearchJob, SQLiteResearchStore
from .research_application import ResearchApplicationService, ResearchWorkspaceStatus
from .research_worker import (
    ResearchProcessSettings, ResearchWorkerError, SupervisedResearchWorker,
)


class ResearchRuntimeError(RuntimeError):
    code = "research_runtime_error"


@dataclass(frozen=True, slots=True)
class ResearchProductionSettings:
    runtime_root: Path
    worker_root: Path
    python_executable: Path
    worker_entrypoint: Path
    bubblewrap_executable: Path
    ollama_url: str
    searxng_url: str
    model: str
    embedding_model: str
    search_providers: tuple[str, ...] = ("github", "huggingface", "searxng")
    cancellation_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        for value, label in (
            (self.runtime_root, "runtime root"), (self.worker_root, "worker root"),
            (self.python_executable, "Python executable"),
            (self.worker_entrypoint, "worker entrypoint"),
            (self.bubblewrap_executable, "Bubblewrap executable"),
        ):
            if not Path(value).is_absolute():
                raise ValueError(f"The Research {label} must be absolute.")
        if self.runtime_root.name != "research":
            raise ValueError("The Research runtime root must end in research.")
        if self.worker_root not in self.python_executable.parents:
            raise ValueError("Research Python must be inside the configured worker root.")
        if self.worker_root not in self.worker_entrypoint.parents:
            raise ValueError("The Research entrypoint must be inside the configured worker root.")
        if tuple(self.search_providers) != ("github", "huggingface", "searxng"):
            raise ValueError("Research providers must be the approved authoritative-source sequence.")
        parsed = urlparse(self.ollama_url)
        if (
            parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.port is None or parsed.path.rstrip("/") or parsed.query
            or parsed.fragment or parsed.username is not None or parsed.password is not None
        ):
            raise ValueError("Research Ollama must be an exact loopback HTTP endpoint.")
        searxng = urlparse(self.searxng_url)
        try:
            import ipaddress
            address = ipaddress.ip_address(searxng.hostname or "")
        except ValueError as exc:
            raise ValueError("Research SearXNG must use a numeric local address.") from exc
        if (
            searxng.scheme != "http" or (not address.is_loopback and not address.is_private)
            or searxng.port is None or searxng.path.rstrip("/") or searxng.query
            or searxng.fragment or searxng.username is not None or searxng.password is not None
        ):
            raise ValueError("Research SearXNG must be an exact local HTTP root.")


@dataclass(frozen=True, slots=True)
class ResearchReadiness:
    available: bool
    code: str
    reason: str


class ResearchRuntime:
    """Narrow integration facade used by conversation, Workspace, and backups."""

    def __init__(
        self, readiness: ResearchReadiness,
        service: ResearchApplicationService | None = None,
    ) -> None:
        self.readiness = readiness
        self.service = service

    @classmethod
    def start(cls, settings: ResearchProductionSettings | None) -> ResearchRuntime:
        if settings is None:
            return cls(ResearchReadiness(False, "configuration_missing", "Research Worker is not administrator-configured."))
        try:
            _prepare_runtime_root(settings.runtime_root)
            store = SQLiteResearchStore(settings.runtime_root / "tori_research.db")
            parsed = urlparse(settings.ollama_url)
            searxng = urlparse(settings.searxng_url)
            worker = SupervisedResearchWorker(
                ResearchProcessSettings(
                    worker_root=settings.worker_root,
                    worker_argv=(str(settings.python_executable), str(settings.worker_entrypoint)),
                    bubblewrap_executable=settings.bubblewrap_executable,
                    ollama_host=str(parsed.hostname), ollama_port=int(parsed.port or 0),
                    searxng_host=str(searxng.hostname), searxng_port=int(searxng.port or 0),
                    model=settings.model, embedding_model=settings.embedding_model,
                    search_providers=settings.search_providers,
                    cancellation_grace_seconds=settings.cancellation_grace_seconds,
                ),
                settings.runtime_root / "sessions",
            )
            service = ResearchApplicationService(store, worker)
            service.recover_startup()
            worker_status = worker.readiness()
            if not worker_status.available:
                return cls(ResearchReadiness(False, "worker_unavailable", worker_status.reason or "Research Worker is unavailable."), service)
            return cls(ResearchReadiness(True, "ready", "Research Worker is ready."), service)
        except (OSError, ValueError, ResearchError, ResearchWorkerError) as exc:
            return cls(ResearchReadiness(False, getattr(exc, "code", "startup_failed"), "Research Worker could not start safely."))

    def status(self) -> ResearchWorkspaceStatus:
        if self.service is None:
            return ResearchWorkspaceStatus(
                "not_configured" if self.readiness.code == "configuration_missing" else "unavailable",
                self.readiness.code, self.readiness.reason, False, False, (), {},
            )
        return self.service.status()

    def cancel(self, identifier: str, *, expected_revision: int) -> ResearchJob:
        if self.service is None:
            raise ResearchRuntimeError("Research Worker is unavailable.")
        return self.service.cancel(identifier, expected_revision=expected_revision)

    def backup_guard(self) -> AbstractContextManager[None]:
        if self.service is None:
            raise ResearchRuntimeError("Research state is unavailable for backup.")
        return self.service.store.maintenance_guard()

    def close(self) -> None:
        if self.service is not None:
            self.service.close()


def _prepare_runtime_root(path: Path) -> None:
    root = Path(path)
    if os.path.lexists(root):
        entry = os.lstat(root)
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise ResearchRuntimeError("The Research runtime root is unsafe.")
        if entry.st_uid != os.geteuid() or stat.S_IMODE(entry.st_mode) & 0o077:
            raise ResearchRuntimeError("The Research runtime root ownership or permissions are unsafe.")
    else:
        root.mkdir(parents=False, mode=0o700)
    sessions = root / "sessions"
    if os.path.lexists(sessions):
        entry = os.lstat(sessions)
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise ResearchRuntimeError("The Research sessions root is unsafe.")
    else:
        sessions.mkdir(mode=0o700)
