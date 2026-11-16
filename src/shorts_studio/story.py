"""From one prompt to a storyboard: ask a text model for the story as JSON, then turn that JSON into a valid Storyboard.

The model is asked for structure (shots, speakers, camera, image descriptions); this module never trusts it. Whatever
comes back is cleaned up so the storyboard always satisfies the rules the rest of the pipeline relies on (known
cameras, a voice for every speaker, highlights that really occur in the line, numbered shots), and it is screened
with the same word lists as everything a user writes. The prompt is screened first, so nothing is spent on a request
that would be refused anyway.
"""
from __future__ import annotations

import re
from typing import Protocol

from .api import voices as voices_catalog
from .models import CAMERAS, Shot, Storyboard, VoiceSpec
from .safety import blocking_issues, screen_text

MIN_SHOTS, MAX_SHOTS, DEFAULT_SHOTS = 6, 24, 12
MAX_CHARACTERS = 4
MAX_PROMPT = 800
NARRATOR_VOICE, NARRATOR_RATE = "ko-KR-InJoonNeural", "+15%"

# the look of the whole film, written for the image model (the model sees these, the user picks by name)
STYLES: dict[str, tuple[str, str]] = {
    "cinematic": ("영화처럼 (실사)",
                  "photorealistic cinematic still, 35mm film look, shallow depth of field, moody natural lighting, "
                  "subtle film grain, vertical 9:16, no text, no watermark"),
    "anime": ("애니메이션",
              "high quality Korean webtoon-anime illustration, clean line art, soft cel shading, rich colors, "
              "vertical 9:16, no text, no watermark"),
    "watercolor": ("수채화",
                   "soft watercolor illustration, gentle washes of color, visible paper texture, warm light, "
                   "vertical 9:16, no text, no watermark"),
    "storybook": ("동화책 일러스트",
                  "flat storybook illustration, bold simple shapes, warm limited palette, soft grain, "
                  "vertical 9:16, no text, no watermark"),
}
DEFAULT_STYLE = "cinematic"

SYSTEM = f"""You write storyboards for vertical short videos (9:16, about 30 to 60 seconds). Reply with one JSON object
that follows the given schema, nothing else.

Language: title, logline and every line of dialogue or narration are in natural spoken Korean. place, character looks
and scene descriptions are in English because an image model reads them.

Story: one clear small story with a beginning, a turn and an ending that lands (a quiet twist, a reveal, a warm
or bitter last beat). Strong first shot. Every shot moves the story. Prefer specific, concrete details over clichés.

Shots: exactly the requested number. The line of a shot is short, at most 30 Korean characters, in one or two short
phrases, no emoji. Some shots are silent (empty text and empty who) to let an image breathe. Speakers are either
"narrator" or the id of a character. Use each camera move for a reason: push_in (tension, intimacy), pull_out
(reveal, loneliness), pan_right (following, scanning), handheld (anxiety, urgency), static (stillness).
highlight lists one to three short words (one or two words each, no punctuation) of the line to emphasise;
each must appear in the line exactly.

Characters: at most {MAX_CHARACTERS}. id is a short lowercase English word. look is one detailed English sentence
about face, age, hair, clothes and accessories, written so that the same person can be drawn identically in every
shot. Give gender (male or female) and age (young, adult or senior) for choosing a voice.

Scenes: each scene is one English sentence describing what the camera sees (framing, subject, setting, light).
List in chars the ids of the characters visible in that shot. Never rely on text, signs or logos in an image: no
brand names, no trademarks, no readable writing. Do not use real people, real companies or real brands.

Content: nothing sexual, nothing involving minors in any harmful way, no instructions for weapons, drugs or
self-harm, no hateful or deceptive content. If the request asks for any of that, write a harmless story on the
nearest safe theme."""

_STRING = {"type": "STRING"}
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": _STRING, "logline": _STRING, "place": _STRING,
        "characters": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "id": _STRING, "look": _STRING,
            "gender": {"type": "STRING", "enum": list(voices_catalog.GENDERS)},
            "age": {"type": "STRING", "enum": list(voices_catalog.AGE_PRESETS)}},
            "required": ["id", "look", "gender", "age"]}},
        "shots": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": _STRING, "who": _STRING,
            "camera": {"type": "STRING", "enum": list(CAMERAS)},
            "highlight": {"type": "ARRAY", "items": _STRING},
            "scene": _STRING,
            "chars": {"type": "ARRAY", "items": _STRING}},
            "required": ["text", "who", "camera", "highlight", "scene", "chars"]}},
    },
    "required": ["title", "logline", "place", "characters", "shots"],
}


class StoryError(ValueError):
    """The request or the model's answer cannot become a storyboard; the message is safe to show the user."""


class StoryProvider(Protocol):
    def generate(self, system: str, prompt: str, schema: dict) -> dict:
        """Return the story as a JSON object that follows `schema`."""


def user_prompt(prompt: str, shots: int) -> str:
    return f"Request (Korean or any language): {prompt.strip()}\nNumber of shots: exactly {shots}."


