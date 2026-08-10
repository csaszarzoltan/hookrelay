"""Destination store for managing per-bin delivery destinations."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.storage import Storage


class DestinationStore:
    """SQLite-backed store for named destination rules per capture bin.

    Destinations define where webhooks from a bin are forwarded, with optional
    transformation, signing, retry policy, and delivery mode.
    """

    def __init__(self, storage: Storage) -> None:
        """Initialize the store bound to ``storage``."""
        self._storage = storage
        self._conn = storage._conn

    def _init_table(self) -> None:
        """Ensure the destinations table exists."""
        self._storage._init_destinations_table()

    def create(
        self,
        bin_id: str,
        url: str,
        transform_id: str | None = None,
        signing_config: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_policy: dict[str, Any] | None = None,
        enabled: bool = True,
        weight: int = 1,
        delivery_mode: str = "broadcast",
    ) -> dict[str, Any]:
        """Create a destination and return its record."""
        if not bin_id or not bin_id.strip():
            raise ValueError("bin_id must not be empty")
        if not url or not url.strip():
            raise ValueError("url must not be empty")
        if weight < 1:
            raise ValueError("weight must be >= 1")
        if delivery_mode not in ("broadcast", "round-robin", "weighted"):
            raise ValueError("delivery_mode must be broadcast, round-robin, or weighted")

        self._init_table()
        destination_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO destinations
               (destination_id, bin_id, url, transform_id, signing_config,
                headers, retry_policy, enabled, weight, delivery_mode,
                delivered_count, failed_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                destination_id,
                bin_id.strip(),
                url.strip(),
                transform_id,
                json.dumps(signing_config or {}),
                json.dumps(headers or {}),
                json.dumps(retry_policy or {}),
                1 if enabled else 0,
                weight,
                delivery_mode,
                now,
                now,
            ),
        )
        self._conn.commit()
        return self.get(destination_id)  # type: ignore[return-value]

    def get(self, destination_id: str) -> dict[str, Any] | None:
        """Return a destination record or ``None`` if absent."""
        self._init_table()
        row = self._conn.execute(
            "SELECT * FROM destinations WHERE destination_id = ?",
            (destination_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list(self, bin_id: str | None = None) -> list[dict[str, Any]]:
        """Return all destinations, newest first, optionally filtered by bin_id."""
        self._init_table()
        if bin_id:
            rows = self._conn.execute(
                "SELECT * FROM destinations WHERE bin_id = ? ORDER BY created_at DESC",
                (bin_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM destinations ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update(
        self,
        destination_id: str,
        *,
        url: str | None = None,
        transform_id: str | None = None,
        signing_config: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_policy: dict[str, Any] | None = None,
        enabled: bool | None = None,
        weight: int | None = None,
        delivery_mode: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a destination; return the updated record or ``None``."""
        existing = self.get(destination_id)
        if existing is None:
            return None

        if url is not None and (not url or not url.strip()):
            raise ValueError("url must not be empty")
        if weight is not None and weight < 1:
            raise ValueError("weight must be >= 1")
        if delivery_mode is not None and delivery_mode not in (
            "broadcast",
            "round-robin",
            "weighted",
        ):
            raise ValueError("delivery_mode must be broadcast, round-robin, or weighted")

        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE destinations
               SET url = ?, transform_id = ?, signing_config = ?, headers = ?,
                   retry_policy = ?, enabled = ?, weight = ?, delivery_mode = ?,
                   updated_at = ?
               WHERE destination_id = ?""",
            (
                url if url is not None else existing["url"],
                transform_id if transform_id is not None else existing["transform_id"],
                json.dumps(signing_config if signing_config is not None else existing["signing_config"]),
                json.dumps(headers if headers is not None else existing["headers"]),
                json.dumps(retry_policy if retry_policy is not None else existing["retry_policy"]),
                1 if (enabled if enabled is not None else existing["enabled"]) else 0,
                weight if weight is not None else existing["weight"],
                delivery_mode if delivery_mode is not None else existing["delivery_mode"],
                now,
                destination_id,
            ),
        )
        self._conn.commit()
        return self.get(destination_id)  # type: ignore[return-value]

    def delete(self, destination_id: str) -> bool:
        """Delete a destination; return True if deleted."""
        self._init_table()
        cur = self._conn.execute(
            "DELETE FROM destinations WHERE destination_id = ?",
            (destination_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a SQLite row to a dict with JSON fields decoded."""
        d = dict(row)
        for field in ("signing_config", "headers", "retry_policy"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        d["enabled"] = bool(d.get("enabled", 1))
        return d