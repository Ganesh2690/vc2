"""Unit tests for Piper TTS frame emission."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import TTSAudioRawFrame, TextFrame
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.config import TTSConfig
from voice_agent.tts.piper_adapter import PiperTTSService


@pytest.mark.asyncio
async def test_piper_emits_tts_audio_raw_frames():
    service = PiperTTSService(config=TTSConfig())
    service.push_frame = AsyncMock()
    service._synthesize_phrase = lambda text: [b"\x00\x00" * 2048]

    await service.process_frame(TextFrame(text="Hello."), FrameDirection.DOWNSTREAM)

    pushed_frames = [call.args[0] for call in service.push_frame.call_args_list]
    audio_frames = [frame for frame in pushed_frames if isinstance(frame, TTSAudioRawFrame)]

    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == service._cfg.sample_rate
    assert audio_frames[0].num_channels == 1
