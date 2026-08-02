"""SuccessRateCalculator — delivered/total rates for the team dashboard (T3).

Read-only success-rate math over the ``deliveries`` table (canonical
statuses) with configurable sliding windows, overall and per endpoint.
Canonical statuses: ``delivered`` counts as success; ``failed`` and
``in-dlq`` count as failures; ``pending`` is excluded from the rate.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from hookrelay.storage import Storage


def _deliveries_table_exists(conn: sqlite3.Connection) -> bool:
    """Return True when the migration-v5 ``deliveries`` table is present."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deliveries'"
    ).fetchone()
    return row is not None


class SuccessRateCalculator:
    """Compute delivery success rates over configurable windows."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def _counts(
        self,
        *,
        endpoint_id: str | None = None,
        window_minutes: int = 60,
    ) -> tuple[int, int]:
        """Return (delivered, failed) counts for the window, ignoring pending."""
        conn = self._storage._conn
        if not _deliveries_table_exists(conn):
            return 0, 0
        conditions = ["status IN ('delivered', 'failed', 'in-dlq')"]
        params: list[str] = []
        if endpoint_id is not None:
            conditions.append("endpoint_id = ?")
            params.append(endpoint_id)
        cutoff = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
        conditions.append("created_at >= ?")
        params.append(cutoff)
        query = (
            "SELECT status, COUNT(*) AS n FROM deliveries WHERE "
            + " AND ".join(conditions)
            + " GROUP BY status"
        )
        delivered = 0
        failed = 0
        for row in conn.execute(query, params).fetchall():
            if row["status"] == "delivered":
                delivered += int(row["n"])
            else:
                failed += int(row["n"])
        return delivered, failed

    def rate(
        self,
        *,
        endpoint_id: str | None = None,
        window_minutes: int = 60,
    ) -> float:
        """Return delivered / (delivered + failed) for the window; 0.0 if none."""
        delivered, failed = self._counts(
            endpoint_id=endpoint_id, window_minutes=window_minutes
        )
        total = delivered + failed
        if total == 0:
            return 0.0
        return delivered / total

    def breakdown(
        self,
        *,
        window_minutes: int = 60,
    ) -> list[dict]:
        """Return per-endpoint success rates.

        ``[{'endpoint_id': str, 'delivered': int, 'failed': int, 'rate': float}, ...]``
        Sorted by endpoint_id for deterministic output.
        """
        conn = self._storage._conn
        if not _deliveries_table_exists(conn):
            return []
        cutoff = (datetime.now(UTC) - timedelta(minutes=window_minutes)).isoformat()
        rows = conn.execute(
            "SELECT endpoint_id, status, COUNT(*) AS n FROM deliveries "
            "WHERE status IN ('delivered', 'failed', 'in-dlq') AND created_at >= ? "
            "GROUP BY endpoint_id, status",
            (cutoff,),
        ).fetchall()
        by_endpoint: dict[str, dict] = {}
        for row in rows:
            entry = by_endpoint.setdefault(
                row["endpoint_id"],
                {"endpoint_id": row["endpoint_id"], "delivered": 0, "failed": 0, "rate": 0.0},
            )
            if row["status"] == "delivered":
                entry["delivered"] += int(row["n"])
            else:
                entry["failed"] += int(row["n"])
        result = []
        for eid in sorted(by_endpoint):
            entry = by_endpoint[eid]
            total = entry["delivered"] + entry["failed"]
            entry["rate"] = entry["delivered"] / total if total else 0.0
            result.append(entry)
        return result
