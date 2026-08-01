from config import settings
from middleware.auth import _is_local_mode


def test_server_role_never_enables_local_auth_bypass(monkeypatch):
    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "local_auth_bypass", True)
    monkeypatch.setattr(settings, "sync_role", "server")

    assert _is_local_mode() is False


def test_client_role_can_explicitly_enable_local_auth_bypass(monkeypatch):
    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "local_auth_bypass", True)
    monkeypatch.setattr(settings, "sync_role", "client")

    assert _is_local_mode() is True
