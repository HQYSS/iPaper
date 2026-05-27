"""
Cursor CLI 对话服务
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import AsyncGenerator, Optional

from config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

CURSOR_FLAGSHIP_MODEL_IDS = [
    "gemini-3.1-pro",
    "claude-opus-4-7-thinking-xhigh",
    "gpt-5.5-extra-high",
]


class CursorCLIService:
    """通过 Cursor CLI headless 模式生成回复。"""

    def is_configured(self) -> bool:
        command = settings.llm.cursor_command or "cursor"
        return shutil.which(command) is not None

    async def chat_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        command = settings.llm.cursor_command or "cursor"
        args = [
            command,
            "agent",
            "-p",
            "--output-format",
            "stream-json",
            "--stream-partial-output",
            "--mode",
            "ask",
            "--trust",
            "--workspace",
            str(PROJECT_ROOT),
        ]
        if settings.llm.cursor_model:
            args.extend(["--model", settings.llm.cursor_model])
        args.append(prompt)
        logger.info(
            "Cursor CLI stream starting command=%s model=%s prompt_chars=%d timeout=%s",
            command,
            settings.llm.cursor_model or "(default)",
            len(prompt),
            settings.llm.cursor_timeout_seconds,
        )

        proc: Optional[asyncio.subprocess.Process] = None
        stderr_task: Optional[asyncio.Task[str]] = None
        emitted = False
        fallback_result = ""
        started_at = asyncio.get_running_loop().time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(PROJECT_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stderr_task = asyncio.create_task(self._read_stderr(proc))

            assert proc.stdout is not None
            while True:
                try:
                    raw_line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=settings.llm.cursor_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    self._terminate(proc)
                    await proc.wait()
                    logger.warning("Cursor CLI stream timed out prompt_chars=%d", len(prompt))
                    raise RuntimeError("Cursor CLI 响应超时") from exc

                if not raw_line:
                    break

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Cursor CLI non-JSON output: %s", line)
                    continue

                if event.get("type") == "assistant" and "timestamp_ms" in event and "model_call_id" not in event:
                    text = self._extract_text(event)
                    if text:
                        if not emitted:
                            logger.info(
                                "Cursor CLI first output after %.2fs",
                                asyncio.get_running_loop().time() - started_at,
                            )
                        emitted = True
                        yield text
                elif event.get("type") == "result":
                    fallback_result = event.get("result") or fallback_result

            return_code = await proc.wait()
            stderr = await stderr_task if stderr_task else ""
            if return_code != 0:
                detail = stderr.strip() or f"exit code {return_code}"
                logger.warning("Cursor CLI failed exit_code=%s stderr=%s", return_code, detail[-1000:])
                raise RuntimeError(f"Cursor CLI 调用失败：{detail}")

            if not emitted and fallback_result:
                logger.info("Cursor CLI emitted fallback result chars=%d", len(fallback_result))
                yield fallback_result
            logger.info(
                "Cursor CLI stream finished exit_code=%s emitted=%s elapsed=%.2fs",
                return_code,
                emitted or bool(fallback_result),
                asyncio.get_running_loop().time() - started_at,
            )
        except asyncio.CancelledError:
            if proc and proc.returncode is None:
                self._terminate(proc)
                await proc.wait()
            logger.info("Cursor CLI stream cancelled")
            raise
        finally:
            if stderr_task and not stderr_task.done():
                stderr_task.cancel()

    async def list_models(self) -> list[dict]:
        command = settings.llm.cursor_command or "cursor"
        proc = await asyncio.create_subprocess_exec(
            command,
            "agent",
            "models",
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError as exc:
            self._terminate(proc)
            await proc.wait()
            raise RuntimeError("获取 Cursor CLI 模型列表超时") from exc

        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or f"exit code {proc.returncode}"
            raise RuntimeError(f"获取 Cursor CLI 模型列表失败：{detail}")

        models = self._parse_models_output(stdout.decode("utf-8", errors="replace"))
        model_by_id = {model["id"]: model for model in models}
        return [
            model_by_id[model_id]
            for model_id in CURSOR_FLAGSHIP_MODEL_IDS
            if model_id in model_by_id
        ]

    @staticmethod
    def _parse_models_output(output: str) -> list[dict]:
        ansi_escape = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
        clean_output = ansi_escape.sub("", output)
        models = []
        for raw_line in clean_output.splitlines():
            line = raw_line.strip()
            if not line or line in {"Loading models…", "Available models"} or line.startswith("Tip:"):
                continue
            if " - " not in line:
                continue
            model_id, rest = line.split(" - ", 1)
            model_id = model_id.strip()
            label = rest.strip()
            is_current = "(current" in label
            is_default = "default" in label
            label = re.sub(r"\s+\([^)]*\)\s*$", "", label).strip()
            models.append({
                "id": model_id,
                "label": label,
                "current": is_current,
                "default": is_default,
            })
        return models

    @staticmethod
    async def _read_stderr(proc: asyncio.subprocess.Process) -> str:
        if proc.stderr is None:
            return ""
        data = await proc.stderr.read()
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_text(event: dict) -> str:
        content = event.get("message", {}).get("content", [])
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)

    @staticmethod
    def _terminate(proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            pass


cursor_cli_service = CursorCLIService()
