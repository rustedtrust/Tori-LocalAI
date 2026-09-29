from datetime import date
from decimal import Decimal
import unittest

from tori.finance import Budget, Debt, FinanceValidationError, money
from tori.finance_service import FinanceService

from finance_fixtures import FakeFinanceRepository, synthetic_snapshot


class FinanceDomainTests(unittest.TestCase):
    def test_money_is_exact_and_rejects_float(self) -> None:
        self.assertEqual(money("10.005"), Decimal("10.01"))
        with self.assertRaises(FinanceValidationError):
            money(1.1)

    def test_budget_validates_month_and_nonnegative_targets(self) -> None:
        with self.assertRaises(FinanceValidationError):
            Budget("2026-13", Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))


class FinanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeFinanceRepository(synthetic_snapshot())
        self.service = FinanceService(self.repository, today=lambda: date(2026, 8, 14))

    def test_spending_separates_refunds_transfers_debt_and_savings(self) -> None:
        result = self.service.spending_summary(date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(dict(result.categories)["Dining / Fast Food"], Decimal("28.00"))
        self.assertEqual(dict(result.categories)["Amazon"], Decimal("105.00"))
        self.assertEqual(result.debt_payments, Decimal("100.00"))
        self.assertEqual(result.transfers, Decimal("-200.00"))
        self.assertEqual(result.total, Decimal("523.00"))

    def test_three_month_trend_is_deterministic(self) -> None:
        trend = self.service.monthly_trend("2026-08")
        self.assertEqual([month for month, _ in trend.months], ["2026-06", "2026-07", "2026-08"])
        self.assertEqual(trend.current_vs_previous, Decimal("398.00"))

    def test_upcoming_bills_excludes_linked_paid_occurrence(self) -> None:
        result = self.service.upcoming_bills(date(2026, 8, 14), days=7)
        self.assertEqual(result.bills, ())
        future = self.service.upcoming_bills(date(2026, 9, 14), days=7)
        self.assertEqual(future.total, Decimal("244.00"))

    def test_debt_summary_orders_apr_and_reports_dates(self) -> None:
        result = self.service.debt_summary()
        self.assertEqual(result.total_balance, Decimal("12000.00"))
        self.assertEqual(result.highest_apr.name, "Citi Card")
        self.assertEqual(result.debts[0].name, "Citi Card")

    def test_stale_balance_and_non_amortizing_payment_warn(self) -> None:
        self.service = FinanceService(self.repository, today=lambda: date(2026, 9, 15))
        summary = self.service.debt_summary()
        self.assertTrue(summary.warnings)
        debt = self.repository.snapshot.debts[0]
        from dataclasses import replace
        self.repository.snapshot = replace(
            self.repository.snapshot,
            debts=(replace(debt, target_payment=debt.minimum_payment, apr=Decimal("999")), self.repository.snapshot.debts[1]),
        )
        scenario = self.service.payoff_scenario("Citi Card")
        self.assertIsNone(scenario.comparison)
        self.assertTrue(any("bounded payoff" in warning for warning in scenario.warnings))

    def test_unlinked_possible_bill_payment_is_not_silently_assumed(self) -> None:
        from dataclasses import replace
        snapshot = self.repository.snapshot
        unlinked = replace(snapshot.transactions[9], related_bill_id=None)
        self.repository.snapshot = replace(snapshot, transactions=snapshot.transactions[:9] + (unlinked,) + snapshot.transactions[10:])
        result = self.service.upcoming_bills(date(2026, 8, 14), days=7)
        self.assertEqual(result.total, Decimal("159.00"))
        self.assertIn("possible unlinked Electric", result.warnings[0])

    def test_affordability_uses_both_budget_and_cash_capacity(self) -> None:
        result = self.service.affordability("900", "2026-08")
        self.assertEqual(result.status, "outside current plan")
        self.assertEqual(result.discretionary_remaining, Decimal("652.00"))
        self.assertEqual(result.conservative_capacity, Decimal("652.00"))

    def test_affordability_fails_closed_without_starting_funds(self) -> None:
        snapshot = synthetic_snapshot()
        budget = snapshot.budgets[0]
        self.repository.snapshot = snapshot.__class__(
            snapshot.revision, snapshot.currency, snapshot.transactions, snapshot.merchant_rules,
            snapshot.bills, snapshot.debts,
            (Budget(budget.month, budget.expected_income, budget.essential_spending_target,
                    budget.discretionary_target, budget.savings_target,
                    budget.extra_debt_payment_target, budget.reserve_buffer),), snapshot.goals,
        )
        result = self.service.affordability("800", "2026-08")
        self.assertEqual(result.status, "insufficient data")
        self.assertIn("Starting available funds", result.warnings[0])

    def test_payoff_extra_payment_saves_time_and_interest(self) -> None:
        result = self.service.payoff_scenario("Citi Card", extra_payment="200")
        self.assertIsNotNone(result.baseline)
        self.assertIsNotNone(result.comparison)
        self.assertEqual(result.comparison.months, 10)
        self.assertEqual(result.comparison.total_interest, Decimal("339.80"))
        self.assertEqual(result.months_saved, 17)
        self.assertEqual(result.interest_saved, Decimal("580.89"))

    def test_payoff_resolves_unique_case_insensitive_friendly_debt_name(self) -> None:
        exact = self.service.payoff_scenario("Citi Card", extra_payment="200")
        shorthand = self.service.payoff_scenario("Citi", extra_payment="200")
        mixed_case = self.service.payoff_scenario("cItI", extra_payment="200")
        self.assertEqual(shorthand, exact)
        self.assertEqual(mixed_case, exact)

    def test_payoff_rejects_ambiguous_or_unknown_friendly_debt_names(self) -> None:
        from dataclasses import replace

        snapshot = self.repository.snapshot
        citi_loan = Debt(
            "debt-citi-loan", "Citi Loan", "loan", Decimal("4000"),
            Decimal("8.50"), Decimal("120"), Decimal("120"),
            date(2026, 8, 24), 3, date(2026, 8, 1),
        )
        self.repository.snapshot = replace(snapshot, debts=(*snapshot.debts, citi_loan))
        with self.assertRaisesRegex(FinanceValidationError, "More than one active debt matches.*Citi Card, Citi Loan"):
            self.service.payoff_scenario("Citi", extra_payment="200")
        with self.assertRaisesRegex(FinanceValidationError, "not recorded"):
            self.service.payoff_scenario("Not A Debt", extra_payment="200")

    def test_goal_progress_derives_debt_goal(self) -> None:
        progress = {item.name: item for item in self.service.goal_progress()}
        self.assertEqual(progress["New Guitar"].current_amount, Decimal("300.00"))
        self.assertEqual(progress["Pay Off Citi"].current_amount, Decimal("2000.00"))

    def test_summary_is_a_rebuildable_projection_not_duplicate_source_data(self) -> None:
        rows = dict(self.service.summary_projection(as_of=date(2026, 8, 14)))
        self.assertEqual(rows["Month-to-date Consumption Spending"], "523.00")
        self.assertEqual(rows["Active Debt Total"], "12000.00")
        self.assertIn("Citi Card", rows["Highest APR Debt"])

    def test_mutation_is_revision_bound(self) -> None:
        proposal = self.service.upsert(self.repository.snapshot.bills[0])
        self.repository.snapshot = self.repository.snapshot.with_revision("rev-9")
        with self.assertRaisesRegex(Exception, "changed"):
            self.service.apply(proposal)


if __name__ == "__main__":
    unittest.main()
