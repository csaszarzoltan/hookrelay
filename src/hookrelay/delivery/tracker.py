"""DeliveryTracker — per-delivery status state machine (T1).

Tracks every delivery through the canonical status vocabulary
(``DeliveryStatus``) and enforces the allowed transition edges:

    pending -> delivered | failed
    failed  -> in-dlq | pending
    in-dlq  -> pending

``delivered`` is terminal. Invalid transitions raise ``ValueError``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import uuid4

from hookrelay.storage import Storage

# Shared DDL for the deliveries table. RetryQueue writes rows here via
# enqueue/record_attempt; DeadLetterQueue flips status to in-dlq / resets to
# pending; DeliveryTracker owns the status state machine. Kept in this module
# so tracker, retry_queue, and dlq stay consistent without duplicating DDL.
DELIVERIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    target_url TEXT,
    method TEXT NOT NULL DEFAULT 'POST',
    headers TEXT NOT NULL DEFAULT '{}',
    body BLOB,
    idempotency_key TEXT,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    policy TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_status_next
    ON deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_endpoint ON deliveries(endpoint_id);
"""


class DeliveryStatus:
    """Canonical delivery statuses (str-enum style constants)."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    IN_DLQ = "in-dlq"
    ALL = (PENDING, DELIVERED, FAILED, IN_DLQ)


class DeliveryTracker:
    """Per-delivery status state machine backed by the deliveries table."""

    # Allowed transitions per current status. delivered is terminal.
    _ALLOWED: ClassVar[dict[str, set[str]]] = {
        DeliveryStatus.PENDING: {DeliveryStatus.DELIVERED, DeliveryStatus.FAILED},
        DeliveryStatus.FAILED: {DeliveryStatus.IN_DLQ, DeliveryStatus.PENDING},
        DeliveryStatus.IN_DLQ: {DeliveryStatus.PENDING},
        DeliveryStatus.DELIVERED: set(),
    }

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._conn = storage._conn  # shared repo pattern (see audit.py)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the deliveries table if it does not exist (idempotent)."""
        self._conn.executescript(DELIVERIES_SCHEMA)
        self._conn.commit()

    def create(
        self,
        *,
        request_id: str,
        endpoint_id: str,
        idempotency_key: str | None = None,
    ) -> str:
        """Insert delivery with status='pending'. Returns delivery_id."""
        delivery_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO deliveries
               (delivery_id, request_id, endpoint_id, idempotency_key, status,
                attempt_count, next_attempt_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
            (
                delivery_id,
                request_id,
                endpoint_id,
                idempotency_key,
                DeliveryStatus.PENDING,
                now,
                now,
                now,
            ),
        )
        self._conn.commit()
        return delivery_id

    def get_status(self, delivery_id: str) -> str:
        """Return the current status; raise KeyError if unknown."""
        row = self._conn.execute(
            "SELECT status FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown delivery: {delivery_id}")
        return str(row["status"])

    def transition(self, delivery_id: str, new_status: str) -> None:
        """Validate allowed edges; raise ValueError on invalid transition."""
        current = self.get_status(delivery_id)
        if new_status not in DeliveryStatus.ALL:
            raise ValueError(f"unknown status: {new_status}")
        if new_status not in self._ALLOWED[current]:
            raise ValueError(f"invalid transition: {current} -> {new_status}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE deliveries SET status = ?, updated_at = ? WHERE delivery_id = ?",
            (new_status, now, delivery_id),
        )
        self._conn.commit()

    def list(
        self,
        status: str | None = None,
        endpoint_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List deliveries, newest first, with optional status/endpoint filters."""
        query = "SELECT * FROM deliveries WHERE 1=1"
        params: list[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if endpoint_id is not None:
            query += " AND endpoint_id = ?"
            params.append(endpoint_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        """Return counts per status, always including every canonical status."""
        counts: dict[str, int] = {status: 0 for status in DeliveryStatus.ALL}
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status"
        ).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["n"])
        return counts
