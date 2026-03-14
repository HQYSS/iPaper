"""
对话 API 路由
"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models import ChatRequest, ChatMessage, ChatHistory
from services.llm_service import llm_service
from services.storage_service import storage_service
from services.arxiv_service import arxiv_service

router = APIRouter()


@router.post("/{paper_id}")
async def chat(paper_id: str, request: ChatRequest):
    """
    发送对话消息（流式响应）
    """
    # 检查论文是否存在
    paper = arxiv_service.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    
    # 检查 LLM 是否配置
    if not llm_service.is_configured():
        raise HTTPException(status_code=400, detail="LLM API Key 未配置")
    
    # 获取历史消息
    history = storage_service.get_chat_history(paper_id)
    
    # 添加用户消息
    user_message = ChatMessage(role="user", content=request.message)
    history.append(user_message)
    
    # 获取 PDF 路径
    pdf_path = arxiv_service.get_pdf_path(paper_id)
    
    async def generate():
        full_response = ""
        reasoning_parts = []
        
        try:
            async for chunk in llm_service.chat_stream(
                messages=history,
                pdf_path=pdf_path,
                quotes=request.quotes,
                reasoning_collector=reasoning_parts
            ):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            
            reasoning = ''.join(reasoning_parts) if reasoning_parts else None
            assistant_message = ChatMessage(
                role="assistant",
                content=full_response,
                reasoning=reasoning
            )
            history.append(assistant_message)
            storage_service.save_chat_history(paper_id, history)
            
            yield f"data: {json.dumps({'type': 'done', 'full_response': full_response})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.get("/{paper_id}/history", response_model=ChatHistory)
async def get_chat_history(paper_id: str):
    """获取对话历史"""
    # 检查论文是否存在
    paper = arxiv_service.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    
    messages = storage_service.get_chat_history(paper_id)
    
    return ChatHistory(paper_id=paper_id, messages=messages)


@router.delete("/{paper_id}/history")
async def clear_chat_history(paper_id: str):
    """清空对话历史"""
    # 检查论文是否存在
    paper = arxiv_service.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    
    storage_service.clear_chat_history(paper_id)
    
    return {"message": "对话历史已清空"}

