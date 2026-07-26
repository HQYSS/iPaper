"""
对话 API 路由（多会话 + 串讲）

LLM 生成任务架构：
- POST /api/chat/{paper}/{session} 启动一个独立的 ChatTask（asyncio.Task），handler 仅作为该任务的"第一个订阅者"，从队列拉 SSE 事件
- 客户端断连只会摘掉订阅者，task 继续跑、继续向 chat_history.json 增量写 partial（每 0.5s 节流一次）
- 客户端重连用 GET /history 拿落盘最新内容；可选用 GET /stream 继续订阅未结束任务（V2，不在本次实现）
- 用户主动停止用 POST /stop 显式取消 task
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError, RateLimitError

logger = logging.getLogger(__name__)

from config import settings
from middleware.auth import get_current_user, get_sync_user
from models import (
    ChatDraftUpdate,
    ChatHistory,
    ChatHistoryUpdate,
    ChatMessage,
    ChatRequest,
    CloudCrossPaperChatRequest,
    CloudSingleChatRequest,
    CrossPaperAddPapersRequest,
    CrossPaperChatHistory,
    CrossPaperChatRequest,
    CrossPaperSessionCreate,
    CrossPaperSessionList,
    CrossPaperSessionMeta,
    SessionCreate,
    SessionList,
    SessionMeta,
)
from services.arxiv_service import arxiv_service
from services.chat_task_service import chat_task_service
from services.cloud_chat_service import cloud_chat_service
from services.llm_service import PageSelectionRequiredError, llm_service
from services.storage_service import storage_service
from services.sync_service import sync_service

router = APIRouter()


def _check_paper(uid: str, paper_id: str):
    paper = arxiv_service.get_paper(uid, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    return paper


def _check_cross_paper_session(uid: str, session_id: str) -> CrossPaperSessionMeta:
    session = storage_service.get_cross_paper_session(uid, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return session


def _page_selection_http_exception(exc: PageSelectionRequiredError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "page_selection_required",
            "message": str(exc),
            "requirements": exc.requirements,
        },
    )


def _llm_error_message(exc: Exception) -> str:
    """把 LLM SDK 异常映射成给用户看的中文消息"""
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或已过期，请在设置中检查"
    if isinstance(exc, RateLimitError):
        return "API 额度不足或请求过于频繁，请稍后再试"
    if isinstance(exc, APIConnectionError):
        return "无法连接到 LLM 服务，请检查网络"
    if isinstance(exc, APIStatusError):
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = str(exc.body) if hasattr(exc, "body") else ""
        msg = f"LLM 服务返回错误 ({exc.status_code})"
        if detail:
            msg += f"：{detail}"
        return msg
    if isinstance(exc, APIError):
        return "LLM 流式响应中断，请稍后重试"
    return f"AI 服务出现错误：{exc}"


def _cloud_chat_forbidden_if_not_server():
    if not settings.is_sync_server:
        raise HTTPException(status_code=403, detail="该接口仅允许云端后端执行")


async def _cloud_generate_events(stream):
    reasoning_collector: list[str] = []
    content_blocks_collector: list[dict] = []
    response_metadata_collector: dict[str, str] = {}
    try:
        async for chunk in stream(
            reasoning_collector,
            content_blocks_collector,
            response_metadata_collector,
        ):
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
        done_event = {
            'type': 'done',
            'finish_reason': 'stop',
            'reasoning': ''.join(reasoning_collector) if reasoning_collector else None,
            'content_blocks': content_blocks_collector or None,
            'response_id': response_metadata_collector.get('response_id'),
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
    except (AuthenticationError, RateLimitError, APIConnectionError, APIStatusError, APIError) as e:
        yield f"data: {json.dumps({'type': 'error', 'message': _llm_error_message(e)}, ensure_ascii=False)}\n\n"
    except Exception as e:
        logger.exception("cloud chat stream failed: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e) or '云端生成失败'}, ensure_ascii=False)}\n\n"


@router.post("/_cloud/single/{paper_id}/stream")
async def cloud_single_chat_stream(
    paper_id: str,
    request: CloudSingleChatRequest,
    user: dict = Depends(get_sync_user),
):
    _cloud_chat_forbidden_if_not_server()
    uid = user["id"]
    paper = _check_paper(uid, paper_id)
    pdf_path = arxiv_service.get_pdf_path(uid, paper_id)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="云端还没有这篇论文 PDF，请等待同步完成后重试")
    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail=llm_service.configured_error_message())

    try:
        prepared_api_messages = llm_service.prepare_chat_api_messages(
            messages=request.messages,
            pdf_path=pdf_path,
            quotes=request.quotes,
            page_selections=request.page_selections,
            paper_id=paper_id,
            paper_title=request.paper_title or paper.title,
        )
    except PageSelectionRequiredError as exc:
        raise _page_selection_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "[chat cloud single] user=%s paper=%s messages=%d delegated_pdf=%s",
        uid,
        paper_id,
        len(request.messages),
        bool(pdf_path),
    )

    async def stream(reasoning_collector, content_blocks_collector, response_metadata_collector):
        async for chunk in llm_service.chat_stream(
            messages=request.messages,
            pdf_path=pdf_path,
            quotes=request.quotes,
            reasoning_collector=reasoning_collector,
            content_blocks_collector=content_blocks_collector,
            response_metadata_collector=response_metadata_collector,
            prepared_api_messages=prepared_api_messages,
        ):
            yield chunk

    return StreamingResponse(
        _cloud_generate_events(stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/_cloud/cross-paper/stream")
async def cloud_cross_paper_chat_stream(
    request: CloudCrossPaperChatRequest,
    user: dict = Depends(get_sync_user),
):
    _cloud_chat_forbidden_if_not_server()
    uid = user["id"]
    for pid in request.paper_ids:
        _check_paper(uid, pid)
        if not arxiv_service.get_pdf_path(uid, pid):
            raise HTTPException(status_code=404, detail=f"云端还没有论文 {pid} 的 PDF，请等待同步完成后重试")
    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail=llm_service.configured_error_message())

    try:
        prepared_api_messages = llm_service.prepare_cross_paper_api_messages(
            messages=request.messages,
            user_id=uid,
            paper_ids=request.paper_ids,
            quotes=request.quotes,
            page_selections=request.page_selections,
        )
    except PageSelectionRequiredError as exc:
        raise _page_selection_http_exception(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "[chat cloud cross] user=%s papers=%s messages=%d",
        uid,
        ",".join(request.paper_ids),
        len(request.messages),
    )

    async def stream(reasoning_collector, content_blocks_collector, response_metadata_collector):
        async for chunk in llm_service.chat_stream_cross_paper(
            messages=request.messages,
            paper_ids=request.paper_ids,
            quotes=request.quotes,
            reasoning_collector=reasoning_collector,
            content_blocks_collector=content_blocks_collector,
            response_metadata_collector=response_metadata_collector,
            prepared_api_messages=prepared_api_messages,
        ):
            yield chunk

    return StreamingResponse(
        _cloud_generate_events(stream),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ==================== Cross-Paper (串讲) — 必须在 {paper_id} 路由前 ====================


@router.get("/cross-paper/sessions", response_model=CrossPaperSessionList)
async def list_cross_paper_sessions(user: dict = Depends(get_current_user)):
    return storage_service.list_cross_paper_sessions(user["id"])


@router.post("/cross-paper/sessions", response_model=CrossPaperSessionMeta)
async def create_cross_paper_session(request: CrossPaperSessionCreate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    for pid in request.paper_ids:
        paper = arxiv_service.get_paper(uid, pid)
        if not paper:
            raise HTTPException(status_code=404, detail=f"论文 {pid} 不存在")

    return storage_service.create_cross_paper_session(
        uid,
        paper_ids=request.paper_ids,
        title=request.title,
    )


@router.delete("/cross-paper/sessions/{session_id}")
async def delete_cross_paper_session(session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    success = storage_service.delete_cross_paper_session(uid, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return {"message": "串讲会话已删除"}


@router.put("/cross-paper/sessions/{session_id}/papers", response_model=CrossPaperSessionMeta)
async def add_papers_to_cross_paper_session(session_id: str, request: CrossPaperAddPapersRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_cross_paper_session(uid, session_id)

    for pid in request.paper_ids:
        paper = arxiv_service.get_paper(uid, pid)
        if not paper:
            raise HTTPException(status_code=404, detail=f"论文 {pid} 不存在")

    updated = storage_service.add_papers_to_cross_paper_session(uid, session_id, request.paper_ids)
    if not updated:
        raise HTTPException(status_code=404, detail="串讲会话不存在")
    return updated


@router.post("/cross-paper/{session_id}")
async def cross_paper_chat(session_id: str, request: CrossPaperChatRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    session = _check_cross_paper_session(uid, session_id)
    logger.info(
        "[chat cross:%s] request user=%s papers=%s provider=%s msg_chars=%d quotes=%d page_selections=%d",
        session_id,
        uid,
        ",".join(session.paper_ids),
        settings.llm.provider,
        len(request.message or ""),
        len(request.quotes or []),
        len(request.page_selections or []),
    )

    delegate_to_cloud = cloud_chat_service.should_delegate()
    if not delegate_to_cloud and not llm_service.is_configured():
        logger.warning("[chat cross:%s] provider not configured provider=%s", session_id, settings.llm.provider)
        raise HTTPException(status_code=400, detail=llm_service.configured_error_message())

    if chat_task_service.is_running("cross", session_id):
        logger.warning("[chat cross:%s] rejected because task already running", session_id)
        raise HTTPException(status_code=409, detail="该会话已有正在生成的回复，请等待完成或先停止")

    messages, forks_raw, _ = storage_service.get_cross_paper_chat_history(uid, session_id)
    logger.info("[chat cross:%s] loaded history messages=%d", session_id, len(messages))

    captured_messages_for_stream = messages + [ChatMessage(role="user", content=request.message, quotes=request.quotes)]
    prepared_api_messages = None
    cloud_stream = None
    try:
        if delegate_to_cloud:
            for pid in session.paper_ids:
                await sync_service.sync_now("cloud-cross-chat-before-open", pid, wait_if_busy=False)
            cloud_stream = await cloud_chat_service.open_cross_paper_stream(
                paper_ids=session.paper_ids,
                messages=captured_messages_for_stream,
                quotes=request.quotes,
                page_selections=request.page_selections,
            )
            logger.info("[chat cross:%s] delegated_to_cloud=true papers=%s", session_id, ",".join(session.paper_ids))
        else:
            prepared_api_messages = llm_service.prepare_cross_paper_api_messages(
                messages=captured_messages_for_stream,
                user_id=uid,
                paper_ids=session.paper_ids,
                quotes=request.quotes,
                page_selections=request.page_selections,
            )
            prepared_size = len(prepared_api_messages) if isinstance(prepared_api_messages, str) else len(prepared_api_messages or [])
            logger.info("[chat cross:%s] prepared provider payload units=%d", session_id, prepared_size)
    except PageSelectionRequiredError as exc:
        logger.info("[chat cross:%s] page selection required requirements=%d", session_id, len(exc.requirements))
        raise _page_selection_http_exception(exc)
    except ValueError as exc:
        logger.warning("[chat cross:%s] invalid request: %s", session_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.warning("[chat cross:%s] cloud delegation failed before start: %s", session_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("[chat cross:%s] cloud delegation failed before start", session_id)
        raise HTTPException(status_code=502, detail=f"云端生成准备失败：{exc}")

    user_message = ChatMessage(
        role="user",
        content=request.message,
        quotes=request.quotes,
    )
    placeholder = ChatMessage(role="assistant", content="", truncated=True)
    messages.append(user_message)
    messages.append(placeholder)

    storage_service.save_cross_paper_chat_history(
        uid,
        session_id,
        session.paper_ids,
        messages,
        forks_raw,
        {"input": "", "quotes": None, "page_selections": request.page_selections},
    )
    logger.info("[chat cross:%s] saved user message and assistant placeholder messages=%d", session_id, len(messages))
    storage_service.set_last_active_cross_paper_session(uid, session_id)

    async def stream_factory(reasoning_collector, content_blocks_collector, response_metadata_collector):
        try:
            if cloud_stream is not None:
                async for chunk in cloud_stream.aiter_chunks(
                    reasoning_collector=reasoning_collector,
                    content_blocks_collector=content_blocks_collector,
                    response_metadata_collector=response_metadata_collector,
                ):
                    yield chunk
            else:
                async for chunk in llm_service.chat_stream_cross_paper(
                    messages=captured_messages_for_stream,
                    paper_ids=session.paper_ids,
                    quotes=request.quotes,
                    reasoning_collector=reasoning_collector,
                    content_blocks_collector=content_blocks_collector,
                    response_metadata_collector=response_metadata_collector,
                    prepared_api_messages=prepared_api_messages,
                ):
                    yield chunk
        except (AuthenticationError, RateLimitError, APIConnectionError, APIStatusError, APIError) as e:
            raise RuntimeError(_llm_error_message(e)) from e

    def persist(content: str, reasoning: Optional[str], content_blocks: Optional[list], response_id: Optional[str], in_progress: bool, finish_reason: Optional[str]):
        cur_messages, cur_forks, cur_draft = storage_service.get_cross_paper_chat_history(uid, session_id)
        truncated = in_progress or finish_reason in ("length", "stopped", "error")
        new_msg = ChatMessage(
            role="assistant",
            content=content,
            content_blocks=content_blocks,
            response_id=response_id,
            reasoning=reasoning,
            truncated=truncated,
        )
        if cur_messages and cur_messages[-1].role == "assistant":
            cur_messages[-1] = new_msg
        else:
            cur_messages.append(new_msg)
        storage_service.save_cross_paper_chat_history(
            uid, session_id, session.paper_ids, cur_messages, cur_forks, cur_draft
        )

    task = chat_task_service.start(
        kind="cross",
        user_id=uid,
        session_id=session_id,
        paper_id=None,
        stream_factory=stream_factory,
        persist=persist,
    )
    logger.info("[chat cross:%s] task started", session_id)

    async def generate():
        try:
            async for ev in chat_task_service.stream_to_subscriber(task):
                # 把 task 内部的事件转换成给前端的 SSE：error 事件可能包含原始 SDK 异常 message，统一处理
                if ev.get("type") == "error":
                    raw = ev.get("message") or ""
                    ev = {"type": "error", "message": raw}
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("cross-paper SSE relay failed: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '连接异常，请刷新重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 不要缓冲 SSE
        },
    )


@router.post("/cross-paper/{session_id}/stop")
async def stop_cross_paper_chat(session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_cross_paper_session(uid, session_id)
    stopped = await chat_task_service.stop("cross", session_id)
    return {"stopped": stopped}


@router.get("/cross-paper/{session_id}/history", response_model=CrossPaperChatHistory)
async def get_cross_paper_chat_history(session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    session = _check_cross_paper_session(uid, session_id)
    messages, forks_raw, draft_raw = storage_service.get_cross_paper_chat_history(uid, session_id)
    storage_service.set_last_active_cross_paper_session(uid, session_id)

    # 清理死掉的空 assistant 占位（任务已不存在但 truncated=True 且 content 为空 → 残留尸体）
    if (
        messages
        and messages[-1].role == "assistant"
        and messages[-1].truncated
        and not (messages[-1].content or "").strip()
        and not chat_task_service.is_running("cross", session_id)
    ):
        messages = messages[:-1]
        storage_service.save_cross_paper_chat_history(
            uid, session_id, session.paper_ids, messages, forks_raw, draft_raw
        )

    return CrossPaperChatHistory(
        session_id=session_id,
        paper_ids=session.paper_ids,
        messages=messages,
        forks=forks_raw,
        draft=draft_raw,
    )


@router.put("/cross-paper/{session_id}/history")
async def update_cross_paper_chat_history(session_id: str, request: ChatHistoryUpdate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    session = _check_cross_paper_session(uid, session_id)
    if chat_task_service.is_running("cross", session_id):
        raise HTTPException(status_code=409, detail="该会话正在生成回复，请等待完成或先停止")
    _, _, draft_raw = storage_service.get_cross_paper_chat_history(uid, session_id)
    forks_dict = None
    if request.forks:
        forks_dict = {k: v.model_dump() for k, v in request.forks.items()}
    storage_service.save_cross_paper_chat_history(
        uid, session_id, session.paper_ids, request.messages, forks_dict, draft_raw
    )
    return {"message": "对话历史已更新"}


@router.put("/cross-paper/{session_id}/history/draft")
async def update_cross_paper_chat_draft(session_id: str, request: ChatDraftUpdate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    session = _check_cross_paper_session(uid, session_id)
    messages, forks_raw, _ = storage_service.get_cross_paper_chat_history(uid, session_id)
    storage_service.save_cross_paper_chat_history(
        uid,
        session_id,
        session.paper_ids,
        messages,
        forks_raw,
        request.draft.model_dump(exclude_none=True),
    )
    storage_service.set_last_active_cross_paper_session(uid, session_id)
    return {"message": "草稿已更新"}


@router.delete("/cross-paper/{session_id}/history")
async def clear_cross_paper_chat_history(session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_cross_paper_session(uid, session_id)
    if chat_task_service.is_running("cross", session_id):
        await chat_task_service.stop("cross", session_id)
    storage_service.clear_cross_paper_chat_history(uid, session_id)
    return {"message": "对话历史已清空"}


# ==================== 单论文 Session 管理 ====================


@router.get("/{paper_id}/sessions", response_model=SessionList)
async def list_sessions(paper_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    return storage_service.list_sessions(uid, paper_id)


@router.post("/{paper_id}/sessions", response_model=SessionMeta)
async def create_session(paper_id: str, request: SessionCreate = None, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    title = request.title if request else None
    return storage_service.create_session(uid, paper_id, title)


@router.delete("/{paper_id}/sessions/{session_id}")
async def delete_session(paper_id: str, session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    session_list = storage_service.list_sessions(uid, paper_id)
    if len(session_list.sessions) <= 1:
        raise HTTPException(status_code=400, detail="至少保留一个会话")
    if chat_task_service.is_running("single", session_id):
        await chat_task_service.stop("single", session_id)
    success = storage_service.delete_session(uid, paper_id, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"message": "会话已删除"}


# ==================== 单论文对话 ====================


@router.post("/{paper_id}/{session_id}")
async def chat(paper_id: str, session_id: str, request: ChatRequest, user: dict = Depends(get_current_user)):
    uid = user["id"]
    paper = _check_paper(uid, paper_id)
    logger.info(
        "[chat single:%s] request user=%s paper=%s provider=%s msg_chars=%d quotes=%d page_selections=%d",
        session_id,
        uid,
        paper_id,
        settings.llm.provider,
        len(request.message or ""),
        len(request.quotes or []),
        len(request.page_selections or []),
    )

    delegate_to_cloud = cloud_chat_service.should_delegate()
    if not delegate_to_cloud and not llm_service.is_configured():
        logger.warning("[chat single:%s] provider not configured provider=%s", session_id, settings.llm.provider)
        raise HTTPException(status_code=400, detail=llm_service.configured_error_message())

    if chat_task_service.is_running("single", session_id):
        logger.warning("[chat single:%s] rejected because task already running", session_id)
        raise HTTPException(status_code=409, detail="该会话已有正在生成的回复，请等待完成或先停止")

    messages, forks_raw, _ = storage_service.get_chat_history(uid, paper_id, session_id)
    pdf_path = arxiv_service.get_pdf_path(uid, paper_id)
    logger.info(
        "[chat single:%s] loaded history messages=%d pdf_available=%s",
        session_id,
        len(messages),
        bool(pdf_path),
    )

    captured_messages_for_stream = messages + [ChatMessage(role="user", content=request.message, quotes=request.quotes)]
    prepared_api_messages = None
    cloud_stream = None
    try:
        if delegate_to_cloud:
            await sync_service.sync_now("cloud-chat-before-open", paper_id, wait_if_busy=False)
            cloud_stream = await cloud_chat_service.open_single_stream(
                paper_id=paper_id,
                messages=captured_messages_for_stream,
                quotes=request.quotes,
                page_selections=request.page_selections,
                paper_title=paper.title,
            )
            logger.info("[chat single:%s] delegated_to_cloud=true paper=%s", session_id, paper_id)
        else:
            prepared_api_messages = llm_service.prepare_chat_api_messages(
                messages=captured_messages_for_stream,
                pdf_path=pdf_path,
                quotes=request.quotes,
                page_selections=request.page_selections,
                paper_id=paper_id,
                paper_title=paper.title,
            )
            prepared_size = len(prepared_api_messages) if isinstance(prepared_api_messages, str) else len(prepared_api_messages or [])
            logger.info("[chat single:%s] prepared provider payload units=%d", session_id, prepared_size)
    except PageSelectionRequiredError as exc:
        logger.info("[chat single:%s] page selection required requirements=%d", session_id, len(exc.requirements))
        raise _page_selection_http_exception(exc)
    except ValueError as exc:
        logger.warning("[chat single:%s] invalid request: %s", session_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.warning("[chat single:%s] cloud delegation failed before start: %s", session_id, exc)
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.exception("[chat single:%s] cloud delegation failed before start", session_id)
        raise HTTPException(status_code=502, detail=f"云端生成准备失败：{exc}")

    user_message = ChatMessage(
        role="user",
        content=request.message,
        quotes=request.quotes,
    )
    placeholder = ChatMessage(role="assistant", content="", truncated=True)
    messages.append(user_message)
    messages.append(placeholder)

    storage_service.save_chat_history(
        uid,
        paper_id,
        session_id,
        messages,
        forks_raw,
        {"input": "", "quotes": None, "page_selections": request.page_selections},
    )
    logger.info("[chat single:%s] saved user message and assistant placeholder messages=%d", session_id, len(messages))
    storage_service.set_last_active_session(uid, paper_id, session_id)

    async def stream_factory(reasoning_collector, content_blocks_collector, response_metadata_collector):
        try:
            if cloud_stream is not None:
                async for chunk in cloud_stream.aiter_chunks(
                    reasoning_collector=reasoning_collector,
                    content_blocks_collector=content_blocks_collector,
                    response_metadata_collector=response_metadata_collector,
                ):
                    yield chunk
            else:
                async for chunk in llm_service.chat_stream(
                    messages=captured_messages_for_stream,
                    pdf_path=pdf_path,
                    quotes=request.quotes,
                    reasoning_collector=reasoning_collector,
                    content_blocks_collector=content_blocks_collector,
                    response_metadata_collector=response_metadata_collector,
                    prepared_api_messages=prepared_api_messages,
                ):
                    yield chunk
        except (AuthenticationError, RateLimitError, APIConnectionError, APIStatusError, APIError) as e:
            raise RuntimeError(_llm_error_message(e)) from e

    def persist(content: str, reasoning: Optional[str], content_blocks: Optional[list], response_id: Optional[str], in_progress: bool, finish_reason: Optional[str]):
        cur_messages, cur_forks, cur_draft = storage_service.get_chat_history(uid, paper_id, session_id)
        truncated = in_progress or finish_reason in ("length", "stopped", "error")
        new_msg = ChatMessage(
            role="assistant",
            content=content,
            content_blocks=content_blocks,
            response_id=response_id,
            reasoning=reasoning,
            truncated=truncated,
        )
        if cur_messages and cur_messages[-1].role == "assistant":
            cur_messages[-1] = new_msg
        else:
            cur_messages.append(new_msg)
        storage_service.save_chat_history(
            uid, paper_id, session_id, cur_messages, cur_forks, cur_draft
        )

    task = chat_task_service.start(
        kind="single",
        user_id=uid,
        session_id=session_id,
        paper_id=paper_id,
        stream_factory=stream_factory,
        persist=persist,
    )
    logger.info("[chat single:%s] task started", session_id)

    async def generate():
        try:
            async for ev in chat_task_service.stream_to_subscriber(task):
                if ev.get("type") == "error":
                    raw_err = ev.get("message") or ""
                    # task 里 stream_factory 抛 SDK 异常时已保存为 task.error_message
                    # 这里把 SDK 错误名映射成中文（如果 message 还是英文异常）
                    ev = {"type": "error", "message": raw_err}
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("chat SSE relay failed: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': '连接异常，请刷新重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{paper_id}/{session_id}/stop")
async def stop_chat(paper_id: str, session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    stopped = await chat_task_service.stop("single", session_id)
    return {"stopped": stopped}


@router.get("/{paper_id}/{session_id}/history", response_model=ChatHistory)
async def get_chat_history(paper_id: str, session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    messages, forks_raw, draft_raw = storage_service.get_chat_history(uid, paper_id, session_id)
    storage_service.set_last_active_session(uid, paper_id, session_id)

    # 清理死掉的空 assistant 占位（任务已不存在但 truncated=True 且 content 为空 → 残留尸体）
    if (
        messages
        and messages[-1].role == "assistant"
        and messages[-1].truncated
        and not (messages[-1].content or "").strip()
        and not chat_task_service.is_running("single", session_id)
    ):
        messages = messages[:-1]
        storage_service.save_chat_history(
            uid, paper_id, session_id, messages, forks_raw, draft_raw
        )

    return ChatHistory(
        paper_id=paper_id,
        session_id=session_id,
        messages=messages,
        forks=forks_raw,
        draft=draft_raw,
    )


@router.put("/{paper_id}/{session_id}/history")
async def update_chat_history(paper_id: str, session_id: str, request: ChatHistoryUpdate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    if chat_task_service.is_running("single", session_id):
        raise HTTPException(status_code=409, detail="该会话正在生成回复，请等待完成或先停止")
    _, _, draft_raw = storage_service.get_chat_history(uid, paper_id, session_id)
    forks_dict = None
    if request.forks:
        forks_dict = {k: v.model_dump() for k, v in request.forks.items()}
    storage_service.save_chat_history(
        uid,
        paper_id,
        session_id,
        request.messages,
        forks_dict,
        draft_raw,
    )
    return {"message": "对话历史已更新"}


@router.put("/{paper_id}/{session_id}/history/draft")
async def update_chat_draft(paper_id: str, session_id: str, request: ChatDraftUpdate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    messages, forks_raw, _ = storage_service.get_chat_history(uid, paper_id, session_id)
    storage_service.save_chat_history(
        uid,
        paper_id,
        session_id,
        messages,
        forks_raw,
        request.draft.model_dump(exclude_none=True),
    )
    storage_service.set_last_active_session(uid, paper_id, session_id)
    return {"message": "草稿已更新"}


@router.delete("/{paper_id}/{session_id}/history")
async def clear_chat_history(paper_id: str, session_id: str, user: dict = Depends(get_current_user)):
    uid = user["id"]
    _check_paper(uid, paper_id)
    if chat_task_service.is_running("single", session_id):
        await chat_task_service.stop("single", session_id)
    storage_service.clear_chat_history(uid, paper_id, session_id)
    return {"message": "对话历史已清空"}
