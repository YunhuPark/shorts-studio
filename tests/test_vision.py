import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

from shorts_studio.models import Shot, Storyboard, VoiceSpec
from shorts_studio.providers import DirectoryImageSource
from shorts_studio.vision import fetch as fetch_mod
from shorts_studio.vision.faces import Face, check_shots, cosine
from shorts_studio.vision.fetch import MODELS, Model, ModelError, fetch, is_valid, model_path


class Cosine(unittest.TestCase):
    def test_basic_values(self):
        self.assertAlmostEqual(cosine(np.array([1.0, 0]), np.array([2.0, 0])), 1.0)
        self.assertAlmostEqual(cosine(np.array([1.0, 0]), np.array([0, 1.0])), 0.0)
        self.assertAlmostEqual(cosine(np.array([1.0, 0]), np.array([-1.0, 0])), -1.0)

    def test_zero_vector_does_not_divide_by_zero(self):
        self.assertEqual(cosine(np.zeros(3), np.ones(3)), 0.0)


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.payload = b"pretend onnx model " * 100
        self.src = self.dir / "source.onnx"
        self.src.write_bytes(self.payload)
        self.model = Model("fake", "fake.onnx", self.src.as_uri(), len(self.payload),
                           hashlib.sha256(self.payload).hexdigest(), "MIT")
        self.dest = self.dir / "dest"
        MODELS["fake"] = self.model
        self.addCleanup(MODELS.pop, "fake", None)

    def test_registry_pins_size_and_hash_of_the_real_models(self):
        for name in ("yunet", "sface"):
            m = MODELS[name]
            self.assertEqual(len(m.sha256), 64)
            self.assertGreater(m.size, 0)
            self.assertTrue(m.url.startswith("https://media.githubusercontent.com/"))
        self.assertEqual({MODELS["yunet"].license, MODELS["sface"].license}, {"MIT", "Apache-2.0"})

    def test_download_is_verified_and_stored(self):
        logs = []
        path = fetch("fake", self.dest, log=logs.append)
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertTrue(is_valid(self.model, path))
        self.assertEqual(list(self.dest.glob("*.part")), [])

    def test_second_fetch_does_not_download_again(self):
        fetch("fake", self.dest, log=lambda s: None)
        self.src.unlink()  # a second download would now fail
        logs = []
        fetch("fake", self.dest, log=logs.append)
        self.assertIn("already present", logs[0])

    def test_corrupt_download_is_rejected_and_leaves_nothing(self):
        bad = Model("fake", "fake.onnx", self.src.as_uri(), len(self.payload), "0" * 64, "MIT")
        MODELS["fake"] = bad
        with self.assertRaises(ModelError):
            fetch("fake", self.dest, log=lambda s: None)
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_model_path_tells_how_to_get_a_missing_model(self):
        with self.assertRaises(ModelError) as cm:
            model_path("fake", self.dest)
        self.assertIn("fetch-models", str(cm.exception))

    def test_default_directory_can_be_overridden_by_environment(self):
        import os
        old = os.environ.get("SHORTS_MODELS")
        os.environ["SHORTS_MODELS"] = str(self.dir)
        try:
            self.assertEqual(fetch_mod.models_dir(), self.dir)
        finally:
            if old is None:
                os.environ.pop("SHORTS_MODELS")
            else:
                os.environ["SHORTS_MODELS"] = old


class FakeEmbedder:
    """Returns pre-set faces per image file name, like a detector would."""

    def __init__(self, faces_by_name):
        self.faces_by_name = faces_by_name

    def embed_all(self, path):
        return list(self.faces_by_name.get(Path(path).name, []))


def face(vec, height=200.0):
    return Face(np.array(vec, dtype=np.float64), 0.99, (0.0, 0.0, height * 0.8, height))


