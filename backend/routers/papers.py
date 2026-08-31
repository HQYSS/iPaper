"""
论文管理 API 路由
"""
import logging
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from models import (
    PaperCreate,
    PaperMeta,
    PaperListItem,
    PaperOpenRequest,
    PaperOpenRequestAck,
    PaperOpenRequestState,
)
from services.arxiv_service import arxiv_service
from services.sync_service import sync_service
from services.translation_service import translation_service
from middleware.auth import get_current_user
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
_OPEN_REQUEST_TTL_SECONDS = 300
_pending_open_papers: dict[tuple[str, str], dict] = {}


def _pending_open_request(uid: str, target: str) -> Optional[dict]:
    key = (uid, target)
    request = _pending_open_papers.get(key)
    if request and time.monotonic() - request["created_at"] > _OPEN_REQUEST_TTL_SECONDS:
        _pending_open_papers.pop(key, None)
        return None
    return request


def _pdf_size_bytes(user_id: str, paper_id: str) -> Optional[int]:
    pdf_path = arxiv_service.get_pdf_path(user_id, paper_id)
    if not pdf_path:
        return None
    try:
        return pdf_path.stat().st_size
    except OSError:
        return None


@router.get("", response_model=List[PaperListItem])
async def list_papers(user: dict = Depends(get_current_user)):
    uid = user["id"]
    papers = arxiv_service.list_papers(uid)
    remote_pdf_statuses = {}
    try:
        remote_pdf_statuses = await sync_service.get_remote_pdf_statuses()
    except Exception:
        logger.warning("failed to fetch cloud PDF statuses", exc_info=True)
    logger.info("list papers count=%d", len(papers))
    items = []
    for p in papers:
        local_progress = arxiv_service.get_download_progress(uid, p.arxiv_id)
        remote = remote_pdf_statuses.get(p.arxiv_id)
        cloud_status = (
            "downloading"
            if settings.is_sync_client and getattr(p, "source_type", "arxiv") == "arxiv"
            else None
        )
        if remote is not None:
            cloud_status = (
                "ready" if remote.get("pdf_available")
                else remote.get("pdf_download_status") or "downloading"
            )
        items.append(PaperListItem(
            arxiv_id=p.arxiv_id,
            source_type=getattr(p, "source_type", "arxiv") or "arxiv",
            source_url=getattr(p, "source_url", None),
            title=p.title,
            title_zh=p.title_zh,
            summary=p.summary[:200] + "..." if len(p.summary) > 200 else p.summary,
            authors=p.authors,
            download_time=p.download_time,
            download_status=getattr(p, "download_status", "ready") or "ready",
            download_error=getattr(p, "download_error", None),
            pdf_size_bytes=_pdf_size_bytes(uid, p.arxiv_id),
            **local_progress,
            cloud_download_status=cloud_status,
            cloud_download_error=(remote or {}).get("pdf_download_error"),
            cloud_download_bytes=(remote or {}).get("pdf_download_bytes", 0),
            cloud_download_total_bytes=(remote or {}).get("pdf_download_total_bytes"),
            cloud_download_progress=(remote or {}).get("pdf_download_progress"),
        ))
    return items


