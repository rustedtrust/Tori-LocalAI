from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import hikari

from tori.chats import ChatService
from tori.conversation import ConversationSession
from tori.conversation_application import ConversationTurnService
from tori.conversation_archive import ConversationArchiveStore
from tori.discord_remote_adapter import (
    DISCORD_GATEWAY_INTENTS,
    DISCORD_MESSAGE_TEXT_LIMIT,
    DiscordGatewayIdentity,
    DiscordGatewayMessage,
    DiscordMessageReceipt,
    DiscordPreparedMessage,
    DiscordPrivateChannel,
    DiscordRemoteAdapterError,
    DiscordRemoteChannel,
    _AmbiguousDiscordSendError,
    _DefiniteDiscordSendError,
    _HikariDiscordClient,
)
from tori.operation_coordinator import OperationCoordinator
from tori.providers import ChatResponse, ModelProvider
from tori.remote_chat import RemoteChatService
from tori.remote_chat_config import RemoteChatConfiguration
from tori.remote_chat_ledger import RemoteAdmissionConflict, RemoteChatLedger
from tori.remote_chat_transport import (
    RemoteDeliveryState,
    RemoteOutboundRequest,
    RemoteTransportState,
)


APPLICATION_ID = "100000000000000001"
BOT_ID = "100000000000000002"
GUILD_ID = "100000000000000003"
OWNER_ID = "100000000000000004"
DM_ID = "100000000000000005"
MESSAGE_ID = "100000000000000006"


def configuration(**changes: object) -> RemoteChatConfiguration:
    values: dict[str, object] = {
        "administrator_permitted": True,
        "enabled": True,
        "connector_id": "discord-owner-dm",
        "application_id": APPLICATION_ID,
        "bot_user_id": BOT_ID,
        "installation_id": GUILD_ID,
        "owner_user_id": OWNER_ID,
        "dm_channel_id": DM_ID,
        "token": "synthetic-token-never-real",
    }
    values.update(changes)
    return RemoteChatConfiguration(**values)  # type: ignore[arg-type]


def gateway_message(**changes: object) -> DiscordGatewayMessage:
    values: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "actor_id": OWNER_ID,
        "channel_id": DM_ID,
        "received_at": "2026-09-05T12:00:00Z",
        "text": "Hello Tori",
    }
    values.update(changes)
    return DiscordGatewayMessage(**values)  # type: ignore[arg-type]


def outbound(text: str = "Hello from Tori") -> RemoteOutboundRequest:
    return RemoteOutboundRequest(
        connector_id="discord-owner-dm",
        external_conversation_id=DM_ID,
        application_request_id="outbound-request-1",
        text=text,
    )


