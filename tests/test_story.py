import copy
import unittest

from shorts_studio.models import CAMERAS
from shorts_studio.providers import ProviderError
from shorts_studio.qa import lint
from shorts_studio.story import (
    MAX_SHOTS,
    MIN_SHOTS,
    SCHEMA,
    STYLES,
    StoryError,
    build_storyboard,
    check_request,
    generate_storyboard,
)


def shot(text="", who="narrator", camera="static", highlight=(), scene="a quiet street", chars=()):
    return {"text": text, "who": who, "camera": camera, "highlight": list(highlight), "scene": scene,
            "chars": list(chars)}


RAW = {
    "title": "마지막 버스", "logline": "막차를 기다리던 두 사람이 서로의 우산을 나눠 쓴다.",
    "place": "a rainy bus stop at night",
    "characters": [
        {"id": "ahjussi", "look": "a man in his sixties with a gray raincoat", "gender": "male", "age": "senior"},
        {"id": "mina", "look": "a woman in her twenties with a yellow umbrella", "gender": "female", "age": "young"},
    ],
    "shots": [
        shot("비 오는 밤, 마지막 버스.", camera="push_in", highlight=["마지막"], scene="wide shot of the bus stop"),
        shot("", who="", scene="rain on the glass shelter"),
        shot("우산 하나뿐이네요.", who="mina", camera="handheld", highlight=["하나뿐"], scene="mina holds her umbrella",
             chars=["mina"]),
        shot("같이 쓰시죠.", who="ahjussi", camera="pull_out", scene="the man steps closer", chars=["ahjussi", "mina"]),
        shot("버스는 오지 않았다.", camera="pan_right", scene="empty road"),
        shot("그래도 따뜻했다.", camera="static", highlight=["따뜻했다"], scene="two figures under one umbrella"),
    ],
}


def raw(**changes):
    r = copy.deepcopy(RAW)
    r.update(changes)
    return r


class BuildStoryboard(unittest.TestCase):
    def test_a_good_story_becomes_a_storyboard_that_lints_clean(self):
        sb = build_storyboard(RAW, 6, "cinematic")
        self.assertEqual([s.n for s in sb.shots], [1, 2, 3, 4, 5, 6])
        self.assertEqual(sb.title, "마지막 버스")
        self.assertEqual(sb.characters, {"ahjussi": "a man in his sixties with a gray raincoat",
                                         "mina": "a woman in her twenties with a yellow umbrella"})
        self.assertEqual(sb.style, STYLES["cinematic"][1])
        self.assertEqual([i for i in lint(sb) if i.level == "error"], [])

    def test_every_speaker_has_a_voice_and_characters_get_different_ones(self):
        sb = build_storyboard(RAW, 6)
        self.assertEqual(set(sb.voices), {"narrator", "ahjussi", "mina"})
        self.assertEqual(sb.voices["narrator"].voice, "ko-KR-InJoonNeural")
        self.assertEqual(len({v.voice for v in sb.voices.values()}), 3)
        self.assertEqual(sb.voices["ahjussi"].rate, "-15%")   # senior preset: lower and slower
        self.assertTrue(all(v.voice.startswith("ko-KR-") and v.provider == "azure" for v in sb.voices.values()))

    def test_two_characters_of_one_gender_do_not_share_a_voice(self):
        characters = [{"id": c, "look": f"{c} look", "gender": "male", "age": "senior"} for c in ("a", "b", "c")]
        sb = build_storyboard(raw(characters=characters), 6)
        self.assertEqual(len({sb.voices[c].voice for c in "abc"}), 3)

    def test_repairs_what_the_model_got_wrong(self):
        shots = copy.deepcopy(RAW["shots"])
        shots[0]["camera"] = "zoom_wildly"                  # unknown camera
        shots[2]["who"] = "ghost"                           # speaker nobody defined
        shots[3]["highlight"] = ["없는말", "같이"]           # one highlight is not in the line
        shots[4]["chars"] = ["nobody", "mina"]              # unknown character
        shots[1]["who"] = "narrator"                        # silent shot with a speaker
        sb = build_storyboard(raw(shots=shots), 6)
        self.assertEqual(sb.shots[0].camera, "static")
        self.assertEqual(sb.shots[2].who, "narrator")
        self.assertEqual(sb.shots[3].highlight, ["같이"])
        self.assertEqual(sb.shots[4].chars, ["mina"])
        self.assertEqual((sb.shots[1].text, sb.shots[1].who), ("", ""))
        self.assertTrue(all(s.camera in CAMERAS for s in sb.shots))

    def test_highlights_lose_punctuation_and_duplicates_but_keep_working(self):
        shots = copy.deepcopy(RAW["shots"])
        shots[3]["text"] = "같이 쓰실래요? 생각보다 넓어요."
        shots[3]["highlight"] = ["같이 쓰실래요?", "넓어요.", "넓어요", "  "]
        sb = build_storyboard(raw(shots=shots), 6)
        self.assertEqual(sb.shots[3].highlight, ["같이 쓰실래요", "넓어요"])
        self.assertEqual([i for i in lint(sb) if i.level == "error"], [])

    def test_extra_shots_are_cut_and_shots_are_renumbered_from_one(self):
        many = [shot(f"{i}번째 장면", scene=f"scene {i}") for i in range(30)]
        sb = build_storyboard(raw(shots=many), 8)
        self.assertEqual([s.n for s in sb.shots], list(range(1, 9)))

    def test_empty_shots_are_dropped_and_too_few_is_an_error(self):
        shots = [shot(f"장면 {i}", scene=f"scene {i}") for i in range(MIN_SHOTS - 1)] + [shot("", who="", scene="")]
        with self.assertRaises(StoryError):
            build_storyboard(raw(shots=shots), 12)

    def test_garbage_does_not_crash(self):
        for bad in ({}, {"shots": "no"}, {"shots": [1, None, "x"], "characters": [1, {"id": 5}]},
                    {"shots": [], "characters": None}):
            with self.assertRaises(StoryError):
                build_storyboard(bad, 12)

    def test_unknown_style_and_character_limits(self):
        with self.assertRaises(StoryError):
            build_storyboard(RAW, 6, "neon-pink")
        many = [{"id": f"c{i}", "look": "x", "gender": "female", "age": "adult"} for i in range(9)]
        self.assertEqual(len(build_storyboard(raw(characters=many), 6).characters), 4)

    def test_narrator_cannot_be_redefined_as_a_character(self):
        chars = [{"id": "Narrator", "look": "a voice", "gender": "male", "age": "adult"}]
        sb = build_storyboard(raw(characters=chars), 6)
        self.assertEqual(sb.characters, {})
        self.assertEqual(sb.voices["narrator"].voice, "ko-KR-InJoonNeural")


