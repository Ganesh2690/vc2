"""Text chunker — converts a stream of LLM tokens into TTS-ready phrases.

Sits between the LLM service and the TTS service.
Receives ``TextFrame`` tokens; emits ``TextFrame`` complete phrases.

Splitting rules (all thresholds are YAML-configurable):
- Split on `.?!;:` (sentence terminators) — always.
- Split on `,` when the current buffer exceeds ``comma_threshold`` chars.
- Force flush when buffer exceeds ``max_chars`` (split at last space).
- Suppress chunks shorter than ``min_chars`` (buffer and accumulate).
- Strip markdown tokens and replace code blocks with a spoken phrase.
"""
from __future__ import annotations

import re
import structlog

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voice_agent.config import ChunkerConfig

log = structlog.get_logger(__name__)

# ── Markdown stripping patterns ───────────────────────────────────────────────

_RE_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_RE_INLINE_CODE = re.compile(r"`[^`]+`")
_RE_BOLD_ITALIC = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_RE_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_RE_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_RE_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RE_SENTENCE_END = re.compile(r"(?<![A-Z][a-z]\.)(?<![Dd]r\.)(?<![Mm]r\.)(?<!\d)[.?!;:]")

_CODE_BLOCK_REPLACEMENT = "I'd share some code, but this is a voice conversation."


def strip_markdown(text: str) -> str:
    """Remove markdown formatting from LLM output before it reaches TTS."""
    # Replace code blocks first (largest construct)
    text = _RE_CODE_BLOCK.sub(_CODE_BLOCK_REPLACEMENT, text)
    text = _RE_INLINE_CODE.sub(lambda m: m.group(0)[1:-1], text)
    # Bold / italic → plain
    text = _RE_BOLD_ITALIC.sub(r"\1", text)
    # Headings → plain
    text = _RE_HEADING.sub("", text)
    # Bullet points — convert to spoken "first, ...; second, ..." list
    ordinals = ["first", "second", "third", "fourth", "fifth",
                "sixth", "seventh", "eighth", "ninth", "tenth"]
    result_lines: list[str] = []
    bullet_group: list[str] = []

    def _flush_bullets() -> None:
        if not bullet_group:
            return
        parts = []
        for i, item in enumerate(bullet_group):
            word = ordinals[i] if i < len(ordinals) else f"item {i + 1}"
            parts.append(f"{word}, {item}")
        result_lines.append("; ".join(parts))
        bullet_group.clear()

    for line in text.split("\n"):
        if _RE_BULLET.match(line):
            bullet_group.append(_RE_BULLET.sub("", line).strip())
        else:
            _flush_bullets()
            result_lines.append(line)
    _flush_bullets()
    text = "\n".join(result_lines)

    # Links → display text only
    text = _RE_LINK.sub(r"\1", text)
    # Collapse extra whitespace
    text = re.sub(r"\n{2,}", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


class TextChunker(FrameProcessor):
    """Buffers LLM tokens and emits complete phrase TextFrames for TTS."""

    def __init__(self, config: ChunkerConfig) -> None:
        super().__init__()
        self._cfg = config
        self._buffer = ""
        self._chunk_count = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if direction != FrameDirection.DOWNSTREAM:
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._chunk_count = 0
            await self.push_frame(frame, direction)

        elif isinstance(frame, TextFrame):
            await self._accumulate(frame.text)

        elif isinstance(frame, LLMFullResponseEndFrame):
            # Flush remaining buffer on response end
            await self._flush(force=True)
            self._buffer = ""
            await self.push_frame(frame, direction)

        else:
            await self.push_frame(frame, direction)

    # ──────────────────────────────────────────────────── core logic ────

    async def _accumulate(self, token: str) -> None:
        self._buffer += token

        if self._cfg.strip_markdown:
            # Only strip when we have a candidate chunk to emit
            pass

        # Check sentence terminators
        if _RE_SENTENCE_END.search(self._buffer):
            await self._flush(force=False)
            return

        # Comma split when buffer is long enough
        if "," in self._buffer and len(self._buffer) >= self._cfg.comma_threshold:
            await self._flush(force=False, split_on_comma=True)
            return

        # Hard max
        if len(self._buffer) >= self._cfg.max_chars:
            await self._flush(force=True)

    async def _flush(self, *, force: bool, split_on_comma: bool = False) -> None:
        """Try to split the buffer at a phrase boundary and emit a chunk."""
        text = self._buffer

        if not text.strip():
            return

        split_pos = -1

        if not force:
            # Try sentence-end boundary
            m = list(_RE_SENTENCE_END.finditer(text))
            if m:
                split_pos = m[-1].end()
            elif split_on_comma:
                comma_pos = text.rfind(",")
                if comma_pos > 0:
                    split_pos = comma_pos + 1

        if force and split_pos < 0:
            # Split at last space to avoid cutting mid-word
            space_pos = text.rfind(" ")
            split_pos = space_pos if space_pos > 0 else len(text)

        if split_pos > 0:
            chunk = text[:split_pos]
            remainder = text[split_pos:]
        else:
            if len(text) >= self._cfg.min_chars:
                chunk = text
                remainder = ""
            else:
                return

        chunk = chunk.strip()
        if self._cfg.strip_markdown:
            chunk = strip_markdown(chunk)

        if force or len(chunk) >= self._cfg.min_chars:
            self._chunk_count += 1
            log.debug("tts_chunk", n=self._chunk_count, chars=len(chunk))
            await self.push_frame(
                TextFrame(text=chunk),
                FrameDirection.DOWNSTREAM,
            )

        self._buffer = remainder.strip()
