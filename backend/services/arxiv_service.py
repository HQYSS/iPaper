"""
arXiv 论文下载服务

流程（方案 C）：
1. `download_paper` 秒级返回占位 meta（download_status=downloading）
2. 真正的 PDF 下载通过 asyncio.create_task 在后台跑，blocking 调用用 to_thread 丢到线程池
3. 下载失败自动重试 3 次（指数退避 2s/4s/8s），仍失败则 download_status=failed
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import arxiv

from config import settings
from models import PaperMeta

logger = logging.getLogger(__name__)

DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_BACKOFF = (2.0, 4.0, 8.0)


class ArxivService:
    """arXiv 论文下载和管理服务"""

    ARXIV_ID_PATTERN = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')
    ARXIV_URL_PATTERN = re.compile(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?')

    def __init__(self):
        # key: f"{user_id}:{arxiv_id}" → 正在跑的后台下载 task
        self._download_tasks: Dict[str, asyncio.Task] = {}

    def parse_arxiv_input(self, input_str: str) -> Optional[str]:
        """
        解析用户输入，提取 arXiv ID
        支持格式：
        - 2301.12345
        - 2301.12345v1
        - https://arxiv.org/abs/2301.12345
        - https://arxiv.org/pdf/2301.12345.pdf
        """
        input_str = input_str.strip()

        url_match = self.ARXIV_URL_PATTERN.search(input_str)
        if url_match:
            arxiv_id = url_match.group(1)
            version = url_match.group(2) or ""
            return arxiv_id + version

        id_match = self.ARXIV_ID_PATTERN.search(input_str)
        if id_match:
            arxiv_id = id_match.group(1)
            version = id_match.group(2) or ""
            return arxiv_id + version

        return None

    def get_paper_dir(self, user_id: str, arxiv_id: str) -> Path:
        base_id = self.ARXIV_ID_PATTERN.match(arxiv_id).group(1)
        return settings.get_user_papers_dir(user_id) / base_id

    @staticmethod
    def _task_key(user_id: str, arxiv_id: str) -> str:
        return f"{user_id}:{arxiv_id}"

    async def download_paper(self, user_id: str, arxiv_input: str) -> Tuple[bool, str, Optional[PaperMeta]]:
        """
        添加论文入口。

        - 解析 ID → 若已存在 ready/downloading 的 meta，直接返回
        - 否则同步查 arXiv metadata（很快），写占位 meta，启动后台 PDF 下载
        - 若已存在但状态为 failed，重新触发后台下载
        """
        arxiv_id = self.parse_arxiv_input(arxiv_input)
        if not arxiv_id:
            return False, f"无法解析 arXiv ID: {arxiv_input}", None

        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"

        # 已存在 → 按状态分支处理
        if meta_file.exists():
            meta = self._load_meta(meta_file)
            status = getattr(meta, "download_status", "ready") or "ready"

            if status == "ready":
                return True, "论文已存在", meta

            if status == "downloading":
                # 同一篇正在下载中（可能是前次未完成进程残留；若后台 task 不在则补一个）
                self._ensure_download_task(user_id, meta)
                return True, "下载进行中", meta

            # failed → 重新触发
            meta.download_status = "downloading"
            meta.download_error = None
            self._save_meta(meta_file, meta)
            self._ensure_download_task(user_id, meta)
            return True, "重新下载中", meta

        # 新论文：查 metadata → 写占位 → 触发后台下载
        try:
            paper = await asyncio.to_thread(self._fetch_metadata, arxiv_id)
        except Exception as e:
            logger.exception("fetch arxiv metadata failed for %s", arxiv_id)
            return False, f"查询 arXiv 失败: {e}", None

        if paper is None:
            return False, f"未找到论文: {arxiv_id}", None

        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"

        meta = PaperMeta(
            arxiv_id=arxiv_id,
            title=paper.title,
            summary=paper.summary,
            authors=[author.name for author in paper.authors],
            download_time=datetime.now(),
            has_latex=False,
            pdf_path=str(pdf_path),
            download_status="downloading",
            download_error=None,
        )

        self._save_meta(meta_file, meta)
        self._update_index(user_id, meta)
        self._ensure_download_task(user_id, meta)

        return True, "下载已开始", meta

    def _fetch_metadata(self, arxiv_id: str):
        """同步查 arXiv metadata（供 to_thread 包装）"""
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))
        return results[0] if results else None

    def _ensure_download_task(self, user_id: str, meta: PaperMeta) -> None:
        """若当前没有在跑的后台 task，启动一个"""
        key = self._task_key(user_id, meta.arxiv_id)
        existing = self._download_tasks.get(key)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._download_pdf_async(user_id, meta.arxiv_id))
        self._download_tasks[key] = task

    async def _download_pdf_async(self, user_id: str, arxiv_id: str) -> None:
        """后台 PDF 下载任务，含最多 3 次重试"""
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        last_err: Optional[str] = None

        for attempt in range(DOWNLOAD_MAX_RETRIES):
            try:
                await asyncio.to_thread(self._blocking_download_pdf, arxiv_id, paper_dir)
                # 成功：更新 meta.json 为 ready
                if meta_file.exists():
                    meta = self._load_meta(meta_file)
                    meta.download_status = "ready"
                    meta.download_error = None
                    self._save_meta(meta_file, meta)
                logger.info("paper %s downloaded (attempt %d)", arxiv_id, attempt + 1)

                # 触发一次 sync（ready 状态才进 manifest）
                try:
                    from services.sync_service import sync_service
                    sync_service.request_sync("paper-ready", arxiv_id)
                except Exception:
                    logger.exception("request_sync failed after paper ready")

                # 任务完成，从登记表清理
                self._download_tasks.pop(self._task_key(user_id, arxiv_id), None)
                return
            except asyncio.CancelledError:
                logger.info("download cancelled for %s", arxiv_id)
                raise
            except Exception as e:
                last_err = str(e)
                logger.warning(
                    "download failed for %s (attempt %d/%d): %s",
                    arxiv_id, attempt + 1, DOWNLOAD_MAX_RETRIES, e,
                )
                if attempt < DOWNLOAD_MAX_RETRIES - 1:
                    await asyncio.sleep(DOWNLOAD_RETRY_BACKOFF[attempt])

        # 连续失败 → 标记 failed
        if meta_file.exists():
            try:
                meta = self._load_meta(meta_file)
                meta.download_status = "failed"
                meta.download_error = last_err or "未知错误"
                self._save_meta(meta_file, meta)
            except Exception:
                logger.exception("failed to mark meta as failed for %s", arxiv_id)

        self._download_tasks.pop(self._task_key(user_id, arxiv_id), None)
        logger.error("download permanently failed for %s: %s", arxiv_id, last_err)

    def _blocking_download_pdf(self, arxiv_id: str, paper_dir: Path) -> None:
        """供 to_thread 调用的同步 PDF 下载。确保原子写入（先写 tmp，再 rename）。"""
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))
        if not results:
            raise RuntimeError(f"arXiv 未返回结果: {arxiv_id}")
        paper = results[0]
        tmp_name = "paper.pdf.part"
        paper.download_pdf(dirpath=str(paper_dir), filename=tmp_name)
        tmp_path = paper_dir / tmp_name
        final_path = paper_dir / "paper.pdf"
        if final_path.exists():
            final_path.unlink()
        tmp_path.rename(final_path)

    def cancel_download(self, user_id: str, arxiv_id: str) -> None:
        """取消后台下载 task（删除论文时调用）"""
        key = self._task_key(user_id, arxiv_id)
        task = self._download_tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

    def get_paper(self, user_id: str, arxiv_id: str) -> Optional[PaperMeta]:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        if meta_file.exists():
            return self._load_meta(meta_file)
        return None

    def list_papers(self, user_id: str) -> List[PaperMeta]:
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"
        if not index_file.exists():
            return []

        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        papers = []
        for item in data.get("papers", []):
            paper_dir = self.get_paper_dir(user_id, item["arxiv_id"])
            meta_file = paper_dir / "meta.json"
            if meta_file.exists():
                papers.append(self._load_meta(meta_file))

        # Keep the library aligned with add order even if index.json was rebuilt.
        papers.sort(key=lambda paper: paper.download_time)
        return papers

    def delete_paper(self, user_id: str, arxiv_id: str) -> bool:
        self.cancel_download(user_id, arxiv_id)
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        if not paper_dir.exists():
            return False

        import shutil
        shutil.rmtree(paper_dir)

        self._remove_from_index(user_id, arxiv_id)

        return True

    def get_pdf_path(self, user_id: str, arxiv_id: str) -> Optional[Path]:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        pdf_path = paper_dir / "paper.pdf"
        if pdf_path.exists():
            return pdf_path
        return None

    def _load_meta(self, meta_file: Path) -> PaperMeta:
        with open(meta_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PaperMeta(**data)

    def _save_meta(self, meta_file: Path, meta: PaperMeta):
        data = meta.model_dump(mode="json")
        data["updated_at"] = datetime.now().isoformat()
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def _update_index(self, user_id: str, meta: PaperMeta):
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"

        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"papers": []}

        for item in data["papers"]:
            if item["arxiv_id"] == meta.arxiv_id:
                return

        data["papers"].append({
            "arxiv_id": meta.arxiv_id,
            "title": meta.title,
            "download_time": meta.download_time.isoformat()
        })

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _remove_from_index(self, user_id: str, arxiv_id: str):
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"

        if not index_file.exists():
            return

        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        data["papers"] = [p for p in data["papers"] if p["arxiv_id"] != arxiv_id]

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


arxiv_service = ArxivService()
