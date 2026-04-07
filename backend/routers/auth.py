"""
认证 API 路由
"""
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends

from config import settings
from models.user import (
    UserCreate,
    UserResponse,
    Token,
    SyncDeviceCreate,
    SyncDeviceResponse,
    SyncDeviceTokenResponse,
)
from services.auth_service import auth_service
from middleware.auth import get_current_user

router = APIRouter()


def _require_admin(user: dict):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")


def _user_response(user: dict) -> UserResponse:
    return UserResponse(id=user["id"], username=user["username"], is_admin=user.get("is_admin", False))


@router.post("/register", response_model=Token)
async def register(body: UserCreate):
    if not settings.invite_code:
        raise HTTPException(status_code=403, detail="注册功能未开放")
    if not body.invite_code or body.invite_code != settings.invite_code:
        raise HTTPException(status_code=403, detail="邀请码无效")

    try:
        user = auth_service.register(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    token = auth_service.create_access_token(user["id"])
    return Token(access_token=token, user=_user_response(user))


@router.post("/login", response_model=Token)
async def login(body: UserCreate):
    user = auth_service.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = auth_service.create_access_token(user["id"])
    return Token(access_token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)):
    return _user_response(user)


# ==================== 管理员接口 ====================

@router.get("/admin/users", response_model=List[UserResponse])
async def list_users(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return [_user_response(u) for u in auth_service.list_users()]


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    if not auth_service.delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "用户已删除"}


class ChangePasswordRequest(BaseModel):
    new_password: str

@router.put("/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    auth_service.change_password(user["id"], body.new_password)
    return {"message": "密码已更新"}


class InviteCodeUpdate(BaseModel):
    invite_code: str

@router.get("/admin/invite-code")
async def get_invite_code(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return {"invite_code": settings.invite_code}

@router.put("/admin/invite-code")
async def update_invite_code(body: InviteCodeUpdate, user: dict = Depends(get_current_user)):
    _require_admin(user)
    settings.invite_code = body.invite_code
    config_file = settings.data_dir / "config.json"
    import json
    data = {}
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    data["invite_code"] = body.invite_code
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return {"message": "邀请码已更新"}


@router.get("/admin/sync-devices", response_model=List[SyncDeviceResponse])
async def list_sync_devices(user: dict = Depends(get_current_user)):
    _require_admin(user)
    return auth_service.list_sync_devices(user["id"])


@router.post("/admin/sync-devices", response_model=SyncDeviceTokenResponse)
async def create_sync_device(body: SyncDeviceCreate, user: dict = Depends(get_current_user)):
    _require_admin(user)
    return auth_service.create_sync_token(user["id"], body.device_name or "")


@router.delete("/admin/sync-devices/{device_id}")
async def revoke_sync_device(device_id: str, user: dict = Depends(get_current_user)):
    _require_admin(user)
    if not auth_service.revoke_sync_device(user["id"], device_id):
        raise HTTPException(status_code=404, detail="同步设备不存在")
    return {"message": "同步设备已吊销"}
