"""Tori's local command-line application."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import logging
import os
from pathlib import Path
import secrets
import time

from . import __version__
from .checkpoints import (
    CheckpointError,
    CheckpointMetadata,
    CheckpointStore,
)
from .backups import BackupService, PRODUCTION_BACKUP_ROOT, PRODUCTION_PROJECT_ROOT
from .actions import (
    ActionContractError,
    parse_run_command,
)
from .capabilities import CapabilityResult
from .capability_registry import cli_capabilities
from .capability_growth import SQLiteImprovementJournal
from .companion_initiative import SQLiteCompanionInitiativeStore
from .night_owl import SQLiteNightOwlStore
from .chats import ChatDetail, ChatService, ChatServiceError
from .command_execution import CommandExecutionService
from .execution_policy import DEFAULT_POLICY_DATABASE, ExecutionPolicyService
from .coding_work_integration import CodingWorkRuntime
from .research_runtime import ResearchRuntime
from .commands import (
    LocalCommandService,
    format_knowledge_listing,
    source_references,
)
from .config import ConfigError, ProviderProfile, Settings, load_settings
from .conversation import ConversationSession
from .context import ContextPolicy, ContextTelemetry
from .conversation_archive import (
    ArchiveContext, ArchiveEntry, ArchiveWebSearch, ArchiveWebSource,
    ConversationArchiveStore, MemoryExtractionRequest,
)
from .finance_conversation import FinanceConversationService
from .finance_service import FinanceService
from .finance_workbook import WorkbookFinanceRepository
from .knowledge import KnowledgeListing, KnowledgePassage, KnowledgeRegistry
from .knowledge_retrieval import KnowledgeRetrievalPort
from .logging_setup import configure_logging
from .memory import SQLiteMemoryStore
from .mcp_runtime import MCPRuntime
from .memory_extraction import (
    MemoryExtractionCoordinator,
    new_extraction_id,
    provider_definition_fingerprint,
)
from .model_catalog import (
    ModelCatalog,
    ModelCatalogError,
    ModelCatalogService,
    ModelIdentity,
    parse_model_selection,
    validate_model_identity,
)
from .providers import (
    ChatMessage,
    ModelDescriptor,
    ModelProvider,
    ModelUnavailableError,
    OllamaProvider,
    OpenAICompatibleProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderTimeoutError,
    ProviderUnsupportedResponseError,
)
from .provider_profiles import (
    ModelProviderProfileController,
    ProviderProfileError,
    SQLiteProviderProfileStore,
)
from .local_provider_settings import LocalProviderSettingsStore
from .planning_runtime import PlanningRuntime
from .project_application import ProjectApplicationService
from .project_context import ProjectContextService
from .response_normalization import ExternalKnowledgeNeededAdvisory
from .search import (
    BARE_SEARCH_CLARIFICATION_MESSAGE, EXTERNAL_KNOWLEDGE_PROPOSAL_MESSAGE,
    FRESHNESS_SEARCH_PROPOSAL_MESSAGE, SEARCH_UNAVAILABLE_MESSAGE,
    SearchAttributionError, SearchConsent, SearchError, SearXNGSearch,
    build_search_context, format_search_answer, search_category_for_query,
)
from .search_application import SearchApplicationPolicy, SearchDisposition
from .search_port import SearchPort
from .source_retrieval import (
    SourceRetrievalPort,
    SourceRetrievalService,
    retrieve_direct_url_evidence,
    retrieve_search_evidence,
)
from .public_source_retrieval import PublicSourceRetriever
from .tts import SpeechCoordinator
from .tts_adapters import create_tts_provider
from .tts_profile_application import TTSProfileApplicationService
from .tts_profile_runtime import TTSProfileRuntime
from .tts_profiles import SQLiteTTSProfileStore, TTSProfileError
from .tts_provider import TTSProviderError
from .user_settings import (
    CapabilitySettingsController,
    SEARCH_DISABLED_MESSAGE,
    SETTINGS_FAILURE_MESSAGE,
    SQLiteUserSettingsStore,
    UserSettingsError,
)
from .tasks import SQLiteOperationalStore
from .scheduled_work import SQLiteScheduledWorkStore
from .time_context import TimeContextError, discover_timezone
from .web import DEFAULT_WEB_PORT, run_web_server, validate_web_port


LOGGER = logging.getLogger(__name__)
EXIT_COMMANDS = frozenset({"/exit", "/quit"})
CHECKPOINT_EXIT_CODE = 5
CHAT_EXIT_CODE = 7

InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]
KnowledgeResultFunction = Callable[[tuple[KnowledgePassage, ...]], None]

def _search_blocked_message(disposition: SearchDisposition) -> str:
    if disposition == "disabled":
        return SEARCH_DISABLED_MESSAGE
    if disposition == "settings_failure":
        return SETTINGS_FAILURE_MESSAGE
    return SEARCH_UNAVAILABLE_MESSAGE


def _project_context_planner(
    chat_service: ChatService | None,
    project_id: str | None,
):  # type: ignore[no-untyped-def]
    if chat_service is None or project_id is None:
        return None
    service = ProjectContextService(ProjectApplicationService(chat_service))
    return lambda request: service.build_pack(project_id, request)


def _combined_context(*parts: str | None) -> str | None:
    retained = [part for part in parts if part]
    return "\n\n".join(retained) or None


def run_once(
    prompt: str,
    provider: ModelProvider,
    *,
    memory_store: SQLiteMemoryStore | None = None,
    memory_warning_function: OutputFunction | None = None,
    knowledge_registry: KnowledgeRetrievalPort | None = None,
    knowledge_warning_function: OutputFunction | None = None,
    knowledge_result_function: KnowledgeResultFunction | None = None,
    chat_service: ChatService | None = None,
    provider_name: str = "unknown",
    model_name: str = "unknown",
    web_search: SearchPort | None = None,
    source_retrieval: SourceRetrievalPort | None = None,
    capability_settings: CapabilitySettingsController | None = None,
    context_policy: ContextPolicy = ContextPolicy(),
    model_capacity: int | None = None,
    memory_coordinator: MemoryExtractionCoordinator | None = None,
) -> str:
    """Send one identity-aware request and return its response text."""

    session = ConversationSession(
        provider,
        memory_store=memory_store,
        memory_warning_function=memory_warning_function,
        knowledge_registry=knowledge_registry,
        knowledge_warning_function=knowledge_warning_function,
        model_name=model_name,
        context_policy=context_policy,
        model_capacity=model_capacity,
        capability_awareness=cli_capabilities(memory_store, knowledge_registry, web_search, capability_settings).awareness,
    )
    search_policy = SearchApplicationPolicy(
        SearchConsent(clock=time.monotonic),
        implementation_available=lambda: (
            web_search is not None and web_search.available
        ),
        capability_settings=capability_settings,
        source_retrieval_available=lambda: source_retrieval is not None,
    )
    search_decision = search_policy.evaluate_explicit(prompt)
    if search_decision.disposition in {
        "disabled", "unavailable", "settings_failure"
    }:
        raise SearchError(_search_blocked_message(search_decision.disposition))
    query = search_decision.query
    if search_decision.source_urls:
        assert source_retrieval is not None
        search_result = retrieve_direct_url_evidence(
            prompt, search_decision.source_urls, source_retrieval
        )
    else:
        search_result = (
            web_search.search(query, category=search_category_for_query(query))
            if query is not None else None
        )
        if search_result is not None and source_retrieval is not None:
            search_result = retrieve_search_evidence(
                search_result, source_retrieval
            )
    answer = session.send(
        prompt,
        supplemental_system=_combined_context(
            build_search_context(search_result) if search_result else None,
        ),
        response_transform=(
            (lambda text: format_search_answer(
                text,
                search_result.sources,
                direct_source=(
                    search_result.capability_id == "web_source_retrieval"
                ),
                failed_source_count=int(
                    (search_result.metadata or {}).get(
                        "failed_source_count", 0
                    )
                ),
            ))
            if search_result is not None else None
        ),
    )
    if chat_service is not None:
        archive_entries = _archive_from_history(
            session.history,
            provider=provider_name,
            model=session.last_response_model or model_name,
            search_result=search_result,
            rendered_answer=answer,
            context=session.last_context_telemetry,
        )
        extraction = MemoryExtractionRequest(
            new_extraction_id(), len(archive_entries) - 2,
            len(archive_entries) - 1, provider_name, model_name,
            provider_definition_fingerprint(provider, provider_name, model_name),
        )
        archived = chat_service.create_chat(
            archive_entries,
            provider=provider_name,
            model=model_name,
            select_active=True,
            context_policy=context_policy,
            memory_extraction=extraction,
        )
        if memory_coordinator is not None:
            memory_coordinator.wake()
    if knowledge_result_function is not None and session.last_knowledge_passages:
        knowledge_result_function(session.last_knowledge_passages)
    return answer


def run_interactive(
    provider: ModelProvider,
    *,
    checkpoint_store: CheckpointStore | None = None,
    memory_store: SQLiteMemoryStore | None = None,
    knowledge_registry: KnowledgeRegistry | None = None,
    provider_name: str = "unknown",
    model_name: str = "unknown",
    initial_history: Sequence[ChatMessage] = (),
    chat_service: ChatService | None = None,
    active_chat: ChatDetail | None = None,
    model_catalog: ModelCatalogService | None = None,
    web_search: SearchPort | None = None,
    source_retrieval: SourceRetrievalPort | None = None,
    capability_settings: CapabilitySettingsController | None = None,
    command_service: CommandExecutionService | None = None,
    context_policy: ContextPolicy = ContextPolicy(),
    model_capacity: int | None = None,
    memory_coordinator: MemoryExtractionCoordinator | None = None,
    input_function: InputFunction = input,
    output_function: OutputFunction = print,
) -> int:
    """Run one multi-turn conversation with automatic archive persistence."""

    store = checkpoint_store if checkpoint_store is not None else CheckpointStore()
    active_project_id = (
        None if active_chat is None else active_chat.metadata.project_id
    )
    session = ConversationSession(
        provider,
        initial_history=initial_history,
        memory_store=memory_store,
        memory_warning_function=output_function,
        knowledge_registry=knowledge_registry,
        knowledge_warning_function=output_function,
        model_name=model_name,
        context_policy=context_policy,
        model_capacity=model_capacity,
        capability_awareness=cli_capabilities(memory_store, knowledge_registry, web_search, capability_settings, commands=command_service).awareness,
        project_context_planner=_project_context_planner(
            chat_service, active_project_id
        ),
    )
    commands = LocalCommandService(
        checkpoint_store=store,
        memory_store=memory_store,
        knowledge_registry=knowledge_registry,
        provider_name=provider_name,
        model_name=model_name,
    )
    search_policy = SearchApplicationPolicy(
        SearchConsent(clock=time.monotonic),
        implementation_available=lambda: (
            web_search is not None and web_search.available
        ),
        capability_settings=capability_settings,
        source_retrieval_available=lambda: source_retrieval is not None,
    )
    search_conversation_key = active_chat.metadata.identifier if active_chat is not None else f"session-{secrets.token_hex(16)}"
    active_identifier = (
        active_chat.metadata.identifier if active_chat is not None else None
    )
    active_revision = (
        active_chat.metadata.revision if active_chat is not None else None
    )
    archive_entries = list(
        active_chat.entries
        if active_chat is not None
        else _archive_from_history(initial_history)
    )
    output_function(
        f"Tori is ready with {provider_name}/{model_name}. "
        "Use /remember, /memories, /update-memory, or /forget "
        "to manage curated memory; use /add-knowledge, /knowledge, or "
        "/remove-knowledge to manage selected local knowledge sources; "
        "use /models and /model to inspect or change the active local model; "
        "use /search QUERY for one explicit web search; "
        "use the loopback browser terminal for supervised commands; "
        "type /save [name] to save this conversation, or /exit or /quit "
        "to end the session."
    )

    while True:
        if memory_coordinator is not None and active_identifier is not None:
            proposal = memory_coordinator.attention_for_chat(active_identifier)
            if proposal is not None:
                output_function("Memory proposal: " + str(proposal["message"]))
                try:
                    entered = input_function("Save this memory? Type YES to confirm: ")
                except (EOFError, KeyboardInterrupt):
                    entered = ""
                try:
                    status = memory_coordinator.decide(
                        str(proposal["extraction_id"]),
                        expected_revision=int(proposal["revision"]),
                        chat_id=active_identifier,
                        token=str(proposal["token"]),
                        decision="confirm" if entered == "YES" else "cancel",
                    )
                except ChatServiceError:
                    status = "Memory proposal was stale or could not be saved."
                output_function(status)
        try:
            prompt = input_function("You: ")
        except EOFError:
            output_function("\nTori: Goodbye for now.")
            return 0
        except KeyboardInterrupt:
            output_function("\nTori stopped.")
            return 130

        normalized_prompt = prompt.strip()
        if normalized_prompt.lower() in EXIT_COMMANDS:
            output_function("Tori: Goodbye for now.")
            return 0

        try:
            command = parse_run_command(normalized_prompt)
        except ActionContractError as exc:
            output_function(f"Command error: {exc}")
            continue
        if command is not None:
            output_function("Command unavailable in the CLI. Use Tori's loopback browser terminal.")
            continue

        model_command = _handle_model_command(
            normalized_prompt,
            catalog=model_catalog,
            current=ModelIdentity(provider_name, model_name),
            chat_service=chat_service,
            active_identifier=active_identifier,
            active_revision=active_revision,
        )
        if model_command is not None:
            text, selection, revised = model_command
            output_function(text)
            if selection is not None:
                provider_name = selection.provider
                model_name = selection.model
                assert model_catalog is not None
                provider = model_catalog.provider_for(selection)
                session.select_model(
                    provider,
                    model_name,
                    model_capacity=model_catalog.known_capacity(selection),
                )
                commands.select_model(provider_name, model_name)
                if revised is not None:
                    active_revision = revised
            continue

        search_result = None
        proposed = False
        declined = False
        try:
            search_decision = search_policy.evaluate(
                normalized_prompt,
                conversation_id=search_conversation_key,
            )
        except ValueError as exc:
            output_function(f"Search error: {exc}")
            continue
        query = search_decision.query
        if search_decision.disposition == "declined":
            answer = "Okay—I won’t search the web for that."
            session.record_exchange(normalized_prompt, answer)
            declined = True
        elif search_decision.disposition == "clarification":
            answer = BARE_SEARCH_CLARIFICATION_MESSAGE
            session.record_exchange(normalized_prompt, answer)
            proposed = True
        elif search_decision.disposition == "proposal":
            answer = FRESHNESS_SEARCH_PROPOSAL_MESSAGE
            session.record_exchange(normalized_prompt, answer)
            proposed = True
        elif search_decision.disposition in {
            "disabled", "unavailable", "settings_failure"
        }:
            search_error = _search_blocked_message(search_decision.disposition)
            if search_decision.source in {"explicit", "consent"}:
                output_function(f"Search error: {search_error}")
                continue
            answer = search_error
            session.record_exchange(normalized_prompt, answer)
            proposed = True
        elif search_decision.disposition == "authorized":
            try:
                if search_decision.source_urls:
                    assert source_retrieval is not None
                    search_result = retrieve_direct_url_evidence(
                        normalized_prompt,
                        search_decision.source_urls,
                        source_retrieval,
                    )
                else:
                    assert query is not None and web_search is not None
                    search_result = web_search.search(
                        query, category=search_category_for_query(query)
                    )
                    if source_retrieval is not None:
                        search_result = retrieve_search_evidence(
                            search_result, source_retrieval
                        )
            except SearchError:
                output_function(f"Search error: {SEARCH_UNAVAILABLE_MESSAGE}")
                continue

        command_result = None if (query is not None or proposed or declined) else commands.handle(
            normalized_prompt,
            history=session.history,
        )
        if command_result is not None:
            if command_result.confirmation is None:
                output_function(command_result.text)
                continue
            confirmation = command_result.confirmation
            expected = f"FORGET {confirmation.identifier}"
            try:
                entered = input_function(confirmation.prompt)
            except (EOFError, KeyboardInterrupt):
                output_function(
                    f"Forget cancelled; memory "
                    f"{confirmation.identifier} remains."
                )
                continue
            if entered != expected:
                output_function(
                    f"Forget cancelled; memory "
                    f"{confirmation.identifier} remains."
                )
                continue
            output_function(
                commands.confirm_forget(
                    confirmation.identifier,
                    expected_updated_at=confirmation.updated_at,
                ).text
            )
            continue

        try:
            if model_catalog is not None:
                model_catalog.catalog()
                current_identity = ModelIdentity(provider_name, model_name)
                if model_catalog.known_status(current_identity) == "unavailable":
                    output_function(
                        "Model error: The selected model is not available locally."
                    )
                    continue
                try:
                    model_catalog.provider_for(current_identity)
                except ModelCatalogError:
                    output_function(
                        "Model error: The selected model provider is not available."
                    )
                    continue
            if not proposed and not declined:
                answer = session.send(
                    normalized_prompt,
                    supplemental_system=_combined_context(
                        build_search_context(search_result)
                        if search_result is not None else None,
                    ),
                    response_transform=(
                        (lambda text: format_search_answer(
                            text,
                            search_result.sources,
                            direct_source=(
                                search_result.capability_id
                                == "web_source_retrieval"
                            ),
                            failed_source_count=int(
                                (search_result.metadata or {}).get(
                                    "failed_source_count", 0
                                )
                            ),
                        ))
                        if search_result is not None else None
                    ),
                )
        except ValueError as exc:
            output_function(f"Input error: {exc}")
            continue
        except ExternalKnowledgeNeededAdvisory:
            advisory = search_policy.propose_external_knowledge(
                normalized_prompt,
                conversation_id=search_conversation_key,
            )
            if advisory.disposition == "proposal":
                answer = EXTERNAL_KNOWLEDGE_PROPOSAL_MESSAGE
            elif advisory.disposition == "clarification":
                answer = (
                    "I'm not finding enough reliable information in what I "
                    "have available. Please give me a shorter search topic "
                    "if you'd like me to offer web search."
                )
            else:
                answer = _search_blocked_message(advisory.disposition)
            session.record_exchange(normalized_prompt, answer)
            proposed = True
        except SearchAttributionError as exc:
            output_function(f"Search error: {exc}")
            continue
        except ProviderTimeoutError as exc:
            LOGGER.error("Model provider timed out: %s", exc)
            output_function(
                "Tori timed out waiting for the configured model provider. "
                "Try again or type /exit."
            )
            continue
        except ProviderConnectionError as exc:
            LOGGER.error("Model provider connection failed: %s", exc)
            output_function(
                "Tori could not reach the configured model provider. "
                "Confirm it is running, then try again or type /exit."
            )
            continue
        except ProviderMalformedResponseError as exc:
            LOGGER.error("Model provider response was malformed: %s", exc)
            output_function(
                "The configured model provider returned a malformed response. "
                "Try again or type /exit."
            )
            continue
        except ProviderUnsupportedResponseError as exc:
            LOGGER.error("Model provider response was unsupported: %s", exc)
            output_function(
                "The configured model provider returned an unsupported response. "
                "Try again or type /exit."
            )
            continue
        except ProviderError as exc:
            LOGGER.error("Model provider request failed: %s", exc)
            output_function(
                "Tori could not complete the model request. "
                "Try again or type /exit."
            )
            continue

        output_function(f"\nTori: {answer}\n")
        if chat_service is not None:
            try:
                archive_entries.extend(
                    _archive_from_history(
                        session.history[-2:],
                        provider=(provider_name if not (proposed or declined) else None),
                        model=(session.last_response_model or model_name) if not (proposed or declined) else None,
                        search_result=search_result,
                        rendered_answer=answer,
                        context=(
                            session.last_context_telemetry
                            if not (proposed or declined)
                            else None
                        ),
                    )
                )
                entries = tuple(archive_entries)
                extraction = (
                    MemoryExtractionRequest(
                        new_extraction_id(), len(entries) - 2, len(entries) - 1,
                        provider_name, model_name,
                        provider_definition_fingerprint(
                            provider, provider_name, model_name
                        ),
                    )
                    if not (proposed or declined) else None
                )
                if active_identifier is None:
                    archived = chat_service.create_chat(
                        entries,
                        provider=provider_name,
                        model=model_name,
                        select_active=True,
                        context_policy=session.context_policy,
                        memory_extraction=extraction,
                        project_context_receipt=(
                            session.last_project_context_pack.receipt(len(entries) - 1)
                            if session.last_project_context_pack is not None else None
                        ),
                    )
                else:
                    assert active_revision is not None
                    archived = chat_service.reconcile_chat(
                        active_identifier,
                        entries,
                        expected_revision=active_revision,
                        provider=provider_name,
                        model=model_name,
                        memory_extraction=extraction,
                        project_context_receipt=(
                            session.last_project_context_pack.receipt(len(entries) - 1)
                            if session.last_project_context_pack is not None else None
                        ),
                    )
                active_identifier = archived.metadata.identifier
                active_revision = archived.metadata.revision
                archive_entries = list(archived.entries)
                if extraction is not None and memory_coordinator is not None:
                    memory_coordinator.wake()
            except ChatServiceError as exc:
                output_function(f"Conversation archive error: {exc}")
        _render_knowledge_footer(
            session.last_knowledge_passages,
            output_function=output_function,
        )


def list_checkpoints(
    store: CheckpointStore,
    *,
    output_function: OutputFunction = print,
) -> None:
    """Print checkpoint metadata without reading transcript content aloud."""

    checkpoints = store.list_checkpoints()
    if not checkpoints:
        output_function(f"No checkpoints found in {store.root}.")
        return

    output_function(f"Conversation checkpoints in {store.root}:")
    for metadata in checkpoints:
        display_name = metadata.display_name or "<unnamed>"
        output_function(
            f"- {metadata.identifier} | name: {display_name} | "
            f"created: {metadata.created_at} | messages: "
            f"{metadata.message_count} | provider: {metadata.provider} | "
            f"model: {metadata.model}"
        )


def remove_checkpoint(
    store: CheckpointStore,
    identifier: str,
    *,
    output_function: OutputFunction = print,
) -> None:
    """Remove one validated checkpoint and report its non-transcript metadata."""

    metadata = store.remove_checkpoint(identifier)
    output_function(f"Removed checkpoint {_format_checkpoint_name(metadata)}.")


def build_provider(settings: Settings) -> ModelProvider:
    """Construct the configured default provider for legacy callers."""

    profile = (
        settings.profile(settings.provider)
        if settings.profiles
        else ProviderProfile(
            settings.provider,
            "Local Ollama",
            "ollama",
            settings.base_url,
            settings.timeout_seconds,
            keep_alive=settings.keep_alive,
        )
    )
    return _build_profile_provider(profile, settings.model_name)


def build_providers(settings: Settings) -> dict[str, ModelProvider]:
    """Construct every administrator-configured model provider profile."""

    if not settings.profiles:
        # Compatibility for callers constructing the pre-M23 Settings shape.
        return {settings.provider: build_provider(settings)}
    return {
        profile.identifier: (
            build_provider(settings)
            if profile.identifier == settings.provider
            else _build_profile_provider(profile, settings.model_name)
        )
        for profile in settings.profiles
    }


def _build_profile_provider(
    profile: ProviderProfile, default_model: str, *, bearer_token: str | None = None
) -> ModelProvider:
    if profile.implementation == "ollama":
        assert profile.keep_alive is not None
        return OllamaProvider(
            profile_id=profile.identifier,
            base_url=profile.base_url,
            model_name=default_model,
            timeout_seconds=profile.timeout_seconds,
            keep_alive=profile.keep_alive,
        )
    if profile.implementation == "openai_compatible":
        return OpenAICompatibleProvider(
            profile_id=profile.identifier,
            base_url=profile.base_url,
            model_name=default_model,
            timeout_seconds=profile.timeout_seconds,
            authentication=profile.authentication,
            credential_environment=profile.credential_environment,
            bearer_token=bearer_token,
            structured_output=profile.structured_output,
        )

    raise ConfigError(f"Unsupported model provider type: {profile.implementation!r}.")


def _configured_profiles(settings: Settings) -> tuple[ProviderProfile, ...]:
    if settings.profiles:
        return settings.profiles
    return (
        ProviderProfile(
            settings.provider,
            "Local Ollama",
            "ollama",
            settings.base_url,
            settings.timeout_seconds,
            keep_alive=settings.keep_alive,
        ),
    )


def build_web_search(settings: Settings) -> SearXNGSearch:
    """Construct the one administrator-configured local search adapter."""
    return SearXNGSearch(
        enabled=settings.search_enabled,
        endpoint=settings.search_endpoint,
        result_limit=settings.search_result_limit,
        timeout_seconds=settings.search_timeout_seconds,
    )


def build_source_retrieval() -> SourceRetrievalService:
    """Construct Tori's bounded public-source retrieval boundary."""

    return SourceRetrievalService(PublicSourceRetriever())


