"""Reference-voice library — the clips OmniVoice clones a voice from.

Each voice is a pair of files in the library directory:

    <voices_dir>/the-lord-chosen.wav    the reference clip itself
    <voices_dir>/the-lord-chosen.json   its metadata (label, ref_text, …)

A JSON sidecar per voice (rather than one index file) means a voice can be added
by dropping in two files, and a git diff of the seed set stays readable.

The library lives on the data volume, not in the repo: on RunPod the container
filesystem is thrown away on every restart, so an uploaded clip has to land on
`/workspace`. `voices_seed/` in the repo holds the starter set and is copied in
once, when the volume is still empty (see `config.seed_voices_if_empty`).

Callers refer to a voice by its stable **id**, never by a path.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

# Extensions the library accepts. OmniVoice reads whatever soundfile/ffmpeg can
# open; this list just keeps the picker honest and the sidecar lookup cheap.
AUDIO_EXTS = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus")

# Sentinel meaning "ignore the library, I supplied a path myself". Distinct from
# "" (no reference at all) so the UI can hide the path field by default.
CUSTOM_VOICE = "__custom__"

DEFAULT_LANGUAGE = "en"

# OmniVoice's docs: a reference longer than ~10 s is slower and clones worse.
# Surfaced as a warning, never enforced — a 19 s clip still works.
IDEAL_MAX_SECONDS = 10.0


@dataclass
class Voice:
    id: str
    label: str
    audio: str                      # file name, relative to library_root()
    description: str = ""
    # Exact transcript of the clip. OmniVoice uses it to compute the speaking
    # rate; blank means it Whisper-transcribes the clip on every model load.
    ref_text: str = ""
    language: str = DEFAULT_LANGUAGE
    duration: float | None = None
    origin: str = ""                # where the clip came from, for provenance
    created_at: str = ""
    fields: dict = field(default_factory=dict)  # forward-compat extras

    def to_dict(self) -> dict:
        d = asdict(self)
        extras = d.pop("fields") or {}
        # `id` is the file stem — storing it too would let the two disagree.
        d.pop("id")
        return {**extras, **d}

    @classmethod
    def from_dict(cls, voice_id: str, data: dict) -> "Voice":
        known = {f for f in cls.__dataclass_fields__ if f not in ("id", "fields")}
        extras = {k: v for k, v in data.items() if k not in known}
        return cls(
            id=voice_id,
            label=str(data.get("label") or voice_id),
            audio=str(data.get("audio") or ""),
            description=str(data.get("description") or ""),
            ref_text=str(data.get("ref_text") or ""),
            # Absent key → the default; an explicitly blank one stays blank so a
            # deliberately unset language is not overwritten on every read.
            language=str(data.get("language", DEFAULT_LANGUAGE) or ""),
            duration=data.get("duration"),
            origin=str(data.get("origin") or ""),
            created_at=str(data.get("created_at") or ""),
            fields=extras,
        )


def library_root() -> Path:
    root = settings.resolved_voices_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def slugify(label: str) -> str:
    """`"The Lord Chosen"` → `"the-lord-chosen"`. Falls back to "voice"."""
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").strip().lower()).strip("-")
    return s or "voice"


def _sidecar(voice_id: str) -> Path:
    return library_root() / f"{voice_id}.json"


def list_voices() -> list[Voice]:
    out: list[Voice] = []
    for p in sorted(library_root().glob("*.json")):
        try:
            out.append(Voice.from_dict(p.stem, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            # Skip malformed sidecars rather than blocking the whole UI.
            continue
    return sorted(out, key=lambda v: v.label.lower())


def get_voice(voice_id: str) -> Voice:
    path = _sidecar(voice_id)
    if not path.exists():
        known = ", ".join(v.id for v in list_voices()) or "(library is empty)"
        raise FileNotFoundError(
            f"Voice '{voice_id}' not found in {library_root()}. Known voices: {known}"
        )
    return Voice.from_dict(voice_id, json.loads(path.read_text(encoding="utf-8")))


def resolve_audio(voice_id: str) -> Path:
    """Absolute path to a voice's clip. Raises if the sidecar or clip is gone."""
    voice = get_voice(voice_id)
    audio = library_root() / voice.audio
    if not audio.is_file():
        raise FileNotFoundError(
            f"Voice '{voice_id}' points at a missing clip: {audio}"
        )
    return audio


