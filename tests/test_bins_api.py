"""Pre-development endpoint tests for Webhook Capture Bins (v1.6.0).

REST + WebSocket coverage against the real FastAPI app
(:func:`hookrelay.server.create_app`):

- Interface tests (router factory signatures): pass immediately.
- Behavioral tests: RED until the developer registers the bins router in
  ``create_app`` (endpoints 404 today), then green after implementation.

Expected routes (contract, see ``hookrelay/bins/api.py``):

  * ``/bin/{bin_id}``                                capture (GET/POST/PUT/PATCH/DELETE)
  * ``POST /api/bins``, ``GET /api/bins``, ``DELETE /api/bins/{bin_id}``
  * ``GET /api/bins/{bin_id}/requests``              paginated listing
  * ``GET /api/bins/{bin_id}/requests/{request_id}`` full payload view
  * ``POST /api/bins/{bin_id}/requests/{request_id}/forward``  one-click forward
  * ``GET /dashboard/bins``                          Bins view page
"""

from __future__ import annotations

import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.bins import api as bins_api
from hookrelay.server import create_app
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _client(tmp_path, monkeypatch):
    store = Storage(str(tmp_path / "bins_api.db"))
    _storage.set(store)
    monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
    return TestClient(create_app()), store


def _create_bin(client) -> dict:
    response = client.post("/api/bins", json={"description": "test bin"})
    assert response.status_code == 201, response.text
    return response.json()


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        payload = json.dumps({"echo": True, "body": body.decode("utf-8", "replace")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # keep test output clean
        pass


@pytest.fixture
def echo_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


def _receive_with_timeout(ws, timeout: float = 5.0):
    """receive_text() with a hard timeout so a missing broadcast can never hang."""

    def _recv():
        result["value"] = ws.receive_text()

    result: dict = {}
    thread = threading.Thread(target=_recv, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None
    return result.get("value")


# ============================================================
# Interface tests — bins API module
# ============================================================


class TestBinsApiModuleInterface:
    def test_build_public_bin_url_exists(self):
        assert callable(bins_api.build_public_bin_url)

    def test_build_public_bin_url_signature(self):
        sig = inspect.signature(bins_api.build_public_bin_url)
        assert {"base_url", "bin_id"} <= set(sig.parameters)

    def test_create_bins_router_exists(self):
        assert callable(bins_api.create_bins_router)

    def test_create_bins_router_signature(self):
        assert inspect.signature(bins_api.create_bins_router).parameters == {}


# ============================================================
# Behavioral — capture endpoint /bin/{bin_id}
# ============================================================


class TestBinCaptureEndpoint:
    def test_post_captures_and_persists(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        response = client.post(
            bin_info["url"],
            content=b'{"event": "created"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in (200, 201)

        listing = client.get(f"/api/bins/{bin_info['bin_id']}/requests").json()
        assert listing["total"] == 1
        item = listing["items"][0]
        assert item["method"] == "POST"
        assert item["headers"].get("content-type") in (
            "application/json",
            "application/json; charset=utf-8",
        )
        assert item["body"] in ('{"event": "created"}', b'{"event": "created"}')

    def test_all_http_methods_captured(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        for method, body in (
            ("POST", b'{"a": 1}'),
            ("GET", None),
            ("PUT", b'{"b": 2}'),
            ("DELETE", None),
        ):
            response = client.request(method, bin_info["url"], content=body)
            assert response.status_code in (200, 201), (method, response.text)

        listing = client.get(f"/api/bins/{bin_info['bin_id']}/requests").json()
        assert listing["total"] == 4
        assert {item["method"] for item in listing["items"]} == {
            "POST", "GET", "PUT", "DELETE",
        }

    def test_capture_records_query_params(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        client.post(f"{bin_info['url']}?foo=bar&n=42", content=b"{}")
        listing = client.get(f"/api/bins/{bin_info['bin_id']}/requests").json()
        assert listing["items"][0]["query_params"] == {"foo": "bar", "n": "42"}

    def test_capture_records_source_ip_and_timestamp(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        client.post(
            bin_info["url"],
            content=b"{}",
            headers={"X-Real-IP": "203.0.113.99"},
        )
        item = client.get(f"/api/bins/{bin_info['bin_id']}/requests").json()["items"][0]
        assert item["source_ip"] == "203.0.113.99"
        assert item["received_at"]

    def test_capture_persists_with_no_ws_client_connected(self, tmp_path, monkeypatch):
        """AC1: capture must persist without any WebSocket client."""
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        # NOTE: no websocket_connect anywhere in this test
        response = client.post(bin_info["url"], content=b'{"ping": true}')
        assert response.status_code in (200, 201)
        assert "request_id" in response.json()
        listing = client.get(f"/api/bins/{bin_info['bin_id']}/requests").json()
        assert listing["total"] == 1
        assert listing["items"][0]["request_id"] == response.json()["request_id"]

    def test_capture_unknown_bin_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/bin/no-such-bin", content=b"{}")
        assert response.status_code == 404


# ============================================================
# Behavioral — bin management API
# ============================================================


class TestBinsManagementApi:
    def test_create_bin_returns_public_url(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/bins", json={"description": "test bin"})
        assert response.status_code == 201
        data = response.json()
        assert data["bin_id"]
        assert "/bin/" in data["url"]
        assert data["url"].endswith(data["bin_id"])

    def test_create_bin_without_description(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/bins", json={})
        assert response.status_code == 201
        assert response.json()["bin_id"]

    def test_list_bins_returns_created(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        _create_bin(client)
        _create_bin(client)
        listing = client.get("/api/bins")
        assert listing.status_code == 200
        assert len(listing.json()) == 2

    def test_delete_bin_removes_it(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        response = client.delete(f"/api/bins/{bin_info['bin_id']}")
        assert response.status_code in (200, 204)
        assert client.get("/api/bins").json() == []

    def test_delete_missing_bin_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        assert client.delete("/api/bins/ghost").status_code == 404

    def test_list_requests_pagination(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        for i in range(5):
            client.post(bin_info["url"], content=f"payload-{i}".encode())

        page = client.get(f"/api/bins/{bin_info['bin_id']}/requests?limit=2&offset=0").json()
        assert page["total"] == 5
        assert len(page["items"]) == 2
        page3 = client.get(f"/api/bins/{bin_info['bin_id']}/requests?limit=2&offset=4").json()
        assert len(page3["items"]) == 1

    def test_get_request_full_payload_view(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        created = client.post(
            bin_info["url"],
            content=b'{"event": "invoice.paid"}',
            headers={"X-Custom": "yes"},
        ).json()
        detail = client.get(
            f"/api/bins/{bin_info['bin_id']}/requests/{created['request_id']}"
        )
        assert detail.status_code == 200
        data = detail.json()
        assert data["method"] == "POST"
        assert data["headers"].get("x-custom") == "yes"
        assert data["body"] in ('{"event": "invoice.paid"}', b'{"event": "invoice.paid"}')
        assert "received_at" in data
        assert "source_ip" in data

    def test_get_request_missing_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        response = client.get(f"/api/bins/{bin_info['bin_id']}/requests/ghost")
        assert response.status_code == 404


# ============================================================
# Behavioral — forward endpoint
# ============================================================


class TestForwardApi:
    def test_forward_ssrf_blocks_private_target(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        captured = client.post(bin_info["url"], content=b"{}").json()
        response = client.post(
            f"/api/bins/{bin_info['bin_id']}/requests/{captured['request_id']}/forward",
            json={"target_url": "http://127.0.0.1:8080/internal"},
        )
        assert response.status_code in (400, 422)
        assert "error" in response.json()

    def test_forward_requires_target_url(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        captured = client.post(bin_info["url"], content=b"{}").json()
        response = client.post(
            f"/api/bins/{bin_info['bin_id']}/requests/{captured['request_id']}/forward",
            json={},
        )
        assert response.status_code in (400, 422)

    def test_forward_success_records_result(
        self, tmp_path, monkeypatch, echo_server
    ):
        # Test seam: allow the local echo server through the SSRF guard.
        # The HTTP round-trip itself is real; the SSRF block path is tested
        # above with the real guard.
        import hookrelay.bins.forward as forward_mod

        monkeypatch.setattr(
            forward_mod, "validate_target_url", lambda url, **kw: (True, None),
            raising=False,
        )
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        captured = client.post(
            bin_info["url"],
            content=b'{"event": "forwarded"}',
            headers={"Content-Type": "application/json"},
        ).json()
        response = client.post(
            f"/api/bins/{bin_info['bin_id']}/requests/{captured['request_id']}/forward",
            json={"target_url": f"{echo_server}/receive"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["status_code"] == 200
        assert result["latency_ms"] >= 0
        assert "echo" in result["response_body"]

    def test_forward_missing_request_returns_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        response = client.post(
            f"/api/bins/{bin_info['bin_id']}/requests/ghost/forward",
            json={"target_url": "https://example.com/hook"},
        )
        assert response.status_code == 404


# ============================================================
# Behavioral — dashboard Bins view + live WS feed
# ============================================================


class TestBinsDashboardView:
    def test_bins_page_is_served(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/dashboard/bins")
        assert response.status_code == 200
        assert "Bins" in response.text

    def test_capture_is_broadcast_to_live_feed(self, tmp_path, monkeypatch):
        """AC4: live request feed reuses /dashboard/ws/live connection manager."""
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        with client.websocket_connect("/dashboard/ws/live") as ws:
            response = client.post(bin_info["url"], content=b'{"live": true}')
            assert response.status_code in (200, 201)
            captured = response.json()

            message = _receive_with_timeout(ws)
            assert message is not None, "no live-feed broadcast received"
            data = json.loads(message)
            assert data.get("bin_id") == bin_info["bin_id"]
            assert data.get("request_id") == captured["request_id"]
