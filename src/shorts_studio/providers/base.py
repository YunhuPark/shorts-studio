"""Provider interfaces. The renderer and CLI depend only on these, never on a vendor."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import Shot, VoiceSpec


class ProviderError(RuntimeError):
    """A vendor call failed in a way the caller should surface to the user."""


class VoiceProvider(Protocol):
    def synthesize(self, text: str, spec: VoiceSpec) -> Path:
        """Return a wav file for `text`. Identical inputs must return a cached file (no repeat charge)."""


class ImageProvider(Protocol):
    def generate(self, prompt: str, refs: list[Path], out_path: Path) -> Path:
        """Create an image for `prompt`, conditioned on reference images; write it to out_path."""


class ImageSource(Protocol):
    def path_for(self, shot: Shot) -> Path | None:
        """Existing image for a shot, or None when it has not been made yet."""
