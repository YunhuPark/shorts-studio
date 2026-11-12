"""FastAPI app for the local dashboard.

Single user, bound to localhost by `shorts-studio serve`. API keys come from environment variables and are
never returned to the browser (only whether they are set). Paid actions need an explicit confirm and stop at a
daily estimated-spend cap.
"""
from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from pydantic import BaseModel, Field

from ..models import CAMERAS, Storyboard
from ..providers import AzureVoiceProvider, DirectoryImageSource, GeminiImageProvider, ProviderError
from ..qa import lint
from ..render import render as render_storyboard
from ..render.bgm import DEFAULT_STYLE as DEFAULT_BGM_STYLE
from ..render.bgm import STYLES as BGM_STYLES
from ..render.subtitles import split_phrases
from ..safety import blocking_issues
from ..vision.faces import check_shots, checks_payload
from ..vision.fetch import ModelError
from . import demo as demo_mode
from . import voices as voices_catalog
from .auth import AuthConfig, make_owner_resolver
from .handlers import JobContext, handle, refund_orphan
from .jobqueue import JobQueue
from .ledger import CreditLedger
from .store import LOCAL_OWNER, OWNER, NotFound, ProjectStore
from .worker import start_threads

VOICE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural$")
RATE_RE = re.compile(r"^[+-]?\d{1,3}%$")
RENDER_RE = re.compile(r"^render-\d{8}-\d{6}\.mp4$")
SAMPLE_TEXT = "오늘이 우리 결혼기념일이라서. 집사람 몫이야."
VOICE_NAMES = voices_catalog.NAMES


@dataclass
class Settings:
    root: Path
    image_price_usd: float = 0.067   # estimate per generated image; check the provider's current price
    daily_cap_usd: float = 2.0       # per user
    monthly_cap_usd: float = 0.0     # all users together; 0 = no monthly budget
    # Only answer requests addressed to localhost: blocks DNS-rebinding pages from driving paid actions.
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    auth: AuthConfig | None = None   # None: one fixed local user (safe only on localhost); else verify login tokens
    embedded_workers: int = 2        # job threads inside the API process; 0 = run separate `worker` processes
    demo: bool = False               # public demo: no provider is ever called, edits are not saved (see api/demo.py)
    demo_dir: Path = Path("demo")
    demo_rate_limit: int = 30        # changing requests per minute per client in demo mode
    trust_proxy: bool = False        # behind one trusted reverse proxy: take the client address from X-Forwarded-For

    @classmethod
    def from_env(cls) -> Settings:
        hosts = tuple(h.strip() for h in os.environ.get("SHORTS_ALLOWED_HOSTS", "").split(",") if h.strip())
        extra: dict = {"allowed_hosts": hosts} if hosts else {}   # hosted: the public host name(s) of the site
        if os.environ.get("SHORTS_DEMO") == "1":
            extra |= {"demo": True, "demo_dir": Path(os.environ.get("SHORTS_DEMO_DIR", "demo")),
                      "demo_rate_limit": int(os.environ.get("SHORTS_DEMO_RATE", "30")),
                      "trust_proxy": os.environ.get("SHORTS_TRUST_PROXY") == "1"}
        return cls(Path(os.environ.get("SHORTS_DATA", ".data")),
                   float(os.environ.get("SHORTS_IMAGE_PRICE_USD", "0.067")),
                   float(os.environ.get("SHORTS_DAILY_CAP_USD", "2.0")),
                   float(os.environ.get("SHORTS_MONTHLY_CAP_USD", "0")),
                   auth=AuthConfig.from_env(), **extra)


@dataclass
class Deps:
    """Vendor hooks, replaceable in tests."""
    image_provider: Callable = field(default=lambda model: GeminiImageProvider(model))
    voice_provider: Callable = field(default=lambda cache: AzureVoiceProvider(cache))
    render_fn: Callable = field(default=render_storyboard)
    embedder: Callable = field(default=lambda: _opencv_embedder())
    # Who is calling? Local mode has one fixed user; a hosted deployment plugs in token verification here and
    # returns the authenticated user id (or raises HTTPException 401).
    owner: Callable[[Request], str] = field(default=lambda request: LOCAL_OWNER)


