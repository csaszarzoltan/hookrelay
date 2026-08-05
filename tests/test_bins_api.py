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
from typing import ClassVar

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


# ============================================================
# Regression tests — review blockers B1/B3 + M1 (task t_5a54ccb2)
# ============================================================


class _RecordingEchoHandler(BaseHTTPRequestHandler):
    """Echo server that records the raw method/headers/body it receives."""

    seen: ClassVar[list[dict]] = []

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        type(self).seen.append(
            {
                "method": self.command,
                "headers": {k: v for k, v in self.headers.items()},
                "body": body,
            }
        )
        payload = json.dumps({"echo": True, "method": self.command}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_POST = _handle
    do_PUT = _handle
    do_GET = _handle
    do_DELETE = _handle

    def log_message(self, format, *args):  # keep test output clean
        pass


@pytest.fixture
def recording_echo_server():
    _RecordingEchoHandler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingEchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


class TestForwardRegressionB1:
    """B1: the forward endpoint must not block the event loop.

    Regression test uses a SINGLE event loop (httpx.ASGITransport), the same
    model as production: a slow forward target must not stall other
    endpoints. Starlette's TestClient spins up a fresh event loop per request,
    which would mask the blocking bug, so it is deliberately not used here.
    """

    async def test_slow_forward_does_not_block_health(
        self, tmp_path, monkeypatch
    ):
        import asyncio
        import time

        import httpx

        import hookrelay.bins.forward as forward_mod

        class _SlowHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
                time.sleep(2.0)
                payload = b'{"echo": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):  # keep test output clean
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            slow_url = f"http://127.0.0.1:{server.server_address[1]}/slow"
            monkeypatch.setattr(
                forward_mod,
                "validate_target_url",
                lambda url, **kw: (True, None),
                raising=False,
            )
            store = Storage(str(tmp_path / "bins_b1.db"))
            _storage.set(store)
            monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)

            transport = httpx.ASGITransport(app=create_app())
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                created = (await client.post("/api/bins", json={})).json()
                captured = (
                    await client.post(created["url"], content=b"{}")
                ).json()

                forward_task = asyncio.create_task(
                    client.post(
                        f"/api/bins/{created['bin_id']}/requests/"
                        f"{captured['request_id']}/forward",
                        json={"target_url": slow_url},
                    )
                )
                # Let the forward reach the slow handler (it sleeps 2s), then
                # check /health is still served promptly on the same loop.
                await asyncio.sleep(0.4)
                started = time.perf_counter()
                health = await client.get("/health")
                elapsed = time.perf_counter() - started
                assert health.status_code == 200
                assert elapsed < 1.0, (
                    f"GET /health took {elapsed:.2f}s while a forward was in "
                    "flight — the forward endpoint is blocking the event loop"
                )
                # The decisive check: /health must be served WHILE the forward
                # is still running. If the endpoint blocks the loop, /health
                # can only respond after the forward completes.
                assert not forward_task.done(), (
                    "/health was only served after the forward finished — the "
                    "forward endpoint is blocking the event loop"
                )
                forward_response = await forward_task
                assert forward_response.status_code == 200
                assert forward_response.json()["status_code"] == 200
        finally:
            server.shutdown()
            thread.join(timeout=5)


class TestForwardRegressionB3Api:
    """B3 via the API: captured binary bytes must round-trip byte-identical."""

    def test_api_forward_preserves_binary_body(
        self, tmp_path, monkeypatch, recording_echo_server
    ):
        import hookrelay.bins.forward as forward_mod

        monkeypatch.setattr(
            forward_mod,
            "validate_target_url",
            lambda url, **kw: (True, None),
            raising=False,
        )
        client, _ = _client(tmp_path, monkeypatch)
        bin_info = _create_bin(client)
        payload = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x01\xff\xfe"
        captured = client.post(
            bin_info["url"],
            content=payload,
            headers={"Content-Type": "application/octet-stream"},
        ).json()
        response = client.post(
            f"/api/bins/{bin_info['bin_id']}/requests/"
            f"{captured['request_id']}/forward",
            json={"target_url": f"{recording_echo_server}/receive"},
        )
        assert response.status_code == 200
        assert len(_RecordingEchoHandler.seen) == 1
        assert _RecordingEchoHandler.seen[0]["body"] == payload


class TestBinsDashboardForwardRegressionM1:
    """M1: the Bins page must actually implement click-to-forward."""

    def test_bins_page_implements_click_to_forward(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        page = client.get("/dashboard/bins").text
        # The live-feed Forward link carries both request id and bin id...
        assert "&bin=" in page
        # ...and the page JS reads the query params, renders a forward form
        # with a target-URL input, and POSTs to the forward endpoint.
        assert "URLSearchParams" in page
        assert "bins-forward" in page
        assert "forward-target-url" in page
        assert "/forward" in page
