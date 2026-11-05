import hashlib
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from shorts_studio.render import bgm

TOTAL = 12.0
# sha1 of compose(12, ...) with the default style, recorded before styles were introduced: the original score
# must not change when presets are added.
ORIGINAL_SHA1 = "463b8f472bc41001e5c22f7f5807611226ed4dcc"


def make(style=None, total=TOTAL):
    d = Path(tempfile.mkdtemp())
    out = d / "bgm.wav"
    bgm.compose(total, out) if style is None else bgm.compose(total, out, style)
    return out


def read(path):
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 44100)
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2).astype(float) / 32768


class Styles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wavs = {name: make(name) for name in bgm.STYLES}

    def test_default_score_is_unchanged(self):
        self.assertEqual(hashlib.sha1(make().read_bytes()).hexdigest(), ORIGINAL_SHA1)
        self.assertEqual(bgm.DEFAULT_STYLE, "night_piano")

    def test_every_style_is_a_clean_stereo_wav_of_the_right_length(self):
        for name, path in self.wavs.items():
            x = read(path)
            self.assertAlmostEqual(len(x) / 44100, TOTAL + 2.0, delta=0.05, msg=name)
            self.assertLessEqual(np.abs(x).max(), 0.91, name)   # no clipping
            self.assertGreater(np.sqrt((x ** 2).mean()), 0.03, name)  # not silent

    def test_every_style_fades_out(self):
        for name, path in self.wavs.items():
            m = read(path).mean(axis=1)
            self.assertLess(np.sqrt((m[-22050:] ** 2).mean()), 0.4 * np.sqrt((m ** 2).mean()), name)

    def test_styles_are_deterministic(self):
        self.assertEqual(make("warm_major").read_bytes(), self.wavs["warm_major"].read_bytes())

    def test_styles_really_differ(self):
        digests = {name: hashlib.sha1(p.read_bytes()).hexdigest() for name, p in self.wavs.items()}
        self.assertEqual(len(set(digests.values())), len(bgm.STYLES))

    def test_tense_style_is_darker_than_the_warm_one(self):
        def centroid(path):
            m = read(path).mean(axis=1)
            spec = np.abs(np.fft.rfft(m))
            return float((spec * np.fft.rfftfreq(len(m), 1 / 44100)).sum() / spec.sum())
        self.assertLess(centroid(self.wavs["tense_low"]) + 100, centroid(self.wavs["warm_major"]))

    def test_unknown_style_is_rejected_with_the_choices(self):
        with self.assertRaises(ValueError) as cm:
            make("jazz")
        self.assertIn("night_piano", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
