# Hookrelay 1.8 Multi-Destination Routing

## Goal

Fan one inbound webhook out to **multiple destinations** — targets attached
to a capture bin, each with its own transformation rule, signing config,
headers, retry policy, and delivery mode. A *destination* is a forwarding
target with an id; a *router* (`MultiDestinationRouter`) picks which
destinations receive a payload based on the delivery mode:
**broadcast**, **round-robin**, or **weighted**.

Destinations are stored in SQLite (`destinations` table, indexed by
`bin_id`) and managed through the REST API, the `hookrelay destination`
CLI group, and the dashboard's Destinations tab. No new environment
variables are required.

## Quick start

```bash
# 1. Create a transformation (optional per-destination payload rewrite)
curl -s -X POST http://localhost:8000/api/v1/transformations \
     -H "Content-Type: application/json" \
     -d '{"name": "add-env", "filters": [".env = \"prod\""]}'

# 2. Create destinations for a bin — each can transform, sign, add headers,
#    and carry its own retry policy
curl -s -X POST http://localhost:8000/api/v1/destinations \
     -H "Content-Type: application/json" \
     -d '{
       "bin_id": "bin-checkout",
       "url": "https://api.acme.com/hook",
       "transform_id": "<transform_id>",
       "signing_config": {"algorithm": "github", "secret": "whsec_checkout"},
       "headers": {"X-Source": "hookrelay"},
       "retry_policy": {"max_retries": 3, "base_delay_seconds": 1.0}
     }'

# 3. Same bin, second destination with weighted delivery
curl -s -X POST http://localhost:8000/api/v1/destinations \
     -H "Content-Type: application/json" \
     -d '{
       "bin_id": "bin-checkout",
       "url": "https://canary.acme.com/hook",
       "delivery_mode": "weighted",
       "weight": 1
     }'
```

A runnable end-to-end example (no server required) is at
[`../examples/transforms_routing.py`](../examples/transforms_routing.py).

## Delivery modes

| Mode | Behaviour |
|---|---|
| `broadcast` (default) | Deliver to **every enabled** destination of the bin |
| `round_robin` | Deliver to **exactly one** destination, cycling through them in order per event |
| `weighted` | Deliver to **exactly one** destination, drawn randomly proportional to each destination's `weight` (default `1`) |

Each destination stores a `delivery_mode` that is used when the bin's router
has no explicit mode override; the router constructor takes the mode that
applies for the fan-out. Disabled destinations (`enabled: false`) are
excluded from all modes. In round-robin and weighted modes, one event is
delivered to exactly one destination — use broadcast when every destination
must receive every event.

## Destination configuration

| Field | Type | Default | Meaning |
|---|---|---|---|
| `bin_id` | string | — | Capture bin the destination belongs to (required) |
| `url` | string | — | Target URL for forwarded webhooks (required, non-empty) |
| `transform_id` | string \| null | `null` | Transformation rule applied to the payload before forwarding |
| `signing_config` | object | `{}` | Outgoing signing config (`algorithm`, `secret`, …) — see [signing.md](signing.md) |
| `headers` | object | `{}` | Extra headers attached to every forwarded request |
| `retry_policy` | object | `{}` | Per-destination retry configuration (see below) |
| `enabled` | bool | `true` | When `false` the destination is excluded from routing |
| `weight` | int | `1` | Weight for `weighted` mode (must be ≥ 1) |
| `delivery_mode` | string | `broadcast` | `broadcast` \| `round_robin` \| `weighted` |

### Retry policies

`retry_policy` mirrors the durable retry-queue policy from v1.5.0
(`hookrelay.config.retry_policy.RetryPolicy`, persisted per delivery):

| Field | Default | Meaning |
|---|---|---|
| `max_retries` | — | Max delivery attempts before the message is failed |
| `base_delay_seconds` | 1.0 | Base delay for the first retry |
| `backoff_factor` | 2.0 | Exponential multiplier per attempt |
| `max_backoff_seconds` | 3600.0 | Cap on the per-attempt delay |
| `jitter` | false | Randomize the backoff delay (deterministic unless enabled) |

