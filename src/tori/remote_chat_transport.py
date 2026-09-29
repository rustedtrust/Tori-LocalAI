"""Transport-neutral Remote Chat values and adapter boundary."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import threading
from typing import Protocol


MAX_REMOTE_TEXT_CHARACTERS = 4_000
MAX_REMOTE_IDENTIFIER_CHARACTERS = 256


class RemoteTransportState(str, Enum):
    OFF = "off"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STOPPING = "stopping"
    ERROR = "error"


class RemoteDeliveryState(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RemoteInboundEnvelope:
    """One SDK-free, already decoded inbound transport event."""

    transport: str
    connector_id: str
    external_message_id: str
    external_actor_id: str
    external_conversation_id: str
    application_id: str
    bot_user_id: str
    installation_id: str
    received_at: str
    text: str
    channel_kind: str = "one_to_one_dm"
    author_kind: str = "human"
    unsupported_content: bool = False

    def __post_init__(self) -> None:
        for name in (
            "transport", "connector_id", "external_message_id",
            "external_actor_id", "external_conversation_id", "application_id",
            "bot_user_id", "installation_id", "received_at",
        ):
            _validate_identifier(getattr(self, name), name)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Remote message text must be non-empty.")
        if len(self.text) > MAX_REMOTE_TEXT_CHARACTERS:
            raise ValueError("Remote message text exceeds the admission limit.")
        if self.channel_kind != "one_to_one_dm":
            raise ValueError("Remote Chat accepts one-to-one DM envelopes only.")
        if self.author_kind != "human":
            raise ValueError("Remote Chat accepts human-authored envelopes only.")
        if not isinstance(self.unsupported_content, bool):
            raise TypeError("Unsupported-content state must be boolean.")


@dataclass(frozen=True, slots=True)
class RemoteOutboundRequest:
    connector_id: str
    external_conversation_id: str
    application_request_id: str
    text: str
    logical_request_id: str | None = None
    chunk_index: int = 0
    chunk_count: int = 1
    allow_user_mentions: bool = False
    allow_role_mentions: bool = False
    allow_everyone_mentions: bool = False
    allow_reply_mentions: bool = False

    def __post_init__(self) -> None:
        for name in (
            "connector_id", "external_conversation_id", "application_request_id"
        ):
            _validate_identifier(getattr(self, name), name)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Remote outbound text must be non-empty.")
        if len(self.text) > MAX_REMOTE_TEXT_CHARACTERS:
            raise ValueError("Remote outbound chunk exceeds the application limit.")
        if self.logical_request_id is not None:
            _validate_identifier(self.logical_request_id, "logical_request_id")
        if (
            isinstance(self.chunk_index, bool)
            or not isinstance(self.chunk_index, int)
            or isinstance(self.chunk_count, bool)
            or not isinstance(self.chunk_count, int)
            or self.chunk_count < 1
            or not 0 <= self.chunk_index < self.chunk_count
        ):
            raise ValueError("Remote outbound chunk position is invalid.")
        if any((
            self.allow_user_mentions,
            self.allow_role_mentions,
            self.allow_everyone_mentions,
            self.allow_reply_mentions,
        )):
            raise ValueError("Remote Chat never authorizes transport mentions.")


@dataclass(frozen=True, slots=True)
class RemoteOutboundResult:
    state: RemoteDeliveryState
    external_message_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, RemoteDeliveryState):
            raise TypeError("Remote delivery state must be typed.")
        if self.state is RemoteDeliveryState.ACKNOWLEDGED:
            _validate_identifier(self.external_message_id, "external_message_id")
            if self.error_code is not None:
                raise ValueError("Acknowledged delivery cannot include an error.")
        elif self.external_message_id is not None:
            raise ValueError("Unacknowledged delivery cannot claim a message ID.")
        if self.error_code is not None:
            _validate_identifier(self.error_code, "error_code")


InboundReceiver = Callable[[RemoteInboundEnvelope], None]
SendEntryAuthorizer = Callable[[], None]


class RemoteSendAttempt(Protocol):
    """A send already initiated by the adapter whose outcome may arrive later."""

    def wait(self) -> RemoteOutboundResult: ...


class RemoteChannelPort(Protocol):
    """Replaceable transport boundary; no provider or application authority.

    ``begin_send`` may perform reversible preparation without application locks.
    At the final linearization point immediately before irreversible external
    invocation, the adapter must call ``authorize_entry``.  Tori either rejects
    it or durably authorizes that entry; after a successful return the attempt is
    treated as initiated even if transport code fails before acknowledgement.
    ``begin_send`` must not return an attempt before that point.  Completion and
    acknowledgement may arrive later via the returned attempt.
    """

    def start(self, receiver: InboundReceiver) -> None: ...

    def stop(self) -> None: ...

    def status(self) -> RemoteTransportState: ...

    @property
    def outbound_text_limit(self) -> int: ...

    def begin_send(
        self,
        request: RemoteOutboundRequest,
        authorize_entry: SendEntryAuthorizer,
    ) -> RemoteSendAttempt: ...


class _ThreadedSendAttempt:
    def __init__(
        self,
        send: Callable[[Callable[[], None]], RemoteOutboundResult],
    ) -> None:
        self._result: RemoteOutboundResult | None = None
        self._error: BaseException | None = None
        self._initiated = threading.Event()
        self._boundary_resolved = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(send,), daemon=False)
        self._thread.start()
        self._boundary_resolved.wait()
        if not self._initiated.is_set():
            self._thread.join()
            if self._error is not None:
                raise self._error
            raise RuntimeError(
                "Remote send ended without entering its initiation boundary."
            )

    def _run(
        self,
        send: Callable[[Callable[[], None]], RemoteOutboundResult],
    ) -> None:
        try:
            self._result = send(self._mark_initiated)
        except BaseException as exc:
            self._error = exc
        finally:
            self._boundary_resolved.set()

    def _mark_initiated(self) -> None:
        self._initiated.set()
        self._boundary_resolved.set()

    def wait(self) -> RemoteOutboundResult:
        self._thread.join()
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise RuntimeError("Remote send ended without a typed result.")
        return self._result


class FakeRemoteChannel:
    """Deterministic fake adapter used to prove the replaceable boundary."""

    def __init__(self) -> None:
        self._receiver: InboundReceiver | None = None
        self._state = RemoteTransportState.OFF
        self.sent: list[RemoteOutboundRequest] = []
        self.next_result: RemoteOutboundResult | None = None
        self._outbound_text_limit = 1_000
        self.send_preparation_started = threading.Event()
        self.send_entry_authorized = threading.Event()
        self.send_completion_pending = threading.Event()
        self.send_completed = threading.Event()
        self._send_entry_allowed = threading.Event()
        self._send_completion_allowed = threading.Event()
        self._send_entry_allowed.set()
        self._send_completion_allowed.set()

    @property
    def outbound_text_limit(self) -> int:
        return self._outbound_text_limit

    def start(self, receiver: InboundReceiver) -> None:
        if self._state is not RemoteTransportState.OFF:
            raise RuntimeError("Fake Remote transport is already started.")
        self._state = RemoteTransportState.CONNECTING
        self._receiver = receiver
        self._state = RemoteTransportState.CONNECTED

    def stop(self) -> None:
        self._state = RemoteTransportState.STOPPING
        self._receiver = None
        self._state = RemoteTransportState.OFF

    def status(self) -> RemoteTransportState:
        return self._state

    def emit(self, envelope: RemoteInboundEnvelope) -> None:
        if self._state is not RemoteTransportState.CONNECTED or self._receiver is None:
            raise RuntimeError("Fake Remote transport is not connected.")
        self._receiver(envelope)

    def send(
        self,
        request: RemoteOutboundRequest,
    ) -> RemoteOutboundResult:
        if self._state is not RemoteTransportState.CONNECTED:
            return RemoteOutboundResult(RemoteDeliveryState.FAILED, error_code="offline")
        self.sent.append(request)
        self.send_completion_pending.set()
        self._send_completion_allowed.wait()
        if self.next_result is not None:
            result, self.next_result = self.next_result, None
            return result
        return RemoteOutboundResult(
            RemoteDeliveryState.ACKNOWLEDGED,
            external_message_id=f"fake-reply-{len(self.sent)}",
        )

    def begin_send(
        self,
        request: RemoteOutboundRequest,
        authorize_entry: SendEntryAuthorizer,
    ) -> RemoteSendAttempt:
        if len(request.text) > self.outbound_text_limit:
            raise ValueError("Remote outbound chunk exceeds the adapter limit.")

        def perform(mark_initiated: Callable[[], None]) -> RemoteOutboundResult:
            self.send_preparation_started.set()
            self._send_entry_allowed.wait()
            authorize_entry()
            mark_initiated()
            self.send_entry_authorized.set()
            try:
                return self.send(request)
            finally:
                self.send_completed.set()

        return _ThreadedSendAttempt(perform)

    def pause_before_send_entry(self) -> None:
        self._send_entry_allowed.clear()

    def allow_send_entry(self) -> None:
        self._send_entry_allowed.set()

    def pause_before_send_completion(self) -> None:
        self._send_completion_allowed.clear()

    def allow_send_completion(self) -> None:
        self._send_completion_allowed.set()


def _validate_identifier(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_REMOTE_IDENTIFIER_CHARACTERS
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Remote {name} is invalid.")
    return value
