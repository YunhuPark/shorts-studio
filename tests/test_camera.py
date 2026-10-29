import unittest

from shorts_studio.models import CAMERAS
from shorts_studio.render.camera import camera, crop_box, ease


class Camera(unittest.TestCase):
    def test_ease_endpoints_and_monotonic(self):
        self.assertEqual(ease(0), 0)
        self.assertEqual(ease(1), 1)
        vals = [ease(i / 100) for i in range(101)]
        self.assertEqual(vals, sorted(vals))

    def test_push_and_pull_are_mirror_images(self):
        for p in (0.0, 0.25, 0.5, 0.75, 1.0):
            push = camera("push_in", p)[0]
            pull = camera("pull_out", 1 - p)[0]
            self.assertAlmostEqual(push, pull)

    def test_motion_is_smooth_every_move(self):
        """No frame-to-frame jumps: the second difference of every parameter stays tiny."""
        frames = 90
        for move in CAMERAS:
            series = [camera(move, i / (frames - 1)) for i in range(frames)]
            for k in range(3):
                vals = [s[k] for s in series]
                second = [abs(vals[i + 1] - 2 * vals[i] + vals[i - 1]) for i in range(1, frames - 1)]
                self.assertLess(max(second), 0.002, (move, k))

    def test_crop_stays_inside_image(self):
        for move in CAMERAS:
            for i in range(31):
                z, fx, fy = camera(move, i / 30)
                x0, y0, cw, ch = crop_box(z, fx, fy, 1144, 2048)
                self.assertGreaterEqual(x0, 0)
                self.assertGreaterEqual(y0, 0)
                self.assertLessEqual(x0 + cw, 1144 + 1e-6)
                self.assertLessEqual(y0 + ch, 2048 + 1e-6)

    def test_zoom_never_below_one(self):
        for move in CAMERAS:
            for i in range(31):
                self.assertGreaterEqual(camera(move, i / 30)[0], 1.0)


if __name__ == "__main__":
    unittest.main()
