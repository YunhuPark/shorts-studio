"""Storyboard data model. The JSON layout is the one used by the prototype's cuts_v2.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CAMERAS = ("push_in", "pull_out", "pan_right", "handheld", "static")


@dataclass
class VoiceSpec:
    provider: str
    voice: str
    rate: str = "0%"
    pitch: str = "0%"


@dataclass
class Shot:
    n: int
    text: str = ""
    who: str = ""
    camera: str = "static"
    highlight: list[str] = field(default_factory=list)
    scene: str = ""
    chars: list[str] = field(default_factory=list)
    min_dur: float | None = None
    sfx: str | None = None


@dataclass
class Storyboard:
    title: str
    logline: str
    voices: dict[str, VoiceSpec]
    style: str
    place: str
    characters: dict[str, str]
    shots: list[Shot]

    @classmethod
    def load(cls, path: str | Path) -> "Storyboard":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        voices = {k: VoiceSpec(**v) for k, v in raw["voices"].items()}
        shots = [Shot(**s) for s in raw["shots"]]
        return cls(raw["title"], raw.get("logline", ""), voices, raw.get("style", ""), raw.get("place", ""),
                   raw.get("characters", {}), shots)

    def image_prompt(self, shot: Shot) -> str:
        """Scene + place + the fixed look of every character in the shot + global style."""
        looks = "; ".join(self.characters[c] for c in shot.chars if c in self.characters)
        parts = [shot.scene, looks, self.place, self.style]
        return ". ".join(p for p in parts if p)
