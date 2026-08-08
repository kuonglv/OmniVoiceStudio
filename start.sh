#!/usr/bin/env bash
# Start OmniVoice Studio on this machine. One command, from a fresh clone:
#
#   ./start.sh                 venv + deps + UI build if needed, then serve
#   ./start.sh --dev           same, plus --reload on Python changes
#   ./start.sh --port 8080     serve somewhere else
#   ./start.sh --rebuild-web   force a UI rebuild (after editing web/)
#   ./start.sh --api-only      skip the UI entirely
#
# This is the local counterpart to bootstrap.sh (a RunPod pod) and
# docker/entrypoint.sh (the container). It installs nothing system-wide and
# nothing GPU: on a laptop everything except synthesis works, which is enough
# to develop against.
set -euo pipefail

cd "$(dirname "$0")"

HOST="127.0.0.1"
DEV=0
REBUILD_WEB=0
API_ONLY=0
REINSTALL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dev)          DEV=1 ;;
    --port)         OVS_PORT="$2"; shift ;;
    --port=*)       OVS_PORT="${1#*=}" ;;
    --host)         HOST="$2"; shift ;;
    --host=*)       HOST="${1#*=}" ;;
    --rebuild-web)  REBUILD_WEB=1 ;;
    --api-only)     API_ONLY=1 ;;
    --reinstall)    REINSTALL=1 ;;
    # The header comment is the help text; print it until the first code line.
    -h|--help)      awk 'NR>1 && /^#/ {print substr($0,3)} NR>1 && !/^#/ {exit}' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# `.env` is read twice over: pydantic-settings reads it for the OVS_ settings,
# and the shell needs OVS_PORT/OVS_DATA_DIR here, before python starts.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

PORT="${OVS_PORT:-8000}"
DATA_DIR="${OVS_DATA_DIR:-./data}"

echo "=== OmniVoice Studio ==="

# --- python ----------------------------------------------------------------
# The venv is the repo's own; nothing here touches the system python.
if [ ! -x .venv/bin/python ]; then
  echo "[1/4] creating .venv …"
  "${PYTHON:-python3}" -m venv .venv
  REINSTALL=1
fi
PY=.venv/bin/python

# Import-checking beats a stamp file: it also catches a venv half-installed by
# an interrupted pip, which is the failure that looks like a code bug.
if [ "$REINSTALL" = "1" ] || ! "$PY" -c 'import fastapi, uvicorn, soundfile, pydantic_settings' 2>/dev/null; then
  echo "[1/4] installing python packages …"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt
else
  echo "[1/4] python packages present"
fi

# --- frontend --------------------------------------------------------------
# `web/out` is a build artifact and gitignored, so a fresh clone has none.
if [ "$API_ONLY" = "1" ]; then
  echo "[2/4] skipping UI (--api-only) — the API still serves /docs"
elif [ -f web/out/index.html ] && [ "$REBUILD_WEB" = "0" ]; then
  echo "[2/4] UI already built (--rebuild-web to redo it)"
elif command -v pnpm >/dev/null 2>&1; then
  echo "[2/4] building UI …"
  (cd web && pnpm install --frozen-lockfile && pnpm build)
elif command -v corepack >/dev/null 2>&1; then
  echo "[2/4] enabling pnpm via corepack, then building UI …"
  corepack enable
  (cd web && pnpm install --frozen-lockfile && pnpm build)
else
  echo "[2/4] no pnpm/node — serving the API only. Install node 20+ and rerun,"
  echo "      or use the endpoints directly at /docs."
fi

# --- data + caches ---------------------------------------------------------
mkdir -p "$DATA_DIR"/{voices,outputs,hf-cache,cache}
export OVS_DATA_DIR="$DATA_DIR"
export HF_HOME="${HF_HOME:-$DATA_DIR/hf-cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$DATA_DIR/cache}"
echo "[3/4] data dir: $DATA_DIR"

# --- what this box can actually do -----------------------------------------
# Reported up front, because a machine with no GPU looks identical in the UI
# until a job fails.
"$PY" - <<'PY'
try:
    import torch
except ModuleNotFoundError:
    print("[4/4] torch not installed — synthesis unavailable (CPU dev mode).")
else:
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"[4/4] GPU: {p.name} ({p.total_memory / 1024**3:.0f} GB, sm_{p.major}{p.minor})")
    else:
        print("[4/4] torch present but no GPU visible — synthesis will fail.")
PY

# A blank token means anyone who reaches the port can use it. Bound to
# localhost that is fine and is the default; bound to 0.0.0.0 it is not.
if [ -z "${OVS_AUTH_TOKEN:-}" ] && [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "localhost" ]; then
  echo
  echo "WARNING: serving on $HOST with no OVS_AUTH_TOKEN — anyone on the"
  echo "         network can upload files and use this machine. Set one in"
  echo "         .env (openssl rand -hex 16)."
fi

# Fail here with a clear message rather than inside uvicorn's traceback.
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo
  echo "error: port $PORT is already in use. Stop it, or pass --port <n>." >&2
  exit 1
fi

echo
echo "→ http://$HOST:$PORT   (API docs at /docs)"
echo

RELOAD=()
if [ "$DEV" = "1" ]; then
  # Watch only the package: --reload on the repo root would restart the server
  # every time a job writes a WAV into data/.
  RELOAD=(--reload --reload-dir ovs)
fi

# `${RELOAD[@]+...}` rather than a plain "${RELOAD[@]}": macOS ships bash 3.2,
# where expanding an empty array under `set -u` is an unbound-variable error.
exec "$PY" -m uvicorn ovs.api.main:app \
  --host "$HOST" --port "$PORT" --workers 1 ${RELOAD[@]+"${RELOAD[@]}"}