class FakeDiscordClient:
    def __init__(self, _token: str) -> None:
        self.identity = DiscordGatewayIdentity(
            APPLICATION_ID, BOT_ID, (GUILD_ID,)
        )
        self.channel = DiscordPrivateChannel(DM_ID, "one_to_one_dm", OWNER_ID)
        self.receiver = None
        self.connection_observer = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.join_future: asyncio.Future[None] | None = None
        self.closed = threading.Event()
        self.created: list[DiscordPreparedMessage] = []
        self.prepare_started = threading.Event()
        self.send_entered = threading.Event()
        self.pause_preparation = False
        self.pause_completion = False
        self.prepare_gate: asyncio.Event | None = None
        self.completion_gate: asyncio.Event | None = None
        self.start_error: BaseException | None = None
        self.prepare_error: BaseException | None = None
        self.send_error: BaseException | None = None
        self.receipt_nonce: str | None = None

    def set_connection_observer(self, observer):  # type: ignore[no-untyped-def]
        self.connection_observer = observer

    async def start(self, receiver):  # type: ignore[no-untyped-def]
        if self.start_error is not None:
            raise self.start_error
        self.receiver = receiver
        self.loop = asyncio.get_running_loop()
        self.join_future = self.loop.create_future()
        self.prepare_gate = asyncio.Event()
        self.completion_gate = asyncio.Event()
        if not self.pause_preparation:
            self.prepare_gate.set()
        if not self.pause_completion:
            self.completion_gate.set()
        return self.identity

    async def close(self) -> None:
        self.closed.set()
        assert self.prepare_gate is not None
        assert self.completion_gate is not None
        assert self.join_future is not None
        self.prepare_gate.set()
        self.completion_gate.set()
        if not self.join_future.done():
            self.join_future.set_result(None)

    async def join(self) -> None:
        assert self.join_future is not None
        await self.join_future

    async def resolve_private_channel(self, channel_id: str) -> DiscordPrivateChannel:
        if channel_id != self.channel.channel_id:
            return DiscordPrivateChannel(channel_id, "unsupported", None)
        return self.channel

    async def prepare_message(
        self, message: DiscordPreparedMessage
    ) -> DiscordPreparedMessage:
        self.prepare_started.set()
        assert self.prepare_gate is not None
        await self.prepare_gate.wait()
        if self.prepare_error is not None:
            raise self.prepare_error
        return message

    async def create_message(
        self, message: DiscordPreparedMessage
    ) -> DiscordMessageReceipt:
        self.created.append(message)
        self.send_entered.set()
        assert self.completion_gate is not None
        await self.completion_gate.wait()
        if self.send_error is not None:
            raise self.send_error
        return DiscordMessageReceipt(
            str(int(MESSAGE_ID) + len(self.created)),
            message.nonce if self.receipt_nonce is None else self.receipt_nonce,
        )

    def allow_preparation(self) -> None:
        assert self.loop is not None and self.prepare_gate is not None
        self.loop.call_soon_threadsafe(self.prepare_gate.set)

    def allow_completion(self) -> None:
        assert self.loop is not None and self.completion_gate is not None
        self.loop.call_soon_threadsafe(self.completion_gate.set)

    def emit(self, event: DiscordGatewayMessage) -> None:
        assert self.loop is not None and self.receiver is not None
        asyncio.run_coroutine_threadsafe(self.receiver(event), self.loop).result(2)

    def connection(self, connected: bool) -> None:
        assert self.loop is not None and self.connection_observer is not None
        self.loop.call_soon_threadsafe(self.connection_observer, connected)


class DiscordRemoteAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeDiscordClient("unused")
        self.received = []
        self.adapter = DiscordRemoteChannel(
            configuration(), client_factory=lambda _token: self.client
        )
        self.adapter.start(self.received.append)

    def tearDown(self) -> None:
        if self.adapter.status() is not RemoteTransportState.OFF:
            self.adapter.stop()

    def test_minimal_intent_and_discord_physical_limit(self) -> None:
        self.assertEqual(DISCORD_GATEWAY_INTENTS, hikari.Intents.DM_MESSAGES)
        self.assertEqual(self.adapter.outbound_text_limit, 2_000)
        self.assertEqual(DISCORD_MESSAGE_TEXT_LIMIT, 2_000)

    def test_exact_owner_dm_is_normalized(self) -> None:
        self.client.emit(gateway_message())
        self.assertEqual(len(self.received), 1)
        envelope = self.received[0]
        self.assertEqual(envelope.transport, "discord_remote")
        self.assertEqual(envelope.external_actor_id, OWNER_ID)
        self.assertEqual(envelope.external_conversation_id, DM_ID)
        self.assertEqual(envelope.application_id, APPLICATION_ID)

    def test_wrong_user_guild_bot_and_unsupported_payloads_are_denied(self) -> None:
        for event in (
            gateway_message(actor_id="100000000000000099"),
            gateway_message(guild_id=GUILD_ID),
            gateway_message(author_is_bot=True),
            gateway_message(author_is_system=True),
            gateway_message(unsupported_content=True),
            gateway_message(message_type=19),
        ):
            self.client.emit(event)
        self.assertEqual(self.received, [])

    def test_guild_termination_phrase_never_reaches_application_admission(self) -> None:
        self.client.emit(gateway_message(
            guild_id=GUILD_ID,
            text="Terminate Discord connection now",
        ))
        self.assertEqual(self.received, [])

    def test_group_dm_and_wrong_recipient_are_denied(self) -> None:
        self.client.channel = DiscordPrivateChannel(DM_ID, "group_dm", None)
        self.adapter.stop()
        self.adapter = DiscordRemoteChannel(
            configuration(dm_channel_id=None),
            client_factory=lambda _token: self.client,
        )
        self.adapter.start(self.received.append)
        self.client.emit(gateway_message())
        self.assertEqual(self.received, [])

    def test_send_orders_entry_after_preparation_and_suppresses_mentions(self) -> None:
        observed = []
        attempt = self.adapter.begin_send(
            outbound(), lambda: observed.append("authorized")
        )
        result = attempt.wait()
        self.assertEqual(observed, ["authorized"])
        self.assertEqual(result.state, RemoteDeliveryState.ACKNOWLEDGED)
        prepared = self.client.created[0]
        self.assertLessEqual(len(prepared.nonce), 25)
        self.assertFalse(prepared.mentions_everyone)
        self.assertFalse(prepared.mentions_reply)
        self.assertFalse(prepared.user_mentions)
        self.assertFalse(prepared.role_mentions)

    def test_disconnect_and_reconnect_are_truthful(self) -> None:
        self.client.connection(False)
        for _ in range(100):
            if self.adapter.status() is RemoteTransportState.CONNECTING:
                break
            threading.Event().wait(.005)
        self.assertEqual(self.adapter.status(), RemoteTransportState.CONNECTING)
        self.client.connection(True)
        for _ in range(100):
            if self.adapter.status() is RemoteTransportState.CONNECTED:
                break
            threading.Event().wait(.005)
        self.assertEqual(self.adapter.status(), RemoteTransportState.CONNECTED)

    def test_disconnect_before_send_entry_prevents_authorization_and_send(self) -> None:
        self.adapter.stop()
        self.client = FakeDiscordClient("unused")
        self.client.pause_preparation = True
        self.adapter = DiscordRemoteChannel(
            configuration(), client_factory=lambda _token: self.client
        )
        self.adapter.start(self.received.append)
        authorized: list[bool] = []
        failures: list[BaseException] = []

        def deliver() -> None:
            try:
                self.adapter.begin_send(
                    outbound(), lambda: authorized.append(True)
                )
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=deliver, daemon=False)
        worker.start()
        self.assertTrue(self.client.prepare_started.wait(2))
        self.client.connection(False)
        for _ in range(100):
            if self.adapter.status() is RemoteTransportState.CONNECTING:
                break
            threading.Event().wait(0.005)
        self.client.allow_preparation()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(authorized, [])
        self.assertEqual(self.client.created, [])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], DiscordRemoteAdapterError)

    def test_authentication_and_identity_failures_are_redacted(self) -> None:
        self.adapter.stop()
        self.client = FakeDiscordClient("unused")
        self.client.start_error = RuntimeError("secret-token-value")
        self.adapter = DiscordRemoteChannel(
            configuration(token="secret-token-value"),
            client_factory=lambda _token: self.client,
        )
        with self.assertRaises(DiscordRemoteAdapterError) as captured:
            self.adapter.start(self.received.append)
        self.assertNotIn("secret-token-value", str(captured.exception))
        self.assertEqual(self.adapter.status(), RemoteTransportState.ERROR)

    def test_changed_gateway_replay_is_left_to_durable_application_check(self) -> None:
        self.client.emit(gateway_message())
        self.client.emit(gateway_message(text="changed"))
        self.assertEqual([item.text for item in self.received], ["Hello Tori", "changed"])

    def test_interruption_after_send_entry_is_ambiguous(self) -> None:
        self.client.pause_completion = True
        self.adapter.stop()
        self.client = FakeDiscordClient("unused")
        self.client.pause_completion = True
        self.adapter = DiscordRemoteChannel(
            configuration(), client_factory=lambda _token: self.client
        )
        self.adapter.start(self.received.append)
        result: list[object] = []

        def deliver() -> None:
            attempt = self.adapter.begin_send(outbound(), lambda: None)
            result.append(attempt.wait())

        worker = threading.Thread(target=deliver, daemon=False)
        worker.start()
        self.assertTrue(self.client.send_entered.wait(2))
        self.adapter.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0].state, RemoteDeliveryState.AMBIGUOUS)


