from __future__ import annotations

import json
from io import BytesIO
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from tori import __version__
from tori.providers.base import (
    ChatMessage,
    ProviderConnectionError,
    ProviderResponseError,
)
from tori.providers.ollama import OllamaProvider
from tori.response_normalization import EXTERNAL_KNOWLEDGE_ADVISORY, normalized_response_stream
from tori.terminal_model_action import PROPOSAL_KEY, parse_model_proposal
from tori.capabilities import SourceRecord
from tori.search import format_search_answer


class FakeResponse:
    def __init__(self, document: object) -> None:
        self._body = json.dumps(document).encode("utf-8")

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore[no-untyped-def]
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


class FakeStreamingResponse:
    def __init__(self, records: list[object | bytes]) -> None:
        self._lines = [
            record if isinstance(record, bytes) else (
                json.dumps(record, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            for record in records
        ]
        self.closed = False

    def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        self.closed = True


class OllamaProviderTests(unittest.TestCase):
    @patch("tori.providers.ollama.urlopen")
    def test_gemma_streamed_proposal_keeps_hidden_channel_out_of_exact_action(self, mock_urlopen) -> None:
        envelope = json.dumps({PROPOSAL_KEY: {"command": "echo hello", "cwd": "/tmp/workspace",
                                             "scope": "PROJECT_SANDBOX"}}, separators=(",", ":"))
        records = [{"model": "gemma4:12b", "message": {"role": "assistant", "content": "",
                                              "thinking": "hidden provider reasoning"}, "done": False}]
        records.extend({"model": "gemma4:12b", "message": {"role": "assistant", "content": token},
                        "done": False} for token in envelope)
        records.append({"model": "gemma4:12b", "message": {"role": "assistant", "content": ""},
                        "done": True})
        mock_urlopen.return_value = FakeStreamingResponse(records)
        seen = []
        def resolve(content):  # type: ignore[no-untyped-def]
            seen.append(content)
            return "Terminal policy approval required" if parse_model_proposal(content) else None
        stream = self.provider.stream_chat_with_options(
            (ChatMessage("user", "Run echo hello for me."),), model="gemma4:12b",
            context_budget=4096)
        visible = "".join(normalized_response_stream(stream, model_action_handler=resolve))
        self.assertEqual(visible, "Terminal policy approval required")
        self.assertEqual(seen, [envelope])
        self.assertNotIn("hidden", visible)
        payload = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(payload["model"], "gemma4:12b")
        self.assertTrue(payload["stream"])
        self.assertNotIn("tools", payload)

    @patch("tori.providers.ollama.urlopen")
    def test_capability_classification_is_structured_not_tool_execution(self, mock_urlopen):
        content = json.dumps({"kind": "discussion", "capability": "tasks"})
        mock_urlopen.return_value = FakeResponse({
            "model": "test-model", "message": {"role": "assistant", "content": content}, "done": True,
        })
        response = self.provider.interpret_capability_intent((ChatMessage("user", "Reminders?"),), model="test-model")
        self.assertEqual(response.content, content)
        payload = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(payload["format"]["required"], ["kind", "capability"])
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertNotIn("tools", payload)

    def setUp(self) -> None:
        self.provider = OllamaProvider(
            base_url="http://127.0.0.1:11434",
            model_name="test-model",
            timeout_seconds=30,
            keep_alive="5m",
        )

    @patch("tori.providers.ollama.urlopen")
    def test_sends_non_streaming_chat_request(self, mock_urlopen) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse(
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": "Hello from Ollama."},
                "done": True,
                "prompt_eval_count": 12,
                "eval_count": 4,
            }
        )

        result = self.provider.chat(
            (
                ChatMessage(role="system", content="Identity"),
                ChatMessage(role="user", content="Hello"),
            )
        )

        self.assertEqual(result.content, "Hello from Ollama.")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.usage.prompt_tokens, 12)  # type: ignore[union-attr]
        self.assertEqual(result.usage.completion_tokens, 4)  # type: ignore[union-attr]
        self.assertEqual(result.usage.total_tokens, 16)  # type: ignore[union-attr]

        request = mock_urlopen.call_args.args[0]
        self.assertEqual(__version__, "0.9.0-public.1")
        self.assertEqual(request.headers["User-agent"], f"Tori/{__version__}")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "Identity"},
                {"role": "user", "content": "Hello"},
            ],
        )
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["keep_alive"], "5m")

    @patch("tori.providers.ollama.urlopen")
    def test_citationless_search_synthesis_is_supported_by_application_provenance(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse({
            "model": "test-model",
            "message": {"role": "assistant", "content": "A current weather summary."},
            "done": True,
        })
        synthesis = self.provider.chat((ChatMessage("user", "Weather?"),)).content
        answer = format_search_answer(
            synthesis,
            (SourceRecord("Weather source", "https://example.test/weather", "Current"),),
        )
        self.assertIn("Retrieved source records for this answer: [1]", answer)

    @patch("tori.providers.ollama.urlopen")
    def test_provider_neutral_context_budget_maps_to_num_ctx(self, mock_urlopen) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse({
            "model": "test-model",
            "message": {"role": "assistant", "content": "answer"},
            "done": True,
        })
        self.provider.chat_with_options(
            (ChatMessage("user", "Hello"),),
            model="test-model",
            context_budget=32768,
        )
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["options"], {"num_ctx": 32768})

    @patch("tori.providers.ollama.urlopen")
    def test_memory_extraction_requests_strict_provider_native_json_schema(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        content = json.dumps({"candidates": []})
        mock_urlopen.return_value = FakeResponse(
            {
                "model": "selected-model",
                "message": {"role": "assistant", "content": content},
                "done": True,
            }
        )

        result = self.provider.extract_memory_candidates(
            (ChatMessage("system", "bounded extraction contract"),),
            model="selected-model",
        )

        self.assertEqual(result.content, content)
        self.assertEqual(result.model, "selected-model")
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["model"], "selected-model")
        schema = payload["format"]
        self.assertEqual(schema["type"], "object")
        self.assertIs(schema["additionalProperties"], False)
        candidates = schema["properties"]["candidates"]
        self.assertEqual(candidates["maxItems"], 3)
        item = candidates["items"]
        self.assertIs(item["additionalProperties"], False)
        self.assertEqual(
            set(item["required"]),
            {"text", "category", "evidence", "origin"},
        )
        self.assertEqual(
            item["properties"]["category"]["enum"],
            ["general", "preference", "project", "goal", "routine", "constraint"],
        )
        self.assertEqual(
            item["properties"]["origin"]["enum"], ["direct", "inferred"]
        )

    @patch("tori.providers.ollama.urlopen")
    def test_memory_relationship_requests_strict_provider_native_json_schema(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        content = json.dumps({"relationship": "independent", "target": None})
        mock_urlopen.return_value = FakeResponse(
            {
                "model": "selected-model",
                "message": {"role": "assistant", "content": content},
                "done": True,
            }
        )

        result = self.provider.assess_memory_relationship(
            (ChatMessage("system", "bounded relationship contract"),),
            model="selected-model",
        )

        self.assertEqual(result.content, content)
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        schema = payload["format"]
        self.assertEqual(schema["type"], "object")
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), {"relationship", "target"})
        self.assertEqual(
            schema["properties"]["relationship"]["enum"],
            ["independent", "duplicate", "update", "contradiction", "uncertain"],
        )
        self.assertEqual(schema["properties"]["target"]["type"], ["string", "null"])

    @patch("tori.providers.ollama.urlopen")
    def test_task_interpretation_uses_strict_provider_native_json_schema(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        content = json.dumps({
            "intent": "none", "task_text": None, "reminder_text": None,
            "target": None, "schedule": None, "clarification": None,
        })
        mock_urlopen.return_value = FakeResponse({
            "model": "selected-model",
            "message": {"role": "assistant", "content": content},
            "done": True,
        })
        result = self.provider.interpret_task_intent(
            (ChatMessage("system", "bounded operational contract"),),
            model="selected-model",
        )
        self.assertEqual(result.content, content)
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "selected-model")
        schema = payload["format"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(
            set(schema["required"]),
            {"intent", "task_text", "reminder_text", "target", "schedule", "clarification"},
        )
        self.assertIn("create_task_with_reminder", schema["properties"]["intent"]["enum"])
        self.assertIs(schema["properties"]["schedule"]["additionalProperties"], False)

    @patch("tori.providers.ollama.urlopen")
    def test_rejects_empty_provider_response(self, mock_urlopen) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse(
            {"model": "test-model", "message": {"content": ""}}
        )

        with self.assertRaisesRegex(ProviderResponseError, "empty"):
            self.provider.chat((ChatMessage(role="user", content="Hello"),))

    @patch("tori.providers.ollama.urlopen")
    def test_dedicated_reasoning_fields_are_validated_and_never_content(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        for field in ("thinking", "reasoning", "reasoning_content"):
            with self.subTest(field=field):
                mock_urlopen.return_value = FakeResponse(
                    {
                        "model": "test-model",
                        "message": {
                            "role": "assistant",
                            "content": "Visible answer.",
                            field: "private provider reasoning",
                        },
                    }
                )
                response = self.provider.chat((ChatMessage("user", "Hi"),))
                self.assertEqual(response.content, "Visible answer.")
                self.assertNotIn("private", repr(response))

        mock_urlopen.return_value = FakeResponse(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "Visible answer.",
                    "thinking": {"private": True},
                },
            }
        )
        with self.assertRaisesRegex(ProviderResponseError, "reasoning field"):
            self.provider.chat((ChatMessage("user", "Hi"),))

    @patch("tori.providers.ollama.urlopen")
    def test_provider_declared_tool_channel_fails_without_execution(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "search", "arguments": {"query": "private"}}}
                    ],
                },
            }
        )
        with self.assertRaisesRegex(ProviderResponseError, "tool-call") as raised:
            self.provider.chat((ChatMessage("user", "Hi"),))
        self.assertNotIn("private", str(raised.exception))

    @patch("tori.providers.ollama.urlopen")
    def test_request_specific_model_is_exact_and_mismatch_is_rejected(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse(
            {
                "model": "chosen/model:Q4",
                "message": {"role": "assistant", "content": "Selected answer"},
            }
        )
        response = self.provider.chat_for_model(
            (ChatMessage("user", "Hello"),), model="chosen/model:Q4"
        )
        payload = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "chosen/model:Q4")
        self.assertEqual(response.model, "chosen/model:Q4")

        mock_urlopen.return_value = FakeResponse(
            {
                "model": "different",
                "message": {"role": "assistant", "content": "Wrong model"},
            }
        )
        with self.assertRaisesRegex(ProviderResponseError, "unexpected model"):
            self.provider.chat_for_model(
                (ChatMessage("user", "Hello"),), model="chosen/model:Q4"
            )

    @patch("tori.providers.ollama.urlopen")
    def test_catalog_normalizes_objective_inventory_without_mutation(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse(
            {
                "models": [
                    {
                        "name": "exact/Model:Q4",
                        "modified_at": "2026-08-02T00:00:00Z",
                        "size": 123,
                        "digest": "abc",
                        "details": {
                            "format": "gguf",
                            "family": "family",
                            "parameter_size": "7B",
                            "quantization_level": "Q4_K_M",
                        },
                    },
                    {"model": "minimal", "details": {}},
                ],
                "future_root_metadata": True,
            }
        )

        models = self.provider.list_models()

        self.assertEqual([item.model for item in models], ["exact/Model:Q4", "minimal"])
        self.assertTrue(all(item.provider == "ollama" for item in models))
        self.assertEqual(models[0].storage_size, 123)
        self.assertEqual(models[0].parameter_size, "7B")
        self.assertIsNone(models[1].family)
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/tags")
        self.assertIsNone(request.data)

    @patch("tori.providers.ollama.urlopen")
    def test_catalog_uses_durable_ollama_profile_id(self, mock_urlopen) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeResponse({"models": [{"name": "shared"}]})
        provider = OllamaProvider(
            profile_id="second-ollama",
            base_url="http://10.0.0.2:11434",
            model_name="shared",
            timeout_seconds=30,
            keep_alive="5m",
        )
        self.assertEqual(provider.list_models()[0].qualified_name, "second-ollama/shared")

    @patch("tori.providers.ollama.urlopen")
    def test_catalog_rejects_malformed_duplicates_and_unavailability_safely(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        cases = (
            ({}, "invalid"),
            ({"models": "wrong"}, "invalid"),
            ({"models": [{"name": "same"}, {"name": "same"}]}, "duplicate"),
            ({"models": [{"name": "bad\nname"}]}, "invalid"),
        )
        for document, message in cases:
            with self.subTest(document=document):
                mock_urlopen.return_value = FakeResponse(document)
                with self.assertRaisesRegex(ProviderResponseError, message):
                    self.provider.list_models()
        mock_urlopen.side_effect = URLError("private socket detail")
        with self.assertRaisesRegex(ProviderConnectionError, "unavailable") as raised:
            self.provider.list_models()
        self.assertNotIn("private", str(raised.exception))

        oversized = FakeResponse({})
        oversized._body = b"x" * (4 * 1024 * 1024 + 1)
        mock_urlopen.side_effect = None
        mock_urlopen.return_value = oversized
        with self.assertRaisesRegex(ProviderResponseError, "oversized"):
            self.provider.list_models()

    @patch("tori.providers.ollama.urlopen")
    def test_streams_ordered_unicode_fragments_with_configured_request(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        response = FakeStreamingResponse(
            [
                {"message": {"role": "assistant", "content": "Hello "}, "done": False},
                {"message": {"role": "assistant", "content": "café \\n"}, "done": False},
                {"message": {"role": "assistant", "content": "世界"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True,
                 "prompt_eval_count": 20, "eval_count": 5},
            ]
        )
        mock_urlopen.return_value = response
        messages = (
            ChatMessage(role="system", content="Identity"),
            ChatMessage(role="user", content="Hello"),
        )

        stream = self.provider.stream_chat(messages)
        self.assertEqual(
            list(stream),
            ["Hello ", "café \\n", "世界"],
        )
        self.assertEqual(stream.result.usage.total_tokens, 25)  # type: ignore[attr-defined,union-attr]
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["keep_alive"], "5m")
        self.assertIs(payload["stream"], True)
        self.assertEqual(request.headers["User-agent"], f"Tori/{__version__}")
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 30)
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "Identity"},
                {"role": "user", "content": "Hello"},
            ],
        )
        self.assertTrue(response.closed)

    @patch("tori.providers.ollama.urlopen")
    def test_stream_tolerates_empty_fragments(self, mock_urlopen) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeStreamingResponse(
            [
                {"message": {"role": "assistant", "content": ""}, "done": False},
                {"message": {"role": "assistant", "content": "answer"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]
        )
        self.assertEqual(
            list(self.provider.stream_chat((ChatMessage("user", "Hi"),))),
            ["answer"],
        )

    @patch("tori.providers.ollama.urlopen")
    def test_stream_preserves_split_external_knowledge_advisory(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        response = FakeStreamingResponse(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "[[TORI:EXTERNAL_",
                    },
                    "done": False,
                },
                {
                    "message": {
                        "role": "assistant",
                        "content": "KNOWLEDGE_NEEDED]]",
                    },
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                },
            ]
        )
        mock_urlopen.return_value = response
        fragments = list(
            self.provider.stream_chat((ChatMessage("user", "Obscure question"),))
        )
        self.assertEqual("".join(fragments), EXTERNAL_KNOWLEDGE_ADVISORY)
        self.assertTrue(response.closed)

    @patch("tori.providers.ollama.urlopen")
    def test_stream_withholds_dedicated_reasoning_and_rejects_tool_channel(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        mock_urlopen.return_value = FakeStreamingResponse(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "thinking": "private strategy",
                    },
                    "done": False,
                },
                {
                    "message": {
                        "role": "assistant",
                        "content": "Visible answer.",
                        "reasoning": "private correction",
                    },
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                },
            ]
        )
        self.assertEqual(
            list(self.provider.stream_chat((ChatMessage("user", "Hi"),))),
            ["", "Visible answer."],
        )

        mock_urlopen.return_value = FakeStreamingResponse(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"function": {"name": "unknown", "arguments": {}}}],
                    },
                    "done": False,
                }
            ]
        )
        with self.assertRaisesRegex(ProviderResponseError, "tool-call"):
            list(self.provider.stream_chat((ChatMessage("user", "Hi"),)))

    @patch("tori.providers.ollama.urlopen")
    def test_dedicated_reasoning_stream_can_be_cancelled_without_exposure(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        response = FakeStreamingResponse(
            [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "thinking": "private reasoning",
                    },
                    "done": False,
                },
                {
                    "message": {"role": "assistant", "content": "Visible later"},
                    "done": False,
                },
            ]
        )
        mock_urlopen.return_value = response
        stream = self.provider.stream_chat((ChatMessage("user", "Hi"),))
        self.assertEqual(next(stream), "")
        stream.close()
        self.assertTrue(response.closed)

    @patch("tori.providers.ollama.urlopen")
    def test_stream_rejects_malformed_and_premature_responses(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        cases = (
            ([b"not-json\n"], "malformed"),
            ([[]], "shape"),
            ([{"message": {"role": "assistant", "content": 7}, "done": False}], "content"),
            ([{"message": {"role": "assistant", "content": "partial"}, "done": False}], "completion"),
            ([{"message": {"role": "user", "content": "wrong"}, "done": False}], "role"),
            ([{"error": "private provider failure"}], "reported"),
        )
        for records, expected in cases:
            with self.subTest(expected=expected):
                response = FakeStreamingResponse(list(records))
                mock_urlopen.return_value = response
                with self.assertRaisesRegex(ProviderResponseError, expected):
                    list(
                        self.provider.stream_chat(
                            (ChatMessage(role="user", content="Hi"),)
                        )
                    )
                self.assertTrue(response.closed)

    @patch("tori.providers.ollama.urlopen")
    def test_stream_normalizes_http_and_transport_failures(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        http_body = BytesIO(b'{"error":"private HTTP detail"}')
        mock_urlopen.side_effect = HTTPError(
            self.provider._endpoint, 500, "failed", {}, http_body
        )
        with self.assertRaises(ProviderResponseError):
            list(self.provider.stream_chat((ChatMessage("user", "Hi"),)))
        self.assertTrue(http_body.closed)

        mock_urlopen.side_effect = URLError("private transport detail")
        with self.assertRaisesRegex(ProviderConnectionError, "connect"):
            list(self.provider.stream_chat((ChatMessage("user", "Hi"),)))

    @patch("tori.providers.ollama.urlopen")
    def test_stream_response_closes_when_iteration_is_abandoned(
        self, mock_urlopen
    ) -> None:  # type: ignore[no-untyped-def]
        response = FakeStreamingResponse(
            [
                {"message": {"role": "assistant", "content": "partial"}, "done": False},
                {"message": {"role": "assistant", "content": "later"}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]
        )
        mock_urlopen.return_value = response
        stream = self.provider.stream_chat((ChatMessage("user", "Hi"),))
        self.assertEqual(next(stream), "partial")
        stream.close()
        self.assertTrue(response.closed)


if __name__ == "__main__":
    unittest.main()
