import asyncio

import pytest
from pydantic import ValidationError

from config import settings
from models import ChatMessage, LLMExecutionConfig
from services import anthropic_service, gpt_responses_service
from services.cloud_chat_service import CloudChatService, CloudChatStream
from services.llm_runtime_config import LLMRuntimeConfig
from routers.chat import _merge_cloud_generation_update


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "provider_id", "expected_provider_id"),
    [
        ("llm_center_gpt_responses", "gpt-5.6-sol", "97", "97"),
        ("llm_center_gpt_responses", "gpt-5.6-sol", "106", "106"),
        ("llm_center_anthropic", "claude-opus-5", "88", "88"),
        ("llm_center_anthropic", "claude-fable-5", "88", "88"),
    ],
)
async def test_cloud_payload_carries_effective_execution_config(
    monkeypatch,
    provider,
    model,
    provider_id,
    expected_provider_id,
):
    monkeypatch.setattr(settings.llm, "provider", provider)
    monkeypatch.setattr(settings.llm, "model", model)
    monkeypatch.setattr(settings.llm, "provider_id", provider_id)
    monkeypatch.setattr(settings.llm, "max_tokens", 32768)
    captured = {}
    service = CloudChatService()

    async def fake_open(path, payload, task_id):
        captured.update({"path": path, "payload": payload, "task_id": task_id})
        return "stream"

    monkeypatch.setattr(service, "_open_stream", fake_open)
    result = await service.open_single_stream(
        paper_id="2401.00001",
        messages=[],
        quotes=None,
        page_selections=None,
        paper_title="Test",
    )

    assert result == "stream"
    assert captured["payload"]["llm"] == {
        "provider": provider,
        "model": model,
        "provider_id": expected_provider_id,
        "max_tokens": 32768,
    }
    assert captured["payload"]["task_id"] == captured["task_id"]


def test_cloud_snapshot_merge_preserves_turns_appended_during_lookup():
    old_generation_id = "a" * 32
    messages = [
        ChatMessage(role="user", content="explain"),
        ChatMessage(
            role="assistant",
            content="partial",
            generation_id=old_generation_id,
            truncated=True,
        ),
        ChatMessage(role="user", content="continue"),
        ChatMessage(
            role="assistant",
            content="remainder",
            generation_id="b" * 32,
        ),
    ]

    updated = ChatMessage(
        role="assistant",
        content="refreshed partial",
        generation_id=None,
        truncated=True,
    )

    assert _merge_cloud_generation_update(messages, old_generation_id, updated)
    assert [message.content for message in messages] == [
        "explain",
        "refreshed partial",
        "continue",
        "remainder",
    ]


class FakeStreamResponse:
    def __init__(self, events):
        self.events = events

    async def aiter_lines(self):
        for event in self.events:
            yield f"data: {__import__('json').dumps(event)}"

    async def aclose(self):
        return None


class FakeStreamClient:
    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_reconnect_uses_terminal_snapshot_instead_of_reopening_stream(monkeypatch):
    service = CloudChatService()

    class SnapshotClient:
        def __init__(self, **kwargs):
            pass

        async def get(self, *args, **kwargs):
            return __import__("httpx").Response(
                200,
                json={
                    "state": "failed",
                    "content": "",
                    "error": "passthrough stream idle timeout",
                },
            )

        async def send(self, *args, **kwargs):
            raise AssertionError("terminal task must not reopen SSE stream")

        async def aclose(self):
            return None

    monkeypatch.setattr("services.cloud_chat_service.httpx.AsyncClient", SnapshotClient)
    client, response = await service._reconnect_task("f" * 32, 0)
    events = [
        __import__("json").loads(line[6:])
        async for line in response.aiter_lines()
        if line.startswith("data: ")
    ]
    await client.aclose()

    assert events == [{
        "type": "error",
        "message": "passthrough stream idle timeout",
        "task_id": "f" * 32,
    }]


