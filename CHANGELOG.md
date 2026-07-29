# Changelog

All notable changes to **hookrelay** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-29

### Features

- **Web Debugging Dashboard** — FastAPI server with browser-based UI for webhook debugging
- **Live Feed** — real-time webhook events pushed via WebSocket, auto-updating table on the dashboard index page
- **Payload Inspector** — rich HTML view of request metadata, headers, query parameters, and body
- **History Browser** — paginated, filterable webhook history with channel/method/path filters
- **Request Replay from Dashboard** — one-click replay with inline result display via the Replay page
- **Live Monitoring WebSocket** — `/dashboard/ws/live` endpoint for programmatic real-time event streaming
- **Health Check Endpoint** — `GET /health` returning status, version, uptime, and request count
- **`hookrelay serve` command** — start the FastAPI server with dashboard from the CLI

### Fixes

- **Static files mount** — CSS (`style.css`) and JS (`dashboard.js`) are now properly served via `StaticFiles` mount in `server.py`
- **Jinja2 template fix** — `is bytes` test replaced with `is string` in `inspect.html` to prevent 500 errors on the inspector page

### Dependencies

- `fastapi>=0.115` — web framework for the server and dashboard
- `uvicorn[standard]>=0.30` — ASGI server
- `jinja2>=3.1` — template engine for dashboard pages

### Dev Dependencies

- `pytest-asyncio>=0.24` — async test support for WebSocket and async endpoints
- `httpx>=0.27` — async HTTP client for dashboard integration tests

### Tests

- 90 new tests across 7 test modules (dashboard router, integration, acceptance, connection manager, live feed, server endpoints, CLI serve)
- 244 total tests (up from 157 in v0.1.0)
- Static file serving tests
- WebSocket live feed broadcast tests
- Dashboard page rendering tests (Live Feed, History, Inspector, Replay)
- Replay API integration tests

## [0.1.0] — 2026-07-23

### Features

- **Webhook relay** — forward webhooks from a public endpoint to localhost via WebSocket tunnel
- **CLI interface** — Typer-based CLI with commands: `forward`, `listen`, `history`, `replay`, `status`
- **Payload inspection** — real-time webhook display with method, headers, body, and query params
- **Request replay** — replay any received webhook with a single `hookrelay replay <id>` command
- **History browser** — search and browse recent webhooks with filters (channel, method, path)
- **Conditional forwarding** — filter by source IP, HTTP method, path pattern, headers, status code
- **SSRF protection** — IP range blocking (IPv4/IPv6), DNS anti-rebinding, protocol whitelist, port validation
- **SQLite persistence** — FTS5-powered search with automatic indexing and pagination
- **Status command** — health check and server info via `hookrelay status`
- **Listen mode** — live listening on a channel with streaming output

### Tests

- 157 tests across 7 test modules (CLI, relay, payload inspection, replay, filters, history, SSRF)
- Interface tests for all public function signatures
- Behavioral tests for error paths, edge cases, and happy paths
- SSRF module: 34 tests covering IP ranges, DNS resolution, protocol validation, and port checking
