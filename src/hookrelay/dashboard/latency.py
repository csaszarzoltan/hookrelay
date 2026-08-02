"""LatencyTracker — duration_ms percentiles for the team dashboard (T3).

Read-only percentile and average computation over
``delivery_attempts.duration_ms`` (nearest-rank method), optionally
filtered by endpoint (via the ``deliveries`` table) and by a sliding
time window.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime, timedelta

from hookrelay.storage import Storage


def _deliveries_table_exists(conn: sqlite3.Connection) -> bool:
    """Return True when the migration-v5 ``deliveries`` table is present."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deliveries'"
    ).fetchone()
    return row is not None


class LatencyTracker:
    """Compute p50/p95/p99 latency percentiles from delivery attempts."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def _duration_ms(
        self,
        *,
        endpoint_id: str | None = None,
        window_minutes: int | None = None,
    ) -> list[float]:
        """Return matching duration_ms values (non-null), ascending order not required."""
        conn = self._storage._conn
        conditions: list[str] = ["da.duration_ms IS NOT NULL"]
        params: list[str] = []
        if window_minutes is not None:
            cutoff = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
            conditions.append("da.attempted_at >= ?")
            params.append(cutoff)
        if endpoint_id is not None:
            # Join delivery_attempts -> deliveries on delivery_id (unique per
            # delivery) rather than request_id, which is 1:N under fan-out and
            # would misattribute latency under shared request_ids.
            if not _deliveries_table_exists(conn):
                return []
            conditions.append("da.delivery_id = d.delivery_id AND d.endpoint_id = ?")
            params.append(endpoint_id)
            query = (
                "SELECT da.duration_ms FROM delivery_attempts da "
                "JOIN deliveries d ON da.delivery_id = d.delivery_id "
                "WHERE " + " AND ".join(conditions)
            )
        else:
            query = (
                "SELECT da.duration_ms FROM delivery_attempts da WHERE "
                + " AND ".join(conditions)
            )
        rows = conn.execute(query, params).fetchall()
        return [float(row["duration_ms"]) for row in rows]

    def percentile(
        self,
        p: float,
        *,
        endpoint_id: str | None = None,
        window_minutes: int | None = None,
    ) -> float | None:
        """Return the p-th percentile of duration_ms (nearest-rank); None if no data.

        p must be in (0, 100].
        """
        values = sorted(
            self._duration_ms(endpoint_id=endpoint_id, window_minutes=window_minutes)
        )
        if not values:
            return None
        if p <= 0 or p > 100:
            raise ValueError("p must be in (0, 100]")
        rank = math.ceil(p / 100 * len(values))
        return values[rank - 1]

    def percentiles(
        self,
        ps: list[float] | None = None,
        *,
        endpoint_id: str | None = None,
        window_minutes: int | None = None,
    ) -> dict[float, float | None]:
        """Return {p: value} for each requested percentile (default p50/p95/p99)."""
        requested = ps if ps is not None else [50.0, 95.0, 99.0]
        return {
            p: self.percentile(
                p, endpoint_id=endpoint_id, window_minutes=window_minutes
            )
            for p in requested
        }

    def average(
        self,
        *,
        endpoint_id: str | None = None,
        window_minutes: int | None = None,
    ) -> float | None:
        """Return mean duration_ms over matching attempts; None if no data."""
        values = self._duration_ms(endpoint_id=endpoint_id, window_minutes=window_minutes)
        if not values:
            return None
        return sum(values) / len(values)
