import unittest
from pathlib import Path

from shorts_studio.models import Shot, Storyboard, VoiceSpec
from shorts_studio.qa import lint

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "convenience-store" / "storyboard.json"


class Example(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = Storyboard.load(EXAMPLE)

    def test_loads_all_shots_in_order(self):
        self.assertEqual([s.n for s in self.sb.shots], list(range(1, 27)))

    def test_every_speaker_has_a_voice(self):
        for s in self.sb.shots:
            if s.text:
                self.assertIn(s.who, self.sb.voices)

    def test_voices_have_no_pitch_shift(self):
        for v in self.sb.voices.values():
            self.assertEqual(v.pitch, "0%")

    def test_example_has_no_lint_errors(self):
        self.assertEqual([i for i in lint(self.sb) if i.level == "error"], [])

    def test_image_prompt_has_scene_character_place_style(self):
        shot = next(s for s in self.sb.shots if s.n == 5)
        prompt = self.sb.image_prompt(shot)
        self.assertIn(shot.scene, prompt)
        self.assertIn(self.sb.characters["grandpa"], prompt)
        self.assertIn(self.sb.place, prompt)
        self.assertIn(self.sb.style, prompt)

    def test_prompt_without_characters_omits_character_text(self):
        shot = next(s for s in self.sb.shots if s.n == 1)
        prompt = self.sb.image_prompt(shot)
        self.assertNotIn(self.sb.characters["grandpa"], prompt)


class LintRules(unittest.TestCase):
    def make(self, **kw) -> Storyboard:
        base = dict(title="t", logline="", voices={"narrator": VoiceSpec("azure", "v")}, style="", place="",
                    characters={}, shots=[Shot(n=1, text="안녕하세요", who="narrator", scene="s")])
        base.update(kw)
        return Storyboard(**base)

    def test_clean_storyboard(self):
        self.assertEqual(lint(self.make()), [])

    def test_duplicate_numbers(self):
        sb = self.make(shots=[Shot(n=1, scene="a"), Shot(n=1, scene="b")])
        self.assertTrue(any("duplicate" in i.message for i in lint(sb)))

    def test_unknown_camera(self):
        sb = self.make(shots=[Shot(n=1, camera="zoom_zoom", scene="a")])
        self.assertTrue(any("camera" in i.message for i in lint(sb)))

    def test_missing_voice(self):
        sb = self.make(shots=[Shot(n=1, text="네", who="ghost", scene="a")])
        self.assertTrue(any(i.level == "error" and "voice" in i.message for i in lint(sb)))

    def test_highlight_not_in_line(self):
        sb = self.make(shots=[Shot(n=1, text="안녕", who="narrator", highlight=["없는말"], scene="a")])
        self.assertTrue(any("highlight" in i.message for i in lint(sb)))


if __name__ == "__main__":
    unittest.main()
