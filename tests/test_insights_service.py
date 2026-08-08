"""Pre-development tests for InsightsService (delivery insights aggregations).

Interface tests (imports, signatures, type hints): pass immediately against
``analysis/analysis-brief.md`` P1-1.

Behavioral tests (endpoints payload, timeseries buckets, failure-reason
classification, window/bucket parsing, missing-table guard): RED until
``src/hookrelay/insights/service.py`` is implemented.

Contract (P1-1 / §5.8):
- ``InsightsService(storage)`` with ``endpoints(window="24h") -> list[dict]``
  and ``timeseries(metric="deliveries", window="24h", bucket="hourly")
  -> list[dict]``.
- Per-endpoint rows: ``{endpoint_id, deliveries, success_rate, p50_ms,
  p95_ms, p99_ms, top_failure_reason}`` sorted by endpoint_id.
- Timeseries buckets: ``{bucket, value}`` (+ ``delivered``/``failed`` for
  metric=deliveries); zero-filled chronological; ``None`` values for
  no-data success_rate/latency_p95 buckets.
- ``classify_failure_reason(row) -> str``: 5xx/4xx/timeout/connection/other.
- ``parse_window("15m"|"1h"|"24h"|"7d") -> minutes``; ``parse_bucket(
  "hourly"|"daily") -> minutes``; invalid -> ValueError.
- Missing ``deliveries`` table => empty lists, never raises.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================

_DELIVERIES_DDL = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    target_url TEXT,
    method TEXT NOT NULL DEFAULT 'POST',
    headers TEXT NOT NULL DEFAULT '{}',
    body BLOB,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    policy TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_status_next
    ON deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_endpoint ON deliveries(endpoint_id);
"""


def _ensure_schema(storage: Storage) -> None:
    storage._conn.executescript(_DELIVERIES_DDL)
    storage._conn.commit()


def _seed_delivery(
    storage: Storage,
    *,
    delivery_id: str,
    endpoint_id: str,
    status: str,
    created_at: datetime | None = None,
) -> None:
    _ensure_schema(storage)
    now = (created_at or datetime.now(UTC)).isoformat()
    storage._conn.execute(
        "INSERT INTO deliveries "
        "(delivery_id, request_id, endpoint_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (delivery_id, f"req-{delivery_id}", endpoint_id, status, now, now),
    )
    storage._conn.commit()


def _seed_attempt(
    storage: Storage,
    *,
    attempt_id: str,
    delivery_id: str,
    endpoint_id: str,
    status: str = "delivered",
    duration_ms: float | None = None,
    response_status: int | None = None,
    error: str | None = None,
    attempted_at: datetime | None = None,
) -> None:
    storage._conn.execute(
        "INSERT INTO delivery_attempts "
        "(attempt_id, request_id, delivery_id, endpoint_id, channel, "
        " target_url, status, response_status, duration_ms, error, "
        " response_headers, response_body, response_body_truncated, attempted_at) "
        "VALUES (?, ?, ?, ?, 'test', NULL, ?, ?, ?, ?, '{}', NULL, 0, ?)",
        (
            attempt_id,
            f"req-{delivery_id}",
            delivery_id,
            endpoint_id,
            status,
            response_status,
            duration_ms,
            error,
            (attempted_at or datetime.now(UTC)).isoformat(),
        ),
    )
    storage._conn.commit()


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "insights.db"))


# ============================================================
# Interface tests
# ============================================================


class TestInsightsServiceInterface:
    def test_module_imports(self):
        from hookrelay.insights import service  # noqa: F401

    def test_service_class_exists(self):
        from hookrelay.insights.service import InsightsService

        assert inspect.isclass(InsightsService)

    def test_init_signature(self):
        from hookrelay.insights.service import InsightsService

        sig = inspect.signature(InsightsService.__init__)
        assert "storage" in sig.parameters

    def test_methods_exist(self):
        from hookrelay.insights.service import InsightsService

        for name in ("endpoints", "timeseries", "classify_failure_reason"):
            assert callable(getattr(InsightsService, name)), name

    def test_endpoints_signature(self):
        from hookrelay.insights.service import InsightsService

        sig = inspect.signature(InsightsService.endpoints)
        assert "window" in sig.parameters
        assert sig.parameters["window"].default == "24h"

    def test_timeseries_signature(self):
        from hookrelay.insights.service import InsightsService

        sig = inspect.signature(InsightsService.timeseries)
        params = sig.parameters
        assert params["metric"].default == "deliveries"
        assert params["window"].default == "24h"
        assert params["bucket"].default == "hourly"

    def test_classify_failure_reason_is_static(self):
        from hookrelay.insights.service import InsightsService

        assert isinstance(
            inspect.getattr_static(InsightsService, "classify_failure_reason"),
            staticmethod,
        )

    def test_parse_window_exists(self):
        from hookrelay.insights.service import parse_window

        assert callable(parse_window)

    def test_parse_bucket_exists(self):
        from hookrelay.insights.service import parse_bucket

        assert callable(parse_bucket)


