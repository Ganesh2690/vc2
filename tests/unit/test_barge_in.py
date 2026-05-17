"""Unit tests for BargeInController."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterruptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.agent.barge_in import BargeInController


def _make_config(confirmation_frames=3, min_speech_ms=150, cooldown_ms=500):
    return SimpleNamespace(
        confirmation_frames=confirmation_frames,
        min_speech_ms=min_speech_ms,
        cooldown_ms=cooldown_ms,
    )


def _make_controller(cfg=None):
    if cfg is None:
        cfg = _make_config()
    ctrl = BargeInController(config=cfg)
    ctrl.push_frame = AsyncMock()
    return ctrl


@pytest.mark.asyncio
async def test_not_armed_by_default():
    """Barge-in does nothing when not armed."""
    ctrl = _make_controller()
    assert not ctrl._armed


@pytest.mark.asyncio
async def test_armed_on_bot_started_speaking():
    ctrl = _make_controller()
    await ctrl.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    assert ctrl._armed


@pytest.mark.asyncio
async def test_disarmed_on_bot_stopped_speaking():
    ctrl = _make_controller()
    await ctrl.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await ctrl.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
    assert not ctrl._armed


@pytest.mark.asyncio
async def test_no_interrupt_when_not_armed():
    ctrl = _make_controller()
    # Sends 5 UserStartedSpeakingFrames without arming
    for _ in range(5):
        await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # Should NOT have emitted InterruptionFrame
    calls = [call.args[0] for call in ctrl.push_frame.call_args_list]
    assert not any(isinstance(c, InterruptionFrame) for c in calls)


@pytest.mark.asyncio
async def test_interrupt_fires_after_confirmation_frames():
    """Interrupt should fire after confirmation_frames consecutive frames."""
    cfg = _make_config(confirmation_frames=2, min_speech_ms=0)
    ctrl = _make_controller(cfg)

    await ctrl.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    assert ctrl._armed

    # Send enough UserStartedSpeakingFrames to reach confirmation_frames
    for _ in range(2):
        await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    calls = [call.args[0] for call in ctrl.push_frame.call_args_list]
    assert any(isinstance(c, InterruptionFrame) for c in calls)


@pytest.mark.asyncio
async def test_consecutive_count_resets_on_stop():
    ctrl = _make_controller()
    await ctrl.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    # Reset
    await ctrl.process_frame(UserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert ctrl._consecutive_frames == 0


@pytest.mark.asyncio
async def test_cooldown_prevents_double_interrupt():
    """Second interrupt within cooldown window should be suppressed."""
    cfg = _make_config(confirmation_frames=1, min_speech_ms=0, cooldown_ms=5000)
    ctrl = _make_controller(cfg)

    await ctrl.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    # First interrupt
    await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    # At this point _in_cooldown should be True — rearm and try again
    ctrl._armed = True
    ctrl._consecutive_frames = 0
    ctrl._speech_started_at = None
    # Second interrupt immediately — should be blocked by cooldown
    await ctrl.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    interrupts = [
        call.args[0]
        for call in ctrl.push_frame.call_args_list
        if isinstance(call.args[0], InterruptionFrame)
    ]
    assert len(interrupts) == 1  # only one interrupt should have fired
