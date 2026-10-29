"""Find the subtitle font. Order: explicit path, SHORTS_FONT env, bundled assets/fonts, dev fallback."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"
# Malgun Gothic ships with Windows. Fine for local development; a hosted service must bundle an
# open font (Pretendard / Noto Sans KR, both OFL) in assets/fonts instead.
DEV_FALLBACK = r"C:\Windows\Fonts\malgunbd.ttf"


def resolve_font(explicit: str | None = None) -> str:
    bundled = [str(p) for pat in ("Pretendard*Bold*", "NotoSansKR*Bold*") for p in sorted(PROJECT_FONTS.glob(pat))]
    for cand in [explicit, os.environ.get("SHORTS_FONT"), *bundled, DEV_FALLBACK]:
        if cand and Path(cand).exists():
            return str(cand)
    raise FileNotFoundError("no Korean font found; put Pretendard/Noto Sans KR Bold in assets/fonts or set SHORTS_FONT")


def is_dev_fallback(path: str) -> bool:
    return os.path.normcase(path) == os.path.normcase(DEV_FALLBACK)
