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
    body, query_params, source_ip, received_at, validation.
    """
    path = headers.get("X-Forwarded-Path", "/")
    now = datetime.now(tz=UTC)
    result = {
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

    # Auto-validate the payload (never blocks)
    try:
        validation_info = auto_validate(
            channel=channel,
            body=body,
            headers=dict(headers),
        )
        result["validation"] = validation_info
    except Exception:
        result["validation"] = {"validated": False, "results": [], "skipped": True}

    return result


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


def auto_validate(
    channel: str,
    body: bytes,
    headers: dict[str, str],
) -> dict:
    """Auto-validate an incoming webhook payload against matching schemas.

    Args:
        channel: The webhook channel.
        body: Raw request body bytes.
        headers: Request headers.

    Returns:
        Dict with 'validated' flag and 'results' list.
    """
    result: dict = {"validated": False, "results": [], "skipped": False}

    # Only validate JSON payloads
    content_type = headers.get("content-type", headers.get("Content-Type", "")).lower()
    if "json" not in content_type:
        # Try to parse anyway, skip if not JSON
        pass

    # Try to parse body as JSON
    import json as json_mod
    try:
        payload = json_mod.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            result["skipped"] = True
            return result
    except (json_mod.JSONDecodeError, UnicodeDecodeError, ValueError):
        result["skipped"] = True
        return result

    # Look up matching schemas for this channel
    try:
        from hookrelay import _storage
        from hookrelay.schemas import SchemaStore

        store = _storage.get()
        if store is None:
            # No store available, can't validate
            import os
            import tempfile

            from hookrelay.storage import Storage
            db_dir = os.path.join(tempfile.gettempdir(), "hookrelay")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "webhooks.db")
            store = Storage(db_path)
            _storage.set(store)

        schema_store = SchemaStore(store)
        schemas = schema_store.list_schemas(channel=channel, enabled_only=True)
    except Exception:
        result["validated"] = False
        return result

    if not schemas:
        result["validated"] = False
        result["no_schema"] = True
        return result

    # Validate against each matching schema
    from hookrelay.validation import validate_payload

    all_results = []
    has_invalid = False
    for schema_record in schemas:
        try:
            vr = validate_payload(
                payload,
                schema_record["schema_definition"],
                draft=schema_record["draft_version"],
            )
            vr_dict = vr.to_dict()
            vr_dict["schema_id"] = schema_record["schema_id"]
            vr_dict["schema_name"] = schema_record["name"]
            all_results.append(vr_dict)
            if not vr.valid:
                has_invalid = True
        except Exception:
            # Never block on validation errors
            all_results.append({
                "schema_id": schema_record["schema_id"],
                "schema_name": schema_record["name"],
                "valid": False,
                "errors": [{"message": "Validation error", "severity": "error"}],
                "warnings": [],
                "infos": [],
            })

    result["validated"] = True
    result["results"] = all_results
    result["valid"] = not has_invalid
    return result
