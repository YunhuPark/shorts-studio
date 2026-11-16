"""What each job kind does. Used by every worker, in the API process or a separate one.

A job carries only plain data (kind, project, owner, params); everything else (storyboard, images, settings) is
loaded here, so a worker process needs nothing from the API process.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..generate import plan_generation, run_generation
from ..providers import DirectoryImageSource
from ..render import RenderOptions
from . import demo
from .jobqueue import Job
from .ledger import CreditLedger
from .store import ProjectStore


@dataclass
class JobContext:
    root: Path
    ledger: CreditLedger
    image_provider: Callable   # model -> provider with generate(prompt, refs, out_path)
    voice_provider: Callable   # cache dir -> provider with synthesize(text, spec)
    render_fn: Callable

    @property
    def tts_cache(self) -> Path:
        return self.root / "cache" / "tts"


def handle(ctx: JobContext, job: Job, report) -> str | None:
    if job.params.get("demo"):   # set only by the API in demo mode: replay, never call a provider
        return handle_demo(ctx, job, report)
    if job.kind.startswith("regenerate-"):
        return regenerate(ctx, job, report)
    if job.kind == "generate-images":
        return generate_images(ctx, job, report)
    if job.kind == "render":
        return render(ctx, job, report)
    raise ValueError(f"unknown job kind: {job.kind}")


def handle_demo(ctx: JobContext, job: Job, report) -> str:
    if job.kind.startswith("regenerate-"):
        return demo.simulate_regenerate(int(job.params["n"]), report)
    if job.kind == "render":
        store = ProjectStore(ctx.root, job.owner)
        shots = [s.n for s in store.load(job.project).shots if store.image_path(job.project, s.n)]
        return demo.simulate_render(shots, report)
    raise ValueError(f"unknown job kind: {job.kind}")


def regenerate(ctx: JobContext, job: Job, report) -> str:
    n = int(job.params["n"])
    try:
        store = ProjectStore(ctx.root, job.owner)
        sb = store.load(job.project)
        s = store.settings(job.project)
        images_dir = store.images_dir(job.project)
        char_refs = {c: images_dir / f for c, f in s["char_refs"].items() if (images_dir / f).exists()}
        shot_refs = {int(k): [images_dir / f for f in v if (images_dir / f).exists()]
                     for k, v in s["shot_refs"].items()}
        items = plan_generation(sb, DirectoryImageSource(images_dir), char_refs, shot_refs, {n}, {n})
        model = s["model"]
        report(f"generating shot {n} with {model}", 0.05)
        run_generation(items, ctx.image_provider(model), images_dir, model, log=lambda line: report(line, 0.9))
    except Exception:
        ctx.ledger.refund(job.params.get("reservation"))  # nothing was produced, give the reservation back
        raise
    return f"cut{n:02d}.png"


def generate_images(ctx: JobContext, job: Job, report) -> str:
    """Make the missing images of a project one after another, in story order.

    In order on purpose: the first image in which a character appears becomes that character's reference, and every
    later shot with the same character is conditioned on it, which is what keeps the faces the same. Each shot was
    reserved separately by the API; a reservation is given back for every shot that did not get its image.
    """
    shots = [int(n) for n in job.params["shots"]]
    reservations = {int(n): rid for n, rid in job.params["reservations"].items()}
    made: list[int] = []
    try:
        store = ProjectStore(ctx.root, job.owner)
        sb = store.load(job.project)
        images_dir = store.images_dir(job.project)
        model = store.settings(job.project)["model"]
        provider = ctx.image_provider(model)
        source = DirectoryImageSource(images_dir)
        for i, n in enumerate(shots):
            report(f"shot {n} ({i + 1}/{len(shots)})", i / len(shots))
            s = store.settings(job.project)
            char_refs = {c: images_dir / f for c, f in s["char_refs"].items() if (images_dir / f).exists()}
            shot_refs = {int(k): [images_dir / f for f in v if (images_dir / f).exists()]
                         for k, v in s["shot_refs"].items()}
            items = plan_generation(sb, source, char_refs, shot_refs, {n}, set())
            if not items:   # an image appeared meanwhile (another tab): nothing to make, nothing to charge
                ctx.ledger.refund(reservations.get(n))
                continue
            run_generation(items, provider, images_dir, model, log=lambda line: None)
            made.append(n)
            shot = sb.shot(n)
            new_refs = [c for c in (shot.chars if shot else []) if c not in s["char_refs"]]
            if new_refs:
                s["char_refs"] = {**s["char_refs"], **{c: f"cut{n:02d}.png" for c in new_refs}}
                store.save_settings(job.project, s)
    except Exception:
        for n in shots:
            if n not in made:
                ctx.ledger.refund(reservations.get(n))
        raise
    return f"{len(made)} images"


def render(ctx: JobContext, job: Job, report) -> str:
    store = ProjectStore(ctx.root, job.owner)
    sb = store.load(job.project)
    only = set(job.params["only"]) if job.params.get("only") else None
    total = max(sum(1 for sh in sb.shots if (only is None or sh.n in only) and store.image_path(job.project, sh.n)), 1)
    out = store.renders_dir(job.project) / time.strftime("render-%Y%m%d-%H%M%S.mp4")
    done = 0

    def log(line: str) -> None:
        nonlocal done
        if line.startswith("shot"):
            done += 1
        report(line, min(done / total, 0.95))

    opts = RenderOptions(work_dir=store.work_dir(job.project), bgm_style=job.params.get("bgm_style", "night_piano"),
                         ai_label=bool(job.params.get("ai_label", False)))
    ctx.render_fn(sb, DirectoryImageSource(store.images_dir(job.project)), ctx.voice_provider(ctx.tts_cache),
                  out, opts, only, log)
    return out.name


def refund_orphan(ctx: JobContext, job: Job) -> None:
    """A worker died while generating: the reserved spend was never used."""
    if job.kind.startswith("regenerate-"):
        ctx.ledger.refund(job.params.get("reservation"))   # idempotent: never refunded twice
    elif job.kind == "generate-images":   # only the shots that never got an image: the others were really spent
        store = ProjectStore(ctx.root, job.owner)
        for n, rid in (job.params.get("reservations") or {}).items():
            try:
                has_image = store.image_path(job.project, int(n)) is not None
            except KeyError:   # the project was deleted meanwhile
                has_image = False
            if not has_image:
                ctx.ledger.refund(rid)
