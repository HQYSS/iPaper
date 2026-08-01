"""Persistent cloud-side LLM tasks that survive HTTP subscriber disconnects."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Callable, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)
StreamFactory = Callable[[List[str], List[dict], Dict[str, str]], AsyncGenerator[str, None]]


class CloudCapacityError(RuntimeError):
    pass


@dataclass
class CloudGenerationTask:
    task_id: str
    user_id: str
    state: str = "accepted"
    content: str = ""
    reasoning: List[str] = field(default_factory=list)
    content_blocks: List[dict] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
    last_persist_at: float = field(default_factory=time.monotonic)
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    asyncio_task: Optional[asyncio.Task] = None

    @property
    def finished(self) -> bool:
        return self.state in {"completed", "failed", "stopped"}


class CloudGenerationService:
    TASK_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
    PERSIST_INTERVAL_SECONDS = 0.5
    MEMORY_RETENTION_SECONDS = 300
    DISK_RETENTION_SECONDS = 24 * 60 * 60
    MAX_GLOBAL_RUNNING_TASKS = 4
    MAX_USER_RUNNING_TASKS = 2
    MAX_RESPONSE_CHARS = 2_000_000
    MAX_TASK_DISK_BYTES = 200 * 1024 * 1024

    def __init__(self):
        self._tasks: Dict[str, CloudGenerationTask] = {}
        self._llm_semaphore = asyncio.Semaphore(self.MAX_GLOBAL_RUNNING_TASKS)

    @staticmethod
    def _task_file(user_id: str, task_id: str) -> Path:
        if not CloudGenerationService.TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("invalid cloud task id")
        task_dir = settings.get_user_data_dir(user_id) / "cloud-tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(task_dir, 0o700)
        path = (task_dir / f"{task_id}.json").resolve()
        if path.parent != task_dir.resolve():
            raise ValueError("cloud task path escapes task directory")
        return path

    def _persist(self, task: CloudGenerationTask, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - task.last_persist_at < self.PERSIST_INTERVAL_SECONDS:
            return
        task.last_persist_at = now
        task.updated_at = time.time()
        path = self._task_file(task.user_id, task.task_id)
        temp = path.with_suffix(".json.tmp")
        payload = json.dumps(
                {
                    "task_id": task.task_id,
                    "user_id": task.user_id,
                    "state": task.state,
                    "content": task.content,
                    "reasoning": task.reasoning,
                    "content_blocks": task.content_blocks,
                    "metadata": task.metadata,
                    "error": task.error,
                    "updated_at": task.updated_at,
                },
                ensure_ascii=False,
                indent=2,
            )
        descriptor = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        temp.replace(path)
        os.chmod(path, 0o600)

    def _load(self, user_id: str, task_id: str) -> Optional[CloudGenerationTask]:
        path = self._task_file(user_id, task_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        state = data.get("state", "failed")
        error = data.get("error")
        if state in {"accepted", "streaming"}:
            state = "failed"
            error = "云端生成进程曾重启，请重新生成"
        return CloudGenerationTask(
            task_id=task_id,
            user_id=user_id,
            state=state,
            content=data.get("content", ""),
            reasoning=data.get("reasoning", []),
            content_blocks=data.get("content_blocks", []),
            metadata=data.get("metadata", {}),
            error=error,
            updated_at=data.get("updated_at", time.time()),
        )

    def _gc_disk(self, user_id: str) -> None:
        task_dir = settings.get_user_data_dir(user_id) / "cloud-tasks"
        if not task_dir.exists():
            return
        cutoff = time.time() - self.DISK_RETENTION_SECONDS
        for path in task_dir.glob("*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        files = sorted(
            task_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )
        total_size = sum(path.stat().st_size for path in files)
        for path in files:
            if total_size <= self.MAX_TASK_DISK_BYTES:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total_size -= size

    def get(self, user_id: str, task_id: str) -> Optional[CloudGenerationTask]:
        task = self._tasks.get(task_id)
        if task and task.user_id == user_id:
            return task
        loaded = self._load(user_id, task_id)
        if loaded:
            self._tasks[task_id] = loaded
        return loaded

    def get_status(self, user_id: Optional[str] = None) -> dict:
        visible = [
            task
            for task in self._tasks.values()
            if user_id is None or task.user_id == user_id
        ]
        running = [
            task
            for task in visible
            if task.state in {"accepted", "streaming"}
        ]
        return {
            "running": len(running),
            "retained": len(visible),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "state": task.state,
                    "updated_at": task.updated_at,
                }
                for task in running
            ],
        }

    @staticmethod
    def task_snapshot(task: CloudGenerationTask) -> dict:
        return {
            "task_id": task.task_id,
            "state": task.state,
            "content": task.content,
            "reasoning": "".join(task.reasoning) if task.reasoning else None,
            "content_blocks": task.content_blocks or None,
            "response_id": task.metadata.get("response_id"),
            "error": task.error,
            "updated_at": task.updated_at,
        }

    def start(
        self,
        user_id: str,
        task_id: str,
        stream_factory: StreamFactory,
    ) -> CloudGenerationTask:
        self._gc_disk(user_id)
        existing = self.get(user_id, task_id)
        if existing:
            return existing
        running = [
            task
            for task in self._tasks.values()
            if task.state in {"accepted", "streaming"}
        ]
        if len(running) >= self.MAX_GLOBAL_RUNNING_TASKS:
            raise CloudCapacityError("云端生成任务已满，请稍后重试")
        if sum(task.user_id == user_id for task in running) >= self.MAX_USER_RUNNING_TASKS:
            raise CloudCapacityError("当前用户已有过多生成任务，请稍后重试")
        task = CloudGenerationTask(task_id=task_id, user_id=user_id)
        self._tasks[task_id] = task
        self._persist(task, force=True)
        task.asyncio_task = asyncio.create_task(self._run(task, stream_factory))
        return task

    async def stop(self, user_id: str, task_id: str) -> bool:
        task = self.get(user_id, task_id)
        if not task or task.finished:
            return False
        task.state = "stopped"
        task.error = "生成已停止"
        if task.asyncio_task and not task.asyncio_task.done():
            task.asyncio_task.cancel()
            await asyncio.gather(task.asyncio_task, return_exceptions=True)
        self._persist(task, force=True)
        self._broadcast(task, self._terminal_event(task))
        return True

    async def _run(self, task: CloudGenerationTask, stream_factory: StreamFactory) -> None:
        try:
            async with self._llm_semaphore:
                task.state = "streaming"
                self._persist(task, force=True)
                async for chunk in stream_factory(task.reasoning, task.content_blocks, task.metadata):
                    if not chunk:
                        continue
                    task.content += chunk
                    if len(task.content) > self.MAX_RESPONSE_CHARS:
                        raise RuntimeError("云端生成内容超过安全上限")
                    self._persist(task)
                    self._broadcast(task, {"type": "chunk", "content": chunk})
            if not task.content.strip():
                raise RuntimeError("AI 服务返回了空响应")
            task.state = "completed"
        except asyncio.CancelledError:
            task.state = "stopped"
            task.error = "生成已停止"
        except Exception as exc:
            task.state = "failed"
            task.error = str(exc) or exc.__class__.__name__
            logger.exception("cloud generation failed task=%s", task.task_id)
        finally:
            self._persist(task, force=True)
            self._broadcast(task, self._terminal_event(task))
            asyncio.create_task(self._evict_later(task))

    async def _evict_later(self, task: CloudGenerationTask) -> None:
        await asyncio.sleep(self.MEMORY_RETENTION_SECONDS)
        if self._tasks.get(task.task_id) is task:
            self._tasks.pop(task.task_id, None)

    @staticmethod
    def _terminal_event(task: CloudGenerationTask) -> dict:
        if task.state == "completed":
            return {
                "type": "done",
                "finish_reason": "stop",
                "reasoning": "".join(task.reasoning) if task.reasoning else None,
                "content_blocks": task.content_blocks or None,
                "response_id": task.metadata.get("response_id"),
                "task_id": task.task_id,
            }
        if task.state == "stopped":
            return {
                "type": "stopped",
                "finish_reason": "stopped",
                "task_id": task.task_id,
            }
        return {
            "type": "error",
            "message": task.error or "云端生成失败",
            "task_id": task.task_id,
        }

    @staticmethod
    def _broadcast(task: CloudGenerationTask, event: dict) -> None:
        for queue in list(task.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({
                    "type": "error",
                    "message": "订阅者消费过慢，请重新连接",
                    "task_id": task.task_id,
                })

    async def subscribe(
        self,
        task: CloudGenerationTask,
        offset: int = 0,
    ) -> AsyncGenerator[dict, None]:
        snapshot = task.content[max(0, offset):]
        queue: Optional[asyncio.Queue] = None
        if not task.finished:
            queue = asyncio.Queue(maxsize=100)
            task.subscribers.append(queue)
        yield {"type": "open", "task_id": task.task_id}
        if snapshot:
            yield {"type": "chunk", "content": snapshot}
        if task.finished:
            yield self._terminal_event(task)
            return
        assert queue is not None
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") in {"done", "error", "stopped"}:
                    return
        finally:
            if queue in task.subscribers:
                task.subscribers.remove(queue)


cloud_generation_service = CloudGenerationService()
