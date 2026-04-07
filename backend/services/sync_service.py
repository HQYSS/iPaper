"""
同步服务 — 生成 manifest、打包/解包论文 bundle、偏好/画像同步
"""
import asyncio
import io
import json
import zipfile
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

LOCAL_SYNC_USER_ID = "441e2fb8d4a64409"
LOCAL_SYNC_POLL_SECONDS = 1.0
LOCAL_PUSH_DEBOUNCE_SECONDS = 2.0
REMOTE_POLL_SECONDS = 15.0


class SyncManifestItem:
    __slots__ = ("arxiv_id", "updated_at")

    def __init__(self, arxiv_id: str, updated_at: str):
        self.arxiv_id = arxiv_id
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {"arxiv_id": self.arxiv_id, "updated_at": self.updated_at}


class SyncDeletedItem:
    __slots__ = ("arxiv_id", "deleted_at")

    def __init__(self, arxiv_id: str, deleted_at: str):
        self.arxiv_id = arxiv_id
        self.deleted_at = deleted_at

    def to_dict(self) -> dict:
        return {"arxiv_id": self.arxiv_id, "deleted_at": self.deleted_at}


class SyncManifest:
    __slots__ = ("papers", "deleted_papers", "preferences_updated_at", "profile_updated_at")

    def __init__(
        self,
        papers: List[SyncManifestItem],
        deleted_papers: List[SyncDeletedItem],
        preferences_updated_at: Optional[str],
        profile_updated_at: Optional[str],
    ):
        self.papers = papers
        self.deleted_papers = deleted_papers
        self.preferences_updated_at = preferences_updated_at
        self.profile_updated_at = profile_updated_at

    def to_dict(self) -> dict:
        return {
            "papers": [p.to_dict() for p in self.papers],
            "deleted_papers": [p.to_dict() for p in self.deleted_papers],
            "preferences_updated_at": self.preferences_updated_at,
            "profile_updated_at": self.profile_updated_at,
        }


