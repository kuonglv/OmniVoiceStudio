# OmniVoice Studio — one image, one port.
#
# Stage 1 builds the Next.js UI to static files; stage 2 is the CUDA runtime
# that serves those files and runs the model. Keeping node out of the runtime
# image saves ~400 MB in a layer that gets pulled on every cold pod start.

# ---------------------------------------------------------------------------
# 1. frontend
# ---------------------------------------------------------------------------
FROM node:22-slim AS web

WORKDIR /build
RUN corepack enable

# Dependencies first so a UI code change does not re-resolve the whole tree.
COPY web/package.json web/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

COPY web/ ./
RUN pnpm build   # → /build/out

# ---------------------------------------------------------------------------
# 2. runtime
# ---------------------------------------------------------------------------
# cu128: RTX 50xx is sm_120 and a cu121/cu124 wheel refuses to run on it. This
# base also covers 4090 / A100 / L40S, so one image fits every pod worth renting.
FROM runpod/pytorch:2.8.0-py3.11-cuda12.8.1-devel-ubuntu22.04

# ffmpeg/ffprobe: clip duration probing and whatever soundfile hands off.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-gpu.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-gpu.txt

COPY ovs/ ./ovs/
COPY voices_seed/ ./voices_seed/
COPY docker/entrypoint.sh /entrypoint.sh
COPY --from=web /build/out ./web/out
RUN chmod +x /entrypoint.sh

# `/workspace` is where RunPod mounts a network volume. Without one the
# container's own filesystem is used and everything is lost on restart — the
# entrypoint says so out loud.
ENV OVS_DATA_DIR=/workspace \
    HF_HOME=/workspace/hf-cache \
    XDG_CACHE_HOME=/workspace/cache \
    PYTHONUNBUFFERED=1

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
