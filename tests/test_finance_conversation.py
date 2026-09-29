from datetime import date
import unittest

from tori.finance_conversation import FinanceConversationService
from tori.finance_service import FinanceService

from finance_fixtures import FakeFinanceRepository, synthetic_snapshot


class FinanceConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conversation = FinanceConversationService(
            FinanceService(FakeFinanceRepository(synthetic_snapshot()), today=lambda: date(2026, 8, 14)),
            today=lambda: date(2026, 8, 14),
        )

    def test_acceptance_questions_are_application_owned(self) -> None:
        questions = {
            "How much did I spend on fast food this month?": "$28.00",
            "How much did I spend on Amazon?": "$105.00",
            "What are my biggest spending categories?": "largest categories",
            "What bills are due in the next seven days?": "$0.00",
            "How much should I reserve for my bills in the next seven days?": "$0.00",
            "What's my average electric bill?": "$155.00",
            "What are my current debt balances?": "$12,000.00",
            "Which debt has the highest APR?": "Citi Card",
            "If I pay an extra $200 a month toward Citi Card, what happens?": "months",
            "Can I afford a $900 guitar this month?": "outside current plan",
            "How much discretionary money do I have left?": "$652.00",
            "Am I spending more on fast food than last month?": "$28.00",
            "What changed in my spending over the last three months?": "2026-06",
        }
        for question, expected in questions.items():
            with self.subTest(question=question):
                turn = self.conversation.interpret(question)
                self.assertTrue(turn.handled)
                self.assertIsNone(turn.mutation)
                self.assertIn(expected, turn.text)

    def test_unrelated_conversation_is_not_hijacked(self) -> None:
        for message in (
            "Tell me about the weather.",
            "What do you think about Amazon as a company?",
            "Explain how debt works.",
            "Fast food is everywhere.",
        ):
            with self.subTest(message=message):
                self.assertFalse(self.conversation.interpret(message).handled)

    def test_initialization_is_proposal_only(self) -> None:
        conversation = FinanceConversationService(FinanceService(FakeFinanceRepository()))
        turn = conversation.interpret("/finance initialize")
        self.assertTrue(turn.handled)
        self.assertIsNotNone(turn.mutation)
        self.assertFalse(conversation._finance.status()["initialized"])

    def test_malformed_finance_command_is_handled_locally(self) -> None:
        turn = self.conversation.interpret("/finance import statement.csv")
        self.assertTrue(turn.handled)
        self.assertIsNone(turn.mutation)
        self.assertIn("Usage: /finance initialize", turn.text)


if __name__ == "__main__":
    unittest.main()
