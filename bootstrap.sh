#!/usr/bin/env bash
# Set up OmniVoice Studio on a stock RunPod pytorch pod — no Docker registry,
# no image build. Slower to start than the prebuilt image (this installs
# packages every time a *fresh* pod boots) but it needs nothing but this repo.
#
# On the pod's web terminal:
#
#   cd /workspace
#   git clone <your-repo-url> OmniVoiceStudio && cd OmniVoiceStudio
#   OVS_AUTH_TOKEN=$(openssl rand -hex 16) ./bootstrap.sh
#
# Clone into /workspace (the network volume) and the install survives a pod
# restart; clone into ~ and it does not.
set -euo pipefail

cd "$(dirname "$0")"
DATA_DIR="${OVS_DATA_DIR:-/workspace}"
PORT="${OVS_PORT:-8000}"

echo "=== OmniVoice Studio bootstrap ==="

if [ -z "${OVS_AUTH_TOKEN:-}" ]; then
  echo
  echo "No OVS_AUTH_TOKEN set. The pod's proxy URL is public — anyone with the"
  echo "pod id could use this GPU. Generating one:"
  OVS_AUTH_TOKEN="$(openssl rand -hex 16)"
  export OVS_AUTH_TOKEN
  echo
  echo "    OVS_AUTH_TOKEN=$OVS_AUTH_TOKEN"
  echo
  echo "Copy that — the web UI asks for it on first load."
  echo
fi

mkdir -p "$DATA_DIR"/{voices,outputs,hf-cache,cache}
export HF_HOME="${HF_HOME:-$DATA_DIR/hf-cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$DATA_DIR/cache}"
export OVS_DATA_DIR="$DATA_DIR"

# --- system packages -------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[1/4] installing ffmpeg …"
  apt-get update -qq && apt-get install -y -qq --no-install-recommends ffmpeg
else
  echo "[1/4] ffmpeg present"
fi

# --- python packages -------------------------------------------------------
# torch comes with the base image and is the right CUDA build for the pod's
# GPU. Reinstalling it here is the fastest way to break a working pod.
echo "[2/4] installing python packages …"
pip install -q --no-cache-dir -r requirements.txt
pip install -q --no-cache-dir -r requirements-gpu.txt

# --- frontend --------------------------------------------------------------
# `web/out` is gitignored (it is a build artifact), so a fresh clone has to
# build it here. Stock RunPod pytorch images carry no node, hence the install.
if [ -f web/out/index.html ] && [ "${OVS_REBUILD_WEB:-0}" != "1" ]; then
  echo "[3/4] frontend already built"
else
  if ! command -v node >/dev/null 2>&1; then
    echo "[3/4] installing node 22 …"
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
    apt-get install -y -qq nodejs
  fi
  if command -v node >/dev/null 2>&1; then
    echo "[3/4] building frontend …"
    corepack enable
    (cd web && pnpm install --frozen-lockfile && pnpm build)
  else
    echo "[3/4] node unavailable — serving the API only. The endpoints still"
    echo "      work; see /docs. Use the Docker image for the web UI."
  fi
fi

# --- go --------------------------------------------------------------------
python - <<'PY'
import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"[4/4] GPU: {p.name} ({p.total_memory / 1024**3:.0f} GB, sm_{p.major}{p.minor})")
else:
    print("[4/4] WARNING: no GPU visible — synthesis will fail.")
PY

echo
echo "Starting on port $PORT. Open the pod's HTTP :$PORT proxy URL."
exec uvicorn ovs.api.main:app --host 0.0.0.0 --port "$PORT" --workers 1
