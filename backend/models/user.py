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
