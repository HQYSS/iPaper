import io
import json
import zipfile

import pytest

from services import sync_service as sync_module
from services.storage_service import StorageService
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

    assert [paper["arxiv_id"] for paper in manifest["papers"]] == ["2401.00001", "2401.00002"]
    assert manifest["papers"][0]["paper_updated_at"] == "2026-01-02T03:04:05"
    assert manifest["papers"][0]["chats_updated_at"] == "2026-01-03T03:04:05"
    assert manifest["papers"][0]["updated_at"] == "2026-01-03T03:04:05"
    assert manifest["papers"][0]["pdf_available"] is True
    assert manifest["papers"][1]["pdf_available"] is False
    assert manifest["preferences_updated_at"] == "2026-01-05T03:04:05"
    assert manifest["profile_updated_at"] == "2026-01-06T03:04:05"


def test_paper_bundle_round_trip_uses_only_local_files(isolated_settings):
    user_id = "bundle-user"
    source_dir = isolated_settings.get_user_papers_dir(user_id) / "2401.00001"
    source_dir.mkdir()
    (source_dir / "paper.pdf").write_bytes(b"%PDF-bundle")
    _write_json(
        source_dir / "meta.json",
        {"arxiv_id": "2401.00001", "download_status": "ready", "updated_at": "2026-01-01T00:00:00"},
    )
    (source_dir / "notes").mkdir()
    (source_dir / "notes" / "note.txt").write_text("本地笔记", encoding="utf-8")
    _write_json(
        source_dir / "chats" / "session.json",
        {"updated_at": "2026-01-02T00:00:00", "messages": [{"role": "user", "content": "new"}]},
    )

    service = SyncService()
    bundle = service.create_paper_metadata_bundle(user_id, "2401.00001")

    assert bundle is not None
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert set(archive.namelist()) == {"meta.json", "notes/note.txt"}

    restored_dir = isolated_settings.get_user_papers_dir(user_id) / "2401.00002"
    _write_json(
        restored_dir / "chats" / "session.json",
        {"updated_at": "2026-01-03T00:00:00", "messages": [{"role": "user", "content": "keep"}]},
    )
    assert service.extract_paper_bundle(user_id, "2401.00002", bundle) is True
    restored = isolated_settings.get_user_papers_dir(user_id) / "2401.00002"
    assert not (restored / "paper.pdf").exists()
    assert (restored / "notes" / "note.txt").read_text(encoding="utf-8") == "本地笔记"
    assert json.loads((restored / "chats" / "session.json").read_text(encoding="utf-8"))[
        "messages"
    ][0]["content"] == "keep"

    legacy_bundle = service.create_paper_bundle(user_id, "2401.00001")
    assert legacy_bundle is not None
    with zipfile.ZipFile(io.BytesIO(legacy_bundle)) as archive:
        assert "paper.pdf" in archive.namelist()
        assert all(not name.startswith("chats/") for name in archive.namelist())


def test_paper_paths_reject_traversal(isolated_settings):
    service = SyncService()
    with pytest.raises(ValueError, match="invalid paper_id"):
        service.delete_paper("path-user", "..")
    with pytest.raises(ValueError, match="invalid paper_id"):
        service.extract_pdf_asset("path-user", "../escape", b"%PDF-test")


def test_bundle_rejects_excessive_uncompressed_size(isolated_settings, monkeypatch):
    service = SyncService()
    monkeypatch.setattr(service, "MAX_BUNDLE_UNCOMPRESSED_BYTES", 4)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("meta.json", b"12345")

    assert service.extract_paper_bundle(
        "zip-limit-user",
        "2401.00001",
        buffer.getvalue(),
    ) is False


def test_pdf_asset_round_trip(isolated_settings):
    service = SyncService()
    user_id = "pdf-asset-user"
    paper_id = "pdf_0123456789abcdef"
    source_dir = isolated_settings.get_user_papers_dir(user_id) / paper_id
    source_dir.mkdir()
    (source_dir / "paper.pdf").write_bytes(b"%PDF-asset")
    _write_json(
        source_dir / "meta.json",
        {"arxiv_id": paper_id, "source_type": "pdf_url", "download_status": "ready"},
    )

    content = service.create_pdf_asset(user_id, paper_id)
    assert content == b"%PDF-asset"
    (source_dir / "paper.pdf").unlink()
    assert service.extract_pdf_asset(user_id, paper_id, content) is True
    assert (source_dir / "paper.pdf").read_bytes() == b"%PDF-asset"
    paper_manifest = service.get_manifest(user_id).papers[0].to_dict()
    assert paper_manifest["pdf_hash"] == service._file_sha256(source_dir / "paper.pdf")
    assert paper_manifest["pdf_updated_at"]
    assert len(service._pdf_hash_cache) == 1
    (source_dir / "paper.pdf").write_bytes(b"%PDF-asset-updated")
    assert service._file_sha256(source_dir / "paper.pdf") != paper_manifest["pdf_hash"]


