from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tori.intelligent_memory import IntelligentMemoryService, _extraction_contract
from tori.memory import (
    CONFIRMED_INFERRED,
    CONFIRMED_UPDATE,
    LEGACY_EXPLICIT_USER_COMMAND,
    MemoryConflictError,
    MemoryError,
    MemoryUnavailableError,
    SQLiteMemoryStore,
)
from tori.providers import ChatResponse, ModelProvider, ProviderResponseError


class ExtractionProvider(ModelProvider):
    def __init__(self, document: object, relationship: object | None = None) -> None:
        self.document = document
        self.relationship = relationship
        self.extraction_calls = 0
        self.relationship_calls = 0
        self.relationship_requests: list[tuple[object, ...]] = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("visible", "test-model")

    def extract_memory_candidates(self, messages, *, model):  # type: ignore[no-untyped-def]
        self.extraction_calls += 1
        if isinstance(self.document, Exception):
            raise self.document
        return ChatResponse(json.dumps(self.document), model)

    def assess_memory_relationship(self, messages, *, model):  # type: ignore[no-untyped-def]
        self.relationship_calls += 1
        self.relationship_requests.append(tuple(messages))
        if self.relationship is None:
            raise ProviderResponseError("unavailable")
        return ChatResponse(json.dumps(self.relationship), model)


class RawExtractionProvider(ExtractionProvider):
    def extract_memory_candidates(self, messages, *, model):  # type: ignore[no-untyped-def]
        return ChatResponse(str(self.document), model)


def candidate(text: str, evidence: str, *, category: str = "preference", origin: str = "direct") -> dict[str, object]:
    return {"text": text, "category": category, "evidence": evidence, "origin": origin}


class IntelligentMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "memory" / "tori.db"

    def service(self, document: object) -> tuple[SQLiteMemoryStore, IntelligentMemoryService]:
        store = SQLiteMemoryStore(self.path)
        provider = ExtractionProvider(document)
        return store, IntelligentMemoryService(
            store, provider, provider_name="test", model_name="test-model"
        )

    def test_direct_durable_candidate_is_saved_with_provenance(self) -> None:
        text = "I prefer afternoon appointments."
        store, service = self.service({"candidates": [candidate(text, text)]})
        result = service.process_completed_turn(text, chat_id="chat-source", user_sequence=4)
        self.assertEqual([item.text for item in result.remembered], [text])
        record = store.list_memories()[0]
        self.assertEqual(record.category, "preference")
        self.assertEqual(record.source_chat_id, "chat-source")
        self.assertFalse(record.user_confirmed)

    def test_live_acceptance_preference_uses_exact_grounded_user_evidence(self) -> None:
        user_text = (
            "For my local AI projects, I prefer native Linux installations under "
            "/example_ai_projects instead of Docker whenever practical."
        )
        evidence = (
            "I prefer native Linux installations under /example_ai_projects instead of "
            "Docker whenever practical."
        )
        model_paraphrase = (
            "Prefers native Linux installations in /example_ai_projects over Docker for "
            "local AI projects."
        )
        store, service = self.service(
            {"candidates": [candidate(model_paraphrase, evidence)]}
        )

        result = service.process_completed_turn(
            user_text, chat_id="chat-source", user_sequence=4
        )

        self.assertEqual(len(result.remembered), 1)
        self.assertEqual(result.remembered[0].text, evidence)
        self.assertEqual(result.remembered[0].category, "preference")
        self.assertEqual([record.text for record in store.list_memories()], [evidence])

    def test_direct_preference_requires_grounded_preference_wording(self) -> None:
        user_text = "Native Linux installations are available under /workspaces."
        store, service = self.service(
            {"candidates": [candidate("Prefers native Linux.", user_text)]}
        )

        result = service.process_completed_turn(
            user_text, chat_id="chat-source", user_sequence=4
        )

        self.assertFalse(result.remembered)
        self.assertEqual(store.list_memories(), ())

    def test_inferred_candidate_requires_one_use_confirmation(self) -> None:
        text = "I often work with blue themes."
        store, service = self.service({"candidates": [candidate("The user prefers blue themes.", text, origin="inferred")]})
        result = service.process_completed_turn(text, chat_id="chat-source", user_sequence=2)
        self.assertFalse(result.remembered)
        proposal = result.proposals[0]
        saved = service.confirm(proposal.token, chat_id="chat-source")
        self.assertIsNotNone(saved)
        self.assertIsNone(service.confirm(proposal.token, chat_id="chat-source"))
        self.assertEqual(len(store.list_memories()), 1)

    def test_live_inferred_pattern_proposes_and_preserves_independent_memory(self) -> None:
        user_text = (
            "For the last few years, whenever I have the choice between a local "
            "AI tool and a cloud AI tool, I've consistently chosen the local option."
        )
        inferred_text = "I prefer local AI tools over cloud AI tools."
        store = SQLiteMemoryStore(self.path)
        existing = store.create(
            "I prefer native Linux installations under /example_ai_projects instead of "
            "Docker whenever practical."
        )
        provider = ExtractionProvider({
            "candidates": [candidate(
                inferred_text, user_text, category="preference", origin="inferred"
            )]
        })
        service = IntelligentMemoryService(
            store, provider, provider_name="test", model_name="test-model"
        )

        result = service.process_completed_turn(
            user_text, chat_id="chat-source", user_sequence=4
        )

        self.assertFalse(result.remembered)
        self.assertEqual(len(result.proposals), 1)
        proposal = result.proposals[0]
        self.assertEqual(proposal.action, "create")
        self.assertEqual(proposal.candidate.category, "preference")
        self.assertEqual(proposal.candidate.origin, "inferred")
        self.assertEqual(proposal.candidate.evidence, user_text)
        self.assertEqual(len(store.list_memories()), 1)
        self.assertTrue(service.dismiss(proposal.token, chat_id="chat-source"))
        self.assertEqual(store.get(existing.identifier).text, existing.text)

        proposal = service.process_completed_turn(
            user_text, chat_id="chat-source", user_sequence=6
        ).proposals[0]
        confirmed = service.confirm(proposal.token, chat_id="chat-source")

        self.assertIsNotNone(confirmed)
        self.assertEqual(confirmed.provenance, CONFIRMED_INFERRED)  # type: ignore[union-attr]
        self.assertEqual(confirmed.text, inferred_text)  # type: ignore[union-attr]
        self.assertEqual(len(store.list_memories()), 2)
        self.assertEqual(store.get(existing.identifier).text, existing.text)

    def test_inferred_candidate_requires_strong_durable_pattern_evidence(self) -> None:
        weak = "I used a local AI tool once."
        store, service = self.service({
            "candidates": [candidate(
                "I prefer local AI tools.", weak, origin="inferred"
            )]
        })

        result = service.process_completed_turn(
            weak, chat_id="chat-source", user_sequence=4
        )

        self.assertFalse(result.remembered)
        self.assertFalse(result.proposals)
        self.assertEqual(store.list_memories(), ())

    def test_extraction_contract_separates_repeated_inference_from_direct_preference(
        self,
    ) -> None:
        contract = " ".join(_extraction_contract().casefold().split())
        self.assertIn("origin rule", contract)
        self.assertIn("direct means evidence literally says the same memory", contract)
        self.assertIn("long-standing pattern must use inferred", contract)
        self.assertIn("consistent choices should produce an inferred candidate", contract)
        self.assertIn("a one-off action should produce none", contract)

    def test_evidence_and_strict_shape_fail_closed(self) -> None:
        for document in (
            {"candidates": [candidate("Unsupported", "not present")]},
            {"candidates": [{**candidate("x", "hello"), "operation": "delete"}]},
            {"candidates": [candidate("x", "hello", category="secret")]},
            {"candidates": [], "sql": "DROP TABLE memories"},
        ):
            with self.subTest(document=document):
                store, service = self.service(document)
                result = service.process_completed_turn("hello", chat_id="chat", user_sequence=0)
                self.assertEqual(result, type(result)())
                self.assertEqual(store.list_memories(), ())

    def test_scheduler_temporary_and_sensitive_candidates_are_rejected(self) -> None:
        examples = (
            "Remind me tomorrow at 2 PM to call the dentist.",
            "My appointment is tomorrow at 2 PM.",
            "I am tired right now.",
            "My password is synthetic-value-1234567890.",
        )
        for text in examples:
            with self.subTest(text=text):
                store, service = self.service({"candidates": [candidate(text, text)]})
                self.assertFalse(service.process_completed_turn(text, chat_id="chat", user_sequence=0).remembered)
                self.assertEqual(store.list_memories(), ())

    def test_duplicate_normalization_suppresses_second_row(self) -> None:
        store, service = self.service({"candidates": [candidate("I prefer tea.", "I prefer tea.")]})
        service.process_completed_turn("I prefer tea.", chat_id="chat", user_sequence=0)
        provider = ExtractionProvider({"candidates": [candidate("  i   PREFER tea. ", "  i   PREFER tea. ")]})
        second = IntelligentMemoryService(store, provider, provider_name="test", model_name="test-model")
        second.process_completed_turn("  i   PREFER tea. ", chat_id="chat", user_sequence=2)
        self.assertEqual(len(store.list_memories()), 1)
        with self.assertRaises(MemoryConflictError):
            store.create("I   PREFER TEA.")

    def test_provider_failure_is_nonfatal_and_writes_nothing(self) -> None:
        store, service = self.service(ProviderResponseError("unavailable"))
        result = service.process_completed_turn("hello", chat_id="chat", user_sequence=0)
        self.assertFalse(result.remembered)
        self.assertFalse(result.proposals)
        self.assertEqual(store.list_memories(), ())

    def test_malformed_oversized_and_too_many_candidates_are_noop(self) -> None:
        store = SQLiteMemoryStore(self.path)
        for response in (
            "not-json",
            "```json\n{\"candidates\": []}\n```",
            "x" * 8_001,
            json.dumps({"candidates": [candidate("hello", "hello")] * 4}),
        ):
            service = IntelligentMemoryService(
                store, RawExtractionProvider(response),
                provider_name="test", model_name="test-model",
            )
            result = service.process_completed_turn("hello", chat_id="chat", user_sequence=0)
            self.assertFalse(result.remembered)
        self.assertEqual(store.list_memories(), ())

    def test_all_approved_durable_categories_can_pass_identical_policy(self) -> None:
        examples = {
            "general": "I use metric measurements.",
            "preference": "I prefer concise summaries.",
            "project": "My ongoing project is named Tori.",
            "goal": "My durable goal is to learn Spanish.",
            "routine": "I review my weekly plan each Sunday.",
            "constraint": "I must keep this project offline.",
        }
        for index, (category, text) in enumerate(examples.items()):
            with self.subTest(category=category):
                path = Path(self.temporary.name) / f"memory-{index}.db"
                store = SQLiteMemoryStore(path)
                service = IntelligentMemoryService(
                    store,
                    ExtractionProvider({"candidates": [candidate(text, text, category=category)]}),
                    provider_name="test", model_name="test-model",
                )
                result = service.process_completed_turn(text, chat_id="chat", user_sequence=index)
                self.assertEqual(result.remembered[0].category, category)

    def test_proposal_is_source_bound_expires_and_stale_update_is_safe(self) -> None:
        now = [10.0]
        existing = SQLiteMemoryStore(self.path)
        old = existing.create("I prefer tea.")
        provider = ExtractionProvider({"candidates": [candidate(
            "I prefer coffee.", "I prefer coffee.", origin="inferred"
        )]}, {"relationship": "contradiction", "target": "related-0"})
        service = IntelligentMemoryService(
            existing, provider, provider_name="test", model_name="test-model",
            clock=lambda: now[0],
        )
        proposal = service.process_completed_turn(
            "I prefer coffee.", chat_id="chat", user_sequence=2
        ).proposals[0]
        self.assertIsNone(service.confirm(proposal.token, chat_id="other-chat"))
        self.assertEqual(existing.get(old.identifier).text, "I prefer tea.")

        proposal = service.process_completed_turn(
            "I prefer coffee.", chat_id="chat", user_sequence=2
        ).proposals[0]
        now[0] = 400.0
        self.assertIsNone(service.confirm(proposal.token, chat_id="chat"))
        self.assertEqual(existing.get(old.identifier).text, "I prefer tea.")

        now[0] = 10.0
        proposal = service.process_completed_turn(
            "I prefer coffee.", chat_id="chat", user_sequence=2
        ).proposals[0]
        existing.update(old.identifier, "I prefer green tea.")
        with self.assertRaises(MemoryError):
            service.confirm(proposal.token, chat_id="chat")
        self.assertEqual(existing.get(old.identifier).text, "I prefer green tea.")

    def test_relationship_classes_are_bounded_and_invalid_targets_cannot_mutate(self) -> None:
        cases = (
            ("independent", None, "created"),
            ("duplicate", "related-0", "suppressed"),
            ("update", "related-0", "update"),
            ("contradiction", "related-0", "update"),
            ("uncertain", None, "create-proposal"),
            ("uncertain", "related-0", "create-proposal"),
            ("update", "related-999", "create-proposal"),
        )
        for index, (relationship, target, expected) in enumerate(cases):
            with self.subTest(relationship=relationship, target=target):
                path = Path(self.temporary.name) / f"relationship-{index}.db"
                store = SQLiteMemoryStore(path)
                store.create("I prefer hot tea every morning.")
                text = "I prefer hot coffee every morning."
                provider = ExtractionProvider(
                    {"candidates": [candidate(text, text)]},
                    {"relationship": relationship, "target": target},
                )
                result = IntelligentMemoryService(
                    store, provider, provider_name="test", model_name="test-model"
                ).process_completed_turn(text, chat_id="chat", user_sequence=2)
                if expected == "created":
                    self.assertEqual(len(result.remembered), 1)
                    self.assertFalse(result.proposals)
                elif expected == "suppressed":
                    self.assertFalse(result.remembered)
                    self.assertFalse(result.proposals)
                else:
                    self.assertFalse(result.remembered)
                    self.assertEqual(len(result.proposals), 1)
                    self.assertEqual(
                        result.proposals[0].action,
                        "update" if expected == "update" else "create",
                    )
                self.assertEqual(store.get("mem-" + "0" * 32), None)

    def test_live_inferred_preference_is_independent_of_deployment_preference(self) -> None:
        original_text = (
            "I prefer native Linux installations under /example_ai_projects instead of "
            "Docker whenever practical."
        )
        user_text = (
            "For the last few years, whenever I have the choice between a local "
            "AI tool and a cloud AI tool, I've consistently chosen the local option."
        )
        inferred_text = "I prefer local AI tools."
        store = SQLiteMemoryStore(self.path)
        original = store.create(original_text)
        provider = ExtractionProvider(
            {"candidates": [candidate(inferred_text, user_text, origin="inferred")]},
            {"relationship": "independent", "target": None},
        )
        service = IntelligentMemoryService(
            store, provider, provider_name="test", model_name="test-model"
        )

        result = service.process_completed_turn(
            user_text, chat_id="chat-independent", user_sequence=2
        )

        self.assertEqual(provider.relationship_calls, 1)
        relationship_instruction = provider.relationship_requests[0][0].content
        self.assertIn("same underlying", relationship_instruction)
        self.assertIn("topical overlap alone", relationship_instruction)
        self.assertIn("target must be null for independent", relationship_instruction)
        self.assertFalse(result.remembered)
        self.assertEqual(len(result.proposals), 1)
        proposal = result.proposals[0]
        self.assertEqual(proposal.action, "create")
        self.assertIsNone(proposal.target_identifier)
        self.assertEqual(len(store.list_memories()), 1)
        confirmed = service.confirm(proposal.token, chat_id="chat-independent")
        self.assertIsNotNone(confirmed)
        self.assertEqual(len(store.list_memories()), 2)
        self.assertEqual(store.get(original.identifier), original)
        self.assertEqual(confirmed.provenance, CONFIRMED_INFERRED)

    def test_genuine_same_dimension_correction_remains_revision_bound_update(self) -> None:
        original_text = (
            "I prefer native Linux installations under /example_ai_projects instead of "
            "Docker whenever practical."
        )
        correction = "I prefer Docker instead of native Linux."
        store = SQLiteMemoryStore(self.path)
        original = store.create(original_text)
        provider = ExtractionProvider(
            {"candidates": [candidate(correction, correction)]},
            {"relationship": "contradiction", "target": "related-0"},
        )
        service = IntelligentMemoryService(
            store, provider, provider_name="test", model_name="test-model"
        )

        result = service.process_completed_turn(
            correction, chat_id="chat-correction", user_sequence=2
        )

        proposal = result.proposals[0]
        self.assertEqual(proposal.action, "update")
        self.assertEqual(proposal.target_identifier, original.identifier)
        self.assertEqual(store.get(original.identifier), original)
        updated = service.confirm(proposal.token, chat_id="chat-correction")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.identifier, original.identifier)
        self.assertEqual(updated.text, correction)
        self.assertEqual(updated.provenance, CONFIRMED_UPDATE)
        self.assertEqual(len(store.list_memories()), 1)

    def test_semantic_relationship_examples_do_not_confuse_topic_with_dimension(self) -> None:
        cases = (
            (
                "different project constraints",
                "Keep my AI projects under /workspaces.",
                "I prefer dark-mode interfaces for AI tools.",
                "independent",
                None,
                "additive",
            ),
            (
                "trivial duplicate",
                "I prefer native Linux over Docker.",
                "I prefer native Linux instead of Docker.",
                "duplicate",
                "related-0",
                "suppressed",
            ),
            (
                "additive preference",
                "I prefer local AI tools.",
                "I prefer open-source AI tools.",
                "independent",
                None,
                "additive",
            ),
            (
                "ambiguous overlap",
                "I prefer concise status updates for projects.",
                "I prefer concise project summaries.",
                "uncertain",
                None,
                "proposal",
            ),
        )
        for index, (label, old_text, new_text, relationship, target, expected) in enumerate(cases):
            with self.subTest(label=label):
                store = SQLiteMemoryStore(
                    Path(self.temporary.name) / f"semantic-{index}.db"
                )
                original = store.create(old_text)
                provider = ExtractionProvider(
                    {"candidates": [candidate(new_text, new_text)]},
                    {"relationship": relationship, "target": target},
                )
                result = IntelligentMemoryService(
                    store, provider, provider_name="test", model_name="test-model"
                ).process_completed_turn(new_text, chat_id="chat", user_sequence=2)

                self.assertEqual(store.get(original.identifier), original)
                if expected == "suppressed":
                    self.assertFalse(result.remembered)
                    self.assertFalse(result.proposals)
                elif expected == "proposal":
                    self.assertFalse(result.remembered)
                    self.assertEqual(result.proposals[0].action, "create")
                    self.assertIsNone(result.proposals[0].target_identifier)
                else:
                    self.assertTrue(result.remembered)
                    self.assertFalse(result.proposals)


class MemoryStorageEvolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_new_store_is_schema_two_private_and_symlink_is_rejected(self) -> None:
        path = self.root / "private" / "memory.db"
        store = SQLiteMemoryStore(path)
        store.initialize()
        self.assertEqual(store.schema_version(), 3)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        link = self.root / "link.db"
        link.symlink_to(path)
        with self.assertRaises(MemoryUnavailableError):
            SQLiteMemoryStore(link).initialize()

    def test_symlink_ancestor_is_rejected(self) -> None:
        real = self.root / "real"
        real.mkdir()
        link = self.root / "linked"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(MemoryUnavailableError):
            SQLiteMemoryStore(link / "memory.db").initialize()

    def test_explicit_schema_one_migration_preserves_exact_records(self) -> None:
        path = self.root / "legacy.db"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE memory_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE memories (
                identifier TEXT PRIMARY KEY, text TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category = 'general'),
                sensitivity TEXT NOT NULL CHECK (sensitivity = 'ordinary'),
                provenance TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO memory_metadata VALUES ('schema_version', '1');
            INSERT INTO memories VALUES (
                'mem-00000000000000000000000000000001', 'Exact legacy text',
                'general', 'ordinary', 'explicit_user_command',
                '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z'
            );
        """)
        connection.close()
        store = SQLiteMemoryStore(path)
        self.assertEqual(store.schema_version(), 1)
        self.assertEqual(store.migrate_v1_to_v2(), (1, 1))
        record = store.list_memories()[0]
        self.assertEqual(record.text, "Exact legacy text")
        self.assertEqual(record.provenance, LEGACY_EXPLICIT_USER_COMMAND)
        self.assertEqual(record.created_at, "2026-01-01T00:00:00Z")
        self.assertEqual(record.updated_at, "2026-01-02T00:00:00Z")

    def test_migration_validation_failure_rolls_back_to_exact_legacy_schema(self) -> None:
        path = self.root / "rollback.db"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE memory_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE memories (
                identifier TEXT PRIMARY KEY, text TEXT NOT NULL,
                category TEXT NOT NULL CHECK (category = 'general'),
                sensitivity TEXT NOT NULL CHECK (sensitivity = 'ordinary'),
                provenance TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            INSERT INTO memory_metadata VALUES ('schema_version', '1');
        """)
        connection.close()
        store = SQLiteMemoryStore(path)
        original = SQLiteMemoryStore._validate_schema

        def fail_new_schema(database):  # type: ignore[no-untyped-def]
            original(database)
            version = database.execute(
                "SELECT value FROM memory_metadata WHERE key='schema_version'"
            ).fetchone()[0]
            if version == "2":
                raise MemoryError("synthetic post-migration validation failure")

        with patch.object(SQLiteMemoryStore, "_validate_schema", side_effect=fail_new_schema):
            with self.assertRaises(MemoryError):
                store.migrate_v1_to_v2()
        self.assertEqual(SQLiteMemoryStore(path).schema_version(), 1)


if __name__ == "__main__":
    unittest.main()
