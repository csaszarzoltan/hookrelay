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
from hookrelay.bins.service import BinService
from hookrelay.ssrf import validate_target_url


class ForwardError(Exception):
    """Base error for bin request forwarding."""


class BinRequestNotFoundError(ForwardError):
    """The captured request does not exist in the bin."""


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

    Raises :class:`ValueError` when the SSRF guard blocks the target and
    :class:`BinRequestNotFoundError` when the request is unknown.
    """
    service = BinService(storage)
    captured = service.get_request(bin_id, request_id)
    if captured is None:
        raise BinRequestNotFoundError(
            f"Request {request_id} not found in bin {bin_id}"
        )

    is_valid, reason = validate_target_url(target_url)
    if not is_valid:
        raise ValueError(reason)

    method = captured.get("method", "POST")
    headers = dict(captured.get("headers") or {})
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
