"""RetryQueue — persistent retry queue with exponential backoff (T1).

Enqueues delivery records, hands due entries (``next_attempt_at <= now``) to
the worker, and records each attempt: a success marks the delivery
``delivered``; a failure either schedules the next attempt with exponential
backoff (capped at ``max_backoff``, optional jitter) or — once ``max_retries``
failed attempts are exhausted — moves the delivery to the DeadLetterQueue.

``RetryPolicy`` is consumed interface-only (duck-typed): the tests supply a
stand-in with the same attribute/method surface, so this module stays
decoupled from the T2 config package.
"""

from __future__ import annotations

import json
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from hookrelay.delivery.dlq import DeadLetterQueue
from hookrelay.delivery.idempotency import IdempotencyManager
from hookrelay.delivery.tracker import DELIVERIES_SCHEMA, DeliveryStatus
from hookrelay.ssrf import validate_target_url
from hookrelay.storage import Storage

if TYPE_CHECKING:
    from hookrelay.config.retry_policy import RetryPolicy

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BASE_DELAY = 1.0
_DEFAULT_BACKOFF_FACTOR = 2.0
_DEFAULT_MAX_BACKOFF = 3600.0
# Deterministic scheduling unless a policy explicitly enables jitter — keeps
# retry timings reproducible in tests and operations.
_DEFAULT_JITTER = False

# Fields a duck-typed policy is expected to expose (mirrors RetryPolicy).
_POLICY_FIELDS = (
    "max_retries",
    "backoff_factor",
    "base_delay_seconds",
    "max_backoff_seconds",
    "jitter",
)


