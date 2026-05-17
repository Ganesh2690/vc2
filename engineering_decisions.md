# Engineering Decisions Log — Windows Voice Conversation Agent

> This file tracks every resolved engineering decision made during the GRILL-ME pre-implementation interview.
> Each entry records the branch, the question asked, the options considered, the decision taken, and the rationale.

---

## Status: IN PROGRESS — GRILL-ME Interview Active

| Branch | Topic | Status |
|--------|-------|--------|
| 1 | Environment and Runtime | ✅ Complete |
| 2 | Project Structure and Build | ✅ Complete |
| 3 | Transport Layer — LiveKit | ✅ Complete |
| 4 | Orchestration Layer — Pipecat | ✅ Complete |
| 5 | Audio Preprocessing | ✅ Complete |
| 6 | VAD — Silero | ✅ Complete |
| 7 | Turn Detection — Smart Turn | ✅ Complete |
| 8 | STT — faster-whisper / Distil-Whisper | ✅ Complete |
| 9 | LLM — OpenAI Nano | ✅ Complete |
| 10 | TTS — Piper | ✅ Complete |
| 11 | Text Chunking (LLM → TTS Bridge) | ✅ Complete |
| 12 | Barge-In Controller | ✅ Complete |
| 13 | Conversation State Machine | ✅ Complete |
| 14 | Conversation Memory | ✅ Complete |
| 15 | UI and Client | ✅ Complete |
| 16 | Observability and Metrics | ✅ Complete |
| 17 | Testing Strategy | ✅ Complete |
| 18 | Error Handling and Fallbacks | ✅ Complete |
| 19 | OpenAI Realtime (Optional Premium Path) | ✅ Complete |
| 20 | Deployment and Packaging | ✅ Complete |

---

## Resolved Decisions

### Branch 1 — Environment and Runtime

#### Decision 1.1 — Python Version
- **Question:** Which Python version to target?
- **Options considered:** 3.11, 3.12, 3.13
- **Decision:** ✅ **Python 3.11**
- **Rationale:** Widest pre-built wheel coverage on Windows for faster-whisper (ctranslate2), Pipecat, LiveKit SDK, Silero VAD, and Piper. No known compatibility blockers across the full stack.

#### Decision 1.2 — Virtual Environment and Package Manager
- **Question:** Which tool manages the virtual environment and packages?
- **Options considered:** uv, poetry, venv + pip + pip-tools, conda
- **Decision:** ✅ **uv**
- **Rationale:** Fastest installs (10–100× pip), handles both venv creation and package installs, produces a `uv.lock` for reproducible environments. Critical advantage for a stack with heavy native packages (ctranslate2, torch, onnxruntime). Single-line bootstrap in `setup.ps1`.

#### Decision 1.3 — Windows Audio API
- **Question:** How should microphone capture and speaker playback be handled on Windows?
- **Options considered:** WASAPI via sounddevice, pyaudio/PortAudio, DirectSound, LiveKit/WebRTC (browser handles it)
- **Decision:** ✅ **LiveKit/WebRTC — browser handles client audio for v1**
- **Rationale:** The v1 client is a web browser; the browser captures mic and handles speaker via WebRTC natively. LiveKit delivers audio frames to the Python agent. No Python-level Windows audio API needed for v1, eliminating a major source of platform complexity. `sounddevice` + WASAPI documented as a future fallback for a native desktop client.

#### Decision 1.4 — GPU / CUDA Strategy
- **Question:** Is CUDA required, and is a CPU-only fallback mandatory?
- **Options considered:** GPU + CPU fallback, CPU-only, GPU-required (no fallback)
- **Decision:** ✅ **CUDA 12.x with CPU-only fallback**
- **Rationale:** Agent auto-detects GPU at startup via `ctranslate2.get_cuda_device_count()`. If no CUDA device is found, falls back to `int8` CPU mode. Keeps v1 runnable on any Windows machine while delivering best latency on NVIDIA GPU hardware. Code difference is a single `device` parameter — minimal maintenance burden.

#### Decision 1.5 — Target Windows Versions
- **Question:** Which Windows versions are supported?
- **Options considered:** Windows 10 (21H2+) + Windows 11, Windows 11 only, Windows 10 only
- **Decision:** ✅ **Windows 10 (21H2+) and Windows 11**
- **Rationale:** Covers the broadest practical install base. WASAPI, WebRTC, Python 3.11, ctranslate2, and onnxruntime all function correctly on both. README will include a note to add the project folder to Windows Defender exclusions to prevent false-positive quarantine of native binaries on first run.

#### Decision 1.6 — Minimum Hardware Specification
- **Question:** What is the minimum hardware spec for the target user?
- **Decision:** ✅ **Accepted as specified below**
- **Rationale:** Sets the testing floor. CPU-only int8 on minimum spec yields ~1–2s STT latency per utterance — functional but slower than GPU path. Documented in README.

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | Intel i5 / AMD Ryzen 5 (8th gen+), 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| GPU | None required (CPU fallback) | NVIDIA GPU with 4 GB VRAM (CUDA 12.x) |
| Storage | 5 GB free (models + env) | 10 GB SSD |
| Network | Broadband (LiveKit Cloud + OpenAI API) | Low-latency broadband |

---

### Branch 2 — Project Structure and Build

#### Decision 2.1 — Monorepo vs Polyrepo
- **Question:** Should the agent service and client live in one repo or separate repos?
- **Options considered:** Monorepo, polyrepo
- **Decision:** ✅ **Monorepo**
- **Rationale:** Single `uv` lockfile, one CI pipeline, and no cross-repo version-pinning friction. The v1 client is minimal HTML/JS with no npm build step, so placing it in `voice-agent/client/` inside the same repo carries zero downside.

#### Decision 2.2 — Package Layout
- **Question:** How should Python source code be organized on disk?
- **Options considered:** `src/` layout, flat layout, design doc folder structure (flat)
- **Decision:** ✅ **`src/` layout**
- **Rationale:** PyPA best practice. Keeps source separate from project root, prevents accidental imports of uninstalled packages, and works cleanly with `uv` + `pyproject.toml`. Architecture doc module boundaries (`agent/`, `audio/`, `stt/`, `llm/`, `tts/`, `transport/`, `memory/`, `metrics/`) are nested inside `src/voice_agent/`.

#### Decision 2.3 — Entry Point
- **Question:** Single `main.py` or a CLI with subcommands?
- **Options considered:** Single `main.py`, CLI with subcommands (argparse)
- **Decision:** ✅ **CLI with subcommands via `argparse`**
- **Rationale:** Subcommands (`start`, `benchmark`, `check`) map naturally to the implementation order in the design doc. No extra dependency — uses stdlib `argparse`. A convenience `main.py` at the repo root delegates to `python -m voice_agent start`.

#### Decision 2.4 — Config Format and Secrets Management
- **Question:** What format for config, and how are secrets handled?
- **Options considered:** YAML split dev/prod, YAML single file, TOML, `.env` only
- **Decision:** ✅ **YAML split into `config/dev.yaml` + `config/prod.yaml`; secrets via dotenv (dev) / env vars (prod)**
- **Rationale:** YAML is more readable than TOML for deeply nested config (model paths, VAD thresholds, chunker settings). Split files prevent dev values leaking into prod. API keys and secrets are never stored in YAML — loaded from `.env` in dev via `python-dotenv`, real environment variables in prod. Config validated at startup with `pydantic` `BaseSettings` so misconfiguration fails fast with a clear error message.

#### Decision 2.5 — Secrets Protection
- **Question:** How are `.env` files and API keys protected from accidental exposure?
- **Options considered:** .env in .gitignore + .env.example, vault, cloud secrets manager
- **Decision:** ✅ **.env in `.gitignore`; `.env.example` committed with placeholder values**
- **Rationale:** Prevents accidental `git commit` of secrets. `.env.example` documents all required keys (`OPENAI_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`) with dummy values so new contributors know exactly what to populate. Pydantic `BaseSettings` raises a clear `ValidationError` at startup if any required key is missing. Vault / cloud secrets deferred to post-v1.

---

### Branch 3 — Transport Layer — LiveKit

#### Decision 3.1 — LiveKit Hosting
- **Question:** Self-hosted LiveKit server or LiveKit Cloud?
- **Options considered:** LiveKit Cloud, self-hosted
- **Decision:** ✅ **LiveKit Cloud for v1**
- **Rationale:** Zero ops burden — no server to provision, TLS/TURN handled automatically, free tier covers dev and demos. The transport adapter pattern means switching to a self-hosted URL is a one-line config change if needed post-v1.

