"""Webhook capture bins (v1.6.0).

Persistent, webhook.site-style test endpoints with one-click forward and
payload inspection. The package is fully implemented:

* :mod:`hookrelay.bins.models` — dataclass data contract
  (``Bin``, ``CapturedRequest``, ``ForwardResult``)
* :mod:`hookrelay.bins.service` — ``BinService`` persistence/management
  over the shared :class:`hookrelay.storage.Storage`
* :mod:`hookrelay.bins.forward` — SSRF-guarded replay of captured requests
  (byte-exact bodies, hop-by-hop headers recomputed)
* :mod:`hookrelay.bins.api` — FastAPI REST wiring (capture + management
  endpoints)
* :mod:`hookrelay.bins.dashboard` — live-feed broadcast + Bins dashboard
  view with click-to-forward
* :mod:`hookrelay.bins.cli` — the ``hookrelay bin`` command group
* :mod:`hookrelay.bins.destination_store` — ``DestinationStore`` persistence
  for per-bin delivery destinations with transformation, signing, retry
  policy, and delivery mode
"""

from __future__ import annotations

from hookrelay.bins.destination_store import DestinationStore
from hookrelay.bins.forward import (
    BinRequestNotFoundError,
    ForwardError,
    forward_captured_request,
)
from hookrelay.bins.models import Bin, CapturedRequest, ForwardResult
from hookrelay.bins.service import BinNotFoundError, BinService

__all__ = [
    "Bin",
    "BinNotFoundError",
    "BinRequestNotFoundError",
    "BinService",
    "CapturedRequest",
    "DestinationStore",
    "ForwardError",
    "ForwardResult",
    "forward_captured_request",
]
