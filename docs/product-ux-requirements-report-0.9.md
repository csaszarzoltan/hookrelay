# Hookrelay 0.9.0 Product, UX, and Next-Version Requirements Report

**Review date:** 2026-08-01  
**Reviewed artifact:** `ZipPrompt.md`, opened as a ZIP archive  
**Declared product version:** 0.9.0  
**Method:** Static source, templates, tests, documentation, and executable regression review  
**Important scope note:** No application source was changed during this review. The only generated artifact is this report.

## Evidence and confidence

This report distinguishes three evidence levels:

- **Confirmed observation:** Directly visible in source code, templates, documentation, or test results.
- **Observed defect:** Demonstrated by a failing automated test or direct source contradiction.
- **Inference:** A likely user goal or behavior derived from the workflow and common webhook-debugging practice. Inferences should be validated by user research.

The supplied project declares version 0.9.0 and includes a CLI, FastAPI server, browser dashboard, SQLite persistence, request replay, JSON Schema validation, advanced filter/routing primitives, delivery diagnostics, retention settings, and optional token authentication.

A clean regression run produced **464 passing tests and 13 failing tests**, plus one non-blocking Pydantic warning. The failures are highly relevant to daily UX and release confidence: live connection state, incremental live updates, dashboard status, path filtering, replay channel/error handling, request-header redaction, request deletion API, delivery-attempt API/timeline, full-text search, and saved views. Several tests describe capabilities claimed by earlier internal implementation reports but absent from the packaged source.

---

# 1. Product understanding

## 1.1 What the application appears to do

Hookrelay is a local-first webhook relay and debugging application for developers. Its intended lifecycle is:

1. A developer starts a FastAPI relay server.
2. A forwarding CLI client connects to a named channel over WebSocket.
3. An external webhook provider sends an HTTP request to `/webhook/{channel}`.
4. Hookrelay stores the request in SQLite.
5. Matching JSON Schemas may validate the body.
6. The request is forwarded to a connected client and then to a local HTTP application.
7. The client reports the local target result to the server.
8. The developer inspects requests and responses in the CLI or dashboard.
9. Stored requests may be replayed.
10. Retention can remove old request data.
11. Optional token authentication can protect dashboard, API, and WebSocket surfaces.

The product is therefore not only a tunnel. It is a local integration-debugging workspace combining traffic capture, delivery, validation, history, replay, and diagnostics.

## 1.2 Likely users

### Primary: individual backend and full-stack developers

Developers integrating Stripe, GitHub, Slack, custom SaaS platforms, or internal event producers with a local application. Their main objective is a fast edit-trigger-inspect-replay loop.

### Secondary: integration engineers

Users managing multiple channels, payload contracts, filtering rules, and target environments. They need reliable routing, explainable outcomes, and reusable views.

### Secondary: QA and test automation engineers

Users reproducing malformed payloads, validating contracts, replaying failures, and converting captured requests into regression cases.

### Emerging: small engineering teams

**Inference:** Optional authentication, retained histories, schemas, and browser access imply demand for shared usage. However, the current single-token model does not yet provide identity, roles, ownership, or auditability.

## 1.3 Main surfaces

### CLI

- `serve`
- `forward`
- `listen`
- `history`
- `replay`
- `status`
- schema create/list/get/delete/validate operations

### Browser dashboard

- Live Feed
- History
- Request Inspector
- Replay
- Settings
- Login and logout when token protection is enabled

### APIs

- health
- webhook ingestion
- replay
- JSON Schema CRUD and validation
- retention read/update/purge
- relay and dashboard WebSockets

### Important internal capabilities not coherently surfaced

- Advanced filters and presets
- Saved filter-set storage primitives
- Conditional routing rules and priorities
- Filter execution history
- Full-text search support in SQLite
- Schema management in the browser
- Active relay connection details

## 1.4 Main workflows and usage scenarios

### Workflow A: first-time setup

1. Install the package.
2. Start `hookrelay serve`.
3. Start `hookrelay forward` with server, channel, and target.
4. Configure the provider webhook URL.
5. Open the dashboard.
6. Trigger a test event.

**Likely goal:** Prove the provider-to-local-app path works.

**Current friction:** Readiness spans terminal, provider configuration, server state, channel state, authentication state, and browser state. The dashboard does not present a single readiness checklist or active-client overview.

### Workflow B: live debugging

1. Keep Live Feed open.
2. Trigger or wait for an event.
3. Identify the newest request.
4. Open Request Details.
5. Inspect payload, headers, validation, and response.
6. Modify local code.
7. Replay or retrigger.

**Likely goal:** Determine whether the provider sent the expected event and whether the local application processed it correctly.

**Observed defect:** The packaged JavaScript still reloads the entire browser page for a live event, and the v0.5 acceptance tests for incremental updates and connection status fail.

### Workflow C: historical discovery

1. Open History.
2. Filter by channel or method.
3. Page through results.
4. Open a request.

**Likely goal:** Find one failure among many similar events.

**Observed defect:** The visible History form contains channel, method, and page size only. Path filtering, full-text search, validation filtering, and saved views are absent or incomplete despite tests and underlying storage capabilities.

### Workflow D: replay

1. Open a stored request.
2. Navigate to the Replay page.
3. Optionally type a target URL.
4. Submit replay.
5. Read a generic result.

**Likely goal:** Reproduce the request after a code change.

**Observed defects:** The API uses the hard-coded `default` channel rather than the stored request channel, and `NoConnectedClientError` is not converted into an actionable HTTP response. The related acceptance test fails with an unhandled exception.

### Workflow E: validation

1. Manage a schema through CLI or API.
2. Associate it with a channel.
3. Receive a request.
4. Read validation results in the Inspector.

