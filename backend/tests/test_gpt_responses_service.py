import json
import asyncio

import pytest

from services import gpt_responses_service as service
from services.llm_runtime_config import LLMRuntimeConfig


class FakeResponse:
    def __init__(self, lines, status_code=200, text=""):
        self._lines = lines
        self.status_code = status_code
        self.text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def aread(self):
        return self.text.encode()

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


def _sse(event):
    return "data: " + json.dumps(event)


def _runtime(provider_id):
    return LLMRuntimeConfig(
        provider="llm_center_gpt_responses",
        api_base="https://example.invalid/llm",
        api_key="test",
        model="gpt-5.6-sol",
        provider_id=provider_id,
        temperature=0.7,
        max_tokens=32768,
    )


def test_store_depends_on_sol_channel():
    assert service.should_store(_runtime("97")) is True
    assert service.should_store(_runtime("106")) is False
    assert service.should_store(_runtime("51")) is False


async def _collect(monkeypatch, response, **kwargs):
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **client_kwargs: FakeClient(response))
    return [
        chunk
        async for chunk in service.stream_response(
            instructions="test",
            input_items=[],
            **kwargs,
        )
    ]


@pytest.mark.asyncio
async def test_stream_response_collects_text_output_and_metadata(monkeypatch):
    output = [{"content": [{"type": "output_text", "text": "你好"}]}]
    response = FakeResponse(
        [
            "event: response.output_text.delta",
            _sse({"type": "response.output_text.delta", "delta": "你", "response_id": "resp_1"}),
            "",
            _sse({"type": "response.output_text.delta", "delta": "好"}),
            _sse({"type": "response.completed", "response": {"id": "resp_1", "output": output}}),
            "data: [DONE]",
        ]
    )
    metadata = {}
    collected_output = []

    chunks = await _collect(
        monkeypatch,
        response,
        metadata_collector=metadata,
        output_collector=collected_output,
    )

    assert chunks == ["你", "好"]
    assert metadata == {"response_id": "resp_1"}
    assert collected_output == output


@pytest.mark.asyncio
async def test_stream_response_handles_multiple_sse_fragments(monkeypatch):
    response = FakeResponse(
        [
            ": keep-alive",
            _sse({"type": "response.output_text.delta", "delta": "part-1"}),
            _sse({"type": "response.output_text.delta", "delta": "part-2"}),
            _sse({"type": "response.output_text.delta", "delta": "part-3"}),
            _sse({"type": "response.completed", "response": {"output": []}}),
            "data: [DONE]",
        ]
    )

    assert await _collect(monkeypatch, response) == ["part-1", "part-2", "part-3"]


@pytest.mark.asyncio
async def test_metadata_does_not_satisfy_first_output_timeout(monkeypatch):
    response = FakeResponse([
        _sse({"type": "response.created", "response": {"id": "resp_1"}}),
        (0.02, _sse({"type": "response.output_text.delta", "delta": "late"})),
    ])
    monkeypatch.setattr(service, "FIRST_OUTPUT_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(RuntimeError, match="first model output timeout after 0.01s"):
        await _collect(monkeypatch, response)


@pytest.mark.asyncio
async def test_reasoning_item_disables_first_output_timeout(monkeypatch):
    response = FakeResponse([
        _sse({
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {"id": "rs_1", "type": "reasoning", "summary": []},
        }),
        (0.02, _sse({"type": "response.output_text.delta", "delta": "answer"})),
        _sse({"type": "response.completed", "response": {"output": []}}),
    ])
    monkeypatch.setattr(service, "FIRST_OUTPUT_TIMEOUT_SECONDS", 0.01)

    assert await _collect(monkeypatch, response) == ["answer"]


@pytest.mark.asyncio
async def test_stream_response_preserves_event_items_when_completed_output_is_empty(monkeypatch):
    reasoning = {
        "id": "rs_1",
        "type": "reasoning",
        "encrypted_content": "encrypted-state",
        "summary": [],
    }
    message = {
        "id": "msg_1",
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "answer"}],
    }
    response = FakeResponse(
        [
            _sse({"type": "response.output_item.added", "output_index": 0, "item": reasoning}),
            _sse({"type": "codex.response.metadata", "response_id": "resp_sol"}),
            _sse({"type": "response.output_item.done", "output_index": 1, "item": message}),
            _sse({"type": "codex.rate_limits", "limits": []}),
            _sse({"type": "response.completed", "response": {"id": "resp_sol", "output": []}}),
            "data: [DONE]",
        ]
    )
    metadata = {}
    collected_output = []

    chunks = await _collect(
        monkeypatch,
        response,
        metadata_collector=metadata,
        output_collector=collected_output,
    )

    assert chunks == []
    assert metadata == {"response_id": "resp_sol"}
    assert collected_output == [reasoning, message]


@pytest.mark.asyncio
async def test_stream_response_replaces_added_item_with_done_item(monkeypatch):
    response = FakeResponse(
        [
            _sse({
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"id": "rs_1", "type": "reasoning", "summary": []},
            }),
            _sse({
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "id": "rs_1",
                    "type": "reasoning",
                    "encrypted_content": "final-state",
                    "summary": [],
                },
            }),
            _sse({"type": "response.completed", "response": {"output": []}}),
        ]
    )
    collected_output = []

    await _collect(monkeypatch, response, output_collector=collected_output)

    assert collected_output == [{
        "id": "rs_1",
        "type": "reasoning",
        "encrypted_content": "final-state",
        "summary": [],
    }]


@pytest.mark.asyncio
async def test_stream_response_rejects_partial_text_followed_by_eof(monkeypatch):
    response = FakeResponse([
        _sse({"type": "response.output_text.delta", "delta": "partial"}),
    ])

    with pytest.raises(RuntimeError, match="ended before response.completed"):
        await _collect(monkeypatch, response)


@pytest.mark.asyncio
async def test_stream_response_rejects_done_without_response_completed(monkeypatch):
    response = FakeResponse([
        _sse({"type": "response.output_text.delta", "delta": "partial"}),
        "data: [DONE]",
    ])

    with pytest.raises(RuntimeError, match="ended before response.completed"):
        await _collect(monkeypatch, response)


@pytest.mark.asyncio
async def test_stream_response_raises_for_http_error(monkeypatch):
    response = FakeResponse([], status_code=429, text='{"error":{"message":"quota exceeded"}}')

    with pytest.raises(RuntimeError, match=r"\(429\).*quota exceeded"):
        await _collect(monkeypatch, response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        {"error": {"type": "server_error", "code": "server_error", "message": "渠道未启用"}},
        {"type": "error", "error": {"message": "upstream failed"}},
        {"type": "response.failed", "response": {"error": {"message": "model failed"}}},
    ],
)
async def test_stream_response_raises_for_embedded_sse_error(monkeypatch, event):
    response = FakeResponse([_sse(event)])

    with pytest.raises(RuntimeError, match=r"\(200\).*(渠道未启用|upstream failed|model failed)"):
        await _collect(monkeypatch, response)
