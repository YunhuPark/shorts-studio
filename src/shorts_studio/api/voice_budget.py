"""One spending boundary for API samples and queued render speech.

Conservative reservations count attempts, including uncertain provider failures.
SQLite serializes budgets across API/worker processes; cache files are scoped to
the authenticated owner and published atomically after synthesis completes.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import tempfile
from pathlib import Path

from ..providers.base import ProviderError
from .ledger import CreditLedger


class VoiceBudgetExceeded(ProviderError):
    pass


class BudgetedVoiceProvider:
    def __init__(self, factory, root: Path, owner: str, project: str, ledger: CreditLedger,
                 daily_cap: float, monthly_cap: float, global_daily_cap: float, usd_per_character: float):
        self.factory, self.owner, self.project, self.ledger = factory, owner, project, ledger
        self.cache = root / "cache" / "budgeted-tts-v1" / owner
        self.daily, self.monthly, self.global_daily = daily_cap, monthly_cap, global_daily_cap
        if (not math.isfinite(usd_per_character) or not 0 < usd_per_character <= 1
                or not all(math.isfinite(v) and v >= 0 for v in (daily_cap, monthly_cap, global_daily_cap))
                or global_daily_cap <= 0):
            raise ProviderError("TTS budgets must be configured with a positive character price and global cap")
        self.price = usd_per_character

    def synthesize(self, text, spec):
        if not isinstance(text, str) or not 0 < len(text) <= 3000:
            raise ProviderError("TTS text must be between 1 and 3000 characters")
        key = hashlib.sha256(f"{spec.provider}|{spec.voice}|{spec.rate}|{spec.pitch}|{text}".encode()).hexdigest()
        path = self.cache / f"{key}.wav"
        if path.is_file():
            return path
        cost = max(len(text) * self.price, 0.000001)
        reservation = self.ledger.reserve(self.owner, self.project, -1, cost, self.daily,
                                          self.monthly, self.global_daily)
        if reservation.id is None:
            raise VoiceBudgetExceeded(f"TTS {reservation.reason} budget reached")
        self.cache.mkdir(parents=True, exist_ok=True)
        # Separate provider scratch paths also prevent two processes writing one
        # vendor cache file concurrently. Both attempts were reserved above.
        with tempfile.TemporaryDirectory(dir=self.cache) as tmp:
            wav = self.factory(Path(tmp)).synthesize(text, spec)
            ready = Path(tmp) / "ready.wav"
            shutil.copyfile(wav, ready)
            os.replace(ready, path)
        return path
