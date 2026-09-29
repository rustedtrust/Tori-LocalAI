"""Production composition for the accepted Remote Chat V1 boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
import os
import threading
import time

from .chats import ChatService
from .context import ContextPolicy
from .conversation import ConversationSession
from .conversation_application import ConversationTurnService
from .discord_remote_adapter import DiscordRemoteChannel
from .memory import SQLiteMemoryStore
from .operation_coordinator import OperationCoordinator
from .providers import ChatMessage, ModelProvider
from .remote_chat import RemoteChatService
from .remote_chat_config import (
    RemoteChatConfiguration,
    RemoteChatConfigStore,
    RemoteConfigError,
)
from .remote_chat_ledger import RemoteChatLedger
from .remote_chat_operations import (
    RemoteSearchHandler,
    RemoteSelfTerminationHandler,
    RemoteUpcomingReminderHandler,
    remote_handlers,
)
from .remote_chat_transport import RemoteChannelPort, RemoteTransportState
from .search_port import SearchPort
from .source_retrieval import SourceRetrievalPort
from .task_reminder_application import TaskReminderApplicationService
from .user_settings import CapabilitySettingsController


class RemoteChatCompositionError(RuntimeError):
    """Enabled Remote Chat cannot be composed without weakening its contract."""


class RemoteChatWebControlError(RuntimeError):
    """A bounded Web enable/disable request could not be completed safely."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RemoteChatComposition:
    conversation_turns: ConversationTurnService
    service: RemoteChatService | None
    backup_guard: Callable[[], AbstractContextManager[None]] | None = None
    startup_configuration_revision: int | None = None


class RemoteChatWebControl:
    """Sanitized status plus loopback-gated owner enablement mutation."""

    def __init__(
        self,
        store: RemoteChatConfigStore,
        service: RemoteChatService | None,
        *,
        setup_error: bool = False,
        startup_configuration_revision: int | None = None,
    ) -> None:
        self._store = store
        self._service = service
        self._setup_error = setup_error
        self._startup_configuration_revision = startup_configuration_revision
        self._session_enabled = False
        self._lock = threading.RLock()

    def status_document(self) -> dict[str, object]:
        try:
            configuration = self._store.load_if_present()
            if configuration is None:
                return {
                    "configured": False,
                    "administrator_permitted": False,
                    "enabled": False,
                    "effective_enabled": False,
                    "state": "not_configured",
                    "restart_required": False,
                }
            live = self._store.combined_status()
        except RemoteConfigError as exc:
            raise RemoteChatWebControlError(
                "Remote Chat status is unavailable.", code="status_unavailable"
            ) from exc
        runtime_state = str(live.get("runtime_state", "runtime_error"))
        service = self._service
        if self._session_enabled and configuration.effective_enabled and service is not None:
            service_status = service.status()
            if (
                service_status.state is RemoteTransportState.CONNECTED
                and service_status.worker_alive
            ):
                runtime_state = "connected_ready"
            elif service_status.state is RemoteTransportState.CONNECTING:
                runtime_state = "connecting"
            elif service_status.state is RemoteTransportState.ERROR:
                runtime_state = "runtime_error"
        effective_enabled = self._session_enabled and configuration.effective_enabled
        if self._setup_error and configuration.effective_enabled:
            state = "error"
        elif not configuration.complete:
            state = "not_configured"
        elif not effective_enabled:
            state = "disabled"
        else:
            state = {
                "connected_ready": "connected",
                "connecting": "connecting",
                "stopping": "stopping",
                "authentication_configuration_error": "error",
                "runtime_error": "error",
            }.get(runtime_state, "disconnected")
        restart_required = bool(
            (effective_enabled or self._setup_error)
            and state != "connected"
            and (
                self._setup_error
                or service is None
                or service.status().state is RemoteTransportState.ERROR
            )
        )
        return {
            "configured": configuration.complete,
            "administrator_permitted": configuration.administrator_permitted,
            "enabled": self._session_enabled,
            "effective_enabled": effective_enabled,
            "configured_enabled": configuration.enabled,
            "state": state,
            "restart_required": restart_required,
        }

    def set_enabled(self, enabled: object) -> dict[str, object]:
        if not isinstance(enabled, bool):
            raise RemoteChatWebControlError(
                "Remote Chat enablement must be true or false.",
                code="invalid_setting",
            )
        with self._lock:
            try:
                if not enabled:
                    self._disable()
                else:
                    self._enable()
            except RemoteConfigError as exc:
                raise RemoteChatWebControlError(
                    "Remote Chat could not change enablement. Verify its local "
                    "configuration and administrator permission.",
                    code="configuration_incomplete",
                ) from exc
            except Exception as exc:
                # Keep provider/SDK/configuration details outside the browser.
                raise RemoteChatWebControlError(
                    "Remote Chat changed state but could not complete its live "
                    "connector transition. Check the terminal and status.",
                    code="runtime_transition_failed",
                ) from exc
            return self.status_document()

    def _disable(self) -> None:
        self._session_enabled = False
        configuration = self._store.load_if_present()
        service = self._service
        if service is not None and service.status().worker_alive:
            service.kill()
        elif configuration is not None and configuration.enabled:
            self._store.set_enabled(False)

    def _enable(self) -> None:
        configuration = self._store.load_if_present()
        if configuration is None:
            raise RemoteConfigError(
                "Remote Chat configuration must be completed locally before enablement."
            )
        if not configuration.effective_enabled:
            configuration = self._store.set_enabled(True)
        self._session_enabled = True
        service = self._service
        if self._setup_error:
            return
        if service is None:
            return
        status = service.status()
        if status.worker_alive and status.state is RemoteTransportState.CONNECTED:
            return
        if status.state is RemoteTransportState.ERROR:
            return
        service.start()

    def refresh_local_enablement(self) -> None:
        """Accept only a post-start local CLI enable revision."""

        with self._lock:
            if self._session_enabled or self._setup_error:
                return
            configuration = self._store.load_if_present()
            if (
                configuration is None
                or self._startup_configuration_revision is None
                or configuration.revision <= self._startup_configuration_revision
                or not configuration.effective_enabled
            ):
                return
            self._session_enabled = True
            service = self._service
            if service is not None:
                service.start()


