import asyncio

import pytest

from services.chat_task_service import ChatTaskService


async def _finish(service, task):
    await task.asyncio_task
    for eviction in list(service._evict_tasks):
        eviction.cancel()
    if service._evict_tasks:
        await asyncio.gather(*service._evict_tasks, return_exceptions=True)


def _start(service, stream_factory, persisted):
    return service.start(
        kind="single",
        user_id="test-user",
        session_id="test-session",
        paper_id="paper-1",
        stream_factory=stream_factory,
        persist=lambda *args: persisted.append(args),
    )


@pytest.mark.asyncio
async def test_task_collects_chunks_persists_and_finishes():
    async def stream(*collectors):
        yield "hello"
        yield ""
        yield " world"

    service = ChatTaskService()
    persisted = []
    task = _start(service, stream, persisted)
    await _finish(service, task)

    events = [event async for event in service.stream_to_subscriber(task)]
    assert task.full_response == "hello world"
    assert task.finish_reason == "stop"
    assert events == [
        {"type": "open"},
        {"type": "chunk", "content": "hello world"},
        {"type": "done", "finish_reason": "stop"},
    ]
    assert persisted[-1][0] == "hello world"
    assert persisted[-1][4:] == (False, "stop")


@pytest.mark.asyncio
async def test_task_converts_stream_exception_to_error():
    async def stream(*collectors):
        yield "partial"
        raise RuntimeError("provider disconnected")

    service = ChatTaskService()
    persisted = []
    task = _start(service, stream, persisted)
    await _finish(service, task)

    assert task.finish_reason == "error"
    assert task.error_message == "provider disconnected"
    assert task.terminal_event == {
        "type": "error",
        "finish_reason": "error",
        "message": "provider disconnected",
    }
    assert persisted[-1][4:] == (False, "error")


@pytest.mark.asyncio
async def test_task_treats_empty_provider_response_as_error():
    async def stream(*collectors):
        yield "   "

    service = ChatTaskService()
    persisted = []
    task = _start(service, stream, persisted)
    await _finish(service, task)

    assert task.finish_reason == "error"
    assert task.error_message == "AI 服务返回了空响应"
    assert task.full_response.startswith("生成失败：")
    assert task.terminal_event["type"] == "error"
    assert persisted[-1][4:] == (False, "error")
