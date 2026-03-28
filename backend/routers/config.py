"""
配置管理 API 路由
"""
import httpx
from fastapi import APIRouter, HTTPException, Depends

from pydantic import BaseModel

from config import settings
from models import LLMConfigUpdate
from middleware.auth import get_current_user

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
