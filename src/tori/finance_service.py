"""Deterministic Finance V1 application service and import policy."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Callable, Iterable, Literal, Sequence
from xml.etree import ElementTree

from .finance import (
    DISCRETIONARY_CATEGORIES, ESSENTIAL_CATEGORIES, Bill, Budget, CandidateTransaction,
    Debt, FinanceConflictError, FinanceError, FinanceMutation, FinanceRepository,
    FinanceSnapshot, FinanceValidationError, Goal, ImportPreview, MerchantRule,
    STALE_BALANCE_DAYS, Transaction, money,
)


@dataclass(frozen=True, slots=True)
class SpendingSummary:
    start: date
    end: date
    total: Decimal
    categories: tuple[tuple[str, Decimal], ...]
    merchants: tuple[tuple[str, Decimal], ...]
    income: Decimal
    debt_payments: Decimal
    savings: Decimal
    transfers: Decimal
    data_through: date | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SpendingTrend:
    months: tuple[tuple[str, Decimal], ...]
    current_vs_previous: Decimal | None
    current_vs_three_month_average: Decimal | None


@dataclass(frozen=True, slots=True)
class BillsSummary:
    bills: tuple[tuple[date, str, Decimal], ...]
    total: Decimal
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DebtSummary:
    debts: tuple[Debt, ...]
    total_balance: Decimal
    highest_apr: Debt | None
    minimum_payments: Decimal
    target_payments: Decimal
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AffordabilityResult:
    purchase_amount: Decimal
    target_month: str
    status: Literal["within current plan", "outside current plan", "insufficient data"]
    discretionary_remaining: Decimal | None
    cash_capacity: Decimal | None
    conservative_capacity: Decimal | None
    post_purchase_buffer: Decimal | None
    obligations: Decimal
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PayoffEstimate:
    months: int
    total_interest: Decimal
    payoff_month: str


@dataclass(frozen=True, slots=True)
class PayoffScenario:
    debt_name: str
    balance_as_of: date
    baseline: PayoffEstimate | None
    comparison: PayoffEstimate | None
    extra_payment: Decimal
    months_saved: int | None
    interest_saved: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoalProgress:
    name: str
    current_amount: Decimal
    target_amount: Decimal
    remaining: Decimal
    percent: Decimal
    amount_as_of: date
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class CSVImportMapping:
    date_column: str = "Date"
    description_column: str = "Description"
    amount_column: str = "Amount"
    type_column: str = "Type"
    source_id_column: str | None = "Transaction ID"
    date_format: str = "%Y-%m-%d"
    debit_positive: bool = False


@dataclass(frozen=True, slots=True)
class FinanceApplyResult:
    snapshot: FinanceSnapshot
    text: str
    source_moved: bool = False


class PDFStatementAdapter:
    """Deliberate adapter boundary; arbitrary PDF parsing is not safe in V1."""

    def parse(self, path: Path, *, account_label: str) -> tuple[CandidateTransaction, ...]:
        raise FinanceError(
            "PDF Finance import needs a reviewed text/layout adapter; this statement was not parsed.",
            code="unsupported_finance_import",
        )


class FinanceService:
    """Own Finance meaning, arithmetic, validation, previews, and proposals."""

    def __init__(
        self,
        repository: FinanceRepository,
        *,
        today: Callable[[], date] = date.today,
        identifier_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._repository = repository
        self._today = today
        self._identifier = identifier_factory or (lambda prefix: f"{prefix}-{secrets.token_hex(12)}")

    @property
    def repository(self) -> FinanceRepository:
        return self._repository

    def status(self) -> dict[str, object]:
        return {
            "initialized": self._repository.exists(),
            "workbook": str(self._repository.workbook_path),
            "revision": self._repository.revision(),
        }

    def summary_projection(self, *, as_of: date | None = None) -> tuple[tuple[str, str], ...]:
        """Build the visible Summary projection without making it canonical state."""

        revision = self._repository.revision()
        day = as_of or self._today()
        start = date(day.year, day.month, 1)
        spending = self.spending_summary(start, day)
        bills_7 = self.upcoming_bills(day, days=7)
        bills_30 = self.upcoming_bills(day, days=30)
        debts = self.debt_summary()
        affordability = self.affordability("0.01", day.strftime("%Y-%m"))
        warnings = tuple(dict.fromkeys((*spending.warnings, *bills_30.warnings, *debts.warnings, *affordability.warnings)))
        category_text = "; ".join(f"{name}: {amount}" for name, amount in spending.categories)
        merchant_text = "; ".join(f"{name}: {amount}" for name, amount in spending.merchants)
        result = (
            ("Generated At", day.isoformat()),
            ("Latest Transaction Date", "" if spending.data_through is None else spending.data_through.isoformat()),
            ("Month-to-date Consumption Spending", str(spending.total)),
            ("Month-to-date Income", str(spending.income)),
            ("Category Totals", category_text),
            ("Merchant Totals", merchant_text),
            ("Bills Due 7 Days", str(bills_7.total)),
            ("Bills Due 30 Days", str(bills_30.total)),
            ("Active Debt Total", str(debts.total_balance)),
            ("Highest APR Debt", "" if debts.highest_apr is None else f"{debts.highest_apr.name} ({debts.highest_apr.apr}%)"),
            ("Discretionary Capacity", "" if affordability.conservative_capacity is None else str(affordability.conservative_capacity)),
            ("Warnings", " | ".join(warnings)),
        )
        self._ensure_revision(revision)
        return result

    def propose_summary_refresh(self, *, as_of: date | None = None) -> FinanceMutation:
        snapshot = self._repository.read()
        updated = replace(snapshot, summary_rows=self.summary_projection(as_of=as_of))
        return FinanceMutation(
            "refresh_summary", snapshot.revision, updated,
            "Replace the derived Finance Summary sheet with this freshly calculated projection?",
        )

    def propose_initialization(self, *, currency: str = "USD") -> FinanceMutation:
        if self._repository.exists():
            raise FinanceValidationError("Finance is already initialized.")
        return FinanceMutation(
            "initialize", None, FinanceSnapshot("", currency=currency),
            f"Create an empty {currency.upper()} Finance V1 workbook and import folders at {self._repository.workbook_path}?",
        )

    def propose_replace(self, snapshot: FinanceSnapshot, *, operation: str, presentation: str) -> FinanceMutation:
        current = self._repository.read()
        return FinanceMutation(operation, current.revision, snapshot.with_revision(current.revision), presentation)

    def upsert(self, record: Bill | Debt | Budget | Goal | MerchantRule | Transaction) -> FinanceMutation:
        snapshot = self._repository.read()
        field, key = self._record_location(record)
        values = list(getattr(snapshot, field))
        identifier = key(record)
        before = next((item for item in values if key(item) == identifier), None)
        values = [item for item in values if key(item) != identifier]
        values.append(record)
        updated = replace(snapshot, summary_rows=(), **{field: tuple(values)})
        verb = "Update" if before is not None else "Add"
        return FinanceMutation(
            f"upsert_{field}", snapshot.revision, updated,
            f"{verb} Finance {type(record).__name__.lower()} “{self._record_name(record)}” with the reviewed values?",
        )

    def delete(self, kind: str, identifier: str) -> FinanceMutation:
        snapshot = self._repository.read()
        field = {
            "transaction": "transactions", "merchant_rule": "merchant_rules", "bill": "bills",
            "debt": "debts", "budget": "budgets", "goal": "goals",
        }.get(kind)
        if field is None:
            raise FinanceValidationError("Finance record kind is invalid.")
        key = (lambda item: item.month) if field == "budgets" else (lambda item: item.identifier)
        values = list(getattr(snapshot, field))
        target = next((item for item in values if key(item) == identifier), None)
        if target is None:
            raise FinanceValidationError("Finance record was not found.")
        updated = replace(
            snapshot,
            summary_rows=(),
            **{field: tuple(item for item in values if key(item) != identifier)},
        )
        return FinanceMutation(
            f"delete_{field}", snapshot.revision, updated,
            f"Delete Finance {kind.replace('_', ' ')} “{self._record_name(target)}”?",
        )

    @staticmethod
    def _record_location(record: object) -> tuple[str, Callable[[object], str]]:
        if isinstance(record, Transaction): return "transactions", lambda item: item.identifier
        if isinstance(record, MerchantRule): return "merchant_rules", lambda item: item.identifier
        if isinstance(record, Bill): return "bills", lambda item: item.identifier
        if isinstance(record, Debt): return "debts", lambda item: item.identifier
        if isinstance(record, Budget): return "budgets", lambda item: item.month
        if isinstance(record, Goal): return "goals", lambda item: item.identifier
        raise FinanceValidationError("Unsupported Finance record.")

    @staticmethod
    def _record_name(record: object) -> str:
        return str(getattr(record, "name", getattr(record, "merchant", getattr(record, "month", getattr(record, "identifier", "record")))))

    def apply(self, mutation: FinanceMutation) -> FinanceApplyResult:
        if mutation.operation == "initialize":
            assert mutation.snapshot is not None
            result = self._repository.create(currency=mutation.snapshot.currency, expected_revision=None)
            return FinanceApplyResult(result, "Finance workbook created.")
        if mutation.snapshot is None or mutation.expected_revision is None:
            raise FinanceValidationError("Finance mutation is incomplete.")
        if mutation.import_preview is not None:
            preview = mutation.import_preview
            if self._file_digest(preview.source_path) != preview.source_digest:
                raise FinanceConflictError("The import source changed before confirmation; nothing was imported.")
            if self._candidate_digest(preview.candidates) != preview.candidate_digest:
                raise FinanceConflictError("The import preview changed before confirmation; nothing was imported.")
        result = self._repository.replace(mutation.snapshot, expected_revision=mutation.expected_revision)
        if mutation.import_preview is None:
            return FinanceApplyResult(result, "Finance change applied and verified.")
        source = mutation.import_preview.source_path
        processed = self._repository.workbook_path.parent / "imports" / "processed" / source.name
        moved = False
        try:
            processed.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if processed.exists():
                processed = processed.with_name(f"{processed.stem}-{mutation.import_preview.identifier}{processed.suffix}")
            shutil.move(str(source), str(processed))
            moved = True
        except OSError:
            return FinanceApplyResult(
                result,
                "Finance transactions were committed and verified, but the source statement could not be moved to processed. Do not reapply it.",
                False,
            )
        return FinanceApplyResult(result, "Finance import committed, verified, and moved to processed.", moved)

    def spending_summary(self, start: date, end: date) -> SpendingSummary:
        if end < start:
            raise FinanceValidationError("Finance period end cannot precede its start.")
        snapshot = self._repository.read()
        selected = tuple(item for item in snapshot.transactions if start <= item.date <= end)
        categories: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        merchants: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        income = debt = savings = transfers = Decimal("0.00")
        for item in selected:
            if item.transaction_type in {"expense", "refund"} or (
                item.transaction_type == "adjustment" and item.category not in {"Income", "Transfer", "Debt Payment", "Savings"}
            ):
                effect = -item.amount
                categories[item.category] += effect
                merchants[item.merchant] += effect
            elif item.transaction_type == "income": income += item.amount
            elif item.transaction_type == "debt_payment": debt += -item.amount
            elif item.transaction_type == "savings": savings += -item.amount
            elif item.transaction_type == "transfer": transfers += item.amount
        total = money(sum(categories.values(), Decimal("0.00")))
        return SpendingSummary(
            start, end, total,
            tuple(sorted(((key, money(value)) for key, value in categories.items()), key=lambda item: (-item[1], item[0]))),
            tuple(sorted(((key, money(value)) for key, value in merchants.items()), key=lambda item: (-item[1], item[0]))),
            money(income), money(debt), money(savings), money(transfers),
            max((item.date for item in snapshot.transactions), default=None),
        )

    def monthly_trend(self, end_month: str, *, count: int = 3) -> SpendingTrend:
        if not 2 <= count <= 12:
            raise FinanceValidationError("Finance trend count must be 2 through 12 months.")
        revision = self._repository.revision()
        year, month_number = self._parse_month(end_month)
        periods: list[tuple[str, Decimal]] = []
        for offset in reversed(range(count)):
            y, m = self._shift_month(year, month_number, -offset)
            start = date(y, m, 1)
            next_y, next_m = self._shift_month(y, m, 1)
            end = date(next_y, next_m, 1) - timedelta(days=1)
            periods.append((f"{y:04d}-{m:02d}", self.spending_summary(start, end).total))
        prior = periods[-2][1]
        current = periods[-1][1]
        average = money(sum((value for _, value in periods[:-1]), Decimal("0")) / Decimal(len(periods) - 1))
        result = SpendingTrend(tuple(periods), money(current - prior), money(current - average))
        self._ensure_revision(revision)
        return result

    def upcoming_bills(self, start: date, *, days: int = 7) -> BillsSummary:
        if not 0 <= days <= 366:
            raise FinanceValidationError("Upcoming bill window must be 0 through 366 days.")
        snapshot = self._repository.read()
        end = start + timedelta(days=days)
        occurrences: list[tuple[date, str, Decimal]] = []
        warnings: list[str] = []
        for bill in snapshot.bills:
            if not bill.active:
                continue
            for due in self._bill_occurrences(bill, start, end):
                paid = any(
                    item.related_bill_id == bill.identifier
                    and date(due.year, due.month, 1) <= item.date <= due
                    for item in snapshot.transactions
                )
                if not paid:
                    occurrences.append((due, bill.name, bill.expected_amount))
                    possible = any(
                        item.related_bill_id is None
                        and item.amount < 0
                        and date(due.year, due.month, 1) <= item.date <= due
                        and bill.name.casefold() in item.merchant.casefold()
                        for item in snapshot.transactions
                    )
                    if possible:
                        warnings.append(
                            f"A possible unlinked {bill.name} payment was not assumed paid."
                        )
        occurrences.sort()
        return BillsSummary(
            tuple(occurrences),
            money(sum((item[2] for item in occurrences), Decimal("0"))),
            tuple(dict.fromkeys(warnings)),
        )

    def average_bill(self, name: str, *, sample_count: int = 3) -> tuple[Decimal | None, int, str | None]:
        snapshot = self._repository.read()
        bill = next((item for item in snapshot.bills if item.name.casefold() == name.strip().casefold()), None)
        if bill is None:
            return None, 0, "That bill is not recorded."
        dated_payments = sorted(
            ((item.date, -item.amount) for item in snapshot.transactions if item.related_bill_id == bill.identifier and item.amount < 0),
            key=lambda item: item[0],
        )[-sample_count:]
        payments = [amount for _when, amount in dated_payments]
        if payments:
            return money(sum(payments, Decimal("0")) / Decimal(len(payments))), len(payments), None
        if bill.rolling_average is not None:
            return bill.rolling_average, 0, "Using the workbook's rolling average because no linked payments are available."
        return None, 0, "No linked bill-payment history is available."

    def debt_summary(self) -> DebtSummary:
        debts = tuple(item for item in self._repository.read().debts if item.active)
        warnings = tuple(
            f"{item.name} balance is dated {item.balance_as_of.isoformat()} and may be stale."
            for item in debts if (self._today() - item.balance_as_of).days > STALE_BALANCE_DAYS
        )
        return DebtSummary(
            tuple(sorted(debts, key=lambda item: (-item.apr, item.priority, item.name))),
            money(sum((item.current_balance for item in debts), Decimal("0"))),
            max(debts, key=lambda item: item.apr, default=None),
            money(sum((item.minimum_payment for item in debts), Decimal("0"))),
            money(sum((item.target_payment for item in debts), Decimal("0"))),
            warnings,
        )

    def affordability(self, purchase_amount: Decimal | str, month: str) -> AffordabilityResult:
        purchase = money(purchase_amount)
        if purchase <= 0:
            raise FinanceValidationError("Purchase amount must be positive.")
        snapshot = self._repository.read()
        budget = next((item for item in snapshot.budgets if item.month == month), None)
        if budget is None:
            result = AffordabilityResult(purchase, month, "insufficient data", None, None, None, None, Decimal("0.00"), ("No budget exists for that month.",))
            self._ensure_revision(snapshot.revision)
            return result
        year, month_number = self._parse_month(month)
        first = date(year, month_number, 1)
        next_y, next_m = self._shift_month(year, month_number, 1)
        last = date(next_y, next_m, 1) - timedelta(days=1)
        spending = self.spending_summary(first, last)
        discretionary_spent = money(sum((value for category, value in spending.categories if category in DISCRETIONARY_CATEGORIES), Decimal("0")))
        discretionary_remaining = max(Decimal("0.00"), money(budget.discretionary_target - discretionary_spent))
        bills = self.upcoming_bills(max(first, self._today()), days=max(0, (last - max(first, self._today())).days))
        debts = self.debt_summary()
        warnings = list(debts.warnings)
        if budget.starting_available_funds is None:
            warnings.append("Starting available funds are unknown.")
            result = AffordabilityResult(purchase, month, "insufficient data", discretionary_remaining, None, None, None, bills.total, tuple(warnings))
            self._ensure_revision(snapshot.revision)
            return result
        outflows = money(sum((-item.amount for item in snapshot.transactions if first <= item.date <= last and item.amount < 0 and item.transaction_type != "transfer"), Decimal("0")))
        paid_savings = money(sum((-item.amount for item in snapshot.transactions if first <= item.date <= last and item.transaction_type == "savings"), Decimal("0")))
        remaining_savings = max(Decimal("0.00"), money(budget.savings_target - paid_savings))
        linked_debt_paid = defaultdict(lambda: Decimal("0.00"))
        for item in snapshot.transactions:
            if first <= item.date <= last and item.transaction_type == "debt_payment" and item.related_debt_id:
                linked_debt_paid[item.related_debt_id] += -item.amount
        remaining_required_debt = money(sum(
            (max(Decimal("0.00"), item.minimum_payment - linked_debt_paid[item.identifier]) for item in debts.debts),
            Decimal("0.00"),
        ))
        total_debt_paid = money(sum(linked_debt_paid.values(), Decimal("0.00")))
        paid_above_minimum = max(Decimal("0.00"), money(total_debt_paid - (debts.minimum_payments - remaining_required_debt)))
        remaining_extra_debt = max(Decimal("0.00"), money(budget.extra_debt_payment_target - paid_above_minimum))
        cash = money(
            budget.starting_available_funds + budget.expected_income - outflows - bills.total
            - remaining_required_debt - remaining_savings - remaining_extra_debt - budget.reserve_buffer
        )
        cash = max(Decimal("0.00"), cash)
        conservative = min(discretionary_remaining, cash)
        status: Literal["within current plan", "outside current plan", "insufficient data"] = (
            "within current plan" if purchase <= conservative and not warnings else
            "insufficient data" if warnings else "outside current plan"
        )
        result = AffordabilityResult(
            purchase, month, status, discretionary_remaining, cash, conservative,
            money(conservative - purchase), money(bills.total + remaining_required_debt), tuple(warnings),
        )
        self._ensure_revision(snapshot.revision)
        return result

    def payoff_scenario(self, debt_name: str, *, extra_payment: Decimal | str = Decimal("0")) -> PayoffScenario:
        debt = self._resolve_active_debt(debt_name)
        extra = money(extra_payment)
        if extra < 0:
            raise FinanceValidationError("Extra payment cannot be negative.")
        warnings: list[str] = []
        if (self._today() - debt.balance_as_of).days > STALE_BALANCE_DAYS:
            warnings.append(f"{debt.name} balance is stale as of {debt.balance_as_of.isoformat()}.")
        baseline = self._payoff(debt.current_balance, debt.apr, debt.target_payment, debt.balance_as_of)
        comparison = self._payoff(debt.current_balance, debt.apr, debt.target_payment + extra, debt.balance_as_of)
        if baseline is None or comparison is None:
            warnings.append("The selected payment does not produce a bounded payoff estimate.")
        return PayoffScenario(
            debt.name, debt.balance_as_of, baseline, comparison, extra,
            None if baseline is None or comparison is None else baseline.months - comparison.months,
            None if baseline is None or comparison is None else money(baseline.total_interest - comparison.total_interest),
            tuple(warnings),
        )

    def _resolve_active_debt(self, reference: str) -> Debt:
        """Resolve an exact or uniquely identifying friendly active-debt name."""

        query = " ".join(reference.casefold().split())
        active = tuple(item for item in self._repository.read().debts if item.active)
        exact = tuple(
            item for item in active
            if " ".join(item.name.casefold().split()) == query
        )
        if len(exact) == 1:
            return exact[0]
        partial = tuple(
            item for item in active
            if query and query in " ".join(item.name.casefold().split())
        )
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            choices = ", ".join(item.name for item in partial)
            raise FinanceValidationError(
                f"More than one active debt matches “{reference.strip()}”: {choices}. "
                "Use a more specific debt name."
            )
        raise FinanceValidationError("That active debt is not recorded.")

    def goal_progress(self) -> tuple[GoalProgress, ...]:
        snapshot = self._repository.read()
        debts = {item.identifier: item for item in snapshot.debts}
        results: list[GoalProgress] = []
        for goal in snapshot.goals:
            if goal.goal_type == "debt_payoff":
                debt = debts[goal.linked_debt_id or ""]
                current = max(Decimal("0"), money((goal.debt_starting_balance or Decimal("0")) - debt.current_balance))
                as_of = debt.balance_as_of
            else:
                current = goal.current_amount or Decimal("0.00")
                as_of = goal.amount_as_of
            current = min(goal.target_amount, current)
            percent = (current / goal.target_amount * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            warning = None
            if (self._today() - as_of).days > STALE_BALANCE_DAYS:
                warning = f"Progress is dated {as_of.isoformat()} and may be stale."
            results.append(GoalProgress(goal.name, current, goal.target_amount, money(goal.target_amount - current), percent, as_of, warning))
        return tuple(results)

    def preview_import(
        self, source_path: Path | str, *, account_label: str, mapping: CSVImportMapping | None = None
    ) -> ImportPreview:
        snapshot = self._repository.read()
        source = Path(source_path).expanduser().absolute()
        incoming = self._repository.workbook_path.parent / "imports" / "incoming"
        try:
            source_resolved = source.resolve(strict=True)
            incoming_resolved = incoming.resolve(strict=True)
            source_resolved.relative_to(incoming_resolved)
            if source_resolved != source:
                raise ValueError("symbolic link")
        except (OSError, ValueError) as exc:
            raise FinanceValidationError("Finance imports must be selected from the configured incoming directory.") from exc
        source = source_resolved
        suffix = source.suffix.casefold()
        if suffix == ".csv":
            raw = self._parse_csv(source, account_label, mapping or CSVImportMapping())
        elif suffix in {".ofx", ".qfx"}:
            raw = self._parse_ofx(source, account_label)
        elif suffix == ".pdf":
            raw = PDFStatementAdapter().parse(source, account_label=account_label)
        else:
            raise FinanceError("Finance import format is unsupported.", code="unsupported_finance_import")
        digest = self._file_digest(source)
        batch_id = f"batch-{digest.removeprefix('sha256:')[:24]}"
        candidates = self._normalize_candidates(raw, snapshot, source_batch_id=batch_id)
        return ImportPreview(
            self._identifier("preview"), source, digest, self._candidate_digest(candidates), snapshot.revision,
            account_label.strip(), candidates, tuple(sorted({warning for item in candidates for warning in item.uncertainty})),
        )

    def revise_preview(
        self,
        preview: ImportPreview,
        candidates: Sequence[CandidateTransaction],
    ) -> ImportPreview:
        """Bind reviewed category/include corrections without changing source facts."""

        self.validate_preview(preview)
        if len(candidates) != len(preview.candidates):
            raise FinanceValidationError("Reviewed import candidates do not match the preview.")
        source_fields = (
            "source_reference", "date", "original_description", "amount", "transaction_type",
            "account_label", "import_source", "source_transaction_id", "source_amount",
            "source_sign_convention", "duplicate_fingerprint", "duplicate_state",
        )
        for before, after in zip(preview.candidates, candidates):
            if any(getattr(before, field) != getattr(after, field) for field in source_fields):
                raise FinanceValidationError("Reviewed import corrections changed immutable source evidence.")
        revised = tuple(candidates)
        return replace(
            preview,
            candidates=revised,
            candidate_digest=self._candidate_digest(revised),
            warnings=tuple(sorted({warning for item in revised for warning in item.uncertainty})),
        )

    def validate_preview(self, preview: ImportPreview) -> None:
        """Fail closed when transient import review authority is stale."""

        if self._repository.revision() != preview.workbook_revision:
            raise FinanceConflictError()
        if self._file_digest(preview.source_path) != preview.source_digest:
            raise FinanceConflictError(
                "The import source changed during review; nothing was imported."
            )
        if self._candidate_digest(preview.candidates) != preview.candidate_digest:
            raise FinanceConflictError(
                "The import preview changed during review; nothing was imported."
            )

    def review_candidate(
        self,
        preview: ImportPreview,
        candidate_number: int,
        *,
        merchant: str | None = None,
        category: str | None = None,
        included: bool | None = None,
    ) -> ImportPreview:
        """Apply one explicit, non-persistent candidate review decision."""

        if isinstance(candidate_number, bool) or not 1 <= candidate_number <= len(preview.candidates):
            raise FinanceValidationError("Finance review candidate number is invalid.")
        candidate = preview.candidates[candidate_number - 1]
        if candidate.duplicate_state == "definite" and included is not False:
            raise FinanceValidationError(
                "A definite duplicate cannot be included through candidate review."
            )
        uncertainties = list(candidate.uncertainty)
        updates: dict[str, object] = {}
        if merchant is not None or category is not None:
            if merchant is None or category is None:
                raise FinanceValidationError(
                    "Reviewed merchant and category must be supplied together."
                )
            reviewed_merchant = " ".join(merchant.strip().split())
            reviewed_category = " ".join(category.strip().split())
            if not reviewed_merchant or not reviewed_category:
                raise FinanceValidationError(
                    "Reviewed merchant and category cannot be empty."
                )
            updates.update(
                merchant=reviewed_merchant,
                category=reviewed_category,
                matched_rule_id=None,
            )
            uncertainties = [
                warning for warning in uncertainties
                if warning not in {
                    "Unknown merchant/category requires review.",
                    "Conflicting merchant rules require review.",
                }
            ]
        if included is not None:
            updates["included"] = included
            uncertainties = [
                warning for warning in uncertainties
                if warning != "Possible duplicate requires review."
            ]
        updates["uncertainty"] = tuple(uncertainties)
        candidates = list(preview.candidates)
        candidates[candidate_number - 1] = replace(candidate, **updates)
        return self.revise_preview(preview, candidates)

    def reviewed_merchant_rule(
        self,
        preview: ImportPreview,
        candidate_number: int,
        *,
        match_type: str,
        match_text: str,
        merchant: str,
        category: str,
    ) -> tuple[ImportPreview, MerchantRule]:
        """Apply one reviewed account-scoped rule to unresolved candidates."""

        self.validate_preview(preview)
        if isinstance(candidate_number, bool) or not 1 <= candidate_number <= len(preview.candidates):
            raise FinanceValidationError("Finance review candidate number is invalid.")
        rule = MerchantRule(
            self._identifier("rule"), match_type, match_text, merchant, category,
            100, account_scope=preview.account_label,
            notes=f"Reviewed during import {preview.identifier}",
        )
        selected = preview.candidates[candidate_number - 1]
        selected_match = self._apply_rules(selected, (rule,))[0]
        if selected_match is None:
            raise FinanceValidationError(
                "The reviewed merchant rule does not match the selected candidate."
            )
        current = self._repository.read()
        combined_rules = (*current.merchant_rules, rule)
        candidates: list[CandidateTransaction] = []
        for candidate in preview.candidates:
            category_warnings = {
                "Unknown merchant/category requires review.",
                "Conflicting merchant rules require review.",
            }
            if not category_warnings.intersection(candidate.uncertainty):
                candidates.append(candidate)
                continue
            normalized_merchant, normalized_category, rule_id, rule_warnings = (
                self._apply_rules(candidate, combined_rules)
            )
            if normalized_merchant is None:
                candidates.append(candidate)
                continue
            remaining = [
                warning for warning in candidate.uncertainty
                if warning not in category_warnings
            ]
            remaining.extend(rule_warnings)
            candidates.append(replace(
                candidate,
                merchant=normalized_merchant,
                category=normalized_category,
                matched_rule_id=rule_id,
                uncertainty=tuple(dict.fromkeys(remaining)),
            ))
        return self.revise_preview(preview, candidates), rule

    def propose_import(
        self,
        preview: ImportPreview,
        *,
        merchant_rules: Sequence[MerchantRule] = (),
    ) -> FinanceMutation:
        self.validate_preview(preview)
        current = self._repository.read()
        batch_id = f"batch-{preview.source_digest.removeprefix('sha256:')[:24]}"
        additions: list[Transaction] = []
        for candidate in preview.included:
            if candidate.merchant is None or candidate.category is None or candidate.uncertainty:
                raise FinanceValidationError("Import preview has unresolved items; nothing was proposed.")
            additions.append(Transaction(
                self._identifier("txn"), candidate.date, candidate.merchant, candidate.original_description,
                candidate.amount, candidate.transaction_type, candidate.category, candidate.account_label,
                candidate.import_source, batch_id, candidate.source_transaction_id,
                candidate.duplicate_fingerprint,
            ))
        rules_by_id = {item.identifier: item for item in current.merchant_rules}
        for rule in merchant_rules:
            rules_by_id[rule.identifier] = rule
        updated = replace(
            current,
            transactions=current.transactions + tuple(additions),
            merchant_rules=tuple(rules_by_id.values()),
            summary_rows=(),
        )
        presentation = (
            f"Import {len(additions)} reviewed transactions from {preview.source_path.name} into Finance? "
            f"{sum(1 for item in preview.candidates if item.duplicate_state == 'definite')} definite duplicates remain excluded. "
            f"Apply {len(merchant_rules)} separately reviewed reusable merchant rules in the same atomic change."
        )
        if merchant_rules:
            details = "; ".join(
                f"{rule.match_type} ‘{rule.match_text}’ → {rule.normalized_merchant} / "
                f"{rule.category} (account: {rule.account_scope})"
                for rule in merchant_rules
            )
            presentation = f"{presentation} Reviewed rules: {details}."
        return FinanceMutation(
            "apply_import", current.revision, updated, presentation, preview,
            tuple(merchant_rules),
        )

    def _normalize_candidates(
        self,
        candidates: Sequence[CandidateTransaction],
        snapshot: FinanceSnapshot,
        *,
        source_batch_id: str,
    ) -> tuple[CandidateTransaction, ...]:
        existing_source_ids = {
            (item.account_label.casefold(), item.source_transaction_id)
            for item in snapshot.transactions if item.source_transaction_id
        }
        committed_counts = Counter(item.duplicate_fingerprint for item in snapshot.transactions)
        batch_already_committed = any(
            item.import_batch_id == source_batch_id for item in snapshot.transactions
        )
        seen_counts: Counter[str] = Counter()
        seen_source_ids: set[tuple[str, str]] = set()
        result: list[CandidateTransaction] = []
        for candidate in candidates:
            fingerprint = self._fingerprint(candidate)
            seen_counts[fingerprint] += 1
            source_key = (
                (candidate.account_label.casefold(), candidate.source_transaction_id)
                if candidate.source_transaction_id else None
            )
            repeated_batch_source_id = (
                source_key is not None and source_key in seen_source_ids
            )
            if source_key is not None:
                seen_source_ids.add(source_key)
            merchant, category, rule_id, uncertainties = self._apply_rules(candidate, snapshot.merchant_rules)
            duplicate: Literal["none", "definite", "possible"] = "none"
            if batch_already_committed:
                duplicate = "definite"
            elif candidate.source_transaction_id and (
                candidate.account_label.casefold(), candidate.source_transaction_id
            ) in existing_source_ids:
                duplicate = "definite"
            elif repeated_batch_source_id:
                duplicate = "definite"
            elif committed_counts[fingerprint] >= seen_counts[fingerprint]:
                duplicate = "possible"
                uncertainties.append("Possible duplicate requires review.")
            if merchant is None:
                merchant = self._friendly_merchant(candidate.original_description)
                category = "Other"
                uncertainties.append("Unknown merchant/category requires review.")
            result.append(replace(
                candidate, merchant=merchant, category=category, matched_rule_id=rule_id,
                duplicate_state=duplicate, uncertainty=tuple(dict.fromkeys(uncertainties)),
                duplicate_fingerprint=fingerprint, included=duplicate != "definite",
            ))
        return tuple(result)

    def _ensure_revision(self, expected: str | None) -> None:
        if self._repository.revision() != expected:
            raise FinanceConflictError("Finance data changed during calculation; please retry for a consistent result.")

    @staticmethod
    def _apply_rules(candidate: CandidateTransaction, rules: Sequence[MerchantRule]) -> tuple[str | None, str | None, str | None, list[str]]:
        text = " ".join(candidate.original_description.casefold().split())
        matches: list[tuple[int, int, MerchantRule]] = []
        specificity = {"exact": 0, "starts_with": 1, "contains": 2}
        for rule in rules:
            if not rule.active or rule.account_scope and rule.account_scope.casefold() != candidate.account_label.casefold():
                continue
            needle = " ".join(rule.match_text.casefold().split())
            matched = text == needle if rule.match_type == "exact" else text.startswith(needle) if rule.match_type == "starts_with" else needle in text
            if matched:
                matches.append((rule.priority, specificity[rule.match_type], rule))
        if not matches:
            return None, None, None, []
        matches.sort(key=lambda item: (item[0], item[1], item[2].identifier))
        best = matches[0]
        tied = [item[2] for item in matches if item[:2] == best[:2]]
        outputs = {(item.normalized_merchant, item.category) for item in tied}
        if len(outputs) > 1:
            return None, None, None, ["Conflicting merchant rules require review."]
        rule = best[2]
        return rule.normalized_merchant, rule.category, rule.identifier, []

    @staticmethod
    def _friendly_merchant(description: str) -> str:
        words = re.sub(r"[^\w&' -]+", " ", description).strip().split()
        return " ".join(words[:6]).title() or "Unknown"

    @staticmethod
    def _fingerprint(candidate: CandidateTransaction) -> str:
        description = " ".join(candidate.original_description.casefold().split())
        raw = "\x1f".join((candidate.account_label.casefold(), candidate.date.isoformat(), str(candidate.amount), candidate.transaction_type, description))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise FinanceError("Finance statement could not be read.", code="finance_import_unavailable") from exc
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _candidate_digest(candidates: Sequence[CandidateTransaction]) -> str:
        payload = [
            {
                "source_reference": item.source_reference, "date": item.date.isoformat(),
                "description": item.original_description, "amount": str(item.amount), "type": item.transaction_type,
                "account": item.account_label, "source_id": item.source_transaction_id,
                "source_amount": None if item.source_amount is None else str(item.source_amount),
                "source_sign": item.source_sign_convention,
                "merchant": item.merchant, "category": item.category, "rule": item.matched_rule_id,
                "duplicate": item.duplicate_state, "uncertainty": item.uncertainty, "included": item.included,
            }
            for item in candidates
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def _parse_csv(self, path: Path, account_label: str, mapping: CSVImportMapping) -> tuple[CandidateTransaction, ...]:
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise FinanceValidationError("Finance CSV exceeds the 20 MB V1 limit.")
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                required = {mapping.date_column, mapping.description_column, mapping.amount_column, mapping.type_column}
                if reader.fieldnames is None or not required <= set(reader.fieldnames):
                    raise FinanceValidationError("CSV columns do not match the reviewed Finance import mapping.")
                result = []
                for index, row in enumerate(reader, start=2):
                    try:
                        transaction_date = date.fromisoformat(row[mapping.date_column]) if mapping.date_format == "%Y-%m-%d" else datetime.strptime(row[mapping.date_column], mapping.date_format).date()
                        raw_amount = money(row[mapping.amount_column])
                        transaction_type = row[mapping.type_column].strip().casefold()
                        if transaction_type not in {"income", "expense", "refund", "transfer", "debt_payment", "savings", "adjustment"}:
                            raise FinanceValidationError("CSV transaction type is invalid.")
                        amount = abs(raw_amount) if transaction_type in {"income", "refund"} else -abs(raw_amount) if transaction_type in {"expense", "debt_payment", "savings"} else raw_amount
                        if mapping.debit_positive and transaction_type not in {"income", "refund"}:
                            amount = -abs(raw_amount)
                        result.append(CandidateTransaction(
                            f"CSV row {index}", transaction_date, row[mapping.description_column], amount,
                            transaction_type, account_label, "CSV",
                            row.get(mapping.source_id_column) or None if mapping.source_id_column else None,
                            raw_amount, "CSV amount normalized by reviewed type/sign mapping",
                        ))
                    except (KeyError, ValueError, FinanceValidationError) as exc:
                        raise FinanceValidationError(f"CSV row {index} is invalid.") from exc
                return tuple(result)
        except UnicodeError as exc:
            raise FinanceValidationError("Finance CSV must be UTF-8 text.") from exc
        except OSError as exc:
            raise FinanceError("Finance CSV could not be read.", code="finance_import_unavailable") from exc

    def _parse_ofx(self, path: Path, account_label: str) -> tuple[CandidateTransaction, ...]:
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise FinanceValidationError("Finance OFX/QFX exceeds the 20 MB V1 limit.")
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as exc:
            raise FinanceError(
                "This OFX/QFX export is not validated XML; a reviewed adapter is required and nothing was imported.",
                code="unsupported_finance_import",
            ) from exc
        result: list[CandidateTransaction] = []
        for index, node in enumerate(root.findall(".//STMTTRN"), start=1):
            values = {child.tag.split("}")[-1]: (child.text or "").strip() for child in node}
            try:
                raw_date = values["DTPOSTED"]
                posted = (
                    date.fromisoformat(raw_date[:10])
                    if "-" in raw_date[:10]
                    else datetime.strptime(raw_date[:8], "%Y%m%d").date()
                )
                raw = money(values["TRNAMT"])
                ofx_type = values.get("TRNTYPE", "OTHER").upper()
                if raw > 0:
                    transaction_type = "income" if ofx_type not in {"CREDIT", "REFUND"} else "refund"
                else:
                    transaction_type = "transfer" if ofx_type in {"XFER", "PAYMENT"} else "expense"
                result.append(CandidateTransaction(
                    f"OFX transaction {index}", posted, values.get("NAME") or values.get("MEMO") or "Unknown",
                    raw, transaction_type, account_label, "OFX/QFX", values.get("FITID") or None,
                    raw, "OFX TRNAMT signed account movement mapped by TRNTYPE",
                ))
            except (KeyError, ValueError, FinanceValidationError) as exc:
                raise FinanceValidationError(f"OFX/QFX transaction {index} is invalid.") from exc
        if not result:
            raise FinanceValidationError("OFX/QFX contains no supported transactions.")
        return tuple(result)

    @staticmethod
    def _parse_month(value: str) -> tuple[int, int]:
        try:
            parsed = date.fromisoformat(f"{value}-01")
        except ValueError as exc:
            raise FinanceValidationError("Month must be YYYY-MM.") from exc
        return parsed.year, parsed.month

    @staticmethod
    def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
        index = year * 12 + month - 1 + delta
        return divmod(index, 12)[0], divmod(index, 12)[1] + 1

    @classmethod
    def _bill_occurrences(cls, bill: Bill, start: date, end: date) -> Iterable[date]:
        current = bill.next_due_date
        while current < start:
            if bill.frequency == "one_time": return
            current = cls._next_due(current, bill.frequency, bill.due_day)
        while current <= end:
            yield current
            if bill.frequency == "one_time": return
            current = cls._next_due(current, bill.frequency, bill.due_day)

    @classmethod
    def _next_due(cls, current: date, frequency: str, due_day: int | None) -> date:
        if frequency == "weekly": return current + timedelta(days=7)
        if frequency == "biweekly": return current + timedelta(days=14)
        months = {"monthly": 1, "quarterly": 3, "annual": 12}[frequency]
        year, month_number = cls._shift_month(current.year, current.month, months)
        next_year, next_month = cls._shift_month(year, month_number, 1)
        last_day = (date(next_year, next_month, 1) - timedelta(days=1)).day
        return date(year, month_number, min(due_day or current.day, last_day))

    @classmethod
    def _payoff(cls, balance: Decimal, apr: Decimal, payment: Decimal, as_of: date) -> PayoffEstimate | None:
        if balance <= 0:
            return PayoffEstimate(0, Decimal("0.00"), f"{as_of.year:04d}-{as_of.month:02d}")
        monthly_rate = apr / Decimal("100") / Decimal("12")
        remaining = balance
        interest_total = Decimal("0.00")
        for month_count in range(1, 1201):
            interest = money(remaining * monthly_rate)
            if payment <= interest:
                return None
            interest_total = money(interest_total + interest)
            remaining = money(remaining + interest - min(payment, remaining + interest))
            if remaining <= 0:
                year, month_number = cls._shift_month(as_of.year, as_of.month, month_count)
                return PayoffEstimate(month_count, interest_total, f"{year:04d}-{month_number:02d}")
        return None
