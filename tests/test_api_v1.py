"""Pre-development tests for /api/v1/transformations and /api/v1/destinations CRUD.

These are behavioral tests that assert target behavior as if the API
endpoints already exist.  They fail with assertion errors or HTTP 404
until the developer registers the new routes in src/hookrelay/server.py.

Target: ~18 tests (all behavioral RED).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Behavioral tests — target behavior (RED until implemented)
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from hookrelay.server import create_app
    from starlette.testclient import TestClient

    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestTransformationsCRUD:
    """Assert expected CRUD behavior for /api/v1/transformations."""

    def test_create_transformation(self, client):
        payload = {
            "name": "add-timestamp",
            "filters": ['.created_at = now | .status = "active"'],
        }
        resp = client.post("/api/v1/transformations", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "transform_id" in data
        assert data["name"] == "add-timestamp"

    def test_list_transformations(self, client):
        resp = client.get("/api/v1/transformations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_transformation_by_id(self, client):
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "test-get", "filters": []},
        )
        tid = create_resp.json()["transform_id"]
        resp = client.get(f"/api/v1/transformations/{tid}")
        assert resp.status_code == 200
        assert resp.json()["transform_id"] == tid

    def test_update_transformation(self, client):
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "old-name", "filters": []},
        )
        tid = create_resp.json()["transform_id"]
        resp = client.put(
            f"/api/v1/transformations/{tid}",
            json={"name": "new-name", "filters": []},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "new-name"

    def test_delete_transformation(self, client):
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "to-delete", "filters": []},
        )
        tid = create_resp.json()["transform_id"]
        resp = client.delete(f"/api/v1/transformations/{tid}")
        assert resp.status_code == 204
        get_resp = client.get(f"/api/v1/transformations/{tid}")
        assert get_resp.status_code == 404

    def test_create_400_empty_name(self, client):
        resp = client.post(
            "/api/v1/transformations", json={"name": "", "filters": []}
        )
        assert resp.status_code in (400, 422)

    def test_get_404_nonexistent(self, client):
        # First verify route exists with a valid create
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "for-404-test", "filters": []},
        )
        assert create_resp.status_code == 201
        # Now try a non-existent ID
        resp = client.get("/api/v1/transformations/__nonexistent__")
        assert resp.status_code == 404

    def test_update_404_nonexistent(self, client):
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "for-update-404", "filters": []},
        )
        assert create_resp.status_code == 201
        resp = client.put(
            "/api/v1/transformations/__nonexistent__",
            json={"name": "x", "filters": []},
        )
        assert resp.status_code == 404

    def test_delete_404_nonexistent(self, client):
        create_resp = client.post(
            "/api/v1/transformations",
            json={"name": "for-delete-404", "filters": []},
        )
        assert create_resp.status_code == 201
        resp = client.delete("/api/v1/transformations/__nonexistent__")
        assert resp.status_code == 404


class TestDestinationsCRUD:
    """Assert expected CRUD behavior for /api/v1/destinations."""

    def test_create_destination(self, client):
        payload = {
            "bin_id": "bin-1",
            "url": "https://example.com/hook",
        }
        resp = client.post("/api/v1/destinations", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "destination_id" in data
        assert data["url"] == "https://example.com/hook"

    def test_list_destinations(self, client):
        resp = client.get("/api/v1/destinations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_destination_by_id(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-1", "url": "https://dest.example.com"},
        )
        did = create_resp.json()["destination_id"]
        resp = client.get(f"/api/v1/destinations/{did}")
        assert resp.status_code == 200
        assert resp.json()["destination_id"] == did

    def test_update_destination(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-1", "url": "https://old.example.com"},
        )
        did = create_resp.json()["destination_id"]
        resp = client.put(
            f"/api/v1/destinations/{did}",
            json={"bin_id": "bin-1", "url": "https://new.example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["url"] == "https://new.example.com"

    def test_delete_destination(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-1", "url": "https://del.example.com"},
        )
        did = create_resp.json()["destination_id"]
        resp = client.delete(f"/api/v1/destinations/{did}")
        assert resp.status_code == 204

    def test_create_400_missing_url(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-ok", "url": "https://valid.example.com"},
        )
        assert create_resp.status_code == 201
        resp = client.post("/api/v1/destinations", json={"bin_id": "bin-1"})
        assert resp.status_code in (400, 422)

    def test_create_400_missing_bin_id(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-ok", "url": "https://valid.example.com"},
        )
        assert create_resp.status_code == 201
        resp = client.post(
            "/api/v1/destinations", json={"url": "https://example.com"}
        )
        assert resp.status_code in (400, 422)

    def test_get_404_nonexistent(self, client):
        create_resp = client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-404", "url": "https://valid.example.com"},
        )
        assert create_resp.status_code == 201
        resp = client.get("/api/v1/destinations/__nonexistent__")
        assert resp.status_code == 404

    def test_list_by_bin_id(self, client):
        client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-filter", "url": "https://a.example.com"},
        )
        client.post(
            "/api/v1/destinations",
            json={"bin_id": "bin-other", "url": "https://b.example.com"},
        )
        resp = client.get("/api/v1/destinations?bin_id=bin-filter")
        assert resp.status_code == 200
        items = resp.json()
        assert all(d["bin_id"] == "bin-filter" for d in items)
