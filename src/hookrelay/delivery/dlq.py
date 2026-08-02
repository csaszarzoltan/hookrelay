"""DeadLetterQueue — dead-letter storage for permanently failed deliveries (T1).

When a delivery exhausts its retries, the queue moves it here together with
the failure reason. Entries can be inspected (optionally filtered by
endpoint), requeued back into the retry queue, or left for manual review.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.delivery.tracker import DELIVERIES_SCHEMA, DeliveryStatus
from hookrelay.storage import Storage

_DLQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS dlq (
    entry_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    request_id TEXT NOT NULL DEFAULT '',
    endpoint_id TEXT NOT NULL DEFAULT '',
    target_url TEXT,
    method TEXT NOT NULL DEFAULT 'POST',
    headers TEXT NOT NULL DEFAULT '{}',
    body BLOB,
    idempotency_key TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    error TEXT,
    dead_lettered_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dlq_endpoint ON dlq(endpoint_id);
"""


class DeadLetterQueue:
    """Dead-letter queue for permanent delivery failures."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._conn = storage._conn  # shared repo pattern (see audit.py)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the dlq (and deliveries) tables if missing (idempotent)."""
        self._conn.executescript(DELIVERIES_SCHEMA)
        self._conn.executescript(_DLQ_SCHEMA)
        self._conn.commit()

    def dead_letter(
        self,
        delivery_id: str,
        *,
        reason: str,
        error: str | None = None,
    ) -> str:
        """Copy delivery metadata into dlq table, set status='in-dlq'.

        Returns the new dlq entry_id.
        """
        entry_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        row = self._conn.execute(
            "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if row is not None:
            item = dict(row)
            self._conn.execute(
                """INSERT INTO dlq
                   (entry_id, delivery_id, request_id, endpoint_id, target_url,
                    method, headers, body, idempotency_key, attempt_count,
                    reason, error, dead_lettered_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry_id,
                    delivery_id,
                    item.get("request_id", ""),
                    item.get("endpoint_id", ""),
                    item.get("target_url"),
                    item.get("method", "POST"),
                    item.get("headers", "{}"),
                    item.get("body"),
                    item.get("idempotency_key"),
                    item.get("attempt_count", 0),
                    reason,
                    error,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE deliveries SET status = ?, updated_at = ? WHERE delivery_id = ?",
                (DeliveryStatus.IN_DLQ, now, delivery_id),
            )
        else:
            # Delivery row unknown (e.g. dead-lettered straight from the queue
            # before enqueue) — still persist the failure for manual review.
            self._conn.execute(
                """INSERT INTO dlq
                   (entry_id, delivery_id, reason, error, dead_lettered_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (entry_id, delivery_id, reason, error, now),
            )
        self._conn.commit()
        return entry_id

    def list_entries(
        self, limit: int = 100, endpoint_id: str | None = None
    ) -> list[dict]:
        """List dlq entries, newest first, optionally filtered by endpoint."""
        query = "SELECT * FROM dlq WHERE 1=1"
        params: list[Any] = []
        if endpoint_id is not None:
            query += " AND endpoint_id = ?"
            params.append(endpoint_id)
        query += " ORDER BY dead_lettered_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            if isinstance(item.get("headers"), str):
                try:
                    item["headers"] = json.loads(item["headers"])
                except ValueError:
                    pass
            result.append(item)
        return result

    def requeue(self, entry_id: str) -> str:
        """Reset attempt_count=0, status='pending', next_attempt_at=now,
        delete the dlq row. Returns delivery_id."""
        row = self._conn.execute(
            "SELECT * FROM dlq WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown dlq entry: {entry_id}")
        item = dict(row)
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE deliveries
               SET attempt_count = 0, status = ?, next_attempt_at = ?, updated_at = ?
               WHERE delivery_id = ?""",
            (DeliveryStatus.PENDING, now, now, item["delivery_id"]),
        )
        self._conn.execute("DELETE FROM dlq WHERE entry_id = ?", (entry_id,))
        self._conn.commit()
        return item["delivery_id"]

    def count(self) -> int:
        """Return the number of entries currently in the dlq."""
        row = self._conn.execute("SELECT COUNT(*) AS n FROM dlq").fetchone()
        return int(row["n"])

    def get(self, entry_id: str) -> dict | None:
        """Return one dlq entry by id, or None."""
        row = self._conn.execute(
            "SELECT * FROM dlq WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)
