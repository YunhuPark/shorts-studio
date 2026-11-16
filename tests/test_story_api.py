import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_api
from test_story import RAW

if test_api.HAVE_API:
    from shorts_studio.api.app import Deps, Settings
    from shorts_studio.providers import ProviderError


class FakeStories:
    def __init__(self):
        self.calls = []
        self.raw = copy.deepcopy(RAW)
        self.error = None

    def __call__(self, model):
        outer = self

        class P:
            def generate(self, system, prompt, schema):
                outer.calls.append((model, prompt))
                if outer.error:
                    raise outer.error
                return outer.raw
        return P()


def no_render(*args, **kwargs):
    raise AssertionError("rendering is not part of these tests")


@unittest.skipUnless(test_api.HAVE_API, "fastapi/httpx not installed (pip install -e .[api,dev])")
class StoryApi(test_api.ApiTest):
    def setUp(self):
        super().setUp()
        self.stories = FakeStories()
        self.settings = Settings(Path(self.tmp.name) / "data", image_price_usd=0.05, daily_cap_usd=1.0,
                                 story_price_usd=0.01, allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render, story_provider=self.stories))

    def spent(self):
        return self.client.get("/api/settings").json()["spent_today_usd"]

    def create(self, **body):
        return self.client.post("/api/stories", json={"prompt": "비 오는 밤 버스 정류장에서 만난 두 사람",
                                                      "shots": 6, "confirm": True, **body})

    def test_settings_describe_the_options_the_screen_needs(self):
        story = self.client.get("/api/settings").json()["story"]
        self.assertEqual(story["price_usd"], 0.01)
        self.assertEqual((story["min_shots"], story["max_shots"], story["default_shots"]), (6, 24, 12))
        self.assertIn("cinematic", [s["name"] for s in story["styles"]])

    def test_a_prompt_becomes_a_project_and_costs_the_estimate(self):
        r = self.client.post("/api/stories", json={"prompt": "비 오는 밤 버스 정류장", "shots": 6})
        self.assertEqual(r.status_code, 400)   # nothing happens without an explicit confirm
        self.assertEqual(r.json()["detail"]["estimated_usd"], 0.01)
        self.assertEqual(self.stories.calls, [])
        r = self.create(style="anime")
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]
        project = self.client.get(f"/api/projects/{pid}").json()
        self.assertEqual(project["title"], "마지막 버스")
        self.assertEqual(len(project["shots"]), 6)
        self.assertFalse(any(s["has_image"] for s in project["shots"]))   # the story only; images come next
        self.assertIn("webtoon", project["style"])
        self.assertEqual(self.spent(), 0.01)
        self.assertEqual(self.stories.calls[0][0], self.settings.story_model)

    def test_two_stories_never_share_a_project(self):
        a, b = self.create().json()["id"], self.create().json()["id"]
        self.assertNotEqual(a, b)

    def test_an_unsafe_prompt_is_refused_before_anything_is_reserved_or_sent(self):
        r = self.create(prompt="야한 이야기를 만들어 줘")
        self.assertEqual(r.status_code, 422)
        self.assertEqual((self.stories.calls, self.spent()), ([], 0.0))
        import contextlib
        import sqlite3
        with contextlib.closing(sqlite3.connect(Path(self.tmp.name) / "data" / "ledger.sqlite3")) as db:
            # not even a reserve-and-refund pair: the request never reached the ledger
            self.assertEqual(db.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)

    def test_bad_input_is_a_readable_422(self):
        for body in ({"prompt": ""}, {"shots": 99}, {"shots": 2}, {"style": "nope"}):
            r = self.create(**body)
            self.assertEqual(r.status_code, 422, body)
            self.assertTrue(r.json()["detail"]["message"], body)

    def test_a_failed_model_call_gives_the_money_back_and_creates_nothing(self):
        self.stories.error = ProviderError("quota exceeded")
        before = self.client.get("/api/projects").json()
        r = self.create()
        self.assertEqual(r.status_code, 503)
        self.assertIn("quota exceeded", r.json()["detail"]["message"])
        self.assertEqual(self.spent(), 0.0)
        self.assertEqual(self.client.get("/api/projects").json(), before)

    def test_content_the_model_slips_in_is_not_saved_and_is_refunded(self):
        self.stories.raw["shots"][2]["scene"] = "a nude figure by the road"
        before = self.client.get("/api/projects").json()
        r = self.create()
        self.assertEqual(r.status_code, 422)
        self.assertEqual((self.spent(), self.client.get("/api/projects").json()), (0.0, before))

    def test_an_unusable_answer_is_refunded_too(self):
        self.stories.raw = {"title": "x", "shots": []}
        self.assertEqual(self.create().status_code, 422)
        self.assertEqual(self.spent(), 0.0)

    def test_the_daily_cap_stops_it_before_the_model_is_called(self):
        small = Settings(Path(self.tmp.name) / "data", daily_cap_usd=0.005, story_price_usd=0.01,
                         allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render, story_provider=self.stories), small)
        r = self.create()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.stories.calls, [])

    def test_demo_mode_opens_the_finished_sample_and_never_calls_a_model(self):
        demo_dir = Path(self.tmp.name) / "demo-bundle"
        (demo_dir / "project" / "images").mkdir(parents=True)
        (demo_dir / "project" / "storyboard.json").write_text(
            (Path(self.tmp.name) / "data" / "projects" / "demo" / "storyboard.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        (demo_dir / "project" / "project.json").write_text("{}", encoding="utf-8")
        demo = Settings(Path(self.tmp.name) / "demo-data", demo=True, demo_dir=demo_dir, demo_rate_limit=1000,
                        allowed_hosts=("testserver", "localhost"))
        from shorts_studio.api import demo as demo_mode
        demo_mode_project = demo_mode.DEMO_PROJECT
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render, story_provider=self.stories), demo)
        r = self.client.post("/api/stories", json={"prompt": "무엇이든", "confirm": True})
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.json()["id"], r.json()["demo"], r.json()["estimated_usd"]), (demo_mode_project, True, 0.0))
        self.assertEqual(self.stories.calls, [])