**Likely goal:** Locate the exact contract violation quickly.

**Current friction:** Management is separated from consumption. The browser has validation display but no schema-management workflow, schema identity/version context, or payload-path navigation.

### Workflow F: retention and access protection

1. Open Settings.
2. Configure retention or purge expired data.
3. Inspect whether access protection is enabled.
4. If token authentication is enabled, log in or use a Bearer token.

**Likely goal:** Use the debugging tool safely without indefinitely keeping sensitive data.

**Strength:** The product now acknowledges privacy and network exposure explicitly.

**Current gap:** Retention is age-based only, access control is one shared token, and there is no audit trail or per-user authorization.

---

# 2. UI/UX analysis

## 2.1 Strengths

- The core mental model of channels, received requests, inspection, and replay is understandable.
- Dark styling is appropriate for a developer monitoring tool and supports long sessions.
- Method and validation badges improve initial scanning.
- The Inspector groups validation, delivery/response details, metadata, headers, body, and actions.
- Settings makes privacy and access protection visible rather than hiding them in configuration.
- Empty states and troubleshooting documentation exist.
- Optional authentication preserves a low-friction local mode.
- The application uses familiar web controls and generally clear page titles.
- The project includes a broad automated test suite and explicit UX acceptance tests, even though not all currently pass.

## 2.2 Weaknesses

### The live dashboard is still document-refresh based

The JavaScript calls `window.location.reload()` after a webhook event. This interrupts selection, focus, scrolling, filters, expanded details, and the user’s visual continuity. Reconnect creates a new WebSocket but does not attach the original event handlers to it. No reliable connected/reconnecting/disconnected indicator is rendered.

### Information architecture lags behind product scope

The navigation primarily exposes Live Feed, History, and Settings. Schemas, connections, routing, filters, and diagnostics are either hidden in other surfaces or not accessible as coherent browser workflows. The dashboard feels like a small request viewer attached to a much broader backend.

### Ingestion visibility and delivery confidence are not unified

The Inspector can show persisted delivery details, but list rows do not expose a clear lifecycle summary. Users cannot scan for received, forwarding, delivered, target error, transport error, invalid, or not-routed states directly from Live Feed or History.

### History discovery is too limited

The presented controls do not meet likely high-volume behavior. There is no visible full-text search, path filter, validation-state filter, delivery-state filter, time range, event type, or saved view. Existing pagination links do not preserve all relevant filters.

### Request inspection requires context switching

Opening a request navigates away from the list. The user loses list context, scroll position, and the ability to compare neighboring requests quickly. A split-pane workspace would better match repeated debugging.

### Replay is a separate, weakly explained action

The user must leave the Inspector. The optional target field does not clearly explain whether it overrides a connected client, bypasses routing, or changes only this attempt. The success message does not communicate target response status, latency, or response body.

### Raw technical data is hard to scan

Request bodies are shown in a preformatted block. There is no JSON tree, syntax-aware search, path/value copy, raw/pretty modes, line wrapping control, or comparison mode. Headers are similarly unsearchable.

### Security signaling is incomplete

The Settings page can indicate protected versus open mode, but shared-token authentication provides no identity. A team cannot know who replayed, deleted, changed retention, or managed schemas. Webhook ingestion intentionally remains public, but there is no optional provider signature verification or ingestion rate limiting.

## 2.3 Confusing elements

- The documentation and implementation reports claim earlier versions implemented incremental updates, saved views, path filtering, deletion API, and delivery-attempt API, while the current packaged source fails their own acceptance tests.
- “Valid” may mean passed schema validation, while a dash can mean no schema, validation skipped, unknown, or pending.
- “Replay successful” may mean accepted by Hookrelay, delivered to a client, or handled successfully by the local target. These are different outcomes.
- The retention page explains days but not current database size, oldest record, estimated deletion count, or last cleanup result.
- The access-protection setting distinguishes protected/open mode but does not explain that webhook ingestion remains public.
- Authentication uses a shared token, but the UI may be read as multi-user security even though there are no user identities or roles.

## 2.4 Friction points

1. Switching between terminal, browser, provider configuration, and local logs during setup.
2. No single readiness view for server, channel, connected client, target, and authentication.
3. Full-page reload on every live event.
4. No visible pause/resume or unseen-event count.
5. Navigating away from the list for each inspection.
6. Recreating search/filter context and manually scanning payload text.
7. Separate CLI/API schema management and dashboard validation reading.
8. Separate Replay page and unclear destination semantics.
9. No direct request comparison.
10. No one-click copy for JSON path/value, curl, request ID, or sanitized bundle.
11. A shared token without user-level auditability.
12. Retention cleanup without preview of impact.
13. Failing tests create uncertainty about whether documented capabilities are actually shippable.

## 2.5 Navigation and workflow observations

A more coherent navigation model would be:

- **Requests**
  - Live
  - History
  - Saved views
- **Connections**
  - Channels
  - Connected clients and targets
- **Schemas**
  - Definitions
  - Validation activity
- **Routing**
  - Rules
  - Match simulation and history
- **Settings**
  - Retention and redaction
  - Access and deployment
  - Diagnostics

Live Feed and History should become modes of one Requests workspace with shared filters and a persistent detail pane.

---

# 3. User behavior analysis

## 3.1 Likely user habits

**Inference:**

- Keep a server terminal, forwarding terminal, browser dashboard, and local application logs open concurrently.
- Work on one provider/channel for a session.
- Trigger the same event repeatedly while changing code.
- Inspect the newest request first.
- Search repeatedly for `type`, `event`, `action`, `id`, or provider delivery ID.
- Compare a successful request with a failed request.
- Replay the same event multiple times.
- Copy request IDs, JSON fragments, curl commands, and errors into tickets or tests.
- Leave the dashboard open for hours and expect reconnection without refresh.
- Prefer keyboard interactions during rapid debugging.
- Expect channel and target choices to persist between sessions.

