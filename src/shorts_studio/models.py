"""Storyboard data model. The JSON layout is the one used by the prototype's cuts_v2.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
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
    def load(cls, path: str | Path) -> Storyboard:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        voices = {k: VoiceSpec(**v) for k, v in raw["voices"].items()}
        shots = [Shot(**s) for s in raw["shots"]]
        return cls(raw["title"], raw.get("logline", ""), voices, raw.get("style", ""), raw.get("place", ""),
                   raw.get("characters", {}), shots)

    def to_dict(self) -> dict:
        shots = []
        for s in self.shots:
            d = asdict(s)
            shots.append({k: v for k, v in d.items() if v is not None})
        return {"title": self.title, "logline": self.logline,
                "voices": {k: asdict(v) for k, v in self.voices.items()},
                "style": self.style, "place": self.place, "characters": self.characters, "shots": shots}

    def save(self, path: str | Path) -> None:
        """Write atomically so a crash never leaves a half-written storyboard."""
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def shot(self, n: int) -> Shot | None:
        return next((s for s in self.shots if s.n == n), None)

    def image_prompt(self, shot: Shot) -> str:
        """Scene + place + the fixed look of every character in the shot + global style."""
        looks = "; ".join(self.characters[c] for c in shot.chars if c in self.characters)
        parts = [shot.scene, looks, self.place, self.style]
        return ". ".join(p for p in parts if p)
