"""Metrics collector — intercepts pipeline frames and emits structured logs.

All 7 latency metrics (per turn):
  1. STT latency         (TranscriptionFrame emit − VAD speech end)
  2. LLM TTFT            (first LLM token − LLM call dispatch)
  3. LLM total gen       (LLMFullResponseEndFrame − LLM call dispatch)
  4. TTS first-audio     (first AudioRawFrame from TTS − TextFrame received)
  5. End-to-end          (first audio out − VAD speech end)
  6. Barge-in detection  (InterruptFrame − first VAD-positive frame)
  7. Chunk count per turn

At session end, p50/p95 aggregates are logged as a structured summary.
"""
from __future__ import annotations

import time
from typing import Optional

import structlog

from pipecat.frames.frames import (
    AudioRawFrame,
    BotStartedSpeakingFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice_agent.frames import InterruptFrame, MetricFrame
from voice_agent.llm.chunker import TextChunker  # for chunk-count signal

log = structlog.get_logger(__name__)


def _p50_p95(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    p50 = sorted_v[int(n * 0.5)]
    p95 = sorted_v[min(int(n * 0.95), n - 1)]
    return round(p50, 1), round(p95, 1)


class MetricsCollector(FrameProcessor):
    """Intercepts frames and records latency timestamps per turn."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self._session_id = session_id
        self._turn_id = 0

        # Per-turn timestamps
        self._vad_end: Optional[float] = None
        self._stt_emit: Optional[float] = None
        self._llm_dispatch: Optional[float] = None
        self._llm_first_token: Optional[float] = None
        self._tts_text_recv: Optional[float] = None
        self._tts_first_audio: Optional[float] = None
        self._bargein_start: Optional[float] = None
        self._first_audio_out: Optional[float] = None
        self._speaking_started: Optional[float] = None
        self._chunk_count = 0

        # Session aggregates
        self._stt_latencies: list[float] = []
        self._llm_ttft_latencies: list[float] = []
        self._llm_total_latencies: list[float] = []
        self._tts_first_latencies: list[float] = []
        self._e2e_latencies: list[float] = []
        self._bargein_latencies: list[float] = []
        self._chunk_counts: list[int] = []

        self._start_time = time.monotonic()

    # ──────────────────────────────────────────────── frame processing ──

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        now = time.monotonic()

        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, UserStartedSpeakingFrame):
                self._bargein_start = now

            elif isinstance(frame, UserStoppedSpeakingFrame):
                self._vad_end = now

            elif isinstance(frame, TranscriptionFrame):
                self._stt_emit = now
                self._turn_id += 1
                self._chunk_count = 0
                if self._vad_end:
                    ms = (now - self._vad_end) * 1000
                    self._stt_latencies.append(ms)
                    await self._emit("stt_latency_ms", ms)

            elif isinstance(frame, LLMFullResponseStartFrame):
                self._llm_dispatch = now
                self._llm_first_token = None

            elif isinstance(frame, AudioRawFrame) and self._tts_text_recv:
                if self._tts_first_audio is None:
                    self._tts_first_audio = now
                    ms = (now - self._tts_text_recv) * 1000
                    self._tts_first_latencies.append(ms)
                    await self._emit("tts_first_audio_ms", ms)

                    if self._vad_end:
                        e2e = (now - self._vad_end) * 1000
                        self._e2e_latencies.append(e2e)
                        await self._emit("e2e_latency_ms", e2e)

            elif isinstance(frame, LLMFullResponseEndFrame):
                if self._llm_dispatch:
                    ms = (now - self._llm_dispatch) * 1000
                    self._llm_total_latencies.append(ms)
                    await self._emit("llm_total_ms", ms)
                    await self._emit("chunk_count", float(self._chunk_count))
                    self._chunk_counts.append(self._chunk_count)
                self._tts_text_recv = now  # TTS starts receiving after LLM ends

            elif isinstance(frame, InterruptFrame):
                if self._bargein_start:
                    ms = frame.elapsed_ms
                    self._bargein_latencies.append(ms)
                    await self._emit("bargein_detection_ms", ms)

        elif direction == FrameDirection.UPSTREAM:
            if isinstance(frame, BotStartedSpeakingFrame):
                self._speaking_started = now
                self._tts_first_audio = None

        await self.push_frame(frame, direction)

    # Track first LLM token
    async def _track_llm_token(self, now: float) -> None:
        if self._llm_first_token is None and self._llm_dispatch:
            self._llm_first_token = now
            ms = (now - self._llm_dispatch) * 1000
            self._llm_ttft_latencies.append(ms)
            await self._emit("llm_ttft_ms", ms)

    async def _emit(self, metric_name: str, value_ms: float) -> None:
        log.info(
            "metric",
            metric=metric_name,
            value=round(value_ms, 1),
            session_id=self._session_id,
            turn_id=self._turn_id,
        )
        await self.push_frame(
            MetricFrame(
                metric_name=metric_name,
                value_ms=value_ms,
                session_id=self._session_id,
                turn_id=self._turn_id,
            ),
            FrameDirection.DOWNSTREAM,
        )

    def session_summary(self) -> dict:
        uptime = round((time.monotonic() - self._start_time), 1)
        stt_p50, stt_p95 = _p50_p95(self._stt_latencies)
        ttft_p50, ttft_p95 = _p50_p95(self._llm_ttft_latencies)
        total_p50, total_p95 = _p50_p95(self._llm_total_latencies)
        tts_p50, tts_p95 = _p50_p95(self._tts_first_latencies)
        e2e_p50, e2e_p95 = _p50_p95(self._e2e_latencies)
        bi_p50, bi_p95 = _p50_p95(self._bargein_latencies)

        summary = {
            "event": "session_summary",
            "session_id": self._session_id,
            "uptime_secs": uptime,
            "total_turns": self._turn_id,
            "bargein_count": len(self._bargein_latencies),
            "stt_latency_p50_ms": stt_p50,
            "stt_latency_p95_ms": stt_p95,
            "llm_ttft_p50_ms": ttft_p50,
            "llm_ttft_p95_ms": ttft_p95,
            "llm_total_p50_ms": total_p50,
            "llm_total_p95_ms": total_p95,
            "tts_first_audio_p50_ms": tts_p50,
            "tts_first_audio_p95_ms": tts_p95,
            "e2e_p50_ms": e2e_p50,
            "e2e_p95_ms": e2e_p95,
            "bargein_detection_p50_ms": bi_p50,
            "bargein_detection_p95_ms": bi_p95,
        }
        log.info(**summary)
        return summary
