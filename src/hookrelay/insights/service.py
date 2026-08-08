"""InsightsService — read-only delivery insights aggregations.

Composes the existing dashboard analyzers (MetricsCollector,
SuccessRateCalculator, LatencyTracker) over the ``deliveries`` and
``delivery_attempts`` tables, adding per-endpoint failure-reason
classification. Never writes. Missing tables are treated as empty data
(same guard the analyzers use).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hookrelay.dashboard.latency import LatencyTracker
from hookrelay.dashboard.metrics import MetricsCollector
from hookrelay.dashboard.success_rate import SuccessRateCalculator
from hookrelay.storage import Storage

_WINDOW_MULTIPLIERS = {"15m": 15, "1h": 60, "24h": 1440, "7d": 10080}

_TIMEOUT_MARKERS = ("timeout", "timed out", "timedout")
_CONNECTION_MARKERS = (
    "connection refused", "connection reset", "connection error",
    "name or service not known", "dns", "unreachable", "network is unreachable",
    "failed to resolve", "connection timed out",
)


def parse_window(window: str) -> int:
    """Convert ``15m``/``1h``/``24h``/``7d`` to minutes.

    Accepts exactly the four literal window tokens of the API contract;
    anything else (including other magnitudes like ``100d``) raises.

    Raises:
        ValueError: for anything else (API layer turns this into 422).
    """
    value = _WINDOW_MULTIPLIERS.get(window.strip())
    if value is None:
        raise ValueError("window must be one of 15m, 1h, 24h, 7d")
    return value


def parse_bucket(bucket: str) -> int:
    """Convert ``hourly`` -> 60 / ``daily`` -> 1440 minutes.

    Case-sensitive (``HOURLY`` is rejected). Raises:
        ValueError: for anything else.
    """
    if bucket == "hourly":
        return 60
    if bucket == "daily":
        return 1440
    raise ValueError("bucket must be one of hourly, daily")


class InsightsService:
    """Read-only delivery insights: per-endpoint stats + time series.

    Args:
        storage: The repo-wide :class:`~hookrelay.storage.Storage` handle.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def endpoints(self, window: str = "24h") -> list[dict]:
        """Return per-endpoint delivery stats over ``window``.

        Each row: ``{endpoint_id, deliveries, success_rate, p50_ms, p95_ms,
        p99_ms, top_failure_reason}`` sorted by endpoint_id. Missing
        ``deliveries`` table yields ``[]``.
        """
        window_minutes = parse_window(window)
        rates = SuccessRateCalculator(self._storage).breakdown(
            window_minutes=window_minutes
        )
        result: list[dict] = []
        for rate in rates:
            endpoint_id = rate["endpoint_id"]
            percentiles = LatencyTracker(self._storage).percentiles(
                endpoint_id=endpoint_id, window_minutes=window_minutes
            )
            total = rate["delivered"] + rate["failed"]
            result.append(
                {
                    "endpoint_id": endpoint_id,
                    "deliveries": total,
                    "success_rate": rate["rate"],
                    "p50_ms": percentiles.get(50.0),
                    "p95_ms": percentiles.get(95.0),
                    "p99_ms": percentiles.get(99.0),
                    "top_failure_reason": self._top_failure_reason(
                        endpoint_id, window_minutes
                    ),
                }
            )
        return result

    def timeseries(
        self, metric: str = "deliveries", window: str = "24h", bucket: str = "hourly"
    ) -> list[dict]:
        """Return chronological buckets for ``metric`` over ``window``.

        ``deliveries`` buckets carry ``{bucket, delivered, failed, value}``;
        ``success_rate`` and ``latency_p95`` carry ``{bucket, value}`` with
        ``None`` values for no-data buckets. Zero-filled and chronological.
        """
        window_minutes = parse_window(window)
        bucket_minutes = parse_bucket(bucket)
        collector = MetricsCollector(self._storage)
        raw = collector.time_series(
            bucket_minutes=bucket_minutes, window_minutes=window_minutes
        )
        if metric == "deliveries":
            return [
                {
                    "bucket": item["bucket"],
                    "delivered": item["delivered"],
                    "failed": item["failed"],
                    "value": item["delivered"] + item["failed"],
                }
                for item in raw
            ]
        if metric == "success_rate":
            return self._rate_series(raw)
        if metric == "latency_p95":
            return self._latency_series(bucket_minutes, window_minutes)
        raise ValueError("metric must be one of deliveries, success_rate, latency_p95")

    # -- helpers ----------------------------------------------------------

    def _rate_series(self, raw: list[dict]) -> list[dict]:
        """Per-bucket success rate (None when a bucket has no finished rows)."""
        result: list[dict] = []
        for item in raw:
            total = item["delivered"] + item["failed"]
            result.append(
                {
                    "bucket": item["bucket"],
                    "value": (item["delivered"] / total) if total else None,
                }
            )
        return result

    def _latency_series(
        self, bucket_minutes: int, window_minutes: int
    ) -> list[dict]:
        """Per-bucket p95 latency from delivery_attempts.duration_ms."""
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=window_minutes)
        bucket_size = timedelta(minutes=bucket_minutes)
        bucket_count = max(1, -(-window_minutes // bucket_minutes))
        buckets: list[dict] = [
            {
                "bucket": (window_start + i * bucket_size).isoformat(),
                "values": [],
            }
            for i in range(bucket_count)
        ]
        conn = self._storage._conn
        try:
            rows = conn.execute(
                "SELECT attempted_at, duration_ms FROM delivery_attempts "
                "WHERE duration_ms IS NOT NULL AND attempted_at >= ?",
                (window_start.isoformat(),),
            ).fetchall()
        except Exception:
            rows = []
        for row in rows:
            try:
                attempted = datetime.fromisoformat(row["attempted_at"])
            except (TypeError, ValueError):
                continue
            if attempted.tzinfo is None:
                attempted = attempted.replace(tzinfo=UTC)
            elapsed = attempted - window_start
            index = int(elapsed.total_seconds() // bucket_size.total_seconds())
            index = max(0, min(index, bucket_count - 1))
            buckets[index]["values"].append(float(row["duration_ms"]))
        result: list[dict] = []
        for item in buckets:
            values = sorted(item["values"])
            if not values:
                result.append({"bucket": item["bucket"], "value": None})
                continue
            rank = max(1, -(-95 * len(values) // 100))
            result.append({"bucket": item["bucket"], "value": values[rank - 1]})
        return result

    def _top_failure_reason(
        self, endpoint_id: str, window_minutes: int
    ) -> str | None:
        """Most common failure reason for one endpoint within the window.

        Only attempts that carry a failure signal (HTTP status >= 400 or a
        non-empty ``error``) are classified; clean successes are ignored.
        """
        conn = self._storage._conn
        try:
            cutoff = (
                datetime.now(UTC) - timedelta(minutes=window_minutes)
            ).isoformat()
            rows = conn.execute(
                "SELECT da.response_status, da.error FROM delivery_attempts da "
                "JOIN deliveries d ON da.delivery_id = d.delivery_id "
                "WHERE d.endpoint_id = ? "
                "AND (da.response_status >= 400 OR da.error IS NOT NULL "
                "AND da.error != '') AND da.attempted_at >= ?",
                (endpoint_id, cutoff),
            ).fetchall()
        except Exception:
            return None
        counts: dict[str, int] = {}
        for row in rows:
            reason = self.classify_failure_reason(
                {"response_status": row["response_status"], "error": row["error"]}
            )
            counts[reason] = counts.get(reason, 0) + 1
        if not counts:
            return None
        return max(counts, key=lambda key: (counts[key], key))

    @staticmethod
    def classify_failure_reason(row: Any) -> str:
        """Bucket a failed delivery attempt into a coarse reason.

        Order: HTTP status class (5xx/4xx) first, then error substrings
        for timeout/connection, else ``other``.
        """
        response_status = row.get("response_status") if isinstance(row, dict) else getattr(row, "response_status", None)
        error = (row.get("error") if isinstance(row, dict) else getattr(row, "error", None)) or ""
        error_lower = str(error).lower()
        if response_status is not None:
            try:
                status = int(response_status)
            except (TypeError, ValueError):
                status = 0
            if 500 <= status < 600:
                return "5xx"
            if 400 <= status < 500:
                return "4xx"
        for marker in _TIMEOUT_MARKERS:
            if marker in error_lower:
                return "timeout"
        for marker in _CONNECTION_MARKERS:
            if marker in error_lower:
                return "connection"
        return "other"
