"""
用户偏好设置 API 路由
"""
import json
from pathlib import Path

from fastapi import APIRouter, Depends

from config import settings
from middleware.auth import get_current_user

router = APIRouter()


def _prefs_path(user_id: str) -> Path:
    return settings.get_user_data_dir(user_id) / "preferences.json"


@router.get("")
async def get_preferences(user: dict = Depends(get_current_user)):
    path = _prefs_path(user["id"])
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.put("")
async def update_preferences(body: dict, user: dict = Depends(get_current_user)):
    path = _prefs_path(user["id"])
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)

    existing.update(body)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return {"message": "ok"}
