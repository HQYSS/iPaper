"""
认证中间件 — FastAPI Depends 函数

本地运行（host=127.0.0.1）时跳过认证，使用 LOCAL_USER_ID 指定的用户。
"""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from services.auth_service import auth_service
from services.log_context import set_log_user_id
from services.sync_service import sync_identity_from_token

_bearer_scheme = HTTPBearer(auto_error=False)

LOCAL_USER_ID = "441e2fb8d4a64409"
LOCAL_USERNAME = "lingxi"


def _is_local_mode() -> bool:
    return (
        settings.local_auth_bypass
        and not settings.is_sync_server
        and settings.host == "127.0.0.1"
    )


def _is_loopback_request(request: Request) -> bool:
    client_host = request.client.host if request.client else ""
    return client_host in {"127.0.0.1", "::1"}


def _make_user_dict(user: dict) -> dict:
    return {"id": user["id"], "username": user["username"], "is_admin": user.get("is_admin", False)}


def _attach_user(request: Request, user: dict) -> dict:
    user_dict = _make_user_dict(user)
    request.state.user_id = user_dict["id"]
    set_log_user_id(user_dict["id"])
    return user_dict


def _get_local_user() -> dict:
    # The desktop client has no cloud auth cookie on ordinary loopback calls.
    # Use the configured device token identity so switching sync accounts also
    # switches the local data namespace instead of silently falling back to the
    # historical lingxi account.
    sync_user_id = sync_identity_from_token(settings.sync_token)
    user = auth_service.get_user_by_id(sync_user_id) if sync_user_id else None
    if user is None:
        user = auth_service.ensure_local_user(LOCAL_USER_ID, LOCAL_USERNAME)
    return _make_user_dict(user)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    if _is_local_mode() and _is_loopback_request(request):
        if credentials is None:
            return _attach_user(request, _get_local_user())
        user = auth_service.get_current_user(credentials.credentials)
        if user is None:
            sync_user_id = sync_identity_from_token(credentials.credentials)
            user = auth_service.get_user_by_id(sync_user_id) if sync_user_id else None
        return _attach_user(request, user) if user else _attach_user(request, _get_local_user())

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
    return _attach_user(request, user)


async def get_sync_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    if _is_local_mode() and _is_loopback_request(request):
        if credentials is None:
            return _attach_user(request, _get_local_user())
        user = auth_service.get_current_user(credentials.credentials)
        if not user:
            user = auth_service.get_user_by_sync_token(credentials.credentials)
        if not user:
            sync_user_id = sync_identity_from_token(credentials.credentials)
            user = auth_service.get_user_by_id(sync_user_id) if sync_user_id else None
        return _attach_user(request, user) if user else _attach_user(request, _get_local_user())

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="未提供认证信息",
        )

    user = auth_service.get_user_by_sync_token(credentials.credentials)
    if not user:
        user = auth_service.get_current_user(credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的同步凭证",
        )
    return _attach_user(request, user)
