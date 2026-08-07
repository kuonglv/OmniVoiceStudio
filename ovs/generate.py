"""The job body: a batch of scripts in, WAV (+ optional SRT) out.

Output for one job lands in a single folder so the whole batch can be zipped
and downloaded as a unit:

    <outputs_dir>/<job_id>/
      manifest.json
      chapter-01.txt      the exact text that was synthesized
      chapter-01.wav
      chapter-01.srt      when subtitles were requested
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import db
from .asr import AsrParams, WhisperMissing, transcribe
from .config import settings
from .tts import SynthesisParams, UnchunkableText, synthesize, write_wav

# Names come from user-supplied filenames or a typed title, and become paths.
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str, fallback: str = "script") -> str:
    """A filename-safe stem. Keeps it short — a long name plus a deep output
    path is how you end up with unopenable files on a Windows client."""
    stem = _SAFE.sub("-", (name or "").strip()).strip("-.")
    return (stem or fallback)[:80]


@dataclass
class Item:
    name: str
    text: str


def job_dir(job_id: str) -> Path:
    return settings.resolved_outputs_dir() / job_id


def run_batch(emit, params: dict) -> dict:
    """Synthesize every item. Called by JobManager in a worker thread.

    One failing item does not abort the batch — a 20-script run should not be
    lost to one script with no punctuation. Failures are counted, logged and
    reported in the result.
    """
    from .jobs import manager

    job_id: str = params["job_id"]
    items = [Item(**it) for it in params["items"]]
    make_srt: bool = bool(params.get("make_srt"))
    syn = SynthesisParams(**params["synthesis"])
    asr = AsrParams(**params.get("asr", {}))

    out_dir = job_dir(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(items)
    emit(f"Output folder: {out_dir}")
    emit(f"{total} script(s) to synthesize" + (" (+ subtitles)" if make_srt else ""))

    results: list[dict] = []
    ok = failed = 0
    # Reserve the last slice of the bar for writing the manifest so it never
    # sits at 100% while the job is still doing something.
    for i, item in enumerate(items, 1):
        if manager.cancel_requested(job_id):
            emit(f"Cancelled — stopped after {i - 1}/{total}.", stream="stderr")
            break

        stem = safe_name(item.name, fallback=f"script-{i:02d}")
        emit("")
        emit(f"=== [{i}/{total}] {stem} ===")
        entry: dict = {"name": stem, "chars": len(item.text)}
        started = time.time()

        try:
            (out_dir / f"{stem}.txt").write_text(item.text, encoding="utf-8")
            result = synthesize(item.text, syn, on_log=emit)
            wav = write_wav(result, out_dir / f"{stem}.wav")
            entry.update(
                wav=wav.name,
                seconds=round(result.seconds, 1),
                sample_rate=result.sample_rate,
                voice_id=result.voice_id,
                chars=result.chars,
            )
            emit(f"[ok] {wav.name} — {result.seconds:.1f}s in {time.time() - started:.0f}s")

            srt_path = None
            if make_srt:
                try:
                    srt_path = transcribe(wav, out_dir, asr, on_log=emit)
                    entry["srt"] = srt_path.name
                except WhisperMissing as exc:
                    # Losing subtitles must not lose the audio that took minutes
                    # of GPU time to produce.
                    emit(f"[asr] skipped — {exc}", stream="stderr")
                    entry["srt_error"] = str(exc)
                except Exception as exc:  # noqa: BLE001
                    emit(f"[asr] FAILED — {exc}", stream="stderr")
                    entry["srt_error"] = str(exc)

            db.record_generation(
                job_id=job_id,
                name=stem,
                voice_id=result.voice_id,
                chars=result.chars,
                seconds=round(result.seconds, 1),
                wav_path=str(wav),
                srt_path=str(srt_path) if srt_path else None,
                params_json=json.dumps(asdict(syn), ensure_ascii=False),
            )
            entry["ok"] = True
            ok += 1
        except UnchunkableText as exc:
            emit(f"[fail] {stem}: {exc}", stream="stderr")
            entry.update(ok=False, error=str(exc))
            failed += 1
        except Exception as exc:  # noqa: BLE001
            emit(f"[fail] {stem}: {type(exc).__name__}: {exc}", stream="stderr")
            entry.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            failed += 1

        results.append(entry)
        emit("", progress=i / max(total, 1) * 0.98)

    manifest = {
        "job_id": job_id,
        "created_at": db.now_iso(),
        "synthesis": asdict(syn),
        "asr": asdict(asr) if make_srt else None,
        "items": results,
        "ok": ok,
        "failed": failed,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    emit("")
    emit(f"Finished. ok={ok} failed={failed} total={total}")
    if failed and not ok:
        # Every item failed — surface it as a failed job so the UI shows red,
        # not a green check over an empty folder.
        raise RuntimeError(
            f"All {failed} script(s) failed — see the log above for each reason."
        )
    return {"output_dir": str(out_dir), "ok": ok, "failed": failed, "items": results}
