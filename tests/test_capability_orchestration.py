"""Full conversation routes with isolated stores and deterministic adapters."""

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tori.capabilities import CapabilityResult, SourceRecord
from tori.capability_registry import (
    CAPABILITIES, CapabilityRegistry, CapabilityState, CapabilityUnderstanding, ambiguous_memory_request,
    capability_question, explicit_memory_text, is_capability_discussion, MessageIntent,
)
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.coding_work import SQLiteCodingWorkStore
from tori.coding_work_application import CodingWorkApplicationService
from tori.coding_worker import FakeCodingWorkerAdapter
from tori.conversation_archive import ConversationArchiveStore
from tori.context import ContextPolicy, context_input_limit, estimate_messages_tokens
from tori.finance_conversation import FinanceConversationService
from tori.finance_service import FinanceService
from tori.identity import runtime_identity_message
from tori.interaction import interaction_guidance_message
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.night_owl import NightOwlSettings, SQLiteNightOwlStore
from tori.planning_application import PlanningService
from tori.project_application import ProjectApplicationService
from tori.providers import ChatMessage, ChatResponse, ModelProvider, ProviderConnectionError
from tori.response_normalization import EXTERNAL_KNOWLEDGE_ADVISORY
from tori.scheduled_work import SQLiteScheduledWorkStore
from tori.system_capabilities import MemoryStatus, SystemCapabilities, SystemConversationService
from tori.tasks import SQLiteOperationalStore
from tori.time_context import capture_time_context
from tori.user_settings import CapabilitySettingsController
from tori.web import WebApplication
from finance_fixtures import FakeFinanceRepository, synthetic_snapshot
from tests.test_coding_work_conversation import RuntimeFacade
from tests.test_planning_conversation import FakePlanningPort


def assert_projected_state(test: unittest.TestCase, text: str, name: str, state: str) -> None:
    """Accept the per-capability hint or compact state group, never an absent ability."""
    test.assertTrue(
        f"{name}: {state}" in text or bool(re.search(
            rf"(?m)^{state.title()}: [^\n]*\b{re.escape(name)}(?=,|\.)", text
        )),
        f"Expected {name} to be projected as {state}.",
    )


class Provider(ModelProvider):
    def __init__(self):
        self.requests = []
        self.intent_requests = []
        self.answer = "Let's talk it through."
        self.intent = {"kind": "discussion", "capability": "finance"}
        self.fail = False

    def chat(self, messages):
        self.requests.append(tuple(messages))
        if self.fail:
            raise ProviderConnectionError("synthetic failure")
        return ChatResponse(self.answer, "model")

    def stream_chat(self, messages):
        yield self.chat(messages).content

    def interpret_capability_intent(self, messages, *, model):
        self.intent_requests.append(tuple(messages))
        return ChatResponse(json.dumps(self.intent), model)


class Search:
    available = True

    def __init__(self):
        self.queries = []
        self.sources = (SourceRecord("Synthetic source", "https://example.com/source", "Synthetic evidence"),)

    def search(self, query, *, category="general"):
        self.queries.append(query)
        return CapabilityResult("web_search", query, "completed", self.sources)


class CapabilityConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.root = Path(self.temp.name)
        self.now = datetime(2026, 8, 14, 14, tzinfo=timezone.utc)
        self.provider = Provider()
        self.memory = SQLiteMemoryStore(root / "memory.db")
        self.chats = ChatService(ConversationArchiveStore(root / "archive.db", clock=lambda: self.now))
        self.tasks = SQLiteOperationalStore(root / "tasks.db", clock=lambda: self.now)
        self.tasks.initialize()
        scheduled = SQLiteScheduledWorkStore(root / "scheduled.db", clock=lambda: self.now)
        scheduled.initialize()
        self.planning = FakePlanningPort()
        self.finance = FakeFinanceRepository(synthetic_snapshot(), root / "finance.xlsx")
        self.work_store = SQLiteCodingWorkStore(root / "coding.db")
        self.work = RuntimeFacade(CodingWorkApplicationService(self.work_store, FakeCodingWorkerAdapter()))
        self.search = Search()
        self.preferences = CapabilitySettingsController(administrator_web_search=True, administrator_speech_output=False, store=None)
        self.app = WebApplication(
            self.provider, port=8765, checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=self.memory, knowledge_registry=KnowledgeRegistry(root / "knowledge", working_directory=root),
            provider_name="fake", model_name="model", chat_service=self.chats,
            project_application=ProjectApplicationService(self.chats),
            operational_store=self.tasks, scheduled_work_store=scheduled,
            coding_work_runtime=self.work, planning_service=PlanningService(self.planning),
            planning_default_task_list="calendar", planning_default_calendar="calendar",
            finance_conversation=FinanceConversationService(FinanceService(self.finance), today=lambda: date(2026, 8, 14)),
            web_search=self.search, capability_settings=self.preferences,
            system_service=SystemConversationService(SystemCapabilities(memory_status_function=lambda: MemoryStatus(16 * 1024**3, 6 * 1024**3, 10 * 1024**3, 37.5))),
            timezone_name="America/Chicago", utc_clock=lambda: self.now,
        )

    def turn(self, text, stream=False):
        if stream:
            events = list(self.app.stream_submit(text))
            self.assertIn(events[-1]["type"], {"complete", "error"})
            return events[-1]
        return self.app.submit(text)[1]

    def test_casual_and_reminder_discussion_never_mutate(self):
        for text in ("Too much to do then wait and unpredictable lol", "What do you need to create a reminder?", "Reminders aren't working.", "Anyway, that was a long day lol"):
            response = self.turn(text, stream=True)
            self.assertEqual(response["transcript"][-1]["text"], self.provider.answer)
        self.assertEqual(len(self.provider.requests), 4)
        self.assertEqual(self.tasks.list_reminders(), ())
        self.assertEqual(self.planning.tasks, {})
        self.assertEqual(self.work.calls, [])
        awareness = "\n".join(m.content for m in self.provider.requests[-1] if m.role == "system")
        for name in ("Memory", "Finance", "CalDAV", "OpenCode", "Supervised Terminal", "SearXNG"):
            self.assertIn(name, awareness)

    def test_reminder_creation_proposes_then_confirms_real_backend(self):
        response = self.turn("Remind me today at 7 PM to look into a fishing trip.", stream=True)
        self.assertEqual(response["confirmation"]["action"], "planning.authorize")
        self.assertEqual(self.planning.tasks, {})
        status, _ = self.app.confirm(response["confirmation"]["token"], "confirm")
        self.assertEqual(status, 201)
        self.assertEqual(len(self.planning.tasks), 1)
        self.assertEqual(self.provider.requests, [])

    def test_reminder_missing_details_clarifies_without_mutation(self):
        self.provider.intent = {"kind": "action", "capability": "tasks"}
        response = self.turn("Create a reminder.")
        self.assertNotIn("confirmation", response)
        self.assertIn("description", response["transcript"][-1]["text"])
        self.assertIn("date/time", response["transcript"][-1]["text"])
        self.assertEqual(self.tasks.list_reminders(), ())
        self.assertEqual(self.planning.tasks, {})

    def test_reminder_without_caldav_uses_actual_local_store(self):
        self.app._planning = None
        response = self.turn("Remind me today at 7 PM to look into a fishing trip.")
        self.assertIn("I’ll remind you", response["transcript"][-1]["text"])
        reminders = self.tasks.list_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].reminder_text, "look into a fishing trip")
        self.assertEqual(reminders[0].scheduled_start_utc, "2026-08-15T00:00:00Z")
        self.assertEqual(self.planning.tasks, {})

    def test_ram_paraphrases_share_real_host_read(self):
        for text in ("How much RAM is available?", "How much memory is available?",
                     "How much RAM is free?", "How much RAM is in use?",
                     "Can you tell me how much system RAM is in use?"):
            response = self.turn(text, stream=True)
            self.assertIn("6.0 GB", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])

    def test_explicit_local_reminder_orders_in_both_web_paths(self):
        self.app._planning = None
        self.provider.intent = {"kind": "action", "capability": "tasks"}
        for stream, text in enumerate((
            "Set a reminder to do the dishes at 2:00 PM today.",
            "Set a reminder to do the dishes today at 2:00 PM.",
            "Remind me to do the dishes at 2:00 PM today.",
            "Remind me today at 2:00 PM to do the dishes.",
        )):
            response = self.turn(text, stream=bool(stream % 2))
            self.assertIn("I’ll remind you", response["transcript"][-1]["text"])
        self.assertEqual(len(self.tasks.list_reminders()), 4)
        self.assertEqual(self.provider.requests, [])

    def test_explicit_memory_uses_policy_not_model(self):
        response = self.turn("Create a memory that I like root beer.", stream=True)
        self.assertIn("Saved memory", response["transcript"][-1]["text"])
        self.assertEqual(self.memory.list_memories()[0].text, "I like root beer.")
        self.turn("Create a memory that my password is synthetic-secret.")
        self.assertEqual(len(self.memory.list_memories()), 1)
        self.assertEqual(self.provider.requests, [])

    def test_natural_durable_preferences_receive_authoritative_memory_receipts(self):
        cases = (
            ("Remember that I prefer Fahrenheit for weather.",
             "I prefer Fahrenheit for weather."),
            ("Please remember I like root beer.", "I like root beer."),
            ("Can you remember that I use Firefox?", "I use Firefox"),
            ("Can you remember to give me weather in Fahrenheit rather than Celsius?",
             "I prefer Fahrenheit rather than Celsius for weather."),
        )
        for text, expected in cases:
            response = self.turn(text, stream=True)
            self.assertIn("Saved memory", response["transcript"][-1]["text"])
            self.assertEqual(response["memory_status"], [response["transcript"][-1]["text"]])
            self.assertIn(expected, [record.text for record in self.memory.list_memories()])
        self.assertEqual(self.provider.requests, [])

    def test_memory_directive_does_not_intercept_timed_reminders_or_casual_talk(self):
        self.app._planning = None
        reminder = self.turn("Remember to take out the trash at 8 PM.", stream=True)
        self.assertIn("today or tomorrow", reminder["transcript"][-1]["text"])
        self.assertEqual(self.tasks.list_reminders(), ())
        created = self.turn("Remember to take out the trash at 8 PM today.", stream=True)
        self.assertIn("I’ll remind you", created["transcript"][-1]["text"])
        self.assertEqual(len(self.tasks.list_reminders()), 1)
        self.provider.answer = "I remember our earlier discussion."
        casual = self.turn("I remember that conversation.", stream=True)
        self.assertEqual(casual["transcript"][-1]["text"], self.provider.answer)
        self.assertEqual(self.memory.list_memories(), ())

    def test_reminder_day_clarification_is_resolved_without_model_generation(self):
        self.app._planning = None
        clarification = self.turn(
            "Remember to take out the trash at 8 PM.", stream=True
        )
        self.assertIn("today or tomorrow", clarification["transcript"][-1]["text"])
        resolved = self.turn("Tonight", stream=True)
        self.assertIn("I’ll remind you", resolved["transcript"][-1]["text"])
        reminders = self.tasks.list_reminders()
        self.assertEqual(len(reminders), 1)
        self.assertEqual(reminders[0].reminder_text, "take out the trash")
        self.assertEqual(self.provider.requests, [])

    def test_ambiguous_memory_request_never_uses_a_model_persistence_promise(self):
        self.provider.answer = "I'll remember that next time."
        response = self.turn("Can you remember this important thing?", stream=True)
        text = response["transcript"][-1]["text"]
        self.assertIn("have not saved a memory", text)
        self.assertNotIn("I'll remember", text)
        self.assertEqual(self.memory.list_memories(), ())
        self.assertEqual(self.provider.requests, [])

    def test_finance_discussion_and_query_are_separate(self):
        before = self.finance.snapshot
        self.turn("Let's discuss making a trip budget.")
        self.assertEqual(len(self.provider.requests), 1)
        response = self.turn("How much did I spend on Amazon?", stream=True)
        self.assertIn("$105.00", response["transcript"][-1]["text"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(self.finance.snapshot, before)

    def test_planning_discussion_and_incomplete_action(self):
        self.turn("How does calendar planning work?")
        self.provider.intent = {"kind": "action", "capability": "planning"}
        response = self.turn("Can you create a plan on my calendar?", stream=True)
        self.assertIn("CalDAV", response["transcript"][-1]["text"])
        self.assertIn("date", response["transcript"][-1]["text"])
        self.assertEqual(self.planning.events, {})
        self.assertEqual(self.planning.tasks, {})

    def test_search_advisory_survives_time_context_and_yes_continues_query(self):
        original = "Who won the town tournament?"
        self.provider.answer = EXTERNAL_KNOWLEDGE_ADVISORY
        response = self.turn(original, stream=True)
        self.assertNotEqual(response["type"], "error")
        self.assertEqual(self.search.queries, [])
        self.provider.answer = "The synthetic evidence supports this answer [1]."
        response = self.turn("Yes, please", stream=True)
        self.assertEqual(self.search.queries, [original])
        self.assertIn("Web findings", response["transcript"][-1]["text"])
        self.assertIn(original, "\n".join(m.content for m in self.provider.requests[-1]))
        self.provider.answer = "Back to our conversation."
        self.turn("Anyway, hello again")
        self.assertEqual(self.search.queries, [original])

    def test_no_results_is_not_synthesis_failure(self):
        self.search.sources = ()
        self.provider.fail = True
        response = self.turn("Search the web for synthetic topic.", stream=True)
        self.assertEqual(response["type"], "complete")
        self.assertIn("No search results", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])
        self.assertNotIn("model", response["transcript"][-1])
        self.assertIsNone(self.app._archive_entries[-1].provider)

    def test_synthesis_failure_does_not_claim_no_results(self):
        self.provider.fail = True
        response = self.turn("Search the web for synthetic topic.", stream=True)
        self.assertEqual(response["code"], "search_synthesis_failed")
        self.assertIn("Retrieval completed with 1", response["error"])

    def test_project_and_coding_proposals_keep_confirmation(self):
        project = self.turn("Create a project called Tori repair.", stream=True)
        self.assertEqual(project["confirmation"]["action"], "project.create")
        self.assertEqual(self.chats.list_projects(), ())
        self.app.confirm(project["confirmation"]["token"], "cancel")
        self.app.new_session(True)
        coding = self.turn(f"Use OpenCode to audit {self.root}.", stream=True)
        self.assertEqual(coding["confirmation"]["action"], "coding_work.authorize")
        self.assertFalse(coding["confirmation"]["proposal"]["workspace_access"]["modify"])
        self.assertEqual(self.work.calls, [])

    def test_capability_status_changes_without_model_or_mutation(self):
        response = self.turn("Can you use OpenCode?")
        self.assertIn("ready", response["transcript"][-1]["text"])
        self.work.admission_open = False
        self.work.readiness = SimpleNamespace(reason="OpenCode executable is unavailable")
        response = self.turn("Can you use OpenCode?", stream=True)
        self.assertIn("OpenCode executable is unavailable", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])
        self.search.available = False
        assert_projected_state(self, self.app._capabilities.awareness(), "Search/SearXNG", "unavailable")
        self.preferences._administrator_web_search = False
        assert_projected_state(self, self.app._capabilities.awareness(), "Search/SearXNG", "disabled")

    def test_semantic_discussion_bypasses_operational_parsers(self):
        # Not one of the deterministic discussion guards. Even task-like wording
        # is advisory discussion, not application mutation authority.
        self.provider.intent = {"kind": "discussion", "capability": "tasks"}
        response = self.turn("I have questions concerning reminders and their limitations.", stream=True)
        self.assertEqual(response["transcript"][-1]["text"], self.provider.answer)
        self.assertEqual(len(self.provider.intent_requests), 1)
        self.assertEqual(self.tasks.list_reminders(), ())
        self.assertEqual(self.planning.tasks, {})

    def test_sync_search_continuation_and_empty_results(self):
        original = "Who won the town tournament?"
        self.provider.answer = EXTERNAL_KNOWLEDGE_ADVISORY
        self.turn(original)
        self.provider.answer = "Synthetic answer [1]."
        self.turn("Yes please")
        self.assertEqual(self.search.queries, [original])
        self.search.sources = ()
        before = len(self.provider.requests)
        response = self.turn("Search the web for a second synthetic topic.")
        self.assertIn("No search results", response["transcript"][-1]["text"])
        self.assertEqual(len(self.provider.requests), before)

    def test_model_awareness_updates_with_current_permission(self):
        self.turn("Hello")
        before = "\n".join(m.content for m in self.provider.requests[-1])
        self.assertIn("Search/SearXNG: configured", before)
        self.preferences._administrator_web_search = False
        self.turn("Hello again")
        after = "\n".join(m.content for m in self.provider.requests[-1])
        self.assertIn("Search/SearXNG: disabled", after)
        assert_projected_state(self, after, "Finance", "configured")

    def test_new_awareness_uses_local_state_without_external_probes(self):
        night_store = SQLiteNightOwlStore(self.root / "night_owl.db")
        self.app._night_owl_store = night_store
        self.app._night_owl = SimpleNamespace(conversation_finding_detail=lambda _text: None)
        self.app._security_center = object()
        self.app._restore = object()
        self.app.voice_input = SimpleNamespace(status=lambda: {"configured": True, "state": "off"})
        self.turn("Hello")
        first = "\n".join(message.content for message in self.provider.requests[-1])
        for name, state in (("Voice input", "configured"), ("Night Owl", "disabled"),
                            ("Security Center", "disabled"), ("Verified restore", "available"),
                            ("Search/SearXNG", "configured")):
            assert_projected_state(self, first, name, state)
        self.assertIn("Direct image generation is not available", first)
        self.assertNotIn("no microphone/STT", first)
        self.assertNotIn("Supervised /run", first)
        night_store.save_settings(NightOwlSettings(enabled=True, categories=("security",)), expected_revision=0)
        self.app.voice_input = SimpleNamespace(status=lambda: {"configured": True, "state": "ready"})
        self.turn("Hello again")
        second = "\n".join(message.content for message in self.provider.requests[-1])
        for name, state in (("Voice input", "available"), ("Night Owl", "configured"),
                            ("Security Center", "configured")):
            assert_projected_state(self, second, name, state)

    def test_capability_questions_are_natural_provider_free_and_inert(self):
        self.app.voice_input = SimpleNamespace(status=lambda: {"configured": True, "state": "off"})
        self.app._restore = object()
        self.app.terminal_launcher = object()
        self.app.terminal_broker = object()
        night_store = SQLiteNightOwlStore(self.root / "night_owl.db")
        self.app._night_owl_store = night_store
        self.app._night_owl = SimpleNamespace(conversation_finding_detail=lambda _text: None)
        self.app._security_center = object()
        for question, expected in (
            ("Can you listen to me or use voice input?", "push-to-talk"),
            ("Can you speak responses out loud?", "selected local TTS profile"),
            ("Can you run a command for me?", "supervised Terminal"),
            ("Do you have a Security Center?", "not a scanner"),
            ("Can you restore a Tori backup?", "safety backup"),
            ("Can you search the web?", "public web sources"),
        ):
            result = self.turn(question, stream=True)
            answer = result["transcript"][-1]["text"]
            self.assertIn(expected, answer)
            for mechanical in ("I have Voice input:", "Current state:", "Boundary:",
                               "Please clarify the specific supported operation", "Nothing has been executed"):
                self.assertNotIn(mechanical, answer)
            self.assertNotIn("confirmation", result)
        self.assertEqual(self.provider.requests, [])
        self.assertEqual(self.provider.intent_requests, [])
        self.assertEqual(self.work.calls, [])
        self.assertEqual(self.search.queries, [])
        self.assertEqual(night_store.list_runs(), ())

    def test_disabled_and_unavailable_capability_questions_remain_truthful(self):
        self.app.voice_input = SimpleNamespace(status=lambda: {"configured": False, "state": "off"})
        answer = self.turn("Can you listen to me?")["transcript"][-1]["text"]
        self.assertIn("isn't configured", answer)
        self.assertNotIn("Current state:", answer)
        self.preferences._administrator_web_search = False
        answer = self.turn("Can you search the web?")["transcript"][-1]["text"]
        self.assertIn("currently turned off", answer)
        self.assertEqual(self.search.queries, [])
        self.provider.answer = "I can't generate images directly."
        answer = self.turn("Can you generate an image?", stream=True)["transcript"][-1]["text"]
        self.assertIn("can't generate images", answer)
        self.assertEqual(len(self.provider.requests), 1)
        self.assertIsNone(capability_question("Can you run a command for me to change files?"))

    def test_information_intent_has_no_action_clarification(self):
        result = self.app._capability_fallback(
            "Tell me about the terminal.", MessageIntent("information", "run", True)
        )
        self.assertIsNotNone(result)
        text = result["transcript"][-1]["text"]
        self.assertIn("supervised Terminal", text)
        self.assertNotIn("Please clarify", text)
        self.assertNotIn("Nothing has been executed", text)
        self.assertEqual(self.work.calls, [])

    def test_registry_advises_local_capabilities_but_never_enables_remote_tools(self):
        self.assertIn("remote_chat", self.app._capabilities.snapshot())
        from tori.remote_chat_runtime import _remote_capability_awareness
        remote = _remote_capability_awareness()
        self.assertNotIn("Security Center", remote)
        self.assertNotIn("Supervised Terminal", remote)
        self.assertIn("execution, mutations", remote)

    def test_memory_management_newest_first_without_store_rewrite(self):
        from datetime import timedelta
        self.memory._clock = lambda: self.now
        older = self.memory.create("I prefer tea.")
        self.memory._clock = lambda: self.now + timedelta(days=1)
        newer = self.memory.create("I like root beer.")
        import hashlib
        path = self.root / "memory.db"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        items = self.app._management.list_memories()
        self.assertEqual([item.identifier for item in items], [newer.identifier, older.identifier])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_semantic_proposal_cannot_supply_executable_arguments(self):
        self.provider.intent = {"kind": "action", "capability": "run", "command": "touch forbidden"}
        result = self.app._understanding.interpret("Talk about shell command safety", self.provider, "model")
        self.assertEqual(result.kind, "conversation")
        self.assertEqual(self.work.calls, [])


