"""Pre-development tests for Schema REST API endpoints (Group F).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import pytest

from hookrelay import server

# ============================================================
# Interface tests — API route existence
# ============================================================

class TestSchemaAPIRoutesInterface:
    """Verify schema REST API routes are registered on the server."""

    def test_server_has_schema_routes(self):
        """Server should have schema API endpoints."""
        from fastapi import FastAPI
        app = server.create_app()
        assert isinstance(app, FastAPI)
        routes = [r.path for r in app.routes]
        for expected_path in [
            "/api/v1/schemas",
            "/api/v1/validate",
        ]:
            assert any(expected_path in path for path in routes)

    def test_server_has_schema_detail_route(self):
        """Server should have /api/v1/schemas/{schema_id}."""
        app = server.create_app()
        routes = [r.path for r in app.routes]
        assert any("schemas/" in path or "{schema_id}" in path for path in routes)


# ============================================================
# Behavioral tests — Schema CRUD API (via TestClient)
# ============================================================

class TestSchemaAPICRUDBehavioral:
    """Call schema REST API endpoints and verify responses."""

    @pytest.fixture
    def client(self):
        """Create a FastAPI TestClient against the server app."""
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_post_schema_creates_schema(self, client):
        """POST /api/v1/schemas should create a new schema."""
        response = client.post(
            "/api/v1/schemas",
            json={
                "name": "test-schema",
                "channel": "test",
                "schema_definition": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                "draft_version": "2020-12",
                "severity_level": "error",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "schema_id" in data
        assert data["name"] == "test-schema"
        assert data["channel"] == "test"

    def test_behavior_get_schemas_lists_all(self, client):
        """GET /api/v1/schemas should list all schemas."""
        # Create a schema first
        client.post("/api/v1/schemas", json={
            "name": "list-test",
            "channel": "test",
            "schema_definition": {"type": "object"},
        })
        response = client.get("/api/v1/schemas")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert any(s["name"] == "list-test" for s in data)

    def test_behavior_get_schemas_filtered_by_channel(self, client):
        """GET /api/v1/schemas?channel=X should filter."""
        client.post("/api/v1/schemas", json={
            "name": "pay-schema",
            "channel": "payments",
            "schema_definition": {"type": "object"},
        })
        response = client.get("/api/v1/schemas?channel=payments")
        assert response.status_code == 200
        data = response.json()
        assert all(s["channel"] == "payments" for s in data)

    def test_behavior_get_schema_by_id(self, client):
        """GET /api/v1/schemas/{id} should return schema detail."""
        created = client.post("/api/v1/schemas", json={
            "name": "detail-test",
            "channel": "test",
            "schema_definition": {"type": "object"},
        }).json()
        schema_id = created["schema_id"]
        response = client.get(f"/api/v1/schemas/{schema_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["schema_id"] == schema_id
        assert data["name"] == "detail-test"

    def test_behavior_get_schema_by_id_not_found(self, client):
        """GET /api/v1/schemas/nonexistent should return 404."""
        response = client.get("/api/v1/schemas/nonexistent-id")
        assert response.status_code == 404

    def test_behavior_put_schema_updates_fields(self, client):
        """PUT /api/v1/schemas/{id} should update schema."""
        created = client.post("/api/v1/schemas", json={
            "name": "before-update",
            "channel": "test",
            "schema_definition": {"type": "object"},
        }).json()
        schema_id = created["schema_id"]
        response = client.put(
            f"/api/v1/schemas/{schema_id}",
            json={"name": "after-update", "enabled": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "after-update"
        assert data["enabled"] is False

    def test_behavior_put_schema_not_found(self, client):
        """PUT /api/v1/schemas/nonexistent should return 404."""
        response = client.put(
            "/api/v1/schemas/nonexistent",
            json={"name": "new-name"},
        )
        assert response.status_code == 404

    def test_behavior_delete_schema_removes_it(self, client):
        """DELETE /api/v1/schemas/{id} should remove schema."""
        created = client.post("/api/v1/schemas", json={
            "name": "delete-me",
            "channel": "test",
            "schema_definition": {"type": "object"},
        }).json()
        schema_id = created["schema_id"]
        response = client.delete(f"/api/v1/schemas/{schema_id}")
        assert response.status_code == 204
        # Verify it's gone
        get_resp = client.get(f"/api/v1/schemas/{schema_id}")
        assert get_resp.status_code == 404

    def test_behavior_delete_schema_not_found(self, client):
        """DELETE /api/v1/schemas/nonexistent should return 404."""
        response = client.delete("/api/v1/schemas/nonexistent")
        assert response.status_code == 404


# ============================================================
# Behavioral tests — Manual validation endpoint
# ============================================================

class TestValidateAPIBehavioral:
    """POST /api/v1/validate should validate payloads."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_validate_valid_payload(self, client):
        """POST /api/v1/validate with valid payload returns valid."""
        response = client.post(
            "/api/v1/validate",
            json={
                "schema": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}},
                },
                "payload": {"x": 42},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True

    def test_behavior_validate_invalid_payload(self, client):
        """POST /api/v1/validate with invalid payload returns errors."""
        response = client.post(
            "/api/v1/validate",
            json={
                "schema": {
                    "type": "object",
                    "required": ["name"],
                },
                "payload": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert len(data["errors"]) >= 1
        assert "message" in data["errors"][0]

    def test_behavior_validate_missing_schema_field(self, client):
        """POST /api/v1/validate without schema field returns 422."""
        response = client.post(
            "/api/v1/validate",
            json={"payload": {}},
        )
        assert response.status_code == 422

    def test_behavior_validate_with_schema_id_ref(self, client):
        """POST /api/v1/validate with schema_id should use stored schema."""
        # Create a schema first
        created = client.post("/api/v1/schemas", json={
            "name": "ref-schema",
            "channel": "test",
            "schema_definition": {
                "type": "object",
                "required": ["email"],
                "properties": {"email": {"type": "string", "format": "email"}},
            },
        }).json()

        response = client.post(
            "/api/v1/validate",
            json={
                "schema_id": created["schema_id"],
                "payload": {"email": "not-an-email"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False

    def test_behavior_validate_with_draft_specified(self, client):
        """POST /api/v1/validate with draft field should use specified draft."""
        response = client.post(
            "/api/v1/validate",
            json={
                "schema": {"type": "object"},
                "payload": {"x": 1},
                "draft": "07",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
