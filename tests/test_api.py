import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path

from PIL import Image

HAVE_API = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None
if HAVE_API:
    from fastapi.testclient import TestClient

    from shorts_studio.api.app import Deps, Settings, create_app
    from shorts_studio.api.store import ProjectStore
    from shorts_studio.providers import ProviderError

STORYBOARD = {
    "title": "테스트", "logline": "l",
    "voices": {"narrator": {"provider": "azure", "voice": "ko-KR-InJoonNeural", "rate": "+22%", "pitch": "0%"},
               "grandpa": {"provider": "azure", "voice": "ko-KR-BongJinNeural", "rate": "-10%", "pitch": "0%"}},
    "style": "STYLE", "place": "PLACE", "characters": {"grandpa": "OLD MAN"},
    "shots": [{"n": 1, "who": "narrator", "text": "저기, 오늘은 두 개네요?", "chars": [], "camera": "push_in",
               "highlight": ["두 개"], "scene": "scene one"},
              {"n": 2, "who": "grandpa", "text": "집사람 몫이야.", "chars": ["grandpa"], "camera": "static",
               "highlight": [], "scene": "scene two"},
              {"n": 3, "who": "", "text": "", "chars": [], "camera": "static", "highlight": [],
               "scene": "no image yet"}],
}


class FakeImages:
    def __init__(self):
        self.calls = []
        self.hold = None   # threading.Event: make generation wait until released
        self.fail = False

    def __call__(self, model):
        outer = self

        class P:
            def generate(self, prompt, refs, out_path):
                outer.calls.append((model, prompt, list(refs)))
                if outer.hold is not None:
                    outer.hold.wait(5)
                if outer.fail:
                    raise ProviderError("quota exceeded")
                Image.new("RGB", (16, 28), "blue").save(out_path)
                return out_path
        return P()


class FakeVoice:
    fail = False

    def __call__(self, cache):
        cache = Path(cache)

        class V:
            def synthesize(self_inner, text, spec):
                if FakeVoice.fail:
                    raise ProviderError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must be set")
                cache.mkdir(parents=True, exist_ok=True)
                p = cache / f"{abs(hash((text, spec.voice, spec.rate)))}.wav"
                with wave.open(str(p), "wb") as w:
                    w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
                    w.writeframes(b"\x00\x00" * 12000)
                return p
        return V()


