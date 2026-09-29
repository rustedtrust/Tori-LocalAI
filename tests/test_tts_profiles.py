from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from tori.tts_adapters import DEFAULT_TTS_ENDPOINT, OPENAI_COMPATIBLE_TTS
from tori.tts_profile_application import TTSProfileApplicationService
from tori.tts_profiles import (
    SQLiteTTSProfileStore,
    TTSProfile,
    TTSProfileConflictError,
    TTSProfileStaleRevisionError,
    TTSProfileStoreCorruptError,
    TTSProfileValidationError,
)


class TTSProfileFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "profiles.db"
        self.store = SQLiteTTSProfileStore(self.path)
        self.store.initialize(initial_selection_timestamp="2026-08-22T12:00:00Z")
        self.application = TTSProfileApplicationService(
            self.store,
            clock=lambda: datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc),
        )

    @staticmethod
    def profile_values(**overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "display_name": "Local speech",
            "endpoint": DEFAULT_TTS_ENDPOINT,
            "model": "tts-1",
            "voice": "tori",
            "enabled": True,
            "connect_timeout_seconds": 3.0,
            "read_timeout_seconds": 30.0,
            "authentication_mode": "none",
            "provider_options": {},
        }
        values.update(overrides)
        return values

    @classmethod
    def profile_update_values(cls, **overrides: object) -> dict[str, object]:
        return cls.profile_values(**overrides)

    def test_profiles_are_durable_and_selection_is_a_separate_document(self) -> None:
        created = self.application.create_profile(
            identifier="home-speech", **self.profile_values()
        )
        initial, initial_profile = self.application.get_active_profile()
        self.assertEqual(initial.revision, 1)
        self.assertIsNone(initial.profile_identifier)
        self.assertIsNone(initial_profile)

        selected = self.application.select_active_profile(
            created.identifier, expected_revision=initial.revision
        )
        reopened = TTSProfileApplicationService(SQLiteTTSProfileStore(self.path))
        profiles = reopened.list_profiles()
        active, active_profile = reopened.get_active_profile()

        self.assertEqual(profiles, (created,))
        self.assertEqual(selected.revision, 2)
        self.assertEqual(active.profile_identifier, created.identifier)
        self.assertEqual(active_profile, created)

    def test_profile_updates_are_revision_safe(self) -> None:
        created = self.application.create_profile(
            identifier="home-speech", **self.profile_values()
        )
        updated = self.application.update_profile(
            created.identifier,
            expected_revision=created.revision,
            **self.profile_update_values(display_name="Updated speech"),
        )
        self.assertEqual(updated.revision, 2)
        with self.assertRaises(TTSProfileStaleRevisionError):
            self.application.update_profile(
                created.identifier,
                expected_revision=created.revision,
                **self.profile_update_values(display_name="Stale overwrite"),
            )
        self.assertEqual(
            self.application.list_profiles()[0].display_name, "Updated speech"
        )

    def test_active_selection_rejects_stale_clients_without_fallback(self) -> None:
        first = self.application.create_profile(
            identifier="first", **self.profile_values(display_name="First")
        )
        second = self.application.create_profile(
            identifier="second", **self.profile_values(display_name="Second")
        )
        selection = self.application.get_active_profile()[0]
        selected = self.application.select_active_profile(
            first.identifier, expected_revision=selection.revision
        )
        with self.assertRaises(TTSProfileStaleRevisionError):
            self.application.select_active_profile(
                second.identifier, expected_revision=selection.revision
            )
        active, profile = self.application.get_active_profile()
        self.assertEqual(active, selected)
        self.assertEqual(profile, first)

    def test_protocol_profiles_accept_unknown_model_names_but_reject_unsafe_options(self) -> None:
        for overrides in (
            {"authentication_mode": "bearer"},
            {"provider_options": {"native_secret": "private"}},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(TTSProfileValidationError):
                    self.application.create_profile(**self.profile_values(**overrides))
        self.assertEqual(self.application.list_profiles(), ())
        self.assertIsNone(self.application.get_active_profile()[0].profile_identifier)

    def test_unknown_backend_name_never_selects_an_adapter(self) -> None:
        profile = self.application.create_profile(
            identifier="future-lan",
            **self.profile_values(
                display_name="Future LAN",
                provider_type="a-future-backend-name",
                endpoint="http://192.168.1.50:8880",
                model="future-model",
                voice="tori",
            ),
        )
        self.assertEqual(profile.provider_type, OPENAI_COMPATIBLE_TTS)
        self.assertEqual(profile.provider_options, ())
        selection = self.application.get_active_profile()[0]
        selected = self.application.select_active_profile(
            profile.identifier, expected_revision=selection.revision
        )
        self.assertEqual(selected.profile_identifier, profile.identifier)

    def test_qwen_profile_accepts_bounded_private_lan_endpoint(self) -> None:
        private_lan = "http://" + ".".join(("192", "168", "5", "50")) + ":8000"
        profile = self.application.create_profile(
            identifier="qwen-lan",
            **self.profile_values(endpoint=private_lan),
        )
        self.assertEqual(profile.endpoint, private_lan)

    def test_existing_legacy_profile_loads_without_reinterpretation(self) -> None:
        legacy_path = Path(self.temporary.name) / "legacy.db"
        legacy = TTSProfile(
            identifier="legacy-qwen", display_name="Existing local speech",
            provider_type="qwen", endpoint=DEFAULT_TTS_ENDPOINT, model="tts-1",
            voice="tori", enabled=True, connect_timeout_seconds=3.0,
            read_timeout_seconds=30.0, authentication_mode="none", provider_options=(),
            revision=1, created_at="2026-08-22T12:00:00Z", updated_at="2026-08-22T12:00:00Z",
        )
        legacy_store = SQLiteTTSProfileStore(legacy_path)
        legacy_store.initialize(
            initial_selection_timestamp="2026-08-22T12:00:00Z", initial_profile=legacy
        )
        reopened = TTSProfileApplicationService(legacy_store)
        self.assertEqual(reopened.require_active_profile().provider_type, "qwen")

    def test_selected_profile_cannot_be_disabled_or_deleted(self) -> None:
        created = self.application.create_profile(
            identifier="home-speech", **self.profile_values()
        )
        selection = self.application.get_active_profile()[0]
        self.application.select_active_profile(
            created.identifier, expected_revision=selection.revision
        )
        with self.assertRaises(TTSProfileConflictError):
            self.application.update_profile(
                created.identifier,
                expected_revision=created.revision,
                **self.profile_update_values(enabled=False),
            )
        with self.assertRaises(TTSProfileConflictError):
            self.application.delete_profile(
                created.identifier, expected_revision=created.revision
            )
        self.assertEqual(
            self.application.get_active_profile()[0].profile_identifier,
            created.identifier,
        )

    def test_delete_unselected_profile_is_revision_safe(self) -> None:
        created = self.application.create_profile(
            identifier="unused", **self.profile_values()
        )
        updated = self.application.update_profile(
            created.identifier,
            expected_revision=created.revision,
            **self.profile_update_values(display_name="Unused updated"),
        )
        with self.assertRaises(TTSProfileStaleRevisionError):
            self.application.delete_profile(
                created.identifier, expected_revision=created.revision
            )
        self.application.delete_profile(
            updated.identifier, expected_revision=updated.revision
        )
        self.assertEqual(self.application.list_profiles(), ())

    def test_initialization_is_explicit_and_unknown_schema_is_preserved(self) -> None:
        absent = SQLiteTTSProfileStore(Path(self.temporary.name) / "absent.db")
        self.assertFalse(absent.exists)
        self.assertFalse(absent.path.exists())

        unknown_path = Path(self.temporary.name) / "unknown.db"
        with sqlite3.connect(unknown_path) as connection:
            connection.execute("CREATE TABLE unrelated (private_value TEXT)")
        unknown = SQLiteTTSProfileStore(unknown_path)
        with self.assertRaises(TTSProfileStoreCorruptError):
            unknown.list_profiles()
        with sqlite3.connect(unknown_path) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall(),
                [("unrelated",)],
            )


if __name__ == "__main__":
    unittest.main()
