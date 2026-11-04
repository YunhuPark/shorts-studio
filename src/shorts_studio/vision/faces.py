"""Objective face-consistency check: YuNet finds every face, SFace turns each into an embedding, cosine similarity
compares it with a reference image of each character.

Every face in a shot is assigned to the closest reference character. A face that matches nobody is flagged as
possible drift; very small faces are reported as too small to judge instead of being counted as drift.

SAME_PERSON_COSINE is OpenCV's published SFace decision threshold for face verification (0.363, larger = more
alike). It was set on photos; stylised or generated images, profiles and tiny faces are noisier, so treat results
as a flag for a human to look at, not as ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from ..models import Storyboard
from ..providers.base import ImageSource
from .fetch import model_path

SAME_PERSON_COSINE = 0.363
MIN_FACE_PX = 80  # below this height a face is too small for a reliable embedding


@dataclass
class Face:
    embedding: np.ndarray
    score: float
    box: tuple[float, float, float, float]  # x, y, w, h


class Embedder(Protocol):
    def embed_all(self, image_path: Path) -> list[Face]:
        """Every face found, largest first (empty list when there is none)."""


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, dtype=np.float64).ravel(), np.asarray(b, dtype=np.float64).ravel()
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


class OpenCVEmbedder:
    def __init__(self, score_threshold: float = 0.8):
        import cv2  # optional dependency: pip install -e ".[vision]"
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(str(model_path("yunet")), "", (320, 320), score_threshold, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(model_path("sface")), "")

    def embed_all(self, image_path: Path) -> list[Face]:
        cv2 = self.cv2
        # imdecode(fromfile) instead of imread so non-ASCII Windows paths work
        img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cannot read image: {image_path}")
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(img)
        if faces is None or len(faces) == 0:
            return []
        out = []
        for f in sorted(faces, key=lambda f: float(f[2] * f[3]), reverse=True):
            feature = self.recognizer.feature(self.recognizer.alignCrop(img, f))
            out.append(Face(np.asarray(feature, dtype=np.float64).ravel(), float(f[-1]),
                            (float(f[0]), float(f[1]), float(f[2]), float(f[3]))))
        return out


@dataclass
class FaceMatch:
    character: str | None  # reference character it matches, None when it matches nobody
    closest: str           # closest reference regardless of the threshold
    similarity: float      # cosine similarity to that closest reference
    height_px: float
    small: bool            # too small to judge reliably


@dataclass
class ShotCheck:
    shot: int
    expected: list[str]
    faces: list[FaceMatch]
    status: str  # "ok" | "drift?" | "small" | "no face"


def reference_embeddings(refs: dict[str, Path], embedder: Embedder) -> dict[str, np.ndarray]:
    out = {}
    for name, path in refs.items():
        faces = embedder.embed_all(path)
        if not faces:
            raise ValueError(f"no face found in the reference image for '{name}': {path}")
        out[name] = faces[0].embedding  # largest face
    return out


def check_shots(sb: Storyboard, images: ImageSource, refs: dict[str, Path], embedder: Embedder,
                threshold: float = SAME_PERSON_COSINE, min_face_px: float = MIN_FACE_PX) -> list[ShotCheck]:
    """Check every shot that features at least one reference character."""
    ref_emb = reference_embeddings(refs, embedder)
    out: list[ShotCheck] = []
    for shot in sb.shots:
        expected = [c for c in shot.chars if c in ref_emb]
        path = images.path_for(shot)
        if not expected or path is None:
            continue
        matches: list[FaceMatch] = []
        for face in embedder.embed_all(path):
            sims = {name: cosine(emb, face.embedding) for name, emb in ref_emb.items()}
            closest = max(sims, key=sims.get)
            sim = sims[closest]
            matches.append(FaceMatch(closest if sim >= threshold else None, closest, sim, face.box[3],
                                     face.box[3] < min_face_px))
        if not matches:
            status = "no face"
        elif any(m.character is None and not m.small for m in matches):
            status = "drift?"
        elif any(m.character is not None for m in matches):
            status = "ok"
        else:
            status = "small"
        out.append(ShotCheck(shot.n, expected, matches, status))
    return out
