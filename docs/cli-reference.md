# CLI Reference

## `hookrelay forward`

Forward webhooks from a channel to a local target URL.

```bash
hookrelay forward <channel> <target> [--server URL] [--timeout SECONDS]
```

**Arguments:**

| Argument  | Description                              |
|-----------|------------------------------------------|
| `channel` | Channel name to listen on (required)     |
| `target`  | Local URL to forward webhooks to (required) |

**Options:**

| Option           | Default                    | Description                  |
|------------------|----------------------------|------------------------------|
| `--server`, `-s` | `http://localhost:8000`    | Relay server URL             |
| `--timeout`, `-t` | `30.0`                    | Connection timeout in seconds |

**Example:**
```bash
hookrelay forward stripe-events http://localhost:3000/webhooks/stripe
```

## `hookrelay listen`

Listen for incoming webhooks on a channel and print them to stdout.

```bash
hookrelay listen <channel> [--server URL]
```

**Example:**
```bash
hookrelay listen mychannel
```

## `hookrelay history`

Browse recent webhook requests.

```bash
hookrelay history [--channel CHANNEL] [--limit N] [--method METHOD] [--path PATH] [--id REQUEST_ID]
```

**Options:**

| Option          | Description                            |
|-----------------|----------------------------------------|
| `--channel`, `-c` | Filter by channel name              |
| `--limit`, `-n`   | Max results (default: 20)           |
| `--method`, `-m`  | Filter by HTTP method (GET, POST, etc.) |
| `--path`, `-p`    | Filter by path pattern              |
| `--id`            | View full details of a specific request |

**Example:**
```bash
hookrelay history
hookrelay history --method POST --limit 50
hookrelay history --id abc123def456
```

## `hookrelay replay`

Replay a stored webhook request.

```bash
hookrelay replay <request_id> [--target URL] [--server URL]
```

**Arguments:**

| Argument     | Description                                             |
|--------------|---------------------------------------------------------|
| `request_id` | The ID of the request to replay (required)              |

**Options:**

| Option          | Default                 | Description                         |
|-----------------|-------------------------|-------------------------------------|
| `--target`, `-t` | —                      | Override the target URL for this replay |
| `--server`, `-s` | `http://localhost:8000` | Relay server URL                    |

**Example:**
```bash
hookrelay replay abc123
hookrelay replay abc123 --target http://localhost:5000/debug
```

## `hookrelay bin`

Manage webhook capture bins (v1.6.0+): persistent, webhook.site-style test
endpoints that capture every request sent to their public URL.

```bash
hookrelay bin create [--description TEXT]
hookrelay bin list
hookrelay bin inspect <bin_id>
hookrelay bin forward <request_id> --to <url>
```

**Subcommands:**

| Command | Description |
|---------|-------------|
| `create` | Create a bin; prints its public capture URL and bin id |
| `list` | List all bins (id, created at, URL, description) |
| `inspect <bin_id>` | Show bin details and its captured requests (prints request ids) |
| `forward <request_id> --to <url>` | Re-send a captured request to a target URL (SSRF-guarded) |

**Arguments:**

| Argument | Description |
|----------|-------------|
| `bin_id` | The bin id printed by `hookrelay bin create` |
| `request_id` | The captured request id printed by `hookrelay bin inspect` — the same convention as `hookrelay replay <request_id>` |

**Options:**

| Option | Description |
|--------|-------------|
| `--description`, `-d` | Optional bin description for `create` |
| `--to` | Target URL for `forward` (required) |

**Example:**
```bash
hookrelay bin create --description "stripe tests"
hookrelay bin list
hookrelay bin inspect 002e2150bc5848169b05b0e451a574cb
hookrelay bin forward f0417633a5a043bf9daaf61e95ef843a --to https://example.com/webhook
```

`bin forward` validates every target with the SSRF guard before sending; a
blocked target (private IP, system port, disallowed protocol) exits non-zero
with the guard's reason on stderr. Full REST API and dashboard reference:
[`docs/capture-bins-1.6.md`](capture-bins-1.6.md).

## `hookrelay serve`

Start the Hookrelay FastAPI server with Web Dashboard UI.

```bash
hookrelay serve [--host HOST] [--port PORT] [--reload]
```

**Options:**

