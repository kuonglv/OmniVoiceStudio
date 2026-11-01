"""Optional subtitle pass — Whisper over the WAV we just generated.

Shells out to the `whisper` CLI (the `openai-whisper` package) rather than
importing it, so the ASR model lives in its own process and its VRAM is handed
back the moment it exits. OmniVoice is already resident and is the thing worth
keeping warm.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import settings

LogFn = Callable[[str], None]

# Languages written without spaces, in full-width glyphs: each character takes
# about two Latin widths on screen, so a line needs half the character budget.
_CJK = {"ja", "japanese", "zh", "chinese", "yue", "cantonese", "ko", "korean"}


def _noop(_: str) -> None:
    pass


@dataclass
class AsrParams:
    model: str | None = None
    output_format: str = "srt"
    # One short line per cue: what a burned-in subtitle needs. Whisper's own
    # defaults produce two long lines that overflow a 9:16 frame.
    max_line_count: int = 1
    max_line_width: int | None = None   # None: 35, or 16 for CJK languages
    language: str | None = None
    initial_prompt: str | None = None
    word_timestamps: bool = True

    def resolved_model(self) -> str:
        return (self.model or settings.whisper_model).strip()

    def is_cjk(self) -> bool:
        return (self.language or "").strip().lower() in _CJK

    def resolved_line_width(self) -> int:
        if self.max_line_width:
            return self.max_line_width
        return 16 if self.is_cjk() else 35


class WhisperMissing(RuntimeError):
    """The `whisper` binary is not on PATH."""


def transcribe(wav: Path, out_dir: Path, params: AsrParams, *, on_log: LogFn = _noop) -> Path:
    """Write `<out_dir>/<wav stem>.<format>` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "whisper", str(wav),
        "--model", params.resolved_model(),
        "--output_format", params.output_format,
        "--word_timestamps", "True" if params.word_timestamps else "False",
        "--max_line_width", str(params.resolved_line_width()),
        "--max_line_count", str(params.max_line_count),
        "--output_dir", str(out_dir),
    ]
    if params.language:
        # Without this Whisper guesses from the first 30 s, and smaller models
        # misread Japanese TTS as Chinese or translate it into English.
        cmd += ["--language", params.language.strip()]
    if params.initial_prompt:
        cmd += ["--initial_prompt", params.initial_prompt]

    lang = params.language or "auto-detect"
    on_log(f"[asr] whisper {params.resolved_model()} ({lang}) on {wav.name} …")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise WhisperMissing(
            "The `whisper` binary is not on PATH — install `openai-whisper` "
            "in this environment to generate subtitles, or turn the SRT pass off."
        ) from exc
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()[-3:]
        raise RuntimeError("whisper failed: " + " | ".join(tail))

    out = out_dir / f"{wav.stem}.{params.output_format}"
    if not out.is_file():
        raise RuntimeError(f"whisper reported success but {out.name} is missing")
    on_log(f"[asr] done — {out.name}")
    return out


def whisper_available() -> bool:
    try:
        subprocess.run(["whisper", "--help"], capture_output=True, timeout=30)
        return True
    except Exception:
        return False