## Destinations REST API

All `/api/v1/destinations` endpoints require the Bearer token when
`HOOKRELAY_API_TOKEN` is configured (see
[Access protection](../README.md#optional-access-protection)).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/destinations` | Create a destination → `201` with the record |
| `GET` | `/api/v1/destinations` | List all destinations; `?bin_id=<id>` filters by bin |
| `GET` | `/api/v1/destinations/{destination_id}` | Fetch one destination; `404` if unknown |
| `PUT` | `/api/v1/destinations/{destination_id}` | Update any configurable field; `404` if unknown, `400` if no fields |
| `DELETE` | `/api/v1/destinations/{destination_id}` | Delete a destination → `204`; `404` if unknown |

Validation (all return `422 {"detail": "..."}`): non-empty `bin_id`/`url`,
`weight >= 1`, and `delivery_mode` one of `broadcast`, `round_robin`,
`weighted`.

The record includes delivery counters updated by the pipeline:
`delivered_count` and `failed_count` (incrementable via
`DestinationStore.increment_delivered` / `increment_failed`), consumed by
the Insights API.

## CLI

`hookrelay destination` manages destinations from the terminal (no GUI
required):

| Command | Description |
|---|---|
| `hookrelay destination add <bin_id> <url> [--transform ID] [--signing-algorithm ALGO] [--signing-secret SECRET] [--header KEY=VALUE]... [--weight N] [--delivery-mode MODE] [--enabled/--disabled]` | Add a destination to a bin and print its JSON record |
| `hookrelay destination list <bin_id>` | List all destinations for a bin |
| `hookrelay destination delete <destination_id>` | Delete a destination |

```bash
hookrelay destination add bin-checkout https://api.acme.com/hook \
  --transform cc3ce48215b54c35a24c28b1d0f70e2d \
  --signing-algorithm github --signing-secret whsec_checkout \
  --header "X-Source=hookrelay"
```

Passing both `--signing-algorithm` and `--signing-secret` builds the
`signing_config`; supplying only one of them leaves signing unset.

## Python API

`hookrelay.routing.destination` is the stable programmatic interface:

| Member | Behaviour |
|---|---|
| `DeliveryMode` | Enum: `BROADCAST`, `ROUND_ROBIN`, `WEIGHTED` |
| `Destination(destination_id, bin_id, url, *, transform_id, signing_config, headers, retry_policy, enabled, weight, delivery_mode)` | Immutable-ish forwarding target with `to_dict()` / `from_dict()` round-trip and thread-safe `record_delivered()` / `record_failed()` counters |
| `MultiDestinationRouter(destinations, mode=BROADCAST)` | Fan-out engine |
| `router.route(payload)` | List of `{"destination_id", "url"}` instructions: all enabled destinations (broadcast) or exactly one (round-robin/weighted) |
| `router.next_destination()` | Next destination for round-robin/weighted modes (weighted = random draw proportional to weight) |
| `router.get_delivery_stats()` | `{destination_id: {"delivered": int, "failed": int}}` |

`hookrelay.routing.destination_store.DestinationStore(storage)` provides
the SQLite-backed CRUD (`create`, `get`, `list(bin_id=...)`, `update`,
`delete`, `increment_delivered`, `increment_failed`) used by the REST API
and CLI. See
[`../examples/transforms_routing.py`](../examples/transforms_routing.py).

## Dashboard Destinations tab

**URL:** `/dashboard/` → *Destinations* tab (dashboard page served by the
Next.js frontend at `/dashboard`).

- **Destination manager per bin** — create and edit destinations for a
  capture bin.
- **Signing form** — algorithm selector (svix / hookdeck / github / custom),
  signing key/secret, header name, timestamp header.
- **Retry + headers** — per-destination retry policy fields and extra
  headers.
- **Delivery mode** — broadcast / round-robin / weighted selector.
- **Delivery logs** — per-destination delivery statistics grouped via the
  insights API.