def build_tts(settings: Settings) -> SpeechCoordinator | None:
    """Construct the legacy fixed source for isolated compatibility callers."""
    if not settings.tts_enabled:
        return None
    try:
        provider = create_tts_provider(
            settings.tts_provider,
            endpoint=settings.tts_endpoint,
            connect_timeout_seconds=settings.tts_connect_timeout_seconds,
            read_timeout_seconds=settings.tts_read_timeout_seconds,
        )
    except (TTSProviderError, ValueError) as exc:
        raise ConfigError(str(exc)) from exc
    return SpeechCoordinator(provider, voice=settings.tts_voice)


def build_tts_profile_lifecycle(
    settings: Settings,
    *,
    store: SQLiteTTSProfileStore | None = None,
) -> tuple[
    SpeechCoordinator | None,
    TTSProfileApplicationService,
    TTSProfileRuntime,
]:
    """Initialize and compose canonical profile-owned production speech."""
    application = TTSProfileApplicationService(
        store if store is not None else SQLiteTTSProfileStore()
    )
    try:
        initialized = application.initialize_from_configured_profile(
            display_name=f"Configured {settings.tts_provider.title()} speech",
            provider_type=settings.tts_provider,
            endpoint=settings.tts_endpoint,
            model=None,
            voice=settings.tts_voice,
            connect_timeout_seconds=settings.tts_connect_timeout_seconds,
            read_timeout_seconds=settings.tts_read_timeout_seconds,
        )
    except TTSProfileError as exc:
        raise ConfigError(
            "Canonical TTS profiles could not be initialized safely."
        ) from exc
    if initialized:
        LOGGER.info(
            "Initialized canonical TTS profiles from the configured compatibility source."
        )
    runtime = TTSProfileRuntime(application)
    coordinator = SpeechCoordinator(runtime) if settings.tts_enabled else None
    return coordinator, application, runtime


