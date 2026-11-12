"""Builds the small, public-safe assets of the demo (demo/): downsized images, a re-encoded video, voice samples
and the pre-computed face check.

Run once on a machine that has the full project in .data/ and the real keys (it makes ~10 short Azure Speech calls):

    python scripts/build_demo_assets.py --video output/convenience_store_final.mp4

The demo server never calls a paid API; it only serves what this script wrote. Nothing here is committed unless you
`git add demo/` yourself, and the files are far smaller than the originals (540 px images, 540x960 video).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shorts_studio.api import voices as catalog  # noqa: E402
from shorts_studio.api.app import SAMPLE_TEXT  # noqa: E402
from shorts_studio.api.store import ProjectStore  # noqa: E402
from shorts_studio.models import VoiceSpec  # noqa: E402
from shorts_studio.providers import AzureVoiceProvider, DirectoryImageSource  # noqa: E402
from shorts_studio.vision.faces import OpenCVEmbedder, check_shots, checks_payload  # noqa: E402

DEMO_RENDER = "render-20261112-000000.mp4"   # the one finished render the demo lists


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args: list[str]) -> None:
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(done.stderr[-800:])


def copy_project(store: ProjectStore, pid: str, out: Path) -> None:
    project = out / "project"
    (project / "images").mkdir(parents=True)
    src = store.dir(pid)
    shutil.copyfile(src / "storyboard.json", project / "storyboard.json")
    settings = store.settings(pid)
    (project / "project.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    sb = store.load(pid)
    for shot in sb.shots:
        path = store.image_path(pid, shot.n)
        if path is None:
            continue
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((540, 960), Image.LANCZOS)
            im.save(project / "images" / f"cut{shot.n:02d}.jpg", "JPEG", quality=80, optimize=True, progressive=True)
    print(f"images: {len(list((project / 'images').glob('*.jpg')))} jpg")


def build_video(video: Path, out: Path) -> None:
    dest = out / "project" / "renders"
    dest.mkdir(parents=True)
    run([ffmpeg(), "-y", "-i", str(video), "-vf", "scale=540:960:flags=lanczos", "-c:v", "libx264", "-crf", "30",
         "-preset", "slow", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
         str(dest / DEMO_RENDER)])
    print(f"video: {(dest / DEMO_RENDER).stat().st_size / 1e6:.1f} MB")


def build_voice_samples(out: Path) -> None:
    dest = out / "voice_samples"
    dest.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        provider = AzureVoiceProvider(cache_dir=Path(tmp))
        for voice in catalog.VOICES:
            wav = provider.synthesize(SAMPLE_TEXT, VoiceSpec("azure", voice.name, "-10%", "0%"))
            run([ffmpeg(), "-y", "-i", str(wav), "-ac", "1", "-b:a", "64k", str(dest / f"{voice.name}.mp3")])
    print(f"voice samples: {len(list(dest.glob('*.mp3')))} mp3")


def build_face_check(store: ProjectStore, pid: str, out: Path) -> None:
    images_dir = store.images_dir(pid)
    refs = {c: images_dir / f for c, f in store.settings(pid)["char_refs"].items() if (images_dir / f).exists()}
    checks = check_shots(store.load(pid), DirectoryImageSource(images_dir), refs, OpenCVEmbedder())
    (out / "face_check.json").write_text(json.dumps(checks_payload(checks), ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(f"face check: {len(checks)} shots, statuses {sorted({c.status for c in checks})}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / ".data"))
    ap.add_argument("--project", default="convenience-store")
    ap.add_argument("--video", required=True, help="the finished full-size render to shrink for the demo")
    ap.add_argument("--out", default=str(ROOT / "demo"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    store = ProjectStore(a.data)
    copy_project(store, a.project, out)
    build_video(Path(a.video), out)
    build_voice_samples(out)
    build_face_check(store, a.project, out)
    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"demo assets: {total / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    main()
