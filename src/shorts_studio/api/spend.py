"""Estimated paid-API spend, recorded per call so a daily cap can stop runaway generation.

Amounts are estimates from the configured unit price, not the provider's invoice."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class SpendLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, project: str, shot: int, usd: float, kind: str = "image") -> None:
        row = {"ts": time.time(), "day": time.strftime("%Y-%m-%d"), "project": project, "shot": shot,
               "usd": usd, "kind": kind}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")

    def today_total(self) -> float:
        if not self.path.exists():
            return 0.0
        today = time.strftime("%Y-%m-%d")
        total = 0.0
        with self._lock, open(self.path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("day") == today:
                    total += float(row.get("usd", 0))
        return round(total, 4)