# ============================================================
# Behavioral — window / bucket parsing
# ============================================================


class TestWindowParsing:
    def test_parse_window_valid(self):
        from hookrelay.insights.service import parse_window

        try:
            assert parse_window("15m") == 15
            assert parse_window("1h") == 60
            assert parse_window("24h") == 1440
            assert parse_window("7d") == 10080
        except NotImplementedError:
            pytest.skip("RED phase — parse_window stub not implemented yet")

    @pytest.mark.parametrize("window", ["99", "2x", "", "24H", "1M", "hourly"])
    def test_parse_window_invalid(self, window):
        from hookrelay.insights.service import parse_window

        try:
            parse_window(window)
        except NotImplementedError:
            pytest.skip("RED phase — parse_window stub not implemented yet")
        with pytest.raises(ValueError):
            parse_window(window)

    @pytest.mark.parametrize("window", ["100d", "999999999999d", "16m", "2h", "8d"])
    def test_parse_window_rejects_arbitrary_magnitudes(self, window):
        """Regression (review Minor-2): only the four literal tokens are valid."""
        from hookrelay.insights.service import parse_window

        with pytest.raises(ValueError):
            parse_window(window)


class TestBucketParsing:
    def test_parse_bucket_valid(self):
        from hookrelay.insights.service import parse_bucket

        try:
            assert parse_bucket("hourly") == 60
            assert parse_bucket("daily") == 1440
        except NotImplementedError:
            pytest.skip("RED phase — parse_bucket stub not implemented yet")

    @pytest.mark.parametrize("bucket", ["weekly", "", "60", "HOURLY"])
    def test_parse_bucket_invalid(self, bucket):
        from hookrelay.insights.service import parse_bucket

        try:
            parse_bucket(bucket)
        except NotImplementedError:
            pytest.skip("RED phase — parse_bucket stub not implemented yet")
        with pytest.raises(ValueError):
            parse_bucket(bucket)


# ============================================================
# Behavioral — classify_failure_reason
# ============================================================


class TestFailureReasonClassification:
    def test_5xx_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": 503, "error": "Service Unavailable"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "5xx"

    def test_4xx_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": 404, "error": "Not Found"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "4xx"

    def test_timeout_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": None, "error": "timed out after 30s"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "timeout"

    def test_connection_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": None, "error": "Connection refused"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "connection"

    def test_dns_error_connection_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": None, "error": "Name or service not known"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "connection"

    def test_other_bucket(self):
        from hookrelay.insights.service import InsightsService

        try:
            reason = InsightsService.classify_failure_reason(
                {"response_status": None, "error": "some weird failure"}
            )
        except NotImplementedError:
            pytest.skip("RED phase — classify_failure_reason stub not implemented yet")
        assert reason == "other"


# ============================================================
# Behavioral — endpoints()
# ============================================================


