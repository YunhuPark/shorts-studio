import unittest

from shorts_studio.render.proc import retry_on_permission


class Retry(unittest.TestCase):
    def flaky(self, failures):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            if calls["n"] <= failures:
                raise PermissionError("[WinError 5] access denied")
            return "ok"
        return fn, calls

    def test_recovers_after_transient_errors(self):
        fn, calls = self.flaky(2)
        self.assertEqual(retry_on_permission(fn, attempts=3, sleep=lambda s: None), "ok")
        self.assertEqual(calls["n"], 3)

    def test_gives_up_after_attempts(self):
        fn, calls = self.flaky(5)
        with self.assertRaises(PermissionError):
            retry_on_permission(fn, attempts=3, sleep=lambda s: None)
        self.assertEqual(calls["n"], 3)

    def test_other_errors_are_not_retried(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise ValueError("bad")
        with self.assertRaises(ValueError):
            retry_on_permission(fn, sleep=lambda s: None)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
