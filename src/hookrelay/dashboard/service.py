"""DashboardService — composes metrics, latency, and success rates (T3).

Read-only composition layer for the team dashboard UI/API. Aggregates
the three analyzers into a summary payload, time-series, and per-endpoint
breakdown. Safe to call from request handlers.
"""

from __future__ import annotations

from hookrelay.dashboard.latency import LatencyTracker
from hookrelay.dashboard.metrics import MetricsCollector
from hookrelay.dashboard.success_rate import SuccessRateCalculator
from hookrelay.storage import Storage


class DashboardService:
    """Compose the team dashboard payloads from the three analyzers."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._metrics = MetricsCollector(storage)
        self._latency = LatencyTracker(storage)
        self._success = SuccessRateCalculator(storage)

    def summary(
        self,
        *,
        window_minutes: int = 60,
    ) -> dict:
        """Return the dashboard summary payload.

        ``{'total_deliveries': int, 'by_status': dict, 'success_rate': float,
            'p50_ms': float | None, 'p95_ms': float | None, 'p99_ms': float | None,
            'endpoints': list[dict]}``
        """
        by_status = self._metrics.count_by_status()
        total_deliveries = sum(by_status.values())
        return {
            "total_deliveries": total_deliveries,
            "by_status": by_status,
            "success_rate": self._success.rate(window_minutes=window_minutes),
            "p50_ms": self._latency.percentile(50.0, window_minutes=window_minutes),
            "p95_ms": self._latency.percentile(95.0, window_minutes=window_minutes),
            "p99_ms": self._latency.percentile(99.0, window_minutes=window_minutes),
            "endpoints": self._metrics.count_by_endpoint(),
        }

    def time_series(
        self,
        *,
        window_minutes: int = 60,
        bucket_minutes: int = 5,
    ) -> list[dict]:
        """Return chronological delivery buckets (see MetricsCollector.time_series)."""
        return self._metrics.time_series(
            bucket_minutes=bucket_minutes, window_minutes=window_minutes
        )

    def endpoint_breakdown(
        self,
        *,
        window_minutes: int = 60,
    ) -> list[dict]:
        """Return per-endpoint delivery + success-rate breakdown."""
        return self._success.breakdown(window_minutes=window_minutes)
