"""Procedural ambient piano + pad scores: slow and sparse, for quiet story shorts.

compose(total_seconds, out_wav, style) writes a 44.1 kHz stereo 16-bit wav that swells toward ~65% of the
length and fades out at the end. Deterministic (fixed seed), so no third-party music licence is involved.
Styles are small presets (tempo, chords, arpeggio pattern, melody); the default "night_piano" is the original score.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 44100

# chord: bass midi, arpeggio midis, melody [(beat offset, midi, beats)]
Chord = tuple[int, list[int], list[tuple[float, int, float]]]


@dataclass(frozen=True)
class Style:
    label: str
    bpm: float
    chords: tuple[Chord, ...]
    arp: tuple[int, ...]            # indices into the chord's arpeggio notes
    arp_step: float = 0.5           # beats between arpeggio notes
    arp_vel: float = 0.20
    melody_vel: float = 0.38
    melody_every: int = 1           # a melody on every n-th bar (after the opening bar)
    pad_gain: float = 0.05


STYLES: dict[str, Style] = {
    "night_piano": Style(          # the original: A minor, Am-F-C-G, quiet and lonely
        "밤의 피아노 (쓸쓸함)", 54,
        ((45, [57, 60, 64, 69], [(0, 76, 2), (2, 74, 1), (3, 72, 1)]),   # Am
         (41, [53, 57, 60, 65], [(0, 72, 2), (2, 69, 2)]),               # F
         (48, [60, 64, 67, 72], [(0, 76, 2), (2, 72, 2)]),               # C
         (43, [59, 62, 67, 71], [(0, 74, 2), (2, 71, 1), (3, 74, 1)])),  # G
        (0, 1, 2, 3, 2, 1, 2, 1)),
    "warm_major": Style(           # C major, C-G-Am-F: gentle and hopeful, for warm or reconciling scenes
        "따뜻한 피아노 (희망)", 66,
        ((48, [60, 64, 67, 72], [(0, 76, 2), (2, 74, 2)]),               # C
         (43, [59, 62, 67, 71], [(0, 74, 2), (2, 71, 1), (3, 72, 1)]),   # G
         (45, [57, 60, 64, 69], [(0, 72, 2), (2, 76, 2)]),               # Am
         (41, [53, 57, 60, 65], [(0, 72, 2), (2, 69, 1), (3, 67, 1)])),  # F
        (0, 2, 1, 3, 2, 1, 3, 2), arp_vel=0.22, melody_vel=0.34),
    "tense_low": Style(            # D minor, Dm-Bb-Gm-A: low, slow pulse with a sparse high note, for suspense
        "낮은 긴장감 (서스펜스)", 72,
        ((38, [50, 53, 57, 62], [(0, 86, 4)]),                           # Dm
         (34, [58, 62, 65, 70], [(0, 84, 4)]),                           # Bb
         (43, [55, 58, 62, 67], [(0, 82, 4)]),                           # Gm
         (45, [57, 61, 64, 69], [(0, 85, 4)])),                          # A (major third: unresolved)
        (0, 2, 1, 2), arp_step=1.0, arp_vel=0.16, melody_vel=0.22, melody_every=2, pad_gain=0.09),
}
DEFAULT_STYLE = "night_piano"


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


def pad(freqs: list[float], length: float, rng: np.random.Generator, gain: float = 0.05) -> np.ndarray:
    t = np.arange(int(SR * length)) / SR
    sig = np.zeros_like(t)
    for f in freqs:
        for det in (0.996, 1.004):
            sig += np.sin(2 * np.pi * f * det * t + rng.uniform(0, 6.28))
    return sig * np.minimum(1.0, t / 1.6) * np.minimum(1.0, (length - t) / 1.6) * gain


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


def compose(total: float, out_wav: str | Path, style: str = DEFAULT_STYLE) -> None:
    if style not in STYLES:
        raise ValueError(f"unknown bgm style '{style}'; choose one of {sorted(STYLES)}")
    st = STYLES[style]
    beat = 60.0 / st.bpm
    bar = 4 * beat
    rng = np.random.default_rng(7)
    bars = int(np.ceil(total / bar)) + 1
    length = int((bars * bar + 5) * SR)
    mono = np.zeros(length)

    def put(sig: np.ndarray, at: float) -> None:
        i = max(int(at * SR), 0)
        j = min(i + len(sig), length)
        if i < length:
            mono[i:j] += sig[: j - i]

    for b in range(bars):
        bass, arp, mel = st.chords[b % len(st.chords)]
        t0 = b * bar
        put(piano(hz(bass), 5.0, 0.55, rng), t0 + rng.uniform(0, 0.015))
        for i, idx in enumerate(st.arp):
            at = t0 + i * st.arp_step * beat + rng.uniform(-0.012, 0.012)
            if at - t0 >= bar:
                break
            put(piano(hz(arp[idx]), 3.5, st.arp_vel * rng.uniform(0.85, 1.1), rng), at)
        if b >= 1 and b % st.melody_every == 0:  # let the opening bar breathe
            for off, m, _beats in mel:
                vel = st.melody_vel * rng.uniform(0.9, 1.1)
                put(piano(hz(m), 4.5, vel, rng), t0 + off * beat + rng.uniform(0, 0.02))
        put(pad([hz(bass + 12)] + [hz(m - 12) for m in arp[:3]], bar + 2.0, rng, st.pad_gain), t0 - 0.5 if b else t0)

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
