"""FastAPI app — API plus, when it has been built, the static frontend.

One process on one port: RunPod exposes a pod over a single HTTP proxy URL, so
serving the UI from the same server as the API avoids a second port and any
CORS setup in production. During `pnpm dev` the UI runs on :3000 instead and
talks here cross-origin, which is what `cors_origins` covers.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import db
from ..config import REPO_ROOT, ensure_dirs, hf_cache_hint, seed_voices_if_empty, settings
from ..jobs import manager
from .auth import AuthMiddleware
from .routes import generate, jobs, outputs, system, voices


@asynccontextmanager
async def lifespan(app: FastAPI):
    hf_cache_hint()
    ensure_dirs()
    db.init_db()
    copied = seed_voices_if_empty()
    if copied:
        print(f"[ovs] seeded {copied} file(s) into {settings.resolved_voices_dir()}")
    # A pod can be stopped mid-generation; without this those jobs stay
    # "running" in the UI forever.
    stale = db.reconcile_stale_jobs()
    if stale:
        print(f"[ovs] marked {stale} stale job(s) as failed")
    manager.attach_loop(asyncio.get_running_loop())
    print(f"[ovs] data dir: {settings.data_dir}")
    if not settings.auth_token.strip():
        print("[ovs] WARNING: OVS_AUTH_TOKEN is empty — the API is unauthenticated.")
    yield


app = FastAPI(title="OmniVoice Studio", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(system.router, prefix="/api", tags=["system"])
app.include_router(voices.router, prefix="/api/voices", tags=["voices"])
app.include_router(generate.router, prefix="/api/generate", tags=["generate"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(outputs.router, prefix="/api/outputs", tags=["outputs"])


def _frontend_dist() -> Path | None:
    """Where the exported Next.js bundle lives, if it was built."""
    override = os.environ.get("OVS_FRONTEND_DIST")
    for c in ([Path(override)] if override else []) + [REPO_ROOT / "web" / "out"]:
        if (c / "index.html").exists():
            return c
    return None


_dist = _frontend_dist()
if _dist is not None:
    # Mounted last so every /api route above wins. `html=True` serves
    # `<path>.html` and falls back to index.html, which is what Next's static
    # export needs for client-side routes.
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
    print(f"[ovs] serving frontend from {_dist}")
else:
    @app.get("/")
    def _no_frontend() -> dict:
        return {
            "ok": True,
            "note": "API only — the frontend has not been built. "
                    "Run `pnpm build` in web/, or use the dev server on :3000.",
            "docs": "/docs",
        }