def test_chat_bundle_replaces_snapshot_and_removes_deleted_sessions(isolated_settings):
    user_id = "chat-snapshot-user"
    service = SyncService()
    source_chats = isolated_settings.get_user_papers_dir(user_id) / "2401.00001" / "chats"
    _write_json(source_chats / "sessions.json", {"updated_at": "2026-01-02T00:00:00", "sessions": []})
    _write_json(source_chats / "active.json", {"updated_at": "2026-01-02T00:00:00", "messages": []})
    bundle = service.create_paper_chats_bundle(user_id, "2401.00001")
    assert bundle is not None

    target_chats = isolated_settings.get_user_papers_dir(user_id) / "2401.00002" / "chats"
    _write_json(target_chats / "deleted.json", {"updated_at": "2026-01-01T00:00:00", "messages": []})
    assert service.extract_paper_chats_bundle(user_id, "2401.00002", bundle) is True

    assert not (target_chats / "deleted.json").exists()
    assert (target_chats / "active.json").exists()


def test_chat_bundle_merge_preserves_sessions_changed_on_both_sides(isolated_settings):
    user_id = "chat-merge-user"
    service = SyncService()
    remote_chats = isolated_settings.get_user_papers_dir(user_id) / "2401.00001" / "chats"
    _write_json(
        remote_chats / "sessions.json",
        {
            "updated_at": "2026-01-02T00:00:00",
            "sessions": [
                {"id": "s_remote", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-02T00:00:00"}
            ],
        },
    )
    _write_json(
        remote_chats / "s_remote.json",
        {"updated_at": "2026-01-02T00:00:00", "messages": []},
    )
    remote_bundle = service.create_paper_chats_bundle(user_id, "2401.00001")
    assert remote_bundle is not None

    local_chats = isolated_settings.get_user_papers_dir(user_id) / "2401.00002" / "chats"
    _write_json(
        local_chats / "sessions.json",
        {
            "updated_at": "2026-01-03T00:00:00",
            "sessions": [
                {"id": "s_local", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-03T00:00:00"}
            ],
        },
    )
    _write_json(
        local_chats / "s_local.json",
        {"updated_at": "2026-01-03T00:00:00", "messages": []},
    )

    assert service.merge_paper_chats_bundle(user_id, "2401.00002", remote_bundle) is True
    merged_index = json.loads((local_chats / "sessions.json").read_text(encoding="utf-8"))
    assert {session["id"] for session in merged_index["sessions"]} == {
        "s_local",
        "s_remote",
    }
    assert (local_chats / "s_local.json").exists()
    assert (local_chats / "s_remote.json").exists()


def test_chat_merge_ignores_malicious_session_ids(isolated_settings):
    user_id = "chat-malicious-user"
    service = SyncService()
    remote_chats = isolated_settings.get_user_papers_dir(user_id) / "2401.00001" / "chats"
    _write_json(
        remote_chats / "sessions.json",
        {
            "updated_at": "2026-01-02T00:00:00",
            "sessions": [{"id": "../../meta", "updated_at": "2026-01-02T00:00:00"}],
            "deleted_sessions": {"../../meta": "2026-01-02T00:00:00"},
        },
    )
    bundle = service.create_paper_chats_bundle(user_id, "2401.00001")
    assert bundle is not None
    target = isolated_settings.get_user_papers_dir(user_id) / "2401.00002"
    _write_json(target / "meta.json", {"safe": True})

    assert service.merge_paper_chats_bundle(user_id, "2401.00002", bundle) is True
    assert json.loads((target / "meta.json").read_text(encoding="utf-8")) == {"safe": True}


def test_cross_paper_bundle_round_trip_replaces_snapshot(isolated_settings):
    user_id = "cross-snapshot-user"
    service = SyncService()
    cross_dir = isolated_settings.get_user_cross_paper_dir(user_id)
    _write_json(
        cross_dir / "sessions.json",
        {"updated_at": "2026-01-03T00:00:00", "sessions": [{"id": "cp_1"}]},
    )
    _write_json(cross_dir / "chats" / "cp_1.json", {"updated_at": "2026-01-03T00:00:00"})
    bundle = service.create_cross_paper_bundle(user_id)
    assert bundle is not None

    _write_json(cross_dir / "chats" / "ghost.json", {"updated_at": "2026-01-01T00:00:00"})
    assert service.extract_cross_paper_bundle(user_id, bundle) is True

    assert not (cross_dir / "chats" / "ghost.json").exists()
    assert (cross_dir / "chats" / "cp_1.json").exists()
    assert service.get_manifest(user_id).cross_paper_updated_at == "2026-01-03T00:00:00"


def test_cross_paper_merge_preserves_sessions_from_both_sides(isolated_settings):
    user_id = "cross-merge-user"
    service = SyncService()
    cross_dir = isolated_settings.get_user_cross_paper_dir(user_id)
    _write_json(
        cross_dir / "sessions.json",
        {
            "updated_at": "2026-01-03T00:00:00",
            "sessions": [{"id": "cp_local", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-03T00:00:00"}],
        },
    )
    _write_json(cross_dir / "chats" / "cp_local.json", {"updated_at": "2026-01-03T00:00:00"})

    remote_dir = isolated_settings.get_user_cross_paper_dir("cross-remote-user")
    _write_json(
        remote_dir / "sessions.json",
        {
            "updated_at": "2026-01-02T00:00:00",
            "sessions": [{"id": "cp_remote", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-02T00:00:00"}],
        },
    )
    _write_json(remote_dir / "chats" / "cp_remote.json", {"updated_at": "2026-01-02T00:00:00"})
    remote_bundle = service.create_cross_paper_bundle("cross-remote-user")
    assert remote_bundle is not None

    assert service.merge_cross_paper_bundle(user_id, remote_bundle) is True
    merged = json.loads((cross_dir / "sessions.json").read_text(encoding="utf-8"))
    assert {session["id"] for session in merged["sessions"]} == {"cp_local", "cp_remote"}

    before = service.get_manifest(user_id).cross_paper_updated_at
    StorageService().create_cross_paper_session(
        user_id,
        ["2401.00001", "2401.00002"],
    )
    after = service.get_manifest(user_id).cross_paper_updated_at
    assert service._compare_timestamps(after, before) > 0


def test_sync_outbox_survives_service_restart(isolated_settings, monkeypatch):
    monkeypatch.setattr(isolated_settings, "sync_role", "client")
    first = SyncService()
    first._priority_paper_ids.add("2401.00001")
    first._priority_chat_paper_ids.add("2401.00002")
    first._documents_dirty = True
    first._cross_paper_dirty = True
    first._persist_outbox()

    restored = SyncService()
    restored._load_outbox()

    assert restored._priority_paper_ids == {"2401.00001"}
    assert restored._priority_chat_paper_ids == {"2401.00002"}
    assert restored._documents_dirty is True
    assert restored._cross_paper_dirty is True


def test_idempotency_record_keeps_payload_digest(isolated_settings):
    service = SyncService()
    service.mark_operation_applied("idem-user", "operation-1", "digest-a")

    record = service.get_operation_record("idem-user", "operation-1")

    assert record is not None
    assert record["payload_digest"] == "digest-a"


@pytest.mark.asyncio
async def test_debounce_replacement_keeps_latest_sync_request(
    isolated_settings,
    monkeypatch,
):
    monkeypatch.setattr(isolated_settings, "sync_role", "client")
    monkeypatch.setattr(sync_module, "LOCAL_PUSH_DEBOUNCE_SECONDS", 0.01)
    service = SyncService()
    runs = []

    async def fake_sync(*args, **kwargs):
        runs.append((args, kwargs))

    monkeypatch.setattr(service, "_sync_once", fake_sync)
    service.request_sync("first", "2401.00001", scope="chats")
    service.request_sync("second", "2401.00001", scope="chats")
    await service._debounced_task

    assert len(runs) == 1
    assert runs[0][1]["target_chat_paper_ids"] == {"2401.00001"}


def test_invalid_bundle_is_rejected(isolated_settings):
    service = SyncService()
    assert service.extract_paper_bundle("invalid-user", "2401.00001", b"not-a-zip") is False
