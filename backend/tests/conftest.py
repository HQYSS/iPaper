import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


# 必须在导入 config 及任何服务单例之前设置，避免测试初始化触碰 ~/.ipaper。
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="ipaper-backend-tests-")).resolve()
os.environ["IPAPER_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["IPAPER_SYNC_ROLE"] = "off"


@pytest.fixture(scope="session", autouse=True)
def isolated_settings():
    from config import settings

    real_data_dir = (Path.home() / ".ipaper").resolve()
    assert settings.data_dir.resolve() == _TEST_DATA_DIR
    assert settings.data_dir.resolve() != real_data_dir
    assert settings.sync_role == "off"
    yield settings
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture
def test_data_dir(isolated_settings):
    return isolated_settings.data_dir


@pytest_asyncio.fixture(autouse=True)
async def reset_chat_tasks():
    """防止后台 ChatTask 和延迟淘汰任务跨测试泄漏。"""
    from services.chat_task_service import chat_task_service

    yield

    running = [
        task.asyncio_task
        for task in chat_task_service._tasks.values()
        if task.asyncio_task and not task.asyncio_task.done()
    ]
    for task in running:
        task.cancel()
    if running:
        await asyncio.gather(*running, return_exceptions=True)

    evictions = list(chat_task_service._evict_tasks)
    for task in evictions:
        task.cancel()
    if evictions:
        await asyncio.gather(*evictions, return_exceptions=True)

    chat_task_service._tasks.clear()
    chat_task_service._evict_tasks.clear()
