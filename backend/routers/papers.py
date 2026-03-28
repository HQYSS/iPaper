"""
论文管理 API 路由
"""
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from models import PaperCreate, PaperMeta, PaperListItem
from services.arxiv_service import arxiv_service
from services.translation_service import translation_service
from middleware.auth import get_current_user

router = APIRouter()


@router.get("", response_model=List[PaperListItem])
async def list_papers(user: dict = Depends(get_current_user)):
    uid = user["id"]
    papers = arxiv_service.list_papers(uid)
    return [
        PaperListItem(
            arxiv_id=p.arxiv_id,
            title=p.title,
            title_zh=p.title_zh,
            summary=p.summary[:200] + "..." if len(p.summary) > 200 else p.summary,
            authors=p.authors,
            download_time=p.download_time
        )
        for p in papers
    ]


@router.post("", response_model=PaperMeta)
async def add_paper(request: PaperCreate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    success, message, meta = await arxiv_service.download_paper(uid, request.arxiv_input)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    await translation_service.ensure_translation(uid, meta.arxiv_id)

    return meta


@router.get("/{paper_id}", response_model=PaperMeta)
async def get_paper(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    meta = arxiv_service.get_paper(uid, paper_id)

    if not meta:
        raise HTTPException(status_code=404, detail="论文不存在")

    return meta


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    success = arxiv_service.delete_paper(uid, paper_id)

    if not success:
        raise HTTPException(status_code=404, detail="论文不存在")

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
            raise HTTPException(status_code=404, detail=f"{lang} PDF 不存在")
        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=f"{paper_id}_{lang}.pdf"
        )

    pdf_path = arxiv_service.get_pdf_path(uid, paper_id)
    if not pdf_path:
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