## 3.2 Repeated actions

- Confirm a forwarding client is connected.
- Filter to one channel.
- Find the newest failed request.
- Open request details.
- Search within JSON and headers.
- Check validation and local response.
- Return to the request list.
- Replay.
- Compare before/after results.
- Sanitize and share evidence.

## 3.3 Likely pain points

- “Did the webhook only reach Hookrelay, or did it reach my app?”
- “Which client and target received it?”
- “Why did a replay use the wrong channel?”
- “Why did the page move or reload while I was inspecting?”
- “Where is the search capability described by the product?”
- “Why is a capability documented but failing its own acceptance test?”
- “What does the validation dash mean?”
- “Can I share this request without exposing secrets?”
- “Who changed retention or replayed this request?”
- “How many records will cleanup remove?”

## 3.4 Usage bottlenecks

### Setup bottleneck

Readiness is distributed across commands, channels, client connections, target reachability, token configuration, and browser state.

### Discovery bottleneck

History supports too few visible dimensions. As traffic grows, scrolling and opening individual requests becomes the dominant cost.

### Diagnosis bottleneck

The complete lifecycle exists across multiple components, but status is not summarized in list rows or a unified timeline with clear terminology.

### Reproduction bottleneck

Replay is not inline, does not preserve variants, and does not clearly expose destination and outcome before and after execution.

### Trust bottleneck

A release declaring 0.9.0 has 13 failing tests covering previously claimed user-facing capabilities. Users and maintainers cannot reliably distinguish shipped behavior from intended behavior.

## 3.5 Expected but missing interactions

- Incremental live rows without reload.
- Visible connected/reconnecting/disconnected state.
- Pause/resume with buffered-event count.
- Split-pane request inspection.
- Search in History and inside a payload.
- Saved request views.
- Filter chips and fully shareable URLs.
- Lifecycle badges in request rows.
- Previous/next request keyboard navigation.
- Inline replay with exact destination and response details.
- Request comparison.
- JSON tree and path/value copy.
- Connection/channel overview.
- Schema and routing management in the browser.
- Retention preview before deletion.
- Per-user audit history in shared mode.

---

# 4. What should be improved

## 4.1 Critical improvements

### 1. Restore release integrity and make the regression suite green

The next version must first resolve all 13 failing tests or explicitly remove unsupported claims and tests. Shipping additional features while core UX tests fail compounds product inconsistency.

### 2. Make Live Feed truly live and resilient

Replace document reload with incremental row updates. Add connection state, proper reconnect handlers, pause/resume, unseen counts, deduplication, bounded DOM size, and recovery of missed events.

### 3. Fix replay correctness and safety

Use the stored request channel, catch no-client errors, show destination semantics, record each replay attempt, and display target outcome. Prevent accidental double submission.

### 4. Protect sensitive request data in every presentation path

The Inspector currently renders sensitive request headers unmasked. Apply consistent redaction across UI, API responses intended for sharing, logs, and exports. Response redaction alone is insufficient.

### 5. Deliver a real request-discovery workflow

Expose FTS search, path, validation, delivery state, time range, and saved views. Preserve all state in the URL and pagination. This is essential for daily use beyond a handful of requests.

### 6. Expose connection readiness

Add a Connections view and status API with active channels, client/session IDs, targets, connected time, heartbeat, and stale state.

### 7. Unify request list, inspection, and replay

Create a Requests workspace with a side panel and inline replay. Preserve list context, selection, scroll, and filters.

## 4.2 Medium-priority improvements

- JSON tree, pretty/raw modes, in-payload search, and copy actions.
- Request comparison across payload, headers, validation, and delivery outcomes.
- Schema CRUD, enable/disable, version, test payload, and channel association in the dashboard.
- Routing-rule builder with simulation and match explanation.
- Saved replay variants and regression fixtures.
- Retention preview with oldest date, database size, candidate count, and last cleanup.
- Authentication audit events, token rotation, and rate limiting.
- Sanitized request/diagnostic export.
- Keyboard shortcuts and accessibility verification.

## 4.3 Nice-to-have improvements

- Provider-aware field extraction and signature-verification helpers.
- Bulk replay with rate controls.
- Replay collections/scenarios.
- Team comments after identity and authorization exist.
- OpenAPI/AsyncAPI or schema-registry integration.
- Optional failure notifications.

---

# 5. Requirements

## Prioritization method

- **Must have:** Required for a trustworthy and efficient core workflow, data safety, or release integrity.
- **Should have:** High recurring value but can follow the core debugging loop.
- **Could have:** Useful for advanced or less frequent scenarios.
- **Won’t have for now:** Deferred until security and core workflow prerequisites exist.

## 5.1 Business requirements

### BR-01: Restore product-release integrity

- **Type:** Business
- **Description:** The next release shall align product claims, documentation, implementation, and automated acceptance tests.
- **User value:** Users can trust that documented workflows work.
- **Priority:** Must have
- **Rationale:** The reviewed package reports 13 failing tests across core UX and previously claimed capabilities.
- **Acceptance criteria:**
  - All committed tests pass in a clean environment.
  - Every README/dashboard claim is covered by a passing test or clearly labeled planned capability.
  - CI blocks release creation on test or lint failure.
  - Version, changelog, health endpoint, and package metadata agree.

### BR-02: Minimize time from event receipt to identified failure stage

