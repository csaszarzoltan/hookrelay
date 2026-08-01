"""TDD acceptance tests for v1.0 versioned data infrastructure."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.events import create_event_envelope
from hookrelay.query import RequestQuery
from hookrelay.relay import RelayManager
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _request(request_id: str, received_at: str | None = None) -> dict:
    return {
        "request_id": request_id,
        "channel": "dev",
        "method": "POST",
        "path": "/events",
        "headers": {"x-event": "invoice.failed"},
        "body": b'{"event":"invoice.failed"}',
        "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": received_at or datetime.now(UTC).isoformat(),
    }


def test_legacy_database_is_migrated_without_losing_requests(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE webhooks (
            request_id TEXT PRIMARY KEY, channel TEXT NOT NULL, method TEXT NOT NULL,
            path TEXT NOT NULL, headers TEXT NOT NULL, body BLOB,
            query_params TEXT NOT NULL, source_ip TEXT NOT NULL,
            received_at TEXT NOT NULL, replayed INTEGER NOT NULL DEFAULT 0
        )"""
    )
    connection.execute(
        "INSERT INTO webhooks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacy", "dev", "POST", "/legacy", "{}", b"{}", "{}", "127.0.0.1", datetime.now(UTC).isoformat(), 0),
    )
    connection.commit()
    connection.close()

    store = Storage(str(path))
    assert store.get_request("legacy")["path"] == "/legacy"
    assert store.schema_version >= 3
    assert [item["version"] for item in store.migration_history()] == list(range(1, store.schema_version + 1))


def test_event_envelope_is_versioned_persisted_and_cursor_addressable(tmp_path):
    store = Storage(str(tmp_path / "events.db"))
    envelope = create_event_envelope("webhook.received", {"request_id": "r1"})
    cursor = store.append_event(envelope)
    assert cursor > 0
    events = store.list_events(after_cursor=0)
    assert events[0]["schema_version"] == 1
    assert events[0]["event_id"] == envelope["event_id"]
    assert events[0]["cursor"] == cursor
    assert store.list_events(after_cursor=cursor) == []


def test_connection_registry_tracks_metadata_heartbeat_and_stale_state():
    manager = RelayManager(stale_after_seconds=30)
    socket = object()
    session_id = manager.register_client(
        "payments",
        socket,
        target_url="http://localhost:9000/hooks",
        client_version="1.0.0",
        capabilities=["delivery_results"],
    )
    connections = manager.list_connections()
    assert connections[0]["session_id"] == session_id
    assert connections[0]["target_url"].endswith("/hooks")
    assert connections[0]["state"] == "connected"
    manager._connections[session_id]["last_heartbeat"] = (
        datetime.now(UTC) - timedelta(seconds=31)
    ).isoformat()
    assert manager.list_connections()[0]["state"] == "stale"
    manager.heartbeat(session_id)
    assert manager.list_connections()[0]["state"] == "connected"


def test_canonical_query_validates_and_uses_cursor_pagination(tmp_path):
    store = Storage(str(tmp_path / "query.db"))
    for index in range(3):
        store.store_request(_request(f"r{index}", f"2026-08-01T10:00:0{index}+00:00"))
    query = RequestQuery(q="invoice", channel="dev", methods=["POST"], limit=2)
    first = store.query_requests(query)
    assert [item["request_id"] for item in first["items"]] == ["r2", "r1"]
    assert first["next_cursor"]
    second = store.query_requests(query.with_cursor(first["next_cursor"]))
    assert [item["request_id"] for item in second["items"]] == ["r0"]
    assert second["next_cursor"] is None


def test_audit_records_are_append_only_and_redact_sensitive_details(tmp_path):
    store = Storage(str(tmp_path / "audit.db"))
    audit_id = store.record_audit_event(
        action="request.replay",
        actor="token:shared",
        object_type="request",
        object_id="r1",
        outcome="success",
        correlation_id="corr-1",
        details={"authorization": "Bearer secret", "channel": "dev"},
    )
    rows = store.list_audit_events(limit=10)
    assert rows[0]["audit_id"] == audit_id
    assert rows[0]["details"]["authorization"] == "••••••••"
    assert rows[0]["correlation_id"] == "corr-1"
    assert not hasattr(store, "update_audit_event")


def test_data_apis_expose_schema_connections_events_query_and_audit(tmp_path):
    store = Storage(str(tmp_path / "api.db"))
    store.store_request(_request("api-request"))
    store.record_audit_event("request.received", "system", "request", "api-request", "success")
    _storage.set(store)
    client = TestClient(create_app())

    assert client.get("/api/data/schema").json()["current_version"] >= 3
    assert client.get("/api/connections").status_code == 200
    assert client.get("/api/events?after_cursor=0").status_code == 200
    queried = client.get("/api/requests/query?q=invoice&limit=10")
    assert queried.status_code == 200
    assert queried.json()["items"][0]["request_id"] == "api-request"
    assert client.get("/api/audit?limit=10").json()[0]["action"] == "request.received"
