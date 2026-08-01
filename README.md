# hookrelay 🪝

**Webhook relay tool for local development.** CLI-first ngrok alternative — forward webhooks to localhost, inspect payloads in real-time, replay historical requests, and filter by source. Now with a **Web Dashboard** for visual debugging and resilient daily workflows.

[![GitHub Release](https://img.shields.io/github/v/release/csaszarzoltan/hookrelay?logo=github)](https://github.com/csaszarzoltan/hookrelay/releases)
[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-244%20passing-brightgreen)](https://github.com/csaszarzoltan/hookrelay/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dashboard](https://img.shields.io/badge/feature-dashboard-blueviolet)](#web-dashboard)

---

## Features

### CLI
- **Webhook relay** — forward webhooks from a public endpoint to `localhost` via a WebSocket tunnel
- **Real-time inspection** — view method, headers, body, and query params as they arrive
- **Request replay** — replay any received webhook with one command: `hookrelay replay <id>`
- **History browser** — search and browse webhooks with FTS5 full-text search
- **Conditional forwarding** — filter by source IP, HTTP method, path, headers, or status code
- **SSRF protection** — IP range blocking (IPv4/IPv6), DNS anti-rebinding, protocol whitelist
- **CLI-first** — Typer-powered, no GUI required, pipe-friendly
- **Lightweight** — Python 3.11+, only 3 runtime dependencies (typer, websocket-client, requests)

### Web Dashboard (v0.2.0+)
- **Live Feed** — real-time webhook events pushed via WebSocket, auto-updating table
- **Payload Inspector** — rich HTML view of request metadata, headers, query params, and body
- **History Browser** — paginated, filterable table with channel/method/path filters and FTS5 search
- **Request Replay** — one-click replay from the dashboard with inline result display
- **Live Monitoring WebSocket** — `/dashboard/ws/live` for programmatic real-time event streaming

## Installation

```bash
pip install hookrelay
```

Or from source:

```bash
git clone https://github.com/csaszarzoltan/hookrelay.git
cd hookrelay
pip install -e .
```

## Quick Start

### 1. Start the server with Dashboard

```bash
hookrelay serve
# Dashboard:  http://localhost:8000/dashboard/
# Health:     http://localhost:8000/health
```

### 2. Forward webhooks to localhost

```bash
hookrelay forward mychannel http://localhost:3000/webhook
```

### 3. Send a webhook to the relay

```bash
curl -X POST http://localhost:8000/webhook/mychannel \
  -H "Content-Type: application/json" \
  -d '{"event": "order.created", "data": {"id": 42}}'
```

The webhook is automatically forwarded to `http://localhost:3000/webhook` **and** appears in the dashboard live feed.

### 4. Open the Dashboard

Navigate to **http://localhost:8000/dashboard/** in your browser:

- Watch webhooks appear in real-time on the **Live Feed** page
- Browse and filter past requests in **History Browser**
- Click **Inspect** to view full request details
- Click **Replay** to re-send a request with one click

### 5. View history (CLI)

```bash
hookrelay history
```

### 6. Replay a request (CLI)

```bash
hookrelay replay <request-id>
```

## Screenshots

| Dashboard Live Feed | Payload Inspector |
|---|---|
| ![Dashboard Live Feed](docs/screenshots/dashboard.png) | ![Inspector](docs/screenshots/inspector.png) |

| History Browser | Request Replay |
|---|---|
| ![History Browser](docs/screenshots/history.png) | ![Replay](docs/screenshots/replay.png) |

## CLI Commands

| Command | Description |
|---|---|
| `hookrelay serve` | Start the FastAPI server with Web Dashboard UI |
| `hookrelay forward <channel> <target>` | Forward webhooks from a channel to a local URL |
| `hookrelay listen <channel>` | Listen for incoming webhooks on a channel |
| `hookrelay history` | Browse recent webhook requests |
| `hookrelay history --id <id>` | View full request details |
| `hookrelay replay <id>` | Replay a stored webhook request |
| `hookrelay status` | Check relay server health |

### Options

- `--server` / `-s` — Relay server URL (default: `http://localhost:8000`)
- `--channel` / `-c` — Filter history by channel
- `--method` / `-m` — Filter history by HTTP method
- `--path` / `-p` — Filter history by path pattern
- `--limit` / `-n` — Max results (default: 20)

## Project Structure

```
hookrelay/
├── src/
│   └── hookrelay/
│       ├── cli.py                # Typer CLI commands (incl. `serve`)
│       ├── client.py             # WebSocket client & local forwarder
│       ├── filters.py            # Conditional forwarding filters
│       ├── history.py            # History browser & search
│       ├── ingester.py           # Webhook ingestion & validation
│       ├── models.py             # Data models
│       ├── relay.py              # WebSocket relay tunnel manager
│       ├── replay.py             # Request replay orchestration
│       ├── server.py             # FastAPI server (dashboard + relay + APIs)
│       ├── ssrf.py               # SSRF protection
│       ├── storage.py            # SQLite storage with FTS5
│       └── dashboard/            # Web Dashboard module
│           ├── __init__.py       # Dashboard router (all UI routes)
│           ├── connection_manager.py  # WebSocket connection manager
│           ├── templates/        # Jinja2 templates
│           │   ├── base.html     # Base layout with sidebar
│           │   ├── index.html    # Live Feed page
│           │   ├── history.html  # History Browser page
│           │   ├── inspect.html  # Payload Inspector page
│           │   └── replay.html   # Request Replay page
│           └── static/           # Frontend assets
│               ├── style.css     # Dashboard styling
│               └── dashboard.js  # WebSocket client & UI logic
├── tests/
│   ├── test_cli.py               # CLI tests
│   ├── test_server.py            # Server endpoint tests
│   ├── test_replay.py            # Replay orchestration tests
│   ├── test_relay.py             # Relay tunnel tests
│   ├── test_history.py           # History browser tests
│   ├── test_filters.py           # Conditional forwarding tests
│   ├── test_payload_inspection.py # Payload inspection tests
│   ├── test_ssrf.py              # SSRF protection tests
│   ├── test_dashboard_router.py  # Dashboard route tests
│   ├── test_dashboard_integration.py # Dashboard integration tests
│   ├── test_dashboard_acceptance.py  # Dashboard acceptance tests
│   ├── test_dashboard_connection_manager.py # Connection manager tests
│   └── test_dashboard_live.py    # Live WebSocket feed tests
├── docs/
│   ├── getting-started.md        # Getting started guide
│   ├── cli-reference.md          # CLI command reference
│   ├── dashboard-guide.md        # Dashboard user guide
│   └── screenshots/              # Dashboard screenshots
├── CHANGELOG.md
└── pyproject.toml
```

## Development

```bash
# Set up
git clone https://github.com/csaszarzoltan/hookrelay.git
cd hookrelay
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest -q

# Lint
ruff check src/ tests/
```

## License

MIT — see [LICENSE](LICENSE) (not present; MIT applies by default per `pyproject.toml`).

### Product and implementation reports

- `docs/product-ux-requirements-report.md` contains the full product, UX, and requirements analysis.
- `IMPLEMENTATION_REPORT.md` documents implemented scope, decisions, tests, assumptions, and remaining opportunities.
