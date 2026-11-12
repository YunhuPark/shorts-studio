"""Dashboard API with fake image / voice / render providers and a seeded demo project, for browser tests.

Nothing here talks to a paid service or uses a real key. Run: python tests/e2e_server.py --port 8766
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import imageio_ffmpeg
import uvicorn
from PIL import Image, ImageDraw

from shorts_studio.api.app import Deps, Settings, create_app
from shorts_studio.api.store import ProjectStore

STORYBOARD = {
    "title": "데모 프로젝트", "logline": "브라우저 테스트용 가짜 프로젝트",
    "voices": {"narrator": {"provider": "azure", "voice": "ko-KR-InJoonNeural", "rate": "+22%", "pitch": "0%"},
               "grandpa": {"provider": "azure", "voice": "ko-KR-BongJinNeural", "rate": "-10%", "pitch": "0%"}},
    "style": "STYLE", "place": "PLACE", "characters": {"grandpa": "OLD MAN"},
    "shots": [
        {"n": 1, "who": "narrator", "text": "저기, 오늘은 두 개네요?", "chars": [], "camera": "push_in",
         "highlight": ["두 개"], "scene": "scene one"},
        {"n": 2, "who": "grandpa", "text": "오늘이 우리 결혼기념일이라서.", "chars": ["grandpa"], "camera": "static",
         "highlight": ["결혼기념일"], "scene": "scene two"},
        {"n": 3, "who": "", "text": "", "chars": [], "camera": "static", "highlight": [], "scene": "silent beat"},
        {"n": 4, "who": "narrator", "text": "하지만 할아버지는 오지 않았다.", "chars": [], "camera": "pull_out",
         "highlight": [], "scene": "no image yet"},
    ],
}


def draw_image(path: Path, label: str, color: str) -> None:
    im = Image.new("RGB", (192, 344), color)
    ImageDraw.Draw(im).text((12, 12), label, fill="white")
    im.save(path)


def make_fixture_video(path: Path) -> None:
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=96x160:d=1:r=10",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-shortest", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", str(path)], check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--demo", action="store_true", help="serve the real demo/ bundle in demo mode (no providers)")
    args = ap.parse_args()
    port = args.port

    if args.demo:   # the public demo exactly as it ships: no keys, no fake providers, real pre-built assets
        root = Path(tempfile.mkdtemp(prefix="shorts-e2e-demo-"))
        demo_dir = Path(__file__).resolve().parents[1] / "demo"
        settings = Settings(root / "data", demo=True, demo_dir=demo_dir, demo_rate_limit=1000)
        print(f"e2e DEMO API on http://127.0.0.1:{port} (data {root})", flush=True)
        uvicorn.run(create_app(settings, Deps()), host="127.0.0.1", port=port, log_level="warning")
        return

    # the UI enables buttons only when keys exist; these are fakes and are never sent anywhere
    os.environ.update(AZURE_SPEECH_KEY="e2e-fake", AZURE_SPEECH_REGION="e2e", GEMINI_API_KEY="e2e-fake")

    root = Path(tempfile.mkdtemp(prefix="shorts-e2e-"))
    sb_file = root / "storyboard.json"
    sb_file.write_text(json.dumps(STORYBOARD, ensure_ascii=False), encoding="utf-8")
    images = root / "seed_images"
    images.mkdir()
    for n, color in ((1, "#304060"), (2, "#406040"), (3, "#604040")):
        draw_image(images / f"cut{n:02d}.png", f"shot {n}", color)
    store = ProjectStore(root / "data")
    store.create("demo", sb_file, images, {"char_refs": {"grandpa": "cut02.png"}})
    fixture = root / "fixture.mp4"
    make_fixture_video(fixture)

    class FakeImages:
        def __call__(self, model):
            class P:
                def generate(self, prompt, refs, out_path):
                    time.sleep(0.8)
                    draw_image(out_path, f"regenerated {time.strftime('%H:%M:%S')}", "#805020")
                    later = time.time() + 10  # make the image version visibly change
                    os.utime(out_path, (later, later))
                    return out_path
            return P()

    class FakeVoice:
        def __call__(self, cache):
            cache = Path(cache)

            class V:
                def synthesize(self, text, spec):
                    cache.mkdir(parents=True, exist_ok=True)
                    p = cache / f"{abs(hash((text, spec.voice, spec.rate)))}.wav"
                    with wave.open(str(p), "wb") as w:
                        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
                        w.writeframes(b"\x00\x00" * 24000)
                    return p
            return V()

    def fake_render(sb, images_src, voices, out, opts, only, log):
        for shot in sb.shots:
            if images_src.path_for(shot):
                time.sleep(0.4)
                log(f"shot{shot.n:02d} rendered")
        Path(out).write_bytes(fixture.read_bytes())

    class FakeEmbedder:
        def embed_all(self, path):  # every image shows one face that looks like the reference
            import numpy as np

            from shorts_studio.vision.faces import Face
            return [Face(np.array([1.0, 0.0]), 0.99, (0, 0, 100, 200))]

    settings = Settings(root / "data", image_price_usd=0.05, daily_cap_usd=1.0)
    print(f"e2e API on http://127.0.0.1:{port} (data {root})", flush=True)
    app = create_app(settings, Deps(FakeImages(), FakeVoice(), fake_render, FakeEmbedder))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
