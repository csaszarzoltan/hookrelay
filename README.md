# hookrelay 🪝

**Webhook relay tool for local development.** CLI-first ngrok alternative — forward webhooks to localhost, inspect payloads in real-time, replay historical requests, and filter by source. Now with a **Web Dashboard** for visual debugging.

[![GitHub Release](https://img.shields.io/github/v/release/csaszarzoltan/hookrelay?logo=github)](https://github.com/csaszarzoltan/hookrelay/releases)
[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1081%20passing-brightgreen)](https://github.com/csaszarzoltan/hookrelay/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dashboard](https://img.shields.io/badge/feature-dashboard-blueviolet)](#web-dashboard)

---

## Features

### What is new in 1.8.0

- **Payload transformations** — named, JQ-style filter rules
  (`uppercase`/`lowercase`/`timestamp`/`uuid`/`hash`/`mask_secrets`
  built-ins, field set/delete/rename, type conversion) applied to webhook
  payloads before delivery; CRUD via `/api/v1/transformations`,
  `hookrelay transform test`, and the dashboard builder with a live
  client-side preview
- **Multi-destination routing** — fan one inbound webhook out to multiple
  destinations per capture bin with `broadcast` / `round_robin` / `weighted`
  delivery modes; per-destination transforms, signing, headers, retry
  policy, and enable/weight
- **Outgoing HMAC signing** — sign payloads leaving the relay in the
  `svix` (Ed25519), `hookdeck`, `github`, or `custom` (HMAC-SHA256) wire
  formats, always stamped with `x-hookrelay-timestamp`; Python verification
  via `verify_signature`
- **Dashboard** — Transformations tab (builder + live preview + builtin
  chips + full CRUD) and Destinations tab (signing/headers/retry/delivery
  mode per destination, delivery logs per destination)

### What is new in 1.7.0

- **Failure alerting** — declarative alert rules (`success_rate_below`,
  `consecutive_failures`, `dlq_depth_above`) evaluated over rolling windows
  of stored delivery history by a ~60s background loop; per-rule cooldown
  prevents alert storms and paused rules never fire
- **Notifiers** — Slack incoming-webhook, SMTP email, and generic outbound
  webhook channels, every outbound URL SSRF-guarded at save and at fire;
  secrets (Slack webhook token, SMTP password) are never exposed by listings
- **Delivery insights API** — `GET /api/insights/endpoints` (per-endpoint
  deliveries, success rate, p50/p95/p99 latency, top failure reason) and
  `GET /api/insights/timeseries` (zero-filled hourly/daily buckets), with
  422 validation on window/bucket
- **Alerts + insights CLI** — `hookrelay alerts list|create|delete` and
  `hookrelay insights endpoints|timeseries`
- **Dashboard** — `/dashboard/alerts` tab (rules list, create form,
  enable/disable toggle, delete) and `/dashboard/insights` view (endpoint
  stats table + canvas time-series chart)
- **1081 passing tests and zero failures**

### What is new in 1.6.0

- **Webhook capture bins** — persistent, webhook.site-style test endpoints that capture every request (method, headers, body, query params, source IP) even with no client connected; one-click forward/replay of any captured request to an SSRF-guarded target
- **Capture bins CLI** — `hookrelay bin create|list|inspect|forward` for terminal-based bin management
- **Bins dashboard** — `/dashboard/bins` view with bin creation, copy-URL, live request feed, and click-to-forward
- **871 passing tests and zero failures**

### Included from 1.5.0

- **Production delivery infrastructure** — persistent `RetryQueue` with capped exponential backoff (optional jitter), `DeadLetterQueue` with failure metadata and requeue, `DeliveryTracker` state machine (pending → delivered | in-dlq), and TTL-based `IdempotencyManager` dedup
- **HMAC verification & per-endpoint configuration** — Svix-style `t=,v1=` signatures with constant-time compare and timestamp tolerance; `EndpointConfig` (timeout/retries/headers/secret) validated against the SSRF guard at configuration time
- **Team dashboard metrics** — counts by status/endpoint, nearest-rank p50/p95/p99 latency, success rates, and a composed `DashboardService` summary payload
- Optional AES-256-GCM encryption for backup database files
- Per-backup random salt and nonce
- PBKDF2-HMAC-SHA256 key derivation with 600,000 iterations
- Encryption-aware Backup center, API, scheduler, CLI, inspection, and restore
- Locked catalog verification without decrypting content
- Backward-compatible plaintext backup format v1 support
- **731 passing tests and zero failures**

### Included from 1.4.0

- Dedicated Backup center in the dashboard
- Verified recovery-point cards and catalog summary
- Read-only restore preview without modifying live data
- One-click backup creation with accessible feedback
- Confirmed, audited deletion of complete backup bundles
- Managed-directory confinement for backup file operations
- **508 passing tests and zero failures**

### Included from 1.3.0

- Stable non-reversible audit actor fingerprints
- HMAC-SHA256 audit checkpoints for external attestation
- Fail-closed checkpoint signing-key configuration
- Verified backup catalog and read-only restore preview data
- Backup inspection path restrictions
- **502 passing tests and zero failures**

### Included from 1.2.0

- Storage-health diagnostics in API and Settings
- Persistent automatic-backup policy
- Interval-based due detection and manual run-now workflow
- Complete backup-bundle retention and pruning
- Database/WAL size and row-count visibility
- Accessible dashboard controls with checksum feedback
- **496 passing tests and zero failures**

### Included from 1.1.0

- Consistent SQLite backup bundles with checksum manifests
- Verified, atomic restore with automatic pre-restore rollback copy
- Tamper-evident SHA-256 audit hash chain
- Audit-chain verification and controlled retention purge
- Backup and audit administration APIs
- `hookrelay data backup`, `restore`, and `verify-audit` commands
- **490 passing tests and zero failures**

### Included from 1.0.0

- Explicit, versioned SQLite migrations with preserved legacy requests
- Durable versioned event envelopes and monotonic reconnect cursors
- Connection registry with session, target, client version, capabilities, heartbeat, and stale state
- Canonical request-query schema with opaque cursor pagination
- Append-only, redacted audit records for sensitive operations
- Data introspection, connection, event, query, and audit APIs
- **483 passing tests and zero failures**

### Included from 0.9.1

- Incremental Live Feed updates without page reloads
- Visible live connection state, resilient reconnect, and pause/resume buffering
- Full-text History search, path and validation filters, and saved request views
- Correct stored-channel replay with actionable no-client feedback
- Consistent sensitive request-header masking
- Request deletion and delivery-attempt APIs
- Restored delivery timeline and dashboard readiness API
- **477 passing tests and zero failures**



### CLI
- **Webhook relay** — forward webhooks from a public endpoint to `localhost` via a WebSocket tunnel
- **Real-time inspection** — view method, headers, body, and query params as they arrive
- **Request replay** — replay any received webhook with one command: `hookrelay replay <id>`
- **Capture bins (v1.6.0+)** — create persistent test endpoints and forward captured requests: `hookrelay bin create|list|inspect|forward`
- **Alerting (v1.7.0+)** — failure alert rules with rolling-window evaluation: `hookrelay alerts list|create|delete`
- **Delivery insights (v1.7.0+)** — per-endpoint stats and time series: `hookrelay insights endpoints|timeseries`
- **Transformations (v1.8.0+)** — preview JQ-style payload filters: `hookrelay transform test`
- **Destinations (v1.8.0+)** — manage multi-destination forwarding targets: `hookrelay destination add|list|delete`
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
- **Team delivery metrics (v1.5.0+)** — read-only analyzers for counts by status/endpoint, p50/p95/p99 latency, and success rates, ready to power dashboard/API views (`hookrelay.dashboard.*`, see [dashboard metrics guide](docs/dashboard-metrics-1.5.md))
- **Bins view (v1.6.0+)** — create capture bins, copy their public URLs, watch a live request feed, and forward captured requests with one click (see [capture bins guide](docs/capture-bins-1.6.md))
- **Alerts tab (v1.7.0+)** — `/dashboard/alerts`: alert rule list, create form, enable/disable toggle, and delete
- **Insights view (v1.7.0+)** — `/dashboard/insights`: per-endpoint delivery stats table and a canvas time-series chart
- **Transformations tab (v1.8.0+)** — transformation builder with live JQ-style preview and builtin chips, full CRUD
- **Destinations tab (v1.8.0+)** — per-bin destination manager with signing config, headers, retry, and delivery mode

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

### 7. Capture webhooks with a bin (v1.6.0+)

Create a persistent test endpoint, point a sender at it, then forward any
captured request (see the [capture bins guide](docs/capture-bins-1.6.md)):

```bash
hookrelay bin create --description "stripe tests"
#   → Bin created: http://localhost:8000/bin/<bin_id>

curl -X POST "http://localhost:8000/bin/<bin_id>?src=stripe" \
     -H "Content-Type: application/json" -d '{"event": "invoice.paid"}'

hookrelay bin inspect <bin_id>     # list captured requests
hookrelay bin forward <request-id> --to https://example.com/webhook
```

## Reliable delivery & webhook security (v1.5.0+)

v1.5.0 adds production webhook infrastructure you can use directly from
Python: a persistent retry queue, dead-letter queue, idempotency dedup,
Svix-style HMAC signature verification, and validated per-endpoint
configuration.

Sign and verify webhook payloads:

```python
from hookrelay.security import HMACVerifier

verifier = HMACVerifier(secret="whsec_...", tolerance_seconds=300)
signature = verifier.sign(payload)          # t=<unix_ts>,v1=<hex>
assert verifier.verify(payload, signature)  # constant-time, replay-aware
```

Enqueue a delivery with retries and idempotency:

```python
from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.delivery import RetryQueue
from hookrelay.storage import Storage

queue = RetryQueue(Storage("webhooks.db"))
queue.enqueue(
    delivery_id="dlv-1",
    request_id="req-1",
    endpoint_id="ep-1",
    target_url="https://example.com/hook",
    method="POST",
    headers={},
    body=b'{"event": "order.created"}',
    idempotency_key="stripe_evt_123",       # duplicate events are rejected
    policy=RetryPolicy(max_retries=5, jitter=True),
)
```

Every target URL passes the shared SSRF guard at enqueue and at configuration
time. Feature guides: [delivery infrastructure](docs/delivery-infrastructure-1.5.md),
[dead-letter queue](docs/dead-letter-queue-1.5.md),
[idempotency](docs/idempotency-1.5.md),
[HMAC verification](docs/hmac-verification-1.5.md),
[endpoint configuration](docs/endpoint-config-1.5.md), and
[dashboard metrics](docs/dashboard-metrics-1.5.md). Runnable examples for
every feature live in [`examples/`](examples/).

## Screenshots

| Dashboard Live Feed | Payload Inspector |
|---|---|
| ![Dashboard Live Feed](docs/screenshots/dashboard.png) | ![Inspector](docs/screenshots/inspector.png) |

| History Browser | Request Replay |
|---|---|
| ![History Browser](docs/screenshots/history.png) | ![Replay](docs/screenshots/replay.png) |

## Webhook capture bins (v1.6.0)

Create persistent, webhook.site-style test endpoints that capture every
request — method, headers, body, query params, source IP and timestamp — even
when no client is connected:

```bash
# 1. Create a bin — prints the public capture URL
hookrelay bin create --description "stripe tests"
#   → Bin created: http://localhost:8000/bin/<bin_id>

# 2. Point any sender at that URL (POST/GET/PUT/PATCH/DELETE all captured)
curl -X POST http://localhost:8000/bin/<bin_id>?src=stripe \
     -H "Content-Type: application/json" -d '{"event": "invoice.paid"}'

# 3. Inspect captured requests (prints request ids)
hookrelay bin inspect <bin_id>

# 4. One-click forward a captured request to any target (SSRF-guarded)
hookrelay bin forward <request_id> --to https://example.com/webhook
```

- REST API: `POST /api/bins`, `GET /api/bins`, `DELETE /api/bins/{id}`,
  `GET /api/bins/{id}/requests` (paginated), per-request full payload view,
  and `POST /api/bins/{id}/requests/{request_id}/forward`.
- Dashboard **Bins** view at `/dashboard/bins`: create a bin, copy its URL,
  watch the live request feed (same WS as `/dashboard/ws/live`), and forward
  captured requests with one click.
- Full reference: [capture bins guide](docs/capture-bins-1.6.md) (REST +
  SSRF behaviour + Python API) and the runnable
  [`examples/capture_bins.py`](examples/capture_bins.py).

## Failure alerting & delivery insights (v1.7.0)

Hookrelay 1.7.0 tells you when delivery breaks: threshold rules evaluated
over rolling windows of stored delivery history, fanned out to Slack,
email, or an outbound webhook.

Create a rule — alert when the checkout endpoint's success rate drops
below 90% over the last hour:

```bash
curl -X POST http://localhost:8000/api/alerts/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "checkout success rate",
    "scope": "endpoint",
    "endpoint_id": "ep-checkout",
    "metric": "success_rate_below",
    "threshold": 0.9,
    "window_minutes": 60,
    "cooldown_minutes": 15
  }'
```

Or from the CLI:

```bash
hookrelay alerts create checkout-success \
  --metric success_rate_below --threshold 0.9 --window-minutes 60
```

Then point a notifier at your channel (Slack, SMTP, or a generic webhook)
and attach it to the rule; the evaluator loop (default 60s) fires the
notifier when the threshold is crossed and the per-rule cooldown (default
15 min) has elapsed. Paused rules never fire. Full reference — metric
types, scopes, cooldown, paused rules, notifier configuration, fire
history and audit — is in the [alerting guide](docs/alerting.md).

Delivery insights give you per-endpoint stats and time series over the
same data:

```bash
curl "http://localhost:8000/api/insights/endpoints?window=24h"
curl "http://localhost:8000/api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly"
```

```bash
hookrelay insights endpoints --window 24h
hookrelay insights timeseries --metric success_rate --window 24h --bucket hourly
```

Invalid windows/buckets return 422 with a `{"detail": ...}` body. See the
[insights API guide](docs/insights-api.md) for request/response examples,
failure-reason classification, and validation behaviour. The dashboard
**Alerts** tab (`/dashboard/alerts`) manages rules with a create form,
enable/disable toggles, and delete; the **Insights** view
(`/dashboard/insights`) renders the stats table and a time-series chart.

## Payload transformations & multi-destination routing (v1.8.0)

v1.8.0 rewrites webhook payloads before delivery and fans one inbound
webhook out to multiple destinations. Create a transformation rule
(JQ-style filters), attach it to destinations per capture bin, and let each
destination sign, add headers, retry, and route its own way.

Create a transformation and preview it against a sample payload:

```bash
curl -s -X POST http://localhost:8000/api/v1/transformations \
  -H "Content-Type: application/json" \
  -d '{"name": "scrub-and-normalize", "filters": [
    ".data.currency |= uppercase", ".data.amount :: integer", "del(.token)"]}'

hookrelay transform test ".data.currency |= uppercase" payload.json
```

Attach signed destinations to a bin with different delivery modes:

```bash
hookrelay destination add bin-checkout https://api.acme.com/hook \
  --transform <transform_id> \
  --signing-algorithm github --signing-secret whsec_checkout \
  --header "X-Source=hookrelay"

hookrelay destination add bin-checkout https://canary.acme.com/hook \
  --delivery-mode weighted --weight 1

hookrelay destination list bin-checkout
```

Delivery modes: `broadcast` (every enabled destination), `round_robin`
(exactly one, cycling), `weighted` (exactly one, drawn proportional to
`weight`). Outgoing signatures follow the `svix` (Ed25519), `hookdeck`,
`github`, or `custom` (HMAC-SHA256) wire formats, always stamped with
`x-hookrelay-timestamp`; receivers verify via Python
(`verify_signature`). Feature guides: [transformations](docs/transformations.md),
[destinations](docs/destinations.md), [signing](docs/signing.md), and the
runnable [`examples/transforms_routing.py`](examples/transforms_routing.py).
The dashboard **Transformations** tab offers a builder with live preview
and builtin chips; the **Destinations** tab manages per-bin signing,
headers, retry, and delivery mode.

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
| `hookrelay bin create` | Create a webhook capture bin and print its public URL |
| `hookrelay bin list` | List all capture bins |
| `hookrelay bin inspect <bin_id>` | Show bin details and captured requests |
| `hookrelay bin forward <request_id> --to <url>` | Forward a captured request to a URL (SSRF-guarded) |
| `hookrelay alerts list` | List all alert rules |
| `hookrelay alerts create <name> --metric <m> --threshold <t>` | Create an alert rule (v1.7.0) |
| `hookrelay alerts delete <rule_id>` | Delete an alert rule (v1.7.0) |
| `hookrelay insights endpoints [--window 24h]` | Per-endpoint delivery stats as JSON (v1.7.0) |
| `hookrelay insights timeseries [--metric deliveries] [--window 24h] [--bucket hourly]` | Bucketed delivery time series as JSON (v1.7.0) |
| `hookrelay transform test <filter> <payload.json>` | Apply a JQ-style filter to a payload file and print the result (v1.8.0) |
| `hookrelay destination add <bin_id> <url> [--transform ID] [--signing-algorithm ALGO] [--signing-secret SECRET] [--header K=V]... [--weight N] [--delivery-mode MODE]` | Add a destination to a bin (v1.8.0) |
| `hookrelay destination list <bin_id>` | List all destinations for a bin (v1.8.0) |
| `hookrelay destination delete <destination_id>` | Delete a destination (v1.8.0) |

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
│       ├── alerts/               # Failure alerting (rules, storage, evaluator, notifiers, API)
│       ├── insights/             # Delivery insights (service, API)
│       ├── bins/                 # Webhook capture bins (service, forward, API, CLI, dashboard)
│       ├── transforms/           # Payload transformation engine + store (v1.8.0)
│       ├── routing/              # Multi-destination routing + destination store (v1.8.0)
│       ├── config/               # Per-endpoint config (RetryPolicy, headers)
│       ├── delivery/             # Retry queue, DLQ, idempotency, tracking
│       ├── security/             # HMAC signature verification + outgoing signing
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
│   ├── delivery-infrastructure-1.5.md  # Retry queue & delivery tracking
│   ├── dead-letter-queue-1.5.md  # Dead-letter queue guide
│   ├── idempotency-1.5.md        # Idempotency dedup guide
│   ├── hmac-verification-1.5.md  # HMAC signature verification guide
│   ├── endpoint-config-1.5.md    # Per-endpoint configuration guide
│   ├── dashboard-metrics-1.5.md  # Dashboard delivery metrics guide
│   ├── capture-bins-1.6.md       # Webhook capture bins guide
│   ├── alerting.md               # Alert rules, evaluator, notifiers guide (v1.7.0)
│   ├── insights-api.md           # Delivery insights API reference (v1.7.0)
│   ├── transformations.md        # Payload transformation engine guide (v1.8.0)
│   ├── destinations.md           # Multi-destination routing guide (v1.8.0)
│   ├── signing.md                # Outgoing signing guide (v1.8.0)
│   └── screenshots/              # Dashboard screenshots
├── examples/
│   ├── basic_relay.py            # Local receiver + relay flow
│   ├── api_usage.py              # History inspection via the client API
│   ├── delivery_retry_queue.py   # Retry queue & delivery tracking
│   ├── dead_letter_queue.py      # DLQ inspect/requeue workflow
│   ├── idempotency.py            # Idempotency key registry
│   ├── hmac_verification.py      # Sign/verify webhook payloads
│   ├── endpoint_config.py        # EndpointConfig + HeaderManager
│   ├── dashboard_metrics.py      # Metrics, latency, success-rate analyzers
│   ├── capture_bins.py           # Webhook capture bins walkthrough
│   └── transforms_routing.py     # Transformations + routing + signing walkthrough (v1.8.0)
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


### Privacy and retention

Open `/dashboard/settings` to configure request retention from 1 to 3650 days. The default is 30 days. The policy runs at server startup and can also be applied immediately from the dashboard. Stored local-response bodies are capped at 16 KiB; common credential and cookie response headers are masked before persistence.

### Implementation report

See `IMPLEMENTATION_REPORT.md` for product rationale, requirements, changed modules, TDD notes, assumptions, validation results, and deferred opportunities.


### Optional access protection

Local development remains open by default. To protect a server that is reachable by other users or networks, set a strong token before starting Hookrelay:

```bash
export HOOKRELAY_API_TOKEN="replace-with-a-long-random-secret"
hookrelay serve
```

The browser redirects protected dashboard pages to `/dashboard/login`. API clients use:

```http
Authorization: Bearer replace-with-a-long-random-secret
```

The forwarding CLI reads the same environment variable and adds the Authorization header automatically. `/health`, `/webhook/{channel}`, and dashboard static assets remain public so health monitors and external webhook providers can continue to operate. Use HTTPS whenever the server is accessed across a network.


### Release integrity

Version 0.9.1 is a reliability restoration release. The generated ZIP is smoke-tested after packaging, and the complete committed test suite must pass before handoff. The product/UX assessment that drove this release is included at `docs/product-ux-requirements-report-0.9.md`; implementation details are in `IMPLEMENTATION_REPORT.md`.


### Versioned data APIs

Hookrelay 1.0 introduces explicit data contracts:

- `GET /api/data/schema` reports the current database, event, and query schema versions.
- `GET /api/connections` returns safe active-client metadata and computed stale state.
- `GET /api/events?after_cursor=0` returns durable events in cursor order for reconnect recovery.
- `GET /api/requests/query` supports canonical search, filters, and opaque cursor pagination.
- `GET /api/audit` returns append-only redacted audit records.

Database migrations run automatically when `Storage` opens a database. A database created by a newer unsupported Hookrelay version is rejected rather than modified.


### Backup and restore

Create a consistent backup while Hookrelay is running:

```bash
hookrelay data backup --db-path ./webhooks.db --destination ./backups
```

Verify the manifest checksum and restore it while the server is stopped:

```bash
hookrelay data restore ./backups/hookrelay-...json --db-path ./webhooks.db
```

If the destination exists, Hookrelay preserves it as `webhooks.db.pre_restore` before atomic replacement. Verify audit integrity with:

```bash
hookrelay data verify-audit --db-path ./webhooks.db
```


### Storage operations

The Settings dashboard now reports SQLite integrity, schema version, database and WAL sizes, request count, and audit-chain status. Automatic backups can be enabled with an interval from 1 to 720 hours and a retention count from 1 to 365 complete bundles.

The application evaluates whether a backup is due when the protected backup-run endpoint is called. For unattended operation, invoke that endpoint or the equivalent storage method from an external scheduler. This design avoids hidden in-process background jobs and works reliably with the current single-process architecture.


### Audit checkpoints

Set a secret dedicated to audit checkpoint signing:

```bash
export HOOKRELAY_AUDIT_SIGNING_KEY="replace-with-a-long-random-secret"
```

Create a checkpoint through `POST /api/audit/checkpoints`, then store the returned JSON outside the Hookrelay database and preferably outside the host. Verify it later through `POST /api/audit/checkpoints/verify`. The key is never returned or stored in the database.

Authenticated actions use a truncated SHA-256 fingerprint such as `token:1a2b3c4d5e6f7890` rather than storing the raw access token.


### Backup center

Open `/dashboard/backups` to review every managed recovery point. Hookrelay verifies each bundle's manifest, size, SHA-256 checksum, and SQLite integrity before labeling it Verified. Inspect restore preview displays application/schema versions and request, event, and audit counts without writing to the backup or live database.

Web restore remains intentionally unavailable. Use the verified CLI restore workflow while the server is stopped. The dashboard can create and delete managed backup bundles, but deletion always requires explicit confirmation and produces an audit event.


### Encrypted backups

Set a dedicated backup-encryption secret before creating or restoring backups:

```bash
export HOOKRELAY_BACKUP_ENCRYPTION_KEY="replace-with-a-long-random-secret"
```

When configured, API, dashboard, scheduled, and CLI backup creation writes an authenticated `.db.enc` file. The manifest remains readable so the catalog can verify size and SHA-256 without the key. Content counts and SQLite integrity require successful decryption.

Use the same environment variable during offline restore:

```bash
HOOKRELAY_BACKUP_ENCRYPTION_KEY="..." \
  hookrelay data restore ./backups/hookrelay-...json --db-path ./webhooks.db
```

Losing the encryption key makes encrypted backups unrecoverable. Store the key separately from both the live database and backup files.
