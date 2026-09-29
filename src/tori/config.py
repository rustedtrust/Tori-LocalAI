"""Configuration loading and validation for Tori."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
from typing import Mapping
import os
import tomllib
import unicodedata
from urllib.parse import urlparse

from .providers.base import validate_model_identity
from .local_endpoints import is_valid_local_http_endpoint
from .search import DEFAULT_SEARCH_ENDPOINT, MAX_SEARCH_RESULTS
from .tts import DEFAULT_TTS_VOICE, validate_voice
from .tts_adapters import (
    DEFAULT_TTS_ENDPOINT,
    DEFAULT_TTS_PROVIDER,
    SUPPORTED_TTS_PROVIDERS,
    is_valid_tts_endpoint,
)
from .time_context import TimeContextError, validate_timezone_name
from .coding_work_runtime import CodingWorkProductionSettings
from .research_runtime import ResearchProductionSettings
from .voice_input_runtime import VoiceRuntimeSettings
from .mcp_runtime import MCPTimeProductionSettings


class ConfigError(ValueError):
    """Raised when Tori's configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class KnownModel:
    model: str
    display_name: str
    context_window_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    identifier: str
    display_name: str
    implementation: str
    base_url: str
    timeout_seconds: float
    keep_alive: str | None = None
    authentication: str = "none"
    credential_environment: str | None = None
    structured_output: str = "json_object"
    known_models: tuple[KnownModel, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanningSettings:
    enabled: bool = False
    backend: str = "radicale"
    url: str = "http://127.0.0.1:5232"
    username: str | None = None
    credential_environment: str | None = None
    default_task_list: str | None = None
    default_calendar: str | None = None
    timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class FinanceSettings:
    enabled: bool = False
    data_root: Path | None = None
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings needed by the first vertical slice."""

    provider: str
    model_name: str
    base_url: str
    timeout_seconds: float
    keep_alive: str
    log_level: str
    search_enabled: bool = True
    search_endpoint: str = DEFAULT_SEARCH_ENDPOINT
    search_result_limit: int = 5
    search_timeout_seconds: float = 8.0
    tts_enabled: bool = True
    tts_provider: str = DEFAULT_TTS_PROVIDER
    tts_endpoint: str = DEFAULT_TTS_ENDPOINT
    tts_voice: str = DEFAULT_TTS_VOICE
    tts_connect_timeout_seconds: float = 3.0
    tts_read_timeout_seconds: float = 30.0
    timezone: str | None = None
    profiles: tuple[ProviderProfile, ...] = ()
    coding_work: CodingWorkProductionSettings | None = None
    research: ResearchProductionSettings | None = None
    planning: PlanningSettings = PlanningSettings()
    finance: FinanceSettings = FinanceSettings()
    voice_input: VoiceRuntimeSettings = VoiceRuntimeSettings()
    mcp_time: MCPTimeProductionSettings = MCPTimeProductionSettings()

    def profile(self, identifier: str) -> ProviderProfile:
        for profile in self.profiles:
            if profile.identifier == identifier:
                return profile
        raise ConfigError(f"Unknown model provider profile: {identifier!r}.")


_DEFAULTS = {
    "provider": "ollama",
    "model_name": "gemma4:12b",
    "base_url": "http://127.0.0.1:11434",
    "timeout_seconds": 600.0,
    "keep_alive": "5m",
    "log_level": "INFO",
    "search_enabled": True,
    "search_endpoint": DEFAULT_SEARCH_ENDPOINT,
    "search_result_limit": 5,
    "search_timeout_seconds": 8.0,
    "tts_enabled": True,
    "tts_provider": DEFAULT_TTS_PROVIDER,
    "tts_endpoint": DEFAULT_TTS_ENDPOINT,
    "tts_voice": DEFAULT_TTS_VOICE,
    "tts_connect_timeout_seconds": 3.0,
    "tts_read_timeout_seconds": 30.0,
    "timezone": None,
    "profiles": (),
}

_ENVIRONMENT_KEYS = {
    "provider": "TORI_MODEL_PROVIDER",
    "model_name": "TORI_MODEL_NAME",
    "base_url": "TORI_MODEL_BASE_URL",
    "timeout_seconds": "TORI_MODEL_TIMEOUT_SECONDS",
    "keep_alive": "TORI_MODEL_KEEP_ALIVE",
    "log_level": "TORI_LOG_LEVEL",
    "search_enabled": "TORI_SEARCH_ENABLED",
    "search_endpoint": "TORI_SEARCH_ENDPOINT",
    "search_result_limit": "TORI_SEARCH_RESULT_LIMIT",
    "search_timeout_seconds": "TORI_SEARCH_TIMEOUT_SECONDS",
    "tts_enabled": "TORI_TTS_ENABLED",
    "tts_provider": "TORI_TTS_PROVIDER",
    "tts_endpoint": "TORI_TTS_ENDPOINT",
    "tts_voice": "TORI_TTS_VOICE",
    "tts_connect_timeout_seconds": "TORI_TTS_CONNECT_TIMEOUT_SECONDS",
    "tts_read_timeout_seconds": "TORI_TTS_READ_TIMEOUT_SECONDS",
    "timezone": "TORI_TIMEZONE",
}

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def load_settings(
    path: Path | str = Path("tori.toml"),
    *,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load settings from defaults, TOML, then environment overrides."""

    config_path = Path(path)
    values: dict[str, object] = dict(_DEFAULTS)

    if config_path.exists():
        try:
            with config_path.open("rb") as config_file:
                document = tomllib.load(config_file)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Could not read {config_path}: {exc}") from exc

        model = document.get("model", {})
        logging_config = document.get("logging", {})
        search = document.get("search", {})
        tts = document.get("tts", {})
        time_config = document.get("time", {})
        coding_work = document.get("coding_work")
        research = document.get("research")
        planning = document.get("planning")
        finance = document.get("finance")
        mcp = document.get("mcp")
        if "voice_input" in document:
            values["voice_input"] = _parse_voice_input(document["voice_input"])

        if not isinstance(model, dict):
            raise ConfigError("The [model] section must be a TOML table.")
        if not isinstance(logging_config, dict):
            raise ConfigError("The [logging] section must be a TOML table.")
        if not isinstance(search, dict):
            raise ConfigError("The [search] section must be a TOML table.")
        if not isinstance(tts, dict):
            raise ConfigError("The [tts] section must be a TOML table.")
        if not isinstance(time_config, dict):
            raise ConfigError("The [time] section must be a TOML table.")
        if coding_work is not None:
            values["coding_work"] = _parse_coding_work(coding_work)
        if research is not None:
            values["research"] = _parse_research(
                research,
                searxng_url=str(search.get("endpoint", values["search_endpoint"])),
            )
        if planning is not None:
            values["planning"] = _parse_planning(planning)
        if finance is not None:
            values["finance"] = _parse_finance(finance)
        if mcp is not None:
            values["mcp_time"] = _parse_mcp(mcp)

        explicit_profiles = model.get("profiles")
        if explicit_profiles is not None:
            legacy_fields = {"provider", "name", "base_url", "timeout_seconds", "keep_alive"}
            if legacy_fields & set(model):
                raise ConfigError(
                    "Explicit model profiles cannot be mixed with legacy [model] endpoint fields."
                )
            values["profiles"] = _parse_profiles(explicit_profiles)
            values["provider"] = model.get("default_profile")
            values["model_name"] = model.get("default_model")
        values.update(
            {
                "provider": model.get("provider", values["provider"]),
                "model_name": model.get("name", values["model_name"]),
                "base_url": model.get("base_url", values["base_url"]),
                "timeout_seconds": model.get(
                    "timeout_seconds", values["timeout_seconds"]
                ),
                "keep_alive": model.get("keep_alive", values["keep_alive"]),
                "log_level": logging_config.get("level", values["log_level"]),
                "search_enabled": search.get("enabled", values["search_enabled"]),
                "search_endpoint": search.get("endpoint", values["search_endpoint"]),
                "search_result_limit": search.get("result_limit", values["search_result_limit"]),
                "search_timeout_seconds": search.get("timeout_seconds", values["search_timeout_seconds"]),
                "tts_enabled": tts.get("enabled", values["tts_enabled"]),
                "tts_provider": tts.get("provider", values["tts_provider"]),
                "tts_endpoint": tts.get("endpoint", values["tts_endpoint"]),
                "tts_voice": tts.get("voice", values["tts_voice"]),
                "tts_connect_timeout_seconds": tts.get(
                    "connect_timeout_seconds", values["tts_connect_timeout_seconds"]
                ),
                "tts_read_timeout_seconds": tts.get(
                    "read_timeout_seconds", values["tts_read_timeout_seconds"]
                ),
                "timezone": time_config.get("timezone", values["timezone"]),
            }
        )

    environment = os.environ if environ is None else environ
    if values["profiles"] and any(
        key.startswith("TORI_MODEL_") for key in environment
    ):
        raise ConfigError(
            "TORI_MODEL_* overrides are supported only with legacy single-provider configuration."
        )
    for key, environment_key in _ENVIRONMENT_KEYS.items():
        override = environment.get(environment_key)
        if override is not None and not (key == "timezone" and values[key] is not None):
            values[key] = override

    return _validate(values)


def _validate(values: Mapping[str, object]) -> Settings:
    provider = _required_text(values["provider"], "model.provider").lower()
    model_name = _required_text(values["model_name"], "model.name")
    base_url = _required_text(values["base_url"], "model.base_url").rstrip("/")
    keep_alive = _required_text(values["keep_alive"], "model.keep_alive")
    log_level = _required_text(values["log_level"], "logging.level").upper()
    search_endpoint = _required_text(values["search_endpoint"], "search.endpoint").rstrip("/")
    tts_provider = _required_text(values["tts_provider"], "tts.provider").lower()
    tts_endpoint = _required_text(values["tts_endpoint"], "tts.endpoint").rstrip("/")
    timezone_name = values["timezone"]
    if timezone_name is not None:
        try:
            timezone_name = validate_timezone_name(timezone_name)
        except TimeContextError as exc:
            raise ConfigError(str(exc)) from exc
    try:
        tts_voice = validate_voice(values["tts_voice"])
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc

    search_enabled_value = values["search_enabled"]
    if isinstance(search_enabled_value, bool):
        search_enabled = search_enabled_value
    elif isinstance(search_enabled_value, str) and search_enabled_value.lower() in {"true", "false"}:
        search_enabled = search_enabled_value.lower() == "true"
    else:
        raise ConfigError("search.enabled must be true or false.")
    try:
        search_result_limit = int(values["search_result_limit"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("search.result_limit must be an integer.") from exc
    if isinstance(values["search_result_limit"], bool) or not 1 <= search_result_limit <= MAX_SEARCH_RESULTS:
        raise ConfigError(f"search.result_limit must be between 1 and {MAX_SEARCH_RESULTS}.")
    try:
        search_timeout_seconds = float(values["search_timeout_seconds"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("search.timeout_seconds must be a number.") from exc
    if not 0 < search_timeout_seconds <= 30:
        raise ConfigError("search.timeout_seconds must be greater than zero and at most 30.")
    if not is_valid_local_http_endpoint(search_endpoint):
        raise ConfigError(
            "search.endpoint must be a numeric loopback or RFC1918 SearXNG root."
        )

    tts_enabled_value = values["tts_enabled"]
    if isinstance(tts_enabled_value, bool):
        tts_enabled = tts_enabled_value
    elif isinstance(tts_enabled_value, str) and tts_enabled_value.lower() in {"true", "false"}:
        tts_enabled = tts_enabled_value.lower() == "true"
    else:
        raise ConfigError("tts.enabled must be true or false.")
    if tts_provider not in SUPPORTED_TTS_PROVIDERS:
        raise ConfigError("tts.provider must identify an approved local TTS adapter.")
    if not is_valid_tts_endpoint(tts_provider, tts_endpoint):
        raise ConfigError("tts.endpoint is not approved for the selected local TTS adapter.")
    try:
        tts_connect_timeout_seconds = float(values["tts_connect_timeout_seconds"])
        tts_read_timeout_seconds = float(values["tts_read_timeout_seconds"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("TTS timeout values must be numbers.") from exc
    if not 0 < tts_connect_timeout_seconds <= 10:
        raise ConfigError("tts.connect_timeout_seconds must be at most 10.")
    if not 0 < tts_read_timeout_seconds <= 120:
        raise ConfigError("tts.read_timeout_seconds must be at most 120.")

    try:
        timeout_seconds = float(values["timeout_seconds"])
    except (TypeError, ValueError) as exc:
        raise ConfigError("model.timeout_seconds must be a number.") from exc

    if timeout_seconds <= 0:
        raise ConfigError("model.timeout_seconds must be greater than zero.")

    try:
        identity = validate_model_identity(provider, model_name)
    except ValueError as exc:
        raise ConfigError("model provider/name contains an invalid identifier.") from exc
    provider = identity.provider
    model_name = identity.model

    raw_profiles = values.get("profiles", ())
    if raw_profiles:
        if not isinstance(raw_profiles, tuple):
            raise ConfigError("model.profiles must be a list of provider profiles.")
        profiles = raw_profiles
        matches = [item for item in profiles if item.identifier == provider]
        if len(matches) != 1:
            raise ConfigError("model.default_profile must identify one configured profile.")
        default_profile = matches[0]
        base_url = default_profile.base_url
        timeout_seconds = default_profile.timeout_seconds
        keep_alive = default_profile.keep_alive or "5m"
    else:
        validate_provider_endpoint(base_url, implementation="ollama")
        profiles = (
            ProviderProfile(
                identifier=provider,
                display_name="Local Ollama",
                implementation="ollama",
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                keep_alive=keep_alive,
            ),
        )

    if log_level not in _VALID_LOG_LEVELS:
        valid = ", ".join(sorted(_VALID_LOG_LEVELS))
        raise ConfigError(f"logging.level must be one of: {valid}.")

    return Settings(
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        keep_alive=keep_alive,
        log_level=log_level,
        search_enabled=search_enabled,
        search_endpoint=search_endpoint,
        search_result_limit=search_result_limit,
        search_timeout_seconds=search_timeout_seconds,
        tts_enabled=tts_enabled,
        tts_provider=tts_provider,
        tts_endpoint=tts_endpoint,
        tts_voice=tts_voice,
        tts_connect_timeout_seconds=tts_connect_timeout_seconds,
        tts_read_timeout_seconds=tts_read_timeout_seconds,
        timezone=timezone_name,
        profiles=profiles,
        coding_work=values.get("coding_work"),
        research=values.get("research"),
        planning=values.get("planning", PlanningSettings()),
        finance=values.get("finance", FinanceSettings()),
        voice_input=values.get("voice_input", VoiceRuntimeSettings()),
        mcp_time=values.get("mcp_time", MCPTimeProductionSettings()),
    )


def _parse_mcp(value: object) -> MCPTimeProductionSettings:
    if not isinstance(value, dict) or set(value) - {"time"}:
        raise ConfigError("The [mcp] section supports only the reviewed Time server.")
    raw = value.get("time", {})
    if not isinstance(raw, dict):
        raise ConfigError("The [mcp.time] section must be a TOML table.")
    allowed = {
        "enabled", "executable", "executable_digest", "package_version",
        "server_info_version", "approved_schema_digest",
        "bubblewrap_executable", "bubblewrap_digest", "timeout_seconds",
    }
    if set(raw) - allowed:
        raise ConfigError("The [mcp.time] section contains unsupported fields.")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("mcp.time.enabled must be true or false.")
    if not enabled:
        if set(raw) - {"enabled"}:
            raise ConfigError("Disabled MCP Time configuration must not retain authority fields.")
        return MCPTimeProductionSettings()
    required = allowed - {"timeout_seconds"}
    if not required.issubset(raw):
        missing = ", ".join(sorted(required - set(raw)))
        raise ConfigError(f"Enabled [mcp.time] is missing: {missing}.")
    try:
        return MCPTimeProductionSettings(
            enabled=True,
            executable=Path(_required_text(raw["executable"], "mcp.time.executable")),
            executable_digest=_required_text(
                raw["executable_digest"], "mcp.time.executable_digest"
            ),
            package_version=_required_text(
                raw["package_version"], "mcp.time.package_version"
            ),
            server_info_version=_required_text(
                raw["server_info_version"], "mcp.time.server_info_version"
            ),
            approved_schema_digest=_required_text(
                raw["approved_schema_digest"], "mcp.time.approved_schema_digest"
            ),
            bubblewrap_executable=Path(_required_text(
                raw["bubblewrap_executable"], "mcp.time.bubblewrap_executable"
            )),
            bubblewrap_digest=_required_text(
                raw["bubblewrap_digest"], "mcp.time.bubblewrap_digest"
            ),
            timeout_seconds=float(raw.get("timeout_seconds", 10.0)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid [mcp.time] configuration: {exc}") from exc


def _parse_finance(value: object) -> FinanceSettings:
    if not isinstance(value, dict):
        raise ConfigError("The [finance] section must be a TOML table.")
    if set(value) - {"enabled", "data_root", "currency"}:
        raise ConfigError("The [finance] section contains unsupported fields.")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("finance.enabled must be true or false.")
    raw_root = value.get("data_root")
    data_root = None
    if raw_root is not None:
        text = _required_text(raw_root, "finance.data_root")
        data_root = Path(text).expanduser()
        if not data_root.is_absolute():
            raise ConfigError("finance.data_root must be an absolute path.")
    if enabled and data_root is None:
        raise ConfigError("Enabled Finance requires finance.data_root.")
    currency = _required_text(value.get("currency", "USD"), "finance.currency").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ConfigError("finance.currency must be a three-letter ISO code.")
    return FinanceSettings(enabled, data_root, currency)


def _parse_planning(value: object) -> PlanningSettings:
    if not isinstance(value, dict):
        raise ConfigError("The [planning] section must be a TOML table.")
    allowed = {
        "enabled", "backend", "url", "username", "credential_environment",
        "default_task_list", "default_calendar", "timeout_seconds",
    }
    if set(value) - allowed:
        raise ConfigError("The [planning] section contains unsupported fields.")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("planning.enabled must be true or false.")
    backend = _required_text(
        value.get("backend", "radicale"), "planning.backend"
    ).lower()
    if backend != "radicale":
        raise ConfigError("planning.backend must identify an approved CalDAV adapter.")
    url = _required_text(
        value.get("url", "http://127.0.0.1:5232"), "planning.url"
    ).rstrip("/")
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("planning.url requires a valid port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ConfigError("planning.url must be a numeric IPv4 loopback URL.")
    username = _optional_text(value.get("username"), "planning.username")
    credential = _optional_text(
        value.get("credential_environment"), "planning.credential_environment"
    )
    if credential is not None and (
        not credential.startswith("TORI_")
        or not credential.replace("_", "").isalnum()
        or not credential.isupper()
    ):
        raise ConfigError("planning.credential_environment must name a TORI_* variable.")
    if credential is not None and username is None:
        raise ConfigError("planning credentials require a username.")
    try:
        timeout = float(value.get("timeout_seconds", 5.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError("planning.timeout_seconds must be a number.") from exc
    if not 0 < timeout <= 30:
        raise ConfigError("planning.timeout_seconds must be at most 30.")
    return PlanningSettings(
        enabled=enabled,
        backend=backend,
        url=url,
        username=username,
        credential_environment=credential,
        default_task_list=_optional_text(
            value.get("default_task_list"), "planning.default_task_list"
        ),
        default_calendar=_optional_text(
            value.get("default_calendar"), "planning.default_calendar"
        ),
        timeout_seconds=timeout,
    )


def _parse_coding_work(value: object) -> CodingWorkProductionSettings:
    if not isinstance(value, dict):
        raise ConfigError("The [coding_work] section must be a TOML table.")
    allowed = {
        "runtime_root", "opencode_executable", "opencode_version",
        "bubblewrap_executable", "provider_upstream", "model",
        "control_timeout_seconds", "model_turn_timeout_seconds",
    }
    if set(value) - allowed:
        raise ConfigError("The [coding_work] section contains unsupported fields.")
    required = allowed - {"control_timeout_seconds", "model_turn_timeout_seconds"}
    if not required.issubset(value):
        missing = ", ".join(sorted(required - set(value)))
        raise ConfigError(f"The [coding_work] section is missing: {missing}.")
    try:
        return CodingWorkProductionSettings(
            runtime_root=Path(_required_text(value["runtime_root"], "coding_work.runtime_root")),
            opencode_executable=Path(_required_text(value["opencode_executable"], "coding_work.opencode_executable")),
            opencode_version=_required_text(value["opencode_version"], "coding_work.opencode_version"),
            bubblewrap_executable=Path(_required_text(value["bubblewrap_executable"], "coding_work.bubblewrap_executable")),
            provider_upstream=_required_text(value["provider_upstream"], "coding_work.provider_upstream"),
            model=_required_text(value["model"], "coding_work.model"),
            control_timeout_seconds=float(value.get("control_timeout_seconds", 30.0)),
            model_turn_timeout_seconds=float(value.get("model_turn_timeout_seconds", 900.0)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid [coding_work] configuration: {exc}") from exc


def _parse_research(value: object, *, searxng_url: str) -> ResearchProductionSettings:
    if not isinstance(value, dict):
        raise ConfigError("The [research] section must be a TOML table.")
    allowed = {
        "runtime_root", "worker_root", "python_executable", "worker_entrypoint",
        "bubblewrap_executable", "ollama_url", "model", "embedding_model",
        "search_providers", "cancellation_grace_seconds",
    }
    if set(value) - allowed:
        raise ConfigError("The [research] section contains unsupported fields.")
    required = allowed - {"search_providers", "cancellation_grace_seconds"}
    if not required.issubset(value):
        missing = ", ".join(sorted(required - set(value)))
        raise ConfigError(f"The [research] section is missing: {missing}.")
    try:
        return ResearchProductionSettings(
            runtime_root=Path(_required_text(value["runtime_root"], "research.runtime_root")),
            worker_root=Path(_required_text(value["worker_root"], "research.worker_root")),
            python_executable=Path(_required_text(value["python_executable"], "research.python_executable")),
            worker_entrypoint=Path(_required_text(value["worker_entrypoint"], "research.worker_entrypoint")),
            bubblewrap_executable=Path(_required_text(value["bubblewrap_executable"], "research.bubblewrap_executable")),
            ollama_url=_required_text(value["ollama_url"], "research.ollama_url"),
            searxng_url=_required_text(searxng_url, "search.endpoint").rstrip("/"),
            model=_required_text(value["model"], "research.model"),
            embedding_model=_required_text(value["embedding_model"], "research.embedding_model"),
            search_providers=_research_search_providers(value.get(
                "search_providers", ["github", "huggingface", "searxng"]
            )),
            cancellation_grace_seconds=float(value.get("cancellation_grace_seconds", 5.0)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid [research] configuration: {exc}") from exc


def _research_search_providers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ConfigError("research.search_providers must be a non-empty string array.")
    return tuple(item.strip() for item in value)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


_APPROVED_MODEL_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def validate_provider_endpoint(value: str, *, implementation: str) -> str:
    """Validate and normalize one bounded numeric LOCAL/LAN model API root."""
    parsed = urlparse(value)
    allowed_paths = {"", "/"} if implementation == "ollama" else {"", "/", "/v1", "/v1/"}
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.path not in allowed_paths
    ):
        raise ConfigError(
            "Model provider endpoints must be bounded HTTP(S) numeric LOCAL/LAN URLs."
        )
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(
            "Model provider endpoints require a numeric IPv4 address and valid port."
        ) from exc
    if (
        not isinstance(address, ipaddress.IPv4Address)
        or not any(address in network for network in _APPROVED_MODEL_NETWORKS)
        or port is None
        or not 1 <= port <= 65535
    ):
        raise ConfigError(
            "Model provider endpoints require numeric IPv4 loopback or RFC1918 LAN addresses."
        )
    normalized = value.rstrip("/")
    if implementation == "openai_compatible" and not normalized.endswith("/v1"):
        normalized += "/v1"
    return normalized


def _parse_profiles(value: object) -> tuple[ProviderProfile, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("model.profiles must be a non-empty array of tables.")
    profiles: list[ProviderProfile] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"model.profiles[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{label} must be a table.")
        allowed = {
            "id", "display_name", "type", "base_url", "timeout_seconds",
            "keep_alive", "authentication", "credential_environment",
            "structured_output", "known_models",
        }
        if set(raw) - allowed:
            raise ConfigError(f"{label} contains unsupported fields.")
        try:
            identifier = validate_model_identity(
                _required_text(raw.get("id"), f"{label}.id"), "placeholder"
            ).provider
        except ValueError as exc:
            raise ConfigError(f"{label}.id is invalid.") from exc
        if identifier in seen:
            raise ConfigError("Model provider profile IDs must be unique.")
        seen.add(identifier)
        display = _required_text(raw.get("display_name", identifier), f"{label}.display_name")
        if len(display) > 80 or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for character in display
        ):
            raise ConfigError(f"{label}.display_name is invalid.")
        implementation = _required_text(raw.get("type"), f"{label}.type").lower()
        if implementation not in {"ollama", "openai_compatible"}:
            raise ConfigError(f"{label}.type is unsupported.")
        base_url = validate_provider_endpoint(
            _required_text(raw.get("base_url"), f"{label}.base_url").rstrip("/"),
            implementation=implementation,
        )
        try:
            timeout = float(raw.get("timeout_seconds", 600.0))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{label}.timeout_seconds must be a number.") from exc
        if not 0 < timeout <= 3600:
            raise ConfigError(f"{label}.timeout_seconds must be between 0 and 3600.")
        keep = raw.get("keep_alive")
        if implementation == "ollama":
            keep = _required_text(keep if keep is not None else "5m", f"{label}.keep_alive")
        elif keep is not None:
            raise ConfigError("keep_alive is valid only for Ollama profiles.")
        authentication = _required_text(raw.get("authentication", "none"), f"{label}.authentication")
        if authentication not in {"none", "dummy_bearer", "environment_bearer"}:
            raise ConfigError(f"{label}.authentication is unsupported.")
        if implementation == "ollama" and authentication != "none":
            raise ConfigError("Ollama profiles do not support authentication modes.")
        credential_environment = raw.get("credential_environment")
        if authentication == "environment_bearer":
            parsed = urlparse(base_url)
            address = ipaddress.ip_address(parsed.hostname or "")
            if (
                implementation != "openai_compatible"
                or credential_environment != "LM_API_TOKEN"
                or not address.is_loopback
            ):
                raise ConfigError(
                    "environment_bearer is limited to the LM_API_TOKEN loopback profile."
                )
        elif credential_environment is not None:
            raise ConfigError(
                f"{label}.credential_environment is valid only for environment_bearer."
            )
        structured = _required_text(raw.get("structured_output", "json_object"), f"{label}.structured_output")
        if structured not in {"json_object", "prompt_only"}:
            raise ConfigError(f"{label}.structured_output is unsupported.")
        if implementation == "ollama" and "structured_output" in raw:
            raise ConfigError(
                "structured_output is valid only for OpenAI-compatible profiles."
            )
        known = _parse_known_models(raw.get("known_models", []), label)
        profiles.append(ProviderProfile(
            identifier, display, implementation, base_url, timeout,
            keep_alive=keep, authentication=authentication,
            credential_environment=credential_environment,
            structured_output=structured, known_models=known,
        ))
    return tuple(profiles)


def _parse_known_models(value: object, profile_label: str) -> tuple[KnownModel, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{profile_label}.known_models must be an array of tables.")
    result: list[KnownModel] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) - {"id", "display_name", "context_window_tokens"}:
            raise ConfigError(f"{profile_label}.known_models contains an invalid record.")
        try:
            model = validate_model_identity("profile", raw.get("id")).model
        except ValueError as exc:
            raise ConfigError(f"{profile_label}.known_models contains an invalid model ID.") from exc
        if model in seen:
            raise ConfigError(f"{profile_label}.known_models contains duplicate IDs.")
        seen.add(model)
        display = _required_text(raw.get("display_name", model), "known model display_name")
        if len(display) > 80 or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for character in display
        ):
            raise ConfigError("Known model display_name is invalid.")
        capacity = raw.get("context_window_tokens")
        if capacity is not None and (
            isinstance(capacity, bool) or not isinstance(capacity, int) or not 4096 <= capacity <= 1_048_576
        ):
            raise ConfigError("Known model context_window_tokens is invalid.")
        result.append(KnownModel(model, display, capacity))
    return tuple(result)


def _parse_voice_input(document: object) -> VoiceRuntimeSettings:
    fields = {"environment_root", "model_root", "port", "readiness_seconds", "shutdown_seconds"}
    if not isinstance(document, dict) or not set(document) <= fields:
        raise ConfigError("Invalid [voice_input] runtime configuration.")
    values = dict(document)
    try:
        for name in ("environment_root", "model_root"):
            if name in values:
                if not isinstance(values[name], str) or not values[name]:
                    raise ValueError()
                values[name] = Path(values[name])
        for name in ("readiness_seconds", "shutdown_seconds"):
            if name in values and type(values[name]) not in {int, float}:
                raise ValueError()
        return VoiceRuntimeSettings(**values)
    except (ValueError, TypeError):
        raise ConfigError("Invalid [voice_input] runtime configuration.") from None
