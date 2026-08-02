"""Delivery infrastructure package — T1 core delivery (retry queue, DLQ, tracking, idempotency).

Implements analysis-brief.md §T1: RetryQueue (exponential backoff, max
retries), DeadLetterQueue (permanent failures with reason), DeliveryTracker
(status state machine), and IdempotencyManager (TTL key dedup).
"""

from hookrelay.delivery.dlq import DeadLetterQueue
from hookrelay.delivery.idempotency import IdempotencyManager
from hookrelay.delivery.retry_queue import RetryQueue
from hookrelay.delivery.tracker import DeliveryStatus, DeliveryTracker

__all__ = [
    "DeadLetterQueue",
    "DeliveryStatus",
    "DeliveryTracker",
    "IdempotencyManager",
    "RetryQueue",
]
