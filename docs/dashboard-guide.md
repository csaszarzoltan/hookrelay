# Dashboard Guide

The Hookrelay Web Dashboard provides a browser-based UI for monitoring, inspecting, and replaying webhooks. It's served by the same FastAPI server that handles webhook ingestion and relay.

## Starting the Dashboard

The dashboard is bundled with the relay server. Start it with:

```bash
hookrelay serve
```

This launches the server on `http://0.0.0.0:8000`. Open **http://localhost:8000/dashboard/** in your browser.

### Options

```bash
hookrelay serve --host 127.0.0.1 --port 9000
```

| Option     | Default    | Description                              |
|------------|------------|------------------------------------------|
| `--host`   | `0.0.0.0`  | Host to bind the server to               |
| `--port`, `-p` | `8000` | Port to bind the server to               |
| `--reload` | —          | Enable auto-reload (development mode)    |

---

## Navigation

The dashboard has a sidebar with two main sections:

### 1. Live Feed

**URL:** `/dashboard/`

The Live Feed page is the default landing page. It shows:

- **Total Requests** — a counter of all webhooks received since the server started
- **Recent Requests Table** — the last 5 received requests with columns for timestamp, HTTP method, channel, path, and source IP
- **Connection Status** — a badge in the top-right indicating WebSocket connection state

The page maintains a persistent WebSocket connection to `/dashboard/ws/live`. When new webhooks arrive, they are:

1. Appended to the table in real-time (most recent first)
2. Capped at 50 rows (oldest are removed)

Each row offers two actions:
- **Inspect** — opens the Payload Inspector for that request
- **Replay** — opens the Request Replay page

### 2. History Browser

**URL:** `/dashboard/history`

The History Browser provides a paginated, filterable view of all stored webhook requests.

#### Filters

Use the filter bar at the top to narrow results:

| Filter    | Type         | Description                     |
|-----------|--------------|---------------------------------|
| Channel   | Text input   | Filter by channel name          |
| Method    | Dropdown     | All, GET, POST, PUT, PATCH, DELETE |
| Path      | Text input   | Filter by path pattern          |

Click **Filter** to apply, **Clear** to reset.

#### Results Table

The table shows the same columns as the Live Feed plus a **Replayed** count. Pagination is controlled via `limit` and `offset` query parameters (default: 20 results, offset 0).

Each row has **Inspect** and **Replay** action buttons.

---

## Payload Inspector

**URL:** `/dashboard/inspect/{request_id}`

The Inspector page shows the full detail of a single webhook request in a structured card layout:

### Metadata Card
- Request ID
- HTTP Method (badge)
- Channel
- Source IP
- Received timestamp
- Path
- Replayed count

### Query Parameters Card
Only shown when the request has query parameters. Displays a key-value table.

### Headers Card
All HTTP headers in a scrollable table. Header names are rendered as `<code>`.

### Body Card
The raw request body, syntax-highlighted in a scrollable `<pre>` block. Supports text bodies decoded as UTF-8; binary payloads are flagged.

### Replay Button
A **Replay Request** button at the bottom of the page links to the replay page for this request.

---

## Request Replay

**URL:** `/dashboard/replay/{request_id}`

The Replay page lets you re-send a stored webhook with one click.

### How It Works

1. The page loads the stored request metadata (method, channel, path, replay count)
2. Click **Replay Now** to send a `POST /api/replay/{request_id}` request
3. The server replays the original request by looking up a connected relay client on the same channel
4. Results are displayed inline as a JSON response

### Possible Outcomes

| Outcome | Status | Meaning |
|---------|--------|---------|
| Replayed successfully | ✅ | The request was forwarded to a connected client |
| No connected client | ⚠️ | No relay client is connected on that channel — the request was stored but not delivered |
| Not found | ❌ | The request ID doesn't exist in storage |

### From the Inspector

You can also navigate directly to the Replay page by clicking **Replay Request** at the bottom of the Payload Inspector.

---

## Live Monitoring WebSocket

**Endpoint:** `ws://localhost:8000/dashboard/ws/live`

The Live Feed uses this WebSocket internally, but you can connect programmatically for custom integrations.

### Message Format

**Inbound (server → client):**

