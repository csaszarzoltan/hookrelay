"""WebSocket client and local HTTP forwarder."""

from __future__ import annotations

import json
import time
from typing import Any

import requests


class WebSocketClient:
    """Client-side WebSocket connection to the relay server."""

    def __init__(
        self, server_url: str, channel: str, target_url: str
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.channel = channel
        self.target_url = target_url.rstrip("/")
        self._ws = None  # Will hold a websocket.WebSocket or similar object

    def connect(self) -> None:
        """Establish the WebSocket connection."""
        import websocket as ws

        self._ws = ws.create_connection(
            f"{self.server_url}/ws/{self.channel}",
            timeout=30,
        )

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                # WebSocket not open or already closed - ignore
                pass
            self._ws = None

    def forward_to_local(
        self, request_data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Forward a webhook request to the local target URL.

        Returns the response dict with status, headers, body.
        """
        from urllib.parse import urlparse
        hostname = (urlparse(self.target_url).hostname or "").lower()
        if hostname.endswith(".invalid") or hostname == "invalid":
            raise ValueError("Reserved .invalid target cannot be forwarded")

        method = request_data.get("method", "POST").upper()
        headers = request_data.get("headers", {})
        body = request_data.get("body")

        # Reconstruct path + query
        path = request_data.get("path", "/")
        qp = request_data.get("query_params", {})
        if qp:
            import urllib.parse
            qs = urllib.parse.urlencode(qp)
            path = f"{path}?{qs}"

        url = self.target_url.rstrip("/") + path

        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=False,
        )

        return {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.content,
        }

    def is_connected(self) -> bool:
        """Check if the WebSocket is currently connected."""
        if self._ws is None:
            return False
        try:
            self._ws.ping()
            return True
        except Exception:
            return False


def connect_and_forward(
    server_url: str,
    channel: str,
    target_url: str,
    timeout: float = 30.0,
    on_request: callable | None = None,
) -> None:
    """Convenience: connect to server and forward requests to local target.

    Runs until disconnected. Calls on_request(request_data) for each
    received webhook before forwarding.
    """
    import websocket as ws

    ws_url = f"{server_url.rstrip('/')}/ws/{channel}"
    ws_conn = ws.create_connection(ws_url, timeout=timeout)

    try:
        while True:
            raw = ws_conn.recv()
            if not raw:
                continue
            data = json.loads(raw)

            message_type = data.get("type")
            if message_type in ("heartbeat", "pong"):
                continue
            if message_type not in (None, "webhook", "replay"):
                continue

            request_data = data.get("data", data)
            if on_request:
                on_request(request_data)

            client = WebSocketClient(server_url, channel, target_url)
            client._ws = ws_conn  # reuse connection
            started = time.perf_counter()
            report = {
                "request_id": request_data.get("request_id"),
                "target_url": target_url,
            }
            try:
                response = client.forward_to_local(request_data, timeout=timeout)
                status_code = response.get("status")
                report.update({
                    "status": "delivered" if status_code is not None and status_code < 400 else "target_error",
                    "response_status": status_code,
                })
            except Exception as exc:
                report.update({
                    "status": "transport_error",
                    "response_status": None,
                    "error": str(exc),
                })
            report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            ws_conn.send(json.dumps({"type": "delivery_result", "data": report}))
    finally:
        try:
            ws_conn.close()
        except Exception:
            pass
