import json
import asyncio

import pytest

from services import anthropic_service as service
from services.llm_runtime_config import LLMRuntimeConfig


class FakeResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            if isinstance(line, tuple):
                delay, line = line
                await asyncio.sleep(delay)
            yield line


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def stream(self, *args, **kwargs):
        return self.response


@pytest.mark.asyncio
async def test_stream_message_raises_for_embedded_sse_error(monkeypatch):
    response = FakeResponse([
        "data: " + json.dumps({
            "type": "error",
            "error": {"type": "server_error", "message": "Anthropic 渠道不可用"},
        }),
    ])
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: FakeClient(response))
    runtime = LLMRuntimeConfig(
        provider="llm_center_anthropic",
        api_base="https://example.invalid/llm",
        api_key="test-key",
        model="claude-opus-5",
        provider_id="88",
        temperature=0.7,
        max_tokens=32768,
    )

    with pytest.raises(RuntimeError, match="Anthropic 渠道不可用"):
        async for _ in service.stream_message(
            system="test",
            messages=[],
            runtime_config=runtime,
        ):
            pass


@pytest.mark.asyncio
async def test_prompt_cache_event_does_not_satisfy_first_output_timeout(monkeypatch):
    response = FakeResponse([
        "data: " + json.dumps({"type": "message_start", "message": {"usage": {"cache_read_input_tokens": 100}}}),
        (0.02, "data: " + json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "late"},
        })),
    ])
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: FakeClient(response))
    monkeypatch.setattr(service, "FIRST_OUTPUT_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(RuntimeError, match="first model output timeout after 0.01s"):
        async for _ in service.stream_message(
            system="test",
            messages=[],
            runtime_config=LLMRuntimeConfig(
                provider="llm_center_anthropic",
                api_base="https://example.invalid/llm",
                api_key="test-key",
                model="claude-fable-5",
                provider_id="88",
                temperature=0.7,
                max_tokens=32768,
            ),
        ):
            pass


@pytest.mark.asyncio
async def test_stream_message_rejects_partial_text_followed_by_eof(monkeypatch):
    response = FakeResponse([
        "data: " + json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "这个问题问到了点子上——答"},
        }),
    ])
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: FakeClient(response))

    chunks = []
    with pytest.raises(RuntimeError, match="ended before message_stop"):
        async for chunk in service.stream_message(
            system="test",
            messages=[],
            runtime_config=LLMRuntimeConfig(
                provider="llm_center_anthropic",
                api_base="https://example.invalid/llm",
                api_key="test-key",
                model="claude-opus-5",
                provider_id="88",
                temperature=0.7,
                max_tokens=32768,
            ),
        ):
            chunks.append(chunk)

    assert chunks == ["这个问题问到了点子上——答"]


@pytest.mark.asyncio
async def test_stream_message_rejects_done_without_message_stop(monkeypatch):
    response = FakeResponse([
        "data: " + json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "partial"},
        }),
        "data: [DONE]",
    ])
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: FakeClient(response))

    with pytest.raises(RuntimeError, match="ended before message_stop"):
        async for _ in service.stream_message(
            system="test",
            messages=[],
            runtime_config=LLMRuntimeConfig(
                provider="llm_center_anthropic",
                api_base="https://example.invalid/llm",
                api_key="test-key",
                model="claude-opus-5",
                provider_id="88",
                temperature=0.7,
                max_tokens=32768,
            ),
        ):
            pass


@pytest.mark.asyncio
async def test_stream_message_accepts_explicit_message_stop(monkeypatch):
    response = FakeResponse([
        "data: " + json.dumps({
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "完整回答"},
        }),
        "data: " + json.dumps({"type": "message_stop"}),
    ])
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: FakeClient(response))

    chunks = [
        chunk
        async for chunk in service.stream_message(
            system="test",
            messages=[],
            runtime_config=LLMRuntimeConfig(
                provider="llm_center_anthropic",
                api_base="https://example.invalid/llm",
                api_key="test-key",
                model="claude-opus-5",
                provider_id="88",
                temperature=0.7,
                max_tokens=32768,
            ),
        )
    ]

    assert chunks == ["完整回答"]
