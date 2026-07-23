# Getting Started with hookrelay

## Overview

hookrelay consists of two components:

1. **Relay Server** — a FastAPI + WebSocket server that receives webhooks and tunnels them to connected clients
2. **CLI Client** — the `hookrelay` command that connects to the relay server and forwards webhooks to your local development server

## Architecture

```
External Webhook → Relay Server → WebSocket Tunnel → hookrelay CLI → Localhost App
```

## Prerequisites

- Python 3.11+
- A running webhook source (e.g., Stripe, GitHub, custom)

## Installation

```bash
pip install hookrelay
```

## Starting the Relay Server

The relay server is included as a separate component:

```bash
uvicorn hookrelay_server.main:app --host 0.0.0.0 --port 8000
```

Or with the provided launcher script:

```bash
# Run the relay server in the background
hookrelay-server &
```

## Forwarding Webhooks

```bash
# Connect to a channel and forward to your local app
hookrelay forward mychannel http://localhost:8080/webhook

# With a custom server
hookrelay forward mychannel http://localhost:8080/webhook --server https://relay.example.com
```

## Inspection & Debugging

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
- `HOOKREAY_DB_DIR` — directory for the SQLite database

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
