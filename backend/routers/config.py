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
from services.sync_service import sync_service

router = APIRouter()


@router.get("")
async def get_config(user: dict = Depends(get_current_user)):
    uid = user["id"]
    user_cfg = settings.load_user_config(uid)
    return {
        "llm": {
            "api_base": settings.llm.api_base,
            "api_key_configured": bool(settings.llm.api_key),
            "model": settings.llm.model,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens
        },
        "data_dir": str(settings.data_dir),
        "hjfy_cookie_configured": bool(user_cfg.get("hjfy_cookie", "") or settings.hjfy_cookie),
        "sync": {
            "url": settings.sync_url,
            "token_configured": bool(settings.sync_token),
        },
    }


@router.put("/llm")
async def update_llm_config(update: LLMConfigUpdate, user: dict = Depends(get_current_user)):
    if update.api_key is not None:
        settings.llm.api_key = update.api_key
    if update.model is not None:
        settings.llm.model = update.model
    if update.temperature is not None:
        settings.llm.temperature = update.temperature
    if update.max_tokens is not None:
        settings.llm.max_tokens = update.max_tokens

    settings.save_config()
    return {"message": "配置已更新"}


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
