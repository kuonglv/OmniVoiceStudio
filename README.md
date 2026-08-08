# OmniVoice Studio

Paste a script, pick a voice, get a WAV — on a GPU box you rent by the hour.

A standalone extract of the OmniVoice half of YTAI: the reference-voice library
and the text-to-speech path, with none of the channels, pipelines or YouTube
machinery. It runs anywhere with a CUDA GPU; it is *built* to run on a RunPod
pod, where the whole app is one container behind one HTTP proxy URL.

```
┌─ web/ (Next.js, static export) ─┐
│  Generate · Voices · Jobs       │
└──────────────┬──────────────────┘
               │ same origin, one port
┌──────────────▼──────────────────┐
│  FastAPI (ovs/api)              │
│    voices  generate  jobs       │
│    outputs system                │
├─────────────────────────────────┤
│  ovs.tts    OmniVoice, cached   │
│  ovs.asr    Whisper → .srt      │
│  ovs.voice_library              │
└──────────────┬──────────────────┘
               │
      /workspace (RunPod volume)
        voices/  outputs/  hf-cache/  ovs.db
```

## What it does

- **Reference voices.** Upload a 3–10 s clip, give it an id, and every
  generation can clone it. Clips live on the data volume, seeded from
  `voices_seed/` in this repo so a fresh machine is never voiceless.
- **Scripts to speech.** Paste one script or upload a folder of `.txt` (or a
  zip). Each becomes a 24 kHz mono WAV. Progress and the model's own output
  stream to the browser live.
- **Subtitles.** Optional Whisper pass over the audio just produced, one short
  line per cue.

## Running it

**On a GPU pod** — see [runpod/README.md](runpod/README.md). That is the
intended deployment and covers the volume, the token and the two ways to get
the code onto a pod.

**On this machine, either way:**

```bash
./start.sh          # venv, deps, UI build if missing, then serve on :8000
./start.sh --dev    # + reload on Python changes
./start.sh --help   # --port, --host, --rebuild-web, --api-only, --reinstall
```

It is safe to rerun: each step is skipped when it is already done. Bound to
`127.0.0.1` unless you pass `--host`, since a blank `OVS_AUTH_TOKEN` means no
authentication.

The same by hand, on a local CUDA machine:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-gpu.txt
(cd web && pnpm install && pnpm build)
OVS_DATA_DIR=./data uvicorn ovs.api.main:app --port 8000
```

**On a laptop with no GPU** — everything except synthesis works, which is
enough to develop against:

```bash
pip install -r requirements.txt          # no torch, no omnivoice
uvicorn ovs.api.main:app --port 8000     # API + prebuilt UI
cd web && pnpm dev                       # or the UI dev server on :3000
```

Generation fails with a clear "omnivoice is not installed" error rather than
something cryptic.

## Layout

| Path | |
|---|---|
| `ovs/voice_library.py` | the library: ids, sidecars, import/rename/replace |
| `ovs/tts.py` | OmniVoice wrapper, model cache, the chunkability guard |
| `ovs/asr.py` | Whisper CLI wrapper |
| `ovs/generate.py` | the job body: a batch of scripts → files on disk |
| `ovs/jobs.py` | job manager, log persistence, WebSocket fan-out |
| `ovs/api/` | FastAPI routes and the bearer-token gate |
| `web/` | Next.js UI, statically exported and served by the API |
| `voices_seed/` | starter clips, committed; copied to the volume on first boot |
| `start.sh` | run it here; `bootstrap.sh` is the pod's equivalent |

## Notes worth keeping

A few things here look like small details and are not:

- **One `generate()` call per script.** OmniVoice chunks long text itself and
  cross-fades the pieces. Splitting the text first gives every piece its own
  voice, its own normalisation and its own fades — that is what makes output
  stutter and drift mid-script.
- **Whitespace is collapsed before synthesis.** The duration estimator charges a
  newline like a spoken letter, so a hard-wrapped script buys silence at every
  line break and the model fills it with a pause.
- **Text with no `.!?` is rejected up front.** The model chunks on punctuation
  too, so it would otherwise spend GPU-minutes on one enormous segment.
- **Voices are ids, not paths.** A path only resolves on the box that wrote it;
  an id resolves everywhere. This is the whole reason the library exists.

## Relationship to YTAI

A fork, not a dependency — the two share no code at runtime. YTAI keeps its own
copy of `voice_library.py` and its `omnivoice_tts` pipeline step, and keeps
working unchanged. If you improve the synthesis logic here, it does not
propagate; port it deliberately or not at all.
