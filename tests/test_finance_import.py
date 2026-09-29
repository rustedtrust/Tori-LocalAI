from pathlib import Path
from tempfile import TemporaryDirectory
from itertools import count
import shutil
import unittest
from dataclasses import replace

from tori.finance import FinanceConflictError, FinanceError, FinanceSnapshot, MerchantRule, Transaction
from tori.finance_service import FinanceService
from tori.finance_workbook import WorkbookFinanceRepository


class FinanceImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name) / "finance"
        self.repository = WorkbookFinanceRepository(self.root)
        created = self.repository.create(currency="USD")
        rules = (
            MerchantRule("mcd", "contains", "MCDONALD", "McDonald's", "Dining / Fast Food", 1),
            MerchantRule("amzn", "contains", "AMZN", "Amazon", "Amazon", 1),
        )
        existing = Transaction(
            "old", __import__("datetime").date(2026, 8, 1), "McDonald's", "MCDONALD #1", -10,
            "expense", "Dining / Fast Food", "Checking", "synthetic", source_transaction_id="known-id",
            duplicate_fingerprint="not-composite",
        )
        self.repository.replace(FinanceSnapshot(created.revision, "USD", (existing,), rules), expected_revision=created.revision)
        identifiers = count(1)
        self.service = FinanceService(
            self.repository,
            identifier_factory=lambda prefix: f"{prefix}-{next(identifiers)}",
        )
        self.incoming = self.root / "imports" / "incoming"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.incoming / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_csv_preview_applies_rules_flags_unknown_and_source_id_duplicate(self) -> None:
        path = self._write(
            "statement.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-01,MCDONALD #1,10,expense,known-id\n"
            "2026-08-02,AMZN MARKETPLACE,25,expense,new-id\n"
            "2026-08-03,UNKNOWN STORE,12,expense,unknown-id\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        self.assertEqual(preview.candidates[0].duplicate_state, "definite")
        self.assertEqual(preview.candidates[1].merchant, "Amazon")
        self.assertEqual(preview.candidates[1].category, "Amazon")
        self.assertIn("Unknown merchant", preview.candidates[2].uncertainty[0])
        self.assertEqual(self.repository.read().transactions[0].identifier, "old")

    def test_count_aware_duplicate_keeps_second_legitimate_same_day_purchase(self) -> None:
        path = self._write(
            "same-day.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-01,MCDONALD #1,10,expense,\n"
            "2026-08-01,MCDONALD #1,10,expense,\n",
        )
        initial = self.service.preview_import(path, account_label="Checking")
        fingerprint = initial.candidates[0].duplicate_fingerprint
        current = self.repository.read()
        existing = current.transactions[0]
        self.repository.replace(
            FinanceSnapshot(current.revision, current.currency, (existing.__class__(
                existing.identifier, existing.date, existing.merchant, existing.original_description,
                existing.amount, existing.transaction_type, existing.category, existing.account_label,
                existing.import_source, existing.import_batch_id, existing.source_transaction_id,
                fingerprint,
            ),), current.merchant_rules), expected_revision=current.revision,
        )
        preview = self.service.preview_import(path, account_label="Checking")
        self.assertEqual([item.duplicate_state for item in preview.candidates], ["possible", "none"])
        reviewed = self.service.review_candidate(preview, 1, included=False)
        self.assertFalse(reviewed.candidates[0].included)
        self.assertFalse(reviewed.candidates[0].uncertainty)
        proposal = self.service.propose_import(reviewed)
        self.assertEqual(len(proposal.import_preview.included), 1)

    def test_same_batch_repeated_source_id_marks_only_later_occurrence_definite(self) -> None:
        path = self._write(
            "same-source-id.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-15,MCDONALD #2,12,expense,POS-0815-114\n"
            "2026-08-15,MCDONALD #2,12,expense,POS-0815-114\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        self.assertEqual(
            [item.duplicate_state for item in preview.candidates],
            ["none", "definite"],
        )
        self.assertTrue(preview.candidates[0].included)
        self.assertFalse(preview.candidates[1].included)

    def test_same_purchase_with_different_source_ids_remains_legitimate(self) -> None:
        path = self._write(
            "different-source-ids.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-15,MCDONALD #2,12,expense,POS-0815-114\n"
            "2026-08-15,MCDONALD #2,12,expense,POS-0815-115\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        self.assertEqual(
            [item.duplicate_state for item in preview.candidates],
            ["none", "none"],
        )
        self.assertTrue(all(item.included for item in preview.candidates))

    def test_confirmed_csv_import_is_revision_and_source_bound_then_moves_source(self) -> None:
        path = self._write(
            "clean.csv",
            "Date,Description,Amount,Type,Transaction ID\n2026-08-02,AMZN MARKETPLACE,25,expense,new-id\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        proposal = self.service.propose_import(preview)
        result = self.service.apply(proposal)
        self.assertTrue(result.source_moved)
        self.assertFalse(path.exists())
        self.assertEqual(len(result.snapshot.transactions), 2)
        processed = next((self.root / "imports" / "processed").iterdir())
        repeated = self.incoming / "repeated.csv"
        shutil.copy2(processed, repeated)
        repeated_preview = self.service.preview_import(repeated, account_label="Checking")
        self.assertEqual(repeated_preview.candidates[0].duplicate_state, "definite")

    def test_changed_source_or_workbook_rejects_confirmation(self) -> None:
        path = self._write(
            "changed.csv",
            "Date,Description,Amount,Type,Transaction ID\n2026-08-02,AMZN,25,expense,new-id\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        proposal = self.service.propose_import(preview)
        path.write_text(path.read_text() + "2026-08-03,AMZN,5,expense,next-id\n", encoding="utf-8")
        with self.assertRaises(FinanceConflictError):
            self.service.apply(proposal)

    def test_reviewed_unknown_correction_and_rule_commit_atomically(self) -> None:
        path = self._write(
            "unknown.csv",
            "Date,Description,Amount,Type,Transaction ID\n2026-08-02,LOCAL CAFE,14,expense,cafe-id\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        corrected = replace(
            preview.candidates[0], merchant="Local Cafe", category="Dining / Fast Food", uncertainty=()
        )
        revised = self.service.revise_preview(preview, (corrected,))
        rule = MerchantRule("cafe", "contains", "LOCAL CAFE", "Local Cafe", "Dining / Fast Food", 5)
        result = self.service.apply(self.service.propose_import(revised, merchant_rules=(rule,)))
        self.assertEqual(result.snapshot.transactions[-1].merchant, "Local Cafe")
        self.assertEqual(result.snapshot.merchant_rules[-1], rule)

    def test_reviewed_rule_resolves_repeated_merchants_without_mutating_preview(self) -> None:
        path = self._write(
            "review.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-02,LOCAL CAFE NORTH,14,expense,cafe-1\n"
            "2026-08-03,LOCAL CAFE SOUTH,9,expense,cafe-2\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        before = self.repository.read()
        self.assertTrue(all(item.uncertainty for item in preview.candidates))

        revised, rule = self.service.reviewed_merchant_rule(
            preview,
            1,
            match_type="contains",
            match_text="LOCAL CAFE",
            merchant="Local Cafe",
            category="Dining / Fast Food",
        )
        self.assertTrue(all(not item.uncertainty for item in revised.candidates))
        self.assertTrue(all(item.merchant == "Local Cafe" for item in revised.candidates))
        self.assertEqual(self.repository.read(), before)

        proposal = self.service.propose_import(revised, merchant_rules=(rule,))
        document = proposal.document()["import"]
        self.assertEqual(document["included_transactions"], 2)
        self.assertEqual(document["merchant_rules"][0]["match_text"], "LOCAL CAFE")
        self.assertEqual(document["merchant_rules"][0]["account_scope"], "Checking")
        self.assertEqual(self.repository.read(), before)

    def test_review_correction_and_authority_fail_closed_when_inputs_change(self) -> None:
        path = self._write(
            "review-stale.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-02,UNKNOWN STORE,14,expense,unknown-1\n",
        )
        preview = self.service.preview_import(path, account_label="Checking")
        revised = self.service.review_candidate(
            preview, 1, merchant="Unknown Store", category="Shopping"
        )
        self.assertFalse(revised.candidates[0].uncertainty)
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaises(FinanceConflictError):
            self.service.propose_import(revised)

        workbook_path = self._write(
            "review-workbook-stale.csv",
            "Date,Description,Amount,Type,Transaction ID\n"
            "2026-08-02,UNKNOWN STORE,14,expense,unknown-2\n",
        )
        workbook_preview = self.service.preview_import(
            workbook_path, account_label="Checking"
        )
        self.service.apply(self.service.upsert(MerchantRule(
            "stale-rule", "contains", "STALE", "Stale", "Other", 10,
        )))
        with self.assertRaises(FinanceConflictError):
            self.service.review_candidate(
                workbook_preview, 1, merchant="Unknown Store", category="Shopping"
            )

    def test_xml_ofx_normalizes_and_pdf_defers_truthfully(self) -> None:
        ofx = self._write(
            "statement.ofx",
            "<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST><STMTTRN>"
            "<TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260810</DTPOSTED><TRNAMT>-12.50</TRNAMT>"
            "<FITID>ofx-1</FITID><NAME>MCDONALD</NAME></STMTTRN></BANKTRANLIST>"
            "</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>",
        )
        preview = self.service.preview_import(ofx, account_label="Checking")
        self.assertEqual(preview.candidates[0].merchant, "McDonald's")
        pdf = self._write("statement.pdf", "%PDF synthetic fixture")
        with self.assertRaisesRegex(FinanceError, "reviewed text/layout adapter"):
            self.service.preview_import(pdf, account_label="Checking")


if __name__ == "__main__":
    unittest.main()
