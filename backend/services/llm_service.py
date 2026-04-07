"""
LLM 对话服务
"""
import io
import json
import base64
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional, List, Dict, Tuple

import fitz
from openai import AsyncOpenAI

from config import settings
from models import ChatMessage, Quote, PaperPageSelection
from services.user_profile_service import user_profile_service
from services.arxiv_service import arxiv_service

logger = logging.getLogger(__name__)

PDF_SIZE_THRESHOLD = 15 * 1024 * 1024  # 15MB
IMAGE_PAYLOAD_LIMIT = 20 * 1024 * 1024  # 20MB (base64 payload before data URL prefix)
IMAGE_DPI = 150
IMAGE_QUALITY = 85


class PageSelectionRequiredError(Exception):
    """转成图像后仍超限，需要用户指定保留页码。"""

    def __init__(self, requirements: List[dict], message: str):
        super().__init__(message)
        self.requirements = requirements


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
        reasoning_collector: Optional[List[str]] = None,
        prepared_api_messages: Optional[list] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
        paper_id: Optional[str] = None,
        paper_title: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话。
        reasoning_collector: 可选的可变列表，用于在流式过程中累积 reasoning 片段。
        调用方在流结束后通过 ''.join(reasoning_collector) 获取完整 reasoning。
        """
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")
        
        api_messages = prepared_api_messages or self._build_messages(
            messages,
            pdf_path,
            quotes,
            page_selections=page_selections,
            paper_id=paper_id,
            paper_title=paper_title,
        )
        
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

    def prepare_chat_api_messages(
        self,
        messages: List[ChatMessage],
        pdf_path: Optional[Path] = None,
        quotes: Optional[List[Quote]] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
        paper_id: Optional[str] = None,
        paper_title: Optional[str] = None,
    ) -> list:
        return self._build_messages(
            messages=messages,
            pdf_path=pdf_path,
            quotes=quotes,
            page_selections=page_selections,
            paper_id=paper_id,
            paper_title=paper_title,
        )

    def prepare_cross_paper_api_messages(
        self,
        messages: List[ChatMessage],
        user_id: str,
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
    ) -> list:
        return self._build_messages_cross_paper(
            messages=messages,
            user_id=user_id,
            paper_ids=paper_ids,
            quotes=quotes,
            page_selections=page_selections,
        )

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
        quotes: Optional[List[Quote]] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
        paper_id: Optional[str] = None,
        paper_title: Optional[str] = None,
    ) -> list:
        """构建 API 消息列表"""
        api_messages = [
            {"role": "system", "content": self.get_system_prompt()}
        ]
        
        pdf_attached = False
        
        for msg in messages:
            if msg.role == "user" and pdf_path and not pdf_attached:
                content = self._build_user_content_with_pdf(
                    msg.content,
                    pdf_path,
                    quotes if msg == messages[-1] else None,
                    page_selection=self._pick_page_selection(page_selections, paper_id),
                    paper_id=paper_id,
                    paper_title=paper_title,
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
        quotes: Optional[List[Quote]] = None,
        page_selection: Optional[PaperPageSelection] = None,
        paper_id: Optional[str] = None,
        paper_title: Optional[str] = None,
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
            content = self._pdf_to_image_blocks(
                pdf_path=pdf_path,
                paper_id=paper_id or pdf_path.stem,
                paper_title=paper_title or pdf_path.name,
                page_selection=page_selection,
            )

        if quotes:
            text = f"{self._format_quotes(quotes)}\n\n{text}"

        content.append({
            "type": "text",
            "text": text
        })

        return content

    @staticmethod
    def _pick_page_selection(
        page_selections: Optional[List[PaperPageSelection]],
        paper_id: Optional[str],
    ) -> Optional[PaperPageSelection]:
        if not page_selections:
            return None
        if paper_id:
            for selection in page_selections:
                if selection.paper_id == paper_id:
                    return selection
        if len(page_selections) == 1:
            return page_selections[0]
        return None

    @staticmethod
    def _normalize_page_ranges(
        page_selection: PaperPageSelection,
        total_pages: int,
        paper_title: str,
    ) -> List[Tuple[int, int]]:
        normalized: List[Tuple[int, int]] = []
        for page_range in page_selection.ranges:
            start = int(page_range.start)
            end = int(page_range.end)
            if start > end:
                raise ValueError(f"{paper_title} 的页码范围无效：起始页不能大于结束页")
            if start < 1 or end > total_pages:
                raise ValueError(f"{paper_title} 的页码范围超出总页数（1-{total_pages}）")
            normalized.append((start, end))

        normalized.sort(key=lambda item: (item[0], item[1]))
        merged: List[Tuple[int, int]] = []
        for start, end in normalized:
            if not merged or start > merged[-1][1] + 1:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    @staticmethod
    def _format_page_ranges(ranges: List[Tuple[int, int]]) -> str:
        parts = []
        for start, end in ranges:
            parts.append(str(start) if start == end else f"{start}-{end}")
        return "、".join(parts)

    @staticmethod
    def _build_page_selection_requirement(
        paper_id: str,
        paper_title: str,
        total_pages: int,
        selected_ranges: Optional[List[Tuple[int, int]]] = None,
    ) -> dict:
        requirement = {
            "paper_id": paper_id,
            "title": paper_title,
            "total_pages": total_pages,
        }
        if selected_ranges:
            requirement["selected_ranges"] = [
                {"start": start, "end": end}
                for start, end in selected_ranges
            ]
        return requirement

    def _pdf_to_image_blocks(
        self,
        pdf_path: Path,
        paper_id: str,
        paper_title: str,
        page_selection: Optional[PaperPageSelection] = None,
    ) -> list:
        """将 PDF 渲染为 JPEG；超限时要求用户明确指定保留页码。"""
        doc = fitz.open(pdf_path)
        try:
            total_pages = len(doc)
            normalized_ranges: Optional[List[Tuple[int, int]]] = None
            if page_selection:
                normalized_ranges = self._normalize_page_ranges(page_selection, total_pages, paper_title)
                target_pages = [
                    page_num
                    for start, end in normalized_ranges
                    for page_num in range(start - 1, end)
                ]
            else:
                target_pages = list(range(total_pages))

            blocks = []
            matrix = fitz.Matrix(IMAGE_DPI / 72, IMAGE_DPI / 72)
            total_payload_bytes = 0
            rendered_pages = 0

            for page_num in target_pages:
                page = doc[page_num]
                pix = page.get_pixmap(matrix=matrix)

                buf = io.BytesIO()
                buf.write(pix.tobytes("jpeg", jpg_quality=IMAGE_QUALITY))
                img_bytes = buf.getvalue()
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                payload_bytes = len(img_b64.encode("ascii"))

                if blocks and total_payload_bytes + payload_bytes > IMAGE_PAYLOAD_LIMIT:
                    if normalized_ranges:
                        raise PageSelectionRequiredError(
                            requirements=[
                                self._build_page_selection_requirement(
                                    paper_id=paper_id,
                                    paper_title=paper_title,
                                    total_pages=total_pages,
                                    selected_ranges=normalized_ranges,
                                )
                            ],
                            message=(
                                f"《{paper_title}》选中的页码范围（{self._format_page_ranges(normalized_ranges)}）"
                                "转成图像后仍超过 20MB，请进一步缩小保留范围。"
                            ),
                        )

                    raise PageSelectionRequiredError(
                        requirements=[
                            self._build_page_selection_requirement(
                                paper_id=paper_id,
                                paper_title=paper_title,
                                total_pages=total_pages,
                            )
                        ],
                        message=(
                            f"《{paper_title}》转成图像后仍超过 20MB，请先选择要保留的页码范围。"
                        ),
                    )

                blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{img_b64}"
                    }
                })
                total_payload_bytes += payload_bytes
                rendered_pages += 1

            logger.info(
                "Converted %d/%d pages of %s to JPEG images (~%.1fMB base64 payload)",
                rendered_pages,
                total_pages,
                paper_id,
                total_payload_bytes / 1024 / 1024,
            )

            if normalized_ranges and rendered_pages < total_pages:
                blocks.append({
                    "type": "text",
                    "text": (
                        f"注意：原始 PDF《{paper_title}》共 {total_pages} 页，这里只提供了第 "
                        f"{self._format_page_ranges(normalized_ranges)} 页的页面图像。请明确说明你的判断仅基于这些页，"
                        "不要假装已经读取了全文。"
                    )
                })

            return blocks
        finally:
            doc.close()

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

    def _build_pdf_content_blocks(
        self,
        pdf_path: Path,
        paper_id: str,
        paper_title: str,
        page_selection: Optional[PaperPageSelection] = None,
    ) -> list:
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
            return self._pdf_to_image_blocks(
                pdf_path=pdf_path,
                paper_id=paper_id,
                paper_title=paper_title,
                page_selection=page_selection,
            )

    def _build_cross_paper_first_user_content(
        self,
        text: str,
        user_id: str,
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
    ) -> list:
        """构建串讲第一条 user 消息（包含所有论文 PDF）"""
        content_blocks = []
        pending_requirements: List[dict] = []
        selection_map: Dict[str, PaperPageSelection] = {
            selection.paper_id: selection
            for selection in (page_selections or [])
            if selection.paper_id
        }

        for arxiv_id in paper_ids:
            meta = arxiv_service.get_paper(user_id, arxiv_id)
            title = meta.title if meta else arxiv_id
            content_blocks.append({
                "type": "text",
                "text": f"=== 论文 [[{arxiv_id}]]: {title} ==="
            })

            pdf_path = arxiv_service.get_pdf_path(user_id, arxiv_id)
            if pdf_path:
                try:
                    content_blocks.extend(self._build_pdf_content_blocks(
                        pdf_path=pdf_path,
                        paper_id=arxiv_id,
                        paper_title=title,
                        page_selection=selection_map.get(arxiv_id),
                    ))
                except PageSelectionRequiredError as exc:
                    pending_requirements.extend(exc.requirements)
            else:
                content_blocks.append({
                    "type": "text",
                    "text": f"（论文 {arxiv_id} 的 PDF 不可用）"
                })

        if pending_requirements:
            has_selected_ranges = any(item.get("selected_ranges") for item in pending_requirements)
            if has_selected_ranges:
                raise PageSelectionRequiredError(
                    requirements=pending_requirements,
                    message="你选择的部分页码范围转成图像后仍超过 20MB，请进一步缩小这些论文的保留范围。",
                )
            raise PageSelectionRequiredError(
                requirements=pending_requirements,
                message="部分论文转成图像后仍超过 20MB，请先为这些论文选择要保留的页码范围。",
            )

        if quotes:
            text = f"{self._format_quotes(quotes)}\n\n{text}"

        content_blocks.append({"type": "text", "text": text})
        return content_blocks

    def _build_messages_cross_paper(
        self,
        messages: List[ChatMessage],
        user_id: str,
        paper_ids: List[str],
        quotes: Optional[List[Quote]] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
    ) -> list:
        """构建串讲模式的 API 消息列表"""
        api_messages = [
            {"role": "system", "content": self.get_cross_paper_system_prompt()}
        ]

        pdfs_attached = False

        for msg in messages:
            if msg.role == "user" and not pdfs_attached:
                content = self._build_cross_paper_first_user_content(
                    msg.content,
                    user_id,
                    paper_ids,
                    quotes if msg == messages[-1] else None,
                    page_selections=page_selections,
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
        prepared_api_messages: Optional[list] = None,
        user_id: Optional[str] = None,
        page_selections: Optional[List[PaperPageSelection]] = None,
    ) -> AsyncGenerator[str, None]:
        """串讲模式的流式对话"""
        if not self.is_configured():
            raise ValueError("LLM API Key 未配置")

        api_messages = prepared_api_messages
        if api_messages is None:
            if not user_id:
                raise ValueError("串讲模式缺少 user_id")
            api_messages = self._build_messages_cross_paper(
                messages,
                user_id,
                paper_ids,
                quotes,
                page_selections=page_selections,
            )

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

