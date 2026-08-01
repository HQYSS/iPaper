"""
同步服务 — 生成 manifest、打包/解包论文 bundle、偏好/画像同步
"""
import asyncio
import io
import json
import zipfile
import logging
import shutil
import hashlib
import socket
import re
import os
import time
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

LOCAL_SYNC_USER_ID = "441e2fb8d4a64409"
LOCAL_SYNC_POLL_SECONDS = 1.0
LOCAL_PUSH_DEBOUNCE_SECONDS = 2.0
REMOTE_POLL_SECONDS = 300.0


class SyncManifestItem:
    __slots__ = (
        "arxiv_id",
        "updated_at",
        "paper_updated_at",
        "chats_updated_at",
        "pdf_available",
        "pdf_hash",
        "pdf_updated_at",
    )

    def __init__(
        self,
        arxiv_id: str,
        updated_at: str,
        paper_updated_at: Optional[str] = None,
        chats_updated_at: Optional[str] = None,
        pdf_available: bool = False,
        pdf_hash: Optional[str] = None,
        pdf_updated_at: Optional[str] = None,
    ):
        self.arxiv_id = arxiv_id
        self.updated_at = updated_at
        self.paper_updated_at = paper_updated_at or updated_at
        self.chats_updated_at = chats_updated_at
        self.pdf_available = pdf_available
        self.pdf_hash = pdf_hash
        self.pdf_updated_at = pdf_updated_at

    def to_dict(self) -> dict:
        return {
            "arxiv_id": self.arxiv_id,
            "updated_at": self.updated_at,
            "paper_updated_at": self.paper_updated_at,
            "chats_updated_at": self.chats_updated_at,
            "pdf_available": self.pdf_available,
            "pdf_hash": self.pdf_hash,
            "pdf_updated_at": self.pdf_updated_at,
        }


class SyncDeletedItem:
    __slots__ = ("arxiv_id", "deleted_at")

    def __init__(self, arxiv_id: str, deleted_at: str):
        self.arxiv_id = arxiv_id
        self.deleted_at = deleted_at

    def to_dict(self) -> dict:
        return {"arxiv_id": self.arxiv_id, "deleted_at": self.deleted_at}


class SyncManifest:
    __slots__ = (
        "papers",
        "deleted_papers",
        "preferences_updated_at",
        "profile_updated_at",
        "cross_paper_updated_at",
        "manifest_version",
        "device_id",
    )

    def __init__(
        self,
        papers: List[SyncManifestItem],
        deleted_papers: List[SyncDeletedItem],
        preferences_updated_at: Optional[str],
        profile_updated_at: Optional[str],
        cross_paper_updated_at: Optional[str] = None,
        manifest_version: int = 2,
        device_id: Optional[str] = None,
    ):
        self.papers = papers
        self.deleted_papers = deleted_papers
        self.preferences_updated_at = preferences_updated_at
        self.profile_updated_at = profile_updated_at
        self.cross_paper_updated_at = cross_paper_updated_at
        self.manifest_version = manifest_version
        self.device_id = device_id

    def to_dict(self) -> dict:
        return {
            "papers": [p.to_dict() for p in self.papers],
            "deleted_papers": [p.to_dict() for p in self.deleted_papers],
            "preferences_updated_at": self.preferences_updated_at,
            "profile_updated_at": self.profile_updated_at,
            "cross_paper_updated_at": self.cross_paper_updated_at,
            "manifest_version": self.manifest_version,
            "device_id": self.device_id,
        }


