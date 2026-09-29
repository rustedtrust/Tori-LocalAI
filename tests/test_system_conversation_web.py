from __future__ import annotations

from collections import namedtuple
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.command_execution import CommandExecutionService, SandboxAvailability
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.providers import ChatResponse, ModelProvider
from tori.system_capabilities import SystemCapabilities, SystemConversationService
from tori.web import WebApplication, WebApplicationError


Usage = namedtuple("Usage", "total used free")


class _Provider(ModelProvider):
    def __init__(self) -> None:
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("model answer", "model")


class _Sandbox:
    def availability(self, _workspace: Path) -> SandboxAvailability:
        return SandboxAvailability(True, "test", "test isolation")

    def argv(self, command: str, workspace: Path) -> tuple[str, ...]:
        return ("/bin/sh", "-c", command, str(workspace))


class SystemConversationWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = self.root = Path(self.temporary.name)
        self.provider = _Provider()
        capabilities = SystemCapabilities(
            disk_usage_function=lambda _path: Usage(2 * 1024**3, 1 * 1024**3, 1 * 1024**3),
            address_function=lambda *_args, **_kwargs: [
                (None, None, None, None, ("192.168.1.20", 0))
            ],
            executable_resolver=lambda _name: None,
            brave_fallback_resolver=lambda: None,
        )
        workspace = root / "workspace"
        workspace.mkdir()
        self.application = WebApplication(
            self.provider,
            port=8765,
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge", working_directory=root),
            provider_name="fake",
            model_name="model",
            chat_service=ChatService(ConversationArchiveStore(root / "archive.db")),
            command_service=CommandExecutionService(workspace, sandbox=_Sandbox()),
            system_service=SystemConversationService(capabilities),
        )

    def test_system_read_is_application_owned_and_bypasses_model(self) -> None:
        status, response = self.application.submit("Tori, how much disk space do I have left?")
        self.assertEqual(status, 200)
        self.assertIn("1.0 GB free out of 2.0 GB", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])

        status, response = self.application.submit("What's my IP address?")
        self.assertEqual(status, 200)
        self.assertIn("192.168.1.20", response["transcript"][-1]["text"])
        self.assertEqual(self.provider.requests, [])

    def test_tori_health_projects_internal_application_state(self) -> None:
        application = WebApplication(
            self.provider,
            port=8766,
            checkpoint_store=CheckpointStore(self.root / "health-checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "health-memory.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "health-knowledge", working_directory=self.root
            ),
            provider_name="fake",
            model_name="model",
        )
        status, response = application.submit("Tori, is Tori healthy?")
        self.assertEqual(status, 200)
        self.assertEqual(
            response["transcript"][-1]["text"],
            "Tori is healthy. Conversation is available.",
        )
        self.assertEqual(self.provider.requests, [])

    def test_system_failure_is_bounded_and_internal_general_command_is_retired(self) -> None:
        status, response = self.application.submit("Open Brave.")
        self.assertEqual(status, 200)
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "system_capability_unavailable")
        self.assertEqual(self.provider.requests, [])

        stream = list(self.application.stream_submit("Open Brave."))
        self.assertEqual(stream[-1]["type"], "error")
        self.assertEqual(stream[-1]["error"], "Brave is not installed or available on this desktop.")
        self.assertNotIn("code", stream[-1])
        self.assertEqual(self.provider.requests, [])

        with self.assertRaises(WebApplicationError) as denied:
            self.application.submit("/run git status")
        self.assertEqual(denied.exception.code, "legacy_command_retired")
        self.assertEqual(self.provider.requests, [])

    def test_service_mutation_is_confirmed_bound_and_verified(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []
        state = {"running": True}

        def runner(argv: object, **kwargs: object) -> object:
            calls.append((argv, kwargs))
            state["running"] = True
            return SimpleNamespace(returncode=0)

        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=runner,
            radicale_status_function=lambda: state["running"],
            action_sleep_function=lambda _seconds: None,
        )
        application = WebApplication(
            self.provider,
            port=8767,
            checkpoint_store=CheckpointStore(self.root / "service-checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "service-memory.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "service-knowledge", working_directory=self.root
            ),
            provider_name="fake",
            model_name="model",
            chat_service=ChatService(
                ConversationArchiveStore(self.root / "service-archive.db")
            ),
            system_service=SystemConversationService(capabilities),
        )

        status, response = application.submit("Tori, restart Radicale.")
        self.assertEqual(status, 200)
        confirmation = response["confirmation"]
        self.assertEqual(confirmation["action"], "system.service_action")
        self.assertEqual(
            confirmation["proposal"],
            {
                "action": "Restart service",
                "service": "Radicale",
                "system_target": "tori-radicale.service",
                "control": "systemd --user",
            },
        )
        self.assertEqual(calls, [])
        status, response = application.confirm(confirmation["token"], "confirm")
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertIn("Planning is reachable", response["transcript"][-1]["text"])
        self.assertEqual(
            calls[0][0],
            ["/usr/bin/systemctl", "--user", "restart", "tori-radicale.service"],
        )
        self.assertFalse(calls[0][1]["shell"])
        with self.assertRaises(WebApplicationError) as raised:
            application.confirm(confirmation["token"], "confirm")
        self.assertEqual(raised.exception.code, "unknown_confirmation")

    def test_service_confirmation_is_stale_after_conversation_changes(self) -> None:
        calls: list[object] = []
        capabilities = SystemCapabilities(
            systemctl_path_function=lambda: "/usr/bin/systemctl",
            systemctl_runner=lambda argv, **_kwargs: (
                calls.append(argv) or SimpleNamespace(returncode=0)
            ),
            radicale_status_function=lambda: True,
            action_sleep_function=lambda _seconds: None,
        )
        application = WebApplication(
            self.provider,
            port=8768,
            checkpoint_store=CheckpointStore(self.root / "stale-checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "stale-memory.db"),
            knowledge_registry=KnowledgeRegistry(
                self.root / "stale-knowledge", working_directory=self.root
            ),
            provider_name="fake",
            model_name="model",
            chat_service=ChatService(
                ConversationArchiveStore(self.root / "stale-archive.db")
            ),
            system_service=SystemConversationService(capabilities),
        )
        _status, response = application.submit("Restart Ollama.")
        token = response["confirmation"]["token"]
        application.submit("A normal conversational question")
        with self.assertRaises(WebApplicationError) as raised:
            application.confirm(token, "confirm")
        self.assertEqual(raised.exception.code, "stale_confirmation")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
