"""Submit a batch of scripts for synthesis."""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ...asr import AsrParams
from ...generate import job_dir, run_batch, safe_name
from ...jobs import manager
from ...tts import SynthesisParams
from ...voice_library import get_voice
from ..schemas import AsrIn, GenerateAccepted, GenerateRequest, ScriptItem, SynthesisIn

router = APIRouter()

# Text files inside an uploaded .zip. Anything else (images, .docx) is ignored
# rather than rejected, so a folder zipped wholesale still works.
TEXT_EXTS = {".txt", ".md"}
MAX_ZIP_ENTRIES = 500


def _validate_voice(syn: SynthesisIn) -> None:
    """Fail an unknown voice id now, at 400, instead of inside the job.

    A job that dies on the voice lookup has already queued behind the GPU and
    shows up as a red row the user has to open to understand.
    """
    vid = (syn.voice or "").strip()
    if vid and vid != "__custom__":
        try:
            get_voice(vid)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif syn.ref_audio and not Path(syn.ref_audio).is_file():
        raise HTTPException(
            status_code=400, detail=f"Reference clip not found: {syn.ref_audio}"
        )


def _submit(items: list[ScriptItem], make_srt: bool, syn: SynthesisIn, asr: AsrIn) -> GenerateAccepted:
    _validate_voice(syn)
    cleaned = [
        {"name": it.name or f"script-{i:02d}", "text": it.text}
        for i, it in enumerate(items, 1)
        if it.text.strip()
    ]
    if not cleaned:
        raise HTTPException(status_code=400, detail="Every script is empty.")

    params = {
        "items": cleaned,
        "make_srt": make_srt,
        "synthesis": asdict(SynthesisParams(**syn.model_dump())),
        "asr": asdict(AsrParams(**asr.model_dump())),
    }
    job_id = manager.submit_sync("generate", run_batch, params)
    return GenerateAccepted(
        job_id=job_id, output_dir=str(job_dir(job_id)), items=len(cleaned)
    )


@router.post("", response_model=GenerateAccepted, status_code=202)
def generate(body: GenerateRequest) -> GenerateAccepted:
    return _submit(body.items, body.make_srt, body.synthesis, body.asr)


@router.post("/upload", response_model=GenerateAccepted, status_code=202)
async def generate_from_upload(
    files: list[UploadFile] = File(...),
    make_srt: bool = Form(False),
    # The multipart body carries the two param objects as JSON strings — a form
    # cannot nest, and duplicating 12 scalar fields here would let them drift
    # from the JSON endpoint's.
    synthesis: str = Form("{}"),
    asr: str = Form("{}"),
) -> GenerateAccepted:
    """Same as POST /api/generate, but the scripts arrive as .txt or .zip files."""
    try:
        syn = SynthesisIn(**json.loads(synthesis or "{}"))
        asr_in = AsrIn(**json.loads(asr or "{}"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Bad params: {exc}") from exc

    items: list[ScriptItem] = []
    for f in files:
        name = f.filename or "script.txt"
        ext = Path(name).suffix.lower()
        raw = await f.read()
        if ext == ".zip":
            items.extend(_items_from_zip(raw, name))
        elif ext in TEXT_EXTS or not ext:
            items.append(
                ScriptItem(name=safe_name(Path(name).stem), text=_decode(raw, name))
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"{name}: expected .txt, .md or .zip",
            )
    if not items:
        raise HTTPException(status_code=400, detail="No script files found in the upload.")
    return _submit(items, make_srt, syn, asr_in)


def _decode(raw: bytes, name: str) -> str:
    """UTF-8, tolerating the BOM a Word/Notepad export leaves at the front."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} is not UTF-8 text — re-save it as UTF-8.",
        ) from exc


def _items_from_zip(raw: bytes, zip_name: str) -> list[ScriptItem]:
    import io

    out: list[ScriptItem] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if len(names) > MAX_ZIP_ENTRIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{zip_name} has {len(names)} entries — cap is {MAX_ZIP_ENTRIES}.",
                )
            for n in sorted(names):
                p = Path(n)
                # Skip macOS resource forks, which every Finder-made zip carries.
                if p.suffix.lower() not in TEXT_EXTS or n.startswith("__MACOSX/"):
                    continue
                out.append(
                    ScriptItem(name=safe_name(p.stem), text=_decode(zf.read(n), n))
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail=f"{zip_name} is not a valid zip") from exc
    return out
