"""Durable job queue on SQLite (stdlib): state survives restarts and is shared by processes.

A job is a row {kind, project, owner, params}. Any worker, in the API process or in a separate
`shorts-studio worker` process, claims the oldest queued job atomically, keeps a heartbeat while it runs, and
finishes or fails it. A running job whose heartbeat stopped (its worker died) is marked failed by `recover_stale`
so the UI never shows a job that will never finish.

Each operation opens its own short connection, so threads and processes can share one database file.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

LOG_KEEP = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    project TEXT NOT NULL,
    owner TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    log TEXT NOT NULL DEFAULT '[]',
    result TEXT,
    error TEXT,
    worker TEXT,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    heartbeat REAL
);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs (state, created);
CREATE INDEX IF NOT EXISTS jobs_owner_project ON jobs (owner, project, created);
"""


@dataclass
class Job:
    id: str
    kind: str
    project: str
    owner: str = "local"
    params: dict = field(default_factory=dict)
    state: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    log: list[str] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    worker: str | None = None
    created: float = 0.0
    started: float | None = None
    finished: float | None = None
    heartbeat: float | None = None

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "project": self.project, "state": self.state,
                "progress": round(self.progress, 3), "log": self.log[-40:], "result": self.result,
                "error": self.error, "created": self.created}


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(row["id"], row["kind"], row["project"], row["owner"], json.loads(row["params"]), row["state"],
               row["progress"], json.loads(row["log"]), row["result"], row["error"], row["worker"], row["created"],
               row["started"], row["finished"], row["heartbeat"])


class JobQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    @contextlib.contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)  # autocommit; we open transactions explicitly
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    @contextlib.contextmanager
    def _tx(self):
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")

    # --- producers ---------------------------------------------------------------------------------------------

    def submit(self, kind: str, project: str, owner: str, params: dict | None = None) -> Job:
        job = Job(uuid.uuid4().hex[:10], kind, project, owner, params or {}, created=time.time())
        with self._tx() as c:
            c.execute("INSERT INTO jobs (id, kind, project, owner, params, created) VALUES (?, ?, ?, ?, ?, ?)",
                      (job.id, kind, project, owner, json.dumps(job.params), job.created))
        return job

    def submit_unique(self, kind: str, project: str, owner: str, params: dict | None = None) -> Job | None:
        """Submit unless the same kind is already queued or running for this project; None when it is."""
        with self._tx() as c:
            busy = c.execute("SELECT 1 FROM jobs WHERE owner=? AND project=? AND kind=? "
                             "AND state IN ('queued','running')", (owner, project, kind)).fetchone()
            if busy:
                return None
            job = Job(uuid.uuid4().hex[:10], kind, project, owner, params or {}, created=time.time())
            c.execute("INSERT INTO jobs (id, kind, project, owner, params, created) VALUES (?, ?, ?, ?, ?, ?)",
                      (job.id, kind, project, owner, json.dumps(job.params), job.created))
        return job

    # --- readers -----------------------------------------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def active(self, project: str, kind: str, owner: str = "local") -> Job | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE owner=? AND project=? AND kind=? "
                            "AND state IN ('queued','running') LIMIT 1", (owner, project, kind)).fetchone()
        return _row_to_job(row) if row else None

    def list(self, project: str | None = None, owner: str = "local") -> list[Job]:
        with self._conn() as c:
            if project is None:
                rows = c.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created DESC", (owner,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM jobs WHERE owner=? AND project=? ORDER BY created DESC",
                                 (owner, project)).fetchall()
        return [_row_to_job(r) for r in rows]

    # --- workers -----------------------------------------------------------------------------------------------

    def claim(self, worker: str) -> Job | None:
        """Atomically take the oldest queued job; two workers can never get the same one."""
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            c.execute("UPDATE jobs SET state='running', worker=?, started=?, heartbeat=? WHERE id=?",
                      (worker, now, now, row["id"]))
            row = c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
        return _row_to_job(row)

    def report(self, job_id: str, line: str, progress: float | None = None) -> None:
        with self._tx() as c:
            row = c.execute("SELECT log FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return
            log = [*json.loads(row["log"]), line][-LOG_KEEP:]
            if progress is None:
                c.execute("UPDATE jobs SET log=?, heartbeat=? WHERE id=?", (json.dumps(log), time.time(), job_id))
            else:
                c.execute("UPDATE jobs SET log=?, progress=?, heartbeat=? WHERE id=?",
                          (json.dumps(log), progress, time.time(), job_id))

    def heartbeat(self, job_id: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE jobs SET heartbeat=? WHERE id=? AND state='running'", (time.time(), job_id))

    def finish(self, job_id: str, result: str | None) -> None:
        with self._tx() as c:
            c.execute("UPDATE jobs SET state='done', progress=1.0, result=?, finished=? WHERE id=?",
                      (result, time.time(), job_id))

    def fail(self, job_id: str, error: str, detail: str = "") -> None:
        with self._tx() as c:
            row = c.execute("SELECT log FROM jobs WHERE id=?", (job_id,)).fetchone()
            log = json.loads(row["log"]) if row else []
            if detail:
                log = [*log, detail][-LOG_KEEP:]
            c.execute("UPDATE jobs SET state='failed', error=?, log=?, finished=? WHERE id=?",
                      (error, json.dumps(log), time.time(), job_id))

    def recover_stale(self, max_age: float) -> list[Job]:
        """Mark running jobs whose worker stopped sending heartbeats as failed; returns them (for refunds)."""
        cutoff = time.time() - max_age
        with self._tx() as c:
            rows = c.execute("SELECT * FROM jobs WHERE state='running' AND COALESCE(heartbeat, 0) < ?",
                             (cutoff,)).fetchall()
            for row in rows:
                c.execute("UPDATE jobs SET state='failed', error=?, finished=? WHERE id=?",
                          ("worker stopped before the job finished", time.time(), row["id"]))
        return [_row_to_job(r) for r in rows]
