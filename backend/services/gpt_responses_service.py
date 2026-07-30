"""
LLM Center OpenAI Responses API helper for GPT-5.5.
"""
import json
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from services.llm_runtime_config import LLMRuntimeConfig

GPT_RESPONSES_PROVIDER = "llm_center_gpt_responses"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_PROVIDER_ID = "64"


def is_gpt_responses_provider(runtime_config: Optional[LLMRuntimeConfig] = None) -> bool:
    return (runtime_config or LLMRuntimeConfig.current()).provider == GPT_RESPONSES_PROVIDER


def responses_url(runtime_config: Optional[LLMRuntimeConfig] = None) -> str:
    config = runtime_config or LLMRuntimeConfig.current()
    return f"{config.api_base.rstrip('/')}/v1/responses"


def headers(runtime_config: Optional[LLMRuntimeConfig] = None) -> dict:
    config = runtime_config or LLMRuntimeConfig.current()
    result = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    provider_id = (config.provider_id or "").strip()
    if provider_id:
        result["providerId"] = provider_id
    return result


def reasoning_config() -> dict:
    return {"effort": DEFAULT_REASONING_EFFORT}


def visible_text_from_output(output: Optional[List[dict]]) -> str:
    if not output:
        return ""
    parts: List[str] = []
    for item in output:
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts)


def _format_error(status_code: int, text: str) -> str:
    try:
        data = json.loads(text)
        detail = data.get("error", {}).get("message") or data.get("message") or text
    except Exception:
        detail = text
    return f"LLM Center GPT Responses API 错误 ({status_code})：{detail}"


def _stream_error_message(event: dict) -> Optional[str]:
    event_type = event.get("type")
    error = event.get("error") or (event.get("response") or {}).get("error")
    if not error and event_type not in {"error", "response.failed"}:
        return None
    if isinstance(error, dict):
        return error.get("message") or error.get("code") or json.dumps(error, ensure_ascii=False)
    return str(error) if error else event.get("message") or "流式响应失败"


def _copy_output(output: Optional[List[dict]]) -> List[dict]:
    return [item.copy() for item in (output or [])]


def _update_metadata(metadata_collector: Optional[Dict[str, str]], response_id: Optional[str]) -> None:
    if metadata_collector is not None and response_id:
        metadata_collector["response_id"] = response_id


def _update_output_collector(output_collector: Optional[List[dict]], output: Optional[List[dict]]) -> None:
    if output_collector is not None and output is not None:
        output_collector.clear()
        output_collector.extend(_copy_output(output))


async def create_response(
    *,
    instructions: str,
    input_items: List[dict],
    previous_response_id: Optional[str] = None,
    model: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    runtime_config: Optional[LLMRuntimeConfig] = None,
) -> str:
    config = runtime_config or LLMRuntimeConfig.current()
    payload = {
        "model": model or config.model,
        "instructions": instructions,
        "input": input_items,
        "max_output_tokens": max_output_tokens or config.max_tokens,
        "reasoning": reasoning_config(),
        "store": True,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=60.0),
        trust_env=False,
    ) as client:
        resp = await client.post(
            responses_url(config),
            headers=headers(config),
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(_format_error(resp.status_code, resp.text))
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(_format_error(200, json.dumps(data, ensure_ascii=False)))
    return visible_text_from_output(data.get("output", []))


async def stream_response(
    *,
    instructions: str,
    input_items: List[dict],
    previous_response_id: Optional[str] = None,
    output_collector: Optional[List[dict]] = None,
    metadata_collector: Optional[Dict[str, str]] = None,
    model: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    runtime_config: Optional[LLMRuntimeConfig] = None,
) -> AsyncGenerator[str, None]:
    config = runtime_config or LLMRuntimeConfig.current()
    payload = {
        "model": model or config.model,
        "instructions": instructions,
        "input": input_items,
        "max_output_tokens": max_output_tokens or config.max_tokens,
        "reasoning": reasoning_config(),
        "store": True,
        "stream": True,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=60.0),
        trust_env=False,
    ) as client:
        async with client.stream(
            "POST",
            responses_url(config),
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
                response = event.get("response") or {}
                _update_metadata(metadata_collector, response.get("id") or event.get("response_id"))

                stream_error = _stream_error_message(event)
                if stream_error:
                    raise RuntimeError(_format_error(200, json.dumps({"error": {"message": stream_error}})))

                if event_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield delta
                    continue

                if event_type == "response.completed":
                    _update_output_collector(output_collector, response.get("output"))
                    _update_metadata(metadata_collector, response.get("id"))
                    continue
