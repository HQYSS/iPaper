"""
翻译功能 API 路由
"""
from fastapi import APIRouter, HTTPException

from services.translation_service import translation_service
from services.arxiv_service import arxiv_service

router = APIRouter()


@router.post("/{paper_id}/translate")
async def trigger_translation(paper_id: str):
    """触发论文翻译（幂等）"""
    if not arxiv_service.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="论文不存在")

    task = await translation_service.ensure_translation(paper_id)
    return {
        "status": task.status,
        "info": task.info,
        "error": task.error,
    }


@router.get("/{paper_id}/translate/status")
async def get_translation_status(paper_id: str):
    """查询翻译进度"""
    if translation_service.has_zh_pdf(paper_id):
        return {"status": "finished", "info": "翻译完成", "error": ""}

    task = translation_service.get_task(paper_id)
    if not task:
        return {"status": "none", "info": "", "error": ""}

    return {
        "status": task.status,
        "info": task.info,
        "error": task.error,
    }