| Option     | Default    | Description                         |
|------------|------------|-------------------------------------|
| `--host`   | `0.0.0.0`  | Host to bind the server to          |
| `--port`, `-p` | `8000` | Port to bind the server to          |
| `--reload` | —          | Enable auto-reload (development mode) |

The server mounts:
- **Web Dashboard** at `http://localhost:8000/dashboard/`
- **Health check** at `http://localhost:8000/health`
- **Webhook ingestion** at `POST http://localhost:8000/webhook/{channel}`
- **Bin capture endpoint** at `GET/POST/PUT/PATCH/DELETE http://localhost:8000/bin/{bin_id}` (v1.6.0+, public)
- **Bins dashboard** at `http://localhost:8000/dashboard/bins` (v1.6.0+)
- **Alerts API** at `/api/alerts/rules`, `/api/alerts/notifiers`, `/api/alerts/status`, `/api/alerts/history` (v1.7.0)
- **Alerts dashboard** at `http://localhost:8000/dashboard/alerts` (v1.7.0)
- **Insights API** at `/api/insights/endpoints`, `/api/insights/timeseries` (v1.7.0)
- **Insights dashboard** at `http://localhost:8000/dashboard/insights` (v1.7.0)
- **Transformations API** at `/api/v1/transformations` (v1.8.0)
- **Destinations API** at `/api/v1/destinations` (v1.8.0)
- **Transformations + Destinations dashboard tabs** at `http://localhost:8000/dashboard/` (v1.8.0, Next.js frontend)
- **Relay WebSocket** at `ws://localhost:8000/ws/{channel}`
- **History API** at `GET http://localhost:8000/api/history`
- **Replay API** at `POST http://localhost:8000/api/replay/{request_id}`
- **Live monitoring WebSocket** at `ws://localhost:8000/dashboard/ws/live`

**Example:**
```bash
hookrelay serve
hookrelay serve --host 127.0.0.1 --port 9000
hookrelay serve --port 8000 --reload
```

## `hookrelay status`

Check the relay server health and version.

```bash
hookrelay status [--server URL]
```

**Example:**
```bash
hookrelay status
hookrelay status --server https://relay.example.com
```

## `hookrelay delivery`

Inspect outbound deliveries (see `docs/api-reference-1.5.md`):

```bash
hookrelay delivery list [--status STATUS] [--endpoint-id ID] [--limit N]
hookrelay delivery status <delivery_id>
```

## `hookrelay dlq`

Inspect and requeue dead-letter entries:

```bash
hookrelay dlq list [--endpoint-id ID] [--limit N]
hookrelay dlq requeue <entry_id>
```

## `hookrelay alerts`

Manage failure alert rules (v1.7.0). Rules are evaluated by the server's
background loop (~60s) over rolling windows of stored delivery history;
see [`docs/alerting.md`](alerting.md).

```bash
hookrelay alerts list
hookrelay alerts create <name> [options]
hookrelay alerts delete <rule_id>
```

**Options for `create`:**

| Option | Default | Description |
|--------|---------|-------------|
| `--scope`, `-s` | `all` | `all` (every endpoint) or `endpoint` |
| `--endpoint-id`, `-e` | — | Endpoint filter (required when `--scope endpoint`) |
| `--metric`, `-m` | `success_rate_below` | `success_rate_below` \| `consecutive_failures` \| `dlq_depth_above` |
| `--threshold`, `-t` | — | Crossing threshold (required) |
| `--window-minutes`, `-w` | `15` | Rolling evaluation window |
| `--cooldown-minutes`, `-c` | `15` | Minimum time between two fires |
| `--notifier`, `-n` | — | Notifier id to fan out to (repeatable) |

**Examples:**
```bash
hookrelay alerts list
hookrelay alerts create checkout-success --metric success_rate_below --threshold 0.9 --window-minutes 60
hookrelay alerts create billing-dlq --metric dlq_depth_above --threshold 5 --notifier slack-1
hookrelay alerts delete 8ee685a4e8bb4e8abca4aa3157099d34
```

Rules are printed as JSON; invalid values exit 1 with the validation
message on stderr (`Error: success_rate_below threshold must be in (0, 1]`).

## `hookrelay insights`

