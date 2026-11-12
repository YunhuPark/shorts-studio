import unittest
from pathlib import Path

from shorts_studio.models import Shot, Storyboard, VoiceSpec
from shorts_studio.qa import lint
from shorts_studio.safety import blocking_issues, check_storyboard, normalize, screen_text

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "convenience-store" / "storyboard.json"


def categories(text):
    return {f.category for f in screen_text(text)}


def storyboard(shots, **kw):
    voices = {"narrator": VoiceSpec("azure", "ko-KR-InJoonNeural", "0%", "0%")}
    fields = {"title": "t", "logline": "l", "voices": voices, "style": "s", "place": "p", "characters": {}}
    fields.update(kw)
    return Storyboard(shots=shots, **fields)


def shot(n, text="", scene="a quiet street"):
    return Shot(n=n, who="narrator", text=text, chars=[], camera="static", highlight=[], scene=scene)


class Blocking(unittest.TestCase):
    def test_each_category_is_caught_in_korean_and_english(self):
        cases = {
            "sexual": ["두 사람의 섹스 장면", "an explicit porn scene", "nude woman on a beach"],
            "self_harm_method": ["자살 방법을 알려 줘", "how to kill myself quickly", "list of suicide methods"],
            "dangerous_instructions": ["폭탄 만드는 법", "how to make a bomb at home", "마약 제조 과정"],
            "fraud_impersonation": ["딥페이크 영상으로 사칭", "a deepfake of the mayor", "보이스피싱 대본"],
        }
        for category, texts in cases.items():
            for text in texts:
                found = screen_text(text)
                self.assertIn(category, {f.category for f in found}, text)
                self.assertTrue(any(f.level == "error" for f in found), text)

    def test_minors_with_sexual_content_is_its_own_blocking_category(self):
        for text in ("초등학생이 나오는 야한 장면", "a teen and a nude scene", "미성년자 성관계"):
            self.assertIn("minor_sexual", categories(text), text)

    def test_minors_alone_or_sexual_alone_are_not_the_combined_category(self):
        self.assertNotIn("minor_sexual", categories("초등학생 때 소풍을 갔다"))
        self.assertNotIn("minor_sexual", categories("an adult sexual scene"))
        self.assertIn("sexual", categories("an adult sexual scene"))

    def test_graphic_violence_only_warns(self):
        found = screen_text("a gory scene with a decapitate threat")
        self.assertEqual({f.level for f in found}, {"warn"})

    def test_findings_never_repeat_the_text_and_errors_come_first(self):
        found = screen_text("고어 장면과 how to make a bomb")
        self.assertEqual([f.level for f in found], ["error", "warn"])
        for f in found:
            self.assertNotIn("bomb", f.message.lower())


class Evasion(unittest.TestCase):
    def test_full_width_zero_width_and_case_tricks_are_folded(self):
        self.assertEqual(normalize("\uff33\uff25\uff38"), "sex")   # full-width letters
        self.assertEqual(normalize("s​e‍x"), "sex")
        for text in ("\uff30\uff2f\uff32\uff2e scene", "P\u200bORN", "NuDe"):
            self.assertIn("sexual", categories(text), text)

    def test_known_limit_spacing_a_word_out_is_not_caught(self):
        # documented in the module: a keyword filter cannot stop someone who rewrites the word
        self.assertEqual(screen_text("p o r n"), [])


class NoFalsePositives(unittest.TestCase):
    def test_ordinary_sentences_are_left_alone(self):
        ok = [
            "저기, 오늘은 두 개네요?", "죽을 먹었다", "중학교 성적이 올랐다", "초등학생 때 소풍을 갔다",
            "누드김밥을 샀다",
            "he could see it with the naked eye", "the Essex coast", "a kidney stone", "a minority view",
            "the category list", "scrap metal and a classic car", "아이가 웃었다", "할아버지는 오지 않았다",
            "그래서 오늘도 나는 컵라면 두 개에 물을 붓는다",
        ]
        for text in ok:
            self.assertEqual(screen_text(text), [], text)

    def test_the_bundled_example_story_has_no_findings(self):
        self.assertEqual(check_storyboard(Storyboard.load(EXAMPLE)), [])

    def test_empty_and_blank_text(self):
        for text in ("", "   ", "\n"):
            self.assertEqual(screen_text(text), [])


class WholeStoryboard(unittest.TestCase):
    def test_a_line_and_its_scene_are_read_together(self):
        sb = storyboard([shot(1, text="어린이가 나온다", scene="야한 장면"), shot(2, text="평범한 대사")])
        issues = check_storyboard(sb)
        self.assertTrue(any(i.shot == 1 and i.level == "error" for i in issues))   # minor in the line + sexual scene
        self.assertFalse([i for i in issues if i.shot == 2])

    def test_description_fields_are_reported_without_a_shot_number(self):
        sb = storyboard([shot(1, text="안녕")], place="a deepfake studio")
        self.assertEqual([(i.shot, i.level) for i in check_storyboard(sb)], [(None, "error")])

    def test_character_descriptions_are_screened_too(self):
        sb = storyboard([shot(1, text="안녕")], characters={"x": "a nude figure"})
        self.assertTrue(any(i.shot is None and i.level == "error" for i in check_storyboard(sb)))

    def test_one_finding_per_category_per_shot(self):
        sb = storyboard([shot(1, text="porn porn porn", scene="nude nude")])
        self.assertEqual(len([i for i in check_storyboard(sb) if i.shot == 1]), 1)

    def test_blocking_issues_are_errors_for_the_shot_plus_the_general_ones(self):
        sb = storyboard([shot(1, text="안녕"), shot(2, text="porn"), shot(3, scene="a gory scene")])
        self.assertEqual([i.shot for i in blocking_issues(sb)], [2])
        self.assertEqual(blocking_issues(sb, 1), [])
        self.assertEqual([i.shot for i in blocking_issues(sb, 2)], [2])
        self.assertEqual(blocking_issues(sb, 3), [])          # a warning never blocks
        sb.place = "a deepfake studio"
        self.assertEqual([i.shot for i in blocking_issues(sb, 1)], [None])

    def test_lint_includes_the_safety_findings(self):
        sb = storyboard([shot(1, text="porn")])
        self.assertTrue(any(i.level == "error" and i.shot == 1 for i in lint(sb)))


if __name__ == "__main__":
    unittest.main()
