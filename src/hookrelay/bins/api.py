"""FastAPI wiring for webhook capture bins (v1.6.0).

Exposes the public capture endpoint ``/bin/{bin_id}`` plus the bin management
REST surface:

  * ``/bin/{bin_id}``                            capture (GET/POST/PUT/PATCH/DELETE)
  * ``POST   /api/bins``                         create a bin
  * ``GET    /api/bins``                         list bins
  * ``DELETE /api/bins/{bin_id}``                delete a bin
  * ``GET    /api/bins/{bin_id}/requests``       paginated listing
  * ``GET    /api/bins/{bin_id}/requests/{request_id}``  full payload view
  * ``POST   /api/bins/{bin_id}/requests/{request_id}/forward``  one-click forward

The capture endpoint persists every request through
:class:`hookrelay.bins.service.BinService` even when no WebSocket client is
connected (AC1), broadcasts the capture to the live dashboard feed, and
returns the captured ``request_id``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from hookrelay import _storage
from hookrelay.bins.dashboard import broadcast_bin_capture
from hookrelay.bins.forward import (
    BinRequestNotFoundError,
    forward_captured_request,
)
from hookrelay.bins.service import BinService
from hookrelay.dashboard import get_live_manager

#: HTTP methods accepted by the public capture endpoint.
_CAPTURE_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def build_public_bin_url(base_url: str, bin_id: str) -> str:
    """Build the public capture URL for a bin.

    E.g. ``build_public_bin_url("http://localhost:8000", "abc")`` →
    ``http://localhost:8000/bin/abc``.
    """
    return f"{base_url.rstrip('/')}/bin/{bin_id}"


class _ForwardTarget(BaseModel):
    """Request body for the one-click forward endpoint."""

    target_url: str


def _get_bin_service() -> BinService:
    """Return a BinService bound to the process-wide storage."""
    return BinService(_get_or_create_storage())


def _get_or_create_storage():
    """Return the shared storage, creating the default one if needed."""
    store = _storage.get()
    if store is None:
        from hookrelay.server import _get_or_create_storage as server_storage

        store = server_storage()
    return store


def _header_value(headers: Any, name: str) -> str | None:
    """Case-insensitive header lookup (FastAPI normalizes to lowercase)."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


def _bin_payload(bin_obj: Any, base_url: str) -> dict[str, Any]:
    """Serialize a :class:`Bin` with a URL derived from the request host."""
    return {
        "bin_id": bin_obj.bin_id,
        "url": build_public_bin_url(base_url, bin_obj.bin_id),
        "created_at": bin_obj.created_at,
        "description": bin_obj.description,
        "request_count": bin_obj.request_count,
    }


def create_bins_router() -> APIRouter:
    """Create the FastAPI router exposing the bins feature."""
    router = APIRouter()

    @router.api_route("/bin/{bin_id}", methods=_CAPTURE_METHODS)
    async def capture_bin_request(bin_id: str, request: Request):
        """Capture any HTTP request sent to the bin's public URL."""
        service = _get_bin_service()
        if service.get_bin(bin_id) is None:
            raise HTTPException(status_code=404, detail="Bin not found")

        method = request.method
        headers = dict(request.headers)
        body = await request.body()
        query_params = dict(request.query_params)
        source_ip = (
            _header_value(headers, "x-real-ip")
            or _header_value(headers, "x-forwarded-for")
            or (request.client.host if request.client else "unknown")
        )

        captured = service.capture(
            bin_id=bin_id,
            method=method,
            headers=headers,
            body=body,
            query_params=query_params,
            source_ip=source_ip,
        )
        try:
            await broadcast_bin_capture(get_live_manager(), captured)
        except Exception:
            # Live feed must never block or fail the capture itself.
            pass
        return JSONResponse(
            status_code=201,
            content={
                "request_id": captured.request_id,
                "bin_id": bin_id,
                "method": method,
                "path": captured.path,
            },
        )

    @router.post("/api/bins", status_code=201)
    async def create_bin(request: Request, body: dict[str, Any] | None = None):
        """Create a capture bin and return its public URL."""
        description = (body or {}).get("description")
        created = _get_bin_service().create_bin(
            description=description if isinstance(description, str) else None
        )
        return _bin_payload(created, str(request.base_url))

    @router.get("/api/bins")
    async def list_bins(request: Request):
        """List all capture bins, newest first."""
        base_url = str(request.base_url)
        return [
            _bin_payload(bin_obj, base_url)
            for bin_obj in _get_bin_service().list_bins()
        ]

    @router.delete("/api/bins/{bin_id}", status_code=204)
    async def delete_bin(bin_id: str):
        """Delete a bin and its captured requests."""
        if not _get_bin_service().delete_bin(bin_id):
            raise HTTPException(status_code=404, detail="Bin not found")
        return JSONResponse(status_code=204, content=None)

    @router.get("/api/bins/{bin_id}/requests")
    async def list_bin_requests(
        bin_id: str, limit: int = 20, offset: int = 0
    ):
        """List captured requests for a bin, newest first, with pagination."""
        service = _get_bin_service()
        if service.get_bin(bin_id) is None:
            raise HTTPException(status_code=404, detail="Bin not found")
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)
        return service.list_requests(bin_id, limit=limit, offset=offset)

    @router.get("/api/bins/{bin_id}/requests/{request_id}")
    async def get_bin_request(bin_id: str, request_id: str):
        """Return the full captured payload of one request."""
        service = _get_bin_service()
        if service.get_bin(bin_id) is None:
            raise HTTPException(status_code=404, detail="Bin not found")
        detail = service.get_request(bin_id, request_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Request not found")
        return detail

    @router.post("/api/bins/{bin_id}/requests/{request_id}/forward")
    async def forward_bin_request(bin_id: str, request_id: str, body: _ForwardTarget):
        """Forward one captured request to an arbitrary, SSRF-guarded URL."""
        service = _get_bin_service()
        if service.get_bin(bin_id) is None:
            raise HTTPException(status_code=404, detail="Bin not found")
        try:
            result = forward_captured_request(
                bin_id=bin_id,
                request_id=request_id,
                target_url=body.target_url,
                storage=_get_or_create_storage(),
            )
        except BinRequestNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return result

    return router
