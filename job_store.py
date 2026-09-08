"""Persistent SQLite job storage shared by web and analysis processes."""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.environ.get("MEP_DATA_DIR", os.path.join(HERE, "data")))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DB_PATH = os.path.join(DATA_DIR, "jobs.sqlite3")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    os.makedirs(DATA_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_store() -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, filename TEXT NOT NULL,
            extension TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'fast',
            status TEXT NOT NULL, stage TEXT NOT NULL, stage_num INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, completed_at REAL,
            saved INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
            worker_pid INTEGER, error TEXT)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, created_at)")


def create_job(job_id: str, owner: str, filename: str, extension: str, mode: str) -> None:
    now = time.time()
    with connect() as db:
        db.execute("""INSERT INTO jobs
            (id, owner, filename, extension, mode, status, stage, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'queued', 'Waiting in queue', ?, ?)""",
            (job_id, owner, filename, extension, mode, now, now))


def get_job(job_id: str, owner: Optional[str] = None) -> Optional[dict]:
    sql, args = "SELECT * FROM jobs WHERE id = ?", (job_id,)
    if owner is not None:
        sql, args = sql + " AND owner = ?", (job_id, owner)
    with connect() as db:
        row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def list_jobs(owner: str, limit: int = 50) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT ?",
            (owner, limit)).fetchall()
    return [dict(row) for row in rows]


def queue_position(job_id: str) -> int:
    with connect() as db:
        row = db.execute("SELECT created_at FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return 0
        return int(db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='queued' AND created_at <= ?",
            (row["created_at"],)).fetchone()[0])


def claim_next_job(worker_pid: int) -> Optional[dict]:
    now = time.time()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        changed = db.execute("""UPDATE jobs SET status='running', stage='Starting analysis',
            stage_num=0, worker_pid=?, updated_at=? WHERE id=? AND status='queued'""",
            (worker_pid, now, row["id"]))
        if changed.rowcount != 1:
            return None
    return get_job(row["id"])


def update_job(job_id: str, **fields) -> None:
    allowed = {"status", "stage", "stage_num", "completed_at", "saved",
               "cancel_requested", "worker_pid", "error", "updated_at"}
    values = {key: value for key, value in fields.items() if key in allowed}
    values.setdefault("updated_at", time.time())
    assignments = ", ".join(f"{key}=?" for key in values)
    with connect() as db:
        db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*values.values(), job_id))


def request_cancel(job_id: str, owner: str) -> Optional[dict]:
    job = get_job(job_id, owner)
    if not job:
        return None
    if job["status"] in ("queued", "running"):
        update_job(job_id, status="cancelled", stage="Cancelled", cancel_requested=1,
                   completed_at=time.time())
    return get_job(job_id, owner)


def set_saved(job_id: str, owner: str, saved: bool) -> bool:
    with connect() as db:
        result = db.execute("UPDATE jobs SET saved=?, updated_at=? WHERE id=? AND owner=?",
                            (int(saved), time.time(), job_id, owner))
    return result.rowcount == 1


def delete_job(job_id: str, owner: str) -> bool:
    job = get_job(job_id, owner)
    if not job or job["status"] == "running":
        return False
    with connect() as db:
        db.execute("DELETE FROM jobs WHERE id=? AND owner=?", (job_id, owner))
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    return True


def cleanup_expired(retention_days: int) -> int:
    cutoff = time.time() - retention_days * 86400
    with connect() as db:
        rows = db.execute("""SELECT id FROM jobs WHERE saved=0
            AND status IN ('complete','failed','cancelled') AND updated_at < ?""",
            (cutoff,)).fetchall()
        db.executemany("DELETE FROM jobs WHERE id=?", [(row["id"],) for row in rows])
    for row in rows:
        shutil.rmtree(job_dir(row["id"]), ignore_errors=True)
    return len(rows)


def recover_stale_running() -> int:
    """Requeue jobs whose previous worker no longer exists (restart/OOM recovery)."""
    recovered = 0
    with connect() as db:
        rows = db.execute("SELECT id, worker_pid FROM jobs WHERE status='running'").fetchall()
        for row in rows:
            alive = False
            if row["worker_pid"]:
                try:
                    os.kill(int(row["worker_pid"]), 0)
                    alive = True
                except (ProcessLookupError, PermissionError):
                    pass
            if not alive:
                db.execute("""UPDATE jobs SET status='queued', stage='Recovered after worker restart',
                    stage_num=0, worker_pid=NULL, updated_at=? WHERE id=?""",
                    (time.time(), row["id"]))
                recovered += 1
    return recovered


def job_dir(job_id: str) -> str:
    return os.path.join(JOBS_DIR, job_id)


def artifact_path(job_id: str, name: str) -> str:
    return os.path.join(job_dir(job_id), name)


init_store()