@unittest.skipUnless(HAVE_API, "fastapi/httpx not installed (pip install -e .[api,dev])")
class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._stops = []
        self.addCleanup(lambda: [stop() for stop in self._stops])
        root = Path(self.tmp.name)
        sb = root / "sb.json"
        sb.write_text(json.dumps(STORYBOARD, ensure_ascii=False), encoding="utf-8")
        imgs = root / "imgs"
        imgs.mkdir()
        for n in (1, 2):
            Image.new("RGB", (572, 1024), "gray").save(imgs / f"cut{n:02d}.png")
        self.store = ProjectStore(root / "data")
        self.store.create("demo", sb, imgs, {"char_refs": {"grandpa": "cut02.png"}})
        self.images = FakeImages()
        self.render_hold = None
        self.render_calls = []

        def fake_render(sb_, images, voices, out, opts, only, log):
            if self.render_hold is not None:
                self.render_hold.wait(5)
            for sh in sb_.shots:
                if images.path_for(sh) and (only is None or sh.n in only):
                    log(f"shot{sh.n:02d} @ 0.0s")
            Path(out).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
            self.render_calls.append(only)

        self.settings = Settings(root / "data", image_price_usd=0.05, daily_cap_usd=0.12,
                                 allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, FakeVoice(), fake_render))

    def use_app(self, deps, settings=None):
        """Replace the app under test. Apps on the same data folder share one job queue, so the previous app's
        workers are stopped first (and every app's workers are stopped before the temp folder is removed)."""
        for stop in self._stops:
            stop()
        self._stops.clear()
        app = create_app(settings or self.settings, deps)
        self._stops.append(app.state.stop_workers)
        self.client = TestClient(app)
        return self.client

    def wait_job(self, job_id, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in ("done", "failed"):
                return job
            time.sleep(0.05)
        self.fail("job did not finish")


class Basics(ApiTest):
    def test_settings_never_expose_key_values(self):
        os.environ["GEMINI_API_KEY"] = "SUPER-SECRET-VALUE"
        os.environ["AZURE_SPEECH_KEY"], os.environ["AZURE_SPEECH_REGION"] = "ANOTHER-SECRET", "koreacentral"
        self.addCleanup(lambda: [os.environ.pop(k, None)
                                 for k in ("GEMINI_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION")])
        r = self.client.get("/api/settings")
        self.assertEqual(r.json()["keys"], {"azure": True, "gemini": True})
        self.assertNotIn("SECRET", r.text)

    def test_list_and_get_project(self):
        listing = self.client.get("/api/projects").json()
        self.assertEqual(listing, [{"id": "demo", "title": "테스트", "logline": "l", "shots": 3, "images": 2}])
        p = self.client.get("/api/projects/demo").json()
        self.assertEqual([s["has_image"] for s in p["shots"]], [True, True, False])
        self.assertEqual(p["shots"][0]["phrases"], ["저기 오늘은 두 개네요?"])
        self.assertIn("push_in", p["cameras"])

    def test_only_localhost_hosts_are_served(self):
        # a page on another domain that resolves to 127.0.0.1 (DNS rebinding) sends its own Host header
        self.assertEqual(self.client.get("/api/health", headers={"host": "evil.example.com"}).status_code, 400)
        self.assertEqual(self.client.get("/api/health", headers={"host": "localhost:8765"}).status_code, 200)

    def test_json_content_type_is_required_for_actions(self):
        # a cross-site form post cannot send application/json without a CORS preflight, so it must be refused
        r = self.client.post("/api/projects/demo/render", content=b'{"only": null}',
                             headers={"content-type": "text/plain"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get("/api/projects/demo/jobs").json(), [])

    def test_unknown_and_unsafe_project_ids_are_404(self):
        for pid in ("nope", "..", "demo%2F..%2F..", "UPPER", ".data"):
            self.assertEqual(self.client.get(f"/api/projects/{pid}").status_code, 404, pid)

    def test_subtitle_preview(self):
        r = self.client.post("/api/subtitles/preview", json={"text": "그래서 대신, 뜨거운 물을 두 컵 부었다."})
        self.assertEqual(r.json()["phrases"], ["그래서 대신 뜨거운 물을", "두 컵 부었다"])


class Editing(ApiTest):
    def test_patch_persists_and_keeps_a_backup(self):
        r = self.client.patch("/api/projects/demo/shots/1", json={"text": "  새 대사  ", "camera": "pull_out",
                                                                   "highlight": ["새", " "]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["text"], "새 대사")
        saved = json.loads((self.store.dir("demo") / "storyboard.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["shots"][0]["camera"], "pull_out")
        self.assertEqual(saved["shots"][0]["highlight"], ["새"])
        bak = json.loads((self.store.dir("demo") / "storyboard.json.bak").read_text(encoding="utf-8"))
        self.assertEqual(bak["shots"][0]["text"], "저기, 오늘은 두 개네요?")

    def test_patch_validation(self):
        self.assertEqual(self.client.patch("/api/projects/demo/shots/1", json={"camera": "spin"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/projects/demo/shots/1", json={"who": "ghost"}).status_code, 422)
        self.assertEqual(self.client.patch("/api/projects/demo/shots/9", json={"text": "x"}).status_code, 404)
        self.assertEqual(self.client.patch("/api/projects/demo/shots/1", json={"text": "x" * 301}).status_code, 422)
        self.assertEqual(self.client.patch("/api/projects/demo/shots/1", json={"min_dur": 99}).status_code, 422)

    def test_untouched_fields_stay(self):
        self.client.patch("/api/projects/demo/shots/2", json={"scene": "changed"})
        shot = self.client.get("/api/projects/demo").json()["shots"][1]
        self.assertEqual(shot["text"], "집사람 몫이야.")
        self.assertEqual(shot["scene"], "changed")

    def test_set_voice(self):
        ok = self.client.put("/api/projects/demo/voices/grandpa",
                             json={"voice": "ko-KR-GookMinNeural", "rate": "-12%", "pitch": "0%"})
        self.assertEqual(ok.json()["voice"], "ko-KR-GookMinNeural")
        self.assertEqual(self.client.get("/api/projects/demo").json()["voices"]["grandpa"]["rate"], "-12%")

    def test_set_voice_rejects_bad_input(self):
        for body in ({"voice": "not-a-voice"}, {"voice": "ko-KR-GookMinNeural", "rate": "fast"},
                     {"voice": "ko-KR-GookMinNeural", "rate": "-10%'><evil"}):
            self.assertEqual(self.client.put("/api/projects/demo/voices/grandpa", json=body).status_code, 422)
        ghost = self.client.put("/api/projects/demo/voices/ghost", json={"voice": "ko-KR-GookMinNeural"})
        self.assertEqual(ghost.status_code, 404)


class Media(ApiTest):
    def test_image_and_thumbnail(self):
        full = self.client.get("/api/projects/demo/images/1")
        self.assertEqual(full.headers["content-type"], "image/png")
        thumb = self.client.get("/api/projects/demo/images/1?w=200")
        self.assertEqual(thumb.headers["content-type"], "image/jpeg")
        from io import BytesIO
        self.assertLessEqual(Image.open(BytesIO(thumb.content)).width, 200)
        self.assertEqual(self.client.get("/api/projects/demo/images/3").status_code, 404)

    def test_voice_sample(self):
        r = self.client.get("/api/voices/sample", params={"voice": "ko-KR-BongJinNeural"})
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "audio/wav"))
        self.assertEqual(self.client.get("/api/voices/sample", params={"voice": "evil"}).status_code, 422)
        too_long = self.client.get("/api/voices/sample", params={"voice": "ko-KR-BongJinNeural", "text": "가" * 121})
        self.assertEqual(too_long.status_code, 422)

    def test_voice_sample_provider_error_is_503(self):
        FakeVoice.fail = True
        self.addCleanup(lambda: setattr(FakeVoice, "fail", False))
        r = self.client.get("/api/voices/sample", params={"voice": "ko-KR-BongJinNeural"})
        self.assertEqual(r.status_code, 503)
        self.assertIn("AZURE_SPEECH_KEY", r.json()["detail"])


class Regenerate(ApiTest):
    def test_needs_explicit_confirmation_and_shows_cost(self):
        r = self.client.post("/api/projects/demo/shots/1/regenerate", json={})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"]["estimated_usd"], 0.05)
        self.assertEqual(self.images.calls, [])

    def test_regenerates_keeps_previous_and_records_spend(self):
        r = self.client.post("/api/projects/demo/shots/2/regenerate", json={"confirm": True})
        self.assertEqual(r.status_code, 202)
        job = self.wait_job(r.json()["id"])
        self.assertEqual(job["state"], "done", job)
        d = self.store.images_dir("demo")
        self.assertTrue((d / "cut02_prev.png").exists())
        self.assertEqual(Image.open(d / "cut02.png").size, (16, 28))
        _model, prompt, refs = self.images.calls[0]
        self.assertIn("OLD MAN", prompt)
        self.assertEqual([p.name for p in refs], ["cut02.png"])  # the configured grandpa reference
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0.05)

    def test_daily_cap_stops_spending(self):
        for _ in range(2):  # 0.05 + 0.05 = 0.10 <= 0.12
            r = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True})
            self.assertEqual(self.wait_job(r.json()["id"])["state"], "done")
        r = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(len(self.images.calls), 2)


class SpendGuards(ApiTest):
    def test_failed_generation_gives_the_reservation_back(self):
        self.images.fail = True
        r = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True})
        job = self.wait_job(r.json()["id"])
        self.assertEqual(job["state"], "failed")
        self.assertIn("quota exceeded", job["error"])
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0)
        # the original image is untouched
        self.assertEqual(Image.open(self.store.images_dir("demo") / "cut01.png").size, (572, 1024))

    def test_same_shot_cannot_be_regenerated_twice_at_once(self):
        self.images.hold = threading.Event()
        first = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True})
        self.assertEqual(first.status_code, 202)
        again = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True})
        self.assertEqual(again.status_code, 409)
        self.images.hold.set()
        self.assertEqual(self.wait_job(first.json()["id"])["state"], "done")
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0.05)

    def test_rapid_requests_cannot_overshoot_the_cap(self):
        self.images.hold = threading.Event()  # nothing has finished when the later requests arrive
        responses = [self.client.post(f"/api/projects/demo/shots/{n}/regenerate", json={"confirm": True})
                     for n in (1, 2, 3)]
        self.assertEqual([r.status_code for r in responses], [202, 202, 429])  # cap 0.12: two of 0.05, not three
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0.10)
        self.images.hold.set()
        for r in responses[:2]:  # let the worker threads finish before the temp folder is removed
            self.wait_job(r.json()["id"])


