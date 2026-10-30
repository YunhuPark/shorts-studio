"""In-process background jobs for the local dashboard (image regeneration, rendering)."""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

Report = Callable[[str, float | None], None]


@dataclass
class Job:
    id: str
    kind: str
    project: str
    state: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    log: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project": self.project, "state": self.state,
                "progress": round(self.progress, 3), "log": self.log[-40:], "result": self.result,
                "error": self.error, "created": self.created}


class JobManager:
    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, project: str, fn: Callable[[Report], str | None]) -> Job:
        job = Job(uuid.uuid4().hex[:10], kind, project)
        with self._lock:
            self._jobs[job.id] = job

        def run() -> None:
            def report(line: str, progress: float | None = None) -> None:
                with self._lock:
                    job.log.append(line)
                    if progress is not None:
                        job.progress = progress
            job.state = "running"
            try:
                job.result = fn(report)
                job.progress, job.state = 1.0, "done"
            except Exception as e:  # shown to the user; the traceback goes to the job log
                job.error = f"{type(e).__name__}: {e}"
                job.log.append(traceback.format_exc(limit=3))
                job.state = "failed"

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self, project: str, kind: str) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values()
                         if j.project == project and j.kind == kind and j.state in ("queued", "running")), None)

    def list(self, project: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if project is None or j.project == project]
        return sorted(jobs, key=lambda j: j.created, reverse=True)
