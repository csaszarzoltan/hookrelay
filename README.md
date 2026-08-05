# hookrelay 🪝

**Webhook relay tool for local development.** CLI-first ngrok alternative — forward webhooks to localhost, inspect payloads in real-time, replay historical requests, and filter by source. Now with a **Web Dashboard** for visual debugging.

[![GitHub Release](https://img.shields.io/github/v/release/csaszarzoltan/hookrelay?logo=github)](https://github.com/csaszarzoltan/hookrelay/releases)
[![Python](https://img.shields.io/badge/python-3.11+-blue?logo=python)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-731%20passing-brightgreen)](https://github.com/csaszarzoltan/hookrelay/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dashboard](https://img.shields.io/badge/feature-dashboard-blueviolet)](#web-dashboard)

---

## Features

### What is new in 1.5.0

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
│       ├── bins/                 # Webhook capture bins (service, forward, API, CLI, dashboard)
│       ├── config/               # Per-endpoint config (RetryPolicy, headers)
│       ├── delivery/             # Retry queue, DLQ, idempotency, tracking
│       ├── security/             # HMAC signature verification
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
│   └── screenshots/              # Dashboard screenshots
├── examples/
│   ├── basic_relay.py            # Local receiver + relay flow
│   ├── api_usage.py              # History inspection via the client API
│   ├── delivery_retry_queue.py   # Retry queue & delivery tracking
│   ├── dead_letter_queue.py      # DLQ inspect/requeue workflow
│   ├── idempotency.py            # Idempotency key registry
│   ├── hmac_verification.py      # Sign/verify webhook payloads
│   ├── endpoint_config.py        # EndpointConfig + HeaderManager
│   └── dashboard_metrics.py      # Metrics, latency, success-rate analyzers
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
