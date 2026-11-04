"""Compare two renders: sampled-frame pixel difference and audio difference.

Use after refactors to show the output did not change.
Usage: python scripts/compare_renders.py old.mp4 new.mp4
"""
import subprocess
import sys

import imageio_ffmpeg
import numpy as np

FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 270, 480


def frames(path):
    raw = subprocess.run([FF, "-loglevel", "error", "-i", path, "-vf", f"fps=2,scale={W}:{H},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (W * H)
    return np.frombuffer(raw[: n * W * H], np.uint8).reshape(n, H, W).astype(np.float64)


def audio(path):
    raw = subprocess.run([FF, "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, "<i2").astype(np.float64) / 32768


def duration(path):
    out = subprocess.run([FF, "-i", path], capture_output=True, text=True).stderr
    h, m, s = out.split("Duration:")[1].split(",")[0].strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main(a, b):
    fa, fb = frames(a), frames(b)
    n = min(len(fa), len(fb))
    diffs = np.abs(fa[:n] - fb[:n]).mean(axis=(1, 2))
    xa, xb = audio(a), audio(b)
    m = min(len(xa), len(xb))

    def rms(x):
        return float(np.sqrt((x ** 2).mean()))

    corr = float(np.corrcoef(xa[:m], xb[:m])[0, 1]) if m else float("nan")
    print(f"duration: {duration(a):.3f}s vs {duration(b):.3f}s")
    print(f"frames compared: {n} (2 per second); mean abs pixel diff = {diffs.mean():.4f}, "
          f"max = {diffs.max():.4f} (0-255 scale)")
    print(f"audio: rms {rms(xa):.4f} vs {rms(xb):.4f}; correlation = {corr:.5f}; "
          f"rms of difference = {rms(xa[:m] - xb[:m]):.5f}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
