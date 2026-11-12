import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from shorts_studio.api import demo, voices
from shorts_studio.models import Storyboard

HAVE_API = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None
if HAVE_API:
    from fastapi.testclient import TestClient

    from shorts_studio.api.app import Deps, Settings, create_app

REAL_DEMO = Path(__file__).resolve().parents[1] / "demo"
STORYBOARD = {
    "title": "데모", "logline": "l",
    "voices": {"narrator": {"provider": "azure", "voice": "ko-KR-InJoonNeural", "rate": "0%", "pitch": "0%"}},
    "style": "S", "place": "P", "characters": {},
    "shots": [{"n": n, "who": "narrator", "text": f"대사 {n}", "chars": [], "camera": "static", "highlight": [],
               "scene": "a quiet street"} for n in (1, 2, 3)],
}
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 200
FACE = {"threshold": 0.363, "checks": [{"shot": 2, "status": "ok", "expected": ["grandpa"], "faces": []}]}


def boom(*args, **kwargs):
    raise AssertionError("a provider was called in demo mode")


def make_demo_dir(root: Path) -> Path:
    d = root / "demo"
    (d / "project" / "images").mkdir(parents=True)
    (d / "project" / "renders").mkdir()
    (d / "voice_samples").mkdir()
    (d / "project" / "storyboard.json").write_text(json.dumps(STORYBOARD, ensure_ascii=False), encoding="utf-8")
    (d / "project" / "project.json").write_text(json.dumps({"model": "m", "char_refs": {}, "shot_refs": {}}))
    for n in (1, 2, 3):
        Image.new("RGB", (54, 96), (n * 60, 90, 120)).save(d / "project" / "images" / f"cut{n:02d}.jpg")
    (d / "project" / "renders" / demo.DEMO_RENDER).write_bytes(VIDEO)
    (d / "voice_samples" / "ko-KR-BongJinNeural.mp3").write_bytes(b"ID3demo-audio")
    (d / "face_check.json").write_text(json.dumps(FACE), encoding="utf-8")
    return d


