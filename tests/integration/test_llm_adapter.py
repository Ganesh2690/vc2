"""Integration test — OpenAI LLM adapter via respx SSE mock.

Marked with @pytest.mark.integration so CI can skip with:
    pytest -m "not integration"
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx


@pytest.mark.integration
@pytest.mark.asyncio
async def test_openai_stream_parses_tokens():
    """Mock OpenAI SSE stream and verify token accumulation."""
    from openai import AsyncOpenAI

    mock_chunks = [
        {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": ", world"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]},
    ]

    def _make_sse(chunks):
        lines = []
        for chunk in chunks:
            lines.append(f"data: {json.dumps(chunk)}\n\n")
        lines.append("data: [DONE]\n\n")
        return "".join(lines)

    sse_body = _make_sse(mock_chunks)

    with respx.mock(base_url="https://api.openai.com") as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                text=sse_body,
                headers={"Content-Type": "text/event-stream"},
            )
        )

        client = AsyncOpenAI(api_key="test-key")
        stream = await client.chat.completions.create(
            model="gpt-5.4-nano-2026-03-17",
            messages=[{"role": "user", "content": "Say hello"}],
            stream=True,
        )
        tokens = []
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                tokens.append(delta.content)

    assert "".join(tokens) == "Hello, world!"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_openai_handles_empty_delta():
    """Empty delta (role-only chunk) should not cause errors."""
    from openai import AsyncOpenAI

    mock_chunks = [
        {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]},
    ]

    def _make_sse(chunks):
        return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    with respx.mock(base_url="https://api.openai.com"):
        respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                text=_make_sse(mock_chunks),
                headers={"Content-Type": "text/event-stream"},
            )
        )
        client = AsyncOpenAI(api_key="test-key")
        stream = await client.chat.completions.create(
            model="gpt-5.4-nano-2026-03-17",
            messages=[{"role": "user", "content": "Hi"}],
            stream=True,
        )
        tokens = []
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                tokens.append(delta.content)

    assert "".join(tokens) == "OK"
