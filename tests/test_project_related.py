"""Slice 5: read-only cross-owner Project continuity and explicit links."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from tori.chats import ChatService, ChatServiceError
from tori.conversation_archive import ConversationArchiveStore
from tori.project_application import ProjectApplicationService
from tori.project_related import ProjectRelatedSources
from tori.project_context import ProjectContextPlanningRequest, ProjectContextService
from tori.context import ContextPolicy
from tori.providers import ChatMessage
from tori.research import ResearchLimits, SQLiteResearchStore
from tori.coding_work import SQLiteCodingWorkStore
from tori.knowledge import KnowledgeRegistry
from tori.companion_initiative import (
    AttentionSignal, InitiativeSettings, SQLiteCompanionInitiativeStore,
)


STAMP = "2026-09-22T12:00:00Z"
LATER = "2026-09-22T12:00:01Z"
FINDING = "finding-" + "a" * 32
SCHEDULE = "work-" + "b" * 32
KNOWLEDGE = "ksrc-" + "c" * 32


class ProjectRelatedTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ConversationArchiveStore(Path(temporary.name) / "archive.db")
        self.chats = ChatService(self.store)
        self.project = ProjectApplicationService(self.chats).create_project(
            title="Alpha", objective="Keep related work visible",
        )
        self.other = ProjectApplicationService(self.chats).create_project(
            title="Beta", objective="Separate work",
        )
        self.finding = SimpleNamespace(
            identifier=FINDING, title="Finding", state="new", revision=2,
            last_seen_at=STAMP, summary="Safe finding summary",
        )
        self.schedule = SimpleNamespace(
            identifier=SCHEDULE, title="Existing schedule", status="active",
            revision=3, updated_at_utc=STAMP,
        )
        self.knowledge = SimpleNamespace(
            identifier=KNOWLEDGE, filename="guide.md", file_type="markdown",
            registered_at=STAMP,
        )
        self.research = SimpleNamespace(
            identifier="research-" + "d" * 32, project_id=self.project.identifier,
            objective="Research objective", state="completed", revision=2,
            updated_at_utc=LATER, progress_message="Completed safely",
            report="PRIVATE REPORT MUST NEVER ENTER PROJECT HOME",
        )
        self.coding = SimpleNamespace(
            identifier="coding-work-" + "e" * 32,
            project_id=self.project.identifier, objective="Implement change",
            state="waiting", revision=4, updated_at_utc=STAMP,
            result_json="PRIVATE CODING RESULT MUST NEVER ENTER PROJECT HOME",
        )
        self.attention = SimpleNamespace(
            identifier="attention-" + "f" * 32,
            project_id=self.project.identifier, title="Review item", state="open",
            revision=1, updated_at_utc=datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
            summary="Safe attention summary",
        )

    def sources(self, **overrides: object) -> ProjectRelatedSources:
        readers = {
            "research": lambda project_id: (
                self.research, self.research_b if hasattr(self, "research_b") else self.research
            ) if project_id == self.project.identifier else (),
            "coding_work": lambda project_id: (
                self.coding,
            ) if project_id == self.project.identifier else (),
            "attention": lambda project_id: (
                self.attention,
            ) if project_id == self.project.identifier else (),
            "night_owl": lambda identifier: self.finding if identifier == FINDING else None,
            "scheduled_work": lambda identifier: self.schedule if identifier == SCHEDULE else None,
            "scheduled_runs": lambda identifier: (
                (SimpleNamespace(status="completed"),) if identifier == SCHEDULE else ()
            ),
            "knowledge": lambda identifier: self.knowledge if identifier == KNOWLEDGE else None,
        }
        readers.update(overrides)
        return ProjectRelatedSources(**readers)

    def test_source_owned_sections_and_activity_are_bounded_and_deterministic(self) -> None:
        self.research_b = SimpleNamespace(**{
            **vars(self.research), "identifier": "research-" + "0" * 32,
        })
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        home = service.get_project_home(self.project.identifier)
        assert home.related_work is not None
        self.assertTrue(home.related_work.complete)
        self.assertEqual(len(home.related_work.research), 2)
        self.assertEqual(len(home.related_work.coding_work), 1)
        self.assertEqual(len(home.related_work.attention), 1)
        self.assertEqual(home.related_work.research[0].identifier, self.research_b.identifier)
        self.assertEqual(home.related_work.recent_activity[0].identifier, self.research_b.identifier)
        self.assertEqual(
            tuple(item.source_type for item in home.related_work.recent_activity[2:4]),
            ("attention", "coding_work"),
        )
        self.assertNotIn("PRIVATE REPORT", repr(home))
        self.assertNotIn("PRIVATE CODING RESULT", repr(home))
        other = service.get_project_home(self.other.identifier)
        assert other.related_work is not None
        self.assertEqual(other.related_work.research, ())
        self.assertEqual(other.related_work.coding_work, ())
        self.assertEqual(service.get_project(self.project.identifier).revision, self.project.revision)

    def test_link_validation_unlink_and_project_delete_preserve_source_owners(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        project = self.project
        for target_type, target_id in (
            ("night_owl_finding", FINDING),
            ("scheduled_work_definition", SCHEDULE),
            ("knowledge_source", KNOWLEDGE),
        ):
            linked = service.link_resource(
                project.identifier, expected_project_revision=project.revision,
                target_type=target_type, target_id=target_id,
            )
            project = linked.project
        home = service.get_project_home(project.identifier)
        assert home.related_work is not None
        self.assertEqual(len(home.links), 3)
        self.assertEqual(len(home.related_work.night_owl), 1)
        self.assertEqual(len(home.related_work.scheduled_work), 1)
        self.assertEqual(home.related_work.scheduled_work[0].summary, "Latest run: completed")
        self.assertEqual(len(home.related_work.knowledge), 1)
        for target_type, target_id in (
            ("night_owl_finding", "finding-" + "9" * 32),
            ("scheduled_work_definition", "work-" + "9" * 32),
            ("knowledge_source", "ksrc-" + "9" * 32),
        ):
            with self.assertRaises(ChatServiceError) as missing:
                service.link_resource(
                    project.identifier, expected_project_revision=project.revision,
                    target_type=target_type, target_id=target_id,
                )
            self.assertEqual(missing.exception.code, "link_target_unavailable")
        link = service.list_links(project.identifier)[0]
        project = service.unlink_resource(
            project.identifier, link.identifier,
            expected_project_revision=project.revision,
            expected_link_revision=link.revision,
        )
        self.assertIsNotNone(self.finding)
        self.assertEqual(len(service.list_links(project.identifier)), 2)
        service.delete_project(project.identifier, expected_revision=project.revision)
        self.assertIsNotNone(self.schedule)
        self.assertIsNotNone(self.knowledge)
        self.assertEqual(self.store.list_project_links(project.identifier), ())

    def test_duplicate_unsupported_and_unavailable_links_fail_without_authority(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        linked = service.link_resource(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            target_type="night_owl_finding", target_id=FINDING,
        )
        for target_type, target_id in (
            ("night_owl_finding", FINDING),
            ("research", self.research.identifier),
            ("night_owl_finding", "finding-not-a-stable-id"),
        ):
            with self.assertRaises(ChatServiceError):
                service.link_resource(
                    self.project.identifier,
                    expected_project_revision=linked.project.revision,
                    target_type=target_type, target_id=target_id,
                )
        offline = ProjectApplicationService(
            self.chats,
            related_sources=self.sources(knowledge=None),
        )
        with self.assertRaises(ChatServiceError) as unavailable:
            offline.link_resource(
                self.project.identifier,
                expected_project_revision=linked.project.revision,
                target_type="knowledge_source", target_id=KNOWLEDGE,
            )
        self.assertEqual(unavailable.exception.code, "link_target_unavailable")
        self.assertEqual(service.get_project(self.project.identifier), linked.project)
        self.assertEqual(service.list_links(self.project.identifier), (linked.record,))
        self.assertEqual(self.finding.state, "new")
        self.assertEqual(self.schedule.status, "active")
        self.assertEqual(self.knowledge.filename, "guide.md")

    def test_unreadable_source_keeps_existing_link_visible_and_removable(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        linked = service.link_resource(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            target_type="knowledge_source", target_id=KNOWLEDGE,
        )

        def unreadable(_identifier: str) -> object:
            raise RuntimeError("source unavailable")

        offline = ProjectApplicationService(
            self.chats, related_sources=self.sources(knowledge=unreadable),
        )
        home = offline.get_project_home(self.project.identifier)
        assert home.related_work is not None
        self.assertEqual(home.links, (linked.record,))
        self.assertIn("knowledge", home.related_work.unavailable_sources)
        self.assertEqual(home.related_work.knowledge, ())
        self.assertEqual(home.freshness.project_revision, linked.project.revision)
        removed = offline.unlink_resource(
            self.project.identifier, linked.record.identifier,
            expected_project_revision=linked.project.revision,
            expected_link_revision=linked.record.revision,
        )
        self.assertEqual(removed.revision, linked.project.revision + 1)
        self.assertEqual(offline.list_links(self.project.identifier), ())
        self.assertEqual(self.knowledge.identifier, KNOWLEDGE)

    def test_unavailable_and_invalid_source_are_truthful_partial_results(self) -> None:
        def unreadable(_project_id: str) -> tuple[object, ...]:
            raise RuntimeError("source offline")

        bad = SimpleNamespace(**{**vars(self.coding), "updated_at_utc": "not-a-date"})
        service = ProjectApplicationService(self.chats, related_sources=self.sources(
            research=unreadable, coding_work=lambda _project_id: (bad,),
        ))
        home = service.get_project_home(self.project.identifier)
        assert home.related_work is not None
        self.assertFalse(home.related_work.complete)
        self.assertEqual(home.related_work.unavailable_sources, ("research", "coding_work"))
        self.assertEqual(
            tuple(item.reason for item in home.related_work.unavailable_details),
            ("Source could not be read safely.", "Source could not be read safely."),
        )
        self.assertEqual(home.related_work.research, ())
        self.assertEqual(home.related_work.coding_work, ())
        self.assertEqual(len(home.related_work.attention), 1)
        self.assertTrue(all(item.source_type != "research" for item in home.related_work.recent_activity))
        self.assertFalse(ProjectRelatedSources().verify_link("night_owl_finding", FINDING))
        self.assertFalse(ProjectRelatedSources(
            night_owl=lambda _identifier: SimpleNamespace(identifier="finding-" + "8" * 32)
        ).verify_link("night_owl_finding", FINDING))

    def test_disappeared_link_target_remains_visible_as_missing(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        linked = service.link_resource(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            target_type="night_owl_finding", target_id=FINDING,
        )
        self.finding = None
        home = service.get_project_home(self.project.identifier)
        assert home.related_work is not None
        self.assertEqual(home.related_work.night_owl[0].availability, "missing")
        self.assertEqual(home.related_work.night_owl[0].identifier, FINDING)
        self.assertEqual(len(service.list_links(linked.project.identifier)), 1)

    def test_project_owned_updates_merge_without_a_second_activity_store(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        decided = service.add_decision(
            self.project.identifier,
            expected_project_revision=self.project.revision,
            text="Keep source ownership separate.",
        )
        home = service.get_project_home(self.project.identifier)
        assert home.related_work is not None
        self.assertIn(
            ("decision", decided.record.identifier),
            {(item.source_type, item.identifier) for item in home.related_work.recent_activity},
        )
        self.assertEqual(service.get_project(self.project.identifier).revision, decided.project.revision)

    def test_native_research_and_coding_queries_filter_before_bounding(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            research = SQLiteResearchStore(root / "research" / "jobs.db")
            foreign = research.create_proposal(
                "Unrelated research", limits=ResearchLimits(),
                origin_chat_id=None, origin_chat_revision=None,
                project_id=self.other.identifier,
            )
            own = research.create_proposal(
                "Project research", limits=ResearchLimits(),
                origin_chat_id=None, origin_chat_revision=None,
                project_id=self.project.identifier,
            )
            self.assertEqual(
                tuple(item.identifier for item in research.list_project_jobs(
                    self.project.identifier, limit=1
                )), (own.identifier,),
            )
            self.assertFalse(hasattr(
                research.list_project_jobs(self.project.identifier)[0], "report"
            ))
            coding = SQLiteCodingWorkStore(root / "coding" / "work.db")
            coding.initialize()
            coding.create_work(
                objective="Unrelated coding", workspace_root=str(root),
                project_id=self.other.identifier,
            )
            own_work = coding.create_work(
                objective="Project coding", workspace_root=str(root),
                project_id=self.project.identifier,
            )
            self.assertEqual(
                tuple(item.identifier for item in coding.list_project_work(
                    self.project.identifier, limit=1
                )), (own_work.identifier,),
            )
            self.assertFalse(hasattr(
                coding.list_project_work(self.project.identifier)[0], "result_json"
            ))
            self.assertNotEqual(foreign.project_id, own.project_id)
            ProjectApplicationService(self.chats).delete_project(
                self.project.identifier, expected_revision=self.project.revision,
            )
            self.assertEqual(research.get(own.identifier).project_id, self.project.identifier)
            self.assertEqual(coding.get_work(own_work.identifier).project_id, self.project.identifier)

    def test_related_sources_never_enter_project_context_or_receipt(self) -> None:
        service = ProjectApplicationService(self.chats, related_sources=self.sources())
        prompt = "What is this Project?"
        pack = ProjectContextService(service).build_pack(
            self.project.identifier,
            ProjectContextPlanningRequest(
                prompt=prompt, policy=ContextPolicy.fixed(8192),
                model_capacity=None,
                mandatory_prefix=(ChatMessage("system", "Tori identity"),),
                optional_context=(), mandatory_suffix=(),
                current_user=ChatMessage("user", prompt),
            ),
        )
        self.assertNotIn("PRIVATE REPORT", pack.rendered_context)
        self.assertNotIn("Research objective", pack.rendered_context)
        self.assertNotIn("Implement change", pack.rendered_context)
        self.assertNotIn("Review item", pack.rendered_context)
        receipt = pack.receipt(1)
        self.assertEqual(receipt.rendered_context, pack.rendered_context)

    def test_real_knowledge_registration_is_only_referenced(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "guide.md"
            source_path.write_text("Private source body stays with Knowledge.", encoding="utf-8")
            registry = KnowledgeRegistry(
                root / "registry", working_directory=root,
                identifier_factory=lambda: KNOWLEDGE,
            )
            source = registry.register("guide.md")
            service = ProjectApplicationService(
                self.chats,
                related_sources=ProjectRelatedSources(knowledge=registry.get),
            )
            linked = service.link_resource(
                self.project.identifier,
                expected_project_revision=self.project.revision,
                target_type="knowledge_source", target_id=source.identifier,
            )
            home = service.get_project_home(self.project.identifier)
            assert home.related_work is not None
            self.assertEqual(home.related_work.knowledge[0].title, "guide.md")
            self.assertEqual(home.related_work.knowledge[0].availability, "not_checked")
            self.assertNotIn("Private source body", repr(home))
            service.unlink_resource(
                self.project.identifier, linked.record.identifier,
                expected_project_revision=linked.project.revision,
                expected_link_revision=linked.record.revision,
            )
            self.assertEqual(registry.get(source.identifier), source)

    def test_native_attention_query_keeps_project_ownership(self) -> None:
        with TemporaryDirectory() as temporary:
            store = SQLiteCompanionInitiativeStore(
                Path(temporary) / "attention" / "attention.db",
                clock=lambda: datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
            )
            store.save_settings(InitiativeSettings(master_enabled=True), expected_revision=0)
            signals = tuple(
                AttentionSignal(
                    "research", "research-" + digit * 32, "research_completed",
                    "Review result", "Safe status only", "worth_reviewing",
                    "silent", 1, "material-" + digit,
                    datetime(2026, 9, 22, 12, tzinfo=timezone.utc),
                    project.identifier,
                )
                for project, digit in ((self.project, "1"), (self.other, "2"))
            )
            store.reconcile_attention("research", signals)
            own = store.list_project_attention(self.project.identifier)
            self.assertEqual(len(own), 1)
            self.assertEqual(own[0].project_id, self.project.identifier)
            self.assertNotEqual(own[0].project_id, self.other.identifier)
