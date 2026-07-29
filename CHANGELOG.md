# Changelog

All notable changes to **hookrelay** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-07-29

### Features

- **Regex Payload Filtering** — `RequestFilter.by_body()`, `by_header_regex()`, `by_json_field()` for regex-based matching on body content, header values, and nested JSON fields via dot-path expressions
- **Conditional Routing Rules** — `RoutingRule` data model and `RouterEngine` with priority-based first-match-wins evaluation; supports channel-scoped conditions, fallback catch-all rules, and max forward count limits
- **Filter Presets** — `FilterPreset` class with built-in presets for Stripe (`charge`/`payment`/`invoice` events), GitHub (X-GitHub-Event + action field), Slack (event type / challenge), HTTP methods, and status code ranges (`2xx`, `4xx`, `5xx`)
- **Filter Chain Composition** — `FilterChain` combinators (`all()`, `any()`, `not_()`) for AND/OR/NOT filter composition and nesting
- **Filter Expression Language** — `FilterExpressionParser` parses string expressions like `method=POST path~^/webhook body.event.type~evt_` into `RequestFilter` instances, supporting `=`, `!=`, and `~` (regex) operators
- **Saved Filter Sets** — Persist, load, list, and delete named filter sets via `Storage.save_filter_set()` and related CRUD methods
- **Routing Rule Storage** — SQLite persistence for routing rules with `Storage.save_routing_rule()`, `list_routing_rules()`, `update_routing_rule()`, `delete_routing_rule()`, `reorder_routing_rules()`
- **Filter Execution History** — `Storage.log_filter_execution()` and `query_filter_history()` for auditing which filters matched which requests

### New Files

- `src/hookrelay/routing.py` — RoutingRule model and RouterEngine (182 lines)
- `tests/test_routing.py` — Routing rule interface and behavioral tests (299 lines)
- `tests/test_storage_filters.py` — Filter/Routing storage persistence tests (343 lines)

### Tests

- 117 new tests across 4 test modules (advanced filtering interface/behavioral, routing, filter/storage persistence)
- 447 total tests (up from 330 in v0.3.0)

## [0.3.0] — 2026-07-29

### Features

- **JSON Schema Validation Engine** — validate webhook payloads against JSON Schema definitions with auto-validation on ingress
- **Dashboard Integration** — real-time validation status display in the dashboard UI with pass/fail indicators
- **Schema CRUD REST API** — create, read, update, delete schema definitions via HTTP endpoints
- **CLI Schema Commands** — `hookrelay schema list|add|remove|validate` for terminal-based schema management
- **Auto-Validation on Webhooks** — incoming webhooks automatically validated against enabled schema definitions per channel
- **Validation Results API** — query validation history and results via REST endpoints
- **Server Foundation** — FastAPI server with `/health` endpoint, WebSocket connections, and static file serving

### Dependencies

- `jsonschema[format-nongpl]>=4.26` — JSON Schema validation (Draft 2020-12, Draft 7, Draft 6, Draft 4)
- `fastapi>=0.110` — REST API and server framework
- `uvicorn>=0.29` — ASGI server
- `jinja2>=3.1` — template engine for dashboard pages

### Tests

- 86 new tests across 8 test modules (schemas, validation, schema API, CLI schema, auto-validation, server, dashboard integration, validation results)
- 330 total tests (up from 244 in v0.2.0)

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
