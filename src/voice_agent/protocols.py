"""Typing protocols (structural interfaces) for all provider adapters.

Any class with matching method signatures satisfies the protocol — no
inheritance required.  Pipeline code imports from here and never
couples to concrete provider implementations.
"""
from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class STTAdapter(Protocol):
    """Streaming speech-to-text provider interface."""

    async def initialize(self) -> None:
        """Load model and run warm-up inference."""
        ...

    async def transcribe(self, audio_bytes: bytes, *, final: bool = False) -> str | None:
        """Transcribe raw 16-bit PCM audio at 16 kHz.

        Returns the transcribed text or ``None`` if nothing was detected.
        ``final`` signals this is the last chunk for the current turn.
        """
        ...

    async def cleanup(self) -> None:
        """Release resources."""
        ...


@runtime_checkable
class LLMAdapter(Protocol):
    """Streaming large-language-model provider interface."""

    async def stream(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 300,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> AsyncIterator[str]:
        """Yield text tokens from the model given a messages list."""
        ...

    async def cancel(self) -> None:
        """Cancel an in-flight streaming request."""
        ...


@runtime_checkable
class TTSAdapter(Protocol):
    """Streaming text-to-speech provider interface."""

    async def initialize(self) -> None:
        """Load voice model and warm-up synthesis."""
        ...

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw 16-bit PCM audio chunks for *text*."""
        ...

    def cancel(self) -> None:
        """Interrupt any in-flight synthesis."""
        ...

    async def cleanup(self) -> None:
        """Release resources."""
        ...


@runtime_checkable
class TransportAdapter(Protocol):
    """Session transport provider interface."""

    async def connect(self, room_name: str, token: str) -> None:
        """Join or create a LiveKit room."""
        ...

    async def disconnect(self) -> None:
        """Leave the room gracefully."""
        ...

    async def send_data(self, payload: dict) -> None:
        """Send a JSON payload over the data channel to the browser client."""
        ...
