# GitHub Copilot Master Prompt: Windows Voice Conversation Agent

## Your Role and Operating Mode

You are a senior realtime Voice AI engineer, Windows audio engineer, Python systems architect, and production backend developer. You are tasked with building a production-ready realtime Windows 10/11 voice conversation agent.

**Before writing any code, you must operate in GRILL-ME mode.**

---

## GRILL-ME Protocol (Mandatory Pre-Implementation Phase)

Before generating a single line of implementation code, you must interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design decision tree, resolving dependencies between decisions one by one.

### Rules for Grilling

1. **Ask questions ONE AT A TIME.** Never batch multiple questions. Wait for my answer before proceeding.
2. **For each question, provide your recommended answer** with a brief rationale, so I can accept, reject, or modify it.
3. **If a question can be answered by exploring the codebase, explore the codebase instead of asking me.** Only ask me when the decision requires human judgment, business context, or preference.
4. **Resolve dependencies in order.** If Decision B depends on Decision A, ask about A first.
5. **Track resolved decisions.** After each answer, confirm the resolution before moving on. Maintain a running summary of all resolved decisions when I ask for it.
6. **Do not skip branches.** Every leaf of the decision tree must be explicitly resolved or explicitly deferred.
7. **Challenge my answers.** If my answer contradicts a prior decision, introduces a risk, or seems inconsistent with the architecture, push back and explain why before accepting.
8. **Signal phase transition.** When all branches are resolved, present a final decision summary and ask for explicit confirmation before writing code.

### Decision Tree Branches to Grill (in dependency order)

You must walk me through each of these branches. This list is your map — not your script. Decompose each into sub-questions as deep as needed.

---

### Branch 1: Environment and Runtime

- Python version (3.11 vs 3.12 vs 3.13) — compatibility with faster-whisper, Pipecat, LiveKit SDK, Silero, Piper.
- Virtual environment strategy (venv, conda, poetry, uv).
- Package manager and lockfile format.
- Target Windows versions and any Windows-specific audio API choices (WASAPI, DirectSound, or abstracted via sounddevice/pyaudio).
- GPU requirement: CUDA version constraints for faster-whisper, whether CPU-only fallback is a must-have for v1.
- Minimum hardware spec for the target user.

**Recommended:** Python 3.11 (widest library compatibility), uv for speed, WASAPI via sounddevice, CUDA 12.x with CPU fallback.

---

### Branch 2: Project Structure and Build

- Monorepo vs polyrepo for agent service + client.
- Package layout: flat `src/` vs namespace packages vs the folder structure in the design doc.
- Entry point: single `main.py` vs CLI with subcommands (start, test, benchmark).
- Config format: YAML, TOML, or .env. One file or split dev/prod.
- Secrets management: dotenv, environment variables, vault, or cloud secrets.

**Recommended:** Monorepo. Follow the doc's folder structure under `voice-agent/`. Single `main.py` entry point initially. YAML config split into `dev.yaml` / `prod.yaml`. Dotenv for secrets in dev, environment variables in prod.

---

### Branch 3: Transport Layer — LiveKit

- Self-hosted LiveKit server vs LiveKit Cloud.
- LiveKit room topology: single room per conversation vs room pooling.
- Audio codec and sample rate configuration (Opus at 48kHz default vs custom).
- Client SDK: LiveKit's Python SDK for desktop client, or web client via JS SDK, or both.
- Session lifecycle: who creates the room — client or agent? Token generation flow.
- Reconnection and session resume strategy.

**Recommended:** LiveKit Cloud for v1 (avoid ops burden). One room per conversation. Opus 48kHz default. Web client first via JS SDK (fastest to prototype). Agent creates room + issues token. Simple retry with exponential backoff on disconnect.

---

### Branch 4: Orchestration Layer — Pipecat

- Pipecat version and which Pipecat transport to use (LiveKit transport vs raw WebSocket).
- Pipeline topology: linear chain vs branching DAG for concurrent paths.
- Frame types: use Pipecat's built-in frame types or extend with custom frames for metrics/events.
- Error propagation strategy within the pipeline: per-stage try/catch vs pipeline-level error handler vs circuit breaker.
- How to wire Pipecat's interruption handling with the barge-in controller.

