# Hookrelay 1.5 REST API — Delivery, DLQ, and Dashboard Metrics

v1.5.0 shipped the delivery infrastructure (retry queue, dead-letter queue,
idempotency, tracking, dashboard analyzers) as a library surface. This guide
documents the REST endpoints and CLI commands that expose it.

## Authentication

All `/api/*` endpoints below are covered by the existing optional auth
middleware: when `HOOKRELAY_API_TOKEN` is set, requests must present a valid
`Authorization: Bearer <token>` header (or a logged-in dashboard session).
Without a configured token (local open mode) they are reachable without
credentials, exactly like the rest of the API.

## REST endpoints

### `GET /api/deliveries`

List outbound deliveries, newest first.

| Query param  | Type | Default | Notes |
|---|---|---|---|
| `status`     | str  | —       | One of `pending`, `delivered`, `failed`, `in-dlq`. Unknown values → 422. |
| `endpoint_id`| str  | —       | Filter by endpoint. |
| `limit`      | int  | 100     | Clamped to `[1, 1000]`. |

```json
[
  {
    "delivery_id": "dlv-1",
    "request_id": "req-1",
    "endpoint_id": "ep-1",
    "target_url": "https://example.com/hook",
    "method": "POST",
    "headers": {},
    "body": null,
    "idempotency_key": null,
    "status": "pending",
    "attempt_count": 0,
    "next_attempt_at": "2026-08-02T10:23:49.485247+00:00",
    "last_error": null,
    "policy": null,
    "created_at": "2026-08-02T10:23:49.485247+00:00",
    "updated_at": "2026-08-02T10:23:49.485247+00:00"
  }
]
```

`headers` and `policy` are returned as parsed objects (not JSON text).

### `POST /api/deliveries` — enqueue

Enqueue a new delivery. The SSRF guard (`validate_target_url`) and the
idempotency-key dedup are enforced on this path; violations return **422**.

Request body:

| Field           | Type           | Required | Notes |
|---|---|---|---|
| `request_id`    | str            | yes      | Upstream webhook request id. |
| `endpoint_id`   | str            | yes      | Endpoint this delivery belongs to. |
| `target_url`    | str            | yes      | Must pass the SSRF guard (http/https, non-private). |
| `method`        | str            | no       | Default `POST`. |
| `headers`       | dict[str,str]  | no       | Outbound headers. |
| `body`          | str \| null    | no       | UTF-8 body text. |
| `idempotency_key` | str \| null | no       | Dedup key; re-using an active key → 422. |
| `policy`        | dict \| null   | no       | `RetryPolicy` fields (`max_retries`, `backoff_factor`, `base_delay_seconds`, `max_backoff_seconds`, `jitter`). |
| `delivery_id`   | str \| null    | no       | Explicit id; a UUID is generated when omitted. |

Returns **201** with the created delivery record. Records a
`delivery.enqueue` audit event.

### `POST /api/deliveries/{delivery_id}/attempts`

Record one delivery attempt and transition status (see the retry-queue
state machine). Unknown delivery → **404**.

Request body:

| Field            | Type | Required | Notes |
|---|---|---|---|
| `success`        | bool | yes      | Outcome of the attempt. |
| `response_status`| int  | no       | HTTP status from the target. |
| `duration_ms`    | float| no       | Round-trip latency. |
| `error`          | str  | no       | Failure detail. |

Returns **200** with the updated delivery record (its `status` reflects the
transition: `delivered`, `pending` with backoff, or `in-dlq` when retries are
exhausted). Records a `delivery.attempt` audit event.

### `GET /api/dlq`

List dead-letter entries, newest first.

| Query param   | Type | Default | Notes |
|---|---|---|---|
| `endpoint_id` | str  | —       | Filter by endpoint. |
| `limit`       | int  | 100     | Clamped to `[1, 1000]`. |

Each entry carries the original delivery metadata plus `reason`, `error`, and
`dead_lettered_at`.

### `POST /api/dlq/{entry_id}/requeue`

Move a dead-letter entry back to the pending queue (`attempt_count` reset,
`next_attempt_at = now`, DLQ row removed). Unknown entry → **404**.

Returns **200**:

```json
{ "delivery_id": "dlv-1", "status": "pending" }
```

Records a `dlq.requeue` audit event.

### `GET /api/dashboard/metrics`

Compose the `DashboardService` analyzers into one payload.

| Query param     | Type | Default | Notes |
|---|---|---|---|
| `window_minutes`| int  | 60      | Rolling window, `[1, 1440]`. |
| `bucket_minutes`| int  | 5       | Time-series bucket, `[1, window_minutes]`. |

```json
{
  "summary": {
    "total_deliveries": 1,
    "by_status": {"pending": 0, "delivered": 1, "failed": 0, "in-dlq": 0},
    "success_rate": 1.0,
    "p50_ms": 20.0,
    "p95_ms": 20.0,
    "p99_ms": 20.0,
    "endpoints": [{"endpoint_id": "ep-1", "delivered": 1, "failed": 0, "total": 1}]
  },
  "time_series": [
    {"bucket": "2026-08-02T09:23:49+00:00", "delivered": 0, "failed": 0}
  ],
  "endpoint_breakdown": [
    {"endpoint_id": "ep-1", "delivered": 1, "failed": 0, "rate": 1.0}
  ]
}
```

A missing `deliveries` table (pre-migration v5) is treated as empty data
(zero-filled summary, empty series/breakdown).

## Dashboard UI wiring

The Live Feed page (`/dashboard/`) renders a summary metrics strip
(`.metrics-strip`) server-side from `DashboardService.summary()` when
delivery data exists — the "team dashboard metrics" claim from the v1.5
changelog is reachable from the running server, not just the library.

## CLI commands

The CLI reads the same default storage as `hookrelay history`.

### `hookrelay delivery list`

```
hookrelay delivery list [--status STATUS] [--endpoint-id ID] [--limit N]
```

Prints one line per delivery (timestamp, status, endpoint, id, target).

### `hookrelay delivery status <delivery_id>`

Prints the full delivery record as JSON.

### `hookrelay dlq list`

```
hookrelay dlq list [--endpoint-id ID] [--limit N]
```

Prints one line per dead-letter entry (timestamp, endpoint, id, reason).

### `hookrelay dlq requeue <entry_id>`

Moves the entry back to the pending queue and prints the resulting
`delivery_id`. Unknown entry exits with code 1.