class Rendering(ApiTest):
    def test_render_job_lists_and_serves_the_file(self):
        r = self.client.post("/api/projects/demo/render", json={})
        self.assertEqual(r.status_code, 202)
        job = self.wait_job(r.json()["id"])
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(job["progress"], 1.0)
        listing = self.client.get("/api/projects/demo/renders").json()
        self.assertEqual(listing[0]["name"], job["result"])
        got = self.client.get(f"/api/projects/demo/renders/{job['result']}")
        self.assertEqual((got.status_code, got.headers["content-type"]), (200, "video/mp4"))

    def test_second_render_while_running_is_409(self):
        self.render_hold = threading.Event()
        first = self.client.post("/api/projects/demo/render", json={})
        time.sleep(0.2)
        self.assertEqual(self.client.post("/api/projects/demo/render", json={}).status_code, 409)
        self.render_hold.set()
        self.assertEqual(self.wait_job(first.json()["id"])["state"], "done")

    def test_render_only_selected_shots(self):
        job = self.wait_job(self.client.post("/api/projects/demo/render", json={"only": [2]}).json()["id"])
        self.assertEqual(job["state"], "done")
        self.assertEqual(self.render_calls[-1], {2})

    def test_render_without_images_is_rejected(self):
        self.assertEqual(self.client.post("/api/projects/demo/render", json={"only": [3]}).status_code, 422)

    def test_render_name_is_validated(self):
        for name in ("../storyboard.json", "evil.mp4", "render-1.mp4"):
            self.assertEqual(self.client.get(f"/api/projects/demo/renders/{name}").status_code, 404)

    def test_failed_job_reports_the_error(self):
        def boom(*a, **k):
            raise RuntimeError("ffmpeg exploded")
        c = self.use_app(Deps(self.images, FakeVoice(), boom))
        jid = c.post("/api/projects/demo/render", json={}).json()["id"]
        end = time.time() + 10
        while time.time() < end:
            job = c.get(f"/api/jobs/{jid}").json()
            if job["state"] != "running" and job["state"] != "queued":
                break
            time.sleep(0.05)
        self.assertEqual(job["state"], "failed")
        self.assertIn("ffmpeg exploded", job["error"])


