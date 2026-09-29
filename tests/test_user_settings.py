from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tori.app import run_interactive, run_once
from tori.capabilities import CapabilityResult
from tori.providers import ChatResponse, ModelProvider
from tori.search import SearchError
from tori.user_settings import (
    _METADATA_SQL,
    _SETTINGS_SQL_V2,
    _SETTINGS_SQL_V1,
    CapabilitySettingsController,
    SQLiteUserSettingsStore,
    UserSettingsCorruptError,
    UserSettingsPermissionError,
    UserSettingsUnavailableError,
    UserSettingsValidationError,
    UserSettingsVersionError,
)


class _RecordingProvider(ModelProvider):
    def __init__(self) -> None:
        self.requests = []

    def chat(self, messages):  # type: ignore[no-untyped-def]
        self.requests.append(tuple(messages))
        return ChatResponse("answer", "fake")


class _RecordingSearch:
    enabled = True
    available = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, category: str = "general") -> CapabilityResult:
        self.queries.append(query)
        return CapabilityResult("web_search", query, "completed", ())


class SQLiteUserSettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "settings" / "tori_settings.db"
        self.store = SQLiteUserSettingsStore(self.path)

    def test_absent_read_preserves_legacy_defaults_without_creating_path(self) -> None:
        state = self.store.read()

        self.assertIsNone(state.web_search_enabled)
        self.assertIsNone(state.speech_output_enabled)
        self.assertIsNone(state.operator_activity_log_enabled)
        self.assertIsNone(state.last_selected_model)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_both_typed_preferences_survive_reopening_and_update_independently(self) -> None:
        search = self.store.set_web_search_enabled(False)
        self.assertFalse(search.web_search_enabled)
        self.assertIsNone(search.speech_output_enabled)
        self.assertIsNone(search.operator_activity_log_enabled)

        reopened = SQLiteUserSettingsStore(self.path)
        speech = reopened.set_speech_output_enabled(False)
        self.assertFalse(speech.web_search_enabled)
        self.assertFalse(speech.speech_output_enabled)
        self.assertEqual(reopened.read(), speech)

        enabled = reopened.set_web_search_enabled(True)
        self.assertTrue(enabled.web_search_enabled)
        self.assertFalse(enabled.speech_output_enabled)

        activity = reopened.set_operator_activity_log_enabled(False)
        self.assertFalse(activity.operator_activity_log_enabled)
        self.assertEqual(SQLiteUserSettingsStore(self.path).read(), activity)

        selection = reopened.set_last_selected_model("lan", "gemma-26b")
        self.assertEqual(selection.last_selected_model.qualified_name, "lan/gemma-26b")
        self.assertEqual(
            SQLiteUserSettingsStore(self.path).read().last_selected_model,
            selection.last_selected_model,
        )

    def test_simultaneous_first_mutations_are_serialized_without_lost_updates(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(self.store.set_web_search_enabled, False),
                executor.submit(self.store.set_speech_output_enabled, False),
            )
            for future in futures:
                future.result(timeout=2)

        state = self.store.read()
        self.assertFalse(state.web_search_enabled)
        self.assertFalse(state.speech_output_enabled)

    def test_schema_is_explicit_singleton_and_boolean_values_are_typed(self) -> None:
        self.store.set_web_search_enabled(False)
        with sqlite3.connect(self.path) as connection:
            columns = tuple(
                (row[1], row[2], row[3], row[5])
                for row in connection.execute("PRAGMA table_info(user_settings)")
            )
            row = connection.execute(
                "SELECT singleton, web_search_enabled, speech_output_enabled "
                ", operator_activity_log_enabled "
                ", last_selected_provider, last_selected_model "
                "FROM user_settings"
            ).fetchone()
        self.assertEqual(
            columns,
            (
                ("singleton", "INTEGER", 0, 1),
                ("web_search_enabled", "INTEGER", 0, 0),
                ("speech_output_enabled", "INTEGER", 0, 0),
                ("operator_activity_log_enabled", "INTEGER", 0, 0),
                ("last_selected_provider", "TEXT", 0, 0),
                ("last_selected_model", "TEXT", 0, 0),
            ),
        )
        self.assertEqual(row, (1, 0, None, None, None, None))

    def test_v1_is_read_without_mutation_and_migrated_on_explicit_write(self) -> None:
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(_METADATA_SQL)
            connection.execute(_SETTINGS_SQL_V1)
            connection.execute(
                "INSERT INTO settings_metadata VALUES ('schema_version', '1')"
            )
            connection.execute("INSERT INTO user_settings VALUES (1, 0, 1)")
        before = self.path.read_bytes()

        legacy = self.store.read()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(legacy.web_search_enabled)
        self.assertTrue(legacy.speech_output_enabled)
        self.assertIsNone(legacy.operator_activity_log_enabled)

        migrated = self.store.set_operator_activity_log_enabled(False)
        self.assertFalse(migrated.web_search_enabled)
        self.assertTrue(migrated.speech_output_enabled)
        self.assertFalse(migrated.operator_activity_log_enabled)
        with sqlite3.connect(self.path) as connection:
            version = connection.execute(
                "SELECT value FROM settings_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(version, "3")

    def test_v2_model_selection_migrates_only_when_selection_is_saved(self) -> None:
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(_METADATA_SQL)
            connection.execute(_SETTINGS_SQL_V2)
            connection.execute(
                "INSERT INTO settings_metadata VALUES ('schema_version', '2')"
            )
            connection.execute("INSERT INTO user_settings VALUES (1, 0, 1, NULL)")
        before = self.path.read_bytes()

        self.assertIsNone(self.store.read().last_selected_model)
        self.assertEqual(self.path.read_bytes(), before)
        selected = self.store.set_last_selected_model("local", "model-a")
        self.assertEqual(selected.last_selected_model.qualified_name, "local/model-a")
        with sqlite3.connect(self.path) as connection:
            version = connection.execute(
                "SELECT value FROM settings_metadata WHERE key='schema_version'"
            ).fetchone()[0]
        self.assertEqual(version, "3")

    def test_wrong_types_are_rejected_before_storage_creation(self) -> None:
        for value in (0, 1, "true", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(UserSettingsValidationError):
                    self.store.set_web_search_enabled(value)
        self.assertFalse(self.path.exists())

    def test_corrupt_and_extra_schema_are_preserved_without_repair(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not a sqlite database")
        before = self.path.read_bytes()
        with self.assertRaises(UserSettingsCorruptError):
            self.store.read()
        self.assertEqual(self.path.read_bytes(), before)

        self.path.unlink()
        self.store.set_web_search_enabled(False)
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        before = self.path.read_bytes()
        with self.assertRaises(UserSettingsCorruptError):
            self.store.read()
        self.assertEqual(self.path.read_bytes(), before)

    def test_unsupported_version_is_preserved(self) -> None:
        self.store.set_speech_output_enabled(False)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "UPDATE settings_metadata SET value = '99' "
                "WHERE key = 'schema_version'"
            )
        before = self.path.read_bytes()
        with self.assertRaises(UserSettingsVersionError):
            self.store.read()
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlinked_database_and_unusable_parent_are_rejected(self) -> None:
        target = Path(self.temporary.name) / "target.db"
        target.write_bytes(b"private target")
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(target)
        with self.assertRaises(UserSettingsUnavailableError):
            self.store.read()
        self.assertEqual(target.read_bytes(), b"private target")

        self.path.unlink()
        self.path.parent.rmdir()
        self.path.parent.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(UserSettingsUnavailableError):
            self.store.set_speech_output_enabled(False)


class CapabilitySettingsControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = SQLiteUserSettingsStore(
            Path(self.temporary.name) / "settings.db"
        )

    def test_absent_overrides_preserve_administrator_behavior(self) -> None:
        state = CapabilitySettingsController(
            administrator_web_search=True,
            administrator_speech_output=True,
            store=self.store,
        ).state()
        self.assertTrue(state.web_search.user_enabled)
        self.assertTrue(state.web_search.effective_enabled)
        self.assertFalse(state.web_search.override_stored)
        self.assertTrue(state.speech_output.effective_enabled)
        self.assertTrue(state.operator_activity_log.effective_enabled)
        self.assertFalse(state.operator_activity_log.override_stored)

    def test_user_disable_gates_only_selected_capability(self) -> None:
        controller = CapabilitySettingsController(
            administrator_web_search=True,
            administrator_speech_output=True,
            store=self.store,
        )
        state = controller.set_web_search_enabled(False)
        self.assertFalse(state.web_search.effective_enabled)
        self.assertTrue(state.speech_output.effective_enabled)
        self.assertTrue(state.web_search.override_stored)

        state = controller.set_operator_activity_log_enabled(False)
        self.assertFalse(state.operator_activity_log.effective_enabled)
        self.assertTrue(state.operator_activity_log.override_stored)

    def test_administrator_disabled_capability_cannot_be_user_enabled(self) -> None:
        controller = CapabilitySettingsController(
            administrator_web_search=False,
            administrator_speech_output=False,
            store=self.store,
        )
        with self.assertRaises(UserSettingsPermissionError):
            controller.set_web_search_enabled(True)
        with self.assertRaises(UserSettingsPermissionError):
            controller.set_speech_output_enabled(True)
        self.assertFalse(self.store.path.exists())
        state = controller.state()
        self.assertFalse(state.web_search.effective_enabled)
        self.assertFalse(state.speech_output.effective_enabled)

    def test_persisted_search_disable_also_gates_cli_entry_paths(self) -> None:
        controller = CapabilitySettingsController(
            administrator_web_search=True,
            administrator_speech_output=True,
            store=self.store,
        )
        controller.set_web_search_enabled(False)
        provider = _RecordingProvider()
        search = _RecordingSearch()

        with self.assertRaisesRegex(SearchError, "disabled in Settings"):
            run_once(
                "/search current fixture",
                provider,
                web_search=search,  # type: ignore[arg-type]
                capability_settings=controller,
            )
        output: list[str] = []
        prompts = iter(("/search current fixture", "/exit"))
        self.assertEqual(
            run_interactive(
                provider,
                web_search=search,  # type: ignore[arg-type]
                capability_settings=controller,
                input_function=lambda _prompt: next(prompts),
                output_function=output.append,
            ),
            0,
        )
        self.assertTrue(any("disabled in Settings" in line for line in output))
        self.assertEqual(search.queries, [])
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
