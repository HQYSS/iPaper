import json
from datetime import datetime

from models import PaperMeta
from services import arxiv_service as arxiv_module
from services.arxiv_service import ArxivService, PLACEHOLDER_METADATA_SUMMARY


class _FakeStreamResponse:
    def __init__(self, content: bytes):
        self._content = content
        self.headers = {"content-length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=256 * 1024):
        yield self._content


def _write_meta(settings, user_id: str, meta: PaperMeta) -> None:
    paper_dir = settings.get_user_papers_dir(user_id) / meta.arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    with open(paper_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta.model_dump(mode="json"), f)


def test_recover_placeholder_metadata_only_schedules_incomplete_arxiv(
    isolated_settings, monkeypatch
):
    service = ArxivService()
    user_id = "metadata-user"
    placeholder = PaperMeta(
        arxiv_id="2607.15330",
        title="arXiv 2607.15330",
        summary=PLACEHOLDER_METADATA_SUMMARY,
        authors=[],
        download_time=datetime.now(),
    )
    complete = placeholder.model_copy(
        update={
            "arxiv_id": "2608.00001",
            "title": "Complete title",
            "summary": "Complete summary",
            "authors": ["Author"],
        }
    )
    pdf_url = placeholder.model_copy(
        update={"arxiv_id": "pdf_deadbeef", "source_type": "pdf_url"}
    )
    for meta in (placeholder, complete, pdf_url):
        _write_meta(isolated_settings, user_id, meta)

    scheduled = []
    monkeypatch.setattr(
        service,
        "_ensure_metadata_task",
        lambda uid, paper_id: scheduled.append((uid, paper_id)),
    )

    assert service.recover_placeholder_metadata() == 1
    assert scheduled == [(user_id, "2607.15330")]


def test_cancel_download_also_cancels_metadata_task():
    service = ArxivService()

    class PendingTask:
        cancelled = False

        def done(self):
            return False

        def cancel(self):
            self.cancelled = True

    task = PendingTask()
    service._metadata_tasks["user:2607.15330"] = task

    service.cancel_download("user", "2607.15330")

    assert task.cancelled is True
    assert "user:2607.15330" not in service._metadata_tasks


def test_update_index_persists_title_for_existing_paper(isolated_settings):
    service = ArxivService()
    user_id = "index-user"
    meta = PaperMeta(
        arxiv_id="2607.15330",
        title="arXiv 2607.15330",
        summary=PLACEHOLDER_METADATA_SUMMARY,
        authors=[],
        download_time=datetime.now(),
    )
    papers_dir = isolated_settings.get_user_papers_dir(user_id)
    papers_dir.mkdir(parents=True, exist_ok=True)
    service._update_index(user_id, meta)

    meta.title = "Recovered title"
    service._update_index(user_id, meta)

    with open(papers_dir / "index.json", encoding="utf-8") as f:
        index = json.load(f)
    assert index["papers"] == [
        {
            "arxiv_id": "2607.15330",
            "title": "Recovered title",
            "download_time": meta.download_time.isoformat(),
        }
    ]


def test_synced_pdf_state_changes_preserve_metadata_revision(
    isolated_settings,
    monkeypatch,
):
    service = ArxivService()
    user_id = "sync-state-user"
    meta = PaperMeta(
        arxiv_id="2607.15330",
        title="Synced paper",
        summary="Summary",
        authors=["Author"],
        download_time=datetime.now(),
        download_status="ready",
    )
    paper_dir = isolated_settings.get_user_papers_dir(user_id) / meta.arxiv_id
    _write_meta(isolated_settings, user_id, meta)
    meta_file = paper_dir / "meta.json"
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    data["updated_at"] = "2026-08-17T08:01:01Z"
    meta_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(service, "_ensure_download_task", lambda *args: None)
    monkeypatch.setattr(service, "_ensure_metadata_task", lambda *args: None)

    service.ensure_pdf_for_synced_metadata(user_id, meta.arxiv_id)
    downloading = json.loads(meta_file.read_text(encoding="utf-8"))
    assert downloading["download_status"] == "downloading"
    assert downloading["updated_at"] == "2026-08-17T08:01:01Z"

    (paper_dir / "paper.pdf").write_bytes(b"%PDF-test")
    service.ensure_pdf_for_synced_metadata(user_id, meta.arxiv_id)
    ready = json.loads(meta_file.read_text(encoding="utf-8"))
    assert ready["download_status"] == "ready"
    assert ready["updated_at"] == "2026-08-17T08:01:01Z"


def test_pdf_download_uses_configured_proxy(isolated_settings, monkeypatch, tmp_path):
    captured = {}
    progress = []

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def stream(self, method, url):
            captured["url"] = url
            return _FakeStreamResponse(b"%PDF-proxied")

    monkeypatch.setattr(arxiv_module.settings, "arxiv_proxy_url", "http://127.0.0.1:18080")
    monkeypatch.setattr(arxiv_module.httpx, "Client", FakeClient)

    ArxivService()._download_pdf_stream(
        "https://arxiv.org/pdf/2401.00001",
        tmp_path,
        progress_callback=lambda downloaded, total: progress.append((downloaded, total)),
    )

    assert captured["proxy"] == "http://127.0.0.1:18080"
    assert (tmp_path / "paper.pdf").read_bytes() == b"%PDF-proxied"
    assert progress == [(len(b"%PDF-proxied"), len(b"%PDF-proxied"))]


def test_pdf_download_omits_proxy_when_unconfigured(isolated_settings, monkeypatch, tmp_path):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def stream(self, method, url):
            return _FakeStreamResponse(b"%PDF-direct")

    monkeypatch.setattr(arxiv_module.settings, "arxiv_proxy_url", "")
    monkeypatch.setattr(arxiv_module.httpx, "Client", FakeClient)

    ArxivService()._download_pdf_stream("https://arxiv.org/pdf/2401.00001", tmp_path)

    assert "proxy" not in captured


def test_pdf_download_does_not_proxy_non_arxiv_url(isolated_settings, monkeypatch, tmp_path):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def stream(self, method, url):
            return _FakeStreamResponse(b"%PDF-private")

    monkeypatch.setattr(arxiv_module.settings, "arxiv_proxy_url", "http://127.0.0.1:18080")
    monkeypatch.setattr(arxiv_module.httpx, "Client", FakeClient)

    ArxivService()._download_pdf_stream("https://papers.example/private.pdf", tmp_path)

    assert "proxy" not in captured
