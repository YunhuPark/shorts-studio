"""File-based project storage for the local dashboard (single user, no database).

<root>/projects/<id>/storyboard.json   the storyboard (edited by the UI; previous version kept as .bak)
                     project.json       settings: image model, reference images per character / shot
                     images/cutNN.png   shot images
                     renders/*.mp4      finished renders
                     work/              render scratch space
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..models import Storyboard

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
DEFAULT_SETTINGS = {"model": "gemini-3.1-flash-image", "char_refs": {}, "shot_refs": {}}


class NotFound(KeyError):
    pass


class ProjectStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "projects").mkdir(parents=True, exist_ok=True)

    def dir(self, pid: str) -> Path:
        if not SLUG.match(pid):
            raise NotFound(pid)
        d = self.root / "projects" / pid
        if not (d / "storyboard.json").exists():
            raise NotFound(pid)
        return d

    def ids(self) -> list[str]:
        base = self.root / "projects"
        return sorted(p.name for p in base.iterdir() if SLUG.match(p.name) and (p / "storyboard.json").exists())

    def load(self, pid: str) -> Storyboard:
        return Storyboard.load(self.dir(pid) / "storyboard.json")

    def save(self, pid: str, sb: Storyboard) -> None:
        d = self.dir(pid)
        shutil.copyfile(d / "storyboard.json", d / "storyboard.json.bak")
        sb.save(d / "storyboard.json")

    def settings(self, pid: str) -> dict:
        path = self.dir(pid) / "project.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return {**DEFAULT_SETTINGS, **data}

    def save_settings(self, pid: str, settings: dict) -> None:
        (self.dir(pid) / "project.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")

    def images_dir(self, pid: str) -> Path:
        d = self.dir(pid) / "images"
        d.mkdir(exist_ok=True)
        return d

    def renders_dir(self, pid: str) -> Path:
        d = self.dir(pid) / "renders"
        d.mkdir(exist_ok=True)
        return d

    def work_dir(self, pid: str) -> Path:
        d = self.dir(pid) / "work"
        d.mkdir(exist_ok=True)
        return d

    def image_path(self, pid: str, n: int) -> Path | None:
        p = self.images_dir(pid) / f"cut{n:02d}.png"
        return p if p.exists() else None

    def create(self, pid: str, storyboard: str | Path, images: str | Path | None = None,
               settings: dict | None = None) -> Path:
        """Create a project from an existing storyboard file (and optionally copy its images)."""
        if not SLUG.match(pid):
            raise ValueError("project id must be lowercase letters, digits and hyphens")
        d = self.root / "projects" / pid
        if d.exists():
            raise FileExistsError(f"project '{pid}' already exists")
        d.mkdir(parents=True)
        shutil.copyfile(storyboard, d / "storyboard.json")
        (d / "images").mkdir()
        if images:
            for f in sorted(Path(images).glob("cut*.png")):
                shutil.copyfile(f, d / "images" / f.name)
        self.save_settings(pid, {**DEFAULT_SETTINGS, **(settings or {})})
        return d
