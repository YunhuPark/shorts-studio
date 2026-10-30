"""Generate missing shot images with reference images so characters and places stay consistent."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from .models import Shot, Storyboard
from .providers.base import ImageProvider, ImageSource, ProviderError

SAME_AS_REFERENCE = ("Use exactly the same person or people, clothes, glasses, hats and the same store interior as "
                     "in the reference images (same faces, same teal-striped walls, same window bar table).")
NO_LOGO = "No brand logos, no trademarks and no readable text or signage anywhere in the image."


@dataclass
class GenItem:
    shot: Shot
    prompt: str
    refs: list[Path]
    replaces: Path | None  # existing image that will be kept as cutNN_prev.png


def plan_generation(sb: Storyboard, images: ImageSource, char_refs: dict[str, Path],
                    shot_refs: dict[int, list[Path]], shots: set[int] | None = None,
                    replace: set[int] | None = None) -> list[GenItem]:
    """Shots to make: those without an image, plus any in `replace`. `shots` limits the candidates."""
    replace = replace or set()
    items: list[GenItem] = []
    for shot in sb.shots:
        if shots is not None and shot.n not in shots:
            continue
        existing = images.path_for(shot)
        if existing is not None and shot.n not in replace:
            continue
        refs = [char_refs[c] for c in shot.chars if c in char_refs] + shot_refs.get(shot.n, [])
        prompt = " ".join(p for p in [SAME_AS_REFERENCE if refs else "", sb.image_prompt(shot), NO_LOGO] if p)
        items.append(GenItem(shot, prompt, refs, existing))
    return items


def _keep_previous(path: Path) -> Path:
    target = path.with_name(path.stem + "_prev.png")
    i = 2
    while target.exists():
        target = path.with_name(f"{path.stem}_prev{i}.png")
        i += 1
    path.rename(target)
    return target


def run_generation(items: list[GenItem], provider: ImageProvider, out_dir: Path, model: str,
                   log: Callable[[str], None] = print) -> list[Path]:
    """Make each image in order; stop at the first provider error so spending stops too."""
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for item in items:
        target = out_dir / f"cut{item.shot.n:02d}.png"
        kept = _keep_previous(target) if item.replaces is not None and target.exists() else None
        try:
            provider.generate(item.prompt, item.refs, target)
        except ProviderError as e:
            if kept is not None:  # put the original back so a failed replace loses nothing
                kept.rename(target)
            raise
        with Image.open(target) as raw:
            rgb = raw.convert("RGB")
        rgb.save(target, "PNG")
        meta = {"shot": item.shot.n, "model": model, "prompt": item.prompt,
                "refs": [str(r) for r in item.refs], "previous": str(kept) if kept else None}
        target.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"made {target.name} ({len(item.refs)} reference image(s))")
        made.append(target)
    return made
