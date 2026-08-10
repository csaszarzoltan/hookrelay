# Hookrelay 1.8 Payload Transformations

## Goal

Rewrite an inbound webhook payload before it is forwarded to a downstream
destination. A **transformation rule** is a named, ordered list of JQ-style
filter expressions that run against the JSON payload at delivery time; the
same engine powers the dashboard builder's live preview and the
`hookrelay transform test` CLI.

Transformations are stored in SQLite (`transformations` table) and can be
attached to any number of destinations (see
[destinations.md](destinations.md)). No new environment variables are
required.

## Quick start

```bash
# 1. Create a transformation rule (POST /api/v1/transformations)
curl -s -X POST http://localhost:8000/api/v1/transformations \
     -H "Content-Type: application/json" \
     -d '{
       "name": "scrub-and-normalize",
       "filters": [
         ".data.currency |= uppercase",
         ".data.amount :: integer",
         ".sent_at = timestamp",
         "del(.token)"
       ]
     }'
```

```json
{
  "transform_id": "cc3ce48215b54c35a24c28b1d0f70e2d",
  "name": "scrub-and-normalize",
  "filters": [".data.currency |= uppercase", ".data.amount :: integer", ".sent_at = timestamp", "del(.token)"],
  "created_at": "2026-08-10T15:24:28.977516+00:00",
  "updated_at": "2026-08-10T15:24:28.977516+00:00"
}
```

```bash
# 2. Preview the result against a sample payload (no server needed)
hookrelay transform test ".data.currency |= uppercase" payload.json
```

```bash
# 3. Attach the rule to a destination so it runs before every forward
curl -s -X POST http://localhost:8000/api/v1/destinations \
     -H "Content-Type: application/json" \
     -d '{
       "bin_id": "bin-checkout",
       "url": "https://api.acme.com/hook",
       "transform_id": "cc3ce48215b54c35a24c28b1d0f70e2d"
     }'
```

A runnable end-to-end example (no server required) is at
[`../examples/transforms_routing.py`](../examples/transforms_routing.py):

```bash
python examples/transforms_routing.py
```

## Filter syntax

A filter list is an ordered list of strings. Each string may contain one or
more **statements** separated by `|` (pipes). Statements run top to bottom
against the payload; every statement sees the output of the previous one.

| Statement | Meaning | Example |
|---|---|---|
| `.` | Identity (no-op) | `.` |
| `.field = <json>` | Set or add a field to a literal value | `.env = "prod"`, `.retries = 3`, `.flag = true` |
| `del(.field)` | Remove a field | `del(.token)` |
| `.new = .old` | Rename a field (moves the value, deletes the source) | `.user_id = .id` |
| `.field |= <builtin>` | Apply a built-in to a field's current value | `.data.currency |= uppercase` |
| `.field = <builtin>` | Assign a generated value (timestamp/uuid/hash) | `.sent_at = timestamp` |
| `.field :: <type>` | Convert a field's type | `.data.amount :: integer` |

Dotted paths address nested fields: `.data.currency` reads/sets
`payload["data"]["currency"]`. Missing intermediate objects are created on
set; `del()` on a missing field is a no-op.

### Type conversions

`.field :: <type>` supports `integer`/`int`, `string`/`str`,
`float`/`number`, and `bool`/`boolean`. String→boolean coercion accepts
`1`, `true`, `yes`, `on` (case-insensitive) as true.

### Literal values on the right-hand side

`.field = <value>` accepts any JSON literal (`"string"`, `42`, `3.14`,
`true`, `false`, `null`, `{...}`, `[...]`), the bare keyword `now` (current
ISO-8601 UTC timestamp), and bare quoted strings. Unquoted dotted tokens
that match an existing field path are treated as a **rename** (`.new = .old`).

## Built-in functions

