"""
arXiv 论文下载服务

流程（方案 C）：
1. `download_paper` 秒级返回占位 meta（download_status=downloading）
2. 真正的 PDF 下载通过 asyncio.create_task 在后台跑，blocking 调用用 to_thread 丢到线程池
3. 下载失败自动重试 3 次（指数退避 2s/4s/8s），仍失败则 download_status=failed
"""
import asyncio
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse, urlunparse

import arxiv
import httpx

from config import settings
from models import PaperMeta

logger = logging.getLogger(__name__)

DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_RETRY_BACKOFF = (2.0, 4.0, 8.0)

# arXiv API 要求 legacy API 不超过 3 秒 1 次、单连接访问。
# metadata 不再阻塞“添加论文”，因此这里优先合规和稳定，而不是快速失败。
METADATA_NUM_RETRIES = 1
METADATA_DELAY_SECONDS = 3.0
METADATA_MIN_INTERVAL_SECONDS = 3.0
METADATA_REFRESH_MAX_RETRIES = 5
METADATA_RETRY_BACKOFF = (60.0, 180.0, 600.0, 1800.0)
PLACEHOLDER_METADATA_SUMMARY = "arXiv 元数据待补齐；PDF 下载完成后即可先阅读。"

PDF_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=20.0, read=180.0, write=30.0, pool=30.0)
PDF_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


