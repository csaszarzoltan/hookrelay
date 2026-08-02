"""IdempotencyManager — key-based dedup with TTL (T1).

Stores idempotency keys mapped to the first delivery that consumed them.
A key is "active" until its expiry; registering an active key again is
rejected so retries/duplicate webhook events never double-deliver.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hookrelay.storage import Storage

_IDEMPOTENCY_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at);
"""


class IdempotencyManager:
    """Idempotency key registry with TTL expiry."""

    def __init__(self, storage: Storage, ttl_seconds: int = 86400) -> None:
        self._storage = storage
        self._ttl_seconds = ttl_seconds
        self._conn = storage._conn  # shared repo pattern (see audit.py)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the idempotency_keys table if missing (idempotent)."""
        self._conn.executescript(_IDEMPOTENCY_SCHEMA)
        self._conn.commit()

    def register(self, key: str, delivery_id: str) -> bool:
        """Store key -> delivery_id with expires_at = now + ttl.

        Returns True if newly registered, False if the key is already active
        (in which case the original mapping is left untouched).
        """
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        row = self._conn.execute(
            "SELECT expires_at FROM idempotency_keys WHERE key = ?", (key,)
        ).fetchone()
        if row is not None and row["expires_at"] > now_iso:
            return False
        expires_at = (now + timedelta(seconds=self._ttl_seconds)).isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO idempotency_keys
               (key, delivery_id, expires_at, created_at)
               VALUES (?, ?, ?, ?)""",
            (key, delivery_id, expires_at, now_iso),
        )
        self._conn.commit()
        return True

    def lookup(self, key: str) -> str | None:
        """Return the delivery_id for an active key, or None."""
        row = self._conn.execute(
            "SELECT delivery_id, expires_at FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None or row["expires_at"] <= datetime.now(UTC).isoformat():
            return None
        return str(row["delivery_id"])

    def is_active(self, key: str) -> bool:
        """True when the key exists and has not expired."""
        return self.lookup(key) is not None

    def purge_expired(self) -> int:
        """Delete expired keys; returns the number of purged rows."""
        cursor = self._conn.execute(
            "DELETE FROM idempotency_keys WHERE expires_at <= ?",
            (datetime.now(UTC).isoformat(),),
        )
        self._conn.commit()
        return cursor.rowcount
