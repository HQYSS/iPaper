"""
Cloud chat delegation.

Local Electron backend uses this service to let the VPS read its own PDF copy
and call LLM Center, so the local machine does not upload the PDF to the LLM.
"""
import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from config import settings
from models import ChatMessage, PaperPageSelection, Quote
from services.llm_service import PageSelectionRequiredError

logger = logging.getLogger(__name__)


class CloudTaskError(RuntimeError):
    pass


class CloudChatStream:
    def __init__(
        self,
        client: httpx.AsyncClient,
        response: httpx.Response,
        task_id: str,
        on_success,
        on_failure,
        reconnect,
    ):
        self._client = client
        self._response = response
        self.task_id = task_id
        self._on_success = on_success
        self._on_failure = on_failure
        self._reconnect = reconnect

    async def aiter_chunks(
        self,
        *,
        reasoning_collector: Optional[List[str]] = None,
        content_blocks_collector: Optional[List[dict]] = None,
        response_metadata_collector: Optional[Dict[str, str]] = None,
    ) -> AsyncGenerator[str, None]:
        received_chars = 0
        reconnect_attempts = 0
        try:
            while True:
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
                                received_chars += len(content)
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
                            self._on_success()
                            return

                        if event_type == "stopped":
                            raise asyncio.CancelledError

                        if event_type == "error":
                            raise CloudTaskError(event.get("message") or "云端生成失败")
                except CloudTaskError:
                    self._on_failure()
                    raise
                except Exception:
                    logger.warning(
                        "cloud stream interrupted task=%s offset=%d",
                        self.task_id,
                        received_chars,
                        exc_info=True,
                    )

                await self._close_transport()
                while reconnect_attempts < 2:
                    reconnect_attempts += 1
                    try:
                        self._client, self._response = await self._reconnect(
                            self.task_id,
                            received_chars,
                        )
                        break
                    except Exception:
                        logger.warning(
                            "cloud reconnect failed task=%s attempt=%d",
                            self.task_id,
                            reconnect_attempts,
                            exc_info=True,
                        )
                        if reconnect_attempts < 2:
                            await asyncio.sleep(0.5 * reconnect_attempts)
                else:
                    self._on_failure()
                    raise RuntimeError("云端生成流意外结束，自动续流失败")
        finally:
            await self.aclose()

    async def _close_transport(self) -> None:
        await self._response.aclose()
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._close_transport()