#### Decision 3.2 — Room Topology
- **Question:** One room per conversation or room pooling?
- **Options considered:** One room per conversation, room pooling
- **Decision:** ✅ **One room per conversation**
- **Rationale:** Simple lifecycle — room created at session start (UUID name), destroyed/expired at session end. ~100–200ms room creation overhead is negligible against total conversation latency. Room pooling adds state-reset complexity with no meaningful v1 benefit.

#### Decision 3.3 — Audio Codec and Sample Rate
- **Question:** Which audio codec and sample rate over the WebRTC transport?
- **Options considered:** Opus 48kHz, Opus 16kHz, PCM passthrough
- **Decision:** ✅ **Opus at 48kHz**
- **Rationale:** LiveKit and WebRTC default — no custom codec configuration required. Browser sends 48kHz Opus; Python agent decodes and resamples to 16kHz at the transport boundary before feeding faster-whisper. Standard LiveKit Agents pattern.

#### Decision 3.4 — Client SDK
- **Question:** Which SDK does the browser client use to connect to LiveKit?
- **Options considered:** LiveKit JS SDK (browser), LiveKit Python SDK (desktop), both
- **Decision:** ✅ **LiveKit JS SDK in the browser, loaded via CDN**
- **Rationale:** No npm/webpack build step needed for v1's minimal HTML/JS client. Browser handles mic/speaker natively via WebRTC. CDN load (`unpkg` or `jsdelivr`) keeps the client to a single HTML file with no build toolchain.

#### Decision 3.5 — Session Lifecycle and Token Generation
- **Question:** Who creates the LiveKit room and how does the browser get a token?
- **Options considered:** Agent creates room + issues token via `/token` endpoint, client creates room (rejected — exposes secret), pre-created rooms
- **Decision:** ✅ **Agent creates room and issues token via `GET /token` HTTP endpoint**
- **Rationale:** Agent has full control over room lifecycle. Browser makes one HTTP call to `/token`; agent creates the room, mints a short-lived participant JWT (TTL: 1 hour) server-side, returns only the token. `LIVEKIT_API_SECRET` is never exposed to the browser. Endpoint served by a lightweight `aiohttp` or `fastapi` server co-located with the agent process.

#### Decision 3.6 — Reconnection Strategy
- **Question:** What happens when the LiveKit connection drops?
- **Options considered:** Exponential backoff (max 5 retries), infinite retry, fail immediately, session resume
- **Decision:** ✅ **Exponential backoff with jitter, max 5 retries, then give up**
- **Rationale:** Backoff schedule: 1s → 2s → 4s → 8s → 16s (capped at 30s), with jitter to avoid thundering herd. On final failure, transitions to `DEGRADED` state. No mid-conversation session resume for v1 — conversation memory is in-memory so state cannot be fully restored; user starts a fresh session.

---

### Branch 4 — Orchestration Layer — Pipecat

#### Decision 4.1 — Pipecat Transport
- **Question:** Which Pipecat transport — LiveKit transport or raw WebSocket?
- **Options considered:** Pipecat `LiveKitTransport`, raw WebSocket, Daily transport
- **Decision:** ✅ **Pipecat `LiveKitTransport`**
- **Rationale:** Purpose-built integration path for this stack. Handles LiveKit ↔ Pipecat frame translation, audio callbacks, participant events, and data channel publishing out of the box. No custom glue code required.

#### Decision 4.2 — Pipeline Topology
- **Question:** Linear chain or branching DAG?
- **Options considered:** Linear chain, branching DAG
- **Decision:** ✅ **Linear chain**
- **Rationale:** All v1 functionality fits a linear chain. The apparent barge-in branching need is handled as a side effect within the VAD stage emitting an interrupt event to the state machine — main pipeline frame flow stays linear, simple to debug and test.

#### Decision 4.3 — Frame Types
- **Question:** Use Pipecat built-in frames only, or extend with custom frames for metrics and events?
- **Options considered:** Built-in frames only, extend with custom frames
- **Decision:** ✅ **Extend with custom frames**
- **Rationale:** Custom `MetricFrame` (latency timestamps), `StateChangeFrame` (state machine transitions), and `InterruptFrame` (barge-in signal) are lightweight Python dataclasses with zero performance cost. Keeps metrics and state events first-class in the pipeline — easy to log, trace, and unit test by inspecting the frame stream.

#### Decision 4.4 — Error Propagation Strategy
- **Question:** Per-stage try/catch, pipeline-level error handler, or circuit breaker?
- **Options considered:** Per-stage try/catch only, pipeline-level handler + per-stage fallback hooks, circuit breaker
- **Decision:** ✅ **Pipeline-level error handler with per-stage fallback hooks**
- **Rationale:** Each stage (STT, LLM, TTS) registers an `on_error` hook that emits a defined fallback frame (retry once, then canned response). A top-level handler catches anything that escapes a stage and transitions the system to `DEGRADED`. Avoids silent error swallowing while keeping fallback behaviour co-located with each stage.

#### Decision 4.5 — Interruption Handling Wiring
- **Question:** How is Pipecat's interruption handling wired with the barge-in controller?
- **Options considered:** Pipecat built-in + custom `BargeInController`, fully custom bypass, Pipecat default with no custom controller
- **Decision:** ✅ **Pipecat built-in interruption events + custom `BargeInController`**
- **Rationale:** Custom `BargeInController` sits between the VAD stage and Pipecat's interruption signal. It applies the 3-frame / 150ms confirmation window before firing a `BotInterruptionFrame` into the pipeline. Pipecat then handles TTS cancellation, buffer flushing, and state transition — no duplication of pipeline mechanics.

---

### Branch 5 — Audio Preprocessing

#### Decision 5.1 — Echo Cancellation
- **Question:** Which AEC approach — OS-level, SpeexDSP, or LiveKit built-in?
- **Options considered:** LiveKit/WebRTC built-in AEC, SpeexDSP, Windows OS-level AEC (WASAPI loopback), py-webrtcvad
- **Decision:** ✅ **LiveKit/WebRTC built-in AEC (browser-side)**
- **Rationale:** Browser WebRTC runs AEC before audio is sent to LiveKit — the agent's own voice is suppressed from the mic feed automatically. Zero integration work, zero Python-side complexity. Only relevant alternatives (SpeexDSP, WASAPI loopback) require a native audio client we don't have in v1.

#### Decision 5.2 — Noise Suppression
- **Question:** RNNoise, Speex NS, or LiveKit's built-in NS?
- **Options considered:** LiveKit/WebRTC built-in NS, RNNoise (Python-side), Speex NS (Python-side)
- **Decision:** ✅ **LiveKit's built-in NS (browser-side)**
- **Rationale:** Already running alongside AEC in the browser before audio reaches LiveKit. Handles common noise cases (background hum, keyboard, fan) with zero additional latency or dependencies. RNNoise deferred to v2 if users report noise bleed-through.

#### Decision 5.3 — AGC (Automatic Gain Control)
- **Question:** Enable or disable AGC for v1?
- **Options considered:** Disable AGC, conservative fixed-gain, adaptive AGC, browser default
- **Decision:** ✅ **Disable AGC for v1**
- **Rationale:** Simpler and more predictable. WebRTC AEC/NS already normalises the signal. Adaptive AGC can introduce volume pumping artifacts that confuse Silero VAD. Browser `getUserMedia` will be called with `{ autoGainControl: false }` to explicitly disable browser-level AGC. No Python-side AGC code required.

#### Decision 5.4 — VAD Frame Size
- **Question:** 10ms, 20ms, or 30ms audio frames for Silero VAD?
- **Options considered:** 10ms, 20ms, 30ms
- **Decision:** ✅ **30ms frames**
- **Rationale:** Silero's recommended frame size. Lowest CPU overhead (33 inferences/sec vs 100 at 10ms). 30ms speech-start detection lag is imperceptible in conversation (human reaction time ~150–200ms). Particularly important for minimum-spec CPU-only hardware defined in Decision 1.6.

#### Decision 5.5 — Resampling Location and Library
- **Question:** Where does 48kHz → 16kHz resampling happen, and with which library?
- **Options considered:** At transport boundary, in VAD stage, in STT stage
- **Decision:** ✅ **At the transport boundary in the `LiveKitTransport` adapter, using `scipy.signal.resample_poly`**
- **Rationale:** Single resampling point — all downstream stages (Silero VAD, faster-whisper STT) receive consistent 16kHz PCM. Silero VAD is trained on 16kHz; feeding it 48kHz frames without resampling degrades accuracy. `scipy` is already in the dependency tree.

