"""
用户画像 API 路由
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks

from models import ProfileAnalysisRequest
from services.user_profile_service import user_profile_service
from services.storage_service import storage_service
from services.arxiv_service import arxiv_service

router = APIRouter()


@router.get("/pending-updates")
async def get_pending_updates():
    """获取待确认的画像更新"""
    pending = user_profile_service.get_pending_updates()
    if not pending:
        return {"has_updates": False}
    return {
        "has_updates": True,
        "timestamp": pending.get("timestamp"),
        "paper_title": pending.get("paper_title"),
        "summary": pending.get("summary"),
        "signals": pending.get("signals", []),
        "edits": pending.get("edits", []),
    }


@router.post("/apply-updates")
async def apply_updates():
    """确认并应用画像更新"""
    success = user_profile_service.apply_pending_updates()
    if not success:
        raise HTTPException(status_code=404, detail="没有待确认的更新")
    return {"message": "画像已更新"}


@router.post("/reject-updates")
async def reject_updates():
    """拒绝画像更新"""
    success = user_profile_service.reject_pending_updates()
    if not success:
        raise HTTPException(status_code=404, detail="没有待确认的更新")
    return {"message": "已拒绝更新"}


@router.post("/trigger-analysis")
async def trigger_analysis(request: ProfileAnalysisRequest, background_tasks: BackgroundTasks):
    """触发画像分析（在后台异步执行）"""
    paper = arxiv_service.get_paper(request.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")

    session_list = storage_service.list_sessions(request.paper_id)
    active_sid = session_list.last_active_session_id
    if not active_sid:
        return {"message": "没有活跃会话，跳过分析"}
    messages, _ = storage_service.get_chat_history(request.paper_id, active_sid)
    if len(messages) < 2:
        return {"message": "对话轮数不足，跳过分析"}

    background_tasks.add_task(
        user_profile_service.analyze_conversation,
        messages,
        paper.title,
        paper.summary,
    )

    return {"message": "画像分析已在后台启动"}
