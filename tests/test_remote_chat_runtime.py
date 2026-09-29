from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tori.backups import BackupService, BackupBusyError
from tori.chats import ChatService
from tori.checkpoints import CheckpointStore
from tori.context import ContextPolicy
from tori.discord_remote_adapter import DiscordRemoteChannel, DiscordRemoteAdapterError
from tori.conversation_archive import ConversationArchiveStore
from tori.memory import SQLiteMemoryStore
from tori.knowledge import KnowledgeRegistry
from tori.operation_coordinator import OperationCoordinator
from tori.providers import ChatResponse, ModelProvider
from tori.remote_chat import RemoteChatDisabledError
from tori.remote_chat_config import RemoteChatConfigStore, RemoteConfigError
from tori.remote_chat_ledger import RemoteChatLedger
from tori.remote_chat_runtime import RemoteChatWebControl, compose_remote_chat
from tori.remote_chat_transport import FakeRemoteChannel, RemoteInboundEnvelope
from tori.task_reminder_application import TaskReminderApplicationService
from tori.tasks import SQLiteOperationalStore
from tori.web import run_web_server


class _Provider(ModelProvider):
    def __init__(self) -> None:
        self.requests: list[tuple[object, ...]] = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("A composed Discord reply.", "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def _enable(store: RemoteChatConfigStore, *, dm: str | None = None) -> None:
    store.initialize()
    store.configure_identity(
        connector_id="discord-owner-dm",
        application_id="100000000000000001",
        bot_user_id="100000000000000002",
        installation_id="100000000000000003",
        owner_user_id="100000000000000004",
        dm_channel_id=dm,
    )
    store.set_token("synthetic-token-never-real")
    store.set_administrator_ceiling(True)
    store.set_enabled(True)


class RemoteChatCompositionTests(unittest.TestCase):
    def test_real_disabled_adapter_composes_without_connecting_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            store = RemoteChatConfigStore(root / "private")
            _enable(store)
            store.set_enabled(False)
            ledger = RemoteChatLedger(project / "runtime/remote_chat/tori_remote_chat.db")
            ledger.initialize()
            memory, chats, reminders = self._dependencies(project)
            with patch("tori.discord_remote_adapter._HikariDiscordClient") as client:
                composition = compose_remote_chat(
                    coordinator=OperationCoordinator(), provider=_Provider(),
                    memory_store=memory, chat_service=chats, task_reminders=reminders,
                    provider_name="test-provider", model_name="test-model",
                    web_search=None, source_retrieval=None, capability_settings=None,
                    context_policy=ContextPolicy(), config_store=store,
                    ledger_factory=lambda: ledger,
                )
                self.assertIsNotNone(composition.service)
                self.assertIsNotNone(composition.backup_guard)
                control = RemoteChatWebControl(store, composition.service)
                self.assertFalse(control.status_document()["restart_required"])
                self.assertEqual(control.status_document()["state"], "disabled")
                with self.assertRaises(RemoteChatDisabledError):
                    composition.service.start()
                uncoordinated = BackupService(project_root=project, backup_root=root / "backups")
                with self.assertRaises(BackupBusyError):
                    uncoordinated.create_backup()
                uncoordinated.configure_remote_chat_guard(composition.backup_guard)
                result = uncoordinated.create_backup()
                payload = uncoordinated.verified_payload(result.identifier)
                self.assertTrue((payload / "runtime/remote_chat/tori_remote_chat.db").is_file())
                self.assertFalse(store.load_if_present().enabled)
                client.assert_not_called()

    def test_real_adapter_still_rejects_incomplete_or_unpermitted_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RemoteChatConfigStore(Path(temporary) / "private")
            _enable(store)
            configuration = store.load_if_present()
            for invalid in (
                replace(configuration, administrator_permitted=False),
                replace(configuration, token=None),
            ):
                with self.assertRaises(DiscordRemoteAdapterError):
                    DiscordRemoteChannel(invalid)

    def test_web_registers_real_disabled_guard_and_setup_failure_still_blocks_backup(self) -> None:
        class Server:
            def serve_forever(self):
                pass

            def server_close(self):
                pass

        def broken_transport(configuration):
            raise DiscordRemoteAdapterError("synthetic private setup detail")

        for factory in (None, broken_transport):
            with self.subTest(valid_startup=factory is None), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project = root / "project"
                project.mkdir()
                store = RemoteChatConfigStore(root / "private")
                _enable(store)
                store.set_enabled(False)
                ledger = RemoteChatLedger(project / "runtime/remote_chat/tori_remote_chat.db")
                ledger.initialize()
                backup = BackupService(project_root=project, backup_root=root / "backups")
                output = []
                with patch("tori.web.create_web_server", return_value=Server()), patch(
                    "tori.discord_remote_adapter._HikariDiscordClient"
                ) as client:
                    code = run_web_server(
                        _Provider(), port=8765,
                        checkpoint_store=CheckpointStore(project / "checkpoints"),
                        memory_store=SQLiteMemoryStore(project / "memory.db"),
                        knowledge_registry=KnowledgeRegistry(project / "knowledge"),
                        provider_name="test-provider", model_name="test-model",
                        chat_service=ChatService(ConversationArchiveStore(project / "conversations.db")),
                        operational_store=SQLiteOperationalStore(project / "tasks.db"),
                        remote_chat_config_store=store,
                        remote_chat_ledger_factory=lambda: ledger,
                        remote_chat_transport_factory=factory,
                        backup_service=backup, output_function=output.append,
                    )
                    self.assertEqual(code, 0)
                    client.assert_not_called()
                self.assertNotIn("synthetic private setup detail", "\n".join(output))
                if factory is None:
                    result = backup.create_backup()
                    self.assertTrue(backup.verified_payload(result.identifier).is_dir())
                else:
                    with self.assertRaises(BackupBusyError):
                        backup.create_backup()

    def _dependencies(self, root: Path):  # type: ignore[no-untyped-def]
        memory = SQLiteMemoryStore(root / "memory.db")
        chats = ChatService(ConversationArchiveStore(root / "conversations.db"))
        chats.initialize()
        operations = SQLiteOperationalStore(root / "tasks.db")
        operations.initialize()
        return memory, chats, TaskReminderApplicationService(operations)

    def test_absent_configuration_is_default_off_and_noncreating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            memory, chats, reminders = self._dependencies(root)
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=None,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=RemoteChatConfigStore(private),
                ledger_factory=lambda: RemoteChatLedger(root / "remote.db"),
            )
            self.assertIsNone(composition.service)
            self.assertFalse(private.exists())
            self.assertFalse((root / "remote.db").exists())

    def test_unconfigured_existing_ledger_has_coherent_backup_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            ledger = RemoteChatLedger(root / "remote.db")
            ledger.initialize()
            memory, chats, reminders = self._dependencies(root)

            composition = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=None,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=store,
                ledger_factory=lambda: ledger,
            )

            self.assertFalse(store.directory.exists())
            self.assertIsNone(composition.service)
            self.assertIsNotNone(composition.backup_guard)
            assert composition.backup_guard is not None
            with composition.backup_guard():
                self.assertEqual(ledger.processing_records(), ())

    def test_enabled_composition_uses_normal_turn_path_and_durable_dm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store)
            memory, chats, reminders = self._dependencies(root)
            provider = _Provider()
            transport = FakeRemoteChannel()
            transport._outbound_text_limit = 2_000
            received_configurations = []
            ledger = RemoteChatLedger(root / "remote.db")
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=provider,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=store,
                ledger_factory=lambda: ledger,
                transport_factory=lambda config: (
                    received_configurations.append(config) or transport
                ),
            )
            self.assertIsNotNone(composition.service)
            service = composition.service
            assert service is not None
            service.initialize()
            service.start()
            self.addCleanup(
                lambda: service.shutdown() if service.status().worker_alive else None
            )
            transport.emit(
                RemoteInboundEnvelope(
                    transport="discord_remote",
                    connector_id="discord-owner-dm",
                    external_message_id="100000000000000006",
                    external_actor_id="100000000000000004",
                    external_conversation_id="100000000000000005",
                    application_id="100000000000000001",
                    bot_user_id="100000000000000002",
                    installation_id="100000000000000003",
                    received_at="2026-09-08T12:00:00Z",
                    text="Hello Tori",
                )
            )
            self.assertTrue(service.wait_idle())
            service.shutdown()
            self.assertEqual(transport.sent[0].text, "A composed Discord reply.")
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(ledger.binding()[3], "100000000000000005")

            _enable_after_disable = store.set_enabled(False)
            self.assertFalse(_enable_after_disable.enabled)
            store.set_enabled(True)
            restarted_transport = FakeRemoteChannel()
            restarted = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=provider,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=store,
                ledger_factory=lambda: ledger,
                transport_factory=lambda config: (
                    received_configurations.append(config) or restarted_transport
                ),
            )
            self.assertIsNotNone(restarted.service)
            self.assertEqual(
                received_configurations[-1].dm_channel_id,
                "100000000000000005",
            )

    def test_self_termination_survives_restart_and_only_local_reenable_reconnects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store, dm="100000000000000005")
            memory, chats, reminders = self._dependencies(root)
            provider = _Provider()
            ledger = RemoteChatLedger(root / "remote.db")
            first_transport = FakeRemoteChannel()
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=provider,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=store,
                ledger_factory=lambda: ledger,
                transport_factory=lambda _config: first_transport,
            )
            service = composition.service
            assert service is not None
            service.initialize()
            service.start()
            first_transport.emit(RemoteInboundEnvelope(
                transport="discord_remote",
                connector_id="discord-owner-dm",
                external_message_id="100000000000000006",
                external_actor_id="100000000000000004",
                external_conversation_id="100000000000000005",
                application_id="100000000000000001",
                bot_user_id="100000000000000002",
                installation_id="100000000000000003",
                received_at="2026-09-08T12:00:00Z",
                text="Terminate Discord connection now",
            ))
            self.assertTrue(service.wait_idle())
            for _ in range(100):
                if not service.status().worker_alive:
                    break
                threading.Event().wait(0.005)
            self.assertFalse(service.status().worker_alive)
            self.assertFalse(store.load().enabled)
            self.assertEqual(first_transport.status().value, "off")

            after_restart = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=None,
                memory_store=memory, chat_service=chats,
                task_reminders=reminders, provider_name="test-provider",
                model_name="test-model", web_search=None,
                source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: ledger,
            )
            self.assertIsNone(after_restart.service)

            store.set_enabled(True)
            second_transport = FakeRemoteChannel()
            reenabled = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=provider,
                memory_store=memory, chat_service=chats,
                task_reminders=reminders, provider_name="test-provider",
                model_name="test-model", web_search=None,
                source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: ledger,
                transport_factory=lambda _config: second_transport,
            )
            second = reenabled.service
            assert second is not None
            second.initialize()
            second.start()
            self.assertEqual(second_transport.status().value, "connected")
            second.shutdown()

    def test_web_control_stops_and_restarts_one_existing_connector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store, dm="100000000000000005")
            memory, chats, reminders = self._dependencies(root)
            transport = FakeRemoteChannel()
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=_Provider(),
                memory_store=memory, chat_service=chats,
                task_reminders=reminders, provider_name="test-provider",
                model_name="test-model", web_search=None,
                source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: RemoteChatLedger(root / "remote.db"),
                transport_factory=lambda _config: transport,
            )
            service = composition.service
            assert service is not None
            control = RemoteChatWebControl(
                store, service,
                startup_configuration_revision=composition.startup_configuration_revision,
            )
            control.set_enabled(True)
            connected = control.status_document()
            self.assertEqual(connected["state"], "connected")
            self.assertEqual(set(connected), {
                "configured", "administrator_permitted", "enabled",
                "effective_enabled", "configured_enabled", "state", "restart_required",
            })

            disabled = control.set_enabled(False)
            self.assertEqual(disabled["state"], "disabled")
            self.assertFalse(store.load().enabled)
            self.assertEqual(transport.status().value, "off")

            reconnected = control.set_enabled(True)
            self.assertEqual(reconnected["state"], "connected")
            self.assertTrue(store.load().enabled)
            self.assertEqual(transport.status().value, "connected")
            service.shutdown()

    def test_configured_prior_enable_starts_each_process_off_until_local_enable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store, dm="100000000000000005")
            saved = store.load()
            memory, chats, reminders = self._dependencies(root)
            first_transport = FakeRemoteChannel()
            first = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=_Provider(),
                memory_store=memory, chat_service=chats, task_reminders=reminders,
                provider_name="test-provider", model_name="test-model",
                web_search=None, source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: RemoteChatLedger(root / "remote.db"),
                transport_factory=lambda _config: first_transport,
            )
            assert first.service is not None
            control = RemoteChatWebControl(
                store, first.service,
                startup_configuration_revision=first.startup_configuration_revision,
            )
            self.assertEqual(control.status_document()["state"], "disabled")
            self.assertEqual(first_transport.status().value, "off")
            control.set_enabled(True)
            self.assertEqual(first_transport.status().value, "connected")
            control.set_enabled(False)
            self.assertEqual(first_transport.status().value, "off")
            # A local CLI enable is a new configuration revision after this
            # process began, so the running process may activate the session.
            store.set_enabled(True)
            control.refresh_local_enablement()
            self.assertEqual(first_transport.status().value, "connected")
            control.set_enabled(False)
            self.assertEqual(first_transport.status().value, "off")

            store.set_enabled(True)
            second_transport = FakeRemoteChannel()
            second = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=_Provider(),
                memory_store=memory, chat_service=chats, task_reminders=reminders,
                provider_name="test-provider", model_name="test-model",
                web_search=None, source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: RemoteChatLedger(root / "remote.db"),
                transport_factory=lambda _config: second_transport,
            )
            assert second.service is not None
            restarted = RemoteChatWebControl(
                store, second.service,
                startup_configuration_revision=second.startup_configuration_revision,
            )
            status = restarted.status_document()
            self.assertFalse(status["enabled"])
            self.assertFalse(status["effective_enabled"])
            self.assertEqual(status["state"], "disabled")
            self.assertTrue(status["configured_enabled"])
            self.assertEqual(store.load().token, saved.token)
            self.assertEqual(second_transport.status().value, "off")

    def test_worker_observing_local_disable_cannot_fence_past_authoritative_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store, dm="100000000000000005")
            memory, chats, reminders = self._dependencies(root)
            ledger = RemoteChatLedger(root / "remote.db")
            transport = FakeRemoteChannel()
            provider = _Provider()
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(), provider=provider,
                memory_store=memory, chat_service=chats, task_reminders=reminders,
                provider_name="test-provider", model_name="test-model",
                web_search=None, source_retrieval=None, capability_settings=None,
                context_policy=ContextPolicy(), config_store=store,
                ledger_factory=lambda: ledger,
                transport_factory=lambda _config: transport,
            )
            service = composition.service
            assert service is not None
            control = RemoteChatWebControl(
                store, service,
                startup_configuration_revision=composition.startup_configuration_revision,
            )
            checking = threading.Event()
            release_check = threading.Event()
            killed_fence = threading.Event()
            original_check = service._configuration_is_current
            failures: list[BaseException] = []

            def delayed_check() -> bool:
                checking.set()
                if not release_check.wait(3):
                    raise AssertionError("Worker was not released after local disable.")
                return original_check()

            def hook(phase: str) -> None:
                if phase == "kill_fence_published":
                    killed_fence.set()

            def disable() -> None:
                try:
                    control.set_enabled(False)
                except BaseException as exc:
                    failures.append(exc)

            prior_message = RemoteInboundEnvelope(
                transport="discord_remote", connector_id="discord-owner-dm",
                external_message_id="100000000000000006",
                external_actor_id="100000000000000004",
                external_conversation_id="100000000000000005",
                application_id="100000000000000001",
                bot_user_id="100000000000000002",
                installation_id="100000000000000003",
                received_at="2026-09-08T12:00:00Z", text="Hello from the prior session",
            )
            with patch.object(service, "_configuration_is_current", side_effect=delayed_check), \
                    patch.object(service, "_call_hook", side_effect=hook):
                try:
                    control.set_enabled(True)
                    self.assertTrue(checking.wait(3), "Worker did not enter the authority check.")
                    transport.emit(prior_message)
                    self.assertEqual(ledger.inbound_records()[0].state, "accepted")
                    worker = threading.Thread(target=disable)
                    worker.start()
                    try:
                        self.assertTrue(killed_fence.wait(3), "Local disable did not publish its fence.")
                    finally:
                        release_check.set()
                        worker.join(4)
                    self.assertFalse(worker.is_alive(), "Disable must join its former worker.")
                finally:
                    release_check.set()
            self.assertEqual(failures, [])
            disabled = store.load()
            self.assertFalse(disabled.enabled)
            self.assertEqual(transport.status().value, "off")
            self.assertEqual(ledger.inbound_records()[0].state, "cancelled")
            self.assertIsNone(ledger.inbound_records()[0].text)
            self.assertEqual(provider.requests, [])
            self.assertEqual(ledger.current_generation(), disabled.generation,
                             "a late old worker must not advance the ledger past configuration")
            store.set_enabled(True)  # Enable changes revision, not generation.
            control.refresh_local_enablement()
            self.assertEqual(ledger.current_generation(), store.load().generation)
            self.assertEqual(transport.status().value, "connected")
            transport.emit(prior_message)
            self.assertEqual(ledger.inbound_records()[0].state, "cancelled")
            self.assertEqual(provider.requests, [])
            transport.emit(replace(prior_message,
                                   external_message_id="100000000000000007",
                                   text="Hello from the new session"))
            self.assertTrue(service.wait_idle())
            self.assertEqual(len(provider.requests), 1)
            control.set_enabled(False)
            self.assertEqual(ledger.current_generation(), store.load().generation)
            self.assertEqual(transport.status().value, "off")

    def test_web_control_reports_a_startup_composition_failure_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RemoteChatConfigStore(Path(temporary) / "private")
            _enable(store)
            control = RemoteChatWebControl(store, None, setup_error=True)

            status = control.status_document()

            self.assertEqual(status["state"], "error")
            self.assertTrue(status["restart_required"])
            self.assertNotIn("token", status)

    def test_disabled_existing_ledger_has_coherent_backup_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            store.initialize()
            ledger = RemoteChatLedger(root / "remote.db")
            ledger.initialize()
            memory, chats, reminders = self._dependencies(root)
            composition = compose_remote_chat(
                coordinator=OperationCoordinator(),
                provider=None,
                memory_store=memory,
                chat_service=chats,
                task_reminders=reminders,
                provider_name="test-provider",
                model_name="test-model",
                web_search=None,
                source_retrieval=None,
                capability_settings=None,
                context_policy=ContextPolicy(),
                config_store=store,
                ledger_factory=lambda: ledger,
            )
            self.assertIsNotNone(composition.backup_guard)
            assert composition.backup_guard is not None
            with composition.backup_guard():
                self.assertEqual(ledger.processing_records(), ())

    def test_existing_configuration_without_its_lock_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            store.initialize()
            (store.directory / "connector.lock").unlink()
            memory, chats, reminders = self._dependencies(root)
            with self.assertRaises(RemoteConfigError):
                compose_remote_chat(
                    coordinator=OperationCoordinator(),
                    provider=None,
                    memory_store=memory,
                    chat_service=chats,
                    task_reminders=reminders,
                    provider_name="test-provider",
                    model_name="test-model",
                    web_search=None,
                    source_retrieval=None,
                    capability_settings=None,
                    context_policy=ContextPolicy(),
                    config_store=store,
                    ledger_factory=lambda: RemoteChatLedger(root / "remote.db"),
                )

    def test_web_lifecycle_starts_and_stops_the_injected_connector(self) -> None:
        class _Server:
            def __init__(self) -> None:
                self.closed = False

            def serve_forever(self) -> None:
                pass

            def server_close(self) -> None:
                self.closed = True

            def shutdown(self) -> None:
                pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = RemoteChatConfigStore(root / "private")
            _enable(store, dm="100000000000000005")
            transport = FakeRemoteChannel()
            server = _Server()
            output: list[str] = []
            chats = ChatService(ConversationArchiveStore(root / "conversations.db"))
            with patch("tori.web.create_web_server", return_value=server):
                code = run_web_server(
                    _Provider(),
                    port=8765,
                    checkpoint_store=CheckpointStore(root / "checkpoints"),
                    memory_store=SQLiteMemoryStore(root / "memory.db"),
                    knowledge_registry=KnowledgeRegistry(root / "knowledge"),
                    provider_name="test-provider",
                    model_name="test-model",
                    chat_service=chats,
                    operational_store=SQLiteOperationalStore(root / "tasks.db"),
                    remote_chat_config_store=store,
                    remote_chat_ledger_factory=lambda: RemoteChatLedger(
                        root / "remote.db"
                    ),
                    remote_chat_transport_factory=lambda _config: transport,
                    output_function=output.append,
                )
            self.assertEqual(code, 0)
            self.assertTrue(server.closed)
            self.assertEqual(transport.status().value, "off")
            self.assertIn("disabled until enabled locally", "\n".join(output))
            self.assertEqual(
                store.combined_status()["runtime_state"],
                "disabled",
            )


if __name__ == "__main__":
    unittest.main()
