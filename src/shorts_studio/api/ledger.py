"""Per-user spend ledger on SQLite: reserve before a paid call, refund if nothing was produced.

Amounts are estimates from the configured unit price, not the provider's invoice. They are stored as integer
micro-dollars so repeated sums never drift.

`reserve` checks the user's daily cap (and an optional all-users monthly budget) and records the reservation in
ONE write transaction, so quick repeated clicks, several API threads or separate worker processes can never
overshoot a cap. `refund` is idempotent: a reservation is given back at most once, however many code paths
(failed job, crashed worker recovery) try.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

MICRO = 1_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    day TEXT NOT NULL,
    owner TEXT NOT NULL,
    project TEXT NOT NULL,
    shot INTEGER NOT NULL,
    micro INTEGER NOT NULL,
    kind TEXT NOT NULL,          -- reserve | refund | legacy
    ref INTEGER                  -- for a refund: the reservation it gives back
);
CREATE UNIQUE INDEX IF NOT EXISTS one_refund_per_reservation ON entries (ref) WHERE kind = 'refund' AND ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS entries_owner_day ON entries (owner, day);
"""


def micro(usd: float) -> int:
    return round(usd * MICRO)


@dataclass
class Reservation:
    id: int | None            # None when denied
    reason: str | None = None  # "daily" | "monthly" when denied
    spent_today_usd: float = 0.0


class CreditLedger:
    def __init__(self, path: str | Path, legacy_jsonl: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
        if legacy_jsonl:
            self._import_legacy(Path(legacy_jsonl))

    @contextlib.contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def _tx(self):
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    def _import_legacy(self, path: Path) -> None:
        """Fold the old single-user spend.jsonl into the 'local' owner, once."""
        if not path.exists():
            return
        with self._tx() as c:
            if c.execute("SELECT 1 FROM entries LIMIT 1").fetchone():
                return
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    c.execute("INSERT INTO entries (ts, day, owner, project, shot, micro, kind) "
                              "VALUES (?, ?, 'local', ?, ?, ?, 'legacy')",
                              (float(row["ts"]), str(row["day"]), str(row["project"]), int(row["shot"]),
                               micro(float(row["usd"]))))
                except (ValueError, KeyError, TypeError):
                    continue

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def reserve(self, owner: str, project: str, shot: int, usd: float, daily_cap_usd: float,
                monthly_cap_usd: float = 0.0, global_daily_cap_usd: float = 0.0) -> Reservation:
        """Atomically check the caps and record the reservation. monthly_cap_usd 0 = no monthly budget."""
        day, cost = self._today(), micro(usd)
        with self._tx() as c:
            today = c.execute("SELECT COALESCE(SUM(micro), 0) FROM entries WHERE owner=? AND day=?",
                              (owner, day)).fetchone()[0]
            if today + cost > micro(daily_cap_usd):
                return Reservation(None, "daily", today / MICRO)
            if global_daily_cap_usd > 0:
                global_today = c.execute("SELECT COALESCE(SUM(micro), 0) FROM entries WHERE day=?",
                                         (day,)).fetchone()[0]
                if global_today + cost > micro(global_daily_cap_usd):
                    return Reservation(None, "global daily", today / MICRO)
            if monthly_cap_usd > 0:
                month = c.execute("SELECT COALESCE(SUM(micro), 0) FROM entries WHERE day LIKE ?",
                                  (day[:7] + "-%",)).fetchone()[0]
                if month + cost > micro(monthly_cap_usd):
                    return Reservation(None, "monthly", today / MICRO)
            cur = c.execute("INSERT INTO entries (ts, day, owner, project, shot, micro, kind) "
                            "VALUES (?, ?, ?, ?, ?, ?, 'reserve')", (time.time(), day, owner, project, shot, cost))
            return Reservation(cur.lastrowid, None, (today + cost) / MICRO)

    def refund(self, reservation_id: int | None) -> bool:
        """Give a reservation back. True only the first time; later calls (or an unknown id) change nothing."""
        if reservation_id is None:
            return False
        with self._tx() as c:
            row = c.execute("SELECT day, owner, project, shot, micro FROM entries WHERE id=? AND kind='reserve'",
                            (reservation_id,)).fetchone()
            if row is None or c.execute("SELECT 1 FROM entries WHERE kind='refund' AND ref=?",
                                        (reservation_id,)).fetchone():
                return False
            day, owner, project, shot, cost = row   # booked on the reservation's day so that day nets to zero
            c.execute("INSERT INTO entries (ts, day, owner, project, shot, micro, kind, ref) "
                      "VALUES (?, ?, ?, ?, ?, ?, 'refund', ?)",
                      (time.time(), day, owner, project, shot, -cost, reservation_id))
            return True

    def today_total(self, owner: str) -> float:
        with self._conn() as c:
            total = c.execute("SELECT COALESCE(SUM(micro), 0) FROM entries WHERE owner=? AND day=?",
                              (owner, self._today())).fetchone()[0]
        return round(total / MICRO, 4)

    def month_total(self) -> float:
        with self._conn() as c:
            total = c.execute("SELECT COALESCE(SUM(micro), 0) FROM entries WHERE day LIKE ?",
                              (self._today()[:7] + "-%",)).fetchone()[0]
        return round(total / MICRO, 4)