def _backup_root_for_project(project_root: Path) -> Path:
    if project_root == PRODUCTION_PROJECT_ROOT:
        return PRODUCTION_BACKUP_ROOT
    return project_root.parent / (project_root.name + "_backups")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    arguments = parser.parse_args(argv)

    checkpoint_action = (
        arguments.list_checkpoints
        or arguments.resume is not None
        or arguments.remove_checkpoint is not None
    )
    chat_action = (
        arguments.list_chats
        or arguments.resume_chat is not None
        or arguments.remove_chat is not None
        or arguments.new_chat
    )
    if arguments.list_models and (checkpoint_action or chat_action):
        parser.error("--list-models cannot be combined with saved-conversation actions")
    if arguments.model is not None and (
        arguments.list_checkpoints
        or arguments.remove_checkpoint is not None
        or arguments.list_chats
        or arguments.remove_chat is not None
    ):
        parser.error("--model cannot be combined with a listing or removal action")
    if arguments.context is not None and (
        arguments.list_checkpoints
        or arguments.remove_checkpoint is not None
        or arguments.list_chats
        or arguments.remove_chat is not None
        or arguments.list_models
    ):
        parser.error("--context cannot be combined with a listing or removal action")
    if checkpoint_action and chat_action:
        parser.error("checkpoint and conversation-archive actions cannot be combined")

    if arguments.prompt is not None and (
        arguments.list_checkpoints
        or arguments.resume is not None
        or arguments.remove_checkpoint is not None
        or arguments.list_chats
        or arguments.resume_chat is not None
        or arguments.remove_chat is not None
        or arguments.new_chat
        or arguments.list_models
    ):
        parser.error(
            "a positional prompt cannot be combined with a saved-conversation action"
        )
    if arguments.web and (
        arguments.prompt is not None
        or arguments.list_checkpoints
        or arguments.remove_checkpoint is not None
        or arguments.list_chats
        or arguments.resume_chat is not None
        or arguments.remove_chat is not None
        or arguments.new_chat
        or arguments.list_models
    ):
        parser.error(
            "--web cannot be combined with a positional prompt, "
            "--list-checkpoints, or --remove-checkpoint"
        )
    if arguments.web_port is not None and not arguments.web:
        parser.error("--web-port requires --web")

    checkpoint_store = CheckpointStore()
    chat_service = ChatService(ConversationArchiveStore())
    memory_store = SQLiteMemoryStore()
    knowledge_registry = KnowledgeRegistry()
    if arguments.list_checkpoints:
        try:
            list_checkpoints(checkpoint_store, output_function=print)
        except CheckpointError as exc:
            print(f"Checkpoint error: {exc}")
            return CHECKPOINT_EXIT_CODE
        return 0

    if arguments.remove_checkpoint is not None:
        try:
            remove_checkpoint(
                checkpoint_store,
                arguments.remove_checkpoint,
                output_function=print,
            )
        except CheckpointError as exc:
            print(f"Checkpoint error: {exc}")
            return CHECKPOINT_EXIT_CODE
        return 0

    if arguments.list_chats:
        try:
            _list_chats(chat_service, output_function=print)
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
        return 0

    if arguments.remove_chat is not None:
        try:
            detail = chat_service.get_chat(arguments.remove_chat)
            removed = chat_service.delete_chat(
                arguments.remove_chat,
                expected_revision=detail.metadata.revision,
            )
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
        print(f"Deleted archived conversation {removed.identifier} ({removed.label}).")
        return 0

    restored_history: Sequence[ChatMessage] = ()
    resumed_metadata: CheckpointMetadata | None = None
    resumed_chat: ChatDetail | None = None
    if arguments.resume is not None:
        try:
            checkpoint = checkpoint_store.load_checkpoint(arguments.resume)
        except CheckpointError as exc:
            print(f"Checkpoint error: {exc}")
            return CHECKPOINT_EXIT_CODE
        restored_history = checkpoint.messages
        resumed_metadata = checkpoint.metadata
        try:
            chat_service.new_session()
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
    elif arguments.resume_chat is not None:
        try:
            detail = chat_service.get_chat(arguments.resume_chat)
            resumed_chat = chat_service.open_chat(
                arguments.resume_chat,
                expected_revision=detail.metadata.revision,
            )
            restored_history = chat_service.model_history(arguments.resume_chat)
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
    elif arguments.new_chat:
        try:
            chat_service.new_session()
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
    elif arguments.prompt is None:
        try:
            active_identifier = chat_service.active_chat_id()
            if active_identifier is not None:
                resumed_chat = chat_service.get_chat(active_identifier)
                restored_history = chat_service.model_history(active_identifier)
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE

    try:
        settings = load_settings(Path(arguments.config))
        configure_logging(settings.log_level)
        providers = build_providers(settings)
        web_search = build_web_search(settings)
        source_retrieval = build_source_retrieval()
        tts_lifecycle = (
            build_tts_profile_lifecycle(settings) if arguments.web else None
        )
        tts = tts_lifecycle[0] if tts_lifecycle is not None else None
        user_settings_store = SQLiteUserSettingsStore()
        capability_settings = CapabilitySettingsController(
            administrator_web_search=settings.search_enabled,
            administrator_speech_output=settings.tts_enabled,
            store=user_settings_store,
        )
        timezone_name = discover_timezone(settings.timezone)
    except (ConfigError, TimeContextError) as exc:
        print(f"Configuration error: {exc}")
        return 2

    configured_identity = validate_model_identity(
        settings.provider, settings.model_name
    )
    try:
        local_provider_settings = LocalProviderSettingsStore()

        def profile_provider(
            profile: ProviderProfile, bearer_token: str | None
        ) -> ModelProvider:
            # Preserve the already-constructed configured provider when no
            # owner override or stored credential is present.  This keeps the
            # flat-settings compatibility path identity-stable while edits
            # and secrets still force a rebuilt effective provider.
            record = local_provider_settings.record(profile.identifier)
            existing = providers.get(profile.identifier)
            if record is None and bearer_token is None and existing is not None:
                return existing
            return _build_profile_provider(
                profile, settings.model_name, bearer_token=bearer_token
            )

        profile_controller = ModelProviderProfileController(
            configured_profiles=_configured_profiles(settings),
            configured_identity=configured_identity,
            provider_factory=profile_provider,
            store=SQLiteProviderProfileStore(),
            local_settings=local_provider_settings,
        )
    except ProviderProfileError as exc:
        print(f"Model provider profile error: {exc}")
        return 2
    model_catalog = profile_controller.catalog
    if arguments.list_models:
        _render_model_catalog(model_catalog.catalog(refresh=True), output_function=print)
        return 0

    selected_identity = configured_identity
    if (
        resumed_chat is None
        and arguments.resume is None
        and arguments.model is None
        and (arguments.web or arguments.prompt is None)
    ):
        try:
            saved_selection = user_settings_store.read().last_selected_model
        except UserSettingsError as exc:
            print(
                "Model selection preference is unavailable; using the configured "
                f"default for this startup: {exc}"
            )
        else:
            if saved_selection is not None:
                selected_identity = saved_selection
    context_policy = (
        resumed_chat.metadata.context_policy
        if resumed_chat is not None
        else ContextPolicy()
    )
    if resumed_chat is not None:
        try:
            selected_identity = resumed_chat.metadata.selected_model
        except ChatServiceError as exc:
            print(f"Conversation archive error: {exc}")
            return CHAT_EXIT_CODE
    if arguments.model is not None:
        try:
            requested = parse_model_selection(
                arguments.model,
                default_provider=settings.provider,
                known_providers=model_catalog.provider_identifiers,
            )
            selected_identity = model_catalog.validate_selection(
                requested.provider, requested.model
            )
            user_settings_store.set_last_selected_model(
                selected_identity.provider, selected_identity.model
            )
            if resumed_chat is not None:
                resumed_chat = chat_service.select_model(
                    resumed_chat.metadata.identifier,
                    expected_revision=resumed_chat.metadata.revision,
                    provider=selected_identity.provider,
                    model=selected_identity.model,
                )
        except (ModelCatalogError, ChatServiceError, UserSettingsError) as exc:
            print(f"Model selection error: {exc}")
            return CHAT_EXIT_CODE
    if arguments.context is not None:
        context_policy = arguments.context
        if resumed_chat is not None:
            try:
                resumed_chat = chat_service.select_context(
                    resumed_chat.metadata.identifier,
                    expected_revision=resumed_chat.metadata.revision,
                    policy=context_policy,
                )
            except ChatServiceError as exc:
                print(f"Context selection error: {exc}")
                return CHAT_EXIT_CODE
    try:
        provider: ModelProvider | None = model_catalog.provider_for(selected_identity)
    except ModelCatalogError:
        if not arguments.web:
            print(
                "Model selection error: The selected model provider is not configured; "
                "no fallback was used."
            )
            return CHAT_EXIT_CODE
        provider = None

    def resolve_memory_provider(
        provider_id: str, deferred_model: str
    ) -> ModelProvider | None:
        try:
            return model_catalog.provider_for(
                ModelIdentity(provider_id, deferred_model)
            )
        except ModelCatalogError:
            return None

    cli_memory_coordinator = MemoryExtractionCoordinator(
        chat_service, memory_store, resolve_memory_provider
    )
    coding_work_runtime = CodingWorkRuntime.start(settings.coding_work)
    research_runtime = ResearchRuntime.start(settings.research)
    planning_runtime = PlanningRuntime.start(settings.planning, environ=os.environ)
    mcp_runtime = MCPRuntime.start(settings.mcp_time) if arguments.web else MCPRuntime()
    planning_status = planning_runtime.service.status()
    finance_conversation = None
    if settings.finance.enabled:
        assert settings.finance.data_root is not None
        repository_root = Path(__file__).resolve().parents[2]
        finance_repository = WorkbookFinanceRepository(
            settings.finance.data_root,
            prohibited_roots=(repository_root, repository_root / "runtime"),
        )
        finance_conversation = FinanceConversationService(
            FinanceService(finance_repository), currency=settings.finance.currency
        )

    LOGGER.info(
        "Tori starting with provider=%s model=%s coding_work=%s research=%s planning=%s mcp_time=%s",
        selected_identity.provider,
        selected_identity.model,
        coding_work_runtime.readiness.code,
        research_runtime.readiness.code,
        planning_status.availability.value,
        mcp_runtime.capability_state().state,
    )

    project_root = Path(__file__).resolve().parents[2]
    backup_root = _backup_root_for_project(project_root)
    try:
        if arguments.web:
            companion_initiative_store = SQLiteCompanionInitiativeStore()
            night_owl_store = SQLiteNightOwlStore()
            return run_web_server(
                provider,
                port=(
                    arguments.web_port
                    if arguments.web_port is not None
                    else DEFAULT_WEB_PORT
                ),
                voice_runtime_settings=settings.voice_input,
                checkpoint_store=checkpoint_store,
                memory_store=memory_store,
                knowledge_registry=knowledge_registry,
                provider_name=selected_identity.provider,
                model_name=selected_identity.model,
                model_catalog=model_catalog,
                provider_profile_controller=profile_controller,
                chat_service=chat_service,
                # An archived resume is owned by the canonical active-chat
                # pointer and WebApplication reloads its complete entries.
                # Passing the same model history as generic checkpoint state
                # would deliberately clear that pointer during construction.
                initial_history=(
                    () if resumed_chat is not None else restored_history
                ),
                web_search=web_search,
                source_retrieval=source_retrieval,
                speech_coordinator=tts,
                tts_profile_application=tts_lifecycle[1],
                tts_profile_runtime=tts_lifecycle[2],
                capability_settings=capability_settings,
                model_selection_store=user_settings_store,
                backup_service=BackupService(
                    project_root=project_root,
                    backup_root=backup_root,
                    coding_work_guard=lambda: coding_work_runtime.backup_guard(
                        project_root=Path(__file__).resolve().parents[2]
                    ),
                    research_guard=(
                        None if research_runtime.service is None
                        else research_runtime.backup_guard
                    ),
                    night_owl_guard=night_owl_store.maintenance_guard,
                ),
                command_service=CommandExecutionService(
                    Path(__file__).resolve().parents[2],
                    policy=ExecutionPolicyService(
                        Path(__file__).resolve().parents[2] / DEFAULT_POLICY_DATABASE
                    ),
                ),
                operational_store=SQLiteOperationalStore(),
                scheduled_work_store=SQLiteScheduledWorkStore(),
                night_owl_store=night_owl_store,
                coding_work_runtime=coding_work_runtime,
                research_runtime=research_runtime,
                planning_service=planning_runtime.service,
                planning_default_task_list=settings.planning.default_task_list,
                planning_default_calendar=settings.planning.default_calendar,
                finance_conversation=finance_conversation,
                timezone_name=timezone_name,
                context_policy=context_policy,
                improvement_journal=SQLiteImprovementJournal(),
                companion_initiative_store=companion_initiative_store,
                mcp_runtime=mcp_runtime,
            )
        if arguments.prompt is None:
            assert provider is not None
            if resumed_metadata is not None:
                print(
                    "Resuming checkpoint "
                    f"{_format_checkpoint_name(resumed_metadata)}."
                )
            elif resumed_chat is not None:
                print(
                    "Resuming archived conversation "
                    f"{resumed_chat.metadata.identifier} ({resumed_chat.metadata.label})."
                )
            cli_memory_coordinator.start()
            try:
                return run_interactive(
                    provider,
                    checkpoint_store=checkpoint_store,
                    memory_store=memory_store,
                    knowledge_registry=knowledge_registry,
                    provider_name=selected_identity.provider,
                    model_name=selected_identity.model,
                    initial_history=restored_history,
                    chat_service=chat_service,
                    active_chat=resumed_chat,
                    model_catalog=model_catalog,
                    web_search=web_search,
                    source_retrieval=source_retrieval,
                    capability_settings=capability_settings,
                    command_service=CommandExecutionService(
                        Path(__file__).resolve().parents[2],
                        policy=ExecutionPolicyService(
                            Path(__file__).resolve().parents[2] / DEFAULT_POLICY_DATABASE
                        ),
                    ),
                    context_policy=context_policy,
                    model_capacity=model_catalog.known_capacity(selected_identity),
                    memory_coordinator=cli_memory_coordinator,
                )
            finally:
                cli_memory_coordinator.stop()

        supplied_knowledge: list[KnowledgePassage] = []
        assert provider is not None
        model_catalog.catalog()
        if model_catalog.known_status(selected_identity) == "unavailable":
            raise ModelUnavailableError(
                "The selected model is not available locally."
            )
        answer = run_once(
            arguments.prompt,
            provider,
            memory_store=memory_store,
            memory_warning_function=print,
            knowledge_registry=knowledge_registry,
            knowledge_warning_function=print,
            knowledge_result_function=supplied_knowledge.extend,
            chat_service=chat_service,
            provider_name=selected_identity.provider,
            model_name=selected_identity.model,
            web_search=web_search,
            source_retrieval=source_retrieval,
            capability_settings=capability_settings,
            context_policy=context_policy,
            model_capacity=model_catalog.known_capacity(selected_identity),
            memory_coordinator=cli_memory_coordinator,
        )
        print(f"\nTori: {answer}")
        _render_knowledge_footer(
            tuple(supplied_knowledge),
            output_function=print,
        )
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nTori stopped.")
        return 130
    except ValueError as exc:
        print(f"Input error: {exc}")
        return 2
    except ProviderTimeoutError as exc:
        LOGGER.error("Model provider timed out: %s", exc)
        print("Tori timed out waiting for the configured model provider.")
        return 3
    except ProviderConnectionError as exc:
        LOGGER.error("Model provider connection failed: %s", exc)
        print(
            "Tori could not reach the configured model provider. "
            "Confirm it is running, then try again."
        )
        return 3
    except SearchError:
        print(f"Search error: {SEARCH_UNAVAILABLE_MESSAGE}")
        return 4
    except ModelUnavailableError:
        print("The selected model is not available locally; no fallback was used.")
        return 4
    except ProviderMalformedResponseError as exc:
        LOGGER.error("Model provider response was malformed: %s", exc)
        print("The configured model provider returned a malformed response.")
        return 4
    except ProviderUnsupportedResponseError as exc:
        LOGGER.error("Model provider response was unsupported: %s", exc)
        print("The configured model provider returned an unsupported response.")
        return 4
    except ProviderError as exc:
        LOGGER.error("Model provider request failed: %s", exc)
        print("Tori could not complete the model request.")
        return 4
    except ChatServiceError as exc:
        LOGGER.error("Conversation archive operation failed safely.")
        print(f"Conversation archive error: {exc}")
        return CHAT_EXIT_CODE
    finally:
        mcp_runtime.close()
        planning_runtime.close()
        coding_work_runtime.shutdown()
        LOGGER.info("Tori stopped cleanly")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tori",
        description="Run Tori's local conversation interfaces.",
    )
    parser.add_argument("--version", action="version", version=f"Tori {__version__}")
    parser.add_argument(
        "prompt",
        nargs="?",
        help=(
            "One request for Tori, followed by immediate exit. "
            "Omit it to start a multi-turn session."
        ),
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List the objective local model catalog and exit.",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Select a provider-native model for the new or active conversation.",
    )
    parser.add_argument(
        "--context",
        type=_parse_context_policy,
        metavar="POLICY",
        help="Select active conversation context: auto or fixed:TOKENS.",
    )
    parser.add_argument(
        "--config",
        default="tori.toml",
        help="Path to the TOML configuration file (default: tori.toml).",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Run the web interface on IPv4 loopback and the local LAN.",
    )
    parser.add_argument(
        "--web-port",
        type=_parse_web_port,
        default=None,
        metavar="PORT",
        help=f"Web port (default: {DEFAULT_WEB_PORT}; requires --web).",
    )
    checkpoint_actions = parser.add_mutually_exclusive_group()
    checkpoint_actions.add_argument(
        "--list-checkpoints",
        action="store_true",
        help="List saved conversation checkpoint metadata and exit.",
    )
    checkpoint_actions.add_argument(
        "--resume",
        metavar="CHECKPOINT_ID",
        help="Resume a validated conversation checkpoint.",
    )
    checkpoint_actions.add_argument(
        "--remove-checkpoint",
        metavar="CHECKPOINT_ID",
        help="Remove one validated conversation checkpoint and exit.",
    )
    chat_actions = parser.add_mutually_exclusive_group()
    chat_actions.add_argument(
        "--list-chats",
        action="store_true",
        help="List automatically archived conversation metadata and exit.",
    )
    chat_actions.add_argument(
        "--resume-chat",
        metavar="CHAT_ID",
        help="Resume one automatically archived conversation.",
    )
    chat_actions.add_argument(
        "--remove-chat",
        metavar="CHAT_ID",
        help="Explicitly delete one automatically archived conversation.",
    )
    chat_actions.add_argument(
        "--new-chat",
        action="store_true",
        help="Start a genuinely new conversation and clear active selection.",
    )
    return parser


