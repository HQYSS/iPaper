import httpx
import pytest

from main import create_app
from middleware.auth import get_current_user
from routers import papers as papers_router


@pytest.fixture(autouse=True)
def clear_open_requests():
    papers_router._pending_open_papers.clear()
    yield
    papers_router._pending_open_papers.clear()


@pytest.mark.asyncio
async def test_electron_open_request_is_durable_and_targeted(monkeypatch):
    monkeypatch.setattr(papers_router.arxiv_service, "get_paper", lambda *_: object())
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "open-request-user",
        "username": "test",
        "is_admin": False,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        queued = await client.post(
            "/api/papers/open-request",
            json={"paper_id": "2608.00001", "target": "electron"},
        )
        request_id = queued.json()["request_id"]

        web_request = await client.get("/api/papers/open-request?target=web")
        first_electron_read = await client.get("/api/papers/open-request?target=electron")
        second_electron_read = await client.get("/api/papers/open-request?target=electron")

        assert web_request.json()["paper_id"] is None
        assert first_electron_read.json() == second_electron_read.json()
        assert first_electron_read.json() == {
            "paper_id": "2608.00001",
            "request_id": request_id,
            "target": "electron",
        }

        wrong_ack = await client.post(
            "/api/papers/open-request/ack",
            json={"request_id": "wrong-request"},
        )
        still_pending = await client.get("/api/papers/open-request?target=electron")
        acknowledged = await client.post(
            "/api/papers/open-request/ack",
            json={"request_id": request_id},
        )
        consumed = await client.get("/api/papers/open-request?target=electron")

    assert wrong_ack.json()["paper_id"] is None
    assert still_pending.json()["request_id"] == request_id
    assert acknowledged.json()["request_id"] == request_id
    assert consumed.json()["paper_id"] is None


@pytest.mark.asyncio
async def test_open_request_expires(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(papers_router.time, "monotonic", lambda: now)
    monkeypatch.setattr(papers_router.arxiv_service, "get_paper", lambda *_: object())
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "expiry-user",
        "username": "test",
        "is_admin": False,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        await client.post(
            "/api/papers/open-request",
            json={"paper_id": "2608.00002", "target": "electron"},
        )
        now += papers_router._OPEN_REQUEST_TTL_SECONDS + 1
        expired = await client.get("/api/papers/open-request?target=electron")

    assert expired.json()["paper_id"] is None
