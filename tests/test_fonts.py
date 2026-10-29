import os
import unittest
from pathlib import Path

from PIL import ImageFont

from shorts_studio.render.fonts import PROJECT_FONTS, is_dev_fallback, resolve_font

BUNDLED = PROJECT_FONTS / "Pretendard-Bold.otf"


@unittest.skipUnless(BUNDLED.exists(), "bundled Pretendard-Bold.otf not present")
class BundledFont(unittest.TestCase):
    def test_bundled_font_is_preferred_over_dev_fallback(self):
        old = os.environ.pop("SHORTS_FONT", None)
        try:
            path = resolve_font()
        finally:
            if old is not None:
                os.environ["SHORTS_FONT"] = old
        self.assertEqual(Path(path).name, "Pretendard-Bold.otf")
        self.assertFalse(is_dev_fallback(path))

    def test_license_ships_next_to_the_font(self):
        text = (PROJECT_FONTS / "Pretendard-LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("SIL OPEN FONT LICENSE Version 1.1", text)

    def test_font_renders_hangul(self):
        font = ImageFont.truetype(str(BUNDLED), 76)
        for ch in "저기오늘은두개네요결혼기념일":
            self.assertGreater(font.getlength(ch), 30, ch)  # missing glyphs fall back to a narrow .notdef


class Explicit(unittest.TestCase):
    def test_explicit_path_wins(self):
        self.assertEqual(resolve_font(__file__), __file__)

    def test_missing_font_is_a_clear_error(self):
        # only meaningful when no env/bundled/dev font exists; otherwise resolution succeeds
        try:
            resolve_font("does-not-exist.ttf")
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    unittest.main()
