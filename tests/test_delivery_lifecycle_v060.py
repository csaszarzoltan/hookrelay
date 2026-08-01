"""TDD acceptance coverage for v0.6 end-to-end delivery visibility."""
from __future__ import annotations

import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.client import connect_and_forward
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _client(tmp_path):
    store = Storage(str(tmp_path / "delivery.db"))
    _storage.set(store)
    return TestClient(create_app()), store


def test_storage_persists_delivery_attempt_timeline(tmp_path):
    store = Storage(str(tmp_path / "attempts.db"))
    attempt_id = store.store_delivery_attempt(
        request_id="req-1",
        channel="payments",
        target_url="http://localhost:8080/hooks",
        status="delivered",
        response_status=204,
        duration_ms=12.5,
    )
    attempts = store.list_delivery_attempts("req-1")
    assert attempts[0]["attempt_id"] == attempt_id
    assert attempts[0]["response_status"] == 204
    assert attempts[0]["duration_ms"] == 12.5


def test_webhook_is_forwarded_to_connected_channel_client(tmp_path):
    client, _ = _client(tmp_path)
    with client.websocket_connect("/ws/payments") as websocket:
        assert websocket.receive_json()["type"] == "heartbeat"
        response = client.post(
            "/webhook/payments",
            headers={"content-type": "application/json"},
            json={"type": "charge.created"},
        )
        message = websocket.receive_json()
    assert response.status_code == 201
    assert message["type"] == "webhook"
    assert message["data"]["request_id"] == response.json()["request_id"]
    assert message["data"]["body"] == '{"type":"charge.created"}'


def test_delivery_result_from_client_is_persisted_and_available_by_api(tmp_path):
    client, store = _client(tmp_path)
    store.store_request({
        "request_id": "req-result", "channel": "dev", "method": "POST",
        "path": "/hook", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1", "received_at": "2026-08-01T10:00:00+00:00",
    })
    with client.websocket_connect("/ws/dev") as websocket:
        websocket.receive_json()
        websocket.send_json({
            "type": "delivery_result",
            "data": {
                "request_id": "req-result", "target_url": "http://localhost:9000",
                "status": "target_error", "response_status": 500,
                "duration_ms": 31.2, "error": "Internal Server Error",
            },
        })
    response = client.get("/api/requests/req-result/delivery-attempts")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "target_error"
    assert response.json()[0]["response_status"] == 500


def test_forwarding_client_reports_success_to_server():
    socket = Mock()
    socket.recv.side_effect = [json.dumps({
        "type": "webhook", "data": {
            "request_id": "r1", "method": "POST", "path": "/hook",
            "headers": {}, "body": "{}", "query_params": {},
        },
    }), KeyboardInterrupt()]
    with patch("websocket.create_connection", return_value=socket), patch(
        "hookrelay.client.WebSocketClient.forward_to_local",
        return_value={"status": 202, "headers": {}, "body": b"accepted"},
    ):
        try:
            connect_and_forward("ws://server", "dev", "http://localhost:9000")
        except KeyboardInterrupt:
            pass
    report = json.loads(socket.send.call_args_list[-1].args[0])
    assert report["type"] == "delivery_result"
    assert report["data"]["request_id"] == "r1"
    assert report["data"]["status"] == "delivered"
    assert report["data"]["response_status"] == 202


def test_inspector_shows_delivery_timeline(tmp_path):
    client, store = _client(tmp_path)
    store.store_request({
        "request_id": "req-ui", "channel": "dev", "method": "POST",
        "path": "/hook", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1", "received_at": "2026-08-01T10:00:00+00:00",
    })
    store.store_delivery_attempt(
        request_id="req-ui", channel="dev", target_url="http://localhost:9000",
        status="delivered", response_status=200, duration_ms=8.4,
    )
    response = client.get("/dashboard/inspect/req-ui")
    assert response.status_code == 200
    assert "Delivery timeline" in response.text
    assert "Delivered" in response.text
    assert "8.4 ms" in response.text