class _Provider(ModelProvider):
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse(self.answer, "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class DiscordRemoteCoreIntegrationTests(unittest.TestCase):
    def test_real_adapter_limit_drives_durable_ordered_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = FakeDiscordClient("unused")
            adapter = DiscordRemoteChannel(
                configuration(), client_factory=lambda _token: client
            )
            provider = _Provider("A" * 4_000)
            ledger = RemoteChatLedger(root / "runtime/remote_chat/ledger.db")
            chats = ChatService(
                ConversationArchiveStore(root / "runtime/conversations/chats.db")
            )
            turns = ConversationTurnService(OperationCoordinator())
            service = RemoteChatService(
                configuration=configuration(),
                ledger=ledger,
                transport=adapter,
                chats=chats,
                conversation_turns=turns,
                session=ConversationSession(provider),
                session_factory=lambda history: ConversationSession(
                    provider, initial_history=history
                ),
                provider_name="test-provider",
                model_name="test-model",
            )
            service.initialize()
            service.start()
            try:
                client.emit(gateway_message())
                self.assertTrue(service.wait_idle())
                self.assertEqual([len(item.text) for item in client.created], [2_000, 2_000])
                chunks = ledger.outbound_chunks()
                self.assertEqual([item.chunk_index for item in chunks], [0, 1])
                self.assertEqual(
                    [item.state for item in chunks],
                    ["delivered_acknowledged", "delivered_acknowledged"],
                )
            finally:
                service.shutdown()


class _GuildIterator:
    def __init__(self, guilds):  # type: ignore[no-untyped-def]
        self.guilds = guilds

    def limit(self, count: int):  # type: ignore[no-untyped-def]
        async def collect():
            return self.guilds[:count]

        return collect()


class _HikariRestFake:
    def __init__(self) -> None:
        self.created = []
        self.send_error = None

    async def fetch_my_user(self):  # type: ignore[no-untyped-def]
        return type("User", (), {"id": int(BOT_ID)})()

    async def fetch_application(self):  # type: ignore[no-untyped-def]
        return type("Application", (), {"id": int(APPLICATION_ID)})()

    def fetch_my_guilds(self):  # type: ignore[no-untyped-def]
        guild = type("Guild", (), {"id": int(GUILD_ID)})()
        return _GuildIterator([guild])

    async def create_message(self, channel_id, text, **kwargs):  # type: ignore[no-untyped-def]
        self.created.append((channel_id, text, kwargs))
        if self.send_error is not None:
            raise self.send_error
        return type("Message", (), {"id": int(MESSAGE_ID), "nonce": kwargs["nonce"]})()


class _HikariBotFake:
    def __init__(self) -> None:
        self.rest = _HikariRestFake()
        self.is_alive = False
        self.subscriptions = []

    def subscribe(self, event_type, callback) -> None:  # type: ignore[no-untyped-def]
        self.subscriptions.append((event_type, callback))

    async def start(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.is_alive = True

    async def close(self) -> None:
        self.is_alive = False

    async def join(self) -> None:
        return None


class HikariClientBoundaryTests(unittest.TestCase):
    def test_hikari_is_minimal_and_send_errors_are_normalized(self) -> None:
        bot = _HikariBotFake()

        async def exercise() -> None:
            with patch(
                "tori.discord_remote_adapter.hikari.GatewayBot", return_value=bot
            ) as constructor:
                client = _HikariDiscordClient("fake-token-never-real")
                identity = await client.start(lambda _message: asyncio.sleep(0))
                self.assertEqual(
                    identity,
                    DiscordGatewayIdentity(APPLICATION_ID, BOT_ID, (GUILD_ID,)),
                )
                arguments = constructor.call_args.kwargs
                self.assertEqual(arguments["intents"], hikari.Intents.DM_MESSAGES)
                self.assertFalse(arguments["auto_chunk_members"])
                self.assertEqual(arguments["cache_settings"].components, 0)
                prepared = DiscordPreparedMessage(DM_ID, "reply", "nonce")
                await client.create_message(prepared)
                sent = bot.rest.created[0][2]
                self.assertEqual(
                    {
                        "mentions_everyone": sent["mentions_everyone"],
                        "mentions_reply": sent["mentions_reply"],
                        "user_mentions": sent["user_mentions"],
                        "role_mentions": sent["role_mentions"],
                    },
                    {
                        "mentions_everyone": False,
                        "mentions_reply": False,
                        "user_mentions": False,
                        "role_mentions": False,
                    },
                )
                bot.rest.send_error = RuntimeError("secret-token-value")
                with self.assertRaises(_AmbiguousDiscordSendError) as captured:
                    await client.create_message(prepared)
                self.assertNotIn("secret-token-value", str(captured.exception))
                await client.close()

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