@unittest.skipUnless(test_api.HAVE_API, "fastapi/httpx not installed (pip install -e .[api,dev])")
class GenerateMissingImages(test_api.ApiTest):
    def setUp(self):
        super().setUp()
        self.stories = FakeStories()
        self.settings = Settings(Path(self.tmp.name) / "data", image_price_usd=0.05, daily_cap_usd=1.0,
                                 story_price_usd=0.01, allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render, story_provider=self.stories))
        self.pid = self.client.post("/api/stories", json={"prompt": "비 오는 밤 버스 정류장", "shots": 6,
                                                          "confirm": True}).json()["id"]

    def start(self, **body):
        return self.client.post(f"/api/projects/{self.pid}/images/generate-missing", json={"confirm": True, **body})

    def spent(self):
        return self.client.get("/api/settings").json()["spent_today_usd"]

    def test_needs_confirm_and_reports_the_count_and_the_price(self):
        r = self.client.post(f"/api/projects/{self.pid}/images/generate-missing", json={})
        self.assertEqual(r.status_code, 400)
        self.assertEqual((r.json()["detail"]["count"], r.json()["detail"]["estimated_usd"]), (6, 0.3))
        self.assertEqual(self.images.calls, [])

    def test_makes_every_missing_image_in_story_order_and_charges_for_exactly_those(self):
        before = self.spent()
        r = self.start()
        self.assertEqual((r.status_code, r.json()["count"], r.json()["skipped"]), (202, 6, 0))
        job = self.wait_job(r.json()["id"])
        self.assertEqual(job["state"], "done", job)
        project = self.client.get(f"/api/projects/{self.pid}").json()
        self.assertTrue(all(s["has_image"] for s in project["shots"]))
        self.assertAlmostEqual(self.spent() - before, 0.3)
        order = [call[1] for call in self.images.calls]   # the prompts, in the order the images were requested
        self.assertEqual(len(order), 6)
        self.assertIn("wide shot of the bus stop", order[0])
        self.assertIn("rain on the glass shelter", order[1])

    def test_a_character_is_pinned_to_the_first_image_they_appear_in_and_later_shots_use_it(self):
        self.wait_job(self.start().json()["id"])
        settings = self.store_settings()
        self.assertEqual(settings["char_refs"], {"mina": "cut03.png", "ahjussi": "cut04.png"})
        refs_by_prompt = {prompt: refs for _, prompt, refs in self.images.calls}
        first_mina = next(p for p in refs_by_prompt if "mina holds her umbrella" in p)
        self.assertEqual(refs_by_prompt[first_mina], [])   # nobody to copy yet
        later = next(p for p in refs_by_prompt if "the man steps closer" in p)
        self.assertEqual([r.name for r in refs_by_prompt[later]], ["cut03.png"])   # mina is known; ahjussi is new here

    def store_settings(self):
        from shorts_studio.api.store import ProjectStore
        return ProjectStore(Path(self.tmp.name) / "data").settings(self.pid)

    def test_as_many_as_the_daily_cap_allows_and_it_says_how_many_were_left_out(self):
        tight = Settings(Path(self.tmp.name) / "data", image_price_usd=0.05, daily_cap_usd=0.16, story_price_usd=0.01,
                         allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render, story_provider=self.stories), tight)
        r = self.start()
        self.assertEqual((r.status_code, r.json()["count"], r.json()["skipped"]), (202, 3, 3))
        self.assertEqual(self.wait_job(r.json()["id"])["state"], "done")
        shots = self.client.get(f"/api/projects/{self.pid}").json()["shots"]
        self.assertEqual([s["has_image"] for s in shots], [True, True, True, False, False, False])

    def test_a_failure_stops_the_run_and_gives_back_the_money_for_what_was_not_made(self):
        calls = {"n": 0}
        original = self.images

        def flaky(model):
            provider = original(model)

            class P:
                def generate(self_inner, prompt, refs, out_path):
                    calls["n"] += 1
                    if calls["n"] == 3:
                        raise ProviderError("quota exceeded")
                    return provider.generate(prompt, refs, out_path)
            return P()

        before = self.spent()
        self.use_app(Deps(flaky, test_api.FakeVoice(), no_render, story_provider=self.stories))
        job = self.wait_job(self.start().json()["id"])
        self.assertEqual(job["state"], "failed")
        shots = self.client.get(f"/api/projects/{self.pid}").json()["shots"]
        self.assertEqual([s["has_image"] for s in shots], [True, True, False, False, False, False])
        self.assertAlmostEqual(self.spent() - before, 0.10)   # two images were really made; the other four came back

    def test_nothing_to_do_is_a_clear_422(self):
        self.wait_job(self.start().json()["id"])
        r = self.start()
        self.assertEqual(r.status_code, 422)

    def test_unsafe_text_added_later_blocks_the_whole_batch(self):
        self.client.patch(f"/api/projects/{self.pid}/shots/2", json={"scene": "a nude figure by the road"})
        r = self.start()
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.images.calls, [])

    def test_a_second_batch_cannot_start_while_one_is_running(self):
        import threading
        self.images.hold = threading.Event()
        first = self.start()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(self.start().status_code, 409)
        self.images.hold.set()
        self.wait_job(first.json()["id"])

    def test_another_users_project_is_a_404(self):
        # the project exists only for its owner; a different project id is simply unknown
        r = self.client.post("/api/projects/story-20000101-000000-ffff/images/generate-missing", json={"confirm": True})
        self.assertEqual(r.status_code, 404)

    def test_demo_mode_does_not_generate(self):
        bundle = Path(__file__).resolve().parents[1] / "demo"   # the real public-demo bundle
        demo = Settings(Path(self.tmp.name) / "demo-data", demo=True, demo_dir=bundle, demo_rate_limit=1000,
                        allowed_hosts=("testserver", "localhost"))
        self.use_app(Deps(self.images, test_api.FakeVoice(), no_render), demo)
        r = self.client.post("/api/projects/convenience-store/images/generate-missing", json={"confirm": True})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.images.calls, [])


if __name__ == "__main__":
    unittest.main()