Query delivery insights (v1.7.0): per-endpoint stats and bucketed time
series, printed as JSON. See [`docs/insights-api.md`](insights-api.md).

```bash
hookrelay insights endpoints [--window 24h]
hookrelay insights timeseries [--metric deliveries] [--window 24h] [--bucket hourly]
```

**Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `--window`, `-w` | `24h` | Rolling window: `15m`, `1h`, `24h`, `7d` |
| `--metric`, `-m` | `deliveries` | `deliveries` \| `success_rate` \| `latency_p95` (timeseries only) |
| `--bucket`, `-b` | `hourly` | Bucket size: `hourly`, `daily` (timeseries only) |

**Examples:**
```bash
hookrelay insights endpoints --window 7d
hookrelay insights timeseries --metric success_rate --window 24h --bucket hourly
```

Invalid values exit 1, e.g. `Error: window must be one of 15m, 1h, 24h, 7d`.

## `hookrelay transform`

Test and preview payload transformations (v1.8.0). Applies a JQ-style filter
expression to a JSON payload file and prints the transformed result. See
[`docs/transformations.md`](transformations.md).

```
hookrelay transform test <filter> <payload.json>
```

**Example:**
```bash
hookrelay transform test ".data.currency |= uppercase" payload.json
```

## `hookrelay destination`

Manage multi-destination forwarding targets per capture bin (v1.8.0). See
[`docs/destinations.md`](destinations.md).

```
hookrelay destination add <bin_id> <url> [options]
hookrelay destination list <bin_id>
hookrelay destination delete <destination_id>
```

**Options for `add`:**

| Option | Description |
|---|---|
| `--transform ID` | Transformation rule ID applied before forwarding |
| `--signing-algorithm ALGO` | Signing algorithm (`svix`/`hookdeck`/`github`/`custom`) |
| `--signing-secret SECRET` | Signing secret (paired with `--signing-algorithm`) |
| `--header K=V` | Extra header to attach (repeatable) |
| `--weight N` | Weight for `weighted` delivery mode (default 1) |
| `--delivery-mode MODE` | `broadcast` (default), `round_robin`, or `weighted` |
| `--enabled/--disabled` | Enable/disable the destination (default enabled) |

**Example:**
```bash
hookrelay destination add bin-checkout https://api.acme.com/hook \
  --transform cc3ce48215b54c35a24c28b1d0f70e2d \
  --signing-algorithm github --signing-secret whsec_checkout \
  --header "X-Source=hookrelay"

hookrelay destination list bin-checkout
hookrelay destination delete 6c6b8a85...
```

## Authentication environment variable

`HOOKRELAY_API_TOKEN` enables access protection on the server and supplies the Bearer token for forwarding clients. It is intentionally not accepted as a command-line option, which reduces accidental disclosure through shell history and process listings.

## `hookrelay data backup`

Creates a consistent SQLite backup and JSON checksum manifest.

```bash
hookrelay data backup --db-path ./webhooks.db --destination ./backups
```

## `hookrelay data restore`

Verifies a backup manifest, SHA-256 checksum, byte size, and SQLite integrity before atomic restore. Run while the Hookrelay server is stopped.

```bash
hookrelay data restore ./backups/hookrelay-...json --db-path ./webhooks.db
```

An existing destination is preserved as `<database>.pre_restore`.

## `hookrelay data verify-audit`

Verifies the complete tamper-evident audit hash chain.

```bash
hookrelay data verify-audit --db-path ./webhooks.db
```

## Audit checkpoint environment variable

`HOOKRELAY_AUDIT_SIGNING_KEY` enables HMAC-SHA256 audit checkpoints. Use a long random secret that is different from `HOOKRELAY_API_TOKEN`. Store returned checkpoint JSON outside the database and ideally outside the Hookrelay host.

## Encrypted backup environment variable

Set `HOOKRELAY_BACKUP_ENCRYPTION_KEY` to encrypt newly created backup database files with AES-256-GCM. Set the same value during restore or content inspection. The manifest stays readable; the database file uses `.db.enc`.

```bash
export HOOKRELAY_BACKUP_ENCRYPTION_KEY="long-random-secret"
hookrelay data backup --db-path ./webhooks.db --destination ./backups
hookrelay data restore ./backups/hookrelay-...json --db-path ./restored.db
```