class Helpers(unittest.TestCase):
    def test_rate_limiter_is_a_sliding_window_per_client(self):
        now = [0.0]
        limiter = demo.RateLimiter(3, window=60, clock=lambda: now[0])
        self.assertEqual([limiter.allow("a") for _ in range(4)], [True, True, True, False])
        self.assertTrue(limiter.allow("b"))          # another visitor is unaffected
        now[0] = 61
        self.assertTrue(limiter.allow("a"))          # the window has slid past the old hits

    def test_rate_limiter_forgets_quiet_clients(self):
        now = [0.0]
        limiter = demo.RateLimiter(1, window=10, clock=lambda: now[0])
        for i in range(demo.MAX_TRACKED_CLIENTS + 5):
            limiter.allow(f"client-{i}")
        now[0] = 100
        limiter.allow("fresh")
        self.assertLess(len(limiter._hits), 10)

    def test_seed_needs_the_assets_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                demo.seed(root / "data", root / "nowhere")
            d = make_demo_dir(root)
            demo.seed(root / "data", d)
            marker = root / "data" / "projects" / demo.DEMO_PROJECT / "storyboard.json"
            self.assertTrue(marker.exists())
            marker.write_text(marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
            demo.seed(root / "data", d)                         # a restart does not overwrite
            self.assertTrue(marker.read_text(encoding="utf-8").endswith(" "))

    def test_simulations_report_progress_and_never_sleep_in_tests(self):
        lines = []
        name = demo.simulate_regenerate(7, lambda line, p=None: lines.append(p), sleep=lambda s: None)
        self.assertEqual(name, "cut07.jpg")
        self.assertEqual(lines, sorted(lines))
        seen = []
        self.assertEqual(demo.simulate_render([1, 2], lambda line, p=None: seen.append(p), sleep=lambda s: None),
                         demo.DEMO_RENDER)
        self.assertEqual(seen, [0.5, 0.95])   # progress never reaches 1.0 before the job itself finishes
        self.assertEqual(demo.simulate_render([], lambda *a: None, sleep=lambda s: None), demo.DEMO_RENDER)


class RealBundle(unittest.TestCase):
    """The committed demo/ folder is complete and consistent."""

    @unittest.skipUnless((REAL_DEMO / "project" / "storyboard.json").exists(), "demo assets not built")
    def test_every_shot_has_an_image_every_voice_a_sample_and_the_video_exists(self):
        sb = Storyboard.load(REAL_DEMO / "project" / "storyboard.json")
        for shot in sb.shots:
            self.assertTrue((REAL_DEMO / "project" / "images" / f"cut{shot.n:02d}.jpg").exists(), shot.n)
        for voice in voices.VOICES:
            self.assertTrue((REAL_DEMO / "voice_samples" / f"{voice.name}.mp3").exists(), voice.name)
        self.assertTrue((REAL_DEMO / "project" / "renders" / demo.DEMO_RENDER).exists())
        faces = demo.face_check(REAL_DEMO)
        self.assertEqual({c["shot"] for c in faces["checks"]} - {s.n for s in sb.shots}, set())
        self.assertLess(sum(f.stat().st_size for f in REAL_DEMO.rglob("*") if f.is_file()), 12_000_000)

    @unittest.skipUnless((REAL_DEMO / "project" / "storyboard.json").exists(), "demo assets not built")
    def test_the_bundled_story_passes_input_screening(self):
        from shorts_studio.safety import check_storyboard
        self.assertEqual(check_storyboard(Storyboard.load(REAL_DEMO / "project" / "storyboard.json")), [])


@unittest.skipUnless(HAVE_API, "needs fastapi and httpx")
class DemoApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings = Settings(root / "data", demo=True, demo_dir=make_demo_dir(root), demo_rate_limit=1000,
                                 allowed_hosts=("testserver",))
        app = create_app(self.settings, Deps(boom, boom, boom, boom))   # every provider explodes if touched
        self.addCleanup(app.state.stop_workers)
        self.client = TestClient(app)
        self.base = f"/api/projects/{demo.DEMO_PROJECT}"

    def wait(self, job_id):
        end = time.time() + 15
        while time.time() < end:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in ("done", "failed"):
                return job
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_settings_say_demo_enable_the_buttons_and_show_no_spending(self):
        s = self.client.get("/api/settings").json()
        self.assertEqual((s["demo"], s["keys"], s["spent_today_usd"], s["image_price_usd"]),
                         (True, {"azure": True, "gemini": True}, 0.0, 0.0))

    def test_the_seeded_project_and_its_jpg_images_are_served(self):
        project = self.client.get(self.base).json()
        self.assertEqual([s["has_image"] for s in project["shots"]], [True, True, True])
        r = self.client.get(f"{self.base}/images/1")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(self.client.get(f"{self.base}/images/1?w=200").status_code, 200)

    def test_edits_are_refused_and_nothing_changes(self):
        r = self.client.patch(f"{self.base}/shots/1", json={"text": "바뀐 대사"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("읽기 전용", r.json()["detail"]["message"])
        v = self.client.put(f"{self.base}/voices/narrator", json={"voice": "ko-KR-BongJinNeural", "rate": "0%"})
        self.assertEqual(v.status_code, 403)
        shots = self.client.get(self.base).json()["shots"]
        self.assertEqual(shots[0]["text"], "대사 1")

    def test_live_subtitle_preview_and_voice_recommendation_still_work(self):
        self.assertEqual(self.client.post("/api/subtitles/preview", json={"text": "저기, 오늘은 두 개네요?"}).json(),
                         {"phrases": ["저기 오늘은 두 개네요?"]})
        r = self.client.get("/api/voices/recommend", params={"gender": "male", "age": "senior"})
        self.assertEqual(r.status_code, 200)

    def test_regeneration_is_replayed_without_a_provider_or_a_charge(self):
        r = self.client.post(f"{self.base}/shots/2/regenerate", json={"confirm": True})
        self.assertEqual((r.status_code, r.json()["estimated_usd"]), (202, 0.0))
        job = self.wait(r.json()["id"])
        self.assertEqual((job["state"], job["result"]), ("done", "cut02.jpg"))
        self.assertTrue(any("실제 이미지 호출 없음" in line for line in job["log"]))
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0.0)

    def test_regeneration_still_needs_confirmation(self):
        r = self.client.post(f"{self.base}/shots/2/regenerate", json={"confirm": False})
        self.assertEqual(r.status_code, 400)

    def test_render_is_replayed_and_the_prebuilt_video_is_served(self):
        r = self.client.post(f"{self.base}/render", json={})
        self.assertEqual(r.status_code, 202)
        job = self.wait(r.json()["id"])
        self.assertEqual((job["state"], job["result"]), ("done", demo.DEMO_RENDER))
        listing = self.client.get(f"{self.base}/renders").json()
        self.assertEqual([x["name"] for x in listing], [demo.DEMO_RENDER])
        video = self.client.get(f"{self.base}/renders/{demo.DEMO_RENDER}")
        self.assertEqual((video.status_code, video.headers["content-type"], video.content), (200, "video/mp4", VIDEO))

    def test_voice_samples_are_premade_files(self):
        r = self.client.get("/api/voices/sample", params={"voice": "ko-KR-BongJinNeural", "rate": "-20%"})
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "audio/mpeg", b"ID3demo-audio"))
        self.assertEqual(self.client.get("/api/voices/sample", params={"voice": "ko-KR-SunHiNeural"}).status_code, 404)
        self.assertEqual(self.client.get("/api/voices/sample", params={"voice": "evil"}).status_code, 422)

    def test_face_check_returns_the_precomputed_result(self):
        self.assertEqual(self.client.post(f"{self.base}/face-check").json(), FACE)
        self.assertEqual(self.client.post("/api/projects/nope/face-check").status_code, 404)


