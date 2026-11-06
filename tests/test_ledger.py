import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from shorts_studio.api.ledger import CreditLedger

SRC = str(Path(__file__).resolve().parents[1] / "src")


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = CreditLedger(self.path)

    def sql(self, statement, *args):
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:
            return c.execute(statement, args).fetchall()


class Reserving(LedgerCase):
    def test_reserve_until_the_daily_cap_then_deny(self):
        results = [self.ledger.reserve("alice", "demo", 1, 0.05, daily_cap_usd=0.12) for _ in range(3)]
        self.assertEqual([r.id is not None for r in results], [True, True, False])
        self.assertEqual((results[2].reason, results[2].spent_today_usd), ("daily", 0.10))
        self.assertEqual(self.ledger.today_total("alice"), 0.10)

    def test_the_cap_is_exact_not_off_by_a_rounding_error(self):
        # 0.1 + 0.2 style float drift must not deny a spend that fits exactly, nor allow one that does not
        ok = [self.ledger.reserve("a", "p", 1, 0.067, daily_cap_usd=0.201) for _ in range(3)]
        self.assertTrue(all(r.id for r in ok))
        self.assertIsNone(self.ledger.reserve("a", "p", 1, 0.067, daily_cap_usd=0.201).id)
        self.assertEqual(self.ledger.today_total("a"), 0.201)

    def test_each_user_has_their_own_daily_cap(self):
        self.assertTrue(self.ledger.reserve("alice", "p", 1, 0.10, 0.10).id)
        self.assertIsNone(self.ledger.reserve("alice", "p", 1, 0.01, 0.10).id)
        self.assertTrue(self.ledger.reserve("bob", "p", 1, 0.10, 0.10).id)
        self.assertEqual((self.ledger.today_total("alice"), self.ledger.today_total("bob")), (0.10, 0.10))

    def test_monthly_budget_is_shared_by_everyone_and_zero_means_off(self):
        self.assertTrue(self.ledger.reserve("alice", "p", 1, 0.05, 1.0, monthly_cap_usd=0.08).id)
        denied = self.ledger.reserve("bob", "p", 1, 0.05, 1.0, monthly_cap_usd=0.08)
        self.assertEqual((denied.id, denied.reason), (None, "monthly"))
        self.assertTrue(self.ledger.reserve("bob", "p", 1, 0.05, 1.0, monthly_cap_usd=0).id)   # 0 = no monthly budget
        self.assertEqual(self.ledger.month_total(), 0.10)

    def test_many_small_amounts_add_up_exactly(self):
        for _ in range(100):
            self.assertTrue(self.ledger.reserve("a", "p", 1, 0.067, daily_cap_usd=100).id)
        self.assertEqual(self.ledger.today_total("a"), 6.7)


class Refunding(LedgerCase):
    def test_refund_gives_the_money_back_exactly_once(self):
        res = self.ledger.reserve("alice", "demo", 3, 0.05, 1.0)
        self.assertTrue(self.ledger.refund(res.id))
        self.assertFalse(self.ledger.refund(res.id))     # a second path (e.g. crash recovery) changes nothing
        self.assertEqual(self.ledger.today_total("alice"), 0.0)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM entries WHERE kind='refund'"), [(1,)])

    def test_refund_ignores_missing_or_foreign_ids(self):
        self.assertFalse(self.ledger.refund(None))
        self.assertFalse(self.ledger.refund(9999))
        res = self.ledger.reserve("alice", "demo", 1, 0.05, 1.0)
        self.assertFalse(self.ledger.refund(res.id + 1))
        self.assertEqual(self.ledger.today_total("alice"), 0.05)

    def test_a_refunded_amount_can_be_spent_again(self):
        first = self.ledger.reserve("a", "p", 1, 0.10, 0.10)
        self.assertIsNone(self.ledger.reserve("a", "p", 1, 0.10, 0.10).id)
        self.ledger.refund(first.id)
        self.assertTrue(self.ledger.reserve("a", "p", 1, 0.10, 0.10).id)

    def test_a_refund_is_booked_on_the_day_of_the_reservation(self):
        res = self.ledger.reserve("a", "p", 1, 0.05, 1.0)
        self.sql("UPDATE entries SET day='2020-01-01' WHERE id=?", res.id)   # pretend it was reserved long ago
        self.assertEqual(self.ledger.today_total("a"), 0.0)
        self.assertTrue(self.ledger.refund(res.id))
        self.assertEqual(self.ledger.today_total("a"), 0.0)                    # today is not pushed negative
        self.assertEqual(self.sql("SELECT SUM(micro) FROM entries WHERE day='2020-01-01'"), [(0,)])


class Concurrency(LedgerCase):
    def test_threads_can_never_overshoot_the_cap(self):
        wins, lock = [], threading.Lock()
        barrier = threading.Barrier(12)

        def attempt():
            barrier.wait()
            r = self.ledger.reserve("a", "p", 1, 0.05, daily_cap_usd=0.30)
            with lock:
                wins.append(r.id is not None)

        threads = [threading.Thread(target=attempt) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(wins), 6)
        self.assertEqual(self.ledger.today_total("a"), 0.30)

    def test_separate_processes_can_never_overshoot_the_cap(self):
        code = (
            "import sys\n"
            "from shorts_studio.api.ledger import CreditLedger\n"
            "ledger = CreditLedger(sys.argv[1])\n"
            "print(sum(1 for _ in range(10) if ledger.reserve('a', 'p', 1, 0.05, daily_cap_usd=0.30).id))\n"
        )
        env = {**os.environ, "PYTHONPATH": SRC}
        procs = [subprocess.Popen([sys.executable, "-c", code, str(self.path)], env=env, stdout=subprocess.PIPE,
                                  text=True) for _ in range(3)]
        wins = sum(int(p.communicate(timeout=120)[0]) for p in procs)
        self.assertEqual(wins, 6)
        self.assertEqual(self.ledger.today_total("a"), 0.30)

    def test_concurrent_refunds_of_one_reservation_count_once(self):
        res = self.ledger.reserve("a", "p", 1, 0.05, 1.0)
        results, lock = [], threading.Lock()

        def go():
            r = self.ledger.refund(res.id)
            with lock:
                results.append(r)

        threads = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.ledger.today_total("a"), 0.0)


class LegacyImport(unittest.TestCase):
    def test_old_single_user_spend_file_becomes_the_local_owners_history_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "spend.jsonl"
            today = time.strftime("%Y-%m-%d")
            rows = [{"ts": time.time(), "day": today, "project": "demo", "shot": 1, "usd": 0.067, "kind": "reserve"},
                    {"ts": time.time(), "day": today, "project": "demo", "shot": 1, "usd": -0.067, "kind": "refund"},
                    {"ts": time.time(), "day": today, "project": "demo", "shot": 2, "usd": 0.067, "kind": "reserve"},
                    {"ts": 1.0, "day": "2020-01-01", "project": "demo", "shot": 3, "usd": 9.0, "kind": "reserve"}]
            legacy.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            first = CreditLedger(Path(tmp) / "l.sqlite3", legacy_jsonl=legacy)
            self.assertEqual(first.today_total("local"), 0.067)
            self.assertEqual(first.today_total("someone-else"), 0.0)
            again = CreditLedger(Path(tmp) / "l.sqlite3", legacy_jsonl=legacy)     # restart: no double counting
            self.assertEqual(again.today_total("local"), 0.067)
            del first, again


if __name__ == "__main__":
    unittest.main()
