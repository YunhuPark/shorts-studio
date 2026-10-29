"""Korean-aware subtitle phrasing and rendering. No trailing periods/commas; '두 개'-style pairs stay together."""
from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

YELLOW, WHITE = (255, 214, 10), (255, 255, 255)
NOBREAK_AFTER = set("한 두 세 네 다섯 여섯 그 이 저 어떤 아무 매일 늘 딱 더 잘 못 안 이제 정말 너무 아주 또 다시 처음 마지막 낡은 하얀 뜨거운 같은 오는".split())


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace(".", "").replace(",", "")).strip()


def split_sentence(sentence: str, limit: int = 15) -> list[str]:
    """Break at word boundaries, keep determiner+noun together, balance chunk lengths."""
    text = clean(sentence)
    if len(text) <= limit:
        return [text]
    tokens = sentence.split()
    comma_after = {i for i, tok in enumerate(tokens) if tok.endswith(",")}
    units: list[tuple[str, bool]] = []
    cur: list[str] = []
    for i, tok in enumerate(tokens):
        cur.append(clean(tok))
        if clean(tok) in NOBREAK_AFTER:
            continue
        units.append((" ".join(cur), i in comma_after))
        cur = []
    if cur:
        units.append((" ".join(cur), False))
    n = len(units)
    target = len(text) / max(2, math.ceil(len(text) / 12))
    memo: dict[int, tuple[float, list[str]]] = {}

    def solve(i: int) -> tuple[float, list[str]]:
        if i == n:
            return 0.0, []
        if i in memo:
            return memo[i]
        best = (1e18, [])
        size = ""
        for j in range(i, n):
            size = (size + " " + units[j][0]).strip()
            if len(size) > limit + 2:
                break
            rest_cost, rest = solve(j + 1)
            cost = (len(size) - target) ** 2 + rest_cost - (6 if units[j][1] and j + 1 < n else 0)
            if cost < best[0]:
                best = (cost, [size] + rest)
        memo[i] = best
        return best

    return solve(0)[1]


def split_phrases(text: str) -> list[str]:
    out: list[str] = []
    for sentence in re.split(r"(?<=[.?!…])\s+", text.strip()):
        if clean(sentence):
            out += split_sentence(sentence)
    return out


def render_phrase(text: str, highlight: list[str], path: Path, font_path: str, size: tuple[int, int] = (1080, 1920)) -> None:
    w, h = size
    font = ImageFont.truetype(font_path, 76)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    colors = [WHITE] * len(text)
    for term in highlight:
        for m in re.finditer(re.escape(term), text):
            for i in range(m.start(), m.end()):
                colors[i] = YELLOW
    lines = [(text, colors)]
    if d.textlength(text, font=font) > w - 120 and " " in text:
        mid = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - len(text) / 2))
        lines = [(text[:mid], colors[:mid]), (text[mid + 1:], colors[mid + 1:])]
    line_h = 100
    top = 1390 - line_h * len(lines) // 2
    for li, (s, cols) in enumerate(lines):
        x = (w - d.textlength(s, font=font)) / 2
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
