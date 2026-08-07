#!/usr/bin/env bash
# Prepare the data volume, then serve. Anything that would silently cost the
# user data or money is a loud warning here rather than a surprise later.
set -euo pipefail

DATA_DIR="${OVS_DATA_DIR:-/workspace}"
PORT="${OVS_PORT:-8000}"

echo "=== OmniVoice Studio ==="

# A pod started without a network volume still has a /workspace — it is just
# part of the container and disappears with it. `mountpoint` is what tells the
# two apart, and getting this wrong means losing every uploaded voice.
if command -v mountpoint >/dev/null 2>&1 && ! mountpoint -q "$DATA_DIR" 2>/dev/null; then
  echo "WARNING: $DATA_DIR is not a mounted volume. Uploaded voices and"
  echo "         generated audio will be LOST when this pod is recycled."
  echo "         Attach a RunPod network volume at $DATA_DIR."
fi

mkdir -p "$DATA_DIR"/{voices,outputs,hf-cache,cache}

if [ -z "${OVS_AUTH_TOKEN:-}" ]; then
  echo "WARNING: OVS_AUTH_TOKEN is not set. The pod's proxy URL is public and"
  echo "         anyone who reaches it can upload files and use the GPU."
  echo "         Set OVS_AUTH_TOKEN in the pod's environment variables."
fi

python - <<'PY'
import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"GPU     : {p.name} ({p.total_memory / 1024**3:.0f} GB, sm_{p.major}{p.minor})")
else:
    print("GPU     : none visible — synthesis will fail. Is this a GPU pod?")
print(f"torch   : {torch.__version__}")
PY

echo "data dir: $DATA_DIR"
echo "port    : $PORT"
echo "========================"

exec uvicorn ovs.api.main:app --host 0.0.0.0 --port "$PORT" --workers 1
