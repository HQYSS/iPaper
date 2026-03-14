"""
Pydantic 数据模型定义
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ============ 论文相关模型 ============

class PaperCreate(BaseModel):
    """添加论文请求"""
    arxiv_input: str = Field(..., description="arXiv ID 或 URL")


class PaperMeta(BaseModel):
    """论文元信息"""
    arxiv_id: str
    title: str
    title_zh: Optional[str] = None
    summary: str
    authors: List[str]
    download_time: datetime
    has_latex: bool = False
    translation_status: str = "pending"  # pending | translating | completed | failed
    translation_progress: int = 0
    pdf_path: Optional[str] = None


class PaperListItem(BaseModel):
    """论文列表项"""
    arxiv_id: str
    title: str
    title_zh: Optional[str] = None
    summary: str
    authors: List[str]
    download_time: datetime


class PaperDetail(PaperMeta):
    """论文详情"""
    pass


# ============ 对话相关模型 ============

class ChatMessage(BaseModel):
    """对话消息"""
    role: str = Field(..., description="消息角色: user | assistant")
    content: str = Field(..., description="消息内容")
    reasoning: Optional[str] = Field(None, description="模型思考过程（仅 assistant 消息）")


class Quote(BaseModel):
    """引用片段"""
    text: str = Field(..., description="引用的文本内容")
    source: str = Field(..., description="引用来源: pdf | chat")


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户消息")
    quotes: Optional[List[Quote]] = Field(None, description="用户引用的文本片段")
    context: Optional[dict] = Field(None, description="上下文信息（页码、章节等）")


class ChatResponse(BaseModel):
    """对话响应"""
    message: str
    

class ChatHistory(BaseModel):
    """对话历史"""
    paper_id: str
    messages: List[ChatMessage]


# ============ 配置相关模型 ============

class LLMConfigUpdate(BaseModel):
    """更新 LLM 配置"""
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ============ 用户画像相关模型 ============

class ProfileAnalysisRequest(BaseModel):
    """触发画像分析请求"""
    paper_id: str = Field(..., description="论文 ID，用于获取对话历史")

