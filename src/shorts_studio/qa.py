"""Deterministic checks on a storyboard. Anything visual (logos, faces) still needs a person or a vision model."""
from __future__ import annotations

from dataclasses import dataclass

from .models import CAMERAS, Storyboard
from .providers.base import ImageSource
from .render.subtitles import split_phrases

MAX_PHRASE = 17


@dataclass
class Issue:
    level: str  # "error" | "warn"
    shot: int | None
    message: str

    def __str__(self) -> str:
        where = f"shot {self.shot}" if self.shot is not None else "storyboard"
        return f"[{self.level}] {where}: {self.message}"


def lint(sb: Storyboard) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[int] = set()
    for s in sb.shots:
        if s.n in seen:
            issues.append(Issue("error", s.n, "duplicate shot number"))
        seen.add(s.n)
        if s.camera not in CAMERAS:
            issues.append(Issue("error", s.n, f"unknown camera '{s.camera}'"))
        if s.text and s.who not in sb.voices:
            issues.append(Issue("error", s.n, f"speaker '{s.who}' has no voice configured"))
        if s.who and not s.text:
            issues.append(Issue("warn", s.n, "speaker set but no text"))
        for term in s.highlight:
            if term not in s.text.replace(".", "").replace(",", ""):
                issues.append(Issue("warn", s.n, f"highlight '{term}' does not appear in the line"))
        for phrase in split_phrases(s.text):
            if phrase.endswith((".", ",")):
                issues.append(Issue("error", s.n, f"subtitle ends with punctuation: '{phrase}'"))
            if len(phrase) > MAX_PHRASE:
                issues.append(Issue("warn", s.n, f"subtitle phrase is long ({len(phrase)}): '{phrase}'"))
        if not s.scene:
            issues.append(Issue("warn", s.n, "no scene description for the image"))
    return issues


def missing_images(sb: Storyboard, images: ImageSource) -> list[int]:
    return [s.n for s in sb.shots if images.path_for(s) is None]
