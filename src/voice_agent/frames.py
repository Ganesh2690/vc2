"""Custom Pipecat frames for the voice agent."""
from __future__ import annotations

from dataclasses import dataclass, field

from pipecat.frames.frames import DataFrame, SystemFrame


@dataclass
class MetricFrame(DataFrame):
    """Carries a single latency metric measurement."""

    metric_name: str = ""
    value_ms: float = 0.0
    session_id: str = ""
    turn_id: int = 0


@dataclass
class StateChangeFrame(DataFrame):
    """Signals a conversation state machine transition."""

    previous_state: str = ""
    new_state: str = ""
    timestamp: float = 0.0


@dataclass
class InterruptFrame(SystemFrame):
    """Signals a confirmed barge-in interruption (after confirmation window)."""

    session_id: str = ""
    elapsed_ms: float = 0.0


@dataclass
class TurnCompleteFrame(DataFrame):
    """Smart Turn decided the user's turn is complete."""

    transcript: str = ""
    confidence: float = 1.0


@dataclass
class TurnIncompleteFrame(DataFrame):
    """Smart Turn decided the user has not finished speaking — keep listening."""

    transcript: str = ""
