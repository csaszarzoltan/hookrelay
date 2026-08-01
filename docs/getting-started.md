# Getting Started with hookrelay

## Overview

hookrelay consists of three components:

1. **Relay Server** — a FastAPI + WebSocket server that receives webhooks and tunnels them to connected clients
2. **Web Dashboard** — a browser-based UI for inspecting payloads, browsing history, replaying requests, and live monitoring (served by the relay server)
3. **CLI Client** — the `hookrelay` command that connects to the relay server and forwards webhooks to your local development server

## Architecture

```
External Webhook → Relay Server ──→ WebSocket Tunnel → hookrelay CLI → Localhost App
                                │
                                └──→ Web Dashboard (http://localhost:8000/dashboard/)
                                        ├── Live Feed (WebSocket)
                                        ├── History Browser (filter/search)
                                        ├── Payload Inspector
                                        └── Request Replay
```

## Prerequisites

- Python 3.11+
- A running webhook source (e.g., Stripe, GitHub, custom)

## Installation

```bash
pip install hookrelay
```

## Starting the Relay Server

The relay server includes both the WebSocket relay and the Web Dashboard:

```bash
hookrelay serve
```

Or with custom host and port:

```bash
hookrelay serve --host 127.0.0.1 --port 9000
```

The dashboard is available at **http://localhost:8000/dashboard/** (or your custom port).

### Options

| Option   | Default   | Description                     |
|----------|-----------|---------------------------------|
| `--host` | `0.0.0.0` | Host to bind the server to      |
| `--port` | `8000`    | Port to bind the server to      |
| `--reload` | —       | Enable auto-reload (development) |

### Health Check

Verify the server is running:

```bash
curl http://localhost:8000/health
```

Returns:

```json
{"status": "ok", "version": "0.2.0", "uptime": 123.45, "total_requests": 42}
```

## Forwarding Webhooks

```bash
# Connect to a channel and forward to your local app
hookrelay forward mychannel http://localhost:8080/webhook

# With a custom server
hookrelay forward mychannel http://localhost:8080/webhook --server https://relay.example.com
```

## Inspection & Debugging

### Dashboard (Browser)

Open **http://localhost:8000/dashboard/** in your browser:

- **Live Feed** — real-time webhook events via WebSocket, auto-updates the table
- **History Browser** — paginated, filterable list with search support
- **Payload Inspector** — detailed view of headers, query params, and body
- **Request Replay** — one-click replay from the dashboard UI

![Dashboard](screenshots/dashboard.png)
*Figure: Hookrelay Web Dashboard — Live Feed view*

### CLI

View incoming webhooks in real-time:

```bash
hookrelay listen mychannel
```

Browse history:

```bash
hookrelay history
hookrelay history --method POST --path /stripe
hookrelay history --id abc123
```

Replay a request:

```bash
hookrelay replay abc123
hookrelay replay abc123 --target http://localhost:9000/retry
```

## Configuration

hookrelay can be configured via environment variables:

- `HOOKRELAY_SERVER` — default relay server URL
- `HOOKRELAY_DB_DIR` — directory for the SQLite database

Or via a `.env` file in the working directory:

```
HOOKRELAY_SERVER=http://localhost:8000
HOOKRELAY_DB_DIR=~/.hookrelay
```

## SSRF Protection

By default, hookrelay blocks forwarding to:

- Private IP ranges (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- Localhost/loopback (127.0.0.1, ::1)
- Link-local addresses
- Ports below 1024

To allow private targets, use the `--allow-private` flag on `forward`.


## Protect remote access (v0.9.0+)

Hookrelay stays unauthenticated when `HOOKRELAY_API_TOKEN` is unset, which preserves the local single-user workflow. Before binding the server to an interface reachable by other machines, configure a long random token:

```bash
export HOOKRELAY_API_TOKEN="replace-with-a-long-random-secret"
hookrelay serve --host 0.0.0.0
```

Use the same environment variable when running a forwarding client. The client sends it as a Bearer token during the relay WebSocket handshake. Browser users sign in through `/dashboard/login`. Use a TLS-terminating reverse proxy for network deployments.