def compose_remote_chat(
    *,
    coordinator: OperationCoordinator,
    provider: ModelProvider | None,
    memory_store: SQLiteMemoryStore,
    chat_service: ChatService | None,
    task_reminders: TaskReminderApplicationService | None,
    provider_name: str,
    model_name: str,
    web_search: SearchPort | None,
    source_retrieval: SourceRetrievalPort | None,
    capability_settings: CapabilitySettingsController | None,
    context_policy: ContextPolicy,
    model_capacity: int | None = None,
    config_store: RemoteChatConfigStore | None = None,
    ledger_factory: Callable[[], RemoteChatLedger] | None = None,
    transport_factory: Callable[[RemoteChatConfiguration], RemoteChannelPort]
    | None = None,
    activity_signal: Callable[[str, str], None] | None = None,
) -> RemoteChatComposition:
    """Compose the shared turn service and an optional default-off connector."""

    store = config_store or RemoteChatConfigStore()
    configuration = store.load_if_present()
    if configuration is None:
        make_ledger = ledger_factory or RemoteChatLedger
        ledger = make_ledger()
        guard = (
            _unconfigured_remote_backup_guard(ledger)
            if os.path.lexists(ledger.path)
            else None
        )
        return RemoteChatComposition(
            ConversationTurnService(coordinator, activity_signal=activity_signal),
            None,
            guard,
        )
    if not (configuration.complete and configuration.administrator_permitted):
        make_ledger = ledger_factory or RemoteChatLedger
        ledger = make_ledger()
        guard = (
            _disabled_remote_backup_guard(store, ledger)
            if os.path.lexists(ledger.path)
            else None
        )
        return RemoteChatComposition(
            ConversationTurnService(coordinator, activity_signal=activity_signal),
            None,
            guard,
        )
    if provider is None or chat_service is None or task_reminders is None:
        if not configuration.enabled:
            make_ledger = ledger_factory or RemoteChatLedger
            ledger = make_ledger()
            guard = (
                _disabled_remote_backup_guard(store, ledger)
                if os.path.lexists(ledger.path)
                else None
            )
            return RemoteChatComposition(
                ConversationTurnService(coordinator, activity_signal=activity_signal), None, guard,
                startup_configuration_revision=configuration.revision,
            )
        raise RemoteChatCompositionError(
            "Enabled Remote Chat is missing a required local application service."
        )

    memory_store.initialize()

    search_handler = RemoteSearchHandler(
        web_search,
        source_retrieval,
        capability_settings,
        clock=time.monotonic,
    )
    service_holder: list[RemoteChatService] = []
    termination_handler = RemoteSelfTerminationHandler(
        lambda request: service_holder[0].terminate_self(request)
    )
    handlers = remote_handlers(
        search=search_handler,
        reminders=RemoteUpcomingReminderHandler(task_reminders),
        terminate_self=termination_handler,
    )
    turns = ConversationTurnService(
        coordinator, remote_handlers=handlers, activity_signal=activity_signal
    )

    def build_session(history: Sequence[ChatMessage]) -> ConversationSession:
        return ConversationSession(
            provider,
            initial_history=history,
            memory_store=memory_store,
            memory_warning_function=lambda _message: None,
            knowledge_registry=None,
            model_name=model_name,
            context_policy=context_policy,
            model_capacity=model_capacity,
            capability_awareness=_remote_capability_awareness,
        )

    make_ledger = ledger_factory or RemoteChatLedger
    make_transport = transport_factory or DiscordRemoteChannel
    ledger = make_ledger()
    ledger.initialize()
    binding = ledger.binding()
    durable_dm_channel_id = None if binding is None else binding[3]
    if (
        configuration.dm_channel_id is not None
        and durable_dm_channel_id is not None
        and configuration.dm_channel_id != durable_dm_channel_id
    ):
        raise RemoteChatCompositionError(
            "Remote Chat configuration conflicts with its durable DM binding."
        )
    adapter_configuration = (
        configuration
        if configuration.dm_channel_id is not None or durable_dm_channel_id is None
        else replace(configuration, dm_channel_id=durable_dm_channel_id)
    )
    service = RemoteChatService(
        configuration=configuration,
        ledger=ledger,
        transport=make_transport(adapter_configuration),
        chats=chat_service,
        conversation_turns=turns,
        session=build_session(()),
        session_factory=build_session,
        provider_name=provider_name,
        model_name=model_name,
        config_store=store,
        search_handler=search_handler,
        activity_signal=activity_signal,
    )
    service_holder.append(service)
    return RemoteChatComposition(
        turns, service, service.backup_guard,
        startup_configuration_revision=configuration.revision,
    )


