"""History browser — retrieve, list, and search webhook requests."""

from __future__ import annotations

import json
import os
from typing import Any


def get_history(
    channel: str | None = None,
    limit: int = 20,
    offset: int = 0,
    method: str | None = None,
    path: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """List stored webhook requests with optional filters.

    Returns newest first. Each item contains at minimum:
    request_id, method, path, received_at, source_ip.
    """
    # This function requires a global storage reference.
    # If no storage is configured, return empty list.
    from hookrelay import _storage

    storage = _storage.get()
    if storage is None:
        return []

    return storage.list_requests(
        channel=channel,
        limit=limit,
        offset=offset,
        method=method,
        path=path,
    )


def get_request_detail(request_id: str) -> dict[str, Any] | None:
    """Get full details for a single request by ID.

    Returns None if not found.
    """
    from hookrelay import _storage

    storage = _storage.get()
    if storage is None:
        return None
    return storage.get_request(request_id)


def search_history(
    query: str,
    channel: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search stored requests by text query across headers, body, path.

    Returns matching requests ranked by relevance.
    """
    from hookrelay import _storage

    storage = _storage.get()
    if storage is None:
        return []
    return storage.search_requests(query=query, channel=channel, limit=limit)


def export_history(
    channel: str | None = None,
    format: str = "json",
    output: str | None = None,
) -> str:
    """Export history to JSON (or other formats).

    Returns the output path or serialized string.
    """
    from hookrelay import _storage

    storage = _storage.get()
    if storage is None:
        return ""

    data = storage.list_requests(channel=channel, limit=10000) if storage else []

    if format == "json":
        # Convert bytes to hex for JSON serialization
        serializable = []
        for item in data:
            item_copy = dict(item)
            if isinstance(item_copy.get("body"), bytes):
                item_copy["body"] = item_copy["body"].hex()
            serializable.append(item_copy)

        content = json.dumps(serializable, indent=2, default=str)

        if output:
            os.makedirs(os.path.dirname(os.path.abspath(output)) or ".", exist_ok=True)
            with open(output, "w") as f:
                f.write(content)
            return output
        return content

    # Fallback: serialize to string
    return json.dumps(data, default=str)
