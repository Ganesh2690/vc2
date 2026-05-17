"""Configuration loader with pydantic validation."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VADConfig(BaseModel):
    threshold: float = 0.5
    min_silence_ms: int = 300
    min_speech_ms: int = 100
    frame_ms: int = 30


class SmartTurnConfig(BaseModel):
    audio_window_secs: float = 3.0
    hard_timeout_secs: float = 3.0
    err_incomplete: bool = True


class STTConfig(BaseModel):
    model: str = "distil-large-v3"
    language: str = "en"
    beam_size: int = 1
    compute_type: str = "auto"
    inference_cadence_ms: int = 500
    pre_speech_buffer_secs: float = 0.5


class LLMConfig(BaseModel):
    model: str = "gpt-5.4-nano-2026-03-17"
    max_tokens: int = 300
    temperature: float = 0.7
    top_p: float = 0.9
    greeting: str = "Hello, I'm ready. How can I help?"
    system_prompt: str = (
        "You are a helpful, concise voice assistant. "
        "Keep responses brief and conversational. "
        "Do not use markdown, bullet points, or code blocks. "
        "Speak naturally as if in a conversation."
    )
    context_turns: int = 10
    max_context_tokens: int = 4000
    retry_delay_secs: float = 1.0


class TTSConfig(BaseModel):
    model_path: str = "models/en_US-lessac-medium.onnx"
    config_path: str = "models/en_US-lessac-medium.onnx.json"
    speaker_id: int | None = None
    phoneme_cache_enabled: bool = True
    fallback_wav_path: str = "assets/fallback.wav"
    sample_rate: int = 22050


class ChunkerConfig(BaseModel):
    min_chars: int = 20
    max_chars: int = 200
    comma_threshold: int = 80
    strip_markdown: bool = True


class BargeInConfig(BaseModel):
    confirmation_frames: int = 3
    min_speech_ms: int = 150
    cooldown_ms: int = 500


class StateMachineConfig(BaseModel):
    processing_timeout_secs: float = 10.0
    degraded_retry_delay_secs: float = 2.0


class TransportConfig(BaseModel):
    audio_in_sample_rate: int = 16000
    audio_out_sample_rate: int = 22050
    audio_in_channels: int = 1
    audio_out_channels: int = 1


class MetricsConfig(BaseModel):
    log_level: str = "INFO"


class ServerConfig(BaseModel):
    host: str = "localhost"
    port: int = 7860
    static_dir: str = "client"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # Required secrets (from .env / environment variables)
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    openai_api_key: str = ""

    # Optional log-level override from env
    log_level: str = ""

    # Sub-configs (populated from YAML, overridable via env)
    vad: VADConfig = Field(default_factory=VADConfig)
    smart_turn: SmartTurnConfig = Field(default_factory=SmartTurnConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)
    barge_in: BargeInConfig = Field(default_factory=BargeInConfig)
    state_machine: StateMachineConfig = Field(default_factory=StateMachineConfig)
    transport: TransportConfig = Field(default_factory=TransportConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_settings(config_path: str | Path | None = None) -> AgentSettings:
    """Load settings from YAML file then overlay environment variables."""
    yaml_data: dict = {}

    if config_path is None:
        env = os.getenv("VOICE_AGENT_ENV", "dev")
        config_path = Path("config") / f"{env}.yaml"

    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path, encoding="utf-8") as fh:
            yaml_data = yaml.safe_load(fh) or {}

    settings = AgentSettings(**yaml_data)

    # Allow LOG_LEVEL env var to override metrics.log_level
    env_log = os.getenv("LOG_LEVEL", "")
    if env_log:
        settings.metrics.log_level = env_log.upper()
    elif settings.log_level:
        settings.metrics.log_level = settings.log_level.upper()

    return settings
