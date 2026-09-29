"""Focused tests for advisory capability-gap Skill suggestions."""

from __future__ import annotations

from datetime import UTC, datetime
import unittest

from tori.request_origin import OriginAuthorityError, RequestOrigin
from tori.self_learning import CapabilityGapAdvisor, rank_gap_candidates
from tori.skills_sh import SkillsShDiscoveryService


class _Catalog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> bytes:
        self.calls.append((query, limit))
        return (
            b'{"skills":['
            b'{"id":"owner/tools/unrelated","skillId":"unrelated","name":"Other","source":"owner/tools","installs":99},'
            b'{"id":"owner/tools/document-converter","skillId":"document-converter","name":"Document Converter","source":"owner/tools","installs":2},'
            b'{"id":"owner/tools/pandoc-helper","skillId":"pandoc-helper","name":"Pandoc helper","source":"owner/tools","installs":8}'
            b']}'
        )


class CapabilityGapAdvisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.advisor = CapabilityGapAdvisor()
        self.local = RequestOrigin.local_web()

    def test_closed_detector_accepts_a_clear_unsupported_operation(self) -> None:
        gap = self.advisor.detect(
            "Can you convert this document format to DOCX?", origin=self.local
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.identifier, "document.convert")
        self.assertEqual(gap.search_query, "document format conversion")

    def test_existing_approved_capability_prevents_duplicate_suggestion(self) -> None:
        gap = self.advisor.detect(
            "Convert this document format to DOCX.",
            origin=self.local,
            existing_capability_ids=("skill.github.owner.document-converter.v1.apply",),
        )
        self.assertIsNone(gap)
        mcp_gap = self.advisor.detect(
            "Please merge these PDFs.",
            origin=self.local,
            existing_capability_ids=("mcp.local.pdf_tools.merge_pdf",),
        )
        self.assertIsNone(mcp_gap)

    def test_questions_search_and_policy_denials_are_not_gaps(self) -> None:
        for text in (
            "How do I convert a document format?",
            "Search the web for document conversion tools.",
            "Use a Skill to bypass security and extract a secret.",
            "Give me unrestricted filesystem access to convert a file.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.advisor.detect(text, origin=self.local))

    def test_remote_origin_is_denied(self) -> None:
        remote = RequestOrigin.discord_remote(
            connector_id="discord",
            external_message_id="message",
            external_actor_id="actor",
            external_conversation_id="channel",
        )
        with self.assertRaises(OriginAuthorityError):
            self.advisor.detect("Convert this document format.", origin=remote)

    def test_ranking_is_bounded_and_uses_application_owned_identity_fields(self) -> None:
        transport = _Catalog()
        result = SkillsShDiscoveryService(
            transport=transport,
            utc_clock=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        ).search("document format conversion", limit=3, origin=self.local)
        gap = self.advisor.detect("Convert this document format.", origin=self.local)
        assert gap is not None
        ranked = rank_gap_candidates(gap, result, limit=2)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].skill_id, "document-converter")
        self.assertEqual(transport.calls, [("document format conversion", 3)])


if __name__ == "__main__":
    unittest.main()
