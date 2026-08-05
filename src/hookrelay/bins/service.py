"""BinService — persistence and management for webhook capture bins (v1.6.0).

Pre-development stub: every public member raises ``NotImplementedError`` until
the developer implements the feature. Interface tests pass immediately against
these signatures; behavioral tests fail (RED) until the implementation lands.

Contract notes for the developer:

- Persistence is delegated to the shared :class:`hookrelay.storage.Storage`
  (the webhooks table already exists; add bin metadata + bin-scoped request
  lookups, e.g. ``bins`` / ``bin_requests`` tables or a ``bin_id`` column).
- ``capture()`` must persist the request **without** requiring a WebSocket
  client — live feed broadcasting happens separately in
  :mod:`hookrelay.bins.dashboard`.
- ``list_requests()`` returns ``{"items": [...], "total": N}`` so the REST
  layer can serve pagination metadata directly.
"""

from __future__ import annotations

from typing import Any

from hookrelay.bins.models import Bin, CapturedRequest
from hookrelay.storage import Storage


class BinNotFoundError(Exception):
    """Raised when a bin does not exist."""


class BinService:
    """Manage capture bins and their captured requests."""

    def __init__(self, storage: Storage) -> None:
        raise NotImplementedError("BinService is not implemented yet")

    def create_bin(self, description: str | None = None) -> Bin:
        """Create a bin and return it with a unique public capture URL."""
        raise NotImplementedError("BinService.create_bin is not implemented yet")

    def get_bin(self, bin_id: str) -> Bin | None:
        """Return the bin or ``None`` if it does not exist."""
        raise NotImplementedError("BinService.get_bin is not implemented yet")

    def list_bins(self) -> list[Bin]:
        """Return all bins, newest first."""
        raise NotImplementedError("BinService.list_bins is not implemented yet")

    def delete_bin(self, bin_id: str) -> bool:
        """Delete a bin and its captured requests; return True if deleted."""
        raise NotImplementedError("BinService.delete_bin is not implemented yet")

    def capture(
        self,
        bin_id: str,
        method: str,
        headers: dict[str, str],
        body: bytes,
        query_params: dict[str, str] | None,
        source_ip: str,
    ) -> CapturedRequest:
        """Capture and persist a request sent to the bin.

        Persists even when no WebSocket client is connected. Raises
        :class:`BinNotFoundError` for an unknown bin.
        """
        raise NotImplementedError("BinService.capture is not implemented yet")

    def list_requests(
        self,
        bin_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List captured requests for a bin, newest first.

        Returns ``{"items": [request_dict, ...], "total": N}`` where each item
        carries method/headers/body/query_params/source_ip/received_at.
        """
        raise NotImplementedError("BinService.list_requests is not implemented yet")

    def get_request(self, bin_id: str, request_id: str) -> dict[str, Any] | None:
        """Return the full payload of one captured request, or ``None``."""
        raise NotImplementedError("BinService.get_request is not implemented yet")
