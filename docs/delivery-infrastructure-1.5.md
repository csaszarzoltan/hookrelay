# Hookrelay 1.5 Delivery Infrastructure (Retry Queue & Tracking)

## Goal

Make outbound webhook delivery durable and observable: every delivery is
persisted, retried with capped exponential backoff, and tracked through a
canonical status vocabulary so operators can see what happened, when, and why.

This guide covers the **retry queue** (`RetryQueue`), the **delivery state
machine** (`DeliveryTracker` / `DeliveryStatus`), and the **retry policy**
(`RetryPolicy`). Dead-letter and idempotency behaviour have their own guides
([dead-letter-queue-1.5.md](dead-letter-queue-1.5.md),
[idempotency-1.5.md](idempotency-1.5.md)).

## Components

### RetryQueue

`hookrelay.delivery.RetryQueue` — persistent retry queue with exponential
backoff. Created on the same `Storage` connection as the rest of the
application; the `deliveries` table is created idempotently on first use.

| Method | Behaviour |
|---|---|
| `enqueue(*, delivery_id, request_id, endpoint_id, target_url, method, headers, body, idempotency_key=None, policy=None)` | Insert a `pending` delivery due immediately. Raises `ValueError` if the target fails the SSRF guard or the idempotency key is already active. Returns `delivery_id`. |
| `dequeue_due(limit=100, now=None)` | Return `pending` deliveries with `next_attempt_at <= now` (oldest first), for the worker loop. |
| `record_attempt(delivery_id, *, success, response_status=None, duration_ms=None, error=None)` | Persist one attempt and transition status: success → `delivered`; failure with retries left → `pending` with a backoff `next_attempt_at`; failure past `max_retries` → hand off to the DLQ (`in-dlq`). Returns the new status. |
| `backoff_delay(attempt, *, base_delay=1.0, backoff_factor=2.0, max_backoff=3600.0, jitter=True)` | Pure function: `min(max_backoff, base_delay * backoff_factor ** attempt)` plus optional uniform jitter in `[0, delay)`. |
| `pending_count()` / `get(delivery_id)` / `delete(delivery_id)` | Queue introspection and maintenance. |

Defaults are deterministic: `jitter=False`, so retry timings are reproducible
in tests and operations unless a policy explicitly enables jitter.

### DeliveryTracker / DeliveryStatus

`hookrelay.delivery.DeliveryTracker` owns the status state machine over the
same `deliveries` table; `DeliveryStatus` defines the canonical vocabulary:

```
pending -> delivered | failed | in-dlq | pending
failed  -> in-dlq | pending
in-dlq  -> pending
delivered (terminal)
```

`transition()` validates every edge and raises `ValueError` on an invalid
transition. `pending -> in-dlq` and `pending -> pending` are valid because the
retry queue can move a delivery straight to the dead-letter queue when retries
are exhausted and can keep it `pending` to schedule the next backoff attempt.

### RetryPolicy

`hookrelay.config.retry_policy.RetryPolicy` — frozen dataclass with
`max_retries` (default 5), `backoff_factor` (2.0), `base_delay_seconds` (1.0),
`max_backoff_seconds` (3600.0), and `jitter` (True). Exposes `backoff_delay(attempt)`,
`to_dict()`, and `from_dict()`. The queue consumes it interface-only, so the
delivery package stays decoupled from the config package.

## Storage

- `deliveries` — one row per delivery: delivery/request/endpoint ids,
  target URL, method, headers (JSON), body, idempotency key, status,
  attempt count, next attempt time, last error, serialized policy, timestamps.
- `delivery_attempts` — one row per attempt (via `Storage.store_delivery_attempt`),
  feeding the dashboard latency metrics.

Both tables are created idempotently by migration v5 and by the delivery
modules themselves.

## Usage

```python
from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.delivery import DeliveryTracker, RetryQueue
from hookrelay.storage import Storage

storage = Storage("webhooks.db")
queue = RetryQueue(storage)
tracker = DeliveryTracker(storage)
policy = RetryPolicy(max_retries=2, base_delay_seconds=1.0, backoff_factor=2.0, jitter=False)

queue.enqueue(
    delivery_id="dlv-ok",
    request_id="req-1",
    endpoint_id="ep-1",
    target_url="https://example.com/hook",
    method="POST",
    headers={"Content-Type": "application/json"},
    body=b'{"event": "order.created"}',
    policy=policy,
)
due = queue.dequeue_due()
for item in due:
    status = queue.record_attempt(
        item["delivery_id"], success=True, response_status=200, duration_ms=42.0
    )
    print(item["delivery_id"], status)
print(tracker.count_by_status())
```

A complete, runnable version is at
[`examples/delivery_retry_queue.py`](../examples/delivery_retry_queue.py).

### Sample output (from the example)

```text
Enqueued dlv-ok and dlv-bad -> pending=2
Dequeued 2 due delivery(ies)
record_attempt(dlv-ok, success=True) -> 'delivered'
record_attempt(dlv-bad, fail 1/2) -> 'pending'
record_attempt(dlv-bad, fail 2/2) -> 'in-dlq'
Status counts: {'pending': 0, 'delivered': 1, 'failed': 0, 'in-dlq': 1}
Backoff schedule: [1.0, 2.0, 4.0, 8.0]
```

## Security decisions

- `RetryQueue.enqueue()` is an SSRF chokepoint: every target URL passes the
  shared `hookrelay.ssrf.validate_target_url` guard (private/loopback/link-local
  addresses, system ports < 1024, and non-http(s) protocols are rejected) —
  the same guard `EndpointConfig.validate()` uses.
- Stored headers are JSON-serialized; sensitive values are never logged by the
  queue itself (see [endpoint-config-1.5.md](endpoint-config-1.5.md) for
  `HeaderManager.redact`).

## TDD validation

83 tests in `tests/test_delivery_core.py` cover enqueue/dequeue/attempt
lifecycle, backoff math (deterministic and jitter bounds), DLQ handoff,
tracker transitions, idempotency rejection, and the SSRF enqueue chokepoint.
Final regression result: **731 passed, 0 failed**.
