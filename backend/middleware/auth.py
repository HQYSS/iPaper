"""
认证中间件 — FastAPI Depends 函数

本地运行（host=127.0.0.1）时跳过认证，使用 LOCAL_USER_ID 指定的用户。
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from services.auth_service import auth_service

_bearer_scheme = HTTPBearer(auto_error=False)

LOCAL_USER_ID = "441e2fb8d4a64409"


def _is_local_mode() -> bool:
    return settings.host == "127.0.0.1"


def _make_user_dict(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "is_admin": user.get("is_admin", False)}


def _get_local_user() -> dict:
    user = auth_service.get_user_by_id(LOCAL_USER_ID)
    if user:
        return _make_user_dict(user)
    return {"id": LOCAL_USER_ID, "username": "local", "is_admin": True}


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    if _is_local_mode():
        if credentials is None:
            return _get_local_user()
        user = auth_service.get_current_user(credentials.credentials)
        return _make_user_dict(user) if user else _get_local_user()

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
    return _make_user_dict(user)