- **Type:** Business
- **Description:** A developer shall determine whether a request failed at ingestion, validation, routing, client delivery, transport, or local target handling from one request workspace.
- **User value:** Reduces manual correlation across logs and screens.
- **Priority:** Must have
- **Rationale:** Fast diagnosis is the product’s primary value proposition.
- **Acceptance criteria:**
  - In usability testing, at least 80% of participants identify a seeded failure stage within 60 seconds.
  - A request displays one ordered lifecycle timeline.
  - Each failed stage includes plain-language and technical explanations.

### BR-03: Make repeated daily debugging materially faster

- **Type:** Business
- **Description:** The product shall support stable, long-running live monitoring and repeated inspect-replay cycles without context loss.
- **User value:** Shorter iteration loops and better adoption.
- **Priority:** Must have
- **Rationale:** Current page refresh and navigation patterns interrupt the dominant workflow.
- **Acceptance criteria:**
  - No full-page refresh is used for live events.
  - Selection, scroll, filters, and panel state survive new traffic.
  - Core inspect-and-replay flow requires no more than two user actions after selecting a request.

### BR-04: Support safe local and small-team deployment

- **Type:** Business
- **Description:** Local open mode shall remain simple, while shared mode shall protect sensitive data and actions.
- **User value:** Safe adoption across more environments.
- **Priority:** Must have
- **Rationale:** Version 0.9 introduces authentication, but shared-token access lacks identity, authorization, and audit.
- **Acceptance criteria:**
  - Deployment mode and exposure are visible.
  - Shared mode records authenticated actors for destructive/outbound actions.
  - Sensitive fields are consistently redacted.
  - Documentation gives tested HTTPS and reverse-proxy guidance.

## 5.2 User requirements

### UR-01: Know the system is ready before sending an event

- **Type:** User
- **Description:** As a developer, I want to see server, authentication, channel, client, target, and heartbeat status before triggering a provider event.
- **User value:** Avoids wasted test attempts.
- **Priority:** Must have
- **Rationale:** Readiness is currently fragmented.
- **Acceptance criteria:**
  - Dashboard shows connected clients per channel.
  - Each connection shows target and last heartbeat.
  - Empty states include a copyable forwarding command.
  - Stale and disconnected states are distinct.

### UR-02: Monitor new requests without losing context

- **Type:** User
- **Description:** As a developer, I want new requests inserted incrementally while preserving my current inspection context.
- **User value:** Stable long-running debugging.
- **Priority:** Must have
- **Rationale:** Current live behavior reloads the page.
- **Acceptance criteria:**
  - New rows appear within two seconds under normal local conditions.
  - No document reload occurs.
  - Pause/resume buffers events and shows an unseen count.
  - Reconnect restores live updates automatically.

### UR-03: Find one request quickly

- **Type:** User
- **Description:** As a developer, I want full-text search and combinable filters across request and outcome data.
- **User value:** Reduces manual scanning.
- **Priority:** Must have
- **Rationale:** Current visible History filters are insufficient and saved-view tests fail.
- **Acceptance criteria:**
  - Search covers path, headers, and indexable body text.
  - Filters include channel, method, path, time, validation state, and delivery state.
  - Active filters appear visibly and persist in the URL.
  - Named views can be created, applied, renamed, and deleted.

### UR-04: Inspect without leaving the list

- **Type:** User
- **Description:** As a developer, I want a detail pane that preserves my list context.
- **User value:** Faster comparison and navigation.
- **Priority:** Must have
- **Rationale:** Full-page Request Details creates repetitive back-and-forth navigation.
- **Acceptance criteria:**
  - Selecting a row opens a side panel.
  - Deep links preserve selected request and filters.
  - Previous/next request navigation works by button and keyboard.

### UR-05: Replay safely and understand the result

- **Type:** User
- **Description:** As a developer, I want replay to show its exact destination and complete outcome.
- **User value:** Reproduces issues without ambiguity or accidental side effects.
- **Priority:** Must have
- **Rationale:** Current replay uses a hard-coded channel and can fail with an unhandled exception.
- **Acceptance criteria:**
  - Default channel is read from the stored request.
  - No-client state returns HTTP 409 and a recovery instruction.
  - Destination, modified fields, and side-effect warning appear before submission.
  - Response status, latency, headers, bounded body, and error appear after replay.
  - Every replay is recorded as a distinct attempt.

### UR-06: Understand validation failures in context

- **Type:** User
- **Description:** As a developer, I want validation errors connected to schema identity and the exact payload location.
- **User value:** Faster contract correction.
- **Priority:** Should have
- **Rationale:** Current display lacks schema-management and rich payload navigation.
- **Acceptance criteria:**
  - Result shows schema name, version, and draft.
  - Clicking an error selects the payload JSON path.
  - No schema, skipped, valid, and invalid are distinct states.

### UR-07: Control retention with confidence

- **Type:** User
- **Description:** As an operator, I want to preview retention impact before data deletion.
- **User value:** Prevents accidental loss and improves privacy control.
- **Priority:** Should have
- **Rationale:** Current controls show days and execute cleanup but not impact.
- **Acceptance criteria:**
  - Settings shows database size, oldest record, candidate count, and last cleanup result.
  - Manual purge requires confirmation including candidate count.
  - Cleanup is transactional across related data.

### UR-08: Share diagnostics without exposing secrets

- **Type:** User
- **Description:** As a developer, I want a sanitized diagnostic export for tickets and teammates.
- **User value:** Easier collaboration with lower privacy risk.
- **Priority:** Should have
- **Rationale:** Request and response headers/bodies may contain credentials or personal data.
- **Acceptance criteria:**
  - Default export is redacted.
  - Export includes request, validation, route, delivery attempts, and product version.
  - Unredacted export requires explicit warning and authorization.

## 5.3 Functional requirements

### FR-01: Incremental live event rendering

