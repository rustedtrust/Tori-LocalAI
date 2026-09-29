from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tori.app import run_once
from tori.chats import ChatService, ChatServiceError
from tori.conversation_archive import (
    ArchiveEntry,
    ArchiveUnavailableError,
    ConversationArchiveStore,
    MemoryExtractionRequest,
)
from tori.intelligent_memory import IntelligentMemoryService, memory_plan_json
from tori.memory import AUTOMATIC_DIRECT, SQLiteMemoryStore
from tori.memory_extraction import (
    MemoryExtractionCoordinator,
    provider_definition_fingerprint,
)
from tests.test_web import MemoryExtractionProvider


CHAT_A = "chat-" + "a" * 32
CHAT_B = "chat-" + "b" * 32
EXTRACTION_A = "extract-" + "1" * 32
EXTRACTION_B = "extract-" + "2" * 32


def candidate(text: str, *, origin: str = "direct") -> dict[str, str]:
    return {
        "text": text,
        "category": "preference",
        "evidence": text,
        "origin": origin,
    }


class MemoryExtractionFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        identifiers = iter((CHAT_A, CHAT_B))
        self.archive = ConversationArchiveStore(
            self.root / "archive.db",
            clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
            identifier_factory=lambda: next(identifiers),
        )
        self.chats = ChatService(self.archive)
        self.memory = SQLiteMemoryStore(
            self.root / "memory.db",
            clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
        self.memory.initialize()

    def enqueue(
        self,
        provider: MemoryExtractionProvider,
        *,
        extraction_id: str = EXTRACTION_A,
        text: str = "I prefer tea.",
    ) -> str:
        fingerprint = provider_definition_fingerprint(provider, "fake", "fake-model")
        detail = self.chats.create_chat(
            (
                ArchiveEntry("user", text),
                ArchiveEntry("assistant", "A safe answer.", provider="fake", model="fake"),
            ),
            provider="fake",
            model="fake-model",
            memory_extraction=MemoryExtractionRequest(
                extraction_id, 0, 1, "fake", "fake-model", fingerprint
            ),
        )
        return detail.metadata.identifier

    def coordinator(
        self,
        provider: MemoryExtractionProvider | None,
        *,
        owner: str,
    ) -> MemoryExtractionCoordinator:
        return MemoryExtractionCoordinator(
            self.chats,
            self.memory,
            lambda provider_id, model_id: provider,
            process_incarnation=owner,
        )

    def test_transcript_and_outbox_insert_are_one_transaction(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        request = MemoryExtractionRequest(
            EXTRACTION_A, 0, 1, "fake", "fake-model",
            provider_definition_fingerprint(provider, "fake", "fake-model"),
        )
        with patch.object(
            ConversationArchiveStore,
            "_insert_memory_extraction",
            side_effect=ArchiveUnavailableError("synthetic enqueue failure"),
        ):
            with self.assertRaises(ChatServiceError):
                self.chats.create_chat(
                    (
                        ArchiveEntry("user", "I prefer tea."),
                        ArchiveEntry("assistant", "Answer", provider="fake", model="fake"),
                    ),
                    provider="fake",
                    model="fake-model",
                    memory_extraction=request,
                )
        self.assertEqual(self.chats.list_chats(), ())
        self.assertEqual(self.chats.list_memory_extractions(), ())

    def test_existing_chat_append_and_outbox_insert_are_one_transaction(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        detail = self.chats.create_chat(
            (
                ArchiveEntry("user", "Earlier question"),
                ArchiveEntry(
                    "assistant", "Earlier answer", provider="fake", model="fake"
                ),
            ),
            provider="fake",
            model="fake-model",
        )
        supplied = detail.entries + (
            ArchiveEntry("user", "I prefer tea."),
            ArchiveEntry("assistant", "Noted.", provider="fake", model="fake"),
        )
        request = MemoryExtractionRequest(
            EXTRACTION_A,
            2,
            3,
            "fake",
            "fake-model",
            provider_definition_fingerprint(provider, "fake", "fake-model"),
        )
        with patch.object(
            ConversationArchiveStore,
            "_insert_memory_extraction",
            side_effect=ArchiveUnavailableError("synthetic enqueue failure"),
        ):
            with self.assertRaises(ChatServiceError):
                self.chats.reconcile_chat(
                    detail.metadata.identifier,
                    supplied,
                    expected_revision=detail.metadata.revision,
                    provider="fake",
                    model="fake-model",
                    memory_extraction=request,
                )

        unchanged = self.chats.get_chat(detail.metadata.identifier)
        self.assertEqual(unchanged, detail)
        self.assertEqual(self.chats.list_memory_extractions(), ())

    def test_direct_candidate_is_applied_once_and_does_not_change_chat_revision(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        chat_id = self.enqueue(provider, text=text)
        before = self.chats.get_chat(chat_id).metadata.revision
        coordinator = self.coordinator(provider, owner="process-current")

        self.assertTrue(coordinator.process_one())

        records = self.memory.list_memories()
        self.assertEqual([record.text for record in records], [text])
        extraction = self.chats.get_memory_extraction(EXTRACTION_A)
        self.assertIsNotNone(extraction)
        self.assertEqual(extraction.state, "completed")  # type: ignore[union-attr]
        self.assertEqual(self.chats.get_chat(chat_id).metadata.revision, before)
        self.assertFalse(coordinator.process_one())

    def test_old_process_claim_is_recovered_but_current_claim_is_not_stolen(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        self.enqueue(provider)
        first = self.chats.claim_next_memory_extraction("process-old")
        self.assertIsNotNone(first)
        self.assertIsNone(self.chats.claim_next_memory_extraction("process-old"))
        recovered = self.chats.claim_next_memory_extraction("process-new")
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered.claim_owner, "process-new")  # type: ignore[union-attr]

    def test_effect_receipt_survives_user_deletion_and_prevents_recreation(self) -> None:
        effect = self.memory.apply_extraction_create(
            effect_id="effect-" + "3" * 32,
            extraction_id=EXTRACTION_A,
            candidate_index=0,
            action="automatic_create",
            text="I prefer tea.",
            category="preference",
            provenance=AUTOMATIC_DIRECT,
            source_chat_id=CHAT_A,
            source_user_sequence=0,
            extraction_provider="fake",
            extraction_model="fake-model",
            user_confirmed=False,
        )
        self.memory.delete(effect.result_memory_id)  # type: ignore[arg-type]
        repeated = self.memory.apply_extraction_create(
            effect_id=effect.effect_id,
            extraction_id=EXTRACTION_A,
            candidate_index=0,
            action="automatic_create",
            text="I prefer tea.",
            category="preference",
            provenance=AUTOMATIC_DIRECT,
            source_chat_id=CHAT_A,
            source_user_sequence=0,
            extraction_provider="fake",
            extraction_model="fake-model",
            user_confirmed=False,
        )
        self.assertEqual(repeated, effect)
        self.assertEqual(self.memory.list_memories(), ())

    def test_crash_after_memory_effect_before_terminalization_is_idempotent(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        self.enqueue(provider, text=text)
        claimed = self.chats.claim_next_memory_extraction("process-old")
        self.assertIsNotNone(claimed)
        service = IntelligentMemoryService(
            self.memory, provider, provider_name="fake", model_name="fake-model"
        )
        plan = service.evaluate_completed_turn(text, suppress_failures=False)
        planned = self.chats.transition_memory_extraction(
            EXTRACTION_A,
            expected_revision=claimed.revision,  # type: ignore[union-attr]
            process_incarnation="process-old",
            state="planned",
            plan_json=memory_plan_json(plan),
        )
        old = self.coordinator(provider, owner="process-old")
        with patch.object(
            self.chats,
            "transition_memory_extraction",
            side_effect=ChatServiceError("synthetic crash", code="unavailable"),
        ):
            with self.assertRaises(ChatServiceError):
                old._apply_plan(planned, plan)
        self.assertEqual(len(self.memory.list_memories()), 1)

        recovered = self.coordinator(provider, owner="process-new")
        self.assertTrue(recovered.process_one())
        self.assertEqual(len(self.memory.list_memories()), 1)
        self.assertEqual(
            self.chats.get_memory_extraction(EXTRACTION_A).state,  # type: ignore[union-attr]
            "completed",
        )

    def test_provider_result_without_plan_is_retried_after_process_restart(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        self.enqueue(provider, text=text)
        old = self.coordinator(provider, owner="process-old")
        original = self.chats.transition_memory_extraction

        def interrupt_plan(*args, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs.get("state") == "planned":
                raise ChatServiceError("synthetic process loss", code="unavailable")
            return original(*args, **kwargs)

        with patch.object(
            self.chats, "transition_memory_extraction", side_effect=interrupt_plan
        ):
            self.assertTrue(old.process_one())
        self.assertEqual(len(provider.extraction_requests), 1)
        self.assertEqual(self.memory.list_memories(), ())

        restarted = self.coordinator(provider, owner="process-new")
        self.assertTrue(restarted.process_one())
        self.assertEqual(len(provider.extraction_requests), 2)
        self.assertEqual(len(self.memory.list_memories()), 1)

    def test_persisted_plan_recovers_without_repeating_provider_call(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        self.enqueue(provider, text=text)
        claimed = self.chats.claim_next_memory_extraction("process-old")
        plan = IntelligentMemoryService(
            self.memory, provider, provider_name="fake", model_name="fake-model"
        ).evaluate_completed_turn(text, suppress_failures=False)
        self.chats.transition_memory_extraction(
            EXTRACTION_A,
            expected_revision=claimed.revision,  # type: ignore[union-attr]
            process_incarnation="process-old",
            state="planned",
            plan_json=memory_plan_json(plan),
        )
        self.assertEqual(len(provider.extraction_requests), 1)

        restarted = self.coordinator(provider, owner="process-new")
        self.assertTrue(restarted.process_one())
        self.assertEqual(len(provider.extraction_requests), 1)
        self.assertEqual(len(self.memory.list_memories()), 1)

    def test_durable_confirmation_is_chat_bound_one_use_and_restart_safe(self) -> None:
        evidence = "I usually prefer concise summaries."
        inferred = "The user prefers concise summaries."
        provider = MemoryExtractionProvider({
            "candidates": [{
                "text": inferred,
                "category": "preference",
                "evidence": evidence,
                "origin": "inferred",
            }]
        })
        chat_id = self.enqueue(provider, text=evidence)
        first_process = self.coordinator(provider, owner="process-old")
        self.assertTrue(first_process.process_one())
        proposal = first_process.attention_for_chat(chat_id)
        self.assertIsNotNone(proposal)
        self.assertIsNone(first_process.attention_for_chat(CHAT_B))

        restarted = self.coordinator(provider, owner="process-new")
        status = restarted.decide(
            proposal["extraction_id"],  # type: ignore[index]
            expected_revision=proposal["revision"],  # type: ignore[index]
            chat_id=chat_id,
            token=proposal["token"],  # type: ignore[index]
            decision="confirm",
        )
        self.assertEqual(status, "Remembered: " + inferred)
        with self.assertRaises(ChatServiceError):
            restarted.decide(
                proposal["extraction_id"],  # type: ignore[index]
                expected_revision=proposal["revision"],  # type: ignore[index]
                chat_id=chat_id,
                token=proposal["token"],  # type: ignore[index]
                decision="confirm",
            )
        self.assertEqual(len(self.memory.list_memories()), 1)

    def test_confirmed_effect_receipt_terminalizes_after_process_loss(self) -> None:
        evidence = "I usually prefer concise summaries."
        inferred = "The user prefers concise summaries."
        provider = MemoryExtractionProvider({
            "candidates": [{
                "text": inferred, "category": "preference",
                "evidence": evidence, "origin": "inferred",
            }]
        })
        chat_id = self.enqueue(provider, text=evidence)
        old = self.coordinator(provider, owner="process-old")
        self.assertTrue(old.process_one())
        proposal = old.attention_for_chat(chat_id)
        self.assertIsNotNone(proposal)

        with patch.object(
            self.chats,
            "transition_memory_extraction",
            side_effect=ChatServiceError("synthetic process loss", code="unavailable"),
        ):
            with self.assertRaises(ChatServiceError):
                old.decide(
                    proposal["extraction_id"],  # type: ignore[index]
                    expected_revision=proposal["revision"],  # type: ignore[index]
                    chat_id=chat_id,
                    token=proposal["token"],  # type: ignore[index]
                    decision="confirm",
                )
        self.assertEqual(len(self.memory.list_memories()), 1)

        restarted = self.coordinator(provider, owner="process-new")
        self.assertTrue(restarted.process_one())
        self.assertIsNone(restarted.attention_for_chat(chat_id))
        self.assertEqual(len(self.memory.list_memories()), 1)
        self.assertEqual(
            self.chats.get_memory_extraction(EXTRACTION_A).state,  # type: ignore[union-attr]
            "completed",
        )

    def test_claimed_confirmation_recovers_as_pending_after_restart(self) -> None:
        evidence = "I usually prefer concise summaries."
        provider = MemoryExtractionProvider({
            "candidates": [{
                "text": "The user prefers concise summaries.",
                "category": "preference", "evidence": evidence,
                "origin": "inferred",
            }]
        })
        chat_id = self.enqueue(provider, text=evidence)
        old = self.coordinator(provider, owner="process-old")
        self.assertTrue(old.process_one())
        proposal = old.attention_for_chat(chat_id)
        self.chats.claim_memory_confirmation(
            EXTRACTION_A,
            expected_revision=proposal["revision"],  # type: ignore[index]
            process_incarnation="process-old",
        )

        restarted = self.coordinator(provider, owner="process-new")
        self.assertTrue(restarted.process_one())
        self.assertIsNotNone(restarted.attention_for_chat(chat_id))
        self.assertEqual(self.memory.list_memories(), ())

    def test_changed_or_missing_provider_fails_without_fallback(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        self.enqueue(provider)
        missing = self.coordinator(None, owner="process-current")
        self.assertTrue(missing.process_one())
        record = self.chats.get_memory_extraction(EXTRACTION_A)
        self.assertEqual(record.state, "failed")  # type: ignore[union-attr]
        self.assertEqual(record.safe_error_code, "provider_unavailable")  # type: ignore[union-attr]

    def test_changed_provider_definition_fails_without_call_or_fallback(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        provider._endpoint = "http://127.0.0.1:11434/v1"  # type: ignore[attr-defined]
        self.enqueue(provider)
        provider._endpoint = "http://192.168.1.2:11434/v1"  # type: ignore[attr-defined]
        coordinator = self.coordinator(provider, owner="process-current")

        self.assertTrue(coordinator.process_one())
        record = self.chats.get_memory_extraction(EXTRACTION_A)
        self.assertEqual(record.state, "failed")  # type: ignore[union-attr]
        self.assertEqual(record.safe_error_code, "provider_definition_changed")  # type: ignore[union-attr]
        self.assertEqual(provider.extraction_requests, [])

    def test_fifo_claim_order(self) -> None:
        provider = MemoryExtractionProvider({"candidates": []})
        self.enqueue(provider, extraction_id=EXTRACTION_A)
        self.chats.new_session()
        self.enqueue(provider, extraction_id=EXTRACTION_B, text="I prefer coffee.")
        first = self.chats.claim_next_memory_extraction("process-current")
        self.assertEqual(first.extraction_id, EXTRACTION_A)  # type: ignore[union-attr]

    def test_chat_deletion_discards_a_returning_provider_result(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        chat_id = self.enqueue(provider, text=text)
        coordinator = self.coordinator(provider, owner="process-current")
        started = threading.Event()
        release = threading.Event()
        original = provider.extract_memory_candidates

        def blocked(*args, **kwargs):  # type: ignore[no-untyped-def]
            started.set()
            release.wait(timeout=3)
            return original(*args, **kwargs)

        provider.extract_memory_candidates = blocked  # type: ignore[method-assign]
        worker = threading.Thread(target=coordinator.process_one)
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        detail = self.chats.get_chat(chat_id)
        with coordinator.source_mutation_guard():
            self.chats.delete_chat(chat_id, expected_revision=detail.metadata.revision)
        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.memory.list_memories(), ())
        self.assertIsNone(self.chats.get_memory_extraction(EXTRACTION_A))

    def test_one_shot_returns_with_pending_work_recovered_next_startup(self) -> None:
        text = "I prefer tea."
        provider = MemoryExtractionProvider({"candidates": [candidate(text)]})
        answer = run_once(
            text,
            provider,
            memory_store=self.memory,
            chat_service=self.chats,
            provider_name="fake",
            model_name="fake-model",
        )

        self.assertEqual(answer, "A local test answer.")
        self.assertEqual(provider.extraction_requests, [])
        self.assertEqual(
            self.chats.list_memory_extractions()[0].state,
            "pending",
        )
        restarted = self.coordinator(provider, owner="process-next-startup")
        self.assertTrue(restarted.process_one())
        self.assertEqual([item.text for item in self.memory.list_memories()], [text])


if __name__ == "__main__":
    unittest.main()
