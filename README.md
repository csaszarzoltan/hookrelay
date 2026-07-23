# hookrelay 🪝

**Webhook relay tool for local development.** CLI-first ngrok alternative — forward webhooks to localhost, inspect payloads in real-time, replay historical requests, and filter by source.

[![GitHub Release](https://img.shields.io/github/v/release/csaszarzoltan/hookrelay?logo=github)](https://github.com/csaszarzoltan/hookrelay/releases)
[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-157%20passing-brightgreen)](https://github.com/csaszarzoltan/hookrelay/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Features

- **Webhook relay** — forward webhooks from a public endpoint to `localhost` via a WebSocket tunnel
- **Real-time inspection** — view method, headers, body, and query params as they arrive
- **Request replay** — replay any received webhook with one command: `hookrelay replay <id>`
- **History browser** — search and browse webhooks with FTS5 full-text search
- **Conditional forwarding** — filter by source IP, HTTP method, path, headers, or status code
- **SSRF protection** — IP range blocking (IPv4/IPv6), DNS anti-rebinding, protocol whitelist
- **CLI-first** — Typer-powered, no GUI required, pipe-friendly
- **Lightweight** — Python 3.11+, only 3 runtime dependencies (typer, websocket-client, requests)

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

### 1. Start the relay server

```bash
hookrelay-server
# Listening on http://localhost:8000
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

The webhook is automatically forwarded to `http://localhost:3000/webhook`.

### 4. View history

```bash
hookrelay history
```

### 5. Replay a request

```bash
hookrelay replay <request-id>
```

## CLI Commands

| Command | Description |
|---|---|
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
│       ├── cli.py       # Typer CLI commands
│       ├── client.py    # WebSocket client & local forwarder
│       ├── filters.py   # Conditional forwarding filters
│       ├── history.py   # History browser & search
│       ├── ingester.py  # Webhook ingestion & validation
│       ├── models.py    # Data models
│       ├── relay.py     # WebSocket relay tunnel manager
│       ├── replay.py    # Request replay orchestration
│       ├── ssrf.py      # SSRF protection
│       └── storage.py   # SQLite storage with FTS5
├── tests/               # 157 tests
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
pytest tests/ -v

# Lint
ruff check src/ tests/
```

## License

MIT — see [LICENSE](LICENSE) (not present; MIT applies by default per `pyproject.toml`).
