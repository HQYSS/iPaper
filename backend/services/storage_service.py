"""
存储服务 - 管理对话历史（多会话）
"""
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from config import settings
from models import ChatMessage, ForkData, SessionMeta, SessionList

logger = logging.getLogger(__name__)


class StorageService:
    """存储服务"""

    def __init__(self):
        self.papers_dir = settings.papers_dir

    # ==================== Session 管理 ====================

    def list_sessions(self, paper_id: str) -> SessionList:
        self._migrate_legacy(paper_id)
        index = self._load_session_index(paper_id)
        return SessionList(
            sessions=index.get("sessions", []),
            last_active_session_id=index.get("last_active_session_id"),
        )

    def create_session(self, paper_id: str, title: Optional[str] = None) -> SessionMeta:
        self._migrate_legacy(paper_id)
        chats_dir = self._get_chats_dir(paper_id)
        chats_dir.mkdir(parents=True, exist_ok=True)

        session_id = f"s_{int(time.time() * 1000)}"
        now = datetime.now()
        meta = SessionMeta(
            id=session_id,
            title=title or "新对话",
            created_at=now,
            updated_at=now,
        )

        index = self._load_session_index(paper_id)
        index.setdefault("sessions", []).append(meta.model_dump(mode="json"))
        self._save_session_index(paper_id, index)

        return meta

    def delete_session(self, paper_id: str, session_id: str) -> bool:
        index = self._load_session_index(paper_id)
        sessions = index.get("sessions", [])
        original_len = len(sessions)
        index["sessions"] = [s for s in sessions if s["id"] != session_id]
        if len(index["sessions"]) == original_len:
            return False

        if index.get("last_active_session_id") == session_id:
            index["last_active_session_id"] = (
                index["sessions"][0]["id"] if index["sessions"] else None
            )

        self._save_session_index(paper_id, index)

        chat_file = self._get_chat_file(paper_id, session_id)
        if chat_file.exists():
            chat_file.unlink()

        return True

    def set_last_active_session(self, paper_id: str, session_id: str):
        index = self._load_session_index(paper_id)
        index["last_active_session_id"] = session_id
        self._save_session_index(paper_id, index)

    def update_session_timestamp(self, paper_id: str, session_id: str):
        """更新 session 的 updated_at 时间戳"""
        index = self._load_session_index(paper_id)
        for s in index.get("sessions", []):
            if s["id"] == session_id:
                s["updated_at"] = datetime.now().isoformat()
                break
        self._save_session_index(paper_id, index)

    # ==================== 对话历史 ====================

    def get_chat_history(self, paper_id: str, session_id: str) -> tuple[List[ChatMessage], Optional[dict]]:
        """Returns (messages, forks_raw_dict_or_None)"""
        chat_file = self._get_chat_file(paper_id, session_id)
        if not chat_file.exists():
            return [], None
        with open(chat_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        messages = [ChatMessage(**msg) for msg in data.get("messages", [])]
        forks = data.get("forks")
        return messages, forks

    def save_chat_history(
        self,
        paper_id: str,
        session_id: str,
        messages: List[ChatMessage],
        forks: Optional[dict] = None,
    ):
        chat_file = self._get_chat_file(paper_id, session_id)
        chat_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "paper_id": paper_id,
            "session_id": session_id,
            "messages": [msg.model_dump() for msg in messages],
        }
        if forks:
            data["forks"] = forks
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.update_session_timestamp(paper_id, session_id)

    def clear_chat_history(self, paper_id: str, session_id: str) -> bool:
        chat_file = self._get_chat_file(paper_id, session_id)
        if chat_file.exists():
            chat_file.unlink()
            return True
        return False

    # ==================== 内部方法 ====================

    def _get_paper_dir(self, paper_id: str) -> Path:
        return self.papers_dir / paper_id.split("v")[0]

    def _get_chats_dir(self, paper_id: str) -> Path:
        return self._get_paper_dir(paper_id) / "chats"

    def _get_chat_file(self, paper_id: str, session_id: str) -> Path:
        return self._get_chats_dir(paper_id) / f"{session_id}.json"

    def _get_session_index_file(self, paper_id: str) -> Path:
        return self._get_chats_dir(paper_id) / "sessions.json"

    def _load_session_index(self, paper_id: str) -> dict:
        index_file = self._get_session_index_file(paper_id)
        if not index_file.exists():
            return {"sessions": [], "last_active_session_id": None}
        with open(index_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_session_index(self, paper_id: str, index: dict):
        index_file = self._get_session_index_file(paper_id)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False, default=str)

    # ==================== 迁移 ====================

    def _migrate_legacy(self, paper_id: str):
        """将旧的 chat_history.json 迁移到 chats/ 目录"""
        paper_dir = self._get_paper_dir(paper_id)
        legacy_file = paper_dir / "chat_history.json"
        if not legacy_file.exists():
            return

        logger.info("Migrating legacy chat_history.json for paper %s", paper_id)

        with open(legacy_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        messages = data.get("messages", [])
        if not messages:
            legacy_file.unlink()
            return

        chats_dir = self._get_chats_dir(paper_id)
        chats_dir.mkdir(parents=True, exist_ok=True)

        session_id = f"s_{int(time.time() * 1000)}"
        now = datetime.now()

        chat_data = {
            "paper_id": paper_id,
            "session_id": session_id,
            "messages": messages,
        }
        chat_file = chats_dir / f"{session_id}.json"
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        index = {
            "sessions": [
                {
                    "id": session_id,
                    "title": "自动讲解",
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
            ],
            "last_active_session_id": session_id,
        }
        self._save_session_index(paper_id, index)

        legacy_file.unlink()
        logger.info("Migration complete: created session %s", session_id)


# 全局服务实例
storage_service = StorageService()
