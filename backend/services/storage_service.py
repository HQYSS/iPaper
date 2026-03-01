"""
存储服务 - 管理对话历史等数据
"""
import json
from pathlib import Path
from typing import List, Optional

from config import settings
from models import ChatMessage, ChatHistory


class StorageService:
    """存储服务"""
    
    def __init__(self):
        self.papers_dir = settings.papers_dir
    
    def get_chat_history(self, paper_id: str) -> List[ChatMessage]:
        """获取对话历史"""
        history_file = self._get_chat_history_file(paper_id)
        
        if not history_file.exists():
            return []
        
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        return [ChatMessage(**msg) for msg in data.get("messages", [])]
    
    def save_chat_history(self, paper_id: str, messages: List[ChatMessage]):
        """保存对话历史"""
        history_file = self._get_chat_history_file(paper_id)
        
        # 确保目录存在
        history_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "paper_id": paper_id,
            "messages": [msg.model_dump() for msg in messages]
        }
        
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def append_message(self, paper_id: str, message: ChatMessage):
        """追加一条消息"""
        messages = self.get_chat_history(paper_id)
        messages.append(message)
        self.save_chat_history(paper_id, messages)
    
    def clear_chat_history(self, paper_id: str) -> bool:
        """清空对话历史"""
        history_file = self._get_chat_history_file(paper_id)
        
        if history_file.exists():
            history_file.unlink()
            return True
        
        return False
    
    def _get_chat_history_file(self, paper_id: str) -> Path:
        """获取对话历史文件路径"""
        # 从 paper_id 获取论文目录
        paper_dir = self.papers_dir / paper_id.split("v")[0]  # 移除版本号
        return paper_dir / "chat_history.json"


# 全局服务实例
storage_service = StorageService()

