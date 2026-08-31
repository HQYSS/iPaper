import pytest

from models import ChatMessage
from services import anthropic_service, gpt_responses_service
from services.llm_service import llm_service
from services.llm_runtime_config import LLMRuntimeConfig


def _runtime(provider: str, model: str, provider_id: str) -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider=provider,
        api_base="https://example.invalid/llm",
        api_key="test",
        model=model,
        provider_id=provider_id,
        temperature=0.7,
        max_tokens=32768,
    )


def test_sol_followup_uses_only_immediately_previous_response_id(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="answer", response_id="resp_1", truncated=False),
        ChatMessage(role="user", content="follow up"),
    ]

    payload = llm_service._build_gpt_responses_single_payload(
        messages,
        pdf,
        runtime_config=_runtime("llm_center_gpt_responses", "gpt-5.6-sol", "97"),
    )

    assert payload["previous_response_id"] == "resp_1"
    assert payload["input"][0]["content"] == [{"type": "input_text", "text": "follow up"}]


def test_sol_106_followup_uses_full_history_instead_of_previous_response_id(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="answer", response_id="resp_1", truncated=False),
        ChatMessage(role="user", content="follow up"),
    ]

    payload = llm_service._build_gpt_responses_single_payload(
        messages,
        pdf,
        runtime_config=_runtime("llm_center_gpt_responses", "gpt-5.6-sol", "106"),
    )

    assert "previous_response_id" not in payload
    assert [item["role"] for item in payload["input"]] == ["user", "assistant", "user"]
    assert payload["input"][0]["content"][0]["type"] == "input_file"


def test_gpt_does_not_reuse_stale_response_chain_after_model_switch(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="gpt", response_id="resp_old", truncated=False),
        ChatMessage(role="user", content="opus question"),
        ChatMessage(role="assistant", content="opus answer", truncated=False),
        ChatMessage(role="user", content="back to gpt"),
    ]

    payload = llm_service._build_gpt_responses_single_payload(messages, pdf)

    assert "previous_response_id" not in payload
    assert payload["input"][0]["content"][0]["type"] == "input_file"


