# Hookrelay 1.0 Data Requirements and Implementation Report

## Scope

This release implements the next data-foundation sequence selected after Hookrelay 0.9.1:

1. Versioned database migrations
2. Versioned WebSocket/event envelope
3. Connection registry
4. Canonical request-query model
5. Append-only audit model

## Requirements

### DR-01: Explicit database schema version

- **Priority:** Must have
- **Requirement:** Every database shall expose an ordered migration history and current schema version.
- **User value:** Safe upgrades without losing captured requests.
- **Acceptance criteria:** Legacy request rows survive initialization; migrations 1 through 3 are recorded exactly once; a database newer than the application is rejected.

### DR-02: Durable event envelope

- **Priority:** Must have
- **Requirement:** Realtime events shall use a versioned envelope containing event ID, event type, timestamp, correlation ID, data, and monotonic cursor.
- **User value:** Live monitoring can recover events missed during disconnects.
- **Acceptance criteria:** Event IDs are unique; cursors increase monotonically; events can be queried after a cursor; unknown future event types can be ignored by clients.

### DR-03: Connection metadata registry

- **Priority:** Must have
- **Requirement:** Relay connections shall register a session ID, channel, target, client version, capabilities, connected time, and heartbeat.
- **User value:** Users can understand system readiness and stale clients.
- **Acceptance criteria:** Registration returns a session ID; heartbeat refreshes state; stale state is computed from a configurable timeout; disconnect removes metadata.

### DR-04: Canonical request query

- **Priority:** Must have
- **Requirement:** Search, filters, ordering, limit, and cursor shall be represented by one versioned validated model.
- **User value:** Dashboard, API, saved views, and future tooling use consistent semantics.
- **Acceptance criteria:** Invalid methods, status values, limits, versions, and cursors are rejected; results use deterministic descending ordering; opaque cursor pagination has no duplicate records.

### DR-05: Append-only audit model

- **Priority:** Must have
- **Requirement:** Security-sensitive and data-changing actions shall create immutable audit records.
- **User value:** Operators can investigate what happened without exposing secrets.
- **Acceptance criteria:** Records include action, actor, object, outcome, correlation ID, details, and timestamp; nested sensitive details are redacted; no update API exists.

### DR-06: Data observability APIs

- **Priority:** Should have
- **Requirement:** Supported schema versions, connections, durable events, request queries, and audit records shall be accessible through protected APIs.
- **Acceptance criteria:** Each API validates limits and cursors and uses existing optional token protection.

## Implementation summary

### New modules

- `hookrelay/migrations.py`: ordered schema migrations and forward-version protection.
- `hookrelay/events.py`: canonical event-envelope constructor.
- `hookrelay/query.py`: validated request-query schema and opaque cursors.

### Extended modules

- `storage.py`: migration visibility, durable events, canonical queries, and audit persistence.
- `relay.py`: metadata-rich connection registry and stale-state calculation.
- `server.py`: event persistence, reconnect API, connection API, query API, audit API, and schema introspection.
- `client.py`: target, version, and capability metadata in the WebSocket handshake.
- `dashboard.js`: cursor persistence and missed-event recovery after reconnect.

## Data contracts

### Event envelope version 1

```json
{
  "schema_version": 1,
  "event_id": "unique-id",
  "event_type": "webhook.received",
  "timestamp": "RFC-3339 timestamp",
  "correlation_id": "request-id",
  "cursor": 42,
  "data": {}
}
```

### Request query version 1

The model supports text, channel, methods, path, validation status, delivery status, time range, replay state, descending received-time ordering, limit, and opaque cursor.

### Audit record

Audit records contain no raw authentication or cookie values. Keys such as authorization, cookie, token, API key, and password are recursively replaced with `••••••••`.

## Reliability and compatibility decisions

- Migrations are idempotent and applied in order.
- Existing request data is not rewritten during the 1.0 migration.
- A newer database schema is rejected to prevent accidental downgrade corruption.
- Event cursors are database-generated integers.
- Request cursors are opaque URL-safe values based on received time and request ID.
- Connection state remains process-local; distributed multi-worker coordination is deferred.
- Audit records are append-only at the application API level.

## Testing

Six TDD-first acceptance tests cover:

1. Legacy database migration and data preservation
2. Event-envelope persistence and cursor traversal
3. Connection metadata, heartbeat, and stale state
4. Canonical request query and cursor pagination
5. Audit redaction and append-only behavior
6. Data API integration

Final validation: **483 passed, 0 failed**. One existing non-failing Pydantic warning remains for `_ValidateRequest.schema`.

## Deferred opportunities

- Migration backup creation and operator-controlled rollback command
- Shared connection registry for multi-worker deployments
- Audit actor identity beyond local/shared-token sessions
- Audit retention and cryptographic tamper evidence
- Query execution plans and indexed delivery/validation status columns for very large datasets
