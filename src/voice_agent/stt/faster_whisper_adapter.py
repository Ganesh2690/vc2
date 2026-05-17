"""faster-whisper STT adapter with integrated Smart Turn evaluation.

Pipeline position: receives AudioRawFrame and speaking-event frames from
the transport; emits InterimTranscriptionFrame (partials) and
TranscriptionFrame (final, turn-complete) downstream.
"""
from __future__ import annotations

import asyncio
import importlib
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import numpy as np
import structlog
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice_agent.config import SmartTurnConfig, STTConfig
from voice_agent.frames import TurnCompleteFrame

log = structlog.get_logger(__name__)


class FasterWhisperSTTService(FrameProcessor):
    """Buffers speech audio, runs faster-whisper inference every N ms, and
    applies a Smart Turn heuristic before emitting a final TranscriptionFrame.
    """

    def __init__(
        self,
        stt_config: STTConfig,
        smart_turn_config: SmartTurnConfig,
    ) -> None:
        super().__init__()
        self._cfg = stt_config
        self._st_cfg = smart_turn_config

        self._model: Any | None = None  # loaded in initialize()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")

        self._is_user_speaking = False
        self._turn_active = False
        self._audio_buffer = bytearray()
        self._last_partial_time: float = 0.0
        self._partial_text: str = ""

        # Smart Turn hard timeout task
        self._smart_turn_task: asyncio.Task | None = None
        self._turn_start_time: float = 0.0
        self._smart_turn_model: Any | None = None  # optional pipecat SmartTurn model

    # ─────────────────────────────────────────────────── initialisation ──

    async def initialize(self) -> None:
        """Load the faster-whisper model and run a dummy warm-up inference."""
        from faster_whisper import WhisperModel

        device = await self._detect_device()
        compute_type = self._resolve_compute_type(device)

        log.info(
            "loading_stt_model",
            model=self._cfg.model,
            device=device,
            compute_type=compute_type,
        )
        loop = asyncio.get_running_loop()

        def _load_model() -> Any:
            return cast(
                Any,
                WhisperModel(
                    self._cfg.model,
                    device=device,
                    compute_type=compute_type,
                ),
            )

        self._model = await loop.run_in_executor(
            self._executor,
            _load_model,
        )

        # Warm up: 1 s of silence
        silence = bytes(int(16000 * 1 * 2))
        await self._transcribe_async(silence)
        log.info("stt_model_ready", model=self._cfg.model)

        # Try to load pipecat's Smart Turn model
        await self._try_load_smart_turn()

    async def _detect_device(self) -> str:
        try:
            import ctranslate2

            return "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            return "cpu"

    def _resolve_compute_type(self, device: str) -> str:
        if self._cfg.compute_type != "auto":
            return self._cfg.compute_type
        return "int8_float16" if device == "cuda" else "int8"

    async def _try_load_smart_turn(self) -> None:
        try:
            smart_turn_module = importlib.import_module("pipecat.audio.turn.smart_turn")
            smart_turn_analyzer = getattr(smart_turn_module, "SmartTurnAnalyzer", None)
            if smart_turn_analyzer is None:
                raise AttributeError("SmartTurnAnalyzer")

            self._smart_turn_model = smart_turn_analyzer()
            log.info("smart_turn_model_loaded")
        except Exception as exc:
            log.info("smart_turn_model_unavailable", reason=str(exc))

    # ──────────────────────────────────────────────── frame processing ──

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            await self._on_speech_start(frame, direction)

        elif isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            await self._on_speech_pause(frame, direction)

        elif isinstance(frame, AudioRawFrame) and self._is_user_speaking:
            await self._on_audio_frame(frame)
            # Audio frames are not forwarded — consumed here

        else:
            await self.push_frame(frame, direction)

    # ─────────────────────────────────────────────── speech event logic ──

    async def _on_speech_start(self, frame: Frame, direction: FrameDirection) -> None:
        resumed_turn = self._cancel_pending_turn_task()
        self._is_user_speaking = True

        if not self._turn_active:
            self._turn_active = True
            self._audio_buffer.clear()
            self._partial_text = ""
            self._last_partial_time = time.monotonic()
            self._turn_start_time = time.monotonic()

        log.debug(
            "speech_start",
            resumed_turn=resumed_turn,
            buffer_bytes=len(self._audio_buffer),
        )
        await self.push_frame(frame, direction)

    async def _on_speech_pause(
        self, frame: Frame, direction: FrameDirection
    ) -> None:
        self._is_user_speaking = False
        log.debug("speech_pause", buffer_bytes=len(self._audio_buffer))
        # Forward the stop frame immediately so downstream state machine updates.
        # ExternalUserTurnStopStrategy in LLMUserAggregator will handle sequencing.
        await self.push_frame(frame, direction)
        self._cancel_pending_turn_task()
        self._smart_turn_task = asyncio.create_task(self._finalize_turn_after_pause())

    async def _on_audio_frame(self, frame: AudioRawFrame) -> None:
        self._audio_buffer.extend(frame.audio)

    # ────────────────────────────────────────────── transcript emission ──

    async def _emit_partial(self) -> None:
        if len(self._audio_buffer) < 3200:  # < 100 ms
            return
        text = await self._transcribe_async(bytes(self._audio_buffer))
        if text:
            self._partial_text = text
            await self.push_frame(
                InterimTranscriptionFrame(
                    text=text,
                    user_id="user",
                    timestamp=str(time.time()),
                ),
                FrameDirection.DOWNSTREAM,
            )

    async def _finalize_turn_after_pause(self) -> None:
        try:
            pause_grace_s = max(0.15, self._cfg.inference_cadence_ms / 1000.0)
            await asyncio.sleep(pause_grace_s)
            await self._evaluate_turn()
        except asyncio.CancelledError:
            log.debug("turn_finalize_cancelled", buffer_bytes=len(self._audio_buffer))
            raise
        finally:
            if self._smart_turn_task is asyncio.current_task():
                self._smart_turn_task = None

    async def _evaluate_turn(self) -> None:
        """Transcribe buffered audio and emit TranscriptionFrame.

        Pipecat's Smart Turn v3.2 (in VADProcessor upstream) has already
        validated the turn end before UserStoppedSpeakingFrame reaches here,
        so we unconditionally emit a TranscriptionFrame for any non-empty text.
        """
        audio = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        self._turn_active = False

        # Fast path: if a partial inference ran recently it already covers
        # most of the audio buffer. Reuse that result instead of running a
        # full re-transcription, which is the main CPU-latency bottleneck.
        cadence_s = self._cfg.inference_cadence_ms / 1000.0
        time_since_partial = time.monotonic() - self._last_partial_time
        if self._partial_text and time_since_partial < cadence_s * 1.5:
            text = self._partial_text
            log.debug("stt_reusing_partial", lag_ms=int(time_since_partial * 1000))
        else:
            text = await self._transcribe_async(audio) or self._partial_text

        if text and text.strip():
            log.info("turn_complete", transcript=text[:80])
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id="user",
                    timestamp=str(time.time()),
                ),
                FrameDirection.DOWNSTREAM,
            )
            await self.push_frame(
                TurnCompleteFrame(transcript=text),
                FrameDirection.DOWNSTREAM,
            )
        else:
            log.debug("turn_empty_transcript")

    async def _smart_turn_classify(self, audio: bytes, text: str) -> bool:
        """Returns True when the turn should be treated as complete."""
        # Try pipecat's Smart Turn model
        if self._smart_turn_model is not None:
            try:
                result = await self._smart_turn_model.analyze(audio, text)
                return result == "complete"
            except Exception as exc:
                log.warning("smart_turn_model_error", error=str(exc))

        # Heuristic fallback
        return self._heuristic_complete(text)

    def _heuristic_complete(self, text: str) -> bool:
        """Simple punctuation + word-count heuristic for turn completeness."""
        if not text or not text.strip():
            return False

        stripped = text.strip()
        words = stripped.split()

        # Too short — likely noise or a fragment
        if len(words) < 2:
            return not self._st_cfg.err_incomplete

        # Ends with sentence-terminating punctuation → complete
        if stripped[-1] in ".?!":
            return True

        # Long enough to be a complete thought
        if len(words) >= 7:
            return True

        # If err_incomplete: default to waiting
        return not self._st_cfg.err_incomplete

    # ──────────────────────────────────────────────────── inference ──────

    async def _transcribe_async(self, audio_bytes: bytes) -> str | None:
        if not self._model or len(audio_bytes) < 3200:
            return None
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self._transcribe_sync,
            audio_bytes,
        )

    def _transcribe_sync(self, audio_bytes: bytes) -> str:
        model = self._model
        if model is None:
            return ""

        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = model.transcribe(
            samples,
            language=self._cfg.language,
            beam_size=self._cfg.beam_size,
            vad_filter=False,  # We have our own VAD
        )
        return " ".join(seg.text for seg in segments).strip()

    # ──────────────────────────────────────────────────── cleanup ─────────

    def _cancel_pending_turn_task(self, *, force: bool = False) -> bool:
        if (
            self._smart_turn_task
            and not self._smart_turn_task.done()
            and (force or self._turn_active)
        ):
            self._smart_turn_task.cancel()
            self._smart_turn_task = None
            return True
        return False

    def _cancel_smart_turn_task(self) -> None:
        self._cancel_pending_turn_task(force=True)

    async def cleanup(self) -> None:
        self._cancel_smart_turn_task()
        self._executor.shutdown(wait=False)
        await super().cleanup()
