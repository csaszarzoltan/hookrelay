"""Persistent retry queue and delivery tracking example (hookrelay v1.5.0).

Demonstrates the production delivery infrastructure:
1. Configure a RetryPolicy (capped exponential backoff, deterministic without jitter).
2. Enqueue deliveries into the persistent RetryQueue.
3. Dequeue due deliveries and record attempts.
4. Watch the DeliveryTracker state machine: pending -> delivered, or
   pending -> in-dlq once retries are exhausted.

Usage:
    python examples/delivery_retry_queue.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.delivery import DeliveryTracker, RetryQueue
from hookrelay.storage import Storage


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-retry-")) / "deliveries.db"
    storage = Storage(str(db))
    queue = RetryQueue(storage)
    tracker = DeliveryTracker(storage)

    policy = RetryPolicy(
        max_retries=2,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        jitter=False,
    )

    # One delivery that will succeed on the first attempt, and one that will
    # fail every attempt and exhaust its retries.
    ok = queue.enqueue(
        delivery_id="dlv-ok",
        request_id="req-1",
        endpoint_id="ep-1",
        target_url="https://example.com/hook",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b'{"event": "order.created"}',
        policy=policy,
    )
    bad = queue.enqueue(
        delivery_id="dlv-bad",
        request_id="req-2",
        endpoint_id="ep-2",
        target_url="https://example.com/hook",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b'{"event": "payment.failed"}',
        policy=policy,
    )
    print(f"Enqueued {ok} and {bad} -> pending={queue.pending_count()}")

    due = queue.dequeue_due()
    print(f"Dequeued {len(due)} due delivery(ies)")

    # First attempt succeeds -> delivered (terminal state).
    status = queue.record_attempt(ok, success=True, response_status=200, duration_ms=42.0)
    print(f"record_attempt({ok}, success=True) -> {status!r}")

    # Two failures exhaust max_retries=2 -> the delivery moves to the DLQ.
    status = queue.record_attempt(
        bad, success=False, response_status=503, duration_ms=120.0, error="service unavailable"
    )
    print(f"record_attempt({bad}, fail 1/2) -> {status!r}")
    status = queue.record_attempt(
        bad, success=False, response_status=503, duration_ms=130.0, error="service unavailable"
    )
    print(f"record_attempt({bad}, fail 2/2) -> {status!r}")

    print("Status counts:", tracker.count_by_status())
    print("dlv-ok  status:", tracker.get_status(ok))
    print("dlv-bad status:", tracker.get_status(bad))

    # Backoff schedule (seconds) for the first 4 attempts under this policy.
    print("Backoff schedule:", [round(policy.backoff_delay(i), 2) for i in range(4)])


if __name__ == "__main__":
    main()
