# Hookrelay 1.5 Dead-Letter Queue

## Goal

Give permanently failed deliveries a durable, inspectable home. When a
delivery exhausts its retries, the retry queue moves it to the dead-letter
queue together with the failure reason, the last error, and the full delivery
metadata — so operators can review, debug, and requeue without losing
evidence.

## Component

`hookrelay.delivery.DeadLetterQueue` — dead-letter storage backed by the `dlq`
table (created idempotently). It shares the application `Storage` connection,
the same pattern as the other delivery modules.

| Method | Behaviour |
|---|---|
| `dead_letter(delivery_id, *, reason, error=None)` | Copy the delivery row into `dlq`, set the delivery status to `in-dlq`, and return a new `entry_id`. If the delivery row is unknown (e.g. dead-lettered before enqueue), the failure is still persisted with minimal metadata for manual review. |
| `list_entries(limit=100, endpoint_id=None)` | List entries, newest first, optionally filtered by endpoint. |
| `requeue(entry_id)` | Reset `attempt_count` to 0, flip the delivery back to `pending` with `next_attempt_at = now`, and delete the `dlq` row. Returns the `delivery_id`. Raises `KeyError` for an unknown entry. |
| `count()` / `get(entry_id)` | Queue introspection. |

### `dlq` table columns

`entry_id` (PK), `delivery_id`, `request_id`, `endpoint_id`, `target_url`,
`method`, `headers` (JSON), `body`, `idempotency_key`, `attempt_count`,
`reason`, `error`, `dead_lettered_at`. An index on `endpoint_id` keeps
per-endpoint review fast.

## Usage

```python
from hookrelay.delivery import DeadLetterQueue, DeliveryTracker, RetryQueue
from hookrelay.storage import Storage

storage = Storage("webhooks.db")
queue = RetryQueue(storage)
dlq = DeadLetterQueue(storage)
tracker = DeliveryTracker(storage)

queue.enqueue(
    delivery_id="dlv-1",
    request_id="req-1",
    endpoint_id="ep-1",
    target_url="https://example.com/hook",
    method="POST",
    headers={},
    body=b'{"event": "order.created"}',
)

entry_id = dlq.dead_letter("dlv-1", reason="max retries exceeded", error="HTTP 500")
print(tracker.get_status("dlv-1"))   # in-dlq
print(dlq.count())                   # 1

restored = dlq.requeue(entry_id)
print(tracker.get_status(restored))  # pending, attempt_count reset to 0
```

A complete, runnable version is at
[`examples/dead_letter_queue.py`](../examples/dead_letter_queue.py).

### Sample output (from the example)

```text
Dead-lettered entry d77c6e5c... -> status=in-dlq
DLQ count: 1
Entry reason: 'max retries exceeded', error: 'HTTP 500'
Requeued delivery dlv-1 -> status=pending
DLQ count after requeue: 0
```

## Operational notes

- The retry queue hands off automatically: `RetryQueue.record_attempt` moves a
  delivery to the DLQ once `attempt_count >= max_retries`.
- Requeueing restarts the full retry budget — there is no cap on how many
  times an entry can be requeued, so gate manual requeues by endpoint health.
- Failed deliveries are counted in the dashboard `failed` bucket (they have
  status `failed` or `in-dlq`); see
  [dashboard-metrics-1.5.md](dashboard-metrics-1.5.md).

## TDD validation

DLQ behaviour (dead-letter placement, reason persistence, status flip to
`in-dlq`, count/listing, endpoint filtering, requeue reset) is covered in
`tests/test_delivery_core.py` as part of the 83 delivery-core tests. Final
regression result: **731 passed, 0 failed**.
