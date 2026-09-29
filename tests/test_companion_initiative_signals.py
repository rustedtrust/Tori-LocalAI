from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sqlite3
import tempfile
import unittest

from test_web import RecordingProvider, free_port
from tori.checkpoints import CheckpointStore
from tori.coding_work import SQLiteCodingWorkStore
from tori.companion_initiative import (
    InitiativeSettings,
    SQLiteCompanionInitiativeStore,
    _SCHEMA_V1,
    resume_window,
)
from tori.companion_initiative_context import StructuredResumeAnchorProvider
from tori.conversation import ConversationSession
from tori.conversation_application import ConversationTurnRequest, ConversationTurnService
from tori.conversation_archive import ArchiveEntry, ConversationArchiveStore
from tori.knowledge import KnowledgeRegistry
from tori.memory import SQLiteMemoryStore
from tori.operation_coordinator import OperationCoordinator
from tori.providers import ChatResponse, ModelProvider
from tori.request_origin import RequestOrigin, RequestOriginKind
from tori.web import WebApplication


UTC = timezone.utc
NOW = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)


class _Provider(ModelProvider):
    def chat(self, messages):  # type: ignore[no-untyped-def]
        return ChatResponse("A normal reply.", "test-model")

    def stream_chat(self, messages):  # type: ignore[no-untyped-def]
        yield "A normal reply."


