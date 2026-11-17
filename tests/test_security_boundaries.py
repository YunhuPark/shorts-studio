import io
import os
from pathlib import Path

from PIL import Image
from test_api import STORYBOARD, ApiTest, Deps, FakeVoice


class SecurityBoundaries(ApiTest):
    def test_thumbnail_is_owner_and_content_specific_even_with_same_timestamp(self):
        import json

        from shorts_studio.api.store import ProjectStore

        root = self.settings.root
        sb = root / "synthetic.json"
        sb.write_text(json.dumps(STORYBOARD), encoding="utf-8")
        for owner, color in (("alice", "red"), ("bob", "blue")):
            store = ProjectStore(root, owner)
            store.create("same", sb)
            path = store.images_dir("same") / "cut01.png"
            Image.new("RGB", (20, 30), color).save(path)
            os.utime(path, (1700000000, 1700000000))
        self.use_app(Deps(owner=lambda request: request.headers["x-test-owner"]))
        a = self.client.get("/api/projects/same/images/1?w=120", headers={"x-test-owner": "alice"})
        b = self.client.get("/api/projects/same/images/1?w=120", headers={"x-test-owner": "bob"})
        self.assertNotEqual(a.content, b.content)
        pixel = Image.open(io.BytesIO(b.content)).getpixel((0, 0))
        self.assertGreater(pixel[2], pixel[0])
        path = ProjectStore(root, "bob").images_dir("same") / "cut01.png"
        Image.new("RGB", (20, 30), "green").save(path)
        os.utime(path, (1700000000, 1700000000))
        changed = self.client.get("/api/projects/same/images/1?w=120", headers={"x-test-owner": "bob"})
        self.assertNotEqual(b.content, changed.content)

    def test_get_sample_never_calls_a_paid_provider(self):
        calls = []

        def provider(cache):
            calls.append(cache)
            return FakeVoice()(cache)

        self.use_app(Deps(voice_provider=provider))
        self.client.get("/api/voices/sample?voice=ko-KR-BongJinNeural")
        self.assertEqual(calls, [])

    def test_paid_sample_requires_confirmation_and_uses_the_user_cap(self):
        self.settings.daily_cap_usd = 0
        self.use_app(Deps(voice_provider=FakeVoice()))
        body = {"voice": "ko-KR-BongJinNeural", "confirm": True}
        self.assertEqual(self.client.post("/api/voices/sample", json=body).status_code, 429)
        self.assertEqual(self.client.post("/api/voices/sample", json={"voice": body["voice"]}).status_code, 400)

    def test_render_speech_uses_the_same_cap_as_samples(self):
        self.settings.daily_cap_usd = 0

        def render(sb, images, voices, out, opts, only, log):
            shot = sb.shots[0]
            voices.synthesize(shot.text, sb.voices[shot.who])
            Path(out).write_bytes(b"synthetic")

        self.use_app(Deps(voice_provider=FakeVoice(), render_fn=render))
        result = self.client.post("/api/projects/demo/render", json={})
        job = self.wait_job(result.json()["id"])
        self.assertEqual(job["state"], "failed")
        self.assertIn("budget", job["error"].lower())