```json
{
  "type": "webhook",
  "data": {
    "request_id": "abc123",
    "method": "POST",
    "channel": "mychannel",
    "path": "/webhook",
    "source_ip": "203.0.113.1",
    "headers": {"content-type": "application/json"},
    "query_params": {},
    "body": "{\"event\": \"order.created\"}",
    "received_at": "2026-07-29T12:00:00"
  }
}
```

- **`webhook`** — a new webhook was received and stored
- **`replay`** — a request was replayed

**Outbound (client → server):**

```json
{"type": "ping"}
```

The server responds with:

```json
{"type": "pong"}
```

### Auto-Reconnect

The dashboard client automatically reconnects after a 3-second delay if the WebSocket connection drops.

---

## Health Check

**URL:** `GET http://localhost:8000/health`

Returns server status in JSON:

```json
{
  "status": "ok",
  "version": "0.2.0",
  "uptime": 123.45,
  "total_requests": 42
}
```

---

## API Endpoints (Dashboard-relevant)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/dashboard/` | Live Feed page |
| `GET` | `/dashboard/history` | History Browser page |
| `GET` | `/dashboard/inspect/{id}` | Payload Inspector page |
| `GET` | `/dashboard/replay/{id}` | Request Replay page |
| `GET` | `/dashboard/static/{file}` | Static assets (CSS, JS) |
| `WS` | `/dashboard/ws/live` | Live monitoring WebSocket |
| `POST` | `/api/replay/{id}` | Trigger a request replay |
| `GET` | `/api/history` | History data (JSON) |
| `GET` | `/api/history/search?q=...` | FTS5 full-text search |
| `GET` | `/health` | Server health check |

---

## Troubleshooting

### Dashboard loads unstyled (no CSS/JS)

Ensure you're running v0.2.0+ and the server was started with `hookrelay serve`. The static files are mounted automatically. If CSS and JS return 404, check that `src/hookrelay/dashboard/static/` exists with `style.css` and `dashboard.js`.

### Live Feed shows "Disconnected"

- Check that the server is running on the expected port
- Verify the WebSocket endpoint: `ws://localhost:8000/dashboard/ws/live`
- Browser console may show connection errors — check for CORS or network issues
- The client auto-reconnects every 3 seconds

### No requests appear in the dashboard

- Confirm webhooks are reaching the server: `curl http://localhost:8000/health` should show `total_requests` increasing
- Check the History Browser — it shows all stored requests regardless of WebSocket connection
- Verify the correct channel is being used


### Response diagnostics and retention (v0.8.0+)

After a forwarding client sends a webhook to the local target, it reports the outcome to Hookrelay. The request inspector can display:

- Delivery, target-error, or transport-error status
- Local HTTP response status
- Forwarding duration
- Redacted response headers
- Up to 16 KiB of response-body text
- A visible truncation marker when the response exceeded the limit

Open **Settings** to configure request retention. A saved policy is applied at application startup, or it can be executed immediately with **Delete expired requests now**. Cleanup removes associated validation and delivery diagnostic records.

### Storage health and automatic backups (v1.2.0+)

The Settings page displays database integrity, schema version, database and WAL sizes, request count, and audit-chain status. The Automatic backups section allows operators to enable a persistent policy, select an interval, choose how many complete backup bundles to retain, save the policy, and create a verified backup immediately.

The policy is evaluated by the backup-run API. Use an external scheduler for unattended operation; Hookrelay intentionally avoids an implicit background scheduler in the web process.

### Backup center (v1.4.0+)

Use the Backups navigation item to open the recovery-point catalog. Every complete bundle is verified before display. Select **Inspect restore preview** to review schema, checksum, SQLite integrity, and record counts. **Create backup** makes a new verified bundle. **Delete bundle** requires confirmation and removes the manifest/database pair.

Restore is deliberately offline. Stop the server and use `hookrelay data restore` after validating the preview.

### Encrypted recovery points (v1.5.0+)

When `HOOKRELAY_BACKUP_ENCRYPTION_KEY` is configured, Backup center creation produces AES-256-GCM encrypted bundles. Cards show **Encrypted**. Without the key, Hookrelay can verify the encrypted artifact checksum but labels content preview as key-required. With the key configured, Inspect restore preview securely decrypts to a temporary file, validates SQLite integrity and counts records, then deletes the temporary file.
