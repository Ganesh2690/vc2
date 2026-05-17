"""Barge-in controller.

Pipeline position: immediately after transport.input().

Monitors VAD events during SPEAKING state and requires:
  - 3 consecutive VAD-positive frames   (90 ms at 30 ms frames)
  - 150 ms of sustained speech
before confirming a real interruption.

On confirmation:
  1. Emits ``BotInterruptionFrame`` upstream (pipecat cancels TTS)
  2. Emits ``InterruptFrame`` downstream (state machine picks up)
  3. Applies 500 ms cooldown before re-arming

False triggers (< 3 frames or < 150 ms) are silently discarded.
"""
from __future__ import annotations

import asyncio
import time

import structlog

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice_agent.config import BargeInConfig
from voice_agent.frames import InterruptFrame

log = structlog.get_logger(__name__)


class BargeInController(FrameProcessor):
    """Multi-frame barge-in confirmation with cooldown."""

    def __init__(self, config: BargeInConfig) -> None:
        super().__init__()
        self._cfg = config

        # Arm state
        self._armed = False        # True only during SPEAKING
        self._in_cooldown = False

        # Confirmation state
        self._consecutive_frames = 0
        self._speech_started_at: float | None = None

    # ──────────────────────────────────────────────── frame processing ──

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM:
            await self._handle_downstream(frame, direction)
        else:
            await self._handle_upstream(frame, direction)

    async def _handle_downstream(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, (UserStartedSpeakingFrame, VADUserStartedSpeakingFrame)):
            if self._armed and not self._in_cooldown:
                # Increment consecutive frame counter; record start time on first frame
                self._consecutive_frames += 1
                if self._speech_started_at is None:
                    self._speech_started_at = time.monotonic()
                log.debug("bargein_candidate_frame", count=self._consecutive_frames)
            # Always forward the frame
            await self.push_frame(frame, direction)

        elif isinstance(frame, (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)):
            # Reset confirmation state — user stopped before confirmation threshold
            if self._consecutive_frames > 0 and self._speech_started_at is not None:
                elapsed_ms = (time.monotonic() - self._speech_started_at) * 1000
                if elapsed_ms < self._cfg.min_speech_ms:
                    log.debug(
                        "bargein_false_trigger",
                        frames=self._consecutive_frames,
                        elapsed_ms=elapsed_ms,
                    )
            self._consecutive_frames = 0
            self._speech_started_at = None
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

        # Check if a buffered VAD-active signal should fire confirmation
        await self._check_confirmation()

    async def _handle_upstream(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, BotStartedSpeakingFrame):
            self._arm()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._disarm()
        await self.push_frame(frame, direction)

    # ──────────────────────────────────────────────── arm / disarm ───────

    def _arm(self) -> None:
        self._armed = True
        self._consecutive_frames = 0
        self._speech_started_at = None
        log.debug("bargein_armed")

    def _disarm(self) -> None:
        self._armed = False
        self._consecutive_frames = 0
        self._speech_started_at = None
        log.debug("bargein_disarmed")

    # ──────────────────────────────────────────── confirmation logic ─────

    async def _check_confirmation(self) -> None:
        if not self._armed or self._in_cooldown:
            return
        if self._consecutive_frames < self._cfg.confirmation_frames:
            return
        if self._speech_started_at is None:
            return

        elapsed_ms = (time.monotonic() - self._speech_started_at) * 1000
        if elapsed_ms < self._cfg.min_speech_ms:
            # Need more speech duration — increment and keep waiting
            self._consecutive_frames += 1
            return

        # ✅ Confirmed barge-in
        log.info(
            "bargein_confirmed",
            frames=self._consecutive_frames,
            elapsed_ms=round(elapsed_ms, 1),
        )
        self._disarm()
        self._in_cooldown = True

        # 1. Cancel TTS + LLM (upstream)
        await self.push_frame(InterruptionFrame(), FrameDirection.UPSTREAM)
        # 2. Notify state machine (downstream)
        await self.push_frame(
            InterruptFrame(elapsed_ms=elapsed_ms),
            FrameDirection.DOWNSTREAM,
        )

        # Apply cooldown (guard against no-loop in tests)
        try:
            asyncio.get_running_loop()
            asyncio.create_task(self._cooldown())
        except RuntimeError:
            self._in_cooldown = False

    async def _cooldown(self) -> None:
        await asyncio.sleep(self._cfg.cooldown_ms / 1000.0)
        self._in_cooldown = False
        log.debug("bargein_cooldown_expired")
