"""Acceptance tests for the v1.5 REST delivery / DLQ / dashboard-metrics API.

Covers the REST surface that exposes the v1.5.0 library-only delivery
infrastructure:

- GET  /api/deliveries                (list with status/endpoint filters)
- POST /api/deliveries                (enqueue with SSRF + idempotency)
- POST /api/deliveries/{id}/attempts  (record an attempt)
- GET  /api/dlq                       (list dead-letter entries)
- POST /api/dlq/{entry_id}/requeue    (requeue a dead-letter entry)
- GET  /api/dashboard/metrics         (DashboardService summary + series)

Auth: the endpoints are covered by the existing optional HOOKRELAY_API_TOKEN
middleware, so with a token configured they require Bearer auth and in local
open mode they are reachable without one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.delivery import DeadLetterQueue, RetryQueue
from hookrelay.server import create_app
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _client(tmp_path, monkeypatch, token: str | None = None):
    store = Storage(str(tmp_path / "api.db"))
    _storage.set(store)
    if token is None:
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HOOKRELAY_API_TOKEN", token)
    return TestClient(create_app()), store


def _enqueue_payload(**overrides) -> dict:
    payload = {
        "request_id": "req-0001",
        "endpoint_id": "ep-0001",
        "target_url": "https://example.com/hook",
        "method": "POST",
        "headers": {"Content-Type": "application/json"},
        "body": '{"event": "created"}',
        "idempotency_key": None,
    }
    payload.update(overrides)
    return payload


# ============================================================
# GET /api/deliveries
# ============================================================


class TestDeliveriesList:
    def test_empty_list_returns_empty_array(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/deliveries")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_enqueued_deliveries(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        RetryQueue(store).enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST",
            headers={}, body=b"{}",
        )
        RetryQueue(store).enqueue(
            delivery_id="dlv-2", request_id="req-2", endpoint_id="ep-2",
            target_url="https://example.org/hook", method="POST",
            headers={}, body=None,
        )
        response = client.get("/api/deliveries")
        assert response.status_code == 200
        items = response.json()
        assert {item["delivery_id"] for item in items} == {"dlv-1", "dlv-2"}
        assert all(item["status"] == "pending" for item in items)
        # headers are parsed back to a dict
        assert items[0]["headers"] == {}

    def test_filters_by_status_and_endpoint(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        queue.enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        queue.enqueue(
            delivery_id="dlv-2", request_id="req-2", endpoint_id="ep-2",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        queue.record_attempt("dlv-1", success=True)

        by_status = client.get("/api/deliveries?status=delivered").json()
        assert [item["delivery_id"] for item in by_status] == ["dlv-1"]

        by_endpoint = client.get("/api/deliveries?endpoint_id=ep-2").json()
        assert [item["delivery_id"] for item in by_endpoint] == ["dlv-2"]

    def test_invalid_status_rejected(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/deliveries?status=bogus")
        assert response.status_code == 422

    def test_limit_is_respected(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        for i in range(5):
            queue.enqueue(
                delivery_id=f"dlv-{i}", request_id=f"req-{i}", endpoint_id="ep-1",
                target_url="https://example.com/hook", method="POST", headers={}, body=None,
            )
        response = client.get("/api/deliveries?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2


# ============================================================
# POST /api/deliveries (enqueue)
# ============================================================


class TestDeliveriesEnqueue:
    def test_enqueue_creates_pending_delivery(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/deliveries", json=_enqueue_payload())
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["endpoint_id"] == "ep-0001"
        assert body["target_url"] == "https://example.com/hook"
        assert "delivery_id" in body

    def test_enqueue_accepts_explicit_delivery_id(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        payload = _enqueue_payload(delivery_id="dlv-custom")
        response = client.post("/api/deliveries", json=payload)
        assert response.status_code == 201
        assert response.json()["delivery_id"] == "dlv-custom"

    def test_enqueue_ssrf_guard_rejects_private_target(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/deliveries", json=_enqueue_payload(target_url="http://127.0.0.1:9000/hook")
        )
        assert response.status_code == 422
        assert "ssrf" in response.json()["detail"].lower() or "private" in response.json()["detail"].lower()

    def test_enqueue_idempotency_duplicate_rejected(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        payload = _enqueue_payload(idempotency_key="key-dup")
        assert client.post("/api/deliveries", json=payload).status_code == 201
        duplicate = client.post("/api/deliveries", json=payload)
        assert duplicate.status_code == 422
        assert "idempotency" in duplicate.json()["detail"].lower()

    def test_enqueue_missing_required_fields_rejected(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/deliveries", json={"endpoint_id": "ep-1"})
        assert response.status_code == 422

    def test_enqueue_accepts_policy_dict(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        payload = _enqueue_payload(policy={"max_retries": 2, "jitter": False})
        response = client.post("/api/deliveries", json=payload)
        assert response.status_code == 201
        assert response.json()["policy"]["max_retries"] == 2

    def test_enqueue_records_audit_event(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        client.post("/api/deliveries", json=_enqueue_payload())
        events = store.list_audit_events(limit=10, action="delivery.enqueue")
        assert len(events) == 1


# ============================================================
# POST /api/deliveries/{id}/attempts
# ============================================================


class TestDeliveriesAttempts:
    def test_record_success_attempt(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        RetryQueue(store).enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        response = client.post(
            "/api/deliveries/dlv-1/attempts",
            json={"success": True, "response_status": 200, "duration_ms": 12.5},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "delivered"

    def test_record_failure_schedules_retry(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        RetryQueue(store).enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        response = client.post(
            "/api/deliveries/dlv-1/attempts",
            json={"success": False, "error": "connection refused"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["attempt_count"] == 1

    def test_record_attempt_unknown_delivery_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post(
            "/api/deliveries/nope/attempts", json={"success": True}
        )
        assert response.status_code == 404

    def test_record_attempt_requires_success_field(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        RetryQueue(store).enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        response = client.post("/api/deliveries/dlv-1/attempts", json={})
        assert response.status_code == 422


# ============================================================
# GET /api/dlq
# ============================================================


class TestDlqList:
    def test_empty_dlq(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/dlq")
        assert response.status_code == 200
        assert response.json() == []

    def test_lists_dead_letter_entries(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        queue.enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
            policy=RetryPolicy(max_retries=0, jitter=False),
        )
        # max_retries=0 -> first failure dead-letters immediately
        queue.record_attempt("dlv-1", success=False, error="boom")
        response = client.get("/api/dlq")
        assert response.status_code == 200
        entries = response.json()
        assert len(entries) == 1
        assert entries[0]["delivery_id"] == "dlv-1"
        assert entries[0]["reason"] == "max retries exceeded"

    def test_dlq_filters_by_endpoint(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        for ep, did in (("ep-1", "dlv-1"), ("ep-2", "dlv-2")):
            queue.enqueue(
                delivery_id=did, request_id=f"req-{did}", endpoint_id=ep,
                target_url="https://example.com/hook", method="POST", headers={}, body=None,
                policy=RetryPolicy(max_retries=0, jitter=False),
            )
            queue.record_attempt(did, success=False, error="boom")
        response = client.get("/api/dlq?endpoint_id=ep-2")
        assert response.status_code == 200
        assert [entry["delivery_id"] for entry in response.json()] == ["dlv-2"]


# ============================================================
# POST /api/dlq/{entry_id}/requeue
# ============================================================


class TestDlqRequeue:
    def test_requeue_returns_delivery_to_pending(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        queue.enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
            policy=RetryPolicy(max_retries=0, jitter=False),
        )
        queue.record_attempt("dlv-1", success=False, error="boom")
        entry_id = DeadLetterQueue(store).list_entries()[0]["entry_id"]

        response = client.post(f"/api/dlq/{entry_id}/requeue")
        assert response.status_code == 200
        body = response.json()
        assert body["delivery_id"] == "dlv-1"
        assert body["status"] == "pending"
        # dlq is now empty and the delivery is pending again
        assert client.get("/api/dlq").json() == []
        assert client.get("/api/deliveries?status=pending").json()[0]["delivery_id"] == "dlv-1"

    def test_requeue_unknown_entry_404(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.post("/api/dlq/does-not-exist/requeue")
        assert response.status_code == 404


# ============================================================
# GET /api/dashboard/metrics
# ============================================================


class TestDashboardMetrics:
    def test_metrics_summary_shape(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        queue.enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        queue.record_attempt("dlv-1", success=True, duration_ms=20.0)
        response = client.get("/api/dashboard/metrics")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_deliveries"] == 1
        assert body["summary"]["by_status"]["delivered"] == 1
        assert isinstance(body["time_series"], list)
        assert len(body["time_series"]) > 0
        assert isinstance(body["endpoint_breakdown"], list)

    def test_metrics_strip_rendered_on_dashboard_index(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        queue = RetryQueue(store)
        queue.enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        queue.record_attempt("dlv-1", success=True, duration_ms=20.0)
        page = client.get("/dashboard/")
        assert page.status_code == 200
        assert 'class="metrics-strip"' in page.text
        assert "Deliveries" in page.text

    def test_metrics_respects_window_bucket_params(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        RetryQueue(store).enqueue(
            delivery_id="dlv-1", request_id="req-1", endpoint_id="ep-1",
            target_url="https://example.com/hook", method="POST", headers={}, body=None,
        )
        response = client.get("/api/dashboard/metrics?window_minutes=30&bucket_minutes=10")
        assert response.status_code == 200
        assert len(response.json()["time_series"]) == 3  # 30 / 10

    def test_metrics_empty_db_is_zero_filled(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/dashboard/metrics")
        assert response.status_code == 200
        body = response.json()
        assert body["summary"]["total_deliveries"] == 0
        assert body["summary"]["by_status"] == {
            "pending": 0, "delivered": 0, "failed": 0, "in-dlq": 0,
        }
        assert body["endpoint_breakdown"] == []


# ============================================================
# Auth coverage
# ============================================================


class TestDeliveryApiAuth:
    def test_endpoints_protected_when_token_configured(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        for path in ("/api/deliveries", "/api/dlq", "/api/dashboard/metrics"):
            assert client.get(path).status_code == 401
        assert client.post("/api/deliveries", json=_enqueue_payload()).status_code == 401

    def test_bearer_token_allows_access(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        headers = {"Authorization": "Bearer secret-token"}
        for path in ("/api/deliveries", "/api/dlq", "/api/dashboard/metrics"):
            assert client.get(path, headers=headers).status_code == 200

    def test_open_mode_without_token(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token=None)
        assert client.get("/api/deliveries").status_code == 200
        assert client.get("/api/dlq").status_code == 200
        assert client.get("/api/dashboard/metrics").status_code == 200
