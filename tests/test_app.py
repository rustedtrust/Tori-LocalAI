from __future__ import annotations

from contextlib import redirect_stderr
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tori.app import (
    build_tts,
    build_tts_profile_lifecycle,
    list_checkpoints,
    main,
    remove_checkpoint,
    run_interactive,
    run_once,
)
from tori.tts_profiles import SQLiteTTSProfileStore
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.config import Settings
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.model_catalog import ModelCatalogService, ModelDescriptor, ModelIdentity
from tori.providers import (
    ChatMessage,
    ChatResponse,
    ModelProvider,
    ProviderConnectionError,
    ProviderError,
)
from tori.user_settings import SQLiteUserSettingsStore


TEST_IDENTIFIER = "cp-20260725T064810Z-a1b2c3d4"
SECOND_IDENTIFIER = "cp-20260725T064811Z-b2c3d4e5"
TEST_TIME = datetime(2026, 7, 25, 6, 48, 10, tzinfo=timezone.utc)


class TTSConstructionTests(unittest.TestCase):
    def test_tts_is_disabled_cleanly_or_built_behind_coordinator(self) -> None:
        base = Settings("ollama", "fake", "http://127.0.0.1:11434", 30, "5m", "INFO")
        disabled = Settings(
            "ollama", "fake", "http://127.0.0.1:11434", 30, "5m", "INFO",
            tts_enabled=False,
        )
        self.assertIsNone(build_tts(disabled))
        coordinator = build_tts(base)
        self.assertIsNotNone(coordinator)
        self.assertEqual(coordinator.voice, "tori")  # type: ignore[union-attr]

    def test_kokoro_is_selected_through_the_same_coordinator_boundary(self) -> None:
        settings = Settings(
            "ollama",
            "fake",
            "http://127.0.0.1:11434",
            30,
            "5m",
            "INFO",
            tts_provider="kokoro",
            tts_endpoint="http://192.168.1.50:8880",
            tts_voice="af_heart",
        )

        coordinator = build_tts(settings)

        self.assertIsNotNone(coordinator)
        self.assertEqual(coordinator.voice, "af_heart")  # type: ignore[union-attr]
        self.assertEqual(  # type: ignore[union-attr]
            coordinator._provider.identity.provider_type, "kokoro"
        )

    def test_profile_lifecycle_seeds_legacy_configuration_once_without_overwrite(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "tts-profiles.db"
            settings = Settings(
                "ollama", "fake", "http://127.0.0.1:11434", 30, "5m", "INFO",
                tts_provider="kokoro",
                tts_endpoint="http://192.168.1.50:8880",
                tts_voice="af_heart",
            )
            coordinator, application, _runtime = build_tts_profile_lifecycle(
                settings, store=SQLiteTTSProfileStore(path)
            )

            selection, profile = application.get_active_profile()
            self.assertTrue(path.exists())
            self.assertEqual(selection.profile_identifier, "configured-speech")
            self.assertEqual(profile.provider_type, "kokoro")  # type: ignore[union-attr]
            self.assertEqual(coordinator.voice, "af_heart")  # type: ignore[union-attr]

            changed = Settings(
                "ollama", "fake", "http://127.0.0.1:11434", 30, "5m", "INFO",
                tts_provider="qwen",
                tts_voice="different",
            )
            reopened, reopened_application, _runtime = build_tts_profile_lifecycle(
                changed, store=SQLiteTTSProfileStore(path)
            )
            _selection, unchanged = reopened_application.get_active_profile()
            self.assertEqual(unchanged, profile)
            self.assertEqual(reopened.voice, "af_heart")  # type: ignore[union-attr]

    def test_disabled_speech_still_initializes_manageable_canonical_profile(self) -> None:
        with TemporaryDirectory() as temporary:
            settings = Settings(
                "ollama", "fake", "http://127.0.0.1:11434", 30, "5m", "INFO",
                tts_enabled=False,
            )
            coordinator, application, _runtime = build_tts_profile_lifecycle(
                settings,
                store=SQLiteTTSProfileStore(Path(temporary) / "profiles.db"),
            )
            self.assertIsNone(coordinator)
            self.assertEqual(
                application.get_active_profile()[0].profile_identifier,
                "configured-speech",
            )

    def test_existing_invalid_profile_store_is_never_replaced_or_migrated(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.db"
            original = b"existing canonical data that is not a TTS profile database"
            path.write_bytes(original)

            coordinator, _application, _runtime = build_tts_profile_lifecycle(
                Settings(
                    "ollama",
                    "fake",
                    "http://127.0.0.1:11434",
                    30,
                    "5m",
                    "INFO",
                ),
                store=SQLiteTTSProfileStore(path),
            )

            self.assertFalse(coordinator.configured())  # type: ignore[union-attr]
            self.assertEqual(path.read_bytes(), original)


class RecordingProvider(ModelProvider):
    def __init__(self, responses: tuple[str, ...] = ("A verified test response.",)) -> None:
        self.requests: list[tuple[ChatMessage, ...]] = []
        self._responses = iter(responses)

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse(content=next(self._responses), model="test-model")


class SelectableProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__(("First model answer", "Second model answer"))
        self.selected_models: list[str] = []

    def list_models(self):  # type: ignore[no-untyped-def]
        return (
            ModelDescriptor("ollama", "model-a", "Model A"),
            ModelDescriptor("ollama", "model-b", "Model B"),
        )

    def chat_for_model(self, messages, *, model):  # type: ignore[no-untyped-def]
        self.selected_models.append(model)
        response = super().chat(messages)
        return ChatResponse(response.content, model)


class ScriptedInput:
    def __init__(self, values: tuple[str, ...]) -> None:
        self._values = iter(values)

    def __call__(self, prompt: str) -> str:
        return next(self._values)


class RecordingInput(ScriptedInput):
    def __init__(self, values: tuple[str, ...]) -> None:
        super().__init__(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return super().__call__(prompt)


class InterruptingInput:
    def __call__(self, prompt: str) -> str:
        raise KeyboardInterrupt


class FailsOnceProvider(ModelProvider):
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise ProviderConnectionError("offline")
        return ChatResponse(content="Recovered answer", model="test-model")


class FailsOnceRequestProvider(ModelProvider):
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("synthetic private provider diagnostic")
        return ChatResponse(content="Recovered answer", model="test-model")


class RunOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_temporary = TemporaryDirectory()
        self.addCleanup(self.runtime_temporary.cleanup)
        archive = ConversationArchiveStore(
            Path(self.runtime_temporary.name) / "runtime" / "conversations.db"
        )
        patcher = patch("tori.app.ConversationArchiveStore", return_value=archive)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_routes_identity_and_one_user_message_through_provider(self) -> None:
        provider = RecordingProvider()

        result = run_once("  Hello, Tori.  ", provider)

        self.assertEqual(result, "A verified test response.")
        self.assertEqual(provider.requests[0][0].role, "system")
        self.assertIn("You are Tori", provider.requests[0][0].content)
        self.assertIn("Interaction guidance", provider.requests[0][1].content)
        self.assertEqual(
            provider.requests[0][2],
            ChatMessage(role="user", content="Hello, Tori."),
        )

    def test_rejects_empty_prompt(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            run_once("   ", RecordingProvider())

    def test_successful_one_request_is_automatically_archived(self) -> None:
        with TemporaryDirectory() as directory:
            service = ChatService(
                ConversationArchiveStore(
                    Path(directory) / "conversations.db",
                    identifier_factory=lambda: "chat-" + "a" * 32,
                )
            )
            answer = run_once(
                "Archive this turn",
                RecordingProvider(),
                chat_service=service,
                provider_name="fake",
                model_name="fake-model",
            )
            active = service.active_chat_id()
            self.assertEqual(answer, "A verified test response.")
            self.assertEqual(active, "chat-" + "a" * 32)
            self.assertEqual(service.get_chat(active).entries[0].text, "Archive this turn")  # type: ignore[arg-type]

    def test_one_request_uses_exact_selected_model_and_records_actual_model(self) -> None:
        provider = SelectableProvider()
        with TemporaryDirectory() as directory:
            service = ChatService(
                ConversationArchiveStore(
                    Path(directory) / "selected.db",
                    identifier_factory=lambda: "chat-" + "7" * 32,
                )
            )
            run_once(
                "Use the selection",
                provider,
                chat_service=service,
                provider_name="ollama",
                model_name="model-b",
            )
            detail = service.get_chat(service.active_chat_id())  # type: ignore[arg-type]
        self.assertEqual(provider.selected_models, ["model-b"])
        self.assertEqual(detail.metadata.selected_model.model, "model-b")
        self.assertEqual(detail.entries[-1].model, "model-b")

    def test_one_request_provider_failures_are_neutral_and_keep_exit_codes(
        self,
    ) -> None:
        settings = Settings(
            provider="ollama",
            model_name="configured-model",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=1.0,
            keep_alive="0",
            log_level="CRITICAL",
        )
        cases = (
            (
                ProviderConnectionError("private connection diagnostic"),
                3,
                "could not reach the configured model provider",
            ),
            (
                ProviderError("private request diagnostic"),
                4,
                "could not complete the model request",
            ),
        )

        for error, expected_code, expected_message in cases:
            with (
                self.subTest(error=type(error).__name__),
                patch("tori.app.CheckpointStore"),
                patch("tori.app.SQLiteMemoryStore"),
                patch("tori.app.KnowledgeRegistry"),
                patch("tori.app.load_settings", return_value=settings),
                patch("tori.app.configure_logging"),
                patch("tori.app.build_provider", return_value=RecordingProvider()),
                patch("tori.app.run_once", side_effect=error),
                patch("builtins.print") as print_mock,
                self.assertLogs("tori.app", level="ERROR"),
            ):
                result = main(("ordinary request",))

            rendered = "\n".join(
                str(call.args[0]) for call in print_mock.call_args_list
            )
            self.assertEqual(result, expected_code)
            self.assertIn(expected_message, rendered.casefold())
            self.assertNotIn("private", rendered.casefold())
            self.assertNotIn("ollama", rendered.casefold())


class InteractiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.checkpoint_root = (
            Path(self.temporary_directory.name) / "checkpoints"
        )
        self.checkpoint_store = CheckpointStore(
            self.checkpoint_root,
            clock=lambda: TEST_TIME,
            identifier_factory=lambda: TEST_IDENTIFIER,
        )

    def test_runs_multiple_turns_and_exits_by_command(self) -> None:
        provider = RecordingProvider(("First answer", "Second answer"))
        output: list[str] = []

        exit_code = run_interactive(
            provider,
            input_function=ScriptedInput(("First", "Second", "/exit")),
            output_function=output.append,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(any("Tori: First answer" in message for message in output))
        self.assertTrue(any("Tori: Second answer" in message for message in output))
        self.assertIn("/save [name]", output[0])
        self.assertEqual(output[-1], "Tori: Goodbye for now.")

    def test_completed_interactive_turns_create_and_reconcile_one_archive(self) -> None:
        service = ChatService(
            ConversationArchiveStore(
                Path(self.temporary_directory.name) / "conversations.db",
                identifier_factory=lambda: "chat-" + "b" * 32,
            )
        )
        exit_code = run_interactive(
            RecordingProvider(("First answer", "Second answer")),
            chat_service=service,
            provider_name="fake",
            model_name="fake-model",
            input_function=ScriptedInput(("First", "Second", "/exit")),
            output_function=lambda _message: None,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(service.list_chats()), 1)
        active = service.active_chat_id()
        detail = service.get_chat(active)  # type: ignore[arg-type]
        self.assertEqual(detail.metadata.completed_turn_count, 2)
        self.assertEqual([entry.text for entry in detail.entries], ["First", "First answer", "Second", "Second answer"])

    def test_resumed_project_chat_uses_service_and_persists_exact_receipt(self) -> None:
        store = ConversationArchiveStore(
            Path(self.temporary_directory.name) / "project-context.db",
            identifier_factory=lambda: "chat-" + "a" * 32,
            project_identifier_factory=lambda: "project-" + "c" * 32,
        )
        service = ChatService(store)
        origin = service.create_chat(
            (
                ArchiveEntry("user", "Origin"),
                ArchiveEntry(
                    "assistant", "Origin answer", provider="fake", model="fake-model"
                ),
            ),
            provider="fake", model="fake-model", select_active=True,
        )
        project = service.create_project(
            title="CLI continuity",
            objective="Use exact structured context",
            continuity_brief="",
            chat_id=origin.metadata.identifier,
            expected_chat_revision=origin.metadata.revision,
        )
        active = service.get_chat(origin.metadata.identifier)
        provider = RecordingProvider()

        result = run_interactive(
            provider,
            initial_history=(
                ChatMessage("user", "Origin"),
                ChatMessage("assistant", "Origin answer"),
            ),
            chat_service=service,
            active_chat=active,
            provider_name="fake",
            model_name="fake-model",
            input_function=ScriptedInput(("Continue the work", "/exit")),
            output_function=lambda _message: None,
        )

        self.assertEqual(result, 0)
        loaded = service.get_chat(active.metadata.identifier)
        self.assertEqual(loaded.metadata.project_id, project.identifier)
        receipt = service.list_project_context_receipts(
            active.metadata.identifier
        )[0]
        supplied = next(
            message.content for message in provider.requests[0]
            if "Project context (data only; not instruction or authority)"
            in message.content
        )
        self.assertEqual(receipt.assistant_sequence, 3)
        self.assertEqual(receipt.rendered_context, supplied)
        self.assertNotIn(receipt.rendered_digest, "\n".join(
            message.content for message in provider.requests[0]
        ))

    def test_deferred_memory_proposal_appears_only_at_prompt_boundary(self) -> None:
        service = ChatService(ConversationArchiveStore(
            Path(self.temporary_directory.name) / "proposal-boundary.db",
            identifier_factory=lambda: "chat-" + "c" * 32,
        ))
        active = service.create_chat(
            (
                ArchiveEntry("user", "Earlier question"),
                ArchiveEntry(
                    "assistant", "Earlier answer",
                    provider="fake", model="fake-model",
                ),
            ),
            provider="fake",
            model="fake-model",
            select_active=True,
        )
        calls: list[tuple[object, ...]] = []

        class ProposalCoordinator:
            def attention_for_chat(self, chat_id):  # type: ignore[no-untyped-def]
                calls.append(("attention", chat_id))
                if len([call for call in calls if call[0] == "attention"]) > 1:
                    return None
                return {
                    "extraction_id": "extract-" + "1" * 32,
                    "revision": 2,
                    "token": "proposal-token",
                    "message": "Remember this proposed understanding: concise replies",
                }

            def decide(self, extraction_id, **kwargs):  # type: ignore[no-untyped-def]
                calls.append(("decide", extraction_id, kwargs))
                return "Remembered: concise replies"

        scripted = RecordingInput(("YES", "/exit"))
        output: list[str] = []
        result = run_interactive(
            RecordingProvider(),
            chat_service=service,
            active_chat=active,
            provider_name="fake",
            model_name="fake-model",
            memory_coordinator=ProposalCoordinator(),  # type: ignore[arg-type]
            input_function=scripted,
            output_function=output.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            scripted.prompts,
            ["Save this memory? Type YES to confirm: ", "You: "],
        )
        self.assertEqual(calls[0], ("attention", active.metadata.identifier))
        self.assertEqual(calls[1][0], "decide")
        self.assertIn("Memory proposal:", output[1])
        self.assertEqual(output[2], "Remembered: concise replies")

    def test_model_commands_list_show_and_change_next_response_durably(self) -> None:
        provider = SelectableProvider()
        catalog = ModelCatalogService(
            {"ollama": provider}, configured=ModelIdentity("ollama", "model-a")
        )
        service = ChatService(
            ConversationArchiveStore(
                Path(self.temporary_directory.name) / "models.db",
                identifier_factory=lambda: "chat-" + "d" * 32,
            )
        )
        output: list[str] = []

        result = run_interactive(
            provider,
            chat_service=service,
            provider_name="ollama",
            model_name="model-a",
            model_catalog=catalog,
            input_function=ScriptedInput(
                ("/model", "/models", "First", "/model model-b", "Second", "/exit")
            ),
            output_function=output.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(provider.selected_models, ["model-a", "model-b"])
        detail = service.get_chat(service.active_chat_id())  # type: ignore[arg-type]
        self.assertEqual(
            [(entry.provider, entry.model) for entry in detail.entries if entry.role == "assistant"],
            [("ollama", "model-a"), ("ollama", "model-b")],
        )
        self.assertEqual(detail.metadata.selected_model.model, "model-b")
        self.assertTrue(any("Current model: ollama/model-a" in line for line in output))
        self.assertTrue(any("ollama/model-b" in line for line in output))

    def test_failed_model_selection_leaves_active_state_unchanged(self) -> None:
        provider = SelectableProvider()
        catalog = ModelCatalogService(
            {"ollama": provider}, configured=ModelIdentity("ollama", "model-a")
        )
        output: list[str] = []
        run_interactive(
            provider,
            provider_name="ollama",
            model_name="model-a",
            model_catalog=catalog,
            input_function=ScriptedInput(("/model missing", "Hello", "/exit")),
            output_function=output.append,
        )
        self.assertEqual(provider.selected_models, ["model-a"])
        self.assertTrue(any("not available" in line for line in output))

    def test_interactive_resume_preserves_historical_entry_model_metadata(self) -> None:
        service = ChatService(
            ConversationArchiveStore(
                Path(self.temporary_directory.name) / "resume-models.db",
                identifier_factory=lambda: "chat-" + "e" * 32,
            )
        )
        active = service.create_chat(
            (
                ArchiveEntry("user", "Old question"),
                ArchiveEntry(
                    "assistant",
                    "Old answer",
                    provider="old-provider",
                    model="old-model",
                ),
            ),
            provider="old-provider",
            model="old-model",
            select_active=True,
        )
        exit_code = run_interactive(
            RecordingProvider(("Current answer",)),
            initial_history=(
                ChatMessage("user", "Old question"),
                ChatMessage("assistant", "Old answer"),
            ),
            chat_service=service,
            active_chat=active,
            provider_name="current-provider",
            model_name="current-model",
            input_function=ScriptedInput(("Current question", "/exit")),
            output_function=lambda _message: None,
        )
        loaded = service.get_chat(active.metadata.identifier)
        self.assertEqual(exit_code, 0)
        self.assertEqual((loaded.entries[1].provider, loaded.entries[1].model), ("old-provider", "old-model"))
        self.assertEqual((loaded.entries[3].provider, loaded.entries[3].model), ("current-provider", "test-model"))

    def test_empty_input_does_not_call_provider(self) -> None:
        provider = RecordingProvider()
        output: list[str] = []

        exit_code = run_interactive(
            provider,
            input_function=ScriptedInput(("   ", "/quit")),
            output_function=output.append,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.requests, [])
        self.assertTrue(any("cannot be empty" in message for message in output))

    def test_keyboard_interrupt_stops_cleanly(self) -> None:
        output: list[str] = []

        exit_code = run_interactive(
            RecordingProvider(),
            input_function=InterruptingInput(),
            output_function=output.append,
        )

        self.assertEqual(exit_code, 130)
        self.assertEqual(output[-1], "\nTori stopped.")

    def test_provider_failure_allows_retry_in_same_session(self) -> None:
        provider = FailsOnceProvider()
        output: list[str] = []

        with self.assertLogs("tori.app", level="ERROR"):
            exit_code = run_interactive(
                provider,
                input_function=ScriptedInput(
                    ("First attempt", "Second attempt", "/exit")
                ),
                output_function=output.append,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.calls, 2)
        self.assertTrue(
            any(
                "could not reach the configured model provider" in message
                for message in output
            )
        )
        self.assertTrue(any("Recovered answer" in message for message in output))

    def test_provider_request_failure_allows_retry_without_raw_diagnostic(
        self,
    ) -> None:
        provider = FailsOnceRequestProvider()
        output: list[str] = []

        with self.assertLogs("tori.app", level="ERROR"):
            exit_code = run_interactive(
                provider,
                input_function=ScriptedInput(
                    ("First attempt", "Second attempt", "/exit")
                ),
                output_function=output.append,
            )

        rendered = "\n".join(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(provider.calls, 2)
        self.assertIn("could not complete the model request", rendered)
        self.assertIn("Recovered answer", rendered)
        self.assertNotIn("synthetic private provider diagnostic", rendered)

    def test_exit_without_save_creates_no_checkpoint(self) -> None:
        exit_code = run_interactive(
            RecordingProvider(),
            checkpoint_store=self.checkpoint_store,
            input_function=ScriptedInput(("Hello", "/exit")),
            output_function=lambda message: None,
        )

        self.assertEqual(exit_code, 0)
        self.assertFalse(self.checkpoint_root.exists())

    def test_save_after_exchange_creates_one_checkpoint_without_provider_call(self) -> None:
        provider = RecordingProvider()
        output: list[str] = []

        exit_code = run_interactive(
            provider,
            checkpoint_store=self.checkpoint_store,
            provider_name="ollama",
            model_name="active-model",
            input_function=ScriptedInput(
                ("Remember cobalt", "/save Cobalt conversation", "/exit")
            ),
            output_function=output.append,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0][-1].content, "Remember cobalt")
        self.assertEqual(len(tuple(self.checkpoint_root.glob("*.json"))), 1)
        metadata = self.checkpoint_store.list_checkpoints()[0]
        self.assertEqual(metadata.display_name, "Cobalt conversation")
        self.assertEqual(metadata.provider, "ollama")
        self.assertEqual(metadata.model, "active-model")
        self.assertTrue(
            any(TEST_IDENTIFIER in message for message in output)
        )
        self.assertTrue(
            any("Cobalt conversation" in message for message in output)
        )
        self.assertTrue(
            any(str(self.checkpoint_root) in message for message in output)
        )

    def test_save_before_exchange_fails_and_session_remains_usable(self) -> None:
        provider = RecordingProvider()
        output: list[str] = []

        exit_code = run_interactive(
            provider,
            checkpoint_store=self.checkpoint_store,
            input_function=ScriptedInput(
                ("/save", "A real question", "/save", "/quit")
            ),
            output_function=output.append,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(len(tuple(self.checkpoint_root.glob("*.json"))), 1)
        self.assertTrue(
            any("There is no completed conversation" in message for message in output)
        )
        self.assertTrue(
            any("Saved checkpoint" in message for message in output)
        )

    def test_failed_provider_request_is_absent_from_saved_checkpoint(self) -> None:
        provider = FailsOnceProvider()

        with self.assertLogs("tori.app", level="ERROR"):
            exit_code = run_interactive(
                provider,
                checkpoint_store=self.checkpoint_store,
                input_function=ScriptedInput(
                    (
                        "Failed private prompt",
                        "Successful prompt",
                        "/save",
                        "/exit",
                    )
                ),
                output_function=lambda message: None,
            )

        self.assertEqual(exit_code, 0)
        checkpoint = self.checkpoint_store.load_checkpoint(TEST_IDENTIFIER)
        self.assertEqual(
            checkpoint.messages,
            (
                ChatMessage(role="user", content="Successful prompt"),
                ChatMessage(role="assistant", content="Recovered answer"),
            ),
        )


class CheckpointCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "checkpoints"
        runtime_root = Path(self.temporary_directory.name) / "injected-runtime"
        injected_stores = {
            "CheckpointStore": CheckpointStore(runtime_root / "checkpoints"),
            "ConversationArchiveStore": ConversationArchiveStore(
                runtime_root / "conversations" / "tori.db"
            ),
            "SQLiteMemoryStore": SQLiteMemoryStore(runtime_root / "memory" / "tori.db"),
            "KnowledgeRegistry": KnowledgeRegistry(runtime_root / "knowledge"),
            "SQLiteUserSettingsStore": SQLiteUserSettingsStore(
                runtime_root / "settings" / "tori_settings.db"
            ),
        }
        for name, store in injected_stores.items():
            patcher = patch(f"tori.app.{name}", return_value=store)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.messages = (
            ChatMessage(role="user", content="Private transcript phrase"),
            ChatMessage(role="assistant", content="Private response phrase"),
        )

    def make_store(
        self,
        identifier: str = TEST_IDENTIFIER,
    ) -> CheckpointStore:
        return CheckpointStore(
            self.root,
            clock=lambda: TEST_TIME,
            identifier_factory=lambda: identifier,
        )

    def save_checkpoint(
        self,
        *,
        identifier: str = TEST_IDENTIFIER,
        display_name: str | None = "Named checkpoint",
        model: str = "saved-model",
    ) -> CheckpointStore:
        store = self.make_store(identifier)
        store.save_checkpoint(
            self.messages,
            display_name=display_name,
            provider="saved-provider",
            model=model,
        )
        return store

    def test_listing_prints_metadata_without_transcript_content(self) -> None:
        store = self.save_checkpoint()
        self.save_checkpoint(
            identifier=SECOND_IDENTIFIER,
            display_name=None,
        )
        output: list[str] = []

        list_checkpoints(store, output_function=output.append)

        rendered = "\n".join(output)
        self.assertIn(TEST_IDENTIFIER, rendered)
        self.assertIn("Named checkpoint", rendered)
        self.assertIn("2026-07-25T06:48:10Z", rendered)
        self.assertIn("messages: 2", rendered)
        self.assertIn("saved-provider", rendered)
        self.assertIn("saved-model", rendered)
        self.assertIn("<unnamed>", rendered)
        self.assertNotIn("Private transcript phrase", rendered)
        self.assertNotIn("Private response phrase", rendered)

    def test_listing_empty_store_succeeds_clearly(self) -> None:
        output: list[str] = []

        list_checkpoints(self.make_store(), output_function=output.append)

        self.assertEqual(
            output,
            [f"No checkpoints found in {self.root}."],
        )
        self.assertFalse(self.root.exists())

    def test_remove_deletes_only_selected_checkpoint(self) -> None:
        first_store = self.save_checkpoint(
            identifier=TEST_IDENTIFIER,
            display_name="First",
        )
        self.save_checkpoint(
            identifier=SECOND_IDENTIFIER,
            display_name="Second",
        )
        output: list[str] = []

        remove_checkpoint(
            first_store,
            TEST_IDENTIFIER,
            output_function=output.append,
        )

        self.assertFalse(
            (self.root / f"{TEST_IDENTIFIER}.json").exists()
        )
        self.assertTrue(
            (self.root / f"{SECOND_IDENTIFIER}.json").exists()
        )
        self.assertEqual(
            output,
            [f"Removed checkpoint {TEST_IDENTIFIER} (First)."],
        )

    def test_list_and_remove_do_not_load_settings_or_build_provider(self) -> None:
        store = self.save_checkpoint()

        with (
            patch("tori.app.CheckpointStore", return_value=store),
            patch("tori.app.load_settings") as load_settings_mock,
            patch("tori.app.build_provider") as build_provider_mock,
            patch("builtins.print"),
        ):
            list_result = main(("--list-checkpoints",))
            remove_result = main(
                ("--remove-checkpoint", TEST_IDENTIFIER)
            )

        self.assertEqual(list_result, 0)
        self.assertEqual(remove_result, 0)
        load_settings_mock.assert_not_called()
        build_provider_mock.assert_not_called()

    def test_failed_resume_does_not_build_provider_or_start_session(self) -> None:
        store = self.make_store()

        with (
            patch("tori.app.CheckpointStore", return_value=store),
            patch("tori.app.load_settings") as load_settings_mock,
            patch("tori.app.build_provider") as build_provider_mock,
            patch("tori.app.run_interactive") as interactive_mock,
            patch("builtins.print") as print_mock,
        ):
            result = main(("--resume", TEST_IDENTIFIER))

        self.assertEqual(result, 5)
        load_settings_mock.assert_not_called()
        build_provider_mock.assert_not_called()
        interactive_mock.assert_not_called()
        self.assertTrue(
            any(
                "was not found" in str(call)
                for call in print_mock.call_args_list
            )
        )

    def test_valid_resume_passes_history_and_uses_active_model(self) -> None:
        store = self.save_checkpoint(model="old-saved-model")
        active_settings = Settings(
            provider="ollama",
            model_name="current-active-model",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=600.0,
            keep_alive="5m",
            log_level="INFO",
        )
        active_provider = RecordingProvider()

        with (
            patch("tori.app.CheckpointStore", return_value=store),
            patch(
                "tori.app.load_settings",
                return_value=active_settings,
            ),
            patch("tori.app.configure_logging"),
            patch(
                "tori.app.build_provider",
                return_value=active_provider,
            ) as build_provider_mock,
            patch(
                "tori.app.run_interactive",
                return_value=0,
            ) as interactive_mock,
            patch("builtins.print") as print_mock,
        ):
            result = main(("--resume", TEST_IDENTIFIER))

        self.assertEqual(result, 0)
        build_provider_mock.assert_called_once_with(active_settings)
        interactive_mock.assert_called_once()
        call = interactive_mock.call_args
        self.assertIs(call.args[0], active_provider)
        self.assertEqual(call.kwargs["initial_history"], self.messages)
        self.assertEqual(call.kwargs["provider_name"], "ollama")
        self.assertEqual(
            call.kwargs["model_name"],
            "current-active-model",
        )
        rendered = "\n".join(
            str(call.args[0]) for call in print_mock.call_args_list
        )
        self.assertIn(TEST_IDENTIFIER, rendered)
        self.assertNotIn("Private transcript phrase", rendered)

    def test_positional_prompt_cannot_be_combined_with_checkpoint_actions(
        self,
    ) -> None:
        actions = (
            ("--list-checkpoints",),
            ("--resume", TEST_IDENTIFIER),
            ("--remove-checkpoint", TEST_IDENTIFIER),
        )

        for action in actions:
            with self.subTest(action=action), redirect_stderr(StringIO()):
                with self.assertRaisesRegex(
                    SystemExit,
                    "2",
                ):
                    main(("one request", *action))

    def test_checkpoint_actions_are_mutually_exclusive(self) -> None:
        with redirect_stderr(StringIO()):
            with self.assertRaisesRegex(SystemExit, "2"):
                main(
                    (
                        "--list-checkpoints",
                        "--resume",
                        TEST_IDENTIFIER,
                    )
                )

    def test_archive_list_remove_and_resume_use_safe_metadata_and_history(self) -> None:
        archive_store = ConversationArchiveStore(
            self.root / "conversations.db",
            identifier_factory=lambda: "chat-" + "c" * 32,
        )
        service = ChatService(archive_store)
        created = service.create_chat(
            (
                ArchiveEntry("user", "Private question"),
                ArchiveEntry(
                    "assistant",
                    "Private answer",
                    provider="ollama",
                    model="old-model",
                ),
            ),
            provider="ollama",
            model="old-model",
        )
        settings = Settings(
            provider="ollama",
            model_name="current-model",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=1,
            keep_alive="0",
            log_level="CRITICAL",
        )
        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("builtins.print") as printed,
        ):
            self.assertEqual(main(("--list-chats",)), 0)
        rendered = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn(created.metadata.identifier, rendered)
        self.assertNotIn("Private answer", rendered)

        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("tori.app.load_settings", return_value=settings),
            patch("tori.app.configure_logging"),
            patch("tori.app.build_provider", return_value=RecordingProvider()),
            patch("tori.app.run_interactive", return_value=0) as interactive,
            patch("builtins.print"),
        ):
            self.assertEqual(main(("--resume-chat", created.metadata.identifier)), 0)
        self.assertEqual(
            interactive.call_args.kwargs["initial_history"],
            (
                ChatMessage("user", "Private question"),
                ChatMessage("assistant", "Private answer"),
            ),
        )

        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("builtins.print"),
        ):
            self.assertEqual(main(("--remove-chat", created.metadata.identifier)), 0)
        self.assertEqual(service.list_chats(), ())

    def test_archived_missing_profile_is_not_replaced_by_configured_provider(self) -> None:
        archive_store = ConversationArchiveStore(
            self.root / "missing-profile.db",
            identifier_factory=lambda: "chat-" + "d" * 32,
        )
        created = archive_store.create_chat(
            (
                ArchiveEntry("user", "Question"),
                ArchiveEntry("assistant", "Answer", provider="removed", model="shared"),
            ),
            provider="removed",
            model="shared",
        )
        settings = Settings(
            provider="ollama", model_name="shared",
            base_url="http://127.0.0.1:11434", timeout_seconds=1,
            keep_alive="0", log_level="CRITICAL",
        )
        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("tori.app.load_settings", return_value=settings),
            patch("tori.app.configure_logging"),
            patch("tori.app.build_provider", return_value=RecordingProvider()),
            patch("tori.app.run_interactive") as interactive,
            patch("builtins.print") as printed,
        ):
            self.assertEqual(main(("--resume-chat", created.metadata.identifier)), 7)
        interactive.assert_not_called()
        rendered = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("no fallback", rendered)

    def test_cli_lists_and_selects_models_without_live_provider(self) -> None:
        settings = Settings(
            provider="ollama",
            model_name="model-a",
            base_url="http://127.0.0.1:11434",
            timeout_seconds=1,
            keep_alive="0",
            log_level="CRITICAL",
        )
        provider = SelectableProvider()
        archive_store = ConversationArchiveStore(
            self.root.parent / "cli-models.db"
        )
        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("tori.app.load_settings", return_value=settings),
            patch("tori.app.configure_logging"),
            patch("tori.app.build_provider", return_value=provider),
            patch("builtins.print") as printed,
        ):
            self.assertEqual(main(("--list-models",)), 0)
        rendered = "\n".join(str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("ollama/model-a", rendered)
        self.assertIn("ollama/model-b", rendered)

        with (
            patch("tori.app.ConversationArchiveStore", return_value=archive_store),
            patch("tori.app.load_settings", return_value=settings),
            patch("tori.app.configure_logging"),
            patch("tori.app.build_provider", return_value=provider),
            patch("tori.app.run_interactive", return_value=0) as interactive,
            patch("builtins.print"),
        ):
            self.assertEqual(main(("--new-chat", "--model", "model-b")), 0)
        self.assertEqual(interactive.call_args.kwargs["model_name"], "model-b")


if __name__ == "__main__":
    unittest.main()
