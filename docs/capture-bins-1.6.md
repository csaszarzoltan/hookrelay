# Hookrelay 1.6 Webhook Capture Bins

## Goal

Give developers a persistent, [webhook.site](https://webhook.site)-style test
endpoint inside hookrelay itself. Create a **bin**, point any webhook sender
at its public URL, and every request — method, headers, body, query params,
source IP, timestamp — is captured and stored, **even when no dashboard or
WebSocket client is connected**. Inspect what arrived, then re-send any
captured request to a target of your choice with one click (SSRF-guarded).

A *bin* is identified by a `bin_id`, which doubles as the webhooks
`channel`, so captured requests automatically inherit hookrelay's existing
persistence, pagination, retention, and audit machinery.

## Quick start

```bash
# 1. Start the server
hookrelay serve

# 2. Create a bin — prints the public capture URL
hookrelay bin create --description "stripe tests"
#   Bin created: http://localhost:8000/bin/<bin_id>
#   Bin ID: <bin_id>

# 3. Point any sender at that URL (POST/GET/PUT/PATCH/DELETE are all captured)
curl -X POST "http://localhost:8000/bin/<bin_id>?src=stripe" \
     -H "Content-Type: application/json" \
     -d '{"event": "invoice.paid", "amount": 4200}'

# 4. Inspect what arrived (prints the captured request ids)
hookrelay bin inspect <bin_id>

# 5. Forward one captured request to any target (SSRF-guarded)
hookrelay bin forward <request_id> --to https://example.com/webhook
```

A runnable end-to-end example (no server needed) is at
[`../examples/capture_bins.py`](../examples/capture_bins.py):

```bash
python examples/capture_bins.py
```

## Public capture endpoint

**`/bin/{bin_id}`** accepts `GET`, `POST`, `PUT`, `PATCH`, and `DELETE`.
Every request is persisted through `BinService` and broadcast to the live
dashboard feed. The endpoint is public in the auth middleware, so external
webhook providers can capture without credentials.

```bash
curl -s -X POST "http://localhost:8000/bin/5765b10f94384fa49aa5f2e412fdfcc6?src=stripe&env=test" \
     -H "Content-Type: application/json" \
     -H "X-Custom: yes" \
     -d '{"event": "invoice.paid", "amount": 4200}'
```

```json
{"request_id":"2604303063164c279050c9756384a374","bin_id":"5765b10f94384fa49aa5f2e412fdfcc6","method":"POST","path":"/"}
```

- Response: `201` with the `request_id`, `bin_id`, `method`, and captured `path`.
- Unknown bin: `404 {"detail": "Bin not found"}`.
- The `source_ip` is taken from `x-real-ip`, falling back to
  `x-forwarded-for`, then the socket peer.
- Captures persist regardless of connected WebSocket clients — the bin id is
  the channel, so `Storage` handles the durability.

## Bin management REST API

All `/api/bins` endpoints require the Bearer token when
`HOOKRELAY_API_TOKEN` is configured (see [Access protection](../README.md#optional-access-protection)).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/bins` | Create a bin (`{"description": "..."}` optional); returns the bin with its public URL |
| `GET` | `/api/bins` | List all bins, newest first |
| `DELETE` | `/api/bins/{bin_id}` | Delete a bin **and all its captured requests** (cascade) |
| `GET` | `/api/bins/{bin_id}/requests` | Paginated request listing (`limit` 1–1000, default 20; `offset` default 0) |
| `GET` | `/api/bins/{bin_id}/requests/{request_id}` | Full payload view of one captured request |
| `POST` | `/api/bins/{bin_id}/requests/{request_id}/forward` | One-click forward to a target URL (`{"target_url": "..."}`) |

### Create

```bash
curl -s -X POST http://localhost:8000/api/bins \
     -H "Content-Type: application/json" \
     -d '{"description": "stripe tests"}'
```

```json
{"bin_id":"5765b10f94384fa49aa5f2e412fdfcc6","url":"http://localhost:8765/bin/5765b10f94384fa49aa5f2e412fdfcc6","created_at":"2026-08-05T12:48:20.969130+00:00","description":"stripe tests","request_count":0}
```

`url` is derived from the request host, so it is reachable from wherever the
server is actually running. The CLI prints the service default
(`http://localhost:8000/...`) instead — use the REST response when the server
listens on another host/port.

### List

```bash
curl -s http://localhost:8000/api/bins
```

```json
[{"bin_id":"5765b10f94384fa49aa5f2e412fdfcc6","url":"http://localhost:8000/bin/5765b10f94384fa49aa5f2e412fdfcc6","created_at":"2026-08-05T12:48:20.969130+00:00","description":"stripe tests","request_count":2}]
```

### Paginated request listing

```bash
curl -s "http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6/requests?limit=20&offset=0"
```

```json
{
  "items": [
    {
      "request_id": "2604303063164c279050c9756384a374",
      "channel": "5765b10f94384fa49aa5f2e412fdfcc6",
      "method": "POST",
      "path": "/",
      "headers": {
        "host": "localhost:8765",
        "user-agent": "curl/8.5.0",
        "accept": "*/*",
        "content-type": "application/json",
        "x-custom": "yes",
        "content-length": "41"
      },
      "body": "{\"event\": \"invoice.paid\", \"amount\": 4200}",
      "query_params": {"src": "stripe", "env": "test"},
      "source_ip": "127.0.0.1",
      "received_at": "2026-08-05T12:48:21.044248+00:00",
      "replayed": 0
    }
  ],
  "total": 2
}
```

Items are newest first. `limit` is clamped to 1–1000; `offset` is clamped to
≥ 0. The `body` is decoded as UTF-8 with lossy replacement for JSON display
(raw bytes are preserved in storage).

### Full payload view

```bash
curl -s "http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6/requests/2604303063164c279050c9756384a374"
```

Returns the same per-item shape as the listing above. Unknown bin →
`404 {"detail": "Bin not found"}`; unknown request →
`404 {"detail": "Request not found"}`.

### Delete

```bash
curl -s -X DELETE http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6 -i | head -1
# HTTP/1.1 204 No Content
```

Deletion cascades to every captured request of the bin.

## One-click forward / replay

`POST /api/bins/{bin_id}/requests/{request_id}/forward` re-sends the captured
method, headers, and body to any target URL:

```bash
curl -s -X POST http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6/requests/2604303063164c279050c9756384a374/forward \
     -H "Content-Type: application/json" \
     -d '{"target_url": "https://example.com/webhook"}'
```

```json
{
  "request_id": "2604303063164c279050c9756384a374",
  "target_url": "https://example.com/webhook",
  "status_code": 405,
  "latency_ms": 78.6,
  "response_body": "<!doctype html><html lang=\"en\">...",
  "error": null
}
```

Behaviour notes (all pinned by regression tests):

- **Off the event loop.** The endpoint is declared as a plain `def`, so
  FastAPI runs it in the threadpool — a slow or hanging target (30 s timeout)
  never stalls capture, dashboard, or live-feed endpoints.
- **Hop-by-hop headers are stripped.** `Host`, `Content-Length`,
  `Connection`, and `Transfer-Encoding` are removed from the replayed headers
  and recomputed by `requests` from the target URL and actual body — replaying
  them would send a stale `Host` (broken virtual-host routing) or a
  `Content-Length` that no longer matches.
- **Byte-exact binary bodies.** The raw stored row is read directly (bypassing
  the lossy UTF-8 decode used for JSON views), so binary payloads replay
  byte-for-byte.
- **Result recording.** Each forward persists a delivery attempt
  (`status_code`, `latency_ms`, `response_body`, or `error` for transport
  failures), visible in the delivery history.
- **Errors.** Unknown request → `404`; SSRF-blocked or malformed target →
  `400 {"error": "<guard reason>"}`.

### SSRF behaviour

Every target passes through `hookrelay.ssrf.validate_target_url` **before any
request is sent**: protocol allowlist (`http`/`https`), private-IP block
(IPv4/IPv6, incl. loopback and link-local), explicit system-port block
(`< 1024`), and a DNS rebinding re-check. A blocked target raises `ValueError`
with the guard's reason:

```bash
curl -s -X POST http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6/requests/2604303063164c279050c9756384a374/forward \
     -H "Content-Type: application/json" \
     -d '{"target_url": "http://127.0.0.1:8080/internal"}'
```

```json
{"error": "Resolved to private IP: 127.0.0.1"}
```

```bash
curl -s -X POST http://localhost:8000/api/bins/5765b10f94384fa49aa5f2e412fdfcc6/requests/2604303063164c279050c9756384a374/forward \
     -H "Content-Type: application/json" \
     -d '{"target_url": "http://example.com:80/webhook"}'
```

```json
{"error": "Port 80 is a system port (< 1024)"}
```

Only explicitly declared ports are checked — default scheme ports
(`https://example.com`) pass the port check and are then subject to the
private-IP and DNS checks. The same guard protects `RetryQueue.enqueue` and
`EndpointConfig.validate` (v1.5.0).

## CLI

`hookrelay bin` manages bins from the terminal (no GUI required):

| Command | Description |
|---|---|
| `hookrelay bin create [--description TEXT]` | Create a bin; prints the public URL and bin id |
| `hookrelay bin list` | List all bins (id, created at, URL, description) |
| `hookrelay bin inspect <bin_id>` | Show bin details and its captured requests |
| `hookrelay bin forward <request_id> --to <url>` | Forward a captured request to a URL (SSRF-guarded) |

`bin forward` takes the **captured request id** — the same convention as
`hookrelay replay <request_id>`. `bin inspect` prints the ids so you can copy
one into `bin forward`.

```bash
$ hookrelay bin create --description "stripe tests"
Bin created: http://localhost:8000/bin/002e2150bc5848169b05b0e451a574cb
Bin ID: 002e2150bc5848169b05b0e451a574cb

$ hookrelay bin list
002e2150bc5848169b05b0e451a574cb  2026-08-05T12:53:20.791927+00:00  http://localhost:8000/bin/002e2150bc5848169b05b0e451a574cb  (stripe tests)

$ hookrelay bin inspect 002e2150bc5848169b05b0e451a574cb
Bin: 002e2150bc5848169b05b0e451a574cb
URL: http://localhost:8000/bin/002e2150bc5848169b05b0e451a574cb
Description: stripe tests
Requests: 1
  2026-08-05T12:53:36.454717+00:00  POST    f0417633a5a043bf9daaf61e95ef843a

$ hookrelay bin forward f0417633a5a043bf9daaf61e95ef843a --to https://example.com/webhook
Forwarded f0417633a5a043bf9daaf61e95ef843a -> https://example.com/webhook
  Status: 405  Latency: 45.2 ms
  Body: <!doctype html><html lang="en">...
```

A blocked target exits non-zero with the guard's reason on stderr:

```bash
$ hookrelay bin forward f0417633a5a043bf9daaf61e95ef843a --to http://127.0.0.1:9999/internal
Error: Resolved to private IP: 127.0.0.1
```

The CLI stores bins in the same database as the server
(`<tempdir>/hookrelay/webhooks.db` by default) and prints the service default
base URL — see the note under [Create](#create).

## Dashboard Bins view

**URL:** `/dashboard/bins`

The Bins page gives you:

- **Create bin** — a form (optional description) that creates a bin and lists
  it in the bin cards below.
- **Copy URL** — each bin card has a copy button for its public capture URL,
  plus a *View requests* link into the REST API.
- **Live request feed** — captured requests stream into the table in
  real-time (time, method, bin, path, source, request id), capped at 100 rows.
  The feed reuses the existing `/dashboard/ws/live` connection manager — no
  polling. Live captures arrive as `bin.capture` messages:

```json
{
  "type": "bin.capture",
  "bin_id": "5765b10f94384fa49aa5f2e412fdfcc6",
  "request_id": "2604303063164c279050c9756384a374",
  "method": "POST",
  "path": "/",
  "source_ip": "127.0.0.1",
  "received_at": "2026-08-05T12:48:21.044248+00:00"
}
```

- **Click-to-forward** — the *Forward* action on a feed row (or
  `?request=<id>&bin=<id>` in the URL) opens the forward panel: type a target
  URL, submit, and the result (`HTTP <status> in <ms>` or the error) appears
  inline.

Like every other dashboard page, `/dashboard/bins` redirects to
`/dashboard/login` when `HOOKRELAY_API_TOKEN` is configured; the capture
endpoint `/bin/...` itself stays public.

## Python API

`hookrelay.bins.service.BinService` drives everything server-side; it is also
the stable interface for programmatic use:

| Method | Behaviour |
|---|---|
| `create_bin(description=None)` | Create a bin; returns a `Bin` (bin_id, url, created_at, description, request_count) |
| `get_bin(bin_id)` | Return the `Bin` or `None` |
| `list_bins()` | All bins, newest first |
| `delete_bin(bin_id)` | Delete a bin and its requests; returns `True` if deleted |
| `capture(bin_id, method, headers, body, query_params, source_ip)` | Persist a request; returns a `CapturedRequest` |
| `list_requests(bin_id, limit=20, offset=0)` | `{"items": [...], "total": N}`, newest first |
| `get_request(bin_id, request_id)` | Full payload dict or `None` |

`hookrelay.bins.forward.forward_captured_request(bin_id, request_id,
target_url, storage, timeout=30.0)` returns a `ForwardResult` (request_id,
target_url, status_code, latency_ms, response_body, error). It raises
`ValueError` when the SSRF guard blocks the target and
`BinRequestNotFoundError` for an unknown request. Data models (`Bin`,
`CapturedRequest`, `ForwardResult`) live in `hookrelay.bins.models`.

See [`../examples/capture_bins.py`](../examples/capture_bins.py) for a
complete, runnable walkthrough — including the SSRF-block path and an
optional `HOOKRELAY_FORWARD_TARGET` env override for a real forward
round-trip.
