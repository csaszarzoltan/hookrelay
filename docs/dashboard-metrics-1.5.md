# Hookrelay 1.5 Dashboard Metrics

## Goal

Give the team dashboard delivery health numbers: counts by status and
endpoint, latency percentiles, and success rates — all read-only over the
`deliveries` / `delivery_attempts` tables, safe to call from request handlers.

## Components

All analyzers live under `hookrelay.dashboard.*`, take the shared `Storage`,
and treat a missing `deliveries` table (pre-migration v5) as empty data.

### MetricsCollector — `hookrelay.dashboard.metrics`

| Method | Behaviour |
|---|---|
| `count_by_status(endpoint_id=None, since=None)` | `{status: count}` over the canonical vocabulary — `pending`, `delivered`, `failed`, `in-dlq` — always zero-filled. |
| `count_by_endpoint(since=None)` | `[{endpoint_id, delivered, failed, total}, ...]` sorted by endpoint id. `failed` counts `failed` **and** `in-dlq` rows. |
| `time_series(bucket_minutes=5, window_minutes=60)` | Chronological `[{bucket: iso_ts, delivered, failed}, ...]` over a rolling window, zero-filled, oldest → newest. |

### LatencyTracker — `hookrelay.dashboard.latency`

Nearest-rank percentiles and the mean over `delivery_attempts.duration_ms`,
optionally filtered by endpoint and a sliding window (default p50/p95/p99):

- `percentile(p, endpoint_id=None, window_minutes=None)` — `p` must be in
  `(0, 100]`; returns `None` when there is no data.
- `percentiles(ps=None, ...)` — default `[50.0, 95.0, 99.0]`.
- `average(endpoint_id=None, window_minutes=None)` — mean duration, `None` if
  empty.

Endpoint filtering joins `delivery_attempts -> deliveries` on `delivery_id`
(unique per delivery), **not** `request_id`, which is 1:N under fan-out and
would misattribute latency across endpoints sharing one request.

### SuccessRateCalculator — `hookrelay.dashboard.success_rate`

`delivered / (delivered + failed)` where `failed` includes `in-dlq`;
`pending` is excluded from the rate.

- `rate(endpoint_id=None, window_minutes=60)` — overall or per-endpoint; `0.0`
  when there is no data.
- `breakdown(window_minutes=60)` — `[{endpoint_id, delivered, failed, rate}, ...]`
  sorted by endpoint id.

### DashboardService — `hookrelay.dashboard.service`

Composes the three analyzers:

- `summary(window_minutes=60)` — `{total_deliveries, by_status, success_rate,
  p50_ms, p95_ms, p99_ms, endpoints}`.
- `time_series(window_minutes=60, bucket_minutes=5)` — pass-through to
  `MetricsCollector.time_series`.
- `endpoint_breakdown(window_minutes=60)` — pass-through to
  `SuccessRateCalculator.breakdown`.

## Usage

```python
from hookrelay.dashboard.latency import LatencyTracker
from hookrelay.dashboard.metrics import MetricsCollector
from hookrelay.dashboard.service import DashboardService
from hookrelay.dashboard.success_rate import SuccessRateCalculator
from hookrelay.storage import Storage

storage = Storage("webhooks.db")

collector = MetricsCollector(storage)
print(collector.count_by_status())
print(collector.count_by_endpoint())

latency = LatencyTracker(storage)
print(latency.percentiles())                    # {50.0: ..., 95.0: ..., 99.0: ...}

success = SuccessRateCalculator(storage)
print(success.rate())                           # 0.75 for 3/4 delivered

svc = DashboardService(storage)
summary = svc.summary()
```

A complete, runnable example that seeds deliveries through the `RetryQueue`
and then reads all analyzers is at
[`examples/dashboard_metrics.py`](../examples/dashboard_metrics.py).

### Sample output (from the example)

```text
count_by_status  : {'pending': 0, 'delivered': 3, 'failed': 0, 'in-dlq': 1}
count_by_endpoint: [{'endpoint_id': 'ep-1', 'delivered': 3, 'failed': 0, 'total': 3}, {'endpoint_id': 'ep-2', 'delivered': 0, 'failed': 1, 'total': 1}]
latency percentiles (ms): {50.0: 20.0, 95.0: 30.0, 99.0: 30.0}
success rate (60m): 75.00%
summary keys: ['by_status', 'endpoints', 'p50_ms', 'p95_ms', 'p99_ms', 'success_rate', 'total_deliveries']
```

## Notes

- These analyzers are a **library surface** (T3) — they compose dashboard
  payloads for UI/API use. No dedicated REST endpoints are exposed for them
  in v1.5.0; call them in-process where the dashboard is served.
- Latency percentiles are nearest-rank, matching the tests
  (`p50` of `[10, 20, 30]` is `20`).
- The success-rate window is a rolling `created_at >= now - window` filter.

## TDD validation

50 dashboard tests in `tests/test_dashboard.py` cover the analyzers and the
composed summary, including the R3 fan-out latency attribution regression
(shared `request_id`, distinct `delivery_id`s). Final regression result:
**731 passed, 0 failed**.
