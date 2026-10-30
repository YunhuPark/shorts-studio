"""Estimate frame-to-frame jitter of a video segment.

Per frame pair: phase-correlation shift (dx, dy) of a centre crop. Smooth camera motion gives a
smooth shift series; rounding jitter shows up as a rough series.
score = mean |second difference| of the shift series, in pixels at 270x480 (lower = smoother).
Usage: python measure_shake.py video.mp4 start_seconds [duration]
"""
import subprocess
import sys

import imageio_ffmpeg
import numpy as np

W, H = 270, 480


def frames(path, start, dur):
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-ss", str(start), "-t", str(dur), "-i", path,
           "-vf", f"scale={W}:{H},format=gray", "-r", "30", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (W * H)
    return np.frombuffer(raw[: n * W * H], np.uint8).reshape(n, H, W).astype(np.float64)


def shift(a, b):
    a, b = a[60:300, 40:230], b[60:300, 40:230]  # rows above the subtitle band (~72% of the height)
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.rfft2((a - a.mean()) * win), np.fft.rfft2((b - b.mean()) * win)
    r = fa * np.conj(fb)
    c = np.fft.irfft2(r / (np.abs(r) + 1e-9), s=a.shape)
    y, x = np.unravel_index(np.argmax(c), c.shape)

    def refine(v, n, arr):
        l, m, p = arr[(v - 1) % n], arr[v], arr[(v + 1) % n]
        d = l - 2 * m + p
        return v + (0.5 * (l - p) / d if d else 0.0)

    sy = refine(y, a.shape[0], c[:, x])
    sx = refine(x, a.shape[1], c[y, :])
    if sy > a.shape[0] / 2:
        sy -= a.shape[0]
    if sx > a.shape[1] / 2:
        sx -= a.shape[1]
    return sx, sy


def main():
    path, start = sys.argv[1], float(sys.argv[2])
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    fr = frames(path, start, dur)
    s = np.array([shift(fr[i], fr[i + 1]) for i in range(len(fr) - 1)])
    d2 = np.abs(s[2:] - 2 * s[1:-1] + s[:-2])
    print(f"{path.split(chr(92))[-1]} @ {start}s: frames={len(fr)} "
          f"jitter_score={d2.mean():.4f}px  max={d2.max():.3f}px  mean_shift={np.abs(s).mean():.3f}px/frame")


if __name__ == "__main__":
    main()
