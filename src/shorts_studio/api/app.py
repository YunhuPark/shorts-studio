"""FastAPI app for the local dashboard.

Single user, bound to localhost by `shorts-studio serve`. API keys come from environment variables and are
never returned to the browser (only whether they are set). Paid actions need an explicit confirm and stop at a
daily estimated-spend cap.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field

from ..generate import plan_generation, run_generation
from ..models import CAMERAS, Storyboard
from ..providers import AzureVoiceProvider, DirectoryImageSource, GeminiImageProvider, ProviderError
from ..qa import lint
from ..render import RenderOptions
from ..render import render as render_storyboard
from ..render.subtitles import split_phrases
from .jobs import JobManager
from .spend import SpendLedger
from .store import NotFound, ProjectStore

VOICE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
RATE_RE = re.compile(r"^[+-]?\d{1,3}%$")
RENDER_RE = re.compile(r"^render-\d{8}-\d{6}\.mp4$")
SAMPLE_TEXT = "오늘이 우리 결혼기념일이라서. 집사람 몫이야."
VOICES = [
    {"name": "ko-KR-InJoonNeural", "gender": "male", "note": "젊은 남성 (내레이터용)"},
    {"name": "ko-KR-BongJinNeural", "gender": "male", "note": ""},
    {"name": "ko-KR-GookMinNeural", "gender": "male", "note": ""},
    {"name": "ko-KR-HyunsuNeural", "gender": "male", "note": ""},
    {"name": "ko-KR-HyunsuMultilingualNeural", "gender": "male", "note": ""},
    {"name": "ko-KR-SunHiNeural", "gender": "female", "note": ""},
    {"name": "ko-KR-JiMinNeural", "gender": "female", "note": ""},
    {"name": "ko-KR-SeoHyeonNeural", "gender": "female", "note": ""},
    {"name": "ko-KR-SoonBokNeural", "gender": "female", "note": ""},
    {"name": "ko-KR-YuJinNeural", "gender": "female", "note": ""},
]
VOICE_NAMES = {v["name"] for v in VOICES}


@dataclass
class Settings:
    root: Path
    image_price_usd: float = 0.067   # estimate per generated image; check the provider's current price
    daily_cap_usd: float = 2.0
    # Only answer requests addressed to localhost: blocks DNS-rebinding pages from driving paid actions.
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(Path(os.environ.get("SHORTS_DATA", ".data")),
                   float(os.environ.get("SHORTS_IMAGE_PRICE_USD", "0.067")),
                   float(os.environ.get("SHORTS_DAILY_CAP_USD", "2.0")))


@dataclass
class Deps:
    """Vendor hooks, replaceable in tests."""
    image_provider: Callable = field(default=lambda model: GeminiImageProvider(model))
    voice_provider: Callable = field(default=lambda cache: AzureVoiceProvider(cache))
    render_fn: Callable = field(default=render_storyboard)


class ShotPatch(BaseModel):
    text: str | None = Field(None, max_length=300)
    who: str | None = None
    camera: str | None = None
    highlight: list[str] | None = None
    scene: str | None = Field(None, max_length=1500)
    min_dur: float | None = Field(None, ge=0.5, le=15)


class VoiceBody(BaseModel):
    voice: str
    rate: str = "0%"
    pitch: str = "0%"


class PreviewBody(BaseModel):
    text: str = Field("", max_length=300)


class RegenBody(BaseModel):
    confirm: bool = False


class RenderBody(BaseModel):
    only: list[int] | None = None


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    deps = deps or Deps()
    store = ProjectStore(settings.root)
    jobs = JobManager()
    ledger = SpendLedger(settings.root / "spend.jsonl")
    spend_lock = threading.Lock()
    tts_cache = settings.root / "cache" / "tts"
    app = FastAPI(title="shorts-studio local dashboard")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.exception_handler(NotFound)
    def _not_found(_req, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": f"not found: {exc.args[0]}"}, status_code=404)

    def shot_view(sb: Storyboard, shot, pid: str) -> dict:
        img = store.image_path(pid, shot.n)
        return {**asdict(shot), "has_image": img is not None,
                "image_version": int(img.stat().st_mtime) if img else None,
                "phrases": split_phrases(shot.text)}

    def project_payload(pid: str) -> dict:
        sb = store.load(pid)
        s = store.settings(pid)
        return {"id": pid, "title": sb.title, "logline": sb.logline,
                "voices": {k: asdict(v) for k, v in sb.voices.items()},
                "characters": sb.characters, "style": sb.style, "place": sb.place,
                "cameras": list(CAMERAS),
                "shots": [shot_view(sb, sh, pid) for sh in sb.shots],
                "issues": [{"level": i.level, "shot": i.shot, "message": i.message} for i in lint(sb)],
                "settings": {"model": s["model"], "char_refs": s["char_refs"], "shot_refs": s["shot_refs"]}}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return {"image_price_usd": settings.image_price_usd, "daily_cap_usd": settings.daily_cap_usd,
                "spent_today_usd": ledger.today_total(),
                "keys": {"azure": bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")),
                         "gemini": bool(os.environ.get("GEMINI_API_KEY"))}}

    @app.get("/api/projects")
    def list_projects() -> list[dict]:
        out = []
        for pid in store.ids():
            sb = store.load(pid)
            have = sum(1 for sh in sb.shots if store.image_path(pid, sh.n))
            out.append({"id": pid, "title": sb.title, "logline": sb.logline, "shots": len(sb.shots), "images": have})
        return out

    @app.get("/api/projects/{pid}")
    def get_project(pid: str) -> dict:
        return project_payload(pid)

    @app.patch("/api/projects/{pid}/shots/{n}")
    def patch_shot(pid: str, n: int, patch: ShotPatch) -> dict:
        sb = store.load(pid)
        shot = sb.shot(n)
        if shot is None:
            raise HTTPException(404, f"shot {n} not found")
        fields = patch.model_dump(exclude_unset=True)
        if "camera" in fields and fields["camera"] not in CAMERAS:
            raise HTTPException(422, f"camera must be one of {list(CAMERAS)}")
        if "who" in fields and fields["who"] and fields["who"] not in sb.voices:
            raise HTTPException(422, f"speaker '{fields['who']}' has no voice; known: {list(sb.voices)}")
        for key, value in fields.items():
            if key in ("text", "scene") and value is not None:
                value = value.strip()
            if key == "highlight" and value is not None:
                value = [h.strip() for h in value if h.strip()]
            setattr(shot, key, value if value is not None or key == "min_dur" else getattr(shot, key))
        store.save(pid, sb)
        return shot_view(sb, shot, pid)

    @app.put("/api/projects/{pid}/voices/{who}")
    def set_voice(pid: str, who: str, body: VoiceBody) -> dict:
        sb = store.load(pid)
        if who not in sb.voices:
            raise HTTPException(404, f"speaker '{who}' not found")
        if body.voice not in VOICE_NAMES or not RATE_RE.match(body.rate) or not RATE_RE.match(body.pitch):
            raise HTTPException(422, "unknown voice or invalid rate/pitch (e.g. '-10%')")
        old = sb.voices[who]
        sb.voices[who] = type(old)(old.provider, body.voice, body.rate, body.pitch)
        store.save(pid, sb)
        return asdict(sb.voices[who])

    @app.post("/api/subtitles/preview")
    def preview(body: PreviewBody) -> dict:
        return {"phrases": split_phrases(body.text)}

    @app.get("/api/projects/{pid}/images/{n}")
    def get_image(pid: str, n: int, w: int | None = None):
        path = store.image_path(pid, n)
        if path is None:
            raise HTTPException(404, "no image for this shot")
        if w is None:
            return FileResponse(path, media_type="image/png")
        w = max(120, min(int(w), 1080))
        thumb = settings.root / "cache" / "thumbs" / f"{pid}_{n}_{int(path.stat().st_mtime)}_{w}.jpg"
        if not thumb.exists():
            thumb.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((w, int(w * 2.2)))
                rgb.save(thumb, "JPEG", quality=84)
        return FileResponse(thumb, media_type="image/jpeg")

    @app.get("/api/voices")
    def list_voices() -> list[dict]:
        return VOICES

    @app.get("/api/voices/sample")
    def voice_sample(voice: str, rate: str = "-10%", text: str = SAMPLE_TEXT):
        if voice not in VOICE_NAMES or not RATE_RE.match(rate) or not (0 < len(text) <= 120):
            raise HTTPException(422, "unknown voice, invalid rate, or text longer than 120 characters")
        from ..models import VoiceSpec
        try:
            wav = deps.voice_provider(tts_cache).synthesize(text, VoiceSpec("azure", voice, rate, "0%"))
        except ProviderError as e:
            raise HTTPException(503, str(e)) from e
        return FileResponse(wav, media_type="audio/wav")

    @app.post("/api/projects/{pid}/shots/{n}/regenerate", status_code=202)
    def regenerate(pid: str, n: int, body: RegenBody) -> dict:
        sb = store.load(pid)
        shot = sb.shot(n)
        if shot is None:
            raise HTTPException(404, f"shot {n} not found")
        est = settings.image_price_usd
        if not body.confirm:
            raise HTTPException(400, {"message": "confirm required", "estimated_usd": est})
        s = store.settings(pid)
        images_dir = store.images_dir(pid)
        char_refs = {c: images_dir / f for c, f in s["char_refs"].items() if (images_dir / f).exists()}
        shot_refs = {int(k): [images_dir / f for f in v if (images_dir / f).exists()]
                     for k, v in s["shot_refs"].items()}
        items = plan_generation(sb, DirectoryImageSource(images_dir), char_refs, shot_refs, {n}, {n})
        model = s["model"]

        def work(report) -> str:
            report(f"generating shot {n} with {model}", 0.05)
            try:
                run_generation(items, deps.image_provider(model), images_dir, model,
                               log=lambda line: report(line, 0.9))
            except Exception:
                ledger.record(pid, n, -est, "refund")  # nothing was produced, give the reservation back
                raise
            return f"cut{n:02d}.png"

        with spend_lock:  # check, reserve and start atomically so quick repeated clicks cannot overshoot the cap
            if jobs.active(pid, f"regenerate-{n}"):
                raise HTTPException(409, f"shot {n} is already being regenerated")
            spent = ledger.today_total()
            if spent + est > settings.daily_cap_usd:
                raise HTTPException(429, {"message": "daily spend cap reached", "spent_today_usd": spent,
                                          "daily_cap_usd": settings.daily_cap_usd})
            ledger.record(pid, n, est, "reserve")
            job = jobs.submit(f"regenerate-{n}", pid, work)
        return job.public() | {"estimated_usd": est}

    @app.post("/api/projects/{pid}/render", status_code=202)
    def start_render(pid: str, body: RenderBody) -> dict:
        sb = store.load(pid)
        images_dir = store.images_dir(pid)
        only = set(body.only) if body.only else None
        total = sum(1 for sh in sb.shots if (only is None or sh.n in only) and store.image_path(pid, sh.n))
        if total == 0:
            raise HTTPException(422, "no shot has an image to render")
        out = store.renders_dir(pid) / time.strftime("render-%Y%m%d-%H%M%S.mp4")

        def work(report) -> str:
            done = 0

            def log(line: str) -> None:
                nonlocal done
                if line.startswith("shot"):
                    done += 1
                report(line, min(done / total, 0.95))

            opts = RenderOptions(work_dir=store.work_dir(pid))
            voices = deps.voice_provider(tts_cache)
            deps.render_fn(sb, DirectoryImageSource(images_dir), voices, out, opts, only, log)
            return out.name

        with spend_lock:
            if jobs.active(pid, "render"):
                raise HTTPException(409, "a render is already running for this project")
            return jobs.submit("render", pid, work).public()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        return job.public()

    @app.get("/api/projects/{pid}/jobs")
    def project_jobs(pid: str) -> list[dict]:
        store.dir(pid)
        return [j.public() for j in jobs.list(pid)]

    @app.get("/api/projects/{pid}/renders")
    def list_renders(pid: str) -> list[dict]:
        files = sorted(store.renders_dir(pid).glob("render-*.mp4"), reverse=True)
        return [{"name": f.name, "bytes": f.stat().st_size, "created": f.stat().st_mtime} for f in files]

    @app.get("/api/projects/{pid}/renders/{name}")
    def get_render(pid: str, name: str):
        if not RENDER_RE.match(name):
            raise HTTPException(404, "not found")
        path = store.renders_dir(pid) / name
        if not path.exists():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="video/mp4", filename=name)

    return app
