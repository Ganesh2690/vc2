"""Unit tests for SessionMemory."""
from __future__ import annotations

import pytest

from voice_agent.memory.session_memory import SessionMemory


def _make_memory(max_turns=10, max_context_tokens=4000, max_response_tokens=300):
    return SessionMemory(
        system_prompt="You are a helpful voice assistant.",
        max_turns=max_turns,
        max_context_tokens=max_context_tokens,
        max_response_tokens=max_response_tokens,
    )


def test_initial_messages_contain_system(memory_store):
    msgs = memory_store.get_messages()
    assert msgs[0]["role"] == "system"
    assert "assistant" in msgs[0]["content"].lower()


def test_append_user_appears_in_messages(memory_store):
    memory_store.append_user("Hello there")
    msgs = memory_store.get_messages()
    user_msgs = [m for m in msgs if m["role"] == "user"]
    assert any("Hello there" in m["content"] for m in user_msgs)


def test_append_assistant_appears_in_messages(memory_store):
    memory_store.append_user("Hi")
    memory_store.append_assistant("Hello! How can I help you?")
    msgs = memory_store.get_messages()
    asst_msgs = [m for m in msgs if m["role"] == "assistant"]
    assert any("Hello! How can I help you?" in m["content"] for m in asst_msgs)


def test_turn_count_increments(memory_store):
    assert memory_store.turn_count == 0
    memory_store.append_user("Q1")
    memory_store.append_assistant("A1")
    assert memory_store.turn_count == 1


def test_trim_by_max_turns():
    mem = _make_memory(max_turns=2)
    for i in range(5):
        mem.append_user(f"Question {i}")
        mem.append_assistant(f"Answer {i}")
    msgs = mem.get_messages()
    # Should have system + 2*2 = 5 messages max
    non_system = [m for m in msgs if m["role"] != "system"]
    assert len(non_system) <= 4  # max_turns * 2 user+assistant pairs


def test_trim_by_token_budget():
    """Token budget forces trimming even within max_turns."""
    # Very small token budget
    mem = _make_memory(max_context_tokens=200, max_response_tokens=50, max_turns=20)
    long_text = "word " * 30  # ~30 tokens
    for _ in range(10):
        mem.append_user(long_text)
        mem.append_assistant(long_text)
    # After trimming, total tokens should be within budget
    msgs = mem.get_messages()
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    total = sum(len(enc.encode(m["content"])) for m in msgs)
    assert total <= 200


def test_get_messages_structure(memory_store):
    memory_store.append_user("Test question")
    memory_store.append_assistant("Test answer")
    msgs = memory_store.get_messages()
    assert msgs[0]["role"] == "system"
    roles = [m["role"] for m in msgs]
    # After system, alternates user/assistant
    non_system = roles[1:]
    assert non_system[0] == "user"
    assert non_system[1] == "assistant"


def test_session_summary(memory_store):
    memory_store.append_user("Hi")
    memory_store.append_assistant("Hello")
    summary = memory_store.session_summary()
    assert "turn_count" in summary
    assert summary["turn_count"] >= 1


def test_empty_memory_summary(memory_store):
    summary = memory_store.session_summary()
    assert summary["turn_count"] == 0
