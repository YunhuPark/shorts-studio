import multiprocessing
import tempfile
import unittest
import wave
from pathlib import Path

from shorts_studio.api.ledger import CreditLedger
from shorts_studio.api.voice_budget import BudgetedVoiceProvider, VoiceBudgetExceeded
from shorts_studio.models import VoiceSpec
from shorts_studio.providers.base import ProviderError

SPEC = VoiceSpec("azure", "ko-KR-InJoonNeural", "0%", "0%")


class SyntheticVoice:
    def __init__(self, cache):
        self.cache = Path(cache)

    def synthesize(self, text, spec):
        p = self.cache / "synthetic.wav"
        with wave.open(str(p), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * 24)
        return p


def process_speech(root, owner, start, results):
    root = Path(root)
    voice = BudgetedVoiceProvider(SyntheticVoice, root, owner, "synthetic", CreditLedger(root / "ledger.db"),
                                  1, 0, 0.1, 0.01)
    start.wait(10)
    try:
        voice.synthesize("abcdefghij", SPEC)
        results.put("ok")
    except VoiceBudgetExceeded:
        results.put("blocked")


class VoiceBudgetTests(unittest.TestCase):
    def test_cached_speech_is_not_charged_twice_and_owners_do_not_share_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = CreditLedger(root / "ledger.db")
            voice = BudgetedVoiceProvider(SyntheticVoice, root, "alice", "sample", ledger, 1, 1, 1, 0.01)
            first = voice.synthesize("hello", SPEC)
            self.assertEqual(voice.synthesize("hello", SPEC), first)
            self.assertEqual(ledger.today_total("alice"), 0.05)
            other = BudgetedVoiceProvider(SyntheticVoice, root, "bob", "render", ledger, 1, 1, 1, 0.01)
            self.assertNotEqual(first, other.synthesize("hello", SPEC))
            self.assertEqual(ledger.today_total("bob"), 0.05)

    def test_invalid_price_and_budget_fail_before_constructing_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = CreditLedger(root / "ledger.db")
            for daily, global_cap, price in ((1, 1, 0), (1, 0, .01), (-1, 1, .01),
                                              (float("nan"), 1, .01), (1, 1, float("inf"))):
                with self.assertRaises(ProviderError):
                    BudgetedVoiceProvider(SyntheticVoice, root, "alice", "test", ledger,
                                          daily, 0, global_cap, price)
            self.assertEqual(ledger.month_total(), 0)

    def test_uncertain_failure_remains_charged_and_stops_the_next_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = CreditLedger(root / "ledger.db")
            calls = []
            def failing_factory(cache):
                calls.append(cache)
                raise ProviderError("synthetic uncertain provider failure")
            voice = BudgetedVoiceProvider(failing_factory, root, "alice", "test", ledger, .05, 1, 1, .01)
            with self.assertRaises(ProviderError):
                voice.synthesize("hello", SPEC)
            with self.assertRaises(VoiceBudgetExceeded):
                voice.synthesize("world", SPEC)
            self.assertEqual(len(calls), 1)
            self.assertEqual(ledger.today_total("alice"), .05)

    def test_separate_worker_processes_cannot_exceed_global_daily_budget(self):
        with tempfile.TemporaryDirectory() as root:
            CreditLedger(Path(root) / "ledger.db")
            ctx = multiprocessing.get_context("spawn")
            start, results = ctx.Event(), ctx.Queue()
            processes = [ctx.Process(target=process_speech, args=(root, owner, start, results))
                         for owner in ("alice", "bob")]
            for process in processes:
                process.start()
            start.set()
            try:
                self.assertEqual(sorted([results.get(timeout=20) for _ in processes]), ["blocked", "ok"])
            finally:
                for process in processes:
                    process.join(10)
                    if process.is_alive():
                        process.terminate()
                        process.join()
            self.assertAlmostEqual(CreditLedger(Path(root) / "ledger.db").month_total(), 0.1)
