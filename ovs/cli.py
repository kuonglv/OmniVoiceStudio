"""Command line for the things you do without the browser.

    python -m ovs.cli voices                       list the library
    python -m ovs.cli add-voice clip.wav "Label"   import a clip
    python -m ovs.cli export-voices                copy the library into voices_seed/
    python -m ovs.cli say script.txt -o out/       synthesize one file

Handy over SSH on a pod, and the only way to drive this from a shell script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import db
from .asr import AsrParams, transcribe
from .config import ensure_dirs, hf_cache_hint, seed_voices_if_empty, settings
from .tts import SynthesisParams, synthesize, write_wav
from .voice_library import export_to_seed, import_audio, list_voices


def cmd_voices(_: argparse.Namespace) -> int:
    voices = list_voices()
    if not voices:
        print(f"No voices in {settings.resolved_voices_dir()}")
        return 0
    width = max(len(v.id) for v in voices)
    for v in voices:
        dur = f"{v.duration:.1f}s" if v.duration else "  ? "
        mark = "" if v.ref_text else "  (no transcript)"
        print(f"{v.id:<{width}}  {dur:>6}  {v.label}{mark}")
    return 0


def cmd_add_voice(args: argparse.Namespace) -> int:
    voice = import_audio(
        Path(args.clip),
        label=args.label,
        voice_id=args.id,
        ref_text=args.ref_text,
        language=args.language,
        description=args.description,
        origin=str(Path(args.clip).resolve()),
    )
    print(f"Added '{voice.id}' ({voice.duration}s) → {settings.resolved_voices_dir()}")
    if not voice.ref_text:
        print("No transcript given — the clip is re-transcribed on every model load.")
    return 0


def cmd_export_voices(_: argparse.Namespace) -> int:
    n = export_to_seed()
    print(f"Copied {n} voice(s) into voices_seed/. Commit them to keep them.")
    return 0


def cmd_say(args: argparse.Namespace) -> int:
    text = Path(args.script).read_text(encoding="utf-8-sig")
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    params = SynthesisParams(
        voice=args.voice or "",
        language=args.language,
        speed=args.speed,
        num_step=args.num_step,
        device=args.device,
    )
    result = synthesize(text, params, on_log=lambda m: print(m, flush=True))
    wav = write_wav(result, out_dir / f"{Path(args.script).stem}.wav")
    print(f"{wav}  ({result.seconds:.1f}s)")

    if args.srt:
        srt = transcribe(wav, out_dir, AsrParams(model=args.whisper_model),
                         on_log=lambda m: print(m, flush=True))
        print(srt)

    db.record_generation(
        job_id=None, name=wav.stem, voice_id=result.voice_id,
        chars=result.chars, seconds=round(result.seconds, 1),
        wav_path=str(wav), srt_path=None,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    hf_cache_hint()
    ensure_dirs()
    db.init_db()
    seed_voices_if_empty()

    p = argparse.ArgumentParser(prog="ovs", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("voices", help="list the voice library").set_defaults(fn=cmd_voices)

    a = sub.add_parser("add-voice", help="import a clip into the library")
    a.add_argument("clip", help="path to the audio file")
    a.add_argument("label", help="human-readable name")
    a.add_argument("--id", default=None, help="explicit id (default: from the label)")
    a.add_argument("--ref-text", default="", help="exact transcript of the clip")
    a.add_argument("--language", default="en")
    a.add_argument("--description", default="")
    a.set_defaults(fn=cmd_add_voice)

    sub.add_parser(
        "export-voices", help="copy the library into voices_seed/ for committing"
    ).set_defaults(fn=cmd_export_voices)

    s = sub.add_parser("say", help="synthesize one script file")
    s.add_argument("script", help="path to a .txt")
    s.add_argument("-o", "--output", default=".", help="output directory")
    s.add_argument("--voice", default=None, help="library voice id")
    s.add_argument("--language", default=None)
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--num-step", type=int, default=32)
    s.add_argument("--device", default=None)
    s.add_argument("--srt", action="store_true", help="also run Whisper")
    s.add_argument("--whisper-model", default=None)
    s.set_defaults(fn=cmd_say)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except Exception as exc:  # noqa: BLE001 — a CLI should not print a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
