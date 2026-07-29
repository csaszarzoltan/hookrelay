"""WebSocket relay tunnel manager (server-side)."""

from __future__ import annotations

import json
import time
from typing import Any


class RelayManager:
    """Manages WebSocket client connections per channel."""

    def __init__(self) -> None:
        self._channels: dict[str, list[Any]] = {}

    def register_client(self, channel: str, websocket: Any) -> None:
        """Register a WebSocket client connection for a channel."""
        if channel not in self._channels:
            self._channels[channel] = []
        if websocket not in self._channels[channel]:
            self._channels[channel].append(websocket)

    def unregister_client(self, channel: str, websocket: Any) -> None:
        """Remove a WebSocket client connection."""
        if channel in self._channels:
            self._channels[channel] = [
                ws for ws in self._channels[channel] if ws is not websocket
            ]
            if not self._channels[channel]:
                del self._channels[channel]

    def broadcast(self, channel: str, message: dict[str, Any]) -> int:
        """Send a message to all connected clients on a channel.

        Returns the number of clients that received the message.
        """
        if channel not in self._channels:
            return 0

        payload = json.dumps(message)
        received_count = 0
        still_connected: list[Any] = []

        for ws in self._channels[channel]:
            try:
                ws.send(payload)
                received_count += 1
                still_connected.append(ws)
            except Exception:
                # Client disconnected, skip it
                pass

        self._channels[channel] = still_connected
        return received_count

    def get_connected_clients(self, channel: str) -> int:
        """Return the count of connected clients on a channel."""
        return len(self._channels.get(channel, []))

    def has_connected_clients(self, channel: str) -> bool:
        """Check if any clients are connected on a channel."""
        return self.get_connected_clients(channel) > 0

    def send_heartbeat(self, channel: str) -> None:
        """Send a heartbeat ping to all clients on a channel."""
        self.broadcast(channel, {"type": "heartbeat", "timestamp": time.time()})

    def forward_replay(self, channel: str, request_data: dict[str, Any]) -> bool:
        """Forward a replayed request to connected clients."""
        sent = self.broadcast(channel, {
            "type": "replay",
            "data": request_data,
            "timestamp": time.time(),
        })
        return sent > 0
