"""
Pydantic 数据模型定义
"""
from datetime import datetime
from typing import Optional, List, Dict
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
    # 英文 PDF 下载状态：downloading | ready | failed
    # 默认 ready 保证旧 meta.json 无需迁移
    download_status: str = "ready"
    download_error: Optional[str] = None


class PaperListItem(BaseModel):
    """论文列表项"""
    arxiv_id: str
    title: str
    title_zh: Optional[str] = None
    summary: str
    authors: List[str]
    download_time: datetime
    download_status: str = "ready"
    download_error: Optional[str] = None


class PaperDetail(PaperMeta):
    """论文详情"""
    pass


# ============ 对话相关模型 ============

class Quote(BaseModel):
    """引用片段"""
    text: str = Field(..., description="引用的文本内容")
    source: str = Field(..., description="引用来源: pdf | chat")


class ChatMessage(BaseModel):
    """对话消息"""
    role: str = Field(..., description="消息角色: user | assistant")
    content: str = Field(..., description="消息内容")
    quotes: Optional[List[Quote]] = Field(None, description="消息关联的引用片段")
    reasoning: Optional[str] = Field(None, description="模型思考过程（仅 assistant 消息）")
    truncated: Optional[bool] = Field(None, description="是否因 max_tokens 被截断（仅 assistant 消息）")


class PageRange(BaseModel):
    """用户选择保留的页码范围（1-based, inclusive）"""
    start: int = Field(..., ge=1, description="起始页码（含）")
    end: int = Field(..., ge=1, description="结束页码（含）")


class PaperPageSelection(BaseModel):
    """单篇论文的保留页码配置"""
    paper_id: Optional[str] = Field(None, description="论文 ID；单论文聊天时可省略")
    ranges: List[PageRange] = Field(..., min_length=1, description="保留的页码范围列表")


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., description="用户消息")
    quotes: Optional[List[Quote]] = Field(None, description="用户引用的文本片段")
    page_selections: Optional[List[PaperPageSelection]] = Field(None, description="用户指定保留的 PDF 页码范围")
    context: Optional[dict] = Field(None, description="上下文信息（页码、章节等）")


class ChatResponse(BaseModel):
    """对话响应"""
    message: str


class ChatDraft(BaseModel):
    """未发送草稿"""
    input: str = Field("", description="输入框中尚未发送的内容")
    quotes: Optional[List[Quote]] = Field(None, description="待发送消息关联的引用片段")
    page_selections: Optional[List[PaperPageSelection]] = Field(None, description="当前会话已选定的 PDF 页码范围")

class ForkData(BaseModel):
    """分支数据"""
    alternatives: List[List[ChatMessage]]
    active: int = 0

class ChatHistory(BaseModel):
    """对话历史"""
    paper_id: str
    session_id: str = ""
    messages: List[ChatMessage]
    forks: Optional[Dict[str, ForkData]] = None
    draft: Optional[ChatDraft] = None

class ChatHistoryUpdate(BaseModel):
    """前端直接更新对话历史（编辑/切换分支时使用）"""
    messages: List[ChatMessage]
    forks: Optional[Dict[str, ForkData]] = None


class ChatDraftUpdate(BaseModel):
    """更新未发送草稿"""
    draft: ChatDraft


# ============ 会话相关模型 ============

class SessionMeta(BaseModel):
    """会话元信息"""
    id: str
    title: str = "新对话"
    created_at: datetime
    updated_at: datetime

class SessionList(BaseModel):
    """会话列表"""
    sessions: List[SessionMeta]
    last_active_session_id: Optional[str] = None

class SessionCreate(BaseModel):
    """新建会话请求"""
    title: Optional[str] = None


# ============ 串讲（Cross-Paper）相关模型 ============

class CrossPaperSessionCreate(BaseModel):
    """新建串讲会话请求"""
    paper_ids: List[str] = Field(..., min_length=2, max_length=5, description="参与串讲的论文 ID 列表")
    title: Optional[str] = None


class CrossPaperSessionMeta(SessionMeta):
    """串讲会话元信息（扩展 SessionMeta）"""
    paper_ids: List[str] = Field(default_factory=list, description="参与串讲的论文 ID 列表")


class CrossPaperSessionList(BaseModel):
    """串讲会话列表"""
    sessions: List[CrossPaperSessionMeta]
    last_active_session_id: Optional[str] = None


class CrossPaperAddPapersRequest(BaseModel):
    """向串讲会话添加论文"""
    paper_ids: List[str] = Field(..., min_length=1, description="要添加的论文 ID 列表")


class CrossPaperChatRequest(BaseModel):
    """串讲对话请求"""
    message: str = Field(..., description="用户消息")
    quotes: Optional[List[Quote]] = Field(None, description="用户引用的文本片段")
    page_selections: Optional[List[PaperPageSelection]] = Field(None, description="用户指定保留的各论文 PDF 页码范围")


class CrossPaperChatHistory(BaseModel):
    """串讲对话历史"""
    session_id: str
    paper_ids: List[str]
    messages: List[ChatMessage]
    forks: Optional[Dict[str, ForkData]] = None
    draft: Optional[ChatDraft] = None


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
    cross_paper_session_id: Optional[str] = Field(None, description="串讲会话 ID（串讲模式时使用）")


class EvolutionChatRequest(BaseModel):
    """进化 Agent 对话请求"""
    message: str = Field(..., description="用户消息")
    paper_id: Optional[str] = Field(None, description="论文 ID")
    cross_paper_session_id: Optional[str] = Field(None, description="串讲会话 ID")
    evolution_messages: List[dict] = Field(default_factory=list, description="进化面板的对话历史")


class SaveEditPlanRequest(BaseModel):
    """保存编辑计划请求"""
    edit_plan: dict = Field(..., description="编辑计划 JSON")
    paper_title: str = Field("", description="来源论文标题")

