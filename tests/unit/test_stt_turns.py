"""Unit tests for faster-whisper turn handling."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest
from pipecat.frames.frames import AudioRawFrame, TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.config import STTConfig, SmartTurnConfig
from voice_agent.stt.faster_whisper_adapter import FasterWhisperSTTService


def _audio_frame(duration_ms: int = 100) -> AudioRawFrame:
    samples = np.zeros(int(16000 * duration_ms / 1000), dtype=np.int16)
    return AudioRawFrame(audio=samples.tobytes(), sample_rate=16000, num_channels=1)


def _make_service() -> FasterWhisperSTTService:
    service = FasterWhisperSTTService(
        stt_config=STTConfig(inference_cadence_ms=20),
        smart_turn_config=SmartTurnConfig(),
    )
    service.push_frame = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_short_pause_resumes_same_stt_turn():
    service = _make_service()
    service._transcribe_async = AsyncMock(return_value="hello there")

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(_audio_frame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    await asyncio.sleep(0.05)
    assert service._transcribe_async.await_count == 0

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(_audio_frame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    await asyncio.sleep(0.2)

    assert service._transcribe_async.await_count == 1
    transcribed_audio = service._transcribe_async.await_args.args[0]
    assert len(transcribed_audio) == len(_audio_frame().audio) * 2

    pushed_frames = [call.args[0] for call in service.push_frame.call_args_list]
    transcripts = [frame for frame in pushed_frames if isinstance(frame, TranscriptionFrame)]
    assert len(transcripts) == 1
    assert transcripts[0].text == "hello there"


@pytest.mark.asyncio
async def test_new_speech_does_not_cancel_in_flight_final_transcription():
    service = _make_service()
    started = asyncio.Event()

    async def transcribe(audio: bytes) -> str:
        started.set()
        await asyncio.sleep(0.05)
        return "first turn"

    service._transcribe_async = AsyncMock(side_effect=transcribe)

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(_audio_frame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    await asyncio.wait_for(started.wait(), timeout=0.3)
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await asyncio.sleep(0.1)

    pushed_frames = [call.args[0] for call in service.push_frame.call_args_list]
    transcripts = [frame for frame in pushed_frames if isinstance(frame, TranscriptionFrame)]
    assert len(transcripts) == 1
    assert transcripts[0].text == "first turn"