class FaceCheck(ApiTest):
    def client_with(self, embedder):
        return self.use_app(Deps(self.images, FakeVoice(), lambda *a, **k: None, embedder))

    @staticmethod
    def fake_embedder(shot_vec):
        """Reference image (cut02) and the shot image are the same file here; shot_vec decides what the shot shows."""
        import numpy as np

        from shorts_studio.vision.faces import Face

        class E:
            def embed_all(self, path):
                vec = shot_vec if Path(path).name != "cut02.png" or shot_vec is None else [1.0, 0.0]
                return [] if vec is None else [Face(np.array(vec), 0.99, (0, 0, 100, 200))]
        return lambda: E()

    def test_matching_face_is_ok(self):
        r = self.client_with(self.fake_embedder([1.0, 0.0])).post("/api/projects/demo/face-check")
        self.assertEqual(r.status_code, 200, r.text)
        checks = r.json()["checks"]
        self.assertEqual([c["shot"] for c in checks], [2])   # only shots that feature a reference character
        self.assertEqual(checks[0]["status"], "ok")
        self.assertEqual(checks[0]["faces"][0]["character"], "grandpa")

    def test_face_that_matches_nobody_is_flagged(self):
        # the reference file and the shot file are the same image, so make the reference vector differ by name
        import numpy as np

        from shorts_studio.vision.faces import Face
        calls = []

        class E:
            def embed_all(self, path):
                calls.append(Path(path).name)
                return [Face(np.array([1.0, 0.0] if len(calls) == 1 else [0.0, 1.0]), 0.99, (0, 0, 100, 200))]
        r = self.client_with(lambda: E()).post("/api/projects/demo/face-check")
        self.assertEqual(r.json()["checks"][0]["status"], "drift?")

    def test_shot_without_a_face(self):
        import numpy as np

        from shorts_studio.vision.faces import Face
        calls = []

        class E:
            def embed_all(self, path):
                calls.append(1)
                return [Face(np.array([1.0, 0.0]), 0.99, (0, 0, 100, 200))] if len(calls) == 1 else []
        r = self.client_with(lambda: E()).post("/api/projects/demo/face-check")
        self.assertEqual(r.json()["checks"][0]["status"], "no face")

    def test_needs_reference_images(self):
        self.store.save_settings("demo", {**self.store.settings("demo"), "char_refs": {}})
        r = self.client_with(self.fake_embedder([1.0, 0.0])).post("/api/projects/demo/face-check")
        self.assertEqual(r.status_code, 422)

    def test_missing_vision_support_is_a_clear_503(self):
        def no_cv2():
            raise ImportError("No module named 'cv2'")
        r = self.client_with(no_cv2).post("/api/projects/demo/face-check")
        self.assertEqual(r.status_code, 503)
        self.assertIn("not available", r.json()["detail"])

    def test_unknown_project_is_404(self):
        self.assertEqual(self.client.post("/api/projects/nope/face-check").status_code, 404)


