import asyncio

import pytest
from pydantic import ValidationError

from config import settings
from models import LLMExecutionConfig
from services import anthropic_service, gpt_responses_service
from services.cloud_chat_service import CloudChatService
from services.llm_runtime_config import LLMRuntimeConfig


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "provider_id", "expected_provider_id"),
    [
        ("llm_center_gpt_responses", "gpt-5.5", "64", ""),
        ("llm_center_anthropic", "claude-opus-5", "88", "88"),
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

    async def fake_open(path, payload):
        captured.update({"path": path, "payload": payload})
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


def test_execution_config_rejects_mismatched_model_route():
    with pytest.raises(ValidationError, match="不支持的云端 LLM 模型或渠道组合"):
        LLMExecutionConfig(
            provider="llm_center_anthropic",
            model="gpt-5.5",
            provider_id="64",
            max_tokens=32768,
        )


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