class _FailingInitiativeStore:
    def record_meaningful_interaction(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("private failure")


class CompanionInitiativeSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SQLiteCompanionInitiativeStore(
            self.root / "initiative.db", clock=lambda: NOW
        )
        self.store.save_settings(
            InitiativeSettings(master_enabled=True, resume_enabled=True),
            expected_revision=0,
        )

    def sink(self, kind: str, identity: str) -> None:
        self.store.record_meaningful_interaction(
            kind, signal_identity=identity
        )

    def web(self, initiative_store=None) -> WebApplication:  # type: ignore[no-untyped-def]
        return WebApplication(
            RecordingProvider(),
            port=free_port(),
            checkpoint_store=CheckpointStore(self.root / "checkpoints"),
            memory_store=SQLiteMemoryStore(self.root / "memory.db"),
            knowledge_registry=KnowledgeRegistry(self.root / "knowledge"),
            provider_name="fake",
            model_name="fake",
            companion_initiative_store=initiative_store,
        )

    def test_accepted_web_turn_records_once_and_passive_state_does_not(self) -> None:
        application = self.web(self.store)
        before = self.store.activity()
        application.session_state()
        self.assertEqual(self.store.activity(), before)
        status, _document = application.submit("Hello, Tori")
        self.assertEqual(status, 200)
        self.assertEqual(self.store.activity().revision, before.revision + 1)
        self.assertEqual(self.store.activity().kind, "local_turn")
        self.assertEqual(
            [item["role"] for item in application._visible_transcript()],
            ["user", "assistant"],
        )

    def test_explicit_control_counts_but_default_off_store_stays_absent(self) -> None:
        application = self.web(self.store)
        before = self.store.activity().revision
        application.record_explicit_user_control("/api/settings/web-search")
        self.assertEqual(self.store.activity().revision, before + 1)
        self.assertEqual(self.store.activity().kind, "settings_change")

        absent = SQLiteCompanionInitiativeStore(self.root / "absent.db")
        default_off = self.web(absent)
        status, _document = default_off.submit("An ordinary turn while Off")
        self.assertEqual(status, 200)
        self.assertFalse(absent.exists)

    def test_signal_identity_is_idempotent_revision_safe_and_persistent(self) -> None:
        before = self.store.activity().revision
        first = self.store.record_meaningful_interaction(
            "local_turn", signal_identity="local:request-1"
        )
        duplicate = self.store.record_meaningful_interaction(
            "local_turn", signal_identity="local:request-1"
        )
        second = self.store.record_meaningful_interaction(
            "local_turn", signal_identity="local:request-2"
        )
        self.assertEqual(first.revision, before + 1)
        self.assertEqual(duplicate.revision, first.revision)
        self.assertEqual(second.revision, first.revision + 1)
        reopened = SQLiteCompanionInitiativeStore(self.store.path)
        replay = reopened.record_meaningful_interaction(
            "local_turn", occurred_at=NOW, signal_identity="local:request-1"
        )
        self.assertEqual(replay.revision, second.revision)

    def test_verified_discord_turn_counts_once_and_model_output_does_not(self) -> None:
        turns = ConversationTurnService(
            OperationCoordinator(), activity_signal=self.sink
        )
        session = ConversationSession(_Provider())
        turns.attach_session(
            session,
            origin_kind=RequestOriginKind.DISCORD_REMOTE,
            conversation_id="remote-chat",
        )
        origin = RequestOrigin.discord_remote(
            connector_id="discord-owner-dm",
            external_message_id="message-1",
            external_actor_id="owner-1",
            external_conversation_id="dm-1",
        )
        request = ConversationTurnRequest(
            "Hello", origin, "remote-chat", 0, origin_sequence=1
        )
        before = self.store.activity().revision
        self.assertEqual(turns.complete(request), "A normal reply.")
        self.assertEqual(self.store.activity().kind, "remote_turn")
        turns.complete(request)
        self.assertEqual(self.store.activity().revision, before + 1)
        # Provider output and outbound handling do not enter the admission sink.
        self.assertEqual(self.store.activity().revision, before + 1)

    def test_initiative_failure_does_not_break_primary_web_turn(self) -> None:
        application = self.web(_FailingInitiativeStore())
        status, document = application.submit("Keep the primary operation healthy")
        self.assertEqual(status, 200)
        self.assertIn("transcript", document)

    def test_schema_one_reopens_and_upgrades_transactionally_on_signal_write(self) -> None:
        connection = sqlite3.connect(self.store.path)
        with connection:
            connection.execute("DROP TABLE initiative_candidate_attention")
            connection.execute("DROP INDEX attention_items_state")
            connection.execute("DROP TABLE attention_items")
            for name in (
                "initiative_candidates_delivery",
                "initiative_candidates_lease",
                "initiative_candidates_type",
            ):
                connection.execute(f"DROP INDEX {name}")
            connection.execute(
                "ALTER TABLE initiative_settings RENAME TO initiative_settings_v3"
            )
            connection.execute(
                "ALTER TABLE initiative_candidates RENAME TO initiative_candidates_v3"
            )
            connection.execute(_SCHEMA_V1[("table", "initiative_settings")])
            connection.execute(_SCHEMA_V1[("table", "initiative_candidates")])
            connection.execute(
                "INSERT INTO initiative_settings SELECT singleton,revision,master_enabled,"
                "morning_enabled,resume_enabled,long_silence_enabled,morning_start,"
                "morning_end,quiet_start,quiet_end,snoozed_until_utc,created_at_utc,"
                "updated_at_utc FROM initiative_settings_v3"
            )
            connection.execute(
                "INSERT INTO initiative_candidates SELECT * FROM initiative_candidates_v3"
            )
            connection.execute("DROP TABLE initiative_settings_v3")
            connection.execute("DROP TABLE initiative_candidates_v3")
            for key in (
                ("index", "initiative_candidates_delivery"),
                ("index", "initiative_candidates_lease"),
                ("index", "initiative_candidates_type"),
            ):
                connection.execute(_SCHEMA_V1[key])
            connection.execute("DROP INDEX initiative_activity_signals_revision")
            connection.execute("DROP TABLE initiative_activity_signals")
            connection.execute(
                "UPDATE initiative_metadata SET value='1' WHERE key='schema_version'"
            )
        connection.close()
        reopened = SQLiteCompanionInitiativeStore(self.store.path, clock=lambda: NOW)
        self.assertTrue(reopened.settings().master_enabled)
        reopened.record_meaningful_interaction(
            "local_turn", signal_identity="local:migrating-request"
        )
        connection = sqlite3.connect(self.store.path)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM initiative_metadata WHERE key='schema_version'"
                ).fetchone(),
                ("4",),
            )
        finally:
            connection.close()


class ResumeAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = InitiativeSettings(
            master_enabled=True, resume_enabled=True
        )
        self.activity = SimpleNamespace(
            revision=1,
            last_meaningful_at_utc=NOW - timedelta(hours=6),
            kind="local_turn",
        )
        self.chats = SimpleNamespace(
            list_chats=lambda: (SimpleNamespace(identifier="chat-1"),),
            list_project_resume_metadata=lambda: (),
        )
        self.coding = SimpleNamespace(resume_metadata=lambda: ())

    def provider(self) -> StructuredResumeAnchorProvider:
        return StructuredResumeAnchorProvider(
            coding_work=self.coding, conversations=self.chats
        )

    def test_waiting_coding_work_is_structured_generic_and_revisioned(self) -> None:
        self.coding.resume_metadata = lambda: (
            SimpleNamespace(
                identifier="coding-work-1",
                project_id=None,
                origin_chat_id="chat-1",
                state="waiting",
                revision=7,
                updated_at_utc="2026-09-15T10:00:00.000000Z",
            ),
        )
        anchor = self.provider().current(
            self.settings, self.activity, at=NOW
        )
        self.assertEqual(
            (anchor.kind, anchor.identifier, anchor.revision, anchor.safe_title),
            ("coding_work", "coding-work-1", 7, None),
        )
        self.assertFalse(hasattr(anchor, "objective"))
        window = resume_window(anchor, self.activity)
        self.assertEqual(window.expires_at_utc, anchor.last_active_at_utc + timedelta(hours=72))

    def test_newer_anchor_replaces_old_and_invalid_deleted_or_expired_disappears(self) -> None:
        rows = [SimpleNamespace(
            project_id="project-1", title="NAS rebuild", project_revision=2,
            chat_id="chat-1", exchange_revision=8,
            last_active_at_utc="2026-09-15T08:00:00.000000Z",
        )]
        self.chats.list_project_resume_metadata = lambda: tuple(rows)
        first = self.provider().current(self.settings, self.activity, at=NOW)
        rows.append(SimpleNamespace(
            project_id="project-2", title="Garden plan", project_revision=1,
            chat_id="chat-1", exchange_revision=4,
            last_active_at_utc="2026-09-15T09:00:00.000000Z",
        ))
        replacement = self.provider().current(self.settings, self.activity, at=NOW)
        self.assertEqual((first.identifier, replacement.identifier), ("project-1", "project-2"))
        rows.clear()
        self.assertIsNone(self.provider().current(self.settings, self.activity, at=NOW))
        rows.append(SimpleNamespace(
            project_id="project-old", title="Old", project_revision=1,
            chat_id="chat-1", exchange_revision=1,
            last_active_at_utc="2026-09-12T14:59:59.000000Z",
        ))
        self.assertIsNone(self.provider().current(self.settings, self.activity, at=NOW))

    def test_disabled_master_or_type_returns_no_anchor(self) -> None:
        self.chats.list_project_resume_metadata = lambda: (SimpleNamespace(
            project_id="project-1", title="Safe title", project_revision=1,
            chat_id="chat-1", exchange_revision=2,
            last_active_at_utc="2026-09-15T10:00:00.000000Z",
        ),)
        self.assertIsNone(self.provider().current(replace(self.settings, master_enabled=False), self.activity, at=NOW))
        self.assertIsNone(self.provider().current(replace(self.settings, resume_enabled=False), self.activity, at=NOW))

    def test_archive_projection_reads_no_transcript_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ids = iter(("chat-" + "1" * 32,))
            projects = iter(("project-" + "a" * 32,))
            store = ConversationArchiveStore(
                Path(directory) / "archive.db",
                clock=lambda: NOW,
                identifier_factory=lambda: next(ids),
                project_identifier_factory=lambda: next(projects),
            )
            chat = store.create_chat((
                ArchiveEntry("user", "PRIVATE USER BODY"),
                ArchiveEntry("assistant", "PRIVATE ASSISTANT BODY", provider="fake", model="model"),
            ), provider="fake", model="model")
            store.create_project(
                title="NAS rebuild",
                objective="PRIVATE PROJECT OBJECTIVE",
                continuity_brief="",
                chat_id=chat.metadata.identifier,
                expected_chat_revision=chat.metadata.revision,
            )
            projection = store.list_project_resume_metadata()
            self.assertEqual(len(projection), 1)
            rendered = repr(projection)
            self.assertNotIn("PRIVATE", rendered)
            self.assertEqual(projection[0].title, "NAS rebuild")

    def test_coding_work_projection_reads_no_objective_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            store = SQLiteCodingWorkStore(
                root / "coding.db",
                clock=lambda: NOW,
                identifier_factory=lambda prefix: prefix + "-" + "1" * 32,
            )
            store.initialize()
            work = store.create_work(
                objective="PRIVATE CODING OBJECTIVE",
                acceptance_criteria="PRIVATE ACCEPTANCE BODY",
                workspace_root=str(workspace),
                origin_chat_id="chat-" + "1" * 32,
            )
            connection = sqlite3.connect(store.path)
            with connection:
                connection.execute(
                    "UPDATE coding_work SET state='waiting',revision=revision+1 "
                    "WHERE identifier=?",
                    (work.identifier,),
                )
            connection.close()
            projection = store.list_resume_metadata()
            self.assertEqual(len(projection), 1)
            self.assertNotIn("PRIVATE", repr(projection))
            self.assertFalse(hasattr(projection[0], "objective"))


if __name__ == "__main__":
    unittest.main()
