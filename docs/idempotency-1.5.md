# Hookrelay 1.5 Idempotency

## Goal

Prevent duplicate deliveries when webhook providers retry or re-send the same
event. A key is registered against the first delivery that consumes it and
stays active until its TTL expires; registering the same key again while it is
active is rejected, so retries and duplicate webhook events never
double-deliver.

## Component

`hookrelay.delivery.IdempotencyManager` — TTL-based key registry backed by the
`idempotency_keys` table (created idempotently).

| Method | Behaviour |
|---|---|
| `register(key, delivery_id)` | Store `key -> delivery_id` with `expires_at = now + ttl`. Returns `True` if newly registered; `False` if the key is already active (the original mapping is left untouched). |
| `lookup(key)` | Return the `delivery_id` for an active key, or `None` once the key has expired. |
| `is_active(key)` | `True` when the key exists and has not expired. |
| `purge_expired()` | Delete expired keys and return the number of purged rows. |

Constructor: `IdempotencyManager(storage, ttl_seconds=86400)` — the default
TTL is 24 hours, matching the `EndpointConfig.idempotency_ttl_seconds` default.

## Usage

```python
from hookrelay.delivery import IdempotencyManager
from hookrelay.storage import Storage

manager = IdempotencyManager(Storage("webhooks.db"), ttl_seconds=86400)

key = "stripe_evt_123"
manager.register(key, "dlv-0001")
assert manager.is_active(key)
assert manager.lookup(key) == "dlv-0001"

# A duplicate webhook event with the same key is rejected while active.
assert manager.register(key, "dlv-0002") is False
assert manager.lookup(key) == "dlv-0001"  # original mapping preserved
```

A complete, runnable version is at
[`examples/idempotency.py`](../examples/idempotency.py).

### Sample output (from the example)

```text
First register: True (True = newly registered)
is_active(stripe_evt_123): True
lookup(stripe_evt_123): dlv-0001
Duplicate register: False (False = already active, rejected)
Original mapping preserved: dlv-0001
Purged 0 expired key(s) (this key is still active)
```

## Integration with the retry queue

`RetryQueue.enqueue()` takes an optional `idempotency_key`: it rejects the
enqueue with `ValueError("idempotency key already active: ...")` before any
row is written, and registers the key only after the delivery row is inserted.
Use the webhook provider's own event id (Stripe `evt_...`, GitHub delivery id,
etc.) as the key — it must be stable across retries of the same event and
unique across distinct events.

## TDD validation

Idempotency register/lookup/expiry/purge behaviour and the enqueue-time
rejection are covered in `tests/test_delivery_core.py` as part of the 83
delivery-core tests. Final regression result: **731 passed, 0 failed**.
