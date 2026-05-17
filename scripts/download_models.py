"""Download Piper TTS model and generate fallback WAV.

Run once before starting the agent:
    uv run python scripts/download_models.py
"""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).parent.parent
MODELS_DIR = ROOT / "models"
ASSETS_DIR = ROOT / "assets"

PIPER_REPO = "rhasspy/piper-voices"
PIPER_MODEL = "en_US-lessac-medium"
PIPER_SUBFOLDER = "en/en_US/lessac/medium"


def download_piper_model() -> Path:
    """Download en_US-lessac-medium.onnx + .onnx.json from HuggingFace."""
    from huggingface_hub import hf_hub_download

    MODELS_DIR.mkdir(exist_ok=True)

    for filename in (f"{PIPER_MODEL}.onnx", f"{PIPER_MODEL}.onnx.json"):
        dest = MODELS_DIR / filename
        if dest.exists():
            print(f"  [skip] {filename} already exists")
            continue
        print(f"  [download] {filename} …", flush=True)
        path = hf_hub_download(
            repo_id=PIPER_REPO,
            filename=f"{PIPER_SUBFOLDER}/{filename}",
            local_dir=str(MODELS_DIR),
            local_dir_use_symlinks=False,
        )
        # hf_hub_download may nest inside subfolders — move to models/
        downloaded = Path(path)
        target = MODELS_DIR / filename
        if downloaded != target:
            downloaded.rename(target)
        print(f"  [ok] {target}")

    return MODELS_DIR / f"{PIPER_MODEL}.onnx"


def generate_fallback_wav(model_path: Path) -> None:
    """Synthesise a short fallback phrase and save it as assets/fallback.wav."""
    ASSETS_DIR.mkdir(exist_ok=True)
    dest = ASSETS_DIR / "fallback.wav"
    if dest.exists():
        print(f"  [skip] {dest} already exists")
        return

    print("  [generate] assets/fallback.wav …", flush=True)
    try:
        from piper import PiperVoice  # type: ignore[import]

        voice = PiperVoice.load(str(model_path))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voice.synthesize_wav(
                "I'm sorry, I encountered a problem. Please try again.",
                wf,
                set_wav_format=True,
            )
        buf.seek(0)
        dest.write_bytes(buf.read())
        print(f"  [ok] {dest}")
    except Exception as exc:
        print(f"  [warn] Could not generate fallback WAV: {exc}", file=sys.stderr)
        print("         The agent will still work; errors just won't play audio.", file=sys.stderr)


def main() -> None:
    print("\n=== Voice Agent — model setup ===\n")

    print("1. Downloading Piper TTS model (en_US-lessac-medium) …")
    model_path = download_piper_model()

    print("\n2. Generating fallback audio …")
    generate_fallback_wav(model_path)

    print("\nDone. Next step: edit .env (add your OPENAI_API_KEY) then run:")
    print("    uv run voice-agent start\n")


if __name__ == "__main__":
    main()
