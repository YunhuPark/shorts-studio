import contextlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from shorts_studio.api.jobqueue import LOG_KEEP, JobQueue
from shorts_studio.api.worker import Worker

SRC = str(Path(__file__).resolve().parents[1] / "src")


class QueueCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.sqlite3"
        self.q = JobQueue(self.path)

    def age_heartbeat(self, job_id, seconds):
        with contextlib.closing(sqlite3.connect(self.path)) as c, c:   # close it too: Windows keeps the file locked
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=?", (time.time() - seconds, job_id))


class Basics(QueueCase):
    def test_submit_get_and_owner_scoping(self):
        a = self.q.submit("render", "demo", "alice", {"only": [1, 2]})
        self.q.submit("render", "demo", "bob")
        self.assertEqual(self.q.get(a.id).params, {"only": [1, 2]})
        self.assertEqual([j.id for j in self.q.list("demo", "alice")], [a.id])
        self.assertEqual(len(self.q.list(owner="bob")), 1)
        self.assertEqual(self.q.list("other", "alice"), [])
        self.assertIsNone(self.q.get("missing"))

    def test_state_survives_reopening_the_database(self):
        job = self.q.submit("render", "demo", "local")
        self.q.claim("w1")
        self.q.report(job.id, "half way", 0.5)
        again = JobQueue(self.path).get(job.id)   # a new process would see exactly this
        self.assertEqual((again.state, again.progress, again.log, again.worker), ("running", 0.5, ["half way"], "w1"))

    def test_claim_is_fifo_and_empty_queue_gives_none(self):
        first = self.q.submit("a", "p", "local")
        time.sleep(0.01)
        second = self.q.submit("b", "p", "local")
        self.assertEqual(self.q.claim("w").id, first.id)
        self.assertEqual(self.q.claim("w").id, second.id)
        self.assertIsNone(self.q.claim("w"))

    def test_every_job_is_claimed_exactly_once_under_contention(self):
        ids = {self.q.submit(f"k{i}", "p", "local").id for i in range(30)}
        claimed, lock = [], threading.Lock()

        def grab(name):
            for _ in range(100):   # bounded, so a broken claim fails the assertion instead of looping forever
                job = self.q.claim(name)
                if job is None:
                    return
                with lock:
                    claimed.append(job.id)

        threads = [threading.Thread(target=grab, args=(f"w{i}",)) for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(claimed), sorted(ids))   # none lost, none twice

    def test_submit_unique_refuses_a_duplicate_until_the_first_ends(self):
        first = self.q.submit_unique("render", "demo", "alice")
        self.assertIsNotNone(first)
        self.assertIsNone(self.q.submit_unique("render", "demo", "alice"))
        self.assertIsNotNone(self.q.submit_unique("render", "demo", "bob"))          # other owner
        self.assertIsNotNone(self.q.submit_unique("render", "other", "alice"))       # other project
        self.assertEqual(self.q.active("demo", "render", "alice").id, first.id)
        self.q.claim("w")
        self.assertIsNone(self.q.submit_unique("render", "demo", "alice"))           # running still counts
        self.q.finish(first.id, "x.mp4")
        self.assertIsNone(self.q.active("demo", "render", "alice"))
        self.assertIsNotNone(self.q.submit_unique("render", "demo", "alice"))

    def test_report_caps_the_log_and_finish_fail_record_the_outcome(self):
        a, b = self.q.submit("a", "p", "local"), self.q.submit("b", "p", "local")
        for i in range(LOG_KEEP + 20):
            self.q.report(a.id, f"line {i}", i / 1000)
        job = self.q.get(a.id)
        self.assertEqual(len(job.log), LOG_KEEP)
        self.assertEqual(job.log[-1], f"line {LOG_KEEP + 19}")
        self.q.finish(a.id, "result.mp4")
        self.q.fail(b.id, "ValueError: nope", "traceback text")
        done, failed = self.q.get(a.id), self.q.get(b.id)
        self.assertEqual((done.state, done.progress, done.result), ("done", 1.0, "result.mp4"))
        self.assertEqual((failed.state, failed.error, failed.log[-1]), ("failed", "ValueError: nope", "traceback text"))
        self.assertEqual(done.public()["state"], "done")
        self.assertNotIn("params", done.public())


