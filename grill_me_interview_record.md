# GRILL-ME Interview Record — Windows Voice Conversation Agent

> **Purpose:** Full verbatim record of the pre-implementation GRILL-ME interview session.
> Each entry shows the question as posed, all options presented with their table, the selected answer, and the rationale.
>
> **Date:** May 15, 2026
> **Status:** ✅ All 20 branches resolved — Ready for implementation

---

## Table of Contents

| Branch | Topic | Decisions |
|--------|-------|-----------|
| [1](#branch-1--environment-and-runtime) | Environment and Runtime | 6 |
| [2](#branch-2--project-structure-and-build) | Project Structure and Build | 5 |
| [3](#branch-3--transport-layer--livekit) | Transport Layer — LiveKit | 6 |
| [4](#branch-4--orchestration-layer--pipecat) | Orchestration Layer — Pipecat | 5 |
| [5](#branch-5--audio-preprocessing) | Audio Preprocessing | 6 |
| [6](#branch-6--vad--silero) | VAD — Silero | 5 |
| [7](#branch-7--turn-detection--smart-turn) | Turn Detection — Smart Turn | 5 |
| [8](#branch-8--stt--faster-whisper) | STT — faster-whisper | 7 |
| [9](#branch-9--llm--openai-nano) | LLM — OpenAI Nano | 8 |
| [10](#branch-10--tts--piper) | TTS — Piper | 6 |
| [11](#branch-11--text-chunking-llm--tts-bridge) | Text Chunking | 5 |
| [12](#branch-12--barge-in-controller) | Barge-In Controller | 6 |
| [13](#branch-13--conversation-state-machine) | Conversation State Machine | 6 |
| [14](#branch-14--conversation-memory) | Conversation Memory | 5 |
| [15](#branch-15--ui-and-client) | UI and Client | 5 |
| [16](#branch-16--observability-and-metrics) | Observability and Metrics | 6 |
| [17](#branch-17--testing-strategy) | Testing Strategy | 6 |
| [18](#branch-18--error-handling-and-fallbacks) | Error Handling and Fallbacks | 5 |
| [19](#branch-19--openai-realtime-optional) | OpenAI Realtime (Optional) | 1 |
| [20](#branch-20--deployment-and-packaging) | Deployment and Packaging | 4 |

---

## Branch 1 — Environment and Runtime

### Q1.1 — Which Python version to target?

> Widest pre-built wheel coverage on Windows for faster-whisper (ctranslate2), Pipecat, LiveKit SDK, Silero VAD, and Piper matters. Python 3.12 and 3.13 have fewer pre-built wheels for ctranslate2 as of this date.

| Option | Wheel coverage | Notes |
|--------|---------------|-------|
| **Python 3.11** | Best | ✅ Recommended |
| Python 3.12 | Good | ctranslate2 wheels may lag |
| Python 3.13 | Limited | Too new; critical wheels missing |

**Selected:** Python 3.11
**Rationale:** Widest pre-built wheel coverage on Windows for the full stack. No known compatibility blockers.

---

### Q1.2 — Which tool manages the virtual environment and packages?

> Package manager selection affects install speed, reproducibility, and cross-platform compatibility for a stack with heavy native packages.

| Option | Install speed | Lockfile | Notes |
|--------|--------------|---------|-------|
| **uv** | 10–100× pip | `uv.lock` | ✅ Recommended |
| poetry | Moderate | `poetry.lock` | Good but slower installs |
| venv + pip + pip-tools | Baseline | `requirements.txt` | Standard but manual |
| conda | Variable | `environment.yml` | Heavier; mixed ecosystem |

**Selected:** uv
**Rationale:** Fastest installs for heavy native packages (ctranslate2, torch, onnxruntime). Single-line bootstrap in `setup.ps1`. Produces `uv.lock` for reproducible environments.

---

### Q1.3 — How should microphone capture and speaker playback be handled on Windows?

> The v1 client type affects which audio API is appropriate.

| Option | Complexity | v1 fit | Notes |
|--------|-----------|--------|-------|
| **LiveKit/WebRTC (browser handles it)** | Zero | ✅ | ✅ Recommended |
| WASAPI via sounddevice | Medium | Native client needed | Good for v2 desktop client |
| pyaudio/PortAudio | Medium | Native client needed | Cross-platform but verbose |
| DirectSound | High | Native client needed | Legacy |

**Selected:** LiveKit/WebRTC — browser handles client audio for v1
**Rationale:** Browser captures mic and handles speaker via WebRTC natively. LiveKit delivers audio frames to the Python agent. No Python-level Windows audio API needed for v1. `sounddevice` + WASAPI documented as future fallback.

---

### Q1.4 — Is CUDA required, and is a CPU-only fallback mandatory?

> Hardware diversity of the target user base requires a decision on GPU dependency.

| Option | Accessibility | Performance | Notes |
|--------|--------------|-------------|-------|
| **CUDA 12.x + CPU fallback** | Wide | Best on GPU, functional on CPU | ✅ Recommended |
| GPU-required (no fallback) | Narrow | Best | Excludes CPU-only users |
| CPU-only | Wide | Slower | No GPU benefit |

**Selected:** CUDA 12.x with automatic CPU-only fallback
**Rationale:** Auto-detect via `ctranslate2.get_cuda_device_count()` at startup. Single `device` parameter difference — minimal maintenance burden.

---

### Q1.5 — Which Windows versions are supported?

| Option | Notes |
|--------|-------|
| **Windows 10 (21H2+) + Windows 11** | ✅ Recommended — broadest practical install base |
| Windows 11 only | Narrows user base unnecessarily |
| Windows 10 only | Misses current default OS |

**Selected:** Windows 10 (21H2+) and Windows 11
**Rationale:** All required components (WASAPI, WebRTC, Python 3.11, ctranslate2, onnxruntime) function correctly on both. README includes note to add folder to Windows Defender exclusions.

---

### Q1.6 — What is the minimum hardware specification?

> Sets the testing floor and documents what the agent is built to run on.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | Intel i5 / AMD Ryzen 5 (8th gen+), 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| GPU | None required (CPU fallback) | NVIDIA GPU 4 GB VRAM (CUDA 12.x) |
| Storage | 5 GB free | 10 GB SSD |
| Network | Broadband | Low-latency broadband |

**Selected:** Accepted as specified above
**Rationale:** CPU-only int8 on minimum spec yields ~1–2s STT latency — functional. Documented in README.

---

## Branch 2 — Project Structure and Build

### Q2.1 — Should the agent service and client live in one repo or separate repos?

| Option | Notes |
|--------|-------|
| **Monorepo** | ✅ Recommended — single `uv` lockfile, one CI pipeline, no cross-repo version friction |
| Polyrepo | Adds cross-repo pinning friction with minimal benefit at this scale |

**Selected:** Monorepo
**Rationale:** Single `uv` lockfile and CI pipeline. v1 client is minimal HTML/JS with no npm build step — zero downside to co-location.

---

### Q2.2 — How should Python source code be organised on disk?

| Option | Notes |
|--------|-------|
| **`src/` layout** | ✅ Recommended — PyPA best practice |
| Flat layout | Risks accidental imports of uninstalled packages |
| Design doc flat structure | Non-standard; less tooling support |

**Selected:** `src/` layout
**Rationale:** Prevents accidental imports of uninstalled packages. Works cleanly with `uv` + `pyproject.toml`. Module boundaries nested inside `src/voice_agent/`: `agent/`, `audio/`, `stt/`, `llm/`, `tts/`, `transport/`, `memory/`, `metrics/`.

---

### Q2.3 — Single `main.py` or a CLI with subcommands?

| Option | Notes |
|--------|-------|
| **CLI with subcommands via `argparse`** | ✅ Recommended — `start`, `benchmark`, `check` |
| Single `main.py` | No subcommand structure; less useful for benchmarking and validation |

**Selected:** CLI with subcommands via `argparse`
**Rationale:** Zero extra dependency (stdlib `argparse`). Subcommands map naturally to distinct execution modes. Convenience `main.py` at repo root delegates to `python -m voice_agent start`.

---

### Q2.4 — What format for config, and how are secrets handled?

| Option | Notes |
|--------|-------|
| **YAML split dev/prod + dotenv + pydantic** | ✅ Recommended |
| YAML single file | dev/prod values mixed; risk of leaking dev config to prod |
| TOML | Less readable for deeply nested config |
| `.env` only | No structured config; no validation |

**Selected:** YAML split into `config/dev.yaml` + `config/prod.yaml`; secrets via dotenv (dev) / env vars (prod); validated with pydantic `BaseSettings`
**Rationale:** Readable, validated, split by environment. API keys never in YAML. Misconfiguration fails fast with clear error.

---

### Q2.5 — How are `.env` files and API keys protected from accidental exposure?

| Option | Notes |
|--------|-------|
| **`.env` in `.gitignore` + `.env.example` committed** | ✅ Recommended — zero-cost, industry standard |
| Vault | Overkill for v1 |
| Cloud secrets manager | Overkill for v1 |

**Selected:** `.env` in `.gitignore`; `.env.example` committed with placeholder values
**Rationale:** Documents all required keys (`OPENAI_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`). Pydantic raises clear `ValidationError` on startup if any required key is missing.

---

## Branch 3 — Transport Layer — LiveKit

### Q3.1 — Self-hosted LiveKit server or LiveKit Cloud?

| Option | Ops burden | Cost | Notes |
|--------|-----------|------|-------|
| **LiveKit Cloud** | Zero | Free tier covers dev | ✅ Recommended |
| Self-hosted | High | Infra cost | One-line config change to switch post-v1 |

**Selected:** LiveKit Cloud for v1
**Rationale:** Zero ops burden; TLS/TURN handled automatically. Switch to self-hosted is a one-line config change.

---

### Q3.2 — One room per conversation or room pooling?

| Option | Complexity | Notes |
|--------|-----------|-------|
| **One room per conversation** | Low | ✅ Recommended |
| Room pooling | High | Adds state-reset complexity; no meaningful v1 benefit |

**Selected:** One room per conversation (UUID name)
**Rationale:** Simple lifecycle — room created at session start, destroyed at end. ~100–200ms creation overhead negligible.

---

### Q3.3 — Which audio codec and sample rate over the WebRTC transport?

| Option | Config needed | Notes |
|--------|--------------|-------|
| **Opus at 48kHz** | None — LiveKit/WebRTC default | ✅ Recommended |
| Opus 16kHz | Custom config | Would require non-standard setup |
| PCM passthrough | High bandwidth | Not WebRTC-native |

**Selected:** Opus at 48kHz
**Rationale:** LiveKit and WebRTC default — no configuration required. Python agent resamples 48kHz → 16kHz at transport boundary.

---

### Q3.4 — Which SDK does the browser client use to connect to LiveKit?

| Option | Build step | Notes |
|--------|-----------|-------|
| **LiveKit JS SDK via CDN** | None | ✅ Recommended |
| LiveKit Python SDK (desktop) | Native app needed | v2 consideration |
| Both | Two codepaths | Unnecessary for v1 |

**Selected:** LiveKit JS SDK in the browser, loaded via CDN
**Rationale:** No npm/webpack build step. Browser handles mic/speaker via WebRTC. Single HTML file client with no toolchain.

---

### Q3.5 — Who creates the LiveKit room and how does the browser get a token?

| Option | Security | Notes |
|--------|---------|-------|
| **Agent creates room + issues token via `GET /token`** | ✅ Secure | ✅ Recommended |
| Client creates room | ❌ Exposes API secret | Rejected — security violation |
| Pre-created rooms | Manual setup | No automation |

**Selected:** Agent creates room and issues token via `GET /token` HTTP endpoint
**Rationale:** `LIVEKIT_API_SECRET` never exposed to browser. Agent mints short-lived participant JWT (TTL: 1 hour) server-side. Endpoint served by aiohttp/fastapi co-located with agent process.

---

### Q3.6 — What happens when the LiveKit connection drops?

| Option | Retries | Notes |
|--------|--------|-------|
| **Exponential backoff max 5 retries then give up** | 5 | ✅ Recommended |
| Infinite retry | ∞ | Could loop forever on permanent disconnect |
| Fail immediately | 0 | WiFi blip kills session permanently |
| Session resume | N/A | State cannot be restored post-reconnect |

**Selected:** Exponential backoff with jitter, max 5 retries (1s → 2s → 4s → 8s → 16s), then DEGRADED
**Rationale:** Covers transient network interruptions. No mid-conversation session resume — conversation memory is in-memory.

---

## Branch 4 — Orchestration Layer — Pipecat

### Q4.1 — Which Pipecat transport?

| Option | Notes |
|--------|-------|
| **Pipecat `LiveKitTransport`** | ✅ Recommended — purpose-built for this stack |
| Raw WebSocket | Custom glue code required |
| Daily transport | Wrong provider |

**Selected:** Pipecat `LiveKitTransport`
**Rationale:** Native integration. Handles LiveKit ↔ Pipecat frame translation, audio callbacks, participant events, and data channel publishing out of the box.

---

### Q4.2 — Linear chain or branching DAG pipeline topology?

| Option | Complexity | Notes |
|--------|-----------|-------|
| **Linear chain** | Low | ✅ Recommended — all v1 functionality fits |
| Branching DAG | High | Barge-in handled as side effect within VAD stage |

**Selected:** Linear chain
**Rationale:** Barge-in branching handled as interrupt event to state machine — main pipeline frame flow stays linear, simple to debug and test.

---

### Q4.3 — Built-in frames only, or extend with custom frames?

| Custom frame | Purpose |
|-------------|---------|
| `MetricFrame` | Latency timestamps per stage |
| `StateChangeFrame` | State machine transitions |
| `InterruptFrame` | Barge-in signal |
| `TurnCompleteFrame` | Smart Turn end-of-turn |
| `TurnIncompleteFrame` | Smart Turn continue-listening |

| Option | Notes |
|--------|-------|
| **Extend with custom frames** | ✅ Recommended |
| Built-in only | Metrics and state events lose pipeline visibility |

**Selected:** Extend with 5 custom frames (listed above)
**Rationale:** Lightweight Python dataclasses, zero performance cost. Keeps metrics and state events first-class in pipeline — easy to log, trace, and unit test.

---

### Q4.4 — Per-stage try/catch, pipeline-level handler, or circuit breaker?

| Option | Notes |
|--------|-------|
| **Pipeline-level handler + per-stage fallback hooks** | ✅ Recommended |
| Per-stage try/catch only | Risk of silent error swallowing |
| Circuit breaker | Overkill for v1 |

**Selected:** Pipeline-level error handler with per-stage fallback hooks
**Rationale:** Each stage registers an `on_error` hook emitting a defined fallback frame. Top-level handler catches anything that escapes a stage and transitions to `DEGRADED`.

---

### Q4.5 — How is Pipecat's interruption handling wired with the barge-in controller?

| Option | Notes |
|--------|-------|
| **Pipecat built-in + custom `BargeInController`** | ✅ Recommended |
| Fully custom (bypass Pipecat) | Duplicates pipeline mechanics |
| Pipecat default only | No confirmation window; too sensitive |

**Selected:** Pipecat built-in interruption events + custom `BargeInController`
**Rationale:** Custom controller sits between VAD stage and Pipecat's interruption signal, applying 3-frame/150ms confirmation window before firing `BotInterruptionFrame`.

---

## Branch 5 — Audio Preprocessing

### Q5.1 — Which AEC approach?

| Option | Location | Integration cost | Notes |
|--------|---------|-----------------|-------|
| **LiveKit/WebRTC built-in AEC (browser-side)** | Browser | Zero | ✅ Recommended |
| SpeexDSP | Python-side | Medium | Requires native audio client |
| Windows OS-level AEC (WASAPI loopback) | OS | High | Requires native audio client |

**Selected:** LiveKit/WebRTC built-in AEC (browser-side)
**Rationale:** Agent voice suppressed from mic feed automatically before reaching LiveKit. Zero integration work.

---

### Q5.2 — Which noise suppression approach?

| Option | Location | Notes |
|--------|---------|-------|
| **LiveKit's built-in NS (browser-side)** | Browser | ✅ Recommended |
| RNNoise (Python-side) | Python | Deferred to v2 |
| Speex NS (Python-side) | Python | Requires native audio client |

**Selected:** LiveKit's built-in NS (browser-side)
**Rationale:** Already running alongside AEC in browser. Handles common noise (background hum, keyboard, fan) with zero latency or dependencies.

---

### Q5.3 — Enable or disable AGC?

| Option | Notes |
|--------|-------|
| **Disable AGC** | ✅ Recommended — more predictable |
| Conservative fixed-gain | Manual tuning required |
| Adaptive AGC | Can cause volume pumping artifacts that confuse Silero VAD |
| Browser default (enabled) | AGC on by default; interferes with VAD |

**Selected:** Disable AGC for v1
**Rationale:** WebRTC AEC/NS already normalises signal. Browser `getUserMedia` called with `{ autoGainControl: false }`.

---

### Q5.4 — What frame size for Silero VAD?

| Frame size | CPU overhead | Detection lag | Notes |
|-----------|-------------|--------------|-------|
| 10ms | High (100 inf/sec) | Lowest | Overkill |
| 20ms | Medium | Low | Fine |
| **30ms** | Low (33 inf/sec) | 30ms | ✅ Recommended — Silero's recommended size |

**Selected:** 30ms frames
**Rationale:** Silero's recommended frame size. Lowest CPU overhead — important for minimum-spec CPU-only hardware.

---

### Q5.5 — Where does 48kHz → 16kHz resampling happen, and with which library?

| Option | Notes |
|--------|-------|
| **At transport boundary via `scipy.signal.resample_poly`** | ✅ Recommended — single resampling point |
| In VAD stage | Downstream stages inconsistently sampled |
| In STT stage | VAD receives 48kHz — trained on 16kHz; accuracy degrades |

**Selected:** At the `LiveKitTransport` adapter boundary using `scipy.signal.resample_poly`
**Rationale:** All downstream stages (Silero VAD, faster-whisper) receive consistent 16kHz PCM. `scipy` already in dependency tree.

---

### Q5.6 — How many seconds of pre-speech audio to retain in the ring buffer?

| Size | Memory cost | Notes |
|------|------------|-------|
| 0.3s | ~19 KB | May miss fast utterance starts |
| **0.5s** | ~32 KB | ✅ Recommended |
| 1.0s | ~64 KB | More than needed |
| 2.0s | ~128 KB | Excessive preamble noise to STT |

**Selected:** 0.5s pre-speech ring buffer
**Rationale:** Captures leading phonemes reliably. Negligible memory cost. Matches design doc recommendation.

---

## Branch 6 — VAD — Silero

### Q6.1 — Which Silero VAD version and runtime?

| Option | Notes |
|--------|-------|
| **Silero VAD v5 via ONNX Runtime** | ✅ Recommended — latest, improved false-positive suppression |
| Silero VAD v4 (ONNX) | Older; slightly worse accuracy |
| Original torch version | Requires separate PyTorch install |

**Selected:** Silero VAD v5 via ONNX Runtime
**Rationale:** Runs via `onnxruntime` — already in dependency tree. Compatible with 30ms frame size.

---

### Q6.2 — What speech detection threshold probability?

| Threshold | Sensitivity | Notes |
|-----------|------------|-------|
| 0.3 | Very sensitive | High false-positive rate |
| **0.5** | Balanced (default) | ✅ Recommended |
| 0.7 | Conservative | May miss soft speech |
| 0.9 | Very conservative | Misses most natural speech |

**Selected:** 0.5 (Silero's default)
**Rationale:** Balanced with pre-cleaned signal from WebRTC NS. Exposed as YAML config.

---

### Q6.3 — Minimum silence duration before firing a speech_pause event?

| Duration | Behaviour | Notes |
|----------|-----------|-------|
| 100ms | Very aggressive | Too many false pauses |
| 200ms | Aggressive | Fine but Smart Turn is the real gate |
| **300ms** | Balanced | ✅ Recommended |
| 500ms | Permissive | Delays turn detection noticeably |
| 800ms+ | Very permissive | Feels unresponsive |

**Selected:** 300ms
**Rationale:** Smart Turn is the real end-of-turn gate; a false pause at 300ms just triggers an evaluation that returns "incomplete". Exposed as YAML config.

---

### Q6.4 — Minimum consecutive speech duration before firing speech_start?

| Duration | Frames (at 30ms) | Notes |
|----------|-----------------|-------|
| 0ms | 0 | Every transient fires |
| 50ms | ~2 | Still catches some transients |
| **100ms** | ~3–4 | ✅ Recommended |
| 200ms | ~7 | May miss single-word utterances |
| 300ms | ~10 | Misses "Yes", "No", "Stop" |

**Selected:** 100ms (~3–4 consecutive 30ms frames)
**Rationale:** Filters virtually all non-speech transients while catching single-word utterances cleanly. Exposed as YAML config.

---

### Q6.5 — Same VAD instance or separate instance for barge-in detection during SPEAKING?

| Option | Notes |
|--------|-------|
| **Single instance (always running)** | ✅ Recommended |
| Separate instance for barge-in | Dual-instance coordination complexity |

**Selected:** Single VAD instance, always running
**Rationale:** Silero v5/ONNX is lightweight (~5 MB, <1ms per 30ms frame). State machine determines what to do with VAD output based on current state.

---

## Branch 7 — Turn Detection — Smart Turn

### Q7.1 — Pipecat built-in Smart Turn or standalone custom implementation?

| Option | Notes |
|--------|-------|
| **Pipecat built-in `SmartTurnAnalyzer`** | ✅ Recommended — native integration |
| Standalone custom classifier | Requires training data; maintenance burden |
| Silence-only turn detection | Too brittle for natural conversation |

**Selected:** Pipecat's built-in Smart Turn
**Rationale:** Native integration — directly consumes pause events and partial transcripts. Maintained by Pipecat team.

---

### Q7.2 — What input does Smart Turn receive?

| Option | Signal richness | Notes |
|--------|----------------|-------|
| Last N seconds audio only | Medium | Misses semantic completeness |
| Partial transcript only | Medium | Misses acoustic prosody |
| **Both audio + transcript** | Highest | ✅ Recommended |
| Nothing (timer only) | None | Equivalent to silence-only detection |

**Selected:** Both: last audio window (3s, configurable) + partial transcript
**Rationale:** Richest signal — acoustic prosody combined with semantic completeness detection. Intended Pipecat Smart Turn usage pattern.

---

### Q7.3 — Smart Turn hard timeout before forcing a transition?

> **Note: This is an override of the design doc's recommendation.**

| Timeout | Effect | Notes |
|---------|--------|-------|
| 1–2s | Too aggressive | Cuts off natural thinking pauses |
| **3s** | Balanced | ✅ Recommended (overrides design doc's 5s) |
| 5s | Design doc value | 300ms VAD pause + 5s = 5.3s of silence — breaks conversational feel |
| 10s | Too long | Feels broken |

**Selected:** 3s hard timeout, then force transition to PROCESSING
**Rationale:** 5s (design doc) was challenged and overridden — 5.3s total silence breaks conversational feel. 3s is generous for CPU-only Smart Turn inference while keeping conversation natural. On timeout, treat as "complete" and proceed.

---

### Q7.4 — When uncertain, err toward "complete" or "incomplete"?

| Option | Effect | Notes |
|--------|--------|-------|
| Err toward "incomplete" | Agent waits a bit longer | ✅ Recommended — being cut off is worse |
| Err toward "complete" | Agent responds faster | Risk of interrupting mid-thought |

**Selected:** Err toward "incomplete"
**Rationale:** Being cut off mid-sentence is significantly more annoying than a brief extra wait. Conservative default for v1.

---

### Q7.5 — Does Smart Turn directly drive state transitions, or emit events?

| Option | Coupling | Notes |
|--------|---------|-------|
| **Event-driven: emit `TurnCompleteFrame` / `TurnIncompleteFrame`** | Loose | ✅ Recommended |
| Directly call state machine methods | Tight | Hard to test; brittle |

**Selected:** Event-driven — Smart Turn emits `TurnCompleteFrame` / `TurnIncompleteFrame` into the pipeline
**Rationale:** Clean separation of concerns. Uses custom frame types from Decision 4.3. Easily testable by injecting frames in unit tests.

---

## Branch 8 — STT — faster-whisper / Distil-Whisper

### Q8.1 — Which model variant?

| Model | Accuracy vs large-v3 | Speed vs large-v3 | VRAM (GPU) | Notes |
|-------|---------------------|------------------|-----------|-------|
| tiny/base | ~85% | 20× | <1 GB | Too low accuracy |
| small | ~92% | 10× | ~1 GB | Acceptable fallback |
| **distil-large-v3** | ~98% | 6× | ~3 GB | ✅ Recommended |
| large-v3 | 100% | 1× | ~6 GB | Overkill; too slow |

**Selected:** `distil-large-v3`
**Rationale:** Best production accuracy/speed trade-off. Model variant exposed as YAML config for easy fallback to `small`.

---

### Q8.2 — Float16, int8, or int8_float16?

| Compute type | Device | Notes |
|-------------|--------|-------|
| float32 | Any | Slowest |
| float16 | GPU | Good |
| **int8_float16** | GPU | ✅ Best GPU throughput |
| **int8** | CPU | ✅ Only practical CPU choice |

**Selected:** Auto-selected at startup: `int8_float16` on GPU, `int8` on CPU
**Rationale:** Reuses CUDA detection logic from Decision 1.4. Both overridable via YAML config.

---

### Q8.3 — Beam size 1 (greedy) or 5?

| Beam | Speed | Accuracy gain | Notes |
|------|-------|--------------|-------|
| **1 (greedy)** | Fastest | Baseline | ✅ Recommended for real-time |
| 5 | 3–5× slower | Negligible for conversational English | Too slow for 500ms inference cadence |

**Selected:** Beam size 1 (greedy decoding)
**Rationale:** Only practical choice for real-time streaming. Exposed as YAML config.

---

### Q8.4 — English-only or multilingual model?

| Option | WER (English) | Size | Notes |
|--------|--------------|------|-------|
| **English-only distil-large-v3** | Better | Smaller | ✅ Recommended |
| Multilingual | Slightly worse | Larger | Deferred to v2 |

**Selected:** English-only for v1
**Rationale:** Better English WER, smaller footprint. Model path is a single YAML config value — upgrading to multilingual requires no code change.

---

### Q8.5 — How often to run inference on buffered speech?

| Cadence | CPU load | Partial transcript freshness | Notes |
|---------|---------|------------------------------|-------|
| Every 30ms (every frame) | Very high | Instant | Impractical |
| Every 250ms | High | Good | 4 inf/sec during speech |
| **Every 500ms** | Balanced | Good | ✅ Recommended |
| On pause only | Low | Delayed | No streaming updates |
| Hybrid 500ms + final on pause | Moderate | Best | More complex |

**Selected:** Every 500ms of new audio
**Rationale:** Balanced CPU load (2 inferences/sec). Responsive partial transcript updates. Interval exposed as YAML config.

---

### Q8.6 — When are partial transcripts emitted downstream?

| Option | Notes |
|--------|-------|
| **Every inference cycle (every 500ms)** | ✅ Recommended — simple and consistent |
| Every word boundary | Requires word-boundary detection logic |
| Timer-based (every N ms) | Decoupled from inference; stale results |

**Selected:** Every inference cycle (every 500ms)
**Rationale:** Whatever faster-whisper returns at 500ms is immediately emitted as `TranscriptionFrame`. UI gets live updates; Smart Turn always has fresh context.

---

### Q8.7 — How to eliminate cold-start latency on the first utterance?

| Option | Notes |
|--------|-------|
| **Pre-load + dummy inference** | ✅ Recommended — warms CUDA kernels and model cache |
| Pre-load only | First real inference still cold-starts CUDA |
| Lazy load | First-utterance delay visible to user |

**Selected:** Pre-load model + run dummy inference on startup
**Rationale:** Silent 1-second audio (zeros at 16kHz) through full inference path at startup. `INITIALIZING → READY` fires only after warm-up completes.

---

## Branch 9 — LLM — OpenAI Nano

### Q9.1 — Which specific OpenAI model?

| Model | Latency | Cost | Quality | Notes |
|-------|---------|------|---------|-------|
| **`gpt-4.1-nano`** | Ultra-low | Lowest | Strong | ✅ Recommended |
| `gpt-4o-mini` | Low | Low | Good | Slightly higher cost/latency |
| `gpt-4o` | Medium | High | Best | Overkill for conversational use |

**Selected:** `gpt-4.1-nano`
**Rationale:** Best fit for fast, cheap, conversational use case. Model identifier in YAML config.

---

### Q9.2 — SSE streaming via SDK or raw HTTP?

| Option | Notes |
|--------|-------|
| **`AsyncOpenAI` SDK with SSE streaming** | ✅ Recommended — official, maintained, async-native |
| Raw HTTP with `httpx` | Manual SSE parsing; no advantage |
| WebSocket | Not the OpenAI API transport |

**Selected:** `AsyncOpenAI` SDK with SSE streaming
**Rationale:** Integrates cleanly with asyncio and Pipecat. Each token yielded as `TextFrame` immediately.

---

### Q9.3 — Static system prompt or dynamic with context injection?

| Option | Notes |
|--------|-------|
| **Dynamic: static base persona + last 10 turns** | ✅ Recommended |
| Static only | No conversation history; agent forgets everything |
| Dynamic with full session history | Unbounded context growth |

**Selected:** Dynamic — static base persona + last 10 turns as message pairs
**Rationale:** Static base prompt defines persona, response style (concise, spoken-word-friendly, no markdown). Last 10 turns appended per call. N=10 configurable via YAML.

---

### Q9.4 — Context window management strategy?

| Option | Notes |
|--------|-------|
| **Sliding window** | ✅ Recommended — simple, predictable |
| Summarisation | Extra LLM calls; deferred to v2 |
| Hard truncation | Same as sliding window but less controlled |
| Keep full history | Unbounded; context overflow |

**Selected:** Sliding window — drop oldest turns when token count exceeds 80% of context window
**Rationale:** Token count estimated with `tiktoken`. No extra LLM calls. Threshold in YAML config.

---

### Q9.5 — What `max_tokens` cap for LLM responses?

| Cap | ~Words | Notes |
|-----|--------|-------|
| 100 | ~75 | Too short for complex answers |
| **300** | ~225 | ✅ Recommended |
| 500 | ~375 | TTS latency grows; too long for conversation |
| Unlimited | ∞ | Essay-length responses possible |

**Selected:** `max_tokens=300`
**Rationale:** Generous enough for complex answers without enabling monologues. TTS latency bounded. Exposed as YAML config.

---

### Q9.6 — What sampling parameters?

| Setting | Style | Notes |
|---------|-------|-------|
| temperature 0.0 | Deterministic | Robotic, repetitive |
| temperature 0.5 | Flat | Too predictable |
| **temperature 0.7, top_p 0.9** | Balanced | ✅ Recommended |
| temperature 1.0+ | Creative | Risk of off-topic drift |

**Selected:** `temperature=0.7`, `top_p=0.9`
**Rationale:** Standard conversational sweet spot. `top_p=0.9` prevents very unlikely tokens. Both in YAML config.

---

### Q9.7 — How to abort an in-flight streaming LLM request on barge-in?

| Option | Notes |
|--------|-------|
| **`asyncio.Task.cancel()`** | ✅ Recommended — idiomatic asyncio |
| SDK cancel method | Less direct |
| Let it finish silently | Wastes API tokens; no barge-in |
| Drain and discard | Slow; still costs tokens |

**Selected:** Close HTTP stream via `asyncio.Task.cancel()`
**Rationale:** LLM call wrapped in `asyncio.Task`. `task.cancel()` raises `CancelledError`, triggers `INTERRUPTED` state transition. Immediate, clean, no wasted tokens.

---

### Q9.8 — What happens on 429 rate limit or 500 server error?

| Option | Notes |
|--------|-------|
| **Retry once + canned fallback** | ✅ Recommended |
| Multiple retries | Delays user too long |
| Fail immediately | No recovery attempt |
| Fall back to different model | Config complexity; latency |

**Selected:** Retry once after 1s backoff, then speak canned fallback response
**Rationale:** Single retry costs only 1s. On second failure, emit canned fallback text to TTS directly. Fallback text configurable in YAML.

---

## Branch 10 — TTS — Piper

### Q10.1 — Which Piper voice model and speaker?

| Model | Size | Quality | Speed | Notes |
|-------|------|---------|-------|-------|
| **`en_US-lessac-medium`** | ~60 MB | High | Fast | ✅ Recommended |
| `en_US-lessac-high` | ~120 MB | Very high | Slower | More VRAM; marginal quality gain |
| `en_US-ryan-medium` | ~60 MB | High | Fast | Different voice character |
| `en_US-amy-low` | ~15 MB | Moderate | Fastest | Noticeable quality reduction |

**Selected:** `en_US-lessac-medium`
**Rationale:** Best production balance of naturalness and speed. Most widely tested Piper voice on Windows. Voice model path in YAML config.

---

### Q10.2 — Subprocess call, shared library, or Python binding?

| Option | Latency | Cancellability | Notes |
|--------|---------|---------------|-------|
| **`piper-tts` Python binding** | Lowest | Easy (stop iterating) | ✅ Recommended |
| Subprocess call | IPC overhead | Complex cancellation | |
| Shared library (ctypes) | Low | Complex | More fragile |

**Selected:** `piper-tts` Python binding
**Rationale:** In-process synthesis via `onnxruntime`. No subprocess spawning or IPC overhead. Cancellable by abandoning synthesis loop.

---

### Q10.3 — Raw PCM, WAV chunks, or Opus before transport?

| Option | Notes |
|--------|-------|
| **Raw PCM internally, Opus at LiveKit transport boundary** | ✅ Recommended — symmetric with input path |
| WAV chunks | Codec parsing inside pipeline |
| Pre-encode to Opus in TTS adapter | Misplaces codec responsibility |

**Selected:** Raw PCM internally, Opus encode at the LiveKit transport boundary
**Rationale:** Symmetric with input path (Decision 5.5). All internal stages work with simple raw PCM. Codec responsibility co-located in transport adapter.

---

### Q10.4 — How to stop Piper mid-synthesis on barge-in?

| Option | Notes |
|--------|-------|
| **Abandon synthesis iterator + flush LiveKit playback buffer** | ✅ Recommended |
| Kill subprocess (N/A) | Not applicable to binding |
| Let current chunk finish | Audible lag after barge-in |
| Thread interrupt | Unsafe — ONNX runtime state corruption |

**Selected:** Abandon synthesis iterator + flush LiveKit playback buffer
**Rationale:** Clean and safe — stop consuming iterator, signal LiveKit transport to flush. Python GC handles unused audio data.

---

### Q10.5 — When to start synthesis?

| Option | Time-to-first-audio | Notes |
|--------|--------------------|----|
| **Start on first complete phrase from chunker** | Lowest | ✅ Recommended — core latency win |
| Wait for full LLM response | Highest | Defeats streaming cascade purpose |
| Start on first N tokens | Very low | Risk of TTS receiving incomplete fragments |

**Selected:** Start synthesis on first complete phrase emitted by the chunker
**Rationale:** LLM continues streaming while Piper speaks first phrase — user hears audio as early as possible. Chunker ensures complete grammatical input to Piper.

---

### Q10.6 — Enable or disable phoneme cache?

| Option | Notes |
|--------|-------|
| **Enable phoneme cache** | ✅ Recommended — free latency win |
| Disable | No reason to disable |

**Selected:** Enable phoneme cache
**Rationale:** Common conversational words repeat constantly. In-memory cache, negligible memory cost (~few MB).

---

## Branch 11 — Text Chunking (LLM → TTS Bridge)

### Q11.1 — Sentence boundaries only, or also clause/phrase boundaries?

| Strategy | First audio latency | Naturalness | Notes |
|----------|--------------------|----|-------|
| **Sentence + clause boundaries** | Low | High | ✅ Recommended |
| Sentence only | Medium | Good | May wait too long for long opening sentence |
| Fixed token count | Lowest | Poor | Piper prosody breaks badly |
| Word boundary only | Very low | Very poor | Too granular |

**Selected:** Sentence + clause boundaries
**Rationale:** Split on `.?!;:` always; split on `,` when buffer exceeds 80 characters. 80-char comma threshold prevents splitting "Hello, how are you?" at the comma. Both thresholds in YAML config.

---

### Q11.2 — Minimum characters before sending a chunk to Piper?

| Min chars | Notes |
|-----------|-------|
| 0 | Every boundary split regardless of length |
| 10 | Very short — catches "Okay." |
| **20** | ✅ Recommended — ~3–5 words |
| 50 | May delay short genuine answers |

**Selected:** 20 characters minimum
**Rationale:** Filters single-word and very short fragments ("I see.", "Sure.") that cause choppy TTS rhythm. Exposed as YAML config.

---

### Q11.3 — Maximum characters before forced flush?

| Max chars | Notes |
|-----------|-------|
| 100 | Aggressive; splits mid-phrase too often |
| **200** | ✅ Recommended — ~2–3 normal sentences |
| 500 | Very permissive |
| No max | Risk of indefinite buffering |

**Selected:** 200 characters maximum buffer before forced flush
**Rationale:** Safety valve for run-on LLM output. Rarely triggered when `gpt-4.1-nano` is instructed to be concise. Exposed as YAML config.

---

### Q11.4 — Sentence boundary detection method?

| Option | Accuracy | Dependency | Latency | Notes |
|--------|----------|-----------|---------|-------|
| **Simple punctuation regex** | Good enough | Zero (stdlib `re`) | <0.1ms | ✅ Recommended |
| spaCy | Near-perfect | ~50 MB model | ~5–20ms | Overkill |
| NLTK | Good | ~10 MB | ~2ms | Unnecessary overhead |

**Selected:** Simple punctuation regex (stdlib `re`)
**Rationale:** LLM output is well-structured. Regex on `.?!;:` with guards for `Mr.`, `Dr.`, decimal numbers handles 99% of cases. spaCy deferred as config-switchable backend.

---

### Q11.5 — How should the chunker handle markdown and code blocks?

| Option | Behaviour | Notes |
|--------|-----------|-------|
| **Strip markdown, skip/replace code blocks** | Remove `**`, `*`, `#`, `-`; replace code blocks with spoken phrase | ✅ Recommended |
| Speak verbatim | TTS reads "asterisk asterisk bold asterisk asterisk" | Terrible UX |
| Fail and regenerate | Ask LLM to reformat | Adds round-trip latency |

**Selected:** Strip markdown, skip/replace code blocks
**Rationale:** System prompt already instructs no markdown; chunker stripping is safety net. Code blocks → "I'd share some code, but this is a voice conversation." Bullet lists → "first... second... third..." All toggleable via YAML config.

---

## Branch 12 — Barge-In Controller

### Q12.1 — Consecutive VAD frames to confirm barge-in?

| Consecutive frames | Duration | Notes |
|--------------------|----------|-------|
| 1 | 30ms | Noise triggers interrupts constantly |
| **3** | 90ms | ✅ Recommended — filters transients, responds within ~100ms |
| 5 | 150ms | Noticeable lag |
| 8 | 240ms | Quarter-second of speech before reaction |

**Selected:** 3 consecutive VAD-positive frames (90ms)
**Rationale:** Standard threshold in production voice systems. Exposed as YAML config.

---

### Q12.2 — Minimum speech duration before acting on barge-in?

| Duration | Effect | Notes |
|----------|--------|-------|
| 0ms | Act immediately on confirmation | React to "mm", "uh" |
| **150ms** | ~5 frames | ✅ Recommended |
| 300ms | Half a second | User said a full word before reaction |
| 500ms | Defeats fast barge-in | Too slow |

**Selected:** 150ms minimum speech duration
**Rationale:** Total detection window: 3-frame confirmation (90ms) + 150ms = ~240ms from first speech frame to action. Imperceptible delay; excludes brief vocalizations. Exposed as YAML config.

---

### Q12.3 — What happens to interrupted TTS context?

| Option | Notes |
|--------|-------|
| **Discard entirely** | ✅ Recommended — conversationally correct |
| Preserve for resumption | Agent ignores barge-in and continues old response |
| Partial discard (keep last sentence) | Complex; marginal benefit |

**Selected:** Discard entirely
**Rationale:** When a user interrupts, they want a response to their new input. Abandon Piper iterator, flush audio queue, emit `InterruptFrame`. LLM generates fresh response.

---

### Q12.4 — What happens to in-flight LLM tokens when barge-in fires?

| Option | Notes |
|--------|-------|
| **Cancel task + discard buffer** | ✅ Recommended — clean interruption |
| Cancel + flush buffer to TTS | Agent keeps speaking briefly after interruption |
| Drain stream then cancel | Can take seconds |
| Retry with barge-in content prepended | STT not complete yet |

**Selected:** Cancel `asyncio.Task` + discard all buffered tokens
**Rationale:** Consistent with Decision 9.6 (asyncio.Task cancellation) and Decision 12.3 (discard TTS context). New LLM call starts only after barge-in utterance is complete.

---

### Q12.5 — Barge-in cooldown period?

| Cooldown | Notes |
|----------|-------|
| 0ms | Cascade interruptions; echo can re-trigger |
| **500ms** | ✅ Recommended |
| 1000ms | User feels locked out for a full second |
| 2000ms | Too restrictive |

**Selected:** 500ms cooldown after a barge-in event
**Rationale:** Time for audio pipeline flush, echo/feedback decay, and state machine transition. Exposed as YAML config.

---

### Q12.6 — Which states should barge-in be active in?

| Option | Notes |
|--------|-------|
| **SPEAKING only** | ✅ Recommended — only meaningful when agent is outputting audio |
| SPEAKING + PROCESSING | PROCESSING interruption handled by Smart Turn |
| All non-LISTENING states | Too broad; could fire in THINKING_PAUSE |
| All states | Nonsensical in LISTENING/SHUTDOWN |

**Selected:** SPEAKING only
**Rationale:** Controller armed on entry to SPEAKING, disarmed on exit. Active state list exposed as YAML config.

---

## Branch 13 — Conversation State Machine

### Q13.1 — Accept design doc's 11-state machine or modify it?

The 11 states from `system_doc.md`:

`INITIALIZING → READY → LISTENING → USER_SPEAKING → THINKING_PAUSE → PROCESSING → SPEAKING → INTERRUPT_CANDIDATE → INTERRUPTED → DEGRADED → SHUTDOWN`

| Option | Notes |
|--------|-------|
| **Accept all 11 states** | ✅ Recommended — each has distinct role |
| Drop THINKING_PAUSE | Loses Smart Turn hook between VAD silence and LLM dispatch |
| Drop INTERRUPT_CANDIDATE | Loses 3-frame confirmation window |
| Merge INTERRUPTED + PROCESSING | Different semantic purposes |
| Add states | No gaps identified for v1 |

**Selected:** All 11 states as defined
**Rationale:** Implemented as Python `Enum`. Each state has a distinct role; no state is redundant.

---

### Q13.2 — Strict whitelist or permissive transitions?

| Option | Notes |
|--------|-------|
| **Strict whitelist — invalid transitions raise `InvalidTransitionError`** | ✅ Recommended |
| Permissive — log warning, allow | Silent failures cascade |
| Strict whitelist — silent no-op | Worst of both worlds |

**Selected:** Strict whitelist — invalid transitions raise `InvalidTransitionError`
**Rationale:** Self-documenting; turns logic bugs into immediate traceable errors. In production, `InvalidTransitionError` caught at pipeline level → `DEGRADED`. Transition table: `dict[ConversationState, set[ConversationState]]`.

---

### Q13.3 — State persistence?

| Option | Notes |
|--------|-------|
| **In-memory only — reset to `INITIALIZING` on restart** | ✅ Recommended |
| Persist to disk (SQLite/file) | State coupled to live resources that don't survive restart |
| Persist to Redis | Same fundamental problem; overkill |

**Selected:** In-memory only
**Rationale:** Voice agent state coupled to live resources (WebRTC, audio buffers, LLM SSE stream). Restoring `SPEAKING` with no active stream is nonsensical. Conversation history is a separate concern (Branch 14).

---

### Q13.4 — How do other components learn about state transitions?

| Option | Notes |
|--------|-------|
| **`StateChangeFrame` through Pipecat pipeline** | ✅ Recommended — consistent with frame-based architecture |
| asyncio Event/Queue per subscriber | Subscriber list management |
| Callback registry | Couples state machine to consumers |
| Polling | Latency and CPU waste |

**Selected:** Emit `StateChangeFrame` through the Pipecat pipeline on every transition
**Rationale:** Frame carries `previous_state`, `new_state`, `timestamp`. Consistent with Decision 4.3. Zero additional infrastructure.

---

### Q13.5 — PROCESSING state watchdog timeout?

| Timeout | Notes |
|---------|-------|
| 5s | May fire during legitimate slow responses |
| **10s** | ✅ Recommended — 3–4× expected worst case |
| 30s | User stares at silent agent for 30s |
| No timeout | Indefinite hang |

**Selected:** 10 seconds
**Rationale:** `gpt-4.1-nano` full response rarely exceeds 3–4s for `max_tokens=300`. On timeout: force `DEGRADED`, emit canned fallback, attempt recovery to `READY`. Exposed as YAML config.

---

### Q13.6 — DEGRADED state recovery?

| Option | Notes |
|--------|-------|
| **Automatic single retry to `READY` after 2s → `SHUTDOWN` on second failure** | ✅ Recommended |
| Exponential backoff | More complex; not needed for v1 |
| Require manual restart | Terrible UX |
| Immediate SHUTDOWN | Only for truly fatal errors |

**Selected:** Automatic single retry to `READY` after 2s; if recovery fails, transition to `SHUTDOWN`
**Rationale:** One attempt covers transient hiccups. Fatal errors (missing API key) skip retry and go directly to `SHUTDOWN`. Retry delay in YAML config.

---

## Branch 14 — Conversation Memory

### Q14.1 — Session-only memory or persist across sessions?

| Option | Scope | Privacy surface | Notes |
|--------|-------|----------------|-------|
| **Session-only — cleared on session end** | Session | Zero | ✅ Recommended |
| Persist to SQLite/file | Cross-session | Requires privacy design | v2 consideration |
| Persist with user profiles | Cross-session | High | Multi-user complexity |

**Selected:** Session-only — memory cleared on session end
**Rationale:** Persistent memory requires identity model, privacy design, schema — out of scope for v1. Persistence deferred to v2 with proper identity layer.

---

### Q14.2 — Turn history format?

| Option | LLM conversion | Notes |
|--------|---------------|-------|
| **Native OpenAI message list** | None — IS the message list | ✅ Recommended |
| Custom `Turn` dataclass | Convert at call time | Extra conversion step |
| Plain string transcript | Must parse before LLM use | Error-prone |
| JSON blob per turn | Less typed than dataclass | |

**Selected:** Native OpenAI message list — `list[dict]` with `role` and `content` keys
**Rationale:** LLM call: `messages = [system_prompt] + memory.turns[-10:]`. Consistent with Decision 9.2.

---

### Q14.3 — How many turns in the sliding window, and what happens to overflow?

| Turns | ~Tokens | Notes |
|-------|---------|-------|
| 5 | ~500–750 | Agent forgets recent exchanges quickly |
| **10** | ~1,000–1,500 | ✅ Recommended (consistent with Decision 9.2) |
| 20 | ~2,000–3,000 | Higher cost per call |
| Unlimited | Grows unbounded | Context overflow |

| Overflow handling | Notes |
|------------------|-------|
| **Discard silently** | ✅ Recommended for v1 |
| Summarise into prefix | Extra LLM call per overflow; deferred to v2 |

**Selected:** 10-turn sliding window, discard overflow silently
**Rationale:** Covers most natural conversation flows. Silent discard is simple and correct for v1.

---

### Q14.4 — When are turns appended to memory?

| Option | Notes |
|--------|-------|
| **Append user on `TranscriptionFrame`; agent on `TurnCompleteFrame`** | ✅ Recommended |
| Delay user turn until agent responds | Risk of losing utterance on crash |
| Append agent tokens streaming | Partial turns if barge-in occurs |
| Batch at session end | No history mid-session |

**Selected:** Append user turn on `TranscriptionFrame`; append agent turn on `TurnCompleteFrame` only
**Rationale:** Interrupted agent turns (barge-in) are NOT appended — only fully delivered turns enter context.

---

### Q14.5 — Token counting method?

| Option | Precision | Notes |
|--------|----------|-------|
| **`tiktoken` per turn; enforce hard budget** | Exact | ✅ Recommended |
| Turn count only (N=10) | Imprecise for long turns | Risk: 10 very long turns could overflow |
| Character estimate (~4 chars/token) | Imprecise | Can over- or under-trim |
| React to API errors | None | Causes failed requests |

**Selected:** `tiktoken` token counting per turn; enforce hard budget
**Rationale:** `tiktoken` already a dependency. Budget = `max_context_tokens - max_tokens - system_prompt_tokens`, all YAML-configurable. Prevents context overflow proactively.

---

## Branch 15 — UI and Client

### Q15.1 — Client type?

| Option | Build step | Notes |
|--------|-----------|-------|
| **Browser-based HTML/JS single page** | None | ✅ Recommended — consistent with Decision 3.4 |
| Electron desktop app | Separate toolchain | v2 consideration |
| Python CLI | No visual feedback | Poor UX for voice agent |
| Native Windows app | .NET stack | Large scope |

**Selected:** Browser-based single HTML page — `client/index.html` + `client/app.js`
**Rationale:** No install, no build step. Served as static files by agent HTTP server. Runs in any Windows browser.

---

### Q15.2 — Transcript display?

| Option | Notes |
|--------|-------|
| **Live rolling transcript — both user and agent turns** | ✅ Recommended |
| Audio only | Loses usability; harder to verify correctness |
| Agent turns only | User can't verify their utterance was understood |
| Word-level timestamps | `faster-whisper` doesn't emit word-level alignment during streaming |

**Selected:** Live rolling transcript for both user and agent turns
**Rationale:** Data already flowing through pipeline. Sent via LiveKit data channel as JSON events. Scrolling panel in UI.

---

### Q15.3 — State and metrics display?

| Option | Notes |
|--------|-------|
| **Show current state + key latency metrics** | ✅ Recommended |
| State only | Loses latency visibility for tuning |
| Metrics only | State context makes metrics meaningful |
| Neither | Hard to know why agent is silent or slow |

**Selected:** Show current conversation state + key latency metrics (STT latency, LLM TTFT, TTS time-to-first-audio)
**Rationale:** `StateChangeFrame` and `MetricFrame` already in pipeline. Same data channel. Compact status bar updated on each frame event.

---

### Q15.4 — Audio device selection?

| Option | Notes |
|--------|-------|
| **Browser default — no selector** | ✅ Recommended for v1 |
| Mic dropdown | Useful but adds complexity; deferred to v2 |
| Mic + speaker dropdowns | Speaker routing via Web Audio API is non-trivial |
| System tray / OS-level | Outside browser scope |

**Selected:** Browser default audio devices — no device selector UI in v1
**Rationale:** `getUserMedia()` with no `deviceId` picks up OS Sound Settings default. README instructs users to set preferred device in Windows Sound Settings.

---

### Q15.5 — Visual design and UI framework?

> User requested React JS. Clarified: React via CDN (no build step) vs React + Vite (requires Node.js build toolchain).

| Option | Build step | Notes |
|--------|-----------|-------|
| Plain HTML minimal UI | None | Simplest |
| Tailwind CDN | None | CDN dependency |
| **React via CDN + Babel Standalone** | None | ✅ Selected — React component model, no build toolchain |
| React + Vite build toolchain | Yes | Requires Node.js; contradicts Decision 15.1 |

**Selected:** React via CDN + Babel Standalone — no build step
**Rationale:** React and ReactDOM loaded from CDN; JSX transpiled in-browser via Babel Standalone. Component model for state management and re-renders without Node.js or build pipeline. `client/` folder remains static HTML + JS only.

---

## Branch 16 — Observability and Metrics

### Q16.1 — Logging framework?

| Option | Structured | Async-safe | Notes |
|--------|-----------|-----------|-------|
| **`structlog` with JSON output** | ✅ | ✅ | ✅ Recommended |
| stdlib `logging` | No (requires setup) | Yes | Manual JSON formatting |
| `loguru` | Partial | Yes | Not JSON-native |
| OpenTelemetry SDK | Yes | Yes | Overkill — distributed tracing |

**Selected:** `structlog` with JSON output to stdout
**Rationale:** Records like `{"event": "stt_complete", "duration_ms": 142, "state": "PROCESSING"}`. Session ID and conversation state bound once at session start. Log level via YAML/env var.

---

### Q16.2 — Metrics collection method?

| Option | External infra | Notes |
|--------|--------------|-------|
| **In-process `MetricFrame` + structlog** | None | ✅ Recommended |
| Prometheus + `prometheus_client` | Prometheus server required | Overkill for v1 |
| StatsD | StatsD daemon required | Overkill for v1 |
| Derive from logs | Post-processing required | Fragile |

**Selected:** In-process `MetricFrame` collection logged via `structlog`
**Rationale:** `MetricFrame` already decided. Same log stream; queryable with any JSON tool. UI receives metrics via LiveKit data channel.

---

### Q16.3 — Which latency metrics per turn?

| # | Metric | Measures |
|---|--------|---------|
| 1 | STT latency | `TranscriptionFrame` emit − VAD end-of-speech |
| 2 | LLM time-to-first-token | First SSE token − LLM call dispatch |
| 3 | LLM total generation time | `TurnCompleteFrame` − LLM call dispatch |
| 4 | TTS time-to-first-audio | First Piper audio chunk − chunk text received |
| 5 | End-to-end turn latency | First audio out − VAD end-of-speech |
| 6 | Barge-in detection latency | `InterruptFrame` − first VAD-positive frame |
| 7 | Chunk count per turn | Number of TTS chunks emitted |

| Option | Notes |
|--------|-------|
| **All 7 metrics** | ✅ Recommended |
| Core 3 only | Misses end-to-end and barge-in |
| End-to-end only | Hides which stage is slow |

**Selected:** All 7 metrics per turn
**Rationale:** Each serves a distinct diagnostic purpose. Per-session p50/p95 aggregated at session end.

---

### Q16.4 — Log level policy?

| Level | Usage |
|-------|-------|
| DEBUG | Frame-by-frame trace (dev only) |
| INFO | Turn events, state transitions, metrics |
| WARNING | Recoverable issues (retry succeeded, fallback triggered) |
| ERROR | Exceptions, failed transitions, DEGRADED entry |

| Option | Notes |
|--------|-------|
| **DEBUG/INFO/WARNING/ERROR (4-level)** | ✅ Recommended |
| DEBUG/INFO/ERROR (3-level) | WARNING useful for retry/fallback distinction |
| INFO only | Can't suppress verbose frame tracing |
| Add CRITICAL | SHUTDOWN can be ERROR; CRITICAL adds marginal value |

**Selected:** Standard 4-level policy: DEBUG / INFO / WARNING / ERROR
**Rationale:** `LOG_LEVEL` via env var and YAML, defaulting to `INFO` in production.

---

### Q16.5 — Health check endpoint?

| Option | Notes |
|--------|-------|
| **`GET /health` returning JSON status** | ✅ Recommended |
| No health endpoint | Can't distinguish DEGRADED from healthy |
| `/ready` + `/live` split | Kubernetes-style; overkill for v1 |
| Health via metrics log | Not machine-readable |

**Selected:** `GET /health` returning `{"status": "ok"|"degraded", "state": "<ConversationState>", "uptime_s": N}`
**Rationale:** 5-line route addition to existing HTTP server. Enables `curl` verification and process monitors.

---

### Q16.6 — Session summary logging?

| Option | Notes |
|--------|-------|
| **Structured JSON summary at session end** | ✅ Recommended |
| Derive from per-turn logs | Requires post-processing |
| Separate `.json` file | Useful but adds file I/O |
| Debug-only | Should be visible at INFO |

**Selected:** Emit structured session summary JSON record at INFO level on session end
**Rationale:** One record per session answers "how did this session go?" Includes: total turns, duration, p50/p95 for all 7 metrics, barge-in count, DEGRADED count, fallback count.

---

## Branch 17 — Testing Strategy

### Q17.1 — Test framework?

| Option | Async support | Notes |
|--------|--------------|-------|
| **pytest + pytest-asyncio** | Native | ✅ Recommended |
| stdlib unittest | Poor | Verbose; manual async wiring |
| pytest + anyio | Good | Less common than pytest-asyncio |
| No framework | None | Unscalable |

**Selected:** pytest + pytest-asyncio with `asyncio_mode = "auto"` in `pyproject.toml`
**Rationale:** De facto standard. Every async test function automatically treated as async test. Rich fixture system for component setup/teardown.

---

### Q17.2 — Unit test scope?

| Component | Test type |
|-----------|-----------|
| State machine | Unit — pure Python Enum + transition logic |
| Text chunker | Unit — pure string processing |
| Markdown stripper | Unit — pure regex |
| Memory module | Unit — in-memory list + tiktoken |
| Config loader | Unit — YAML parse + pydantic |
| Barge-in controller | Unit — mock VAD frame stream + timer |
| Metrics processor | Unit — mock MetricFrame stream |
| STT adapter | Integration — requires faster-whisper model |
| LLM adapter | Integration — requires OpenAI API (+ respx unit test) |
| TTS adapter | Integration — requires Piper binary |

| Option | Notes |
|--------|-------|
| **Unit test pure-logic; mock at adapter interfaces** | ✅ Recommended |
| Unit test everything including models | Impractical in CI |
| Integration tests only | Slow; hard to isolate regressions |

**Selected:** Unit test pure-logic components; mock I/O boundary at adapter interfaces
**Rationale:** Pure-logic components are deterministic. Adapter unit tests with deep mocks add fragility without catching real integration bugs.

---

### Q17.3 — Integration test approach?

| Option | Notes |
|--------|-------|
| **`@pytest.mark.integration`, skipped in CI by default** | ✅ Recommended |
| Run all in CI | Requires GPU, model files, API keys in CI |
| Separate ad-hoc scripts | Loses pytest fixture reuse |
| respx HTTP mocking only | Valid for LLM adapter unit tests; not STT/TTS |

**Selected:** `@pytest.mark.integration` marker; skipped in CI by default. LLM adapter additionally gets `respx`-based unit test for SSE stream handling.
**Rationale:** `pytest -m integration` locally. `respx` fakes OpenAI SSE stream without real API key.

---

### Q17.4 — Benchmark structure?

| Option | Notes |
|--------|-------|
| **End-to-end latency benchmark via `benchmark` subcommand** | ✅ Recommended |
| pytest-benchmark | Microbenchmarks; not useful for end-to-end latency |
| Manual scripts | No structured output |
| No benchmarks | Latency targets unverifiable |

**Selected:** `uv run voice-agent benchmark --input fixtures/test_audio.wav`
**Rationale:** Runs full pipeline with real models. Reports all 7 latency metrics as JSON summary. ~5 pre-recorded WAV fixtures of varying lengths in `tests/fixtures/`.

---

### Q17.5 — CI/CD pipeline?

| Option | Notes |
|--------|-------|
| **GitHub Actions: unit tests + ruff + mypy on every push** | ✅ Recommended |
| GitHub Actions + integration tests | Requires GPU/model/API keys in CI |
| pre-commit hooks only | No server-side enforcement |
| No CI | Not appropriate for maintained codebase |

**Selected:** GitHub Actions running: (1) `uv sync`, (2) `ruff check src/ tests/`, (3) `mypy src/`, (4) `pytest tests/ -m "not integration"` on every push to `main` and PRs
**Rationale:** Fast (<2 min). No secrets or GPU required. Workflow at `.github/workflows/ci.yml`.

---

### Q17.6 — Test fixtures strategy?

| Option | Notes |
|--------|-------|
| **pytest fixtures in `conftest.py`** | ✅ Recommended — standard pytest pattern |
| Copy-paste setup per file | Duplication; maintenance burden |
| `tests/helpers.py` factory functions | Loses pytest scope management |
| fixtures + faker/factory_boy | Overkill for audio/text domain |

**Key fixtures defined:**

| Fixture | Scope | Content |
|---------|-------|---------|
| `sample_config` | session | Loaded from test YAML |
| `sample_audio_frame` | function | 30ms PCM bytes |
| `sample_transcription` | function | Short/medium/long utterance strings |
| `mock_pipeline` | function | Mock Pipecat pipeline |
| `state_machine` | function | Fresh `ConversationStateMachine` instance |
| `memory_store` | function | Empty `SessionMemory` instance |

**Selected:** `conftest.py`-based pytest fixtures at `tests/` root
**Rationale:** Auto-discovered and auto-injected. Scope management prevents stateful test pollution.

---

## Branch 18 — Error Handling and Fallbacks

### Q18.1 — STT failure handling?

| Option | Notes |
|--------|-------|
| **Canned "I didn't catch that, could you repeat?" + LISTENING** | ✅ Recommended |
| Transition to DEGRADED | Too severe for transient failures |
| Silent drop | User doesn't know they weren't heard |
| Retry STT N times | Resource-related failures likely repeat immediately |

**Selected:** Emit canned "I didn't catch that, could you repeat?" audio + return to LISTENING
**Rationale:** STT failures almost always transient (GPU OOM, thread contention). Fallback phrase configurable in YAML. Logged at WARNING.

---

### Q18.2 — LLM failure handling?

| Option | Notes |
|--------|-------|
| **Retry once → canned "I'm having trouble thinking" → LISTENING** | ✅ Recommended |
| Retry once → DEGRADED | Too severe for single turn failure |
| No retry → immediate fallback | Wastes a retry that often succeeds |
| Queue and retry later | Voice doesn't tolerate multi-second waits |

**Selected:** Retry once → canned "I'm having trouble thinking" audio → return to LISTENING
**Rationale:** Consistent with Decision 9.6. Distinct fallback phrase from STT fallback. Second failure logged at ERROR. Phrase configurable in YAML.

---

### Q18.3 — TTS failure handling?

| Option | Notes |
|--------|-------|
| **Abandon synthesis, play pre-synthesised fallback WAV, return to LISTENING** | ✅ Recommended |
| Retry synthesis | Piper failures usually binary; retry fails again |
| Fallback to shorter Piper text | Piper is the failure point |
| Transition to DEGRADED | Too severe for transient failures |

**Selected:** Abandon synthesis, play pre-synthesised `assets/fallback.wav`, return to LISTENING
**Rationale:** If Piper is broken, Piper-generated fallback also fails. WAV generated once and committed to repo. Logged at WARNING.

---

### Q18.4 — Transport failure handling?

| Option | Notes |
|--------|-------|
| **Exponential backoff (1s/2s/4s/8s/16s), max 5 retries → SHUTDOWN** | ✅ Recommended |
| Immediate single retry | Too aggressive for brief network hiccups |
| Reconnect indefinitely | Could loop forever |
| Immediate SHUTDOWN | WiFi blip kills session permanently |

**Selected:** Exponential backoff reconnect (5 retries) → SHUTDOWN
**Rationale:** Consistent with Decision 3.6. During reconnect: `DEGRADED`, halt pipeline. On success: `READY`. On exhaustion: `SHUTDOWN`.

---

### Q18.5 — Provider swap abstraction?

| Option | Notes |
|--------|-------|
| **Formal `typing.Protocol` per adapter type; config injection** | ✅ Recommended |
| Concrete classes only | Pipeline couples to specific providers |
| ABCs (`abc.ABC`) | Less Pythonic; requires inheritance |
| Full plugin architecture | Overkill for v1 |

**Protocols defined in `src/voice_agent/protocols.py`:**

| Protocol | Implementations |
|----------|----------------|
| `STTAdapter` | `FasterWhisperAdapter` |
| `LLMAdapter` | `OpenAINanoAdapter` |
| `TTSAdapter` | `PiperAdapter` |
| `TransportAdapter` | `LiveKitTransportAdapter` |

**Selected:** Formal `typing.Protocol` interface per adapter type; concrete implementations injected via config
**Rationale:** Structural subtyping — no inheritance required. Mock implementations in unit tests naturally satisfy protocols. Config selects backend (e.g. `stt.backend: "faster_whisper"` → `FasterWhisperAdapter`). Pipeline code never couples to concrete providers.

---

## Branch 19 — OpenAI Realtime (Optional)

### Q19.1 — Include OpenAI Realtime API in v1 or defer to v2?

| Option | Notes |
|--------|-------|
| **Defer entirely to v2** | ✅ Recommended |
| Include as alternative backend | Doubles adapter surface and testing scope |
| Replace local stack entirely | Loses offline capability; higher cost |
| Realtime default + local fallback | Two complete pipeline paths |

**Selected:** Defer entirely to v2
**Rationale:** `typing.Protocol` interfaces (Decision 18.5) make a v2 Realtime adapter a clean, isolated addition with no pipeline changes. Swap path documented in README. No Realtime code in v1. Remaining questions (modes, runtime switching, transcript visibility) moot for v1.

---

## Branch 20 — Deployment and Packaging

### Q20.1 — Distribution method?

| Option | Notes |
|--------|-------|
| **`uv` clone-and-run** | ✅ Recommended — consistent with Decision 1.2 |
| PyPI package | Significant extra work; deferred to v2 |
| Windows installer | Separate toolchain; out of scope for v1 |
| Docker only | Real-time audio through Docker adds latency |

**Selected:** `uv`-managed venv; clone-and-run via `uv run voice-agent start`
**Rationale:** README is the installer: `git clone` → `uv sync` → `.env` → `uv run voice-agent start`. No packaging overhead for a v1 developer tool.

---

### Q20.2 — Docker support?

| Option | Notes |
|--------|-------|
| **No Docker in v1** | ✅ Recommended |
| CPU-only Dockerfile | Loses GPU acceleration |
| CUDA Dockerfile | WSL2 + NVIDIA Container Toolkit = more complex than native Python |
| Docker Compose | No additional services in v1 |

**Selected:** No Docker in v1 — README documents native Windows setup only
**Rationale:** Target platform is native Windows 10/11. Docker adds virtualisation layer to all latency-sensitive paths. Deferred to v2 for Linux server deployment demand.

---

### Q20.3 — Process mode?

| Option | Notes |
|--------|-------|
| **Foreground process only** | ✅ Recommended |
| Windows service (pywin32/NSSM) | Complex; not needed for interactive tool |
| Task Scheduler | Fragile; hard to manage |
| Foreground + optional service install | Adds scope |

**Selected:** Foreground process only — `uv run voice-agent start` in a terminal
**Rationale:** Interactive tool requiring a present user. `Ctrl+C` triggers graceful `SHUTDOWN`. Terminal window with live log output is useful for debugging. Service support deferred to v2.

---

### Q20.4 — First-run setup?

| Option | Notes |
|--------|-------|
| **`voice-agent check` subcommand + `.env.example`** | ✅ Recommended — zero extra scope |
| Interactive setup wizard | Useful but adds scope |
| README only | Users discover missing config via cryptic errors |
| Auto-download models | Adds significant download logic |

**Checks performed by `uv run voice-agent check`:**

| Check | Pass condition |
|-------|---------------|
| `LIVEKIT_URL` | Set in env |
| `OPENAI_API_KEY` | Set in env |
| CUDA device | Found (or CPU fallback noted) |
| Piper model file | Exists at configured path |
| faster-whisper model | Cached locally |

**Selected:** `uv run voice-agent check` pre-flight validation + `.env.example` with inline comments
**Rationale:** `check` subcommand already decided (Decision 2.3). README documents 5-step setup sequence. Zero extra scope.

---

## Final Confirmation

All 20 branches resolved. **User confirmed all decisions on May 15, 2026.**

### Implementation Order (from `prompt.md`)

| Step | Task |
|------|------|
| 1 | Folder structure + `pyproject.toml` |
| 2 | Config loader (`config/dev.yaml`, `config/prod.yaml`, pydantic `BaseSettings`) |
| 3 | Protocol/interface definitions (`src/voice_agent/protocols.py`) |
| 4 | Conversation state machine (`src/voice_agent/agent/state_machine.py`) |
| 5 | Audio preprocessing (`src/voice_agent/audio/`) |
| 6 | Silero VAD adapter (`src/voice_agent/audio/vad.py`) |
| 7 | Smart Turn adapter (`src/voice_agent/audio/smart_turn.py`) |
| 8 | faster-whisper STT adapter (`src/voice_agent/stt/`) |
| 9 | OpenAI nano LLM adapter (`src/voice_agent/llm/`) |
| 10 | Text chunker (`src/voice_agent/llm/chunker.py`) |
| 11 | Piper TTS adapter (`src/voice_agent/tts/`) |
| 12 | Barge-in controller (`src/voice_agent/agent/barge_in.py`) |
| 13 | Pipecat pipeline wiring (`src/voice_agent/agent/pipeline.py`) |
| 14 | LiveKit transport adapter (`src/voice_agent/transport/`) |
| 15 | Metrics and logging (`src/voice_agent/metrics/`) |
| 16 | Conversation memory (`src/voice_agent/memory/`) |
| 17 | Web client (`client/index.html`, `client/app.js`) |
| 18 | Startup and warmup (`src/voice_agent/__main__.py`) |
| 19 | Tests (`tests/`, `tests/conftest.py`, `.github/workflows/ci.yml`) |
| 20 | README and `.env.example` |
