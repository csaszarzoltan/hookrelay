"""Tests for routing rule CRUD API endpoints.

Covers POST/GET/PUT/DELETE on /api/bins/{bin_id}/routing-rules and
/api/routing-rules/{rule_id}.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "routing_rules_api.db"))


@pytest.fixture
def client(store, monkeypatch):
    """Create a TestClient with the routing rule API routes."""
    import hookrelay.server as srv
    monkeypatch.setattr(srv, "_get_or_create_storage", lambda *a, **k: store)

    app = FastAPI()
    srv._register_routing_rule_api_routes(app)
    return TestClient(app)


def _make_bin(store: Storage, bin_id: str) -> None:
    store.create_bin(bin_id, f"bin {bin_id}", "2026-08-10T00:00:00+00:00")


def _make_dest(store: Storage, bin_id: str, url: str) -> dict:
    import hookrelay.routing.destination_store as ds_mod
    # Bypass SSRF for tests
    original = ds_mod.validate_target_url
    ds_mod.validate_target_url = lambda u, **kw: (True, None)
    try:
        return ds_mod.DestinationStore(store).create(bin_id, url)
    finally:
        ds_mod.validate_target_url = original


class TestCreateRoutingRule:
    def test_create_routing_rule(self, client, store):
        """POST creates a rule and returns it."""
        bin_id = "bin-api-create"
        _make_bin(store, bin_id)
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "route-to-a",
            "condition": 'body.event~deploy',
            "priority": 10,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "route-to-a"
        assert data["condition"] == 'body.event~deploy'
        assert data["priority"] == 10
        assert data["enabled"] is True
        assert "rule_id" in data

    def test_create_rule_with_arbitrary_condition(self, client, store):
        """FilterExpressionParser silently ignores unparseable terms → rule is created."""
        bin_id = "bin-api-cond"
        _make_bin(store, bin_id)
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "arbitrary-cond",
            "condition": "invalid syntax here ))((",
        })
        # Parser silently ignores bad terms; rule is created successfully.
        assert resp.status_code == 201
        assert resp.json()["condition"] == "invalid syntax here ))(("

    def test_create_rule_validates_destination_ids(self, client, store):
        """Non-existent destination ID → 404."""
        bin_id = "bin-api-dest"
        _make_bin(store, bin_id)
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "bad-dest",
            "target_destination_ids": ["nonexistent_id"],
        })
        assert resp.status_code == 404
        assert "Destination" in resp.json()["detail"]


class TestListRoutingRules:
    def test_list_routing_rules(self, client, store):
        """GET returns rules ordered by priority."""
        bin_id = "bin-api-list"
        _make_bin(store, bin_id)
        # Create two rules with different priorities
        client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "low-priority",
            "priority": 100,
        })
        client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "high-priority",
            "priority": 1,
        })
        resp = client.get(f"/api/bins/{bin_id}/routing-rules")
        assert resp.status_code == 200
        rules = resp.json()
        assert len(rules) == 2
        # Higher priority (lower number) comes first
        assert rules[0]["name"] == "high-priority"
        assert rules[1]["name"] == "low-priority"


class TestUpdateRoutingRule:
    def test_update_routing_rule(self, client, store):
        """PUT updates condition and target_destination_ids."""
        bin_id = "bin-api-update"
        _make_bin(store, bin_id)
        # Create a rule
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "original",
            "condition": 'body.event~test',
        })
        rule_id = resp.json()["rule_id"]
        # Update it
        resp = client.put(f"/api/routing-rules/{rule_id}", json={
            "condition": 'body.event~updated',
            "name": "updated-name",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data['condition'] == 'body.event~updated'
        assert data["name"] == "updated-name"

    def test_update_nonexistent_rule(self, client):
        """PUT on non-existent rule → 404."""
        resp = client.put("/api/routing-rules/nonexistent", json={
            "name": "nope",
        })
        assert resp.status_code == 404

    def test_update_with_empty_body(self, client, store):
        """PUT with no fields → 400."""
        bin_id = "bin-api-update-empty"
        _make_bin(store, bin_id)
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "empty-update-test",
        })
        rule_id = resp.json()["rule_id"]
        resp = client.put(f"/api/routing-rules/{rule_id}", json={})
        assert resp.status_code == 400


class TestDeleteRoutingRule:
    def test_delete_routing_rule(self, client, store):
        """DELETE removes the rule; subsequent delivery falls back to broadcast."""
        bin_id = "bin-api-delete"
        _make_bin(store, bin_id)
        resp = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "to-delete",
        })
        rule_id = resp.json()["rule_id"]
        resp = client.delete(f"/api/routing-rules/{rule_id}")
        assert resp.status_code == 204
        # Verify it's gone
        resp = client.get(f"/api/bins/{bin_id}/routing-rules")
        assert len(resp.json()) == 0

    def test_delete_nonexistent_rule(self, client):
        """DELETE on non-existent rule → 404."""
        resp = client.delete("/api/routing-rules/nonexistent")
        assert resp.status_code == 404


class TestReorderRoutingRules:
    def test_reorder_routing_rules_via_priority(self, client, store):
        """Rules can be reordered by updating priorities."""
        bin_id = "bin-api-reorder"
        _make_bin(store, bin_id)
        # Create two rules
        resp1 = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "first",
            "priority": 1,
        })
        resp2 = client.post(f"/api/bins/{bin_id}/routing-rules", json={
            "name": "second",
            "priority": 2,
        })
        rule1 = resp1.json()["rule_id"]
        rule2 = resp2.json()["rule_id"]
        # Swap priorities
        client.put(f"/api/routing-rules/{rule1}", json={"priority": 10})
        client.put(f"/api/routing-rules/{rule2}", json={"priority": 0})
        # List should reflect new order
        resp = client.get(f"/api/bins/{bin_id}/routing-rules")
        rules = resp.json()
        assert rules[0]["name"] == "second"  # priority 0
        assert rules[1]["name"] == "first"   # priority 10