class CloudChatService:
    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_COOLDOWN_SECONDS = 60.0

    def __init__(self):
        self._failure_count = 0
        self._circuit_open_until = 0.0

    def _check_circuit(self) -> None:
        remaining = self._circuit_open_until - time.monotonic()
        if remaining > 0:
            raise RuntimeError(
                f"云端生成暂时熔断，请在 {int(remaining) + 1} 秒后重试或切换本地降级"
            )

    def _record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = (
                time.monotonic() + self.CIRCUIT_COOLDOWN_SECONDS
            )

    def get_status(self) -> dict:
        remaining = max(0, self._circuit_open_until - time.monotonic())
        return {
            "state": "open" if remaining > 0 else "closed",
            "failures": self._failure_count,
            "retry_after_seconds": int(remaining),
        }

    def should_delegate(self) -> bool:
        return (
            settings.is_sync_client
            and settings.llm.execution_mode == "cloud"
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
        task_id = uuid.uuid4().hex
        payload = {
            "messages": [msg.model_dump(mode="json", exclude_none=True) for msg in messages],
            "quotes": [quote.model_dump(mode="json") for quote in (quotes or [])] or None,
            "page_selections": [
                selection.model_dump(mode="json", exclude_none=True)
                for selection in (page_selections or [])
            ] or None,
            "paper_title": paper_title,
            "llm": self._execution_payload(),
            "task_id": task_id,
        }
        return await self._open_stream(
            f"/chat/_cloud/single/{paper_id}/stream",
            payload,
            task_id,
        )

    async def open_cross_paper_stream(
        self,
        *,
        paper_ids: List[str],
        messages: List[ChatMessage],
        quotes: Optional[List[Quote]],
        page_selections: Optional[List[PaperPageSelection]],
    ) -> CloudChatStream:
        task_id = uuid.uuid4().hex
        payload = {
            "paper_ids": paper_ids,
            "messages": [msg.model_dump(mode="json", exclude_none=True) for msg in messages],
            "quotes": [quote.model_dump(mode="json") for quote in (quotes or [])] or None,
            "page_selections": [
                selection.model_dump(mode="json", exclude_none=True)
                for selection in (page_selections or [])
            ] or None,
            "llm": self._execution_payload(),
            "task_id": task_id,
        }
        return await self._open_stream(
            "/chat/_cloud/cross-paper/stream",
            payload,
            task_id,
        )

    async def _open_stream(self, path: str, payload: dict, task_id: str) -> CloudChatStream:
        self._check_circuit()
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
            return CloudChatStream(
                client,
                response,
                task_id,
                self._record_success,
                self._record_failure,
                self._reconnect_task,
            )
        except Exception:
            self._record_failure()
            if response is not None:
                await response.aclose()
            await client.aclose()
            raise

    async def _reconnect_task(
        self,
        task_id: str,
        offset: int,
    ) -> tuple[httpx.AsyncClient, httpx.Response]:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=30.0, read=900.0, write=60.0, pool=60.0),
            verify=settings.sync_verify_ssl,
        )
        snapshot_response = await client.get(
            f"{self._api_base()}/chat/_cloud/tasks/{task_id}",
            headers=self._headers(),
        )
        if snapshot_response.status_code == 200:
            snapshot = snapshot_response.json()
            if snapshot.get("state") not in {"accepted", "streaming"}:
                events = []
                remaining = (snapshot.get("content") or "")[max(0, offset):]
                if remaining:
                    events.append({"type": "chunk", "content": remaining})
                state = snapshot.get("state")
                if state == "completed":
                    events.append({
                        "type": "done",
                        "reasoning": snapshot.get("reasoning"),
                        "content_blocks": snapshot.get("content_blocks"),
                        "response_id": snapshot.get("response_id"),
                        "task_id": task_id,
                    })
                elif state == "stopped":
                    events.append({"type": "stopped", "task_id": task_id})
                else:
                    events.append({
                        "type": "error",
                        "message": snapshot.get("error") or "云端生成失败",
                        "task_id": task_id,
                    })
                body = "".join(
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    for event in events
                )
                return client, httpx.Response(
                    200,
                    content=body.encode("utf-8"),
                    headers={"content-type": "text/event-stream"},
                )
        elif snapshot_response.status_code != 404:
            message = await self._error_message(snapshot_response)
            await client.aclose()
            raise RuntimeError(message)

        response = await client.send(
            client.build_request(
                "GET",
                f"{self._api_base()}/chat/_cloud/tasks/{task_id}/stream",
                headers=self._headers(),
                params={"offset": offset},
            ),
            stream=True,
        )
        if response.status_code >= 400:
            message = await self._error_message(response)
            await response.aclose()
            await client.aclose()
            raise RuntimeError(message)
        return client, response

    async def cancel_task(self, task_id: str) -> bool:
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=settings.sync_verify_ssl,
        ) as client:
            response = await client.post(
                f"{self._api_base()}/chat/_cloud/tasks/{task_id}/cancel",
                headers=self._headers(),
            )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return bool(response.json().get("stopped"))

    async def get_task(self, task_id: str) -> Optional[dict]:
        async with httpx.AsyncClient(
            timeout=30.0,
            verify=settings.sync_verify_ssl,
        ) as client:
            response = await client.get(
                f"{self._api_base()}/chat/_cloud/tasks/{task_id}",
                headers=self._headers(),
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

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
