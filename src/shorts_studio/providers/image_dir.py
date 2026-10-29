"""Images that already exist on disk as cutNN.png (what the prototype produced)."""
from __future__ import annotations

from pathlib import Path

from ..models import Shot


class DirectoryImageSource:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def path_for(self, shot: Shot) -> Path | None:
        p = self.directory / f"cut{shot.n:02d}.png"
        return p if p.exists() else None
