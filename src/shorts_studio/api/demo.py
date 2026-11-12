"""Public demo mode: the whole dashboard works, but nothing paid ever runs.

With SHORTS_DEMO=1 the server reads no API key and calls no provider. It serves a pre-built project (downsized
images, one finished video, pre-made voice samples, a pre-computed face check; see scripts/build_demo_assets.py),
replays image regeneration and rendering as a short progress animation, refuses to save edits, and rate-limits every
request that would change something. Visitors can therefore never spend the owner's money or alter each other's view.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

DEMO_PROJECT = "convenience-store"
DEMO_RENDER = "render-20261112-000000.mp4"
READ_ONLY_MESSAGE = (
    "이 데모는 읽기 전용입니다. 대사와 목소리를 고쳐 보며 자막 미리보기를 확인할 수는 있지만 저장은 되지 않습니다."
)
MAX_TRACKED_CLIENTS = 5000


def seed(root: Path, demo_dir: Path) -> None:
    """Copy the pre-built project into the data folder (once)."""
    src = demo_dir / "project"
    if not (src / "storyboard.json").exists():
        raise FileNotFoundError(f"demo assets not found in {demo_dir}; run scripts/build_demo_assets.py first")
    dest = root / "projects" / DEMO_PROJECT
    if not dest.exists():
        shutil.copytree(src, dest)


def voice_sample(demo_dir: Path, voice: str) -> Path | None:
    path = demo_dir / "voice_samples" / f"{voice}.mp3"
    return path if path.exists() else None


def face_check(demo_dir: Path) -> dict:
    return json.loads((demo_dir / "face_check.json").read_text(encoding="utf-8"))


class RateLimiter:
    """At most `limit` allowed requests per client within `window` seconds (sliding window, in memory)."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > MAX_TRACKED_CLIENTS:   # forget clients that have gone quiet
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                    del self._hits[key]
            return True


PREVIEW_PATH = "/api/subtitles/preview"


def client_address(forwarded: str, peer: str, hops: int) -> str:
    """Who is calling? hops=0: the connection itself (do not trust X-Forwarded-For). hops=n: n trusted proxies each
    appended the address they saw, so the visitor is the n-th entry from the right; the entries further left are
    whatever the visitor sent and are never used."""
    if hops <= 0:
        return peer
    parts = [p.strip() for p in forwarded.split(",") if p.strip()]
    return parts[-hops] if len(parts) >= hops else peer


class DemoLimits:
    """Three budgets per minute for requests that are not plain reads."""

    def __init__(self, per_client: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.client = RateLimiter(per_client, window, clock)
        # the live subtitle preview is a cheap, pure POST sent every time someone pauses while typing
        self.preview = RateLimiter(per_client * 10, window, clock)
        # last line of defence: if visitors cannot be told apart (a wrong proxy setting), the total is still capped
        self.everyone = RateLimiter(per_client * 20, window, clock)

    def allow(self, client: str, path: str) -> bool:
        bucket = self.preview if path == PREVIEW_PATH else self.client
        return bucket.allow(client) and self.everyone.allow("*")


def simulate_regenerate(n: int, report, sleep: Callable[[float], None] = time.sleep) -> str:
    steps = (
        "프롬프트를 준비하는 중 (데모: 실제 이미지 호출 없음)",
        "이미지를 만드는 중 (시뮬레이션)",
        "저장하는 중 (시뮬레이션)",
    )
    for i, line in enumerate(steps):
        report(line, 0.1 + 0.3 * i)
        sleep(0.4)
    return f"cut{n:02d}.jpg"


def simulate_render(shot_numbers: list[int], report, sleep: Callable[[float], None] = time.sleep) -> str:
    total = max(len(shot_numbers), 1)
    for done, n in enumerate(shot_numbers, 1):
        report(f"shot{n:02d} rendered (데모: 미리 만든 영상을 보여 줍니다)", min(done / total, 0.95))
        sleep(0.08)
    return DEMO_RENDER
