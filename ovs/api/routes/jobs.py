"""Job listing, log replay, and the live WebSocket stream."""

from __future__ import annotations

import asyncio
import json
import shutil

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ... import db
from ...config import settings
from ...generate import job_dir
from ...jobs import manager
from ..auth import token_ok
from ..schemas import Job, JobLog

router = APIRouter()


def _job(row) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        progress=row["progress"],
        params=json.loads(row["params_json"] or "{}"),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


@router.get("", response_model=list[Job])
def list_jobs(limit: int = 100, status: str | None = None) -> list[Job]:
    return [_job(r) for r in db.list_jobs(limit=limit, status=status)]


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str) -> Job:
    row = db.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job(row)


@router.get("/{job_id}/logs", response_model=list[JobLog])
def get_logs(job_id: str, after_id: int = 0, limit: int = 5000) -> list[JobLog]:
    if db.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return [
        JobLog(id=r["id"], ts=r["ts"], stream=r["stream"], line=r["line"])
        for r in db.list_job_logs(job_id, after_id=after_id, limit=limit)
    ]


@router.post("/{job_id}/cancel")
def cancel(job_id: str) -> dict:
    if db.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ok = manager.cancel(job_id)
    return {
        "cancelled": ok,
        # Be explicit: the current script finishes rendering before the worker
        # notices. Otherwise the log looks like the cancel was ignored.
        "note": "The script currently being synthesized will finish first.",
    }


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, with_output: bool = False) -> None:
    row = db.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] in ("running", "pending"):
        manager.cancel(job_id)
    if with_output:
        shutil.rmtree(job_dir(job_id), ignore_errors=True)
    db.delete_job(job_id)


@router.post("/clear")
def clear_jobs(statuses: list[str] | None = None) -> dict:
    """Bulk-delete finished jobs. Output folders are left on the volume —
    deleting hours of generated audio as a side effect of tidying a list is not
    something a user can undo."""
    valid = {"succeeded", "failed", "cancelled"}
    statuses = statuses or list(valid)
    bad = [s for s in statuses if s not in valid]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot bulk-delete by status(es): {bad} — only finished jobs.",
        )
    return {"deleted": db.delete_jobs_by_status(statuses)}


@router.websocket("/ws/{job_id}")
async def stream(ws: WebSocket, job_id: str) -> None:
    """Stream a job's logs + status live.

    Messages: {"type":"hello"|"log"|"status"|"ping"|"close"|"error", …}
    """
    await ws.accept()

    # The middleware does not see WebSocket handshakes, so the token is checked
    # here — a browser cannot set headers on a WebSocket, hence the query param.
    if settings.auth_token.strip() and not token_ok(ws.query_params.get("token")):
        await ws.send_json({"type": "error", "error": "Missing or invalid token"})
        await ws.close()
        return

    row = db.get_job(job_id)
    if row is None:
        await ws.send_json({"type": "error", "error": "Job not found"})
        await ws.close()
        return

    # 1. Initial state + historical logs, so a reconnect sees the whole run.
    await ws.send_json({"type": "hello", "job": _job(row).model_dump()})
    for log in db.list_job_logs(job_id):
        await ws.send_json({"type": "log", "stream": log["stream"], "line": log["line"]})

    if row["status"] in ("succeeded", "failed", "cancelled"):
        await ws.send_json({
            "type": "status", "status": row["status"],
            "progress": row["progress"], "error": row["error"],
        })
        await ws.send_json({"type": "close"})
        await ws.close()
        return

    # 2. Live events.
    queue = manager.subscribe(job_id)
    try:
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # RunPod's proxy drops idle connections; a long synthesis emits
                # nothing for minutes, so keep the socket warm.
                await ws.send_json({"type": "ping"})
                continue
            await ws.send_json(payload)
            if payload.get("type") == "close":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(job_id, queue)
        try:
            await ws.close()
        except Exception:
            pass