class Recovery(QueueCase):
    def test_a_job_whose_worker_stopped_is_failed_but_live_and_queued_jobs_are_not(self):
        dead, alive, waiting = (self.q.submit(k, "p", "local") for k in ("dead", "alive", "waiting"))
        self.q.claim("w1"), self.q.claim("w2")
        self.age_heartbeat(dead.id, 120)
        recovered = self.q.recover_stale(60)
        self.assertEqual([j.id for j in recovered], [dead.id])
        self.assertEqual(self.q.get(dead.id).state, "failed")
        self.assertIn("worker stopped", self.q.get(dead.id).error)
        self.assertEqual(self.q.get(alive.id).state, "running")
        self.assertEqual(self.q.get(waiting.id).state, "queued")
        self.assertEqual(self.q.recover_stale(60), [])    # idempotent


class Workers(QueueCase):
    def test_success_failure_and_empty_queue(self):
        ok = self.q.submit("ok", "p", "local")
        bad = self.q.submit("bad", "p", "local")

        def handler(job, report):
            report(f"working on {job.kind}", 0.4)
            if job.kind == "bad":
                raise RuntimeError("ffmpeg exploded")
            return "out.mp4"

        w = Worker(self.q, handler, name="w1")
        self.assertTrue(w.run_one() and w.run_one())
        self.assertFalse(w.run_one())
        done, failed = self.q.get(ok.id), self.q.get(bad.id)
        self.assertEqual((done.state, done.result, done.worker, done.log), ("done", "out.mp4", "w1", ["working on ok"]))
        self.assertEqual(failed.state, "failed")
        self.assertEqual(failed.error, "RuntimeError: ffmpeg exploded")
        self.assertIn("Traceback", failed.log[-1])

    def test_heartbeat_keeps_a_long_silent_job_alive(self):
        job = self.q.submit("long", "p", "local")
        seen = {}

        def slow(job_, report):
            time.sleep(0.8)   # no report() for longer than stale_after
            return "done"

        worker = Worker(self.q, slow, stale_after=0.3, heartbeat_every=0.05)
        t = threading.Thread(target=worker.run_one)
        t.start()
        time.sleep(0.5)
        seen["recovered"] = self.q.recover_stale(0.3)   # another worker checking in the middle of the job
        t.join()
        self.assertEqual(seen["recovered"], [])
        self.assertEqual(self.q.get(job.id).state, "done")

    def test_a_job_without_heartbeat_is_recovered_and_the_handler_is_told(self):
        job = self.q.submit("regenerate-3", "demo", "alice", {"n": 3, "est": 0.05})
        self.q.claim("dead-worker")
        self.age_heartbeat(job.id, 300)
        told = []
        Worker(self.q, lambda j, r: None, on_orphan=told.append, stale_after=60).recover()
        self.assertEqual([(j.kind, j.params) for j in told], [("regenerate-3", {"n": 3, "est": 0.05})])

    def test_a_failing_orphan_hook_does_not_stop_the_others(self):
        for i in range(2):
            self.q.submit(f"k{i}", "p", "local")
            self.age_heartbeat(self.q.claim("dead").id, 300)
        told = []

        def hook(job):
            told.append(job.id)
            raise OSError("ledger locked")

        self.assertEqual(len(Worker(self.q, lambda j, r: None, on_orphan=hook).recover()), 2)
        self.assertEqual(len(told), 2)

    def test_a_separate_process_can_run_the_job(self):
        job = self.q.submit("render", "demo", "alice")
        code = (
            "import sys\n"
            "from shorts_studio.api.jobqueue import JobQueue\n"
            "from shorts_studio.api.worker import Worker\n"
            "def handler(job, report):\n"
            "    report('from the other process', 0.5)\n"
            "    return 'proc.mp4'\n"
            "w = Worker(JobQueue(sys.argv[1]), handler, name='proc')\n"
            "print(w.run_one())\n"
        )
        env = {**os.environ, "PYTHONPATH": SRC}
        out = subprocess.run([sys.executable, "-c", code, str(self.path)], env=env, capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        done = self.q.get(job.id)
        self.assertEqual((done.state, done.result, done.worker), ("done", "proc.mp4", "proc"))
        self.assertEqual(done.log, ["from the other process"])


if __name__ == "__main__":
    unittest.main()
