"""Runtime settings.

Everything the app writes lives under one root (`OVS_DATA_DIR`) so a RunPod
network volume mounted at `/workspace` survives the container being recycled —
pods are ephemeral, the volume is not. On a dev laptop the default falls back to
`./data` inside the repo.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

# `/workspace` is where RunPod mounts a network volume. Outside a pod that path
# does not exist and is not writable, so fall back to a repo-local dir.
_DEFAULT_DATA_DIR = Path("/workspace") if Path("/workspace").is_dir() else REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OVS_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = _DEFAULT_DATA_DIR
    # Overridable individually so a machine can keep, say, the voice library
    # somewhere other than the data root.
    voices_dir: Path | None = None
    outputs_dir: Path | None = None
    db_path: Path | None = None

    # --- OmniVoice defaults (per-request values override these) -------------
    model_id: str = "k2-fsa/OmniVoice"
    device: str = "cuda:0"
    # Whisper CLI model size for the optional SRT pass.
    whisper_model: str = "small"

    # --- Access control -----------------------------------------------------
    # A RunPod pod is reachable at a guessable https://<podid>-8000.proxy.runpod.net
    # with no authentication of its own, so the API refuses to serve anything
    # without this token. Blank = open, which is only safe on localhost.
    auth_token: str = ""

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    def resolved_voices_dir(self) -> Path:
        return self.voices_dir or (self.data_dir / "voices")

    def resolved_outputs_dir(self) -> Path:
        return self.outputs_dir or (self.data_dir / "outputs")

    def resolved_db_path(self) -> Path:
        return self.db_path or (self.data_dir / "ovs.db")


settings = Settings()


def ensure_dirs() -> None:
    """Create the data tree. Called at import of `ovs.db` and by the entrypoint."""
    for p in (
        settings.data_dir,
        settings.resolved_voices_dir(),
        settings.resolved_outputs_dir(),
    ):
        p.mkdir(parents=True, exist_ok=True)


def seed_voices_if_empty() -> int:
    """Copy `voices_seed/` into the library when the library has no voices.

    The seed clips are committed to git; the live library lives on the volume.
    A fresh volume would otherwise start with an empty voice dropdown. Returns
    the number of files copied.
    """
    import shutil

    seed = REPO_ROOT / "voices_seed"
    dest = settings.resolved_voices_dir()
    dest.mkdir(parents=True, exist_ok=True)
    if not seed.is_dir() or any(dest.glob("*.json")):
        return 0
    n = 0
    for src in sorted(seed.iterdir()):
        if src.is_file():
            shutil.copy2(src, dest / src.name)
            n += 1
    return n


def hf_cache_hint() -> None:
    """Point HuggingFace + Whisper caches at the volume if nothing set them.

    The OmniVoice weights are multi-GB; without this they re-download from
    HuggingFace on every pod start, which is the single slowest part of a cold
    boot.
    """
    if not os.environ.get("HF_HOME"):
        os.environ["HF_HOME"] = str(settings.data_dir / "hf-cache")
    if not os.environ.get("XDG_CACHE_HOME"):
        os.environ["XDG_CACHE_HOME"] = str(settings.data_dir / "cache")
