"""
认证 API 路由
"""
from fastapi import APIRouter, HTTPException, Depends

from config import settings
from models.user import UserCreate, UserResponse, Token
from services.auth_service import auth_service
from middleware.auth import get_current_user

router = APIRouter()


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
    return Token(
        access_token=token,
        user=UserResponse(id=user["id"], username=user["username"]),
    )


@router.post("/login", response_model=Token)
async def login(body: UserCreate):
    user = auth_service.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = auth_service.create_access_token(user["id"])
    return Token(
        access_token=token,
        user=UserResponse(id=user["id"], username=user["username"]),
    )


@router.get("/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)):
    return UserResponse(id=user["id"], username=user["username"])
