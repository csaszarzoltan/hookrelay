"""BinService — persistence and management for webhook capture bins (v1.6.0).

A *bin* is a persistent, webhook.site-style test endpoint. Requests sent to
``/bin/{bin_id}`` are captured and persisted through the shared
:class:`hookrelay.storage.Storage` (the bin id doubles as the webhooks
``channel``, so captured requests automatically inherit the existing
persistence, pagination and audit machinery) — they are stored even when no
WebSocket client is connected. Live-feed broadcasting is a separate concern
handled by :mod:`hookrelay.bins.dashboard`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.bins.models import Bin, CapturedRequest
from hookrelay.storage import Storage

#: Base URL used for service-level URLs (REST layer re-derives it from the
#: incoming request's ``base_url`` so the returned URL is actually reachable).
DEFAULT_BIN_BASE_URL = "http://localhost:8000"


class BinNotFoundError(Exception):
    """Raised when a bin does not exist."""


class BinService:
    """Manage capture bins and their captured requests."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Bin metadata
    # ------------------------------------------------------------------

    def create_bin(self, description: str | None = None) -> Bin:
        """Create a bin and return it with a unique public capture URL."""
        from hookrelay.bins.api import build_public_bin_url

        bin_id = uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        self._storage.create_bin(bin_id, description, created_at)
        return Bin(
            bin_id=bin_id,
            url=build_public_bin_url(DEFAULT_BIN_BASE_URL, bin_id),
            created_at=created_at,
            description=description,
            request_count=0,
        )

    def get_bin(self, bin_id: str) -> Bin | None:
        """Return the bin or ``None`` if it does not exist."""
        row = self._storage.get_bin(bin_id)
        if row is None:
            return None
        return self._bin_from_row(row)

    def list_bins(self) -> list[Bin]:
        """Return all bins, newest first."""
        return [self._bin_from_row(row) for row in self._storage.list_bins()]

    def delete_bin(self, bin_id: str) -> bool:
        """Delete a bin and its captured requests; return True if deleted."""
        return self._storage.delete_bin(bin_id)

    def _bin_from_row(self, row: dict[str, Any]) -> Bin:
        """Build a :class:`Bin` from a storage metadata row."""
        from hookrelay.bins.api import build_public_bin_url

        return Bin(
            bin_id=row["bin_id"],
            url=build_public_bin_url(DEFAULT_BIN_BASE_URL, row["bin_id"]),
            created_at=row["created_at"],
            description=row.get("description"),
            request_count=self._storage.count_requests(channel=row["bin_id"]),
        )

    # ------------------------------------------------------------------
    # Captured requests
    # ------------------------------------------------------------------

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
        if self.get_bin(bin_id) is None:
            raise BinNotFoundError(f"Bin {bin_id} not found")
        request_id = uuid4().hex
        received_at = datetime.now(UTC).isoformat()
        path = headers.get("X-Forwarded-Path", "/")
        self._storage.store_request(
            {
                "request_id": request_id,
                "channel": bin_id,
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": body,
                "query_params": dict(query_params) if query_params else {},
                "source_ip": source_ip,
                "received_at": received_at,
            }
        )
        return CapturedRequest(
            request_id=request_id,
            bin_id=bin_id,
            method=method,
            headers=dict(headers),
            body=body,
            query_params=dict(query_params) if query_params else {},
            source_ip=source_ip,
            received_at=received_at,
            path=path,
        )

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
        rows = self._storage.list_requests(
            channel=bin_id, limit=limit, offset=offset
        )
        return {
            "items": [self._decode_body(row) for row in rows],
            "total": self._storage.count_requests(channel=bin_id),
        }

    def get_request(self, bin_id: str, request_id: str) -> dict[str, Any] | None:
        """Return the full payload of one captured request, or ``None``."""
        row = self._storage.get_request(request_id)
        if row is None or row.get("channel") != bin_id:
            return None
        return self._decode_body(row)

    @staticmethod
    def _decode_body(row: dict[str, Any]) -> dict[str, Any]:
        """Decode the BLOB body for JSON serialization (never raises)."""
        item = dict(row)
        if isinstance(item.get("body"), bytes):
            item["body"] = item["body"].decode("utf-8", errors="replace")
        return item
