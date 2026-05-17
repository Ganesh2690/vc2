"""CLI entry point for the voice agent.

Subcommands:
  start      — load settings, warm-up all services, run the pipeline
  check      — validate environment (env vars, CUDA, models)
  benchmark  — run pipeline on a fixture WAV and report latencies
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import structlog

from voice_agent.logging_config import configure_logging


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-agent",
        description="Real-time voice conversation agent",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start the voice agent server")
    p_start.add_argument(
        "--config",
        default=None,
        help="Path to YAML config (default: config/dev.yaml or config/prod.yaml "
             "based on VOICE_AGENT_ENV)",
    )

    # check
    sub.add_parser("check", help="Check environment and model availability")

    # benchmark
    p_bench = sub.add_parser(
        "benchmark", help="Benchmark latencies using a fixture WAV"
    )
    p_bench.add_argument(
        "--wav",
        default="tests/fixtures/sample.wav",
        help="Path to WAV file for benchmarking",
    )

    return parser


# ─────────────────────────────────────────────────────────────── start ────

async def _run_start(config_path: str | None) -> None:
    from voice_agent.config import load_settings
    from voice_agent.transport.livekit_adapter import LiveKitServer
    from voice_agent.agent.pipeline import build_pipeline
    from pipecat.pipeline.runner import PipelineRunner

    settings = load_settings(config_path)
    configure_logging(settings.log_level)
    log = structlog.get_logger(__name__)

    session_id = uuid.uuid4().hex[:12]
    log.info("starting_voice_agent", session_id=session_id)

    # HTTP server (token endpoint + static client files)
    server = LiveKitServer(
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
        livekit_url=settings.livekit_url,
        host=settings.server.host,
        port=settings.server.port,
        static_dir="client",
    )
    await server.start()

    # Mint the agent-side token (the agent joins as a participant)
    from voice_agent.transport.livekit_adapter import _mint_token
    agent_token = _mint_token(
        settings.livekit_api_key,
        settings.livekit_api_secret,
        server.room_name,
        "agent",
    )

    task, state_machine, memory, metrics = await build_pipeline(
        settings=settings,
        token=agent_token,
        room_name=server.room_name,
        session_id=session_id,
    )

    state_machine.on_state_change(lambda prev, new: server.update_state(new.value))

    log.info(
        "open_browser",
        url=f"http://{settings.server.host}:{settings.server.port}",
    )

    runner = PipelineRunner()
    try:
        await runner.run(task)
    finally:
        metrics.session_summary()
        await server.stop()
        log.info("shutdown_complete", session_id=session_id)


# ─────────────────────────────────────────────────────────────── check ────

def _run_check() -> None:
    """Validate environment without starting the server."""
    configure_logging("INFO")
    import importlib

    errors: list[str] = []
    warnings: list[str] = []

    # Env vars
    for var in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "OPENAI_API_KEY"):
        if not os.environ.get(var):
            errors.append(f"Missing env var: {var}")

    # Python packages
    for pkg in ("pipecat", "faster_whisper", "piper", "livekit", "structlog", "tiktoken"):
        try:
            importlib.import_module(pkg)
        except ImportError:
            errors.append(f"Package not installed: {pkg}")

    # CUDA availability (optional)
    try:
        import ctranslate2
        devices = ctranslate2.get_supported_compute_types("cuda")
        if devices:
            print(f"[ok] CUDA available — compute types: {', '.join(devices)}")
        else:
            warnings.append("CUDA device found but no compatible compute types")
    except Exception:
        warnings.append("CUDA not available — will use CPU (slower STT)")

    # Piper model
    model_path = Path("models/en_US-lessac-medium.onnx")
    if model_path.exists():
        print(f"[ok] Piper model: {model_path}")
    else:
        errors.append(
            f"Piper model not found: {model_path}  "
            "— run: uv run python scripts/download_models.py"
        )

    # faster-whisper cache (warn only — downloads automatically)
    import os as _os
    hf_cache = Path(_os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    whisper_cached = any(
        hf_cache.rglob("*distil-large-v3*")
    ) if hf_cache.exists() else False
    if whisper_cached:
        print("[ok] faster-whisper distil-large-v3 model cached")
    else:
        warnings.append(
            "faster-whisper distil-large-v3 not cached — will download (~1.5 GB) on first start"
        )

    # Fallback WAV (warn only)
    fallback = Path("assets/fallback.wav")
    if fallback.exists():
        print(f"[ok] Fallback WAV: {fallback}")
    else:
        warnings.append(
            "Fallback WAV missing — run: uv run python scripts/download_models.py"
        )

    # LiveKit binary
    lk_bin = Path("bin/livekit-server.exe")
    lk_available = lk_bin.exists() or bool(
        # also accept if livekit-server is on PATH
        __import__("shutil").which("livekit-server")
    )
    if lk_available:
        print(f"[ok] LiveKit server binary: {lk_bin if lk_bin.exists() else 'on PATH'}")
    else:
        errors.append(
            "LiveKit server binary not found — run: uv run python scripts/download_models.py"
        )

    # OpenAI API key sanity check
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key and not openai_key.startswith("sk-..."):
        print("[ok] OPENAI_API_KEY is set")
    elif openai_key == "sk-...":
        errors.append("OPENAI_API_KEY is still the placeholder value — edit .env")

    # Summary
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[error] {e}")

    if errors:
        print(f"\n{len(errors)} error(s) found. Fix them before starting.")
        sys.exit(1)
    else:
        print("\nAll checks passed.")


# ──────────────────────────────────────────────────────────── benchmark ────

async def _run_benchmark(wav_path: str) -> None:
    from voice_agent.config import load_settings
    configure_logging("WARNING")
    from pathlib import Path as _Path
    import wave, array, time as _time

    wav = _Path(wav_path)
    if not wav.exists():
        print(f"WAV not found: {wav}")
        sys.exit(1)

    settings = load_settings()
    from voice_agent.stt.faster_whisper_adapter import FasterWhisperSTTService

    stt = FasterWhisperSTTService(
        stt_config=settings.stt,
        smart_turn_config=settings.smart_turn,
    )
    await stt.initialize()

    with wave.open(str(wav), "rb") as wf:
        raw = wf.readframes(wf.getnframes())

    t0 = _time.monotonic()
    result = await stt._transcribe_bytes(raw)
    elapsed = (_time.monotonic() - t0) * 1000

    print(json.dumps({"stt_latency_ms": round(elapsed, 1), "transcript": result}, indent=2))
    await stt.cleanup()


# ─────────────────────────────────────────────────────────────── main ────

def main() -> None:
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = _make_parser()
    args = parser.parse_args()

    if args.command == "start":
        asyncio.run(_run_start(getattr(args, "config", None)))
    elif args.command == "check":
        _run_check()
    elif args.command == "benchmark":
        asyncio.run(_run_benchmark(args.wav))
