"""
对话 API 路由（多会话 + 串讲）
"""
import json
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import AuthenticationError, RateLimitError, APIConnectionError, APIStatusError

logger = logging.getLogger(__name__)

from models import (
    ChatDraftUpdate, ChatRequest, ChatMessage, ChatHistory, ChatHistoryUpdate,
    SessionList, SessionMeta, SessionCreate,
    CrossPaperSessionCreate, CrossPaperSessionMeta, CrossPaperSessionList,
    CrossPaperAddPapersRequest, CrossPaperChatRequest, CrossPaperChatHistory,
)
from services.llm_service import llm_service
from services.storage_service import storage_service
from services.arxiv_service import arxiv_service

router = APIRouter()


def _check_paper(paper_id: str):
    paper = arxiv_service.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


def _check_cross_paper_session(session_id: str) -> CrossPaperSessionMeta:
    session = storage_service.get_cross_paper_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return session


# ==================== Cross-Paper (串讲) — 必须在 {paper_id} 路由前 ====================

@router.get("/cross-paper/sessions", response_model=CrossPaperSessionList)
async def list_cross_paper_sessions():
    """获取所有串讲会话"""
    return storage_service.list_cross_paper_sessions()


@router.post("/cross-paper/sessions", response_model=CrossPaperSessionMeta)
async def create_cross_paper_session(request: CrossPaperSessionCreate):
    """新建串讲会话"""
    for pid in request.paper_ids:
        paper = arxiv_service.get_paper(pid)
        if not paper:
            raise HTTPException(status_code=404, detail=f"论文 {pid} 不存在")

    return storage_service.create_cross_paper_session(
        paper_ids=request.paper_ids,
        title=request.title,
    )


@router.delete("/cross-paper/sessions/{session_id}")
async def delete_cross_paper_session(session_id: str):
    """删除串讲会话"""
    success = storage_service.delete_cross_paper_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return {"message": "串讲会话已删除"}


@router.put("/cross-paper/sessions/{session_id}/papers", response_model=CrossPaperSessionMeta)
async def add_papers_to_cross_paper_session(session_id: str, request: CrossPaperAddPapersRequest):
    """向串讲会话添加论文"""
    _check_cross_paper_session(session_id)

    for pid in request.paper_ids:
        paper = arxiv_service.get_paper(pid)
        if not paper:
            raise HTTPException(status_code=404, detail=f"论文 {pid} 不存在")

    updated = storage_service.add_papers_to_cross_paper_session(session_id, request.paper_ids)
    if not updated:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return updated