class Ownership(ApiTest):
    """Every request belongs to one owner; one owner must never see or touch another's projects or jobs."""

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        for who in ("alice", "bob"):
            ProjectStore(root / "data", who).create("demo", root / "sb.json", root / "imgs",
                                                    {"char_refs": {"grandpa": "cut02.png"}})

        def render(sb_, images, voices, out, opts, only, log):
            Path(out).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        deps = Deps(self.images, FakeVoice(), render, owner=lambda request: request.headers.get("x-user", ""))
        self.use_app(deps)

    def as_(self, who):
        return {"x-user": who}

    def test_each_owner_sees_only_their_own_projects(self):
        ProjectStore(Path(self.tmp.name) / "data", "alice").create(
            "alices-only", Path(self.tmp.name) / "sb.json", Path(self.tmp.name) / "imgs")
        alice = [p["id"] for p in self.client.get("/api/projects", headers=self.as_("alice")).json()]
        bob = [p["id"] for p in self.client.get("/api/projects", headers=self.as_("bob")).json()]
        self.assertEqual(alice, ["alices-only", "demo"])
        self.assertEqual(bob, ["demo"])
        self.assertEqual(self.client.get("/api/projects/alices-only", headers=self.as_("bob")).status_code, 404)

    def test_same_project_id_is_independent_per_owner(self):
        r = self.client.patch("/api/projects/demo/shots/1", json={"text": "alice edit"}, headers=self.as_("alice"))
        self.assertEqual(r.status_code, 200)
        bob = self.client.get("/api/projects/demo", headers=self.as_("bob")).json()
        self.assertEqual(bob["shots"][0]["text"], "저기, 오늘은 두 개네요?")

    def test_other_owners_job_looks_missing(self):
        job = self.client.post("/api/projects/demo/render", json={}, headers=self.as_("alice")).json()
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}", headers=self.as_("alice")).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}", headers=self.as_("bob")).status_code, 404)
        self.assertEqual(self.client.get("/api/projects/demo/jobs", headers=self.as_("bob")).json(), [])

    def test_a_running_render_of_one_owner_does_not_block_the_other(self):
        self.render_hold = None
        first = self.client.post("/api/projects/demo/render", json={}, headers=self.as_("alice"))
        second = self.client.post("/api/projects/demo/render", json={}, headers=self.as_("bob"))
        self.assertEqual((first.status_code, second.status_code), (202, 202))

    def test_missing_or_malformed_identity_is_rejected(self):
        for who in ("", "../alice", "a/b", "x" * 80):
            r = self.client.get("/api/projects", headers=self.as_(who))
            self.assertEqual(r.status_code, 401, who)

    def test_owner_id_cannot_escape_the_data_folder(self):
        for bad in ("..", "../x", "a/b", "", "a b"):
            with self.assertRaises(ValueError):
                ProjectStore(Path(self.tmp.name) / "data", bad)

    def test_local_owner_keeps_the_original_folder_layout(self):
        local = Path(self.tmp.name) / "data" / "projects" / "demo" / "storyboard.json"
        self.assertTrue(local.exists())
        self.assertTrue((Path(self.tmp.name) / "data" / "users" / "alice" / "projects" / "demo").exists())


