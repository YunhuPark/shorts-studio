import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra" / "budget_cutoff"))
import cutoff


def event(payload) -> dict:
    return {"message": {"data": base64.b64encode(json.dumps(payload).encode()).decode()}}


class BudgetCutoffTest(unittest.TestCase):
    def test_below_budget_does_not_cut(self):
        self.assertFalse(cutoff.should_cut({"costAmount": 6999.0, "budgetAmount": 7000.0}))

    def test_reaching_the_budget_cuts(self):
        self.assertTrue(cutoff.should_cut({"costAmount": 7000.0, "budgetAmount": 7000.0}))
        # numbers may arrive as strings
        self.assertTrue(cutoff.should_cut({"costAmount": "7123.4", "budgetAmount": "7000"}))

    def test_unreadable_or_odd_payloads_never_cut(self):
        odd = [
            {},
            {"costAmount": 1},
            {"costAmount": "x", "budgetAmount": 7000},
            {"costAmount": None, "budgetAmount": 7000},
            {"costAmount": 5, "budgetAmount": 0},
            {"costAmount": 5, "budgetAmount": -1},
        ]
        for payload in odd:
            self.assertFalse(cutoff.should_cut(payload), payload)

    def test_handle_closes_exactly_when_the_budget_is_reached(self):
        closed = []
        logs = []
        below = event({"costAmount": 100, "budgetAmount": 7000})
        self.assertFalse(cutoff.handle(below, lambda: closed.append(1), logs.append))
        self.assertEqual(closed, [])
        over = event({"costAmount": 7001, "budgetAmount": 7000})
        self.assertTrue(cutoff.handle(over, lambda: closed.append(1), logs.append))
        self.assertEqual(closed, [1])
        self.assertTrue(any("closing" in line for line in logs))

    def test_a_malformed_message_raises_instead_of_silently_passing(self):
        with self.assertRaises(json.JSONDecodeError):
            cutoff.handle({"message": {"data": base64.b64encode(b"not json").decode()}}, lambda: None)
        with self.assertRaises(ValueError):
            cutoff.decode_message(event([1, 2]))


if __name__ == "__main__":
    unittest.main()
