"""TDD acceptance tests for optional dashboard and API authentication."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _client(tmp_path, monkeypatch, token: str | None = "correct-token"):
    store = Storage(str(tmp_path / "auth.db"))
    _storage.set(store)
    if token is None:
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HOOKRELAY_API_TOKEN", token)
    return TestClient(create_app())


def test_local_mode_remains_open_without_configured_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, None)
    assert client.get("/dashboard/").status_code == 200
    assert client.get("/api/settings/retention").status_code == 200


def test_protected_dashboard_redirects_to_login(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard/login")
    login = client.get("/dashboard/login")
    assert login.status_code == 200
    assert 'id="access-token"' in login.text


def test_login_sets_secure_session_and_logout_revokes_it(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    rejected = client.post("/dashboard/login", data={"token": "wrong"})
    assert rejected.status_code == 401
    accepted = client.post(
        "/dashboard/login", data={"token": "correct-token"}, follow_redirects=False
    )
    assert accepted.status_code == 303
    assert "hookrelay_session=" in accepted.headers["set-cookie"]
    assert "HttpOnly" in accepted.headers["set-cookie"]
    assert "SameSite=strict" in accepted.headers["set-cookie"]
    assert client.get("/dashboard/").status_code == 200
    logout = client.post("/dashboard/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert client.get("/dashboard/", follow_redirects=False).status_code == 303


def test_api_accepts_bearer_token_and_rejects_missing_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/api/settings/retention").status_code == 401
    response = client.get(
        "/api/settings/retention",
        headers={"Authorization": "Bearer correct-token"},
    )
    assert response.status_code == 200


def test_health_webhook_and_static_assets_remain_public(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200
    assert client.get("/dashboard/static/style.css").status_code == 200
    webhook = client.post("/webhook/public-provider", json={"event": "created"})
    assert webhook.status_code == 201


def test_relay_websocket_requires_token_when_auth_enabled(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    try:
        with client.websocket_connect("/ws/dev"):
            raise AssertionError("unauthenticated websocket connected")
    except Exception:
        pass
    with client.websocket_connect("/ws/dev?token=correct-token") as websocket:
        assert websocket.receive_json()["type"] == "heartbeat"


def test_forwarding_client_uses_environment_token(monkeypatch):
    from unittest.mock import Mock, patch

    from hookrelay.client import connect_and_forward

    monkeypatch.setenv("HOOKRELAY_API_TOKEN", "client-token")
    socket = Mock()
    socket.recv.side_effect = [KeyboardInterrupt()]
    with patch("websocket.create_connection", return_value=socket) as create_connection:
        try:
            connect_and_forward("ws://server", "dev", "http://localhost:9000")
        except KeyboardInterrupt:
            pass
    assert create_connection.call_args.kwargs["header"][0] == "Authorization: Bearer client-token"