def test_anthropic_pdf_uses_explicit_prompt_cache_breakpoint(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    payload = llm_service._build_anthropic_single_payload(
        [ChatMessage(role="user", content="explain")],
        pdf,
        runtime_config=_runtime("llm_center_anthropic", "claude-opus-5", "88"),
    )

    document = payload["messages"][0]["content"][0]
    assert document["type"] == "document"
    assert document["cache_control"] == {"type": "ephemeral"}


def test_anthropic_pdf_threshold_depends_on_opus_model():
    opus_48 = _runtime("llm_center_anthropic", "claude-opus-4-8", "52")
    opus_5 = _runtime("llm_center_anthropic", "claude-opus-5", "88")
    fable_5 = _runtime("llm_center_anthropic", "claude-fable-5", "88")

    assert llm_service._anthropic_pdf_size_threshold(opus_48) == 14 * 1024 * 1024
    assert llm_service._anthropic_pdf_size_threshold(opus_5) == 22 * 1024 * 1024
    assert llm_service._anthropic_pdf_size_threshold(fable_5) == 22 * 1024 * 1024


def test_sol_pdf_threshold_depends_on_channel():
    sol_97 = _runtime("llm_center_gpt_responses", "gpt-5.6-sol", "97")
    sol_106 = _runtime("llm_center_gpt_responses", "gpt-5.6-sol", "106")

    assert llm_service._gpt_responses_pdf_size_threshold(sol_97) == 14 * 1024 * 1024
    assert llm_service._gpt_responses_pdf_size_threshold(sol_106) == 35 * 1024 * 1024


def test_anthropic_replays_signed_thinking_blocks():
    blocks = [
        {"type": "thinking", "thinking": "private state", "signature": "signed"},
        {"type": "text", "text": "answer"},
    ]
    message = ChatMessage(
        role="assistant",
        content="answer",
        content_blocks=blocks,
        truncated=False,
    )

    assert llm_service._assistant_anthropic_content(message) == blocks


def test_anthropic_drops_unsigned_thinking_blocks():
    message = ChatMessage(
        role="assistant",
        content="answer",
        content_blocks=[
            {"type": "thinking", "thinking": "private state"},
            {"type": "text", "text": "answer"},
        ],
        truncated=False,
    )

    assert llm_service._assistant_anthropic_content(message) == [
        {"type": "text", "text": "answer"}
    ]


def test_anthropic_cross_paper_uses_only_one_cache_breakpoint(tmp_path, monkeypatch):
    paper_ids = [f"2401.0000{index}" for index in range(1, 6)]
    for paper_id in paper_ids:
        paper_dir = tmp_path / paper_id
        paper_dir.mkdir()
        (paper_dir / "paper.pdf").write_bytes(b"%PDF-test")

    monkeypatch.setattr(
        "services.llm_service.arxiv_service.get_paper",
        lambda user_id, paper_id: None,
    )
    monkeypatch.setattr(
        "services.llm_service.arxiv_service.get_pdf_path",
        lambda user_id, paper_id: tmp_path / paper_id / "paper.pdf",
    )
    payload = llm_service._build_anthropic_cross_paper_payload(
        [ChatMessage(role="user", content="compare")],
        "user",
        paper_ids,
        runtime_config=_runtime("llm_center_anthropic", "claude-opus-5", "88"),
    )

    cache_breakpoints = [
        block
        for message in payload["messages"]
        for block in message["content"]
        if block.get("cache_control")
    ]
    assert len(cache_breakpoints) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_message",
    [
        "previous_response_id is only supported on Responses WebSocket v2",
        "previous_response_not_found",
    ],
)
async def test_gpt_stream_falls_back_when_channel_rejects_previous_response_id(
    tmp_path,
    monkeypatch,
    error_message,
):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="answer", response_id="resp_1", truncated=False),
        ChatMessage(role="user", content="follow up"),
    ]
    calls = []

    async def fake_stream_response(**kwargs):
        calls.append(kwargs)
        if kwargs.get("previous_response_id"):
            raise RuntimeError(error_message)
        yield "fallback-ok"

    monkeypatch.setattr(gpt_responses_service, "stream_response", fake_stream_response)
    chunks = [
        chunk
        async for chunk in llm_service.chat_stream(
            messages,
            pdf_path=pdf,
            runtime_config=_runtime(
                "llm_center_gpt_responses",
                "gpt-5.6-sol",
                "97",
            ),
        )
    ]

    assert chunks == ["fallback-ok"]
    assert calls[0]["previous_response_id"] == "resp_1"
    assert calls[1].get("previous_response_id") is None
    assert calls[1]["input_items"][0]["content"][0]["type"] == "input_file"


@pytest.mark.asyncio
async def test_gpt_stream_retries_idle_timeout_before_first_text(monkeypatch):
    calls = 0

    async def fake_stream_response(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("passthrough stream idle timeout after 120s waiting for next chunk")
        yield "retry-ok"

    monkeypatch.setattr(gpt_responses_service, "stream_response", fake_stream_response)
    monkeypatch.setattr("services.llm_service.asyncio.sleep", lambda _: _completed_sleep())
    chunks = [
        chunk
        async for chunk in llm_service.chat_stream(
            [ChatMessage(role="user", content="question")],
            runtime_config=_runtime("llm_center_gpt_responses", "gpt-5.6-sol", "97"),
        )
    ]

    assert chunks == ["retry-ok"]
    assert calls == 2


@pytest.mark.asyncio
async def test_anthropic_stream_retries_idle_timeout_before_first_text(monkeypatch):
    calls = 0

    async def fake_stream_message(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("passthrough stream idle timeout after 120s waiting for next chunk")
        yield "retry-ok"

    monkeypatch.setattr(anthropic_service, "stream_message", fake_stream_message)
    monkeypatch.setattr("services.llm_service.asyncio.sleep", lambda _: _completed_sleep())
    chunks = [
        chunk
        async for chunk in llm_service.chat_stream(
            [ChatMessage(role="user", content="question")],
            runtime_config=_runtime("llm_center_anthropic", "claude-fable-5", "88"),
        )
    ]

    assert chunks == ["retry-ok"]
    assert calls == 3


async def _completed_sleep():
    return None
