"""
LLM Center Anthropic Messages API helper.
"""
import json
import logging
from typing import AsyncGenerator, List, Optional

import httpx

from services.llm_runtime_config import LLMRuntimeConfig

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_PROVIDER = "llm_center_anthropic"
DEFAULT_THINKING_BUDGET = 2048


def is_anthropic_provider(runtime_config: Optional[LLMRuntimeConfig] = None) -> bool:
    return (runtime_config or LLMRuntimeConfig.current()).provider == ANTHROPIC_PROVIDER


def messages_url(runtime_config: Optional[LLMRuntimeConfig] = None) -> str:
    config = runtime_config or LLMRuntimeConfig.current()
    return f"{config.api_base.rstrip('/')}/v1/messages"


def headers(runtime_config: Optional[LLMRuntimeConfig] = None) -> dict:
    config = runtime_config or LLMRuntimeConfig.current()
    result = {
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    provider_id = (config.provider_id or "").strip()
    if provider_id:
        result["providerId"] = provider_id
    return result


def thinking_config(max_tokens: int) -> dict:
    budget = min(DEFAULT_THINKING_BUDGET, max(1024, max_tokens // 2))
    if budget >= max_tokens:
        budget = max(1024, max_tokens - 512)
    return {"type": "enabled", "budget_tokens": budget}


def visible_text_from_blocks(blocks: Optional[List[dict]]) -> str:
    if not blocks:
        return ""
    parts = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def has_valid_thinking_signatures(blocks: Optional[List[dict]]) -> bool:
    if not blocks:
        return False
    for block in blocks:
        block_type = block.get("type")
        if block_type == "thinking" and not block.get("signature"):
            return False
        if block_type == "redacted_thinking" and not block.get("data"):
            return False
    return True


def _snapshot_blocks(blocks_by_index: dict[int, dict]) -> List[dict]:
    return [
        blocks_by_index[index].copy()
        for index in sorted(blocks_by_index)
        if blocks_by_index[index].get("type")
    ]


def _format_error(status_code: int, text: str) -> str:
    try:
        data = json.loads(text)
        detail = data.get("error", {}).get("message") or data.get("message") or text
    except Exception:
        detail = text
    return f"LLM Center Anthropic API 错误 ({status_code})：{detail}"


def _stream_error_message(event: dict) -> Optional[str]:
    error = event.get("error")
    if not error and event.get("type") != "error":
        return None
    if isinstance(error, dict):
        return error.get("message") or error.get("code") or json.dumps(error, ensure_ascii=False)
    return str(error) if error else event.get("message") or "流式响应失败"


async def create_message(
    *,
    system: str,
    messages: List[dict],
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    thinking: bool = False,
    runtime_config: Optional[LLMRuntimeConfig] = None,
) -> str:
    config = runtime_config or LLMRuntimeConfig.current()
    token_limit = max_tokens or config.max_tokens
    payload = {
        "model": model or config.model,
        "max_tokens": token_limit,
        "system": system,
        "messages": messages,
    }
    if thinking:
        payload["thinking"] = thinking_config(token_limit)
    elif temperature is not None:
        payload["temperature"] = temperature

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=600.0, write=600.0, pool=60.0),
        trust_env=False,
    ) as client:
        resp = await client.post(
            messages_url(config),
            headers=headers(config),
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(_format_error(resp.status_code, resp.text))
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(_format_error(200, json.dumps(data, ensure_ascii=False)))
    return visible_text_from_blocks(data.get("content", []))


async def stream_message(
    *,
    system: str,
    messages: List[dict],
    content_blocks_collector: Optional[List[dict]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    runtime_config: Optional[LLMRuntimeConfig] = None,
) -> AsyncGenerator[str, None]:
    config = runtime_config or LLMRuntimeConfig.current()
    token_limit = max_tokens or config.max_tokens
    payload = {
        "model": model or config.model,
        "max_tokens": token_limit,
        "system": system,
        "messages": messages,
        "thinking": thinking_config(token_limit),
        "stream": True,
    }

    blocks_by_index: dict[int, dict] = {}
    last_cache_usage: Optional[tuple] = None

    def update_collector():
        if content_blocks_collector is not None:
            content_blocks_collector.clear()
            content_blocks_collector.extend(_snapshot_blocks(blocks_by_index))

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=60.0),
        trust_env=False,
    ) as client:
        async with client.stream(
            "POST",
            messages_url(config),
            headers=headers(config),
            json=payload,
        ) as resp:
            if resp.status_code >= 400:
                text = await resp.aread()
                raise RuntimeError(_format_error(resp.status_code, text.decode("utf-8", errors="replace")))

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line.startswith("event:") or line.startswith(":"):
                    continue
                if not line.startswith("data: "):
                    continue
                raw = line[6:]
                if raw == "[DONE]":
                    break
                event = json.loads(raw)
                event_type = event.get("type")
                stream_error = _stream_error_message(event)
                if stream_error:
                    raise RuntimeError(
                        _format_error(
                            200,
                            json.dumps({"error": {"message": stream_error}}, ensure_ascii=False),
                        )
                    )

                usage = (event.get("message") or {}).get("usage") or event.get("usage")
                cache_usage = (
                    usage.get("cache_creation_input_tokens", 0),
                    usage.get("cache_read_input_tokens", 0),
                    usage.get("input_tokens", 0),
                ) if isinstance(usage, dict) else None
                if cache_usage and cache_usage != last_cache_usage and (
                    usage.get("cache_creation_input_tokens") is not None
                    or usage.get("cache_read_input_tokens") is not None
                ):
                    logger.info(
                        "anthropic prompt cache creation_tokens=%s read_tokens=%s input_tokens=%s",
                        usage.get("cache_creation_input_tokens", 0),
                        usage.get("cache_read_input_tokens", 0),
                        usage.get("input_tokens", 0),
                    )
                    last_cache_usage = cache_usage

                if event_type == "content_block_start":
                    index = int(event["index"])
                    block = event.get("content_block", {}).copy()
                    blocks_by_index[index] = block
                    update_collector()
                    continue

                if event_type == "content_block_delta":
                    index = int(event["index"])
                    delta = event.get("delta", {})
                    block = blocks_by_index.setdefault(index, {"type": "text", "text": ""})
                    delta_type = delta.get("type")
                    if delta_type == "text_delta":
                        text = delta.get("text", "")
                        block["text"] = block.get("text", "") + text
                        update_collector()
                        if text:
                            yield text
                    elif delta_type == "thinking_delta":
                        block["type"] = "thinking"
                        block["thinking"] = block.get("thinking", "") + delta.get("thinking", "")
                        update_collector()
                    elif delta_type == "signature_delta":
                        block["signature"] = delta.get("signature", "")
                        update_collector()
                    elif delta_type == "redacted_thinking_delta":
                        block["type"] = "redacted_thinking"
                        block["data"] = block.get("data", "") + delta.get("data", "")
                        update_collector()
                    continue

                if event_type == "content_block_stop":
                    update_collector()
                    continue
