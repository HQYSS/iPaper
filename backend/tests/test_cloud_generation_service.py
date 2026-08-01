import asyncio

import pytest

from services.cloud_generation_service import CloudCapacityError, CloudGenerationService


@pytest.mark.asyncio
async def test_cloud_task_continues_without_subscriber_and_can_be_reloaded():
    service = CloudGenerationService()

    async def stream(reasoning, blocks, metadata):
        metadata["response_id"] = "resp_1"
        yield "hello"
        await asyncio.sleep(0)
        yield " cloud"

    task_id = "a" * 32
    task = service.start("cloud-user", task_id, stream)
    await task.asyncio_task

    assert task.state == "completed"
    assert task.content == "hello cloud"
    reloaded = CloudGenerationService().get("cloud-user", task_id)
    assert reloaded is not None
    events = [event async for event in CloudGenerationService().subscribe(reloaded)]
    assert events[0] == {"type": "open", "task_id": task_id}
    assert events[1] == {"type": "chunk", "content": "hello cloud"}
    assert events[-1]["type"] == "done"
    assert events[-1]["response_id"] == "resp_1"


@pytest.mark.asyncio
async def test_cloud_task_persists_empty_response_as_failure():
    service = CloudGenerationService()

    async def empty_stream(reasoning, blocks, metadata):
        if False:
            yield ""

    task = service.start("cloud-user", "c" * 32, empty_stream)
    await task.asyncio_task

    assert task.state == "failed"
    assert task.error == "AI 服务返回了空响应"


def test_cloud_task_id_rejects_path_traversal():
    service = CloudGenerationService()
    with pytest.raises(ValueError, match="invalid cloud task id"):
        service.get("cloud-user", "../../../users")


@pytest.mark.asyncio
async def test_cloud_task_can_be_cancelled():
    service = CloudGenerationService()

    async def stream(reasoning, blocks, metadata):
        while True:
            await asyncio.sleep(1)
            yield "later"

    task_id = "b" * 32
    task = service.start("cloud-user", task_id, stream)
    assert await service.stop("cloud-user", task_id) is True
    assert task.state == "stopped"


@pytest.mark.asyncio
async def test_cloud_task_enforces_per_user_concurrency_limit():
    service = CloudGenerationService()

    async def stream(reasoning, blocks, metadata):
        await asyncio.sleep(10)
        yield "done"

    first = service.start("cloud-user", "1" * 32, stream)
    second = service.start("cloud-user", "2" * 32, stream)
    with pytest.raises(CloudCapacityError, match="过多生成任务"):
        service.start("cloud-user", "3" * 32, stream)

    await service.stop("cloud-user", first.task_id)
    await service.stop("cloud-user", second.task_id)
