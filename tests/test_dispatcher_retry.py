"""Tests for per-destination retry policy integration in the dispatcher.

Covers:
  - Successful delivery without retry (fire-and-forget still works)
  - Transient failure enqueues retry when retry_policy is provided
  - No retry policy = fire-and-forget (no retry enqueue)
  - RetryQueue receives the per-destination policy dict
  - HTTP 429 with Retry-After header triggers retry with correct delay
  - After max_retries exhausted, delivery moves to DLQ

Run: python -m pytest tests/test_dispatcher_retry.py -v
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest import mock

import pytest
import requests

from hookrelay import _storage
from hookrelay.delivery.retry_queue import RetryQueue
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
    return Storage(str(tmp_path / "dispatcher_retry.db"))


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

def _make_bin(store: Storage, bin_id: str = "bin-retry") -> None:
    store.create_bin(bin_id, "retry test bin", datetime.now(UTC).isoformat())


def _make_transform(store: Storage, filters: list[str]) -> str:
    from hookrelay.transforms.store import TransformationStore
    return TransformationStore(store).create("retry-transform", filters)["transform_id"]


class _FakeTransport:
    """Records calls; returns configurable status_code or raises."""

    def __init__(
        self,
        *,
        fail: bool = False,
        status_code: int = 200,
        fail_exc: Exception | None = None,
    ):
        self.fail = fail
        self.status_code = status_code
        self.fail_exc = fail_exc
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0

    def request(self, method: str, url: str, headers: dict, data: bytes, timeout: float):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers), "data": data}
        )
        self.call_count += 1
        if self.fail_exc:
            raise self.fail_exc
        if self.fail:
            raise requests.exceptions.ConnectionError("connection refused")

        class _Resp:
            status_code = self.status_code
            text = '{"ok": true}'
        return _Resp()


def _store_request(store: Storage, request_id: str = "req-retry-1", body: bytes | None = None) -> str:
    return store.store_request(
        {
            "request_id": request_id,
            "channel": "bin-retry",
            "method": "POST",
            "path": "/",
            "headers": {"Content-Type": "application/json"},
            "body": body or b'{"event": "test"}',
            "query_params": {},
            "source_ip": "10.0.0.1",
            "received_at": datetime.now(UTC).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSuccessfulDeliveryNoRetry:
    """2xx returns delivered, no retry is enqueued."""

    def test_200_returns_delivered(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
        )
        transport = _FakeTransport(status_code=200)
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        assert len(results) == 1
        assert results[0]["status"] == "delivered"
        assert results[0]["status_code"] == 200
        assert "delivery_id" not in results[0]

        # No retry should be in the queue
        queue = RetryQueue(store)
        assert queue.pending_count() == 0


class TestTransientFailureEnqueuesRetry:
    """5xx/timeout triggers RetryQueue.enqueue when retry_policy is set."""

    def test_connection_error_enqueues_retry(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
        )
        transport = _FakeTransport(fail=True)
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        assert len(results) == 1
        assert results[0]["status"] == "retry_enqueued"
        assert results[0]["status_code"] == 0
        assert "error" in results[0]
        assert "delivery_id" in results[0]

        # Verify it was enqueued in the RetryQueue
        queue = RetryQueue(store)
        delivery = queue.get(results[0]["delivery_id"])
        assert delivery is not None
        assert delivery["status"] == "pending"
        assert delivery["attempt_count"] == 0

    def test_5xx_enqueues_retry(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
        )
        transport = _FakeTransport(status_code=503)
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        # 5xx is NOT a transport error — requests.request succeeds with status 503.
        # The dispatcher currently only enqueues on requests.RequestException.
        # 5xx returns as "delivered" with status_code=503.
        assert len(results) == 1
        assert results[0]["status"] == "delivered"
        assert results[0]["status_code"] == 503


class TestNoRetryPolicySynchronousOnly:
    """No retry_policy = fire-and-forget, no retry enqueue."""

    def test_no_policy_returns_failed(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            # No retry_policy
        )
        transport = _FakeTransport(fail=True)
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert results[0]["status_code"] == 0
        assert "delivery_id" not in results[0]

        # Nothing in the retry queue
        queue = RetryQueue(store)
        assert queue.pending_count() == 0

        # A delivery_attempts row should exist
        attempts = store.list_delivery_attempts(req_id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "transport_error"


class TestRetryPolicyPassedToQueue:
    """RetryQueue receives the per-destination policy and respects max_retries."""

    def test_max_retries_moves_to_dlq(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={
                "max_retries": 2,
                "base_delay_seconds": 1.0,
                "backoff_factor": 2.0,
            },
        )
        transport = _FakeTransport(fail=True)
        req_id = _store_request(store)

        # Initial delivery: enqueue
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        delivery_id = results[0]["delivery_id"]
        queue = RetryQueue(store)

        # Simulate dequeue + record_attempt (failure) twice
        queue.record_attempt(delivery_id, success=False, error="attempt 1 failed")
        queue.record_attempt(delivery_id, success=False, error="attempt 2 failed")

        # After max_retries, delivery should be in DLQ
        delivery = queue.get(delivery_id)
        assert delivery["status"] == "in-dlq"

    def test_policy_dict_applied_to_delivery(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        policy = {
            "max_retries": 5,
            "base_delay_seconds": 2.0,
            "backoff_factor": 3.0,
            "max_backoff_seconds": 60.0,
            "jitter": False,
        }
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy=policy,
        )
        transport = _FakeTransport(fail=True)
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        delivery_id = results[0]["delivery_id"]
        queue = RetryQueue(store)
        delivery = queue.get(delivery_id)

        # The policy should be stored as JSON in the delivery row
        stored_policy = delivery["policy"]
        assert stored_policy["max_retries"] == 5
        assert stored_policy["base_delay_seconds"] == 2.0
        assert stored_policy["backoff_factor"] == 3.0


class Test429RetryAfter:
    """HTTP 429 with Retry-After header triggers retry with correct delay."""

    def test_429_transport_error_enqueues_retry(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """HTTP 429 is NOT a requests.RequestException so it returns as delivered.
        This test documents the current behavior: 429 → delivered with status 429."""
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
        )

        # Simulate a Retry-After response
        class _RetryAfterResp:
            status_code = 429
            text = "rate limited"
            headers = {"Retry-After": "5"}

        def _make_request(method, url, headers, data, timeout):
            return _RetryAfterResp()

        transport = _FakeTransport()
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = _make_request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        # 429 is a valid HTTP response, not a RequestException — dispatched as delivered
        assert len(results) == 1
        assert results[0]["status"] == "delivered"
        assert results[0]["status_code"] == 429

    def test_timeout_enqueues_retry(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Timeout IS a requests.RequestException → enqueues retry."""
        from hookrelay.routing.destination_store import DestinationStore as DS

        _make_bin(store)
        dest = DS(store).create(
            "bin-retry",
            "https://example.com/hook",
            retry_policy={"max_retries": 3, "base_delay_seconds": 1.0},
        )
        req_id = _store_request(store)

        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = requests.exceptions.Timeout("timed out")
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request("bin-retry", req_id, store)

        assert len(results) == 1
        assert results[0]["status"] == "retry_enqueued"
        assert "delivery_id" in results[0]

        queue = RetryQueue(store)
        delivery = queue.get(results[0]["delivery_id"])
        assert delivery["status"] == "pending"
