import json

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