class SyncService:
    PAPER_ID_PATTERN = re.compile(r"^(?:\d{4}\.\d{4,5}|pdf_[0-9a-f]{16})$")
    CHAT_SESSION_PATTERN = re.compile(r"^s_[A-Za-z0-9_-]+$")
    CROSS_SESSION_PATTERN = re.compile(r"^cp_[A-Za-z0-9_-]+$")
    MAX_BUNDLE_MEMBERS = 10_000
    MAX_BUNDLE_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._debounced_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._priority_paper_ids = set()
        self._priority_chat_paper_ids = set()
        self._documents_dirty = False
        self._cross_paper_dirty = False
        self._last_remote_sync_at: float = time.monotonic()
        self._sync_lock = asyncio.Lock()
        self._last_local_fingerprint = ""
        self._last_remote_fingerprint = ""
        self._last_sync_at: Optional[str] = None
        self._last_sync_error: Optional[str] = None
        self._outbox_generation = 0
        self._entity_locks: Dict[str, asyncio.Lock] = {}

    @staticmethod
    def _client_role_required() -> bool:
        return settings.is_sync_client

    def _paper_dir(self, user_id: str, paper_id: str) -> Path:
        if not self.PAPER_ID_PATTERN.fullmatch(paper_id):
            raise ValueError("invalid paper_id")
        papers_dir = settings.get_user_papers_dir(user_id).resolve()
        paper_dir = (papers_dir / paper_id).resolve()
        if paper_dir.parent != papers_dir:
            raise ValueError("paper_id escapes papers directory")
        return paper_dir

    def _validated_zip_members(self, archive: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) > self.MAX_BUNDLE_MEMBERS:
            raise ValueError("bundle contains too many files")
        total_size = 0
        for member in members:
            path = Path(member.filename)
            if member.filename.startswith("/") or ".." in path.parts:
                raise ValueError("bundle contains unsafe path")
            total_size += member.file_size
            if total_size > self.MAX_BUNDLE_UNCOMPRESSED_BYTES:
                raise ValueError("bundle expands beyond size limit")
        return members

    @staticmethod
    def _install_directory_snapshot(temp_dir: Path, target_dir: Path) -> None:
        parent = target_dir.parent
        backups = sorted(
            parent.glob(f".{target_dir.name}-backup-*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not target_dir.exists() and backups:
            backups[0].rename(target_dir)
            backups = backups[1:]
        for stale in backups:
            shutil.rmtree(stale, ignore_errors=True)

        backup = parent / f".{target_dir.name}-backup-{uuid.uuid4().hex}"
        if target_dir.exists():
            target_dir.rename(backup)
        try:
            temp_dir.rename(target_dir)
        except Exception:
            if backup.exists() and not target_dir.exists():
                backup.rename(target_dir)
            raise
        shutil.rmtree(backup, ignore_errors=True)

    @staticmethod
    def _safe_session_path(base: Path, session_id: str, cross: bool = False) -> Path:
        pattern = (
            SyncService.CROSS_SESSION_PATTERN
            if cross
            else SyncService.CHAT_SESSION_PATTERN
        )
        if not pattern.fullmatch(session_id):
            raise ValueError("invalid session id")
        resolved_base = base.resolve()
        path = (resolved_base / f"{session_id}.json").resolve()
        if path.parent != resolved_base:
            raise ValueError("session path escapes chats directory")
        return path

    @staticmethod
    def _file_sha256(path: Path) -> Optional[str]:
        if not path.exists():
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _file_mtime(path: Path) -> Optional[str]:
        if not path.exists():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()

    @staticmethod
    def _device_id() -> str:
        raw = f"{socket.gethostname()}:{settings.data_dir.resolve()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _outbox_path() -> Path:
        return settings.data_dir / "sync_outbox.json"

    def _persist_outbox(self) -> None:
        if not self._client_role_required():
            return
        self._write_json_atomic(
            self._outbox_path(),
            {
                "paper_ids": sorted(self._priority_paper_ids),
                "chat_paper_ids": sorted(self._priority_chat_paper_ids),
                "documents_dirty": self._documents_dirty,
                "cross_paper_dirty": self._cross_paper_dirty,
                "generation": self._outbox_generation,
                "updated_at": datetime.now().isoformat(),
            },
        )

    def _load_outbox(self) -> None:
        path = self._outbox_path()
        if not path.exists():
            return
        try:
            data = self._read_json(path)
            self._priority_paper_ids.update(data.get("paper_ids", []))
            self._priority_chat_paper_ids.update(data.get("chat_paper_ids", []))
            self._documents_dirty = bool(data.get("documents_dirty"))
            self._cross_paper_dirty = bool(data.get("cross_paper_dirty"))
            self._outbox_generation = int(data.get("generation", 0))
        except Exception:
            logger.exception("Failed to load sync outbox")

    def is_operation_applied(self, user_id: str, operation_id: Optional[str]) -> bool:
        return self.get_operation_record(user_id, operation_id) is not None

    def get_operation_record(
        self,
        user_id: str,
        operation_id: Optional[str],
    ) -> Optional[dict]:
        if not operation_id:
            return None
        digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        path = (
            settings.get_user_data_dir(user_id)
            / "sync"
            / "idempotency"
            / f"{digest}.json"
        )
        return self._read_json(path) if path.exists() else None

    def entity_lock(self, user_id: str, entity: str) -> asyncio.Lock:
        key = f"{user_id}:{entity}"
        lock = self._entity_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._entity_locks[key] = lock
        return lock

    def mark_operation_applied(
        self,
        user_id: str,
        operation_id: Optional[str],
        payload_digest: Optional[str] = None,
    ) -> None:
        if not operation_id:
            return
        digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        path = (
            settings.get_user_data_dir(user_id)
            / "sync"
            / "idempotency"
            / f"{digest}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(
            path,
            {
                "operation_id": operation_id,
                "payload_digest": payload_digest,
                "applied_at": datetime.now().isoformat(),
            },
        )
        self._gc_idempotency(path.parent)

    @staticmethod
    def _gc_idempotency(directory: Path) -> None:
        files = list(directory.glob("*.json"))
        if len(files) <= 1000:
            return
        cutoff = time.time() - 7 * 24 * 60 * 60
        for path in files:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    def get_manifest(self, user_id: str) -> SyncManifest:
        papers_dir = settings.get_user_papers_dir(user_id)
        items: List[SyncManifestItem] = []
        deleted_items: List[SyncDeletedItem] = []

        if papers_dir.exists():
            for paper_dir in sorted(papers_dir.iterdir()):
                if not paper_dir.is_dir():
                    continue
                meta_file = paper_dir / "meta.json"
                if not meta_file.exists():
                    continue
                # 元信息先同步，PDF 由各端按来源异步获取或走独立 asset 端点。
                if not self._paper_ready_for_sync(paper_dir, meta_file):
                    continue
                paper_updated_at = self._get_paper_content_updated_at(paper_dir)
                chats_updated_at = self._get_paper_chats_updated_at(paper_dir)
                updated_at = self._max_timestamp(paper_updated_at, chats_updated_at)
                items.append(SyncManifestItem(
                    arxiv_id=paper_dir.name,
                    updated_at=updated_at,
                    paper_updated_at=paper_updated_at,
                    chats_updated_at=chats_updated_at,
                    pdf_available=(paper_dir / "paper.pdf").exists(),
                    pdf_hash=self._file_sha256(paper_dir / "paper.pdf"),
                    pdf_updated_at=self._file_mtime(paper_dir / "paper.pdf"),
                ))

        active_deletions = self._get_active_paper_tombstones(user_id)
        for arxiv_id, deleted_at in sorted(active_deletions.items()):
            deleted_items.append(SyncDeletedItem(arxiv_id=arxiv_id, deleted_at=deleted_at))

        pref_updated = self._get_file_updated_at(
            settings.get_user_data_dir(user_id) / "preferences.json"
        )
        profile_updated = self.get_profile_updated_at(user_id)
        cross_paper_updated = self._get_directory_updated_at(
            settings.get_user_cross_paper_dir(user_id)
        )

        return SyncManifest(
            papers=items,
            deleted_papers=deleted_items,
            preferences_updated_at=pref_updated,
            profile_updated_at=profile_updated,
            cross_paper_updated_at=cross_paper_updated,
            manifest_version=2,
            device_id=self._device_id(),
        )

    # ==================== Paper bundle ====================

    @staticmethod
    def _paper_ready_for_sync(paper_dir: Path, meta_file: Path) -> bool:
        """判断论文元信息是否可进入 manifest。PDF 不再是前置条件。"""
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                json.load(f)
        except Exception:
            return False
        return True

    def create_paper_metadata_bundle(self, user_id: str, paper_id: str) -> Optional[bytes]:
        paper_dir = self._paper_dir(user_id, paper_id)
        if not paper_dir.exists():
            return None
        meta_file = paper_dir / "meta.json"
        if not meta_file.exists() or not self._paper_ready_for_sync(paper_dir, meta_file):
            return None

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in paper_dir.rglob("*"):
                if file_path.is_file():
                    relative_path = file_path.relative_to(paper_dir)
                    if (
                        "chats" in relative_path.parts
                        or file_path.suffix.lower() == ".pdf"
                        or file_path.name.endswith(".part")
                    ):
                        continue
                    arcname = str(relative_path)
                    zf.write(file_path, arcname)
        return buf.getvalue()

    def create_paper_bundle(self, user_id: str, paper_id: str) -> Optional[bytes]:
        """Legacy v1 bundle: metadata + PDF assets, but never chats."""
        paper_dir = self._paper_dir(user_id, paper_id)
        if not paper_dir.exists() or not (paper_dir / "meta.json").exists():
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in paper_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                relative_path = file_path.relative_to(paper_dir)
                if "chats" in relative_path.parts or file_path.name.endswith(".part"):
                    continue
                zf.write(file_path, str(relative_path))
        return buf.getvalue()

    def extract_paper_bundle(self, user_id: str, paper_id: str, bundle_bytes: bytes) -> bool:
        paper_dir = self._paper_dir(user_id, paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = paper_dir.parent / f".paper-sync-{paper_id}-{uuid.uuid4().hex}"
        buf = io.BytesIO(bundle_bytes)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                temp_dir.mkdir(parents=True, exist_ok=False)
                for member_info in self._validated_zip_members(zf):
                    member = member_info.filename
                    if "chats" in Path(member).parts:
                        continue
                    target = temp_dir / member
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except (zipfile.BadZipFile, ValueError):
            logger.error("Invalid zip bundle for paper %s", paper_id)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        except Exception:
            logger.exception("Failed to stage paper bundle %s", paper_id)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        try:
            for source in temp_dir.rglob("*"):
                if not source.is_file():
                    continue
                target = paper_dir / source.relative_to(temp_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)
        except Exception:
            logger.exception("Failed to install paper bundle %s", paper_id)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        shutil.rmtree(temp_dir, ignore_errors=True)

        self.clear_paper_tombstone(user_id, paper_id)
        self._rebuild_papers_index(user_id)
        try:
            from services.arxiv_service import arxiv_service
            arxiv_service.ensure_pdf_for_synced_metadata(user_id, paper_id)
        except Exception:
            logger.exception("Failed to schedule PDF acquisition for synced paper %s", paper_id)
        return True

    def create_pdf_asset(self, user_id: str, paper_id: str) -> Optional[bytes]:
        pdf_path = self._paper_dir(user_id, paper_id) / "paper.pdf"
        if not pdf_path.exists():
            return None
        return pdf_path.read_bytes()

    def extract_pdf_asset(self, user_id: str, paper_id: str, content: bytes) -> bool:
        if b"%PDF" not in content[:1024]:
            return False
        paper_dir = self._paper_dir(user_id, paper_id)
        paper_dir.mkdir(parents=True, exist_ok=True)
        temp_path = paper_dir / "paper.pdf.sync"
        temp_path.write_bytes(content)
        final_path = paper_dir / "paper.pdf"
        temp_path.replace(final_path)
        meta_file = paper_dir / "meta.json"
        if meta_file.exists():
            meta = self._read_json(meta_file)
            meta["download_status"] = "ready"
            meta["download_error"] = None
            self._write_json(meta_file, meta)
        self._rebuild_papers_index(user_id)
        return True

    def create_paper_chats_bundle(self, user_id: str, paper_id: str) -> Optional[bytes]:
        chats_dir = self._paper_dir(user_id, paper_id) / "chats"
        if not chats_dir.exists():
            return None

        files = [path for path in chats_dir.rglob("*") if path.is_file()]
        if not files:
            return None

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in files:
                arcname = str(file_path.relative_to(chats_dir))
                zf.write(file_path, arcname)
        return buf.getvalue()

    def extract_paper_chats_bundle(self, user_id: str, paper_id: str, bundle_bytes: bytes) -> bool:
        paper_dir = self._paper_dir(user_id, paper_id)
        chats_dir = paper_dir / "chats"
        temp_dir = paper_dir / f".chats-sync-{uuid.uuid4().hex}"
        buf = io.BytesIO(bundle_bytes)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                members = [
                    member.filename
                    for member in self._validated_zip_members(zf)
                ]
                temp_dir.mkdir(parents=True, exist_ok=False)
                for member in members:
                    target = temp_dir / member
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except (zipfile.BadZipFile, ValueError):
            logger.error("Invalid chats zip bundle for paper %s", paper_id)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        except Exception:
            logger.exception("Failed to extract chats bundle for paper %s", paper_id)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        self._install_directory_snapshot(temp_dir, chats_dir)
        return True

    def merge_paper_chats_bundle(self, user_id: str, paper_id: str, bundle_bytes: bytes) -> bool:
        """Merge remote sessions into local state before a CAS-protected push."""
        chats_dir = self._paper_dir(user_id, paper_id) / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
                remote_files = {
                    member.filename: json.loads(
                        zf.read(member.filename).decode("utf-8")
                    )
                    for member in self._validated_zip_members(zf)
                    if member.filename.endswith(".json")
                }
        except (
            zipfile.BadZipFile,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            logger.exception("Invalid remote chats bundle for merge paper=%s", paper_id)
            return False

        local_index_path = chats_dir / "sessions.json"
        local_index = (
            self._read_json(local_index_path)
            if local_index_path.exists()
            else {"sessions": [], "last_active_session_id": None}
        )
        remote_index = remote_files.pop(
            "sessions.json",
            {"sessions": [], "last_active_session_id": None},
        )
        tombstones = {
            session_id: deleted_at
            for session_id, deleted_at in local_index.get("deleted_sessions", {}).items()
            if self.CHAT_SESSION_PATTERN.fullmatch(session_id)
        }
        for session_id, deleted_at in remote_index.get("deleted_sessions", {}).items():
            if not self.CHAT_SESSION_PATTERN.fullmatch(session_id):
                continue
            if self._compare_timestamps(deleted_at, tombstones.get(session_id)) > 0:
                tombstones[session_id] = deleted_at

        merged_sessions = {
            session["id"]: session
            for session in local_index.get("sessions", [])
            if self.CHAT_SESSION_PATTERN.fullmatch(session.get("id", ""))
        }
        for session in remote_index.get("sessions", []):
            session_id = session.get("id")
            if not self.CHAT_SESSION_PATTERN.fullmatch(session_id or ""):
                continue
            current = merged_sessions.get(session_id)
            if not current or self._compare_timestamps(
                session.get("updated_at"),
                current.get("updated_at"),
            ) > 0:
                merged_sessions[session_id] = session

        for session_id, deleted_at in tombstones.items():
            current = merged_sessions.get(session_id)
            if current and self._compare_timestamps(
                deleted_at,
                current.get("updated_at"),
            ) >= 0:
                merged_sessions.pop(session_id, None)
                self._safe_session_path(chats_dir, session_id).unlink(missing_ok=True)

        for filename, remote_data in remote_files.items():
            session_id = Path(filename).stem
            if not self.CHAT_SESSION_PATTERN.fullmatch(session_id):
                continue
            if session_id in tombstones and self._compare_timestamps(
                tombstones[session_id],
                remote_data.get("updated_at"),
            ) >= 0:
                continue
            local_path = self._safe_session_path(chats_dir, session_id)
            local_data = self._read_json(local_path) if local_path.exists() else {}
            if self._compare_timestamps(
                remote_data.get("updated_at"),
                local_data.get("updated_at"),
            ) > 0:
                self._write_json(local_path, remote_data)

        local_index["sessions"] = sorted(
            merged_sessions.values(),
            key=lambda session: session.get("created_at", ""),
        )
        local_index["deleted_sessions"] = tombstones
        local_index["updated_at"] = self._max_timestamp(
            local_index.get("updated_at"),
            remote_index.get("updated_at"),
        )
        self._write_json(local_index_path, local_index)
        return True

    # ==================== Cross-paper bundle ====================

    def create_cross_paper_bundle(self, user_id: str) -> Optional[bytes]:
        cross_dir = settings.get_user_cross_paper_dir(user_id)
        if not cross_dir.exists():
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in cross_dir.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, str(file_path.relative_to(cross_dir)))
        return buf.getvalue()

    def extract_cross_paper_bundle(self, user_id: str, bundle_bytes: bytes) -> bool:
        cross_dir = settings.get_user_cross_paper_dir(user_id)
        parent_dir = cross_dir.parent
        temp_dir = parent_dir / f".cross-paper-sync-{uuid.uuid4().hex}"
        try:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
                members = [
                    member.filename
                    for member in self._validated_zip_members(zf)
                ]
                temp_dir.mkdir(parents=True, exist_ok=False)
                for member in members:
                    target = temp_dir / member
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except (zipfile.BadZipFile, ValueError):
            logger.error("Invalid cross-paper zip bundle")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        except Exception:
            logger.exception("Failed to extract cross-paper bundle")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False
        self._install_directory_snapshot(temp_dir, cross_dir)
        return True

    def merge_cross_paper_bundle(self, user_id: str, bundle_bytes: bytes) -> bool:
        cross_dir = settings.get_user_cross_paper_dir(user_id)
        try:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
                remote_files = {
                    member.filename: json.loads(
                        zf.read(member.filename).decode("utf-8")
                    )
                    for member in self._validated_zip_members(zf)
                    if member.filename.endswith(".json")
                }
        except (
            zipfile.BadZipFile,
            ValueError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ):
            logger.exception("Invalid remote cross-paper bundle for merge")
            return False

        index_path = cross_dir / "sessions.json"
        local_index = (
            self._read_json(index_path)
            if index_path.exists()
            else {"sessions": [], "last_active_session_id": None}
        )
        remote_index = remote_files.pop(
            "sessions.json",
            {"sessions": [], "last_active_session_id": None},
        )
        tombstones = {
            session_id: deleted_at
            for session_id, deleted_at in local_index.get("deleted_sessions", {}).items()
            if self.CROSS_SESSION_PATTERN.fullmatch(session_id)
        }
        for session_id, deleted_at in remote_index.get("deleted_sessions", {}).items():
            if not self.CROSS_SESSION_PATTERN.fullmatch(session_id):
                continue
            if self._compare_timestamps(deleted_at, tombstones.get(session_id)) > 0:
                tombstones[session_id] = deleted_at

        sessions = {
            session["id"]: session
            for session in local_index.get("sessions", [])
            if self.CROSS_SESSION_PATTERN.fullmatch(session.get("id", ""))
        }
        for session in remote_index.get("sessions", []):
            session_id = session.get("id")
            if not self.CROSS_SESSION_PATTERN.fullmatch(session_id or ""):
                continue
            current = sessions.get(session_id)
            if session_id and (
                not current
                or self._compare_timestamps(
                    session.get("updated_at"),
                    current.get("updated_at"),
                ) > 0
            ):
                sessions[session_id] = session
        chats_dir = cross_dir / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)
        for session_id, deleted_at in tombstones.items():
            current = sessions.get(session_id)
            if current and self._compare_timestamps(
                deleted_at,
                current.get("updated_at"),
            ) >= 0:
                sessions.pop(session_id, None)
                self._safe_session_path(
                    chats_dir,
                    session_id,
                    cross=True,
                ).unlink(missing_ok=True)

        for filename, remote_data in remote_files.items():
            session_id = Path(filename).stem
            if not self.CROSS_SESSION_PATTERN.fullmatch(session_id):
                continue
            if session_id in tombstones and self._compare_timestamps(
                tombstones[session_id],
                remote_data.get("updated_at"),
            ) >= 0:
                continue
            local_path = self._safe_session_path(
                chats_dir,
                session_id,
                cross=True,
            )
            local_data = self._read_json(local_path) if local_path.exists() else {}
            if self._compare_timestamps(
                remote_data.get("updated_at"),
                local_data.get("updated_at"),
            ) > 0:
                self._write_json(local_path, remote_data)

        local_index["sessions"] = sorted(
            sessions.values(),
            key=lambda session: session.get("created_at", ""),
        )
        local_index["deleted_sessions"] = tombstones
        local_index["updated_at"] = self._max_timestamp(
            local_index.get("updated_at"),
            remote_index.get("updated_at"),
        )
        self._write_json(index_path, local_index)
        return True

    def delete_paper(self, user_id: str, paper_id: str, deleted_at: Optional[str] = None) -> bool:
        # 先取消可能还在跑的后台下载，避免它回写 meta.json
        try:
            from services.arxiv_service import arxiv_service
            arxiv_service.cancel_download(user_id, paper_id)
        except Exception:
            logger.exception("cancel_download failed for %s:%s", user_id, paper_id)

        paper_dir = self._paper_dir(user_id, paper_id)
        existed = paper_dir.exists()
        if existed:
            import shutil
            shutil.rmtree(paper_dir)
        self._record_paper_tombstone(user_id, paper_id, deleted_at)
        self._rebuild_papers_index(user_id)
        return existed

    def clear_paper_tombstone(self, user_id: str, paper_id: str) -> None:
        tombstones = self._read_deleted_papers(user_id)
        if paper_id in tombstones:
            tombstones.pop(paper_id, None)
            self._write_deleted_papers(user_id, tombstones)

    # ==================== Preferences ====================

    def get_preferences(self, user_id: str) -> Optional[dict]:
        pref_file = settings.get_user_data_dir(user_id) / "preferences.json"
        if not pref_file.exists():
            return None
        return self._read_json(pref_file)

    def put_preferences(self, user_id: str, data: dict) -> None:
        pref_file = settings.get_user_data_dir(user_id) / "preferences.json"
        pref_file.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["updated_at"] = data.get("updated_at") or datetime.now().isoformat()
        self._write_json(pref_file, payload)

    # ==================== Profile ====================

    def get_profile(self, user_id: str) -> Optional[str]:
        profile_file = settings.get_user_profile_dir(user_id) / "profile.md"
        if not profile_file.exists():
            return None
        return profile_file.read_text(encoding="utf-8")

    def put_profile(self, user_id: str, content: str, updated_at: Optional[str] = None) -> None:
        profile_dir = settings.get_user_profile_dir(user_id)
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "profile.md").write_text(content, encoding="utf-8")
        self._write_json(
            profile_dir / "profile.meta.json",
            {"updated_at": updated_at or datetime.now().isoformat()},
        )

    def get_profile_updated_at(self, user_id: str) -> Optional[str]:
        profile_dir = settings.get_user_profile_dir(user_id)
        meta_file = profile_dir / "profile.meta.json"
        if meta_file.exists():
            return self._read_json(meta_file).get("updated_at")
        return self._get_file_updated_at(profile_dir / "profile.md")

    # ==================== Internal helpers ====================

    def _deleted_papers_file(self, user_id: str) -> Path:
        return settings.get_user_data_dir(user_id) / "deleted_papers.json"

    def _read_deleted_papers(self, user_id: str) -> dict:
        path = self._deleted_papers_file(user_id)
        if not path.exists():
            return {}
        return self._read_json(path)

    def _write_deleted_papers(self, user_id: str, tombstones: dict) -> None:
        path = self._deleted_papers_file(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(path, tombstones)

    def _record_paper_tombstone(self, user_id: str, paper_id: str, deleted_at: Optional[str] = None) -> None:
        tombstones = self._read_deleted_papers(user_id)
        tombstones[paper_id] = deleted_at or datetime.now().isoformat()
        self._write_deleted_papers(user_id, tombstones)

    def _get_active_paper_tombstones(self, user_id: str) -> dict:
        tombstones = self._read_deleted_papers(user_id)
        papers_dir = settings.get_user_papers_dir(user_id)
        active = {}
        for arxiv_id, deleted_at in tombstones.items():
            meta_file = papers_dir / arxiv_id / "meta.json"
            paper_updated_at = ""
            if meta_file.exists():
                meta = self._read_json(meta_file)
                paper_updated_at = meta.get("updated_at") or meta.get("download_time", "")
            if self._compare_timestamps(deleted_at, paper_updated_at) > 0:
                active[arxiv_id] = deleted_at
        return active

    @staticmethod
    def _compare_timestamps(left: Optional[str], right: Optional[str]) -> int:
        left_dt = datetime.fromisoformat(left) if left else datetime.min
        right_dt = datetime.fromisoformat(right) if right else datetime.min
        if left_dt > right_dt:
            return 1
        if left_dt < right_dt:
            return -1
        return 0

    def _max_timestamp(self, *values: Optional[str]) -> str:
        latest = datetime.min
        for value in values:
            if not value:
                continue
            candidate = datetime.fromisoformat(value)
            if candidate > latest:
                latest = candidate
        if latest == datetime.min:
            return datetime.min.isoformat()
        return latest.isoformat()

    def _paper_fingerprint(self, manifest: SyncManifest) -> str:
        return json.dumps(
            {
                "papers": sorted(
                    (item.to_dict() for item in manifest.papers),
                    key=lambda item: item["arxiv_id"],
                ),
                "deleted_papers": sorted(
                    (item.to_dict() for item in manifest.deleted_papers),
                    key=lambda item: item["arxiv_id"],
                ),
                "preferences_updated_at": manifest.preferences_updated_at,
                "profile_updated_at": manifest.profile_updated_at,
                "cross_paper_updated_at": manifest.cross_paper_updated_at,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _get_paper_content_updated_at(self, paper_dir: Path) -> str:
        latest = datetime.min
        for file_path in paper_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if "chats" in file_path.relative_to(paper_dir).parts:
                continue
            if file_path.suffix.lower() == ".pdf" or file_path.name.endswith(".part"):
                continue
            data = {}
            if file_path.suffix == ".json":
                try:
                    data = self._read_json(file_path)
                except Exception:
                    data = {}
            candidate = data.get("updated_at") or data.get("download_time")
            if candidate:
                candidate_dt = datetime.fromisoformat(candidate)
            else:
                candidate_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
            if candidate_dt > latest:
                latest = candidate_dt
        if latest == datetime.min:
            meta_file = paper_dir / "meta.json"
            if meta_file.exists():
                meta = self._read_json(meta_file)
                fallback = meta.get("updated_at") or meta.get("download_time")
                if fallback:
                    latest = datetime.fromisoformat(fallback)
                else:
                    latest = datetime.fromtimestamp(meta_file.stat().st_mtime)
            else:
                latest = datetime.fromtimestamp(paper_dir.stat().st_mtime)
        return latest.isoformat()

    def _get_paper_chats_updated_at(self, paper_dir: Path) -> Optional[str]:
        chats_dir = paper_dir / "chats"
        if not chats_dir.exists():
            return None

        latest = datetime.min
        for file_path in chats_dir.rglob("*"):
            if not file_path.is_file() or file_path.suffix != ".json":
                continue
            try:
                data = self._read_json(file_path)
            except Exception:
                data = {}
            candidates = []
            if data.get("updated_at"):
                candidates.append(data.get("updated_at"))
            for session in data.get("sessions", []) or []:
                if isinstance(session, dict) and session.get("updated_at"):
                    candidates.append(session.get("updated_at"))
            if candidates:
                candidate_dt = max(datetime.fromisoformat(value) for value in candidates)
            else:
                candidate_dt = datetime.fromtimestamp(file_path.stat().st_mtime)
            if candidate_dt > latest:
                latest = candidate_dt
        return latest.isoformat() if latest != datetime.min else None

    def _rebuild_papers_index(self, user_id: str) -> None:
        papers_dir = settings.get_user_papers_dir(user_id)
        index_file = papers_dir / "index.json"
        existing_order = []
        if index_file.exists():
            existing_order = self._read_json(index_file).get("papers", [])

        current_papers = {}
        for paper_dir in papers_dir.iterdir():
            if not paper_dir.is_dir():
                continue
            meta_file = paper_dir / "meta.json"
            if not meta_file.exists():
                continue
            meta = self._read_json(meta_file)
            arxiv_id = meta.get("arxiv_id", paper_dir.name)
            current_papers[arxiv_id] = {
                "arxiv_id": arxiv_id,
                "title": meta.get("title", ""),
                "download_time": meta.get("download_time", ""),
            }

        papers = []
        seen = set()

        # Preserve the original index order so sync/import does not reshuffle the library.
        for item in existing_order:
            arxiv_id = item.get("arxiv_id")
            if not arxiv_id or arxiv_id not in current_papers:
                continue
            papers.append(current_papers[arxiv_id])
            seen.add(arxiv_id)

        # Append newly discovered papers after the existing list.
        for paper_dir in sorted(papers_dir.iterdir()):
            if not paper_dir.is_dir():
                continue
            meta_file = paper_dir / "meta.json"
            if not meta_file.exists():
                continue
            meta = self._read_json(meta_file)
            arxiv_id = meta.get("arxiv_id", paper_dir.name)
            if arxiv_id in seen:
                continue
            papers.append(current_papers[arxiv_id])
            seen.add(arxiv_id)

        self._write_json(index_file, {"papers": papers})

    def request_sync(
        self,
        reason: str = "local-change",
        paper_id: Optional[str] = None,
        scope: str = "paper",
    ) -> None:
        if not self._client_role_required():
            return
        if paper_id:
            if scope == "chats":
                self._priority_chat_paper_ids.add(paper_id)
            else:
                self._priority_paper_ids.add(paper_id)
        elif scope == "cross_paper":
            self._cross_paper_dirty = True
        else:
            self._documents_dirty = True
        self._outbox_generation += 1
        self._persist_outbox()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._debounced_task and not self._debounced_task.done() and not self.is_syncing():
            self._debounced_task.cancel()
        if not self._debounced_task or self._debounced_task.done() or self.is_syncing():
            self._debounced_task = loop.create_task(self._debounced_sync(reason))
        self._wake_event.set()
        logger.warning("Scheduled local sync: %s paper=%s scope=%s", reason, paper_id, scope)

    def is_syncing(self) -> bool:
        return self._sync_lock.locked()

    def get_status(self) -> dict:
        return {
            "syncing": self.is_syncing(),
            "last_sync_at": self._last_sync_at,
            "last_error": self._last_sync_error,
            "pending": {
                "papers": len(self._priority_paper_ids),
                "chats": len(self._priority_chat_paper_ids),
                "documents": int(self._documents_dirty),
                "cross_paper": int(self._cross_paper_dirty),
            },
        }

    async def announce_paper_metadata(self, user_id: str, paper_id: str) -> bool:
        """Push a tiny metadata bundle immediately so cloud acquisition can start."""
        if not self._client_role_required():
            return False
        sync_token = settings.sync_token.strip()
        sync_base = self._normalize_sync_base()
        bundle = self.create_paper_metadata_bundle(user_id, paper_id)
        if not sync_token or not sync_base or bundle is None:
            return False
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=30.0),
                verify=settings.sync_verify_ssl,
            ) as client:
                auth_headers = {"Authorization": f"Bearer {sync_token}"}
                manifest_response = await client.get(
                    f"{sync_base}/manifest",
                    headers={**auth_headers, "X-Sync-Protocol": "2"},
                )
                manifest_response.raise_for_status()
                remote_paper = next(
                    (
                        item
                        for item in manifest_response.json().get("papers", [])
                        if item.get("arxiv_id") == paper_id
                    ),
                    {},
                )
                local_paper = next(
                    (
                        item.to_dict()
                        for item in self.get_manifest(user_id).papers
                        if item.arxiv_id == paper_id
                    ),
                    {},
                )
                local_updated = local_paper.get("paper_updated_at")
                remote_updated = remote_paper.get("paper_updated_at")
                if self._compare_timestamps(local_updated, remote_updated) <= 0:
                    return True
                response = await client.put(
                    f"{sync_base}/papers/{paper_id}/metadata/bundle",
                    headers=self._write_headers(
                        sync_token,
                        f"paper:{paper_id}",
                        local_updated,
                        remote_updated,
                    ),
                    files={"file": (f"{paper_id}-metadata.zip", bundle, "application/zip")},
                )
                response.raise_for_status()
            logger.info(
                "announced paper metadata paper=%s bytes=%d",
                paper_id,
                len(bundle),
            )
            return True
        except Exception:
            logger.exception("paper metadata announcement failed paper=%s", paper_id)
            return False

    async def sync_now(
        self,
        reason: str = "manual",
        paper_id: Optional[str] = None,
        wait_if_busy: bool = True,
        scope: str = "paper",
    ) -> None:
        if not self._client_role_required():
            return
        if self.is_syncing() and not wait_if_busy:
            logger.info("skip immediate sync because another sync is running reason=%s paper=%s", reason, paper_id)
            return
        if paper_id:
            if scope == "chats":
                self._priority_chat_paper_ids.add(paper_id)
            else:
                self._priority_paper_ids.add(paper_id)
        elif scope == "cross_paper":
            self._cross_paper_dirty = True
        elif scope == "paper":
            self._documents_dirty = True
        self._outbox_generation += 1
        self._persist_outbox()
        await self._sync_once(
            LOCAL_SYNC_USER_ID,
            reason,
            target_paper_ids={paper_id} if paper_id and scope != "chats" else set() if scope == "chats" else None,
            target_chat_paper_ids={paper_id} if paper_id and scope == "chats" else set(),
            sync_documents=paper_id is None and scope != "cross_paper",
            sync_cross_paper=scope == "cross_paper" or (paper_id is None and scope == "paper"),
        )

    async def startup(self) -> None:
        if not self._client_role_required():
            return
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._load_outbox()
        self._task = asyncio.create_task(self._background_loop())
        if (
            self._priority_paper_ids
            or self._priority_chat_paper_ids
            or self._documents_dirty
            or self._cross_paper_dirty
        ):
            self._wake_event.set()
        logger.info("Local background sync worker started")

    async def shutdown(self) -> None:
        if not self._client_role_required():
            return
        if self._debounced_task and not self._debounced_task.done():
            self._debounced_task.cancel()
        if not self._task:
            return
        self._stop_event.set()
        self._wake_event.set()
        await self._task
        self._task = None
        logger.info("Local background sync worker stopped")

    async def _background_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            should_sync = now - self._last_remote_sync_at >= REMOTE_POLL_SECONDS

            if should_sync:
                try:
                    await self._sync_once(LOCAL_SYNC_USER_ID, "remote-poll")
                except Exception:
                    self._last_sync_error = "remote-poll failed"
                    logger.exception("Background sync failed: remote-poll")
                self._last_remote_sync_at = time.monotonic()
                continue

            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=LOCAL_SYNC_POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            self._wake_event.clear()

    async def _debounced_sync(self, reason: str) -> None:
        try:
            await asyncio.sleep(LOCAL_PUSH_DEBOUNCE_SECONDS)
            logger.warning("Running debounced local sync: %s", reason)
            target_paper_ids = set(self._priority_paper_ids)
            target_chat_paper_ids = set(self._priority_chat_paper_ids)
            sync_documents = self._documents_dirty
            sync_cross_paper = self._cross_paper_dirty
            if (
                not target_paper_ids
                and not target_chat_paper_ids
                and not sync_documents
                and not sync_cross_paper
            ):
                return
            await self._sync_once(
                LOCAL_SYNC_USER_ID,
                reason,
                target_paper_ids=target_paper_ids,
                target_chat_paper_ids=target_chat_paper_ids,
                sync_documents=sync_documents,
                sync_cross_paper=sync_cross_paper,
            )
        except asyncio.CancelledError:
            logger.warning("Cancelled debounced local sync: %s", reason)
            return
        except Exception:
            self._last_sync_error = f"{reason} failed"
            logger.exception("Debounced local sync failed: %s", reason)

    def _normalize_sync_base(self) -> str:
        sync_url = (settings.sync_url or "").rstrip("/")
        if not sync_url:
            return ""
        if sync_url.endswith("/sync"):
            return sync_url
        if sync_url.endswith("/api"):
            return f"{sync_url}/sync"
        return f"{sync_url}/api/sync"

    def _write_headers(
        self,
        sync_token: str,
        entity: str,
        revision: Optional[str],
        base_revision: Optional[str] = None,
        include_base: bool = True,
    ) -> dict:
        normalized_revision = revision or "__none__"
        operation_id = f"{self._device_id()}:{entity}:{normalized_revision}"
        headers = {
            "Authorization": f"Bearer {sync_token}",
            "Idempotency-Key": operation_id,
        }
        if include_base:
            headers["X-Base-Revision"] = base_revision or "__none__"
        return headers

    async def _sync_once(
        self,
        user_id: str,
        reason: str,
        target_paper_ids: Optional[set[str]] = None,
        target_chat_paper_ids: Optional[set[str]] = None,
        sync_documents: bool = True,
        sync_cross_paper: bool = True,
    ) -> None:
        if not self._client_role_required():
            return
        sync_token = settings.sync_token.strip()
        sync_base = self._normalize_sync_base()
        if not sync_token or not sync_base:
            return

        async with self._sync_lock:
            synced_generation = self._outbox_generation
            sync_run_id = uuid.uuid4().hex[:10]
            started = time.monotonic()
            logger.info("sync started run=%s reason=%s user=%s", sync_run_id, reason, user_id)
            local_manifest = self.get_manifest(user_id)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=60.0),
                verify=settings.sync_verify_ssl,
            ) as client:
                remote_manifest_resp = await client.get(
                    f"{sync_base}/manifest",
                    headers={
                        "Authorization": f"Bearer {sync_token}",
                        "X-Sync-Protocol": "2",
                    },
                )
                remote_manifest_resp.raise_for_status()
                remote_manifest = remote_manifest_resp.json()
                if remote_manifest.get("manifest_version") != 2:
                    raise RuntimeError("云端同步协议版本过旧，请先升级云端后端")

                await self._sync_papers(
                    client,
                    sync_base,
                    sync_token,
                    user_id,
                    local_manifest.to_dict(),
                    remote_manifest,
                    sync_run_id,
                    target_paper_ids=target_paper_ids,
                )
                await self._sync_chats(
                    client,
                    sync_base,
                    sync_token,
                    user_id,
                    local_manifest.to_dict(),
                    remote_manifest,
                    sync_run_id,
                    target_paper_ids=target_chat_paper_ids,
                )
                if sync_cross_paper:
                    await self._sync_cross_paper(
                        client,
                        sync_base,
                        sync_token,
                        user_id,
                        local_manifest.cross_paper_updated_at,
                        remote_manifest.get("cross_paper_updated_at"),
                        sync_run_id,
                    )
                if sync_documents:
                    await self._sync_document(
                        client,
                        "preferences",
                        local_manifest.preferences_updated_at,
                        remote_manifest.get("preferences_updated_at"),
                        lambda: self.get_preferences(user_id) or {},
                        lambda data: self.put_preferences(user_id, data),
                        f"{sync_base}/preferences",
                        sync_token,
                        sync_run_id,
                    )
                    await self._sync_document(
                        client,
                        "profile",
                        local_manifest.profile_updated_at,
                        remote_manifest.get("profile_updated_at"),
                        lambda: {"content": self.get_profile(user_id) or "", "updated_at": self.get_profile_updated_at(user_id)},
                        lambda data: self.put_profile(user_id, data.get("content", ""), data.get("updated_at")),
                        f"{sync_base}/profile",
                        sync_token,
                        sync_run_id,
                    )

            final_local_manifest = self.get_manifest(user_id)
            self._last_local_fingerprint = self._paper_fingerprint(final_local_manifest)
            self._last_remote_fingerprint = json.dumps(remote_manifest, ensure_ascii=False, sort_keys=True)
            logger.info(
                "sync completed run=%s reason=%s duration_ms=%d",
                sync_run_id,
                reason,
                int((time.monotonic() - started) * 1000),
            )
            if self._outbox_generation == synced_generation:
                if target_paper_ids is None:
                    self._priority_paper_ids.clear()
                else:
                    self._priority_paper_ids.difference_update(target_paper_ids)
                if target_chat_paper_ids is None:
                    self._priority_chat_paper_ids.clear()
                else:
                    self._priority_chat_paper_ids.difference_update(target_chat_paper_ids)
                if sync_documents:
                    self._documents_dirty = False
                if sync_cross_paper:
                    self._cross_paper_dirty = False
            else:
                logger.info(
                    "sync outbox changed during run=%s; retaining pending entries",
                    sync_run_id,
                )
            self._persist_outbox()
            self._last_sync_at = datetime.now().isoformat()
            self._last_sync_error = None

    async def _sync_cross_paper(
        self,
        client: httpx.AsyncClient,
        sync_base: str,
        sync_token: str,
        user_id: str,
        local_updated: Optional[str],
        remote_updated: Optional[str],
        sync_run_id: str,
    ) -> None:
        url = f"{sync_base}/cross-paper/bundle"
        headers = {"Authorization": f"Bearer {sync_token}"}
        merged_remote = False
        if self._compare_timestamps(remote_updated, local_updated) > 0:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                return
            response.raise_for_status()
            if not self.merge_cross_paper_bundle(user_id, response.content):
                raise RuntimeError("invalid remote cross-paper bundle")
            merged_remote = True
            local_updated = self._get_directory_updated_at(
                settings.get_user_cross_paper_dir(user_id)
            )
        if merged_remote or self._compare_timestamps(local_updated, remote_updated) > 0:
            if remote_updated:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    if not self.merge_cross_paper_bundle(user_id, response.content):
                        raise RuntimeError("invalid remote cross-paper bundle")
            bundle = self.create_cross_paper_bundle(user_id)
            if bundle is None:
                return
            response = await client.put(
                url,
                headers=self._write_headers(
                    sync_token,
                    "cross-paper",
                    local_updated,
                    remote_updated,
                ),
                files={"file": ("cross-paper.zip", bundle, "application/zip")},
            )
            response.raise_for_status()
            logger.info(
                "sync cross-paper run=%s action=push bytes=%d",
                sync_run_id,
                len(bundle),
            )

    async def _sync_papers(
        self,
        client: httpx.AsyncClient,
        sync_base: str,
        sync_token: str,
        user_id: str,
        local_manifest: dict,
        remote_manifest: dict,
        sync_run_id: str,
        target_paper_ids: Optional[set[str]] = None,
    ) -> None:
        local_papers = {paper["arxiv_id"]: paper for paper in local_manifest.get("papers", [])}
        remote_papers = {paper["arxiv_id"]: paper for paper in remote_manifest.get("papers", [])}
        local_deleted = {paper["arxiv_id"]: paper for paper in local_manifest.get("deleted_papers", [])}
        remote_deleted = {paper["arxiv_id"]: paper for paper in remote_manifest.get("deleted_papers", [])}
        paper_ids = set(local_papers) | set(remote_papers) | set(local_deleted) | set(remote_deleted)
        if target_paper_ids is not None:
            paper_ids &= target_paper_ids
        ordered_paper_ids = [
            *[paper_id for paper_id in self._priority_paper_ids if paper_id in paper_ids],
            *[paper_id for paper_id in sorted(paper_ids) if paper_id not in self._priority_paper_ids],
        ]

        for paper_id in ordered_paper_ids:
            local_updated = local_papers.get(paper_id, {}).get("paper_updated_at") or local_papers.get(paper_id, {}).get("updated_at")
            remote_updated = remote_papers.get(paper_id, {}).get("paper_updated_at") or remote_papers.get(paper_id, {}).get("updated_at")
            local_deleted_at = local_deleted.get(paper_id, {}).get("deleted_at")
            remote_deleted_at = remote_deleted.get(paper_id, {}).get("deleted_at")

            if self._compare_timestamps(remote_deleted_at, local_deleted_at) > 0 and self._compare_timestamps(remote_deleted_at, local_updated) > 0:
                self.delete_paper(user_id, paper_id, remote_deleted_at)
                logger.info("sync paper run=%s action=delete-local paper=%s remote_deleted_at=%s", sync_run_id, paper_id, remote_deleted_at)
                continue

            if self._compare_timestamps(local_deleted_at, remote_deleted_at) > 0 and self._compare_timestamps(local_deleted_at, remote_updated) > 0:
                resp = await client.delete(
                    f"{sync_base}/papers/{paper_id}",
                    headers=self._write_headers(
                        sync_token,
                        f"paper-delete:{paper_id}",
                        local_deleted_at,
                        remote_updated,
                    ),
                    params={"deleted_at": local_deleted_at},
                )
                resp.raise_for_status()
                logger.info("sync paper run=%s action=delete-remote paper=%s local_deleted_at=%s", sync_run_id, paper_id, local_deleted_at)
                continue

            if self._compare_timestamps(remote_updated, local_updated) > 0:
                resp = await client.get(
                    f"{sync_base}/papers/{paper_id}/metadata/bundle",
                    headers={"Authorization": f"Bearer {sync_token}"},
                )
                resp.raise_for_status()
                self.extract_paper_bundle(user_id, paper_id, resp.content)
                await self._sync_pdf_asset(
                    client,
                    sync_base,
                    sync_token,
                    user_id,
                    paper_id,
                    remote_papers.get(paper_id, {}),
                )
                logger.info("sync paper run=%s action=pull paper=%s bytes=%d remote_updated=%s local_updated=%s", sync_run_id, paper_id, len(resp.content), remote_updated, local_updated)
                continue

            if self._compare_timestamps(local_updated, remote_updated) > 0:
                bundle = self.create_paper_metadata_bundle(user_id, paper_id)
                if bundle is None:
                    logger.info("sync paper run=%s action=skip paper=%s reason=no-bundle", sync_run_id, paper_id)
                    continue
                files = {"file": (f"{paper_id}.zip", bundle, "application/zip")}
                resp = await client.put(
                    f"{sync_base}/papers/{paper_id}/metadata/bundle",
                    headers=self._write_headers(
                        sync_token,
                        f"paper:{paper_id}",
                        local_updated,
                        remote_updated,
                    ),
                    files=files,
                )
                resp.raise_for_status()
                await self._sync_pdf_asset(
                    client,
                    sync_base,
                    sync_token,
                    user_id,
                    paper_id,
                    remote_papers.get(paper_id, {}),
                )
                logger.info("sync paper run=%s action=push paper=%s bytes=%d local_updated=%s remote_updated=%s", sync_run_id, paper_id, len(bundle), local_updated, remote_updated)
                continue

            await self._sync_pdf_asset(
                client,
                sync_base,
                sync_token,
                user_id,
                paper_id,
                remote_papers.get(paper_id, {}),
            )
            logger.debug("sync paper run=%s action=skip paper=%s reason=up-to-date", sync_run_id, paper_id)

    async def _sync_pdf_asset(
        self,
        client: httpx.AsyncClient,
        sync_base: str,
        sync_token: str,
        user_id: str,
        paper_id: str,
        remote_paper: dict,
    ) -> None:
        paper_dir = self._paper_dir(user_id, paper_id)
        meta_file = paper_dir / "meta.json"
        if not meta_file.exists():
            return
        meta = self._read_json(meta_file)
        if meta.get("source_type", "arxiv") == "arxiv":
            return
        pdf_path = paper_dir / "paper.pdf"
        remote_available = bool(remote_paper.get("pdf_available"))
        local_hash = self._file_sha256(pdf_path)
        remote_hash = remote_paper.get("pdf_hash")
        local_updated = self._file_mtime(pdf_path)
        remote_updated = remote_paper.get("pdf_updated_at")
        if local_hash and remote_hash and local_hash == remote_hash:
            return
        headers = {"Authorization": f"Bearer {sync_token}"}
        url = f"{sync_base}/papers/{paper_id}/pdf"
        should_push = bool(local_hash and not remote_available)
        should_pull = bool(remote_available and not local_hash)
        if local_hash and remote_hash and local_hash != remote_hash:
            comparison = self._compare_timestamps(local_updated, remote_updated)
            if comparison > 0:
                should_push = True
            elif comparison < 0:
                should_pull = True
            else:
                raise RuntimeError(f"PDF asset conflict for {paper_id}")
        if should_push:
            content = pdf_path.read_bytes()
            response = await client.put(
                url,
                headers=self._write_headers(
                    sync_token,
                    f"pdf:{paper_id}",
                    hashlib.sha256(content).hexdigest(),
                    remote_hash,
                ),
                files={"file": (f"{paper_id}.pdf", content, "application/pdf")},
            )
            response.raise_for_status()
            logger.info("sync pdf asset action=push paper=%s bytes=%d", paper_id, len(content))
            return
        if should_pull:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            if not self.extract_pdf_asset(user_id, paper_id, response.content):
                raise RuntimeError(f"invalid remote PDF asset for {paper_id}")
            logger.info(
                "sync pdf asset action=pull paper=%s bytes=%d",
                paper_id,
                len(response.content),
            )
            return

    async def _sync_chats(
        self,
        client: httpx.AsyncClient,
        sync_base: str,
        sync_token: str,
        user_id: str,
        local_manifest: dict,
        remote_manifest: dict,
        sync_run_id: str,
        target_paper_ids: Optional[set[str]] = None,
    ) -> None:
        local_papers = {paper["arxiv_id"]: paper for paper in local_manifest.get("papers", [])}
        remote_papers = {paper["arxiv_id"]: paper for paper in remote_manifest.get("papers", [])}
        paper_ids = set(local_papers) | set(remote_papers)
        if target_paper_ids is not None:
            paper_ids &= target_paper_ids

        for paper_id in sorted(paper_ids):
            local_updated = local_papers.get(paper_id, {}).get("chats_updated_at")
            remote_updated = remote_papers.get(paper_id, {}).get("chats_updated_at")

            if self._compare_timestamps(remote_updated, local_updated) > 0:
                resp = await client.get(
                    f"{sync_base}/papers/{paper_id}/chats/bundle",
                    headers={"Authorization": f"Bearer {sync_token}"},
                )
                if resp.status_code == 404:
                    logger.info("sync chats run=%s action=skip paper=%s reason=remote-no-chats", sync_run_id, paper_id)
                    continue
                resp.raise_for_status()
                if not self.merge_paper_chats_bundle(
                    user_id,
                    paper_id,
                    resp.content,
                ):
                    raise RuntimeError(f"failed to merge remote chats for {paper_id}")
                bundle = self.create_paper_chats_bundle(user_id, paper_id)
                if bundle is not None:
                    merged_updated = self._get_paper_chats_updated_at(
                        self._paper_dir(user_id, paper_id)
                    )
                    push = await client.put(
                        f"{sync_base}/papers/{paper_id}/chats/bundle",
                        headers=self._write_headers(
                            sync_token,
                            f"chats:{paper_id}",
                            merged_updated,
                            remote_updated,
                        ),
                        files={
                            "file": (
                                f"{paper_id}-chats.zip",
                                bundle,
                                "application/zip",
                            )
                        },
                    )
                    push.raise_for_status()
                logger.info("sync chats run=%s action=pull-merge paper=%s bytes=%d remote_updated=%s local_updated=%s", sync_run_id, paper_id, len(resp.content), remote_updated, local_updated)
                continue

            if self._compare_timestamps(local_updated, remote_updated) > 0:
                if remote_updated:
                    remote_bundle = await client.get(
                        f"{sync_base}/papers/{paper_id}/chats/bundle",
                        headers={"Authorization": f"Bearer {sync_token}"},
                    )
                    if remote_bundle.status_code == 200:
                        if not self.merge_paper_chats_bundle(
                            user_id,
                            paper_id,
                            remote_bundle.content,
                        ):
                            raise RuntimeError(
                                f"failed to merge remote chats for {paper_id}"
                            )
                bundle = self.create_paper_chats_bundle(user_id, paper_id)
                if bundle is None:
                    logger.info("sync chats run=%s action=skip paper=%s reason=no-local-chats", sync_run_id, paper_id)
                    continue
                files = {"file": (f"{paper_id}-chats.zip", bundle, "application/zip")}
                resp = await client.put(
                    f"{sync_base}/papers/{paper_id}/chats/bundle",
                    headers=self._write_headers(
                        sync_token,
                        f"chats:{paper_id}",
                        local_updated,
                        remote_updated,
                    ),
                    files=files,
                )
                resp.raise_for_status()
                logger.info("sync chats run=%s action=push paper=%s bytes=%d local_updated=%s remote_updated=%s", sync_run_id, paper_id, len(bundle), local_updated, remote_updated)
                continue

            logger.debug("sync chats run=%s action=skip paper=%s reason=up-to-date", sync_run_id, paper_id)

    async def _sync_document(self, client: httpx.AsyncClient, name: str, local_updated: Optional[str], remote_updated: Optional[str], get_local_data, apply_remote_data, remote_url: str, sync_token: str, sync_run_id: str) -> None:
        if self._compare_timestamps(remote_updated, local_updated) > 0:
            resp = await client.get(remote_url, headers={"Authorization": f"Bearer {sync_token}"})
            resp.raise_for_status()
            apply_remote_data(resp.json())
            logger.info("sync document run=%s action=pull name=%s remote_updated=%s local_updated=%s", sync_run_id, name, remote_updated, local_updated)
            return

        if self._compare_timestamps(local_updated, remote_updated) > 0:
            resp = await client.put(
                remote_url,
                headers=self._write_headers(
                    sync_token,
                    f"document:{name}",
                    local_updated,
                    remote_updated,
                ),
                json=get_local_data(),
            )
            resp.raise_for_status()
            logger.info("sync document run=%s action=push name=%s local_updated=%s remote_updated=%s", sync_run_id, name, local_updated, remote_updated)

    def _get_file_updated_at(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        if path.suffix == ".json":
            data = self._read_json(path)
            return data.get("updated_at")
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()

    def _get_directory_updated_at(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        latest = datetime.min
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            candidate: Optional[str] = None
            if file_path.suffix == ".json":
                try:
                    candidate = self._read_json(file_path).get("updated_at")
                except Exception:
                    candidate = None
            candidate_dt = (
                datetime.fromisoformat(candidate)
                if candidate
                else datetime.fromtimestamp(file_path.stat().st_mtime)
            )
            if candidate_dt > latest:
                latest = candidate_dt
        return latest.isoformat() if latest != datetime.min else None

    @staticmethod
    def _read_json(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def _write_json_atomic(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(
            temp,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        temp.replace(path)


sync_service = SyncService()
