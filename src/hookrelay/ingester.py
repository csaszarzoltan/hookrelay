"""Webhook ingestion — receive, validate, store, and relay incoming requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def receive_webhook(
    channel: str,
    method: str,
    headers: dict[str, str],
    body: bytes,
    query_params: dict[str, str] | None,
    source_ip: str,
) -> dict[str, Any]:
    """Receive an incoming webhook, store it, and return metadata.

    Returns a dict with keys: request_id, method, path, headers,
    body, query_params, source_ip, received_at.
    """
    path = headers.get("X-Forwarded-Path", "/")
    now = datetime.now(tz=UTC)
    return {
        "request_id": uuid4().hex,
        "channel": channel,
        "method": method,
        "path": path,
        "headers": dict(headers),
        "body": body,
        "query_params": dict(query_params) if query_params else {},
        "source_ip": source_ip,
        "received_at": now.isoformat(),
    }


def extract_method(headers: dict[str, str], default: str = "POST") -> str:
    """Extract the HTTP method from a webhook request.

    Checks X-Forwarded-Method, X-HTTP-Method-Override, or falls back
    to default.
    """
    for header in ("X-Forwarded-Method", "X-HTTP-Method-Override", "X-Method"):
        value = headers.get(header)
        if value:
            return value.upper()
    return default.upper()


def extract_headers(raw_headers: dict[str, str]) -> dict[str, str]:
    """Normalize and extract relevant headers from raw request."""
    normalized: dict[str, str] = {}
    for key, value in raw_headers.items():
        # Normalize header names to Title-Case
        normalized_key = "-".join(
            part.capitalize() for part in key.replace("_", "-").split("-")
        )
        normalized[normalized_key] = value
    return normalized


def extract_body(raw_body: bytes, max_size: int = 10 * 1024 * 1024) -> bytes:
    """Extract and validate request body within size limits."""
    if len(raw_body) > max_size:
        raise ValueError(
            f"Payload size {len(raw_body)} exceeds maximum {max_size}"
        )
    return raw_body


def extract_query_params(
    raw_params: dict[str, str] | None,
) -> dict[str, str]:
    """Extract and normalize query parameters."""
    if raw_params is None:
        return {}
    return dict(raw_params)


def validate_payload_size(body: bytes, max_size: int = 10 * 1024 * 1024) -> bool:
    """Check payload is within configured size limit."""
    return len(body) <= max_size
