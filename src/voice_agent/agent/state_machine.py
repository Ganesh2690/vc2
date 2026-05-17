"""Conversation state machine with strict whitelist transitions."""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Callable

import structlog

log = structlog.get_logger(__name__)


class ConversationState(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    LISTENING = "LISTENING"
    USER_SPEAKING = "USER_SPEAKING"
    THINKING_PAUSE = "THINKING_PAUSE"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    INTERRUPT_CANDIDATE = "INTERRUPT_CANDIDATE"
    INTERRUPTED = "INTERRUPTED"
    DEGRADED = "DEGRADED"
    SHUTDOWN = "SHUTDOWN"


class InvalidTransitionError(Exception):
    """Raised when a state transition is not in the whitelist."""


# Strict whitelist: only these transitions are legal.
ALLOWED_TRANSITIONS: dict[ConversationState, set[ConversationState]] = {
    ConversationState.INITIALIZING: {
        ConversationState.READY,
        ConversationState.SHUTDOWN,
    },
    ConversationState.READY: {
        ConversationState.LISTENING,
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.LISTENING: {
        ConversationState.USER_SPEAKING,
        ConversationState.SPEAKING,        # next TTS chunk in same assistant response
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.USER_SPEAKING: {
        ConversationState.THINKING_PAUSE,
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.THINKING_PAUSE: {
        ConversationState.USER_SPEAKING,   # Smart Turn: incomplete
        ConversationState.PROCESSING,      # Smart Turn: complete
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.PROCESSING: {
        ConversationState.USER_SPEAKING,   # user continued while LLM/TTS was pending
        ConversationState.THINKING_PAUSE,
        ConversationState.SPEAKING,
        ConversationState.READY,           # cancelled / error
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.SPEAKING: {
        ConversationState.SPEAKING,        # repeated start frame while chunked TTS continues
        ConversationState.INTERRUPT_CANDIDATE,
        ConversationState.READY,           # playback finished
        ConversationState.LISTENING,       # playback finished → back to listen
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.INTERRUPT_CANDIDATE: {
        ConversationState.SPEAKING,        # false trigger
        ConversationState.INTERRUPTED,     # confirmed barge-in
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.INTERRUPTED: {
        ConversationState.USER_SPEAKING,
        ConversationState.LISTENING,
        ConversationState.DEGRADED,
        ConversationState.SHUTDOWN,
    },
    ConversationState.DEGRADED: {
        ConversationState.READY,
        ConversationState.LISTENING,
        ConversationState.USER_SPEAKING,
        ConversationState.THINKING_PAUSE,
        ConversationState.PROCESSING,
        ConversationState.SPEAKING,
        ConversationState.SHUTDOWN,
    },
    ConversationState.SHUTDOWN: set(),
}


class ConversationStateMachine:
    """Thread-safe (asyncio) conversation state machine."""

    def __init__(
        self,
        processing_timeout_secs: float = 10.0,
        degraded_retry_delay_secs: float = 2.0,
    ) -> None:
        self._state = ConversationState.INITIALIZING
        self._processing_timeout_secs = processing_timeout_secs
        self._degraded_retry_delay_secs = degraded_retry_delay_secs
        self._on_state_change: list[Callable] = []
        self._processing_watchdog_task: asyncio.Task | None = None
        self._degraded_retry_count = 0
        self._state_entered_at: float = time.monotonic()

    # ──────────────────────────────────────────────────────── properties ──

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def state_age_secs(self) -> float:
        return time.monotonic() - self._state_entered_at

    # ─────────────────────────────────────────────────── event listeners ──

    def on_state_change(self, callback: Callable) -> None:
        """Register a coroutine or callable for state-change events."""
        self._on_state_change.append(callback)

    # ───────────────────────────────────────────────────── transitions ────

    def transition(self, new_state: ConversationState) -> None:
        """Perform a validated state transition.

        Raises ``InvalidTransitionError`` if the transition is not in the
        whitelist.  In production the pipeline-level handler catches this
        and transitions to DEGRADED.
        """
        allowed = ALLOWED_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Transition {self._state.value} → {new_state.value} is not "
                "in the whitelist"
            )

        previous = self._state
        self._state = new_state
        self._state_entered_at = time.monotonic()

        log.info(
            "state_transition",
            previous=previous.value,
            new=new_state.value,
        )

        # PROCESSING watchdog
        if new_state == ConversationState.PROCESSING:
            self._start_processing_watchdog()
        elif previous == ConversationState.PROCESSING:
            self._cancel_processing_watchdog()

        # Notify all subscribers
        for cb in self._on_state_change:
            if asyncio.iscoroutinefunction(cb):
                try:
                    asyncio.get_running_loop()
                    asyncio.create_task(cb(previous, new_state))
                except RuntimeError:
                    pass  # No running loop — skip async callback in sync context
            else:
                cb(previous, new_state)

    def try_transition(self, new_state: ConversationState) -> bool:
        """Attempt a transition without raising; returns True on success."""
        try:
            self.transition(new_state)
            return True
        except InvalidTransitionError as exc:
            log.warning("invalid_transition_ignored", error=str(exc))
            return False

    # ────────────────────────────────────────────── watchdog / recovery ──

    def _start_processing_watchdog(self) -> None:
        self._cancel_processing_watchdog()
        try:
            loop = asyncio.get_running_loop()
            self._processing_watchdog_task = loop.create_task(
                self._processing_watchdog()
            )
        except RuntimeError:
            # No running event loop (e.g. synchronous test context) — skip watchdog
            pass

    def _cancel_processing_watchdog(self) -> None:
        if self._processing_watchdog_task and not self._processing_watchdog_task.done():
            self._processing_watchdog_task.cancel()
        self._processing_watchdog_task = None

    async def _processing_watchdog(self) -> None:
        await asyncio.sleep(self._processing_timeout_secs)
        if self._state == ConversationState.PROCESSING:
            log.warning(
                "processing_watchdog_fired",
                timeout_secs=self._processing_timeout_secs,
            )
            self.try_transition(ConversationState.DEGRADED)

    async def attempt_degraded_recovery(self) -> bool:
        """Attempt to recover from DEGRADED.

        Makes exactly one retry attempt.  If it succeeds, resets the counter
        and returns True.  On second failure, transitions to SHUTDOWN and
        returns False.
        """
        self._degraded_retry_count += 1
        log.info(
            "degraded_recovery_attempt",
            attempt=self._degraded_retry_count,
            delay_secs=self._degraded_retry_delay_secs,
        )
        await asyncio.sleep(self._degraded_retry_delay_secs)

        if self._degraded_retry_count <= 1:
            if self.try_transition(ConversationState.READY):
                self._degraded_retry_count = 0
                log.info("degraded_recovery_succeeded")
                return True

        log.error(
            "degraded_recovery_failed",
            attempts=self._degraded_retry_count,
        )
        self.try_transition(ConversationState.SHUTDOWN)
        return False