- **Type:** Functional
- **Description:** The dashboard shall render WebSocket events as row insertions/updates without navigation.
- **User value:** Continuous monitoring.
- **Priority:** Must have
- **Rationale:** Current JavaScript reloads the page.
- **Acceptance criteria:**
  - Duplicate event IDs update rather than duplicate rows.
  - Client-side rows are bounded to a configurable limit.
  - An empty state disappears when the first event arrives.
  - Automated browser test proves no reload occurs.

### FR-02: Resilient live connection state

- **Type:** Functional
- **Description:** The dashboard shall expose connected, reconnecting, disconnected, and stale states.
- **User value:** Makes system state visible.
- **Priority:** Must have
- **Rationale:** Current reconnect does not restore handlers.
- **Acceptance criteria:**
  - Reconnect uses bounded exponential backoff and jitter.
  - Handlers are restored on each connection.
  - Missed records are reconciled from a server cursor.
  - Manual retry is available.

### FR-03: Active connection registry

- **Type:** Functional
- **Description:** The server shall expose active relay clients by channel with target and heartbeat metadata.
- **User value:** Readiness and delivery transparency.
- **Priority:** Must have
- **Rationale:** No coherent connection overview is currently available.
- **Acceptance criteria:**
  - Registry exposes session ID, channel, target, connected time, last heartbeat, and state.
  - Stale clients expire after a defined timeout.
  - API and UI use the same source.

### FR-04: Unified request query API

- **Type:** Functional
- **Description:** One API shall support search, filtering, stable ordering, and pagination.
- **User value:** Fast discovery and shareable states.
- **Priority:** Must have
- **Rationale:** Current search/filter capabilities are fragmented and the related acceptance tests fail.
- **Acceptance criteria:**
  - Supports text, channel, method, path, time, validation, delivery, replayed state, and cursor.
  - Invalid query syntax returns actionable 422 detail.
  - Ordering is deterministic under concurrent ingestion.
  - Response includes next cursor and applied filters.

### FR-05: Saved request views

- **Type:** Functional
- **Description:** Users shall save named request query configurations.
- **User value:** Eliminates repeated setup.
- **Priority:** Must have
- **Rationale:** Repeated filtering is likely daily behavior and current saved-view tests fail.
- **Acceptance criteria:**
  - Create, apply, update, duplicate, rename, and delete are supported.
  - View stores filters, search, sort, and visible columns.
  - Duplicate names are handled clearly.

### FR-06: Correct replay workflow

- **Type:** Functional
- **Description:** Replay shall use the stored request channel unless the user explicitly chooses an override.
- **User value:** Correct reproduction.
- **Priority:** Must have
- **Rationale:** Current code uses `default`.
- **Acceptance criteria:**
  - Stored channel is the default.
  - Missing request returns 404.
  - No client returns 409 with channel and recovery command.
  - Unexpected relay errors return a traceable 5xx without leaking secrets.

### FR-07: Consistent request redaction

- **Type:** Functional
- **Description:** Request headers and configured JSON paths shall be redacted in UI, logs, API views, and exports.
- **User value:** Prevents accidental disclosure.
- **Priority:** Must have
- **Rationale:** The Inspector currently exposes Authorization values.
- **Acceptance criteria:**
  - Default header list includes Authorization, cookies, API keys, and tokens.
  - Redaction is case-insensitive.
  - Automated tests cover UI, API, logs, and export.
  - Reveal action, if present, is authorized and audited.

### FR-08: Delivery-attempt API and timeline

- **Type:** Functional
- **Description:** Persisted delivery attempts shall be retrievable and consistently rendered.
- **User value:** End-to-end diagnostic evidence.
- **Priority:** Must have
- **Rationale:** Storage exists, but the expected API/timeline tests fail.
- **Acceptance criteria:**
  - `GET /api/requests/{id}/delivery-attempts` returns newest-first attempts.
  - Inspector uses the same API/model.
  - Timeline distinguishes original forward and replay.
  - Missing request returns 404.

### FR-09: Request deletion API and UI

- **Type:** Functional
- **Description:** Users shall delete one request and related diagnostics after explicit confirmation.
- **User value:** Privacy and cleanup.
- **Priority:** Must have
- **Rationale:** Storage supports deletion, but expected API behavior is absent.
- **Acceptance criteria:**
  - Delete without confirmation returns 400.
  - Confirmed delete returns 204.
  - Related validation and delivery records are removed transactionally.
  - UI returns to filtered History and confirms completion.

### FR-10: Inline structured payload viewer

- **Type:** Functional
- **Description:** Inspector shall support JSON tree, pretty, and raw modes.
- **User value:** Faster payload reading.
- **Priority:** Should have
- **Rationale:** Raw preformatted bodies are slow to scan.
- **Acceptance criteria:**
  - Valid JSON is formatted without value changes.
  - Search, collapse, path copy, and value copy are available.
  - Large/binary payloads use safe preview limits.

### FR-11: Request comparison

- **Type:** Functional
- **Description:** Users shall compare two requests and outcomes.
- **User value:** Fast regression diagnosis.
- **Priority:** Should have
- **Rationale:** Comparing repeated events is a common debugging habit.
- **Acceptance criteria:**
  - Compare payload, headers, query, validation, and delivery.
  - Added, removed, and changed values are distinct.
  - Secret values remain redacted.

### FR-12: Schema management workspace

- **Type:** Functional
- **Description:** Dashboard shall support schema CRUD, activation, versioning, and testing.
- **User value:** Removes CLI/API context switching.
- **Priority:** Should have
- **Rationale:** Schema operations exist but are not a coherent browser workflow.
- **Acceptance criteria:**
  - Import/paste, validate, test, enable/disable, version, and delete are supported.
  - Test can use pasted JSON or a stored request.
  - Historical validation retains schema identity/version.

