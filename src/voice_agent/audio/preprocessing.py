"""Audio preprocessing: resampling and pre-speech ring buffer."""
from __future__ import annotations

import struct
from collections import deque

import numpy as np
from scipy.signal import resample_poly


def resample_48k_to_16k(pcm_48k: bytes) -> bytes:
    """Resample 48 kHz 16-bit mono PCM to 16 kHz.

    Called once per incoming LiveKit audio frame at the transport boundary
    so all downstream stages (VAD, STT) receive consistent 16 kHz audio.
    """
    # Convert bytes → int16 → float32 in [−1, 1]
    samples = np.frombuffer(pcm_48k, dtype=np.int16).astype(np.float32) / 32768.0

    # 48000 / 16000 = 3/1 downsample ratio
    resampled = resample_poly(samples, up=1, down=3)

    # Clip and convert back to int16 bytes
    resampled = np.clip(resampled, -1.0, 1.0)
    return (resampled * 32767).astype(np.int16).tobytes()


def pcm_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """Convert raw 16-bit PCM bytes to float32 numpy array in [−1, 1]."""
    return np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0


class RingBuffer:
    """Fixed-size ring buffer that stores raw PCM bytes (pre-speech audio)."""

    def __init__(self, max_seconds: float, sample_rate: int = 16000) -> None:
        # Each sample is 2 bytes (int16)
        self._max_bytes = int(max_seconds * sample_rate * 2)
        self._buf: deque[bytes] = deque()
        self._size = 0

    def push(self, chunk: bytes) -> None:
        """Add a chunk; drop oldest bytes if buffer is full."""
        self._buf.append(chunk)
        self._size += len(chunk)
        while self._size > self._max_bytes and self._buf:
            dropped = self._buf.popleft()
            self._size -= len(dropped)

    def drain(self) -> bytes:
        """Return all buffered bytes and clear the buffer."""
        data = b"".join(self._buf)
        self._buf.clear()
        self._size = 0
        return data

    def peek(self) -> bytes:
        """Return all buffered bytes without clearing."""
        return b"".join(self._buf)

    @property
    def size_bytes(self) -> int:
        return self._size
