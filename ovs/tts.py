"""OmniVoice synthesis.

One `synthesize()` for the whole app. Everything here that looks like a small
detail was paid for in bad audio at some point — see the comments before
changing any of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import settings
from .voice_library import resolve_reference

# Used only if the loaded model does not expose `sampling_rate`.
FALLBACK_SAMPLE_RATE = 24000

# Sentinel `voice` value meaning "no reference at all".
VOICE_NONE = ""

LogFn = Callable[[str], None]


def _noop(_: str) -> None:
    pass


def normalize_text(text: str) -> str:
    """Collapse every whitespace run to a single space.

    OmniVoice's duration estimator charges a newline the same weight as a spoken
    Latin letter (1.0) — a Windows CRLF pair 2.0 — against 0.2 for a space.
    Since the model must fill the duration it was given, a hard-wrapped or
    pasted-from-Word script buys extra time at every line break and the model
    fills it with a pause, right where there is no punctuation.
    """
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Group sentences into ~`max_chars` blocks.

    NOT used for synthesis — OmniVoice chunks internally. This only powers the
    pre-flight punctuation check below.
    """
    sentences = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks or [text.strip()]


class UnchunkableText(ValueError):
    """Raised when a script has no sentence punctuation to break on."""


def check_chunkable(text: str, max_chars: int = 300) -> None:
    """Refuse text OmniVoice would turn into one enormous segment.

    OmniVoice splits on punctuation too, so a script with no `.!?` becomes a
    single chunk that takes many GPU-minutes and comes out flat. Failing here
    costs a second; failing inside `generate()` costs the whole render.
    """
    biggest = max(len(c) for c in split_sentences(text, max_chars=max_chars))
    if biggest > max_chars * 2:
        raise UnchunkableText(
            f"Text is not chunkable ({biggest} chars in a single block, limit is "
            f"{max_chars}). The script probably lacks '.', '!' or '?' sentence "
            f"breaks — OmniVoice chunks on punctuation, so it would generate one "
            f"enormous segment. Add punctuation, or raise max_chars_per_chunk."
        )


# Loaded models, keyed by (model_id, device). Loading OmniVoice takes tens of
# seconds and several GB; a pod serves many requests from one process, so the
# model is loaded once and kept warm. This is the main reason a long-lived pod
# beats a serverless cold start here.
_MODEL_CACHE: dict[tuple[str, str], object] = {}


def is_model_loaded(model_id: str | None = None, device: str | None = None) -> bool:
    key = (model_id or settings.model_id, device or settings.device)
    return key in _MODEL_CACHE


def load_model(model_id: str, device: str, *, on_log: LogFn = _noop):
    key = (model_id, device)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached

    try:
        from omnivoice import OmniVoice
    except ImportError as exc:
        raise RuntimeError(
            "The `omnivoice` package is not installed in this environment. "
            "OmniVoice Studio is meant to run on a GPU box (RunPod pod / local "
            "CUDA machine) — see runpod/README.md."
        ) from exc

    on_log(f"[load] OmniVoice {model_id} on {device} …")
    try:
        import torch

        kwargs = {"device_map": device, "dtype": torch.float16}
    except ImportError:
        kwargs = {"device_map": device}
    try:
        model = OmniVoice.from_pretrained(model_id, **kwargs)
    except Exception as exc:  # noqa: BLE001 - surface load failure verbatim
        raise RuntimeError(f"OmniVoice load failed: {type(exc).__name__}: {exc}") from exc

    on_log("[load] model ready")
    _MODEL_CACHE[key] = model
    return model


def unload_models() -> int:
    """Drop cached models and free VRAM. Returns how many were released."""
    n = len(_MODEL_CACHE)
    _MODEL_CACHE.clear()
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return n