@unittest.skipUnless(HAVE_API, "needs fastapi and httpx")
class DemoRateLimit(unittest.TestCase):
    def make(self, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        settings = Settings(root / "data", demo=True, demo_dir=make_demo_dir(root), allowed_hosts=("testserver",), **kw)
        app = create_app(settings, Deps(boom, boom, boom, boom))
        self.addCleanup(app.state.stop_workers)
        return TestClient(app)

    def test_changing_requests_are_limited_but_reading_is_not(self):
        client = self.make(demo_rate_limit=3)
        post = lambda: client.post("/api/subtitles/preview", json={"text": "a"}).status_code  # noqa: E731
        self.assertEqual([post() for _ in range(5)], [200, 200, 200, 429, 429])
        self.assertEqual(client.get("/api/health").status_code, 200)
        r = client.post("/api/subtitles/preview", json={"text": "a"})
        self.assertEqual(r.headers["retry-after"], "60")
        for _ in range(20):
            self.assertEqual(client.get("/api/projects").status_code, 200)

    def test_behind_a_trusted_proxy_each_forwarded_client_has_its_own_budget(self):
        client = self.make(demo_rate_limit=2, trust_proxy=True)

        def post(ip):
            headers = {"x-forwarded-for": f"9.9.9.9, {ip}"}   # a client-supplied first hop, then the proxy's view
            return client.post("/api/subtitles/preview", json={"text": "a"}, headers=headers)
        self.assertEqual([post("1.1.1.1").status_code for _ in range(3)], [200, 200, 429])
        self.assertEqual(post("2.2.2.2").status_code, 200)      # a different visitor behind the same proxy

    def test_without_a_trusted_proxy_the_forwarded_header_cannot_be_used_to_dodge_the_limit(self):
        client = self.make(demo_rate_limit=2)
        codes = [client.post("/api/subtitles/preview", json={"text": "a"},
                             headers={"x-forwarded-for": f"7.7.7.{i}"}).status_code for i in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])


if __name__ == "__main__":
    unittest.main()
