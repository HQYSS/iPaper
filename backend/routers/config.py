"""
配置管理 API 路由
"""
from fastapi import APIRouter

from config import settings
from models import LLMConfigUpdate

router = APIRouter()


@router.get("")
async def get_config():
    """获取当前配置"""
    return {
        "llm": {
            "api_base": settings.llm.api_base,
            "api_key_configured": bool(settings.llm.api_key),
            "model": settings.llm.model,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens
        },
        "data_dir": str(settings.data_dir)
    }


@router.put("/llm")
async def update_llm_config(update: LLMConfigUpdate):
    """更新 LLM 配置"""
    if update.api_key is not None:
        settings.llm.api_key = update.api_key
    if update.model is not None:
        settings.llm.model = update.model
    if update.temperature is not None:
        settings.llm.temperature = update.temperature
    if update.max_tokens is not None:
        settings.llm.max_tokens = update.max_tokens
    
    # 保存配置
    settings.save_config()
    
    return {"message": "配置已更新"}