class SyncService:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._debounced_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._priority_paper_ids = set()
        self._last_remote_sync_at: float = 0.0
        self._sync_lock = asyncio.Lock()
        self._last_local_fingerprint = ""
        self._last_remote_fingerprint = ""

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
                updated_at = self._get_paper_bundle_updated_at(paper_dir)
                items.append(SyncManifestItem(
                    arxiv_id=paper_dir.name,
                    updated_at=updated_at,
                ))

        active_deletions = self._get_active_paper_tombstones(user_id)
        for arxiv_id, deleted_at in sorted(active_deletions.items()):
            deleted_items.append(SyncDeletedItem(arxiv_id=arxiv_id, deleted_at=deleted_at))

        pref_updated = self._get_file_updated_at(
            settings.get_user_data_dir(user_id) / "preferences.json"
        )
        profile_updated = self.get_profile_updated_at(user_id)

        return SyncManifest(
            papers=items,
            deleted_papers=deleted_items,
            preferences_updated_at=pref_updated,
            profile_updated_at=profile_updated,
        )

    # ==================== Paper bundle ====================

    def create_paper_bundle(self, user_id: str, paper_id: str) -> Optional[bytes]:
        paper_dir = settings.get_user_papers_dir(user_id) / paper_id
        if not paper_dir.exists():
            return None

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in paper_dir.rglob("*"):
                if file_path.is_file():
                    arcname = str(file_path.relative_to(paper_dir))
                    zf.write(file_path, arcname)
        return buf.getvalue()

    def extract_paper_bundle(self, user_id: str, paper_id: str, bundle_bytes: bytes) -> bool:
        paper_dir = settings.get_user_papers_dir(user_id) / paper_id
        paper_dir.mkdir(parents=True, exist_ok=True)

        buf = io.BytesIO(bundle_bytes)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                for member in zf.namelist():
                    if member.startswith("..") or member.startswith("/"):
                        continue
                    target = paper_dir / member
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except zipfile.BadZipFile:
            logger.error("Invalid zip bundle for paper %s", paper_id)
            return False

        self.clear_paper_tombstone(user_id, paper_id)
        self._rebuild_papers_index(user_id)
        return True

    def delete_paper(self, user_id: str, paper_id: str, deleted_at: Optional[str] = None) -> bool:
        paper_dir = settings.get_user_papers_dir(user_id) / paper_id
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
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def _get_paper_bundle_updated_at(self, paper_dir: Path) -> str:
        latest = datetime.min
        for file_path in paper_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix != ".json":
                continue
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

    def request_sync(self, reason: str = "local-change", paper_id: Optional[str] = None) -> None:
        if settings.host != "127.0.0.1":
            return
        if paper_id:
            self._priority_paper_ids.add(paper_id)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._debounced_task and not self._debounced_task.done():
            self._debounced_task.cancel()
        self._debounced_task = loop.create_task(self._debounced_sync(reason))
        self._wake_event.set()
        logger.warning("Scheduled local sync: %s paper=%s", reason, paper_id)

    async def startup(self) -> None:
        if settings.host != "127.0.0.1":
            return
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._background_loop())
        logger.info("Local background sync worker started")

    async def shutdown(self) -> None:
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
            await self._sync_once(LOCAL_SYNC_USER_ID, reason)
        except asyncio.CancelledError:
            logger.warning("Cancelled debounced local sync: %s", reason)
            return
        except Exception:
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

    async def _sync_once(self, user_id: str, reason: str) -> None:
        sync_token = settings.sync_token.strip()
        sync_base = self._normalize_sync_base()
        if not sync_token or not sync_base:
            return

        async with self._sync_lock:
            local_manifest = self.get_manifest(user_id)
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=30.0, read=300.0, write=300.0, pool=60.0)
            ) as client:
                remote_manifest_resp = await client.get(
                    f"{sync_base}/manifest",
                    headers={"Authorization": f"Bearer {sync_token}"},
                )
                remote_manifest_resp.raise_for_status()
                remote_manifest = remote_manifest_resp.json()

                await self._sync_papers(client, sync_base, sync_token, user_id, local_manifest.to_dict(), remote_manifest)
                await self._sync_document(
                    client,
                    "preferences",
                    local_manifest.preferences_updated_at,
                    remote_manifest.get("preferences_updated_at"),
                    lambda: self.get_preferences(user_id) or {},
                    lambda data: self.put_preferences(user_id, data),
                    f"{sync_base}/preferences",
                    sync_token,
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
                )

            final_local_manifest = self.get_manifest(user_id)
            self._last_local_fingerprint = self._paper_fingerprint(final_local_manifest)
            self._last_remote_fingerprint = json.dumps(remote_manifest, ensure_ascii=False, sort_keys=True)
            logger.info("Background sync completed: %s", reason)

    async def _sync_papers(self, client: httpx.AsyncClient, sync_base: str, sync_token: str, user_id: str, local_manifest: dict, remote_manifest: dict) -> None:
        local_papers = {paper["arxiv_id"]: paper for paper in local_manifest.get("papers", [])}
        remote_papers = {paper["arxiv_id"]: paper for paper in remote_manifest.get("papers", [])}
        local_deleted = {paper["arxiv_id"]: paper for paper in local_manifest.get("deleted_papers", [])}
        remote_deleted = {paper["arxiv_id"]: paper for paper in remote_manifest.get("deleted_papers", [])}
        paper_ids = set(local_papers) | set(remote_papers) | set(local_deleted) | set(remote_deleted)
        ordered_paper_ids = [
            *[paper_id for paper_id in self._priority_paper_ids if paper_id in paper_ids],
            *[paper_id for paper_id in sorted(paper_ids) if paper_id not in self._priority_paper_ids],
        ]

        for paper_id in ordered_paper_ids:
            local_updated = local_papers.get(paper_id, {}).get("updated_at")
            remote_updated = remote_papers.get(paper_id, {}).get("updated_at")
            local_deleted_at = local_deleted.get(paper_id, {}).get("deleted_at")
            remote_deleted_at = remote_deleted.get(paper_id, {}).get("deleted_at")

            if self._compare_timestamps(remote_deleted_at, local_deleted_at) > 0 and self._compare_timestamps(remote_deleted_at, local_updated) > 0:
                self.delete_paper(user_id, paper_id, remote_deleted_at)
                continue

            if self._compare_timestamps(local_deleted_at, remote_deleted_at) > 0 and self._compare_timestamps(local_deleted_at, remote_updated) > 0:
                resp = await client.delete(
                    f"{sync_base}/papers/{paper_id}",
                    headers={"Authorization": f"Bearer {sync_token}"},
                )
                resp.raise_for_status()
                continue

            if self._compare_timestamps(remote_updated, local_updated) > 0:
                resp = await client.get(
                    f"{sync_base}/papers/{paper_id}/bundle",
                    headers={"Authorization": f"Bearer {sync_token}"},
                )
                resp.raise_for_status()
                self.extract_paper_bundle(user_id, paper_id, resp.content)
                continue

            if self._compare_timestamps(local_updated, remote_updated) > 0:
                bundle = self.create_paper_bundle(user_id, paper_id)
                if bundle is None:
                    continue
                files = {"file": (f"{paper_id}.zip", bundle, "application/zip")}
                resp = await client.put(
                    f"{sync_base}/papers/{paper_id}/bundle",
                    headers={"Authorization": f"Bearer {sync_token}"},
                    files=files,
                )
                resp.raise_for_status()

        self._priority_paper_ids.difference_update(ordered_paper_ids)

    async def _sync_document(self, client: httpx.AsyncClient, name: str, local_updated: Optional[str], remote_updated: Optional[str], get_local_data, apply_remote_data, remote_url: str, sync_token: str) -> None:
        if self._compare_timestamps(remote_updated, local_updated) > 0:
            resp = await client.get(remote_url, headers={"Authorization": f"Bearer {sync_token}"})
            resp.raise_for_status()
            apply_remote_data(resp.json())
            return

        if self._compare_timestamps(local_updated, remote_updated) > 0:
            resp = await client.put(remote_url, headers={"Authorization": f"Bearer {sync_token}"}, json=get_local_data())
            resp.raise_for_status()

    def _get_file_updated_at(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None
        if path.suffix == ".json":
            data = self._read_json(path)
            return data.get("updated_at")
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()

    @staticmethod
    def _read_json(path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


sync_service = SyncService()
