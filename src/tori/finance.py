"""Presentation-neutral Finance V1 domain and repository contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Literal, Protocol, TypeVar


CONTRACT_VERSION = "1"
DEFAULT_CURRENCY = "USD"
MONEY_QUANTUM = Decimal("0.01")
STALE_BALANCE_DAYS = 31

TransactionType = Literal[
    "income", "expense", "refund", "transfer", "debt_payment", "savings", "adjustment"
]
DuplicateState = Literal["none", "definite", "possible"]

DEFAULT_CATEGORIES = (
    "Income", "Housing", "Utilities", "Groceries", "Dining / Fast Food",
    "Shopping", "Amazon", "Transportation", "Entertainment", "Subscriptions",
    "Healthcare", "Personal", "Debt Payment", "Savings", "Transfer", "Other",
)
ESSENTIAL_CATEGORIES = frozenset({"Housing", "Utilities", "Groceries", "Transportation", "Healthcare"})
DISCRETIONARY_CATEGORIES = frozenset({
    "Dining / Fast Food", "Shopping", "Amazon", "Entertainment", "Subscriptions", "Personal", "Other"
})


class FinanceError(RuntimeError):
    """Base bounded Finance failure."""

    def __init__(self, message: str, *, code: str = "finance_error") -> None:
        super().__init__(message)
        self.code = code


class FinanceValidationError(FinanceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="invalid_finance_data")


class FinanceConflictError(FinanceError):
    def __init__(self, message: str = "Finance data changed before confirmation; nothing was overwritten.") -> None:
        super().__init__(message, code="stale_confirmation")


def money(value: Decimal | int | str) -> Decimal:
    """Return exact currency money, rejecting floats and non-finite values."""

    if isinstance(value, bool) or isinstance(value, float):
        raise FinanceValidationError("Money must use exact decimal input, not binary floating point.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise FinanceValidationError("Money value is invalid.") from exc
    if not result.is_finite():
        raise FinanceValidationError("Money value must be finite.")
    return result.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: str, field_name: str, *, optional: bool = False) -> str:
    result = " ".join(value.strip().split())
    if not result and not optional:
        raise FinanceValidationError(f"{field_name} is required.")
    if any(ord(character) < 32 and character not in "\t" for character in result):
        raise FinanceValidationError(f"{field_name} contains unsupported control characters.")
    return result


def _priority(value: int) -> int:
    if isinstance(value, bool) or not 1 <= value <= 999:
        raise FinanceValidationError("Priority must be an integer from 1 through 999.")
    return value


@dataclass(frozen=True, slots=True)
class Transaction:
    identifier: str
    date: date
    merchant: str
    original_description: str
    amount: Decimal
    transaction_type: TransactionType
    category: str
    account_label: str
    import_source: str
    import_batch_id: str | None = None
    source_transaction_id: str | None = None
    duplicate_fingerprint: str = ""
    related_bill_id: str | None = None
    related_debt_id: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("identifier", "merchant", "original_description", "category", "account_label", "import_source"):
            object.__setattr__(self, name, _text(getattr(self, name), name.replace("_", " ").title()))
        object.__setattr__(self, "amount", money(self.amount))
        if self.amount == 0:
            raise FinanceValidationError("Transaction amount cannot be zero.")
        if self.transaction_type not in {
            "income", "expense", "refund", "transfer", "debt_payment", "savings", "adjustment"
        }:
            raise FinanceValidationError("Transaction type is invalid.")
        expected_positive = self.transaction_type in {"income", "refund"}
        expected_negative = self.transaction_type in {"expense", "debt_payment", "savings"}
        if expected_positive and self.amount < 0 or expected_negative and self.amount > 0:
            raise FinanceValidationError("Transaction amount sign conflicts with its type.")
        for name in ("import_batch_id", "source_transaction_id", "related_bill_id", "related_debt_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, name, optional=True) or None)
        object.__setattr__(self, "duplicate_fingerprint", _text(self.duplicate_fingerprint, "Duplicate fingerprint"))
        object.__setattr__(self, "notes", _text(self.notes, "Notes", optional=True))


@dataclass(frozen=True, slots=True)
class MerchantRule:
    identifier: str
    match_type: Literal["exact", "starts_with", "contains"]
    match_text: str
    normalized_merchant: str
    category: str
    priority: int
    active: bool = True
    account_scope: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.match_type not in {"exact", "starts_with", "contains"}:
            raise FinanceValidationError("Merchant rule match type is invalid.")
        for name in ("identifier", "match_text", "normalized_merchant", "category"):
            object.__setattr__(self, name, _text(getattr(self, name), name.replace("_", " ").title()))
        if self.match_type == "contains" and len(self.match_text) < 3:
            raise FinanceValidationError("A contains merchant rule needs at least three characters.")
        object.__setattr__(self, "priority", _priority(self.priority))
        if self.account_scope is not None:
            object.__setattr__(self, "account_scope", _text(self.account_scope, "Account scope", optional=True) or None)
        object.__setattr__(self, "notes", _text(self.notes, "Notes", optional=True))


@dataclass(frozen=True, slots=True)
class Bill:
    identifier: str
    name: str
    category: str
    amount_kind: Literal["fixed", "variable"]
    expected_amount: Decimal
    next_due_date: date
    frequency: Literal["weekly", "biweekly", "monthly", "quarterly", "annual", "one_time"]
    autopay: bool
    active: bool = True
    rolling_average: Decimal | None = None
    due_day: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("identifier", "name", "category"):
            object.__setattr__(self, name, _text(getattr(self, name), name.title()))
        if self.amount_kind not in {"fixed", "variable"}:
            raise FinanceValidationError("Bill amount kind is invalid.")
        if self.frequency not in {"weekly", "biweekly", "monthly", "quarterly", "annual", "one_time"}:
            raise FinanceValidationError("Bill frequency is invalid.")
        object.__setattr__(self, "expected_amount", money(self.expected_amount))
        if self.expected_amount < 0:
            raise FinanceValidationError("Bill expected amount cannot be negative.")
        if self.rolling_average is not None:
            object.__setattr__(self, "rolling_average", money(self.rolling_average))
        if self.due_day is not None and (isinstance(self.due_day, bool) or not 1 <= self.due_day <= 31):
            raise FinanceValidationError("Bill due day must be 1 through 31.")


@dataclass(frozen=True, slots=True)
class Debt:
    identifier: str
    name: str
    debt_type: Literal["credit_card", "loan", "other"]
    current_balance: Decimal
    apr: Decimal
    minimum_payment: Decimal
    target_payment: Decimal
    next_due_date: date
    priority: int
    balance_as_of: date
    active: bool = True
    due_day: int | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, "Debt ID"))
        object.__setattr__(self, "name", _text(self.name, "Debt name"))
        if self.debt_type not in {"credit_card", "loan", "other"}:
            raise FinanceValidationError("Debt type is invalid.")
        for name in ("current_balance", "minimum_payment", "target_payment"):
            object.__setattr__(self, name, money(getattr(self, name)))
            if getattr(self, name) < 0:
                raise FinanceValidationError(f"Debt {name.replace('_', ' ')} cannot be negative.")
        try:
            apr = Decimal(str(self.apr))
        except InvalidOperation as exc:
            raise FinanceValidationError("Debt APR is invalid.") from exc
        if not apr.is_finite() or apr < 0:
            raise FinanceValidationError("Debt APR cannot be negative.")
        object.__setattr__(self, "apr", apr.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
        if self.target_payment < self.minimum_payment:
            raise FinanceValidationError("Debt target payment cannot be below its minimum payment.")
        object.__setattr__(self, "priority", _priority(self.priority))
        if self.due_day is not None and (isinstance(self.due_day, bool) or not 1 <= self.due_day <= 31):
            raise FinanceValidationError("Debt due day must be 1 through 31.")


@dataclass(frozen=True, slots=True)
class Budget:
    month: str
    expected_income: Decimal
    essential_spending_target: Decimal
    discretionary_target: Decimal
    savings_target: Decimal
    extra_debt_payment_target: Decimal
    reserve_buffer: Decimal
    starting_available_funds: Decimal | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(f"{self.month}-01")
        except ValueError as exc:
            raise FinanceValidationError("Budget month must be YYYY-MM.") from exc
        for name in (
            "expected_income", "essential_spending_target", "discretionary_target",
            "savings_target", "extra_debt_payment_target", "reserve_buffer",
        ):
            object.__setattr__(self, name, money(getattr(self, name)))
            if getattr(self, name) < 0:
                raise FinanceValidationError(f"Budget {name.replace('_', ' ')} cannot be negative.")
        if self.starting_available_funds is not None:
            object.__setattr__(self, "starting_available_funds", money(self.starting_available_funds))


@dataclass(frozen=True, slots=True)
class Goal:
    identifier: str
    name: str
    goal_type: Literal["purchase", "savings", "debt_payoff"]
    target_amount: Decimal
    priority: int
    status: Literal["active", "paused", "completed"]
    amount_as_of: date
    current_amount: Decimal | None = None
    linked_debt_id: str | None = None
    debt_starting_balance: Decimal | None = None
    target_date: date | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, "Goal ID"))
        object.__setattr__(self, "name", _text(self.name, "Goal name"))
        if self.goal_type not in {"purchase", "savings", "debt_payoff"}:
            raise FinanceValidationError("Goal type is invalid.")
        if self.status not in {"active", "paused", "completed"}:
            raise FinanceValidationError("Goal status is invalid.")
        object.__setattr__(self, "target_amount", money(self.target_amount))
        if self.target_amount <= 0:
            raise FinanceValidationError("Goal target amount must be positive.")
        if self.current_amount is not None:
            object.__setattr__(self, "current_amount", money(self.current_amount))
            if self.current_amount < 0:
                raise FinanceValidationError("Goal current amount cannot be negative.")
        if self.debt_starting_balance is not None:
            object.__setattr__(self, "debt_starting_balance", money(self.debt_starting_balance))
        if self.goal_type == "debt_payoff":
            if not self.linked_debt_id or self.debt_starting_balance is None:
                raise FinanceValidationError("Debt-payoff goals require a linked debt and starting balance.")
        elif self.linked_debt_id is not None or self.debt_starting_balance is not None:
            raise FinanceValidationError("Only debt-payoff goals may link a debt.")
        object.__setattr__(self, "priority", _priority(self.priority))


@dataclass(frozen=True, slots=True)
class FinanceSnapshot:
    revision: str
    currency: str = DEFAULT_CURRENCY
    transactions: tuple[Transaction, ...] = ()
    merchant_rules: tuple[MerchantRule, ...] = ()
    bills: tuple[Bill, ...] = ()
    debts: tuple[Debt, ...] = ()
    budgets: tuple[Budget, ...] = ()
    goals: tuple[Goal, ...] = ()
    summary_rows: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise FinanceValidationError("Finance currency must be a three-letter ISO code.")
        object.__setattr__(self, "currency", currency)
        for values, label, key in (
            (self.transactions, "transaction", lambda item: item.identifier),
            (self.merchant_rules, "merchant rule", lambda item: item.identifier),
            (self.bills, "bill", lambda item: item.identifier),
            (self.debts, "debt", lambda item: item.identifier),
            (self.budgets, "budget", lambda item: item.month),
            (self.goals, "goal", lambda item: item.identifier),
        ):
            identifiers = [key(item) for item in values]
            if len(identifiers) != len(set(identifiers)):
                raise FinanceValidationError(f"Duplicate {label} identity exists.")
        bill_ids = {item.identifier for item in self.bills}
        debt_ids = {item.identifier for item in self.debts}
        if any(item.related_bill_id and item.related_bill_id not in bill_ids for item in self.transactions):
            raise FinanceValidationError("A transaction references an unknown bill.")
        if any(item.related_debt_id and item.related_debt_id not in debt_ids for item in self.transactions):
            raise FinanceValidationError("A transaction references an unknown debt.")
        if any(item.linked_debt_id and item.linked_debt_id not in debt_ids for item in self.goals):
            raise FinanceValidationError("A goal references an unknown debt.")

    def with_revision(self, revision: str) -> FinanceSnapshot:
        return replace(self, revision=revision)


@dataclass(frozen=True, slots=True)
class CandidateTransaction:
    source_reference: str
    date: date
    original_description: str
    amount: Decimal
    transaction_type: TransactionType
    account_label: str
    import_source: str
    source_transaction_id: str | None = None
    source_amount: Decimal | None = None
    source_sign_convention: str = ""
    merchant: str | None = None
    category: str | None = None
    matched_rule_id: str | None = None
    duplicate_state: DuplicateState = "none"
    uncertainty: tuple[str, ...] = ()
    duplicate_fingerprint: str = ""
    included: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", money(self.amount))
        if self.source_amount is not None:
            object.__setattr__(self, "source_amount", money(self.source_amount))
        for name in ("source_reference", "original_description", "account_label", "import_source"):
            object.__setattr__(self, name, _text(getattr(self, name), name.replace("_", " ").title()))
        if self.transaction_type not in {
            "income", "expense", "refund", "transfer", "debt_payment", "savings", "adjustment"
        }:
            raise FinanceValidationError("Candidate transaction type is invalid.")
        if self.amount == 0:
            raise FinanceValidationError("Candidate transaction amount cannot be zero.")
        if self.source_transaction_id is not None:
            object.__setattr__(self, "source_transaction_id", _text(self.source_transaction_id, "Source transaction ID", optional=True) or None)
        object.__setattr__(self, "source_sign_convention", _text(self.source_sign_convention, "Source sign convention", optional=True))
        if self.duplicate_state not in {"none", "definite", "possible"}:
            raise FinanceValidationError("Duplicate state is invalid.")


@dataclass(frozen=True, slots=True)
class ImportPreview:
    identifier: str
    source_path: Path
    source_digest: str
    candidate_digest: str
    workbook_revision: str
    account_label: str
    candidates: tuple[CandidateTransaction, ...]
    warnings: tuple[str, ...] = ()

    @property
    def included(self) -> tuple[CandidateTransaction, ...]:
        return tuple(item for item in self.candidates if item.included and item.duplicate_state != "definite")


@dataclass(frozen=True, slots=True)
class FinanceMutation:
    operation: str
    expected_revision: str | None
    snapshot: FinanceSnapshot | None
    presentation: str
    import_preview: ImportPreview | None = None
    reviewed_merchant_rules: tuple[MerchantRule, ...] = ()

    def document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "operation": self.operation,
            "review": self.presentation,
        }
        if self.import_preview is not None:
            document["import"] = {
                "filename": self.import_preview.source_path.name,
                "account_label": self.import_preview.account_label,
                "source_digest": self.import_preview.source_digest,
                "candidate_digest": self.import_preview.candidate_digest,
                "workbook_revision": self.import_preview.workbook_revision,
                "included_transactions": len(self.import_preview.included),
                "excluded_definite_duplicates": sum(
                    item.duplicate_state == "definite"
                    for item in self.import_preview.candidates
                ),
                "merchant_rules": [
                    {
                        "match_type": rule.match_type,
                        "match_text": rule.match_text,
                        "normalized_merchant": rule.normalized_merchant,
                        "category": rule.category,
                        "account_scope": rule.account_scope,
                    }
                    for rule in self.reviewed_merchant_rules
                ],
            }
        return document


class FinanceRepository(Protocol):
    @property
    def workbook_path(self) -> Path: ...
    def exists(self) -> bool: ...
    def revision(self) -> str | None: ...
    def read(self) -> FinanceSnapshot: ...
    def create(self, *, currency: str, expected_revision: str | None = None) -> FinanceSnapshot: ...
    def replace(self, snapshot: FinanceSnapshot, *, expected_revision: str) -> FinanceSnapshot: ...


Record = TypeVar("Record")