class RegistryTests(unittest.TestCase):
    def test_all_configured_awareness_keeps_smallest_context_usable(self):
        registry = CapabilityRegistry({
            item.identifier: lambda: CapabilityState("available") for item in CAPABILITIES
        })
        current_time = capture_time_context(
            lambda: datetime(2026, 9, 27, 12, tzinfo=timezone.utc), "America/Chicago"
        )
        guidance = interaction_guidance_message()
        required = (
            runtime_identity_message(),
            ChatMessage("system", guidance.content + "\n\n" + registry.awareness()),
            ChatMessage("system", current_time.provider_context()),
            ChatMessage("user", "Can you help me with a task?"),
        )
        self.assertLess(estimate_messages_tokens(required),
                        context_input_limit(ContextPolicy.fixed(4096), None))

    def test_explicit_memory_and_reminder_boundaries_are_application_owned(self):
        self.assertEqual(
            explicit_memory_text("Can you remember to give me weather in F rather than C degrees?"),
            "I prefer Fahrenheit rather than Celsius for weather.",
        )
        self.assertIsNone(explicit_memory_text("Remember to call Bob tomorrow."))
        self.assertTrue(ambiguous_memory_request("Can you remember this important thing?"))
        self.assertFalse(ambiguous_memory_request("I remember this important thing."))

    def test_discussion_guard_does_not_hide_explicit_repair_request(self):
        self.assertFalse(is_capability_discussion("Fix the code in /tmp/example because reminders are not working."))

    def test_unknown_intents_extra_fields_and_commands_cannot_gain_authority(self):
        understanding = CapabilityUnderstanding(CapabilityRegistry())
        provider = Provider()
        for document in (
            {"kind": "execute", "capability": "tasks"},
            {"kind": "action", "capability": "invented_tool"},
            {"kind": "action", "capability": "tasks", "arguments": {}},
            {"kind": ["action"], "capability": "tasks"},
        ):
            provider.intent = document
            result = understanding.interpret("What tasks are supported?", provider, "model")
            self.assertFalse(result.understood)
        before = len(provider.intent_requests)
        understanding.interpret("/run Brave", provider, "model")
        self.assertEqual(len(provider.intent_requests), before)

    def test_read_failure_is_safe_and_awareness_is_bounded(self):
        def broken():
            raise RuntimeError("secret diagnostic")
        registry = CapabilityRegistry({"memory": broken})
        text = registry.awareness()
        assert_projected_state(self, text, "Memory", "unavailable")
        self.assertNotIn("secret diagnostic", text)
        self.assertLess(len(text), 3000)

    def test_current_capability_descriptions_are_bounded_and_not_image_execution(self):
        registry = CapabilityRegistry({
            "tts": lambda: CapabilityState("configured"),
            "voice_input": lambda: CapabilityState("configured"),
            "security": lambda: CapabilityState("disabled"),
            "scheduled_work": lambda: CapabilityState("available"),
            "night_owl": lambda: CapabilityState("disabled"),
            "capability_growth": lambda: CapabilityState("available"),
            "restore": lambda: CapabilityState("configured"),
            "run": lambda: CapabilityState("configured"),
            "search": lambda: CapabilityState("configured"),
        })
        text = registry.awareness()
        self.assertEqual(text, registry.awareness())
        for expected in (
            "Search/SearXNG", "public web search", "Voice input",
            "push-to-talk", "Supervised Terminal", "Night Owl",
            "Security Center", "not local scans or alerts", "Capability Growth",
            "Verified restore", "Direct image generation is not available",
        ):
            self.assertIn(expected, text)
        for name, state in (("Security Center", "disabled"), ("Night Owl", "disabled"),
                            ("Speech output", "configured"), ("Voice input", "configured"),
                            ("Verified restore", "configured"), ("Scheduled Work", "available")):
            assert_projected_state(self, text, name, state)
        for identifier, phrase in (("scheduled_work", "Night Owl"),
                                   ("tts", "OpenAI-compatible"), ("restore", "safety backup"),
                                   ("capability_growth", "Skills Reviews")):
            self.assertIn(phrase, registry.describe(identifier))
        self.assertNotIn("Supervised /run", text)
        self.assertNotIn("selected Qwen/Kokoro", text)
        self.assertNotIn("no microphone/STT", text)
        self.assertIn("not a scanner", registry.describe("security"))
        self.assertIn("no automatic", registry.describe("night_owl"))
        absent = CapabilityRegistry().awareness()
        self.assertIn("Supported but not configured here:", absent)
        self.assertIn("Voice input", absent)
        self.assertIn("Security Center", absent)

    def test_absent_mcp_uses_no_model_context_but_configured_state_does(self):
        self.assertNotIn("MCP Time:", CapabilityRegistry().awareness())
        registry = CapabilityRegistry(
            {"mcp_time": lambda: CapabilityState("available")}
        )
        assert_projected_state(self, registry.awareness(), "MCP Time", "available")


if __name__ == "__main__":
    unittest.main()
