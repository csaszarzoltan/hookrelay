# Changelog

All notable changes to **hookrelay** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.7.0] — 2026-08-08

### Features

- **Failure Alerting** — declarative alert rules (`alert_rules` table, migration 6) evaluated by a configurable ~60s background loop (daemon thread, off the event loop) over rolling windows of stored delivery attempts: `success_rate_below`, `consecutive_failures`, and `dlq_depth_above` metrics, with per-rule cooldown (default 15 min); paused rules never fire
- **Notifiers** — Slack incoming-webhook, SMTP email (stdlib `smtplib`, STARTTLS + auth), and generic outbound webhook channels, fan-out through a `NotifierRegistry`; every outbound URL is SSRF-guarded (repo `ssrf.validate_target_url`) at save and at fire; notifier definitions persist under `app_settings["alert_notifiers"]`
- **Alerts API** — `GET/POST /api/alerts/rules`, `PATCH/DELETE /api/alerts/rules/{id}`, notifier CRUD + test endpoint, `GET /api/alerts/status` and `GET /api/alerts/history` (fire history table, migration 7, with tamper-evident audit entries)
- **Delivery Insights** — `GET /api/insights/endpoints` (per-endpoint deliveries/success-rate/latency percentiles/top failure reason) and `GET /api/insights/timeseries` (zero-filled chronological buckets for deliveries/success_rate/latency_p95) with 422 validation on window/bucket
- **Alerts + Insights CLI** — `hookrelay alerts list|create|delete` and `hookrelay insights endpoints|timeseries`
- **Dashboard** — `/dashboard/alerts` tab (rules list, create form, enable/disable toggle, delete) and `/dashboard/insights` view (endpoint stats table + canvas time-series chart)

### Tests

- 263 pre-dev TDD tests for alerting + insights across 7 files (`test_alert_rules`, `test_alert_evaluator`, `test_notifiers`, `test_alerts_api`, `test_alert_history`, `test_insights_service`, `test_insights_api`)
- Full suite baseline: 871 pre-existing tests unchanged

### Docs

- README — `hookrelay alerts` / `hookrelay insights` CLI usage and dashboard tabs

## [1.6.0] — 2026-08-05

### Features

- **Webhook Capture Bins** — public capture endpoint `/bin/{bin_id}` (GET/POST/PUT/PATCH/DELETE) plus `/api/bins` CRUD with paginated request listing and full payload view; the bin id doubles as the webhooks channel, so captures persist even with no WebSocket client connected
- **Forward Replay** — one-click re-send of a captured request (method/headers/body) to any target, SSRF-guarded via `ssrf.validate_target_url`; the forward endpoint runs off the event loop (sync def, threadpooled), strips hop-by-hop headers (Host/Content-Length/Connection/Transfer-Encoding) and lets `requests` recompute them, and replays binary bodies byte-exact from the raw stored row
- **Bins CLI** — `hookrelay bin create|list|inspect|forward` group wired into the main CLI
- **Bins Dashboard** — new `/dashboard/bins` page with bin creation, copy-URL, live feed, and click-to-forward; capture events broadcast over the existing `/dashboard/ws/live` connection manager
- **Storage & Server** — `bins` table with cascading request cleanup, bin CRUD in `Storage`, routers mounted with a flat `app.routes`, and `/bin/` made public in the auth middleware

### Fixes

- **Review blockers B1–B3** — forward endpoint no longer stalls the event loop (sync def); Host/Content-Length/Connection/Transfer-Encoding stripped and recomputed on replay; byte-exact binary body replay from the raw stored row
- **Review mediums M1–M4** — dashboard click-to-forward implemented and the served-page JS is now valid (double-escaped strings fixed); package docstring describes the feature; dead `SSRFError` catch removed from the bin CLI; `_get_or_create_storage` return type annotated
- **Security gate** — replaced f-string-built SQL in `schemas.py` and `backup.py` with allowlist/parameterized construction (behavior byte-identical)
- **Routing-rule hardening** — `update_routing_rule` drops non-allowlisted keys before building the SET clause; `cli status` validates the health URL through the SSRF guard plus an explicit http/https scheme check
- **Hermetic test fixtures** — `test_validation_results.py` store fixture moved to `tmp_path` (no fixed `/tmp` DB collisions on full-suite runs)

### Tests

- 93 new pre-dev TDD tests for capture bins: `test_bins.py` (52), `test_bins_api.py` (24), `test_bins_cli.py` (17)
- 5 regression tests pinning B1 (off-loop forward), B2 (hop-by-hop header strip), B3 (byte-exact replay, unit + API round-trip), and M1 (click-to-forward)
- Full suite: **871 passed, 0 failed, 0 errors, 0 skipped** (27 modules, junitxml-verified); ruff clean on scope

### Docs

- README — capture bins usage: `hookrelay bin` commands and `/dashboard/bins`
- Package docstring updated to describe the implemented feature

## [1.5.0] — 2026-08-02

### Features

