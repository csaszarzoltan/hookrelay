"""Acceptance tests for the v0.5 daily-debugging dashboard improvements."""
from pathlib import Path

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _client(tmp_path):
    store = Storage(str(tmp_path / "ux.db"))
    _storage.set(store)
    return TestClient(create_app()), store


def test_dashboard_exposes_live_connection_status(tmp_path):
    client, _ = _client(tmp_path)
    response = client.get("/dashboard/")
    assert response.status_code == 200
    assert 'id="connection-status"' in response.text
    assert 'aria-live="polite"' in response.text
    assert 'id="pause-live"' in response.text


def test_live_script_updates_rows_without_page_reload():
    script = Path("src/hookrelay/dashboard/static/dashboard.js").read_text(encoding="utf-8")
    assert "window.location.reload" not in script
    assert "insertLiveRequest" in script
    assert "reconnectAttempts" in script


def test_dashboard_status_api_reports_monitor_and_relay_state(tmp_path):
    client, _ = _client(tmp_path)
    response = client.get("/api/dashboard/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["dashboard_connections"], int)
    assert isinstance(body["relay_channels"], dict)


def test_history_filters_include_path_and_preserve_state(tmp_path):
    client, store = _client(tmp_path)
    for request_id, path in (("one", "/stripe/charge"), ("two", "/github/push")):
        store.store_request({
            "request_id": request_id,
            "channel": "dev",
            "method": "POST",
            "path": path,
            "headers": {},
            "body": b"{}",
            "query_params": {},
            "source_ip": "127.0.0.1",
            "received_at": "2026-08-01T09:00:00+00:00",
        })
    response = client.get("/dashboard/history?channel=dev&method=POST&path=stripe&limit=1")
    assert response.status_code == 200
    assert "/stripe/charge" in response.text
    assert "/github/push" not in response.text
    assert 'name="path"' in response.text
    assert "channel=dev" in response.text
    assert "path=stripe" in response.text


def test_replay_uses_stored_channel_and_returns_actionable_no_client(tmp_path):
    client, store = _client(tmp_path)
    store.store_request({
        "request_id": "replay-me",
        "channel": "payments",
        "method": "POST",
        "path": "/event",
        "headers": {},
        "body": b"{}",
        "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": "2026-08-01T09:00:00+00:00",
    })
    response = client.post("/api/replay/replay-me", json={})
    assert response.status_code == 409
    assert response.json()["channel"] == "payments"
    assert response.json()["code"] == "no_connected_client"


def test_inspector_masks_sensitive_headers(tmp_path):
    client, store = _client(tmp_path)
    store.store_request({
        "request_id": "secret",
        "channel": "dev",
        "method": "POST",
        "path": "/event",
        "headers": {"authorization": "Bearer very-secret", "x-event": "safe"},
        "body": b"{}",
        "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": "2026-08-01T09:00:00+00:00",
    })
    response = client.get("/dashboard/inspect/secret")
    assert "Bearer very-secret" not in response.text
    assert "••••••••" in response.text
    assert "safe" in response.text