### FR-13: Routing rule simulator

- **Type:** Functional
- **Description:** Users shall build and simulate routing rules against history before activation.
- **User value:** Prevents misrouting.
- **Priority:** Should have
- **Rationale:** Routing/filter primitives exist but lack an operable UI.
- **Acceptance criteria:**
  - Priority order and first-match semantics are explicit.
  - Simulation shows matches, non-matches, and target.
  - Invalid expressions cannot be activated.
  - Runtime details explain the matched rule.

### FR-14: Authentication audit events

- **Type:** Functional
- **Description:** Shared mode shall record security-sensitive actions.
- **User value:** Accountability and troubleshooting.
- **Priority:** Should have
- **Rationale:** A shared token cannot identify actors today.
- **Acceptance criteria:**
  - Login failure/success, replay, delete, retention, schema, and routing changes are recorded.
  - Audit records exclude secrets.
  - Retention for audit data is separately configurable.

## 5.4 Non-functional requirements

### NFR-01: Release quality gate

- **Type:** Non-functional
- **Description:** CI shall require green tests, lint, packaging, and documentation checks.
- **User value:** Reliable upgrades.
- **Priority:** Must have
- **Rationale:** The reviewed artifact has 13 failing tests.
- **Acceptance criteria:**
  - Clean-environment test run is mandatory.
  - Package import and smoke test run from the generated archive.
  - Documentation examples are executable where practical.
  - Release is blocked on failure.

### NFR-02: Live performance

- **Type:** Non-functional
- **Description:** Dashboard shall remain responsive during realistic bursts.
- **User value:** Reliable high-volume debugging.
- **Priority:** Must have
- **Rationale:** Full-page reload cannot scale.
- **Acceptance criteria:**
  - At 20 events/second for 60 seconds, p95 visible update latency is under two seconds in the reference environment.
  - UI remains interactive.
  - Memory growth is bounded.

### NFR-03: Reliability and recovery

- **Type:** Non-functional
- **Description:** Temporary network interruption shall recover without silent event loss.
- **User value:** Trustworthy monitoring.
- **Priority:** Must have
- **Rationale:** Users leave the dashboard open for long sessions.
- **Acceptance criteria:**
  - Reconnection is automatic and visible.
  - Missed events are reconciled.
  - Duplicate deliveries are identified.

### NFR-04: Security

- **Type:** Non-functional
- **Description:** Shared deployment shall use secure defaults and layered controls.
- **User value:** Protects sensitive traffic and side-effecting actions.
- **Priority:** Must have
- **Rationale:** Hookrelay stores payloads and can replay requests.
- **Acceptance criteria:**
  - Constant-time token comparison remains.
  - Login and replay endpoints are rate-limited in shared mode.
  - HTTPS guidance is tested.
  - Secrets never appear in logs or standard exports.
  - Public ingress can optionally verify provider signatures.

### NFR-05: Accessibility

- **Type:** Non-functional
- **Description:** Core workflows shall conform to WCAG 2.2 AA.
- **User value:** Inclusive keyboard, screen-reader, and low-vision use.
- **Priority:** Must have
- **Rationale:** Current UI has some semantics but no demonstrated full accessibility validation.
- **Acceptance criteria:**
  - All actions are keyboard operable.
  - Status is not color-only.
  - Focus order and visible focus pass manual review.
  - Screen-reader tests cover live updates, validation, replay, login, and deletion.

### NFR-06: Data integrity and migration safety

- **Type:** Non-functional
- **Description:** Database evolution shall use explicit versioned migrations.
- **User value:** Preserves history across upgrades.
- **Priority:** Must have
- **Rationale:** Features have added tables and columns through create-if-not-exists behavior.
- **Acceptance criteria:**
  - Schema version is stored.
  - Upgrade from each supported version is tested.
  - Migration failure rolls back or creates a recoverable backup.

### NFR-07: Privacy

- **Type:** Non-functional
- **Description:** Storage, display, export, and deletion policies shall be consistent.
- **User value:** Predictable handling of sensitive data.
- **Priority:** Must have
- **Rationale:** Request redaction is currently incomplete.
- **Acceptance criteria:**
  - Documented data inventory exists.
  - Redaction rules apply across request and response data.
  - Retention preview and deletion are auditable.
  - Optional no-body-storage mode is available.

## 5.5 UX/UI requirements

### UX-01: Unified Requests workspace

- **Type:** UX/UI
- **Description:** Live and historical requests shall share list, filters, columns, and detail pane.
- **User value:** One mental model and fewer context switches.
- **Priority:** Must have
- **Rationale:** Users work with requests, not separate page concepts.
- **Acceptance criteria:**
  - Live/history toggle preserves applicable state.
  - Selected request is deep-linkable.
  - Inspector and replay do not navigate away from the list.

### UX-02: Visible lifecycle summary

- **Type:** UX/UI
- **Description:** Every request row shall show a compact lifecycle state.
- **User value:** Fast failure scanning.
- **Priority:** Must have
- **Rationale:** Users need to distinguish receipt from successful local handling.
- **Acceptance criteria:**
  - Labels and icons accompany color.
  - States include received, invalid, forwarding, delivered, target error, transport error, not routed, and unknown.
  - State explanation is available on focus/hover.

### UX-03: Clear empty, loading, and error states

- **Type:** UX/UI
- **Description:** Each workspace shall distinguish no data, no matches, loading, disconnected, unauthorized, missing request, and operation failure.
- **User value:** Faster recovery.
- **Priority:** Must have
- **Rationale:** Ambiguous state is especially costly in a debugging tool.
- **Acceptance criteria:**
  - Every error contains a recovery action.
  - Technical details can be expanded.
  - No-client replay state shows a copyable connect command.

