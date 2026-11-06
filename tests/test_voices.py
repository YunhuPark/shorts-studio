import importlib.util
import tempfile
import unittest
from pathlib import Path

from shorts_studio.api import voices

HAVE_API = importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("httpx") is not None
if HAVE_API:
    from fastapi.testclient import TestClient

    from shorts_studio.api.app import Deps, Settings, create_app


class Catalog(unittest.TestCase):
    def test_every_voice_is_complete_and_unique(self):
        names = [v.name for v in voices.VOICES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(voices.NAMES, set(names))
        for v in voices.VOICES:
            self.assertRegex(v.name, r"^ko-KR-[A-Za-z]+Neural$")
            self.assertIn(v.gender, voices.GENDERS)
            self.assertTrue(70 < v.pitch_hz < 400, v)

    def test_both_genders_have_enough_voices_to_recommend(self):
        for gender in voices.GENDERS:
            self.assertGreaterEqual(sum(v.gender == gender for v in voices.VOICES), 3)


class Recommending(unittest.TestCase):
    def names(self, gender, age):
        return [v["name"].replace("ko-KR-", "").replace("Neural", "") for v in voices.recommend(gender, age)["voices"]]

    def test_senior_prefers_the_lowest_voice_young_the_highest(self):
        self.assertEqual(self.names("male", "senior")[0], "BongJin")
        self.assertEqual(self.names("male", "young")[0], "InJoon")
        self.assertEqual(self.names("female", "senior")[0], "JiMin")
        self.assertEqual(self.names("female", "young")[0], "SeoHyeon")

    def test_adult_is_closest_to_the_middle(self):
        # the male voices sit at 130, 135, 135, 136 and 155 Hz: the two 135 Hz voices are the middle
        self.assertEqual(set(self.names("male", "adult")[:2]), {"Hyunsu", "HyunsuMultilingual"})

    def test_only_the_requested_gender_is_returned_and_at_most_three(self):
        for gender in voices.GENDERS:
            for age in voices.AGE_PRESETS:
                got = voices.recommend(gender, age)["voices"]
                self.assertEqual(len(got), 3)
                self.assertTrue(all(v["gender"] == gender for v in got))

    def test_senior_is_slower_and_lower_and_admits_it_is_an_approximation(self):
        senior, young = voices.recommend("male", "senior"), voices.recommend("male", "young")
        self.assertEqual((senior["rate"], senior["pitch"]), ("-15%", "-5%"))
        self.assertTrue(young["rate"].startswith("+"))
        self.assertIn("근사치", senior["note"])

    def test_bad_input_is_rejected(self):
        for gender, age in (("other", "adult"), ("male", "ancient"), ("", "")):
            with self.assertRaises(ValueError):
                voices.recommend(gender, age)


@unittest.skipUnless(HAVE_API, "needs fastapi and httpx")
class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        app = create_app(Settings(Path(self.tmp.name) / "data", allowed_hosts=("testserver",), embedded_workers=0),
                         Deps())
        self.client = TestClient(app)

    def test_the_voice_list_carries_gender_and_measured_pitch(self):
        got = self.client.get("/api/voices").json()
        self.assertEqual(len(got), len(voices.VOICES))
        self.assertTrue(all({"name", "gender", "pitch_hz", "note"} <= set(v) for v in got))

    def test_recommend_endpoint(self):
        r = self.client.get("/api/voices/recommend", params={"gender": "male", "age": "senior"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["voices"][0]["name"], "ko-KR-BongJinNeural")
        self.assertEqual((body["rate"], body["pitch"]), ("-15%", "-5%"))

    def test_recommend_rejects_unknown_values(self):
        for params in ({"gender": "x", "age": "senior"}, {"gender": "male", "age": "x"}, {"gender": "male"}):
            self.assertEqual(self.client.get("/api/voices/recommend", params=params).status_code, 422, params)


if __name__ == "__main__":
    unittest.main()
