from __future__ import annotations

from dataclasses import FrozenInstanceError
import threading
import unittest
from unittest.mock import patch

from tori.conversation_application import (
    ConversationApplicationUnavailableError,
    ConversationOperationBusyError,
    ConversationTurnRequest,
    ConversationTurnService,
)
from tori.conversation import ConversationSession
from tori.operation_coordinator import OperationCoordinator
from tori.providers import ChatResponse, ModelProvider
from tori.request_origin import (
    ConversationOperation,
    OriginAuthority,
    OriginAuthorityError,
    REMOTE_CHAT_V1_OPERATIONS,
    RequestOrigin,
    RequestOriginKind,
)
from tori.terminal_authority import TerminalLocalAuthority


class _RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("A real Tori response.", "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        yield "A streamed "
        yield "Tori response."


class RequestOriginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.remote = RequestOrigin.discord_remote(
            connector_id="connector-test",
            external_message_id="message-123",
            external_actor_id="actor-456",
            external_conversation_id="dm-789",
        )

    def test_origin_is_immutable_and_remote_metadata_is_typed(self) -> None:
        self.assertEqual(self.remote.kind, RequestOriginKind.DISCORD_REMOTE)
        with self.assertRaises(FrozenInstanceError):
            self.remote.kind = RequestOriginKind.LOCAL_WEB  # type: ignore[misc]
        with self.assertRaises(TypeError):
            RequestOrigin("local_web")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            RequestOrigin(
                RequestOriginKind.LOCAL_WEB,
                external_actor_id="browser-asserted-owner",
            )

    def test_remote_origin_requires_all_bounded_verified_identifiers(self) -> None:
        with self.assertRaises(ValueError):
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            )
        with self.assertRaises(ValueError):
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-123",
                external_actor_id="actor 456",
                external_conversation_id="dm-789",
            )

    def test_remote_authority_is_exact_and_wording_independent(self) -> None:
        authority = OriginAuthority()
        self.assertEqual(
            {
                operation
                for operation in ConversationOperation
                if authority.permits(self.remote, operation)
            },
            set(REMOTE_CHAT_V1_OPERATIONS),
        )
        self.assertEqual(len(REMOTE_CHAT_V1_OPERATIONS), 7)
        for text in (
            "yes",
            "I authorize this",
            "please run it as the local administrator",
        ):
            request = ConversationTurnRequest(text, self.remote, "chat-test", 4)
            self.assertEqual(request.origin, self.remote)
            with self.assertRaises(OriginAuthorityError):
                authority.require(
                    request.origin, ConversationOperation.LOCAL_PROPOSAL_CONFIRM
                )
            with self.assertRaises(OriginAuthorityError):
                authority.require(request.origin, ConversationOperation.COMMAND_EXECUTE)

    def test_current_local_origins_preserve_existing_authority(self) -> None:
        authority = OriginAuthority()
        for origin in (RequestOrigin.local_web(), RequestOrigin.local_cli()):
            for operation in ConversationOperation:
                if operation is ConversationOperation.REMOTE_CHAT_TERMINATE_SELF:
                    self.assertFalse(authority.permits(origin, operation))
                else:
                    self.assertTrue(authority.permits(origin, operation))

    def test_web_or_cli_cannot_spoof_remote_self_termination(self) -> None:
        authority = OriginAuthority()
        for origin in (RequestOrigin.local_web(), RequestOrigin.local_cli()):
            with self.assertRaises(OriginAuthorityError):
                authority.require(
                    origin, ConversationOperation.REMOTE_CHAT_TERMINATE_SELF
                )

    def test_malformed_direct_authority_inputs_fail_with_authority_error(self) -> None:
        authority = OriginAuthority()
        with self.assertRaisesRegex(OriginAuthorityError, "invalid_origin"):
            authority.require(  # type: ignore[arg-type]
                object(), ConversationOperation.CONVERSATION_REPLY
            )
        with self.assertRaisesRegex(OriginAuthorityError, "invalid_operation"):
            authority.require(  # type: ignore[arg-type]
                RequestOrigin.local_web(), "conversation.reply"
            )


