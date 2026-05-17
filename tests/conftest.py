"""Shared pytest fixtures."""
from __future__ import annotations

import numpy as np
import pytest

from voice_agent.agent.state_machine import ConversationStateMachine
from voice_agent.memory.session_memory import SessionMemory


@pytest.fixture
def sample_config():
    """Minimal AgentSettings-like namespace (avoids env dependency in unit tests)."""
    from types import SimpleNamespace
    cfg = SimpleNamespace(
        vad=SimpleNamespace(threshold=0.5, min_silence_ms=300, min_speech_ms=100),
        smart_turn=SimpleNamespace(
            enabled=True,
            model_path=None,
            timeout_secs=3.0,
            err_toward_incomplete=True,
        ),
        stt=SimpleNamespace(
            model="distil-large-v3",
            language="en",
            beam_size=1,
            inference_cadence_ms=500,
            device="cpu",
            compute_type="int8",
        ),
        llm=SimpleNamespace(
            model="gpt-5.4-nano-2026-03-17",
            system_prompt="You are a helpful voice assistant.",
            max_tokens=300,
            temperature=0.7,
            top_p=0.9,
            context_turns=10,
            max_context_tokens=4000,
        ),
        tts=SimpleNamespace(
            model_path="models/en_US-lessac-medium.onnx",
            speaker=None,
            length_scale=1.0,
            fallback_wav="assets/fallback.wav",
        ),
        chunker=SimpleNamespace(
            min_chars=20,
            max_chars=200,
            comma_threshold=80,
        ),
        barge_in=SimpleNamespace(
            confirmation_frames=3,
            min_speech_ms=150,
            cooldown_ms=500,
        ),
        state_machine=SimpleNamespace(
            processing_timeout_secs=10,
            degraded_retry_delay_secs=1,
        ),
    )
    return cfg


@pytest.fixture
def sample_audio_frame():
    """30 ms of silence as 16-bit PCM bytes (16 kHz, mono)."""
    samples = np.zeros(480, dtype=np.int16)  # 480 samples = 30 ms @ 16 kHz
    return samples.tobytes()


@pytest.fixture
def sample_transcription():
    return "Hello, can you help me with something?"


@pytest.fixture
def state_machine():
    return ConversationStateMachine(
        processing_timeout_secs=10,
        degraded_retry_delay_secs=1,
    )


@pytest.fixture
def memory_store():
    return SessionMemory(
        system_prompt="You are a helpful assistant.",
        max_turns=10,
        max_context_tokens=4000,
        max_response_tokens=300,
    )
