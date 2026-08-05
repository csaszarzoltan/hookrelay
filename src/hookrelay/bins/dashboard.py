"""Dashboard 'Bins' view — live request feed for capture bins (v1.6.0).

Pre-development stub: raises ``NotImplementedError`` until implemented.

Contract notes for the developer:

- ``broadcast_bin_capture`` MUST reuse the process-wide live
  :class:`hookrelay.dashboard.connection_manager.ConnectionManager` returned
  by :func:`hookrelay.dashboard.get_live_manager` — the same manager that
  serves ``/dashboard/ws/live``. The broadcast payload must include the bin id
  and captured request id (plus method/path/timestamp) so the Bins view can
  render the live request feed.
- ``create_bins_dashboard_router()`` serves the Bins view page at
  ``GET /dashboard/bins`` (create a bin, copy its URL, live feed, click-to-
  forward buttons).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from hookrelay.dashboard.connection_manager import ConnectionManager


async def broadcast_bin_capture(manager: ConnectionManager, captured: Any) -> None:
    """Broadcast a newly captured request to connected live-feed clients."""
    raise NotImplementedError("broadcast_bin_capture is not implemented yet")


def create_bins_dashboard_router() -> APIRouter:
    """Create the router serving the Bins dashboard view."""
    raise NotImplementedError("create_bins_dashboard_router is not implemented yet")
