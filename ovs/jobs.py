"""In-process job manager.

Jobs are persisted in the `jobs` + `job_logs` tables so they survive a restart,
and broadcast to WebSocket subscribers in real time. A job function receives an
`emit(line, stream, progress=)` callback that appends to the DB *and* fans out
to any live subscriber.

Synthesis runs in a thread executor rather than a subprocess: the OmniVoice
model is cached in this process (see `ovs.tts._MODEL_CACHE`), and spawning a
child would reload multiple GB of weights per job.
"""

from __future__ import annotations

import asyncio
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable

from . import db

EmitFn = Callable[..., None]  # emit(line, stream="stdout", *, progress: float|None)
JobFn = Callable[[EmitFn, dict], "dict | None"]
AsyncJobFn = Callable[[EmitFn, dict], Awaitable["dict | None"]]


class JobManager:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        # One worker: a second concurrent generation would contend for the same
        # GPU and make both slower, and OmniVoice's model object is not known to
        # be thread-safe. Queueing is the honest behaviour here.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ovs-job")
        self._subscribers: dict[str, set[asyncio.Queue[dict]]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        # Set by a running job so it can be asked to stop between items.
        self._cancel_flags: dict[str, bool] = {}

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ---- subscriptions -----------------------------------------------------

    def subscribe(self, job_id: str) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(job_id, set()).add(q)
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue[dict]) -> None:
        bucket = self._subscribers.get(job_id)
        if bucket is None:
            return
        bucket.discard(q)
        if not bucket:
            self._subscribers.pop(job_id, None)

    def _broadcast(self, job_id: str, payload: dict) -> None:
        for q in list(self._subscribers.get(job_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the oldest to make room — a slow browser must not stall
                # a running generation.
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass

    # ---- log emission ------------------------------------------------------

    def _make_emit(self, job_id: str) -> EmitFn:
        """A thread-safe emit callable. Worker code runs off the event loop, so
        broadcasting hops back onto it; the sqlite write is fine from a thread
        because `connect()` opens a fresh connection per call."""

        def emit(
            line: str = "", stream: str = "stdout", *, progress: float | None = None
        ) -> None:
            line = (line or "").rstrip("\n")
            if line:
                db.append_job_log(job_id, line, stream=stream)
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(
                        self._broadcast, job_id,
                        {"type": "log", "stream": stream, "line": line},
                    )
            if progress is not None:
                p = max(0.0, min(1.0, progress))
                db.update_job_progress(job_id, p)
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(
                        self._broadcast, job_id,
                        {"type": "status", "status": "running", "progress": p},
                    )

        return emit

    def _broadcast_status(
        self, job_id: str, status: str, *,
        progress: float | None = None, error: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"type": "status", "status": status}
        if progress is not None:
            payload["progress"] = progress
        if error is not None:
            payload["error"] = error
        self._broadcast(job_id, payload)

    # ---- cancellation ------------------------------------------------------

    def cancel_requested(self, job_id: str) -> bool:
        """Checked by long sync jobs between items — a thread in the executor
        cannot be interrupted, so cooperative cancellation is the only kind
        available. A 10-minute script still finishes its current item."""
        return self._cancel_flags.get(job_id, False)

    def cancel(self, job_id: str) -> bool:
        self._cancel_flags[job_id] = True
        task = self._tasks.get(job_id)
        if task is None:
            return False
        # Async jobs die immediately; sync ones notice the flag at the next item.
        task.cancel()
        return True

    # ---- submit ------------------------------------------------------------

    def submit_sync(self, kind: str, func: JobFn, params: dict) -> str:
        job_id = db.create_job(kind, json.dumps(params, ensure_ascii=False, default=str))
        assert self._loop is not None, "JobManager loop not attached"
        self._tasks[job_id] = self._loop.create_task(self._run_sync(job_id, func, params))
        return job_id

    async def _run_sync(self, job_id: str, func: JobFn, params: dict) -> None:
        emit = self._make_emit(job_id)
        db.start_job(job_id)
        self._broadcast_status(job_id, "running")
        try:
            assert self._loop is not None
            result = await self._loop.run_in_executor(
                self._executor, func, emit, {**params, "job_id": job_id}
            )
            result_json = (
                json.dumps(result, ensure_ascii=False, default=str)
                if result is not None else None
            )
            status = "cancelled" if self.cancel_requested(job_id) else "succeeded"
            db.finish_job(job_id, status, result_json=result_json)
            self._broadcast_status(job_id, status, progress=1.0 if status == "succeeded" else None)
        except asyncio.CancelledError:
            # The executor thread keeps running to the end of its current item;
            # the flag makes it stop after that. Mark the job now so the UI is
            # honest about the request having been made.
            db.finish_job(job_id, "cancelled", error="cancelled by user")
            self._broadcast_status(job_id, "cancelled")
        except Exception as exc:
            emit(f"ERROR: {exc}\n{traceback.format_exc()}", stream="stderr")
            db.finish_job(job_id, "failed", error=str(exc))
            self._broadcast_status(job_id, "failed", error=str(exc))
        finally:
            self._tasks.pop(job_id, None)
            self._cancel_flags.pop(job_id, None)
            self._broadcast(job_id, {"type": "close"})


manager = JobManager()