# ASCII punctuation plus the ellipsis and the curly quotes, written as code points so the source stays plain ASCII
_PUNCT = re.compile("[" + re.escape("?!.,~\"'") + "".join(map(chr, (0x2026, 0x201C, 0x201D, 0x2018, 0x2019))) + "]+")


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(value).strip().lower().replace("-", "_").replace(" ", "_"))[:20]


def _clean(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _cast(raw_characters: object) -> tuple[dict[str, str], dict[str, VoiceSpec]]:
    """Character looks and one voice each (a different voice per character whenever the catalog has one to spare)."""
    looks: dict[str, str] = {}
    voices: dict[str, VoiceSpec] = {"narrator": VoiceSpec("azure", NARRATOR_VOICE, NARRATOR_RATE, "0%")}
    used = {NARRATOR_VOICE}
    for item in raw_characters if isinstance(raw_characters, list) else []:
        if not isinstance(item, dict) or len(looks) >= MAX_CHARACTERS:
            continue
        cid, look = _slug(item.get("id")), _clean(item.get("look"), 400)
        if not cid or cid == "narrator" or cid in looks or not look:
            continue
        gender = item.get("gender") if item.get("gender") in voices_catalog.GENDERS else "male"
        age = item.get("age") if item.get("age") in voices_catalog.AGE_PRESETS else "adult"
        rec = voices_catalog.recommend(gender, age, limit=len(voices_catalog.VOICES))
        pick = next((v["name"] for v in rec["voices"] if v["name"] not in used), rec["voices"][0]["name"])
        used.add(pick)
        looks[cid] = look
        voices[cid] = VoiceSpec("azure", pick, rec["rate"], rec["pitch"])
    return looks, voices


def build_storyboard(raw: dict, shots: int, style: str = DEFAULT_STYLE) -> Storyboard:
    """Validate and repair the model's JSON. Raises StoryError when too little is usable."""
    if style not in STYLES:
        raise StoryError(f"알 수 없는 화풍입니다: {style}")
    looks, voices = _cast(raw.get("characters"))
    out: list[Shot] = []
    raw_shots = raw.get("shots")
    for item in (raw_shots if isinstance(raw_shots, list) else [])[:shots]:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"), 120)
        scene = _clean(item.get("scene"), 600)
        if not scene and not text:
            continue
        who = str(item.get("who") or "").strip().lower()
        who = who if who in voices else "narrator"
        camera = item.get("camera") if item.get("camera") in CAMERAS else "static"
        flat = text.replace(".", "").replace(",", "")
        terms = (_PUNCT.sub("", h).strip() for h in (item.get("highlight") or []) if isinstance(h, str))
        highlight = [h for h in dict.fromkeys(_clean(t, 20) for t in terms) if h and h in flat][:3]
        chars = [c for c in dict.fromkeys(_slug(c) for c in (item.get("chars") or []) if isinstance(c, str))
                 if c in looks]
        out.append(Shot(n=len(out) + 1, text=text, who=who if text else "", camera=camera, highlight=highlight,
                        scene=scene, chars=chars))
    if len(out) < MIN_SHOTS:
        raise StoryError("이야기가 너무 짧게 만들어졌습니다. 조금 더 구체적으로 적고 다시 시도해 주세요.")
    title = _clean(raw.get("title"), 60) or "제목 없는 이야기"
    return Storyboard(title=title, logline=_clean(raw.get("logline"), 200), voices=voices, style=STYLES[style][1],
                      place=_clean(raw.get("place"), 400), characters=looks, shots=out)


def check_request(prompt: str, shots: int, style: str) -> str:
    """Normalised prompt, or StoryError. Runs before anything is spent."""
    prompt = (prompt or "").strip()
    if len(prompt) < 4:
        raise StoryError("만들고 싶은 이야기를 한 줄 이상 적어 주세요.")
    if len(prompt) > MAX_PROMPT:
        raise StoryError(f"설명이 너무 깁니다. {MAX_PROMPT}자 이하로 줄여 주세요.")
    if not MIN_SHOTS <= shots <= MAX_SHOTS:
        raise StoryError(f"컷 수는 {MIN_SHOTS}개에서 {MAX_SHOTS}개 사이여야 합니다.")
    if style not in STYLES:
        raise StoryError(f"알 수 없는 화풍입니다: {style}")
    errors = [f for f in screen_text(prompt) if f.level == "error"]
    if errors:
        raise StoryError(errors[0].message)
    return prompt


def generate_storyboard(provider: StoryProvider, prompt: str, shots: int = DEFAULT_SHOTS,
                        style: str = DEFAULT_STYLE) -> Storyboard:
    prompt = check_request(prompt, shots, style)
    sb = build_storyboard(provider.generate(SYSTEM, user_prompt(prompt, shots), SCHEMA), shots, style)
    blocked = blocking_issues(sb)
    if blocked:   # the model strayed into something we do not make; nothing is saved
        raise StoryError("만들어진 이야기에 허용되지 않는 내용이 있어 저장하지 않았습니다: "
                         + "; ".join(dict.fromkeys(i.message for i in blocked)))
    return sb