### UX-04: Developer copy and keyboard actions

- **Type:** UX/UI
- **Description:** Frequently reused technical values shall be copyable and core navigation keyboard accessible.
- **User value:** Reduces repetitive manipulation.
- **Priority:** Should have
- **Rationale:** Users transfer IDs, URLs, JSON, and commands continuously.
- **Acceptance criteria:**
  - Copy request ID, webhook URL, target, header, JSON path/value, body, and curl.
  - Shortcuts cover search, next/previous, replay, pause, and close panel.
  - Shortcut help is discoverable.

### UX-05: Retention impact preview

- **Type:** UX/UI
- **Description:** Settings shall preview cleanup impact before deletion.
- **User value:** Safe data control.
- **Priority:** Should have
- **Rationale:** Current action does not quantify impact before confirmation.
- **Acceptance criteria:**
  - Candidate count and oldest/newest candidate are shown.
  - Confirmation repeats impact.
  - Completion shows deleted count and reclaimed space when measurable.

## 5.6 Data and integration requirements

### DIR-01: Versioned event envelope

- **Type:** Data/integration
- **Description:** Dashboard and relay WebSockets shall use a documented versioned event envelope.
- **User value:** Reliable live client behavior and compatibility.
- **Priority:** Must have
- **Rationale:** Current live data is minimal and reconnect recovery is absent.
- **Acceptance criteria:**
  - Envelope has schema version, event ID, type, timestamp, and entity data/reference.
  - Clients safely ignore unknown events.
  - Cursor reconciliation is supported.

### DIR-02: Connection protocol metadata

- **Type:** Data/integration
- **Description:** Relay clients shall register session and target metadata.
- **User value:** Readiness and explainability.
- **Priority:** Must have
- **Rationale:** Channel counts alone are insufficient.
- **Acceptance criteria:**
  - Registration includes protocol version, session ID, channel, target, capabilities, and heartbeat.
  - Old clients receive clear compatibility behavior.
  - Sensitive local details can be masked.

### DIR-03: Query and saved-view schema

- **Type:** Data/integration
- **Description:** Request query definitions shall be versioned and reusable in URLs, saved views, APIs, and routing simulation.
- **User value:** Consistent discovery.
- **Priority:** Must have
- **Rationale:** Search/filter semantics are currently fragmented.
- **Acceptance criteria:**
  - One canonical schema represents search, filters, sorting, columns, and cursor.
  - Saved views migrate across compatible versions.
  - Invalid fields are rejected explicitly.

### DIR-04: Audit model

- **Type:** Data/integration
- **Description:** Security-sensitive actions shall produce append-only audit records with actor identity where available.
- **User value:** Accountability.
- **Priority:** Should have
- **Rationale:** Shared-token authentication is not sufficient for team operation.
- **Acceptance criteria:**
  - Record actor, action, object, timestamp, outcome, and correlation ID.
  - Never record raw tokens or unredacted secrets.
  - Export and retention policies are defined.

---

## 5.7 MoSCoW summary

### Must have

- BR-01 through BR-04
- UR-01 through UR-05
- FR-01 through FR-09
- NFR-01 through NFR-07
- UX-01 through UX-03
- DIR-01 through DIR-03

### Should have

- UR-06 through UR-08
- FR-10 through FR-14
- UX-04 and UX-05
- DIR-04

### Could have

- Provider-aware views
- Signature-verification helpers
- Bulk replay with rate limits
- Replay scenarios
- Sanitized share bundles with expiring links after identity is available
- Optional failure notifications
- OpenAPI/AsyncAPI integration

### Won’t have for now

- Public multi-tenant SaaS hosting
- Enterprise distributed message-broker guarantees
- Exactly-once delivery claims
- Public share links before identity, authorization, audit, and redaction are complete
- Autonomous AI payload modification or replay
- Mobile-first design, because core workflows are desktop developer activities

---

# 6. New opportunities

## 6.1 Request comparison and regression fixtures

**Opportunity:** Compare a successful request with a failed request, then save one as a regression fixture.

**Why users may want it:** Developers repeatedly ask whether payload or local behavior changed.

**Evidence/reasoning:** History, validation, delivery attempts, and replay already provide the source data. Comparison connects existing capabilities into a daily workflow.

## 6.2 Provider-aware request summaries

**Opportunity:** Detect common providers and show event type, delivery ID, signature state, object ID, and action as columns.

**Why users may want it:** Generic raw JSON requires repeated scanning.

**Evidence/reasoning:** Provider presets already exist in filtering code, and documentation uses Stripe/GitHub/Slack examples.

## 6.3 Saved replay variants

**Opportunity:** Save an edited replay copy as a named test case with an expected status or validation result.

**Why users may want it:** Edge cases are replayed repeatedly after code changes.

**Evidence/reasoning:** Replay, stored requests, schemas, and delivery attempts already supply the foundation.

## 6.4 Contract regression dashboard

**Opportunity:** Aggregate validation failures by schema version, path, channel, event type, and time.

**Why users may want it:** A developer needs to know whether a contract failure is isolated or systematic.

**Evidence/reasoning:** Validation results are persisted, and schema operations already exist.

## 6.5 Routing simulation and explainability

**Opportunity:** Run proposed rules against recent requests and show matches, conflicts, and selected targets before activation.

**Why users may want it:** Priority and regex rules are powerful but error-prone.

**Evidence/reasoning:** Filter and routing primitives exist but lack a coherent operational surface.

## 6.6 Team mode with identity and audit

**Opportunity:** Evolve shared-token protection into authenticated users, roles, token rotation, and audit.

**Why users may want it:** Debugging often involves developers, QA, and integration owners.

