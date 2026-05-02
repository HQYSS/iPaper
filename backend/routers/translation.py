"""
翻译功能 API 路由
"""
from fastapi import APIRouter, HTTPException, Depends

from services.translation_service import translation_service
from services.arxiv_service import arxiv_service
from middleware.auth import get_current_user

router = APIRouter()


@router.post("/{paper_id}/translate")
async def trigger_translation(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    meta = arxiv_service.get_paper(uid, paper_id)
    if not meta:
        raise HTTPException(status_code=404, detail="论文不存在")
    if getattr(meta, "source_type", "arxiv") != "arxiv":
        raise HTTPException(status_code=400, detail="非 arXiv PDF 暂不支持中文翻译")

    task = await translation_service.ensure_translation(uid, paper_id)
    return {
        "status": task.status,
        "info": task.info,
        "error": task.error,
    }


@router.get("/{paper_id}/translate/status")
async def get_translation_status(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    if translation_service.has_zh_pdf(uid, paper_id):
        return {"status": "finished", "info": "翻译完成", "error": ""}

    task = translation_service.get_task(uid, paper_id)
    if not task:
        return {"status": "none", "info": "", "error": ""}

    return {
        "status": task.status,
        "info": task.info,
        "error": task.error,
    }
