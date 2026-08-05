"""Data models for webhook capture bins (v1.6.0).

A *bin* is a persistent, webhook.site-style test endpoint
(``https://relay/bin/<bin_id>``). Every request sent to that URL is captured
and stored, regardless of whether any WebSocket client is connected.

These dataclasses are the fixed data contract for the feature — the service,
forwarding, REST API, CLI and dashboard all build on them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Bin:
    """A persistent webhook capture bin."""

    bin_id: str
    url: str
    created_at: str
    description: str | None = None
    request_count: int = 0


@dataclass
class CapturedRequest:
    """A single request captured by a bin."""

    request_id: str
    bin_id: str
    method: str
    headers: dict[str, str]
    body: bytes
    query_params: dict[str, str]
    source_ip: str
    received_at: str
    path: str = "/"


@dataclass
class ForwardResult:
    """Outcome of forwarding a captured request to a target URL."""

    request_id: str
    target_url: str
    status_code: int
    latency_ms: float
    response_body: str
    error: str | None = None
