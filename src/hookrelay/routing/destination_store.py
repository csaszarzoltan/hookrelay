"""Persistence layer for per-destination forwarding targets."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.security.outgoing import SUPPORTED_ALGORITHMS
from hookrelay.ssrf import validate_target_url
from hookrelay.storage import Storage


def validate_destination_url(url: str) -> str:
    """Validate and normalize a destination URL through the SSRF guard.

    Enforces the repo-wide SSRF policy (scheme allowlist http/https,
    private/loopback/link-local rejection, system-port block) so a
    destination can never point at an internal address.

    Raises:
        ValueError: When the URL is empty or fails the SSRF guard.
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty")
    url = url.strip()
    is_valid, reason = validate_target_url(url)
    if not is_valid:
        raise ValueError(f"url fails SSRF guard: {reason}")
    return url


def validate_signing_config(signing_config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a destination's outgoing signing configuration.

    Enforces the same contract as :class:`hookrelay.security.outgoing.OutgoingSigner`:
    the algorithm must be one of ``svix`` / ``hookdeck`` / ``github`` /
    ``custom`` and the secret must be a non-empty string.

    Raises:
        ValueError: When the algorithm is unknown or the secret is invalid.
    """
    if signing_config is None:
        return None
    if not isinstance(signing_config, dict):
        raise TypeError("signing_config must be an object")
    algorithm = signing_config.get("algorithm")
    if not algorithm:
        # An empty signing config object means "no signing" — same as None.
        if not signing_config:
            return None
        raise ValueError("signing_config.algorithm is required")
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(
            f"unsupported signing algorithm '{algorithm}'; "
            f"supported: {', '.join(sorted(SUPPORTED_ALGORITHMS))}"
        )
    secret = signing_config.get("secret")
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("signing_config.secret must be a non-empty string")
    if len(secret) < 8:
        raise ValueError("signing_config.secret must be at least 8 characters")
    return dict(signing_config)


def validate_retry_policy(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a destination's per-destination retry policy.

    When *policy* is not ``None``, each **present** field is validated against
    the ranges expected by :class:`hookrelay.delivery.retry_queue.RetryQueue`.
    Missing fields are left for the queue to fill with defaults (partial
    policies are permitted).

    Returns:
        The validated policy dict, or ``None`` if no policy was given.

    Raises:
        TypeError: If *policy* is not a dict or ``None``.
        ValueError: If any present field is out of the accepted range.
    """
    if policy is None:
        return None
    if not isinstance(policy, dict):
        raise TypeError("retry_policy must be an object")
    if not policy:
        # Empty dict means "use defaults" — equivalent to None.
        return None

    validated = dict(policy)

    if "max_retries" in validated:
        v = validated["max_retries"]
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("retry_policy.max_retries must be an integer")
        if v < 1 or v > 20:
            raise ValueError(
                "retry_policy.max_retries must be between 1 and 20"
            )

    if "base_delay_seconds" in validated:
        v = validated["base_delay_seconds"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(
                "retry_policy.base_delay_seconds must be a number"
            )
        if v < 0.1 or v > 3600:
            raise ValueError(
                "retry_policy.base_delay_seconds must be between 0.1 and 3600"
            )

    if "backoff_factor" in validated:
        v = validated["backoff_factor"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError("retry_policy.backoff_factor must be a number")
        if v < 1.0 or v > 10.0:
            raise ValueError(
                "retry_policy.backoff_factor must be between 1.0 and 10.0"
            )

    if "max_backoff_seconds" in validated:
        v = validated["max_backoff_seconds"]
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ValueError(
                "retry_policy.max_backoff_seconds must be a number"
            )
        if v < 1 or v > 86400:
            raise ValueError(
                "retry_policy.max_backoff_seconds must be between 1 and 86400"
            )

    if "jitter" in validated and not isinstance(validated["jitter"], bool):
        raise ValueError("retry_policy.jitter must be a boolean")

    return validated


class DestinationStore:
    """SQLite-backed store for per-destination forwarding targets."""

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
        *,
        transform_id: str | None = None,
        signing_config: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_policy: dict[str, Any] | None = None,
        enabled: bool = True,
        weight: int = 1,
        delivery_mode: str = "broadcast",
    ) -> dict[str, Any]:
        """Create a destination and return its record.

        Args:
            bin_id: The capture bin this destination belongs to.
            url: Target URL (validated non-empty).
            transform_id: Optional transformation rule id.
            signing_config: Optional signing config (algorithm, secret).
            headers: Extra headers to forward.
            retry_policy: Per-destination retry policy.
            enabled: Whether the destination is active.
            weight: Weight for weighted delivery mode.
            delivery_mode: Default mode for this destination.

        Returns:
            The created record dict.

        Raises:
            ValueError: If required fields are empty or invalid.
        """
        if not bin_id or not bin_id.strip():
            raise ValueError("bin_id must not be empty")
        url = validate_destination_url(url)
        if weight < 1:
            raise ValueError("weight must be >= 1")
        if delivery_mode not in ("broadcast", "round_robin", "weighted"):
            raise ValueError("delivery_mode must be broadcast|round_robin|weighted")
        signing_config = validate_signing_config(signing_config)
        retry_policy = validate_retry_policy(retry_policy)

        self._init_table()
        destination_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO destinations
              (destination_id, bin_id, url, transform_id, signing_config, headers,
               retry_policy, enabled, weight, delivery_mode,
               delivered_count, failed_count, created_at, updated_at)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)""",
            (
                destination_id,
                bin_id.strip(),
                url,
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
        """Return all destinations, optionally filtered by bin_id."""
        self._init_table()
        if bin_id is not None:
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
        """Update a destination; return the updated record or ``None``.

        Args:
            destination_id: The destination's id.
            url: Optional new URL.
            transform_id: Optional new transform_id.
            signing_config: Optional new signing config.
            headers: Optional new headers.
            retry_policy: Optional new retry policy.
            enabled: Optional enabled toggle.
            weight: Optional new weight (>= 1).
            delivery_mode: Optional new mode.

        Returns:
            The updated record, or ``None`` if not found.

        Raises:
            ValueError: If provided ``url`` is empty or ``weight`` < 1 or invalid mode.
        """
        existing = self.get(destination_id)
        if existing is None:
            return None

        if url is not None:
            url = validate_destination_url(url)
        if weight is not None and weight < 1:
            raise ValueError("weight must be >= 1")
        if delivery_mode is not None and delivery_mode not in (
            "broadcast",
            "round_robin",
            "weighted",
        ):
            raise ValueError("delivery_mode must be broadcast|round_robin|weighted")
        if signing_config is not None:
            signing_config = validate_signing_config(signing_config)
        if retry_policy is not None:
            retry_policy = validate_retry_policy(retry_policy)

        now = datetime.now(UTC).isoformat()

        def _json(value: Any, fallback: Any) -> str:
            return json.dumps(value if value is not None else fallback)

        self._conn.execute(
            """UPDATE destinations
               SET url = ?, transform_id = ?, signing_config = ?, headers = ?,
                   retry_policy = ?, enabled = ?, weight = ?, delivery_mode = ?,
                   updated_at = ?
               WHERE destination_id = ?""",
            (
                url if url is not None else existing["url"],
                transform_id if transform_id is not None else existing["transform_id"],
                _json(signing_config, existing["signing_config"]),
                _json(headers, existing["headers"]),
                _json(retry_policy, existing["retry_policy"]),
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

    def increment_delivered(self, destination_id: str) -> None:
        """Increment delivered_count for a destination."""
        self._conn.execute(
            "UPDATE destinations SET delivered_count = delivered_count + 1 WHERE destination_id = ?",
            (destination_id,),
        )
        self._conn.commit()

    def increment_failed(self, destination_id: str) -> None:
        """Increment failed_count for a destination."""
        self._conn.execute(
            "UPDATE destinations SET failed_count = failed_count + 1 WHERE destination_id = ?",
            (destination_id,),
        )
        self._conn.commit()

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a SQLite row to a dict with JSON fields decoded."""
        d = dict(row)
        for field in ("signing_config", "headers", "retry_policy"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        d["enabled"] = bool(d.get("enabled", 1))
        return d