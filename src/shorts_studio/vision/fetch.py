"""Download and verify the face models (OpenCV Zoo: YuNet detector MIT, SFace recogniser Apache-2.0).

The files are stored with Git LFS upstream, so they come from media.githubusercontent.com. They are checked
against the size and sha256 that the LFS pointers publish, and kept out of git (assets/models/*.onnx).
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MEDIA = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
PROJECT_MODELS = Path(__file__).resolve().parents[3] / "assets" / "models"


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class Model:
    name: str
    filename: str
    url: str
    size: int
    sha256: str
    license: str


MODELS = {
    "yunet": Model("yunet", "face_detection_yunet_2023mar.onnx",
                   f"{MEDIA}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                   232589, "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", "MIT"),
    "sface": Model("sface", "face_recognition_sface_2021dec.onnx",
                   f"{MEDIA}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                   38696353, "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", "Apache-2.0"),
}


def models_dir() -> Path:
    return Path(os.environ.get("SHORTS_MODELS", PROJECT_MODELS))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_valid(model: Model, path: Path) -> bool:
    return path.exists() and path.stat().st_size == model.size and sha256_of(path) == model.sha256


def model_path(name: str, directory: Path | None = None) -> Path:
    """Path of a verified model, or ModelError telling how to get it."""
    model = MODELS[name]
    path = (directory or models_dir()) / model.filename
    if not is_valid(model, path):
        raise ModelError(f"model '{name}' is missing or corrupt at {path}; run `python -m shorts_studio fetch-models`")
    return path


def fetch(name: str, directory: Path | None = None, log=print) -> Path:
    """Download one model if it is not already present and valid; verify size and sha256."""
    model = MODELS[name]
    directory = directory or models_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / model.filename
    if is_valid(model, target):
        log(f"{model.filename}: already present and verified")
        return target
    log(f"downloading {model.filename} ({model.size / 1024 / 1024:.1f} MB, {model.license}) ...")
    fd, tmp_name = tempfile.mkstemp(dir=directory, suffix=".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with urllib.request.urlopen(model.url, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        if not is_valid(model, tmp):
            raise ModelError(f"{model.filename}: downloaded file failed the size/sha256 check (expected "
                             f"{model.size} bytes, got {tmp.stat().st_size})")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    log(f"{model.filename}: verified sha256 {model.sha256[:12]}...")
    return target
