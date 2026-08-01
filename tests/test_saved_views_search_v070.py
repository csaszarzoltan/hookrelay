"""TDD acceptance tests for v0.7 search and saved request views."""
from __future__ import annotations

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _client(tmp_path):
    store = Storage(str(tmp_path / "views.db"))
    _storage.set(store)
    return TestClient(create_app()), store


def _request(store, request_id, path, body):
    store.store_request({
        "request_id": request_id, "channel": "dev", "method": "POST",
        "path": path, "headers": {"x-provider": "stripe"},
        "body": body.encode(), "query_params": {}, "source_ip": "127.0.0.1",
        "received_at": f"2026-08-01T10:00:0{request_id[-1]}+00:00",
    })


def test_history_full_text_search_finds_payload_and_path(tmp_path):
    client, store = _client(tmp_path)
    _request(store, "req1", "/payments", '{"event":"invoice.failed"}')
    _request(store, "req2", "/github", '{"action":"push"}')
    response = client.get("/dashboard/history?q=invoice")
    assert response.status_code == 200
    assert "/payments" in response.text
    assert "/github" not in response.text
    assert 'name="q"' in response.text
    assert 'value="invoice"' in response.text


def test_saved_view_round_trip_and_unique_name(tmp_path):
    store = Storage(str(tmp_path / "roundtrip.db"))
    view_id = store.save_request_view("Stripe failures", {"q": "invoice", "channel": "dev"})
    view = store.get_request_view(view_id)
    assert view["filters"] == {"q": "invoice", "channel": "dev"}
    assert store.list_request_views()[0]["name"] == "Stripe failures"
    try:
        store.save_request_view("Stripe failures", {"q": "other"})
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate saved view name accepted")


def test_saved_view_api_create_apply_delete(tmp_path):
    client, _ = _client(tmp_path)
    created = client.post("/api/request-views", json={
        "name": "Failed invoices",
        "filters": {"q": "invoice.failed", "channel": "payments"},
    })
    assert created.status_code == 201
    view_id = created.json()["view_id"]
    listed = client.get("/api/request-views")
    assert listed.json()[0]["name"] == "Failed invoices"
    page = client.get(f"/dashboard/history?view={view_id}")
    assert page.status_code == 200
    assert 'value="invoice.failed"' in page.text
    deleted = client.delete(f"/api/request-views/{view_id}")
    assert deleted.status_code == 204


def test_history_page_exposes_saved_view_controls(tmp_path):
    client, store = _client(tmp_path)
    store.save_request_view("My daily view", {"channel": "dev"})
    response = client.get("/dashboard/history")
    assert 'id="saved-view"' in response.text
    assert "My daily view" in response.text
    assert 'id="save-view"' in response.text
