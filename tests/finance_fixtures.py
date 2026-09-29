"""Synthetic-only Finance V1 fixtures."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from tori.finance import Bill, Budget, Debt, FinanceConflictError, FinanceSnapshot, Goal, MerchantRule, Transaction


def transaction(
    identifier: str, when: str, merchant: str, amount: str, category: str,
    *, transaction_type: str = "expense", bill: str | None = None, debt: str | None = None,
    description: str | None = None,
) -> Transaction:
    return Transaction(
        identifier, date.fromisoformat(when), merchant, description or merchant.upper(), Decimal(amount),
        transaction_type, category, "Checking", "synthetic", duplicate_fingerprint=f"fp-{identifier}",
        related_bill_id=bill, related_debt_id=debt,
    )


def synthetic_snapshot(revision: str = "rev-1") -> FinanceSnapshot:
    transactions = (
        transaction("t1", "2026-06-04", "McDonald's", "-12.50", "Dining / Fast Food"),
        transaction("t2", "2026-06-08", "Amazon", "-80.00", "Amazon"),
        transaction("t3", "2026-07-04", "McDonald's", "-15.00", "Dining / Fast Food"),
        transaction("t4", "2026-07-08", "Amazon", "-110.00", "Amazon"),
        transaction("t5", "2026-08-02", "McDonald's", "-18.25", "Dining / Fast Food"),
        transaction("t6", "2026-08-03", "McDonald's", "-9.75", "Dining / Fast Food"),
        transaction("t7", "2026-08-04", "Amazon", "-125.00", "Amazon"),
        transaction("t8", "2026-08-05", "Market", "-90.00", "Groceries"),
        transaction("t9", "2026-08-06", "Gas Station", "-45.00", "Transportation"),
        transaction("t10", "2026-08-07", "Electric", "-155.00", "Utilities", bill="bill-electric"),
        transaction("t11", "2026-08-08", "Internet", "-85.00", "Utilities", bill="bill-internet"),
        transaction("t12", "2026-08-09", "Streaming", "-15.00", "Subscriptions"),
        transaction("t13", "2026-08-10", "Amazon", "20.00", "Amazon", transaction_type="refund"),
        transaction("t14", "2026-08-11", "Transfer", "-200.00", "Transfer", transaction_type="transfer"),
        transaction("t15", "2026-08-12", "Citi Card", "-100.00", "Debt Payment", transaction_type="debt_payment", debt="debt-citi"),
    )
    rules = (
        MerchantRule("rule-mcd", "contains", "MCDONALD", "McDonald's", "Dining / Fast Food", 10),
        MerchantRule("rule-amzn", "contains", "AMZN", "Amazon", "Amazon", 10),
    )
    bills = (
        Bill("bill-electric", "Electric", "Utilities", "variable", Decimal("159"), date(2026, 8, 20), "monthly", True, rolling_average=Decimal("157"), due_day=20),
        Bill("bill-internet", "Internet", "Utilities", "fixed", Decimal("85"), date(2026, 8, 15), "monthly", True, due_day=15),
    )
    debts = (
        Debt("debt-citi", "Citi Card", "credit_card", Decimal("3000"), Decimal("24.99"), Decimal("90"), Decimal("150"), date(2026, 8, 22), 1, date(2026, 8, 1)),
        Debt("debt-auto", "Auto Loan", "loan", Decimal("9000"), Decimal("6.25"), Decimal("325"), Decimal("325"), date(2026, 8, 25), 2, date(2026, 8, 1)),
    )
    budgets = (
        Budget("2026-08", Decimal("5000"), Decimal("1500"), Decimal("800"), Decimal("400"), Decimal("200"), Decimal("500"), Decimal("1000")),
    )
    goals = (
        Goal("goal-guitar", "New Guitar", "purchase", Decimal("900"), 1, "active", date(2026, 8, 1), current_amount=Decimal("300"), target_date=date(2026, 12, 1)),
        Goal("goal-citi", "Pay Off Citi", "debt_payoff", Decimal("2000"), 2, "active", date(2026, 8, 1), linked_debt_id="debt-citi", debt_starting_balance=Decimal("5000")),
    )
    return FinanceSnapshot(revision, "USD", transactions, rules, bills, debts, budgets, goals)


class FakeFinanceRepository:
    def __init__(self, snapshot: FinanceSnapshot | None = None, path: Path = Path("/tmp/synthetic-finance/tori_finance.xlsx")) -> None:
        self.snapshot = snapshot
        self.workbook_path = path

    def exists(self) -> bool:
        return self.snapshot is not None

    def revision(self) -> str | None:
        return None if self.snapshot is None else self.snapshot.revision

    def read(self) -> FinanceSnapshot:
        if self.snapshot is None:
            from tori.finance import FinanceError
            raise FinanceError("Finance has not been initialized.", code="finance_not_initialized")
        return self.snapshot

    def create(self, *, currency: str, expected_revision: str | None = None) -> FinanceSnapshot:
        if self.snapshot is not None or expected_revision is not None:
            raise FinanceConflictError()
        self.snapshot = FinanceSnapshot("rev-1", currency)
        return self.snapshot

    def replace(self, snapshot: FinanceSnapshot, *, expected_revision: str) -> FinanceSnapshot:
        if self.snapshot is None or self.snapshot.revision != expected_revision:
            raise FinanceConflictError()
        next_revision = f"rev-{int(expected_revision.split('-')[-1]) + 1}"
        self.snapshot = replace(snapshot, revision=next_revision)
        return self.snapshot
