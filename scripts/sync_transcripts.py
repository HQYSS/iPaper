#!/usr/bin/env python3
"""
将 Cursor agent-transcripts 中的论文讨论对话同步到 papers/{id}/chat_history.json。

用法:
    python scripts/sync_transcripts.py              # 增量同步所有新对话
    python scripts/sync_transcripts.py --all        # 强制重新同步所有对话
    python scripts/sync_transcripts.py --list       # 列出所有可识别的论文对话
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

IPAPER_DIR = Path.home() / ".ipaper"
PROJECT_ROOT = Path(__file__).parent.parent
PAPERS_DIR = PROJECT_ROOT / "papers"
TRANSCRIPTS_BASE = Path.home() / ".cursor" / "projects"
PROCESSED_FILE = IPAPER_DIR / "processed_transcripts.json"

ARXIV_ID_PATTERN = re.compile(r'\b(\d{4}\.\d{4,5})(v\d+)?\b')


def find_transcripts_dir() -> Optional[Path]:
    """找到当前项目的 agent-transcripts 目录"""
    for project_dir in TRANSCRIPTS_BASE.iterdir():
        if not project_dir.is_dir():
            continue
        transcripts = project_dir / "agent-transcripts"
        if transcripts.exists() and "iPaper" in project_dir.name:
            return transcripts
    return None


def load_processed() -> dict:
    """加载已处理的 transcript ID 列表"""
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r") as f:
            return json.load(f)
    return {"processed": {}}


def save_processed(data: dict):
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def extract_user_text(content_items: list) -> str:
    """从 transcript content 数组中提取用户文本"""
    texts = []
    for item in content_items:
        if item.get("type") == "text":
            text = item.get("text", "")
            match = re.search(r'<user_query>\s*(.*?)\s*</user_query>', text, re.DOTALL)
            if match:
                texts.append(match.group(1).strip())
            elif not text.startswith("<"):
                texts.append(text.strip())
    return "\n".join(texts)


def extract_assistant_text(content_items: list) -> str:
    """从 transcript content 数组中提取 assistant 文本（跳过工具调用等）"""
    texts = []
    for item in content_items:
        if item.get("type") == "text":
            text = item.get("text", "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts)


def find_arxiv_ids_in_conversation(messages: list[dict]) -> set[str]:
    """从对话内容中识别 arXiv ID"""
    ids = set()
    for msg in messages:
        text = msg.get("content", "")
        for match in ARXIV_ID_PATTERN.finditer(text):
            ids.add(match.group(1))
    return ids


def parse_transcript(filepath: Path) -> list[dict]:
    """解析 JSONL transcript 为消息列表"""
    messages = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = record.get("role", "")
            content_items = record.get("message", {}).get("content", [])

            if role == "user":
                text = extract_user_text(content_items)
                if text:
                    messages.append({"role": "user", "content": text})
            elif role == "assistant":
                text = extract_assistant_text(content_items)
                if text:
                    messages.append({"role": "assistant", "content": text})

    return messages


def is_paper_discussion(messages: list[dict]) -> bool:
    """判断对话是否涉及论文讨论（非开发/配置类对话）"""
    if not messages:
        return False

    paper_keywords = ["论文", "paper", "讲解", "arXiv", "arxiv"]
    first_few = " ".join(m["content"][:200] for m in messages[:4])
    return any(kw.lower() in first_few.lower() for kw in paper_keywords)


def save_chat_history(paper_id: str, messages: list[dict], transcript_id: str):
    """保存为 iPaper 兼容的 chat_history.json 格式（全量覆盖该 transcript 的消息）"""
    paper_dir = PAPERS_DIR / paper_id
    if not paper_dir.exists():
        print(f"  [跳过] 论文目录不存在: {paper_dir}")
        return False

    history_file = paper_dir / "chat_history.json"

    existing_data = {"paper_id": paper_id, "sessions": {}}
    if history_file.exists():
        with open(history_file, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            if "sessions" not in existing_data:
                existing_data["sessions"] = {}

    existing_data["sessions"][transcript_id] = {
        "messages": messages,
        "synced_at": datetime.now().isoformat()
    }

    all_messages = []
    for session in existing_data["sessions"].values():
        all_messages.extend(session["messages"])

    existing_data["paper_id"] = paper_id
    existing_data["messages"] = all_messages

    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)

    return True


def sync(force_all: bool = False, list_only: bool = False):
    transcripts_dir = find_transcripts_dir()
    if not transcripts_dir:
        print("未找到 iPaper 项目的 agent-transcripts 目录")
        sys.exit(1)

    print(f"Transcripts 目录: {transcripts_dir}")

    processed = load_processed()
    results = {"synced": 0, "skipped": 0, "no_paper": 0}

    for session_dir in sorted(transcripts_dir.iterdir()):
        if not session_dir.is_dir():
            continue

        transcript_id = session_dir.name
        jsonl_file = session_dir / f"{transcript_id}.jsonl"

        if not jsonl_file.exists():
            continue

        file_size = jsonl_file.stat().st_size
        prev = processed["processed"].get(transcript_id)
        if not force_all and prev and prev.get("file_size") == file_size:
            results["skipped"] += 1
            continue

        is_update = prev is not None and prev.get("status") == "synced"
        messages = parse_transcript(jsonl_file)
        if not messages:
            continue

        arxiv_ids = find_arxiv_ids_in_conversation(messages)

        if list_only:
            if arxiv_ids:
                id_str = ", ".join(arxiv_ids)
                preview = messages[0]["content"][:60] if messages else ""
                print(f"  {transcript_id[:8]}... → 论文: {id_str} ({len(messages)} 条消息)")
            continue

        if not arxiv_ids:
            results["no_paper"] += 1
            processed["processed"][transcript_id] = {
                "at": datetime.now().isoformat(),
                "file_size": file_size,
                "status": "no_paper_id"
            }
            continue

        action = "更新" if is_update else "同步"
        for paper_id in arxiv_ids:
            if save_chat_history(paper_id, messages, transcript_id):
                print(f"  [{action}] {transcript_id[:8]}... → {paper_id} ({len(messages)} 条消息)")
                results["synced"] += 1
                processed["processed"][transcript_id] = {
                    "at": datetime.now().isoformat(),
                    "file_size": file_size,
                    "status": "synced",
                    "paper_ids": list(arxiv_ids)
                }

    if not list_only:
        save_processed(processed)
        print(f"\n完成: 同步 {results['synced']}, 跳过 {results['skipped']}, 非论文对话 {results['no_paper']}")


if __name__ == "__main__":
    force_all = "--all" in sys.argv
    list_only = "--list" in sys.argv
    sync(force_all=force_all, list_only=list_only)