@pytest.mark.asyncio
async def test_cloud_stream_reconnects_from_character_offset_after_eof():
    reconnect_calls = []

    async def reconnect(task_id, offset):
        reconnect_calls.append((task_id, offset))
        return (
            FakeStreamClient(),
            FakeStreamResponse([
                {"type": "chunk", "content": "lo"},
                {"type": "done", "response_id": "resp_1"},
            ]),
        )

    stream = CloudChatStream(
        FakeStreamClient(),
        FakeStreamResponse([{"type": "chunk", "content": "hel"}]),
        "a" * 32,
        lambda: None,
        lambda: None,
        reconnect,
    )
    metadata = {}
    chunks = [
        chunk
        async for chunk in stream.aiter_chunks(
            response_metadata_collector=metadata,
        )
    ]

    assert chunks == ["hel", "lo"]
    assert reconnect_calls == [("a" * 32, 3)]
    assert metadata["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_cloud_stream_retries_when_first_reconnect_attempt_fails():
    attempts = 0

    async def reconnect(task_id, offset):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary network error")
        return (
            FakeStreamClient(),
            FakeStreamResponse([{"type": "done"}]),
        )

    stream = CloudChatStream(
        FakeStreamClient(),
        FakeStreamResponse([]),
        "d" * 32,
        lambda: None,
        lambda: None,
        reconnect,
    )

    assert [chunk async for chunk in stream.aiter_chunks()] == []
    assert attempts == 2


@pytest.mark.asyncio
async def test_cloud_stream_maps_stopped_terminal_to_cancellation():
    async def reconnect(task_id, offset):
        raise AssertionError("stopped stream must not reconnect")

    stream = CloudChatStream(
        FakeStreamClient(),
        FakeStreamResponse([{"type": "stopped"}]),
        "e" * 32,
        lambda: None,
        lambda: None,
        reconnect,
    )

    with pytest.raises(asyncio.CancelledError):
        async for _ in stream.aiter_chunks():
            pass


def test_execution_config_rejects_mismatched_model_route():
    with pytest.raises(ValidationError, match="不支持的云端 LLM 模型或渠道组合"):
        LLMExecutionConfig(
            provider="llm_center_anthropic",
            model="gpt-5.5",
            provider_id="64",
            max_tokens=32768,
        )


def test_execution_config_accepts_only_fixed_sol_route():
    config = LLMExecutionConfig(
        provider="llm_center_gpt_responses",
        model="gpt-5.6-sol",
        provider_id="97",
        max_tokens=32768,
    )
    assert config.provider_id == "97"

    with pytest.raises(ValidationError, match="不支持的云端 LLM 模型或渠道组合"):
        LLMExecutionConfig(
            provider="llm_center_gpt_responses",
            model="gpt-5.6-sol",
            provider_id="",
            max_tokens=32768,
        )


def test_execution_config_accepts_only_verified_fable_route():
    config = LLMExecutionConfig(
        provider="llm_center_anthropic",
        model="claude-fable-5",
        provider_id="88",
        max_tokens=32768,
    )
    assert config.provider_id == "88"

    with pytest.raises(ValidationError, match="不支持的云端 LLM 模型或渠道组合"):
        LLMExecutionConfig(
            provider="llm_center_anthropic",
            model="claude-fable-5",
            provider_id="52",
            max_tokens=32768,
        )


def test_cloud_chat_circuit_opens_after_repeated_failures(monkeypatch):
    service = CloudChatService()
    monkeypatch.setattr(service, "CIRCUIT_COOLDOWN_SECONDS", 60)

    for _ in range(service.CIRCUIT_FAILURE_THRESHOLD):
        service._record_failure()

    assert service.get_status()["state"] == "open"
    with pytest.raises(RuntimeError, match="云端生成暂时熔断"):
        service._check_circuit()
    service._record_success()
    assert service.get_status()["state"] == "closed"


def test_runtime_config_uses_server_credentials_without_mutating_global_settings(monkeypatch):
    monkeypatch.setattr(settings.llm, "provider", "llm_center_gpt_responses")
    monkeypatch.setattr(settings.llm, "model", "gpt-5.5")
    monkeypatch.setattr(settings.llm, "provider_id", "")
    monkeypatch.setattr(settings.llm, "api_key", "server-secret")
    execution = LLMExecutionConfig(
        provider="llm_center_anthropic",
        model="claude-opus-5",
        provider_id="88",
        max_tokens=32768,
    )

    runtime = LLMRuntimeConfig.from_execution(execution)

    assert runtime.provider == "llm_center_anthropic"
    assert runtime.model == "claude-opus-5"
    assert runtime.provider_id == "88"
    assert runtime.api_key == "server-secret"
    assert settings.llm.provider == "llm_center_gpt_responses"
    assert settings.llm.model == "gpt-5.5"


@pytest.mark.asyncio
async def test_concurrent_runtime_configs_do_not_share_model_or_route():
    common = {
        "api_base": "https://example.invalid/llm",
        "api_key": "server-secret",
        "temperature": 0.7,
        "max_tokens": 32768,
    }
    gpt = LLMRuntimeConfig(
        provider="llm_center_gpt_responses",
        model="gpt-5.5",
        provider_id="",
        **common,
    )
    opus = LLMRuntimeConfig(
        provider="llm_center_anthropic",
        model="claude-opus-5",
        provider_id="88",
        **common,
    )

    async def inspect_gpt():
        await asyncio.sleep(0)
        return gpt_responses_service.responses_url(gpt), gpt_responses_service.headers(gpt)

    async def inspect_opus():
        await asyncio.sleep(0)
        return anthropic_service.messages_url(opus), anthropic_service.headers(opus)

    (gpt_url, gpt_headers), (opus_url, opus_headers) = await asyncio.gather(
        inspect_gpt(),
        inspect_opus(),
    )

    assert gpt_url.endswith("/v1/responses")
    assert "providerId" not in gpt_headers
    assert opus_url.endswith("/v1/messages")
    assert opus_headers["providerId"] == "88"