class CheckShots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for n in (1, 2, 3, 4, 5, 6):
            (self.dir / f"cut{n:02d}.png").write_bytes(b"x")
        self.sb = Storyboard("t", "", {"narrator": VoiceSpec("azure", "v")}, "", "", {},
                             [Shot(n=1, chars=["grandpa"]), Shot(n=2, chars=["grandpa", "alba"]),
                              Shot(n=3, chars=["grandpa"]), Shot(n=4, chars=["grandpa"]),
                              Shot(n=5, chars=[]), Shot(n=6, chars=["alba"]), Shot(n=7, chars=["grandpa"])])
        self.refs = {"grandpa": self.dir / "ref_g.png", "alba": self.dir / "ref_a.png"}
        self.G, self.A = [1.0, 0.0], [0.0, 1.0]
        self.faces = {"ref_g.png": [face(self.G)], "ref_a.png": [face(self.A)]}

    def run_check(self, **kw):
        res = check_shots(self.sb, DirectoryImageSource(self.dir), self.refs, FakeEmbedder(self.faces), **kw)
        return {r.shot: r for r in res}

    def test_matching_face_is_ok_and_assigned(self):
        self.faces["cut01.png"] = [face([0.9, 0.1])]
        r = self.run_check()[1]
        self.assertEqual((r.status, r.faces[0].character), ("ok", "grandpa"))

    def test_two_people_in_a_frame_are_each_assigned_to_the_right_reference(self):
        # the larger face is the clerk: comparing only the biggest face with grandpa would call this drift
        self.faces["cut02.png"] = [face([0.05, 1.0], 300), face([1.0, 0.1], 150)]
        r = self.run_check()[2]
        self.assertEqual(r.status, "ok")
        self.assertEqual({f.character for f in r.faces}, {"alba", "grandpa"})

    def test_unrecognised_face_is_flagged_as_possible_drift(self):
        self.faces["cut03.png"] = [face([-1.0, -1.0])]  # similar to neither reference
        self.assertEqual(self.run_check()[3].status, "drift?")

    def test_tiny_faces_are_not_judged(self):
        self.faces["cut04.png"] = [face([-1.0, -1.0], height=40)]
        r = self.run_check()[4]
        self.assertEqual(r.status, "small")
        self.assertTrue(r.faces[0].small)

    def test_no_face_found(self):
        self.faces["cut06.png"] = []
        self.assertEqual(self.run_check()[6].status, "no face")

    def test_shots_without_reference_characters_or_images_are_skipped(self):
        checked = self.run_check()
        self.assertNotIn(5, checked)   # no characters listed
        self.assertNotIn(7, checked)   # image does not exist

    def test_threshold_is_adjustable(self):
        self.faces["cut01.png"] = [face([0.5, 0.8])]  # cosine to grandpa about 0.53
        self.assertEqual(self.run_check(threshold=0.363)[1].status, "ok")
        self.assertEqual(self.run_check(threshold=0.9)[1].status, "drift?")

    def test_reference_without_a_face_is_an_error(self):
        self.faces["ref_g.png"] = []
        with self.assertRaises(ValueError):
            self.run_check()


HAVE_CV = importlib.util.find_spec("cv2") is not None
try:
    model_path("yunet")
    model_path("sface")
    HAVE_MODELS = True
except ModelError:
    HAVE_MODELS = False


@unittest.skipUnless(HAVE_CV and HAVE_MODELS, "needs opencv (the [vision] extra) and `fetch-models`")
class OpenCVSmoke(unittest.TestCase):
    def test_blank_image_has_no_face_and_does_not_crash(self):
        from PIL import Image

        from shorts_studio.vision.faces import OpenCVEmbedder
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "blank.png"
            Image.new("RGB", (320, 480), "gray").save(p)
            self.assertEqual(OpenCVEmbedder().embed_all(p), [])

    def test_unreadable_file_is_a_clear_error(self):
        from shorts_studio.vision.faces import OpenCVEmbedder
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "broken.png"
            p.write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                OpenCVEmbedder().embed_all(p)


if __name__ == "__main__":
    unittest.main()
