"""Pre-development tests for the insights REST API.

Interface tests (router factory, mounting contract): pass immediately.
Behavioral tests (endpoints + timeseries payloads, 422 validation, auth):
RED until the developer implements ``src/hookrelay/insights/api.py`` and
mounts it flat in ``create_app`` (analysis-brief.md P1-2, §6).

Contract (P1-2 / §5.9):
- ``create_insights_router() -> APIRouter``; mounted flat, token-protected.
- ``GET /api/insights/endpoints?window=24h`` -> ``{window, endpoints: [...]}``
  ; 422 with ``{"detail": "window must be one of 15m, 1h, 24h, 7d"}``.
- ``GET /api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly``
  -> ``{metric, window, bucket, buckets: [...]}``; 422 for invalid metric
  (deliveries|success_rate|latency_p95), window, or bucket (hourly|daily).
- Errors are JSON ``{"detail": ...}``; endpoints not public.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.server import create_app
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================

_DELIVERIES_DDL = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL
)
"""


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _client(tmp_path, monkeypatch, token: str | None = None):
    store = Storage(str(tmp_path / "insights_api.db"))
    _storage.set(store)
    if token is None:
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HOOKRELAY_API_TOKEN", token)
    return TestClient(create_app()), store


def _seed_delivery(store, delivery_id, endpoint_id, status, created_at=None):
    store._conn.executescript(_DELIVERIES_DDL)
    now = (created_at or datetime.now(UTC)).isoformat()
    store._conn.execute(
        "INSERT INTO deliveries (delivery_id, request_id, endpoint_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (delivery_id, f"req-{delivery_id}", endpoint_id, status, now),
    )
    store._conn.commit()


# ============================================================
# Interface tests
# ============================================================


class TestInsightsApiInterface:
    def test_module_imports(self):
        from hookrelay.insights import api as insights_api  # noqa: F401

    def test_create_insights_router_exists(self):
        from hookrelay.insights.api import create_insights_router

        assert callable(create_insights_router)

    def test_create_insights_router_returns_router(self):
        from hookrelay.insights.api import create_insights_router

        try:
            router = create_insights_router()
        except NotImplementedError:
            pytest.skip("RED phase — router stub not implemented yet")
        assert isinstance(router, APIRouter)

    def test_router_registered_in_create_app(self):
        app = create_app()
        paths = {getattr(r, "path", None) for r in app.routes}
        assert "/api/insights/endpoints" in paths
        assert "/api/insights/timeseries" in paths


# ============================================================
# Behavioral — GET /api/insights/endpoints
# ============================================================