class BgmStyle(ApiTest):
    def setUp(self):
        super().setUp()
        self.styles_seen = []
        self.labels_seen = []

        def render(sb_, images, voices, out, opts, only, log):
            self.styles_seen.append(opts.bgm_style)
            self.labels_seen.append(opts.ai_label)
            Path(out).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        self.use_app(Deps(self.images, FakeVoice(), render))

    def test_lists_the_available_styles_with_labels(self):
        styles = self.client.get("/api/bgm-styles").json()
        self.assertEqual({s["name"] for s in styles}, {"night_piano", "warm_major", "tense_low"})
        self.assertTrue(all(s["label"] for s in styles))

    def test_render_uses_the_chosen_style_and_defaults_to_the_original(self):
        job = self.client.post("/api/projects/demo/render", json={"bgm_style": "tense_low"}).json()
        self.wait_job(job["id"])
        job = self.client.post("/api/projects/demo/render", json={}).json()
        self.wait_job(job["id"])
        self.assertEqual(self.styles_seen, ["tense_low", "night_piano"])

    def test_the_ai_label_is_on_by_default_and_can_be_switched_off(self):
        self.wait_job(self.client.post("/api/projects/demo/render", json={}).json()["id"])
        self.wait_job(self.client.post("/api/projects/demo/render", json={"ai_label": False}).json()["id"])
        self.assertEqual(self.labels_seen, [True, False])

    def test_unknown_style_is_rejected_before_anything_runs(self):
        r = self.client.post("/api/projects/demo/render", json={"bgm_style": "jazz"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.styles_seen, [])


class DurableJobs(ApiTest):
    def queue(self):
        from shorts_studio.api.jobqueue import JobQueue
        return JobQueue(self.settings.root / "jobs.sqlite3")

    def test_a_finished_job_is_still_there_after_the_api_restarts(self):
        job = self.wait_job(self.client.post("/api/projects/demo/render", json={}).json()["id"])
        self.assertEqual(job["state"], "done")
        self.use_app(Deps(self.images, FakeVoice(), lambda *a, **k: None))   # a fresh API process on the same folder
        again = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual((again["state"], again["result"]), ("done", job["result"]))
        self.assertEqual(len(self.client.get("/api/projects/demo/jobs").json()), 1)

    def test_a_regeneration_orphaned_by_a_crash_is_failed_and_its_reservation_refunded(self):
        import contextlib
        import sqlite3

        from shorts_studio.api.ledger import CreditLedger
        ledger = CreditLedger(self.settings.root / "ledger.sqlite3")
        for stop in self._stops:                                        # the running app would claim the job itself
            stop()
        self._stops.clear()
        res = ledger.reserve("local", "demo", 1, 0.05, daily_cap_usd=1.0)   # the crashed API had reserved the spend
        job = self.queue().submit("regenerate-1", "demo", "local", {"n": 1, "est": 0.05, "reservation": res.id})
        self.queue().claim("crashed-worker")
        with contextlib.closing(sqlite3.connect(self.settings.root / "jobs.sqlite3")) as c, c:
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - 600, job.id))
        self.assertEqual(ledger.today_total("local"), 0.05)

        self.use_app(Deps(self.images, FakeVoice(), lambda *a, **k: None))   # restart: workers recover stale jobs
        got = self.wait_job(job.id)
        self.assertEqual(got["state"], "failed")
        self.assertEqual(ledger.today_total("local"), 0.0)                   # reservation given back exactly once
        self.assertEqual(self.client.get("/api/settings").json()["spent_today_usd"], 0.0)
        time.sleep(0.5)
        self.assertEqual(ledger.today_total("local"), 0.0)                   # and not refunded again by later passes

    def test_api_without_workers_queues_and_a_separate_worker_runs_the_job(self):
        from dataclasses import replace

        from shorts_studio.api.handlers import JobContext, handle
        from shorts_studio.api.ledger import CreditLedger
        from shorts_studio.api.worker import Worker

        rendered = []

        def render(sb_, images, voices, out, opts, only, log):
            rendered.append(opts.bgm_style)
            Path(out).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        settings = replace(self.settings, embedded_workers=0)
        self.use_app(Deps(self.images, FakeVoice(), render), settings)
        queued = self.client.post("/api/projects/demo/render", json={"bgm_style": "warm_major"}).json()
        time.sleep(0.6)
        self.assertEqual(self.client.get(f"/api/jobs/{queued['id']}").json()["state"], "queued")  # nobody runs it

        ledger = CreditLedger(settings.root / "ledger.sqlite3")
        ctx = JobContext(settings.root, ledger, self.images, FakeVoice(), render)
        Worker(self.queue(), lambda job, report: handle(ctx, job, report), name="other-process").run_one()
        job = self.client.get(f"/api/jobs/{queued['id']}").json()
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(rendered, ["warm_major"])
        self.assertEqual(self.client.get("/api/projects/demo/renders").json()[0]["name"], job["result"])