def resolve_reference(
    voice_id: str | None,
    ref_audio: str | None = None,
    ref_text: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Turn a (library id, hand-supplied path) pair into the clip actually used.

    Returns `(audio_path, ref_text, voice_id)` — `voice_id` is None when the
    caller supplied its own path. Every entry point funnels through here so they
    agree on what `voice=""` vs `voice="__custom__"` vs a real id mean.

    Raises `FileNotFoundError` for an unknown id rather than quietly falling back
    to no cloning — a wrong voice only becomes audible after the whole script is
    rendered, which on a long script is GPU-minutes wasted.
    """
    vid = (voice_id or "").strip()
    text = (ref_text or "").strip()
    if vid and vid != CUSTOM_VOICE:
        voice = get_voice(vid)
        # An explicitly supplied transcript wins over the library's.
        return str(resolve_audio(vid)), (text or voice.ref_text) or None, vid
    return (ref_audio or "").strip() or None, text or None, None


def probe_duration(path: Path) -> float | None:
    """Clip length in seconds via ffprobe, or None when ffprobe is unavailable."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return None


def save_voice(voice: Voice) -> Path:
    """Write (or rewrite) a voice's sidecar. The clip must already be in place."""
    path = _sidecar(voice.id)
    if not voice.created_at:
        voice.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(
        json.dumps(voice.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def import_audio(
    src: Path,
    *,
    label: str,
    voice_id: str | None = None,
    description: str = "",
    ref_text: str = "",
    language: str = DEFAULT_LANGUAGE,
    origin: str = "",
    overwrite: bool = False,
) -> Voice:
    """Copy an audio file into the library and write its sidecar."""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"Reference clip not found: {src}")
    ext = src.suffix.lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(
            f"Unsupported audio format {ext or '(no extension)'} — expected one "
            f"of {', '.join(AUDIO_EXTS)}"
        )

    vid = slugify(voice_id or label)
    if _sidecar(vid).exists() and not overwrite:
        raise FileExistsError(f"Voice '{vid}' already exists")

    dest = library_root() / f"{vid}{ext}"
    shutil.copy2(src, dest)

    voice = Voice(
        id=vid,
        label=label or vid,
        audio=dest.name,
        description=description,
        ref_text=ref_text,
        language=language,
        duration=probe_duration(dest),
        origin=origin,
    )
    save_voice(voice)
    return voice


def replace_audio(voice_id: str, src: Path, *, origin: str = "") -> Voice:
    """Swap a voice's clip for another file, keeping its id and metadata.

    The id is what callers store, so replacing the clip in place lets a voice be
    re-recorded without anyone updating a reference to it.
    """
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"Reference clip not found: {src}")
    ext = src.suffix.lower()
    if ext not in AUDIO_EXTS:
        raise ValueError(
            f"Unsupported audio format {ext or '(no extension)'} — expected one "
            f"of {', '.join(AUDIO_EXTS)}"
        )

    voice = get_voice(voice_id)
    dest = library_root() / f"{voice_id}{ext}"
    old = library_root() / voice.audio
    if src.resolve() == dest.resolve():
        raise ValueError("That file is already this voice's clip.")
    shutil.copy2(src, dest)
    # A different extension means the old clip is now an orphan sitting in the
    # library with no sidecar pointing at it.
    if old.is_file() and old.resolve() != dest.resolve():
        old.unlink()

    voice.audio = dest.name
    voice.duration = probe_duration(dest)
    voice.origin = origin or str(src)
    save_voice(voice)
    return voice


def rename_voice(old_id: str, new_id: str) -> Voice:
    """Give a voice a new id, renaming its clip and sidecar to match."""
    new_id = slugify(new_id)
    voice = get_voice(old_id)
    if new_id == old_id:
        return voice
    if _sidecar(new_id).exists():
        raise FileExistsError(f"Voice '{new_id}' already exists")

    old_audio = library_root() / voice.audio
    if old_audio.is_file():
        new_audio = library_root() / f"{new_id}{old_audio.suffix}"
        shutil.move(str(old_audio), str(new_audio))
        voice.audio = new_audio.name

    voice.id = new_id
    save_voice(voice)
    _sidecar(old_id).unlink(missing_ok=True)
    return voice


def delete_voice(voice_id: str) -> bool:
    """Remove a voice's sidecar and its clip. False when it did not exist."""
    path = _sidecar(voice_id)
    if not path.exists():
        return False
    try:
        audio = library_root() / get_voice(voice_id).audio
        if audio.is_file():
            audio.unlink()
    except Exception:
        pass  # sidecar is authoritative; drop it even if the clip is already gone
    path.unlink()
    return True


def export_to_seed() -> int:
    """Copy the live library back into the repo's `voices_seed/`.

    The volume is the source of truth at runtime, but a clip uploaded on the pod
    only survives that volume. Running this (via `python -m ovs.cli export-voices`)
    and committing the result is how a voice becomes permanent.
    """
    from .config import REPO_ROOT

    seed = REPO_ROOT / "voices_seed"
    seed.mkdir(parents=True, exist_ok=True)
    n = 0
    for voice in list_voices():
        clip = library_root() / voice.audio
        if not clip.is_file():
            continue
        shutil.copy2(clip, seed / clip.name)
        shutil.copy2(_sidecar(voice.id), seed / f"{voice.id}.json")
        n += 1
    return n
