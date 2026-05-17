# Voice Agent

Real-time voice conversation agent built on **Pipecat**, **LiveKit**, **faster-whisper**, **Piper TTS**, and **OpenAI GPT-4.1-nano**. Runs on Windows (CPU or CUDA GPU). No Docker required.

---

## Architecture

```
Browser (LiveKit JS SDK)
    ↕ WebRTC audio + data channel
LiveKit Cloud Room
    ↕
┌─────────────────────────────────────────────────────────┐
│  Pipeline (Pipecat)                                      │
│                                                          │
│  LiveKitTransport.input()  ← Silero VAD v5               │
│  → BargeInController       ← 3-frame barge-in confirm    │
│  → ConversationController  ← state machine + UI events  │
│  → MetricsCollector        ← 7 latency metrics          │
│  → FasterWhisperSTTService ← distil-large-v3 + SmartTurn│
│  → OpenAILLMContext.user() ← sliding-window memory      │
│  → OpenAILLMService        ← gpt-4.1-nano streaming     │
│  → TextChunker             ← sentence-boundary phrases  │
│  → PiperTTSService         ← en_US-lessac-medium        │
│  → LiveKitTransport.output()                             │
│  → OpenAILLMContext.assistant()                          │
└─────────────────────────────────────────────────────────┘
    ↕ HTTP (aiohttp)
GET /token   — mint LiveKit JWT for browser
GET /health  — liveness probe
GET /        — serve client/index.html
```

**State machine** (11 states): INITIALIZING → READY → LISTENING → USER_SPEAKING → THINKING_PAUSE → PROCESSING → SPEAKING → (INTERRUPT_CANDIDATE → INTERRUPTED) → LISTENING, with DEGRADED and SHUTDOWN escape states.

---

## Quick Start

### 1. Prerequisites

- Python 3.11
- [uv](https://github.com/astral-sh/uv) — `pip install uv`
- A [LiveKit Cloud](https://cloud.livekit.io) account (free tier works)
- An [OpenAI API key](https://platform.openai.com)

### 2. Clone & install

```bash
git clone <repo-url>
cd "conversation agent"
uv sync
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — fill in LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
```

### 4. Download Piper model

```bash
# Create models/ directory and download
mkdir -p models
# Download from HuggingFace:
# https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium
# Files needed: en_US-lessac-medium.onnx  and  en_US-lessac-medium.onnx.json
# Place both in models/
```

### 5. Generate fallback WAV (optional but recommended)

```bash
mkdir -p assets
uv run python -c "
from piper import PiperVoice
import wave, io
voice = PiperVoice.load('models/en_US-lessac-medium.onnx')
buf = io.BytesIO()
with wave.open(buf, 'wb') as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
    for chunk in voice.synthesize_stream_raw('I am sorry, I encountered an error.'):
        wf.writeframes(chunk)
buf.seek(0)
open('assets/fallback.wav', 'wb').write(buf.read())
print('fallback.wav created')
"
```

### 6. Check setup

```bash
uv run voice-agent check
```

### 7. Start

```bash
uv run voice-agent start
# Open http://localhost:7860 in your browser
```

---

## Configuration

Two built-in YAML configs in `config/`:

| File | Use |
|------|-----|
| `config/dev.yaml` | Development — `localhost:7860`, `DEBUG` logs |
| `config/prod.yaml` | Production — `0.0.0.0:7860`, `INFO` logs |

Activate via `VOICE_AGENT_ENV=prod` or `--config path/to/config.yaml`.

All settings can be overridden with environment variables using `__` as delimiter, e.g. `LLM__MAX_TOKENS=150`.

---

## CLI Reference

```
voice-agent start [--config FILE]   Start the voice agent server
voice-agent check                   Validate environment and models
voice-agent benchmark [--wav FILE]  Benchmark STT latency on a WAV file
```

---

## Running Tests

```bash
# Unit tests only (no API keys needed)
uv run pytest tests/ -m "not integration" -v

# All tests including integration (needs OPENAI_API_KEY)
uv run pytest tests/ -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/ --ignore-missing-imports
```

---

## Metrics

All 7 latency metrics per turn (logged as structured JSON + emitted to browser):

| Metric | Description |
|--------|-------------|
| `stt_latency_ms` | VAD end → TranscriptionFrame |
| `llm_ttft_ms` | LLM dispatch → first token |
| `llm_total_ms` | LLM dispatch → LLMFullResponseEndFrame |
| `tts_first_audio_ms` | TextFrame received → first AudioRawFrame out |
| `e2e_latency_ms` | VAD end → first audio out |
| `bargein_detection_ms` | First VAD positive → InterruptFrame |
| `chunk_count` | TTS chunks per turn |

Session p50/p95 aggregates logged on shutdown.

---

## Troubleshooting

**`ImportError: No module named 'piper'`**
```bash
uv sync  # reinstall all deps
```

**CUDA not detected**
```bash
# Check ctranslate2 CUDA support:
python -c "import ctranslate2; print(ctranslate2.get_supported_compute_types('cuda'))"
# If empty, install CUDA-enabled ctranslate2:
uv pip install ctranslate2 --extra-index-url https://pypi.org/simple
```

**LiveKit connection error**
- Verify `LIVEKIT_URL` starts with `wss://` (not `ws://` for cloud)
- Check API key and secret in LiveKit Cloud dashboard

**Piper model not found**
- Ensure both `.onnx` and `.onnx.json` files are in `models/`
- Run `voice-agent check` to verify

**High STT latency on CPU**
- Expected: 500ms–2s on CPU. Use CUDA GPU for <200ms.
- Set `STT__COMPUTE_TYPE=int8` to minimise CPU inference cost.

---

## Project Structure

```
src/voice_agent/
├── __init__.py           version
├── __main__.py           python -m voice_agent
├── cli.py                argparse entry point
├── config.py             pydantic settings + YAML loader
├── frames.py             custom Pipecat frames
├── logging_config.py     structlog JSON setup
├── protocols.py          typing.Protocol adapters
├── agent/
│   ├── barge_in.py       barge-in controller
│   ├── pipeline.py       pipeline wiring
│   └── state_machine.py  11-state FSM
├── audio/
│   └── preprocessing.py  resampling + ring buffer
├── llm/
│   └── chunker.py        text chunker + markdown stripper
├── memory/
│   └── session_memory.py sliding-window context memory
├── metrics/
│   └── collector.py      7-metric latency collector
├── stt/
│   └── faster_whisper_adapter.py  STT + Smart Turn
├── transport/
│   └── livekit_adapter.py         HTTP server + token mint
└── tts/
    └── piper_adapter.py           Piper TTS service
client/
├── index.html            React CDN + LiveKit JS SDK
└── app.js                React UI components
config/
├── dev.yaml
└── prod.yaml
tests/
├── conftest.py
├── unit/
│   ├── test_state_machine.py
│   ├── test_chunker.py
│   ├── test_barge_in.py
│   └── test_memory.py
├── integration/
│   └── test_llm_adapter.py
└── fixtures/
```