@router.post("", response_model=PaperMeta)
async def add_paper(request: PaperCreate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    logger.info("add paper requested input=%s", request.arxiv_input)
    success, message, meta = await arxiv_service.download_paper(
        uid,
        request.arxiv_input,
        metadata_fallback={
            "title": request.title,
            "summary": request.summary,
            "authors": request.authors,
            "source_url": request.source_url,
        },
    )

    if not success:
        logger.warning("add paper failed input=%s message=%s", request.arxiv_input, message)
        raise HTTPException(status_code=400, detail=message)

    sync_service.clear_paper_tombstone(uid, meta.arxiv_id)
    if getattr(meta, "source_type", "arxiv") == "arxiv":
        await translation_service.ensure_translation(uid, meta.arxiv_id)
    sync_service.request_sync("paper-added", meta.arxiv_id)
    await sync_service.announce_paper_metadata(uid, meta.arxiv_id)
    logger.info("add paper accepted paper=%s status=%s", meta.arxiv_id, meta.download_status)

    return meta


@router.post("/open-request", response_model=PaperOpenRequestState)
async def request_open_paper(request: PaperOpenRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    if not arxiv_service.get_paper(uid, request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")
    request_id = uuid.uuid4().hex
    _pending_open_papers[(uid, request.target)] = {
        "paper_id": request.paper_id,
        "request_id": request_id,
        "target": request.target,
        "created_at": time.monotonic(),
    }
    logger.info(
        "paper open request queued paper=%s target=%s request=%s",
        request.paper_id,
        request.target,
        request_id,
    )
    return PaperOpenRequestState(
        paper_id=request.paper_id,
        request_id=request_id,
        target=request.target,
    )


@router.get("/open-request", response_model=PaperOpenRequestState)
async def get_open_paper_request(
    target: str = "electron",
    user: dict = Depends(get_current_user),
):
    uid = user["id"]
    if target not in {"electron", "web"}:
        raise HTTPException(status_code=422, detail="不支持的目标客户端")
    request = _pending_open_request(uid, target)
    return PaperOpenRequestState(**request) if request else PaperOpenRequestState()


@router.post("/open-request/ack", response_model=PaperOpenRequestState)
async def acknowledge_open_paper_request(
    acknowledgement: PaperOpenRequestAck,
    user: dict = Depends(get_current_user),
):
    uid = user["id"]
    for key, request in list(_pending_open_papers.items()):
        if key[0] != uid or request["request_id"] != acknowledgement.request_id:
            continue
        _pending_open_papers.pop(key, None)
        logger.info(
            "paper open request acknowledged paper=%s target=%s request=%s",
            request["paper_id"],
            request["target"],
            request["request_id"],
        )
        return PaperOpenRequestState(**request)
    return PaperOpenRequestState()


@router.get("/{paper_id}", response_model=PaperMeta)
async def get_paper(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    meta = arxiv_service.get_paper(uid, paper_id)

    if not meta:
        logger.warning("get paper not found paper=%s", paper_id)
        raise HTTPException(status_code=404, detail="论文不存在")

    return meta


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    success = sync_service.delete_paper(uid, paper_id)

    if not success:
        logger.warning("delete paper not found paper=%s", paper_id)
        raise HTTPException(status_code=404, detail="论文不存在")

    sync_service.request_sync("paper-deleted", paper_id)
    logger.info("paper deleted paper=%s", paper_id)
    return {"message": "删除成功"}


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(paper_id: str, lang: str = "en", user: dict = Depends(get_current_user)):
    uid = user["id"]
    paper_dir = arxiv_service.get_paper_dir(uid, paper_id)

    filename_map = {
        "zh": "paper_zh.pdf",
        "bilingual": "paper_bilingual.pdf",
    }

    if lang in filename_map:
        path = paper_dir / filename_map[lang]
        if not path.exists():
            logger.warning("translated pdf missing paper=%s lang=%s", paper_id, lang)
            raise HTTPException(status_code=404, detail=f"{lang} PDF 不存在")
        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=f"{paper_id}_{lang}.pdf"
        )

    pdf_path = arxiv_service.get_pdf_path(uid, paper_id)
    if not pdf_path:
        logger.warning("pdf missing paper=%s", paper_id)
        raise HTTPException(status_code=404, detail="PDF 不存在")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{paper_id}.pdf"
    )


@router.get("/{paper_id}/translations")
async def check_translations(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    paper_dir = arxiv_service.get_paper_dir(uid, paper_id)
    return {
        "zh": (paper_dir / "paper_zh.pdf").exists(),
        "bilingual": (paper_dir / "paper_bilingual.pdf").exists(),
    }


@router.get("/{paper_id}/export")
async def export_paper(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    pdf_path = arxiv_service.get_pdf_path(uid, paper_id)

    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF 不存在")

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{paper_id}.pdf",
        headers={"Content-Disposition": f"attachment; filename={paper_id}.pdf"}
    )
