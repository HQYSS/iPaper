"""
ChatTaskService - LLM 生成任务管理（脱离 HTTP 请求生命周期）

设计要点（详见 docs/dev/02-后端.md "AI 对话独立任务"）：
- 每次 POST /api/chat/... 在内存里登记一个独立 asyncio.Task 跑 LLM stream
- HTTP handler 只是这个 Task 的"订阅者"，从队列里拉 chunk 转 SSE
- 客户端断连 → 仅把订阅者摘掉，Task 继续跑、继续往磁盘写 partial
- 客户端重连 → GET /history 拿落盘最新内容；若任务尚未结束，可再调 stream 端点继续订阅
- 用户主动停止 → 显式 POST /stop（取消 Task）

每个 Task 内部行为：
- 边收 chunk 边广播 → 同步给所有当前订阅者
- 节流落盘：每 PERSIST_INTERVAL_SECONDS 调一次 persist 回调写盘
- 不论正常结束 / 取消 / 异常，finally 中都会做最后一次 persist + 广播终态事件
- 完成后保留 TASK_RETENTION_SECONDS 秒供晚到订阅者拿到终态，再从内存字典清掉
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# 节流落盘间隔（秒）
PERSIST_INTERVAL_SECONDS = 0.5
# 任务结束后保留在内存里的时间（秒）
TASK_RETENTION_SECONDS = 300

# 持久化回调签名：(content, reasoning, in_progress, finish_reason)
# 同步函数（内部走 storage_service 的同步文件 IO）；保持同步可以避免 finally 里再 await 时被二次取消
PersistFn = Callable[[str, Optional[str], bool, Optional[str]], None]
# 流提供者：传入 reasoning_collector，返回异步迭代器（chunk 字符串）
StreamFactory = Callable[[List[str]], "AsyncGenerator[str, None]"]


@dataclass
class _Subscriber:
    queue: "asyncio.Queue[dict]"


@dataclass
class ChatTask:
    kind: str
    user_id: str
    session_id: str
    paper_id: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    full_response: str = ""
    reasoning_parts: List[str] = field(default_factory=list)
    finished: bool = False
    finished_at: Optional[float] = None
    finish_reason: Optional[str] = None
    error_message: Optional[str] = None
    subscribers: List[_Subscriber] = field(default_factory=list)
    asyncio_task: Optional[asyncio.Task] = None
    terminal_event: Optional[dict] = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.kind, self.session_id)

    def is_running(self) -> bool:
        return not self.finished

    def _broadcast(self, event: dict):
        for sub in list(self.subscribers):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


class ChatTaskService:
    def __init__(self):
        self._tasks: Dict[Tuple[str, str], ChatTask] = {}
        self._evict_tasks: Set[asyncio.Task] = set()

    def get(self, kind: str, session_id: str) -> Optional[ChatTask]:
        return self._tasks.get((kind, session_id))

    def is_running(self, kind: str, session_id: str) -> bool:
        t = self.get(kind, session_id)
        return t is not None and t.is_running()

    async def stop(self, kind: str, session_id: str) -> bool:
        """主动停止任务（用户点'停止生成'）。返回 True 表示找到了在跑的任务并已发出取消"""
        task = self.get(kind, session_id)
        if not task or task.finished:
            return False
        if task.finish_reason is None:
            task.finish_reason = "stopped"
        if task.asyncio_task and not task.asyncio_task.done():
            task.asyncio_task.cancel()
        return True

    def start(
        self,
        *,
        kind: str,
        user_id: str,
        session_id: str,
        paper_id: Optional[str],
        stream_factory: StreamFactory,
        persist: PersistFn,
    ) -> ChatTask:
        if self.is_running(kind, session_id):
            raise RuntimeError(f"session {kind}:{session_id} already has a running task")

        task = ChatTask(
            kind=kind,
            user_id=user_id,
            session_id=session_id,
            paper_id=paper_id,
        )
        self._tasks[task.key] = task
        task.asyncio_task = asyncio.create_task(
            self._run(task, stream_factory, persist),
            name=f"chat-task-{kind}-{session_id}",
        )
        return task

    async def _run(self, task: ChatTask, stream_factory: StreamFactory, persist: PersistFn):
        last_persist_at = time.monotonic()
        dirty = False

        def _do_persist(force: bool = False):
            nonlocal last_persist_at, dirty
            now = time.monotonic()
            if not force:
                if not dirty:
                    return
                if now - last_persist_at < PERSIST_INTERVAL_SECONDS:
                    return
            try:
                reasoning = ''.join(task.reasoning_parts) if task.reasoning_parts else None
                in_progress = not task.finished
                persist(task.full_response, reasoning, in_progress, task.finish_reason)
                last_persist_at = now
                dirty = False
            except Exception:
                logger.exception("[chat-task %s:%s] persist failed", task.kind, task.session_id)

        try:
            async for chunk in stream_factory(task.reasoning_parts):
                if not chunk:
                    continue
                task.full_response += chunk
                dirty = True
                task._broadcast({"type": "chunk", "content": chunk})
                _do_persist()
            # 正常结束
            if task.finish_reason is None:
                task.finish_reason = "stop"
        except asyncio.CancelledError:
            # 用户停止 / 进程关停 → 不再向上抛，让 finally 自然走完
            if task.finish_reason is None:
                task.finish_reason = "stopped"
            logger.info("[chat-task %s:%s] cancelled (reason=%s)", task.kind, task.session_id, task.finish_reason)
        except Exception as e:
            task.finish_reason = "error"
            task.error_message = str(e) or e.__class__.__name__
            logger.exception("[chat-task %s:%s] failed: %s", task.kind, task.session_id, e)
        finally:
            task.finished = True
            task.finished_at = time.time()
            _do_persist(force=True)

            if task.finish_reason in ("stop", "length"):
                terminal: dict = {"type": "done", "finish_reason": task.finish_reason}
            elif task.finish_reason == "stopped":
                terminal = {"type": "stopped", "finish_reason": "stopped"}
            else:
                terminal = {
                    "type": "error",
                    "finish_reason": task.finish_reason or "error",
                    "message": task.error_message or "AI 服务出现错误",
                }
            task.terminal_event = terminal
            task._broadcast(terminal)

            evict = asyncio.create_task(self._evict_later(task))
            self._evict_tasks.add(evict)
            evict.add_done_callback(self._evict_tasks.discard)

    async def _evict_later(self, task: ChatTask):
        try:
            await asyncio.sleep(TASK_RETENTION_SECONDS)
        finally:
            self._tasks.pop(task.key, None)

    async def stream_to_subscriber(self, task: ChatTask) -> AsyncGenerator[dict, None]:
        """订阅一个任务，按事件 yield。HTTP handler 退出（客户端断连）时
        generator 自然退出，finally 摘除订阅者。"""
        # 任务已结束：直接吐 partial + terminal 退出
        if task.finished:
            yield {"type": "open"}
            if task.full_response:
                yield {"type": "chunk", "content": task.full_response}
            if task.terminal_event:
                yield task.terminal_event
            return

        # 仍在跑：先抓快照、再加入订阅；两步之间无 await 所以是原子的
        snapshot = task.full_response
        sub = _Subscriber(queue=asyncio.Queue())
        task.subscribers.append(sub)
        try:
            yield {"type": "open"}
            if snapshot:
                yield {"type": "chunk", "content": snapshot}
            while True:
                ev = await sub.queue.get()
                yield ev
                if ev.get("type") in ("done", "stopped", "error"):
                    break
        finally:
            try:
                task.subscribers.remove(sub)
            except ValueError:
                pass


chat_task_service = ChatTaskService()
