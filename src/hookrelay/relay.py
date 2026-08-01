"""WebSocket relay tunnel manager (server-side)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class RelayManager:
    """Manages WebSocket client connections per channel."""

    def __init__(self, stale_after_seconds: int = 90) -> None:
        self._channels: dict[str, list[Any]] = {}
        self._connections: dict[str, dict[str, Any]] = {}
        self._websocket_sessions: dict[int, str] = {}
        self._stale_after_seconds = stale_after_seconds

    def register_client(
        self,
        channel: str,
        websocket: Any,
        *,
        target_url: str | None = None,
        client_version: str | None = None,
        capabilities: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Register a client and return its stable connection session ID."""
        if channel not in self._channels:
            self._channels[channel] = []
        if websocket not in self._channels[channel]:
            self._channels[channel].append(websocket)
        session_id = session_id or uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._connections[session_id] = {
            "session_id": session_id,
            "channel": channel,
            "target_url": target_url,
            "client_version": client_version,
            "capabilities": sorted(set(capabilities or [])),
            "connected_at": now,
            "last_heartbeat": now,
        }
        self._websocket_sessions[id(websocket)] = session_id
        return session_id

    def unregister_client(self, channel: str, websocket: Any) -> None:
        """Remove a WebSocket client connection."""
        if channel in self._channels:
            self._channels[channel] = [
                ws for ws in self._channels[channel] if ws is not websocket
            ]
            if not self._channels[channel]:
                del self._channels[channel]
        session_id = self._websocket_sessions.pop(id(websocket), None)
        if session_id:
            self._connections.pop(session_id, None)

    def heartbeat(self, session_id: str) -> bool:
        """Refresh a connection heartbeat."""
        connection = self._connections.get(session_id)
        if connection is None:
            return False
        connection["last_heartbeat"] = datetime.now(UTC).isoformat()
        return True

    def list_connections(self, channel: str | None = None) -> list[dict[str, Any]]:
        """Return safe connection metadata with computed stale state."""
        now = datetime.now(UTC)
        result = []
        for connection in self._connections.values():
            if channel and connection["channel"] != channel:
                continue
            item = dict(connection)
            last = datetime.fromisoformat(item["last_heartbeat"])
            item["state"] = (
                "stale"
                if (now - last).total_seconds() > self._stale_after_seconds
                else "connected"
            )
            result.append(item)
        return sorted(result, key=lambda item: (item["channel"], item["connected_at"]))

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

    async def broadcast_async(self, channel: str, message: dict[str, Any]) -> int:
        """Send a message to ASGI or synchronous WebSocket clients."""
        clients = self._channels.get(channel, [])
        sent = 0
        alive = []
        for websocket in clients:
            try:
                if hasattr(websocket, "send_json"):
                    await websocket.send_json(message)
                else:
                    websocket.send(json.dumps(message))
                sent += 1
                alive.append(websocket)
            except Exception:
                pass
        if alive:
            self._channels[channel] = alive
        else:
            self._channels.pop(channel, None)
        return sent

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

_shared_relay_manager = RelayManager()


def get_shared_relay_manager() -> RelayManager:
    """Return the process-wide relay manager used by server and dashboard."""
    return _shared_relay_manager
