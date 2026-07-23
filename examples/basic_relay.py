"""Basic webhook relay example.

This example shows how to:
1. Start a local HTTP server (simulating your app)
2. Connect hookrelay to a relay server
3. Relay a webhook to the local server

Usage:
    # Terminal 1: Start the relay server
    uvicorn hookrelay_server.main:app --port 8000

    # Terminal 2: Start this local server
    python examples/basic_relay.py

    # Terminal 3: Forward webhooks
    hookrelay forward demo http://localhost:9000/webhook

    # Terminal 4: Send a test webhook
    curl -X POST http://localhost:8000/webhook/demo \
        -H "Content-Type: application/json" \
        -d '{"event": "test", "data": {"hello": "world"}}'
"""

from __future__ import annotations

import json
from http.server import HTTPServer, BaseHTTPRequestHandler


class WebhookHandler(BaseHTTPRequestHandler):
    """A simple HTTP handler that prints received webhooks."""

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        print(f"\n=== Webhook Received ===")
        print(f"Path: {self.path}")
        print(f"Headers: {dict(self.headers)}")
        print(f"Body: {json.loads(body) if body else '(empty)'}")
        print("========================\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format: str, *args: object) -> None:
        # Suppress default HTTP server logs for cleaner output
        pass


def main() -> None:
    port = 9000
    server = HTTPServer(("localhost", port), WebhookHandler)
    print(f"🚀 Local webhook receiver running on http://localhost:{port}/webhook")
    print(f"   Use: hookrelay forward demo http://localhost:{port}/webhook")
    print("   Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
