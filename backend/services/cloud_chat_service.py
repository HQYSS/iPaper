"""
Cloud chat delegation.

Local Electron backend uses this service to let the VPS read its own PDF copy
and call LLM Center, so the local machine does not upload the PDF to the LLM.
"""
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from config import settings
from models import ChatMessage, PaperPageSelection, Quote
from services.llm_service import PageSelectionRequiredError

logger = logging.getLogger(__name__)


class CloudChatStream:
    def __init__(self, client: httpx.AsyncClient, response: httpx.Response):
        self._client = client
        self._response = response

    async def aiter_chunks(
        self,
        *,
        reasoning_collector: Optional[List[str]] = None,
        content_blocks_collector: Optional[List[dict]] = None,
        response_metadata_collector: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[str, None]:
        try:
            async for line in self._response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    logger.warning("cloud chat skipped malformed SSE line")
                    continue

                event_type = event.get("type")
                if event_type == "chunk":
                    content = event.get("content") or ""
                    if content:
                        yield content
                    continue

                if event_type == "done":
                    reasoning = event.get("reasoning")
                    if reasoning_collector is not None and reasoning:
                        reasoning_collector.clear()
                        reasoning_collector.append(reasoning)
                    content_blocks = event.get("content_blocks")
                    if content_blocks_collector is not None and content_blocks is not None:
                        content_blocks_collector.clear()
                        content_blocks_collector.extend(content_blocks)
                    response_id = event.get("response_id")
                    if response_metadata_collector is not None and response_id:
                        response_metadata_collector["response_id"] = response_id
                    return

                if event_type == "error":
                    raise RuntimeError(event.get("message") or "云端生成失败")
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        try:
            await self._response.aclose()
        finally:
            await self._client.aclose()


class CloudChatService:
    def should_delegate(self) -> bool:
        return (
            settings.is_sync_client
            and settings.llm.provider != "cursor_cli"
            and bool((settings.sync_url or "").strip())
            and bool((settings.sync_token or "").strip())
        )

    def configured_error_message(self) -> str:
        if not settings.sync_url.strip():
            return "未配置云端同步地址，无法委托云端生成"
        if not settings.sync_token.strip():
            return "未配置同步凭证，无法委托云端生成"
        return "云端委托未启用"

    def _api_base(self) -> str:
        sync_url = (settings.sync_url or "").rstrip("/")
        if sync_url.endswith("/sync"):
            return sync_url[:-5]
        if sync_url.endswith("/api"):
            return sync_url
        return f"{sync_url}/api"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {settings.sync_token.strip()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _execution_payload() -> dict:
        provider_id = (settings.llm.provider_id or "").strip()
        # 64 号 GPT 渠道已停用；留空让 LLM Center 自动选择健康渠道。
        if settings.llm.provider == "llm_center_gpt_responses" and provider_id == "64":
            provider_id = ""
        return {
            "provider": settings.llm.provider,
            "model": settings.llm.model,
            "provider_id": provider_id,
            "max_tokens": settings.llm.max_tokens,
        }

    async def open_single_stream(
        self,
        *,
        paper_id: str,
        messages: List[ChatMessage],
        quotes: Optional[List[Quote]],
        page_selections: Optional[List[PaperPageSelection]],
        paper_title: Optional[str],
    ) -> CloudChatStream:
        payload = {
            "messages": [msg.model_dump(mode="json", exclude_none=True) for msg in messages],
            "quotes": [quote.model_dump(mode="json") for quote in (quotes or [])] or None,
            "page_selections": [
                selection.model_dump(mode="json", exclude_none=True)
                for selection in (page_selections or [])
            ] or None,
            "paper_title": paper_title,
            "llm": self._execution_payload(),
        }
        return await self._open_stream(f"/chat/_cloud/single/{paper_id}/stream", payload)

    async def open_cross_paper_stream(
        self,
        *,
        paper_ids: List[str],
        messages: List[ChatMessage],
        quotes: Optional[List[Quote]],
        page_selections: Optional[List[PaperPageSelection]],
    ) -> CloudChatStream:
        payload = {
            "paper_ids": paper_ids,
            "messages": [msg.model_dump(mode="json", exclude_none=True) for msg in messages],
            "quotes": [quote.model_dump(mode="json") for quote in (quotes or [])] or None,
            "page_selections": [
                selection.model_dump(mode="json", exclude_none=True)
                for selection in (page_selections or [])
            ] or None,
            "llm": self._execution_payload(),
        }
        return await self._open_stream("/chat/_cloud/cross-paper/stream", payload)

    async def _open_stream(self, path: str, payload: dict) -> CloudChatStream:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=60.0),
            verify=settings.sync_verify_ssl,
        )
        response: Optional[httpx.Response] = None
        try:
            request = client.build_request(
                "POST",
                f"{self._api_base()}{path}",
                headers=self._headers(),
                json=payload,
            )
            response = await client.send(request, stream=True)
            if response.status_code == 409:
                body = await response.aread()
                data = json.loads(body.decode("utf-8", errors="replace") or "{}")
                detail = data.get("detail") if isinstance(data, dict) else None
                if isinstance(detail, dict) and detail.get("code") == "page_selection_required":
                    raise PageSelectionRequiredError(
                        detail.get("requirements") or [],
                        detail.get("message") or "需要选择保留页码",
                    )
            if response.status_code >= 400:
                message = await self._error_message(response)
                raise RuntimeError(message)
            logger.info("cloud chat stream opened path=%s", path)
            return CloudChatStream(client, response)
        except Exception:
            if response is not None:
                await response.aclose()
            await client.aclose()
            raise

    @staticmethod
    async def _error_message(response: httpx.Response) -> str:
        body = await response.aread()
        text = body.decode("utf-8", errors="replace")
        try:
            data = json.loads(text or "{}")
            detail = data.get("detail")
            if isinstance(detail, str):
                return detail
            if isinstance(detail, dict):
                return detail.get("message") or json.dumps(detail, ensure_ascii=False)
        except Exception:
            pass
        if "<html" in text.lower() or "<!doctype" in text.lower():
            return f"云端生成失败（HTTP {response.status_code}）。云端后端或上游网关暂时不可用，请稍后重试。"
        return text or f"云端生成失败 ({response.status_code})"


cloud_chat_service = CloudChatService()
