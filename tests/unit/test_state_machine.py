"""Unit tests for ConversationStateMachine."""
from __future__ import annotations

import asyncio

import pytest

from voice_agent.agent.state_machine import (
    ConversationState,
    InvalidTransitionError,
)

S = ConversationState


def test_initial_state(state_machine):
    assert state_machine.state == S.INITIALIZING


def test_valid_transition(state_machine):
    state_machine.transition(S.READY)
    assert state_machine.state == S.READY


def test_invalid_transition_raises(state_machine):
    with pytest.raises(InvalidTransitionError):
        state_machine.transition(S.SPEAKING)


def test_try_transition_returns_false_on_invalid(state_machine):
    result = state_machine.try_transition(S.SPEAKING)
    assert result is False
    assert state_machine.state == S.INITIALIZING


def test_try_transition_returns_true_on_valid(state_machine):
    result = state_machine.try_transition(S.READY)
    assert result is True


def test_full_happy_path(state_machine):
    transitions = [
        S.READY,
        S.LISTENING,
        S.USER_SPEAKING,
        S.THINKING_PAUSE,
        S.PROCESSING,
        S.SPEAKING,
        S.LISTENING,
    ]
    for target in transitions:
        state_machine.transition(target)
    assert state_machine.state == S.LISTENING


def test_assistant_can_continue_speaking_after_chunk_gap(state_machine):
    state_machine.transition(S.READY)
    state_machine.transition(S.LISTENING)
    state_machine.transition(S.SPEAKING)
    state_machine.transition(S.SPEAKING)
    assert state_machine.state == S.SPEAKING


def test_processing_accepts_user_continuation(state_machine):
    state_machine.transition(S.READY)
    state_machine.transition(S.LISTENING)
    state_machine.transition(S.USER_SPEAKING)
    state_machine.transition(S.THINKING_PAUSE)
    state_machine.transition(S.PROCESSING)
    state_machine.transition(S.USER_SPEAKING)
    state_machine.transition(S.THINKING_PAUSE)
    assert state_machine.state == S.THINKING_PAUSE


def test_degraded_can_recover_to_live_conversation_state(state_machine):
    state_machine.transition(S.READY)
    state_machine.transition(S.DEGRADED)
    state_machine.transition(S.SPEAKING)
    assert state_machine.state == S.SPEAKING


def test_on_state_change_callback(state_machine):
    events = []
    state_machine.on_state_change(lambda prev, new: events.append((prev, new)))
    state_machine.transition(S.READY)
    assert len(events) == 1
    assert events[0] == (S.INITIALIZING, S.READY)


def test_multiple_callbacks(state_machine):
    count = [0]
    state_machine.on_state_change(lambda p, n: count.__setitem__(0, count[0] + 1))
    state_machine.on_state_change(lambda p, n: count.__setitem__(0, count[0] + 1))
    state_machine.transition(S.READY)
    assert count[0] == 2


def test_interrupt_path(state_machine):
    state_machine.transition(S.READY)
    state_machine.transition(S.LISTENING)
    state_machine.transition(S.USER_SPEAKING)
    state_machine.transition(S.THINKING_PAUSE)
    state_machine.transition(S.PROCESSING)
    state_machine.transition(S.SPEAKING)
    state_machine.transition(S.INTERRUPT_CANDIDATE)
    state_machine.transition(S.INTERRUPTED)
    state_machine.transition(S.LISTENING)
    assert state_machine.state == S.LISTENING


def test_degraded_state_reachable(state_machine):
    state_machine.transition(S.READY)
    state_machine.transition(S.DEGRADED)
    assert state_machine.state == S.DEGRADED


@pytest.mark.asyncio
async def test_watchdog_triggers_degraded(state_machine):
    """Processing watchdog fires and transitions to DEGRADED after timeout."""
    # Override timeout to something very small for testing
    state_machine._processing_timeout_secs = 0.05
    state_machine.transition(S.READY)
    state_machine.transition(S.LISTENING)
    state_machine.transition(S.USER_SPEAKING)
    state_machine.transition(S.THINKING_PAUSE)
    state_machine.transition(S.PROCESSING)
    await asyncio.sleep(0.2)  # let watchdog fire
    assert state_machine.state in (S.DEGRADED, S.READY)  # retry may have fired
