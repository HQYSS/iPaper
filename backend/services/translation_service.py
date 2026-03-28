"""
论文翻译服务 — 基于 hjfy.top（幻觉翻译）
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, Dict

import httpx

from config import settings

logger = logging.getLogger(__name__)

HJFY_BASE = "https://hjfy.top"
HJFY_STATUS_URL = f"{HJFY_BASE}/api/arxivStatus"
HJFY_FILES_URL = f"{HJFY_BASE}/api/arxivFiles"

POLL_INTERVAL_SECONDS = 10


class TranslationTask:
    """单个翻译任务的状态"""
    __slots__ = ("arxiv_id", "status", "info", "error")

    def __init__(self, arxiv_id: str):
        self.arxiv_id = arxiv_id
        self.status: str = "pending"   # pending | polling | finished | failed | error | needs_login
        self.info: str = ""
        self.error: str = ""


class TranslationService:
    """管理所有论文的翻译任务"""

    def __init__(self):
        self._tasks: Dict[str, TranslationTask] = {}

    @staticmethod
    def _strip_version(arxiv_id: str) -> str:
        m = re.match(r"(\d{4}\.\d{4,5})", arxiv_id)
        return m.group(1) if m else arxiv_id

    @staticmethod
    def _task_key(user_id: str, arxiv_id: str) -> str:
        return f"{user_id}:{arxiv_id}"

    def get_task(self, user_id: str, arxiv_id: str) -> Optional[TranslationTask]:
        return self._tasks.get(self._task_key(user_id, self._strip_version(arxiv_id)))

    def _pdf_path(self, user_id: str, arxiv_id: str) -> Path:
        base_id = self._strip_version(arxiv_id)
        return settings.get_user_papers_dir(user_id) / base_id / "paper_zh.pdf"

    def has_zh_pdf(self, user_id: str, arxiv_id: str) -> bool:
        return self._pdf_path(user_id, arxiv_id).exists()

    async def ensure_translation(self, user_id: str, arxiv_id: str) -> TranslationTask:
        """
        确保翻译存在。如果本地已有 PDF 直接返回 finished，
        否则启动后台轮询任务。幂等——对同一篇论文多次调用不会重复创建任务。
        """
        base_id = self._strip_version(arxiv_id)
        key = self._task_key(user_id, base_id)

        if self.has_zh_pdf(user_id, base_id):
            task = TranslationTask(base_id)
            task.status = "finished"
            self._tasks[key] = task
            return task

        existing = self._tasks.get(key)
        if existing and existing.status == "polling":
            return existing

        task = TranslationTask(base_id)
        task.status = "polling"
        task.info = "正在查询翻译状态…"
        self._tasks[key] = task

        asyncio.create_task(self._poll_loop(user_id, task))
        return task

    async def _poll_loop(self, user_id: str, task: TranslationTask):
        base_id = task.arxiv_id
        cookie = self._get_cookie(user_id)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                while True:
                    headers = {}
                    if cookie:
                        headers["Cookie"] = cookie

                    resp = await client.get(
                        f"{HJFY_STATUS_URL}/{base_id}",
                        headers=headers,
                    )
                    data = resp.json()

                    if data.get("status") == 101:
                        if not cookie:
                            task.status = "needs_login"
                            task.error = "该论文尚未被翻译，需要配置幻觉翻译 Cookie 以触发新翻译"
                            logger.warning("Translation requires login for %s", base_id)
                            return
                        task.info = "等待翻译服务响应…"
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue

                    if data.get("status") != 0:
                        task.status = "failed"
                        task.error = data.get("msg", "未知错误")
                        logger.error("Translation status error for %s: %s", base_id, data)
                        return

                    inner = data["data"]
                    hjfy_status = inner.get("status", "")
                    info = inner.get("info", "")

                    if info:
                        task.info = info

                    if hjfy_status == "finished":
                        await self._download_pdf(client, user_id, base_id, headers)
                        task.status = "finished"
                        task.info = "翻译完成"
                        logger.info("Translation finished for %s", base_id)
                        return

                    if hjfy_status in ("failed", "error", "fault"):
                        task.status = "failed"
                        task.error = {
                            "failed": "翻译失败",
                            "error": "翻译出错，可能该论文没有 LaTeX 源码",
                            "fault": "LaTeX 编译失败",
                        }.get(hjfy_status, hjfy_status)
                        return

                    task.info = info or "翻译中…"
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

        except Exception as e:
            task.status = "error"
            task.error = f"翻译服务异常: {e}"
            logger.exception("Translation poll error for %s", base_id)

    async def _download_pdf(
        self, client: httpx.AsyncClient, user_id: str, base_id: str, headers: dict
    ):
        resp = await client.get(f"{HJFY_FILES_URL}/{base_id}", headers=headers)
        data = resp.json()

        if data.get("status") != 0:
            raise RuntimeError(f"Failed to get files: {data}")

        zh_url = data["data"].get("zhCN")
        if not zh_url:
            raise RuntimeError("No zhCN PDF URL in response")

        pdf_resp = await client.get(zh_url, follow_redirects=True, timeout=120)
        pdf_resp.raise_for_status()

        out_path = self._pdf_path(user_id, base_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(pdf_resp.content)
        logger.info("Downloaded zh PDF to %s (%d bytes)", out_path, len(pdf_resp.content))

    @staticmethod
    def _get_cookie(user_id: str) -> str:
        return settings.get_user_hjfy_cookie(user_id)


translation_service = TranslationService()
