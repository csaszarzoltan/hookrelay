"""Forward captured bin requests to arbitrary target URLs (v1.6.0).

Pre-development stub: raises ``NotImplementedError`` until implemented.

Contract notes for the developer:

- The target URL MUST be validated with ``hookrelay.ssrf.validate_target_url``
  before any request is sent (reuse the shared guard, do not inline DNS
  checks). On a blocked target raise ``ValueError`` with the guard's reason —
  this matches the existing convention in ``RetryQueue.enqueue`` and
  ``EndpointConfig.validate``.
- The forwarded request must reuse the captured method, headers and body.
- The result (HTTP status, latency in ms, response body) is returned as a
  :class:`hookrelay.bins.models.ForwardResult`.
"""

from __future__ import annotations

from typing import Any

from hookrelay.bins.models import ForwardResult


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
    result. Raises :class:`ValueError` when the SSRF guard blocks the target
    and :class:`BinRequestNotFoundError` when the request is unknown.
    """
    raise NotImplementedError("forward_captured_request is not implemented yet")