class CheckRequest(unittest.TestCase):
    def test_limits_are_enforced_with_readable_messages(self):
        for prompt, shots in (("", 12), ("가", 12), ("가" * 801, 12), ("할아버지의 하루", MIN_SHOTS - 1),
                              ("할아버지의 하루", MAX_SHOTS + 1)):
            with self.assertRaises(StoryError, msg=(prompt[:5], shots)):
                check_request(prompt, shots, "cinematic")
        with self.assertRaises(StoryError):
            check_request("할아버지의 하루", 12, "nope")
        self.assertEqual(check_request("  할아버지의 하루  ", 12, "anime"), "할아버지의 하루")

    def test_a_request_that_would_be_refused_is_refused_before_anything_is_spent(self):
        with self.assertRaises(StoryError):
            check_request("야한 이야기를 만들어 줘", 12, "cinematic")
        with self.assertRaises(StoryError):
            check_request("딥페이크 영상 만드는 이야기", 12, "cinematic")


class GenerateStoryboard(unittest.TestCase):
    class Provider:
        def __init__(self, result=None, error=None):
            self.result, self.error, self.calls = result, error, []

        def generate(self, system, prompt, schema):
            self.calls.append((system, prompt, schema))
            if self.error:
                raise self.error
            return self.result

    def test_sends_the_schema_and_the_shot_count_and_returns_the_storyboard(self):
        provider = self.Provider(RAW)
        sb = generate_storyboard(provider, "비 오는 날 버스 정류장 이야기", 6, "watercolor")
        system, prompt, schema = provider.calls[0]
        self.assertIs(schema, SCHEMA)
        self.assertIn("exactly 6", prompt)
        self.assertIn("비 오는 날 버스 정류장 이야기", prompt)
        self.assertIn("9:16", system)
        self.assertEqual(sb.style, STYLES["watercolor"][1])

    def test_content_the_model_slips_in_is_refused_and_nothing_is_returned(self):
        shots = copy.deepcopy(RAW["shots"])
        shots[2]["scene"] = "a nude figure by the road"
        with self.assertRaises(StoryError) as ctx:
            generate_storyboard(self.Provider(raw(shots=shots)), "비 오는 날 버스 정류장 이야기", 6)
        self.assertIn("허용되지 않는", str(ctx.exception))

    def test_provider_errors_pass_through_for_the_caller_to_report(self):
        with self.assertRaises(ProviderError):
            generate_storyboard(self.Provider(error=ProviderError("quota")), "비 오는 날 버스 정류장 이야기", 6)

    def test_the_prompt_is_not_sent_when_the_request_is_refused(self):
        provider = self.Provider(RAW)
        with self.assertRaises(StoryError):
            generate_storyboard(provider, "야한 이야기", 6)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
