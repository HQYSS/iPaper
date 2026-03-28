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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:

    def __init__(self):
        self._users_file = settings.data_dir / "users.json"
        self._secret_file = settings.data_dir / "jwt_secret.key"

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

    def _find_user(self, username: str) -> Optional[dict]:
        for u in self._load_users():
            if u["username"] == username:
                return u
        return None

    def register(self, username: str, password: str) -> dict:
        if self._find_user(username):
            raise ValueError("用户名已存在")

        user = {
            "id": uuid.uuid4().hex[:16],
            "username": username,
            "password_hash": pwd_context.hash(password),
            "created_at": datetime.now().isoformat(),
        }
        users = self._load_users()
        users.append(user)
        self._save_users(users)
        logger.info("User registered: %s", username)
        return user

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

    def get_current_user(self, token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[JWT_ALGORITHM])
        except JWTError:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        for u in self._load_users():
            if u["id"] == user_id:
                return u
        return None


auth_service = AuthService()
