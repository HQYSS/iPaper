from models import ChatMessage
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


def test_gpt_followup_uses_only_immediately_previous_response_id(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="answer", response_id="resp_1", truncated=False),
        ChatMessage(role="user", content="follow up"),
    ]

    payload = llm_service._build_gpt_responses_single_payload(messages, pdf)

    assert payload["previous_response_id"] == "resp_1"
    assert payload["input"][0]["content"] == [{"type": "input_text", "text": "follow up"}]


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