**Evidence/reasoning:** Version 0.9 already introduces access protection, indicating demand for network/shared usage. Identity is the logical next security boundary.

## 6.7 Sanitized diagnostic bundle

**Opportunity:** Export request, validation, route, delivery attempts, and version metadata in one redacted bundle.

**Why users may want it:** Teams need reproducible evidence for tickets without manual copy/paste.

**Evidence/reasoning:** The product already stores all component data but lacks a safe sharing workflow.

---

# 7. Final recommendation

## 7.1 What should be built first

Build **Release 0.9.1: Reliability and workflow restoration** before introducing another major feature family.

### Immediate release scope

1. Make all 13 failing tests pass.
2. Replace live page reload with incremental updates and reliable reconnect.
3. Restore connection-status API and visible readiness state.
4. Fix replay to use the stored channel and return actionable errors.
5. Redact sensitive request headers in the Inspector and all secondary surfaces.
6. Expose delivery-attempt and request-deletion APIs consistently.
7. Restore full-text search, path/validation filters, filter persistence, and saved views or remove unsupported claims until they are complete.
8. Add archive-level smoke testing to CI so the delivered ZIP is tested, not only the developer worktree.

## 7.2 Why this should come first

The product has meaningful capabilities and a strong value proposition, but the current artifact contains contradictions between documentation, tests, and implemented UI. Adding schema or routing UI before restoring release integrity would increase scope while core flows remain unreliable. The fastest adoption gain comes from making receive-find-inspect-replay trustworthy and efficient.

## 7.3 UI and workflow priorities

1. Unified Requests workspace with live/history modes.
2. Incremental live list with pause, unseen count, connection state, and recovery.
3. Lifecycle badges in list rows.
4. Side-panel inspection with structured payload navigation.
5. Search, combinable filters, shareable URLs, and saved views.
6. Inline replay with exact destination and detailed outcome.
7. Connection/channel readiness screen.
8. Consistent redaction and sanitized export.

## 7.4 Requirements most likely to improve adoption and efficiency

The highest-impact set is BR-01 through BR-03, UR-01 through UR-05, FR-01 through FR-09, NFR-01 through NFR-05, UX-01 through UX-03, and DIR-01 through DIR-03. Together they repair trust, remove repeated navigation, improve discovery, and make the end-to-end delivery lifecycle obvious.

## 7.5 Recommended research plan

Run five to eight moderated sessions across individual developers, integration engineers, and QA users. Give participants these tasks:

1. Start the server and receive a first webhook.
2. Diagnose a webhook received by Hookrelay but not delivered to a client.
3. Diagnose a local target HTTP 500 response.
4. Find one event among 500 requests.
5. Fix a schema validation error.
6. Replay a request after a code change.
7. Compare a successful and failing request.
8. Configure retention and predict what will be deleted.
9. Sign in from a new browser and connect a forwarding client in protected mode.
10. Export a sanitized diagnostic bundle.

Measure task completion, time, errors, context switches, confidence, and recovery behavior. Use the findings to validate labels, lifecycle states, default columns, replay warnings, and connection guidance.

---

# Appendix A: verified release-risk register

## Risk R-01: Packaged release does not satisfy committed acceptance tests

- **Severity:** Critical
- **Evidence:** 13 failures out of 477 tests in a clean run.
- **Impact:** Users cannot trust version claims or documentation.
- **Mitigation:** Archive-level CI gate and release checklist.

## Risk R-02: Live monitoring interrupts user activity

- **Severity:** High
- **Evidence:** `window.location.reload()` remains in dashboard JavaScript.
- **Impact:** Lost context and poor burst handling.
- **Mitigation:** Incremental event rendering and reliable reconnect.

## Risk R-03: Replay uses the wrong channel and can raise an unhandled exception

- **Severity:** High
- **Evidence:** Replay passes `channel="default"` and does not catch no-client error.
- **Impact:** Failed or misdirected reproduction.
- **Mitigation:** Use stored channel and typed API errors.

## Risk R-04: Sensitive request headers are visible

- **Severity:** High
- **Evidence:** Authorization value appears in Inspector output under acceptance test.
- **Impact:** Credential exposure through screen sharing, exports, or screenshots.
- **Mitigation:** Consistent request redaction policy.

## Risk R-05: Claimed search and saved-view workflows are absent

- **Severity:** High
- **Evidence:** Four related tests fail and UI controls are not present.
- **Impact:** History becomes inefficient with realistic traffic volume.
- **Mitigation:** Deliver canonical query API and saved-view model.

## Risk R-06: Shared-token authentication lacks identity and audit

- **Severity:** Medium
- **Evidence:** One environment token grants the same access to all users.
- **Impact:** No actor attribution for replay, deletion, or settings changes.
- **Mitigation:** Add user identities, roles, audit, and token rotation before broader team positioning.

---

# Appendix B: direct observations versus inference

## Direct observations

- Package and source declare version 0.9.0.
- Surfaces include CLI, dashboard, REST APIs, and WebSockets.
- Dashboard pages include Live Feed, History, Inspector, Replay, Settings, and Login.
- Optional token authentication, response diagnostics, and retention are present.
- Advanced filter/routing primitives exist in source.
- Clean test execution produced 464 passes and 13 failures.
- Live JavaScript still performs full-page reload.
- Replay uses a hard-coded default channel.
- Inspector request-header redaction acceptance test fails.
- Search, saved-view, request-deletion API, delivery-attempt API, and connection-status tests fail.

## Inferences requiring validation

- Users keep the dashboard open for long sessions.
- Inspect and replay are among the most frequent actions.
- Users repeatedly filter to one channel/provider/event type.
- Request comparison and saved replay variants would reduce daily effort.
- Small-team demand exists but requires identity and audit before safe positioning.
