from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.app import run_once
from tori.chats import ChatService
from tori.conversation import ConversationSession
from tori.conversation_archive import ConversationArchiveStore
from tori.providers import ChatMessage, ChatResponse, ModelProvider, ProviderResponseError
from tori.response_normalization import (
    EXTERNAL_KNOWLEDGE_ADVISORY,
    ExternalKnowledgeNeededAdvisory,
    MAX_TOOL_SHAPED_RESPONSE_CHARACTERS,
    normalize_model_response,
    normalized_response_stream,
)


class FixtureProvider(ModelProvider):
    def __init__(self, response: str, *, fragments: tuple[str, ...] | None = None) -> None:
        self.response = response
        self.fragments = fragments
        self.requests = 0
        self.closed = 0

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests += 1
        return ChatResponse(self.response, "fixture-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests += 1
        try:
            yield from self.fragments if self.fragments is not None else (self.response,)
        finally:
            self.closed += 1


class PseudoToolContainmentTests(unittest.TestCase):
    def test_external_knowledge_advisory_is_exact_internal_control_data(self) -> None:
        valid = (
            EXTERNAL_KNOWLEDGE_ADVISORY,
            f" \n{EXTERNAL_KNOWLEDGE_ADVISORY}\n ",
            f"```\n{EXTERNAL_KNOWLEDGE_ADVISORY}\n```",
            f"```text\n {EXTERNAL_KNOWLEDGE_ADVISORY} \n```",
            f"`{EXTERNAL_KNOWLEDGE_ADVISORY}`",
        )
        for advisory in valid:
            with self.subTest(advisory=advisory):
                with self.assertRaises(ExternalKnowledgeNeededAdvisory):
                    normalize_model_response(advisory)
        for invalid in (
            f"Ordinary answer. {EXTERNAL_KNOWLEDGE_ADVISORY}",
            f"{EXTERNAL_KNOWLEDGE_ADVISORY} extra",
            f"```python\n{EXTERNAL_KNOWLEDGE_ADVISORY}\n```",
            f"```\nanswer\n{EXTERNAL_KNOWLEDGE_ADVISORY}\n```",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ProviderResponseError):
                normalize_model_response(invalid)
        with self.assertRaises(ProviderResponseError):
            normalize_model_response(
                EXTERNAL_KNOWLEDGE_ADVISORY,
                allow_external_knowledge_advisory=False,
            )
        self.assertEqual(
            normalize_model_response("I'm not sure; here is what I do know."),
            "I'm not sure; here is what I do know.",
        )

    def test_stream_never_yields_advisory_control_data(self) -> None:
        streams = (
            (EXTERNAL_KNOWLEDGE_ADVISORY,),
            (" \n[[TORI:EXTERNAL_", "KNOWLEDGE_NEEDED]]\n "),
            ("```\n[[TORI:EXTERNAL_", "KNOWLEDGE_NEEDED]]\n```"),
        )
        for fragments in streams:
            with self.subTest(fragments=fragments):
                yielded: list[str] = []
                with self.assertRaises(ExternalKnowledgeNeededAdvisory):
                    yielded.extend(normalized_response_stream(iter(fragments)))
                self.assertFalse(any(yielded))

    def test_malformed_tori_control_lookalikes_never_become_visible(self) -> None:
        malformed = (
            "[[TORI_EXTERNAL_KNOWLEDGE_NEEDED]]",
            "[[TORI:EXTERNAL_KNOWLEDGE_NEEDED",
            "Ordinary prefix. [[TORI_EXTERNAL_KNOWLEDGE_NEEDED]]",
            "Ordinary prefix. [[ TORI : EXTERNAL_KNOWLEDGE_NEEDED ]]",
        )
        for content in malformed:
            with self.subTest(content=content):
                with self.assertRaisesRegex(ProviderResponseError, "control"):
                    normalize_model_response(content)

        yielded: list[str] = []
        with self.assertRaisesRegex(ProviderResponseError, "control"):
            yielded.extend(normalized_response_stream(iter((
                "[[TORI_EXTERNAL_", "KNOWLEDGE_NEEDED]]",
            ))))
        self.assertFalse(any(yielded))

        yielded = []
        with self.assertRaisesRegex(ProviderResponseError, "control"):
            yielded.extend(normalized_response_stream(iter((
                "Ordinary prefix. ", "[[TORI_EXTERNAL_", "KNOWLEDGE_NEEDED]]",
            ))))
        self.assertNotIn("TORI_EXTERNAL", "".join(yielded))

    def test_observed_and_formatted_tool_shapes_are_rejected_narrowly(self) -> None:
        fixtures = (
            '{"tool":"search","recency_days":-1,"source":"","query":"current members"}',
            '{"name":"search","arguments":{"query":"current members"}}',
            '  { "tool" : "unknown", "query" : "value" }  ',
            '```json\n{"name":"search","arguments":{"query":"value"}}\n```',
            '{"tool":"search","query":"value","unapproved":true}',
            '{"name":"unknown","arguments":{}}',
        )
        for content in fixtures:
            with self.subTest(content=content), self.assertRaisesRegex(
                ProviderResponseError, "tool-call"
            ):
                normalize_model_response(content)

    def test_malformed_and_oversized_tool_shapes_fail_without_echo(self) -> None:
        fixtures = (
            '{"tool":"search","query":',
            '```json\n{"name":"search","arguments":',
            '{"tool":"search","query":"' + (
                "x" * MAX_TOOL_SHAPED_RESPONSE_CHARACTERS
            ),
        )
        for content in fixtures:
            with self.subTest(length=len(content)):
                with self.assertRaises(ProviderResponseError) as raised:
                    normalize_model_response(content)
                self.assertNotIn("search", str(raised.exception).casefold())
                self.assertNotIn("arguments", str(raised.exception).casefold())

    def test_ordinary_json_and_tool_discussion_remain_supported(self) -> None:
        ordinary = (
            '{"answer":"structured legitimate JSON","items":[1,2]}',
            '[{"name":"search","arguments":{"query":"example"}}]',
            'A tool-call example is {"name":"search","arguments":{}}.',
        )
        for content in ordinary:
            with self.subTest(content=content):
                self.assertEqual(normalize_model_response(content), content)

    def test_streamed_pseudo_tool_is_never_yielded_or_committed(self) -> None:
        provider = FixtureProvider(
            "",
            fragments=(
                '{"name":"sea',
                'rch","arguments":{"query":"current members"}}',
            ),
        )
        session = ConversationSession(provider)
        stream = session.stream("Please run the tool search")
        visible: list[str] = []
        with self.assertRaisesRegex(ProviderResponseError, "tool-call"):
            for fragment in stream:
                if fragment:
                    visible.append(fragment)
        self.assertEqual(visible, [])
        self.assertEqual(session.history, ())
        self.assertEqual(provider.requests, 1)
        self.assertEqual(provider.closed, 1)


class ReasoningNormalizationTests(unittest.TestCase):
    def test_complete_leading_reasoning_is_removed_but_xml_examples_remain(self) -> None:
        self.assertEqual(
            normalize_model_response(
                "  <think>private drafting and correction</think>\nFinal answer."
            ),
            "Final answer.",
        )
        example = "An XML-like example is <think>visible sample</think>."
        self.assertEqual(normalize_model_response(example), example)

        provider = FixtureProvider(
            "",
            fragments=("An XML-like example is <think>visible ", "sample</think>."),
        )
        session = ConversationSession(provider)
        self.assertEqual("".join(session.stream("Show an example")), example)

    def test_split_reasoning_tags_and_content_never_become_visible_history(self) -> None:
        provider = FixtureProvider(
            "",
            fragments=(" <thi", "nk>private strategy", "</th", "ink>Final ", "answer."),
        )
        session = ConversationSession(provider)
        visible = [fragment for fragment in session.stream("Question") if fragment]
        self.assertEqual(visible, ["Final answer."])
        self.assertEqual(
            session.history,
            (
                ChatMessage("user", "Question"),
                ChatMessage("assistant", "Final answer."),
            ),
        )
        self.assertNotIn("private", repr(session.history))

    def test_malformed_unterminated_closing_only_and_empty_final_fail(self) -> None:
        fixtures = (
            "<think>private without a close",
            "private drafting</think>Final answer.",
            "<think>private</think>   ",
            "<think>outer <think>nested</think>final",
        )
        for content in fixtures:
            with self.subTest(content=content):
                provider = FixtureProvider(content, fragments=(content,))
                session = ConversationSession(provider)
                visible: list[str] = []
                with self.assertRaises(ProviderResponseError):
                    for fragment in session.stream("Question"):
                        if fragment:
                            visible.append(fragment)
                self.assertEqual(visible, [])
                self.assertEqual(session.history, ())

    def test_cancellation_during_hidden_reasoning_closes_without_commit(self) -> None:
        provider = FixtureProvider(
            "",
            fragments=("<think>private first", "private later</think>Final"),
        )
        session = ConversationSession(provider)
        stream = session.stream("Question")
        self.assertEqual(next(stream), "")
        stream.close()
        self.assertEqual(provider.closed, 1)
        self.assertEqual(session.history, ())

    def test_cli_and_archive_receive_only_normalized_final_content(self) -> None:
        private = "private reasoning marker"
        provider = FixtureProvider(f"<think>{private}</think>Visible final.")
        with TemporaryDirectory() as temporary:
            service = ChatService(
                ConversationArchiveStore(Path(temporary) / "conversations.db")
            )
            answer = run_once(
                "Question",
                provider,
                chat_service=service,
                provider_name="fixture",
                model_name="fixture-model",
            )
            archived = service.get_chat(service.active_chat_id())
        self.assertEqual(answer, "Visible final.")
        self.assertEqual(archived.entries[-1].text, "Visible final.")
        self.assertNotIn(private, repr(archived))


if __name__ == "__main__":
    unittest.main()
