"""
用户认证服务 — 注册、登录、JWT 管理
"""
import json
import secrets
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from jose import jwt, JWTError
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

TOKEN_EXPIRE_DAYS = 30
JWT_ALGORITHM = "HS256"
SYNC_TOKEN_TYPE = "sync_device"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:

    def __init__(self):
        self._users_file = settings.data_dir / "users.json"
        self._secret_file = settings.data_dir / "jwt_secret.key"
        self._sync_devices_file = settings.data_dir / "sync_devices.json"

    @property
    def _jwt_secret(self) -> str:
        if self._secret_file.exists():
            return self._secret_file.read_text().strip()
        secret = secrets.token_hex(32)
        self._secret_file.parent.mkdir(parents=True, exist_ok=True)
        self._secret_file.write_text(secret)
        return secret

    def _load_users(self) -> List[dict]:
        if not self._users_file.exists():
            return []
        with open(self._users_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_users(self, users: List[dict]) -> None:
        self._users_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._users_file, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)

    def _load_sync_devices(self) -> List[dict]:
        if not self._sync_devices_file.exists():
            return []
        with open(self._sync_devices_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_sync_devices(self, devices: List[dict]) -> None:
        self._sync_devices_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._sync_devices_file, "w", encoding="utf-8") as f:
            json.dump(devices, f, indent=2, ensure_ascii=False)

    def _find_user(self, username: str) -> Optional[dict]:
        for u in self._load_users():
            if u["username"] == username:
                return u
        return None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        for u in self._load_users():
            if u["id"] == user_id:
                return u
        return None

    def ensure_local_user(self, user_id: str, username: str) -> dict:
        users = self._load_users()
        now = datetime.now().isoformat()

        for user in users:
            if user["id"] == user_id:
                user["username"] = username
                user["is_admin"] = True
                user.setdefault("created_at", now)
                if not user.get("password_hash"):
                    user["password_hash"] = pwd_context.hash(secrets.token_hex(16))
                self._save_users(users)
                return user

        user = {
            "id": user_id,
            "username": username,
            "password_hash": pwd_context.hash(secrets.token_hex(16)),
            "is_admin": True,
            "created_at": now,
        }
        users.append(user)
        self._save_users(users)
        logger.info("Created local admin user: %s (%s)", username, user_id)
        return user

    def register(self, username: str, password: str, is_admin: bool = False) -> dict:
        if self._find_user(username):
            raise ValueError("用户名已存在")

        user = {
            "id": uuid.uuid4().hex[:16],
            "username": username,
            "password_hash": pwd_context.hash(password),
            "is_admin": is_admin,
            "created_at": datetime.now().isoformat(),
        }
        users = self._load_users()
        if not users and not is_admin:
            user["is_admin"] = True
        users.append(user)
        self._save_users(users)
        logger.info("User registered: %s (admin=%s)", username, user["is_admin"])
        return user

    def list_users(self) -> List[dict]:
        return [
            {"id": u["id"], "username": u["username"], "is_admin": u.get("is_admin", False), "created_at": u.get("created_at")}
            for u in self._load_users()
        ]

    def delete_user(self, user_id: str) -> bool:
        users = self._load_users()
        original_len = len(users)
        users = [u for u in users if u["id"] != user_id]
        if len(users) == original_len:
            return False
        self._save_users(users)
        return True

    def change_password(self, user_id: str, new_password: str) -> bool:
        users = self._load_users()
        for u in users:
            if u["id"] == user_id:
                u["password_hash"] = pwd_context.hash(new_password)
                self._save_users(users)
                return True
        return False

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        user = self._find_user(username)
        if not user:
            return None
        if not pwd_context.verify(password, user["password_hash"]):
            return None
        return user

    def create_access_token(self, user_id: str) -> str:
        expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
        payload = {"sub": user_id, "exp": expire}
        return jwt.encode(payload, self._jwt_secret, algorithm=JWT_ALGORITHM)

    def create_sync_token(self, user_id: str, device_name: str = "") -> dict:
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("用户不存在")

        now_dt = datetime.utcnow()
        now = now_dt.isoformat()
        device_id = uuid.uuid4().hex
        normalized_name = (device_name or "iPaper Electron").strip() or "iPaper Electron"
        token = jwt.encode(
            {
                "sub": user_id,
                "sid": device_id,
                "typ": SYNC_TOKEN_TYPE,
                "iat": int(now_dt.timestamp()),
            },
            self._jwt_secret,
            algorithm=JWT_ALGORITHM,
        )
        devices = self._load_sync_devices()
        devices.append({
            "device_id": device_id,
            "user_id": user_id,
            "device_name": normalized_name,
            "created_at": now,
            "last_used_at": None,
            "revoked_at": None,
        })
        self._save_sync_devices(devices)
        return {
            "device_id": device_id,
            "device_name": normalized_name,
            "created_at": now,
            "token": token,
        }

    def list_sync_devices(self, user_id: str) -> List[dict]:
        return [
            {
                "device_id": device["device_id"],
                "device_name": device.get("device_name", ""),
                "created_at": device.get("created_at"),
                "last_used_at": device.get("last_used_at"),
                "revoked_at": device.get("revoked_at"),
            }
            for device in self._load_sync_devices()
            if device.get("user_id") == user_id
        ]

    def revoke_sync_device(self, user_id: str, device_id: str) -> bool:
        devices = self._load_sync_devices()
        changed = False
        for device in devices:
            if device.get("user_id") == user_id and device.get("device_id") == device_id and not device.get("revoked_at"):
                device["revoked_at"] = datetime.utcnow().isoformat()
                changed = True
                break
        if changed:
            self._save_sync_devices(devices)
        return changed

    def get_user_by_sync_token(self, token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
        except JWTError:
            return None

        if payload.get("typ") != SYNC_TOKEN_TYPE:
            return None

        user_id = payload.get("sub")
        device_id = payload.get("sid")
        if not user_id or not device_id:
            return None

        devices = self._load_sync_devices()
        matched_device = None
        for device in devices:
            if device.get("user_id") == user_id and device.get("device_id") == device_id:
                matched_device = device
                break
        if not matched_device or matched_device.get("revoked_at"):
            return None

        matched_device["last_used_at"] = datetime.utcnow().isoformat()
        self._save_sync_devices(devices)
        return self.get_user_by_id(user_id)

    def get_current_user(self, token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
        except JWTError:
            return None

        if payload.get("typ") == SYNC_TOKEN_TYPE:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        for u in self._load_users():
            if u["id"] == user_id:
                return u
        return None


auth_service = AuthService()