class ArxivService:
    """arXiv 论文下载和管理服务"""

    ARXIV_ID_PATTERN = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?')
    ARXIV_URL_PATTERN = re.compile(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(v\d+)?')
    PDF_URL_PATTERN = re.compile(r'^https?://', re.IGNORECASE)

    def __init__(self):
        # key: f"{user_id}:{arxiv_id}" → 正在跑的后台下载 task
        self._download_tasks: Dict[str, asyncio.Task] = {}
        self._metadata_tasks: Dict[str, asyncio.Task] = {}
        self._metadata_lock = asyncio.Lock()
        self._metadata_last_request_at: float = 0.0

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

    def parse_pdf_url_input(self, input_str: str) -> Optional[str]:
        """解析普通 PDF URL。arXiv URL 优先走 arXiv 元数据流程。"""
        input_str = input_str.strip()
        if not self.PDF_URL_PATTERN.match(input_str):
            return None
        if self.ARXIV_URL_PATTERN.search(input_str):
            return None
        return input_str

    def get_paper_dir(self, user_id: str, arxiv_id: str) -> Path:
        match = self.ARXIV_ID_PATTERN.match(arxiv_id)
        base_id = match.group(1) if match else arxiv_id
        return settings.get_user_papers_dir(user_id) / base_id

    @staticmethod
    def _paper_id_for_pdf_url(pdf_url: str) -> str:
        digest = hashlib.sha256(pdf_url.encode("utf-8")).hexdigest()[:16]
        return f"pdf_{digest}"

    @staticmethod
    def _title_from_pdf_url(pdf_url: str) -> str:
        parsed = urlparse(pdf_url)
        filename = unquote(Path(parsed.path).name)
        if filename.lower().endswith(".pdf"):
            filename = filename[:-4]
        title = filename.replace("_", " ").replace("-", " ").strip()
        return title or parsed.netloc or "PDF 论文"

    @staticmethod
    def _task_key(user_id: str, arxiv_id: str) -> str:
        return f"{user_id}:{arxiv_id}"

    @staticmethod
    def _clean_metadata_text(value: Optional[str]) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _clean_metadata_authors(value: Optional[List[str]]) -> List[str]:
        if not value:
            return []
        authors: List[str] = []
        seen = set()
        for author in value:
            cleaned = ArxivService._clean_metadata_text(author)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            authors.append(cleaned)
        return authors[:50]

    @staticmethod
    def _is_placeholder_metadata(meta: PaperMeta) -> bool:
        return (
            meta.title == f"arXiv {meta.arxiv_id}"
            or meta.summary == PLACEHOLDER_METADATA_SUMMARY
            or not meta.authors
        )

    def _apply_metadata_fallback(
        self,
        user_id: str,
        meta: PaperMeta,
        fallback: Optional[dict],
        persist: bool = True,
    ) -> PaperMeta:
        """Use page-scraped metadata while the arXiv API is rate-limited."""
        if not fallback or getattr(meta, "source_type", "arxiv") != "arxiv":
            return meta

        changed = False
        title = self._clean_metadata_text(fallback.get("title"))
        summary = self._clean_metadata_text(fallback.get("summary"))
        authors = self._clean_metadata_authors(fallback.get("authors"))
        source_url = self._clean_metadata_text(fallback.get("source_url"))

        if title and (not meta.title or meta.title == f"arXiv {meta.arxiv_id}"):
            meta.title = title
            changed = True
        if summary and (not meta.summary or meta.summary == PLACEHOLDER_METADATA_SUMMARY):
            meta.summary = summary
            changed = True
        if authors and not meta.authors:
            meta.authors = authors
            changed = True
        if source_url and "arxiv.org/" in source_url and not meta.source_url:
            meta.source_url = source_url
            changed = True

        if changed and persist:
            meta_file = self.get_paper_dir(user_id, meta.arxiv_id) / "meta.json"
            self._save_meta(meta_file, meta)
            self._update_index(user_id, meta)
            logger.info("metadata fallback applied for %s", meta.arxiv_id)

        return meta

    async def download_paper(
        self,
        user_id: str,
        arxiv_input: str,
        metadata_fallback: Optional[dict] = None,
    ) -> Tuple[bool, str, Optional[PaperMeta]]:
        """
        添加论文入口。

        - 解析 ID → 若已存在 ready/downloading 的 meta，直接返回
        - 否则同步查 arXiv metadata（很快），写占位 meta，启动后台 PDF 下载
        - 若已存在但状态为 failed，重新触发后台下载
        """
        arxiv_id = self.parse_arxiv_input(arxiv_input)
        if not arxiv_id:
            pdf_url = self.parse_pdf_url_input(arxiv_input)
            if pdf_url:
                logger.info("parsed PDF URL input user=%s url_host=%s", user_id, urlparse(pdf_url).netloc)
                return await self._add_pdf_url_paper(user_id, pdf_url)
            return False, f"无法解析 arXiv ID 或 PDF URL: {arxiv_input}", None
        logger.info("parsed arxiv input user=%s arxiv_id=%s", user_id, arxiv_id)

        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"

        # 已存在 → 按状态分支处理
        if meta_file.exists():
            meta = self._load_meta(meta_file)
            status = getattr(meta, "download_status", "ready") or "ready"
            if getattr(meta, "source_type", "arxiv") == "arxiv":
                meta = self._apply_metadata_fallback(user_id, meta, metadata_fallback)
                self._ensure_metadata_task(user_id, meta.arxiv_id)

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

        # 新论文：先写入最小占位 meta，让 PDF 下载不再被 arXiv metadata API 卡住。
        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"

        meta = PaperMeta(
            arxiv_id=arxiv_id,
            source_type="arxiv",
            source_url=f"https://arxiv.org/abs/{arxiv_id}",
            title=f"arXiv {arxiv_id}",
            summary=PLACEHOLDER_METADATA_SUMMARY,
            authors=[],
            download_time=datetime.now(),
            has_latex=False,
            pdf_path=str(pdf_path),
            download_status="downloading",
            download_error=None,
        )
        meta = self._apply_metadata_fallback(user_id, meta, metadata_fallback, persist=False)

        self._save_meta(meta_file, meta)
        self._update_index(user_id, meta)
        self._ensure_download_task(user_id, meta)
        self._ensure_metadata_task(user_id, meta.arxiv_id)

        return True, "下载已开始", meta

    async def _add_pdf_url_paper(self, user_id: str, pdf_url: str) -> Tuple[bool, str, Optional[PaperMeta]]:
        paper_id = self._paper_id_for_pdf_url(pdf_url)
        paper_dir = self.get_paper_dir(user_id, paper_id)
        meta_file = paper_dir / "meta.json"

        if meta_file.exists():
            meta = self._load_meta(meta_file)
            status = getattr(meta, "download_status", "ready") or "ready"

            if status == "ready":
                return True, "论文已存在", meta

            if status == "downloading":
                self._ensure_download_task(user_id, meta)
                return True, "下载进行中", meta

            meta.download_status = "downloading"
            meta.download_error = None
            self._save_meta(meta_file, meta)
            self._ensure_download_task(user_id, meta)
            return True, "重新下载中", meta

        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"
        meta = PaperMeta(
            arxiv_id=paper_id,
            source_type="pdf_url",
            source_url=pdf_url,
            title=self._title_from_pdf_url(pdf_url),
            summary=f"PDF URL: {pdf_url}",
            authors=[],
            download_time=datetime.now(),
            has_latex=False,
            pdf_path=str(pdf_path),
            translation_status="completed",
            download_status="downloading",
            download_error=None,
        )

        self._save_meta(meta_file, meta)
        self._update_index(user_id, meta)
        self._ensure_download_task(user_id, meta)

        return True, "下载已开始", meta

    def _fetch_metadata(self, arxiv_id: str):
        """同步查 arXiv metadata（供 to_thread 包装）。

        该调用只用于后台补齐 title/summary/authors，不阻塞添加论文。
        外层 `_fetch_metadata_rate_limited` 会串行化请求并保证至少 3 秒间隔，
        避免频繁添加论文时触发 arXiv legacy API 的 429 限流。
        """
        client = arxiv.Client(
            num_retries=METADATA_NUM_RETRIES,
            delay_seconds=METADATA_DELAY_SECONDS,
        )
        search = arxiv.Search(id_list=[arxiv_id])
        results = list(client.results(search))
        return results[0] if results else None

    def _ensure_download_task(self, user_id: str, meta: PaperMeta) -> None:
        """若当前没有在跑的后台 task，启动一个"""
        key = self._task_key(user_id, meta.arxiv_id)
        existing = self._download_tasks.get(key)
        if existing and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("cannot schedule download for %s without a running event loop", meta.arxiv_id)
            return
        task = loop.create_task(self._download_pdf_async(user_id, meta.arxiv_id))
        self._download_tasks[key] = task
        logger.info("download task scheduled user=%s paper=%s", user_id, meta.arxiv_id)

    def _has_active_download_task(self, user_id: str, arxiv_id: str) -> bool:
        existing = self._download_tasks.get(self._task_key(user_id, arxiv_id))
        return bool(existing and not existing.done())

    def _ensure_metadata_task(self, user_id: str, arxiv_id: str) -> None:
        """后台补齐 arXiv metadata。只对 arXiv 来源生效，且同一篇幂等。"""
        key = self._task_key(user_id, arxiv_id)
        existing = self._metadata_tasks.get(key)
        if existing and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("cannot schedule metadata refresh for %s without a running event loop", arxiv_id)
            return
        task = loop.create_task(self._refresh_metadata_async(user_id, arxiv_id))
        self._metadata_tasks[key] = task
        logger.info("metadata task scheduled user=%s paper=%s", user_id, arxiv_id)

    def recover_incomplete_downloads(self) -> int:
        """Recover downloads that were interrupted by a backend restart.

        Download tasks live in memory. During development, uvicorn reloads can leave
        meta.json stuck at download_status=downloading after the task disappeared.
        Scanning persisted paper directories on startup makes the state self-healing.
        """
        recovered = 0
        users_root = settings.data_dir / "data"
        if not users_root.exists():
            return 0

        for user_dir in users_root.iterdir():
            if not user_dir.is_dir():
                continue
            papers_dir = user_dir / "papers"
            if not papers_dir.exists():
                continue
            for meta_file in papers_dir.glob("*/meta.json"):
                try:
                    meta = self._load_meta(meta_file)
                    before = getattr(meta, "download_status", "ready") or "ready"
                    repaired = self._repair_download_state(user_dir.name, meta)
                    after = getattr(repaired, "download_status", "ready") or "ready"
                    if before == "downloading" and after == "downloading":
                        recovered += 1
                except Exception:
                    logger.exception("failed to recover download state from %s", meta_file)

        if recovered:
            logger.info("recovered %d interrupted download task(s)", recovered)
        return recovered

    def _repair_download_state(self, user_id: str, meta: PaperMeta) -> PaperMeta:
        """Align persisted download_status with files and in-memory tasks."""
        paper_dir = self.get_paper_dir(user_id, meta.arxiv_id)
        meta_file = paper_dir / "meta.json"
        pdf_path = paper_dir / "paper.pdf"
        part_path = paper_dir / "paper.pdf.part"
        status = getattr(meta, "download_status", "ready") or "ready"

        if pdf_path.exists():
            if self._path_looks_like_pdf(pdf_path):
                if status != "ready" or meta.download_error:
                    meta.download_status = "ready"
                    meta.download_error = None
                    self._save_meta(meta_file, meta)
                    self._update_index(user_id, meta)
                return meta

            if status != "failed":
                meta.download_status = "failed"
                meta.download_error = "本地 PDF 文件损坏，请重新下载"
                self._save_meta(meta_file, meta)
            return meta

        if status == "ready":
            meta.download_status = "failed"
            meta.download_error = "本地 PDF 文件缺失，请重新下载"
            self._save_meta(meta_file, meta)
            return meta

        if status == "downloading":
            if self._has_active_download_task(user_id, meta.arxiv_id):
                return meta
            part_path.unlink(missing_ok=True)
            self._ensure_download_task(user_id, meta)

        return meta

    @staticmethod
    def _path_looks_like_pdf(path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                return b"%PDF" in f.read(1024)
        except OSError:
            return False

    async def _fetch_metadata_rate_limited(self, arxiv_id: str):
        async with self._metadata_lock:
            elapsed = time.monotonic() - self._metadata_last_request_at
            if elapsed < METADATA_MIN_INTERVAL_SECONDS:
                await asyncio.sleep(METADATA_MIN_INTERVAL_SECONDS - elapsed)
            try:
                return await asyncio.to_thread(self._fetch_metadata, arxiv_id)
            finally:
                self._metadata_last_request_at = time.monotonic()

    async def _refresh_metadata_async(self, user_id: str, arxiv_id: str) -> None:
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        try:
            for attempt in range(METADATA_REFRESH_MAX_RETRIES):
                try:
                    paper = await self._fetch_metadata_rate_limited(arxiv_id)
                    if paper is None:
                        logger.warning("metadata not found for %s", arxiv_id)
                        return
                    if not meta_file.exists():
                        return
                    meta = self._load_meta(meta_file)
                    if getattr(meta, "source_type", "arxiv") != "arxiv":
                        return
                    meta.title = paper.title
                    meta.summary = paper.summary
                    meta.authors = [author.name for author in paper.authors]
                    meta.source_url = paper.entry_id or f"https://arxiv.org/abs/{arxiv_id}"
                    self._save_meta(meta_file, meta)
                    self._update_index(user_id, meta)
                    logger.info("metadata refreshed for %s", arxiv_id)
                    try:
                        from services.sync_service import sync_service
                        sync_service.request_sync("paper-metadata", arxiv_id)
                    except Exception:
                        logger.exception("request_sync failed after metadata refresh")
                    return
                except arxiv.HTTPError as e:
                    status = getattr(e, "status", None)
                    if status == 429 and attempt < METADATA_REFRESH_MAX_RETRIES - 1:
                        retry_in = METADATA_RETRY_BACKOFF[min(attempt, len(METADATA_RETRY_BACKOFF) - 1)]
                        logger.warning(
                            "arxiv metadata refresh rate-limited for %s; retrying in %.0fs",
                            arxiv_id,
                            retry_in,
                        )
                        await asyncio.sleep(retry_in)
                        continue
                    logger.warning(
                        "arxiv metadata refresh HTTPError for %s: status=%s",
                        arxiv_id,
                        status,
                    )
                    return
                except Exception:
                    if attempt < METADATA_REFRESH_MAX_RETRIES - 1:
                        retry_in = METADATA_RETRY_BACKOFF[min(attempt, len(METADATA_RETRY_BACKOFF) - 1)]
                        logger.exception(
                            "metadata refresh failed for %s; retrying in %.0fs",
                            arxiv_id,
                            retry_in,
                        )
                        await asyncio.sleep(retry_in)
                        continue
                    logger.exception("metadata refresh failed for %s", arxiv_id)
                    return
        except asyncio.CancelledError:
            raise
        finally:
            self._metadata_tasks.pop(self._task_key(user_id, arxiv_id), None)

    async def _download_pdf_async(self, user_id: str, arxiv_id: str) -> None:
        """后台 PDF 下载任务，含最多 3 次重试"""
        paper_dir = self.get_paper_dir(user_id, arxiv_id)
        meta_file = paper_dir / "meta.json"
        last_err: Optional[str] = None
        logger.info("download task started user=%s paper=%s", user_id, arxiv_id)

        for attempt in range(DOWNLOAD_MAX_RETRIES):
            try:
                meta = self._load_meta(meta_file)
                if getattr(meta, "source_type", "arxiv") == "pdf_url":
                    await asyncio.to_thread(self._blocking_download_pdf_url, meta.source_url, paper_dir)
                else:
                    await asyncio.to_thread(self._blocking_download_pdf, arxiv_id, paper_dir)
                # 成功：更新 meta.json 为 ready
                if meta_file.exists():
                    meta = self._load_meta(meta_file)
                    meta.download_status = "ready"
                    meta.download_error = None
                    self._save_meta(meta_file, meta)
                size = (paper_dir / "paper.pdf").stat().st_size if (paper_dir / "paper.pdf").exists() else 0
                logger.info("paper %s downloaded attempt=%d size_bytes=%d", arxiv_id, attempt + 1, size)

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
                last_err = self._format_download_error(e)
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
        """供 to_thread 调用的同步 PDF 下载。避免再次请求 arXiv metadata API。"""
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        referer = f"https://arxiv.org/abs/{arxiv_id}"
        try:
            self._download_pdf_stream(pdf_url, paper_dir, referer=referer)
        except Exception as httpx_error:
            logger.warning("httpx arxiv PDF download failed for %s, falling back: %s", arxiv_id, httpx_error)
            self._download_arxiv_pdf_with_urllib(pdf_url, paper_dir)

    def _blocking_download_pdf_url(self, pdf_url: Optional[str], paper_dir: Path) -> None:
        """从普通 PDF URL 下载 PDF。确保原子写入，并验证结果像 PDF。"""
        if not pdf_url:
            raise RuntimeError("PDF URL 为空")

        self._download_pdf_stream(pdf_url, paper_dir, referer=self._referer_for_pdf_url(pdf_url))

    def _download_pdf_stream(self, pdf_url: str, paper_dir: Path, referer: Optional[str] = None) -> None:
        tmp_path = paper_dir / "paper.pdf.part"
        final_path = paper_dir / "paper.pdf"
        if tmp_path.exists():
            tmp_path.unlink()

        headers = self._pdf_download_headers(referer)
        try:
            with httpx.Client(follow_redirects=True, timeout=PDF_DOWNLOAD_TIMEOUT, headers=headers) as client:
                # 这里不用 stream：当前网络环境下 arXiv PDF 流式读取偶发 SSL 读错误，
                # 一次性读取同一 URL 更稳定；论文 PDF 通常在可接受大小范围内。
                resp = client.get(pdf_url)
                resp.raise_for_status()
                content = resp.content

            header = content[:1024]
            if b"%PDF" not in header:
                raise RuntimeError("下载内容不是 PDF")

            tmp_path.write_bytes(content)
            if final_path.exists():
                final_path.unlink()
            tmp_path.rename(final_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _download_arxiv_pdf_with_urllib(pdf_url: str, paper_dir: Path) -> None:
        tmp_path = paper_dir / "paper.pdf.part"
        final_path = paper_dir / "paper.pdf"
        if tmp_path.exists():
            tmp_path.unlink()
        try:
            urllib.request.urlretrieve(pdf_url, tmp_path)
            with open(tmp_path, "rb") as f:
                header = f.read(1024)
            if b"%PDF" not in header:
                raise RuntimeError("下载内容不是 PDF")
            if final_path.exists():
                final_path.unlink()
            tmp_path.rename(final_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _pdf_download_headers(referer: Optional[str] = None) -> dict:
        headers = {
            "User-Agent": PDF_USER_AGENT,
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    @staticmethod
    def _referer_for_pdf_url(pdf_url: str) -> Optional[str]:
        parsed = urlparse(pdf_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        path = parsed.path
        if path.endswith(".full.pdf"):
            path = path[:-len(".full.pdf")]
        elif path.lower().endswith(".pdf"):
            path = path[:-4]
        return urlunparse((parsed.scheme, parsed.netloc, path or "/", "", "", ""))

    @staticmethod
    def _format_download_error(error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            if status == 403:
                return "源站拒绝程序下载（HTTP 403）"
            if status == 404:
                return "PDF 不存在或 arXiv ID 有误（HTTP 404）"
            if status == 429:
                return "源站暂时限流（HTTP 429），请稍后重试"
            return f"源站返回 HTTP {status}"
        if isinstance(error, httpx.TimeoutException):
            return "PDF 下载超时，请稍后重试"
        if isinstance(error, httpx.NetworkError):
            return "网络连接失败，请稍后重试"
        if isinstance(error, urllib.error.HTTPError):
            if error.code == 404:
                return "PDF 不存在或 arXiv ID 有误（HTTP 404）"
            if error.code == 429:
                return "源站暂时限流（HTTP 429），请稍后重试"
            return f"源站返回 HTTP {error.code}"
        return str(error)

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
            meta = self._load_meta(meta_file)
            return self._repair_download_state(user_id, meta)
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
                meta = self._load_meta(meta_file)
                papers.append(self._repair_download_state(user_id, meta))

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
        meta_file = paper_dir / "meta.json"
        if meta_file.exists():
            self._repair_download_state(user_id, self._load_meta(meta_file))
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
                item["title"] = meta.title
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
