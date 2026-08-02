"""MetricsCollector — delivery count aggregation for the team dashboard (T3).

Read-only aggregation over the ``deliveries`` and ``delivery_attempts``
tables (migration v5): counts by status, by endpoint, and bucketed
time-series. Safe to call from request handlers — never writes.

Statuses use the canonical vocabulary: pending/delivered/failed/in-dlq.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta

from hookrelay.storage import Storage

_CANONICAL_STATUSES = ("pending", "delivered", "failed", "in-dlq")


def _deliveries_table_exists(conn: sqlite3.Connection) -> bool:
    """Return True when the migration-v5 ``deliveries`` table is present.

    Migration v5 lands with T1; until then the table may be absent. All
    readers treat a missing table as empty data instead of raising.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deliveries'"
    ).fetchone()
    return row is not None


class MetricsCollector:
    """Aggregate delivery counts by status, endpoint, and time buckets."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def count_by_status(
        self,
        *,
        endpoint_id: str | None = None,
        since: datetime | None = None,
    ) -> dict[str, int]:
        """Return {status: count} for deliveries, optionally filtered.

        Statuses are the canonical vocabulary: pending/delivered/failed/in-dlq.
        Every canonical status is present in the result (zero-filled); only the
        ``deliveries`` table is consulted.
        """
        counts: dict[str, int] = {status: 0 for status in _CANONICAL_STATUSES}
        conn = self._storage._conn
        if not _deliveries_table_exists(conn):
            return counts
        query = "SELECT status, COUNT(*) FROM deliveries"
        conditions: list[str] = []
        params: list[str] = []
        if endpoint_id is not None:
            conditions.append("endpoint_id = ?")
            params.append(endpoint_id)
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY status"
        for row in conn.execute(query, params).fetchall():
            counts[row["status"]] = int(row[1])
        return counts

    def count_by_endpoint(
        self,
        *,
        since: datetime | None = None,
    ) -> list[dict]:
        """Return per-endpoint delivery counts.

        ``[{'endpoint_id': str, 'delivered': int, 'failed': int, 'total': int}, ...]``

        ``delivered`` counts canonical ``delivered`` rows; ``failed`` counts
        ``failed`` and ``in-dlq`` rows; ``total`` counts every delivery row.
        Sorted by endpoint_id for deterministic output.
        """
        conn = self._storage._conn
        if not _deliveries_table_exists(conn):
            return []
        query = (
            "SELECT endpoint_id, status, COUNT(*) AS n FROM deliveries"
        )
        conditions: list[str] = []
        params: list[str] = []
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since.isoformat())
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY endpoint_id, status"
        by_endpoint: dict[str, dict] = {}
        for row in conn.execute(query, params).fetchall():
            entry = by_endpoint.setdefault(
                row["endpoint_id"],
                {"endpoint_id": row["endpoint_id"], "delivered": 0, "failed": 0, "total": 0},
            )
            entry["total"] += int(row["n"])
            if row["status"] == "delivered":
                entry["delivered"] += int(row["n"])
            elif row["status"] in ("failed", "in-dlq"):
                entry["failed"] += int(row["n"])
        return [by_endpoint[eid] for eid in sorted(by_endpoint)]

    def time_series(
        self,
        *,
        bucket_minutes: int = 5,
        window_minutes: int = 60,
    ) -> list[dict]:
        """Return chronological delivery counts bucketed over a rolling window.

        ``[{'bucket': iso_ts, 'delivered': int, 'failed': int}, ...]`` oldest -> newest.
        Buckets cover the full window (zero-filled where no deliveries occurred).
        ``bucket`` is the bucket start time in ISO-8601 UTC.
        """
        now = datetime.now(UTC)
        window_start = now - timedelta(minutes=window_minutes)
        bucket_size = timedelta(minutes=bucket_minutes)
        bucket_count = max(1, math.ceil(window_minutes / bucket_minutes))
        buckets = [
            {
                "bucket": (window_start + i * bucket_size).isoformat(),
                "delivered": 0,
                "failed": 0,
            }
            for i in range(bucket_count)
        ]
        conn = self._storage._conn
        if not _deliveries_table_exists(conn):
            return buckets
        rows = conn.execute(
            "SELECT created_at, status FROM deliveries WHERE created_at >= ?",
            (window_start.isoformat(),),
        ).fetchall()
        for row in rows:
            created = datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            elapsed = created - window_start
            index = int(elapsed.total_seconds() // bucket_size.total_seconds())
            index = max(0, min(index, bucket_count - 1))
            if row["status"] == "delivered":
                buckets[index]["delivered"] += 1
            elif row["status"] in ("failed", "in-dlq"):
                buckets[index]["failed"] += 1
        return buckets
