"""Durable transport-neutral Remote Chat application core."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import threading, time
from typing import Iterator

from .chats import ChatService, ChatServiceError
from .conversation import ConversationSession
from .conversation_application import ConversationTurnRequest, ConversationTurnService
from .conversation_archive import ArchiveEntry
from .providers import ChatMessage
from .operator_observability import operator_error, operator_event, operator_failure
from .remote_chat_config import RemoteChatConfiguration, RemoteChatConfigStore, RemoteConfigError
from .remote_chat_ledger import InboundRecord, OutboundChunkRecord, RemoteAdmissionConflict, RemoteChatLedger, RemoteLedgerError
from .remote_chat_operations import RemoteSearchHandler
from .remote_chat_transport import (
    MAX_REMOTE_TEXT_CHARACTERS, RemoteChannelPort, RemoteDeliveryState,
    RemoteInboundEnvelope, RemoteOutboundRequest, RemoteTransportState,
)
from .request_origin import (
    ConversationOperation,
    OriginAuthorityError,
    RequestOrigin,
    RequestOriginKind,
)

REMOTE_CHAT_LABEL = "Remote Chat"
REMOTE_CHAT_PROVENANCE_TEXT = "Tori Remote Chat reservation provenance."
REMOTE_BLOCKED_MESSAGE = (
    "That operation is not available through Remote Chat. Use Tori locally for "
    "sensitive information, changes, execution, or confirmations."
)

class RemoteChatError(RuntimeError):
    code = "remote_chat_error"

class RemoteChatDisabledError(RemoteChatError):
    code = "remote_chat_disabled"

@dataclass(frozen=True, slots=True)
class RemoteChatStatus:
    state: RemoteTransportState
    enabled: bool
    generation: int
    chat_id: str | None
    worker_alive: bool
    active: bool
    last_error: str | None

class RemoteChatService:
    """One-owner FIFO core over shared Conversation and a replaceable port."""
    def __init__(
        self, *, configuration: RemoteChatConfiguration, ledger: RemoteChatLedger,
        transport: RemoteChannelPort, chats: ChatService,
        conversation_turns: ConversationTurnService, session: ConversationSession,
        session_factory: Callable[[Sequence[ChatMessage]], ConversationSession] | None = None,
        provider_name: str, model_name: str,
        config_store: RemoteChatConfigStore | None = None,
        search_handler: RemoteSearchHandler | None = None,
        shutdown_timeout_seconds: float = 5.0,
        synchronization_hook: Callable[[str], None] | None = None,
        activity_signal: Callable[[str, str], None] | None = None,
    ) -> None:
        self._configuration = configuration
        self._configuration_generation = configuration.generation
        self._ledger, self._transport, self._chats = ledger, transport, chats
        self._turns, self._session, self._session_factory = conversation_turns, session, session_factory
        self._provider_name, self._model_name = provider_name, model_name
        self._config_store, self._search_handler = config_store, search_handler
        self._shutdown_timeout, self._hook = shutdown_timeout_seconds, synchronization_hook
        self._activity_signal = activity_signal
        self._condition = threading.Condition()
        self._fence_lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._closing = self._paused = self._active = self._fatal = False
        self._backup_requested = False
        self._last_error: str | None = None
        self._generation = 0
        self._chat_id: str | None = None
        self._provenance_event_id: str | None = None

    def initialize(self) -> str:
        current = self._load_configuration()
        if not current.effective_enabled:
            raise RemoteChatDisabledError("Remote Chat is not legitimately activated.")
        self._configuration = current
        self._configuration_generation = current.generation
        self._ledger.initialize(); self._chats.initialize(); self._ledger.reconcile_uncertain_sends()
        self._chat_id = self._ledger.reserve_chat()
        binding = self._ledger.binding()
        if binding is None: raise RemoteChatError("Remote Chat reservation disappeared.")
        self._provenance_event_id = binding[4]
        try:
            detail = self._chats.get_chat(self._chat_id)
        except ChatServiceError as exc:
            if exc.code != "not_found": raise RemoteChatError("Remote Chat binding could not be verified.") from exc
            if binding[1] == "bound": raise RemoteChatError("The bound Remote Chat conversation is missing.") from exc
            for record in self._ledger.processing_records(): self._ledger.fail(record, "interrupted_before_archive")
        else:
            self._require_provenance(detail)
            self._ledger.mark_chat_bound(self._chat_id)
            self._reconcile_processing(detail)
            history = self._chats.model_history(self._chat_id)
            if self._session.history != history: self._replace_session(history)
        # Configuration is the durable cross-process authority. Reconcile archived
        # crash state first, then terminalize every older connector generation.
        self._ledger.fence_generation(current.generation, code="configuration_generation_fenced")
        self._generation = current.generation
        self._turns.attach_session(self._session, origin_kind=RequestOriginKind.DISCORD_REMOTE,
                                   conversation_id=self._chat_id)
        return self._chat_id

    def start(self) -> None:
        current = self._load_configuration()
        if not current.effective_enabled:
            raise RemoteChatDisabledError("Remote Chat is disabled by local administrator or owner configuration.")
        self._configuration, self._configuration_generation = current, current.generation
        if self._chat_id is None: self.initialize()
        with self._fence_lock, self._authority_guard(current.generation):
            with self._condition:
                if self._worker is not None and not self._worker.is_alive():
                    self._worker = None
                if self._worker is not None:
                    raise RemoteChatError("Remote Chat is already started.")
            continuation_error = self._clear_remote_continuations()
            if continuation_error is not None:
                self._fatal = self._closing = self._paused = True
                self._last_error = "continuation_cleanup_failure"
                self._safe_stop_transport()
                raise RemoteChatError(
                    "Remote Chat continuation state could not be cleared before startup."
                ) from continuation_error
            self._ledger.fence_generation(
                current.generation, code="configuration_generation_fenced"
            )
            self._generation = current.generation
            self._reconcile_stopped_state()
            with self._condition:
                self._closing = self._paused = self._fatal = self._backup_requested = False
                try: self._transport.start(self.admit)
                except Exception:
                    self._safe_stop_transport(); raise
                if self._transport.status() is not RemoteTransportState.CONNECTED:
                    self._safe_stop_transport(); raise RemoteChatError("Remote Chat transport did not become ready.")
                self._worker = threading.Thread(target=self._worker_loop, name="tori-remote-chat", daemon=False)
                self._worker.start(); self._condition.notify_all()

    def admit(self, envelope: RemoteInboundEnvelope) -> bool:
        try:
            with self._fence_lock, self._authority_guard(self._generation) as current:
                self._call_hook("admission_before_mutation")
                with self._condition:
                    if (self._closing or self._paused or self._backup_requested or self._worker is None
                                or self._transport.status() is not RemoteTransportState.CONNECTED): return False
                if not self._authorized_envelope(envelope, current):
                    operator_event(
                        "remote_chat.admission.denied",
                        origin="discord_remote",
                        category="identity_or_payload",
                    )
                    return False
                self._ledger.bind_dm(envelope.external_conversation_id)
                record, admitted = self._ledger.admit(envelope, self._generation)
        except RemoteAdmissionConflict:
            self._last_error = "immutable_identity_conflict"; raise
        except (RemoteLedgerError, RemoteConfigError, RemoteChatDisabledError):
            self._last_error = "admission_fenced"; return False
        if admitted:
            if self._activity_signal is not None:
                try:
                    self._activity_signal(
                        "remote_turn",
                        f"discord:{record.connector_id}:{record.external_message_id}",
                    )
                except Exception as exc:
                    operator_failure(
                        "companion_initiative.activity.failed",
                        exc,
                        code=getattr(exc, "code", "activity_unavailable"),
                        origin="discord_remote",
                    )
            operator_event(
                "remote_chat.turn.admitted",
                origin="discord_remote",
                sequence=record.receipt_order,
            )
            with self._condition: self._condition.notify_all()
        return admitted

    def kill(self) -> None:
        """Publish the durable authority fence before any later irreversible step."""
        error: BaseException | None = None
        with self._condition:
            self._closing = self._paused = True
            self._condition.notify_all()
        try:
            self._call_hook("kill_requested_before_fence")
        except BaseException as exc:
            error = exc
            self._last_error = "kill_synchronization_failure"
        with self._fence_lock:
            target = self._generation + 1
            if self._config_store is not None:
                try:
                    self._configuration = self._disable_configuration()
                    self._configuration_generation = self._configuration.generation
                    target = self._configuration.generation
                except BaseException as exc: error = exc
            try:
                self._generation = self._ledger.fence_generation(
                    target, code="connector_killed"
                )
                self._call_hook("kill_fence_published")
            except BaseException as exc:
                error = error or exc; self._last_error = "kill_fence_failure"
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            error = error or continuation_error
            self._fatal = True
            self._last_error = "kill_continuation_cleanup_failure"
        self._safe_stop_transport()
        try:
            self._join_worker()
        except BaseException as exc:
            error = error or exc
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            error = error or continuation_error
            self._fatal = True
            self._last_error = "kill_continuation_cleanup_failure"
        if self._fatal or error is not None:
            raise RemoteChatError(
                "Remote Chat kill could not publish every durable fence."
            ) from error

    def terminate_self(self, request: ConversationTurnRequest) -> None:
        """Durably remove only this verified owner-DM connector's authority."""

        self._turns.require_operation(
            request, ConversationOperation.REMOTE_CHAT_TERMINATE_SELF
        )
        if self._config_store is None:
            raise RemoteChatError(
                "Remote self-termination requires durable private configuration."
            )
        error: BaseException | None = None
        with self._fence_lock:
            current = self._load_configuration()
            binding = self._ledger.binding()
            durable_dm = None if binding is None else binding[3]
            origin = request.origin
            if not (
                current.effective_enabled
                and current.generation == self._generation
                and request.conversation_id == self._chat_id
                and origin.kind is RequestOriginKind.DISCORD_REMOTE
                and origin.connector_id == current.connector_id
                and origin.external_actor_id == current.owner_user_id
                and durable_dm is not None
                and origin.external_conversation_id == durable_dm
                and (
                    current.dm_channel_id is None
                    or current.dm_channel_id == durable_dm
                )
            ):
                raise OriginAuthorityError(
                    "Remote self-termination requires the exact bound owner DM."
                )
            with self._condition:
                self._closing = self._paused = True
                self._condition.notify_all()
            try:
                disabled = self._disable_configuration()
                self._configuration = disabled
                self._configuration_generation = disabled.generation
                self._generation = self._ledger.fence_generation(
                    disabled.generation,
                    code="connector_self_terminated",
                )
            except BaseException as exc:
                error = exc
                self._fatal = True
                self._last_error = "self_termination_fence_failure"
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            error = error or continuation_error
            self._fatal = True
            self._last_error = "self_termination_continuation_cleanup_failure"
        self._safe_stop_transport()
        if self._fatal or error is not None:
            operator_error(
                "remote_chat.self_termination.failed",
                code=self._last_error or "self_termination_failure",
                origin="discord_remote",
            )
            raise RemoteChatError(
                "Remote Chat self-termination could not publish every durable fence."
            ) from error
        operator_event(
            "remote_chat.self_terminated",
            origin="discord_remote",
            generation=self._generation,
        )

    def shutdown(self) -> None:
        error: BaseException | None = None
        with self._condition:
            self._closing = self._paused = True
            self._condition.notify_all()
        try:
            self._call_hook("shutdown_requested_before_stop")
        except BaseException as exc:
            error = exc
            self._fatal = True
            self._last_error = "shutdown_synchronization_failure"
        with self._fence_lock:
            pass
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            error = continuation_error
            self._fatal = True
            self._last_error = "shutdown_continuation_cleanup_failure"
        self._safe_stop_transport()
        try:
            self._join_worker()
        except BaseException as exc:
            error = error or exc
        if self._worker is None:
            continuation_error = self._clear_remote_continuations()
            if continuation_error is not None:
                error = error or continuation_error
                self._fatal = True
                self._last_error = "shutdown_continuation_cleanup_failure"
            try:
                self._reconcile_stopped_state()
                self._require_no_current_inflight_state()
            except BaseException as exc:
                error = error or exc
                self._fatal = True
                self._last_error = "shutdown_durability_unproven"
        if self._fatal or error is not None:
            raise RemoteChatError(
                "Remote Chat shutdown could not prove clean durable state."
            ) from error

    @contextmanager
    def backup_guard(self) -> Iterator[None]:
        """Exclude the complete admission/archive/delivery mutation windows."""
        with self._condition:
            self._backup_requested = True
            self._condition.notify_all()
        with self._fence_lock:
            with self._condition:
                generation = self._generation; self._paused = True; self._condition.notify_all()
        deadline = time.monotonic() + self._shutdown_timeout
        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if not self._closing:
                        self._paused = False; self._backup_requested = False
                        self._condition.notify_all()
                    raise RemoteChatError("Remote Chat is busy; backup was not published.")
                self._condition.wait(remaining)
        with self._fence_lock:
            acquired = self._turns.coordinator.acquire(blocking=False)
            if not acquired:
                with self._condition:
                    if not self._closing:
                        self._paused = False; self._backup_requested = False
                        self._condition.notify_all()
                raise RemoteChatError("Conversation is busy; backup was not published.")
            try:
                self._ledger.checkpoint(); yield
            finally:
                self._turns.coordinator.release()
                with self._condition:
                    if not self._closing and generation == self._generation and not self._fatal:
                        self._paused = False; self._backup_requested = False
                        self._condition.notify_all()

    def wait_idle(self, timeout_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                if self._fatal:
                    return False
                try:
                    durable_work = self._ledger_has_pending_work()
                except Exception:
                    self._fatal = self._closing = self._paused = True
                    self._last_error = "idle_state_unavailable"
                    self._condition.notify_all()
                    self._safe_stop_transport()
                    return False
                if not self._active and not durable_work:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0: return False
                self._condition.wait(min(remaining, .05))

    def status(self) -> RemoteChatStatus:
        worker = self._worker
        state = RemoteTransportState.ERROR if self._fatal else self._transport.status()
        return RemoteChatStatus(state, self._configuration.effective_enabled and not self._closing,
            self._generation, self._chat_id, worker is not None and worker.is_alive(),
            self._active, self._last_error)

    def _worker_loop(self) -> None:
        try:
            while True:
                with self._condition:
                    if self._closing: return
                    if self._paused or self._backup_requested:
                        self._condition.wait(.25); continue
                if not self._configuration_is_current():
                    self._fence_external_disable(); return
                if not self._ledger_has_runnable_work():
                    with self._condition:
                        if self._closing: return
                        self._condition.wait(.25)
                    continue
                with self._condition:
                    if self._closing: return
                    self._active = True
                try: self._process_one()
                except RemoteChatDisabledError:
                    self._fence_external_disable(); return
                except Exception:
                    self._worker_fatal("worker_failure"); return
                finally:
                    with self._condition: self._active = False; self._condition.notify_all()
        except BaseException:
            self._worker_fatal("worker_fatal_exception")
        finally:
            with self._condition: self._active = False; self._condition.notify_all()

    def _process_one(self) -> None:
        pending = self._ledger.pending_chunks()
        if pending:
            self._deliver(pending[0]); return
        with self._fence_lock, self._authority_guard(self._generation):
            detail = self._current_chat(); base_revision = 0 if detail is None else detail.metadata.revision
            record = self._ledger.claim_next(base_revision, self._generation)
        if record is None: return
        if record.text is None: self._ledger.fail(record, "missing_retained_input"); return
        request = ConversationTurnRequest(record.text, RequestOrigin.discord_remote(
            connector_id=record.connector_id, external_message_id=record.external_message_id,
            external_actor_id=record.external_actor_id,
            external_conversation_id=record.external_conversation_id), self._chat_id,
            base_revision, record.receipt_order)
        history_before = tuple(self._session.history)
        turn_started = time.monotonic()
        try: reply = self._turns.complete(request)
        except OriginAuthorityError: reply = REMOTE_BLOCKED_MESSAGE
        except Exception as exc:
            self._ledger.fail(record, "conversation_failed")
            operator_failure(
                "remote_chat.turn.failed",
                exc,
                code="conversation_failed",
                origin="discord_remote",
                sequence=record.receipt_order,
                traceback=True,
            )
            return
        if not isinstance(reply, str) or not reply.strip() or len(reply) > MAX_REMOTE_TEXT_CHARACTERS:
            self._replace_session(history_before)
            self._ledger.fail(record, "logical_reply_size_invalid"); return
        try:
            chunks = _delivery_chunks(reply, self._transport.outbound_text_limit)
        except Exception:
            self._replace_session(history_before)
            self._ledger.fail(record, "delivery_plan_invalid")
            raise
        self._call_hook("before_archive_fence")
        try:
            with self._fence_lock, self._authority_guard(record.connector_generation):
                with self._condition:
                    if self._closing: raise RemoteChatDisabledError("Remote Chat was fenced before archive persistence.")
                completed_revision = base_revision
                if tuple(self._session.history) != history_before:
                    completed_revision = self._persist_session(base_revision, record)
                self._call_hook("archive_persisted_before_outbound")
                outbound = self._ledger.complete(record, archive_completed_revision=completed_revision,
                    reply=reply, generation=record.connector_generation, chunks=chunks)
                operator_event(
                    "remote_chat.outbound.published",
                    origin="discord_remote",
                    chunk_count=len(chunks),
                    sequence=record.receipt_order,
                )
        except RemoteChatDisabledError:
            self._replace_session(history_before)
            if (
                record.connector_generation == self._generation
                and self._configuration_is_current()
            ):
                self._ledger.fail(record, "fenced_before_archive")
            return
        except Exception:
            try: self._ledger.require_reconciliation(record, "archive_completion_interrupted")
            finally: raise
        pending = self._ledger.outbound_chunks(outbound.application_request_id)
        operator_event(
            "remote_chat.turn.completed",
            origin="discord_remote",
            elapsed_ms=int((time.monotonic() - turn_started) * 1000),
            sequence=record.receipt_order,
        )
        # Kill may suppress the just-published reply after the archive/ledger
        # publication fence is released. Only an unsent pending chunk can enter
        # delivery; a terminalized chunk is already durable cancellation truth.
        if pending and pending[0].state == "pending": self._deliver(pending[0])

    def _deliver(self, chunk: OutboundChunkRecord) -> None:
        if chunk.text is None:
            self._ledger.finish_chunk(chunk.chunk_id, state="failed", error_code="missing_retained_output"); return
        request = RemoteOutboundRequest(
            connector_id=chunk.inbound_connector_id,
            external_conversation_id=chunk.destination_id,
            application_request_id=chunk.chunk_id,
            logical_request_id=chunk.application_request_id,
            chunk_index=chunk.chunk_index,
            chunk_count=next(x for x in self._ledger.outbound_records()
                             if x.application_request_id == chunk.application_request_id).chunk_count,
            text=chunk.text)
        claimed: OutboundChunkRecord | None = None
        entry_authorized = False

        def authorize_entry() -> None:
            nonlocal claimed, entry_authorized
            with self._fence_lock, self._authority_guard(chunk.connector_generation):
                with self._condition:
                    closing = self._closing
                if closing:
                    self._terminalize_uninitiated_chunk(
                        chunk.chunk_id, "fenced_before_send_initiation"
                    )
                    raise RemoteChatDisabledError(
                        "Remote Chat was fenced before send initiation."
                    )
                claimed = self._ledger.claim_chunk(
                    chunk.chunk_id, chunk.connector_generation
                )
                entry_authorized = True

        try:
            self._call_hook("send_preparation_started")
            attempt = self._transport.begin_send(request, authorize_entry)
        except RemoteChatDisabledError: return
        except Exception:
            if entry_authorized:
                self._terminalize_uncertain_chunk(
                    chunk.chunk_id, "send_initiation_exception"
                )
            else:
                self._terminalize_uninitiated_chunk(
                    chunk.chunk_id, "send_preparation_exception"
                )
            return
        if claimed is None:
            self._terminalize_uninitiated_chunk(
                chunk.chunk_id, "send_entry_not_authorized"
            )
            raise RemoteChatError(
                "Remote transport returned without authorized send entry."
            )
        try: result = attempt.wait()
        except BaseException:
            self._terminalize_uncertain_chunk(claimed.chunk_id, "send_exception"); return
        try:
            with self._fence_lock, self._authority_guard(chunk.connector_generation):
                with self._condition:
                    closing = self._closing
                if closing and result.state is not RemoteDeliveryState.ACKNOWLEDGED:
                    self._ledger.finish_chunk(
                        chunk.chunk_id,
                        state="ambiguous",
                        error_code="shutdown_during_send",
                    )
                    operator_error(
                        "remote_chat.send.ambiguous",
                        origin="discord_remote",
                        chunk_index=chunk.chunk_index,
                        code="shutdown_during_send",
                    )
                elif result.state is RemoteDeliveryState.ACKNOWLEDGED:
                    self._ledger.finish_chunk(chunk.chunk_id, state="delivered_acknowledged",
                                              external_message_id=result.external_message_id)
                    operator_event(
                        "remote_chat.send.acknowledged",
                        origin="discord_remote",
                        chunk_index=chunk.chunk_index,
                    )
                elif result.state is RemoteDeliveryState.AMBIGUOUS:
                    self._ledger.finish_chunk(chunk.chunk_id, state="ambiguous",
                                              error_code=result.error_code or "delivery_ambiguous")
                    operator_error(
                        "remote_chat.send.ambiguous",
                        origin="discord_remote",
                        chunk_index=chunk.chunk_index,
                        code=result.error_code or "delivery_ambiguous",
                    )
                else:
                    self._ledger.finish_chunk(chunk.chunk_id, state="failed",
                                              error_code=result.error_code or "delivery_failed")
                    operator_error(
                        "remote_chat.send.failed",
                        origin="discord_remote",
                        chunk_index=chunk.chunk_index,
                        code=result.error_code or "delivery_failed",
                    )
        except (RemoteChatDisabledError, RemoteConfigError):
            self._terminalize_uncertain_chunk(chunk.chunk_id, "generation_changed_during_send")

    def _terminalize_uninitiated_chunk(self, chunk_id: str, code: str) -> None:
        try:
            self._ledger.finish_chunk(chunk_id, state="failed", error_code=code)
            operator_error(
                "remote_chat.send.failed",
                origin="discord_remote",
                code=code,
            )
        except RemoteLedgerError as exc:
            try:
                record = next(
                    item for item in self._ledger.outbound_chunks()
                    if item.chunk_id == chunk_id
                )
            except (RemoteLedgerError, StopIteration) as verification_error:
                raise RemoteChatError(
                    "Remote Chat pre-entry terminalization could not be verified."
                ) from verification_error
            if record.state not in {
                "delivered_acknowledged", "ambiguous", "failed", "suppressed"
            }:
                raise RemoteChatError(
                    "Remote Chat pre-entry delivery remains durably unresolved."
                ) from exc

    def _terminalize_uncertain_chunk(self, chunk_id: str, code: str) -> None:
        try:
            self._ledger.finish_chunk(chunk_id, state="ambiguous", error_code=code)
            operator_error(
                "remote_chat.send.ambiguous",
                origin="discord_remote",
                code=code,
            )
        except RemoteLedgerError as exc:
            try:
                record = next(
                    item for item in self._ledger.outbound_chunks()
                    if item.chunk_id == chunk_id
                )
            except (RemoteLedgerError, StopIteration) as verification_error:
                raise RemoteChatError(
                    "Remote Chat delivery terminalization could not be verified."
                ) from verification_error
            if record.state not in {
                "delivered_acknowledged", "ambiguous", "failed", "suppressed"
            }:
                raise RemoteChatError(
                    "Remote Chat delivery remains durably unresolved."
                ) from exc

    def _persist_session(self, base_revision: int, record: InboundRecord) -> int:
        assert self._chat_id is not None and self._provenance_event_id is not None
        detail = self._current_chat()
        archived_history = () if detail is None else self._chats.model_history(self._chat_id)
        if tuple(self._session.history[:len(archived_history)]) != archived_history:
            raise RemoteChatError("Remote Chat session diverged from its archive.")
        new_history = self._session.history[len(archived_history):]
        turn_marker = ArchiveEntry(
            "assistant", "Remote Chat admitted-turn correlation.",
            application_event_id=_turn_event_id(record),
            application_event_type="remote_chat_turn",
        )
        generated = tuple(ArchiveEntry(
            item.role, item.content,
            provider=self._provider_name if item.role == "assistant" else None,
            model=self._model_name if item.role == "assistant" else None,
        ) for item in new_history)
        if detail is None:
            if base_revision != 0: raise RemoteChatError("Remote Chat archive binding changed unexpectedly.")
            entries = (self._provenance_entry(), turn_marker) + generated
            created = self._chats.create_chat(entries, provider=self._provider_name,
                model=self._model_name, identifier=self._chat_id, label=REMOTE_CHAT_LABEL,
                select_active=False)
            self._ledger.mark_chat_bound(self._chat_id); return created.metadata.revision
        self._require_provenance(detail)
        entries = detail.entries + (turn_marker,) + generated
        reconciled = self._chats.reconcile_chat(self._chat_id, entries,
            expected_revision=base_revision, provider=self._provider_name,
            model=self._model_name, label=REMOTE_CHAT_LABEL)
        return reconciled.metadata.revision

    def _provenance_entry(self) -> ArchiveEntry:
        assert self._provenance_event_id is not None
        return ArchiveEntry("assistant", REMOTE_CHAT_PROVENANCE_TEXT,
            application_event_id=self._provenance_event_id,
            application_event_type="remote_chat_binding")

    def _require_provenance(self, detail) -> None:
        if detail.metadata.label != REMOTE_CHAT_LABEL or not detail.entries:
            raise RemoteChatError("The reserved Remote Chat identifier conflicts with another chat.")
        marker = detail.entries[0]
        if not (
            marker.role == "assistant"
            and marker.text == REMOTE_CHAT_PROVENANCE_TEXT
            and marker.application_event_id == self._provenance_event_id
            and marker.application_event_type == "remote_chat_binding"
            and marker.provider is None
            and marker.model is None
            and not marker.sources
            and marker.web_search is None
            and marker.context is None
        ):
            raise RemoteChatError("The reserved Remote Chat conversation has conflicting provenance.")

    def _current_chat(self):  # type: ignore[no-untyped-def]
        assert self._chat_id is not None
        try: return self._chats.get_chat(self._chat_id)
        except ChatServiceError as exc:
            if exc.code == "not_found": return None
            raise

    def _reconcile_processing(self, detail) -> None:  # type: ignore[no-untyped-def]
        for record in self._ledger.processing_records():
            base = record.archive_base_revision
            if (base is not None and detail.metadata.revision == base + 1
                    and len(detail.entries) >= 4 and record.text is not None
                    and detail.entries[-3].application_event_id == _turn_event_id(record)
                    and detail.entries[-3].application_event_type == "remote_chat_turn"
                    and detail.entries[-2].role == "user" and detail.entries[-2].text == record.text
                    and detail.entries[-1].role == "assistant"
                    and detail.entries[-1].application_event_id is None):
                reply = detail.entries[-1].text
                if len(reply) <= MAX_REMOTE_TEXT_CHARACTERS:
                    self._ledger.complete(record, archive_completed_revision=detail.metadata.revision,
                        reply=reply, generation=record.connector_generation,
                        chunks=_delivery_chunks(reply, self._transport.outbound_text_limit))
                else: self._ledger.fail(record, "archived_reply_size_invalid")
            else: self._ledger.fail(record, "interrupted_processing")

    @contextmanager
    def _authority_guard(self, generation: int) -> Iterator[RemoteChatConfiguration]:
        if self._config_store is None:
            if not self._configuration.effective_enabled or generation != self._generation:
                raise RemoteChatDisabledError("Remote Chat connector generation is fenced.")
            yield self._configuration; return
        try:
            with self._config_store.generation_guard(generation) as current:
                if not current.effective_enabled:
                    raise RemoteChatDisabledError("Remote Chat connector is disabled.")
                yield current
        except RemoteConfigError as exc:
            raise RemoteChatDisabledError(
                "Remote Chat connector generation is no longer authoritative."
            ) from exc

    def _load_configuration(self) -> RemoteChatConfiguration:
        return self._configuration if self._config_store is None else self._config_store.load()

    def _disable_configuration(self) -> RemoteChatConfiguration:
        assert self._config_store is not None
        last_error: BaseException | None = None
        for _attempt in range(8):
            current = self._config_store.load()
            if not current.enabled:
                return current
            try:
                return self._config_store.set_enabled(False)
            except RemoteConfigError as exc:
                last_error = exc
        raise RemoteChatError("Remote Chat configuration changed continuously during kill.") from last_error

    def _configuration_is_current(self) -> bool:
        try:
            current = self._load_configuration()
            return current.effective_enabled and current.generation == self._generation
        except Exception:
            self._last_error = "private_configuration_unsafe"; return False

    def _fence_external_disable(self) -> None:
        with self._fence_lock:
            with self._condition:
                self._closing = self._paused = True; self._condition.notify_all()
            try:
                current = self._load_configuration()
                # A local disable may already have advanced configuration and
                # fenced the ledger while this worker was checking authority.
                # Configuration owns durable generations: a late worker must
                # not publish an extra ledger-only generation that re-enable
                # cannot reach (enable changes revision, not generation).
                target = current.generation if self._config_store is not None else self._generation + 1
            except Exception: target = self._generation + 1
            try: self._generation = self._ledger.fence_generation(target, code="external_configuration_fenced")
            except Exception: self._last_error = "external_fence_failure"; self._fatal = True
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            self._last_error = "external_fence_continuation_cleanup_failure"
            self._fatal = True
        self._safe_stop_transport()

    def _worker_fatal(self, code: str) -> None:
        failures: list[str] = []
        with self._fence_lock, self._condition:
            self._fatal = self._closing = self._paused = True
            self._last_error = code
            self._condition.notify_all()
        try:
            self._ledger.reconcile_uncertain_sends()
            for record in self._ledger.processing_records():
                if record.state == "processing": self._ledger.require_reconciliation(record, code)
        except BaseException:
            failures.append("durability_unproven")
        continuation_error = self._clear_remote_continuations()
        if continuation_error is not None:
            failures.append("continuation_cleanup_failure")
        try:
            self._transport.stop()
        except BaseException:
            failures.append("transport_stop_failure")
        if failures:
            self._last_error = code + "+" + "+".join(failures)
        operator_error(
            "remote_chat.worker.failed",
            code=self._last_error or code,
            origin="discord_remote",
        )

    def _authorized_envelope(self, envelope: RemoteInboundEnvelope, configuration: RemoteChatConfiguration) -> bool:
        return (configuration.effective_enabled and envelope.transport == "discord_remote"
            and envelope.connector_id == configuration.connector_id
            and envelope.application_id == configuration.application_id
            and envelope.bot_user_id == configuration.bot_user_id
            and envelope.installation_id == configuration.installation_id
            and envelope.external_actor_id == configuration.owner_user_id
            and (configuration.dm_channel_id is None or envelope.external_conversation_id == configuration.dm_channel_id)
            and not envelope.unsupported_content)

    def _replace_session(self, history: Sequence[ChatMessage]) -> None:
        if self._session_factory is None:
            raise RemoteChatError("Remote Chat cannot restore its exact archived Conversation history.")
        self._session = self._session_factory(tuple(history))
        if self._chat_id is not None:
            self._turns.attach_session(self._session, origin_kind=RequestOriginKind.DISCORD_REMOTE,
                                       conversation_id=self._chat_id)

    def _ledger_has_pending_work(self) -> bool:
        return bool(
            any(
                item.connector_generation == self._generation
                and item.state in {"pending", "sending"}
                for item in self._ledger.outbound_chunks()
            )
            or any(
                item.connector_generation == self._generation
                and item.state in {"accepted", "processing", "reconciliation_required"}
                for item in self._ledger.inbound_records()
            )
        )

    def _ledger_has_runnable_work(self) -> bool:
        return bool(
            any(
                item.connector_generation == self._generation
                and item.state == "pending"
                for item in self._ledger.outbound_chunks()
            )
            or any(
                item.connector_generation == self._generation
                and item.state == "accepted"
                for item in self._ledger.inbound_records()
            )
        )

    def _require_no_current_inflight_state(self) -> None:
        unresolved_inbound = any(
            item.connector_generation == self._generation
            and item.state in {"processing", "reconciliation_required"}
            for item in self._ledger.inbound_records()
        )
        unresolved_send = any(
            item.connector_generation == self._generation and item.state == "sending"
            for item in self._ledger.outbound_chunks()
        )
        if unresolved_inbound or unresolved_send:
            raise RemoteChatError(
                "Remote Chat durable in-flight state remains unresolved."
            )

    def _reconcile_stopped_state(self) -> None:
        self._ledger.reconcile_uncertain_sends()
        processing = self._ledger.processing_records()
        if not processing:
            return
        detail = self._current_chat()
        if detail is None:
            for record in processing:
                self._ledger.fail(record, "interrupted_before_archive")
            return
        self._require_provenance(detail)
        self._reconcile_processing(detail)

    def _clear_remote_continuations(self) -> BaseException | None:
        if self._search_handler is None:
            return None
        try:
            self._search_handler.clear()
        except BaseException as exc:
            return exc
        return None

    def _join_worker(self) -> None:
        worker = self._worker
        if worker is None: return
        if worker is threading.current_thread(): return
        worker.join(self._shutdown_timeout)
        if worker.is_alive():
            self._last_error = "shutdown_unproven"
            raise RemoteChatError("Remote Chat worker shutdown could not be proven.")
        self._worker = None

    def _safe_stop_transport(self) -> None:
        try: self._transport.stop()
        except Exception: self._fatal = True; self._last_error = "transport_stop_failure"

    def _call_hook(self, phase: str) -> None:
        if self._hook is not None: self._hook(phase)

def _delivery_chunks(text: str, limit: int) -> tuple[str, ...]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_REMOTE_TEXT_CHARACTERS:
        raise RemoteChatError("Remote transport advertised an unsafe physical text limit.")
    if not isinstance(text, str) or not text or len(text) > MAX_REMOTE_TEXT_CHARACTERS:
        raise RemoteChatError("Remote logical reply is outside the application bound.")
    return tuple(text[offset:offset + limit] for offset in range(0, len(text), limit))

def _turn_event_id(record: InboundRecord) -> str:
    return "event-" + record.immutable_hash[:32]