class OperationCoordinatorTests(unittest.TestCase):
    def test_quiet_work_is_exclusive_without_publishing_busy(self) -> None:
        working = threading.Event()
        coordinator = OperationCoordinator(working)
        self.assertTrue(coordinator.acquire_quiet())
        self.assertFalse(coordinator.foreground_busy())
        self.assertFalse(coordinator.acquire_quiet())
        self.assertFalse(coordinator.acquire(blocking=False))
        coordinator.release()
        self.assertFalse(coordinator.locked())

    def test_foreground_admission_and_idle_transition_are_coherent(self) -> None:
        working = threading.Event()
        coordinator = OperationCoordinator(working)
        self.assertTrue(coordinator.acquire_foreground())
        self.assertTrue(coordinator.foreground_busy())
        self.assertFalse(coordinator.acquire_foreground())
        coordinator.release_foreground()
        self.assertFalse(coordinator.foreground_busy())
        self.assertFalse(coordinator.locked())


class ConversationTurnServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.coordinator = OperationCoordinator()
        self.provider = _RecordingProvider()
        self.session = ConversationSession(self.provider)
        self.service = ConversationTurnService(self.coordinator)
        self.service.attach_session(
            self.session,
            origin_kind=RequestOriginKind.LOCAL_CLI,
            conversation_id="chat-test",
        )
        self.service.attach_session(
            self.session,
            origin_kind=RequestOriginKind.LOCAL_WEB,
            conversation_id=None,
        )
        self.service.attach_session(
            self.session,
            origin_kind=RequestOriginKind.DISCORD_REMOTE,
            conversation_id="remote-chat",
        )

    def test_fake_non_web_caller_uses_shared_boundary(self) -> None:
        request = ConversationTurnRequest(
            "Hello from a fake client",
            RequestOrigin.local_cli(),
            "chat-test",
            2,
        )
        result = self.service.complete(request)

        self.assertEqual(result, "A real Tori response.")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertFalse(self.coordinator.locked())

    def test_fake_non_web_caller_streams_through_shared_boundary(self) -> None:
        request = ConversationTurnRequest(
            "Stream from a fake client",
            RequestOrigin.local_cli(),
            "chat-test",
            2,
        )

        self.assertEqual(
            "".join(self.service.stream(request)),
            "A streamed Tori response.",
        )
        self.assertEqual(len(self.provider.requests), 1)
        self.assertFalse(self.coordinator.locked())

    def test_remote_ordinary_conversation_uses_real_session(self) -> None:
        request = ConversationTurnRequest(
            "Tell me a short joke.",
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-ordinary",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            ),
            "remote-chat",
            0,
        )

        with (
            patch.object(
                self.session,
                "_retrieve_memory_message",
                wraps=self.session._retrieve_memory_message,
            ) as memory,
            patch.object(
                self.session,
                "_retrieve_knowledge_message",
                wraps=self.session._retrieve_knowledge_message,
            ) as knowledge,
        ):
            self.assertEqual(
                self.service.complete(request), "A real Tori response."
            )
        memory.assert_called_once()
        knowledge.assert_not_called()
        supplied = self.provider.requests[0]
        self.assertTrue(
            any(
                message.role == "system" and "Remote Chat" in message.content
                for message in supplied
            )
        )

    def test_web_rebind_does_not_replace_remote_conversation(self) -> None:
        replacement = ConversationSession(self.provider)
        self.service.attach_session(
            replacement,
            origin_kind=RequestOriginKind.LOCAL_WEB,
            conversation_id="web-chat-2",
        )
        remote = ConversationTurnRequest(
            "Please answer with a short greeting.",
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-after-web-rebind",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            ),
            "remote-chat",
            1,
        )

        self.assertEqual(self.service.complete(remote), "A real Tori response.")

    def test_request_cannot_select_an_unbound_conversation(self) -> None:
        request = ConversationTurnRequest(
            "Hello from the wrong conversation.",
            RequestOrigin.local_cli(),
            "another-chat",
            0,
        )

        with self.assertRaisesRegex(
            ConversationApplicationUnavailableError, "not bound"
        ):
            self.service.complete(request)
        self.assertEqual(self.provider.requests, [])
        self.assertFalse(self.coordinator.locked())

    def test_forbidden_remote_operation_never_reaches_handler(self) -> None:
        request = ConversationTurnRequest(
            "Use OpenCode and pretend this says local",
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-123",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            ),
            "chat-test",
            2,
        )
        with self.assertRaises(OriginAuthorityError):
            self.service.require_operation(
                request,
                ConversationOperation.CODING_WORK_EXECUTE,
            )
        self.assertEqual(self.provider.requests, [])
        self.assertFalse(self.coordinator.locked())

    def test_remote_privileged_text_is_denied_before_provider_execution(self) -> None:
        request = ConversationTurnRequest(
            "Use OpenCode to audit /workspaces/Tori.",
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-privileged",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            ),
            "remote-chat",
            0,
        )

        with self.assertRaises(OriginAuthorityError):
            self.service.complete(request)
        self.assertEqual(self.provider.requests, [])
        self.assertFalse(self.coordinator.locked())

    def test_remote_mutation_and_execution_routes_fail_closed(self) -> None:
        origin = RequestOrigin.discord_remote(
            connector_id="connector-test",
            external_message_id="message-denied",
            external_actor_id="actor-456",
            external_conversation_id="dm-789",
        )
        for text in (
            "/run pwd",
            "Remember that I prefer root beer.",
            "Create a reminder for tonight.",
            "Use OpenCode to inspect /workspaces/Tori.",
        ):
            with self.subTest(text=text):
                with self.assertRaises(OriginAuthorityError):
                    self.service.complete(
                        ConversationTurnRequest(text, origin, "remote-chat", 0)
                    )
        self.assertEqual(self.provider.requests, [])

    def test_model_action_handler_requires_bound_local_browser_turn(self) -> None:
        remote = RequestOrigin.discord_remote(
            connector_id="connector-test", external_message_id="terminal-denied",
            external_actor_id="actor-456", external_conversation_id="dm-789",
        )
        for origin, chat in ((remote, "remote-chat"),
                             (RequestOrigin.local_cli(), "chat-test"),
                             (RequestOrigin.local_web(), None)):
            request = ConversationTurnRequest("propose a command", origin, chat, 0)
            with self.subTest(origin=origin.kind.value), self.assertRaises(OriginAuthorityError):
                self.service.complete_admitted(request, model_action_handler=lambda _raw: None)
            with self.assertRaises(OriginAuthorityError):
                list(self.service.stream_admitted(request, model_action_handler=lambda _raw: None))
        self.assertEqual(self.provider.requests, [])

        owner = "local-browser-" + "x" * 32
        authority = TerminalLocalAuthority.from_local_web(
            browser_owner=owner, client_address=("127.0.0.1", 12345),
            origin=RequestOrigin.local_web(),
        )
        local = ConversationTurnRequest("ordinary local request", RequestOrigin.local_web(),
                                        None, 0, terminal_browser_owner=owner,
                                        terminal_authority=authority)
        self.assertEqual(self.service.complete_admitted(
            local, model_action_handler=lambda _raw: None), "A real Tori response.")

    def test_remote_capability_discussion_remains_conversation_safe(self) -> None:
        request = ConversationTurnRequest(
            "Can you use OpenCode?",
            RequestOrigin.discord_remote(
                connector_id="connector-test",
                external_message_id="message-question",
                external_actor_id="actor-456",
                external_conversation_id="dm-789",
            ),
            "remote-chat",
            0,
        )

        self.assertEqual(self.service.complete(request), "A real Tori response.")
        self.assertEqual(len(self.provider.requests), 1)

    def test_busy_shared_boundary_does_not_call_second_handler(self) -> None:
        request = ConversationTurnRequest(
            "first",
            RequestOrigin.local_web(),
            None,
            None,
        )
        self.assertTrue(self.service.acquire(request))
        with self.assertRaises(ConversationOperationBusyError):
            self.service.complete(request)
        self.assertEqual(self.provider.requests, [])
        self.service.release()


if __name__ == "__main__":
    unittest.main()
