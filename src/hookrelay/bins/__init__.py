"""Webhook capture bins (v1.6.0).

Persistent, webhook.site-style test endpoints with one-click forward and
payload inspection. Pre-development package: models are real dataclasses
(data contract); service/forward/api/dashboard/cli are stubs raising
``NotImplementedError`` until the developer implements the feature.
"""

from __future__ import annotations

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
    "ForwardError",
    "ForwardResult",
    "forward_captured_request",
]
