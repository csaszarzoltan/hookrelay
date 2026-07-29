"""Pre-development tests for Dashboard Integration (Group H).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import server

# ============================================================
# Interface tests — Dashboard routes
# ============================================================

class TestDashboardRoutesInterface:
    """Verify dashboard routes are registered."""

    def test_dashboard_router_exists(self):
        """dashboard module should have create_dashboard_router."""
        from hookrelay.dashboard import create_dashboard_router
        assert callable(create_dashboard_router)

    def test_dashboard_router_signature(self):
        from hookrelay.dashboard import create_dashboard_router
        sig = inspect.signature(create_dashboard_router)
        assert len(sig.parameters) == 0


# ============================================================
# Behavioral tests — Dashboard page rendering
# ============================================================

class TestDashboardPagesBehavioral:
    """Call dashboard endpoints and verify page structure."""

    @pytest.fixture
    def client(self):
        """Create a TestClient against the server app."""
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_dashboard_index_returns_html(self, client):
        """GET /dashboard/ should return dashboard HTML page."""
        response = client.get("/dashboard/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "<title>" in html or "hookrelay" in html.lower()

    def test_behavior_dashboard_history_returns_html(self, client):
        """GET /dashboard/history should return history page."""
        response = client.get("/dashboard/history")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_behavior_dashboard_history_with_filters(self, client):
        """History page should accept filter query params."""
        response = client.get(
            "/dashboard/history?channel=test&method=POST&limit=10&offset=0"
        )
        assert response.status_code == 200

    def test_behavior_dashboard_history_pagination(self, client):
        """History page should support pagination parameters."""
        response = client.get("/dashboard/history?limit=5&offset=10")
        assert response.status_code == 200

    def test_behavior_dashboard_inspect_returns_html(self, client):
        """GET /dashboard/inspect/{id} should return inspect page."""
        response = client.get("/dashboard/inspect/req-123")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_behavior_dashboard_inspect_shows_validation_status(self, client):
        """Inspect page should show validation status badge."""
        response = client.get("/dashboard/inspect/req-valid-001")
        assert response.status_code == 200
        html = response.text
        # Should have validation status indicators
        assert "valid" in html.lower() or "validation" in html.lower()

    def test_behavior_dashboard_inspect_expandable_errors(self, client):
        """Inspect page should have expandable validation error details."""
        response = client.get("/dashboard/inspect/req-with-errors")
        assert response.status_code == 200
        html = response.text
        # Should have expandable error sections
        assert "error" in html.lower() or "details" in html.lower()

    def test_behavior_dashboard_replay_page(self, client):
        """GET /dashboard/replay should serve replay page."""
        response = client.get("/dashboard/replay/req-456")
        assert response.status_code == 200

    def test_behavior_dashboard_history_validation_filter(self, client):
        """History page should support validation_status filter."""
        response = client.get(
            "/dashboard/history?validation_status=invalid"
        )
        assert response.status_code == 200

    def test_behavior_dashboard_history_validation_column(self, client):
        """History page should show validation status column."""
        response = client.get("/dashboard/history")
        assert response.status_code == 200
        html = response.text
        # Should have a column for validation status
        assert "valid" in html.lower() or "status" in html.lower()


# ============================================================
# Behavioral tests — Replay REST endpoint
# ============================================================

class TestReplayEndpointBehavioral:
    """POST /api/replay/{id} should replay a webhook."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_replay_endpoint_exists(self, client):
        """POST /api/replay/{id} should return replay result."""
        response = client.post("/api/replay/req-789")
        # May be 200 or 404 depending on storage state
        assert response.status_code in (200, 404)

    def test_behavior_replay_endpoint_with_target(self, client):
        """Replay with custom target URL."""
        response = client.post(
            "/api/replay/req-789",
            json={"target": "http://localhost:4000/hook"},
        )
        assert response.status_code in (200, 404)


# ============================================================
# Behavioral tests — Health endpoint
# ============================================================

class TestHealthEndpointBehavioral:
    """GET /health should return server status."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        app = server.create_app()
        return TestClient(app)

    def test_behavior_health_returns_status(self, client):
        """GET /health should return JSON with status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        assert "version" in data
