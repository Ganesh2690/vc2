"""Piper TTS adapter — wraps piper-tts Python binding.

Pipeline position: receives TextFrame phrases from the TextChunker;
emits TTSStartedFrame, AudioRawFrame chunks, TTSStoppedFrame.

Key behaviours:
- Synthesis runs in a thread pool (ONNX is synchronous).
- cancel() stops any in-flight synthesis immediately by setting a flag.
- Falls back to a pre-synthesised WAV on failure.
- Emits one AudioRawFrame per Piper audio chunk (~2048 samples).
"""
from __future__ import annotations

import asyncio
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import structlog
from pipecat.frames.frames import (
    CancelFrame,
    Frame,
    SystemFrame,
    TextFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice_agent.config import TTSConfig

log = structlog.get_logger(__name__)

_PIPER_CHUNK_SAMPLES = 2048  # samples per emitted AudioRawFrame


class PiperTTSService(FrameProcessor):
    """Synthesises audio from phrase TextFrames using piper-tts."""

    def __init__(self, config: TTSConfig) -> None:
        super().__init__()
        self._cfg = config
        self._voice: Any | None = None  # loaded in initialize()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")
        self._cancelled = False
        self._fallback_audio: bytes | None = None

    # ─────────────────────────────────────────────────── initialisation ──

    async def initialize(self) -> None:
        """Load Piper voice model and run a warm-up synthesis."""
        from piper import PiperVoice

        model_path = Path(self._cfg.model_path)
        config_path = Path(self._cfg.config_path)

        if not model_path.exists():
            raise FileNotFoundError(
                f"Piper model not found: {model_path}\n"
                "Download from https://github.com/rhasspy/piper/releases"
            )

        log.info("loading_tts_model", model=str(model_path))
        loop = asyncio.get_running_loop()

        def _load_voice() -> Any:
            return cast(
                Any,
                PiperVoice.load(
                    str(model_path),
                    config_path=str(config_path) if config_path.exists() else None,
                    use_cuda=False,  # Piper uses ONNX — CUDA handled automatically
                ),
            )

        self._voice = await loop.run_in_executor(
            self._executor,
            _load_voice,
        )

        # Warm up
        await self._synthesize_async("Hello.")
        log.info("tts_model_ready")

        # Pre-load fallback WAV
        self._load_fallback_wav()

    def _load_fallback_wav(self) -> None:
        path = Path(self._cfg.fallback_wav_path)
        if path.exists():
            try:
                with wave.open(str(path), "rb") as wf:
                    self._fallback_audio = wf.readframes(wf.getnframes())
                log.debug("fallback_wav_loaded", path=str(path))
            except Exception as exc:
                log.warning("fallback_wav_load_error", error=str(exc))

    # ──────────────────────────────────────────────── frame processing ──

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, SystemFrame):
            # System frames (CancelFrame, EndFrame …) bypass synthesis
            if isinstance(frame, CancelFrame):
                self.cancel()
            await self.push_frame(frame, direction)
            return

        if direction == FrameDirection.UPSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TextFrame) and frame.text.strip():
            await self._handle_text(frame.text)
        else:
            await self.push_frame(frame, direction)

    # ─────────────────────────────────────────────────────── synthesis ──

    async def _handle_text(self, text: str) -> None:
        self._cancelled = False
        t0 = time.monotonic()
        log.info("tts_synthesis_start", chars=len(text), text=text[:80])

        await self.push_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)

        try:
            await self._stream_synthesis(text, t0)
        except Exception as exc:
            log.error("tts_synthesis_error", error=str(exc))
            await self._play_fallback()
        finally:
            await self.push_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
            elapsed = (time.monotonic() - t0) * 1000
            log.info("tts_synthesis_complete", value=elapsed, text=text[:80])

    async def _stream_synthesis(self, text: str, t0: float) -> None:
        """Run synthesis in thread pool and stream audio frames."""
        first_chunk = True
        loop = asyncio.get_event_loop()

        # Get chunk iterator from thread pool
        chunks: list[bytes] = await loop.run_in_executor(
            self._executor,
            self._synthesize_phrase,
            text,
        )

        for chunk in chunks:
            if self._cancelled:
                log.debug("tts_cancelled_mid_stream")
                return
            if first_chunk:
                elapsed = (time.monotonic() - t0) * 1000
                log.info("tts_first_audio_ms", value=elapsed, text=text[:40])
                first_chunk = False

            await self.push_frame(
                TTSAudioRawFrame(
                    audio=chunk,
                    sample_rate=self._cfg.sample_rate,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )

    def _synthesize_phrase(self, text: str) -> list[bytes]:
        """Synthesise a phrase to a list of raw PCM chunks (blocking)."""
        voice = self._voice
        if voice is None:
            return []

        chunks: list[bytes] = []
        buffer = bytearray()

        for audio_chunk in voice.synthesize(text):
            if self._cancelled:
                break
            buffer.extend(audio_chunk.audio_int16_bytes)
            # Emit fixed-size chunks
            while len(buffer) >= _PIPER_CHUNK_SAMPLES * 2:
                chunk = bytes(buffer[: _PIPER_CHUNK_SAMPLES * 2])
                buffer = buffer[_PIPER_CHUNK_SAMPLES * 2 :]
                chunks.append(chunk)

        # Remaining samples
        if buffer and not self._cancelled:
            chunks.append(bytes(buffer))

        return chunks

    async def _synthesize_async(self, text: str) -> list[bytes]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._synthesize_phrase, text)

    async def _play_fallback(self) -> None:
        if self._fallback_audio:
            await self.push_frame(
                TTSAudioRawFrame(
                    audio=self._fallback_audio,
                    sample_rate=self._cfg.sample_rate,
                    num_channels=1,
                ),
                FrameDirection.DOWNSTREAM,
            )

    def cancel(self) -> None:
        """Interrupt in-flight synthesis immediately."""
        self._cancelled = True

    async def cleanup(self) -> None:
        self.cancel()
        self._executor.shutdown(wait=False)
        await super().cleanup()
