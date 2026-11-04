"""Audio mix: voices -> ducked score, rain bed, door chime -> one wav."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .proc import run


def run_ffmpeg(cmd: list[str]) -> None:
    p = run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError("ffmpeg failed:\n" + p.stderr[-1500:])


def build_audio(ffmpeg: str, items: list[tuple[float, Path]], total: float, chime_at: float | None,
                bgm_wav: Path, out_wav: Path) -> None:
    """items: (start_seconds, wav). Voices drive a sidechain that ducks the score."""
    cmd = [ffmpeg, "-y"]
    for _, p in items:
        cmd += ["-i", str(p)]
    k = len(items)
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=pink:amplitude=0.6:sample_rate=44100",
            "-f", "lavfi", "-t", "1.2", "-i", "sine=frequency=1568:sample_rate=44100",
            "-f", "lavfi", "-t", "1.2", "-i", "sine=frequency=1175:sample_rate=44100",
            "-i", str(bgm_wav)]
    st = "aformat=channel_layouts=stereo"
    parts, vl = [], []
    for i, (start, _) in enumerate(items):
        parts.append(f"[{i}:a]aresample=44100,adelay={int(start * 1000)}:all=1,{st}[a{i}]")
        vl.append(f"[a{i}]")
    parts.append(f"{''.join(vl)}amix=inputs={k}:normalize=0:duration=longest[vsum]")
    parts.append("[vsum]asplit=2[vm1][vm2]")
    parts.append(f"[{k}:a]highpass=f=600,lowpass=f=6500,volume=0.05,afade=t=in:d=1.5,"
                 f"afade=t=out:st={max(total - 2.5, 0):.2f}:d=2.5,{st}[rain]")
    parts.append(f"[{k + 3}:a]aresample=44100,volume=0.30,{st}[bgm0]")
    parts.append("[bgm0][vm2]sidechaincompress=threshold=0.015:ratio=4:attack=40:release=600[bgmd]")
    labels = ["[vm1]", "[rain]", "[bgmd]"]
    if chime_at is not None:
        for j, (fq, vol, extra) in enumerate(((k + 1, 0.10, 0.0), (k + 2, 0.08, 0.28))):
            parts.append(f"[{fq}:a]afade=t=out:st=0.05:d=1.0,volume={vol},"
                         f"adelay={int((chime_at + extra) * 1000)}:all=1,{st}[ch{j}]")
            labels.append(f"[ch{j}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                 f"loudnorm=I=-16:TP=-1.5:LRA=11[out]")
    run_ffmpeg([*cmd, "-filter_complex", ";".join(parts), "-map", "[out]", "-ar", "44100", str(out_wav)])