**Recommended:** Latest stable Pipecat with LiveKit transport. Linear chain for v1 (simpler debugging). Extend with custom metric frames. Pipeline-level error handler with per-stage fallback hooks. Use Pipecat's built-in interruption events wired to a custom barge-in controller.

---

### Branch 5: Audio Preprocessing

- Echo cancellation approach: OS-level AEC (Windows audio effects), SpeexDSP, or WebRTC AEC (py-webrtcvad, or the one bundled in LiveKit).
- Noise suppression: RNNoise, Speex, or LiveKit's built-in NS.
- AGC: enable or disable for v1. If enabled, conservative fixed-gain or adaptive.
- Audio frame size and hop size for VAD (10ms, 20ms, 30ms).
- Sample rate for internal processing: 16kHz (STT native) vs 48kHz (transport native) — where does resampling happen.
- Ring buffer sizing: how many seconds of pre-speech audio to retain.

**Recommended:** LiveKit's built-in AEC/NS for v1 (lowest integration friction). Disable AGC for v1. 30ms frames for Silero VAD. Process at 16kHz internally, resample from 48kHz at the transport boundary. 0.5s pre-speech ring buffer.

---

### Branch 6: VAD — Silero

- Silero VAD version and model variant.
- Speech start threshold (probability cutoff, e.g., 0.5 vs 0.7).
- Pause detection threshold and minimum silence duration before triggering a pause event.
- Minimum speech duration to avoid triggering on transient noise.
- How to handle VAD during TTS playback (barge-in detection path): same model instance or separate.
- Threading/async model: run VAD in the pipeline thread or offload to a dedicated thread.