@router.post("/cross-paper/{session_id}")
async def cross_paper_chat(session_id: str, request: CrossPaperChatRequest):
    """串讲对话（流式响应）"""
    session = _check_cross_paper_session(session_id)

    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail="LLM API Key 未配置")

    messages, forks_raw, _ = storage_service.get_cross_paper_chat_history(session_id)

    user_message = ChatMessage(
        role="user",
        content=request.message,
        quotes=request.quotes,
    )
    messages.append(user_message)

    storage_service.save_cross_paper_chat_history(
        session_id,
        session.paper_ids,
        messages,
        forks_raw,
        {"input": "", "quotes": None},
    )
    storage_service.set_last_active_cross_paper_session(session_id)

    async def generate():
        full_response = ""
        reasoning_parts = []

        try:
            async for chunk in llm_service.chat_stream_cross_paper(
                messages=messages,
                paper_ids=session.paper_ids,
                quotes=request.quotes,
                reasoning_collector=reasoning_parts,
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            reasoning = ''.join(reasoning_parts) if reasoning_parts else None
            assistant_message = ChatMessage(
                role="assistant",
                content=full_response,
                reasoning=reasoning,
            )
            messages.append(assistant_message)
            storage_service.save_cross_paper_chat_history(
                session_id,
                session.paper_ids,
                messages,
                forks_raw,
                {"input": "", "quotes": None},
            )

            yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"

        except AuthenticationError:
            logger.error("LLM AuthenticationError")
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期，请在设置中检查'})}\n\n"
        except RateLimitError as e:
            logger.error("LLM RateLimitError: %s", e.message if hasattr(e, 'message') else e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'API 额度不足或请求过于频繁，请稍后再试'})}\n\n"
        except APIConnectionError as e:
            logger.error("LLM APIConnectionError: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接到 LLM 服务，请检查网络'})}\n\n"
        except APIStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(e.body) if hasattr(e, 'body') else ""
            logger.error("LLM APIStatusError %d: %s", e.status_code, detail)
            user_msg = f"LLM 服务返回错误 ({e.status_code})"
            if detail:
                user_msg += f"：{detail}"
            yield f"data: {json.dumps({'type': 'error', 'message': user_msg})}\n\n"
        except Exception as e:
            logger.error("LLM unexpected error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'AI 服务出现错误：{e}'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/cross-paper/{session_id}/history", response_model=CrossPaperChatHistory)
async def get_cross_paper_chat_history(session_id: str):
    """获取串讲对话历史"""
    session = _check_cross_paper_session(session_id)
    messages, forks_raw, draft_raw = storage_service.get_cross_paper_chat_history(session_id)
    storage_service.set_last_active_cross_paper_session(session_id)
    return CrossPaperChatHistory(
        session_id=session_id,
        paper_ids=session.paper_ids,
        messages=messages,
        forks=forks_raw,
        draft=draft_raw,
    )


@router.put("/cross-paper/{session_id}/history")
async def update_cross_paper_chat_history(session_id: str, request: ChatHistoryUpdate):
    """直接更新串讲对话历史"""
    session = _check_cross_paper_session(session_id)
    _, _, draft_raw = storage_service.get_cross_paper_chat_history(session_id)
    forks_dict = None
    if request.forks:
        forks_dict = {k: v.model_dump() for k, v in request.forks.items()}
    storage_service.save_cross_paper_chat_history(
        session_id, session.paper_ids, request.messages, forks_dict, draft_raw
    )
    return {"message": "对话历史已更新"}


@router.put("/cross-paper/{session_id}/history/draft")
async def update_cross_paper_chat_draft(session_id: str, request: ChatDraftUpdate):
    """更新串讲会话的未发送草稿"""
    session = _check_cross_paper_session(session_id)
    messages, forks_raw, _ = storage_service.get_cross_paper_chat_history(session_id)
    storage_service.save_cross_paper_chat_history(
        session_id,
        session.paper_ids,
        messages,
        forks_raw,
        request.draft.model_dump(exclude_none=True),
    )
    storage_service.set_last_active_cross_paper_session(session_id)
    return {"message": "草稿已更新"}


@router.delete("/cross-paper/{session_id}/history")
async def clear_cross_paper_chat_history(session_id: str):
    """清空串讲对话历史"""
    _check_cross_paper_session(session_id)
    storage_service.clear_cross_paper_chat_history(session_id)
    return {"message": "对话历史已清空"}


# ==================== 单论文 Session 管理 ====================

@router.get("/{paper_id}/sessions", response_model=SessionList)
async def list_sessions(paper_id: str):
    """获取论文的所有会话"""
    _check_paper(paper_id)
    return storage_service.list_sessions(paper_id)


@router.post("/{paper_id}/sessions", response_model=SessionMeta)
async def create_session(paper_id: str, request: SessionCreate = None):
    """新建会话"""
    _check_paper(paper_id)
    title = request.title if request else None
    return storage_service.create_session(paper_id, title)


@router.delete("/{paper_id}/sessions/{session_id}")
async def delete_session(paper_id: str, session_id: str):
    """删除会话"""
    _check_paper(paper_id)
    session_list = storage_service.list_sessions(paper_id)
    if len(session_list.sessions) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个会话")
    success = storage_service.delete_session(paper_id, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "会话已删除"}


# ==================== 单论文对话 ====================

@router.post("/{paper_id}/{session_id}")
async def chat(paper_id: str, session_id: str, request: ChatRequest):
    """发送对话消息（流式响应）"""
    _check_paper(paper_id)

    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail="LLM API Key 未配置")

    messages, forks_raw, _ = storage_service.get_chat_history(paper_id, session_id)

    user_message = ChatMessage(
        role="user",
        content=request.message,
        quotes=request.quotes,
    )
    messages.append(user_message)

    pdf_path = arxiv_service.get_pdf_path(paper_id)

    storage_service.save_chat_history(
        paper_id,
        session_id,
        messages,
        forks_raw,
        {"input": "", "quotes": None},
    )
    storage_service.set_last_active_session(paper_id, session_id)

    async def generate():
        full_response = ""
        reasoning_parts = []

        try:
            async for chunk in llm_service.chat_stream(
                messages=messages,
                pdf_path=pdf_path,
                quotes=request.quotes,
                reasoning_collector=reasoning_parts
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            reasoning = ''.join(reasoning_parts) if reasoning_parts else None
            assistant_message = ChatMessage(
                role="assistant",
                content=full_response,
                reasoning=reasoning
            )
            messages.append(assistant_message)
            storage_service.save_chat_history(
                paper_id,
                session_id,
                messages,
                forks_raw,
                {"input": "", "quotes": None},
            )

            yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"

        except AuthenticationError:
            logger.error("LLM AuthenticationError")
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期，请在设置中检查'})}\n\n"
        except RateLimitError as e:
            logger.error("LLM RateLimitError: %s", e.message if hasattr(e, 'message') else e)
            yield f"data: {json.dumps({'type': 'error', 'message': 'API 额度不足或请求过于频繁，请稍后再试'})}\n\n"
        except APIConnectionError as e:
            logger.error("LLM APIConnectionError: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接到 LLM 服务，请检查网络'})}\n\n"
        except APIStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(e.body) if hasattr(e, 'body') else ""
            logger.error("LLM APIStatusError %d: %s", e.status_code, detail)
            user_msg = f"LLM 服务返回错误 ({e.status_code})"
            if detail:
                user_msg += f"：{detail}"
            yield f"data: {json.dumps({'type': 'error', 'message': user_msg})}\n\n"
        except Exception as e:
            logger.error("LLM unexpected error: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': f'AI 服务出现错误：{e}'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/{paper_id}/{session_id}/history", response_model=ChatHistory)
async def get_chat_history(paper_id: str, session_id: str):
    """获取对话历史"""
    _check_paper(paper_id)
    messages, forks_raw, draft_raw = storage_service.get_chat_history(paper_id, session_id)
    storage_service.set_last_active_session(paper_id, session_id)
    return ChatHistory(
        paper_id=paper_id,
        session_id=session_id,
        messages=messages,
        forks=forks_raw,
        draft=draft_raw,
    )


@router.put("/{paper_id}/{session_id}/history")
async def update_chat_history(paper_id: str, session_id: str, request: ChatHistoryUpdate):
    """直接更新对话历史（编辑消息/切换分支时使用）"""
    _check_paper(paper_id)
    _, _, draft_raw = storage_service.get_chat_history(paper_id, session_id)
    forks_dict = None
    if request.forks:
        forks_dict = {k: v.model_dump() for k, v in request.forks.items()}
    storage_service.save_chat_history(
        paper_id,
        session_id,
        request.messages,
        forks_dict,
        draft_raw,
    )
    return {"message": "对话历史已更新"}


@router.put("/{paper_id}/{session_id}/history/draft")
async def update_chat_draft(paper_id: str, session_id: str, request: ChatDraftUpdate):
    """更新会话的未发送草稿"""
    _check_paper(paper_id)
    messages, forks_raw, _ = storage_service.get_chat_history(paper_id, session_id)
    storage_service.save_chat_history(
        paper_id,
        session_id,
        messages,
        forks_raw,
        request.draft.model_dump(exclude_none=True),
    )
    storage_service.set_last_active_session(paper_id, session_id)
    return {"message": "草稿已更新"}


@router.delete("/{paper_id}/{session_id}/history")
async def clear_chat_history(paper_id: str, session_id: str):
    """清空对话历史"""
    _check_paper(paper_id)
    storage_service.clear_chat_history(paper_id, session_id)
    return {"message": "对话历史已清空"}
