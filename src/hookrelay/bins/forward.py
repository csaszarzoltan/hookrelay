"""Forward captured bin requests to arbitrary target URLs (v1.6.0).

Every target URL passes through :func:`hookrelay.ssrf.validate_target_url`
(protocol allowlist, private-IP block, system-port block, DNS rebinding
re-check) before any request is sent. A blocked target raises
:class:`ValueError` with the guard's reason — the same convention used by
``RetryQueue.enqueue`` and ``EndpointConfig.validate``.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from hookrelay.bins.models import ForwardResult
from hookrelay.ssrf import validate_target_url


class ForwardError(Exception):
    """Base error for bin request forwarding."""


class BinRequestNotFoundError(ForwardError):
    """The captured request does not exist in the bin."""


#: Headers that are never replayed verbatim when forwarding a captured
#: request. They are either derived from the request line/body (Host,
#: Content-Length) or hop-by-hop (Connection, Transfer-Encoding) — replaying
#: them sends a stale ``Host`` to the target (broken virtual-host routing), a
#: ``Content-Length`` that no longer matches the re-encoded body, and
#: connection-level framing from the original sender. ``requests`` recomputes
#: all of them from the target URL and the actual body.
_STRIPPED_FORWARD_HEADERS = frozenset(
    {"host", "content-length", "connection", "transfer-encoding"}
)


def forward_captured_request(
    bin_id: str,
    request_id: str,
    target_url: str,
    storage: Any,
    timeout: float = 30.0,
) -> ForwardResult:
    """Forward one captured request to ``target_url``.

    Re-sends the captured method/headers/body to the target, records
    ``status_code`` / ``latency_ms`` / ``response_body`` and returns the
    result. The outcome is also persisted as a delivery attempt so the
    dashboard/API can display forwarding history.

    The body is forwarded as the exact stored bytes — the raw storage row is
    read directly because :meth:`BinService.get_request` decodes the BLOB as
    UTF-8 with ``errors="replace"``, which would corrupt non-UTF-8 payloads
    before they are re-encoded for the target. ``Host``, ``Content-Length``,
    ``Connection`` and ``Transfer-Encoding`` are stripped from the replayed
    headers so ``requests`` recomputes them.

    Raises :class:`ValueError` when the SSRF guard blocks the target and
    :class:`BinRequestNotFoundError` when the request is unknown.
    """
    # Read the RAW stored row: `service.get_request` decodes the body to a
    # lossy UTF-8 string (errors="replace"), so forwarding must bypass it to
    # preserve binary payloads byte-for-byte.
    captured = storage.get_request(request_id)
    if captured is None or captured.get("channel") != bin_id:
        raise BinRequestNotFoundError(
            f"Request {request_id} not found in bin {bin_id}"
        )

    is_valid, reason = validate_target_url(target_url)
    if not is_valid:
        raise ValueError(reason)

    method = captured.get("method", "POST")
    headers = {
        key: value
        for key, value in (captured.get("headers") or {}).items()
        if key.lower() not in _STRIPPED_FORWARD_HEADERS
    }
    body = captured.get("body")
    if isinstance(body, str):
        body = body.encode("utf-8")

    started = time.perf_counter()
    try:
        response = requests.request(
            method, target_url, headers=headers, data=body, timeout=timeout
        )
    except requests.RequestException as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        storage.store_delivery_attempt(
            request_id=request_id,
            channel=bin_id,
            status="transport_error",
            target_url=target_url,
            error=str(exc),
            duration_ms=latency_ms,
        )
        return ForwardResult(
            request_id=request_id,
            target_url=target_url,
            status_code=0,
            latency_ms=latency_ms,
            response_body="",
            error=str(exc),
        )

    latency_ms = (time.perf_counter() - started) * 1000.0
    storage.store_delivery_attempt(
        request_id=request_id,
        channel=bin_id,
        status="delivered",
        target_url=target_url,
        response_status=response.status_code,
        duration_ms=latency_ms,
        response_body=response.text,
    )
    return ForwardResult(
        request_id=request_id,
        target_url=target_url,
        status_code=response.status_code,
        latency_ms=latency_ms,
        response_body=response.text,
    )