| Built-in | Statement form | Behaviour |
|---|---|---|
| `uppercase` | `.field |= uppercase` | Uppercase the field's string value |
| `lowercase` | `.field |= lowercase` | Lowercase the field's string value |
| `timestamp` | `.field = timestamp` | Replace with the current ISO-8601 UTC timestamp |
| `uuid` | `.field = uuid` | Replace with a fresh UUID v4 string (36 chars) |
| `hash` | `.field = hash` | Replace with the hex SHA-256 digest of the field's string form |
| `mask_secrets` | `.field |= mask_secrets` | Mask the value for logs/previews: keeps first 2 and last 2 chars, stars the middle (`sk_live_1234567890abc` → `sk***********bc`); values ≤ 4 chars become `***` |

The dashboard builder offers the same functions as clickable **builtin
chips**, inserting the statement snippet into the filter editor.

## Preview

There is no server-side preview endpoint; preview is available three ways:

- **Dashboard** — the Transformations tab renders a live preview as you
  type. The preview is computed **client-side** in TypeScript
  (`frontend/lib/api.ts` `previewTransformation`), mirroring the Python
  engine exactly for the documented sub-language; the backend engine remains
  the source of truth at delivery time.
- **CLI** — `hookrelay transform test <filter> <payload.json>` loads the
  payload file, applies the filter, and prints the result as JSON.
- **Python** — `preview_transformation(filters, payload)` returns the
  transformed dict without persisting anything:

```python
from hookrelay.transforms.engine import preview_transformation

result = preview_transformation(
    [".data.currency |= uppercase", "del(.token)"],
    {"data": {"currency": "usd"}, "token": "sk_live_x"},
)
# {'data': {'currency': 'USD'}}
```

## Transformation rules REST API

All `/api/v1/transformations` endpoints require the Bearer token when
`HOOKRELAY_API_TOKEN` is configured (see
[Access protection](../README.md#optional-access-protection)).

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/transformations` | Create a rule (`{"name": "...", "filters": [...]}`) → `201` with the record |
| `GET` | `/api/v1/transformations` | List all rules, newest first |
| `GET` | `/api/v1/transformations/{transform_id}` | Fetch one rule; `404` if unknown |
| `PUT` | `/api/v1/transformations/{transform_id}` | Update `name` and/or `filters`; `404` if unknown, `400` if no fields |
| `DELETE` | `/api/v1/transformations/{transform_id}` | Delete a rule → `204`; `404` if unknown |

Validation (all return `422 {"detail": "..."}`):

- `name` must be non-empty and ≤ 120 characters
- `filters` must be a list of strings

## CLI

| Command | Description |
|---|---|
| `hookrelay transform test <filter> <payload.json>` | Apply a JQ-style filter to a JSON payload file and print the result |

## Python API

`hookrelay.transforms.engine` is the stable programmatic interface:

| Member | Behaviour |
|---|---|
| `TransformationEngine(filters)` | Build an engine from an ordered filter list |
| `engine.apply(payload)` | Apply all filters; returns a new dict (never mutates input) |
| `engine.preview(payload)` | Dry-run alias of `apply` |
| `engine.add_field(path, value)` | Register a literal field set |
| `engine.remove_field(path)` | Register a field removal |
| `engine.rename_field(old, new)` | Register a field rename |
| `engine.convert_type(path, type)` | Register a type conversion |
| `apply_builtins(payload, fn, path)` | Apply one named built-in to one dotted path |
| `preview_transformation(filters, payload)` | One-shot: engine + apply |

`hookrelay.transforms.store.TransformationStore(storage)` provides the
SQLite-backed CRUD (`create`, `get`, `list`, `update`, `delete`) used by the
REST API and CLI. See
[`../examples/transforms_routing.py`](../examples/transforms_routing.py).

## Dashboard Transformations tab

**URL:** `/dashboard/` → *Transformations* tab (dashboard page served by the
Next.js frontend at `/dashboard`).

- **Rule list** — every saved rule with its name and filter count.
- **Builder** — create/edit a rule: name input, filter editor (one input per
  filter string, add/remove rows), and builtin chips that insert statement
  snippets.
- **Live preview** — a test payload textarea and the transformed output side
  by side, recomputed on every keystroke (client-side engine mirror).
- **CRUD** — save (create/update), delete; the same rules the REST API and
  CLI manage.
