"""Browse, play and download what a job produced.

Every path here is confined to `<outputs_dir>/<job_id>/`: the job id is matched
against a hex pattern and the resolved file must still sit inside that folder,
so a crafted `?name=../../ovs.db` cannot walk out of it.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ... import db
from ...config import settings
from ...generate import job_dir
from ..schemas import OutputFile, OutputSet

router = APIRouter()

# Job ids are uuid4().hex. Anything else is not a job id and never becomes a path.
JOB_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")

KINDS = {
    ".wav": "audio", ".mp3": "audio", ".flac": "audio",
    ".srt": "subtitle", ".vtt": "subtitle",
    ".txt": "text", ".md": "text", ".json": "text",
}

# Streamed inline so the browser's <audio> element can seek instead of
# downloading the whole file first.
MEDIA_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".srt": "text/plain; charset=utf-8", ".vtt": "text/vtt; charset=utf-8",
    ".txt": "text/plain; charset=utf-8", ".json": "application/json",
}


def _dir_for(job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job id")
    d = job_dir(job_id)
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="No output for that job")
    return d


def _resolve(job_id: str, name: str) -> Path:
    d = _dir_for(job_id)
    path = (d / name).resolve()
    # `Path.resolve()` collapses any `..` — after that the file must still be
    # inside the job folder.
    if not path.is_relative_to(d.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail=f"No such file: {name}")
    return path


def _describe(d: Path) -> OutputSet:
    files: list[OutputFile] = []
    total = 0
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        size = p.stat().st_size
        total += size
        files.append(
            OutputFile(name=p.name, size=size, kind=KINDS.get(p.suffix.lower(), "other"))
        )
    row = db.get_job(d.name)
    return OutputSet(
        job_id=d.name,
        created_at=row["created_at"] if row else None,
        status=row["status"] if row else None,
        files=files,
        total_size=total,
    )


@router.get("", response_model=list[OutputSet])
def list_outputs(limit: int = 50) -> list[OutputSet]:
    root = settings.resolved_outputs_dir()
    if not root.is_dir():
        return []
    dirs = sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    return [_describe(d) for d in dirs]


@router.get("/{job_id}", response_model=OutputSet)
def get_output(job_id: str) -> OutputSet:
    return _describe(_dir_for(job_id))


@router.get("/{job_id}/manifest")
def get_manifest(job_id: str) -> dict:
    path = _resolve(job_id, "manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/{job_id}/zip")
def download_zip(job_id: str):
    """Zip the whole job folder in memory and stream it out.

    A batch is typically a handful of WAVs; if that ever grows past what is
    comfortable to hold in RAM, switch to a temp file on the volume.
    """
    d = _dir_for(job_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(d.iterdir()):
            if p.is_file():
                zf.write(p, arcname=p.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job_id[:8]}.zip"'},
    )


@router.get("/{job_id}/file/{name}")
def get_file(job_id: str, name: str, download: bool = False):
    path = _resolve(job_id, name)
    media = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        # `filename=` makes it an attachment; omitting it lets <audio> stream it.
        filename=path.name if download else None,
    )


@router.delete("/{job_id}", status_code=204)
def delete_output(job_id: str) -> None:
    shutil.rmtree(_dir_for(job_id), ignore_errors=True)
    db.delete_generations_for_job(job_id)
