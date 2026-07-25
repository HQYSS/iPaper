"""
LLM Center OpenAI Responses API helper for GPT-5.5.
"""
import json
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from config import settings

GPT_RESPONSES_PROVIDER = "llm_center_gpt_responses"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_PROVIDER_ID = "64"


def is_gpt_responses_provider() -> bool:
    return settings.llm.provider == GPT_RESPONSES_PROVIDER


def responses_url() -> str:
    return f"{settings.llm.api_base.rstrip('/')}/v1/responses"


def headers() -> dict:
    result = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm.api_key}",
    }
    provider_id = (settings.llm.provider_id or "").strip()
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
) -> str:
    payload = {
        "model": model or settings.llm.model,
        "instructions": instructions,
        "input": input_items,
        "max_output_tokens": max_output_tokens or settings.llm.max_tokens,
        "reasoning": reasoning_config(),
        "store": True,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=60.0)) as client:
        resp = await client.post(responses_url(), headers=headers(), json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(_format_error(resp.status_code, resp.text))
        data = resp.json()
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
) -> AsyncGenerator[str, None]:
    payload = {
        "model": model or settings.llm.model,
        "instructions": instructions,
        "input": input_items,
        "max_output_tokens": max_output_tokens or settings.llm.max_tokens,
        "reasoning": reasoning_config(),
        "store": True,
        "stream": True,
    }
    if previous_response_id:
        payload["previous_response_id"] = previous_response_id

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=30.0, read=900.0, write=900.0, pool=60.0)) as client:
        async with client.stream("POST", responses_url(), headers=headers(), json=payload) as resp:
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

                if event_type == "response.output_text.delta":
                    delta = event.get("delta", "")
                    if delta:
                        yield delta
                    continue

                if event_type == "response.completed":
                    _update_output_collector(output_collector, response.get("output"))
                    _update_metadata(metadata_collector, response.get("id"))
                    continue
