from __future__ import annotations

import logging
import unittest

from tori.conversation import ConversationSession
from tori.conversation_application import ConversationTurnRequest, ConversationTurnService
from tori.operation_coordinator import OperationCoordinator
from tori.operator_observability import (
    operator_activity_enabled,
    operator_error,
    operator_event,
    operator_failure,
    set_operator_activity_enabled,
)
from tori.providers import ChatResponse, ModelProvider, ProviderResponseError
from tori.request_origin import RequestOrigin, RequestOriginKind
from tori.search import SearchConsent


class _Provider(ModelProvider):
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure

    def chat(self, _messages):  # type: ignore[no-untyped-def]
        if self.failure is not None:
            raise self.failure
        return ChatResponse("private assistant response", "test-model")

    def stream_chat(self, _messages):  # type: ignore[no-untyped-def]
        yield "private assistant response"


class OperatorObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        set_operator_activity_enabled(True)
        self.addCleanup(set_operator_activity_enabled, True)

    def test_conversation_events_never_emit_prompt_or_response_text(self) -> None:
        provider = _Provider()
        service = ConversationTurnService(OperationCoordinator())
        service.attach_session(
            ConversationSession(provider, model_name="test-model"),
            origin_kind=RequestOriginKind.LOCAL_WEB,
            conversation_id="chat-test",
        )
        prompt = "private prompt marker TOKEN-never-log"
        with self.assertLogs("tori.operator", logging.INFO) as captured:
            answer = service.complete(ConversationTurnRequest(
                prompt, RequestOrigin.local_web(), "chat-test", 0
            ))
        output = "\n".join(captured.output)
        self.assertEqual(answer, "private assistant response")
        self.assertIn("conversation.turn.completed", output)
        self.assertIn("provider.turn.started", output)
        self.assertNotIn(prompt, output)
        self.assertNotIn(answer, output)
        self.assertNotIn("TOKEN-never-log", output)

    def test_failure_traceback_replaces_sensitive_exception_message(self) -> None:
        secret = "discord-token-PRIVATE-MARKER"
        error = ProviderResponseError("provider failed with " + secret)
        with self.assertLogs("tori.operator", logging.ERROR) as captured:
            operator_failure(
                "provider.turn.failed",
                error,
                code="provider_error",
                traceback=True,
                origin="discord_remote",
            )
        output = "\n".join(captured.output)
        self.assertIn("ProviderResponseError", output)
        self.assertIn("provider_error", output)
        self.assertNotIn(secret, output)
        self.assertNotIn("provider failed with", output)

    def test_consent_events_never_emit_search_query(self) -> None:
        query = "private search query marker"
        consent = SearchConsent(clock=lambda: 10.0)
        with self.assertLogs("tori.operator", logging.INFO) as captured:
            consent.propose(query, "chat")
            self.assertEqual(consent.resolve("yes", "chat"), ("affirmative", query))
        output = "\n".join(captured.output)
        self.assertIn("search.consent.created", output)
        self.assertIn("search.consent.accepted", output)
        self.assertNotIn(query, output)

    def test_untrusted_operator_value_is_redacted(self) -> None:
        secret = "secret value with spaces TOKEN-never-log"
        with self.assertLogs("tori.operator", logging.INFO) as captured:
            operator_event("test.event", provider=secret)
        output = "\n".join(captured.output)
        self.assertIn("provider=redacted", output)
        self.assertNotIn(secret, output)

    def test_activity_off_suppresses_info_but_never_errors_and_on_resumes(self) -> None:
        normal_secret = "private prompt marker must never appear"
        error_secret = "private discord token must never appear"
        with self.assertLogs("tori.operator", logging.INFO) as captured:
            set_operator_activity_enabled(False)
            operator_event("conversation.turn.started", origin="discord_remote")
            operator_error(
                "remote_chat.worker.failed",
                code="runtime_error",
                detail=error_secret,
            )
            operator_failure(
                "remote_chat.transport.failed",
                RuntimeError(error_secret),
                code="transport_error",
                traceback=True,
            )
            set_operator_activity_enabled(True)
            operator_event(
                "conversation.turn.completed",
                origin="local_web",
                detail=normal_secret,
            )
        output = "\n".join(captured.output)
        self.assertTrue(operator_activity_enabled())
        self.assertNotIn("conversation.turn.started", output)
        self.assertIn("remote_chat.worker.failed", output)
        self.assertIn("remote_chat.transport.failed", output)
        self.assertIn("conversation.turn.completed", output)
        self.assertNotIn(normal_secret, output)
        self.assertNotIn(error_secret, output)


if __name__ == "__main__":
    unittest.main()
