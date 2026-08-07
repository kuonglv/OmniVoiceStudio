"""Health probe and environment report.

`/api/health` is reachable without a token (see `ovs.api.auth.PUBLIC_PATHS`) so
a pod can be checked for liveness before the token is configured — it therefore
reports only whether the box is usable, never paths or contents.
`/api/system` is gated and carries the detail.
"""

from __future__ import annotations

import shutil

from fastapi import APIRouter

from ... import db
from ...asr import whisper_available
from ...config import settings
from ...tts import is_model_loaded, unload_models
from ...voice_library import library_root, list_voices

router = APIRouter()


def _gpu() -> dict:
    """What torch can see. Absent torch is normal on a dev laptop."""
    try:
        import torch
    except ImportError:
        return {"torch": None, "cuda_available": False, "gpu_name": None}
    info = {
        "torch": torch.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu_name": None,
        "vram_total_gb": None,
    }
    if info["cuda_available"]:
        try:
            props = torch.cuda.get_device_properties(0)
            info["gpu_name"] = props.name
            info["vram_total_gb"] = round(props.total_memory / 1024**3, 1)
        except Exception:
            pass
    return info


@router.get("/health")
def health() -> dict:
    gpu = _gpu()
    try:
        omnivoice_installed = __import__("importlib.util", fromlist=["util"]).util.find_spec(
            "omnivoice"
        ) is not None
    except Exception:
        omnivoice_installed = False
    return {
        "ok": True,
        "version": __import__("ovs").__version__,
        **gpu,
        "omnivoice_installed": omnivoice_installed,
        "model_loaded": is_model_loaded(),
        # Lets the UI show a token prompt before the first 401 instead of after.
        "auth_required": bool(settings.auth_token.strip()),
    }


@router.get("/system")
def system() -> dict:
    """Paths, disk headroom and defaults. Token-gated."""
    data_dir = settings.data_dir
    try:
        usage = shutil.disk_usage(data_dir)
        disk = {
            "total_gb": round(usage.total / 1024**3, 1),
            "free_gb": round(usage.free / 1024**3, 1),
        }
    except Exception:
        disk = {}
    return {
        "data_dir": str(data_dir),
        "voices_dir": str(library_root()),
        "outputs_dir": str(settings.resolved_outputs_dir()),
        "db_path": str(db.db_path()),
        "disk": disk,
        "voices": len(list_voices()),
        "whisper_available": whisper_available(),
        "defaults": {
            "model_id": settings.model_id,
            "device": settings.device,
            "whisper_model": settings.whisper_model,
        },
    }


@router.post("/system/unload")
def unload() -> dict:
    """Drop the cached OmniVoice model and free VRAM.

    Useful before running something else on the same GPU without paying to
    restart the pod.
    """
    return {"released": unload_models()}
