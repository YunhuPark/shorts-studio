"""Procedural ambient piano + pad score (A minor, Am-F-C-G): slow and sparse for a quiet night story.

compose(total_seconds, out_wav) writes a 44.1 kHz stereo 16-bit wav that swells toward ~65% of the
length and fades out at the end. Deterministic (fixed seed), so no third-party music licence is involved.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 54
BEAT = 60.0 / BPM
BAR = 4 * BEAT

# chord: bass midi, arpeggio midis, melody [(beat offset, midi, beats)]
CHORDS = [
    (45, [57, 60, 64, 69], [(0, 76, 2), (2, 74, 1), (3, 72, 1)]),  # Am
    (41, [53, 57, 60, 65], [(0, 72, 2), (2, 69, 2)]),              # F
    (48, [60, 64, 67, 72], [(0, 76, 2), (2, 72, 2)]),              # C
    (43, [59, 62, 67, 71], [(0, 74, 2), (2, 71, 1), (3, 74, 1)]),  # G
]
ARP = [0, 1, 2, 3, 2, 1, 2, 1]


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def piano(f: float, ring: float, vel: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(int(SR * ring)) / SR
    sig = np.zeros_like(t)
    decay = (220.0 / f) ** 0.3
    for k in range(1, 9):
        fk = f * k * np.sqrt(1 + 0.0003 * k * k)
        if fk > SR / 2.6:
            break
        tau = 2.8 / (1 + 0.9 * (k - 1)) * decay
        amp = 1.0 / k ** 1.1
        for det, w in ((1.0, 1.0), (1.0015, 0.5)):
            sig += w * amp * np.sin(2 * np.pi * fk * det * t + rng.uniform(0, 6.28)) * np.exp(-t / tau)
    sig *= np.minimum(1.0, t / 0.005)
    n = int(SR * 0.008)
    sig[:n] += rng.standard_normal(n) * np.hanning(n) * 0.05  # hammer noise
    return sig * vel


def pad(freqs: list[float], length: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(int(SR * length)) / SR
    sig = np.zeros_like(t)
    for f in freqs:
        for det in (0.996, 1.004):
            sig += np.sin(2 * np.pi * f * det * t + rng.uniform(0, 6.28))
    return sig * np.minimum(1.0, t / 1.6) * np.minimum(1.0, (length - t) / 1.6) * 0.05


def reverb(x: np.ndarray, rng: np.random.Generator, wet: float = 0.45) -> np.ndarray:
    n = int(SR * 2.6)
    t = np.arange(n) / SR
    out = []
    for _ in range(2):
        ir = rng.standard_normal(n) * np.exp(-t / 0.75)
        k = 24  # soften highs
        ir = np.convolve(ir, np.ones(k) / k, mode="same")
        ir /= np.sqrt((ir ** 2).sum()) + 1e-9
        size = 1 << int(np.ceil(np.log2(len(x) + n)))
        y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
        out.append(x * (1 - wet) + y * wet)
    return np.stack(out, axis=1)


def compose(total: float, out_wav: str | Path) -> None:
    rng = np.random.default_rng(7)
    bars = int(np.ceil(total / BAR)) + 1
    length = int((bars * BAR + 5) * SR)
    mono = np.zeros(length)

    def put(sig: np.ndarray, at: float) -> None:
        i = max(int(at * SR), 0)
        j = min(i + len(sig), length)
        if i < length:
            mono[i:j] += sig[: j - i]

    for b in range(bars):
        bass, arp, mel = CHORDS[b % 4]
        t0 = b * BAR
        put(piano(hz(bass), 5.0, 0.55, rng), t0 + rng.uniform(0, 0.015))
        for i, idx in enumerate(ARP):
            at = t0 + i * BEAT / 2 + rng.uniform(-0.012, 0.012)
            put(piano(hz(arp[idx]), 3.5, 0.20 * rng.uniform(0.85, 1.1), rng), at)
        if b >= 1:  # let the opening bar breathe
            for off, m, _beats in mel:
                put(piano(hz(m), 4.5, 0.38 * rng.uniform(0.9, 1.1), rng), t0 + off * BEAT + rng.uniform(0, 0.02))
        put(pad([hz(bass + 12)] + [hz(m - 12) for m in arp[:3]], BAR + 2.0, rng), t0 - 0.5 if b else t0)

    t = np.arange(length) / SR
    swell = 0.55 + 0.45 * np.exp(-((t - 0.65 * total) / (0.28 * total)) ** 2)
    mono *= swell * np.minimum(1.0, t / 3.0) * np.clip((total + 2.0 - t) / 4.0, 0.0, 1.0)
    stereo = reverb(mono, rng)[: int((total + 2.0) * SR)]
    stereo *= 0.9 / (np.abs(stereo).max() + 1e-9)
    pcm = (stereo * 32767).astype("<i2")
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
