import io
import json
import zipfile

from services.sync_service import SyncService


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_manifest_includes_only_ready_papers_and_document_timestamps(isolated_settings):
    user_id = "manifest-user"
    papers_dir = isolated_settings.get_user_papers_dir(user_id)

    ready_dir = papers_dir / "2401.00001"
    ready_dir.mkdir()
    (ready_dir / "paper.pdf").write_bytes(b"%PDF-test")
    _write_json(
        ready_dir / "meta.json",
        {
            "arxiv_id": "2401.00001",
            "download_status": "ready",
            "updated_at": "2026-01-02T03:04:05",
        },
    )
    _write_json(
        ready_dir / "chats" / "session.json",
        {"updated_at": "2026-01-03T03:04:05", "messages": []},
    )

    incomplete_dir = papers_dir / "2401.00002"
    incomplete_dir.mkdir()
    _write_json(
        incomplete_dir / "meta.json",
        {"download_status": "downloading", "updated_at": "2026-01-04T03:04:05"},
    )

    _write_json(
        isolated_settings.get_user_data_dir(user_id) / "preferences.json",
        {"updated_at": "2026-01-05T03:04:05"},
    )
    profile_dir = isolated_settings.get_user_profile_dir(user_id)
    (profile_dir / "profile.md").write_text("test profile", encoding="utf-8")
    _write_json(profile_dir / "profile.meta.json", {"updated_at": "2026-01-06T03:04:05"})

    manifest = SyncService().get_manifest(user_id).to_dict()

    assert [paper["arxiv_id"] for paper in manifest["papers"]] == ["2401.00001"]
    assert manifest["papers"][0]["paper_updated_at"] == "2026-01-02T03:04:05"
    assert manifest["papers"][0]["chats_updated_at"] == "2026-01-03T03:04:05"
    assert manifest["papers"][0]["updated_at"] == "2026-01-03T03:04:05"
    assert manifest["preferences_updated_at"] == "2026-01-05T03:04:05"
    assert manifest["profile_updated_at"] == "2026-01-06T03:04:05"


def test_paper_bundle_round_trip_uses_only_local_files(isolated_settings):
    user_id = "bundle-user"
    source_dir = isolated_settings.get_user_papers_dir(user_id) / "source-paper"
    source_dir.mkdir()
    (source_dir / "paper.pdf").write_bytes(b"%PDF-bundle")
    _write_json(
        source_dir / "meta.json",
        {"arxiv_id": "source-paper", "download_status": "ready", "updated_at": "2026-01-01T00:00:00"},
    )
    (source_dir / "notes").mkdir()
    (source_dir / "notes" / "note.txt").write_text("本地笔记", encoding="utf-8")

    service = SyncService()
    bundle = service.create_paper_bundle(user_id, "source-paper")

    assert bundle is not None
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {"paper.pdf", "meta.json", "notes/note.txt"}

    assert service.extract_paper_bundle(user_id, "restored-paper", bundle) is True
    restored = isolated_settings.get_user_papers_dir(user_id) / "restored-paper"
    assert (restored / "paper.pdf").read_bytes() == b"%PDF-bundle"
    assert (restored / "notes" / "note.txt").read_text(encoding="utf-8") == "本地笔记"


def test_invalid_bundle_is_rejected(isolated_settings):
    service = SyncService()
    assert service.extract_paper_bundle("invalid-user", "paper", b"not-a-zip") is False