class RetryQueue:
    """Persistent retry queue with exponential backoff."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._conn = storage._conn  # shared repo pattern (see audit.py)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the deliveries table if missing (idempotent)."""
        self._conn.executescript(DELIVERIES_SCHEMA)
        self._conn.commit()

    def enqueue(
        self,
        *,
        delivery_id: str,
        request_id: str,
        endpoint_id: str,
        target_url: str,
        method: str,
        headers: dict[str, str],
        body: bytes | None,
        idempotency_key: str | None = None,
        policy: RetryPolicy | None = None,
    ) -> str:
        """Insert delivery row with status='pending', next_attempt_at=now.

        Returns delivery_id. Raises ValueError if idempotency_key already
        active or if ``target_url`` fails the SSRF guard.
        """
        is_valid, reason = validate_target_url(target_url)
        if not is_valid:
            raise ValueError(f"target_url fails SSRF guard: {reason}")
        manager = IdempotencyManager(self._storage)
        if idempotency_key is not None and manager.is_active(idempotency_key):
            raise ValueError(f"idempotency key already active: {idempotency_key}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO deliveries
               (delivery_id, request_id, endpoint_id, target_url, method,
                headers, body, idempotency_key, status, attempt_count,
                next_attempt_at, policy, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                delivery_id,
                request_id,
                endpoint_id,
                target_url,
                method,
                json.dumps(headers),
                body,
                idempotency_key,
                DeliveryStatus.PENDING,
                now,
                self._policy_to_json(policy),
                now,
                now,
            ),
        )
        self._conn.commit()
        if idempotency_key is not None:
            manager.register(idempotency_key, delivery_id)
        return delivery_id

    def dequeue_due(self, limit: int = 100, now: datetime | None = None) -> list[dict]:
        """Return pending deliveries with next_attempt_at <= now (oldest first)."""
        now_iso = (now if now is not None else datetime.now(UTC)).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM deliveries
               WHERE status = ? AND next_attempt_at IS NOT NULL AND next_attempt_at <= ?
               ORDER BY next_attempt_at ASC, created_at ASC
               LIMIT ?""",
            (DeliveryStatus.PENDING, now_iso, limit),
        ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def record_attempt(
        self,
        delivery_id: str,
        *,
        success: bool,
        response_status: int | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> str:
        """Persist one attempt, increment attempt_count, transition status.

        success -> 'delivered'; failure with attempts remaining -> 'pending'
        with backoff next_attempt_at; failure past max_retries -> DLQ
        ('in-dlq'). Returns new status.
        """
        row = self._conn.execute(
            "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown delivery: {delivery_id}")
        item = dict(row)
        policy = self._stored_policy(item)
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        attempt_count = int(item["attempt_count"]) + 1

        if success:
            new_status = DeliveryStatus.DELIVERED
            next_attempt_at: str | None = None
            last_error: str | None = None
        elif attempt_count >= policy.get("max_retries", _DEFAULT_MAX_RETRIES):
            # Exhausted retries: persist the incremented attempt count, then
            # hand off to the DLQ, which snapshots metadata and flips status.
            self._conn.execute(
                """UPDATE deliveries
                   SET attempt_count = ?, last_error = ?, updated_at = ?
                   WHERE delivery_id = ?""",
                (attempt_count, error, now_iso, delivery_id),
            )
            self._conn.commit()
            DeadLetterQueue(self._storage).dead_letter(
                delivery_id, reason="max retries exceeded", error=error
            )
            self._record_attempt_row(item, DeliveryStatus.IN_DLQ, response_status, duration_ms, error)
            return DeliveryStatus.IN_DLQ
        else:
            new_status = DeliveryStatus.PENDING
            delay = self.backoff_delay(
                attempt_count - 1,
                base_delay=policy.get("base_delay_seconds", _DEFAULT_BASE_DELAY),
                backoff_factor=policy.get("backoff_factor", _DEFAULT_BACKOFF_FACTOR),
                max_backoff=policy.get("max_backoff_seconds", _DEFAULT_MAX_BACKOFF),
                jitter=policy.get("jitter", _DEFAULT_JITTER),
            )
            next_attempt_at = (now + timedelta(seconds=delay)).isoformat()
            last_error = error

        self._conn.execute(
            """UPDATE deliveries
               SET status = ?, attempt_count = ?, next_attempt_at = ?,
                   last_error = ?, updated_at = ?
               WHERE delivery_id = ?""",
            (new_status, attempt_count, next_attempt_at, last_error, now_iso, delivery_id),
        )
        self._conn.commit()
        self._record_attempt_row(item, new_status, response_status, duration_ms, error)
        return new_status

    def _record_attempt_row(
        self,
        item: dict[str, Any],
        status: str,
        response_status: int | None,
        duration_ms: float | None,
        error: str | None,
    ) -> None:
        """Append one row to delivery_attempts via the existing storage API."""
        self._storage.store_delivery_attempt(
            request_id=item.get("request_id", ""),
            channel=item.get("channel", ""),
            status=status,
            target_url=item.get("target_url"),
            response_status=response_status,
            duration_ms=duration_ms,
            error=error,
            delivery_id=item.get("delivery_id"),
            endpoint_id=item.get("endpoint_id"),
        )

    @staticmethod
    def backoff_delay(
        attempt: int,
        *,
        base_delay: float = 1.0,
        backoff_factor: float = 2.0,
        max_backoff: float = 3600.0,
        jitter: bool = True,
    ) -> float:
        """Pure function: min(max_backoff, base_delay * backoff_factor ** attempt),
        plus optional uniform jitter in [0, delay). attempt is 0-indexed.
        """
        base = min(max_backoff, base_delay * (backoff_factor**attempt))
        if not jitter:
            return base
        return base + random.random() * base

    def pending_count(self) -> int:
        """Number of deliveries currently in 'pending' status."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM deliveries WHERE status = ?",
            (DeliveryStatus.PENDING,),
        ).fetchone()
        return int(row["n"])

    def get(self, delivery_id: str) -> dict | None:
        """Return one delivery by id, or None."""
        row = self._conn.execute(
            "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def delete(self, delivery_id: str) -> bool:
        """Delete a delivery; returns True if a row was removed."""
        cursor = self._conn.execute(
            "DELETE FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _policy_to_json(policy: Any) -> str | None:
        """Serialize a duck-typed policy to JSON for persistence."""
        if policy is None:
            return None
        if hasattr(policy, "to_dict"):
            data = policy.to_dict()
        else:
            data = {f: getattr(policy, f) for f in _POLICY_FIELDS if hasattr(policy, f)}
        return json.dumps(data) if data else None

    @staticmethod
    def _stored_policy(item: dict[str, Any]) -> dict[str, Any]:
        """Deserialize the stored policy JSON back to a plain dict."""
        raw = item.get("policy")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a deliveries row, parsing JSON columns."""
        item = dict(row)
        if isinstance(item.get("headers"), str):
            try:
                item["headers"] = json.loads(item["headers"])
            except ValueError:
                pass
        if item.get("policy"):
            try:
                item["policy"] = json.loads(item["policy"])
            except ValueError:
                pass
        return item
