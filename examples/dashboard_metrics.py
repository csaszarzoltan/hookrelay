"""Team dashboard metrics example (hookrelay v1.5.0).

Seeds a few deliveries through the RetryQueue, then exercises the
read-only dashboard analyzers: MetricsCollector, LatencyTracker,
SuccessRateCalculator, and the composed DashboardService summary.

Usage:
    python examples/dashboard_metrics.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.dashboard.latency import LatencyTracker
from hookrelay.dashboard.metrics import MetricsCollector
from hookrelay.dashboard.service import DashboardService
from hookrelay.dashboard.success_rate import SuccessRateCalculator
from hookrelay.delivery import RetryQueue
from hookrelay.storage import Storage


def seed(storage: Storage) -> None:
    """Seed 3 successful deliveries on ep-1 and 1 failed delivery on ep-2."""
    queue = RetryQueue(storage)
    for i in range(3):
        queue.enqueue(
            delivery_id=f"dlv-{i}",
            request_id=f"req-{i}",
            endpoint_id="ep-1",
            target_url="https://example.com/hook",
            method="POST",
            headers={},
            body=b"{}",
        )
        queue.record_attempt(
            f"dlv-{i}", success=True, response_status=200, duration_ms=10.0 * (i + 1)
        )
    queue.enqueue(
        delivery_id="dlv-x",
        request_id="req-x",
        endpoint_id="ep-2",
        target_url="https://example.com/hook",
        method="POST",
        headers={},
        body=b"{}",
        policy=RetryPolicy(max_retries=1, jitter=False),
    )
    queue.record_attempt("dlv-x", success=False, response_status=503, error="boom")


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-metrics-")) / "deliveries.db"
    storage = Storage(str(db))
    seed(storage)

    collector = MetricsCollector(storage)
    print(f"count_by_status  : {collector.count_by_status()}")
    print(f"count_by_endpoint: {collector.count_by_endpoint()}")

    latency = LatencyTracker(storage)
    print(f"latency percentiles (ms): {latency.percentiles()}")

    success = SuccessRateCalculator(storage)
    print(f"success rate (60m): {success.rate():.2%}")

    svc = DashboardService(storage)
    summary = svc.summary()
    print(f"summary keys: {sorted(summary)}")
    print(f"summary      : {summary['total_deliveries']=}, {summary['by_status']=}, "
          f"{summary['success_rate']=}, {summary['p50_ms']=}, {summary['p95_ms']=}, {summary['p99_ms']=}")
    print(f"endpoints    : {summary['endpoints']}")


if __name__ == "__main__":
    main()
