"""Pre-development tests for hookrelay Webhook Capture Bins (v1.6.0).

Library-level coverage (models, BinService, forward, dashboard helpers):

- Interface tests (imports, signatures, type hints, dataclass contract):
  pass immediately against the stubs in ``src/hookrelay/bins/``.
- Behavioral tests: fail (RED) until the developer implements the feature.

Endpoint (REST/WS) tests live in ``tests/test_bins_api.py``; CLI tests in
``tests/test_bins_cli.py``. Follows the existing ``tests/test_<module>.py``
pre-dev pattern used across the repo (interface PASS + behavioral RED).
"""

from __future__ import annotations

import inspect
import json
import threading
from dataclasses import fields, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, get_type_hints

import pytest

from hookrelay import _storage
from hookrelay.bins import (
    Bin,
    BinNotFoundError,
    BinRequestNotFoundError,
    BinService,
    CapturedRequest,
    ForwardError,
    ForwardResult,
    forward_captured_request,
)
from hookrelay.bins import api as bins_api
from hookrelay.bins import dashboard as bins_dashboard
from hookrelay.bins import service as bins_service
from hookrelay.ssrf import SSRFError
from hookrelay.storage import Storage

pytestmark = pytest.mark.asyncio


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "bins.db"))


@pytest.fixture
def seeded_store(store) -> Storage:
    """A store with a bin_id used as the webhooks channel (dev contract)."""
    store.store_request(
        {
            "request_id": "req-captured-1",
            "channel": "bin-demo-1",
            "method": "POST",
            "path": "/",
            "headers": {"Content-Type": "application/json", "X-Custom": "yes"},
            "body": b'{"event": "invoice.paid"}',
            "query_params": {"src": "stripe"},
            "source_ip": "203.0.113.42",
            "received_at": "2026-08-05T00:00:00+00:00",
        }
    )
    return store


