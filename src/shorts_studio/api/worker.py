"""Workers: claim jobs from the durable queue and run them with the registered handlers.

The same Worker runs inside the API process (threads, default for the local dashboard) or alone in
`shorts-studio worker` (separate process). While a job runs, a heartbeat thread keeps it alive; if the process
dies, the heartbeat stops and `recover_stale` fails the job and lets the handler give back reserved spend.
"""
from __future__ import annotations

import contextlib
import os
import threading
import traceback
import uuid
from collections.abc import Callable

from .jobqueue import Job, JobQueue

Report = Callable[[str, float | None], None]
Handler = Callable[[Job, Report], "str | None"]

HEARTBEAT_EVERY = 5.0
STALE_AFTER = 60.0


class Worker:
    def __init__(self, queue: JobQueue, handler: Handler, on_orphan: Callable[[Job], None] | None = None,
                 name: str | None = None, poll: float = 0.2, stale_after: float = STALE_AFTER,
                 heartbeat_every: float = HEARTBEAT_EVERY):
        self.queue = queue
        self.handler = handler
        self.on_orphan = on_orphan
        self.id = name or f"w{os.getpid()}-{uuid.uuid4().hex[:4]}"
        self.poll = poll
        self.stale_after = stale_after
        self.heartbeat_every = heartbeat_every

    def recover(self) -> list[Job]:
        orphans = self.queue.recover_stale(self.stale_after)
        for job in orphans:
            if self.on_orphan:
                with contextlib.suppress(Exception):  # a failed refund must not stop recovery of the others
                    self.on_orphan(job)
        return orphans

    def run_one(self) -> bool:
        """Claim and run a single job; False when the queue had nothing."""
        job = self.queue.claim(self.id)
        if job is None:
            return False
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(self.heartbeat_every):
                with contextlib.suppress(Exception):
                    self.queue.heartbeat(job.id)

        threading.Thread(target=beat, daemon=True, name=f"beat-{job.id}").start()
        try:
            result = self.handler(job, lambda line, progress=None: self.queue.report(job.id, line, progress))
        except Exception as e:  # shown to the user; the traceback goes to the job log
            self.queue.fail(job.id, f"{type(e).__name__}: {e}", traceback.format_exc(limit=3))
        else:
            self.queue.finish(job.id, result)
        finally:
            stop.set()
        return True

    def run_forever(self, stop: threading.Event) -> None:
        ticks = 0
        while not stop.is_set():
            try:
                if ticks % max(int(self.stale_after / 4 / self.poll), 1) == 0:
                    self.recover()
                ticks += 1
                if not self.run_one():
                    stop.wait(self.poll)
            except Exception:
                if not self.queue.path.exists():  # data folder removed: nothing left to serve
                    return
                stop.wait(max(self.poll, 1.0))  # e.g. the database was locked for a while; try again


def start_threads(queue: JobQueue, handler: Handler, on_orphan: Callable[[Job], None] | None, count: int,
                  **kw) -> tuple[threading.Event, list[threading.Thread]]:
    stop = threading.Event()
    threads = []
    for i in range(count):
        w = Worker(queue, handler, on_orphan, **kw)
        t = threading.Thread(target=w.run_forever, args=(stop,), daemon=True, name=f"worker-{i}")
        t.start()
        threads.append(t)
    return stop, threads