class TestInsightsEndpointsApi:
    def test_empty_db_shape(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get("/api/insights/endpoints?window=24h")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["window"] == "24h"
        assert data["endpoints"] == []

    def test_with_data(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        _seed_delivery(store, "d1", "ep1", "delivered")
        _seed_delivery(store, "d2", "ep1", "failed")
        response = client.get("/api/insights/endpoints?window=24h")
        assert response.status_code == 200
        endpoints = response.json()["endpoints"]
        assert len(endpoints) == 1
        ep = endpoints[0]
        assert ep["endpoint_id"] == "ep1"
        assert ep["deliveries"] == 2
        assert ep["success_rate"] == pytest.approx(0.5)
        assert "p50_ms" in ep and "p95_ms" in ep and "p99_ms" in ep
        assert "top_failure_reason" in ep

    @pytest.mark.parametrize("window", ["99", "2x", "", "weekly", "1M"])
    def test_invalid_window_422(self, tmp_path, monkeypatch, window):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(f"/api/insights/endpoints?window={window}")
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "window must be one of 15m, 1h, 24h, 7d"

    @pytest.mark.parametrize("window", ["15m", "1h", "7d"])
    def test_valid_windows_accepted(self, tmp_path, monkeypatch, window):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(f"/api/insights/endpoints?window={window}")
        assert response.status_code == 200, (window, response.text)


# ============================================================
# Behavioral — GET /api/insights/timeseries
# ============================================================


class TestInsightsTimeseriesApi:
    def test_shape(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            "/api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly"
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["metric"] == "deliveries"
        assert data["window"] == "24h"
        assert data["bucket"] == "hourly"
        assert len(data["buckets"]) == 24

    def test_buckets_with_data(self, tmp_path, monkeypatch):
        client, store = _client(tmp_path, monkeypatch)
        _seed_delivery(store, "d1", "ep1", "delivered",
                       created_at=datetime.now(UTC) - timedelta(minutes=5))
        response = client.get(
            "/api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly"
        )
        assert response.status_code == 200
        buckets = response.json()["buckets"]
        assert sum(b["delivered"] for b in buckets) == 1

    @pytest.mark.parametrize("metric", ["bogus", "", "deliveries_per_second"])
    def test_invalid_metric_422(self, tmp_path, monkeypatch, metric):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            f"/api/insights/timeseries?metric={metric}&window=24h&bucket=hourly"
        )
        assert response.status_code == 422, response.text
        assert "detail" in response.json()

    @pytest.mark.parametrize("metric", ["deliveries", "success_rate", "latency_p95"])
    def test_valid_metrics_accepted(self, tmp_path, monkeypatch, metric):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            f"/api/insights/timeseries?metric={metric}&window=24h&bucket=hourly"
        )
        assert response.status_code == 200, (metric, response.text)

    def test_invalid_window_422(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            "/api/insights/timeseries?metric=deliveries&window=99&bucket=hourly"
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "window must be one of 15m, 1h, 24h, 7d"

    @pytest.mark.parametrize("bucket", ["weekly", "", "60", "HOURLY"])
    def test_invalid_bucket_422(self, tmp_path, monkeypatch, bucket):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            f"/api/insights/timeseries?metric=deliveries&window=24h&bucket={bucket}"
        )
        assert response.status_code == 422, response.text
        assert "detail" in response.json()

    @pytest.mark.parametrize("bucket", ["hourly", "daily"])
    def test_valid_buckets_accepted(self, tmp_path, monkeypatch, bucket):
        client, _ = _client(tmp_path, monkeypatch)
        response = client.get(
            f"/api/insights/timeseries?metric=deliveries&window=24h&bucket={bucket}"
        )
        assert response.status_code == 200, (bucket, response.text)


# ============================================================
# Behavioral — auth + coexistence
# ============================================================


class TestInsightsApiAuth:
    def test_endpoints_protected_when_token_configured(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        assert client.get("/api/insights/endpoints").status_code == 401
        assert client.get("/api/insights/timeseries").status_code == 401

    def test_bearer_token_allows_access(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token="secret-token")
        headers = {"Authorization": "Bearer secret-token"}
        assert (
            client.get("/api/insights/endpoints", headers=headers).status_code == 200
        )

    def test_open_mode_without_token(self, tmp_path, monkeypatch):
        client, _ = _client(tmp_path, monkeypatch, token=None)
        assert client.get("/api/insights/endpoints").status_code == 200

    def test_dashboard_metrics_still_works(self, tmp_path, monkeypatch):
        """Both endpoints coexist (no regression on /api/dashboard/metrics)."""
        client, _ = _client(tmp_path, monkeypatch)
        assert client.get("/api/dashboard/metrics").status_code == 200


# ============================================================
# Behavioral — hookrelay insights CLI (P1-4)
# ============================================================


class TestInsightsCli:
    def test_insights_app_registered(self):
        from hookrelay.cli import app as cli_app

        group_names = [g.name for g in cli_app.registered_groups]
        command_names = [c.name for c in cli_app.registered_commands]
        assert "insights" in group_names or "insights" in command_names

    def test_backend_functions_exist(self):
        from hookrelay.cli import insights_endpoints, insights_timeseries

        assert callable(insights_endpoints)
        assert callable(insights_timeseries)

    def test_backend_signatures(self):
        from hookrelay.cli import insights_endpoints, insights_timeseries

        ep_sig = inspect.signature(insights_endpoints)
        assert ep_sig.parameters["window"].default == "24h"

        ts_sig = inspect.signature(insights_timeseries)
        assert ts_sig.parameters["metric"].default == "deliveries"
        assert ts_sig.parameters["window"].default == "24h"
        assert ts_sig.parameters["bucket"].default == "hourly"

    def test_timeseries_prints_json(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hookrelay import _storage as storage_mod
        from hookrelay.cli import app as cli_app

        storage_mod.set(Storage(str(tmp_path / "insights_cli.db")))
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["insights", "timeseries", "--metric", "deliveries",
             "--window", "24h", "--bucket", "hourly"],
        )
        assert result.exit_code == 0, result.output
        assert "bucket" in result.output

    def test_invalid_window_exits_1(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from hookrelay import _storage as storage_mod
        from hookrelay.cli import app as cli_app

        storage_mod.set(Storage(str(tmp_path / "insights_cli2.db")))
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["insights", "endpoints", "--window", "99"],
        )
        assert result.exit_code == 1
        assert "window" in result.output
