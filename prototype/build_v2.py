"""cuts_v2.json + Downloads/shorts_v2/cutNN.png -> cinematic 9:16 short.

Per shot: smooth sub-pixel camera move rendered frame by frame, film grade, Korean-aware phrase
subtitles (no trailing periods) with highlighted keywords.
Audio: Azure neural voices (narrator / grandpa), procedural piano score with ducking, rain bed, door chime.
Shots whose image is missing are skipped, so the script runs on a partial set.

Usage (PYTHONPATH must hold imageio_ffmpeg, PIL, numpy; AZURE_SPEECH_KEY / _REGION set):
    python build_v2.py                          # all available shots
    python build_v2.py --only 5,6               # quick preview
    python build_v2.py --grandpa ko-KR-GookMinNeural [--grandpa-rate -10%]
    python build_v2.py --samples                # write grandpa voice candidates to output/voice_samples
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
import wave
from xml.sax.saxutils import escape

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

import make_bgm

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "shorts_v2")
WORK = os.path.join(os.environ.get("TEMP", HERE), "shorts_v2_work")
OUT_DIR = os.path.join(HERE, "output")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = r"C:\Windows\Fonts\malgunbd.ttf"
W, H, FPS = 1080, 1920, 30

# voice, rate, pitch. No pitch shifting: it makes a young voice sound processed, not old.
VOICES = {
    "narrator": ("ko-KR-InJoonNeural", "+22%", "0%"),
    "grandpa": ("ko-KR-BongJinNeural", "-10%", "0%"),
}
LEAD, TAIL, MIN_DUR = 0.15, 0.2, 1.6
YELLOW, WHITE = (255, 214, 10), (255, 255, 255)
GRADE = "eq=contrast=1.06:saturation=0.93:gamma=0.97,vignette=PI/5,noise=alls=3:allf=t"
NOBREAK_AFTER = set("한 두 세 네 다섯 여섯 그 이 저 어떤 아무 매일 늘 딱 더 잘 못 안 이제 정말 너무 아주 또 다시 처음 마지막 낡은 하얀 뜨거운 같은 오는".split())
SAMPLE_TEXT = "오늘이 우리 결혼기념일이라서. 집사람 몫이야."
SAMPLE_VOICES = ["ko-KR-BongJinNeural", "ko-KR-GookMinNeural", "ko-KR-HyunsuNeural",
                 "ko-KR-HyunsuMultilingualNeural", "ko-KR-InJoonNeural"]


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        sys.exit("ffmpeg failed:\n" + p.stderr[-1500:])


# ---------------------------------------------------------------- voice
def tts_to(path, text, voice, rate, pitch):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prosody = f"<prosody rate='{rate}' pitch='{pitch}'>{escape(text)}</prosody>"
    ssml = f"<speak version='1.0' xml:lang='ko-KR'><voice name='{voice}'>{prosody}</voice></speak>"
    req = urllib.request.Request(
        f"https://{os.environ['AZURE_SPEECH_REGION']}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={"Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
                 "Content-Type": "application/ssml+xml",
                 "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                 "User-Agent": "shorts-builder"})
    with urllib.request.urlopen(req) as r, open(path, "wb") as f:
        f.write(r.read())


def tts(text, who):
    voice, rate, pitch = VOICES[who]
    key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()[:16]
    path = os.path.join(WORK, "tts", key + ".wav")
    if not os.path.exists(path):
        tts_to(path, text, voice, rate, pitch)
    return path


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


# ---------------------------------------------------------------- subtitles
def clean(s):
    return re.sub(r"\s+", " ", s.replace(".", "").replace(",", "")).strip()


def split_sentence(sentence, limit=15):
    """Break at word boundaries, keep determiner+noun ('두 개') together, balance chunk lengths."""
    text = clean(sentence)
    if len(text) <= limit:
        return [text]
    comma_after = {i for i, tok in enumerate(sentence.split()) if tok.endswith(",")}
    units, cur = [], []
    for i, tok in enumerate(sentence.split()):
        cur.append(clean(tok))
        if clean(tok) in NOBREAK_AFTER:
            continue
        units.append((" ".join(cur), i in comma_after))
        cur = []
    if cur:
        units.append((" ".join(cur), False))
    n = len(units)
    k = max(2, math.ceil(len(text) / 12))
    target = len(text) / k
    best = {}

    def solve(i):  # best split of units[i:] -> (cost, chunks)
        if i == n:
            return 0.0, []
        if i in best:
            return best[i]
        res = (1e18, [])
        size = ""
        for j in range(i, n):
            size = (size + " " + units[j][0]).strip()
            if len(size) > limit + 2:
                break
            c, rest = solve(j + 1)
            cost = (len(size) - target) ** 2 + c - (6 if units[j][1] and j + 1 < n else 0)
            if cost < res[0]:
                res = (cost, [size] + rest)
        best[i] = res
        return res

    return solve(0)[1]


def split_phrases(text):
    out = []
    for sentence in re.split(r"(?<=[.?!…])\s+", text.strip()):
        if clean(sentence):
            out += split_sentence(sentence)
    return out


def render_phrase(text, highlight, path):
    font = ImageFont.truetype(FONT, 76)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    colors = [WHITE] * len(text)
    for term in highlight:
        for m in re.finditer(re.escape(term), text):
            for i in range(m.start(), m.end()):
                colors[i] = YELLOW
    lines = [(text, colors)]
    if d.textlength(text, font=font) > W - 120 and " " in text:
        mid = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - len(text) / 2))
        lines = [(text[:mid], colors[:mid]), (text[mid + 1:], colors[mid + 1:])]
    line_h = 100
    top = 1390 - line_h * len(lines) // 2
    for li, (s, cols) in enumerate(lines):
        x = (W - d.textlength(s, font=font)) / 2
        y = top + li * line_h
        xs, cx = [], x
        for ch in s:
            xs.append(cx)
            cx += d.textlength(ch, font=font)
        for ch, cx in zip(s, xs):  # outline first so neighbours never cover a glyph
            d.text((cx, y), ch, font=font, fill=(0, 0, 0, 255), stroke_width=7, stroke_fill=(0, 0, 0, 255))
        for ch, cx, col in zip(s, xs, cols):
            d.text((cx, y), ch, font=font, fill=col + (255,))
    img.save(path)


# ---------------------------------------------------------------- camera
def ease(p):
    return p * p * (3 - 2 * p)


def camera(move, p):
    """zoom and focus-centre fractions at progress p (0..1). Eased, no per-frame rounding."""
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


def build_shot(s, dur, voice_len, first, last):
    n = s["n"]
    frames = max(2, int(round(dur * FPS)))
    src = Image.open(os.path.join(IMG_DIR, f"cut{n:02d}.png")).convert("RGB")
    up = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
    sw, sh = up.size
    chain = f"[0:v]{GRADE},format=yuv420p"
    if first:
        chain += ",fade=t=in:d=0.6"
    if last:
        chain += f",fade=t=out:st={dur - 0.9:.2f}:d=0.9"
    filt, last_label, pngs = chain + "[v0]", "v0", []
    if s["text"]:
        phrases = split_phrases(s["text"])
        weights = [len(p.replace(" ", "")) or 1 for p in phrases]
        t = LEAD
        for i, (p, wgt) in enumerate(zip(phrases, weights)):
            span = voice_len * wgt / sum(weights)
            start, end = t, t + span + (0.2 if i == len(phrases) - 1 else 0)
            t += span
            png = os.path.join(WORK, f"sub{n:02d}_{i}.png")
            render_phrase(p, s["highlight"], png)
            pngs.append(png)
            filt += (f";[{last_label}][{len(pngs)}:v]overlay=0:0:"
                     f"enable='between(t,{start:.2f},{end:.2f})'[v{i + 1}]")
            last_label = f"v{i + 1}"
    cmd = [FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    for png in pngs:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", png]
    mp4 = os.path.join(WORK, f"shot{n:02d}.mp4")
    cmd += ["-filter_complex", filt, "-map", f"[{last_label}]", "-c:v", "libx264", "-crf", "17",
            "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", "-frames:v", str(frames), mp4]
    log = open(os.path.join(WORK, "ffmpeg_shot.log"), "w")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
    for i in range(frames):
        z, fx, fy = camera(s["camera"], i / (frames - 1))
        cw, ch = sw / z, sh / z
        x0 = min(max(fx * sw - cw / 2, 0), sw - cw)
        y0 = min(max(fy * sh - ch / 2, 0), sh - ch)
        frame = up.transform((W, H), Image.AFFINE, (cw / W, 0, x0, 0, ch / H, y0), resample=Image.BICUBIC)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait():
        log.close()
        sys.exit("ffmpeg failed for shot %d:\n%s" % (n, open(os.path.join(WORK, "ffmpeg_shot.log")).read()[-1500:]))
    log.close()
    return mp4


# ---------------------------------------------------------------- audio
def build_audio(items, total, chime_at, bgm_wav, out_wav):
    """items: (start_seconds, wav). Voices -> ducked piano score, rain bed, door chime -> one wav."""
    cmd = [FFMPEG, "-y"]
    for _, p in items:
        cmd += ["-i", p]
    k = len(items)
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anoisesrc=color=pink:amplitude=0.6:sample_rate=44100",
            "-f", "lavfi", "-t", "1.2", "-i", "sine=frequency=1568:sample_rate=44100",
            "-f", "lavfi", "-t", "1.2", "-i", "sine=frequency=1175:sample_rate=44100",
            "-i", bgm_wav]
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
    run(cmd + ["-filter_complex", ";".join(parts), "-map", "[out]", "-ar", "44100", out_wav])


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    if "--samples" in sys.argv:
        d = os.path.join(OUT_DIR, "voice_samples")
        for v in SAMPLE_VOICES:
            tts_to(os.path.join(d, v.replace("ko-KR-", "").replace("Neural", "") + ".wav"),
                   SAMPLE_TEXT, v, "-10%", "0%")
            print("sample:", v)
        return
    if arg("--grandpa"):
        VOICES["grandpa"] = (arg("--grandpa"), arg("--grandpa-rate", VOICES["grandpa"][1]), "0%")
    only = {int(x) for x in arg("--only").split(",")} if arg("--only") else None
    with open(os.path.join(HERE, "cuts_v2.json"), encoding="utf-8") as f:
        story = json.load(f)
    shots = [s for s in story["shots"] if (only is None or s["n"] in only)]
    missing = [s["n"] for s in shots if not os.path.exists(os.path.join(IMG_DIR, f"cut{s['n']:02d}.png"))]
    if missing:
        print("skipping shots with no image:", missing)
    shots = [s for s in shots if s["n"] not in missing]

    plan = []
    for s in shots:
        wav = tts(s["text"], s["who"]) if s["text"] else None
        vlen = wav_seconds(wav) if wav else 0.0
        plan.append((s, wav, vlen, max(LEAD + vlen + TAIL, s.get("min_dur", MIN_DUR), MIN_DUR)))

    clips, audio_items, t, chime_at = [], [], 0.0, None
    for i, (s, wav, vlen, dur) in enumerate(plan):
        if s.get("sfx") == "door chime":
            chime_at = t + 0.2
        clips.append(build_shot(s, dur, vlen, i == 0, i == len(plan) - 1))
        if wav:
            audio_items.append((t + LEAD, wav))
        print(f"shot{s['n']:02d} @{t:5.1f}s {dur:4.1f}s {s['camera']:9s} {' | '.join(split_phrases(s['text']))}")
        t += dur

    listing = os.path.join(WORK, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.writelines(f"file '{c.replace(chr(92), '/')}'\n" for c in clips)
    video = os.path.join(WORK, "video_only.mp4")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", video])
    bgm = os.path.join(WORK, f"bgm_{int(t)}.wav")
    if not os.path.exists(bgm):
        make_bgm.compose(t, bgm)
    wav_all = os.path.join(WORK, "audio.wav")
    build_audio(audio_items, t, chime_at, bgm, wav_all)
    final = os.path.join(OUT_DIR, "shorts_v2.mp4")
    run([FFMPEG, "-y", "-i", video, "-i", wav_all, "-c:v", "libx264", "-crf", "22", "-preset", "medium",
         "-maxrate", "10M", "-bufsize", "20M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-shortest", final])
    print(f"done: {final}  ({t:.1f}s, {len(plan)} shots)")


if __name__ == "__main__":
    main()
