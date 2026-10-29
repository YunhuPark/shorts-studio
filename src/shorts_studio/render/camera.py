"""Camera moves as pure functions of progress. Eased and evaluated per frame in floating point,
because rounding the crop to whole pixels (ffmpeg zoompan) made the picture jitter."""
from __future__ import annotations

import math


def ease(p: float) -> float:
    return p * p * (3 - 2 * p)


def camera(move: str, p: float) -> tuple[float, float, float]:
    """Return (zoom, focus_x, focus_y) at progress p in [0, 1]; focus is a fraction of the image."""
    s = ease(p)
    if move == "push_in":
        return 1.0 + 0.10 * s, 0.5, 0.5
    if move == "pull_out":
        return 1.10 - 0.10 * s, 0.5, 0.5
    if move == "pan_right":
        return 1.18, 0.43 + 0.14 * s, 0.5
    if move == "handheld":  # slow drift only; fast wobble reads as shaky
        return 1.05, 0.5 + 0.006 * math.sin(2 * math.pi * p * 0.7), 0.5 + 0.005 * math.cos(2 * math.pi * p * 0.5)
    return 1.02 + 0.015 * s, 0.5, 0.5  # static


def crop_box(zoom: float, fx: float, fy: float, sw: int, sh: int) -> tuple[float, float, float, float]:
    """(x0, y0, width, height) of the source region to show, kept inside the image."""
    cw, ch = sw / zoom, sh / zoom
    x0 = min(max(fx * sw - cw / 2, 0), sw - cw)
    y0 = min(max(fy * sh - ch / 2, 0), sh - ch)
    return x0, y0, cw, ch