def _opencv_embedder():
    """Needs the optional `vision` extra and the models from `fetch-models`."""
    from ..vision.faces import OpenCVEmbedder
    return OpenCVEmbedder()


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
    bgm_style: str = DEFAULT_BGM_STYLE
    ai_label: bool = True   # the dashboard discloses AI generation unless the user switches it off


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    deps = deps or Deps()
    stores: dict[str, ProjectStore] = {}
    resolve_owner = make_owner_resolver(settings.auth) if settings.auth else deps.owner
    jobs = JobQueue(settings.root / "jobs.sqlite3")
    ledger = CreditLedger(settings.root / "ledger.sqlite3", legacy_jsonl=settings.root / "spend.jsonl")
    stores_lock = threading.Lock()
    face_lock = threading.Lock()  # one face check at a time: it is CPU heavy
    tts_cache = settings.root / "cache" / "tts"
    app = FastAPI(title="shorts-studio local dashboard")
    ctx = JobContext(settings.root, ledger, deps.image_provider, deps.voice_provider, deps.render_fn)
    app.state.stop_workers = lambda: None
    if settings.embedded_workers > 0:  # `serve --no-worker` leaves the queue to separate `worker` processes
        stop, threads = start_threads(jobs, lambda job, report: handle(ctx, job, report),
                                      lambda job: refund_orphan(ctx, job), settings.embedded_workers)

        def stop_workers() -> None:
            stop.set()
            for t in threads:
                t.join(timeout=5)
        app.state.stop_workers = stop_workers
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    if settings.demo:
        demo_mode.seed(settings.root, settings.demo_dir)
        limiter = demo_mode.RateLimiter(settings.demo_rate_limit)

        @app.middleware("http")
        async def demo_rate_limit(request: Request, call_next):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                client = request.client.host if request.client else "unknown"
                if settings.trust_proxy:   # one trusted proxy appends the real address last
                    client = request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or client
                if not limiter.allow(client):
                    return JSONResponse({"detail": {"message": "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요."}},
                                        status_code=429, headers={"Retry-After": "60"})
            return await call_next(request)

    @app.exception_handler(NotFound)
    def _not_found(_req, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": f"not found: {exc.args[0]}"}, status_code=404)

    def writable() -> None:
        if settings.demo:
            raise HTTPException(403, {"message": demo_mode.READ_ONLY_MESSAGE})

    def get_owner(request: Request) -> str:
        owner = resolve_owner(request)
        if not isinstance(owner, str) or not OWNER.match(owner):
            raise HTTPException(401, "not signed in")
        return owner

    def get_store(owner: str = Depends(get_owner)) -> ProjectStore:
        with stores_lock:
            if owner not in stores:
                stores[owner] = ProjectStore(settings.root, owner)
            return stores[owner]

    def shot_view(store: ProjectStore, sb: Storyboard, shot, pid: str) -> dict:
        img = store.image_path(pid, shot.n)
        return {**asdict(shot), "has_image": img is not None,
                "image_version": int(img.stat().st_mtime) if img else None,
                "phrases": split_phrases(shot.text)}

    def project_payload(store: ProjectStore, pid: str) -> dict:
        sb = store.load(pid)
        s = store.settings(pid)
        return {"id": pid, "title": sb.title, "logline": sb.logline,
                "voices": {k: asdict(v) for k, v in sb.voices.items()},
                "characters": sb.characters, "style": sb.style, "place": sb.place,
                "cameras": list(CAMERAS),
                "shots": [shot_view(store, sb, sh, pid) for sh in sb.shots],
                "issues": [{"level": i.level, "shot": i.shot, "message": i.message} for i in lint(sb)],
                "settings": {"model": s["model"], "char_refs": s["char_refs"], "shot_refs": s["shot_refs"]}}

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings(owner: str = Depends(get_owner)) -> dict:
        if settings.demo:   # buttons stay enabled; nothing behind them is real
            return {"image_price_usd": 0.0, "daily_cap_usd": settings.daily_cap_usd, "spent_today_usd": 0.0,
                    "keys": {"azure": True, "gemini": True}, "demo": True}
        return {"image_price_usd": settings.image_price_usd, "daily_cap_usd": settings.daily_cap_usd,
                "spent_today_usd": ledger.today_total(owner),
                "keys": {"azure": bool(os.environ.get("AZURE_SPEECH_KEY") and os.environ.get("AZURE_SPEECH_REGION")),
                         "gemini": bool(os.environ.get("GEMINI_API_KEY"))}}

    @app.get("/api/projects")
    def list_projects(store: ProjectStore = Depends(get_store)) -> list[dict]:
        out = []
        for pid in store.ids():
            sb = store.load(pid)
            have = sum(1 for sh in sb.shots if store.image_path(pid, sh.n))
            out.append({"id": pid, "title": sb.title, "logline": sb.logline, "shots": len(sb.shots), "images": have})
        return out

    @app.get("/api/projects/{pid}")
    def get_project(pid: str, store: ProjectStore = Depends(get_store)) -> dict:
        return project_payload(store, pid)

    @app.patch("/api/projects/{pid}/shots/{n}")
    def patch_shot(pid: str, n: int, patch: ShotPatch, store: ProjectStore = Depends(get_store),
                   _writable: None = Depends(writable)) -> dict:
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
        return shot_view(store, sb, shot, pid)

    @app.put("/api/projects/{pid}/voices/{who}")
    def set_voice(pid: str, who: str, body: VoiceBody, store: ProjectStore = Depends(get_store),
                  _writable: None = Depends(writable)) -> dict:
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
    def preview(body: PreviewBody, owner: str = Depends(get_owner)) -> dict:
        return {"phrases": split_phrases(body.text)}

    @app.get("/api/projects/{pid}/images/{n}")
    def get_image(pid: str, n: int, w: int | None = None, store: ProjectStore = Depends(get_store)):
        path = store.image_path(pid, n)
        if path is None:
            raise HTTPException(404, "no image for this shot")
        if w is None:
            return FileResponse(path, media_type="image/jpeg" if path.suffix == ".jpg" else "image/png")
        w = max(120, min(int(w), 1080))
        thumb = settings.root / "cache" / "thumbs" / f"{pid}_{n}_{int(path.stat().st_mtime)}_{w}.jpg"
        if not thumb.exists():
            thumb.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as im:
                rgb = im.convert("RGB")
                rgb.thumbnail((w, int(w * 2.2)))
                rgb.save(thumb, "JPEG", quality=84)
        return FileResponse(thumb, media_type="image/jpeg")

    @app.get("/api/bgm-styles")
    def list_bgm_styles(owner: str = Depends(get_owner)) -> list[dict]:
        return [{"name": k, "label": v.label} for k, v in BGM_STYLES.items()]

    @app.get("/api/voices")
    def list_voices(owner: str = Depends(get_owner)) -> list[dict]:
        return [{"name": v.name, "gender": v.gender, "note": v.note, "pitch_hz": v.pitch_hz}
                for v in voices_catalog.VOICES]

    @app.get("/api/voices/recommend")
    def recommend_voices(gender: str, age: str, owner: str = Depends(get_owner)) -> dict:
        try:
            return voices_catalog.recommend(gender, age)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/voices/sample")
    def voice_sample(voice: str, rate: str = "-10%", text: str = SAMPLE_TEXT, owner: str = Depends(get_owner)):
        if voice not in VOICE_NAMES or not RATE_RE.match(rate) or not (0 < len(text) <= 120):
            raise HTTPException(422, "unknown voice, invalid rate, or text longer than 120 characters")
        if settings.demo:   # a pre-made sample, whatever the speed/text asked for
            sample = demo_mode.voice_sample(settings.demo_dir, voice)
            if sample is None:
                raise HTTPException(404, "this voice has no demo sample")
            return FileResponse(sample, media_type="audio/mpeg")
        from ..models import VoiceSpec
        try:
            wav = deps.voice_provider(tts_cache).synthesize(text, VoiceSpec("azure", voice, rate, "0%"))
        except ProviderError as e:
            raise HTTPException(503, str(e)) from e
        return FileResponse(wav, media_type="audio/wav")

    @app.post("/api/projects/{pid}/shots/{n}/regenerate", status_code=202)
    def regenerate(pid: str, n: int, body: RegenBody, store: ProjectStore = Depends(get_store)) -> dict:
        sb = store.load(pid)
        shot = sb.shot(n)
        if shot is None:
            raise HTTPException(404, f"shot {n} not found")
        blocked = blocking_issues(sb, n)
        if blocked:  # nothing is reserved or sent to the image provider
            raise HTTPException(422, {"message": "; ".join(dict.fromkeys(i.message for i in blocked)),
                                      "issues": [{"shot": i.shot, "message": i.message} for i in blocked]})
        est = 0.0 if settings.demo else settings.image_price_usd
        if not body.confirm:
            raise HTTPException(400, {"message": "confirm required", "estimated_usd": est})
        kind = f"regenerate-{n}"
        if jobs.active(pid, kind, store.owner):
            raise HTTPException(409, f"shot {n} is already being regenerated")
        if settings.demo:   # replay only: no reservation, no provider
            job = jobs.submit_unique(kind, pid, store.owner, {"n": n, "est": 0.0, "demo": True})
            if job is None:
                raise HTTPException(409, f"shot {n} is already being regenerated")
            return job.public() | {"estimated_usd": 0.0}
        res = ledger.reserve(store.owner, pid, n, est, settings.daily_cap_usd, settings.monthly_cap_usd)
        if res.id is None:
            if res.reason == "monthly":
                raise HTTPException(429, {"message": "monthly budget reached; new paid work is paused"})
            raise HTTPException(429, {"message": "daily spend cap reached", "spent_today_usd": res.spent_today_usd,
                                      "daily_cap_usd": settings.daily_cap_usd})
        job = jobs.submit_unique(kind, pid, store.owner, {"n": n, "est": est, "reservation": res.id})
        if job is None:  # the same shot was queued in between (another tab or process): give the money back
            ledger.refund(res.id)
            raise HTTPException(409, f"shot {n} is already being regenerated")
        return job.public() | {"estimated_usd": est}

    @app.post("/api/projects/{pid}/render", status_code=202)
    def start_render(pid: str, body: RenderBody, store: ProjectStore = Depends(get_store)) -> dict:
        if body.bgm_style not in BGM_STYLES:
            raise HTTPException(422, f"unknown bgm style; choose one of {sorted(BGM_STYLES)}")
        sb = store.load(pid)
        blocked = blocking_issues(sb)
        if blocked:
            raise HTTPException(422, {"message": "; ".join(dict.fromkeys(i.message for i in blocked)),
                                      "issues": [{"shot": i.shot, "message": i.message} for i in blocked]})
        only = set(body.only) if body.only else None
        total = sum(1 for sh in sb.shots if (only is None or sh.n in only) and store.image_path(pid, sh.n))
        if total == 0:
            raise HTTPException(422, "no shot has an image to render")
        job = jobs.submit_unique("render", pid, store.owner,
                                 {"only": sorted(only) if only else None, "bgm_style": body.bgm_style,
                                  "ai_label": body.ai_label, **({"demo": True} if settings.demo else {})})
        if job is None:
            raise HTTPException(409, "a render is already running for this project")
        return job.public()

    @app.post("/api/projects/{pid}/face-check")
    def face_check(pid: str, store: ProjectStore = Depends(get_store)) -> dict:
        """Free, local: compares the faces in each shot with the project's character reference images."""
        if settings.demo:   # computed once with the real models (scripts/build_demo_assets.py)
            store.dir(pid)
            return demo_mode.face_check(settings.demo_dir)
        sb = store.load(pid)
        images_dir = store.images_dir(pid)
        refs = {c: images_dir / f for c, f in store.settings(pid)["char_refs"].items() if (images_dir / f).exists()}
        if not refs:
            raise HTTPException(422, "no character reference images are set for this project")
        with face_lock:
            try:
                embedder = deps.embedder()
                checks = check_shots(sb, DirectoryImageSource(images_dir), refs, embedder)
            except (ImportError, ModelError) as e:
                raise HTTPException(503, f"face check is not available: {e}") from e
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
        return checks_payload(checks)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, owner: str = Depends(get_owner)) -> dict:
        job = jobs.get(job_id)
        if job is None or job.owner != owner:  # another user's job looks the same as a missing one
            raise HTTPException(404, "job not found")
        return job.public()

    @app.get("/api/projects/{pid}/jobs")
    def project_jobs(pid: str, store: ProjectStore = Depends(get_store)) -> list[dict]:
        store.dir(pid)
        return [j.public() for j in jobs.list(pid, store.owner)]

    @app.get("/api/projects/{pid}/renders")
    def list_renders(pid: str, store: ProjectStore = Depends(get_store)) -> list[dict]:
        files = sorted(store.renders_dir(pid).glob("render-*.mp4"), reverse=True)
        return [{"name": f.name, "bytes": f.stat().st_size, "created": f.stat().st_mtime} for f in files]

    @app.get("/api/projects/{pid}/renders/{name}")
    def get_render(pid: str, name: str, store: ProjectStore = Depends(get_store)):
        if not RENDER_RE.match(name):
            raise HTTPException(404, "not found")
        path = store.renders_dir(pid) / name
        if not path.exists():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type="video/mp4", filename=name)

    return app
