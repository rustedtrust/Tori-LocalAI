"""Hikari-backed Discord transport for the Remote Chat application port.

All Hikari values and lifecycle mechanics remain in this module.  The public
adapter emits and accepts only the transport-neutral Remote Chat values.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import threading
from typing import Protocol

import hikari

from .remote_chat_config import RemoteChatConfiguration
from .operator_observability import operator_event, operator_failure
from .remote_chat_transport import (
    MAX_REMOTE_TEXT_CHARACTERS,
    InboundReceiver,
    RemoteChannelPort,
    RemoteDeliveryState,
    RemoteInboundEnvelope,
    RemoteOutboundRequest,
    RemoteOutboundResult,
    RemoteSendAttempt,
    RemoteTransportState,
    SendEntryAuthorizer,
)


DISCORD_MESSAGE_TEXT_LIMIT = 2_000
DISCORD_NONCE_LIMIT = 25
DISCORD_GATEWAY_INTENTS = hikari.Intents.DM_MESSAGES
DISCORD_MAX_RATE_LIMIT_SECONDS = 30.0
DISCORD_MAX_SERVER_RETRIES = 1


class DiscordRemoteAdapterError(RuntimeError):
    """Safe adapter failure that never incorporates an SDK exception string."""

    code = "discord_transport_error"


class _DefiniteDiscordSendError(RuntimeError):
    def __init__(self, code: str, *, fatal: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.fatal = fatal


class _AmbiguousDiscordSendError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DiscordGatewayIdentity:
    application_id: str
    bot_user_id: str
    installation_guild_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscordGatewayMessage:
    message_id: str
    actor_id: str
    channel_id: str
    received_at: str
    text: str | None
    guild_id: str | None = None
    author_is_bot: bool = False
    author_is_system: bool = False
    webhook_id: str | None = None
    message_type: int = 0
    unsupported_content: bool = False


@dataclass(frozen=True, slots=True)
class DiscordPrivateChannel:
    channel_id: str
    kind: str
    recipient_id: str | None


@dataclass(frozen=True, slots=True)
class DiscordPreparedMessage:
    channel_id: str
    text: str
    nonce: str
    mentions_everyone: bool = False
    mentions_reply: bool = False
    user_mentions: bool = False
    role_mentions: bool = False


@dataclass(frozen=True, slots=True)
class DiscordMessageReceipt:
    message_id: str
    nonce: str | None


GatewayMessageReceiver = Callable[[DiscordGatewayMessage], Awaitable[None]]


class _DiscordClientPort(Protocol):
    async def start(self, receiver: GatewayMessageReceiver) -> DiscordGatewayIdentity: ...

    async def close(self) -> None: ...

    async def join(self) -> None: ...

    async def resolve_private_channel(self, channel_id: str) -> DiscordPrivateChannel: ...

    async def prepare_message(self, message: DiscordPreparedMessage) -> DiscordPreparedMessage: ...

    async def create_message(self, message: DiscordPreparedMessage) -> DiscordMessageReceipt: ...


DiscordClientFactory = Callable[[str], _DiscordClientPort]


class _DiscordSendAttempt(RemoteSendAttempt):
    def __init__(self) -> None:
        self._boundary = threading.Event()
        self._authorized = False
        self._boundary_error: BaseException | None = None
        self._result: Future[RemoteOutboundResult] = Future()

    @property
    def boundary_resolved(self) -> bool:
        return self._boundary.is_set()

    def authorized(self) -> None:
        self._authorized = True
        self._boundary.set()

    def rejected(self, error: BaseException) -> None:
        if self._boundary.is_set():
            return
        self._boundary_error = error
        self._boundary.set()
        if not self._result.done():
            self._result.set_exception(error)

    def finish(self, result: RemoteOutboundResult) -> None:
        if not self._result.done():
            self._result.set_result(result)

    def fail(self, error: BaseException) -> None:
        if not self._result.done():
            self._result.set_exception(error)

    def wait_for_boundary(self) -> None:
        self._boundary.wait()
        if self._boundary_error is not None:
            raise self._boundary_error
        if not self._authorized:
            raise DiscordRemoteAdapterError(
                "Discord send ended without an authorized entry boundary."
            )

    def wait(self) -> RemoteOutboundResult:
        return self._result.result()


class DiscordRemoteChannel(RemoteChannelPort):
    """One-owner, private-DM-only Discord Gateway transport."""

    def __init__(
        self,
        configuration: RemoteChatConfiguration,
        *,
        client_factory: DiscordClientFactory | None = None,
        startup_timeout_seconds: float = 30.0,
        shutdown_timeout_seconds: float = 15.0,
    ) -> None:
        # Construction is inert: the process starts Off and the application
        # owns live enablement/generation checks before calling start(). Requiring
        # enabled here prevents a valid disabled connector (and its backup guard)
        # from being composed at all.
        if not (configuration.complete and configuration.administrator_permitted):
            raise DiscordRemoteAdapterError(
                "Discord Remote Chat requires a complete administrator-permitted configuration."
            )
        assert configuration.token is not None
        assert configuration.connector_id is not None
        self._connector_id = configuration.connector_id
        self._application_id = _discord_id(configuration.application_id, "application")
        self._bot_user_id = _discord_id(configuration.bot_user_id, "bot user")
        self._installation_id = _discord_id(
            configuration.installation_id, "installation guild"
        )
        self._owner_user_id = _discord_id(configuration.owner_user_id, "owner user")
        self._configured_dm_channel_id = (
            None
            if configuration.dm_channel_id is None
            else _discord_id(configuration.dm_channel_id, "DM channel")
        )
        self._token = configuration.token
        self._client_factory = client_factory or _HikariDiscordClient
        self._startup_timeout = _positive_timeout(
            startup_timeout_seconds, "startup"
        )
        self._shutdown_timeout = _positive_timeout(
            shutdown_timeout_seconds, "shutdown"
        )
        self._lock = threading.RLock()
        self._state = RemoteTransportState.OFF
        self._receiver: InboundReceiver | None = None
        self._verified_dm_channel_id: str | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: _DiscordClientPort | None = None
        self._startup_complete = threading.Event()
        self._startup_error = False
        self._stopping = False
        self._identity_verified = False
        self._runner_futures: set[Future[object]] = set()

    @property
    def outbound_text_limit(self) -> int:
        return DISCORD_MESSAGE_TEXT_LIMIT

    def status(self) -> RemoteTransportState:
        with self._lock:
            return self._state

    def start(self, receiver: InboundReceiver) -> None:
        if not callable(receiver):
            raise TypeError("Discord inbound receiver must be callable.")
        with self._lock:
            self._join_finished_thread()
            if self._state is not RemoteTransportState.OFF or self._thread is not None:
                raise DiscordRemoteAdapterError(
                    "Discord Remote Chat transport is already started."
                )
            self._state = RemoteTransportState.CONNECTING
            operator_event("remote_chat.transport.connecting", transport="discord")
            self._receiver = receiver
            self._verified_dm_channel_id = None
            self._identity_verified = False
            self._startup_complete.clear()
            self._startup_error = False
            self._stopping = False
            self._thread = threading.Thread(
                target=self._thread_main,
                name="tori-discord-gateway",
                daemon=False,
            )
            self._thread.start()
        if not self._startup_complete.wait(self._startup_timeout):
            self._fail_startup()
            raise DiscordRemoteAdapterError(
                "Discord Remote Chat connection timed out."
            )
        with self._lock:
            failed = self._startup_error or self._state is not RemoteTransportState.CONNECTED
        if failed:
            self.stop()
            self._mark_error()
            raise DiscordRemoteAdapterError(
                "Discord Remote Chat could not authenticate and verify its configuration."
            )
        operator_event("remote_chat.transport.connected", transport="discord")

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            loop = self._loop
            client = self._client
            if thread is None:
                self._receiver = None
                if self._state is not RemoteTransportState.ERROR:
                    self._state = RemoteTransportState.OFF
                return
            self._stopping = True
            self._state = RemoteTransportState.STOPPING
            operator_event("remote_chat.transport.stopping", transport="discord")
        if loop is not None and client is not None and loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_client(), loop)
                future.result(self._shutdown_timeout)
            except BaseException:
                self._mark_error()
        thread.join(self._shutdown_timeout)
        if thread.is_alive():
            self._mark_error()
            raise DiscordRemoteAdapterError(
                "Discord Remote Chat shutdown could not be proven."
            )
        with self._lock:
            self._thread = None
            self._loop = None
            self._client = None
            self._receiver = None
            self._verified_dm_channel_id = None
            if self._state is not RemoteTransportState.ERROR:
                self._state = RemoteTransportState.OFF
        operator_event("remote_chat.transport.stopped", transport="discord")

    def begin_send(
        self,
        request: RemoteOutboundRequest,
        authorize_entry: SendEntryAuthorizer,
    ) -> RemoteSendAttempt:
        if request.connector_id != self._connector_id:
            raise DiscordRemoteAdapterError(
                "Discord outbound connector identity does not match."
            )
        destination = _discord_id(
            request.external_conversation_id, "outbound DM channel"
        )
        if len(request.text) > self.outbound_text_limit:
            raise ValueError("Discord outbound text exceeds the physical limit.")
        if any(
            (
                request.allow_user_mentions,
                request.allow_role_mentions,
                request.allow_everyone_mentions,
                request.allow_reply_mentions,
            )
        ):
            raise DiscordRemoteAdapterError(
                "Discord Remote Chat does not permit mentions."
            )
        with self._lock:
            if (
                self._state is not RemoteTransportState.CONNECTED
                or self._loop is None
                or self._client is None
                or self._stopping
            ):
                raise DiscordRemoteAdapterError(
                    "Discord Remote Chat transport is not connected."
                )
            if destination != self._verified_dm_channel_id:
                raise DiscordRemoteAdapterError(
                    "Discord outbound DM identity has not been verified."
                )
            loop = self._loop
            client = self._client
            attempt = _DiscordSendAttempt()
            prepared = DiscordPreparedMessage(
                channel_id=destination,
                text=request.text,
                nonce=_discord_nonce(request.application_request_id),
            )
            runner = asyncio.run_coroutine_threadsafe(
                self._send(client, prepared, authorize_entry, attempt), loop
            )
            self._runner_futures.add(runner)
            runner.add_done_callback(
                lambda completed: self._runner_finished(completed, attempt)
            )
        attempt.wait_for_boundary()
        return attempt

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            loop.run_until_complete(self._start_client())
            with self._lock:
                should_run = (
                    not self._stopping
                    and not self._startup_error
                    and self._state is RemoteTransportState.CONNECTED
                )
            if should_run:
                loop.run_forever()
        except BaseException as exc:
            operator_failure(
                "remote_chat.transport.failed",
                exc,
                code="gateway_runtime_error",
                transport="discord",
                traceback=True,
            )
            self._fail_startup()
        finally:
            try:
                loop.run_until_complete(self._cancel_sends())
                loop.run_until_complete(self._close_client())
                loop.run_until_complete(loop.shutdown_asyncgens())
            except BaseException:
                self._mark_error()
            finally:
                loop.close()
                with self._lock:
                    if self._stopping and self._state is not RemoteTransportState.ERROR:
                        self._state = RemoteTransportState.OFF
                    elif not self._stopping:
                        self._state = RemoteTransportState.ERROR
                    self._startup_complete.set()

    async def _start_client(self) -> None:
        try:
            client = self._client_factory(self._token)
            with self._lock:
                self._client = client
            observe_connection = getattr(client, "set_connection_observer", None)
            if callable(observe_connection):
                observe_connection(self._gateway_connection_changed)
            identity = await client.start(self._receive_gateway_message)
            self._verify_gateway_identity(identity)
            if self._configured_dm_channel_id is not None:
                channel = await client.resolve_private_channel(
                    self._configured_dm_channel_id
                )
                self._verify_dm_channel(channel)
                self._verified_dm_channel_id = channel.channel_id
            with self._lock:
                if self._stopping:
                    raise DiscordRemoteAdapterError(
                        "Discord Remote Chat stopped during startup."
                    )
                self._identity_verified = True
                self._state = RemoteTransportState.CONNECTED
            self._startup_complete.set()
            asyncio.create_task(self._monitor_client(client))
        except BaseException as exc:
            operator_failure(
                "remote_chat.transport.failed",
                exc,
                code="authentication_or_configuration_error",
                transport="discord",
            )
            with self._lock:
                self._startup_error = True
            self._mark_error()
            self._startup_complete.set()

    async def _monitor_client(self, client: _DiscordClientPort) -> None:
        try:
            await client.join()
        except BaseException:
            self._mark_error()
        finally:
            with self._lock:
                stopping = self._stopping
                loop = self._loop
            if not stopping:
                self._mark_error()
            if loop is not None and loop.is_running():
                loop.stop()

    async def _close_client(self) -> None:
        with self._lock:
            client = self._client
        await self._cancel_sends()
        if client is not None:
            try:
                await client.close()
            except BaseException:
                self._mark_error()

    async def _cancel_sends(self) -> None:
        current = asyncio.current_task()
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not current and task.get_name().startswith("tori-discord-send-")
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send(
        self,
        client: _DiscordClientPort,
        prepared: DiscordPreparedMessage,
        authorize_entry: SendEntryAuthorizer,
        attempt: _DiscordSendAttempt,
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            task.set_name(f"tori-discord-send-{prepared.nonce}")
        authorized = False
        try:
            original = prepared
            prepared = await client.prepare_message(prepared)
            if not isinstance(prepared, DiscordPreparedMessage) or prepared != original:
                raise DiscordRemoteAdapterError(
                    "Discord send preparation changed an authoritative request."
                )
            with self._lock:
                if (
                    self._state is not RemoteTransportState.CONNECTED
                    or self._stopping
                    or not self._identity_verified
                ):
                    attempt.rejected(
                        DiscordRemoteAdapterError(
                            "Discord disconnected before send authorization."
                        )
                    )
                    return
            try:
                authorize_entry()
            except BaseException as exc:
                attempt.rejected(exc)
                return
            authorized = True
            attempt.authorized()
            receipt = await client.create_message(prepared)
        except _DefiniteDiscordSendError as exc:
            if not authorized:
                attempt.rejected(exc)
                return
            if exc.fatal:
                self._mark_error()
                asyncio.create_task(self._close_after_fatal_send(client))
            attempt.finish(
                RemoteOutboundResult(RemoteDeliveryState.FAILED, error_code=exc.code)
            )
            return
        except _AmbiguousDiscordSendError as exc:
            if not authorized:
                attempt.rejected(exc)
                return
            attempt.finish(
                RemoteOutboundResult(
                    RemoteDeliveryState.AMBIGUOUS, error_code=exc.code
                )
            )
            return
        except asyncio.CancelledError:
            error = DiscordRemoteAdapterError(
                "Discord send preparation was stopped before authorization."
            )
            if authorized:
                attempt.finish(
                    RemoteOutboundResult(
                        RemoteDeliveryState.AMBIGUOUS,
                        error_code="discord_send_interrupted",
                    )
                )
            else:
                attempt.rejected(error)
            raise
        except BaseException as exc:
            if authorized:
                attempt.finish(
                    RemoteOutboundResult(
                        RemoteDeliveryState.AMBIGUOUS,
                        error_code="discord_send_outcome_unknown",
                    )
                )
            else:
                attempt.rejected(
                    DiscordRemoteAdapterError(
                        "Discord send preparation failed before authorization."
                    )
                )
            return
        if not isinstance(receipt, DiscordMessageReceipt):
            attempt.finish(
                RemoteOutboundResult(
                    RemoteDeliveryState.AMBIGUOUS,
                    error_code="discord_acknowledgement_unverified",
                )
            )
            return
        message_id = _optional_discord_id(receipt.message_id)
        if message_id is None or receipt.nonce != prepared.nonce:
            attempt.finish(
                RemoteOutboundResult(
                    RemoteDeliveryState.AMBIGUOUS,
                    error_code="discord_acknowledgement_unverified",
                )
            )
            return
        attempt.finish(
            RemoteOutboundResult(
                RemoteDeliveryState.ACKNOWLEDGED,
                external_message_id=message_id,
            )
        )

    async def _receive_gateway_message(self, event: DiscordGatewayMessage) -> None:
        if not isinstance(event, DiscordGatewayMessage):
            self._mark_error()
            return
        with self._lock:
            if self._state is not RemoteTransportState.CONNECTED or self._stopping:
                return
            receiver = self._receiver
            client = self._client
        if receiver is None or client is None:
            return
        if (
            event.guild_id is not None
            or event.actor_id != self._owner_user_id
            or event.author_is_bot
            or event.author_is_system
            or event.webhook_id is not None
            or event.message_type != int(hikari.MessageType.DEFAULT)
            or event.unsupported_content
            or not isinstance(event.text, str)
            or not event.text.strip()
            or len(event.text) > MAX_REMOTE_TEXT_CHARACTERS
        ):
            return
        try:
            message_id = _discord_id(event.message_id, "message")
            channel_id = _discord_id(event.channel_id, "DM channel")
            received_at = _timestamp(event.received_at)
        except DiscordRemoteAdapterError:
            return
        with self._lock:
            verified = self._verified_dm_channel_id
        if verified is None:
            try:
                channel = await client.resolve_private_channel(channel_id)
                self._verify_dm_channel(channel)
            except BaseException:
                return
            with self._lock:
                if self._verified_dm_channel_id not in {None, channel_id}:
                    return
                self._verified_dm_channel_id = channel_id
        elif verified != channel_id:
            return
        envelope = RemoteInboundEnvelope(
            transport="discord_remote",
            connector_id=self._connector_id,
            external_message_id=message_id,
            external_actor_id=event.actor_id,
            external_conversation_id=channel_id,
            application_id=self._application_id,
            bot_user_id=self._bot_user_id,
            installation_id=self._installation_id,
            received_at=received_at,
            text=event.text,
        )
        try:
            receiver(envelope)
        except BaseException:
            self._mark_error()
            await self._cancel_sends()
            try:
                await client.close()
            except BaseException:
                self._mark_error()

    def _verify_gateway_identity(self, identity: DiscordGatewayIdentity) -> None:
        if (
            not isinstance(identity, DiscordGatewayIdentity)
            or _discord_id(identity.application_id, "authenticated application")
            != self._application_id
            or _discord_id(identity.bot_user_id, "authenticated bot user")
            != self._bot_user_id
            or (self._installation_id,)
            != tuple(
                _discord_id(item, "installation guild")
                for item in identity.installation_guild_ids
            )
        ):
            raise DiscordRemoteAdapterError(
                "Discord authenticated identity does not match configuration."
            )

    def _verify_dm_channel(self, channel: DiscordPrivateChannel) -> None:
        if (
            not isinstance(channel, DiscordPrivateChannel)
            or channel.kind != "one_to_one_dm"
            or _discord_id(channel.channel_id, "DM channel") != channel.channel_id
            or channel.recipient_id != self._owner_user_id
            or (
                self._configured_dm_channel_id is not None
                and channel.channel_id != self._configured_dm_channel_id
            )
        ):
            raise DiscordRemoteAdapterError(
                "Discord channel is not the configured owner one-to-one DM."
            )

    def _mark_error(self) -> None:
        with self._lock:
            self._state = RemoteTransportState.ERROR

    def _gateway_connection_changed(self, connected: bool) -> None:
        with self._lock:
            if self._stopping or self._state in {
                RemoteTransportState.OFF,
                RemoteTransportState.ERROR,
            }:
                return
            self._state = (
                RemoteTransportState.CONNECTED
                if connected and self._identity_verified
                else RemoteTransportState.CONNECTING
            )

    async def _close_after_fatal_send(self, client: _DiscordClientPort) -> None:
        try:
            await client.close()
        except BaseException:
            self._mark_error()

    def _runner_finished(
        self, runner: Future[object], attempt: _DiscordSendAttempt
    ) -> None:
        with self._lock:
            self._runner_futures.discard(runner)
        if runner.cancelled():
            if not attempt.boundary_resolved:
                attempt.rejected(
                    DiscordRemoteAdapterError(
                        "Discord send preparation stopped before authorization."
                    )
                )
            else:
                attempt.fail(
                    _AmbiguousDiscordSendError("discord_send_interrupted")
                )
            return
        try:
            error = runner.exception()
        except BaseException:
            error = _AmbiguousDiscordSendError("discord_send_outcome_unknown")
        if error is not None:
            if not attempt.boundary_resolved:
                attempt.rejected(
                    DiscordRemoteAdapterError(
                        "Discord send preparation failed before authorization."
                    )
                )
            else:
                attempt.fail(
                    _AmbiguousDiscordSendError("discord_send_outcome_unknown")
                )

    def _fail_startup(self) -> None:
        with self._lock:
            self._startup_error = True
            self._state = RemoteTransportState.ERROR
            self._startup_complete.set()
            loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    def _join_finished_thread(self) -> None:
        if self._thread is not None and not self._thread.is_alive():
            self._thread.join()
            self._thread = None


class _HikariDiscordClient(_DiscordClientPort):
    """Narrow projection of Hikari used only by ``DiscordRemoteChannel``."""

    def __init__(self, token: str) -> None:
        self._bot = hikari.GatewayBot(
            token,
            intents=DISCORD_GATEWAY_INTENTS,
            banner=None,
            logs=None,
            auto_chunk_members=False,
            cache_settings=hikari.impl.CacheSettings(components=0),
            max_rate_limit=DISCORD_MAX_RATE_LIMIT_SECONDS,
            max_retries=DISCORD_MAX_SERVER_RETRIES,
            http_settings=hikari.impl.HTTPSettings(
                timeouts=hikari.impl.HTTPTimeoutSettings(total=30.0)
            ),
        )
        self._receiver: GatewayMessageReceiver | None = None
        self._connection_observer: Callable[[bool], None] | None = None

    def set_connection_observer(self, observer: Callable[[bool], None]) -> None:
        self._connection_observer = observer

    async def start(self, receiver: GatewayMessageReceiver) -> DiscordGatewayIdentity:
        self._receiver = receiver
        self._bot.subscribe(hikari.DMMessageCreateEvent, self._on_message)
        self._bot.subscribe(hikari.ShardDisconnectedEvent, self._on_disconnected)
        self._bot.subscribe(hikari.ShardReadyEvent, self._on_connected)
        self._bot.subscribe(hikari.ShardResumedEvent, self._on_connected)
        try:
            await self._bot.start(check_for_updates=False)
            me = await self._bot.rest.fetch_my_user()
            application = await self._bot.rest.fetch_application()
            guilds = tuple(
                str(guild.id)
                for guild in await self._bot.rest.fetch_my_guilds().limit(2)
            )
        except BaseException as exc:
            raise DiscordRemoteAdapterError(
                "Discord authentication or startup failed."
            ) from None
        return DiscordGatewayIdentity(str(application.id), str(me.id), guilds)

    async def close(self) -> None:
        if self._bot.is_alive:
            await self._bot.close()

    async def join(self) -> None:
        await self._bot.join()

    async def resolve_private_channel(self, channel_id: str) -> DiscordPrivateChannel:
        try:
            channel = await self._bot.rest.fetch_channel(int(channel_id))
        except BaseException:
            raise DiscordRemoteAdapterError(
                "Discord DM identity could not be verified."
            ) from None
        if isinstance(channel, hikari.DMChannel):
            return DiscordPrivateChannel(
                str(channel.id), "one_to_one_dm", str(channel.recipient.id)
            )
        if isinstance(channel, hikari.GroupDMChannel):
            return DiscordPrivateChannel(str(channel.id), "group_dm", None)
        return DiscordPrivateChannel(str(channel.id), "unsupported", None)

    async def prepare_message(
        self, message: DiscordPreparedMessage
    ) -> DiscordPreparedMessage:
        return message

    async def create_message(
        self, message: DiscordPreparedMessage
    ) -> DiscordMessageReceipt:
        try:
            sent = await self._bot.rest.create_message(
                int(message.channel_id),
                message.text,
                nonce=message.nonce,
                mentions_everyone=False,
                mentions_reply=False,
                user_mentions=False,
                role_mentions=False,
            )
        except (hikari.UnauthorizedError, hikari.ForbiddenError) as exc:
            raise _DefiniteDiscordSendError(
                "discord_authorization_failed", fatal=True
            ) from None
        except (hikari.BadRequestError, hikari.NotFoundError) as exc:
            raise _DefiniteDiscordSendError("discord_send_rejected") from None
        except hikari.RateLimitTooLongError:
            raise _DefiniteDiscordSendError("discord_rate_limit_exceeded") from None
        except BaseException:
            raise _AmbiguousDiscordSendError(
                "discord_send_outcome_unknown"
            ) from None
        return DiscordMessageReceipt(str(sent.id), getattr(sent, "nonce", None))

    async def _on_message(self, event: hikari.DMMessageCreateEvent) -> None:
        receiver = self._receiver
        if receiver is None:
            return
        message = event.message
        unsupported = bool(
            message.attachments
            or message.embeds
            or message.components
            or message.stickers
            or message.message_snapshots
            or message.poll is not None
            or message.message_reference is not None
            or message.application is not None
            or message.application_id is not None
            or message.interaction_metadata is not None
            or message.is_tts
        )
        timestamp = message.timestamp
        received_at = (
            ""
            if timestamp.tzinfo is None
            else timestamp.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        )
        await receiver(
            DiscordGatewayMessage(
                message_id=str(message.id),
                actor_id=str(message.author.id),
                channel_id=str(message.channel_id),
                received_at=received_at,
                text=message.content,
                guild_id=(None if message.guild_id is None else str(message.guild_id)),
                author_is_bot=message.author.is_bot,
                author_is_system=message.author.is_system,
                webhook_id=(
                    None if message.webhook_id is None else str(message.webhook_id)
                ),
                message_type=int(message.type),
                unsupported_content=unsupported,
            )
        )

    async def _on_disconnected(self, _event: hikari.ShardDisconnectedEvent) -> None:
        if self._connection_observer is not None:
            self._connection_observer(False)

    async def _on_connected(
        self, _event: hikari.ShardReadyEvent | hikari.ShardResumedEvent
    ) -> None:
        if self._connection_observer is not None:
            self._connection_observer(True)


def _discord_nonce(application_request_id: str) -> str:
    digest = hashlib.sha256(application_request_id.encode("utf-8")).digest()[:18]
    nonce = "t" + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    if len(nonce) > DISCORD_NONCE_LIMIT:
        raise AssertionError("Discord nonce derivation exceeded its fixed bound.")
    return nonce


def _discord_id(value: object, label: str) -> str:
    normalized = _optional_discord_id(value)
    if normalized is None:
        raise DiscordRemoteAdapterError(
            f"Discord {label} identity is not a valid numeric ID."
        )
    return normalized


def _optional_discord_id(value: object) -> str | None:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    if value != str(int(value)):
        return None
    number = int(value)
    if not 0 < number < 2**64:
        return None
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise DiscordRemoteAdapterError("Discord message timestamp is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiscordRemoteAdapterError(
            "Discord message timestamp is invalid."
        ) from exc
    if parsed.tzinfo is None:
        raise DiscordRemoteAdapterError("Discord message timestamp is invalid.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_timeout(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise ValueError(f"Discord {label} timeout must be positive.")
    return float(value)
