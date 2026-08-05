"""FastAPI wiring for webhook capture bins (v1.6.0).

Pre-development stub: raises ``NotImplementedError`` until implemented.

Contract notes for the developer:

- ``create_bins_router()`` returns an :class:`fastapi.APIRouter` that is
  included in :func:`hookrelay.server.create_app`. Expected routes:

  * ``/bin/{bin_id}`` — GET/POST/PUT/PATCH/DELETE capture endpoint (public)
  * ``POST   /api/bins``                                  create a bin
  * ``GET    /api/bins``                                  list bins
  * ``DELETE /api/bins/{bin_id}``                         delete a bin
  * ``GET    /api/bins/{bin_id}/requests``                paginated listing
  * ``GET    /api/bins/{bin_id}/requests/{request_id}``   full payload view
  * ``POST   /api/bins/{bin_id}/requests/{request_id}/forward``  one-click forward

- The capture endpoint must persist the request even with no WebSocket client
  connected (AC1), return the captured ``request_id``, and be reachable at the
  public URL returned by :func:`build_public_bin_url`.
"""

from __future__ import annotations

from fastapi import APIRouter


def build_public_bin_url(base_url: str, bin_id: str) -> str:
    """Build the public capture URL for a bin.

    E.g. ``build_public_bin_url("http://localhost:8000", "abc")`` →
    ``http://localhost:8000/bin/abc``.
    """
    raise NotImplementedError("build_public_bin_url is not implemented yet")


def create_bins_router() -> APIRouter:
    """Create the FastAPI router exposing the bins feature."""
    raise NotImplementedError("create_bins_router is not implemented yet")
