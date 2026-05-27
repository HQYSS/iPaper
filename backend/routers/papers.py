"""
论文管理 API 路由
"""
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from models import PaperCreate, PaperMeta, PaperListItem, PaperOpenRequest, PaperOpenRequestState
from services.arxiv_service import arxiv_service
from services.sync_service import sync_service
from services.translation_service import translation_service
from middleware.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()
_pending_open_papers: dict[str, str] = {}


@router.get("", response_model=List[PaperListItem])
async def list_papers(user: dict = Depends(get_current_user)):
    uid = user["id"]
    papers = arxiv_service.list_papers(uid)
    logger.info("list papers count=%d", len(papers))
    return [
        PaperListItem(
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
        )
        for p in papers
    ]


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
    logger.info("add paper accepted paper=%s status=%s", meta.arxiv_id, meta.download_status)

    return meta


@router.post("/open-request", response_model=PaperOpenRequestState)
async def request_open_paper(request: PaperOpenRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    if not arxiv_service.get_paper(uid, request.paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")
    _pending_open_papers[uid] = request.paper_id
    logger.info("paper open request queued paper=%s", request.paper_id)
    return PaperOpenRequestState(paper_id=request.paper_id)


@router.get("/open-request", response_model=PaperOpenRequestState)
async def consume_open_paper_request(user: dict = Depends(get_current_user)):
    uid = user["id"]
    paper_id = _pending_open_papers.pop(uid, None)
    if paper_id:
        logger.info("paper open request consumed paper=%s", paper_id)
    return PaperOpenRequestState(paper_id=paper_id)


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
