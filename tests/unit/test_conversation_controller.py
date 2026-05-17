"""Unit tests for ConversationController state transitions."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TextFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.aggregators.llm_response_universal import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from voice_agent.agent.pipeline import AssistantResponsePublisher, ConversationController
from voice_agent.agent.state_machine import ConversationState, ConversationStateMachine
from voice_agent.memory.session_memory import SessionMemory


@pytest.mark.asyncio
async def test_controller_reaches_listening_after_response():
    state_machine = ConversationStateMachine()
    memory = SessionMemory(
        system_prompt="You are helpful.",
        max_turns=10,
        max_context_tokens=4000,
        max_response_tokens=300,
    )
    transport = AsyncMock()
    controller = ConversationController(
        state_machine=state_machine,
        memory=memory,
        transport=transport,
        session_id="test-session",
    )
    controller.push_frame = AsyncMock()

    state_machine.transition(ConversationState.READY)
    state_machine.transition(ConversationState.LISTENING)

    await controller.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await controller.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await controller.process_frame(
        TranscriptionFrame(text="hello", user_id="user", timestamp="0"),
        FrameDirection.DOWNSTREAM,
    )
    await controller.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
    await controller.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    assert state_machine.state == ConversationState.LISTENING
    messages = [json.loads(call.args[0]) for call in transport.send_message.call_args_list]
    assert any(message["type"] == "ready_for_user" for message in messages)


@pytest.mark.asyncio
async def test_assistant_response_publisher_sends_live_and_final_transcripts():
    memory = SessionMemory(
        system_prompt="You are helpful.",
        max_turns=10,
        max_context_tokens=4000,
        max_response_tokens=300,
    )
    transport = AsyncMock()
    publisher = AssistantResponsePublisher(memory=memory, transport=transport)
    publisher.push_frame = AsyncMock()

    await publisher.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await publisher.process_frame(TextFrame(text="Four."), FrameDirection.DOWNSTREAM)
    await publisher.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    messages = [call.args[0] for call in transport.send_message.call_args_list]
    assert any('"final": false' in message and "Four." in message for message in messages)
    assert any('"final": true' in message and "Four." in message for message in messages)
    assert memory.get_messages()[-1] == {"role": "assistant", "content": "Four."}


@pytest.mark.asyncio
async def test_assistant_response_publisher_updates_llm_context():
    memory = SessionMemory(
        system_prompt="You are helpful.",
        max_turns=10,
        max_context_tokens=4000,
        max_response_tokens=300,
    )
    llm_context = LLMContext(messages=memory.get_messages())
    transport = AsyncMock()
    publisher = AssistantResponsePublisher(
        memory=memory,
        transport=transport,
        llm_context=llm_context,
    )
    publisher.push_frame = AsyncMock()

    await publisher.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await publisher.process_frame(TextFrame(text="Four."), FrameDirection.DOWNSTREAM)
    await publisher.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    assert llm_context.get_messages()[-1] == {"role": "assistant", "content": "Four."}


@pytest.mark.asyncio
async def test_assistant_response_publisher_falls_back_on_empty_llm_response():
    memory = SessionMemory(
        system_prompt="You are helpful.",
        max_turns=10,
        max_context_tokens=4000,
        max_response_tokens=300,
    )
    transport = AsyncMock()
    publisher = AssistantResponsePublisher(memory=memory, transport=transport)
    publisher.push_frame = AsyncMock()

    await publisher.process_frame(LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM)
    await publisher.process_frame(LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM)

    pushed_text = [
        call.args[0].text
        for call in publisher.push_frame.call_args_list
        if isinstance(call.args[0], TextFrame)
    ]
    assert any("didn't get a response" in text for text in pushed_text)
    assert "didn't get a response" in memory.get_messages()[-1]["content"]
