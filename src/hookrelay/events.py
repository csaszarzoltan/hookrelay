"""Versioned event envelopes for durable realtime reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

EVENT_SCHEMA_VERSION = 1


def create_event_envelope(
    event_type: str,
    data: dict[str, Any],
    *,
    correlation_id: str | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Create the canonical event envelope shared by APIs and WebSockets."""
    if not event_type or "." not in event_type:
        raise ValueError("event_type must be a non-empty namespaced value")
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": event_id or uuid4().hex,
        "event_type": event_type,
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "correlation_id": correlation_id,
        "data": data,
    }
