"""Visible "AI generated" label and file metadata for the final video.

The label is a small rounded badge drawn once with Pillow and laid over the whole video by ffmpeg; the same
disclosure is written into the mp4 metadata (comment / description). The wording and position are settings, not
legal advice: the exact disclosure rules (Korea's AI Basic Act guidelines, platform policies) must be checked.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LABEL_X, LABEL_Y = 48, 110   # top-left, below the phone's status bar and clear of the subtitles
DEFAULT_TEXT = "AI 생성"
METADATA_COMMENT = "AI-generated content: images, voice and music were produced with generative AI / synthesis."


def make_label_png(text: str, font_path: str, out: Path, size: int = 40) -> Path:
    font = ImageFont.truetype(font_path, size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.textbbox((0, 0), text, font=font)
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = 22, 14
    w, h = text_w + 2 * pad_x, text_h + 2 * pad_y
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(0, 0, 0, 150), outline=(255, 255, 255, 200),
                           width=2)
    draw.text((pad_x - box[0], pad_y - box[1]), text, font=font, fill=(255, 255, 255, 255))
    img.save(out)
    return out


def final_encode_args(ffmpeg: str, video: Path, audio: Path, out: Path, label_png: Path | None) -> list[str]:
    """The last ffmpeg call: encode, mix in the audio and, when a label is given, overlay it and add metadata."""
    head = [ffmpeg, "-y", "-i", str(video), "-i", str(audio)]
    if label_png is not None:
        head += ["-i", str(label_png), "-filter_complex", f"[0:v][2:v]overlay={LABEL_X}:{LABEL_Y}[v]",
                 "-map", "[v]", "-map", "1:a"]
    tail = ["-c:v", "libx264", "-crf", "22", "-preset", "medium", "-maxrate", "10M", "-bufsize", "20M",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    if label_png is not None:
        tail += ["-metadata", f"comment={METADATA_COMMENT}", "-metadata", f"description={METADATA_COMMENT}"]
    return [*head, *tail, str(out)]