class _EchoHandler(BaseHTTPRequestHandler):
    """Records method/headers/body and echoes them back (for forward tests)."""

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
        payload = json.dumps(
            {"echo": True, "method": self.command, "body": body.decode("utf-8", "replace")}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle

    def log_message(self, format, *args):  # keep test output clean
        pass


@pytest.fixture
def echo_server():
    _EchoHandler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def allow_ssrf(monkeypatch):
    """Test seam: let the forward code reach a local echo server.

    Only the SSRF guard is bypassed — the HTTP round-trip itself is real.
    The SSRF *block* path is tested separately with the real guard.
    """

    def _allow(url, allow_private=False, allowed_protocols=None):
        return True, None

    import hookrelay.bins.forward as forward_mod
    import hookrelay.ssrf as ssrf_mod

    monkeypatch.setattr(forward_mod, "validate_target_url", _allow, raising=False)
    monkeypatch.setattr(ssrf_mod, "validate_target_url", _allow, raising=False)


# ============================================================
# Interface tests — models (dataclass contract)
# ============================================================


class TestModelsInterface:
    """The three models are dataclasses with the documented fields."""

    def test_bin_is_dataclass(self):
        assert is_dataclass(Bin)

    def test_bin_fields(self):
        names = {f.name for f in fields(Bin)}
        assert {"bin_id", "url", "created_at"} <= names
        assert "description" in names
        assert "request_count" in names

    def test_bin_defaults(self):
        b = Bin(bin_id="b1", url="http://relay/bin/b1", created_at="2026-08-05T00:00:00Z")
        assert b.description is None
        assert b.request_count == 0

    def test_captured_request_is_dataclass(self):
        assert is_dataclass(CapturedRequest)

    def test_captured_request_fields(self):
        names = {f.name for f in fields(CapturedRequest)}
        assert {
            "request_id", "bin_id", "method", "headers", "body",
            "query_params", "source_ip", "received_at",
        } <= names
        assert "path" in names

    def test_captured_request_defaults(self):
        r = CapturedRequest(
            request_id="r1", bin_id="b1", method="POST",
            headers={}, body=b"", query_params={}, source_ip="1.2.3.4",
            received_at="2026-08-05T00:00:00Z",
        )
        assert r.path == "/"

    def test_forward_result_is_dataclass(self):
        assert is_dataclass(ForwardResult)

    def test_forward_result_fields(self):
        names = {f.name for f in fields(ForwardResult)}
        assert {"request_id", "target_url", "status_code", "latency_ms", "response_body"} <= names
        assert "error" in names

    def test_forward_result_defaults(self):
        r = ForwardResult(
            request_id="r1", target_url="https://example.com/h",
            status_code=200, latency_ms=12.5, response_body="ok",
        )
        assert r.error is None


# ============================================================
# Interface tests — BinService
# ============================================================


class TestBinServiceInterface:
    def test_exported_from_package(self):
        assert BinService is bins_service.BinService

    def test_bin_not_found_error_is_exception(self):
        assert issubclass(BinNotFoundError, Exception)

    def test_init_signature(self):
        sig = inspect.signature(BinService.__init__)
        assert "storage" in sig.parameters

    def test_create_bin_signature(self):
        sig = inspect.signature(BinService.create_bin)
        assert "description" in sig.parameters
        assert sig.parameters["description"].default is None

    def test_create_bin_returns_bin(self):
        hints = get_type_hints(BinService.create_bin)
        assert hints["return"] is Bin

    def test_get_bin_signature(self):
        sig = inspect.signature(BinService.get_bin)
        assert "bin_id" in sig.parameters

    def test_list_bins_returns_list_of_bin(self):
        hints = get_type_hints(BinService.list_bins)
        assert hints["return"] == list[Bin]

    def test_delete_bin_signature(self):
        sig = inspect.signature(BinService.delete_bin)
        assert "bin_id" in sig.parameters
        hints = get_type_hints(BinService.delete_bin)
        assert hints["return"] is bool

    def test_capture_signature(self):
        sig = inspect.signature(BinService.capture)
        assert {"bin_id", "method", "headers", "body", "query_params", "source_ip"} <= set(
            sig.parameters
        )

    def test_capture_returns_captured_request(self):
        hints = get_type_hints(BinService.capture)
        assert hints["return"] is CapturedRequest

    def test_list_requests_signature(self):
        sig = inspect.signature(BinService.list_requests)
        assert "bin_id" in sig.parameters
        assert sig.parameters["limit"].default == 20
        assert sig.parameters["offset"].default == 0

    def test_list_requests_returns_dict(self):
        hints = get_type_hints(BinService.list_requests)
        assert "dict" in str(hints["return"])

    def test_get_request_signature(self):
        sig = inspect.signature(BinService.get_request)
        assert {"bin_id", "request_id"} <= set(sig.parameters)


# ============================================================
# Interface tests — forward
# ============================================================


class TestForwardInterface:
    def test_forward_errors_are_exceptions(self):
        assert issubclass(ForwardError, Exception)
        assert issubclass(BinRequestNotFoundError, ForwardError)

    def test_forward_captured_request_signature(self):
        sig = inspect.signature(forward_captured_request)
        params = sig.parameters
        assert {"bin_id", "request_id", "target_url", "storage"} <= set(params)
        assert params["timeout"].default == 30.0

    def test_forward_returns_forward_result(self):
        hints = get_type_hints(forward_captured_request)
        assert hints["return"] is ForwardResult


# ============================================================
# Interface tests — api + dashboard helpers
# ============================================================


class TestBinsApiInterface:
    def test_build_public_bin_url_signature(self):
        sig = inspect.signature(bins_api.build_public_bin_url)
        assert {"base_url", "bin_id"} <= set(sig.parameters)

    def test_build_public_bin_url_returns_str(self):
        hints = get_type_hints(bins_api.build_public_bin_url)
        assert hints["return"] is str

    def test_create_bins_router_signature(self):
        sig = inspect.signature(bins_api.create_bins_router)
        assert sig.parameters == {}


class TestBinsDashboardInterface:
    def test_broadcast_bin_capture_is_async(self):
        assert inspect.iscoroutinefunction(bins_dashboard.broadcast_bin_capture)

    def test_broadcast_bin_capture_signature(self):
        sig = inspect.signature(bins_dashboard.broadcast_bin_capture)
        assert {"manager", "captured"} <= set(sig.parameters)

    def test_create_bins_dashboard_router_signature(self):
        sig = inspect.signature(bins_dashboard.create_bins_dashboard_router)
        assert sig.parameters == {}


# ============================================================
# Behavioral tests — BinService (RED until implemented)
# ============================================================


class TestBinServiceBehavioral:
    """Create/list/delete bins, capture, paginated listing, full payload."""

    def test_create_bin_returns_public_url(self, store):
        service = BinService(store)
        created = service.create_bin("webhook testing")
        assert isinstance(created, Bin)
        assert "/bin/" in created.url
        assert created.url.endswith(created.bin_id)
        assert created.bin_id

    def test_create_bin_urls_are_unique(self, store):
        service = BinService(store)
        first = service.create_bin()
        second = service.create_bin()
        assert first.bin_id != second.bin_id
        assert first.url != second.url

    def test_get_bin_returns_created_bin(self, store):
        service = BinService(store)
        created = service.create_bin("desc")
        fetched = service.get_bin(created.bin_id)
        assert fetched is not None
        assert fetched.bin_id == created.bin_id
        assert fetched.url == created.url

    def test_get_bin_missing_returns_none(self, store):
        service = BinService(store)
        assert service.get_bin("no-such-bin") is None

    def test_list_bins_returns_created_bins(self, store):
        service = BinService(store)
        service.create_bin("one")
        service.create_bin("two")
        bins = service.list_bins()
        assert len(bins) == 2
        assert {b.description for b in bins} == {"one", "two"}

    def test_delete_bin_removes_it(self, store):
        service = BinService(store)
        created = service.create_bin()
        assert service.delete_bin(created.bin_id) is True
        assert service.get_bin(created.bin_id) is None

    def test_delete_missing_bin_returns_false(self, store):
        service = BinService(store)
        assert service.delete_bin("no-such-bin") is False

    def test_capture_persists_without_ws_client(self, store):
        """AC1 core: capture works with no WebSocket client connected."""
        service = BinService(store)
        created = service.create_bin()
        captured = service.capture(
            bin_id=created.bin_id,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=b'{"hello": "world"}',
            query_params={"foo": "bar"},
            source_ip="203.0.113.7",
        )
        assert isinstance(captured, CapturedRequest)
        assert captured.bin_id == created.bin_id
        listing = service.list_requests(created.bin_id)
        assert listing["total"] == 1
        assert listing["items"][0]["request_id"] == captured.request_id

    def test_capture_records_full_request_fields(self, store):
        service = BinService(store)
        created = service.create_bin()
        captured = service.capture(
            bin_id=created.bin_id,
            method="PUT",
            headers={"Content-Type": "text/plain", "X-Trace": "t-1"},
            body=b"raw payload",
            query_params={"a": "1", "b": "2"},
            source_ip="198.51.100.9",
        )
        assert captured.method == "PUT"
        assert captured.headers == {"Content-Type": "text/plain", "X-Trace": "t-1"}
        assert captured.body == b"raw payload"
        assert captured.query_params == {"a": "1", "b": "2"}
        assert captured.source_ip == "198.51.100.9"
        # timestamp is an ISO-8601 string
        datetime.fromisoformat(captured.received_at)

    def test_capture_unknown_bin_raises(self, store):
        service = BinService(store)
        with pytest.raises(BinNotFoundError):
            service.capture(
                bin_id="ghost-bin",
                method="POST",
                headers={},
                body=b"",
                query_params=None,
                source_ip="1.2.3.4",
            )

    def test_list_requests_pagination(self, store):
        service = BinService(store)
        created = service.create_bin()
        for i in range(5):
            service.capture(
                bin_id=created.bin_id,
                method="POST",
                headers={},
                body=f"req-{i}".encode(),
                query_params=None,
                source_ip="1.2.3.4",
            )
        page1 = service.list_requests(created.bin_id, limit=2, offset=0)
        assert page1["total"] == 5
        assert len(page1["items"]) == 2
        page2 = service.list_requests(created.bin_id, limit=2, offset=2)
        assert len(page2["items"]) == 2
        last = service.list_requests(created.bin_id, limit=2, offset=4)
        assert len(last["items"]) == 1

    def test_list_requests_empty_bin(self, store):
        service = BinService(store)
        created = service.create_bin()
        listing = service.list_requests(created.bin_id)
        assert listing == {"items": [], "total": 0}

    def test_get_request_full_payload(self, store):
        service = BinService(store)
        created = service.create_bin()
        service.capture(
            bin_id=created.bin_id,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=b'{"event": "paid"}',
            query_params={"src": "stripe"},
            source_ip="203.0.113.42",
        )
        listing = service.list_requests(created.bin_id)
        request_id = listing["items"][0]["request_id"]
        detail = service.get_request(created.bin_id, request_id)
        assert detail is not None
        assert detail["method"] == "POST"
        assert detail["headers"] == {"Content-Type": "application/json"}
        assert detail["query_params"] == {"src": "stripe"}
        assert detail["source_ip"] == "203.0.113.42"
        assert "received_at" in detail
        # body may be bytes or str depending on storage decode — either is fine
        assert detail["body"] in (b'{"event": "paid"}', '{"event": "paid"}')

    def test_get_request_missing_returns_none(self, store):
        service = BinService(store)
        created = service.create_bin()
        assert service.get_request(created.bin_id, "no-such-request") is None

    def test_get_request_wrong_bin_returns_none(self, store):
        service = BinService(store)
        created = service.create_bin()
        service.capture(
            bin_id=created.bin_id, method="POST", headers={}, body=b"",
            query_params=None, source_ip="1.2.3.4",
        )
        listing = service.list_requests(created.bin_id)
        request_id = listing["items"][0]["request_id"]
        other = service.create_bin()
        assert service.get_request(other.bin_id, request_id) is None


# ============================================================
# Behavioral tests — forward (RED until implemented)
# ============================================================


class TestForwardBehavioral:
    def test_forward_ssrf_blocks_private_target(self, store, seeded_store):
        """Real SSRF guard: 127.0.0.1 must be rejected (no seam here)."""
        with pytest.raises((ValueError, SSRFError)):
            forward_captured_request(
                bin_id="bin-demo-1",
                request_id="req-captured-1",
                target_url="http://127.0.0.1:8080/steal",
                storage=seeded_store,
            )

    def test_forward_blocks_system_port(self, store, seeded_store):
        with pytest.raises((ValueError, SSRFError)):
            forward_captured_request(
                bin_id="bin-demo-1",
                request_id="req-captured-1",
                target_url="http://example.com:80/webhook",
                storage=seeded_store,
            )

    def test_forward_success_records_status_latency_body(
        self, seeded_store, echo_server, allow_ssrf
    ):
        result = forward_captured_request(
            bin_id="bin-demo-1",
            request_id="req-captured-1",
            target_url=f"{echo_server}/target",
            storage=seeded_store,
        )
        assert isinstance(result, ForwardResult)
        assert result.request_id == "req-captured-1"
        assert result.target_url == f"{echo_server}/target"
        assert result.status_code == 200
        assert result.latency_ms >= 0
        assert "echo" in result.response_body

    def test_forward_preserves_method_headers_body(
        self, seeded_store, echo_server, allow_ssrf
    ):
        forward_captured_request(
            bin_id="bin-demo-1",
            request_id="req-captured-1",
            target_url=f"{echo_server}/forward",
            storage=seeded_store,
        )
        assert len(_EchoHandler.seen) == 1
        seen = _EchoHandler.seen[0]
        assert seen["method"] == "POST"
        assert seen["headers"].get("X-Custom") == "yes"
        assert seen["body"] == b'{"event": "invoice.paid"}'

    def test_forward_unknown_request_raises(self, store):
        with pytest.raises((BinRequestNotFoundError, SSRFError)):
            forward_captured_request(
                bin_id="bin-demo-1",
                request_id="missing-request",
                target_url="https://example.com/hook",
                storage=store,
            )


# ============================================================
# Behavioral tests — dashboard live-feed helpers (RED until implemented)
# ============================================================


class TestBinsDashboardBehavioral:
    async def test_broadcast_bin_capture_pushes_live_message(self):
        from hookrelay.dashboard.connection_manager import ConnectionManager

        received: list[str] = []

        class FakeWebSocket:
            async def send_text(self, payload: str) -> None:
                received.append(payload)

        manager = ConnectionManager()
        manager._connections.append(FakeWebSocket())  # type: ignore[arg-type]

        captured = CapturedRequest(
            request_id="req-1",
            bin_id="bin-1",
            method="POST",
            headers={},
            body=b"{}",
            query_params={},
            source_ip="203.0.113.7",
            received_at="2026-08-05T00:00:00+00:00",
        )
        await bins_dashboard.broadcast_bin_capture(manager, captured)

        assert len(received) == 1
        message = json.loads(received[0])
        assert message["bin_id"] == "bin-1"
        assert message["request_id"] == "req-1"


# ============================================================
# Regression tests — review blockers B2/B3 (task t_5a54ccb2)
# ============================================================


class TestForwardRegressionB2:
    """B2: forward must not replay stale Host/Content-Length/hop-by-hop headers.

    The captured headers belong to the ORIGINAL sender; replaying them
    verbatim sends ``Host: stale-original-host`` to the target (broken
    virtual-host routing) and a Content-Length that no longer matches the
    replayed body. The forward must strip those and let ``requests``
    recompute them from the target URL and body.
    """

    def test_forward_uses_target_host_and_recomputed_content_length(
        self, store, echo_server, allow_ssrf
    ):
        from urllib.parse import urlparse

        payload = b'{"event": "invoice.paid"}'
        store.store_request(
            {
                "request_id": "req-b2-stale-headers",
                "channel": "bin-b2",
                "method": "POST",
                "path": "/",
                "headers": {
                    "Host": "stale-original-host:9999",
                    "Content-Length": "5",  # deliberately stale (body is 27B)
                    "Connection": "keep-alive",
                    "X-Custom": "kept",
                },
                "body": payload,
                "query_params": {},
                "source_ip": "203.0.113.42",
                "received_at": "2026-08-05T00:00:00+00:00",
            }
        )
        target = f"{echo_server}/b2"
        forward_captured_request(
            bin_id="bin-b2",
            request_id="req-b2-stale-headers",
            target_url=target,
            storage=store,
        )
        assert len(_EchoHandler.seen) == 1
        seen = _EchoHandler.seen[0]
        # The echo server must see ITS OWN host:port, not the stale original.
        assert seen["headers"].get("Host") == urlparse(target).netloc
        # Content-Length must match the replayed body, not the stale value.
        assert int(seen["headers"].get("Content-Length", 0)) == len(payload)
        # The captured body itself is still forwarded intact.
        assert seen["body"] == payload
        # Non-stale custom headers are preserved.
        assert seen["headers"].get("X-Custom") == "kept"


class TestForwardRegressionB3:
    """B3: forward must replay the exact stored bytes, not a lossy decode.

    ``BinService.get_request`` decodes the stored BLOB as UTF-8 with
    ``errors="replace"``, which irreversibly corrupts binary payloads
    (image/gzip/protobuf) before they are re-encoded for the target.
    Forwarding must use the raw stored bytes.
    """

    def test_forward_preserves_binary_body_byte_for_byte(
        self, store, echo_server, allow_ssrf
    ):
        payload = b"\x00\x01\xff\xfe\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        store.store_request(
            {
                "request_id": "req-b3-binary",
                "channel": "bin-b3",
                "method": "POST",
                "path": "/",
                "headers": {"Content-Type": "application/octet-stream"},
                "body": payload,
                "query_params": {},
                "source_ip": "203.0.113.42",
                "received_at": "2026-08-05T00:00:00+00:00",
            }
        )
        forward_captured_request(
            bin_id="bin-b3",
            request_id="req-b3-binary",
            target_url=f"{echo_server}/b3",
            storage=store,
        )
        assert len(_EchoHandler.seen) == 1
        assert _EchoHandler.seen[0]["body"] == payload
