"""Acceptance tests for request deletion and retention controls."""
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _stored(store, request_id, received_at):
    store.store_request({
        "request_id": request_id, "channel": "dev", "method": "POST",
        "path": "/hook", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1", "received_at": received_at,
    })


def test_delete_request_removes_related_delivery_attempts(tmp_path):
    store = Storage(str(tmp_path / "delete.db"))
    _stored(store, "delete-me", datetime.now(UTC).isoformat())
    store.store_delivery_attempt("delete-me", "dev", "delivered")
    assert store.delete_request("delete-me") is True
    assert store.get_request("delete-me") is None
    assert store.list_delivery_attempts("delete-me") == []


def test_retention_purge_removes_only_expired_requests(tmp_path):
    store = Storage(str(tmp_path / "retention.db"))
    _stored(store, "old", (datetime.now(UTC) - timedelta(days=40)).isoformat())
    _stored(store, "new", datetime.now(UTC).isoformat())
    assert store.purge_requests_older_than(days=30) == 1
    assert store.get_request("old") is None
    assert store.get_request("new") is not None


def test_delete_api_requires_explicit_confirmation(tmp_path):
    store = Storage(str(tmp_path / "api.db"))
    _storage.set(store)
    _stored(store, "delete-api", datetime.now(UTC).isoformat())
    client = TestClient(create_app())
    denied = client.delete("/api/requests/delete-api")
    assert denied.status_code == 400
    deleted = client.delete("/api/requests/delete-api?confirm=true")
    assert deleted.status_code == 204
    assert store.get_request("delete-api") is None
