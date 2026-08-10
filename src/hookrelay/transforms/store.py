"""Persistence layer for named transformation rules."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.storage import Storage


class TransformationStore:
    """SQLite-backed store for named transformation rules.

    Rules persist a ``name`` and an ordered ``filters`` list that can be
    replayed through :class:`hookrelay.transforms.engine.TransformationEngine`
    by the delivery pipeline.
    """

    def __init__(self, storage: Storage) -> None:
        """Initialize the store bound to ``storage``."""
        self._storage = storage
        self._conn = storage._conn

    def _init_table(self) -> None:
        """Ensure the transformations table exists."""
        self._storage._init_transformations_table()

    def create(
        self, name: str, filters: list[str]
    ) -> dict[str, Any]:
        """Create a transformation rule and return its record.

        Args:
            name: Human-readable, non-empty name (allowlisted pattern).
            filters: Ordered list of JQ-style filter expressions.

        Returns:
            The created record dict.

        Raises:
            ValueError: If ``name`` is empty or filters are not strings.
        """
        if not name or not name.strip():
            raise ValueError("name must not be empty")
        if not isinstance(filters, list) or not all(
            isinstance(f, str) for f in filters
        ):
            raise ValueError("filters must be a list of strings")
        name = name.strip()
        if len(name) > 120:
            raise ValueError("name must be 120 characters or fewer")
        self._init_table()
        transform_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO transformations
               (transform_id, name, filters, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (transform_id, name, json.dumps(filters), now, now),
        )
        self._conn.commit()
        return self.get(transform_id)  # type: ignore[return-value]

    def get(self, transform_id: str) -> dict[str, Any] | None:
        """Return a transformation record or ``None`` if absent."""
        self._init_table()
        row = self._conn.execute(
            "SELECT * FROM transformations WHERE transform_id = ?",
            (transform_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list(self) -> list[dict[str, Any]]:
        """Return all transformation rules, newest first."""
        self._init_table()
        rows = self._conn.execute(
            "SELECT * FROM transformations ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update(
        self, transform_id: str, *, name: str | None = None, filters: list[str] | None = None
    ) -> dict[str, Any] | None:
        """Update a transformation rule; return the updated record or ``None``.

        Args:
            transform_id: The rule's id.
            name: Optional new name (validated).
            filters: Optional new filters list.

        Returns:
            The updated record, or ``None`` if the id does not exist.

        Raises:
            ValueError: If a provided ``name`` is empty or ``filters`` invalid.
        """
        existing = self.get(transform_id)
        if existing is None:
            return None
        if name is not None:
            if not name.strip():
                raise ValueError("name must not be empty")
            if len(name.strip()) > 120:
                raise ValueError("name must be 120 characters or fewer")
            name = name.strip()
        if filters is not None and (
            not isinstance(filters, list) or not all(isinstance(f, str) for f in filters)
        ):
            raise ValueError("filters must be a list of strings")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE transformations
               SET name = ?, filters = ?, updated_at = ?
               WHERE transform_id = ?""",
            (
                name if name is not None else existing["name"],
                json.dumps(filters if filters is not None else existing["filters"]),
                now,
                transform_id,
            ),
        )
        self._conn.commit()
        return self.get(transform_id)  # type: ignore[return-value]

    def delete(self, transform_id: str) -> bool:
        """Delete a transformation rule; return True if deleted."""
        self._init_table()
        cur = self._conn.execute(
            "DELETE FROM transformations WHERE transform_id = ?",
            (transform_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a SQLite row to a dict with JSON fields decoded."""
        d = dict(row)
        if isinstance(d.get("filters"), str):
            d["filters"] = json.loads(d["filters"])
        return d
