"""
LLM 对话服务
"""
import json
import base64
from pathlib import Path
from typing import AsyncGenerator, Optional, List

from openai import AsyncOpenAI

from config import settings
from models import ChatMessage, Quote
from services.user_profile_service import user_profile_service


FALLBACK_SYSTEM_PROMPT = """你是一个专业的学术论文阅读助手。你的任务是帮助用户理解论文内容。
使用中文回答，但保留专业术语的英文原文。基于论文内容回答，不要编造论文中没有的信息。"""


class LLMService:
    """LLM 对话服务"""

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
    
    @property
    def client(self) -> AsyncOpenAI:
        """获取 OpenAI 客户端（懒加载）"""
        if self._client is None or self._client.api_key != settings.llm.api_key:
            self._client = AsyncOpenAI(
                api_key=settings.llm.api_key,
                base_url=settings.llm.api_base
            )
        return self._client
    
    def is_configured(self) -> bool:
        """检查是否已配置 API Key"""
        return bool(settings.llm.api_key)
    
    async def chat(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        quotes: Optional[List[Quote]] = None
    ) -> str:
        """
        非流式对话
        """
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")
        
        api_messages = self._build_messages(messages, pdf_path, quotes)
        
        response = await self.client.chat.completions.create(
            model=settings.llm.model,
            messages=api_messages,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            extra_body={"reasoning": {"effort": "medium"}}
        )
        
        return response.choices[0].message.content
    
    async def chat_stream(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        quotes: Optional[List[Quote]] = None,
        reasoning_collector: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式对话。
        reasoning_collector: 可选的可变列表，用于在流式过程中累积 reasoning 片段。
        调用方在流结束后通过 ''.join(reasoning_collector) 获取完整 reasoning。
        """
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")
        
        api_messages = self._build_messages(messages, pdf_path, quotes)
        
        stream = await self.client.chat.completions.create(
            model=settings.llm.model,
            messages=api_messages,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            stream=True,
            extra_body={"reasoning": {"effort": "medium"}}
        )
        
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            
            if reasoning_collector is not None:
                self._collect_reasoning(delta, reasoning_collector)
            
            if delta.content:
                yield delta.content
    
    @staticmethod
    def _collect_reasoning(delta, collector: List[str]):
        """从流式 delta 中提取 reasoning 文本"""
        reasoning_str = getattr(delta, 'reasoning', None)
        if reasoning_str:
            collector.append(reasoning_str)
            return
        reasoning_details = getattr(delta, 'reasoning_details', None)
        if reasoning_details:
            for detail in reasoning_details:
                text = detail.get('text', '') if isinstance(detail, dict) else getattr(detail, 'text', '')
                if text:
                    collector.append(text)
    
    def get_system_prompt(self) -> str:
        """获取 system prompt（优先使用用户画像编译版本）"""
        if user_profile_service.has_profile():
            return user_profile_service.compile_system_prompt()
        return FALLBACK_SYSTEM_PROMPT

    @staticmethod
    def _format_quotes(quotes: List[Quote]) -> str:
        """将引用列表格式化为干净的文本，带来源标注"""
        source_labels = {"pdf": "来自论文", "chat": "来自对话"}
        parts = []
        for q in quotes:
            label = source_labels.get(q.source, q.source)
            parts.append(f"[{label}]\n\"{q.text}\"")
        return "用户引用了以下内容：\n\n" + "\n\n".join(parts)

    def _build_messages(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        quotes: Optional[List[Quote]] = None
    ) -> list:
        """构建 API 消息列表"""
        api_messages = [
            {"role": "system", "content": self.get_system_prompt()}
        ]
        
        pdf_attached = False
        
        for msg in messages:
            if msg.role == "user" and pdf_path and not pdf_attached:
                content = self._build_user_content_with_pdf(
                    msg.content, pdf_path, quotes if msg == messages[-1] else None
                )
                api_messages.append({"role": "user", "content": content})
                pdf_attached = True
            else:
                text = msg.content
                if quotes and msg == messages[-1] and msg.role == "user":
                    text = f"{self._format_quotes(quotes)}\n\n{text}"
                msg_dict = {"role": msg.role, "content": text}
                if msg.role == "assistant" and msg.reasoning:
                    msg_dict["reasoning"] = msg.reasoning
                api_messages.append(msg_dict)
        
        return api_messages
    
    def _build_user_content_with_pdf(
        self,
        text: str,
        pdf_path: Path,
        quotes: Optional[List[Quote]] = None
    ) -> list:
        """构建包含 PDF 的用户消息内容"""
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
        
        content = [
            {
                "type": "file",
                "file": {
                    "filename": pdf_path.name,
                    "file_data": f"data:application/pdf;base64,{pdf_base64}"
                }
            }
        ]
        
        if quotes:
            text = f"{self._format_quotes(quotes)}\n\n{text}"
        
        content.append({
            "type": "text",
            "text": text
        })
        
        return content


# 全局服务实例
llm_service = LLMService()