#### Decision 5.6 — Pre-Speech Ring Buffer Size
- **Question:** How many seconds of pre-speech audio to retain in the ring buffer?
- **Options considered:** 0.3s, 0.5s, 1.0s, 2.0s
- **Decision:** ✅ **0.5s pre-speech ring buffer**
- **Rationale:** Captures leading phonemes and fast utterance starts reliably without feeding unnecessary preamble noise to STT. Memory cost is negligible: ~32 KB at 16kHz mono int16. Matches design doc recommendation.

---

### Branch 6 — VAD — Silero

#### Decision 6.1 — Silero VAD Version and Model Variant
- **Question:** Which Silero VAD version and runtime?
- **Options considered:** Silero VAD v5 (ONNX), Silero VAD v4 (ONNX), original torch version
- **Decision:** ✅ **Silero VAD v5 via ONNX Runtime**
- **Rationale:** Latest stable release with improved false-positive suppression over v4. Runs via `onnxruntime` — already in the dependency tree. No separate PyTorch install needed just for VAD. Compatible with the 30ms frame size decided in Decision 5.4.

#### Decision 6.2 — Speech Start Threshold
- **Question:** What probability cutoff triggers a speech_start event?
- **Options considered:** 0.3 (very sensitive), 0.5 (balanced/default), 0.7 (conservative), 0.9 (very conservative)
- **Decision:** ✅ **0.5 (Silero's default)**
- **Rationale:** Balanced between false positives and missed starts. Input signal is pre-cleaned by WebRTC NS (Decision 5.2), making 0.5 a well-suited threshold. Exposed as a YAML config value so it can be tuned without a code change.

#### Decision 6.3 — Pause Detection Threshold
- **Question:** Minimum silence duration before firing a speech_pause event?
- **Options considered:** 100ms, 200ms, 300ms, 500ms, 800ms+
- **Decision:** ✅ **300ms**
- **Rationale:** Balanced — catches real pauses while tolerating brief hesitations. Safe to be slightly aggressive here because Smart Turn (Branch 7) is the real end-of-turn gate; a false pause at 300ms just triggers a Smart Turn evaluation that returns "incomplete". Exposed as a YAML config value.

#### Decision 6.4 — Minimum Speech Duration
- **Question:** Minimum consecutive speech duration before firing speech_start downstream?
- **Options considered:** 0ms, 50ms, 100ms, 200ms, 300ms
- **Decision:** ✅ **100ms (~3–4 consecutive 30ms frames)**
- **Rationale:** Filters out virtually all non-speech transients (keyboard clicks, door slams, coughs) while adding only 100ms to speech-start latency. Short enough to capture single-word utterances like "Yes", "No", "Stop" cleanly. Exposed as YAML config.

#### Decision 6.5 — VAD Instance During TTS Playback
- **Question:** Same VAD instance or separate instance for barge-in detection during SPEAKING state?
- **Options considered:** Single instance (always running), separate instance for barge-in
- **Decision:** ✅ **Single VAD instance, always running**
- **Rationale:** Silero v5 via ONNX is lightweight (~5MB, <1ms per 30ms frame). One instance runs continuously on every incoming mic frame regardless of conversation state. The `BargeInController` and state machine determine what to do with VAD output based on current state — no dual-instance coordination needed.

---

### Branch 7 — Turn Detection — Smart Turn

#### Decision 7.1 — Smart Turn Integration
- **Question:** Pipecat's built-in Smart Turn or standalone custom implementation?
- **Options considered:** Pipecat built-in `SmartTurnAnalyzer`, standalone custom classifier, silence-only turn detection
- **Decision:** ✅ **Pipecat's built-in Smart Turn**
- **Rationale:** Native integration — directly consumes pause events and partial transcripts already flowing through the Pipecat pipeline. Maintained by the Pipecat team and designed to plug into `LiveKitTransport`. Silence-only detection explicitly rejected as too brittle for natural conversation.

#### Decision 7.2 — Smart Turn Context
- **Question:** What input does Smart Turn receive to make its end-of-turn decision?
- **Options considered:** Last N seconds of audio only, partial transcript only, both audio + transcript, nothing (timer only)
- **Decision:** ✅ **Both: last audio window (3s, configurable) + partial transcript**
- **Rationale:** Richest signal — acoustic prosody (trailing intonation, pitch drop) combined with semantic completeness detection. Intended usage pattern in Pipecat's Smart Turn design. Audio window size exposed as YAML config.

#### Decision 7.3 — Smart Turn Hard Timeout
- **Question:** How long before Smart Turn is considered stuck and we force a transition?
- **Options considered:** 1–2s (too aggressive), 3s, 5s (design doc), 10s (too long)
- **Decision:** ✅ **3s hard timeout, then force transition to PROCESSING**
- **Rationale:** 5s (design doc recommendation) was overridden — a 300ms VAD pause + 5s timeout = 5.3s of silence, which breaks conversational feel. 3s is generous enough for Smart Turn inference on CPU-only hardware while keeping the conversation natural. On timeout, treat as "complete" and proceed to PROCESSING rather than discarding the utterance.

#### Decision 7.4 — Smart Turn Uncertainty Bias
- **Question:** When uncertain, should Smart Turn err toward "complete" or "incomplete"?
- **Options considered:** Err toward "incomplete" (keep listening), err toward "complete" (respond quickly)
- **Decision:** ✅ **Err toward "incomplete"**
- **Rationale:** Being cut off mid-sentence is significantly more annoying to users than a brief extra wait. Conservative default for v1 — feels polite and unhurried. Sensitivity can be tuned tighter once real conversation patterns are observed.

#### Decision 7.5 — Smart Turn ↔ State Machine Wiring
- **Question:** Does Smart Turn directly drive state transitions, or emit events the state machine consumes?
- **Options considered:** Smart Turn emits events → state machine handles transitions; Smart Turn directly calls state machine methods
- **Decision:** ✅ **Event-driven: Smart Turn emits `TurnCompleteFrame` / `TurnIncompleteFrame` into the pipeline**
- **Rationale:** Clean separation of concerns — Smart Turn knows nothing about states, state machine knows nothing about turn detection internals. Uses the custom frame types established in Decision 4.3. Easily testable by injecting frames in unit tests. Loosely coupled — Smart Turn implementation can be swapped without touching the state machine.

---

### Branch 8 — STT — faster-whisper / Distil-Whisper

#### Decision 8.1 — STT Model Size
- **Question:** Which Distil-Whisper / faster-whisper model variant?
- **Options considered:** tiny/base, small, distil-large-v3, large-v3
- **Decision:** ✅ **`distil-large-v3`**
- **Rationale:** Best production accuracy/speed trade-off — retains ~98% of large-v3 accuracy at ~6× the inference speed. GPU: ~3 GB VRAM; CPU int8: ~2 GB RAM, ~1–2s/utterance. Model variant exposed as YAML config for easy fallback to `small` if CPU latency is unacceptable on minimum-spec hardware.

#### Decision 8.2 — STT Compute Type
- **Question:** float16, int8, or int8_float16?
- **Options considered:** float32, float16, int8_float16, int8
- **Decision:** ✅ **Auto-selected at startup: `int8_float16` on GPU, `int8` on CPU**
- **Rationale:** `int8_float16` gives best GPU throughput with negligible accuracy loss over float16. `int8` is the only practical choice for CPU — dramatically faster than float32. Auto-selection reuses the CUDA detection logic from Decision 1.4. Both values overridable via YAML config.

#### Decision 8.3 — Beam Size
- **Question:** Beam size 1 (greedy) or 5 for streaming inference?
- **Options considered:** 1 (greedy), 5
- **Decision:** ✅ **Beam size 1 (greedy decoding)**
- **Rationale:** Only practical choice for real-time streaming — beam=5 is ~3–5× slower with negligible accuracy improvement for conversational English. Inference runs every 500ms of buffered speech; beam=1 keeps this within latency budget. Exposed as YAML config for experimentation.

#### Decision 8.4 — Language Model Variant
- **Question:** English-only model or multilingual?
- **Options considered:** English-only distil-large-v3, multilingual distil-large-v3
- **Decision:** ✅ **English-only for v1**
- **Rationale:** Better English WER, smaller footprint, faster inference than the multilingual variant. Hindi-English code-switching deferred to v2. Model path is a single YAML config value — upgrading to multilingual requires no code change.

#### Decision 8.5 — STT Streaming Strategy
- **Question:** How often to run inference on buffered speech?
- **Options considered:** Every frame (30ms), every 250ms, every 500ms, on pause only, hybrid 500ms + final on pause
- **Decision:** ✅ **Every 500ms of new audio**
- **Rationale:** Balanced CPU load (2 inferences/sec during active speech) while providing responsive partial transcript updates to the UI. Simpler than the hybrid approach — a single consistent inference cadence. Interval exposed as YAML config.

#### Decision 8.6 — Partial Transcript Emission
- **Question:** When are partial transcripts emitted downstream?
- **Options considered:** Every inference cycle, every word boundary, every N ms (timer-based)
- **Decision:** ✅ **Every inference cycle (every 500ms)**
- **Rationale:** Simple and consistent — whatever faster-whisper returns at the 500ms mark is immediately emitted as a `TranscriptionFrame` into the pipeline. UI gets live updates; Smart Turn always has fresh text context. No additional buffering or word-boundary detection logic needed.

#### Decision 8.7 — STT Warm-Up Strategy
- **Question:** How to eliminate cold-start latency on the first utterance?
- **Options considered:** Pre-load + dummy inference, pre-load only, lazy load
- **Decision:** ✅ **Pre-load model + run dummy inference on startup**
- **Rationale:** Runs a silent 1-second audio segment (zeros at 16kHz) through the full inference path at startup to compile CUDA kernels and warm the model cache. `INITIALIZING → READY` transition fires only after warm-up completes. Users see a "warming up..." indicator rather than an unexpected multi-second delay on their first word.

---

### Branch 9 — LLM — OpenAI Nano

#### Decision 9.1 — LLM Model Identifier
- **Question:** Which specific OpenAI model to use?
- **Options considered:** `gpt-4.1-nano`, `gpt-4o-mini`, `gpt-4o`
- **Decision:** ✅ **`gpt-4.1-nano`**
- **Rationale:** Current best fit for the fast, cheap, conversational use case — ultra-low-latency streaming, low cost, strong conversational quality. Model identifier exposed as YAML config for easy switching without code changes.

#### Decision 9.2 — LLM Streaming Transport
- **Question:** SSE streaming via OpenAI Python SDK, or raw HTTP?
- **Options considered:** `AsyncOpenAI` SDK with SSE streaming, raw HTTP with `httpx`, WebSocket
- **Decision:** ✅ **`AsyncOpenAI` SDK with SSE streaming**
- **Rationale:** Official, maintained, async-native. Integrates cleanly with `asyncio` and Pipecat's async pipeline. Each streaming token yielded as a `TextFrame` into the pipeline immediately, enabling the chunker to start TTS as early as possible.

#### Decision 9.3 — System Prompt Strategy
- **Question:** Static system prompt or dynamic with conversation context injection?
- **Options considered:** Static only, dynamic with last N turns, dynamic with full session history
- **Decision:** ✅ **Dynamic system prompt — static base persona + last 10 turns as message pairs**
- **Rationale:** Static base prompt defines agent persona, response style (concise, spoken-word-friendly, no markdown/bullet points/code blocks), and behaviour rules. Last 10 turns of history appended as `user`/`assistant` message pairs per call. Assembled by the `memory/` context builder module. N=10 is configurable via YAML.

#### Decision 9.4 — Context Window Management
- **Question:** Sliding window, summarization, hard truncation, or keep full history?
- **Options considered:** Sliding window, summarization, hard truncation, keep full history
- **Decision:** ✅ **Sliding window**
- **Rationale:** Drop oldest turns when estimated token count exceeds 80% of `gpt-4.1-nano`'s context window. Token count estimated with `tiktoken`. Simple, predictable, no extra LLM calls. Summarization deferred to v2. Threshold exposed as YAML config.

#### Decision 9.5 — Max Tokens Per Response
- **Question:** What is the `max_tokens` cap for LLM responses?
- **Options considered:** 100, 300, 500, unlimited
- **Decision:** ✅ **`max_tokens=300`**
- **Rationale:** ~225 words — generous enough for complex conversational answers without enabling essay-length monologues. TTS latency grows with response length; capping at 300 keeps time-to-first-audio bounded. System prompt also instructs the model to be concise. Exposed as YAML config.

#### Decision 9.6 — Temperature and Top-P
- **Question:** What sampling parameters control conversational style?
- **Options considered:** temperature 0.0 (deterministic), 0.5 (flat), 0.7/top_p 0.9 (balanced), 1.0+ (creative/risky)
- **Decision:** ✅ **`temperature=0.7`, `top_p=0.9`**
- **Rationale:** Standard conversational sweet spot — natural phrasing variation without off-topic drift or hallucination. `top_p=0.9` (nucleus sampling) prevents very unlikely tokens from appearing even at temperature 0.7. Both exposed as YAML config.

#### Decision 9.7 — LLM Barge-In Cancellation
- **Question:** How to abort an in-flight streaming LLM request on barge-in?
- **Options considered:** Close HTTP stream via `asyncio.Task.cancel()`, SDK cancel method, let it finish silently, drain and discard
- **Decision:** ✅ **Close the HTTP stream via `asyncio.Task.cancel()`**
- **Rationale:** LLM streaming call wrapped in an `asyncio.Task`. On barge-in, `task.cancel()` raises `CancelledError` inside the coroutine, which is caught and triggers the `INTERRUPTED` state transition. Immediate, clean, idiomatic asyncio — no wasted API tokens or cost.

#### Decision 9.8 — LLM Retry and Fallback
- **Question:** What happens on 429 rate limit or 500 server error?
- **Options considered:** Retry once + canned fallback, multiple retries, fail immediately, fall back to different model
- **Decision:** ✅ **Retry once after 1s backoff, then speak canned fallback response**
- **Rationale:** Single retry costs only 1s — worth attempting before giving up. On second failure, emit canned fallback text ("Sorry, I'm having a bit of trouble right now — could you say that again?") as a `TextFrame` directly to TTS, bypassing the chunker. Transitions `DEGRADED → READY` after fallback plays. Fallback text configurable in YAML.

---

### Branch 10 — TTS — Piper

#### Decision 10.1 — Piper Voice Model
- **Question:** Which Piper voice model and speaker?
- **Options considered:** `en_US-lessac-medium`, `en_US-lessac-high`, `en_US-ryan-medium`, `en_US-amy-low`
- **Decision:** ✅ **`en_US-lessac-medium`**
- **Rationale:** Best production balance of naturalness and synthesis speed (~60 MB). Most widely used Piper voice in production systems; well-tested on Windows. Voice model path exposed as YAML config for easy swapping.

#### Decision 10.2 — Piper Integration Method
- **Question:** Subprocess call, shared library, or Python binding?
- **Options considered:** `piper-tts` Python binding, subprocess call, shared library (ctypes)
- **Decision:** ✅ **`piper-tts` Python binding**
- **Rationale:** In-process synthesis via `onnxruntime` (already in dependency tree) — no subprocess spawning, no IPC overhead. Lowest latency path. Cancellable by abandoning the synthesis loop. Cleanest async integration with Pipecat pipeline.

#### Decision 10.3 — TTS Audio Output Format
- **Question:** Raw PCM, WAV chunks, or Opus encode before transport?
- **Options considered:** Raw PCM → Opus at transport boundary, WAV chunks, pre-encode to Opus in TTS adapter
- **Decision:** ✅ **Raw PCM internally, Opus encode at the LiveKit transport boundary**
- **Rationale:** Symmetric with the input path (Decision 5.5). All internal pipeline stages work with simple raw PCM — no codec parsing anywhere except the two transport boundaries. Codec responsibility co-located in the transport adapter.

#### Decision 10.4 — TTS Barge-In Cancellation
- **Question:** How to stop Piper mid-synthesis on barge-in?
- **Options considered:** Abandon synthesis iterator + flush buffer, kill subprocess (N/A), let current chunk finish, thread interrupt (unsafe)
- **Decision:** ✅ **Abandon synthesis iterator + flush LiveKit playback buffer**
- **Rationale:** `piper-tts` synthesises via an iterator — stopping consumption of the iterator is clean, safe, and immediate. No subprocess or thread concerns. On `BotInterruptionFrame`, stop iterating and signal LiveKit transport to flush its playback buffer. Python GC handles unused audio data with no ONNX runtime state corruption.

#### Decision 10.5 — TTS Synthesis Start Timing
- **Question:** Wait for full LLM response, or start synthesis on first complete phrase?
- **Options considered:** Start on first complete phrase from chunker, wait for full response, start on first N tokens
- **Decision:** ✅ **Start synthesis on first complete phrase emitted by the chunker**
- **Rationale:** Core latency win of the streaming cascade architecture. Chunker buffers tokens until a sentence/clause boundary, ensuring Piper always receives grammatically complete input. LLM continues streaming into the chunker while Piper is already speaking the first phrase — user hears audio as early as possible.

#### Decision 10.6 — Piper Phoneme Cache
- **Question:** Enable or disable phoneme cache?
- **Options considered:** Enable, disable
- **Decision:** ✅ **Enable phoneme cache**
- **Rationale:** Free latency win — common conversational words ("I", "you", "okay", "right", "that's") repeat constantly and benefit immediately from cached phonemisation. In-memory cache with negligible memory cost (~few MB). No complexity cost.

---

### Branch 11 — Text Chunking (LLM → TTS Bridge)

#### Decision 11.1 — Chunking Strategy
- **Question:** Sentence boundaries only, or also clause/phrase boundaries?
- **Options considered:** Sentence + clause boundaries, sentence only, fixed token count, word boundary only
- **Decision:** ✅ **Sentence + clause boundaries**
- **Rationale:** Split on `.?!;:` always; split on `,` when accumulated buffer exceeds 80 characters. Lower time-to-first-audio than sentence-only (first chunk ready after first clause, not full sentence). 80-char comma threshold prevents splitting short phrases like "Hello, how are you?". Both thresholds exposed as YAML config.

#### Decision 11.2 — Minimum Chunk Size
- **Question:** Minimum characters before sending a chunk to Piper?
- **Options considered:** 0, 10, 20, 50
- **Decision:** ✅ **20 characters**
- **Rationale:** Filters single-word and very short acknowledgement fragments ("I see.", "Sure.") that cause choppy TTS rhythm. Long enough to avoid per-synthesis overhead on tiny inputs; short enough to not delay real responses. Exposed as YAML config.

#### Decision 11.3 — Maximum Buffer Size Before Forced Flush
- **Question:** Maximum characters before forcing a chunk flush without a clean boundary?
- **Options considered:** 100, 200, 500, no max
- **Decision:** ✅ **200 characters**
- **Rationale:** Safety valve for run-on LLM output with no punctuation. Covers ~2–3 normal sentences; rarely triggered in practice when `gpt-4.1-nano` is instructed to be concise. Prevents indefinite buffering on malformed output. Exposed as YAML config.

#### Decision 11.4 — Sentence Boundary Detection Method
- **Question:** Regex, spaCy, or NLTK for sentence boundary detection?
- **Options considered:** Simple punctuation regex, spaCy, NLTK
- **Decision:** ✅ **Simple punctuation regex (stdlib `re`)**
- **Rationale:** `gpt-4.1-nano` output is well-structured and uses standard punctuation reliably. Regex splitting on `.?!;:` with edge-case guards (abbreviations like `Mr.`, `Dr.`, decimal numbers) handles 99% of real cases. Zero dependencies, <0.1ms per call. spaCy deferred as a config-switchable backend if edge cases arise in practice.

#### Decision 11.5 — Markdown and LLM Artifact Handling
- **Question:** Strip markdown/code blocks, speak verbatim, or request regeneration?
- **Options considered:** Strip markdown + skip code blocks, speak verbatim, fail and regenerate
- **Decision:** ✅ **Strip markdown, skip/replace code blocks**
- **Rationale:** System prompt already instructs model to avoid markdown; chunker stripping is a safety net. Markdown tokens (`**`, `*`, `#`, `-`) removed via regex before Piper receives text. Code blocks replaced with spoken phrase "I'd share some code, but this is a voice conversation." Bullet lists converted to "first... second... third..." natural spoken form. All stripping logic toggleable via YAML config.

---

### Branch 12 — Barge-In Controller

#### Decision 12.1 — Consecutive VAD Frames to Confirm Barge-In
- **Question:** How many consecutive VAD-positive frames required to confirm a real interruption?
- **Options considered:** 1 (30ms), 3 (90ms), 5 (150ms), 8 (240ms)
- **Decision:** ✅ **3 consecutive frames (90ms)**
- **Rationale:** Filters transient noise (coughs, clicks, room spikes) while responding to real speech within ~100ms. Standard threshold used in production voice systems. Fast enough to feel instantaneous; robust enough to avoid false triggers. Exposed as YAML config.

#### Decision 12.2 — Minimum Speech Duration Before Acting on Barge-In
- **Question:** Minimum total speech duration before cancelling TTS and LLM on barge-in?
- **Options considered:** 0ms, 150ms, 300ms, 500ms
- **Decision:** ✅ **150ms**
- **Rationale:** Excludes brief vocalizations ("mm", "uh", typically <100ms) while requiring a sustained intentional utterance. Total detection window from first speech frame to action: 3-frame confirmation (90ms) + 150ms = ~240ms — imperceptible as a delay to the user. Exposed as YAML config.

#### Decision 12.3 — Interrupted TTS Context Handling
- **Question:** Discard interrupted TTS remainder, preserve for resumption, or partial discard?
- **Options considered:** Discard entirely, preserve for resumption, partial discard (keep last sentence)
- **Decision:** ✅ **Discard entirely**
- **Rationale:** Conversationally correct — when a user interrupts, they want a response to their new input, not a continuation of the old one. Abandon Piper iterator, flush audio queue, emit `InterruptFrame` downstream. LLM generates a fresh response to the new user utterance. Preserving context would cause the agent to ignore the barge-in content, which defeats the purpose of interruption.

#### Decision 12.4 — In-Flight LLM Token Handling on Barge-In
- **Question:** What happens to buffered LLM tokens not yet sent to TTS when barge-in fires?
- **Options considered:** Cancel task + discard buffer, cancel + flush buffer to TTS, drain stream then cancel, retry with barge-in content prepended
- **Decision:** ✅ **Cancel `asyncio.Task` + discard all buffered tokens**
- **Rationale:** Only option consistent with a clean, instantaneous-feeling interruption. Flushing buffered tokens would cause the agent to keep speaking briefly after interruption. New LLM call starts only after barge-in utterance is complete and STT produces a transcript. Consistent with Decision 9.6 (asyncio.Task cancellation) and Decision 12.3 (discard TTS context).

#### Decision 12.5 — Barge-In Cooldown Period
- **Question:** How long after an interruption before another barge-in can trigger?
- **Options considered:** 0ms, 500ms, 1000ms, 2000ms
- **Decision:** ✅ **500ms**
- **Rationale:** Allows audio pipeline to flush, echo/feedback from the interruption to decay, and state machine to transition cleanly. Short enough that the user doesn't feel locked out; long enough to prevent cascade interruptions or echo re-triggering. Exposed as YAML config.

#### Decision 12.6 — States Where Barge-In Is Active
- **Question:** Which conversation states should the barge-in controller be armed in?
- **Options considered:** SPEAKING only, SPEAKING + PROCESSING, all non-LISTENING states, all states
- **Decision:** ✅ **SPEAKING only**
- **Rationale:** Barge-in is an audio interruption mechanism — only meaningful when agent is actively outputting audio. PROCESSING interruption is handled by Smart Turn / turn timeout, not the barge-in controller. Controller armed on entry to SPEAKING, disarmed on exit. Active state list exposed as YAML config for flexibility.

---

### Branch 13 — Conversation State Machine

#### Decision 13.1 — Full State Set
- **Question:** Accept design doc's 11-state machine or modify it?
- **Options considered:** Accept all 11, drop THINKING_PAUSE, drop INTERRUPT_CANDIDATE, merge INTERRUPTED+PROCESSING, add states
- **Decision:** ✅ **All 11 states as defined** — `INITIALIZING → READY → LISTENING → USER_SPEAKING → THINKING_PAUSE → PROCESSING → SPEAKING → INTERRUPT_CANDIDATE → INTERRUPTED → DEGRADED → SHUTDOWN`
- **Rationale:** Each state has a distinct role. THINKING_PAUSE gives Smart Turn a clean hook between VAD silence and LLM dispatch. INTERRUPT_CANDIDATE covers the 3-frame barge-in confirmation window without race conditions. Implemented as a Python `Enum`.

#### Decision 13.2 — Allowed State Transitions Policy
- **Question:** Strict whitelist (exception on invalid), permissive (warn + allow), or silent no-op?
- **Options considered:** Strict whitelist raising exception, permissive with warning, strict whitelist silent no-op
- **Decision:** ✅ **Strict whitelist — invalid transitions raise `InvalidTransitionError`**
- **Rationale:** Makes the state machine self-documenting and turns logic bugs into immediate traceable errors rather than silent state corruption. In production, `InvalidTransitionError` is caught at the pipeline level and triggers a `DEGRADED` state gracefully. Transition table defined as `dict[ConversationState, set[ConversationState]]`.

#### Decision 13.3 — State Persistence
- **Question:** In-memory only, persist to disk, or persist to Redis?
- **Options considered:** In-memory only, persist to disk (file/SQLite), persist to Redis
- **Decision:** ✅ **In-memory only — reset to `INITIALIZING` on restart**
- **Rationale:** Voice agent state is tightly coupled to live resources (WebRTC connection, audio buffers, LLM SSE stream) that don't survive a process restart. Restoring a persisted state like `SPEAKING` with no active audio stream would be nonsensical. Correct restart behaviour is always a clean session. Conversation turn history (Branch 14) is a separate concern.

#### Decision 13.4 — State Change Event Emission
- **Question:** How do other components learn about state transitions?
- **Options considered:** `StateChangeFrame` through Pipecat pipeline, asyncio Event/Queue per subscriber, callback registry, polling
- **Decision:** ✅ **Emit `StateChangeFrame` through the Pipecat pipeline on every transition**
- **Rationale:** Consistent with the frame-based architecture (Decision 4.3). Zero additional infrastructure — all downstream pipeline stages receive an ordered, consistent view of state changes. Frame carries `previous_state`, `new_state`, and `timestamp`. No subscriber management or coupling between state machine and consumers.

#### Decision 13.5 — PROCESSING State Watchdog Timeout
- **Question:** How long before a stuck PROCESSING state is force-transitioned to DEGRADED?
- **Options considered:** 5s, 10s, 30s, no timeout
- **Decision:** ✅ **10 seconds**
- **Rationale:** `gpt-4.1-nano` first-token latency typically <1s; full response rarely exceeds 3–4s for `max_tokens=300`. 10s is 3–4× the expected worst case — a genuine fault detector, not a trigger for normal slow responses. On timeout: force transition to `DEGRADED`, emit canned fallback audio, attempt recovery to `READY`. Exposed as YAML config.

#### Decision 13.6 — DEGRADED State Recovery
- **Question:** Automatic retry to READY, exponential backoff, manual restart, or SHUTDOWN?
- **Options considered:** Automatic single retry after 2s, exponential backoff, require manual restart, transition to SHUTDOWN
- **Decision:** ✅ **Automatic single retry to `READY` after 2s; if recovery fails, transition to `SHUTDOWN`**
- **Rationale:** One automatic recovery attempt covers transient hiccups without building a full retry loop for v1. Best UX — agent recovers silently with a canned phrase and conversation continues. Fatal errors (missing API key, etc.) skip retry and go directly to `SHUTDOWN`. Retry delay exposed as YAML config.

---

### Branch 14 — Conversation Memory

#### Decision 14.1 — Memory Scope
- **Question:** Session-only memory, or persist across sessions?
- **Options considered:** Session-only, persist to SQLite/file, persist with user profiles
- **Decision:** ✅ **Session-only — memory cleared on session end**
- **Rationale:** Persistent memory requires an identity model, privacy design, and schema decisions that are out of scope for v1. Session-only keeps architecture clean with zero privacy surface. No disk writes for conversation history. Persistence deferred to v2 with a proper identity layer.

#### Decision 14.2 — Turn History Format
- **Question:** OpenAI message list, custom dataclass, plain string transcript, or JSON blob?
- **Options considered:** Native OpenAI message list, custom `Turn` dataclass, plain string transcript, JSON blob per turn
- **Decision:** ✅ **Native OpenAI message list — `list[dict]` with `role` and `content` keys**
- **Rationale:** Zero conversion at LLM call time — memory IS the message list. LLM call is simply `messages = [system_prompt] + memory.turns[-10:]`. Consistent with Decision 9.2 (last 10 turns as dynamic prompt). Timestamps and token counts tracked separately in metrics if needed.

#### Decision 14.3 — Active Context Window Size and Overflow Handling
- **Question:** How many turns in the sliding window, and what happens to overflow?
- **Options considered:** 5/10/20/unlimited turns; discard overflow vs. summarise into prefix
- **Decision:** ✅ **10-turn sliding window, discard overflow silently**
- **Rationale:** Consistent with Decision 9.2. Covers most natural conversation flows (~1,000–1,500 tokens). Silent discard is simple and correct for v1 — agent doesn't recall events beyond 10 turns ago. Summarisation adds a full LLM call per overflow event; deferred to v2.

#### Decision 14.4 — Turn Append Policy
- **Question:** When are user and agent turns appended to memory?
- **Options considered:** Append on TranscriptionFrame + TurnCompleteFrame, delay user turn, append agent tokens streaming, batch at session end
- **Decision:** ✅ **Append user turn on `TranscriptionFrame`; append agent turn on `TurnCompleteFrame` only**
- **Rationale:** Clean boundary — both turns fully committed before next exchange begins. User utterance safely in memory even if agent crashes mid-response. Interrupted agent turns (barge-in) are NOT appended — only fully delivered turns enter context, preventing the LLM from seeing its own half-finished responses.

#### Decision 14.5 — Token Counting Method
- **Question:** tiktoken per-turn counting with hard budget, turn count only, character estimate, or react to API errors?
- **Options considered:** tiktoken per turn with hard budget, turn count only (N=10), character estimate, no tracking
- **Decision:** ✅ **`tiktoken` token counting per turn; enforce hard budget**
- **Rationale:** `tiktoken` already a dependency (Decision 9.3) — zero additional cost. Store `token_count` at append time. Trim oldest turns when `sum(token_counts) > budget`. Budget = `max_context_tokens - max_tokens - system_prompt_tokens`, all YAML-configurable. Prevents context overflow proactively rather than reacting to API errors. More precise than turn counting alone when turn lengths vary significantly.

---

### Branch 15 — UI and Client

#### Decision 15.1 — Client Type
- **Question:** Browser-based HTML/JS, Electron, Python CLI, or native Windows app?
- **Options considered:** Browser HTML/JS single page, Electron desktop, Python CLI, native Windows app
- **Decision:** ✅ **Browser-based single HTML page — `client/index.html` + `client/app.js`**
- **Rationale:** Consistent with Decision 3.4 (LiveKit JS SDK via CDN). No install, no build step, no additional toolchain. Served as static files by the agent's startup HTTP server. Runs in any Windows browser.

#### Decision 15.2 — Transcript Display
- **Question:** Live rolling transcript, audio-only, agent-only, or word-level highlighted transcript?
- **Options considered:** Live rolling transcript (both turns), audio only, agent turn only, word-level timestamps
- **Decision:** ✅ **Live rolling transcript for both user and agent turns**
- **Rationale:** Transcript data already flows through the pipeline (`TranscriptionFrame` for user, `TurnCompleteFrame` for agent). Sent to browser via LiveKit data channel as JSON events at negligible cost. Aids comprehension, lets user verify their utterance was understood correctly, and assists debugging. Displayed in a scrolling panel.

#### Decision 15.3 — State and Metrics Display
- **Question:** Show conversation state + latency metrics, state only, metrics only, or neither?
- **Options considered:** State + key latency metrics, state only, metrics only, transcript only
- **Decision:** ✅ **Show current conversation state + key latency metrics**
- **Rationale:** `StateChangeFrame` and `MetricFrame` already flow through the pipeline (Decisions 4.3, 13.4). Same LiveKit data channel as transcript — zero additional infrastructure. Rendered as a compact status bar showing current state badge and last STT latency, LLM time-to-first-token, and TTS time-to-first-audio. Updated on each frame event.

#### Decision 15.4 — Audio Device Selection
- **Question:** Browser default devices, mic dropdown, mic + speaker dropdowns, or OS-level control?
- **Options considered:** Browser default (no selector), mic dropdown, mic + speaker dropdowns, system tray
- **Decision:** ✅ **Browser default audio devices — no device selector UI in v1**
- **Rationale:** Windows users set preferred mic/headset in OS Sound Settings — `getUserMedia()` with no `deviceId` constraint picks it up automatically. Zero UI complexity. Device selector deferred to v2 if user feedback demands it. README instructs users to set preferred device in Windows Sound Settings.

#### Decision 15.5 — Visual Design and UI Framework
- **Question:** Minimal plain HTML, CSS framework, React+Vite build toolchain, or React via CDN?
- **Options considered:** Plain HTML minimal UI, Tailwind CDN, React + Vite build toolchain, React via CDN + Babel Standalone
- **Decision:** ✅ **React via CDN + Babel Standalone — no build step**
- **Rationale:** Consistent with Decision 15.1 (no build step, no additional toolchain). React and ReactDOM loaded from CDN; JSX transpiled in-browser via Babel Standalone. Gives React component model (state management, re-renders for transcript/metrics updates) without Node.js or a build pipeline. Suitable for a single-page dev tool at this scale. `client/` folder remains static HTML + JS only.

---

### Branch 16 — Observability and Metrics

#### Decision 16.1 — Logging Framework
- **Question:** `structlog` JSON, stdlib `logging`, `loguru`, or OpenTelemetry SDK?
- **Options considered:** structlog with JSON output, stdlib logging, loguru, opentelemetry SDK
- **Decision:** ✅ **`structlog` with JSON output to stdout**
- **Rationale:** Structured key-value records (e.g. `{"event": "stt_complete", "duration_ms": 142, "state": "PROCESSING"}`) trivially parseable by log aggregators. Async-safe; integrates cleanly with asyncio. Session ID and conversation state bound once at session start and automatically carried on every log call. Log level configurable via YAML/env var.

#### Decision 16.2 — Metrics Collection Method
- **Question:** In-process MetricFrame + structlog, Prometheus, StatsD, or derive from logs?
- **Options considered:** In-process MetricFrame collection + structlog emit, Prometheus + prometheus_client, StatsD, no structured metrics
- **Decision:** ✅ **In-process `MetricFrame` collection logged via `structlog`**
- **Rationale:** `MetricFrame` already decided (Decision 4.3). Metrics processor stage reads frames from pipeline and emits structured JSON: `{"event": "metric", "metric": "stt_latency_ms", "value": 142}`. Same log stream as application logs — queryable with any JSON tool. UI receives metrics via LiveKit data channel (Decision 15.3). No external infrastructure for v1.

#### Decision 16.3 — Tracked Latency Metrics
- **Question:** Which per-turn latency metrics are captured?
- **Options considered:** All 7 metrics, core 3 only (STT/LLM TTFT/TTS first-audio), end-to-end only
- **Decision:** ✅ **All 7 metrics per turn**
  1. STT latency (`TranscriptionFrame` emit − VAD end-of-speech)
  2. LLM time-to-first-token (first SSE token − LLM call dispatch)
  3. LLM total generation time (`TurnCompleteFrame` − LLM call dispatch)
  4. TTS time-to-first-audio (first Piper audio chunk − chunk text received)
  5. End-to-end turn latency (first audio out − VAD end-of-speech)
  6. Barge-in detection latency (`InterruptFrame` − first VAD-positive frame)
  7. Chunk count per turn (number of TTS chunks emitted)
- **Rationale:** Each metric serves a distinct diagnostic purpose. End-to-end latency alone hides which stage is slow. Per-session p50/p95 aggregated and logged at session end.

#### Decision 16.4 — Log Level Policy
- **Question:** Standard 4-level, 3-level, single level, or 5-level with CRITICAL?
- **Options considered:** DEBUG/INFO/WARNING/ERROR (4-level), DEBUG/INFO/ERROR (3-level), INFO only, add CRITICAL for SHUTDOWN
- **Decision:** ✅ **Standard 4-level policy: DEBUG / INFO / WARNING / ERROR**
- **Rationale:** DEBUG: frame-by-frame trace (dev only). INFO: turn events, state transitions, metrics. WARNING: recoverable issues (retry succeeded, fallback triggered). ERROR: exceptions, failed transitions, DEGRADED entry. `LOG_LEVEL` configurable via env var and YAML, defaulting to `INFO` in production.

#### Decision 16.5 — Health Check Endpoint
- **Question:** `GET /health` JSON, no health endpoint, readiness+liveness split, or health via logs?
- **Options considered:** GET /health JSON, no endpoint, /ready + /live split, health via log stream
- **Decision:** ✅ **`GET /health` returning JSON status**
- **Rationale:** Agent already has an HTTP server for `/token` and static files (Decisions 3.5, 15.1). A 5-line route addition. Returns `{"status": "ok"|"degraded", "state": "<ConversationState>", "uptime_s": N}`. Enables process monitors, Docker health checks, and simple `curl` verification. Distinguishes "process running but stuck in DEGRADED" from healthy.

#### Decision 16.6 — Session Summary Logging
- **Question:** Structured session summary on shutdown, derive from per-turn logs, separate file, or debug-only?
- **Options considered:** Structured JSON summary at session end, derive manually from logs, write to separate .json file, debug-only
- **Decision:** ✅ **Emit structured session summary JSON record at INFO level on session end**
- **Rationale:** One record per session answers "how did this session go?" without replaying hundreds of log lines. Includes: total turns, session duration, p50/p95 for all 7 metrics, barge-in count, DEGRADED entry count, fallback trigger count. Low-volume (one record/session) — always emitted at INFO, not gated behind DEBUG.

---

### Branch 17 — Testing Strategy

#### Decision 17.1 — Test Framework
- **Question:** pytest + pytest-asyncio, unittest, pytest + anyio, or no framework?
- **Options considered:** pytest + pytest-asyncio, stdlib unittest, pytest + anyio, no framework
- **Decision:** ✅ **pytest + pytest-asyncio**
- **Rationale:** De facto standard for Python async testing. `asyncio_mode = "auto"` in `pyproject.toml` — every async test function automatically treated as async test without per-test decorator. Rich fixture system maps cleanly to pipeline component setup/teardown. Integrates with structlog and Pipecat pipeline components.

#### Decision 17.2 — Unit Test Scope
- **Question:** Which components get unit tests, and where is the mock boundary?
- **Options considered:** Unit test pure-logic + mock at adapter interfaces, unit test everything including models, integration tests only
- **Decision:** ✅ **Unit test pure-logic components; mock I/O boundary at adapter interfaces**
- **Components with unit tests:** state machine, text chunker, markdown stripper, memory module, config loader, barge-in controller, metrics processor
- **Components via integration tests:** STT adapter (faster-whisper), LLM adapter (OpenAI), TTS adapter (Piper), LiveKit transport
- **Rationale:** Pure-logic components are deterministic and fast to test in isolation. Model/API adapters require external resources; unit-testing them with deep mocks adds fragility without catching real integration bugs. Mock boundary is the adapter protocol interface, not internal implementation.

#### Decision 17.3 — Integration Test Approach
- **Question:** Local-only with pytest marker, run all in CI, separate scripts, or respx HTTP mocking?
- **Options considered:** `@pytest.mark.integration` local-only skip CI, full CI integration tests, separate ad-hoc scripts, respx HTTP mocking only
- **Decision:** ✅ **`@pytest.mark.integration` marker; skipped in CI by default. LLM adapter additionally gets `respx`-based unit test for SSE stream handling.**
- **Rationale:** Keeps CI fast with no GPU/model/API key requirements. Developers run `pytest -m integration` locally against real models and APIs. `respx` fakes the OpenAI SSE stream for LLM adapter unit test coverage without a real API key. STT and TTS integration tests require real model files — local only.

#### Decision 17.4 — Benchmark Structure
- **Question:** End-to-end latency benchmark with fixture audio, pytest-benchmark, manual scripts, or none?
- **Options considered:** End-to-end latency benchmark via `benchmark` subcommand, pytest-benchmark microbenchmarks, manual scripts, no benchmarks
- **Decision:** ✅ **End-to-end latency benchmark via `benchmark` subcommand against fixture audio files**
- **Rationale:** Directly exercises the real stack with real models. `uv run voice-agent benchmark --input fixtures/test_audio.wav` runs full pipeline pass and reports all 7 latency metrics as a JSON summary to stdout. ~5 pre-recorded WAV utterances of varying lengths committed to `tests/fixtures/`. Results comparable across hardware configurations and code changes.

#### Decision 17.5 — CI/CD Pipeline
- **Question:** GitHub Actions unit+lint+type, GitHub Actions with integration tests, pre-commit only, or no CI?
- **Options considered:** GitHub Actions unit tests + ruff + mypy, GitHub Actions + integration tests, local pre-commit hooks only, no CI
- **Decision:** ✅ **GitHub Actions: unit tests + `ruff` lint + `mypy` type check on every push to `main` and PRs**
- **Rationale:** Fast (<2 min); no secrets, GPU, or model downloads required. Catches majority of regressions. Workflow: (1) `uv sync`, (2) `ruff check src/ tests/`, (3) `mypy src/`, (4) `pytest tests/ -m "not integration"`. Workflow file at `.github/workflows/ci.yml`.

#### Decision 17.6 — Test Fixtures Strategy
- **Question:** conftest.py fixtures, copy-paste setup, factory helpers, or data generation libraries?
- **Options considered:** pytest fixtures in conftest.py, copy-paste per file, tests/helpers.py factory functions, fixtures + faker/factory_boy
- **Decision:** ✅ **`conftest.py`-based pytest fixtures at `tests/` root**
- **Rationale:** Standard pytest pattern; auto-discovered and auto-injected. Key fixtures: `sample_config` (session scope), `sample_audio_frame` (30ms PCM bytes), `sample_transcription` (short/medium/long strings), `mock_pipeline`, `state_machine` (function scope — fresh per test), `memory_store` (function scope — empty per test). Scope management prevents stateful test pollution.

---

### Branch 18 — Error Handling and Fallbacks

#### Decision 18.1 — STT Failure Handling
- **Question:** Canned fallback + LISTENING, transition to DEGRADED, silent drop, or retry?
- **Options considered:** Canned "I didn't catch that" + return to LISTENING, transition to DEGRADED, silent drop, retry N times
- **Decision:** ✅ **Emit canned "I didn't catch that, could you repeat?" audio + return to LISTENING**
- **Rationale:** STT failures are almost always transient (GPU OOM, thread contention). Single graceful fallback gives user clear feedback and a chance to repeat without escalating to DEGRADED. Fallback phrase configurable in YAML. Failure logged at WARNING level. Fallback count tracked in session metrics (Decision 16.6).

#### Decision 18.2 — LLM Failure Handling
- **Question:** Retry-once + canned fallback + LISTENING, retry-once + DEGRADED, no retry, or queue and retry later?
- **Options considered:** Retry once → canned fallback → LISTENING, retry once → DEGRADED, no retry → immediate fallback, queue and retry
- **Decision:** ✅ **Retry once → canned "I'm having trouble thinking" audio → return to LISTENING**
- **Rationale:** Consistent with Decision 9.6 (retry-once + canned fallback). LLM failures (rate limit, transient 500) are often recoverable on first retry. Distinct fallback phrase from STT fallback signals different failure mode to user. Second failure logged at ERROR level. Fallback phrase configurable in YAML.

#### Decision 18.3 — TTS Failure Handling
- **Question:** Pre-synthesised fallback WAV, retry synthesis, fallback to shorter Piper text, or DEGRADED?
- **Options considered:** Pre-synthesised fallback WAV + LISTENING, retry synthesis, shorter canned text via Piper, transition to DEGRADED
- **Decision:** ✅ **Abandon synthesis, play pre-synthesised fallback WAV, return to LISTENING**
- **Rationale:** If Piper is the failure point, a Piper-generated fallback also fails. Pre-synthesised `assets/fallback.wav` ("Something went wrong, please try again") is generated once and committed to the repo — always available regardless of Piper's state. Failure logged at WARNING level.

#### Decision 18.4 — Transport Failure Handling
- **Question:** Exponential backoff reconnect, single retry, indefinite reconnect, or immediate SHUTDOWN?
- **Options considered:** Exponential backoff max 5 retries → SHUTDOWN, immediate single retry → SHUTDOWN, indefinite reconnect, immediate SHUTDOWN
- **Decision:** ✅ **Exponential backoff reconnect (1s/2s/4s/8s/16s, max 5 retries) → SHUTDOWN**
- **Rationale:** Consistent with Decision 3.6 (same policy for initial connection applied to mid-session drops). Covers most common failure mode (brief network interruption). During reconnect: transition to `DEGRADED`, halt pipeline activity. On success: return to `READY`. On exhaustion of retries: `SHUTDOWN`.

#### Decision 18.5 — Provider Swap Abstraction
- **Question:** Formal Protocol interfaces, concrete classes only, ABCs, or full plugin architecture?
- **Options considered:** `typing.Protocol` per adapter type + config injection, concrete classes only, ABCs, full plugin system
- **Decision:** ✅ **Formal `typing.Protocol` interface per adapter type; concrete implementations injected via config**
- **Rationale:** `STTAdapter`, `LLMAdapter`, `TTSAdapter` protocols defined in `src/voice_agent/protocols.py`. Structural subtyping — no inheritance required; any class with matching method signatures satisfies the protocol. Mock implementations in unit tests naturally satisfy protocols. Config selects backend (e.g. `stt.backend: "faster_whisper"`) → instantiates `FasterWhisperAdapter`. Pipeline code never couples to concrete providers.

---

### Branch 19 — OpenAI Realtime (Optional)

#### Decision 19.1 — OpenAI Realtime API Inclusion
- **Question:** Include Realtime API in v1 (as alternative backend, replacement, or default), or defer to v2?
- **Options considered:** Defer to v2, include as alternative backend, replace local stack entirely, Realtime default + local fallback
- **Decision:** ✅ **Defer entirely to v2**
- **Rationale:** `typing.Protocol` adapter interfaces (Decision 18.5) make a v2 Realtime adapter a clean, isolated addition with no pipeline changes. Including it in v1 would double the adapter surface and testing scope. Swap path documented in README. No Realtime code in v1. Remaining Branch 19 questions (modes, runtime switching, transcript visibility) are moot for v1.

---

### Branch 20 — Deployment and Packaging

#### Decision 20.1 — Distribution Method
- **Question:** uv clone-and-run, PyPI package, Windows installer, or Docker only?
- **Options considered:** uv-managed venv + `uv run`, PyPI package, Windows installer, Docker only
- **Decision:** ✅ **`uv`-managed venv; clone-and-run via `uv run voice-agent start`**
- **Rationale:** Consistent with Decision 1.2 (uv as package manager). README is the installer: `git clone` → `uv sync` → copy `.env.example` to `.env` → fill in keys → `uv run voice-agent start`. No packaging overhead for a v1 developer tool. PyPI distribution deferred to v2.

#### Decision 20.2 — Docker Support
- **Question:** No Docker, CPU-only Dockerfile, CUDA Dockerfile, or Docker Compose?
- **Options considered:** No Docker (native Windows only), Dockerfile CPU-only, Dockerfile with CUDA, Docker Compose
- **Decision:** ✅ **No Docker in v1 — README documents native Windows setup only**
- **Rationale:** Target platform is native Windows 10/11. Docker adds virtualisation between microphone input, real-time audio processing, and network stack — all latency-sensitive. Windows + CUDA + Docker Desktop (WSL2 + NVIDIA Container Toolkit) is more complex than native Python. Docker deferred to v2 if Linux server deployment is demanded.

#### Decision 20.3 — Process Mode
- **Question:** Foreground process, Windows service, Task Scheduler, or both?
- **Options considered:** Foreground process only, Windows service (pywin32/NSSM), Task Scheduler, foreground + optional service install
- **Decision:** ✅ **Foreground process only — `uv run voice-agent start` in a terminal**
- **Rationale:** Voice agent is an interactive tool requiring a present user. Terminal window with live log output is useful during development and debugging. `Ctrl+C` triggers graceful `SHUTDOWN` sequence. Windows service adds complexity with no benefit for the primary use case. Service support deferred to v2.

#### Decision 20.4 — First-Run Setup
- **Question:** `check` subcommand + `.env.example`, interactive setup wizard, README only, or auto-download models?
- **Options considered:** `voice-agent check` + `.env.example`, interactive `voice-agent setup` wizard, README only, auto-download on first run
- **Decision:** ✅ **`uv run voice-agent check` pre-flight validation + `.env.example` with inline comments**
- **Rationale:** `check` subcommand already decided (Decision 2.3). Validates: `LIVEKIT_URL` set, `OPENAI_API_KEY` set, CUDA device found (or CPU fallback noted), Piper model file exists, faster-whisper model cached. Clear pass/fail checklist output tells user exactly what's missing before starting. README documents the 5-step setup sequence. Zero extra scope.

