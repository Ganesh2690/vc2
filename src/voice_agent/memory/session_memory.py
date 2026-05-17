"""Conversation memory — in-memory sliding window for the LLM context.

Stores the last N turns as a native OpenAI messages list.
Applies a tiktoken hard budget so the context never overflows.
Interrupted agent turns (barge-in) are NOT appended.
"""
from __future__ import annotations

import time
from typing import Any

import structlog
import tiktoken

log = structlog.get_logger(__name__)


class SessionMemory:
    """Session-scoped turn history with tiktoken budget management."""

    def __init__(
        self,
        system_prompt: str,
        max_turns: int = 10,
        max_context_tokens: int = 4000,
        max_response_tokens: int = 300,
        model_name: str = "gpt-4o",  # close enough for tiktoken encoding
    ) -> None:
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._max_context_tokens = max_context_tokens
        self._max_response_tokens = max_response_tokens

        try:
            self._enc = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self._enc = tiktoken.get_encoding("cl100k_base")

        # Turn history: list of {"role": ..., "content": ..., "_tokens": int}
        self._turns: list[dict[str, Any]] = []
        self._total_tokens = 0

        # System prompt token count
        self._system_tokens = len(self._enc.encode(system_prompt))

    # ──────────────────────────────────────────────── public interface ──

    def get_messages(self) -> list[dict[str, str]]:
        """Return the full message list (system + turns) for an LLM call."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        messages.extend(
            {"role": t["role"], "content": t["content"]} for t in self._turns
        )
        return messages

    def append_user(self, text: str) -> None:
        """Append a user utterance (on TranscriptionFrame)."""
        self._append("user", text)

    def append_assistant(self, text: str) -> None:
        """Append a fully delivered assistant turn (on TurnCompleteFrame).

        Interrupted / partial turns must NOT be appended.
        """
        self._append("assistant", text)

    @property
    def turn_count(self) -> int:
        """Number of complete conversation turns (user+assistant pairs)."""
        return len(self._turns) // 2

    def clear(self) -> None:
        self._turns.clear()
        self._total_tokens = 0

    # ──────────────────────────────────────────────── internal helpers ──

    def _append(self, role: str, content: str) -> None:
        tokens = len(self._enc.encode(content))
        self._turns.append({"role": role, "content": content, "_tokens": tokens})
        self._total_tokens += tokens
        self._trim()
        log.debug("memory_append", role=role, tokens=tokens, total=self.turn_count)

    def _trim(self) -> None:
        """Remove oldest turns until within budget (turns + tokens)."""
        # Hard turn limit
        while len(self._turns) > self._max_turns * 2:  # *2 → user+assistant pairs
            self._drop_oldest()

        # Token budget
        budget = self._max_context_tokens - self._max_response_tokens - self._system_tokens
        while self._total_tokens > budget and self._turns:
            self._drop_oldest()

    def _drop_oldest(self) -> None:
        if self._turns:
            dropped = self._turns.pop(0)
            self._total_tokens -= dropped["_tokens"]
            log.debug("memory_trim", dropped_role=dropped["role"])

    def session_summary(self, metrics: dict | None = None) -> dict:
        """Structured summary for session end."""
        summary: dict = {
            "event": "session_end",
            "turn_count": self.turn_count,
            "memory_tokens": self._total_tokens,
        }
        if metrics:
            summary.update(metrics)
        return summary
