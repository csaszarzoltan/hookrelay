"""End-to-end tests for the v1.8.0 multi-destination delivery pipeline.

Covers the four tech-lead review blockers:

* B1 — routing -> transform -> sign -> send is wired into the actual
  delivery path: a webhook ingested on a bin with destinations is
  delivered to the destination URL (via a mocked transport), the
  transformation is applied, signature headers are present, and the
  destination's ``delivered_count`` / ``failed_count`` counters move.
* B2 — there is exactly ONE canonical ``DestinationStore`` (the
  ``hookrelay.routing`` one); ``hookrelay.bins`` re-exports it.
* B3 — ``signing_config`` is validated at the API boundary: unknown
  algorithms and empty secrets are rejected with 422.
* B4 — destination URLs are SSRF-guarded at create/update: private /
  loopback targets are rejected with 422/400.

Delivery tests monkeypatch the HTTP transport inside
:mod:`hookrelay.delivery.dispatcher` so no real network is involved
and the full route -> transform -> sign -> send chain runs in-process.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest
import requests

from hookrelay import _storage
from hookrelay.bins import DestinationStore  # re-exported (B2)
from hookrelay.routing.destination_store import DestinationStore as RoutingStore
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "destinations_delivery.db"))


# ---------------------------------------------------------------------------
# B2 — single canonical DestinationStore
# ---------------------------------------------------------------------------


class TestSingleDestinationStore:
    def test_bins_reexports_routing_store(self):
        """B2: hookrelay.bins.DestinationStore IS the routing one (no dup)."""
        assert DestinationStore is RoutingStore

    def test_bins_module_has_no_own_store_module(self):
        """B2: the duplicate module must be gone."""
        import importlib.util

        assert (
            importlib.util.find_spec("hookrelay.bins.destination_store") is None
        ), "duplicate bins/destination_store.py must be deleted"

    def test_round_robin_mode_allowlist(self, store):
        """B2: the canonical store accepts round_robin and rejects round-robin."""
        import pytest

        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError):
            dst.create(
                "bin-1",
                "https://example.com/hook",
                delivery_mode="round-robin",
            )


# ---------------------------------------------------------------------------
# B4 — SSRF guard on destination create/update (store level)
# ---------------------------------------------------------------------------


class TestDestinationSSRFGuard:
    def test_create_rejects_loopback(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError, match="(?i)ssrf|private|protocol|resolve"):
            dst.create("bin-1", "http://127.0.0.1:8080/steal")

    def test_create_rejects_private_ip(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError):
            dst.create("bin-1", "http://192.168.1.5:9000/hook")

    def test_create_rejects_non_http_scheme(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError):
            dst.create("bin-1", "file:///etc/passwd")

    def test_update_rejects_private_target(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        created = dst.create("bin-1", "https://example.com/hook")
        with pytest.raises(ValueError):
            dst.update(created["destination_id"], url="http://10.0.0.1:8000/hook")

    def test_create_accepts_public_https(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        created = dst.create("bin-1", "https://example.com/hook")
        assert created["url"] == "https://example.com/hook"


# ---------------------------------------------------------------------------
# B3 — signing_config validation at the store boundary
# ---------------------------------------------------------------------------


class TestSigningConfigValidation:
    def test_create_rejects_unknown_algorithm(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError, match="(?i)algorithm"):
            dst.create(
                "bin-1",
                "https://example.com/hook",
                signing_config={"algorithm": "md5", "secret": "whsec_x"},
            )

    def test_create_rejects_empty_secret(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError, match="(?i)secret"):
            dst.create(
                "bin-1",
                "https://example.com/hook",
                signing_config={"algorithm": "github", "secret": ""},
            )

    def test_create_rejects_non_string_secret(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        with pytest.raises(ValueError):
            dst.create(
                "bin-1",
                "https://example.com/hook",
                signing_config={"algorithm": "github", "secret": 12345},
            )

    def test_create_accepts_supported_algorithm(self, store):
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        created = dst.create(
            "bin-1",
            "https://example.com/hook",
            signing_config={"algorithm": "github", "secret": "whsec_valid"},
        )
        assert created["signing_config"]["algorithm"] == "github"


# ---------------------------------------------------------------------------
# B1 — delivery pipeline: route -> transform -> sign -> send
# ---------------------------------------------------------------------------


class _FakeTransport:
    """Records outgoing calls; simulates success or transport failure."""

    def __init__(self, *, fail: bool = False, status_code: int = 200):
        self.fail = fail
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, headers: dict, data: bytes, timeout: float):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "data": data}
        )
        if self.fail:
            raise requests.exceptions.ConnectionError(
                "connection refused by fake transport"
            )

        class _Resp:
            status_code = self.status_code
            text = '{"echo": true}'

        return _Resp()


@pytest.fixture
def dispatcher_module():
    import hookrelay.delivery.dispatcher as disp

    return disp


@pytest.fixture
def allow_destination_ssrf(monkeypatch):
    """Let delivery tests create destinations without DNS dependency.

    Mirrors the ``allow_ssrf`` seam in test_bins.py: only the create-time
    guard is bypassed; the delivery transport is fully mocked anyway.
    """

    def _allow(url, allow_private=False, allowed_protocols=None):
        return True, None

    import hookrelay.routing.destination_store as dst_mod

    monkeypatch.setattr(dst_mod, "validate_target_url", _allow, raising=False)


def _make_bin(store: Storage, bin_id: str = "bin-e2e") -> None:
    store.create_bin(bin_id, "e2e bin", "2026-08-10T00:00:00+00:00")


def _make_transform(store: Storage, filters: list[str]) -> str:
    from hookrelay.transforms.store import TransformationStore

    return TransformationStore(store).create("e2e-transform", filters)["transform_id"]


class TestDeliveryPipeline:
    def test_ingest_routes_transforms_signs_and_increments_delivered(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """B1 e2e #1: full delivery chain with delivered_count increment."""
        _make_bin(store)
        transform_id = _make_transform(store, [".env = \"prod\"", "del(.token)"])
        from hookrelay.routing.destination_store import DestinationStore as DS

        dest = DS(store).create(
            "bin-e2e",
            "https://example.com/hook",
            transform_id=transform_id,
            signing_config={"algorithm": "github", "secret": "whsec_e2e"},
            headers={"X-Source": "hookrelay"},
        )
        transport = _FakeTransport()
        # No SSRF in the delivery path: destination URLs were already
        # validated at create time; the transport is fully mocked.
        with mock.patch.object(
            dispatcher_module.requests, "request", autospec=True
        ) as fake_request:
            fake_request.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request

            request_id = store.store_request(
                {
                    "request_id": "req-e2e-1",
                    "channel": "bin-e2e",
                    "method": "POST",
                    "path": "/",
                    "headers": {"Content-Type": "application/json"},
                    "body": b'{"event": "invoice.paid", "token": "sk_live_1"}',
                    "query_params": {},
                    "source_ip": "203.0.113.1",
                    "received_at": "2026-08-10T00:00:00+00:00",
                }
            )
            results = deliver_captured_request("bin-e2e", request_id, store)

        assert len(results) == 1
        assert results[0]["destination_id"] == dest["destination_id"]
        assert results[0]["status"] == "delivered"
        assert results[0]["status_code"] == 200

        # 1) delivered to the destination URL
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["url"] == "https://example.com/hook"
        assert call["method"] == "POST"

        # 2) transform applied to the payload
        sent_body = json.loads(call["data"])
        assert sent_body["env"] == "prod"
        assert "token" not in sent_body

        # 3) signature headers present
        assert "x-hookrelay-signature" in call["headers"]
        assert "x-hookrelay-timestamp" in call["headers"]
        # 4) destination extra headers attached
        assert call["headers"]["X-Source"] == "hookrelay"

        # 5) delivered_count incremented, failed_count untouched
        record = DS(store).get(dest["destination_id"])
        assert record["delivered_count"] == 1
        assert record["failed_count"] == 0

        # 6) a delivery attempt row was persisted (dashboard feed)
        attempts = store.list_delivery_attempts(request_id)
        assert len(attempts) == 1
        assert attempts[0]["endpoint_id"] == dest["destination_id"]
        assert attempts[0]["status"] == "delivered"

    def test_failed_delivery_increments_failed_count(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """B1 e2e #2: transport failure -> failed_count incremented."""
        _make_bin(store)
        from hookrelay.routing.destination_store import DestinationStore as DS

        dest = DS(store).create("bin-e2e", "https://example.com/hook")
        transport = _FakeTransport(fail=True)
        with mock.patch.object(
            dispatcher_module.requests, "request", autospec=True
        ) as fake_request:
            fake_request.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request

            request_id = store.store_request(
                {
                    "request_id": "req-e2e-2",
                    "channel": "bin-e2e",
                    "method": "POST",
                    "path": "/",
                    "headers": {},
                    "body": b'{"event": "x"}',
                    "query_params": {},
                    "source_ip": "203.0.113.1",
                    "received_at": "2026-08-10T00:00:00+00:00",
                }
            )
            results = deliver_captured_request("bin-e2e", request_id, store)

        assert len(results) == 1
        assert results[0]["status"] == "failed"
        record = DS(store).get(dest["destination_id"])
        assert record["failed_count"] == 1
        assert record["delivered_count"] == 0
        attempts = store.list_delivery_attempts(request_id)
        assert attempts[0]["status"] == "transport_error"
        assert "connection refused" in (attempts[0]["error"] or "")

    def test_no_destinations_returns_empty(self, store, dispatcher_module):
        """A bin without destinations is not delivered anywhere."""
        _make_bin(store)
        from hookrelay.delivery.dispatcher import deliver_captured_request

        request_id = store.store_request(
            {
                "request_id": "req-e2e-3",
                "channel": "bin-e2e",
                "method": "POST",
                "path": "/",
                "headers": {},
                "body": b"{}",
                "query_params": {},
                "source_ip": "203.0.113.1",
                "received_at": "2026-08-10T00:00:00+00:00",
            }
        )
        assert deliver_captured_request("bin-e2e", request_id, store) == []

    def test_round_robin_delivers_to_exactly_one(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Round-robin mode picks a single destination per event."""
        _make_bin(store)
        from hookrelay.routing.destination_store import DestinationStore as DS

        dst = DS(store)
        dst.create(
            "bin-e2e", "https://a.example.com/hook", delivery_mode="round_robin"
        )
        dst.create(
            "bin-e2e", "https://b.example.com/hook", delivery_mode="round_robin"
        )
        transport = _FakeTransport()
        with mock.patch.object(
            dispatcher_module.requests, "request", autospec=True
        ) as fake_request:
            fake_request.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request

            request_id = store.store_request(
                {
                    "request_id": "req-e2e-4",
                    "channel": "bin-e2e",
                    "method": "POST",
                    "path": "/",
                    "headers": {},
                    "body": b"{}",
                    "query_params": {},
                    "source_ip": "203.0.113.1",
                    "received_at": "2026-08-10T00:00:00+00:00",
                }
            )
            results = deliver_captured_request("bin-e2e", request_id, store)

        assert len(results) == 1
        assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# B3 + B4 — API boundary validation (server.py)
# ---------------------------------------------------------------------------


class TestDestinationApiValidation:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from hookrelay.server import create_app

        store = Storage(str(tmp_path / "dest_api.db"))
        _storage.set(store)
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
        return TestClient(create_app()), store

    def test_api_rejects_loopback_url(self, client):
        """B4 e2e #3: SSRF rejection on destination create -> 422."""
        c, _ = client
        resp = c.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-1", "url": "http://127.0.0.1:8080/steal"},
        )
        assert resp.status_code in (400, 422)

    def test_api_rejects_unknown_signing_algorithm(self, client):
        """B3: unknown algorithm -> 422."""
        c, _ = client
        resp = c.post(
            "/api/v1/destinations",
            json={
                "bin_id": "bin-1",
                "url": "https://example.com/hook",
                "signing_config": {"algorithm": "md5", "secret": "whsec_x"},
            },
        )
        assert resp.status_code == 422

    def test_api_rejects_empty_signing_secret(self, client):
        """B3: empty secret -> 422."""
        c, _ = client
        resp = c.post(
            "/api/v1/destinations",
            json={
                "bin_id": "bin-1",
                "url": "https://example.com/hook",
                "signing_config": {"algorithm": "github", "secret": "  "},
            },
        )
        assert resp.status_code == 422

    def test_api_accepts_valid_destination(self, client):
        """Sanity: a valid public destination with signing is accepted."""
        c, _ = client
        resp = c.post(
            "/api/v1/destinations",
            json={
                "bin_id": "bin-1",
                "url": "https://example.com/hook",
                "signing_config": {"algorithm": "github", "secret": "whsec_ok"},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["signing_config"]["algorithm"] == "github"
