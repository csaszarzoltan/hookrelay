"""Tests for transformation audit trail (before/after payload capture).

Covers:
  - No transform → NULL audit fields
  - Transform applied → both payloads stored
  - Audit fields retrievable via list_delivery_attempts
  - Non-JSON payload → audit fields NULL
  - Transform failure still captures before payload

Run: python -m pytest tests/test_transformation_audit_trail.py -v
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest import mock

import pytest
import requests

from hookrelay import _storage
from hookrelay.storage import Storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "transform_audit.db"))


@pytest.fixture
def dispatcher_module():
    import hookrelay.delivery.dispatcher as disp
    return disp


@pytest.fixture
def allow_destination_ssrf(monkeypatch):
    def _allow(url, allow_private=False, allowed_protocols=None):
        return True, None

    import hookrelay.routing.destination_store as dst_mod
    monkeypatch.setattr(dst_mod, "validate_target_url", _allow, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bin(store: Storage, bin_id: str = "bin-audit") -> None:
    store.create_bin(bin_id, "audit test bin", datetime.now(UTC).isoformat())


def _make_transform(store: Storage, filters: list[str]) -> str:
    from hookrelay.transforms.store import TransformationStore
    return TransformationStore(store).create("audit-transform", filters)["transform_id"]


def _store_request(
    store: Storage,
    request_id: str = "req-audit-1",
    body: bytes | None = None,
    channel: str = "bin-audit",
) -> str:
    return store.store_request(
        {
            "request_id": request_id,
            "channel": channel,
            "method": "POST",
            "path": "/",
            "headers": {"Content-Type": "application/json"},
            "body": body or b'{"event": "test", "token": "sk_secret"}',
            "query_params": {},
            "source_ip": "10.0.0.1",
            "received_at": datetime.now(UTC).isoformat(),
        }
    )


class _FakeTransport:
    """Records outgoing calls; returns 200 or raises on failure."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, headers: dict, data: bytes, timeout: float):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "data": data}
        )
        if self.fail:
            raise requests.exceptions.ConnectionError("connection refused")

        class _Resp:
            status_code = 200
            text = '{"ok": true}'
        return _Resp()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNoTransformNoAuditFields:
    """No transform → transform_before and transform_after are NULL."""

    def test_no_transform_null_audit(self, store, dispatcher_module, allow_destination_ssrf):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        # Destination without transform_id
        dest = DS(store).create("bin-audit", "https://example.com/hook")
        transport = _FakeTransport()
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-audit", req_id, store)

        assert results[0]["status"] == "delivered"

        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1
        assert attempts[0]["transform_before"] is None
        assert attempts[0]["transform_after"] is None


class TestTransformCapturesBeforeAfter:
    """Transform applied → both payloads stored."""

    def test_transform_applied_captures_both_payloads(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        transform_id = _make_transform(store, ['del(.token)'])
        dest = DS(store).create(
            "bin-audit",
            "https://example.com/hook",
            transform_id=transform_id,
        )
        transport = _FakeTransport()
        req_id = _store_request(
            store,
            body=b'{"event": "invoice.paid", "token": "sk_live_xxx"}',
        )

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-audit", req_id, store)

        assert results[0]["status"] == "delivered"

        # Verify the transform was applied to the sent payload
        sent_body = json.loads(transport.calls[0]["data"])
        assert "token" not in sent_body
        assert sent_body["event"] == "invoice.paid"

        # Verify audit trail
        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1

        before = json.loads(attempts[0]["transform_before"])
        after = json.loads(attempts[0]["transform_after"])

        # Before: original payload with token
        assert before["token"] == "sk_live_xxx"
        assert before["event"] == "invoice.paid"

        # After: transformed payload without token
        assert "token" not in after
        assert after["event"] == "invoice.paid"


class TestAuditFieldsInDeliveryAttemptQuery:
    """Audit fields are retrievable via store.list_delivery_attempts."""

    def test_queryable(self, store, dispatcher_module, allow_destination_ssrf):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        transform_id = _make_transform(store, ['del(.token)'])
        dest = DS(store).create(
            "bin-audit",
            "https://example.com/hook",
            transform_id=transform_id,
        )
        transport = _FakeTransport()
        req_id = _store_request(
            store,
            body=b'{"event": "test", "token": "secret_key"}',
        )

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-audit", req_id, store)

        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1
        attempt = attempts[0]

        # Both fields are bytes (BLOB)
        assert isinstance(attempt["transform_before"], bytes)
        assert isinstance(attempt["transform_after"], bytes)
        assert attempt["transform_before"] != attempt["transform_after"]

        # Verify they parse as valid JSON
        before = json.loads(attempt["transform_before"])
        after = json.loads(attempt["transform_after"])
        assert "token" in before
        assert "token" not in after


class TestNonJsonPayloadNoAudit:
    """Binary forwarded payloads → audit fields NULL."""

    def test_binary_payload_null_audit(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        transform_id = _make_transform(store, ['del(.token)'])
        dest = DS(store).create(
            "bin-audit",
            "https://example.com/hook",
            transform_id=transform_id,
        )
        transport = _FakeTransport()
        # Binary (non-JSON) payload
        req_id = _store_request(
            store,
            body=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR',
        )

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-audit", req_id, store)

        assert results[0]["status"] == "delivered"

        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1
        # Binary payloads are forwarded byte-exact; transform doesn't change them
        assert attempts[0]["transform_before"] is None
        assert attempts[0]["transform_after"] is None


class TestTransformFailureStillCapturesBefore:
    """Raw payload captured even on delivery failure with transform."""

    def test_failed_delivery_with_transform_captures_audit(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        transform_id = _make_transform(store, ['del(.token)'])
        dest = DS(store).create(
            "bin-audit",
            "https://example.com/hook",
            transform_id=transform_id,
        )
        transport = _FakeTransport(fail=True)
        req_id = _store_request(
            store,
            body=b'{"event": "test", "token": "secret_key"}',
        )

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-audit", req_id, store)

        assert results[0]["status"] == "failed"

        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "transport_error"

        # Even on failure, audit trail should capture the payloads
        assert attempts[0]["transform_before"] is not None
        assert attempts[0]["transform_after"] is not None

        before = json.loads(attempts[0]["transform_before"])
        after = json.loads(attempts[0]["transform_after"])
        assert before["token"] == "secret_key"
        assert "token" not in after
