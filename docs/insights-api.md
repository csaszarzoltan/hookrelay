# Hookrelay Delivery Insights API (v1.7.0)

The insights API exposes read-only analytics over Hookrelay's stored
delivery history — per-endpoint stats (deliveries, success rate, latency
percentiles, top failure reason) and chronological time series for
charting. It reuses the v1.5.0 dashboard analyzers (`MetricsCollector`,
`SuccessRateCalculator`, `LatencyTracker`) over the `deliveries` and
`delivery_attempts` tables, adding per-endpoint failure-reason
classification. It never writes.

Two endpoints, both mounted flat in `create_app` and covered by the
existing optional auth middleware (401 without a Bearer token when
`HOOKRELAY_API_TOKEN` is set):

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/insights/endpoints` | Per-endpoint delivery stats over a window. |
| `GET` | `/api/insights/timeseries` | Zero-filled chronological buckets for charting. |

## Query parameters

### `window`

Exactly one of four literal tokens. Anything else — including other
magnitudes like `100d` or `999999999999d` — returns **422**:

| Token | Window |
|---|---|
| `15m` | 15 minutes |
| `1h` | 1 hour |
| `24h` | 24 hours (default) |
| `7d` | 7 days |

### `bucket` (timeseries only)

| Token | Bucket size |
|---|---|
| `hourly` | 60 minutes (default) |
| `daily` | 1440 minutes |

`bucket` is case-sensitive (`HOURLY` is rejected).

### `metric` (timeseries only)

| Metric | Bucket shape |
|---|---|
| `deliveries` | `{bucket, delivered, failed, value}` |
| `success_rate` | `{bucket, value}` (delivered/(delivered+failed), `null` for no-data buckets) |
| `latency_p95` | `{bucket, value}` (nearest-rank p95 of `delivery_attempts.duration_ms`, `null` for empty buckets) |

## `GET /api/insights/endpoints`

Per-endpoint delivery stats over the window, sorted by `endpoint_id`:

```bash
curl "http://localhost:8000/api/insights/endpoints?window=24h"
```

```json
{
  "window": "24h",
  "endpoints": [
    {
      "endpoint_id": "ep-billing",
      "deliveries": 6,
      "success_rate": 0.3333333333333333,
      "p50_ms": 400.0,
      "p95_ms": 8000.0,
      "p99_ms": 8000.0,
      "top_failure_reason": "5xx"
    },
    {
      "endpoint_id": "ep-checkout",
      "deliveries": 10,
      "success_rate": 0.8,
      "p50_ms": 88.0,
      "p95_ms": 300.0,
      "p99_ms": 300.0,
      "top_failure_reason": "5xx"
    }
  ]
}
```

Field notes:

- `success_rate` is `delivered / (delivered + failed)` over the window
  (pending excluded) — the same math as the dashboard success-rate
  analyzer.
- `p50_ms` / `p95_ms` / `p99_ms` are nearest-rank latency percentiles of
  `delivery_attempts.duration_ms` for that endpoint within the window;
  `null` when the endpoint has no attempt rows.
- `top_failure_reason` is the most common failure class among failed
  attempts (see classification below); `null` when there are no failures.

### Failure-reason classification

Failed attempts (HTTP status >= 400 or a non-empty `error`) are bucketed
into a coarse reason, checked in this order:

1. HTTP status class first: `5xx`, then `4xx`
2. `timeout` — error text contains `timeout`, `timed out`, or `timedout`
3. `connection` — error text contains e.g. `connection refused`,
   `connection reset`, `connection error`, `dns`, `unreachable`,
   `failed to resolve`, `connection timed out`
4. otherwise `other`

### Validation

Invalid windows return **422** with a `{"detail": ...}` body:

```bash
curl -i "http://localhost:8000/api/insights/endpoints?window=100d"
```

```json
{"detail": "window must be one of 15m, 1h, 24h, 7d"}
```

## `GET /api/insights/timeseries`

Chronological, zero-filled buckets over the window. With
`metric=deliveries`, each bucket carries the delivered/failed split plus a
combined `value`:

```bash
curl "http://localhost:8000/api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly"
```

```json
{
  "metric": "deliveries",
  "window": "24h",
  "bucket": "hourly",
  "buckets": [
    {
      "bucket": "2026-08-07T19:19:28.327576+00:00",
      "delivered": 0,
      "failed": 0,
      "value": 0
    },
    {
      "bucket": "2026-08-08T15:19:28.327576+00:00",
      "delivered": 1,
      "failed": 0,
      "value": 1
    },
    {
      "bucket": "2026-08-08T16:19:28.327576+00:00",
      "delivered": 2,
      "failed": 1,
      "value": 3
    },
    {
      "bucket": "2026-08-08T17:19:28.327576+00:00",
      "delivered": 4,
      "failed": 1,
      "value": 5
    },
    {
      "bucket": "2026-08-08T18:19:28.327576+00:00",
      "delivered": 3,
      "failed": 4,
      "value": 7
    }
  ]
}
```

Zero-filled: a 24h/hourly request always returns 24 buckets; buckets
without rows report `delivered: 0, failed: 0, value: 0`. For
`success_rate` and `latency_p95`, no-data buckets report `"value": null`
instead:

```bash
curl "http://localhost:8000/api/insights/timeseries?metric=success_rate&window=24h&bucket=hourly"
```

```json
{
  "metric": "success_rate",
  "window": "24h",
  "bucket": "hourly",
  "buckets": [
    {"bucket": "2026-08-07T19:19:28.334846+00:00", "value": null},
    {"bucket": "2026-08-08T15:19:28.334846+00:00", "value": 1.0},
    {"bucket": "2026-08-08T16:19:28.334846+00:00", "value": 0.6666666666666666},
    {"bucket": "2026-08-08T17:19:28.334846+00:00", "value": 0.8},
    {"bucket": "2026-08-08T18:19:28.334846+00:00", "value": 0.42857142857142855}
  ]
}
```

A `window=1h&bucket=hourly` request returns a single bucket.

### Validation

Each invalid parameter returns **422** with a `{"detail": ...}` body:

```bash
curl -i "http://localhost:8000/api/insights/timeseries?metric=bogus&window=24h&bucket=hourly"
```

```json
{"detail": "metric must be one of deliveries, success_rate, latency_p95"}
```

```bash
curl -i "http://localhost:8000/api/insights/timeseries?metric=deliveries&window=99&bucket=hourly"
```

```json
{"detail": "window must be one of 15m, 1h, 24h, 7d"}
```

```bash
curl -i "http://localhost:8000/api/insights/timeseries?metric=deliveries&window=24h&bucket=weekly"
```

```json
{"detail": "bucket must be one of hourly, daily"}
```

Validation order: `metric`, then `window`, then `bucket`. All error
bodies use the repo's manual-422 pattern (`{"detail": ...}`), the same as
`/api/dashboard/metrics`.

## CLI

```bash
hookrelay insights endpoints [--window 24h]
hookrelay insights timeseries [--metric deliveries] [--window 24h] [--bucket hourly]
```

Output is JSON. Invalid values exit 1 with the same messages as the API:

```bash
$ hookrelay insights endpoints --window 99
Error: window must be one of 15m, 1h, 24h, 7d
```

## Python API

```python
from hookrelay.insights.service import InsightsService
from hookrelay.storage import Storage

service = InsightsService(Storage("webhooks.db"))

endpoints = service.endpoints(window="24h")
for ep in endpoints:
    print(ep["endpoint_id"], ep["success_rate"], ep["p95_ms"],
          ep["top_failure_reason"])

buckets = service.timeseries(metric="deliveries", window="24h", bucket="hourly")
for bucket in buckets:
    print(bucket["bucket"], bucket["delivered"], bucket["failed"])
```

Helpers: `parse_window("15m"|"1h"|"24h"|"7d") -> minutes` and
`parse_bucket("hourly"|"daily") -> minutes` raise `ValueError` on
anything else (the API layer turns that into 422).
`InsightsService.classify_failure_reason({response_status, error}) -> str`
exposes the failure-reason classifier.

## Dashboard

The **Insights** view at `/dashboard/insights` renders the endpoint stats
table and a canvas time-series chart (success rate + deliveries over
time) from these endpoints.

## Related

- [Alerting](alerting.md) — threshold rules, the evaluation loop, and
  notifier setup over the same delivery data
- [Dashboard metrics](dashboard-metrics-1.5.md) — the underlying
  analyzers (`MetricsCollector`, `SuccessRateCalculator`, `LatencyTracker`)
