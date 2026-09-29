from __future__ import annotations

from io import BytesIO
import json
import socket
import unittest
from urllib.error import HTTPError, URLError

from tori.providers import (
    ChatMessage,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderMalformedResponseError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from tori.providers.openai_compatible import (
    DUMMY_BEARER_TOKEN,
    OpenAICompatibleProvider,
)
from tori.capabilities import SourceRecord
from tori.search import format_search_answer


class FakeResponse:
    def __init__(self, body: object, *, stream: bool = False) -> None:
        if stream:
            self._body = BytesIO(b"".join(body))  # type: ignore[arg-type]
        else:
            self._body = BytesIO(json.dumps(body).encode("utf-8"))
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):  # type: ignore[no-untyped-def]
        self.close()
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def readline(self, size: int = -1) -> bytes:
        return self._body.readline(size)

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, responses=(), error: Exception | None = None):  # type: ignore[no-untyped-def]
        self.responses = list(responses)
        self.error = error
        self.requests = []

    def open(self, request, timeout):  # type: ignore[no-untyped-def]
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def event(document: object) -> bytes:
    return b"data: " + json.dumps(document).encode("utf-8") + b"\n\n"


class OpenAICompatibleProviderTests(unittest.TestCase):
    def test_capability_classification_is_structured_not_tool_execution(self):
        content = json.dumps({"kind": "discussion", "capability": "tasks"})
        opener = FakeOpener((FakeResponse({
            "model": "shared", "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        }),))
        result = self.provider(opener).interpret_capability_intent((ChatMessage("user", "Reminders?"),), model="shared")
        self.assertEqual(result.content, content)
        payload = json.loads(opener.requests[0][0].data)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", payload)

    def provider(self, opener: FakeOpener, *, auth: str = "none") -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            profile_id="lab", base_url="http://10.0.0.8:8000/v1",
            model_name="shared", timeout_seconds=30,
            authentication=auth, opener=opener,  # type: ignore[arg-type]
        )

    def test_adapter_requires_one_canonical_v1_api_root(self) -> None:
        for value in (
            "http://10.0.0.8:8000",
            "http://10.0.0.8:8000/",
            "http://10.0.0.8:8000/api",
            "http://10.0.0.8:8000/v1/",
            "http://10.0.0.8:8000/v1/v1",
            "http://user@10.0.0.8:8000/v1",
            "http://10.0.0.8/v1",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "canonical /v1"):
                OpenAICompatibleProvider(
                    profile_id="lab",
                    base_url=value,
                    model_name="shared",
                    timeout_seconds=30,
                    opener=FakeOpener(),  # type: ignore[arg-type]
                )

    def test_complete_validates_model_content_and_usage(self) -> None:
        opener = FakeOpener((FakeResponse({
            "model": "shared", "choices": [{
                "message": {"role": "assistant", "content": " Local answer. "},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        }),))
        result = self.provider(opener).chat((ChatMessage("user", "Hello"),))
        self.assertEqual(result.content, "Local answer.")
        self.assertEqual(result.usage.prompt_tokens, 11)  # type: ignore[union-attr]
        request = opener.requests[0][0]
        self.assertEqual(request.full_url, "http://10.0.0.8:8000/v1/chat/completions")
        self.assertNotIn("Authorization", request.headers)
        payload = json.loads(request.data)
        self.assertEqual(payload["stream"], False)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("stream_options", payload)

    def test_citationless_search_synthesis_is_supported_by_application_provenance(self) -> None:
        opener = FakeOpener((FakeResponse({
            "model": "shared",
            "choices": [{
                "message": {"role": "assistant", "content": "A current weather summary."},
                "finish_reason": "stop",
            }],
        }),))
        synthesis = self.provider(opener).chat((ChatMessage("user", "Weather?"),)).content
        answer = format_search_answer(
            synthesis,
            (SourceRecord("Weather source", "https://example.test/weather", "Current"),),
        )
        self.assertIn("Retrieved source records for this answer: [1]", answer)

    def test_complete_contains_reasoning_and_returns_only_visible_content(self) -> None:
        opener = FakeOpener((FakeResponse({
            "model": "shared", "choices": [{
                "message": {
                    "role": "assistant",
                    "reasoning": "private reasoning must remain contained",
                    "content": " Visible answer. ",
                },
                "finish_reason": "stop",
            }],
        }),))
        result = self.provider(opener).chat((ChatMessage("user", "Hello"),))
        self.assertEqual(result.content, "Visible answer.")
        self.assertNotIn("private reasoning", result.content)

    def test_structured_output_is_added_only_to_auxiliary_calls(self) -> None:
        responses = (
            FakeResponse({
                "model": "shared", "choices": [{
                    "message": {"role": "assistant", "content": "ordinary text"},
                    "finish_reason": "stop",
                }],
            }),
            FakeResponse({
                "model": "shared", "choices": [{
                    "message": {"role": "assistant", "content": '{"items":[]}'},
                    "finish_reason": "stop",
                }],
            }),
        )
        opener = FakeOpener(responses)
        provider = self.provider(opener)
        provider.chat((ChatMessage("user", "ordinary"),))
        provider.extract_memory_candidates(
            (ChatMessage("system", "Return JSON."),), model="shared"
        )
        ordinary = json.loads(opener.requests[0][0].data)
        auxiliary = json.loads(opener.requests[1][0].data)
        self.assertNotIn("response_format", ordinary)
        self.assertEqual(
            auxiliary["response_format"], {"type": "json_object"}
        )

    def test_stream_exposes_terminal_metadata_only_after_exhaustion(self) -> None:
        response = FakeResponse((
            event({"model": "shared", "choices": [{"delta": {
                "reasoning": "First private reasoning fragment.", "content": "",
            }, "finish_reason": None}]}),
            event({"model": "shared", "choices": [{"delta": {
                "reasoning": "Second private reasoning fragment.", "content": "",
            }, "finish_reason": None}]}),
            event({"model": "shared", "choices": [{"delta": {"content": "One "}, "finish_reason": None}]}),
            event({"model": "shared", "choices": [{"delta": {"content": "two."}, "finish_reason": "stop"}]}),
            event({"model": "shared", "choices": [], "usage": {
                "prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11,
            }}),
            b"data: [DONE]\n\n",
        ), stream=True)
        stream = self.provider(FakeOpener((response,))).stream_chat_for_model(
            (ChatMessage("user", "Hello"),), model="shared"
        )
        self.assertIsNone(stream.result)  # type: ignore[attr-defined]
        self.assertEqual(list(stream), ["One ", "two."])
        self.assertEqual(stream.result.model, "shared")  # type: ignore[attr-defined,union-attr]
        self.assertEqual(stream.result.usage.total_tokens, 11)  # type: ignore[attr-defined,union-attr]
        self.assertTrue(response.closed)

    def test_reasoning_only_stream_fails_without_visible_output(self) -> None:
        response = FakeResponse((
            event({"model": "shared", "choices": [{
                "delta": {"reasoning": "private only", "content": ""},
                "finish_reason": None,
            }]}),
            event({"model": "shared", "choices": [{
                "delta": {"reasoning": "", "content": ""},
                "finish_reason": "stop",
            }]}),
            b"data: [DONE]\n\n",
        ), stream=True)
        stream = self.provider(FakeOpener((response,))).stream_chat(
            (ChatMessage("user", "Hello"),)
        )
        with self.assertRaisesRegex(ProviderMalformedResponseError, "empty"):
            list(stream)
        self.assertIsNone(stream.result)  # type: ignore[attr-defined]
        self.assertTrue(response.closed)

    def test_malformed_reasoning_type_fails_safely(self) -> None:
        complete = FakeResponse({
            "model": "shared", "choices": [{
                "message": {
                    "role": "assistant", "reasoning": ["not text"],
                    "content": "visible",
                },
                "finish_reason": "stop",
            }],
        })
        with self.assertRaisesRegex(
            ProviderMalformedResponseError, "reasoning metadata"
        ):
            self.provider(FakeOpener((complete,))).chat(
                (ChatMessage("user", "Hello"),)
            )

        stream_response = FakeResponse((
            event({"model": "shared", "choices": [{
                "delta": {"reasoning": {"not": "text"}, "content": "visible"},
                "finish_reason": "stop",
            }]}),
            b"data: [DONE]\n\n",
        ), stream=True)
        with self.assertRaisesRegex(
            ProviderMalformedResponseError, "reasoning metadata"
        ):
            list(self.provider(FakeOpener((stream_response,))).stream_chat(
                (ChatMessage("user", "Hello"),)
            ))

    def test_catalog_and_dummy_bearer_are_bounded(self) -> None:
        opener = FakeOpener((FakeResponse({"data": [{"id": "shared"}, {"id": "other"}]}),))
        models = self.provider(opener, auth="dummy_bearer").list_models()
        self.assertEqual([item.qualified_name for item in models], ["lab/shared", "lab/other"])
        request = opener.requests[0][0]
        self.assertEqual(request.full_url, "http://10.0.0.8:8000/v1/models")
        self.assertEqual(request.headers["Authorization"], f"Bearer {DUMMY_BEARER_TOKEN}")

    def test_environment_bearer_uses_only_the_supplied_local_token(self) -> None:
        opener = FakeOpener((FakeResponse({"data": [{"id": "shared"}]}),))
        provider = OpenAICompatibleProvider(
            profile_id="lm_studio", base_url="http://127.0.0.1:1234/v1",
            model_name="shared", timeout_seconds=30,
            authentication="environment_bearer",
            credential_environment="LM_API_TOKEN",
            environ={"LM_API_TOKEN": "local-test-token"},
            opener=opener,  # type: ignore[arg-type]
        )

        self.assertEqual([item.model for item in provider.list_models()], ["shared"])
        self.assertEqual(
            opener.requests[0][0].headers["Authorization"],
            "Bearer local-test-token",
        )

    def test_missing_environment_bearer_fails_before_transport(self) -> None:
        opener = FakeOpener()
        provider = OpenAICompatibleProvider(
            profile_id="lm_studio", base_url="http://127.0.0.1:1234/v1",
            model_name="shared", timeout_seconds=30,
            authentication="environment_bearer",
            credential_environment="LM_API_TOKEN", environ={},
            opener=opener,  # type: ignore[arg-type]
        )

        with self.assertRaises(ProviderAuthenticationError):
            provider.list_models()
        self.assertEqual(opener.requests, [])

    def test_stored_bearer_takes_precedence_over_environment(self) -> None:
        opener = FakeOpener((FakeResponse({"data": [{"id": "shared"}]}),))
        provider = OpenAICompatibleProvider(
            profile_id="lm_studio", base_url="http://127.0.0.1:1234/v1",
            model_name="shared", timeout_seconds=30,
            authentication="environment_bearer",
            credential_environment="LM_API_TOKEN",
            bearer_token="stored-local-token",
            environ={"LM_API_TOKEN": "environment-token"},
            opener=opener,  # type: ignore[arg-type]
        )
        provider.list_models()
        self.assertEqual(
            opener.requests[0][0].headers["Authorization"],
            "Bearer stored-local-token",
        )

    def test_http_authentication_failure_is_safe_and_distinct(self) -> None:
        error = HTTPError(
            "http://127.0.0.1:1234/v1/models", 401, "unauthorized",
            {}, BytesIO(b"secret server detail"),
        )
        with self.assertRaises(ProviderAuthenticationError) as captured:
            self.provider(FakeOpener(error=error)).list_models()
        self.assertNotIn("secret", str(captured.exception))

    def test_malformed_tool_model_and_transport_fail_safely(self) -> None:
        documents = (
            {"model": "other", "choices": []},
            {"model": "shared", "choices": [{
                "message": {"role": "assistant", "content": "x", "tool_calls": [{}]},
                "finish_reason": "tool_calls",
            }]},
            {"model": "shared", "choices": [{
                "message": {"role": "assistant", "content": ["multimodal"]},
                "finish_reason": "stop",
            }]},
        )
        for document in documents:
            with self.subTest(document=document), self.assertRaises(ProviderResponseError):
                self.provider(FakeOpener((FakeResponse(document),))).chat(
                    (ChatMessage("user", "Hello"),)
                )
        with self.assertRaises(ProviderConnectionError) as captured:
            self.provider(FakeOpener(error=URLError("secret endpoint diagnostic"))).chat(
                (ChatMessage("user", "Hello"),)
            )
        self.assertNotIn("secret", str(captured.exception))

    def test_timeout_is_distinct_from_connection_failure(self) -> None:
        for error in (socket.timeout("private timeout"), URLError(socket.timeout("wrapped"))):
            with self.subTest(error=type(error).__name__), self.assertRaises(
                ProviderTimeoutError
            ) as captured:
                self.provider(FakeOpener(error=error)).chat(
                    (ChatMessage("user", "Hello"),)
                )
            self.assertNotIn("private", str(captured.exception))

        with self.assertRaises(ProviderTimeoutError):
            self.provider(FakeOpener(error=socket.timeout("catalog timeout"))).list_models()

    def test_stream_requires_done_and_rejects_nonstop_finish(self) -> None:
        for lines in (
            (event({"model": "shared", "choices": [{"delta": {"content": "x"}, "finish_reason": None}]}),),
            (event({"model": "shared", "choices": [{"delta": {"content": "x"}, "finish_reason": None}]}), b"data: [DONE]\n\n"),
            (event({"model": "shared", "choices": [{"delta": {"tool_calls": [{}]}, "finish_reason": "tool_calls"}]}), b"data: [DONE]\n\n"),
        ):
            with self.subTest(lines=lines), self.assertRaises(ProviderResponseError):
                list(self.provider(FakeOpener((FakeResponse(lines, stream=True),))).stream_chat(
                    (ChatMessage("user", "Hello"),)
                ))


if __name__ == "__main__":
    unittest.main()
