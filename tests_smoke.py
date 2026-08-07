#!/usr/bin/env python3
"""End-to-end check of the generate path with a stubbed OmniVoice model.

    python tests_smoke.py

Everything except the model itself is real: the chunkability guard, reference
resolution, WAV writing, the manifest, the generations table. Runs on a laptop
with no GPU, which is the point — it catches the plumbing breaking without
renting anything.
"""

from __future__ import annotations

import json
import math
import sys
import types
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

# --- stub `omnivoice` before ovs.tts tries to import it ---------------------
_stub = types.ModuleType("omnivoice")


class FakeModel:
    sampling_rate = 24000

    @classmethod
    def from_pretrained(cls, model_id, **kw):
        print(f"  [stub] from_pretrained({model_id}, {kw})")
        return cls()

    def generate(self, text, **kw):
        print(f"  [stub] generate({len(text)} chars, {sorted(kw)})")
        assert "\n" not in text, "text should have been whitespace-normalized"
        n = int(self.sampling_rate * max(1.0, len(text) / 15.0))
        t = np.arange(n) / self.sampling_rate
        return (0.2 * np.sin(2 * math.pi * 220 * t)).astype(np.float32)


_stub.OmniVoice = FakeModel
sys.modules["omnivoice"] = _stub

from ovs import db, jobs  # noqa: E402
from ovs.config import ensure_dirs, seed_voices_if_empty, settings  # noqa: E402
from ovs.generate import run_batch  # noqa: E402
from ovs.tts import UnchunkableText, check_chunkable  # noqa: E402


class FakeManager:
    """run_batch polls this between items; nothing here is cancelled."""

    def cancel_requested(self, _job_id: str) -> bool:
        return False


def main() -> int:
    ensure_dirs()
    db.init_db()
    seeded = seed_voices_if_empty()
    print(f"data dir: {settings.data_dir} (seeded {seeded} file(s))")

    # -- the chunkability guard --------------------------------------------
    try:
        check_chunkable("word " * 200)  # 1000 chars, no punctuation
        raise AssertionError("guard did not fire on unpunctuated text")
    except UnchunkableText as exc:
        print(f"ok  guard fires: {str(exc)[:60]}…")
    check_chunkable("Hello there. " * 100)
    print("ok  guard allows punctuated text")

    # -- a real batch through the real job body ----------------------------
    jobs.manager = FakeManager()  # type: ignore[assignment]

    def emit(line="", stream="stdout", *, progress=None):
        if line:
            print("   |", line)

    job_id = db.create_job("generate", "{}")
    result = run_batch(
        emit,
        {
            "job_id": job_id,
            "items": [
                # A name with spaces and punctuation, to exercise safe_name.
                {"name": "hello world!!", "text": "Hello there.\nThis is a test.  Line two."},
                {"name": "bad", "text": "x" * 900},
            ],
            "make_srt": False,
            "synthesis": {"voice": "joker", "device": "cpu"},
            "asr": {},
        },
    )

    out = Path(result["output_dir"])
    print()
    print("result:", json.dumps({k: v for k, v in result.items() if k != "items"}))
    print("files :", sorted(p.name for p in out.iterdir()))

    assert result["ok"] == 1 and result["failed"] == 1, result
    assert (out / "hello-world.wav").is_file(), "wav missing, or the name was not sanitized"
    assert (out / "manifest.json").is_file()

    import soundfile as sf

    data, sr = sf.read(out / "hello-world.wav")
    print(f"wav   : {len(data) / sr:.1f}s @ {sr} Hz")
    assert sr == 24000 and len(data) > 0

    counts = db.voice_usage_counts()
    assert counts.get("joker") == 1, counts
    print("usage :", counts)

    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
