"""Voice catalog and a simple recommendation, so a new character can be cast without trial and error.

Only what can be measured is recorded: gender and the median pitch of each voice reading the same sentence at
-10% speed (autocorrelation over voiced frames). Azure's Korean voices have no real elderly timbre, so "senior"
means "the lowest voice available, slowed down a little": an approximation, and the UI says so. Whether a voice
sounds right for a character is still a human judgement; the recommendation only orders the candidates.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    name: str
    gender: str          # "male" | "female"
    pitch_hz: int        # measured median pitch, same sentence, rate -10%
    note: str = ""


VOICES: tuple[Voice, ...] = (
    Voice("ko-KR-InJoonNeural", "male", 155, "젊은 남성 (내레이터용)"),
    Voice("ko-KR-BongJinNeural", "male", 130),
    Voice("ko-KR-GookMinNeural", "male", 136),
    Voice("ko-KR-HyunsuNeural", "male", 135),
    Voice("ko-KR-HyunsuMultilingualNeural", "male", 135),
    Voice("ko-KR-SunHiNeural", "female", 212),
    Voice("ko-KR-JiMinNeural", "female", 202),
    Voice("ko-KR-SeoHyeonNeural", "female", 247),
    Voice("ko-KR-SoonBokNeural", "female", 205),
    Voice("ko-KR-YuJinNeural", "female", 207),
)
NAMES = {v.name for v in VOICES}
GENDERS = ("male", "female")

# age band -> (rate, pitch) to start from; the voices themselves cannot change their age
AGE_PRESETS = {"young": ("+5%", "0%"), "adult": ("-5%", "0%"), "senior": ("-15%", "-5%")}
AGE_NOTES = {
    "young": "높은 음높이 순으로 추천합니다.",
    "adult": "그 성별의 중간 음높이에 가까운 순으로 추천합니다.",
    "senior": "낮은 음높이 순으로 추천하고 속도를 늦춥니다. AI 음성은 노인 음색을 정확히 내지 못하므로 근사치입니다.",
}


def recommend(gender: str, age: str, limit: int = 3) -> dict:
    if gender not in GENDERS:
        raise ValueError(f"gender must be one of {list(GENDERS)}")
    if age not in AGE_PRESETS:
        raise ValueError(f"age must be one of {list(AGE_PRESETS)}")
    pool = [v for v in VOICES if v.gender == gender]
    pitches = sorted(v.pitch_hz for v in pool)
    middle = pitches[len(pitches) // 2]
    if age == "young":
        ordered = sorted(pool, key=lambda v: (-v.pitch_hz, v.name))
    elif age == "senior":
        ordered = sorted(pool, key=lambda v: (v.pitch_hz, v.name))
    else:
        ordered = sorted(pool, key=lambda v: (abs(v.pitch_hz - middle), v.name))
    rate, pitch = AGE_PRESETS[age]
    return {"note": AGE_NOTES[age], "rate": rate, "pitch": pitch,
            "voices": [{"name": v.name, "gender": v.gender, "pitch_hz": v.pitch_hz} for v in ordered[:limit]]}
