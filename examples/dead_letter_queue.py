"""Dead-letter queue example (hookrelay v1.5.0).

Shows how permanently failed deliveries land in the DeadLetterQueue
with their failure metadata, how operators inspect them, and how an
entry can be requeued back into the retry queue.

Usage:
    python examples/dead_letter_queue.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hookrelay.delivery import DeadLetterQueue, DeliveryTracker, RetryQueue
from hookrelay.storage import Storage


def main() -> None:
    db = Path(tempfile.mkdtemp(prefix="hookrelay-dlq-")) / "deliveries.db"
    storage = Storage(str(db))
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

    # Simulate the retry queue exhausting retries and handing off to the DLQ.
    entry_id = dlq.dead_letter("dlv-1", reason="max retries exceeded", error="HTTP 500")
    print(f"Dead-lettered entry {entry_id[:8]}... -> status={tracker.get_status('dlv-1')}")
    print(f"DLQ count: {dlq.count()}")

    entry = dlq.get(entry_id)
    if entry is None:
        raise SystemExit("expected dlq entry to exist")
    print(f"Entry reason: {entry['reason']!r}, error: {entry['error']!r}")

    # Requeue resets attempt_count to 0 and flips the delivery back to pending.
    restored = dlq.requeue(entry_id)
    print(f"Requeued delivery {restored} -> status={tracker.get_status(restored)}")
    print(f"DLQ count after requeue: {dlq.count()}")


if __name__ == "__main__":
    main()
