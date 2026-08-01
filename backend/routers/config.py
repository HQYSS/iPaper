"""
配置管理 API 路由
"""
import httpx
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends

from pydantic import BaseModel
from typing import Optional

from config import settings
from models import LLMConfigUpdate
from middleware.auth import get_current_user
from services.cursor_cli_service import cursor_cli_service
from services.sync_service import sync_service

router = APIRouter()

VALID_LLM_PROVIDERS = {"llm_center_gpt_responses", "llm_center_anthropic", "cursor_cli"}
PROVIDER_DEFAULTS = {
    "llm_center_gpt_responses": {"model": "gpt-5.5", "provider_id": "", "max_tokens": 32768},
    "llm_center_anthropic": {"model": "claude-opus-4-8", "provider_id": "52", "max_tokens": 32768},
}


@router.get("")
async def get_config(user: dict = Depends(get_current_user)):
    uid = user["id"]
    user_cfg = settings.load_user_config(uid)
    return {
        "llm": {
            "provider": settings.llm.provider,
            "api_base": settings.llm.api_base,
            "api_key_configured": bool(settings.llm.api_key),
            "model": settings.llm.model,
            "provider_id": settings.llm.provider_id,
            "execution_mode": settings.llm.execution_mode,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens,
            "cursor_command": settings.llm.cursor_command,
            "cursor_model": settings.llm.cursor_model,
            "cursor_timeout_seconds": settings.llm.cursor_timeout_seconds,
            "cursor_cli_available": cursor_cli_service.is_configured(),
        },
        "data_dir": str(settings.data_dir),
        "hjfy_cookie_configured": bool(user_cfg.get("hjfy_cookie", "") or settings.hjfy_cookie),
        "sync": {
            "role": settings.sync_role,
            "url": settings.sync_url,
            "verify_ssl": settings.sync_verify_ssl,
            "token_configured": bool(settings.sync_token),
        },
    }


@router.put("/llm")
async def update_llm_config(update: LLMConfigUpdate, user: dict = Depends(get_current_user)):
    if update.provider is not None:
        provider = update.provider.strip()
        if provider not in VALID_LLM_PROVIDERS:
            raise HTTPException(status_code=400, detail="不支持的 LLM Provider")
        settings.llm.provider = provider
        defaults = PROVIDER_DEFAULTS.get(provider)
        if defaults:
            settings.llm.model = defaults["model"]
            settings.llm.provider_id = defaults["provider_id"]
            settings.llm.max_tokens = defaults["max_tokens"]
    if update.api_key is not None:
        settings.llm.api_key = update.api_key
    if update.model is not None:
        settings.llm.model = update.model
    if update.provider_id is not None:
        settings.llm.provider_id = update.provider_id.strip()
    if update.execution_mode is not None:
        settings.llm.execution_mode = update.execution_mode
    if update.temperature is not None:
        settings.llm.temperature = update.temperature
    if update.max_tokens is not None:
        settings.llm.max_tokens = update.max_tokens
    if update.cursor_command is not None:
        settings.llm.cursor_command = update.cursor_command.strip() or "cursor"
    if update.cursor_model is not None:
        settings.llm.cursor_model = update.cursor_model.strip()
    if update.cursor_timeout_seconds is not None:
        if update.cursor_timeout_seconds < 30:
            raise HTTPException(status_code=400, detail="Cursor CLI 超时时间不能小于 30 秒")
        settings.llm.cursor_timeout_seconds = update.cursor_timeout_seconds

    settings.save_config()
    return {"message": "配置已更新"}


@router.get("/llm/cursor-models")
async def list_cursor_models(user: dict = Depends(get_current_user)):
    if not cursor_cli_service.is_configured():
        raise HTTPException(status_code=400, detail="Cursor CLI 不可用，请确认已安装 cursor 命令")
    try:
        return {"models": await cursor_cli_service.list_models()}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class HjfyCookieUpdate(BaseModel):
    cookie: str


class SyncConfigUpdate(BaseModel):
    sync_url: Optional[str] = None
    sync_token: Optional[str] = None
    clear_sync_token: bool = False


@router.put("/hjfy")
async def update_hjfy_cookie(update: HjfyCookieUpdate, user: dict = Depends(get_current_user)):
    uid = user["id"]
    cookie = update.cookie.strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie 不能为空")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://hjfy.top/api/userinfo",
            headers={"Cookie": cookie},
        )
        data = resp.json()
        if not data.get("login"):
            raise HTTPException(status_code=400, detail="Cookie 无效或已过期，请重新登录 hjfy.top")

    user_cfg = settings.load_user_config(uid)
    user_cfg["hjfy_cookie"] = cookie
    settings.save_user_config(uid, user_cfg)
    return {"message": "Cookie 已验证并保存", "nickname": data.get("nickname", "")}


@router.put("/sync")
async def update_sync_config(update: SyncConfigUpdate, user: dict = Depends(get_current_user)):
    if not settings.is_sync_client:
        raise HTTPException(status_code=400, detail="当前后端不是同步客户端，不能修改本机同步配置")
    if update.sync_url is not None:
        settings.sync_url = update.sync_url.strip()
    if update.clear_sync_token:
        settings.sync_token = ""
    elif update.sync_token is not None:
        settings.sync_token = update.sync_token.strip()
    settings.save_config()
    sync_service.request_sync("sync-config-updated")
    return {
        "message": "同步配置已更新",
        "updated_at": datetime.now().isoformat(),
    }