def _parse_web_port(value: str) -> int:
    try:
        return validate_web_port(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _parse_context_policy(value: str) -> ContextPolicy:
    try:
        return ContextPolicy.parse(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _format_checkpoint_name(metadata: CheckpointMetadata) -> str:
    if metadata.display_name is None:
        return metadata.identifier
    return f"{metadata.identifier} ({metadata.display_name})"


def _list_chats(
    service: ChatService, *, output_function: OutputFunction
) -> None:
    chats = service.list_chats()
    active = service.active_chat_id()
    if not chats:
        output_function("No archived conversations found.")
        return
    output_function("Automatically archived conversations:")
    for item in chats:
        selected = " | active" if item.identifier == active else ""
        output_function(
            f"- {item.identifier} | {item.label} | updated: {item.updated_at} | "
            f"turns: {item.completed_turn_count} | provider: {item.latest_provider} | "
            f"model: {item.latest_model}{selected}"
        )


def _archive_from_history(
    history: Sequence[ChatMessage],
    *,
    provider: str | None = None,
    model: str | None = None,
    search_result: CapabilityResult | None = None,
    rendered_answer: str | None = None,
    context: ContextTelemetry | None = None,
) -> tuple[ArchiveEntry, ...]:
    entries = tuple(
        ArchiveEntry(
            message.role,
            rendered_answer if message.role == "assistant" and rendered_answer is not None else message.content,
            provider=provider if message.role == "assistant" else None,
            model=model if message.role == "assistant" else None,
            context=(
                _archive_context(context)
                if message.role == "assistant" and provider is not None
                else None
            ),
        )
        for message in history
    )
    if search_result is None:
        return entries
    web_search = ArchiveWebSearch(
        query=search_result.input_text,
        status=search_result.status,
        sources=tuple(
            ArchiveWebSource(source.title, source.url)
            for source in search_result.sources
        ),
    )
    return tuple(
        ArchiveEntry(
            item.role, item.text, item.sources, item.provider, item.model,
            item.created_at, web_search if item.role == "assistant" else None,
            context=item.context,
        )
        for item in entries
    )


def _archive_context(value: ContextTelemetry | None) -> ArchiveContext | None:
    if value is None:
        return None
    usage = value.actual_usage
    return ArchiveContext(
        requested_policy=value.requested_policy,
        effective_budget=value.effective_budget,
        estimator_version=value.estimator_version,
        estimated_input_tokens=value.estimated_input_tokens,
        included_history_messages=value.included_history_messages,
        omitted_history_messages=value.omitted_history_messages,
        actual_prompt_tokens=None if usage is None else usage.prompt_tokens,
        actual_completion_tokens=None if usage is None else usage.completion_tokens,
        actual_total_tokens=None if usage is None else usage.total_tokens,
    )


def _handle_model_command(
    prompt: str,
    *,
    catalog: ModelCatalogService | None,
    current: ModelIdentity,
    chat_service: ChatService | None,
    active_identifier: str | None,
    active_revision: int | None,
) -> tuple[str, ModelIdentity | None, int | None] | None:
    command, separator, argument = prompt.partition(" ")
    normalized = command.lower()
    if normalized not in {"/models", "/model"}:
        return None
    if catalog is None:
        return "Model catalog unavailable in this interface.", None, None
    if normalized == "/models":
        if separator and argument.strip():
            return "Model command failed: Usage: /models", None, None
        lines: list[str] = []
        _render_model_catalog(
            catalog.catalog_with(current, refresh=True),
            output_function=lines.append,
        )
        return "\n".join(lines), None, None
    if not separator or not argument.strip():
        status = catalog.known_status(current)
        return (
            f"Current model: {current.qualified_name} ({status}).",
            None,
            None,
        )
    try:
        requested = parse_model_selection(
            argument.strip(),
            default_provider=current.provider,
            known_providers=catalog.provider_identifiers,
        )
        selected = catalog.validate_selection(
            requested.provider, requested.model
        )
        revision = None
        if active_identifier is not None:
            if chat_service is None or active_revision is None:
                raise ChatServiceError(
                    "The active chat state is invalid.", code="conflict"
                )
            revised = chat_service.select_model(
                active_identifier,
                expected_revision=active_revision,
                provider=selected.provider,
                model=selected.model,
            )
            revision = revised.metadata.revision
    except (ModelCatalogError, ChatServiceError) as exc:
        return f"Model selection failed: {exc}", None, None
    return f"Selected model: {selected.qualified_name}.", selected, revision


def _render_model_catalog(
    catalog: ModelCatalog, *, output_function: OutputFunction
) -> None:
    if catalog.error is not None:
        output_function(catalog.error)
    if not catalog.models:
        output_function("No local models were reported.")
        return
    output_function("Local model catalog (objective provider metadata):")
    for item in catalog.models:
        details = [item.status]
        if item.family is not None:
            details.append(f"family {item.family}")
        if item.parameter_size is not None:
            details.append(f"parameters {item.parameter_size}")
        if item.quantization is not None:
            details.append(f"quantization {item.quantization}")
        if item.storage_size is not None:
            details.append(f"bytes {item.storage_size}")
        output_function(f"- {item.qualified_name} | " + " | ".join(details))


def _render_knowledge_listing(
    listing: KnowledgeListing,
    *,
    registry: KnowledgeRegistry,
    output_function: OutputFunction,
) -> None:
    """Render the shared knowledge listing for the CLI."""

    for line in format_knowledge_listing(listing, registry=registry).splitlines():
        output_function(line)


def _render_knowledge_footer(
    passages: tuple[KnowledgePassage, ...],
    *,
    output_function: OutputFunction,
) -> None:
    if not passages:
        return
    output_function("Knowledge supplied:")
    for reference in source_references(passages):
        if reference.line_start == reference.line_end:
            location = f"source line {reference.line_start}"
        else:
            location = (
                f"source span {reference.line_start}–{reference.line_end}"
            )
        output_function(f"- {reference.filename} — {location}")
