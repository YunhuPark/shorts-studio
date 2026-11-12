"""First-line input screening for storyboard text: a transparent keyword/pattern check, nothing more.

What it is: a fast, deterministic filter that runs before money is spent (image regeneration) or a video is
produced (render), so the clearest policy violations are stopped with a plain explanation. Findings are either
"error" (blocks paid work and rendering) or "warn" (shown to the user, e.g. content some platforms age-restrict).

What it is not: a content-moderation system. It cannot read intent, context, hate speech, harassment or whether a
name belongs to a real person, and a determined user can phrase around any word list. Image and voice providers
apply their own safety filters, and a hosted service still needs a trained classifier, a reporting channel and
human review. The word lists below are a conservative starting point that the service owner must review.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import Storyboard
from .qa import Issue

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­"))


def normalize(text: str) -> str:
    """Fold full-width letters, drop zero-width characters, lowercase, collapse whitespace."""
    folded = unicodedata.normalize("NFKC", text).translate(_INVISIBLE).lower()
    return re.sub(r"\s+", " ", folded).strip()


def _words(*terms: str) -> re.Pattern[str]:
    """Latin terms match whole words; Hangul terms match as substrings (Korean has no word boundaries)."""
    parts = []
    for t in terms:
        parts.append(rf"\b{re.escape(t)}\b" if t.isascii() else re.escape(t))
    return re.compile("|".join(parts))


# phrases that look like a hit but are ordinary words
_BENIGN = re.compile("|".join(map(re.escape, ["누드김밥", "naked eye", "naked eyes"])))

MINOR = _words(
    "아동", "미성년", "초등학생", "중학생", "어린이", "소년", "소녀", "10대", "십대",
    "child", "children", "kid", "kids", "minor", "minors", "underage", "teen", "teenage", "teenager",
    "schoolgirl", "schoolboy", "preteen", "loli",
)
SEXUAL = _words(
    "섹스", "성관계", "성행위", "성적인", "야한", "야동", "음란", "포르노", "나체", "누드", "알몸",
    "sex", "sexual", "sexually", "porn", "nsfw", "erotic", "lewd", "nude", "naked",
)

@dataclass(frozen=True)
class Rule:
    category: str
    level: str          # "error" blocks paid work and rendering, "warn" is shown only
    message: str
    pattern: re.Pattern[str]


RULES: tuple[Rule, ...] = (
    Rule("sexual", "error", "성적인 표현이 들어 있어 만들 수 없습니다", SEXUAL),
    Rule("self_harm_method", "error", "자해·자살 방법을 알려 주는 내용은 만들 수 없습니다",
         _words("자살 방법", "자살하는 법", "자살하는 방법", "죽는 방법", "목숨을 끊는 방법", "자해하는 방법",
                "how to kill myself", "suicide method", "suicide methods", "ways to commit suicide")),
    Rule("dangerous_instructions", "error", "위험한 물건이나 마약을 만드는 방법은 만들 수 없습니다",
         _words("폭탄 만드는", "폭탄 제조", "마약 제조", "마약 만드는", "how to make a bomb", "build a bomb",
                "synthesize meth", "how to make meth")),
    Rule("fraud_impersonation", "error", "딥페이크·사칭·사기 목적의 내용은 만들 수 없습니다",
         _words("딥페이크", "deepfake", "보이스피싱", "voice phishing", "scam script")),
    Rule("graphic_violence", "warn", "잔인한 묘사가 있습니다. 일부 플랫폼에서 연령 제한이 걸릴 수 있습니다",
         _words("고어", "참수", "시체", "피투성이", "gore", "gory", "dismember", "decapitate", "beheading")),
)
MINOR_SEXUAL_MESSAGE = "미성년자가 나오는 성적인 내용은 어떤 경우에도 만들 수 없습니다"


@dataclass(frozen=True)
class Finding:
    category: str
    level: str
    message: str


def screen_text(text: str) -> list[Finding]:
    """Findings for one piece of text, strongest first. The text is returned nowhere: only the category."""
    if not text or not text.strip():
        return []
    t = _BENIGN.sub(" ", normalize(text))
    found: list[Finding] = []
    if MINOR.search(t) and SEXUAL.search(t):
        found.append(Finding("minor_sexual", "error", MINOR_SEXUAL_MESSAGE))
    for rule in RULES:
        if rule.pattern.search(t):
            found.append(Finding(rule.category, rule.level, rule.message))
    return sorted(found, key=lambda f: (f.level != "error", f.category))


def check_storyboard(sb: Storyboard) -> list[Issue]:
    """Issues for the whole storyboard: its description fields once, and each shot's line plus scene together."""
    issues: list[Issue] = []
    seen: set[tuple[int | None, str]] = set()

    def add(shot: int | None, findings: list[Finding]) -> None:
        for f in findings:
            if (shot, f.category) not in seen:
                seen.add((shot, f.category))
                issues.append(Issue(f.level, shot, f.message))

    general = " \n ".join([sb.title, sb.logline, sb.style, sb.place, *sb.characters.values()])
    add(None, screen_text(general))
    for s in sb.shots:
        add(s.n, screen_text(f"{s.text} \n {s.scene}"))
    return issues


def blocking_issues(sb: Storyboard, shot: int | None = None) -> list[Issue]:
    """Errors that must stop paid work: the whole-storyboard ones plus those of `shot` (all shots when None)."""
    return [i for i in check_storyboard(sb) if i.level == "error" and (shot is None or i.shot in (None, shot))]
