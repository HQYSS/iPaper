"""
认证中间件 — FastAPI Depends 函数

本地运行（host=127.0.0.1）时跳过认证，使用固定本地用户。
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from services.auth_service import auth_service

_bearer_scheme = HTTPBearer(auto_error=False)

LOCAL_USER = {"id": "local", "username": "local"}


def _is_local_mode() -> bool:
    return settings.host == "127.0.0.1"


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    if _is_local_mode():
        if credentials is None:
            return LOCAL_USER
        user = auth_service.get_current_user(credentials.credentials)
        return {"id": user["id"], "username": user["username"]} if user else LOCAL_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="未提供认证信息",
        )
    user = auth_service.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的 token",
        )
    return {"id": user["id"], "username": user["username"]}
