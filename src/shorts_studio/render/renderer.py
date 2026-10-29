"""Storyboard + images + voices -> mp4. Ported from the prototype; behaviour is meant to be identical."""
from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from ..models import Shot, Storyboard
from ..providers.base import ImageSource, VoiceProvider
from . import bgm
from .camera import camera, crop_box
from .fonts import resolve_font
from .mix import build_audio, run_ffmpeg
from .proc import popen
from .subtitles import render_phrase, split_phrases

GRADE = "eq=contrast=1.06:saturation=0.93:gamma=0.97,vignette=PI/5,noise=alls=3:allf=t"


@dataclass
class RenderOptions:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    lead: float = 0.15        # silence before a line starts
    tail: float = 0.2         # silence after it
    min_dur: float = 1.6
    font: str | None = None
    ffmpeg: str | None = None
    work_dir: Path = Path(".cache/work")


@dataclass
class ShotPlan:
    shot: Shot
    image: Path
    wav: Path | None
    voice_len: float
    dur: float


@dataclass
class RenderResult:
    path: Path
    duration: float
    shots: list[ShotPlan]
    skipped: list[int]


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def plan_shots(sb: Storyboard, images: ImageSource, voices: VoiceProvider, opts: RenderOptions,
               only: set[int] | None = None) -> tuple[list[ShotPlan], list[int]]:
    plans: list[ShotPlan] = []
    skipped: list[int] = []
    for shot in sb.shots:
        if only is not None and shot.n not in only:
            continue
        image = images.path_for(shot)
        if image is None:
            skipped.append(shot.n)
            continue
        wav = voices.synthesize(shot.text, sb.voices[shot.who]) if shot.text else None
        vlen = wav_seconds(wav) if wav else 0.0
        dur = max(opts.lead + vlen + opts.tail, shot.min_dur or opts.min_dur, opts.min_dur)
        plans.append(ShotPlan(shot, image, wav, vlen, dur))
    return plans, skipped


def render_shot(plan: ShotPlan, opts: RenderOptions, ffmpeg: str, font: str, first: bool, last: bool) -> Path:
    shot, dur = plan.shot, plan.dur
    w, h, fps = opts.width, opts.height, opts.fps
    frames = max(2, int(round(dur * fps)))
    work = Path(opts.work_dir)
    src = Image.open(plan.image).convert("RGB")
    up = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
    sw, sh = up.size

    chain = f"[0:v]{GRADE},format=yuv420p"
    if first:
        chain += ",fade=t=in:d=0.6"
    if last:
        chain += f",fade=t=out:st={dur - 0.9:.2f}:d=0.9"
    filt, last_label, pngs = chain + "[v0]", "v0", []
    if shot.text:
        phrases = split_phrases(shot.text)
        weights = [len(p.replace(" ", "")) or 1 for p in phrases]
        t = opts.lead
        for i, (p, wgt) in enumerate(zip(phrases, weights)):
            span = plan.voice_len * wgt / sum(weights)
            start, end = t, t + span + (0.2 if i == len(phrases) - 1 else 0)
            t += span
            png = work / f"sub{shot.n:02d}_{i}.png"
            render_phrase(p, shot.highlight, png, font, (w, h))
            pngs.append(png)
            filt += (f";[{last_label}][{len(pngs)}:v]overlay=0:0:"
                     f"enable='between(t,{start:.2f},{end:.2f})'[v{i + 1}]")
            last_label = f"v{i + 1}"

    cmd = [ffmpeg, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-"]
    for png in pngs:
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(png)]
    mp4 = work / f"shot{shot.n:02d}.mp4"
    cmd += ["-filter_complex", filt, "-map", f"[{last_label}]", "-c:v", "libx264", "-crf", "17",
            "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(fps), "-an", "-frames:v", str(frames), str(mp4)]
    log_path = work / "ffmpeg_shot.log"
    with open(log_path, "w") as log:
        proc = popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
        for i in range(frames):
            z, fx, fy = camera(shot.camera, i / (frames - 1))
            x0, y0, cw, ch = crop_box(z, fx, fy, sw, sh)
            frame = up.transform((w, h), Image.AFFINE, (cw / w, 0, x0, 0, ch / h, y0), resample=Image.BICUBIC)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        code = proc.wait()
    if code:
        raise RuntimeError(f"ffmpeg failed for shot {shot.n}:\n{log_path.read_text()[-1500:]}")
    return mp4


def render(sb: Storyboard, images: ImageSource, voices: VoiceProvider, out_path: str | Path,
           opts: RenderOptions | None = None, only: set[int] | None = None,
           log: Callable[[str], None] = print) -> RenderResult:
    opts = opts or RenderOptions()
    if opts.ffmpeg is None:
        import imageio_ffmpeg
        opts.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    font = resolve_font(opts.font)
    work = Path(opts.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    plans, skipped = plan_shots(sb, images, voices, opts, only)
    if skipped:
        log(f"skipping shots with no image: {skipped}")
    if not plans:
        raise RuntimeError("nothing to render: no shot has an image")

    clips: list[Path] = []
    audio_items: list[tuple[float, Path]] = []
    t, chime_at = 0.0, None
    for i, plan in enumerate(plans):
        if plan.shot.sfx == "door chime":
            chime_at = t + 0.2
        clips.append(render_shot(plan, opts, opts.ffmpeg, font, i == 0, i == len(plans) - 1))
        if plan.wav:
            audio_items.append((t + opts.lead, plan.wav))
        log(f"shot{plan.shot.n:02d} @{t:5.1f}s {plan.dur:4.1f}s {plan.shot.camera:9s} "
            f"{' | '.join(split_phrases(plan.shot.text))}")
        t += plan.dur

    listing = work / "list.txt"
    listing.write_text("".join(f"file '{c.resolve().as_posix()}'\n" for c in clips), encoding="utf-8")
    video = work / "video_only.mp4"
    run_ffmpeg([opts.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(video)])
    score = work / f"bgm_{int(t)}.wav"
    if not score.exists():
        bgm.compose(t, score)
    mixed = work / "audio.wav"
    build_audio(opts.ffmpeg, audio_items, t, chime_at, score, mixed)
    run_ffmpeg([opts.ffmpeg, "-y", "-i", str(video), "-i", str(mixed), "-c:v", "libx264", "-crf", "22",
                "-preset", "medium", "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_path)])
    log(f"done: {out_path}  ({t:.1f}s, {len(plans)} shots)")
    return RenderResult(out_path, t, plans, skipped)
