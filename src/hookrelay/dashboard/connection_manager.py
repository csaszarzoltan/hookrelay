"""WebSocket connection manager for live monitoring dashboard."""

from __future__ import annotations

from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections for live dashboard updates."""

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected dashboard clients."""
        import json as json_mod
        payload = json_mod.dumps(message)
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                # If send fails, remove the stale connection
                try:
                    self._connections.remove(ws)
                except ValueError:
                    pass

    @property
    def active_connections(self) -> int:
        """Return the number of active WebSocket connections."""
        return len(self._connections)