class UserLimits(ApiTest):
    """Spend caps are per user, and an optional monthly budget is shared by everyone."""

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        for who in ("alice", "bob"):
            ProjectStore(root / "data", who).create("demo", root / "sb.json", root / "imgs")
        self.deps = Deps(self.images, FakeVoice(), lambda *a, **k: None,
                         owner=lambda request: request.headers.get("x-user", ""))
        self.use_app(self.deps)

    def regen(self, who, n):
        r = self.client.post(f"/api/projects/demo/shots/{n}/regenerate", json={"confirm": True},
                             headers={"x-user": who})
        if r.status_code == 202:
            self.wait_as(who, r.json()["id"])
        return r

    def wait_as(self, who, job_id, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            job = self.client.get(f"/api/jobs/{job_id}", headers={"x-user": who}).json()
            if job["state"] in ("done", "failed"):
                return job
            time.sleep(0.05)
        self.fail("job did not finish")

    def spent(self, who):
        return self.client.get("/api/settings", headers={"x-user": who}).json()["spent_today_usd"]

    def test_one_users_cap_does_not_block_another_user(self):
        self.assertEqual(self.regen("alice", 1).status_code, 202)
        self.assertEqual(self.regen("alice", 2).status_code, 202)
        denied = self.regen("alice", 1)                       # cap 0.12, price 0.05: a third image does not fit
        self.assertEqual(denied.status_code, 429)
        self.assertIn("daily", denied.json()["detail"]["message"])
        self.assertEqual(self.regen("bob", 1).status_code, 202)
        self.assertEqual((self.spent("alice"), self.spent("bob")), (0.10, 0.05))

    def test_a_failed_generation_gives_the_money_back_to_the_right_user(self):
        self.images.fail = True
        self.assertEqual(self.regen("alice", 1).status_code, 202)
        self.assertEqual((self.spent("alice"), self.spent("bob")), (0.0, 0.0))

    def test_monthly_budget_pauses_everyone(self):
        from dataclasses import replace
        self.use_app(self.deps, replace(self.settings, monthly_cap_usd=0.07))
        self.assertEqual(self.regen("alice", 1).status_code, 202)
        denied = self.regen("bob", 1)
        self.assertEqual(denied.status_code, 429)
        self.assertIn("monthly", denied.json()["detail"]["message"])
        self.assertEqual(self.spent("bob"), 0.0)

    def test_two_quick_clicks_for_the_same_shot_cost_once(self):
        self.images.hold = threading.Event()
        first = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True},
                                 headers={"x-user": "alice"})
        second = self.client.post("/api/projects/demo/shots/1/regenerate", json={"confirm": True},
                                  headers={"x-user": "alice"})
        self.images.hold.set()
        self.wait_as("alice", first.json()["id"])
        self.assertEqual((first.status_code, second.status_code), (202, 409))
        self.assertEqual(self.spent("alice"), 0.05)


if __name__ == "__main__":
    unittest.main()
