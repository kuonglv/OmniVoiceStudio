"""Reference-voice library CRUD + audio preview.

Thin HTTP layer over `ovs.voice_library`. Clips are uploaded from the browser:
the backend usually runs on a remote pod, so browsing its filesystem for a file
is not a thing the user can do.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ... import db
from ...voice_library import (
    AUDIO_EXTS,
    DEFAULT_LANGUAGE,
    IDEAL_MAX_SECONDS,
    Voice,
    delete_voice,
    export_to_seed,
    get_voice,
    import_audio,
    library_root,
    list_voices,
    rename_voice,
    replace_audio,
    save_voice,
    slugify,
)
from ..schemas import VoiceOut, VoiceRename, VoiceUpdate

router = APIRouter()


def _out(voice: Voice, counts: dict[str, int]) -> VoiceOut:
    return VoiceOut(
        id=voice.id,
        label=voice.label,
        description=voice.description,
        ref_text=voice.ref_text,
        language=voice.language,
        duration=voice.duration,
        origin=voice.origin,
        created_at=voice.created_at,
        audio=voice.audio,
        used_by=counts.get(voice.id, 0),
    )


def _counts() -> dict[str, int]:
    try:
        return db.voice_usage_counts()
    except Exception:  # noqa: BLE001 — usage is a nicety, not worth a 500
        return {}


@router.get("", response_model=list[VoiceOut])
def get_voices() -> list[VoiceOut]:
    counts = _counts()
    return [_out(v, counts) for v in list_voices()]


@router.get("/meta")
def get_meta() -> dict:
    """Constants the UI needs so the two never drift apart."""
    return {
        "library_root": str(library_root()),
        "audio_exts": list(AUDIO_EXTS),
        "default_language": DEFAULT_LANGUAGE,
        "ideal_max_seconds": IDEAL_MAX_SECONDS,
    }


@router.post("", response_model=VoiceOut, status_code=201)
async def create_voice(
    file: UploadFile = File(...),
    label: str = Form(...),
    description: str = Form(""),
    ref_text: str = Form(""),
    language: str = Form(DEFAULT_LANGUAGE),
    voice_id: str = Form(""),
) -> VoiceOut:
    """Add a voice by uploading its clip. The file is copied into the library."""
    name = file.filename or ""
    ext = Path(name).suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format {ext or '(no extension)'} — expected "
                   f"one of {', '.join(AUDIO_EXTS)}",
        )
    vid = slugify(voice_id or label)
    if (library_root() / f"{vid}.json").exists():
        raise HTTPException(status_code=409, detail=f"Voice '{vid}' already exists")

    # Stage the upload on disk first — import_audio copies from a real file so
    # it can probe the duration before committing anything to the library.
    with tempfile.TemporaryDirectory(prefix="voice_upload_") as td:
        staged = Path(td) / f"upload{ext}"
        with staged.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            voice = import_audio(
                staged, label=label, voice_id=vid, description=description,
                ref_text=ref_text, language=language, origin=f"uploaded: {name}",
            )
        except (ValueError, FileExistsError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(voice, _counts())


@router.post("/{voice_id}/clip", response_model=VoiceOut)
async def replace_clip(voice_id: str, file: UploadFile = File(...)) -> VoiceOut:
    """Point an existing voice at a different recording, keeping its id.

    Anything referencing this voice picks up the new clip on its next run.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format {ext or '(no extension)'}",
        )
    with tempfile.TemporaryDirectory(prefix="voice_clip_") as td:
        staged = Path(td) / f"upload{ext}"
        with staged.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            voice = replace_audio(voice_id, staged, origin=f"uploaded: {file.filename}")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(voice, _counts())


@router.patch("/{voice_id}", response_model=VoiceOut)
def update_voice(voice_id: str, body: VoiceUpdate) -> VoiceOut:
    try:
        voice = get_voice(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for key, val in body.model_dump(exclude_none=True).items():
        setattr(voice, key, val)
    save_voice(voice)
    return _out(voice, _counts())


@router.post("/{voice_id}/rename", response_model=VoiceOut)
def rename(voice_id: str, body: VoiceRename) -> VoiceOut:
    target = slugify(body.new_id or body.label or "")
    if not target:
        raise HTTPException(status_code=400, detail="new_id or label is required")
    try:
        voice = get_voice(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if target != voice_id:
        try:
            voice = rename_voice(voice_id, target)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if body.label:
        voice.label = body.label
        save_voice(voice)
    return _out(voice, _counts())


@router.delete("/{voice_id}", status_code=204)
def remove_voice(voice_id: str) -> None:
    if not delete_voice(voice_id):
        raise HTTPException(status_code=404, detail=f"Voice '{voice_id}' not found")


@router.get("/{voice_id}/audio")
def get_audio(voice_id: str):
    """Stream the clip so the UI can play it back."""
    try:
        voice = get_voice(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = library_root() / voice.audio
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Clip missing: {path}")
    return FileResponse(path, filename=voice.audio)


@router.post("/export-seed")
def export_seed() -> dict:
    """Copy the live library back into the repo's `voices_seed/` for committing.

    The library lives on the pod's volume; this is how a clip uploaded there
    becomes part of the repo and therefore survives the volume.
    """
    return {"exported": export_to_seed()}