def _disabled_remote_backup_guard(
    store: RemoteChatConfigStore,
    ledger: RemoteChatLedger,
) -> Callable[[], AbstractContextManager[None]]:
    @contextmanager
    def guard() -> Iterator[None]:
        with store.generation_guard() as current:
            if current.effective_enabled:
                raise RemoteChatCompositionError(
                    "Remote Chat became enabled before backup quiescence."
                )
            ledger.initialize()
            if ledger.processing_records() or any(
                chunk.state == "sending" for chunk in ledger.outbound_chunks()
            ):
                raise RemoteChatCompositionError(
                    "Remote Chat has unfinished work; backup was not published."
                )
            ledger.checkpoint()
            yield

    return guard


def _unconfigured_remote_backup_guard(
    ledger: RemoteChatLedger,
) -> Callable[[], AbstractContextManager[None]]:
    """Protect an inactive historical ledger when no connector can be composed."""

    @contextmanager
    def guard() -> Iterator[None]:
        ledger.initialize()
        if ledger.processing_records() or any(
            chunk.state == "sending" for chunk in ledger.outbound_chunks()
        ):
            raise RemoteChatCompositionError(
                "Remote Chat has unfinished work; backup was not published."
            )
        ledger.checkpoint()
        yield

    return guard


def _remote_capability_awareness() -> str:
    return (
        "REMOTE CHAT CAPABILITIES: ordinary conversation and bounded curated "
        "Memory context are available. Search and weather require configured "
        "Search plus one-use consent. Upcoming reminders are read-only. "
        "The exact owner-DM termination command may only reduce Remote Chat "
        "authority by disabling its own connector. "
        "execution, mutations, Knowledge contents, Finance, Projects, host "
        "telemetry, Settings, services, backups, and local proposal confirmation "
        "are unavailable from Remote Chat."
    )