class TestEndpoints:
    def test_empty_db_returns_empty_list(self, store):
        from hookrelay.insights.service import InsightsService

        try:
            result = InsightsService(store).endpoints("24h")
        except NotImplementedError:
            pytest.skip("RED phase — endpoints stub not implemented yet")
        assert result == []

    def test_missing_deliveries_table_returns_empty(self, tmp_path):
        """Fresh DB without deliveries: empty, never raises."""
        from hookrelay.insights.service import InsightsService

        bare = Storage(str(tmp_path / "bare.db"))
        try:
            result = InsightsService(bare).endpoints("24h")
        except NotImplementedError:
            pytest.skip("RED phase — endpoints stub not implemented yet")
        assert result == []

    def test_per_endpoint_payload(self, store):
        from hookrelay.insights.service import InsightsService

        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="delivered")
        _seed_delivery(store, delivery_id="d2", endpoint_id="ep1", status="failed")
        _seed_delivery(store, delivery_id="d3", endpoint_id="ep2", status="delivered")
        _seed_attempt(store, attempt_id="a1", delivery_id="d1", endpoint_id="ep1",
                      duration_ms=100.0, response_status=200)
        _seed_attempt(store, attempt_id="a2", delivery_id="d2", endpoint_id="ep1",
                      duration_ms=500.0, response_status=503, error="Service Unavailable")

        try:
            result = InsightsService(store).endpoints("24h")
        except NotImplementedError:
            pytest.skip("RED phase — endpoints stub not implemented yet")
        assert [e["endpoint_id"] for e in result] == ["ep1", "ep2"]
        ep1 = result[0]
        assert ep1["deliveries"] == 2
        assert ep1["success_rate"] == pytest.approx(0.5)
        assert ep1["p50_ms"] == pytest.approx(100.0)
        assert ep1["p95_ms"] == pytest.approx(500.0)
        assert ep1["p99_ms"] == pytest.approx(500.0)
        assert ep1["top_failure_reason"] == "5xx"
        ep2 = result[1]
        assert ep2["deliveries"] == 1
        assert ep2["success_rate"] == pytest.approx(1.0)


# ============================================================
# Behavioral — timeseries()
# ============================================================


class TestTimeseries:
    def test_empty_db_zero_filled_buckets(self, store):
        from hookrelay.insights.service import InsightsService

        try:
            buckets = InsightsService(store).timeseries(
                "deliveries", "24h", "hourly"
            )
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        assert len(buckets) == 24
        assert all(b["delivered"] == 0 and b["failed"] == 0 for b in buckets)
        assert buckets[0]["bucket"] < buckets[-1]["bucket"]

    def test_missing_deliveries_table_returns_empty(self, tmp_path):
        from hookrelay.insights.service import InsightsService

        bare = Storage(str(tmp_path / "bare2.db"))
        try:
            buckets = InsightsService(bare).timeseries("deliveries", "24h", "hourly")
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        assert isinstance(buckets, list)

    def test_deliveries_metric_counts(self, store):
        from hookrelay.insights.service import InsightsService

        now = datetime.now(UTC)
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1",
                       status="delivered", created_at=now - timedelta(minutes=10))
        _seed_delivery(store, delivery_id="d2", endpoint_id="ep1",
                       status="failed", created_at=now - timedelta(minutes=5))
        try:
            buckets = InsightsService(store).timeseries(
                "deliveries", "24h", "hourly"
            )
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        total_delivered = sum(b["delivered"] for b in buckets)
        total_failed = sum(b["failed"] for b in buckets)
        assert total_delivered == 1
        assert total_failed == 1

    def test_success_rate_metric_shape(self, store):
        from hookrelay.insights.service import InsightsService

        now = datetime.now(UTC)
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1",
                       status="delivered", created_at=now - timedelta(minutes=10))
        try:
            buckets = InsightsService(store).timeseries(
                "success_rate", "24h", "hourly"
            )
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        assert len(buckets) == 24
        assert all("value" in b for b in buckets)

    def test_latency_p95_metric_shape(self, store):
        from hookrelay.insights.service import InsightsService

        now = datetime.now(UTC)
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1",
                       status="delivered", created_at=now - timedelta(minutes=10))
        _seed_attempt(store, attempt_id="a1", delivery_id="d1", endpoint_id="ep1",
                      duration_ms=120.0, attempted_at=now - timedelta(minutes=10))
        try:
            buckets = InsightsService(store).timeseries(
                "latency_p95", "24h", "hourly"
            )
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        assert len(buckets) == 24
        assert all("value" in b for b in buckets)

    def test_daily_bucket_count(self, store):
        from hookrelay.insights.service import InsightsService

        try:
            buckets = InsightsService(store).timeseries(
                "deliveries", "7d", "daily"
            )
        except NotImplementedError:
            pytest.skip("RED phase — timeseries stub not implemented yet")
        assert len(buckets) == 7
