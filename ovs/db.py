"""SQLite store for jobs, their logs, and a history of generations.

Deliberately small — this app has no channels, pipelines or videos, only "text
went in, audio came out". Three tables:

    jobs         one row per submitted generation (status, params, result)
    job_logs     the streamed console output, replayed on WebSocket reconnect
    generations  one row per synthesized clip, so the Voices page can say how
                 often a voice has actually been used
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import ensure_dirs, settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,
    progress     REAL NOT NULL DEFAULT 0.0,
    params_json  TEXT NOT NULL DEFAULT '{}',
    result_json  TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS job_logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ts      TEXT NOT NULL,
    stream  TEXT NOT NULL,
    line    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generations (
    id          TEXT PRIMARY KEY,
    job_id      TEXT,
    name        TEXT NOT NULL,
    voice_id    TEXT,
    chars       INTEGER NOT NULL DEFAULT 0,
    seconds     REAL,
    wav_path    TEXT,
    srt_path    TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id, id);
CREATE INDEX IF NOT EXISTS idx_generations_voice ON generations(voice_id);
CREATE INDEX IF NOT EXISTS idx_generations_job ON generations(job_id);
"""

# Finished jobs' logs are trimmed after this many days — a long script's log is
# thousands of lines and nobody reads last month's.
JOB_LOG_RETENTION_DAYS = 7


def db_path() -> Path:
    return settings.resolved_db_path()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Jobs write logs from worker threads while the event loop reads them; WAL
    # is what keeps those from blocking each other.
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with connect() as conn:
        conn.executescript(SCHEMA)


# -- jobs -------------------------------------------------------------------


def create_job(kind: str, params_json: str = "{}") -> str:
    jid = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id, kind, status, progress, params_json, created_at) "
            "VALUES(?, ?, 'pending', 0.0, ?, ?)",
            (jid, kind, params_json, now_iso()),
        )
    try:
        prune_job_logs(JOB_LOG_RETENTION_DAYS)
    except Exception:
        pass  # never let log cleanup block job creation
    return jid


def start_job(job_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=?",
            (now_iso(), job_id),
        )


def update_job_progress(job_id: str, progress: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET progress=? WHERE id=?",
            (max(0.0, min(1.0, progress)), job_id),
        )


def finish_job(
    job_id: str,
    status: str,
    result_json: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE jobs SET status=?, completed_at=?, result_json=?, error=?,
                progress = CASE WHEN ?='succeeded' THEN 1.0 ELSE progress END
            WHERE id=?
            """,
            (status, now_iso(), result_json, error, status, job_id),
        )


def get_job(job_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def list_jobs(limit: int = 100, status: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM jobs"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY created_at DESC LIMIT ?"
    with connect() as conn:
        return conn.execute(sql, args + (limit,)).fetchall()


def delete_job(job_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def delete_jobs_by_status(statuses: list[str]) -> int:
    if not statuses:
        return 0
    marks = ",".join("?" * len(statuses))
    with connect() as conn:
        cur = conn.execute(f"DELETE FROM jobs WHERE status IN ({marks})", tuple(statuses))
        return cur.rowcount or 0


def reconcile_stale_jobs(older_than_hours: int = 6) -> int:
    """Fail jobs left `running` by a pod that was stopped mid-generation.

    A RunPod pod can be killed at any moment; without this every such job stays
    "running" forever in the UI.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    ).isoformat(timespec="seconds")
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
            SET status='failed',
                error = COALESCE(error, 'stale job: the pod restarted mid-run'),
                completed_at = COALESCE(completed_at, started_at, created_at)
            WHERE status IN ('running','pending')
              AND COALESCE(started_at, created_at) < ?
            """,
            (cutoff,),
        )
        return cur.rowcount or 0


# -- job logs ---------------------------------------------------------------


def append_job_log(job_id: str, line: str, stream: str = "stdout") -> None:
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO job_logs(job_id, ts, stream, line) VALUES(?, ?, ?, ?)",
                (job_id, now_iso(), stream, line),
            )
    except Exception:
        # The job can be deleted while its worker thread is still emitting (a
        # sync job in the executor can't be stopped synchronously), which breaks
        # the FK. Swallow that race; re-raise anything else.
        if get_job(job_id) is not None:
            raise


def list_job_logs(job_id: str, after_id: int = 0, limit: int = 5000) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM job_logs WHERE job_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (job_id, after_id, limit),
        ).fetchall()


def prune_job_logs(days: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )
    with connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM job_logs WHERE job_id IN (
                SELECT id FROM jobs
                WHERE status IN ('succeeded','failed','cancelled')
                  AND COALESCE(completed_at, created_at) < ?
            )
            """,
            (cutoff,),
        )
        return cur.rowcount or 0


# -- generations ------------------------------------------------------------


def record_generation(
    *,
    job_id: str | None,
    name: str,
    voice_id: str | None,
    chars: int,
    seconds: float | None,
    wav_path: str | None,
    srt_path: str | None,
    params_json: str = "{}",
) -> str:
    gid = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO generations(id, job_id, name, voice_id, chars, seconds, "
            "wav_path, srt_path, params_json, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (gid, job_id, name, voice_id, chars, seconds, wav_path, srt_path,
             params_json, now_iso()),
        )
    return gid


def voice_usage_counts() -> dict[str, int]:
    """voice id -> how many clips were generated with it."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT voice_id, COUNT(*) AS n FROM generations "
            "WHERE voice_id IS NOT NULL AND voice_id != '' GROUP BY voice_id"
        ).fetchall()
    return {r["voice_id"]: r["n"] for r in rows}


def list_generations(limit: int = 200, job_id: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM generations"
    args: tuple = ()
    if job_id:
        sql += " WHERE job_id = ?"
        args = (job_id,)
    sql += " ORDER BY created_at DESC LIMIT ?"
    with connect() as conn:
        return conn.execute(sql, args + (limit,)).fetchall()


def delete_generations_for_job(job_id: str) -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM generations WHERE job_id = ?", (job_id,))
        return cur.rowcount or 0