@dataclass
class SynthesisParams:
    """Everything the model's `generate()` takes, plus how to pick the voice."""

    voice: str = VOICE_NONE          # library id, "" or "__custom__"
    ref_audio: str | None = None     # only when voice is "" / "__custom__"
    ref_text: str | None = None
    language: str | None = None
    speed: float = 1.0
    num_step: int = 32
    guidance_scale: float = 2.0
    audio_chunk_duration: float = 15.0
    audio_chunk_threshold: float = 30.0
    max_chars_per_chunk: int = 300
    model_id: str | None = None
    device: str | None = None

    def resolved_model_id(self) -> str:
        return (self.model_id or settings.model_id).strip()

    def resolved_device(self) -> str:
        return (self.device or settings.device).strip()


@dataclass
class SynthesisResult:
    audio: "object"          # np.ndarray, float32 mono
    sample_rate: int
    seconds: float
    chars: int
    voice_id: str | None
    ref_audio: str | None


def synthesize(text: str, params: SynthesisParams, *, on_log: LogFn = _noop) -> SynthesisResult:
    """Render `text` to a mono float32 waveform.

    The whole script goes through ONE `generate()` call. OmniVoice splits long
    text itself (audio_chunk_duration / audio_chunk_threshold), cross-fades the
    pieces and — when no reference is given — reuses its first chunk as the
    voice reference for the rest. Splitting the text here instead would give
    every piece an independent voice, its own peak normalisation and its own
    fade in/out: that is what makes output stutter and change timbre mid-script.
    """
    import numpy as np

    text = normalize_text(text)
    if not text:
        raise ValueError("Nothing to synthesize — the script is empty.")
    check_chunkable(text, max_chars=params.max_chars_per_chunk)

    ref_audio, ref_text, voice_id = resolve_reference(
        params.voice, params.ref_audio, params.ref_text
    )
    if ref_audio and not Path(ref_audio).is_file():
        raise FileNotFoundError(f"Reference clip not found: {ref_audio}")
    # ref_text feeds speed_factor = ref_weight / ref_audio_duration, so its
    # whitespace skews every duration estimate the same way the script's does.
    ref_text = normalize_text(ref_text or "") or None

    model = load_model(params.resolved_model_id(), params.resolved_device(), on_log=on_log)

    gen_kwargs: dict = {
        "num_step": params.num_step,
        "guidance_scale": params.guidance_scale,
        "audio_chunk_duration": params.audio_chunk_duration,
        "audio_chunk_threshold": params.audio_chunk_threshold,
    }
    if params.language:
        gen_kwargs["language"] = params.language
    # speed stretches the duration the model has to fill, so only send it when
    # a different rate was actually asked for.
    if params.speed and params.speed != 1.0:
        gen_kwargs["speed"] = params.speed
    if ref_audio:
        gen_kwargs["ref_audio"] = ref_audio
        if ref_text:
            gen_kwargs["ref_text"] = ref_text

    on_log(
        f"[tts] {len(text)} chars, voice={voice_id or ('custom' if ref_audio else 'none')}, "
        f"speed={params.speed}, num_step={params.num_step}"
    )
    audio = model.generate(text=text, **gen_kwargs)
    arr = audio[0] if isinstance(audio, (list, tuple)) else audio
    full = np.asarray(arr).squeeze().astype(np.float32, copy=False)
    if full.ndim == 0 or full.size == 0:
        raise RuntimeError("OmniVoice returned empty audio.")

    sample_rate = int(getattr(model, "sampling_rate", None) or FALLBACK_SAMPLE_RATE)
    seconds = len(full) / sample_rate
    on_log(f"[tts] done — {seconds:.1f}s of audio at {sample_rate} Hz")

    return SynthesisResult(
        audio=full,
        sample_rate=sample_rate,
        seconds=seconds,
        chars=len(text),
        voice_id=voice_id,
        ref_audio=ref_audio,
    )


def write_wav(result: SynthesisResult, path: Path) -> Path:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), result.audio, result.sample_rate)
    return path
