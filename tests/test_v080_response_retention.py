from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.client import connect_and_forward
from hookrelay.server import create_app
from hookrelay.storage import Storage


def request_record(request_id: str, days_old: int = 0) -> dict:
    return {
        "request_id": request_id, "channel": "dev", "method": "POST",
        "path": "/hook", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": (datetime.now(UTC) - timedelta(days=days_old)).isoformat(),
    }


def test_response_capture_is_redacted_and_bounded(tmp_path):
    store = Storage(str(tmp_path / "capture.db"))
    store.store_request(request_record("r1"))
    store.store_delivery_attempt(
        "r1", "dev", "target_error", response_status=500,
        response_headers={"Authorization": "secret", "Content-Type": "text/plain"},
        response_body="x" * 20000,
    )
    result = store.list_delivery_attempts("r1")[0]
    assert result["response_headers"]["Authorization"] == "••••••••"
    assert result["response_headers"]["Content-Type"] == "text/plain"
    assert len(result["response_body"].encode()) <= 16384
    assert result["response_body_truncated"] is True


def test_forwarding_client_reports_response_details():
    socket = Mock()
    socket.recv.side_effect = [json.dumps({
        "type": "webhook", "data": {
            "request_id": "r2", "method": "POST", "path": "/hook",
            "headers": {}, "body": "{}", "query_params": {},
        },
    }), KeyboardInterrupt()]
    response = {
        "status": 500,
        "headers": {"Set-Cookie": "session=secret", "Content-Type": "text/plain"},
        "body": b"failure details",
    }
    with patch("websocket.create_connection", return_value=socket), patch(
        "hookrelay.client.WebSocketClient.forward_to_local", return_value=response,
    ):
        try:
            connect_and_forward("ws://server", "dev", "http://localhost:9000")
        except KeyboardInterrupt:
            pass
    report = json.loads(socket.send.call_args_list[-1].args[0])["data"]
    assert report["status"] == "target_error"
    assert report["response_headers"]["Set-Cookie"] == "••••••••"
    assert report["response_body"] == "failure details"


def test_retention_setting_and_manual_purge(tmp_path):
    store = Storage(str(tmp_path / "retention.db"))
    _storage.set(store)
    client = TestClient(create_app())
    store.store_request(request_record("old", 40))
    store.store_request(request_record("new", 1))
    assert client.put("/api/settings/retention", json={"days": 30}).json()["days"] == 30
    assert client.get("/api/settings/retention").json()["days"] == 30
    result = client.post("/api/settings/retention/purge")
    assert result.json()["deleted"] == 1
    assert store.get_request("old") is None
    assert store.get_request("new") is not None


def test_settings_page_has_retention_controls(tmp_path):
    store = Storage(str(tmp_path / "settings.db"))
    _storage.set(store)
    page = TestClient(create_app()).get("/dashboard/settings")
    assert page.status_code == 200
    assert 'id="retention-days"' in page.text
    assert 'id="save-retention"' in page.text
    assert 'id="purge-now"' in page.text

def test_app_startup_applies_configured_retention(tmp_path):
    store = Storage(str(tmp_path / "startup.db"))
    store.store_request(request_record("expired", 20))
    store.set_setting("retention_days", 7)
    _storage.set(store)
    create_app()
    assert store.get_request("expired") is None