- **Production Delivery Infrastructure** — persistent `RetryQueue` with idempotency dedup and exponential backoff (capped, jittered), `DeadLetterQueue` with failure metadata and requeue, `DeliveryTracker`/`DeliveryStatus` state machine (pending → delivered | failed → in-dlq | pending), and `IdempotencyManager` with TTL-based key registry; new `deliveries`, `dlq`, `idempotency_keys` tables created idempotently
- **REST API + CLI for Delivery & DLQ** — `GET/POST /api/deliveries`, `POST /api/deliveries/{id}/attempts`, `GET /api/dlq`, `POST /api/dlq/{entry_id}/requeue` (SSRF guard + idempotency preserved on enqueue), plus `hookrelay delivery list|status` and `hookrelay dlq list|requeue` CLI subcommands
- **Dashboard Metrics API & UI wiring** — `GET /api/dashboard/metrics` returns `{summary, time_series, endpoint_breakdown}` from `DashboardService`, and the Live Feed page renders a summary metrics strip server-side
- **HMAC Verification & Per-Endpoint Configuration** — Svix-style `HMACVerifier` (`t=,v1=` signatures, constant-time compare, timestamp tolerance, key rotation), `RetryPolicy` (frozen dataclass with capped exponential backoff and jitter), `EndpointConfig` (timeout/retries/headers/secret with `validate()`), `HeaderManager` (allowlist + injected headers, case-insensitive sensitive-header redaction)
- **Team Dashboard Metrics** — `MetricsCollector` (count by status/endpoint, zero-filled time series), `LatencyTracker` (nearest-rank p50/p95/p99 + average with endpoint filter and sliding window), `SuccessRateCalculator` (delivered/(delivered+failed), overall + per-endpoint), `DashboardService` summary payload
- **Data Resilience, Governance & Encryption** — HMAC-SHA256 audit hash chain for tamper evidence, SQLite backup/restore with atomic rollback and checksums, AES-256-GCM encrypted recovery points, protected backup/health endpoints, Backup Center with storage health monitoring and automated backup policy controls
- **Versioned Data APIs & Reliability (v1.0.0)** — versioned event envelopes with monotonic cursors, explicit schema migrations with audit logging, connection registry with heartbeat/stale detection, incremental live updates with exponential-backoff WebSocket reconnection, full-text search, combinable filters, named saved views
- **Authentication & Response Diagnostics** — token-based dashboard/WebSocket auth via `HOOKRELAY_API_TOKEN`, settings page for configurable request retention, response inspector (status/headers/body), client-side delivery reporting with redacted sensitive headers
- **Delivery Lifecycle Tracking & Saved Views** — delivery attempt tracking (status/duration/errors), persistent saved request views, full-text search across payloads/headers/paths, delivery timeline visualization, request deletion with diagnostic cleanup
- **Dashboard UX, Resilience & Security** — resilient WebSocket reconnection with live updates, advanced history filtering (method/path/validation status), sensitive header redaction, ARIA accessibility, pause-live-updates, `.invalid` hostname forwarding guard, deterministic URI/date-time format checkers

### Fixes

- **SSRF guard at both chokepoints (R1)** — `EndpointConfig.validate()` and `RetryQueue.enqueue()` enforce the shared `hookrelay.ssrf.validate_target_url` guard (private/loopback/metadata targets rejected)
- **State-machine reconciliation (R2)** — `DeliveryTracker` allows `pending → {in-dlq, pending}` to agree with `RetryQueue.record_attempt` / DLQ handoff edges
- **Fan-out attribution (R3)** — dashboard latency joins `delivery_attempts → deliveries` on `delivery_id` (unique per delivery) instead of `request_id` (1:N under fan-out)
- **v4 reopen regression** — `_ensure_delivery_attempt_columns()` now runs before `_init_schema()` so the v5 index never hits a pre-existing v4 table; schema v4→v5 is a no-op
- **Hermetic test fixtures** — `test_schemas.py` uses `tmp_path` (no `/tmp` pollution)

### Tests

- 773 tests passing (735 at this commit + 38 new API/CLI/UI-wiring tests), 0 failed, 0 skipped
- 213 new tests across delivery core (83), security/config (80), dashboard (50); 514 existing tests, zero regressions
- 3 regression tests pinning R1 SSRF chokepoints (config + enqueue) and R3 fan-out latency attribution under a shared `request_id`
- 38 new API/CLI/UI-wiring tests in `tests/test_delivery_api.py` and `tests/test_delivery_cli.py` (deliveries list/enqueue/attempts, dlq list/requeue, dashboard metrics, auth coverage, CLI subcommands)
- Ruff clean on all touched files (repo-wide pre-existing lint in examples/ unchanged)

### Docs

- `docs/data-requirements-1.0.md` — versioned data contracts and reliability requirements
- `docs/backup-center-1.4.md` — backup/restore, encryption, and storage health guide
- `docs/delivery-infrastructure-1.5.md` — retry queue, delivery tracking, and retry policy guide
- `docs/dead-letter-queue-1.5.md` — DLQ inspect/requeue guide
- `docs/api-reference-1.5.md` — REST + CLI contract for delivery, DLQ, and dashboard metrics
- `docs/idempotency-1.5.md` — TTL-based idempotency dedup guide
- `docs/hmac-verification-1.5.md` — Svix-style HMAC signature verification guide
- `docs/endpoint-config-1.5.md` — per-endpoint configuration and header management guide
- `docs/dashboard-metrics-1.5.md` — metrics, latency, and success-rate analyzers guide
- `examples/delivery_retry_queue.py`, `examples/dead_letter_queue.py`, `examples/idempotency.py`, `examples/hmac_verification.py`, `examples/endpoint_config.py`, `examples/dashboard_metrics.py` — runnable, verified examples for each new feature
- `docs/product-ux-requirements-report.md` / `-0.9.md` — UX requirements reports
- `docs/dashboard-guide.md`, `docs/cli-reference.md`, `docs/getting-started.md` — updated for auth, retention, delivery, and data commands
- `IMPLEMENTATION_REPORT.md` — per-release implementation notes
- `scripts/repro_v4_reopen.py` — reproduction script proving clean v4 DB reopen

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
