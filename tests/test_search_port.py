from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tori.app import run_once
from tori.capabilities import CapabilityResult, SourceRecord
from tori.providers import ChatResponse, ModelProvider
from tori.search import DEFAULT_SEARCH_ENDPOINT, SearchError, SearXNGSearch
from tori.search_port import SearchPort


class _FakeSearch:
    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self.queries: list[str] = []

    @property
    def available(self) -> bool:
        return self._available

    def search(self, query: str, *, category: str = "general") -> CapabilityResult:
        self.queries.append(query)
        return CapabilityResult(
            "web_search",
            query,
            "completed",
            (
                SourceRecord(
                    "Replaceable source",
                    "https://example.test/replaceable",
                    "A normalized result supplied without SearXNG.",
                ),
            ),
        )


class _CitingProvider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("The result is supported [1].", "fake-model")


class SearchPortTests(unittest.TestCase):
    def test_fake_and_current_adapter_conform_to_tori_search_contract(self) -> None:
        fake = _FakeSearch()
        adapter = SearXNGSearch(
            enabled=True,
            endpoint=DEFAULT_SEARCH_ENDPOINT,
            result_limit=3,
            timeout_seconds=1.0,
        )

        self.assertIsInstance(fake, SearchPort)
        self.assertIsInstance(adapter, SearchPort)
        self.assertTrue(adapter.available)

    def test_one_shot_can_substitute_fake_without_searxng_knowledge(self) -> None:
        search = _FakeSearch()

        answer = run_once(
            "/search replaceable architecture",
            _CitingProvider(),
            web_search=search,
        )

        self.assertEqual(search.queries, ["replaceable architecture"])
        self.assertIn("The result is supported [1].", answer)
        self.assertIn("https://example.test/replaceable", answer)

    def test_unavailable_port_fails_without_execution(self) -> None:
        search = _FakeSearch(available=False)

        with self.assertRaisesRegex(SearchError, "not able to use web search"):
            run_once(
                "/search unavailable implementation",
                _CitingProvider(),
                web_search=search,
            )

        self.assertEqual(search.queries, [])

    def test_port_module_has_only_narrow_normalized_result_dependency(self) -> None:
        path = Path(__file__).parents[1] / "src" / "tori" / "search_port.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        forbidden = {
            "http",
            "web",
            "providers",
            "conversation_archive",
            "memory_extraction",
            "projects",
            "tasks",
            "scheduled_work",
            "command_execution",
            "tts",
        }
        self.assertTrue(forbidden.isdisjoint(imported))
        self.assertEqual(imported & {"capabilities"}, {"capabilities"})


if __name__ == "__main__":
    unittest.main()
