"""Bounded application-owned conversational access to Finance V1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import re

from .finance import (
    CandidateTransaction,
    FinanceError,
    FinanceMutation,
    ImportPreview,
    MerchantRule,
)
from .finance_service import FinanceService
from .capability_registry import is_capability_discussion


_FINANCE_HINT = re.compile(
    r"(?i)\b(?:finance|budget|spent|spending|bills?|debt|apr|discretionary|afford|"
    r"amazon|fast food|electric bill|credit cards?|loans?|pay off|payoff|extra \$?\d+ (?:a|per) month)\b"
)
_SPENT = re.compile(r"(?i)\bhow much (?:did|have) i spend\w* (?:on |eating )?(?P<subject>fast food|amazon)(?: (?P<when>this month|last month))?")
_AFFORD = re.compile(r"(?i)\bcan i afford (?:an? )?\$?(?P<amount>\d+(?:\.\d{1,2})?)(?: [\w -]+)?(?: this month)?\b")
_PAYOFF = re.compile(
    r"(?i)\bif i pay an? extra \$?(?P<amount>\d+(?:\.\d{1,2})?) (?:a|per) month "
    r"(?:on|toward) (?P<debt>[^?,.]+?)(?:,?\s+what happens)?[?.]?$"
)
_AVERAGE_BILL = re.compile(r"(?i)\b(?:what(?:'s| is) )?my average (?P<name>[\w -]+?) bill\b")
_IMPORT = re.compile(r"(?i)^/finance import (?P<file>[^|]+?)\s*\|\s*(?P<account>[^|]+?)\s*$")
_REVIEW_RULE = re.compile(
    r"(?i)^/finance review rule (?P<number>\d+)\s*\|\s*"
    r"(?P<match_type>exact|starts_with|contains)\s*\|\s*"
    r"(?P<match_text>[^|]+?)\s*\|\s*(?P<merchant>[^|]+?)\s*\|\s*"
    r"(?P<category>[^|]+?)\s*$"
)
_REVIEW_CORRECTION = re.compile(
    r"(?i)^/finance review (?P<number>\d+)\s*\|\s*"
    r"(?P<merchant>[^|]+?)\s*\|\s*(?P<category>[^|]+?)\s*$"
)
_REVIEW_DECISION = re.compile(
    r"(?i)^/finance review (?P<number>\d+)\s*\|\s*"
    r"(?P<decision>include|exclude)\s*$"
)
_FINANCE_COMMAND = re.compile(r"(?i)^/finance(?:\s|$)")


def is_finance_command(text: str) -> bool:
    """Return whether text is a bounded Finance slash command."""

    return _FINANCE_COMMAND.match(text.strip()) is not None


@dataclass(frozen=True, slots=True)
class FinanceConversationTurn:
    handled: bool
    text: str | None = None
    mutation: FinanceMutation | None = None
    review: FinanceImportReview | None = None
    review_changed: bool = False


@dataclass(frozen=True, slots=True)
class FinanceImportReview:
    """One exact transient import preview and its reviewed durable rules."""

    preview: ImportPreview
    merchant_rules: tuple[MerchantRule, ...] = ()


class FinanceConversationService:
    """Recognize only the bounded Finance V1 acceptance language and commands."""

    def __init__(self, finance: FinanceService, *, today=date.today, currency: str = "USD") -> None:
        self._finance = finance
        self._today = today
        self._currency = currency

    def interpret(
        self,
        text: str,
        *,
        review: FinanceImportReview | None = None,
    ) -> FinanceConversationTurn:
        normalized = " ".join(text.strip().split())
        if is_capability_discussion(normalized):
            return FinanceConversationTurn(False)
        if normalized.casefold() == "/finance initialize":
            mutation = self._finance.propose_initialization(currency=self._currency)
            return FinanceConversationTurn(True, mutation.presentation, mutation)
        import_match = _IMPORT.match(normalized)
        if import_match:
            filename = import_match.group("file").strip()
            if Path(filename).name != filename or filename in {".", ".."}:
                return FinanceConversationTurn(
                    True,
                    "Use only the statement filename from Finance imports/incoming; no path was accepted.",
                )
            source = (
                self._finance.repository.workbook_path.parent
                / "imports" / "incoming" / filename
            )
            preview = self._finance.preview_import(
                source, account_label=import_match.group("account").strip()
            )
            unresolved = self._unresolved(preview)
            if unresolved:
                next_review = FinanceImportReview(preview)
                return FinanceConversationTurn(
                    True,
                    self._review_summary(next_review),
                    review=next_review,
                    review_changed=True,
                )
            mutation = self._finance.propose_import(preview)
            return FinanceConversationTurn(True, mutation.presentation, mutation)
        if normalized.casefold() == "/finance review cancel":
            if review is None:
                return FinanceConversationTurn(
                    True, "There is no active Finance import review. Nothing was changed."
                )
            return FinanceConversationTurn(
                True,
                "Finance import review cancelled; nothing was imported or changed.",
                review_changed=True,
            )
        if normalized.casefold() in {"/finance review", "/finance review propose"}:
            if review is None:
                return FinanceConversationTurn(
                    True,
                    "There is no active Finance import review. Start with "
                    "/finance import FILENAME | FRIENDLY ACCOUNT.",
                )
            self._finance.validate_preview(review.preview)
            if normalized.casefold().endswith(" propose"):
                unresolved = self._unresolved(review.preview)
                if unresolved:
                    return FinanceConversationTurn(
                        True,
                        f"{len(unresolved)} included transactions still need review. "
                        "Nothing was proposed or imported.\n" + self._review_summary(review),
                    )
                mutation = self._finance.propose_import(
                    review.preview, merchant_rules=review.merchant_rules
                )
                return FinanceConversationTurn(
                    True, mutation.presentation, mutation,
                    review_changed=True,
                )
            return FinanceConversationTurn(True, self._review_summary(review))
        rule_match = _REVIEW_RULE.match(normalized)
        if rule_match:
            if review is None:
                return FinanceConversationTurn(
                    True, "There is no active Finance import review. Nothing was changed."
                )
            revised, rule = self._finance.reviewed_merchant_rule(
                review.preview,
                int(rule_match.group("number")),
                match_type=rule_match.group("match_type").casefold(),
                match_text=rule_match.group("match_text"),
                merchant=rule_match.group("merchant"),
                category=rule_match.group("category"),
            )
            next_review = FinanceImportReview(
                revised, (*review.merchant_rules, rule)
            )
            return FinanceConversationTurn(
                True,
                "Reviewed reusable rule added to this pending import only; it "
                "will become durable only with the final import confirmation.\n"
                + self._review_summary(next_review),
                review=next_review,
                review_changed=True,
            )
        correction_match = _REVIEW_CORRECTION.match(normalized)
        if correction_match:
            if review is None:
                return FinanceConversationTurn(
                    True, "There is no active Finance import review. Nothing was changed."
                )
            revised = self._finance.review_candidate(
                review.preview,
                int(correction_match.group("number")),
                merchant=correction_match.group("merchant"),
                category=correction_match.group("category"),
            )
            next_review = FinanceImportReview(revised, review.merchant_rules)
            return FinanceConversationTurn(
                True, self._review_summary(next_review),
                review=next_review, review_changed=True,
            )
        decision_match = _REVIEW_DECISION.match(normalized)
        if decision_match:
            if review is None:
                return FinanceConversationTurn(
                    True, "There is no active Finance import review. Nothing was changed."
                )
            revised = self._finance.review_candidate(
                review.preview,
                int(decision_match.group("number")),
                included=decision_match.group("decision").casefold() == "include",
            )
            next_review = FinanceImportReview(revised, review.merchant_rules)
            return FinanceConversationTurn(
                True, self._review_summary(next_review),
                review=next_review, review_changed=True,
            )
        if is_finance_command(normalized):
            return FinanceConversationTurn(
                True,
                "Finance command failed: Usage: /finance initialize or "
                "/finance import FILENAME | FRIENDLY ACCOUNT; during review use "
                "/finance review, /finance review NUMBER | MERCHANT | CATEGORY, "
                "/finance review NUMBER | include|exclude, /finance review rule "
                "NUMBER | exact|starts_with|contains | MATCH | MERCHANT | CATEGORY, "
                "/finance review propose, or /finance review cancel. Nothing was changed.",
            )
        if not _FINANCE_HINT.search(normalized):
            return FinanceConversationTurn(False)
        lower = normalized.casefold()
        bounded_read = (
            _SPENT.search(normalized) is not None
            or _AFFORD.search(normalized) is not None
            or _PAYOFF.search(normalized) is not None
            or _AVERAGE_BILL.search(normalized) is not None
            or any(phrase in lower for phrase in (
                "biggest spending categories", "largest spending categories",
                "bills are due in the next seven days", "bills are due in the next 7 days",
                "bills are due next week", "bills due soon", "reserve for my bills",
                "current debt balances", "current credit-card", "current credit card",
                "loan balances", "debt has the highest apr", "highest apr",
                "discretionary money do i have left", "discretionary money remains",
                "more on fast food than last month", "changed in my spending over the last three months",
            ))
        )
        if not bounded_read:
            return FinanceConversationTurn(False)
        if not self._finance.status()["initialized"]:
            return FinanceConversationTurn(True, "Finance has not been initialized, so I don't have Finance data to calculate from yet.")
        try:
            match = _SPENT.search(normalized)
            if match:
                start, end = self._period(match.group("when") or "this month")
                result = self._finance.spending_summary(start, end)
                subject = match.group("subject").casefold()
                if subject == "fast food":
                    amount = next((value for key, value in result.categories if key == "Dining / Fast Food"), Decimal("0.00"))
                    label = "fast food"
                else:
                    amount = next((value for key, value in result.merchants if key.casefold() == "amazon"), None)
                    if amount is None:
                        amount = next((value for key, value in result.categories if key == "Amazon"), Decimal("0.00"))
                    label = "Amazon"
                return FinanceConversationTurn(True, f"You spent ${amount:,.2f} on {label} {match.group('when') or 'this month'}.")
            if "biggest spending categories" in lower or "largest spending categories" in lower:
                start, end = self._period("this month")
                result = self._finance.spending_summary(start, end)
                details = ", ".join(f"{name}: ${amount:,.2f}" for name, amount in result.categories[:5]) or "no recorded spending"
                return FinanceConversationTurn(True, f"Your largest categories this month are {details}.")
            if "bills" in lower and ("next seven days" in lower or "next 7 days" in lower or "next week" in lower or "due soon" in lower):
                result = self._finance.upcoming_bills(self._today(), days=7)
                details = "; ".join(f"{name} ${amount:,.2f} on {due.isoformat()}" for due, name, amount in result.bills) or "none"
                prefix = "Reserve" if "reserve" in lower or "how much" in lower else "Upcoming bills are"
                return FinanceConversationTurn(True, f"{prefix} ${result.total:,.2f} for the next seven days. Bills: {details}.")
            average = _AVERAGE_BILL.search(normalized)
            if average:
                value, count, warning = self._finance.average_bill(average.group("name"))
                if value is None:
                    return FinanceConversationTurn(True, warning or "That bill average is unavailable.")
                sample = f" from {count} linked payments" if count else ""
                suffix = f" {warning}" if warning else ""
                return FinanceConversationTurn(True, f"Your average {average.group('name')} bill is ${value:,.2f}{sample}.{suffix}".strip())
            payoff = _PAYOFF.search(normalized)
            if payoff:
                result = self._finance.payoff_scenario(payoff.group("debt").strip(), extra_payment=payoff.group("amount"))
                if result.comparison is None:
                    return FinanceConversationTurn(True, "I can't produce a reliable payoff estimate from the current payment and balance data.")
                comparison = result.comparison
                savings = "" if result.months_saved is None else f" That is about {result.months_saved} months sooner and ${result.interest_saved:,.2f} less interest than the current target-payment estimate."
                warning = " " + " ".join(result.warnings) if result.warnings else ""
                return FinanceConversationTurn(True, f"With an extra ${result.extra_payment:,.2f} per month, {result.debt_name} is estimated at {comparison.months} months and ${comparison.total_interest:,.2f} interest.{savings}{warning}")
            if "debt" in lower or "credit-card" in lower or "credit card" in lower or "loan balances" in lower:
                if "highest apr" in lower:
                    summary = self._finance.debt_summary()
                    if summary.highest_apr is None:
                        return FinanceConversationTurn(True, "No active debts are recorded.")
                    item = summary.highest_apr
                    return FinanceConversationTurn(True, f"{item.name} has the highest APR at {item.apr}% (balance ${item.current_balance:,.2f} as of {item.balance_as_of.isoformat()}).")
                summary = self._finance.debt_summary()
                details = "; ".join(f"{item.name}: ${item.current_balance:,.2f} as of {item.balance_as_of.isoformat()}" for item in summary.debts) or "none"
                warning = " " + " ".join(summary.warnings) if summary.warnings else ""
                return FinanceConversationTurn(True, f"Active debt total is ${summary.total_balance:,.2f}. Balances: {details}.{warning}")
            afford = _AFFORD.search(normalized)
            if afford:
                current_month = self._today().strftime("%Y-%m")
                result = self._finance.affordability(afford.group("amount"), current_month)
                if result.status == "insufficient data":
                    return FinanceConversationTurn(True, "I don't have enough current Finance data to answer confidently. " + " ".join(result.warnings))
                return FinanceConversationTurn(True, f"That purchase is {result.status}. Conservative capacity is ${result.conservative_capacity:,.2f}, leaving ${result.post_purchase_buffer:,.2f} after the purchase.")
            if "discretionary" in lower and ("left" in lower or "remaining" in lower):
                result = self._finance.affordability("0.01", self._today().strftime("%Y-%m"))
                if result.conservative_capacity is None:
                    return FinanceConversationTurn(True, "I can't calculate discretionary capacity yet. " + " ".join(result.warnings))
                return FinanceConversationTurn(True, f"You have ${result.conservative_capacity:,.2f} of conservative discretionary capacity; the category target has ${result.discretionary_remaining:,.2f} remaining.")
            if "more on fast food than last month" in lower:
                current_start, current_end = self._period("this month")
                last_start, last_end = self._period("last month")
                current = dict(self._finance.spending_summary(current_start, current_end).categories).get("Dining / Fast Food", Decimal("0"))
                previous = dict(self._finance.spending_summary(last_start, last_end).categories).get("Dining / Fast Food", Decimal("0"))
                direction = "more" if current > previous else "less" if current < previous else "the same amount"
                return FinanceConversationTurn(True, f"You spent ${current:,.2f} on fast food this month versus ${previous:,.2f} last month — {direction}.")
            if "changed" in lower and "three months" in lower:
                trend = self._finance.monthly_trend(self._today().strftime("%Y-%m"), count=3)
                details = ", ".join(f"{month}: ${amount:,.2f}" for month, amount in trend.months)
                return FinanceConversationTurn(True, f"Consumption spending over the last three months was {details}. Current versus previous: ${trend.current_vs_previous:,.2f}.")
        except FinanceError as exc:
            return FinanceConversationTurn(True, str(exc))
        return FinanceConversationTurn(False)

    def apply(self, mutation: FinanceMutation) -> str:
        return self._finance.apply(mutation).text

    def _review_summary(self, review: FinanceImportReview) -> str:
        self._finance.validate_preview(review.preview)
        unresolved = self._unresolved(review.preview)
        definite = sum(
            item.duplicate_state == "definite"
            for item in review.preview.candidates
        )
        header = (
            f"Previewed {len(review.preview.candidates)} transactions from "
            f"{review.preview.source_path.name}: {len(unresolved)} need review and "
            f"{definite} are definite duplicates. Nothing was imported."
        )
        if not unresolved:
            return (
                f"{header}\nReview is complete. Use /finance review propose to "
                "create the exact confirmation-bound import proposal."
            )
        lines = [header, "Unresolved items (up to 10 shown):"]
        for number, candidate in unresolved[:10]:
            amount = (
                f"-${abs(candidate.amount):,.2f}"
                if candidate.amount < 0 else f"${candidate.amount:,.2f}"
            )
            lines.append(
                f"- #{number} · {candidate.date.isoformat()} · {amount} · "
                f"{candidate.original_description} · proposed "
                f"{candidate.merchant or 'unresolved'} / "
                f"{candidate.category or 'unresolved'} · "
                + " ".join(candidate.uncertainty)
            )
        lines.extend((
            "Resolve one: /finance review NUMBER | MERCHANT | CATEGORY",
            "Apply a reusable account-scoped rule: /finance review rule NUMBER | "
            "exact|starts_with|contains | MATCH | MERCHANT | CATEGORY",
            "For a possible duplicate: /finance review NUMBER | include or exclude",
        ))
        if len(unresolved) > 10:
            lines.append(
                f"Resolve a shown item, then use /finance review to continue "
                f"through the remaining {len(unresolved) - 10}."
            )
        return "\n".join(lines)

    @staticmethod
    def _unresolved(
        preview: ImportPreview,
    ) -> tuple[tuple[int, CandidateTransaction], ...]:
        return tuple(
            (number, candidate)
            for number, candidate in enumerate(preview.candidates, start=1)
            if candidate.included
            and candidate.duplicate_state != "definite"
            and candidate.uncertainty
        )

    def _period(self, label: str) -> tuple[date, date]:
        today = self._today()
        if label == "last month":
            year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        else:
            year, month = today.year, today.month
        start = date(year, month, 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        return start, date(next_year, next_month, 1) - timedelta(days=1)
