import json

import pytest

from services import gpt_responses_service as service


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
            "data: [DONE]",
        ]
    )

    assert await _collect(monkeypatch, response) == ["part-1", "part-2", "part-3"]


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
