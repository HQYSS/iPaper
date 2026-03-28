"""
用户画像 API 路由 — 进化 Agent 对话式交互
"""
import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from openai import AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

from models import EvolutionChatRequest, SaveEditPlanRequest, ChatMessage
from services.evolution_service import evolution_service
from services.storage_service import storage_service
from services.arxiv_service import arxiv_service
from middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/current")
async def get_current_profile(user: dict = Depends(get_current_user)):
    uid = user["id"]
    content = evolution_service.load_profile(uid)
    if not content:
        raise HTTPException(status_code=404, detail="画像文件不存在")
    return {"content": content}


@router.get("/changelog")
async def get_changelog(user: dict = Depends(get_current_user)):
    uid = user["id"]
    content = evolution_service.load_changelog(uid)
    return {"content": content}


@router.post("/evolution-chat")
async def evolution_chat(request: EvolutionChatRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    chat_messages: List[ChatMessage] = []
    paper_title = ""
    paper_summary = ""

    paper_ids: List[str] = []

    if request.cross_paper_session_id:
        session = storage_service.get_cross_paper_session(uid, request.cross_paper_session_id)
        if not session:
            raise HTTPException(status_code=404, detail="串讲会话不存在")
        messages_raw, _, _ = storage_service.get_cross_paper_chat_history(
            uid, request.cross_paper_session_id
        )
        chat_messages = messages_raw
        paper_ids = session.paper_ids

        titles = []
        for pid in session.paper_ids:
            p = arxiv_service.get_paper(uid, pid)
            if p:
                titles.append(p.title)
        paper_title = " / ".join(titles) if titles else "串讲对话"
        paper_summary = f"串讲论文: {', '.join(session.paper_ids)}"

    elif request.paper_id:
        paper = arxiv_service.get_paper(uid, request.paper_id)
        if not paper:
            raise HTTPException(status_code=404, detail="论文不存在")

        session_list = storage_service.list_sessions(uid, request.paper_id)
        active_sid = session_list.last_active_session_id
        if active_sid:
            messages_raw, _, _ = storage_service.get_chat_history(
                uid, request.paper_id, active_sid
            )
            chat_messages = messages_raw

        paper_ids = [request.paper_id]
        paper_title = paper.title
        paper_summary = paper.summary
    else:
        raise HTTPException(status_code=400, detail="需要提供 paper_id 或 cross_paper_session_id")

    if len(chat_messages) < 2:
        raise HTTPException(status_code=400, detail="对话轮数不足，至少需要 2 条消息")

    pdf_paths = []
    for pid in paper_ids:
        pdf_path = arxiv_service.get_pdf_path(uid, pid)
        if pdf_path:
            pdf_paths.append(pdf_path)

    async def generate():
        full_response = ""
        try:
            async for chunk in evolution_service.chat_stream(
                user_id=uid,
                evolution_messages=request.evolution_messages,
                chat_messages=chat_messages,
                paper_title=paper_title,
                paper_summary=paper_summary,
                pdf_paths=pdf_paths,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            edit_plan = evolution_service.parse_edit_plan(full_response)
            done_data = {"type": "done", "full_response": full_response}
            if edit_plan:
                done_data["edit_plan"] = edit_plan
            yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

        except AuthenticationError:
            logger.error("Evolution Agent AuthenticationError")
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期'})}\n\n"
        except RateLimitError as e:
            logger.error("Evolution Agent RateLimitError: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'API 额度不足或请求过于频繁'})}\n\n"
        except APIConnectionError as e:
            logger.error("Evolution Agent APIConnectionError: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接到 LLM 服务'})}\n\n"
        except APIStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(e.body) if hasattr(e, "body") else ""
            logger.error("Evolution Agent APIStatusError %d: %s", e.status_code, detail)
            user_msg = f"LLM 服务返回错误 ({e.status_code})"
            if detail:
                user_msg += f"：{detail}"
            yield f"data: {json.dumps({'type': 'error', 'message': user_msg})}\n\n"
        except Exception as e:
            logger.error("Evolution Agent unexpected error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'进化分析出错：{e}'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/save-edit-plan")
async def save_edit_plan(request: SaveEditPlanRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    pending = evolution_service.save_pending(uid, request.edit_plan, request.paper_title)
    return {
        "message": "编辑计划已保存",
        "validation": pending["validation"],
    }


@router.post("/apply-updates")
async def apply_updates(user: dict = Depends(get_current_user)):
    uid = user["id"]
    success = evolution_service.apply_pending(uid)
    if not success:
        raise HTTPException(status_code=404, detail="没有待确认的更新")
    return {"message": "画像已更新"}


@router.post("/reject-updates")
async def reject_updates(user: dict = Depends(get_current_user)):
    uid = user["id"]
    success = evolution_service.reject_pending(uid)
    if not success:
        raise HTTPException(status_code=404, detail="没有待确认的更新")
    return {"message": "已拒绝更新"}


@router.get("/pending-updates")
async def get_pending_updates(user: dict = Depends(get_current_user)):
    uid = user["id"]
    pending = evolution_service.get_pending(uid)
    if not pending:
        return {"has_updates": False}
    return {
        "has_updates": True,
        "timestamp": pending.get("timestamp"),
        "paper_title": pending.get("paper_title"),
        "summary": pending.get("summary"),
        "edits": pending.get("edits", []),
        "validation": pending.get("validation"),
    }