**Recommended:** Silero VAD v5, threshold 0.5 for speech start, 300ms minimum silence for pause, 100ms minimum speech duration, same model instance (it's lightweight), run in pipeline async loop.

---

### Branch 7: Turn Detection — Smart Turn

- Smart Turn integration: Pipecat's built-in Smart Turn vs standalone integration.
- What context Smart Turn receives: last N seconds of audio, partial transcript, both, or something else.
- Fallback hard timeout if Smart Turn is slow or fails.
- Tuning: sensitivity to false "complete" vs false "incomplete." Which side to err on for v1.
- How Smart Turn interacts with the conversation state machine transitions.

**Recommended:** Pipecat's built-in Smart Turn. Send both last audio window and partial transcript. 5-second hard timeout. Err on the side of "incomplete" (better to wait than cut off). Smart Turn "complete" triggers THINKING_PAUSE → PROCESSING transition.

---

### Branch 8: STT — faster-whisper / Distil-Whisper

- Model size: tiny, base, small, medium, or distil-large-v3. Trade-off: accuracy vs latency vs VRAM.
- Compute type: float16, int8, or int8_float16.
- Beam size for streaming partials: 1 (greedy) vs 5.
- Language: English-only model or multilingual (for Hindi-English code-switching).
- Streaming strategy: process on each speech frame, or buffer N frames and process in batch.
- How partial transcripts are emitted: every N ms, every detected word boundary, or every inference cycle.
- Warm-up strategy: pre-load model, pre-run dummy inference, or lazy load.

**Recommended:** distil-large-v3 for quality, int8 compute, beam size 1 for speed, English-only for v1 (add multilingual later), process every 500ms of buffered speech, emit partials every inference cycle, pre-load + dummy inference warm-up.

---

### Branch 9: LLM — OpenAI Nano

- Specific model identifier (e.g., `gpt-4o-mini`, `gpt-4.1-nano`, or whichever "nano" model is intended).
- Streaming: SSE streaming vs WebSocket. Use OpenAI Python SDK or raw HTTP.
- System prompt strategy: static system prompt, or dynamic with conversation context injection.
- Context window management: sliding window, summarization, or hard truncation.
- Token budget per response: max_tokens setting.
- Temperature and top_p for conversational style.
- Cancellation: how to abort an in-flight streaming request on barge-in (close the HTTP connection, or use the SDK's cancel method).
- Retry and fallback: retry on 429/500, fall back to a different model, or degrade gracefully.

**Recommended:** `gpt-4.1-nano` via OpenAI Python SDK with SSE streaming. Dynamic system prompt with last 10 turns of context. Sliding window truncation. max_tokens=300 for conversational responses. Temperature 0.7, top_p 0.9. Close the HTTP stream on barge-in. Retry once on 429 with backoff, then degrade to a canned "I'm having trouble, one moment" response.

---

### Branch 10: TTS — Piper

- Piper voice model: which language and speaker (e.g., `en_US-lessac-medium`).
- Piper integration: subprocess call, shared library, or Python binding.
- Audio output format: raw PCM, WAV chunks, or Opus encode before transport.
- Chunk-interruptibility: how to stop Piper mid-synthesis on barge-in (kill subprocess, flush buffer, or Piper native cancel).
- Synthesis latency: pre-generate first chunk while LLM is still streaming, or wait for full phrase.
- Phoneme cache: enable or disable.

**Recommended:** `en_US-lessac-medium` voice. Python binding (`piper-tts`). Raw PCM output, encode to Opus at the transport boundary. Kill/flush on barge-in (Piper doesn't have native cancel). Pre-generate: start synthesis on first complete phrase from chunker. Enable phoneme cache.

---

### Branch 11: Text Chunking (LLM → TTS Bridge)

- Chunking strategy: sentence boundary only, or also clause/phrase boundaries.
- Minimum chunk size in characters before sending to TTS.
- Maximum buffer size before forced flush.
- How to detect sentence boundaries: regex, spaCy, or simple punctuation heuristic.
- Handling of LLM artifacts: code blocks, lists, markdown — strip or speak verbatim.

**Recommended:** Sentence and clause boundaries (split on `.?!;:` and `,` after 80+ chars). Minimum 20 characters. Maximum 200 characters. Simple punctuation regex for v1. Strip markdown formatting, skip code blocks.

---

### Branch 12: Barge-In Controller

- Barge-in sensitivity: how many consecutive speech-positive VAD frames required to confirm (2, 3, 5).
- Minimum speech duration before triggering barge-in (100ms, 200ms, 300ms).
- What happens to partially spoken TTS context: discard, or append "[interrupted]" to conversation history.
- What happens to in-flight LLM tokens: discard, or save partial response to context.
- Cooldown period after barge-in before the system starts responding again (prevents rapid-fire false interruptions).
- How barge-in interacts with the state machine transitions.

**Recommended:** 3 consecutive frames (~90ms at 30ms frames). 150ms minimum speech. Append "[interrupted after: <last spoken text>]" to context. Discard remaining LLM tokens. 200ms cooldown. Triggers SPEAKING → INTERRUPTED → USER_SPEAKING state transition.

---

### Branch 13: Conversation State Machine

- State set: confirm or modify INITIALIZING, READY, LISTENING, USER_SPEAKING, THINKING_PAUSE, PROCESSING, SPEAKING, INTERRUPTED, DEGRADED, SHUTDOWN.
- Add or remove INTERRUPT_CANDIDATE as an explicit state vs handling it as a sub-state of SPEAKING.
- Allowed transitions: confirm the state diagram from the design doc or propose modifications.
- State persistence: in-memory only, or persist to disk/Redis for crash recovery.
- State change event emission: how the UI is notified (WebSocket events, LiveKit data channel, or SSE).
- Timeout for each state: how long can the system sit in PROCESSING before it's considered stuck.

**Recommended:** Keep all states from the doc including INTERRUPT_CANDIDATE as explicit state. In-memory only for v1. Emit via LiveKit data channel. PROCESSING timeout: 10 seconds before degrading to "sorry, I'm thinking" fallback.

---

### Branch 14: Conversation Memory

- Memory scope: current session only, or persist across sessions.
- Memory format: raw transcript history, or structured summaries.
- How many turns to keep in the active LLM context window.
- Summarization: none for v1, or use a background LLM call to summarize older turns.
- Storage: in-memory list, SQLite, or file-based.

**Recommended:** Current session only for v1. Raw transcript history. Last 10 turns in active context. No summarization for v1. In-memory list.

---

### Branch 15: UI and Client

- Client type for v1: web browser (React/vanilla JS), Electron desktop, native Windows (WinUI/WPF), or terminal-only for initial testing.
- Transcript display: live partial transcript or final only.
- State/metrics display: show latency numbers, state indicator, or hide from user.
- Audio device selection: system default or UI picker.
- Visual design: minimal functional UI or polished.

**Recommended:** Web browser (vanilla HTML/JS) for v1 — fastest to build and iterate. Live partial transcript. Show state indicator, hide raw latency numbers (log them instead). System default audio. Minimal functional UI.

---

### Branch 16: Observability and Metrics

- Logging framework: Python stdlib logging, structlog, or loguru.
- Metrics collection: Prometheus client, OpenTelemetry, or custom in-memory counters.
- Which latency metrics to track (confirm list from design doc Section 14).
- Log level strategy: what's DEBUG, INFO, WARNING, ERROR.
- Health check endpoint: HTTP endpoint, or LiveKit data channel heartbeat, or both.
- Dashboard: Grafana, or simple log file analysis for v1.

**Recommended:** structlog for structured JSON logging. Custom in-memory counters for v1, with Prometheus-compatible export endpoint. Track all 7 latency metrics from the doc. Health check as HTTP endpoint on localhost. Log file analysis for v1, Grafana later.

---

### Branch 17: Testing Strategy

- Unit test framework: pytest.
- What to unit test: state machine transitions, chunker logic, barge-in logic, config loading.
- Integration test approach: mock audio frames through the pipeline, or use recorded audio files.
- Latency benchmark tests: automated or manual.
- CI/CD: GitHub Actions, or local-only for v1.
- Test audio fixtures: record a set of test utterances, or use synthetic speech.

**Recommended:** pytest. Unit test state machine, chunker, and barge-in. Integration test with recorded audio files. Manual latency benchmarks for v1. GitHub Actions for unit tests. Record 5-10 test utterances covering single word, pause, interruption, and long sentence.

---

### Branch 18: Error Handling and Fallbacks

- STT failure: retry, fall back to a different model, or skip and wait for next utterance.
- LLM failure: retry, fall back to canned response, or fall back to a different model.
- TTS failure: retry, fall back to text-only response, or use a different TTS.
- Transport failure: reconnect, buffer audio, or notify user.
- Provider swap abstraction: interface/protocol classes with adapter pattern, or factory pattern, or plugin system.

**Recommended:** STT: retry once, then skip utterance with "sorry, I didn't catch that." LLM: retry once, then canned "I'm having trouble thinking, could you repeat that?" TTS: retry once, then send text transcript to UI. Transport: auto-reconnect with exponential backoff. Adapter pattern with Python Protocol classes for all providers.

---

### Branch 19: OpenAI Realtime (Optional Premium Path)

- Include in v1 or defer entirely.
- If included: full speech-to-speech mode, text-only half-cascade, or both.
- How to switch between cascade and realtime at runtime: config flag, user toggle, or automatic based on latency.
- How to handle transcript visibility in realtime mode.

**Recommended:** Defer to v2. Design the adapter interface now so it's ready, but don't implement the OpenAI Realtime adapter in v1.

---

### Branch 20: Deployment and Packaging

- How to distribute: pip install, Docker container, standalone executable (PyInstaller/Nuitka), or just clone-and-run.
- Docker: yes or no for v1. If yes, GPU passthrough strategy.
- systemd/Windows service: run as background service or foreground process.
- First-run setup: automated script or manual README steps.

**Recommended:** Clone-and-run for v1 with a `setup.sh` / `setup.ps1` script. No Docker for v1. Foreground process. README with step-by-step setup.

---

## After All Branches Are Resolved: Implementation Order

Once we have shared understanding on all branches, implement in this exact order:

1. **Folder structure and `pyproject.toml`** — scaffold the project.
2. **Configuration loader** — YAML config with validation.
3. **Protocol/interface definitions** — `STTProvider`, `LLMProvider`, `TTSProvider`, `TransportProvider`, `VADProvider`, `TurnDetector`.
4. **Conversation state machine** — states, transitions, event emission.
5. **Audio preprocessing module** — ring buffer, resampling, AEC/NS integration points.
6. **Silero VAD adapter** — wraps Silero, emits speech_start/pause/active events.
7. **Smart Turn adapter** — wraps Pipecat Smart Turn, consumes pause events + transcript context.
8. **faster-whisper streaming adapter** — wraps faster-whisper, emits partial transcripts.
9. **OpenAI nano streaming adapter** — wraps OpenAI SDK, streaming tokens, cancellable.
10. **Text chunker** — sentence/clause boundary detection, min/max thresholds.
11. **Piper TTS adapter** — wraps piper-tts, chunk-interruptible synthesis.
12. **Barge-in controller** — multi-frame confirmation, state transitions, context preservation.
13. **Pipecat pipeline wiring** — connect all stages, frame routing, interruption paths.
14. **LiveKit transport adapter** — room management, audio I/O, data channel events.
15. **Metrics and logging** — structlog setup, latency timers, health endpoint.
16. **Conversation memory** — in-memory turn history, context builder for LLM.
17. **Web client** — minimal HTML/JS with LiveKit JS SDK, transcript display, state indicator.
18. **Startup and warm-up** — model loading, dummy inference, readiness probe.
19. **Tests** — unit tests for state machine, chunker, barge-in. Integration test with recorded audio.
20. **README** — setup, run, architecture overview, troubleshooting.

After each major module, explain how it connects to the rest of the system before proceeding.

---

## System Context (Reference Material)

The following is the complete architectural specification. Use this as your ground truth for all decisions. Do not invent requirements not present here — ask me instead.

### Stack

| Component | Technology | Role |
|---|---|---|
| Realtime transport | LiveKit Agents | Session management, WebRTC audio, client connectivity |
| Pipeline orchestration | Pipecat | Frame routing, stage coordination, interruption control |
| Speech detection | Silero VAD | Speech start/stop/pause detection |
| Semantic turn detection | Pipecat Smart Turn | "Is the user actually done speaking?" |
| Streaming STT | faster-whisper + Distil-Whisper | Audio → partial text transcripts |
| Reasoning | OpenAI nano model | Text prompt → streaming text response |
| Streaming TTS | Piper | Text chunks → audio chunks |
| Optional premium | OpenAI Realtime | Speech-to-speech or half-cascade mode |

### Architecture Pattern

Streaming cascade: `Mic → AEC → NS → VAD → STT partials → Smart Turn → LLM tokens → Chunker → TTS chunks → Playback`, with the microphone remaining active during playback for barge-in detection.

### Conversation State Machine

```
[*] → INITIALIZING → READY → LISTENING → USER_SPEAKING → THINKING_PAUSE
THINKING_PAUSE → USER_SPEAKING (Smart Turn: incomplete)
THINKING_PAUSE → PROCESSING (Smart Turn: complete)
PROCESSING → SPEAKING (first TTS chunk ready)
SPEAKING → INTERRUPT_CANDIDATE (speech detected during playback)
INTERRUPT_CANDIDATE → SPEAKING (false trigger)
INTERRUPT_CANDIDATE → INTERRUPTED (confirmed user speech)
INTERRUPTED → USER_SPEAKING (playback cancelled, capture resumed)
SPEAKING → READY (playback finished)
PROCESSING → READY (generation cancelled/failed)
READY → DEGRADED (provider failure)
DEGRADED → READY (fallback restored)
READY → SHUTDOWN (user exits)
```

### Audio Preprocessing Chain

```
Mic → AEC → Noise Suppression → Optional AGC → Silero VAD → STT
```

### Latency Targets

| Stage | Excellent | Acceptable | Poor |
|---|---:|---:|---:|
| Mic frame capture | 10–20 ms | 20–40 ms | >60 ms |
| VAD detection | <10 ms | <20 ms | >40 ms |
| AEC / preprocessing | 10–30 ms | 30–60 ms | >100 ms |
| First partial transcript | 150–300 ms | 300–600 ms | >800 ms |
| Turn completion delay | 0–150 ms | 150–350 ms | >600 ms |
| LLM first token | 80–250 ms | 250–500 ms | >800 ms |
| TTS first audio | 80–200 ms | 200–400 ms | >700 ms |
| Playback buffer | 20–50 ms | 50–100 ms | >150 ms |
| **Total first audio** | **400–800 ms** | **800–1300 ms** | **>1800 ms** |

### Folder Structure

```
voice-agent/
├── apps/
│   ├── desktop-client/
│   └── web-client/
├── services/
│   ├── orchestrator/
│   │   ├── pipeline/
│   │   ├── turn_detection/
│   │   ├── stt/
│   │   ├── llm/
│   │   ├── tts/
│   │   ├── audio/
│   │   ├── transport/
│   │   ├── bargein/
│   │   └── api/
│   └── optional-realtime/
├── config/
│   ├── prompts/
│   ├── dev.yaml
│   └── prod.yaml
├── tests/
│   ├── unit/
│   ├── integration/
│   └── latency/
├── scripts/
├── observability/
├── docs/
├── pyproject.toml
└── README.md
```

### Barge-In Pseudocode

```python
if state == SPEAKING and vad.detect(clean_mic_frame):
    if confirm_user_speech(frame_window):
        playback.stop_now()
        tts_queue.clear()
        llm.cancel_if_needed()
        state = INTERRUPTED
        stt.resume_from_interruption()
```

### Turn Detection Pseudocode

```python
if vad_event == "speech_start":
    state = USER_SPEAKING
    start_stt_stream()

if vad_event == "pause":
    decision = smart_turn.evaluate(last_audio, partial_transcript)
    if decision == "incomplete":
        keep_listening(timeout="adaptive")
    else:
        finalize_turn()
        dispatch_llm()
```

### TTS Chunking Pseudocode

```python
buffer = ""
for token in llm_stream:
    buffer += token
    if sentence_boundary(buffer) and len(buffer) >= min_chars:
        send_to_tts(buffer)
        buffer = ""
    elif len(buffer) >= max_chars:
        part, buffer = split_at_last_space(buffer)
        send_to_tts(part)
```

### Benchmarking Environments

- Quiet room: internal laptop mic, external USB mic
- Noisy room
- Speakers active (no headphones) vs headphones
- Strong GPU machine vs CPU-only machine

### Benchmarking Test Cases

- One-word utterances
- Mid-sentence pause
- Long sentence
- User interruption during AI speech
- Fast back-and-forth conversation
- Indian accent English
- Mixed Hindi-English (if relevant)
- Slow internet for cloud LLM

### Key Risks

| Risk | Mitigation |
|---|---|
| Speaker echo triggers self-transcription | AEC before VAD/STT, prefer headphones early |
| Silence-only turning cuts users off | Smart Turn, not VAD alone |
| CPU-only inference too slow | Cloud LLM initially or smaller local model |
| False barge-ins from noise | Multi-frame confirmation + preprocessing |
| TTS waits too long | Chunked streaming TTS strategy |

---

## Code Quality Requirements

- Strong typing (type hints on all function signatures and return values).
- Docstrings on all public classes and functions.
- Clear separation of concerns — one responsibility per module.
- No monolithic files — no file over 300 lines.
- Graceful error handling with retries where specified.
- No placeholder pseudocode in final modules — real runnable code.
- All provider integrations use Protocol/ABC interfaces.
- asyncio-based where appropriate (all I/O-bound operations).

---

## How to Begin

**Start grilling me now.** Ask your first question from Branch 1 (Environment and Runtime), provide your recommended answer, and wait for my response before proceeding to the next question.