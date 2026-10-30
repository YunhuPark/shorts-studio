import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from shorts_studio.generate import NO_LOGO, SAME_AS_REFERENCE, plan_generation, run_generation
from shorts_studio.models import Shot, Storyboard, VoiceSpec
from shorts_studio.providers import DirectoryImageSource, ProviderError


def storyboard() -> Storyboard:
    return Storyboard(
        title="t", logline="", voices={"narrator": VoiceSpec("azure", "v")}, style="STYLE", place="PLACE",
        characters={"grandpa": "OLD MAN", "alba": "CLERK"},
        shots=[Shot(n=1, scene="exterior"), Shot(n=2, scene="old man", chars=["grandpa"]),
               Shot(n=3, scene="two people", chars=["grandpa", "alba"]), Shot(n=4, scene="empty table")])


class FakeProvider:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def generate(self, prompt, refs, out_path):
        self.calls.append((prompt, list(refs)))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise ProviderError("quota")
        Image.new("RGB", (8, 16), "gray").save(out_path)
        return out_path


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.images = DirectoryImageSource(self.dir)
        for n in (2,):
            Image.new("RGB", (8, 16)).save(self.dir / f"cut{n:02d}.png")
        self.refs = {"grandpa": self.dir / "g.png", "alba": self.dir / "a.png"}

    def test_only_missing_shots_are_planned(self):
        items = plan_generation(storyboard(), self.images, self.refs, {})
        self.assertEqual([i.shot.n for i in items], [1, 3, 4])

    def test_replace_includes_existing_and_remembers_it(self):
        items = plan_generation(storyboard(), self.images, self.refs, {}, replace={2})
        item = next(i for i in items if i.shot.n == 2)
        self.assertEqual(item.replaces, self.dir / "cut02.png")

    def test_shots_filter_limits_candidates(self):
        items = plan_generation(storyboard(), self.images, self.refs, {}, shots={3, 4})
        self.assertEqual([i.shot.n for i in items], [3, 4])

    def test_character_refs_follow_the_shot_characters(self):
        items = {i.shot.n: i for i in plan_generation(storyboard(), self.images, self.refs, {})}
        self.assertEqual(items[3].refs, [self.refs["grandpa"], self.refs["alba"]])
        self.assertEqual(items[1].refs, [])

    def test_extra_shot_refs_are_appended(self):
        extra = self.dir / "place.png"
        items = {i.shot.n: i for i in plan_generation(storyboard(), self.images, self.refs, {4: [extra]})}
        self.assertEqual(items[4].refs, [extra])

    def test_prompt_wording(self):
        items = {i.shot.n: i for i in plan_generation(storyboard(), self.images, self.refs, {})}
        self.assertTrue(items[3].prompt.startswith(SAME_AS_REFERENCE))
        self.assertNotIn(SAME_AS_REFERENCE, items[1].prompt)  # no references, so no "same as" line
        for item in items.values():
            self.assertTrue(item.prompt.endswith(NO_LOGO))
        self.assertIn("OLD MAN", items[3].prompt)
        self.assertIn("CLERK", items[3].prompt)


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.images = DirectoryImageSource(self.dir)
        self.refs = {"grandpa": self.dir / "g.png"}

    def test_writes_image_and_metadata(self):
        items = plan_generation(storyboard(), self.images, self.refs, {}, shots={2})
        made = run_generation(items, FakeProvider(), self.dir, "model-x", log=lambda s: None)
        self.assertEqual([p.name for p in made], ["cut02.png"])
        meta = json.loads((self.dir / "cut02.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["model"], "model-x")
        self.assertEqual(meta["shot"], 2)

    def test_replace_keeps_the_old_image_as_prev(self):
        old = self.dir / "cut01.png"
        Image.new("RGB", (4, 4), "red").save(old)
        items = plan_generation(storyboard(), self.images, {}, {}, shots={1}, replace={1})
        run_generation(items, FakeProvider(), self.dir, "m", log=lambda s: None)
        self.assertTrue((self.dir / "cut01_prev.png").exists())
        self.assertEqual(Image.open(self.dir / "cut01_prev.png").getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(Image.open(self.dir / "cut01.png").size, (8, 16))

    def test_failed_replace_restores_the_original(self):
        old = self.dir / "cut01.png"
        Image.new("RGB", (4, 4), "red").save(old)
        items = plan_generation(storyboard(), self.images, {}, {}, shots={1}, replace={1})
        with self.assertRaises(ProviderError):
            run_generation(items, FakeProvider(fail_on=1), self.dir, "m", log=lambda s: None)
        self.assertEqual(Image.open(old).getpixel((0, 0)), (255, 0, 0))
        self.assertFalse((self.dir / "cut01_prev.png").exists())

    def test_stops_at_first_error_and_keeps_earlier_images(self):
        items = plan_generation(storyboard(), self.images, {}, {}, shots={1, 3, 4})
        with self.assertRaises(ProviderError):
            run_generation(items, FakeProvider(fail_on=2), self.dir, "m", log=lambda s: None)
        self.assertTrue((self.dir / "cut01.png").exists())
        self.assertFalse((self.dir / "cut04.png").exists())  # never attempted after the failure


if __name__ == "__main__":
    unittest.main()
