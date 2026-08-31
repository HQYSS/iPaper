import json
from types import SimpleNamespace

import httpx
import pytest

from main import create_app
from middleware.auth import get_current_user
from routers import chat as chat_router


def _parse_sse(body):
    return [
        json.loads(block.removeprefix("data: "))
        for block in body.strip().split("\n\n")
        if block.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_single_paper_chat_sse_contract(monkeypatch):
    saved_histories = []

    monkeypatch.setattr(chat_router.arxiv_service, "get_paper", lambda user_id, paper_id: SimpleNamespace(title="Test"))
    monkeypatch.setattr(chat_router.arxiv_service, "get_pdf_path", lambda user_id, paper_id: None)
    monkeypatch.setattr(chat_router.cloud_chat_service, "should_delegate", lambda: False)
    monkeypatch.setattr(chat_router.llm_service, "is_configured", lambda: True)
    monkeypatch.setattr(chat_router.llm_service, "prepare_chat_api_messages", lambda **kwargs: [])

    async def chat_stream(**kwargs):
        yield "契约"
        yield "正常"

    monkeypatch.setattr(chat_router.llm_service, "chat_stream", chat_stream)
    monkeypatch.setattr(chat_router.storage_service, "get_chat_history", lambda *args: ([], None, None))
    monkeypatch.setattr(
        chat_router.storage_service,
        "save_chat_history",
        lambda *args, **kwargs: saved_histories.append((args, kwargs)),
    )
    monkeypatch.setattr(chat_router.storage_service, "set_last_active_session", lambda *args: None)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "integration-user",
        "username": "test",
        "is_admin": False,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat/2401.00001/session-1",
            json={"message": "请解释这篇论文"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert events[0] == {"type": "open"}
    assert "".join(event["content"] for event in events if event["type"] == "chunk") == "契约正常"
    assert events[-1] == {"type": "done", "finish_reason": "stop"}
    assert all(event["type"] in {"open", "chunk", "done"} for event in events)
    assert saved_histories
    final_messages = saved_histories[-1][0][3]
    assert final_messages[-1].role == "assistant"
    assert final_messages[-1].content == "契约正常"
    assert final_messages[-1].truncated is False

    task = chat_router.chat_task_service.get("single", "session-1")
    if task and task.asyncio_task:
        await task.asyncio_task
    for eviction in list(chat_router.chat_task_service._evict_tasks):
        eviction.cancel()


@pytest.mark.asyncio
async def test_cloud_prestart_failure_is_persisted(monkeypatch):
    saved_histories = []

    monkeypatch.setattr(chat_router.arxiv_service, "get_paper", lambda *args: SimpleNamespace(title="Test"))
    monkeypatch.setattr(chat_router.arxiv_service, "get_pdf_path", lambda *args: None)
    monkeypatch.setattr(chat_router.cloud_chat_service, "should_delegate", lambda: True)
    monkeypatch.setattr(chat_router.storage_service, "get_chat_history", lambda *args: ([], None, None))
    monkeypatch.setattr(
        chat_router.storage_service,
        "save_chat_history",
        lambda *args, **kwargs: saved_histories.append((args, kwargs)),
    )
    monkeypatch.setattr(chat_router.storage_service, "set_last_active_session", lambda *args: None)

    async def sync_now(*args, **kwargs):
        return None

    async def open_stream(**kwargs):
        raise RuntimeError("云端准备论文 PDF 超时，请稍后重试")

    monkeypatch.setattr(chat_router.sync_service, "sync_now", sync_now)
    monkeypatch.setattr(chat_router.cloud_chat_service, "open_single_stream", open_stream)

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "integration-user",
        "username": "test",
        "is_admin": False,
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/chat/2401.00001/session-failed",
            json={"message": "请为我详细讲解这篇论文。"},
        )

    assert response.status_code == 502
    final_messages = saved_histories[-1][0][3]
    assert [message.role for message in final_messages] == ["user", "assistant"]
    assert final_messages[0].content == "请为我详细讲解这篇论文。"
    assert final_messages[1].content == "生成失败：云端准备论文 PDF 超时，请稍后重试"
    assert saved_histories[-1][1]["trigger_sync"] is True
