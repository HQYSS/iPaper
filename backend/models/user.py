"""
用户认证相关模型
"""
from typing import Optional
from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str
    invite_code: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    username: str
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class SyncDeviceCreate(BaseModel):
    device_name: Optional[str] = None


class SyncDeviceResponse(BaseModel):
    device_id: str
    device_name: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None


class SyncDeviceTokenResponse(BaseModel):
    device_id: str
    device_name: str
    created_at: str
    token: str
