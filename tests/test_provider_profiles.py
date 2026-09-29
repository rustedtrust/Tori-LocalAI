from __future__ import annotations

from pathlib import Path
from http.client import HTTPConnection
import json
import socket
import sqlite3
import threading
from tempfile import TemporaryDirectory
import unittest

from tori.config import ProviderProfile
from tori.checkpoints import CheckpointStore
from tori.chats import ChatService
from tori.conversation_archive import ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.model_catalog import ModelIdentity
from tori.local_provider_settings import (
    LocalProviderSettingsError,
    LocalProviderSettingsStore,
)
from tori.provider_profiles import (
    ModelProviderProfileController,
    ProviderProfileConflictError,
    ProviderProfileStoreCorruptError,
    ProviderProfileStoreUnavailableError,
    ProviderProfileValidationError,
    SQLiteProviderProfileStore,
)
from tori.providers.base import (
    ChatResponse,
    ModelDescriptor,
    ProviderAuthenticationError,
    ProviderStream,
)
from tori.web import LOOPBACK_HOST, WebApplication, WebApplicationError, create_web_server


class FakeProvider:
    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id

    def list_models(self):  # type: ignore[no-untyped-def]
        return (ModelDescriptor(self.profile_id, "shared", "Shared", "available"),)

    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("ok", "shared")

    def chat_with_options(self, messages, **options):  # type: ignore[no-untyped-def]
        return self.chat(messages)

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        return ProviderStream(iter(("ok",)))

    def stream_chat_with_options(self, messages, **options):  # type: ignore[no-untyped-def]
        return self.stream_chat(messages)

    def extract_memory_candidates(self, messages, *, model):  # type: ignore[no-untyped-def]
        return ChatResponse('{"candidates":[]}', model)

    def assess_memory_relationship(self, messages, *, model):  # type: ignore[no-untyped-def]
        return ChatResponse('{"relationship":"unrelated"}', model)

    def interpret_task_intent(self, messages, *, model):  # type: ignore[no-untyped-def]
        return ChatResponse('{"intent":"none"}', model)


class AuthenticationRequiredProvider(FakeProvider):
    def list_models(self):  # type: ignore[no-untyped-def]
        raise ProviderAuthenticationError("Authentication required.")


def profile_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "display_name": "Secondary Local",
        "base_url": "http://192.168.1.50:11434/v1",
        "timeout_seconds": 30,
        "authentication": "none",
        "structured_output": "json_object",
        "known_models": [
            {
                "model": "gemma4:12b",
                "display_name": "Gemma 4 12B",
                "context_window_tokens": None,
            }
        ],
    }
    values.update(overrides)
    return values


class ProviderProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "profiles" / "providers.db"
        self.store = SQLiteProviderProfileStore(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_explicit_schema_one_initialization_and_exact_empty_read(self) -> None:
        self.assertFalse(self.path.exists())
        with self.assertRaises(ProviderProfileStoreUnavailableError):
            self.store.list_profiles()
        self.store.initialize()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.list_profiles(), ())
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM provider_profile_metadata WHERE key='schema_version'"
                ).fetchone()[0],
                "1",
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with self.assertRaises(ProviderProfileConflictError):
            self.store.initialize()

    def test_create_update_enable_disable_delete_and_stale_revisions(self) -> None:
        self.store.initialize()
        created = self.store.create(identifier="secondary", **profile_values())
        self.assertEqual(created.identifier, "secondary")
        self.assertEqual(created.revision, 1)
        renamed = self.store.update(
            "secondary", expected_revision=1,
            **profile_values(display_name="Renamed Local"),
        )
        self.assertEqual(renamed.identifier, created.identifier)
        self.assertEqual(renamed.display_name, "Renamed Local")
        self.assertEqual(renamed.revision, 2)
        with self.assertRaises(ProviderProfileConflictError):
            self.store.update("secondary", expected_revision=1, **profile_values())
        disabled = self.store.set_enabled(
            "secondary", expected_revision=2, enabled=False
        )
        self.assertFalse(disabled.enabled)
        with self.assertRaises(ProviderProfileConflictError):
            self.store.delete("secondary", expected_revision=2)
        self.store.delete("secondary", expected_revision=3)
        self.assertEqual(self.store.list_profiles(), ())

    def test_local_network_auth_and_known_model_validation(self) -> None:
        self.store.initialize()
        for endpoint in (
            "http://localhost:11434/v1", "http://8.8.8.8:11434/v1",
            "http://169.254.1.1:11434/v1", "http://192.168.1.50/v1",
            "http://192.168.1.50:11434/v1/models",
            "http://user@192.168.1.50:11434/v1",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ProviderProfileValidationError):
                self.store.create(**profile_values(base_url=endpoint))
        with self.assertRaises(ProviderProfileValidationError):
            self.store.create(**profile_values(authentication="api_key"))
        with self.assertRaises(ProviderProfileValidationError):
            self.store.create(**profile_values(known_models=[{
                "model": "x", "display_name": "x", "context_window_tokens": 12,
            }]))
        accepted = self.store.create(**profile_values(
            base_url="https://127.1.2.3:8443", authentication="dummy_bearer"
        ))
        self.assertEqual(accepted.base_url, "https://127.1.2.3:8443/v1")
        self.assertEqual(accepted.authentication, "dummy_bearer")
        self.assertNotIn("tori-local-compatibility", self.path.read_bytes().decode("latin1"))

    def test_malformed_and_symlink_stores_fail_closed(self) -> None:
        self.path.parent.mkdir()
        self.path.write_bytes(b"not sqlite")
        with self.assertRaises(ProviderProfileStoreCorruptError):
            self.store.list_profiles()
        self.path.unlink()
        target = self.path.parent / "target.db"
        target.write_bytes(b"x")
        self.path.symlink_to(target)
        with self.assertRaises(ProviderProfileStoreUnavailableError):
            self.store.list_profiles()


class LocalProviderSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "private" / "providers.json"
        self.store = LocalProviderSettingsStore(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_token_is_owner_private_atomic_replaceable_and_clearable(self) -> None:
        self.assertEqual(self.store.records(), {})
        first = self.store.replace_token("lm_studio", "fake-token-one")
        self.assertEqual(first.token, "fake-token-one")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        second = self.store.replace_token("lm_studio", "fake-token-two")
        self.assertEqual(second.token, "fake-token-two")
        self.assertNotIn("fake-token-one", self.path.read_text(encoding="utf-8"))
        self.assertIn("fake-token-two", self.path.read_text(encoding="utf-8"))
        self.assertIsNone(self.store.clear_token("lm_studio"))
        self.assertEqual(self.store.records(), {})

    def test_unsafe_existing_file_is_rejected_without_replacement(self) -> None:
        self.path.parent.mkdir(mode=0o700)
        target = self.path.parent / "target"
        target.write_text("preserve", encoding="utf-8")
        self.path.symlink_to(target)
        with self.assertRaises(LocalProviderSettingsError):
            self.store.replace_token("lm_studio", "fake-token")
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")


class ProviderProfileControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.store = SQLiteProviderProfileStore(
            Path(self.temporary.name) / "profiles.db"
        )
        self.store.initialize()
        self.configured = ProviderProfile(
            "ollama", "Local Ollama", "ollama", "http://127.0.0.1:11434",
            30, keep_alive="5m",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def controller(self) -> ModelProviderProfileController:
        return ModelProviderProfileController(
            configured_profiles=(self.configured,),
            configured_identity=ModelIdentity("ollama", "shared"),
            provider_factory=lambda item, token: FakeProvider(item.identifier),
            store=self.store,
            local_settings=LocalProviderSettingsStore(
                Path(self.temporary.name) / "config" / "providers.json"
            ),
            environ={},
        )

    def test_sources_coexist_and_overlapping_model_ids_remain_distinct(self) -> None:
        controller = self.controller()
        created = controller.create(identifier="secondary", **profile_values())
        self.assertEqual(created.identifier, "secondary")
        self.assertEqual(controller.catalog.provider_identifiers, ("ollama", "secondary"))
        models = controller.catalog.catalog(refresh=True).models
        self.assertIn(("ollama", "shared"), {(x.provider, x.model) for x in models})
        self.assertIn(("secondary", "shared"), {(x.provider, x.model) for x in models})
        state = controller.state()
        config = next(x for x in state["profiles"] if x["identifier"] == "ollama")
        user = next(x for x in state["profiles"] if x["identifier"] == "secondary")
        self.assertTrue(config["editable"])
        self.assertFalse(config["deletable"])
        self.assertEqual(config["base_url"], "http://127.0.0.1:11434")
        self.assertTrue(user["editable"])
        self.assertNotIn("dummy_token", user)

    def test_collision_disable_and_delete_do_not_remap_identity(self) -> None:
        with self.assertRaises(ProviderProfileConflictError):
            self.controller().create(identifier="ollama", **profile_values())
        controller = self.controller()
        created = controller.create(identifier="secondary", **profile_values())
        controller.set_enabled(
            "secondary", expected_revision=created.revision, enabled=False
        )
        self.assertNotIn("secondary", controller.catalog.provider_identifiers)
        controller.delete("secondary", expected_revision=2)
        self.assertEqual(controller.catalog.provider_identifiers, ("ollama",))
        self.assertEqual(ModelIdentity("secondary", "shared").provider, "secondary")

    def test_preexisting_cross_source_collision_is_rejected(self) -> None:
        self.store.create(identifier="ollama", **profile_values())
        with self.assertRaises(ProviderProfileConflictError):
            self.controller()

    def test_built_in_override_preserves_identity_and_is_not_deletable(self) -> None:
        controller = self.controller()
        before = controller.state()["profiles"][0]
        controller.update(
            "ollama",
            expected_revision=before["revision"],
            display_name="Primary Ollama",
            base_url="http://127.0.0.1:11435",
            timeout_seconds=45,
            authentication="none",
            structured_output="json_object",
            known_models=[],
        )
        after = controller.state()["profiles"][0]
        self.assertEqual(after["identifier"], "ollama")
        self.assertEqual(after["implementation"], "ollama")
        self.assertEqual(after["display_name"], "Primary Ollama")
        self.assertEqual(after["base_url"], "http://127.0.0.1:11435")
        self.assertTrue(after["editable"])
        self.assertFalse(after["deletable"])
        with self.assertRaises(ProviderProfileValidationError):
            controller.delete("ollama", expected_revision=after["revision"])

    def test_stored_token_precedes_environment_and_clear_restores_fallback(self) -> None:
        captured: list[tuple[str, str | None]] = []
        lm_studio = ProviderProfile(
            "lm_studio", "LM Studio", "openai_compatible",
            "http://127.0.0.1:1234/v1", 30,
            authentication="environment_bearer",
            credential_environment="LM_API_TOKEN",
            structured_output="prompt_only",
        )
        local_settings = LocalProviderSettingsStore(
            Path(self.temporary.name) / "secrets" / "providers.json"
        )
        controller = ModelProviderProfileController(
            configured_profiles=(lm_studio,),
            configured_identity=ModelIdentity("lm_studio", "loaded-model"),
            provider_factory=lambda item, token: (
                captured.append((item.identifier, token)) or FakeProvider(item.identifier)
            ),
            store=self.store,
            local_settings=local_settings,
            environ={"LM_API_TOKEN": "fake-environment-token"},
        )
        initial = controller.state()["profiles"][0]
        self.assertEqual(initial["token_source"], "environment")
        self.assertNotIn("fake-environment-token", str(initial))
        controller.set_token(
            "lm_studio", action="replace", token="fake-stored-token"
        )
        stored = controller.state()["profiles"][0]
        self.assertEqual(stored["token_source"], "stored")
        self.assertNotIn("fake-stored-token", str(stored))
        self.assertEqual(captured[-1], ("lm_studio", "fake-stored-token"))
        controller.set_token("lm_studio", action="clear")
        cleared = controller.state()["profiles"][0]
        self.assertEqual(cleared["token_source"], "environment")
        self.assertNotIn("fake-environment-token", str(cleared))
        self.assertEqual(captured[-1], ("lm_studio", None))


class ProviderProfileWebApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = SQLiteProviderProfileStore(root / "providers" / "profiles.db")
        self.store.initialize()
        self.fake = FakeProvider("fake")
        configured = ProviderProfile(
            "fake", "Configured Fixture", "ollama", "http://127.0.0.1:11434",
            30, keep_alive="5m",
        )
        lm_studio = ProviderProfile(
            "lm_studio", "LM Studio", "openai_compatible",
            "http://127.0.0.1:1234/v1", 30,
            authentication="environment_bearer",
            credential_environment="LM_API_TOKEN",
            structured_output="prompt_only",
        )
        self.local_settings = LocalProviderSettingsStore(
            root / "config" / "providers.json"
        )
        self.controller = ModelProviderProfileController(
            configured_profiles=(configured, lm_studio),
            configured_identity=ModelIdentity("fake", "shared"),
            provider_factory=lambda item, token: (
                AuthenticationRequiredProvider(item.identifier)
                if item.identifier == "lm_studio"
                else FakeProvider(item.identifier)
            ),
            store=self.store,
            local_settings=self.local_settings,
            environ={},
        )
        self.chat_service = ChatService(
            ConversationArchiveStore(root / "conversations" / "archive.db")
        )
        self.application = WebApplication(
            self.fake,
            port=18765,
            checkpoint_store=CheckpointStore(root / "checkpoints"),
            memory_store=SQLiteMemoryStore(root / "memory" / "memory.db"),
            knowledge_registry=KnowledgeRegistry(root / "knowledge"),
            provider_name="fake",
            model_name="shared",
            provider_profile_controller=self.controller,
            chat_service=self.chat_service,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_safe_management_state_and_crud(self) -> None:
        initial = self.application.provider_profiles_state()
        configured = initial["profiles"][0]
        self.assertEqual(configured["source"], "configuration")
        self.assertTrue(configured["editable"])
        self.assertFalse(configured["deletable"])
        self.assertEqual(configured["base_url"], "http://127.0.0.1:11434")
        status, created = self.application.create_provider_profile(profile_values())
        self.assertEqual(status, 201)
        user = next(x for x in created["profiles"] if x["source"] == "user")
        self.assertEqual(user["base_url"], "http://192.168.1.50:11434/v1")
        self.assertNotIn("dummy_bearer_token", str(created))
        status, updated = self.application.update_provider_profile({
            "identifier": user["identifier"],
            "expected_revision": user["revision"],
            **profile_values(display_name="Edited Secondary"),
        })
        self.assertEqual(status, 200)
        edited = next(x for x in updated["profiles"] if x["source"] == "user")
        self.assertEqual(edited["display_name"], "Edited Secondary")
        with self.assertRaises(WebApplicationError) as confirmation:
            self.application.delete_provider_profile({
                "identifier": edited["identifier"],
                "expected_revision": edited["revision"],
                "confirmed": False,
            })
        self.assertEqual(confirmation.exception.code, "confirmation_required")

    def test_healthy_active_catalog_isolated_from_lm_authentication_failure(self) -> None:
        state = self.application.model_catalog_state(refresh=True)
        self.assertIsNone(state["error"])
        profiles = {item["identifier"]: item for item in state["profiles"]}
        self.assertEqual(profiles["fake"]["status"], "available")
        self.assertEqual(profiles["lm_studio"]["status"], "unavailable")
        managed = {
            item["identifier"]: item
            for item in self.application.provider_profiles_state()["profiles"]
        }
        self.assertEqual(
            managed["lm_studio"]["catalog_status"],
            {"availability": "unavailable", "reason_code": "authentication_required"},
        )

    def test_token_api_never_reads_secret_back_or_changes_selection(self) -> None:
        selected = self.application._selected_model
        status, state = self.application.set_provider_profile_token({
            "identifier": "lm_studio",
            "action": "replace",
            "token": "fake-browser-submitted-token",
        })
        self.assertEqual(status, 200)
        lm_studio = next(
            item for item in state["profiles"] if item["identifier"] == "lm_studio"
        )
        self.assertTrue(lm_studio["token_configured"])
        self.assertEqual(lm_studio["token_source"], "stored")
        self.assertNotIn("fake-browser-submitted-token", json.dumps(state))
        self.assertEqual(self.application._selected_model, selected)
        status, cleared = self.application.set_provider_profile_token({
            "identifier": "lm_studio", "action": "clear",
        })
        self.assertEqual(status, 200)
        lm_studio = next(
            item for item in cleared["profiles"] if item["identifier"] == "lm_studio"
        )
        self.assertFalse(lm_studio["token_configured"])
        self.assertIsNone(lm_studio["token_source"])
        self.assertEqual(self.application._selected_model, selected)

    def test_disabling_selected_profile_preserves_archive_identity_without_fallback(self) -> None:
        _, created = self.application.create_provider_profile(profile_values())
        user = next(x for x in created["profiles"] if x["source"] == "user")
        self.application.select_model(user["identifier"], "shared")
        self.application.submit("Create one archived turn")
        active_id = self.chat_service.active_chat_id()
        assert active_id is not None
        before = self.chat_service.get_chat(active_id)
        _, state = self.application.set_provider_profile_enabled({
            "identifier": user["identifier"],
            "expected_revision": user["revision"],
            "enabled": False,
        })
        after = self.chat_service.get_chat(active_id)
        self.assertEqual(
            after.metadata.selected_provider_name,
            before.metadata.selected_provider_name,
        )
        self.assertEqual(after.metadata.selected_model_name, before.metadata.selected_model_name)
        self.assertEqual(after.entries, before.entries)
        self.assertEqual(self.application._selected_model.provider, user["identifier"])
        self.assertIsNone(self.application._provider)
        self.assertFalse(next(x for x in state["profiles"] if x["source"] == "user")["enabled"])

    def test_busy_and_stale_mutations_are_rejected(self) -> None:
        _, created = self.application.create_provider_profile(profile_values())
        user = next(x for x in created["profiles"] if x["source"] == "user")
        self.application.set_provider_profile_enabled({
            "identifier": user["identifier"],
            "expected_revision": user["revision"],
            "enabled": False,
        })
        with self.assertRaises(WebApplicationError) as stale:
            self.application.set_provider_profile_enabled({
                "identifier": user["identifier"],
                "expected_revision": user["revision"],
                "enabled": True,
            })
        self.assertEqual(stale.exception.status, 409)
        self.application._operation_lock.acquire()
        try:
            with self.assertRaises(WebApplicationError) as busy:
                self.application.create_provider_profile(profile_values(display_name="Busy"))
            self.assertEqual(busy.exception.code, "busy")
        finally:
            self.application._operation_lock.release()


class ProviderProfileHTTPTests(ProviderProfileWebApplicationTests):
    def setUp(self) -> None:
        super().setUp()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((LOOPBACK_HOST, 0))
            port = probe.getsockname()[1]
        self.application.port = port
        self.application.expected_host = f"{LOOPBACK_HOST}:{port}"
        self.application.expected_origin = f"http://{self.application.expected_host}"
        self.server = create_web_server(self.application)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def request(
        self, method: str, path: str, body: dict[str, object] | None = None,
        *, origin: str | None = None, content_type: str = "application/json",
    ) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection(LOOPBACK_HOST, self.application.port, timeout=3)
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Host": self.application.expected_host}
        if body is not None:
            headers.update({
                "Origin": origin or self.application.expected_origin,
                "X-Tori-CSRF": self.application.csrf_token,
                "Content-Type": content_type,
            })
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        document = json.loads(response.read())
        connection.close()
        return response.status, document

    def test_routes_preserve_request_boundaries_and_minimize_configuration_data(self) -> None:
        status, initial = self.request("GET", "/api/model-providers")
        self.assertEqual(status, 200)
        configured = initial["profiles"][0]
        self.assertTrue(configured["editable"])
        self.assertFalse(configured["deletable"])
        self.assertEqual(configured["base_url"], "http://127.0.0.1:11434")
        status, edited_builtin = self.request(
            "POST", "/api/model-providers/update",
            {
                "identifier": configured["identifier"],
                "expected_revision": configured["revision"],
                "display_name": "Edited Local Ollama",
                "base_url": "http://127.0.0.1:11435",
                "timeout_seconds": 45,
                "authentication": "none",
                "structured_output": "json_object",
                "known_models": [],
            },
        )
        self.assertEqual(status, 200)
        edited_configured = next(
            item for item in edited_builtin["profiles"]
            if item["identifier"] == configured["identifier"]
        )
        self.assertEqual(edited_configured["display_name"], "Edited Local Ollama")
        self.assertEqual(edited_configured["base_url"], "http://127.0.0.1:11435")
        self.assertFalse(edited_configured["deletable"])
        body = profile_values(authentication="dummy_bearer")
        status, created = self.request("POST", "/api/model-providers/create", body)
        self.assertEqual(status, 201)
        self.assertNotIn("tori-local-compatibility", json.dumps(created))
        self.assertNotIn("authorization", json.dumps(created).lower())
        status, rejected = self.request(
            "POST", "/api/model-providers/create", body,
            origin="http://127.0.0.1:1",
        )
        self.assertEqual(status, 403)
        self.assertFalse(rejected["ok"])
        status, rejected = self.request(
            "POST", "/api/model-providers/create", body,
            content_type="text/plain",
        )
        self.assertEqual(status, 415)
        status, rejected = self.request(
            "POST", "/api/model-providers/create", {**body, "extra": True}
        )
        self.assertEqual(status, 400)

    def test_token_route_is_write_only_and_origin_protected(self) -> None:
        fake_token = "fake-http-token"
        status, saved = self.request(
            "POST", "/api/model-providers/token",
            {"identifier": "lm_studio", "action": "replace", "token": fake_token},
        )
        self.assertEqual(status, 200)
        self.assertNotIn(fake_token, json.dumps(saved))
        profile = next(
            item for item in saved["profiles"] if item["identifier"] == "lm_studio"
        )
        self.assertTrue(profile["token_configured"])
        self.assertEqual(profile["token_source"], "stored")
        status, rejected = self.request(
            "POST", "/api/model-providers/token",
            {"identifier": "lm_studio", "action": "replace", "token": "fake"},
            origin="http://127.0.0.1:1",
        )
        self.assertEqual(status, 403)
        self.assertNotIn("fake-http-token", json.dumps(rejected))
        status, cleared = self.request(
            "POST", "/api/model-providers/token",
            {"identifier": "lm_studio", "action": "clear"},
        )
        self.assertEqual(status, 200)
        profile = next(
            item for item in cleared["profiles"] if item["identifier"] == "lm_studio"
        )
        self.assertFalse(profile["token_configured"])


if __name__ == "__main__":
    unittest.main()
