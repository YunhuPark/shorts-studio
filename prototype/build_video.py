"""cuts.json + cut1..6.png -> 9:16 zoom/pan shorts with narration and burned-in subtitles.

Narration: Azure AI Speech if AZURE_SPEECH_KEY / AZURE_SPEECH_REGION are set,
otherwise the installed Windows Korean voice (Heami).
Usage: set PYTHONPATH to the folder holding imageio_ffmpeg + PIL, then
    python build_video.py
"""
import json
import os
import subprocess
import sys
import urllib.request
import wave
from xml.sax.saxutils import escape

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
WORK = os.path.join(os.environ.get("TEMP", HERE), "shorts_work")
OUT_DIR = os.path.join(HERE, "output")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FONT = r"C:\Windows\Fonts\malgunbd.ttf"
W, H, FPS = 1080, 1920, 30
PAD = 0.5          # silence after each cut, seconds
ZOOM = 0.15        # total zoom travel per cut
AZURE_VOICE = "ko-KR-SunHiNeural"


def tts_azure(text, wav_path):
    key, region = os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"]
    ssml = (
        "<speak version='1.0' xml:lang='ko-KR'>"
        f"<voice name='{AZURE_VOICE}'>{escape(text)}</voice></speak>"
    )
    req = urllib.request.Request(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "shorts-builder",
        },
    )
    with urllib.request.urlopen(req) as r, open(wav_path, "wb") as f:
        f.write(r.read())


def tts_windows(text, wav_path):
    txt_path = wav_path + ".txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.SelectVoice('Microsoft Heami Desktop');"
        "$s.Rate = 1;"
        f"$s.SetOutputToWaveFile('{wav_path}');"
        f"$s.Speak([IO.File]::ReadAllText('{txt_path}', [Text.Encoding]::UTF8));"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def subtitle_png(text, path):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 58)
    max_w = W - 200
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    line_h = 82
    box_h = line_h * len(lines) + 50
    top = H - 330 - box_h
    d.rounded_rectangle((70, top, W - 70, top + box_h), radius=36, fill=(0, 0, 0, 150))
    for i, line in enumerate(lines):
        w = d.textlength(line, font=font)
        d.text(((W - w) / 2, top + 25 + i * line_h), line, font=font, fill="white",
               stroke_width=3, stroke_fill="black")
    img.save(path)


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(HERE, "cuts.json"), encoding="utf-8") as f:
        cuts = json.load(f)
    use_azure = bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION"))
    print("voice:", "Azure " + AZURE_VOICE if use_azure else "Windows Heami (fallback)")

    parts = []
    for c in cuts:
        n = c["n"]
        wav = os.path.join(WORK, f"cut{n}.wav")
        sub = os.path.join(WORK, f"sub{n}.png")
        mp4 = os.path.join(WORK, f"cut{n}.mp4")
        (tts_azure if use_azure else tts_windows)(c["text"], wav)
        dur = wav_seconds(wav) + PAD
        frames = int(dur * FPS)
        subtitle_png(c["text"], sub)
        z = f"1+{ZOOM}*on/{frames}" if n % 2 else f"{1 + ZOOM}-{ZOOM}*on/{frames}"
        vf = (
            f"[0:v]scale=1620:2880:flags=lanczos,"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},"
            f"format=yuv420p[bg];[bg][1:v]overlay=0:0[v]"
        )
        run([FFMPEG, "-y", "-loop", "1", "-i", os.path.join(IMG_DIR, f"cut{n}.png"),
             "-i", sub, "-i", wav,
             "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
             "-af", f"apad=whole_dur={dur:.3f}",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-t", f"{dur:.3f}", mp4])
        parts.append(mp4)
        print(f"cut{n}: {dur:.1f}s")

    listing = os.path.join(WORK, "list.txt")
    with open(listing, "w", encoding="utf-8") as f:
        f.writelines(f"file '{p.replace(chr(92), '/')}'\n" for p in parts)
    final = os.path.join(OUT_DIR, "shorts.mp4")
    run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", final])
    print("done:", final)


if __name__ == "__main__":
    sys.exit(main())
