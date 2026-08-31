"""轻量用户关注与内容流 API。"""
import json
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from config import settings
from middleware.auth import get_sync_user
from services.auth_service import auth_service

router = APIRouter()


def _social_dir(user_id: str) -> Path:
    path = settings.get_user_data_dir(user_id) / "social"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _following_path(user_id: str) -> Path:
    return _social_dir(user_id) / "following.json"


def _read_following(user_id: str) -> list[str]:
    path = _following_path(user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [str(value) for value in data.get("user_ids", [])]
    except (OSError, json.JSONDecodeError):
        return []


def _write_following(user_id: str, user_ids: list[str]) -> None:
    _following_path(user_id).write_text(
        json.dumps({"user_ids": sorted(set(user_ids))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _paper_items(user_id: str) -> list[dict]:
    papers_dir = settings.get_user_papers_dir(user_id)
    result = []
    if not papers_dir.exists():
        return result
    for paper_dir in papers_dir.iterdir():
        meta_path = paper_dir / "meta.json"
        if not paper_dir.is_dir() or not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        chats_dir = paper_dir / "chats"
        session_count = len(list(chats_dir.glob("*.json"))) if chats_dir.exists() else 0
        chat_preview = ""
        if chats_dir.exists():
            for chat_path in sorted(chats_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
                try:
                    chat = json.loads(chat_path.read_text(encoding="utf-8"))
                    messages = chat.get("messages", [])
                    if messages:
                        chat_preview = str(messages[-1].get("content") or "").strip()
                        if chat_preview:
                            break
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    continue
        result.append({
            "arxiv_id": meta.get("arxiv_id", paper_dir.name),
            "title": meta.get("title") or f"arXiv {paper_dir.name}",
            "summary": meta.get("summary") or "",
            "updated_at": meta.get("updated_at") or meta.get("download_time"),
            "session_count": session_count,
            "chat_preview": chat_preview[:240],
        })
    return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)


def _paper_detail(user_id: str, paper_id: str) -> Optional[dict]:
    paper = next((item for item in _paper_items(user_id) if item["arxiv_id"] == paper_id), None)
    if not paper:
        return None
    paper_dir = settings.get_user_papers_dir(user_id) / paper_id
    chats_dir = paper_dir / "chats"
    sessions_meta = {}
    sessions_path = chats_dir / "sessions.json"
    if sessions_path.exists():
        try:
            raw = json.loads(sessions_path.read_text(encoding="utf-8"))
            sessions_meta = {str(item.get("id")): item for item in raw.get("sessions", [])}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            sessions_meta = {}
    sessions = []
    if chats_dir.exists():
        for chat_path in chats_dir.glob("*.json"):
            if chat_path.name == "sessions.json":
                continue
            try:
                raw = json.loads(chat_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            session_id = str(raw.get("session_id") or chat_path.stem)
            messages = raw.get("messages", [])
            sessions.append({
                "id": session_id,
                "title": sessions_meta.get(session_id, {}).get("title") or "对话",
                "created_at": sessions_meta.get(session_id, {}).get("created_at") or raw.get("updated_at"),
                "updated_at": sessions_meta.get(session_id, {}).get("updated_at") or raw.get("updated_at"),
                "messages": messages if isinstance(messages, list) else [],
            })
    sessions.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {"paper": paper, "sessions": sessions}


def _user_card(user: dict, current_id: str, following: set[str]) -> dict:
    papers = _paper_items(user["id"])
    return {
        "id": user["id"],
        "username": user["username"],
        "is_following": user["id"] in following,
        "paper_count": len(papers),
        "chat_count": sum(item["session_count"] for item in papers),
        "papers": papers[:8],
        "is_self": user["id"] == current_id,
    }


def _sync_base() -> str:
    value = (settings.sync_url or "").rstrip("/")
    return value if value.endswith("/api") else f"{value}/api"


async def _proxy_if_client(path: str, method: str, user: dict, body: Optional[dict] = None):
    if not settings.is_sync_client:
        return None
    token = settings.sync_token.strip()
    if not token:
        raise HTTPException(status_code=503, detail="尚未绑定云端账号")
    async with httpx.AsyncClient(verify=settings.sync_verify_ssl, timeout=20) as client:
        response = await client.request(
            method,
            f"{_sync_base()}{path}",
            headers={"Authorization": f"Bearer {token}", "X-Sync-Protocol": "2"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return response.json()


@router.get("/users")
async def search_users(
    q: str = Query("", max_length=80),
    user: dict = Depends(get_sync_user),
):
    proxied = await _proxy_if_client(f"/social/users?q={q}", "GET", user)
    if proxied is not None:
        return proxied
    following = set(_read_following(user["id"]))
    query = q.strip().lower()
    # Admin is still a normal social identity; the flag only controls
    # administration APIs and must not hide the account from discovery.
    users = auth_service.list_users()
    if query:
        users = [item for item in users if query in item.get("username", "").lower()]
    return {"users": [_user_card(item, user["id"], following) for item in users[:30]]}


@router.get("/users/{target_id}")
async def get_user_profile(target_id: str, user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client(f"/social/users/{target_id}", "GET", user)
    if proxied is not None:
        return proxied
    target = auth_service.get_user_by_id(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    following = set(_read_following(user["id"]))
    profile = _user_card(target, user["id"], following)
    profile["papers"] = _paper_items(target_id)
    return profile


@router.get("/users/{target_id}/papers/{paper_id}")
async def get_user_paper_detail(target_id: str, paper_id: str, user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client(f"/social/users/{target_id}/papers/{paper_id}", "GET", user)
    if proxied is not None:
        return proxied
    detail = _paper_detail(target_id, paper_id)
    if not detail:
        raise HTTPException(status_code=404, detail="论文不存在")
    target = auth_service.get_user_by_id(target_id)
    detail["username"] = target["username"] if target else target_id
    return detail


@router.get("/following")
async def list_following(user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client("/social/following", "GET", user)
    if proxied is not None:
        return proxied
    following = set(_read_following(user["id"]))
    users = [auth_service.get_user_by_id(uid) for uid in following]
    return {"users": [_user_card(item, user["id"], following) for item in users if item]}


@router.post("/follow/{target_id}")
async def follow_user(target_id: str, user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client(f"/social/follow/{target_id}", "POST", user)
    if proxied is not None:
        return proxied
    target = auth_service.get_user_by_id(target_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能关注自己")
    ids = _read_following(user["id"])
    if target_id not in ids:
        ids.append(target_id)
        _write_following(user["id"], ids)
    return {"following": True}


@router.delete("/follow/{target_id}")
async def unfollow_user(target_id: str, user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client(f"/social/follow/{target_id}", "DELETE", user)
    if proxied is not None:
        return proxied
    _write_following(user["id"], [uid for uid in _read_following(user["id"]) if uid != target_id])
    return {"following": False}


@router.get("/feed")
async def following_feed(user: dict = Depends(get_sync_user)):
    proxied = await _proxy_if_client("/social/feed", "GET", user)
    if proxied is not None:
        return proxied
    following = set(_read_following(user["id"]))
    feed = []
    for target_id in following:
        target = auth_service.get_user_by_id(target_id)
        if not target:
            continue
        for paper in _paper_items(target_id)[:12]:
            feed.append({**paper, "user_id": target_id, "username": target["username"]})
    feed.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {"items": feed[:50]}
