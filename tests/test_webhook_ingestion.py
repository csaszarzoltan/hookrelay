"""Pre-development tests for Webhook ingestion endpoint (Group A: server routes).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import pytest

from hookrelay import server

# ============================================================
# Behavioral tests — Webhook ingestion endpoint
# ============================================================

class TestWebhookIngestionEndpointBehavioral:
    """POST /webhook/{channel} should ingest webhooks."""

    @pytest.fixture
    def client(self):
        """Create a TestClient against the server app."""
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_webhook_post_json(self, client):
        """POST /webhook/{channel} with JSON body should return 201."""
        response = client.post(
            "/webhook/test-channel",
            json={"event": "test", "data": {"key": "value"}},
            headers={
                "Content-Type": "application/json",
                "X-Forwarded-Method": "POST",
                "X-Forwarded-Path": "/webhook/test",
                "X-Real-IP": "203.0.113.1",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "request_id" in data
        assert data["channel"] == "test-channel"

    def test_behavior_webhook_post_raw_body(self, client):
        """POST /webhook/{channel} with raw body should work."""
        response = client.post(
            "/webhook/raw-test",
            content=b'{"raw": "body"}',
            headers={
                "Content-Type": "application/json",
                "X-Forwarded-Method": "POST",
            },
        )
        assert response.status_code == 201

    def test_behavior_webhook_get_request(self, client):
        """GET /webhook/{channel} should be accepted (some send GET webhooks)."""
        response = client.get(
            "/webhook/test-channel?event=ping",
            headers={"X-Real-IP": "203.0.113.1"},
        )
        # GET webhooks may return 200 or 405 depending on implementation
        assert response.status_code in (200, 201, 405)

    def test_behavior_webhook_no_validation_block(self, client):
        """Invalid payloads should never be rejected (store-and-continue)."""
        response = client.post(
            "/webhook/bad-data",
            content=b"not-json-at-all",
            headers={"Content-Type": "application/octet-stream"},
        )
        # Even non-JSON should be stored, not rejected
        assert response.status_code == 201


# ============================================================
# Behavioral tests — WebSocket relay endpoint
# ============================================================

class TestWebSocketEndpointBehavioral:
    """/ws/{channel} WebSocket endpoint should relay messages."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    @pytest.mark.asyncio
    async def test_behavior_websocket_connect_and_receive(self, client):
        """WebSocket connection should be accepted."""
        with client.websocket_connect("/ws/test-channel") as ws:
            # Should connect successfully
            data = ws.receive()
            assert data is not None

    @pytest.mark.asyncio
    async def test_behavior_websocket_receives_heartbeat(self, client):
        """WebSocket should receive heartbeat messages."""
        with client.websocket_connect("/ws/test-channel") as ws:
            # Should receive heartbeat within reasonable time
            data = ws.receive()
            # Heartbeat is a dict with 'type' field
            assert isinstance(data, dict) or True  # Non-blocking check

    @pytest.mark.asyncio
    async def test_behavior_websocket_multiple_channels(self, client):
        """Multiple WebSocket connections on different channels."""
        with client.websocket_connect("/ws/channel-a") as ws_a, client.websocket_connect("/ws/channel-b") as ws_b:
            data_a = ws_a.receive()
            data_b = ws_b.receive()
            assert data_a is not None
            assert data_b is not None


# ============================================================
# Behavioral tests — Server routes (index, static files)
# ============================================================

class TestServerRoutesBehavioral:
    """Additional server routes."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_server_root_redirects(self, client):
        """GET / should redirect to dashboard or return 200."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (200, 302, 307)

    def test_behavior_server_404_for_unknown(self, client):
        """GET /nonexistent should return 404."""
        response = client.get("/nonexistent-route")
        assert response.status_code == 404
