"""
LLM 对话服务
"""
import io
import json
import base64
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional, List

import fitz
from openai import AsyncOpenAI

from config import settings
from models import ChatMessage, Quote
from services.user_profile_service import user_profile_service
from services.arxiv_service import arxiv_service

logger = logging.getLogger(__name__)

PDF_SIZE_THRESHOLD = 15 * 1024 * 1024  # 15MB
IMAGE_DPI = 150
IMAGE_QUALITY = 85


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
        """构建包含 PDF 的用户消息内容。大 PDF 自动转为逐页图片。"""
        pdf_size = pdf_path.stat().st_size

        if pdf_size <= PDF_SIZE_THRESHOLD:
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
        else:
            logger.info(
                "PDF too large (%.1fMB > %dMB), converting to page images",
                pdf_size / 1024 / 1024, PDF_SIZE_THRESHOLD // 1024 // 1024
            )
            content = self._pdf_to_image_blocks(pdf_path)

        if quotes:
            text = f"{self._format_quotes(quotes)}\n\n{text}"

        content.append({
            "type": "text",
            "text": text
        })

        return content

    @staticmethod
    def _pdf_to_image_blocks(pdf_path: Path) -> list:
        """将 PDF 逐页渲染为 JPEG，返回 OpenAI vision 格式的 image_url 块列表。"""
        doc = fitz.open(pdf_path)
        blocks = []
        matrix = fitz.Matrix(IMAGE_DPI / 72, IMAGE_DPI / 72)

        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)

            buf = io.BytesIO()
            buf.write(pix.tobytes("jpeg", jpg_quality=IMAGE_QUALITY))
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            blocks.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })

        doc.close()
        total_kb = sum(len(b["image_url"]["url"]) * 3 / 4 for b in blocks) / 1024
        logger.info("Converted %d pages to JPEG images (total ~%.0fKB)", len(blocks), total_kb)
        return blocks

    # ==================== Cross-Paper (串讲) ====================

    CROSS_PAPER_PROMPT_ADDON = """
---

## 多论文串讲模式

你现在进入了**多论文串讲模式**。用户选择了多篇论文，希望你深入分析它们在技术上的异同。

### 串讲原则

1. **找到共同主线**：这几篇论文在解决什么共同的问题？它们的出发点是否一致？
2. **对比而非罗列**：绝对不要逐篇依次总结。你的每一段分析都应该涉及至少两篇论文的对比。
3. **揭示技术演进**：如果论文之间有明确的时间线或引用关系，讲清楚技术是怎么一步步演进的。
4. **深挖方法的本质共性**：不同论文的方法表面上可能差异很大，但在训练时起到的作用可能本质相同。你必须运用对深度学习的深刻理解，透过表面差异看到底层共性。方法之间有差异是正常的且往往不重要；真正有价值的洞察是发现"看起来不同的设计，其实在做同一件事"。
5. **突出真正重要的分歧**：当论文对同一问题采取了不同的技术路线时，分析各自的取舍——为什么 A 选了这条路，B 选了另一条？这种分歧是根本性的还是表面的？各自的假设是什么？

### 串讲输出结构

**1. 主题与定位**
这组论文共同在解决什么问题？各自的切入角度是什么？

**2. 技术路线对比**
- 用表格或结构化对比展示核心方法差异
- 对每个关键技术决策，分析不同论文的选择和理由
- 使用计算图/数据流视角描述关键差异
- 重点分析：哪些表面差异其实本质相同？哪些看似微小的不同才是真正的分歧？

**3. 实验对比**（如果适用）
- 横向对比表格（如果多篇论文在相同 benchmark 上有结果）
- 分析评测方式的差异
- 关注反直觉的结果

### 引用标注

讨论某篇论文的内容时，用 **[[arXiv ID]]** 格式标注来源，例如 [[2301.12345]]。这些标注会被渲染为可点击的链接，点击后切换到对应论文的 PDF 视图。确保读者能追溯到具体论文。
"""

    def get_cross_paper_system_prompt(self) -> str:
        base = self.get_system_prompt()
        return base + self.CROSS_PAPER_PROMPT_ADDON

    def _build_pdf_content_blocks(self, pdf_path: Path) -> list:
        """构建单个 PDF 的内容块列表（复用现有大小判断逻辑）"""
        pdf_size = pdf_path.stat().st_size
        if pdf_size <= PDF_SIZE_THRESHOLD:
            with open(pdf_path, "rb") as f:
                pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
            return [{
                "type": "file",
                "file": {
                    "filename": pdf_path.name,
                    "file_data": f"data:application/pdf;base64,{pdf_base64}"
                }
            }]
        else:
            logger.info(
                "PDF too large (%.1fMB > %dMB), converting to page images",
                pdf_size / 1024 / 1024, PDF_SIZE_THRESHOLD // 1024 // 1024
            )
            return self._pdf_to_image_blocks(pdf_path)

    def _build_cross_paper_first_user_content(
        self,
        text: str,
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
    ) -> list:
        """构建串讲第一条 user 消息（包含所有论文 PDF）"""
        content_blocks = []

        for arxiv_id in paper_ids:
            meta = arxiv_service.get_paper(arxiv_id)
            title = meta.title if meta else arxiv_id
            content_blocks.append({
                "type": "text",
                "text": f"=== 论文 [[{arxiv_id}]]: {title} ==="
            })

            pdf_path = arxiv_service.get_pdf_path(arxiv_id)
            if pdf_path:
                content_blocks.extend(self._build_pdf_content_blocks(pdf_path))
            else:
                content_blocks.append({
                    "type": "text",
                    "text": f"（论文 {arxiv_id} 的 PDF 不可用）"
                })

        if quotes:
            text = f"{self._format_quotes(quotes)}\n\n{text}"

        content_blocks.append({"type": "text", "text": text})
        return content_blocks

    def _build_messages_cross_paper(
        self,
        messages: List[ChatMessage],
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
    ) -> list:
        """构建串讲模式的 API 消息列表"""
        api_messages = [
            {"role": "system", "content": self.get_cross_paper_system_prompt()}
        ]

        pdfs_attached = False

        for msg in messages:
            if msg.role == "user" and not pdfs_attached:
                content = self._build_cross_paper_first_user_content(
                    msg.content, paper_ids,
                    quotes if msg == messages[-1] else None,
                )
                api_messages.append({"role": "user", "content": content})
                pdfs_attached = True
            else:
                text = msg.content
                if quotes and msg == messages[-1] and msg.role == "user":
                    text = f"{self._format_quotes(quotes)}\n\n{text}"
                msg_dict = {"role": msg.role, "content": text}
                if msg.role == "assistant" and msg.reasoning:
                    msg_dict["reasoning"] = msg.reasoning
                api_messages.append(msg_dict)

        return api_messages

    async def chat_stream_cross_paper(
        self,
        messages: List[ChatMessage],
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
        reasoning_collector: Optional[List[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """串讲模式的流式对话"""
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")

        api_messages = self._build_messages_cross_paper(messages, paper_ids, quotes)

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


# 全局服务实例
llm_service = LLMService()

