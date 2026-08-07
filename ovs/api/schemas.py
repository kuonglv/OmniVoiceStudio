"""Wire types shared by the routes and (mirrored by hand) the frontend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..voice_library import DEFAULT_LANGUAGE


# -- voices -----------------------------------------------------------------


class VoiceOut(BaseModel):
    id: str
    label: str
    description: str = ""
    ref_text: str = ""
    language: str = DEFAULT_LANGUAGE
    duration: float | None = None
    origin: str = ""
    created_at: str = ""
    audio: str = ""
    used_by: int = 0   # clips generated with this voice


class VoiceUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    ref_text: str | None = None
    language: str | None = None


class VoiceRename(BaseModel):
    new_id: str | None = None
    label: str | None = None


# -- generation -------------------------------------------------------------


class ScriptItem(BaseModel):
    name: str = ""
    text: str


class SynthesisIn(BaseModel):
    """Mirrors `ovs.tts.SynthesisParams`."""

    voice: str = ""
    ref_audio: str | None = None
    ref_text: str | None = None
    language: str | None = None
    speed: float = 1.0
    num_step: int = Field(default=32, ge=1, le=200)
    guidance_scale: float = 2.0
    audio_chunk_duration: float = 15.0
    audio_chunk_threshold: float = 30.0
    max_chars_per_chunk: int = Field(default=300, ge=50)
    model_id: str | None = None
    device: str | None = None


class AsrIn(BaseModel):
    """Mirrors `ovs.asr.AsrParams`."""

    model: str | None = None
    output_format: str = "srt"
    max_line_count: int = 1
    max_line_width: int = 35
    language: str | None = None
    initial_prompt: str | None = None
    word_timestamps: bool = True


class GenerateRequest(BaseModel):
    items: list[ScriptItem] = Field(min_length=1)
    make_srt: bool = False
    synthesis: SynthesisIn = Field(default_factory=SynthesisIn)
    asr: AsrIn = Field(default_factory=AsrIn)


class GenerateAccepted(BaseModel):
    job_id: str
    output_dir: str
    items: int


# -- jobs -------------------------------------------------------------------


class Job(BaseModel):
    id: str
    kind: str
    status: str
    progress: float
    params: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class JobLog(BaseModel):
    id: int
    ts: str
    stream: str
    line: str


# -- outputs ----------------------------------------------------------------


class OutputFile(BaseModel):
    name: str
    size: int
    kind: str          # "audio" | "subtitle" | "text" | "other"


class OutputSet(BaseModel):
    job_id: str
    created_at: str | None = None
    status: str | None = None
    files: list[OutputFile] = []
    total_size: int = 0
