from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tori.app import run_once
from tori.knowledge import (
    KnowledgeError,
    KnowledgePassage,
    KnowledgeRetrieval,
    KnowledgeRegistry,
)
from tori.knowledge_retrieval import KnowledgeRetrievalPort
from tori.providers import ChatResponse, ModelProvider


class _FakeKnowledgeRetrieval:
    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure
        self.queries: list[str] = []

    def retrieve(self, query: str) -> KnowledgeRetrieval:
        self.queries.append(query)
        if self.failure:
            raise KnowledgeError("retrieval unavailable")
        return KnowledgeRetrieval(
            passages=(
                KnowledgePassage(
                    "fake-source",
                    "replaceable.md",
                    1,
                    1,
                    "The replaceable marker is indigo harbor.",
                ),
            ),
            warnings=("Fake retrieval warning.",),
            protected_passages_omitted=0,
        )


class _RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("Acknowledged.", "fake-model")


class KnowledgeRetrievalPortTests(unittest.TestCase):
    def test_fake_and_current_registry_conform_to_retrieval_contract(self) -> None:
        with TemporaryDirectory() as temporary:
            registry = KnowledgeRegistry(Path(temporary) / "knowledge")

            self.assertIsInstance(_FakeKnowledgeRetrieval(), KnowledgeRetrievalPort)
            self.assertIsInstance(registry, KnowledgeRetrievalPort)
            self.assertFalse(hasattr(KnowledgeRetrievalPort, "list_sources"))
            self.assertFalse(hasattr(KnowledgeRetrievalPort, "deregister"))

    def test_one_shot_substitutes_fake_retrieval_without_registry_knowledge(self) -> None:
        retrieval = _FakeKnowledgeRetrieval()
        provider = _RecordingProvider()
        warnings: list[str] = []
        passages: list[KnowledgePassage] = []

        answer = run_once(
            "What is the replaceable marker?",
            provider,
            knowledge_registry=retrieval,
            knowledge_warning_function=warnings.append,
            knowledge_result_function=passages.extend,
        )

        self.assertEqual(answer, "Acknowledged.")
        self.assertEqual(retrieval.queries, ["What is the replaceable marker?"])
        self.assertEqual(warnings, ["Fake retrieval warning."])
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].text, "The replaceable marker is indigo harbor.")
        self.assertIn("indigo harbor", provider.requests[0][2].content)

    def test_retrieval_failure_degrades_without_blocking_conversation(self) -> None:
        retrieval = _FakeKnowledgeRetrieval(failure=True)
        provider = _RecordingProvider()
        warnings: list[str] = []

        answer = run_once(
            "Continue without optional knowledge.",
            provider,
            knowledge_registry=retrieval,
            knowledge_warning_function=warnings.append,
        )

        self.assertEqual(answer, "Acknowledged.")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            warnings,
            [
                "Tori could not access the local knowledge registry; "
                "continuing without local knowledge."
            ],
        )

    def test_contract_has_no_presentation_provider_or_unrelated_domain_dependency(self) -> None:
        path = Path(__file__).parents[1] / "src" / "tori" / "knowledge_retrieval.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            node.module or alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        self.assertTrue(
            {
                "web",
                "http",
                "providers",
                "conversation_archive",
                "memory",
                "projects",
                "tasks",
                "scheduled_work",
                "sqlite3",
            }.isdisjoint(imported)
        )
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("KnowledgeRegistry", imported_names)

    def test_conversation_core_no_longer_imports_concrete_registry(self) -> None:
        path = Path(__file__).parents[1] / "src" / "tori" / "conversation.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }

        self.assertNotIn("KnowledgeRegistry", imported_names)
        self.assertIn("KnowledgeRetrievalPort", imported_names)


if __name__ == "__main__":
    unittest.main()
