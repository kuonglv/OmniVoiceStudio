# Deploying on RunPod

Two routes to the same running app. Pick by whether you have a container
registry to push to.

| | Docker image | `bootstrap.sh` |
|---|---|---|
| Needs a registry account | yes | no |
| Cold start | ~1 min | ~5 min (installs packages) |
| Repeatable | exactly | depends on what pip resolves that day |
| Best for | a pod you start and stop often | trying it today |

Either way you want a **network volume**, and either way you want
`OVS_AUTH_TOKEN`.

---

## 0. The network volume (do this first)

RunPod pods are ephemeral: stop one and its filesystem is gone. Uploaded voice
clips, generated audio and — worst of all — the multi-GB OmniVoice weights all
live under `/workspace`, so without a volume every restart re-downloads the
model and loses every voice.

1. RunPod console → **Storage** → **New Network Volume**
2. Pick the same datacenter you will rent the GPU in (a volume only attaches to
   pods in its own datacenter — this is the constraint that most often forces a
   different GPU than planned).
3. Size: **50 GB** is comfortable. The model is a few GB, and an hour of 24 kHz
   mono WAV is about 170 MB.

## 1. Pick a GPU

OmniVoice is a diffusion TTS model; it wants VRAM more than it wants compute.

| GPU | VRAM | Notes |
|---|---|---|
| **RTX 4090** | 24 GB | the sweet spot — cheapest card that never runs out |
| RTX 5090 | 32 GB | sm_120, needs the cu128 build this image uses |
| L40S / A100 | 48 / 80 GB | more than needed; rent if 4090s are unavailable |
| RTX 3090 | 24 GB | works, noticeably slower |

Do not pick a CPU-only pod. `/api/health` will tell you `cuda_available: false`
and every generation fails.

## 2a. Route A — Docker image

```bash
# on your laptop
docker build -t <dockerhub-user>/omnivoice-studio:latest .
docker push  <dockerhub-user>/omnivoice-studio:latest
```

The build is amd64. On an Apple-silicon Mac add `--platform linux/amd64` (it
emulates, so expect it to be slow — a CI runner is nicer if you rebuild often).

Then in the RunPod console → **Pods** → **Deploy**:

| Field | Value |
|---|---|
| Container image | `<dockerhub-user>/omnivoice-studio:latest` |
| Container disk | 20 GB |
| Volume mount path | `/workspace` |
| Network volume | the one from step 0 |
| Expose HTTP ports | `8000` |
| Environment | `OVS_AUTH_TOKEN` = a long random string |

Generate the token with `openssl rand -hex 16`.

## 2b. Route B — `bootstrap.sh` on a stock pod

Deploy a pod from RunPod's **PyTorch 2.8 / CUDA 12.8** template with the same
volume and exposed port 8000, then in its web terminal:

```bash
cd /workspace
git clone <your-repo-url> OmniVoiceStudio
cd OmniVoiceStudio
OVS_AUTH_TOKEN=$(openssl rand -hex 16) ./bootstrap.sh
```

Clone into `/workspace`, not `~` — only `/workspace` is on the volume, so only
that survives a restart. On a later start, re-run `./bootstrap.sh`; the pip and
node installs are cached on the volume and it comes up quickly.

## 3. Open it

RunPod shows the proxy URL on the pod card:

```
https://<pod-id>-8000.proxy.runpod.net
```

The UI prompts for the token on first load. It is stored in that browser's
localStorage, so you enter it once per browser.

Sanity check before anything else — this endpoint needs no token:

```bash
curl https://<pod-id>-8000.proxy.runpod.net/api/health
```

Look for `"cuda_available": true`, the right `gpu_name`, and
`"omnivoice_installed": true`.

## 4. First run

1. **Voices** → confirm the four seeded voices are there, play one.
2. **Generate** → paste a couple of sentences, pick a voice, Generate.
   The first run loads the model — expect a minute of nothing in the log before
   `[tts] start`. Later runs skip that; the model stays in memory.
3. Download the WAV, listen, then queue the real script.

---

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `OVS_AUTH_TOKEN` | *(empty)* | Bearer token for every `/api` call. **Set it.** |
| `OVS_DATA_DIR` | `/workspace` | Root for voices, outputs, caches, the sqlite DB |
| `OVS_VOICES_DIR` | `$OVS_DATA_DIR/voices` | Override the library location |
| `OVS_OUTPUTS_DIR` | `$OVS_DATA_DIR/outputs` | Override where audio is written |
| `OVS_MODEL_ID` | `k2-fsa/OmniVoice` | Default HuggingFace model |
| `OVS_DEVICE` | `cuda:0` | Default torch device |
| `OVS_WHISPER_MODEL` | `small` | Default Whisper size for the SRT pass |
| `OVS_PORT` | `8000` | Port to serve on |
| `HF_HOME` | `$OVS_DATA_DIR/hf-cache` | Keeps model weights on the volume |

## Cost

A pod bills for wall-clock time whether or not it is generating. The model
stays loaded between jobs, which is exactly what you want *while working* and
pure waste overnight.

- **Stop the pod when you are done.** A stopped pod costs only volume storage.
- Queue a batch rather than one script at a time — you pay for the idle minutes
  between submissions either way.
- `POST /api/system/unload` frees VRAM without stopping the pod, for when you
  want to run something else on the same GPU.

## Troubleshooting

**`cuda_available: false`** — the pod has no GPU, or torch was reinstalled over
the base image's build. Do not `pip install torch` on a RunPod pytorch image.

**`No module named 'omnivoice'`** — `pip install omnivoice` inside the pod
(route B does this for you; route A bakes it into the image).

**"Text is not chunkable"** — the script has no `.`, `!` or `?`. OmniVoice
splits on punctuation, so unpunctuated text becomes one enormous segment. Add
punctuation; the guard is saving you GPU-minutes.

**The log stream stops updating** — RunPod's proxy drops idle connections. The
socket sends a keepalive every 30 s, but a dropped one recovers on reload:
reconnecting replays the job's whole log.

**Voices vanished after a restart** — the volume was not mounted at
`/workspace`. The startup log warns about this. Re-add them, then hit
**Export to repo** on the Voices page and commit `voices_seed/` so the next
pod seeds itself.

**Everything 401s** — the token in the browser does not match `OVS_AUTH_TOKEN`
on the pod. Click the token button in the header and re-enter it.
