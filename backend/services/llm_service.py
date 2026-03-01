"""
LLM 对话服务
"""
import json
import base64
from pathlib import Path
from typing import AsyncGenerator, Optional, List

from openai import AsyncOpenAI

from config import settings
from models import ChatMessage
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
        selected_text: Optional[str] = None
    ) -> str:
        """
        非流式对话
        """
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")
        
        # 构建消息列表
        api_messages = self._build_messages(messages, pdf_path, selected_text)
        
        response = await self.client.chat.completions.create(
            model=settings.llm.model,
            messages=api_messages,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens
        )
        
        return response.choices[0].message.content
    
    async def chat_stream(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        selected_text: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        流式对话
        """
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")
        
        # 构建消息列表
        api_messages = self._build_messages(messages, pdf_path, selected_text)
        
        stream = await self.client.chat.completions.create(
            model=settings.llm.model,
            messages=api_messages,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def get_system_prompt(self) -> str:
        """获取 system prompt（优先使用用户画像编译版本）"""
        if user_profile_service.has_profile():
            return user_profile_service.compile_system_prompt()
        return FALLBACK_SYSTEM_PROMPT

    def _build_messages(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        selected_text: Optional[str] = None
    ) -> list:
        """构建 API 消息列表"""
        api_messages = [
            {"role": "system", "content": self.get_system_prompt()}
        ]
        
        # 如果有 PDF，在第一条用户消息中附加
        pdf_attached = False
        
        for msg in messages:
            if msg.role == "user" and pdf_path and not pdf_attached:
                # 附加 PDF 到第一条用户消息
                content = self._build_user_content_with_pdf(
                    msg.content, pdf_path, selected_text
                )
                api_messages.append({"role": "user", "content": content})
                pdf_attached = True
            else:
                # 普通消息
                content = msg.content
                if selected_text and msg == messages[-1]:
                    content = f"用户选中了以下文本：\n\n\"{selected_text}\"\n\n{content}"
                api_messages.append({"role": msg.role, "content": content})
        
        return api_messages
    
    def _build_user_content_with_pdf(
        self,
        text: str,
        pdf_path: Path,
        selected_text: Optional[str] = None
    ) -> list:
        """构建包含 PDF 的用户消息内容"""
        # 读取 PDF 并转为 base64
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
        
        content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:application/pdf;base64,{pdf_base64}"
                }
            }
        ]
        
        # 添加选中文本（如果有）
        if selected_text:
            text = f"用户选中了以下文本：\n\n\"{selected_text}\"\n\n{text}"
        
        content.append({
            "type": "text",
            "text": text
        })
        
        return content


# 全局服务实例
llm_service = LLMService()

