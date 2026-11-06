import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

from shorts_studio.render.fonts import resolve_font
from shorts_studio.render.label import (
    LABEL_X,
    LABEL_Y,
    METADATA_COMMENT,
    final_encode_args,
    make_label_png,
)

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


class Arguments(unittest.TestCase):
    def test_without_a_label_the_final_command_is_exactly_the_original(self):
        # this is the command the renderer ran before labels existed; the default output must not change
        original = ["ff", "-y", "-i", "v.mp4", "-i", "a.wav", "-c:v", "libx264", "-crf", "22", "-preset", "medium",
                    "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "out.mp4"]
        self.assertEqual(final_encode_args("ff", Path("v.mp4"), Path("a.wav"), Path("out.mp4"), None), original)

    def test_with_a_label_it_overlays_the_image_and_writes_metadata(self):
        args = final_encode_args("ff", Path("v.mp4"), Path("a.wav"), Path("out.mp4"), Path("label.png"))
        self.assertIn(f"[0:v][2:v]overlay={LABEL_X}:{LABEL_Y}[v]", args)
        self.assertEqual(args[args.index("-map") + 1], "[v]")
        self.assertIn(f"comment={METADATA_COMMENT}", args)
        self.assertEqual(args[-1], "out.mp4")


class Badge(unittest.TestCase):
    def test_the_badge_is_a_small_rounded_translucent_pill_with_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = make_label_png("AI 생성", resolve_font(), Path(tmp) / "label.png")
            img = Image.open(png).convert("RGBA")
            a = np.asarray(img)
            self.assertLess(img.width, 400)
            self.assertLess(img.height, 120)
            self.assertEqual(a[0, 0, 3], 0)                       # rounded: the corner is transparent
            self.assertGreater(a[img.height // 2, 3, 3], 100)     # the pill body is visible
            self.assertGreater(((a[..., :3] > 240).all(axis=2) & (a[..., 3] > 240)).sum(), 80)   # white glyph pixels
            del img


class RealFfmpeg(unittest.TestCase):
    """Encode a tiny clip with and without the label using the real ffmpeg and look at the result."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.video = d / "v.mp4"
        cls.audio = d / "a.wav"
        out = run([FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=0x305070:s=540x960:d=1:r=10", "-pix_fmt", "yuv420p",
                   str(cls.video)])
        assert out.returncode == 0, out.stderr
        with wave.open(str(cls.audio), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
            w.writeframes(b"\x00\x00" * 24000)
        cls.png = make_label_png("AI 생성", resolve_font(), d / "label.png")
        cls.plain, cls.labelled = d / "plain.mp4", d / "labelled.mp4"
        for out_path, label in ((cls.plain, None), (cls.labelled, cls.png)):
            r = run(final_encode_args(FFMPEG, cls.video, cls.audio, out_path, label))
            assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def frame(self, path):
        png = Path(self.tmp.name) / f"{path.stem}.png"
        r = run([FFMPEG, "-y", "-ss", "0.5", "-i", str(path), "-frames:v", "1", str(png)])
        self.assertEqual(r.returncode, 0, r.stderr)
        with Image.open(png) as im:
            return np.asarray(im.convert("RGB")).astype(int)

    def metadata(self, path):
        return run([FFMPEG, "-i", str(path), "-f", "ffmetadata", "-"]).stdout

    def test_the_badge_is_burned_in_at_the_top_left_and_nowhere_else(self):
        plain, labelled = self.frame(self.plain), self.frame(self.labelled)
        with Image.open(self.png) as badge:
            w, h = badge.size
        inside = np.abs(plain[LABEL_Y:LABEL_Y + h, LABEL_X:LABEL_X + w] - labelled[LABEL_Y:LABEL_Y + h,
                                                                                    LABEL_X:LABEL_X + w]).mean()
        outside = np.abs(plain[LABEL_Y + h + 40:] - labelled[LABEL_Y + h + 40:]).mean()
        self.assertGreater(inside, 15)     # clearly different where the badge is
        self.assertLess(outside, 2)        # the rest of the picture is untouched (only codec noise)

    def test_the_disclosure_is_also_written_into_the_file_metadata(self):
        self.assertIn(METADATA_COMMENT, self.metadata(self.labelled))
        self.assertNotIn("AI-generated", self.metadata(self.plain))

    def test_both_outputs_keep_their_audio(self):
        for path in (self.plain, self.labelled):
            self.assertIn("Audio:", run([FFMPEG, "-i", str(path)]).stderr, path.name)


if __name__ == "__main__":
    unittest.main()
