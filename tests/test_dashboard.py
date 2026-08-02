"""Pre-development tests for the team dashboard (T3): metrics, latency, success rates.

Interface tests (imports, signatures, type hints): pass immediately.
Behavioral tests (aggregation, percentiles, rates, time-series): RED against
NotImplementedError stubs in hookrelay/dashboard/* until implemented.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from hookrelay.dashboard import latency as latency_mod
from hookrelay.dashboard import metrics as metrics_mod
from hookrelay.dashboard import service as service_mod
from hookrelay.dashboard import success_rate as success_rate_mod
from hookrelay.storage import Storage

# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

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


def _ensure_schema(storage: Storage) -> None:
    """Idempotently create the migration-v5 table the dashboard reads from.

    Migration v5 lands with T1; until then tests create the minimal schema
    themselves so behavioral assertions can be seeded. No-op once v5 exists.
    """
    storage._conn.execute(_DELIVERIES_DDL)
    storage._conn.commit()


def _seed_delivery(
    storage: Storage,
    *,
    delivery_id: str,
    request_id: str,
    endpoint_id: str,
    status: str,
    created_at: datetime | None = None,
) -> None:
    """Insert one canonical delivery row (deliveries table)."""
    _ensure_schema(storage)
    storage._conn.execute(
        "INSERT INTO deliveries (delivery_id, request_id, endpoint_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            delivery_id,
            request_id,
            endpoint_id,
            status,
            (created_at or datetime.now(UTC)).isoformat(),
        ),
    )
    storage._conn.commit()


def _seed_attempt(
    storage: Storage,
    *,
    attempt_id: str,
    request_id: str,
    status: str = "delivered",
    duration_ms: float | None = None,
    attempted_at: datetime | None = None,
) -> None:
    """Insert one delivery_attempt row (v4 table, always present)."""
    storage._conn.execute(
        "INSERT INTO delivery_attempts "
        "(attempt_id, request_id, channel, target_url, status, response_status, "
        " duration_ms, error, response_headers, response_body, response_body_truncated, attempted_at) "
        "VALUES (?, ?, 'test', NULL, ?, NULL, ?, NULL, '{}', NULL, 0, ?)",
        (
            attempt_id,
            request_id,
            status,
            duration_ms,
            (attempted_at or datetime.now(UTC)).isoformat(),
        ),
    )
    storage._conn.commit()


@pytest.fixture
def storage(tmp_path):
    """Isolated Storage per test (tmp_path)."""
    return Storage(str(tmp_path / "dashboard.db"))


# ============================================================
# Interface tests — MetricsCollector
# ============================================================


class TestMetricsCollectorInterface:
    """Verify MetricsCollector class and methods exist with correct signatures."""

    def test_metrics_collector_class_exists(self):
        assert hasattr(metrics_mod, "MetricsCollector")
        assert inspect.isclass(metrics_mod.MetricsCollector)

    def test_metrics_collector_init_signature(self):
        sig = inspect.signature(metrics_mod.MetricsCollector.__init__)
        params = sig.parameters
        assert "storage" in params
        assert params["storage"].annotation is not inspect.Parameter.empty

    def test_metrics_collector_count_by_status_signature(self):
        sig = inspect.signature(metrics_mod.MetricsCollector.count_by_status)
        params = sig.parameters
        assert "endpoint_id" in params
        assert "since" in params
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["since"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["endpoint_id"].default is None
        assert params["since"].default is None
        assert "dict" in str(sig.return_annotation)

    def test_metrics_collector_count_by_endpoint_signature(self):
        sig = inspect.signature(metrics_mod.MetricsCollector.count_by_endpoint)
        params = sig.parameters
        assert "since" in params
        assert params["since"].kind is inspect.Parameter.KEYWORD_ONLY
        assert "list" in str(sig.return_annotation)

    def test_metrics_collector_time_series_signature(self):
        sig = inspect.signature(metrics_mod.MetricsCollector.time_series)
        params = sig.parameters
        assert "bucket_minutes" in params
        assert "window_minutes" in params
        assert params["bucket_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["bucket_minutes"].default == 5
        assert params["window_minutes"].default == 60
        assert "list" in str(sig.return_annotation)


# ============================================================
# Interface tests — LatencyTracker
# ============================================================


class TestLatencyTrackerInterface:
    """Verify LatencyTracker class and methods exist with correct signatures."""

    def test_latency_tracker_class_exists(self):
        assert hasattr(latency_mod, "LatencyTracker")
        assert inspect.isclass(latency_mod.LatencyTracker)

    def test_latency_tracker_init_signature(self):
        sig = inspect.signature(latency_mod.LatencyTracker.__init__)
        assert "storage" in sig.parameters

    def test_latency_tracker_percentile_signature(self):
        sig = inspect.signature(latency_mod.LatencyTracker.percentile)
        params = sig.parameters
        assert "p" in params
        assert params["p"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert "endpoint_id" in params
        assert "window_minutes" in params
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["endpoint_id"].default is None
        assert params["window_minutes"].default is None
        assert "float" in str(sig.return_annotation)

    def test_latency_tracker_percentiles_signature(self):
        sig = inspect.signature(latency_mod.LatencyTracker.percentiles)
        params = sig.parameters
        assert "ps" in params
        assert params["ps"].default is None
        assert "endpoint_id" in params
        assert "window_minutes" in params
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert "dict" in str(sig.return_annotation)

    def test_latency_tracker_average_signature(self):
        sig = inspect.signature(latency_mod.LatencyTracker.average)
        params = sig.parameters
        assert "endpoint_id" in params
        assert "window_minutes" in params
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert "float" in str(sig.return_annotation)


# ============================================================
# Interface tests — SuccessRateCalculator
# ============================================================


class TestSuccessRateCalculatorInterface:
    """Verify SuccessRateCalculator class and methods exist with correct signatures."""

    def test_success_rate_calculator_class_exists(self):
        assert hasattr(success_rate_mod, "SuccessRateCalculator")
        assert inspect.isclass(success_rate_mod.SuccessRateCalculator)

    def test_success_rate_calculator_init_signature(self):
        sig = inspect.signature(success_rate_mod.SuccessRateCalculator.__init__)
        assert "storage" in sig.parameters

    def test_success_rate_calculator_rate_signature(self):
        sig = inspect.signature(success_rate_mod.SuccessRateCalculator.rate)
        params = sig.parameters
        assert "endpoint_id" in params
        assert "window_minutes" in params
        assert params["endpoint_id"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["endpoint_id"].default is None
        assert params["window_minutes"].default == 60
        assert "float" in str(sig.return_annotation)

    def test_success_rate_calculator_breakdown_signature(self):
        sig = inspect.signature(success_rate_mod.SuccessRateCalculator.breakdown)
        params = sig.parameters
        assert "window_minutes" in params
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].default == 60
        assert "list" in str(sig.return_annotation)


# ============================================================
# Interface tests — DashboardService
# ============================================================


class TestDashboardServiceInterface:
    """Verify DashboardService class and methods exist with correct signatures."""

    def test_dashboard_service_class_exists(self):
        assert hasattr(service_mod, "DashboardService")
        assert inspect.isclass(service_mod.DashboardService)

    def test_dashboard_service_init_signature(self):
        sig = inspect.signature(service_mod.DashboardService.__init__)
        assert "storage" in sig.parameters

    def test_dashboard_service_summary_signature(self):
        sig = inspect.signature(service_mod.DashboardService.summary)
        params = sig.parameters
        assert "window_minutes" in params
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].default == 60
        assert "dict" in str(sig.return_annotation)

    def test_dashboard_service_time_series_signature(self):
        sig = inspect.signature(service_mod.DashboardService.time_series)
        params = sig.parameters
        assert "window_minutes" in params
        assert "bucket_minutes" in params
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["bucket_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].default == 60
        assert params["bucket_minutes"].default == 5
        assert "list" in str(sig.return_annotation)

    def test_dashboard_service_endpoint_breakdown_signature(self):
        sig = inspect.signature(service_mod.DashboardService.endpoint_breakdown)
        params = sig.parameters
        assert "window_minutes" in params
        assert params["window_minutes"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["window_minutes"].default == 60
        assert "list" in str(sig.return_annotation)


# ============================================================
# Seed helper — logical delivery event (deliveries + attempts)
# ============================================================


def _seed_event(
    storage: Storage,
    *,
    delivery_id: str,
    request_id: str,
    endpoint_id: str,
    status: str,
    created_at: datetime | None = None,
    duration_ms: float | None = None,
) -> None:
    """Seed one logical delivery event consistently in BOTH tables.

    The dashboard reads from ``deliveries`` (canonical statuses) and
    ``delivery_attempts`` (duration_ms + legacy statuses), so every event is
    written to both: ``delivered`` -> attempt status ``delivered``, anything
    else -> legacy attempt status ``target_error`` (maps to "failed").
    """
    _seed_delivery(
        storage,
        delivery_id=delivery_id,
        request_id=request_id,
        endpoint_id=endpoint_id,
        status=status,
        created_at=created_at,
    )
    attempt_status = "delivered" if status == "delivered" else "target_error"
    _seed_attempt(
        storage,
        attempt_id=f"att-{delivery_id}",
        request_id=request_id,
        status=attempt_status,
        duration_ms=duration_ms,
        attempted_at=created_at,
    )


# ============================================================
# Behavioral tests — MetricsCollector (RED until implemented)
# ============================================================


class TestMetricsCollectorBehavior:
    """Metrics aggregation over seeded delivery data."""

    def test_count_by_status_aggregates_counts(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d4", request_id="r4", endpoint_id="ep-2", status="failed")
        _seed_event(storage, delivery_id="d5", request_id="r5", endpoint_id="ep-2", status="failed")

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.count_by_status()

        assert result["delivered"] == 3
        assert result["failed"] == 2

    def test_count_by_status_filters_by_endpoint(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-2", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-2", status="failed")

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.count_by_status(endpoint_id="ep-2")

        assert result["delivered"] == 1
        assert result["failed"] == 1

    def test_count_by_status_respects_since(self, storage):
        now = datetime.now(UTC)
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=10))
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(hours=3))

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.count_by_status(since=now - timedelta(hours=1))

        assert result["delivered"] == 1

    def test_count_by_endpoint_breakdown(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d4", request_id="r4", endpoint_id="ep-2", status="delivered")

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.count_by_endpoint()

        by_id = {row["endpoint_id"]: row for row in result}
        assert by_id["ep-1"]["delivered"] == 2
        assert by_id["ep-1"]["failed"] == 1
        assert by_id["ep-1"]["total"] == 3
        assert by_id["ep-2"]["delivered"] == 1
        assert by_id["ep-2"]["failed"] == 0
        assert by_id["ep-2"]["total"] == 1

    def test_time_series_buckets_chronological(self, storage):
        now = datetime.now(UTC)
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=50))
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(minutes=20))
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=5))

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.time_series(bucket_minutes=15, window_minutes=60)

        # Complete coverage: 60/15 = 4 buckets, oldest -> newest
        assert len(result) == 4
        stamps = [row["bucket"] for row in result]
        assert stamps == sorted(stamps)
        for row in result:
            assert "bucket" in row
            assert "delivered" in row
            assert "failed" in row

    def test_time_series_counts_land_in_buckets(self, storage):
        now = datetime.now(UTC)
        # Two events in the most recent 15-minute bucket
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=2))
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(minutes=6))
        # One event 40 minutes ago (third bucket back)
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=40))

        collector = metrics_mod.MetricsCollector(storage)
        result = collector.time_series(bucket_minutes=15, window_minutes=60)

        total_delivered = sum(row["delivered"] for row in result)
        total_failed = sum(row["failed"] for row in result)
        assert total_delivered == 2
        assert total_failed == 1

    def test_time_series_zero_filled_when_no_events(self, storage):
        # No deliveries at all -> still complete, zero-filled buckets
        collector = metrics_mod.MetricsCollector(storage)
        result = collector.time_series(bucket_minutes=10, window_minutes=60)

        assert len(result) == 6
        assert all(row["delivered"] == 0 and row["failed"] == 0 for row in result)


# ============================================================
# Behavioral tests — LatencyTracker (RED until implemented)
# ============================================================


class TestLatencyTrackerBehavior:
    """Percentile and average computation over delivery attempts."""

    def _seed_range(self, storage, endpoint_id: str, start: int, stop: int) -> None:
        """Seed attempts with durations start..stop (inclusive) for one endpoint."""
        for i, ms in enumerate(range(start, stop + 1), start=1):
            _seed_event(
                storage,
                delivery_id=f"d-{endpoint_id}-{i}",
                request_id=f"r-{endpoint_id}-{i}",
                endpoint_id=endpoint_id,
                status="delivered",
                duration_ms=float(ms),
            )

    def test_percentile_p50_known_dataset(self, storage):
        # durations [1..100] ms -> p50 = 50.0 (nearest-rank)
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.percentile(50.0) == 50.0

    def test_percentile_p95_known_dataset(self, storage):
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.percentile(95.0) == 95.0

    def test_percentile_p99_known_dataset(self, storage):
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.percentile(99.0) == 99.0

    def test_percentile_empty_data_returns_none(self, storage):
        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.percentile(50.0) is None

    def test_percentiles_defaults_p50_p95_p99(self, storage):
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        result = tracker.percentiles()

        assert result[50.0] == 50.0
        assert result[95.0] == 95.0
        assert result[99.0] == 99.0

    def test_percentiles_custom_ps(self, storage):
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        result = tracker.percentiles(ps=[25.0, 75.0])

        assert result[25.0] == 25.0
        assert result[75.0] == 75.0

    def test_average_known_dataset(self, storage):
        # durations [1..100] -> mean = 50.5
        self._seed_range(storage, "ep-1", 1, 100)

        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.average() == 50.5

    def test_average_empty_data_returns_none(self, storage):
        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.average() is None

    def test_percentile_filters_by_endpoint(self, storage):
        # ep-1: durations [1..100]; ep-2: durations [200..300]
        self._seed_range(storage, "ep-1", 1, 100)
        self._seed_range(storage, "ep-2", 200, 300)

        tracker = latency_mod.LatencyTracker(storage)
        assert tracker.percentile(50.0, endpoint_id="ep-1") == 50.0
        assert tracker.percentile(50.0, endpoint_id="ep-2") == 250.0

    def test_percentile_filters_by_window(self, storage):
        now = datetime.now(UTC)
        # Recent: durations [100, 200, 300]; old: [1, 2, 3]
        for i, ms in enumerate([100.0, 200.0, 300.0], start=1):
            _seed_event(
                storage,
                delivery_id=f"d-new-{i}",
                request_id=f"r-new-{i}",
                endpoint_id="ep-1",
                status="delivered",
                duration_ms=ms,
                created_at=now - timedelta(minutes=5),
            )
        for i, ms in enumerate([1.0, 2.0, 3.0], start=1):
            _seed_event(
                storage,
                delivery_id=f"d-old-{i}",
                request_id=f"r-old-{i}",
                endpoint_id="ep-1",
                status="delivered",
                duration_ms=ms,
                created_at=now - timedelta(hours=5),
            )

        tracker = latency_mod.LatencyTracker(storage)
        # 60-minute window sees only the recent three -> p50 = 200.0
        assert tracker.percentile(50.0, window_minutes=60) == 200.0


# ============================================================
# Behavioral tests — SuccessRateCalculator (RED until implemented)
# ============================================================


class TestSuccessRateCalculatorBehavior:
    """Success rate math over seeded delivery data."""

    def test_rate_3_of_5_equals_0_6(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d4", request_id="r4", endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d5", request_id="r5", endpoint_id="ep-1", status="failed")

        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate() == pytest.approx(0.6)

    def test_rate_zero_when_no_attempts(self, storage):
        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate() == 0.0

    def test_rate_zero_when_all_failed(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="failed")

        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate() == 0.0

    def test_rate_one_when_all_delivered(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")

        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate() == 1.0

    def test_rate_filters_by_endpoint(self, storage):
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-2", status="failed")

        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate(endpoint_id="ep-1") == 1.0
        assert calc.rate(endpoint_id="ep-2") == 0.0

    def test_rate_respects_window(self, storage):
        now = datetime.now(UTC)
        # Recent window: 3 delivered / 5 -> 0.6
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=5))
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=10))
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=20))
        _seed_event(storage, delivery_id="d4", request_id="r4", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(minutes=30))
        _seed_event(storage, delivery_id="d5", request_id="r5", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(minutes=40))
        # Old failures (outside 60-minute window) must be excluded
        _seed_event(storage, delivery_id="d6", request_id="r6", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(hours=5))
        _seed_event(storage, delivery_id="d7", request_id="r7", endpoint_id="ep-1",
                    status="failed", created_at=now - timedelta(hours=6))

        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.rate(window_minutes=60) == pytest.approx(0.6)

    def test_breakdown_per_endpoint(self, storage):
        # ep-1: 3 delivered / 5 -> 0.6 ; ep-2: 1 delivered / 1 -> 1.0
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d2", request_id="r2", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d3", request_id="r3", endpoint_id="ep-1", status="delivered")
        _seed_event(storage, delivery_id="d4", request_id="r4", endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d5", request_id="r5", endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d6", request_id="r6", endpoint_id="ep-2", status="delivered")

        calc = success_rate_mod.SuccessRateCalculator(storage)
        result = calc.breakdown()

        by_id = {row["endpoint_id"]: row for row in result}
        assert by_id["ep-1"]["delivered"] == 3
        assert by_id["ep-1"]["failed"] == 2
        assert by_id["ep-1"]["rate"] == pytest.approx(0.6)
        assert by_id["ep-2"]["delivered"] == 1
        assert by_id["ep-2"]["failed"] == 0
        assert by_id["ep-2"]["rate"] == 1.0

    def test_breakdown_empty_returns_empty_list(self, storage):
        calc = success_rate_mod.SuccessRateCalculator(storage)
        assert calc.breakdown() == []


# ============================================================
# Behavioral tests — DashboardService (RED until implemented)
# ============================================================


class TestDashboardServiceBehavior:
    """Composed dashboard payloads over seeded data."""

    def _seed_balanced(self, storage) -> None:
        """ep-1: 3 delivered + 2 failed; ep-2: 1 delivered; durations 1..100 on ep-1."""
        for i in range(1, 4):
            _seed_event(storage, delivery_id=f"d1-{i}", request_id=f"r1-{i}",
                        endpoint_id="ep-1", status="delivered", duration_ms=float(i))
        _seed_event(storage, delivery_id="d1-4", request_id="r1-4",
                    endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d1-5", request_id="r1-5",
                    endpoint_id="ep-1", status="failed")
        _seed_event(storage, delivery_id="d2-1", request_id="r2-1",
                    endpoint_id="ep-2", status="delivered", duration_ms=50.0)

    def test_summary_returns_all_required_keys(self, storage):
        self._seed_balanced(storage)

        svc = service_mod.DashboardService(storage)
        result = svc.summary()

        assert "total_deliveries" in result
        assert "by_status" in result
        assert "success_rate" in result
        assert "p50_ms" in result
        assert "p95_ms" in result
        assert "p99_ms" in result
        assert "endpoints" in result

    def test_summary_totals_consistent(self, storage):
        self._seed_balanced(storage)

        svc = service_mod.DashboardService(storage)
        result = svc.summary()

        assert result["total_deliveries"] == 6
        assert result["by_status"]["delivered"] == 4
        assert result["by_status"]["failed"] == 2
        # 4 delivered / 6 total
        assert result["success_rate"] == pytest.approx(4 / 6)

    def test_summary_percentiles_consistent_with_latency(self, storage):
        self._seed_balanced(storage)

        svc = service_mod.DashboardService(storage)
        result = svc.summary()

        tracker = latency_mod.LatencyTracker(storage)
        assert result["p50_ms"] == tracker.percentile(50.0)
        assert result["p95_ms"] == tracker.percentile(95.0)
        assert result["p99_ms"] == tracker.percentile(99.0)

    def test_summary_endpoints_breakdown(self, storage):
        self._seed_balanced(storage)

        svc = service_mod.DashboardService(storage)
        result = svc.summary()

        by_id = {row["endpoint_id"]: row for row in result["endpoints"]}
        assert by_id["ep-1"]["delivered"] == 3
        assert by_id["ep-1"]["failed"] == 2
        assert by_id["ep-2"]["delivered"] == 1
        assert by_id["ep-2"]["failed"] == 0

    def test_time_series_returns_buckets(self, storage):
        now = datetime.now(UTC)
        _seed_event(storage, delivery_id="d1", request_id="r1", endpoint_id="ep-1",
                    status="delivered", created_at=now - timedelta(minutes=10))

        svc = service_mod.DashboardService(storage)
        result = svc.time_series(bucket_minutes=15, window_minutes=60)

        assert len(result) == 4
        assert all("bucket" in row and "delivered" in row and "failed" in row for row in result)

    def test_endpoint_breakdown_returns_rates(self, storage):
        self._seed_balanced(storage)

        svc = service_mod.DashboardService(storage)
        result = svc.endpoint_breakdown()

        by_id = {row["endpoint_id"]: row for row in result}
        assert by_id["ep-1"]["rate"] == pytest.approx(0.6)
        assert by_id["ep-2"]["rate"] == 1.0




