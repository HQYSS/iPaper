"""
同步服务 — 生成 manifest、打包/解包论文 bundle、偏好/画像同步
"""
import io
import json
import zipfile
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from config import settings

logger = logging.getLogger(__name__)


class SyncManifestItem:
    __slots__ = ("arxiv_id", "updated_at")

    def __init__(self, arxiv_id: str, updated_at: str):
        self.arxiv_id = arxiv_id
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {"arxiv_id": self.arxiv_id, "updated_at": self.updated_at}


class SyncManifest:
    __slots__ = ("papers", "preferences_updated_at", "profile_updated_at")

    def __init__(
        self,
        papers: List[SyncManifestItem],
        preferences_updated_at: Optional[str],
        profile_updated_at: Optional[str],
    ):
        self.papers = papers
        self.preferences_updated_at = preferences_updated_at
        self.profile_updated_at = profile_updated_at

    def to_dict(self) -> dict:
        return {
            "papers": [p.to_dict() for p in self.papers],
            "preferences_updated_at": self.preferences_updated_at,
            "profile_updated_at": self.profile_updated_at,
        }


class SyncService:

    def get_manifest(self, user_id: str) -> SyncManifest:
        papers_dir = settings.get_user_papers_dir(user_id)
        items: List[SyncManifestItem] = []

        if papers_dir.exists():
            for paper_dir in sorted(papers_dir.iterdir()):
                if not paper_dir.is_dir():
                    continue
                meta_file = paper_dir / "meta.json"
                if not meta_file.exists():
                    continue
                meta = self._read_json(meta_file)
                updated_at = meta.get("updated_at") or meta.get("download_time", "")
                items.append(SyncManifestItem(
                    arxiv_id=paper_dir.name,
                    updated_at=updated_at,
                ))

        pref_updated = self._get_file_updated_at(
            settings.get_user_data_dir(user_id) / "preferences.json"
        )
        profile_updated = self._get_file_updated_at(
            settings.get_user_profile_dir(user_id) / "profile.md"
        )

        return SyncManifest(
            papers=items,
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

        self._touch_paper_updated_at(user_id, paper_id)
        return True

    # ==================== Preferences ====================

    def get_preferences(self, user_id: str) -> Optional[dict]:
        pref_file = settings.get_user_data_dir(user_id) / "preferences.json"
        if not pref_file.exists():
            return None
        return self._read_json(pref_file)

    def put_preferences(self, user_id: str, data: dict) -> None:
        pref_file = settings.get_user_data_dir(user_id) / "preferences.json"
        pref_file.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = datetime.now().isoformat()
        self._write_json(pref_file, data)

    # ==================== Profile ====================

    def get_profile(self, user_id: str) -> Optional[str]:
        profile_file = settings.get_user_profile_dir(user_id) / "profile.md"
        if not profile_file.exists():
            return None
        return profile_file.read_text(encoding="utf-8")

    def put_profile(self, user_id: str, content: str) -> None:
        profile_dir = settings.get_user_profile_dir(user_id)
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "profile.md").write_text(content, encoding="utf-8")

    # ==================== Internal helpers ====================

    def _touch_paper_updated_at(self, user_id: str, paper_id: str) -> None:
        meta_file = settings.get_user_papers_dir(user_id) / paper_id / "meta.json"
        if meta_file.exists():
            meta = self._read_json(meta_file)
            meta["updated_at"] = datetime.now().isoformat()
            self._write_json(meta_file, meta)

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
