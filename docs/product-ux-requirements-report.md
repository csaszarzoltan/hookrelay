# Hookrelay Next-Version Product and UX Requirements Report

**Review basis:** Static analysis of the attached `ZipPrompt.md`, which contains a flattened representation of the Hookrelay 0.4.0 Python application, documentation, dashboard templates and assets, and test materials.

**Assessment date:** 2026-08-01  
**Product version reviewed:** 0.4.0  
**Confidence note:** This is a source-and-documentation review, not an observed usability test or a live runtime evaluation. Statements marked **Inference** describe likely behavior or user needs. Some source files are visibly truncated or malformed in the flattened archive, so implementation-level findings should be verified against the original repository and a running build.

---

## Executive summary

Hookrelay appears to be a developer-focused webhook relay and debugging product that combines a Python CLI, a FastAPI relay server, WebSocket tunneling, SQLite history, a browser dashboard, request replay, JSON Schema validation, advanced filtering, and conditional routing. Its core value proposition is strong: shorten the feedback loop between an external webhook provider and a local development environment.

The product has accumulated meaningful backend capability through versions 0.1.0 to 0.4.0, but the user-facing experience has not kept pace. The browser dashboard still exposes only a narrow subset of the system: Live Feed, History, Inspect, and Replay. Schema management, saved filters, routing rules, filter execution history, connection management, and operational diagnostics are mostly CLI, API, storage, or model capabilities rather than coherent user workflows. The highest-value next step is therefore not another isolated backend feature. It is to turn existing capabilities into a reliable, transparent, low-friction debugging workspace.

The most urgent problems are:

1. **Live monitoring is not truly live.** The JavaScript reloads the entire page after every webhook and the reconnect logic creates an unreferenced WebSocket rather than restoring handlers and UI status.
2. **Delivery outcome is not visible.** Users cannot reliably see whether a request was delivered, which target handled it, the local response status, latency, failure reason, or active client state.
3. **Replay is separated from inspection and gives weak feedback.** It requires context switching and reports only generic success or failure.
4. **Advanced capabilities are hidden.** Validation, filtering, routing, and schema functionality lack an integrated dashboard workflow.
5. **Information architecture is too shallow for the product’s current scope.** The navigation still reflects a small monitoring tool rather than a multi-capability webhook debugging environment.
6. **Source and documentation exhibit important contradictions.** Examples include a “local development” product whose documented SSRF defaults block localhost, a live feed described as row-level real-time updates while the implementation reloads the page, and docs that describe actions or columns absent from the supplied templates.
7. **Safety and trust controls are incomplete at the product layer.** Webhook bodies and headers can contain secrets or personal data; there is no visible redaction, retention, deletion, authentication, or access-control workflow.

**Recommended first release theme:** “Reliable daily debugging.” Build a unified Requests workspace with true incremental live updates, connected-client and target visibility, delivery outcome and latency, inline inspection, safe replay, persistent filtering, and clear empty/error/reconnection states. Move schema and routing management into the UI only after the core request-to-delivery loop is trustworthy.

---

# 1. Product understanding

## 1.1 What the application appears to do

Hookrelay is a webhook relay and debugging system for local development. Its apparent end-to-end model is:

1. An external provider sends an HTTP request to `/webhook/{channel}`.
2. The FastAPI server receives and stores the request.
3. Matching JSON Schemas may validate the JSON payload.
4. The server forwards the request through a channel-based WebSocket connection.
5. A Hookrelay CLI client receives the request and forwards it to a local HTTP endpoint.
6. The developer monitors requests through the CLI or browser dashboard.
7. Stored requests can be inspected, searched, filtered, and replayed.
8. Version 0.4.0 adds filtering and conditional routing primitives, presets, saved filter sets, rule persistence, and filter execution history.

The product is positioned as a CLI-first, Python-based alternative to webhook tunneling/debugging tools, with a bundled browser UI for visual inspection.

## 1.2 Apparent product boundaries

### Exposed user surfaces

- **CLI:** `serve`, `forward`, `listen`, `history`, `replay`, `status`, and schema commands.
- **Web dashboard:** Live Feed, History, Request Inspector, Replay.
- **REST API:** history, replay, schema CRUD, validation, health.
- **WebSocket endpoints:** relay by channel and dashboard live monitoring.
- **Python API:** storage, filtering, routing, validation, and relay primitives.

### Internal capabilities with limited or no user-facing workflow

- Saved filter sets.
- Filter presets and expression language.
- Conditional routing rules and priority ordering.
- Filter execution history.
- Schema lifecycle beyond CLI/API operations.
- Validation history and multi-schema result interpretation.
- Export exists in a Python helper but is not surfaced in the documented CLI or dashboard.

## 1.3 Likely user segments

### Primary segment: individual application developers

Developers integrating Stripe, GitHub, Slack, or custom webhooks into a service running locally. They need rapid feedback, payload inspection, replay, and clear delivery diagnostics.

### Secondary segment: backend and integration engineers

Engineers developing or troubleshooting event-driven integrations across environments. They are more likely to use channels, advanced filters, schemas, routing rules, APIs, and saved configurations.

### Secondary segment: QA and test automation engineers

Users who need to reproduce webhook scenarios, inspect malformed payloads, validate contracts, rerun failures, and retain evidence of test outcomes.

### Emerging segment: small engineering teams

**Inference:** The presence of stored history, routing, schemas, and a browser dashboard suggests potential team usage, but the reviewed product does not yet show authentication, ownership, collaboration, or environment separation required for safe shared deployment.

## 1.4 Main workflows and usage scenarios

### Workflow A: initial setup and first webhook

1. Install the package.
2. Start the server with `hookrelay serve`.
3. Start a forwarding client with channel and local target.
4. Configure the external provider to call the relay endpoint.
5. Open the dashboard and wait for traffic.

**User goal:** Prove that the webhook source can reach the local application.

**Observed risk:** Setup spans terminal commands, provider configuration, endpoint construction, and browser monitoring. The UI does not appear to guide the user through these dependencies or display a complete “ready” state.

### Workflow B: live debugging

1. Keep the Live Feed open.
2. Trigger an event externally.
3. Find the newest row.
4. Open the Inspector.
5. Read headers and body.
6. Return to the feed or history and trigger again.

**User goal:** Compare what was sent with what the local application received and how it responded.

**Observed risk:** Every event reloads the page, request details require navigation, and local delivery outcomes are not shown.

### Workflow C: find an earlier request

1. Open History.
2. Filter by channel, method, or path.
3. Move through offset-based pages.
4. Open a matching request.

**User goal:** Locate one request among many similar calls.

**Observed risk:** The supplied template does not expose full-text search despite backend support, filters are narrow, “Next” can appear without knowledge of remaining results, and filter state is likely lost during pagination because pagination links do not preserve filter query parameters.

### Workflow D: inspect and diagnose validation errors

1. Open a request.
2. Review the validation badge and errors.
3. Expand error details.
4. Compare the payload path with the schema constraint.

**User goal:** Identify exactly why a webhook contract failed and fix the sending or receiving implementation.

**Observed risk:** Validation results are supported, but schema identity, schema version, actionable suggestions, JSON path navigation, and cross-request validation filtering are weak or unavailable in the UI.

### Workflow E: replay a request

1. Open a request.
2. Navigate to a separate replay page.
3. Optionally enter a target URL.
4. submit replay.
5. Receive a generic browser message.

**User goal:** Reproduce a case quickly against the current local implementation.

**Observed risk:** The user cannot verify the exact replay destination, connected client, modified input, response body/status, duration, or whether replay semantics match the original request.

### Workflow F: manage schemas

1. Create or list schemas via CLI/API.
2. Associate a schema with a channel.
3. Send a webhook.
4. inspect validation results in the dashboard.

**User goal:** Continuously check webhook contracts during development.

**Observed risk:** Management and consumption are split between CLI/API and UI, increasing context switching and making schema state difficult to understand.

### Workflow G: filter and route traffic

1. Build an expression or preset in code.
2. Save filter sets or routing rules through storage-level methods.
3. Evaluate requests in the router engine.

**User goal:** Send only relevant events to the right local destination and reduce noise.

**Observed risk:** The supplied material does not demonstrate an end-to-end integrated UI or ingestion-to-routing execution path. Users cannot safely preview, test, order, or troubleshoot rules through the dashboard.

## 1.5 Product strengths

- Clear core problem and developer value proposition.
- Compact installation and startup model.
- CLI and dashboard serve different work styles.
- Persistent request history with FTS5 search support.
- Request replay reduces dependence on the external provider.
- JSON Schema validation can shift contract errors earlier in development.
- Channel-based separation is easy to understand at a basic level.
- SSRF-oriented validation shows awareness of forwarding risk.
- Broad automated test inventory indicates intent to protect behavior.
- Filtering and routing primitives provide a credible foundation for more demanding integrations.

## 1.6 Important evidence limitations and contradictions

These findings are based on the supplied flattened archive and should be verified in the original codebase:

- Several Python files contain truncated bodies or malformed syntax in the attached representation, including CLI, dashboard router, server, validation, and examples.
- Dashboard documentation describes Inspect and Replay actions in request rows, while the supplied templates primarily link the request ID to inspection and do not show equivalent row actions.
- Documentation says live events are appended and capped at 50 rows, while `dashboard.js` reloads the entire page after an event.
- Documentation describes automatic WebSocket reconnection and a connection-status badge, while the JavaScript opens a new socket without reattaching handlers or updating any visible status.
- Documentation says the recent requests table shows five items, while JavaScript comments and other materials imply up to 50 live rows.
- README describes only three runtime dependencies even though `pyproject.toml` lists a larger runtime dependency set.
- Documentation says forwarding is for localhost, but the SSRF section says private and loopback targets are blocked by default, and the referenced `--allow-private` option is not visible in the supplied CLI signature.
- The schema command documentation and implementation naming differ (`add/remove` in changelog versus `create/delete` in code).
- `body_base64` is represented with hexadecimal encoding in the model, which conflicts with its name.
- The replay JavaScript treats any 2xx response as success but does not display response content or delivery details.
- Filtering parser comments claim OR support, but the parser appears to flatten connectors and defaults to sequential AND behavior. Several custom filter types referenced by the parser are not visibly handled in `_matches`.
- Routing and filter persistence exist, but their integration into real ingress and relay behavior is not demonstrated in the supplied material.

---

# 2. UI/UX analysis

## 2.1 Strengths

- The top-level concepts of Live Feed and History are understandable for a developer tool.
- Dark styling suits long-running monitoring use and differentiates request methods with color.
- Request metadata is organized into recognizable groups.
- Empty-state copy on the Live Feed gives a basic endpoint pattern.
- Validation errors are designed to expand and collapse, reducing initial visual density.
- The interface uses familiar tables, badges, forms, and pagination.
- Replay is discoverable from the Inspector.

## 2.2 Weaknesses

### The interface does not represent the full product

The navigation exposes only Live Feed and History. Validation management, routing, filters, connections, settings, and operational health are missing from the dashboard information architecture. As backend scope expands, this makes the application feel fragmented and forces users to remember which surface contains which capability.

### Live Feed violates the expectation of a monitoring console

A real-time feed should update individual rows without losing scroll position, selected request, focus, filter state, or visual continuity. Reloading the whole page after each event creates flicker, interrupts inspection, increases network work, and makes rapid bursts difficult to follow.

### Important state is invisible

The interface does not clearly show:

- Which channels have connected clients.
- Which local targets are currently active.
- Whether the relay is ready.
- Whether an individual request was forwarded.
- Local response status and body.
- Forwarding duration.
- Retry or replay outcome history.
- Whether validation was skipped, not configured, passed, or failed.
- Which routing rule matched.

This creates a critical diagnostic gap: a request appearing in the dashboard proves ingestion, not successful delivery.

### Request detail requires too much navigation

Users repeatedly move from a list to a full request page and back. For a debugging tool, a split-pane inspector or expandable row would preserve list context and support rapid comparison.

### History discovery is underpowered

The product has FTS5 search and advanced filters, but the visible History page shows only channel, method, and path controls. There is no obvious search field, time range, validation state, delivery status, provider/event type, or saved view.

### Replay is not designed as a safe developer action

Replay can cause side effects. The interface lacks a clear destination summary, request preview, confirmation rules for risky targets, duplicate-warning semantics, response detail, and a persistent audit trail.

### Dense technical content is not optimized for scanning

The body is rendered as a raw preformatted block. There is no JSON tree, syntax-aware search, copy path/value action, line numbers, wrapping toggle, raw/pretty tabs, or diff against another request. Headers similarly lack search, copying, and sensitive-value masking.

### Accessibility is not evidenced

The style relies on color for method and validation meaning, uses small text in places, and does not show focus styles for all actionable elements. Expandable error headers may not have semantic buttons or ARIA state. Responsive behavior for wide request tables is not evident.

## 2.3 Confusing elements

- “Total requests” may mean since startup in documentation but stored total in other contexts.
- “Valid” can mean passed validation, while “—” may mean no schema, skipped validation, pending validation, or unknown.
- Channel is central to the product but has no dedicated explanation, creation flow, status, or overview.
- Optional target override on replay does not explain whether it bypasses channel routing or which component uses the URL.
- The same product uses server URLs, WebSocket channels, target URLs, webhook paths, forwarded paths, and routing targets without a clear visual model.
- Full request IDs exist, but list items show truncated IDs without prominent copy actions.
- The product describes source filtering and status-code filtering, but users may not know whether status refers to inbound HTTP status, local target response, or replay response.

## 2.4 Friction points

1. Switching between terminal, browser, and external provider during setup.
2. Re-entering channel and target values on repeated runs.
3. Full-page reload on every live request.
4. Navigating away from the list to inspect every request.
5. Returning to the list without preserved selection or scroll position.
6. Manually scanning raw JSON to find the relevant event field.
7. Recreating filters instead of saving and reapplying a view.
8. Opening a separate replay page for a frequent action.
9. Receiving generic replay feedback without local response diagnostics.
10. Using CLI/API to manage schemas and then dashboard to inspect results.
11. Lack of visible connection state before attempting replay.
12. Offset pagination without clear page number, range, or total-page context.
13. Pagination links apparently failing to preserve active filters.
14. No bulk cleanup or retention controls for a growing history database.
15. No masking control for secrets in Authorization, signature, cookie, or token headers.

## 2.5 Navigation and workflow observations

A more appropriate information architecture is:

- **Requests**
  - Live
  - History
  - Saved views
- **Connections**
  - Channels
  - Local clients and targets
- **Schemas**
  - Definitions
  - Validation activity
- **Routing**
  - Rules
  - Match history
- **Settings**
  - Storage and retention
  - Security and redaction
  - Server configuration

The Live Feed and History should likely become modes of one Requests workspace rather than separate conceptual destinations. Users think in terms of “requests I am debugging,” then switch between live stream and historical search.

---

# 3. User behavior analysis

## 3.1 Likely user habits

**Inference based on the product’s workflows:**

- Keep one terminal running the relay client and one browser tab showing incoming traffic.
- Trigger the same provider event repeatedly while editing local code.
- Focus on one channel, provider, or event type for a work session.
- Inspect a small subset of headers and JSON fields repeatedly.
- Replay the same failed request multiple times after each code change.
- Compare a successful request with a failing request.
- Copy request IDs, JSON fragments, signature headers, or curl commands into logs, tickets, or tests.
- Prefer keyboard-driven workflows when debugging rapidly.
- Leave the dashboard open for long periods and expect robust reconnection.
- Use saved configuration across sessions rather than type server, channel, and target values every time.

## 3.2 Repeated actions

- Filter to the current channel.
- Open the newest request.
- Search the payload for `type`, `event`, `id`, or `action`.
- Copy a value or request ID.
- Replay the current request.
- Inspect local status and error text.
- Return to the request list.
- Clear previous events or distinguish new events from old ones.
- Confirm whether a client is connected before triggering the provider again.

## 3.3 Likely pain points

- “The webhook reached Hookrelay, but did it reach my app?”
- “Which local endpoint received it?”
- “Why did this work once and fail now?”
- “Did the provider send something different, or did my local code change?”
- “Why does replay say success when my app still failed?”
- “Which schema or rule produced this result?”
- “Why did this request route somewhere unexpected?”
- “Where did my filter go after paging or refreshing?”
- “Can I safely share this payload without exposing secrets?”
- “How do I remove stored sensitive data?”

## 3.4 Usage bottlenecks

### Diagnostic bottleneck

The request lifecycle is fragmented across ingress, relay, local forward, validation, and replay, but the UI displays mainly ingress metadata. Users must correlate terminal output, dashboard request data, and local application logs manually.

### Context-switching bottleneck

Advanced actions use different surfaces. Schemas are managed in CLI/API, validation is viewed in the dashboard, filters exist in code/storage, and routing exists as a model. This raises learning cost and error probability.

### High-volume bottleneck

A full-page reload and basic table are unsuitable for event bursts. Users need pause, resume, unseen counts, deduplication cues, stable selection, and client-side or server-side streaming filters.

### Reproduction bottleneck

Replay does not visibly support controlled edits, saved replay variants, bulk replay, sequencing, or precise outcome inspection. Reproducing edge cases remains more manual than the product promise implies.

## 3.5 Expected but missing interactions

- Pause/resume live stream while retaining buffered events.
- Click a row to inspect in a side panel.
- Keyboard navigation through requests.
- Copy request ID, endpoint, header, JSON path, value, or curl command.
- Pretty/raw/tree views for JSON.
- Search inside payload and headers.
- Compare two requests.
- Replay inline and view status, latency, headers, and body.
- Edit a copy before replay without modifying the stored original.
- Pin, tag, annotate, or bookmark a request.
- Save a filter as a named view.
- Preview which past requests match a filter or routing rule.
- See why a rule matched or did not match.
- View active connections per channel and last heartbeat.
- Redact secrets automatically and reveal them only with an explicit action.
- Delete selected requests and configure retention.
- Export sanitized evidence.

---

# 4. What should be improved

## 4.1 Critical improvements

### 1. Make live monitoring truly incremental and resilient

Replace page reloads with row-level updates. Add connected, reconnecting, disconnected, and stale states; restore event handlers after reconnect; buffer bursts; preserve selection, scroll, and filters.

### 2. Expose the complete request lifecycle

Capture and display ingress, matched route, connected client, target URL, delivery status, local response status, latency, error category, and replay history. This is the single most valuable improvement because it answers whether the developer’s app actually received and handled the webhook.

### 3. Unify list, inspection, and replay

Create a Requests workspace with a list and resizable detail pane. Allow inline replay, clear destination preview, optional edited copy, and detailed outcome without losing list context.

### 4. Add a connection and readiness model

Show server health, channel state, number of connected clients, active targets, last heartbeat, and last delivery. Prevent or clearly explain replay attempts when no client is connected.

### 5. Fix history search, filter persistence, and pagination

Expose full-text search, time range, delivery and validation states, and event/provider fields. Preserve all filters across pagination and use cursor-based or stable pagination for changing datasets.

### 6. Protect sensitive payload data

Add default secret masking, configurable redaction rules, retention limits, deletion tools, sanitized export, and deployment warnings when binding to non-loopback interfaces. Shared deployment should require authentication.

### 7. Reconcile product behavior and documentation

Resolve contradictions around localhost forwarding, SSRF defaults, CLI options, live-update behavior, schema command names, row actions, dependencies, and version reporting.

### 8. Verify and integrate filtering/routing semantics

Ensure expression operators behave as documented, then expose rule testing and match explanations. Do not present routing as production-ready until ingress-to-forwarding integration and outcome recording are verified.

## 4.2 Medium-priority improvements

- Dashboard schema CRUD with channel assignment, enable/disable, version, and test payload.
- Saved views and provider presets in the Requests workspace.
- JSON tree, pretty/raw view, in-payload search, and copy actions.
- Request comparison.
- Tags, notes, and bookmarks.
- Export in JSON, curl, and sanitized formats.
- Clear data and retention settings.
- Better onboarding with generated endpoints and a readiness checklist.
- Keyboard shortcuts and accessible semantics.
- Rule builder with plain-language summary and matched-sample preview.
- Better validation explanations and links to the exact payload field.

## 4.3 Nice-to-have improvements

- Bulk replay with rate controls.
- Replay collections or scenarios.
- Team comments and share links after authentication is available.
- Provider signature verification helpers.
- Import from curl or captured HTTP request.
- OpenAPI/AsyncAPI or schema-registry integration.
- Optional notifications for repeated failures or contract regressions.

---

# 5. Requirements

## Prioritization method

- **Must have:** Required for a trustworthy, efficient core debugging workflow or to prevent significant security/usability failure.
- **Should have:** High-value capability that materially improves regular use but can follow the core lifecycle work.
- **Could have:** Useful enhancement for advanced or less-frequent scenarios.
- **Won’t have for now:** Deliberately deferred because prerequisites or product maturity are insufficient.

## 5.1 Business requirements

### BR-01: Reduce time to diagnose a webhook failure

- **Type:** Business requirement
- **Description:** Hookrelay shall enable a developer to determine whether a webhook was ingested, forwarded, received by a local target, and successfully handled from one coherent request view.
- **User value:** Eliminates manual correlation across the dashboard, terminal, and local logs.
- **Priority:** Must have
- **Rationale:** The current dashboard proves ingestion but does not visibly close the delivery loop.
- **Acceptance criteria:**
  - A usability test participant can identify the failed lifecycle stage for a seeded failure in at most 60 seconds.
  - The request view distinguishes ingestion, routing, forwarding, local response, and replay outcomes.
  - Each failed stage contains a plain-language reason and technical detail.

### BR-02: Make the dashboard suitable for repeated daily debugging

- **Type:** Business requirement
- **Description:** The browser experience shall support long-running monitoring and repeated inspect-replay cycles without disruptive refreshes or loss of context.
- **User value:** Faster iteration and higher confidence during development sessions.
- **Priority:** Must have
- **Rationale:** The current full-page refresh behavior conflicts with the core live-monitoring use case.
- **Acceptance criteria:**
  - New events appear without full-page navigation.
  - Selection, filters, scroll position, and inspector state remain stable when new requests arrive.
  - The dashboard recovers from a temporary connection interruption without user reload.

### BR-03: Convert existing advanced capabilities into coherent workflows

- **Type:** Business requirement
- **Description:** Filtering, validation, and routing capabilities shall be accessible through consistent UI and API workflows with explainable outcomes.
- **User value:** Users benefit from capabilities already present in the codebase without learning internal APIs or storage methods.
- **Priority:** Should have
- **Rationale:** The backend feature set exceeds the dashboard’s visible product scope.
- **Acceptance criteria:**
  - Users can discover each supported capability from primary navigation or contextual actions.
  - Each configured filter, schema, and rule has a visible status and usage outcome.
  - Unsupported or partially integrated functions are not presented as complete.

### BR-04: Protect user trust and sensitive webhook data

- **Type:** Business requirement
- **Description:** Hookrelay shall provide secure defaults for displaying, storing, exporting, and deleting webhook data.
- **User value:** Reduces accidental exposure of secrets and personal data.
- **Priority:** Must have
- **Rationale:** Headers and payloads routinely contain credentials, signatures, personal data, and business events.
- **Acceptance criteria:**
  - Known secret-bearing headers are masked by default.
  - Retention and deletion controls are available.
  - Exports can be sanitized.
  - Non-loopback/shared deployment produces explicit access-control guidance.

### BR-05: Establish measurable product quality for core workflows

- **Type:** Business requirement
- **Description:** The next version shall define outcome metrics for setup, live monitoring, diagnosis, and replay.
- **User value:** Leads to improvements based on effectiveness rather than feature count.
- **Priority:** Should have
- **Rationale:** The project has extensive tests but no visible user-experience success measures.
- **Acceptance criteria:**
  - Product telemetry is opt-in and documents collected fields, or local-only usage metrics are available without external transmission.
  - The team can measure first-webhook success, replay success, connection failures, and time-to-diagnosis in research sessions.
  - Release criteria include task-completion benchmarks for core workflows.

## 5.2 User requirements

### UR-01: See whether the system is ready before triggering a webhook

- **Type:** User requirement
- **Description:** As a developer, I want to see server, channel, client, and target readiness so that I do not waste time triggering events into an incomplete setup.
- **User value:** Prevents avoidable failed attempts.
- **Priority:** Must have
- **Rationale:** Readiness currently spans separate CLI and server states.
- **Acceptance criteria:**
  - The dashboard shows server status, active channel clients, and targets.
  - Stale/disconnected clients are visually distinct.
  - A no-client state includes a copyable command to connect one.

### UR-02: Diagnose one request without leaving the request list

- **Type:** User requirement
- **Description:** As a developer, I want to inspect a request in a side panel so that I retain list context while iterating.
- **User value:** Reduces navigation and cognitive load.
- **Priority:** Must have
- **Rationale:** Inspecting is a frequent action currently requiring page navigation.
- **Acceptance criteria:**
  - Selecting a row opens a detail panel without page navigation.
  - Browser back/forward and deep links preserve the selected request.
  - The user can move to previous/next request by button and keyboard.

### UR-03: Find a relevant request quickly

- **Type:** User requirement
- **Description:** As a developer, I want to search and filter by payload, header, channel, method, path, time, validation, and delivery status.
- **User value:** Reduces scanning in noisy histories.
- **Priority:** Must have
- **Rationale:** Backend search and filtering exist, but the visible UI exposes only a small subset.
- **Acceptance criteria:**
  - Search covers path, headers, and text payload where indexable.
  - Multiple filters can be combined.
  - Active filters are visible, removable individually, and preserved in the URL.
  - Pagination or infinite loading preserves filter state.

### UR-04: Replay safely with full outcome feedback

- **Type:** User requirement
- **Description:** As a developer, I want to preview where a replay will go and see the target response so that I can reproduce issues confidently.
- **User value:** Makes replay an effective debugging loop rather than a blind action.
- **Priority:** Must have
- **Rationale:** Current feedback is generic and destination semantics are unclear.
- **Acceptance criteria:**
  - Replay shows channel, connected client, destination, method, and path before submission.
  - The outcome shows delivery state, HTTP status, duration, response headers, and response body subject to limits/redaction.
  - The original stored request remains immutable.
  - Replay attempts are recorded with time and outcome.

### UR-05: Understand validation failures in payload context

- **Type:** User requirement
- **Description:** As a developer, I want validation errors linked to the exact payload fields and schema version so that I can fix contract failures quickly.
- **User value:** Shortens contract-debugging time.
- **Priority:** Should have
- **Rationale:** Current validation output is present but not sufficiently contextual.
- **Acceptance criteria:**
  - Each result identifies schema name, version, and draft.
  - Clicking an error focuses the corresponding JSON path.
  - “No schema,” “skipped,” “valid,” and “invalid” are distinct states.

### UR-06: Reuse my working context

- **Type:** User requirement
- **Description:** As a repeat user, I want saved views and remembered channel/target choices so that I do not recreate setup and filters each session.
- **User value:** Speeds routine workflows.
- **Priority:** Should have
- **Rationale:** Developers repeatedly focus on the same channel and event types.
- **Acceptance criteria:**
  - Users can save, rename, apply, and delete request views.
  - The last active view can be restored locally.
  - Saved configuration clearly indicates whether it is local, server-wide, or shared.

### UR-07: Compare successful and failing events

- **Type:** User requirement
- **Description:** As a developer, I want to compare two requests and their delivery outcomes so that I can identify meaningful differences.
- **User value:** Supports common regression diagnosis.
- **Priority:** Should have
- **Rationale:** Manual comparison of raw payloads is slow and error-prone.
- **Acceptance criteria:**
  - Users can select two requests from the list.
  - The comparison highlights additions, removals, and changed values in headers, query parameters, JSON body, and outcome.
  - Secret values remain masked.

### UR-08: Control and remove stored data

- **Type:** User requirement
- **Description:** As a user, I want to delete selected requests, clear a channel, and configure retention so that development data does not accumulate indefinitely.
- **User value:** Improves privacy, storage hygiene, and confidence.
- **Priority:** Must have
- **Rationale:** SQLite persistence currently has no visible lifecycle management.
- **Acceptance criteria:**
  - Delete one, delete selected, clear channel, and clear all actions exist with appropriate confirmation.
  - Retention can be configured by age and/or count.
  - Deletion includes associated validation and replay records.

## 5.3 Functional requirements

### FR-01: Incremental live-feed updates

- **Type:** Functional requirement
- **Description:** The dashboard shall insert or update request records from WebSocket events without reloading the document.
- **User value:** Keeps monitoring continuous and stable.
- **Priority:** Must have
- **Rationale:** Current JavaScript reloads the page for every webhook.
- **Acceptance criteria:**
  - A newly ingested request appears within two seconds under normal local conditions.
  - No full-page navigation occurs.
  - Duplicate events update an existing row instead of creating duplicate rows.
  - A configurable local buffer prevents the DOM from growing without limit.

### FR-02: Robust WebSocket state management

- **Type:** Functional requirement
- **Description:** The client shall reconnect with restored handlers, backoff, and visible state.
- **User value:** Reliable long-running monitoring.
- **Priority:** Must have
- **Rationale:** The supplied reconnect code creates a new socket without attaching handlers.
- **Acceptance criteria:**
  - States include connected, reconnecting, disconnected, and stale.
  - Reconnect uses bounded exponential backoff with jitter.
  - After reconnection, missed records are fetched from the last known cursor.
  - The user can retry immediately.

### FR-03: Persist delivery attempts and target responses

- **Type:** Functional requirement
- **Description:** The server shall persist each forward/replay attempt and its outcome as a separate record linked to the original request.
- **User value:** Provides end-to-end evidence and troubleshooting history.
- **Priority:** Must have
- **Rationale:** Existing request storage records replay count but not detailed delivery results.
- **Acceptance criteria:**
  - Stored fields include attempt ID, request ID, channel, client ID, target, started/completed time, status, response code, latency, error category, and bounded response metadata.
  - Multiple attempts do not overwrite one another.
  - The request API returns an attempt timeline.

### FR-04: Active connection registry

- **Type:** Functional requirement
- **Description:** The system shall expose active relay clients by channel with target and heartbeat metadata.
- **User value:** Clarifies readiness and replay availability.
- **Priority:** Must have
- **Rationale:** Connection state is required to interpret delivery behavior.
- **Acceptance criteria:**
  - Each connection has a non-secret client/session ID, channel, target, connected time, last heartbeat, and state.
  - Stale connections are removed or marked within a defined timeout.
  - APIs and dashboard use the same registry.

### FR-05: Unified request query API

- **Type:** Functional requirement
- **Description:** The history API shall support stable, combinable search and filters.
- **User value:** Enables fast discovery and a responsive UI.
- **Priority:** Must have
- **Rationale:** Current list and search paths are separate and filters are limited.
- **Acceptance criteria:**
  - Query supports text, channel, method, path, received range, validation state, delivery state, source, replayed state, and cursor.
  - Results have deterministic ordering.
  - API returns total where efficient, next cursor, and applied filters.
  - Invalid filters return actionable 4xx errors.

### FR-06: Inline request inspector

- **Type:** Functional requirement
- **Description:** The Requests workspace shall load request detail in a side panel while retaining the list.
- **User value:** Accelerates scan-inspect-replay cycles.
- **Priority:** Must have
- **Rationale:** Full-page context switching is repetitive.
- **Acceptance criteria:**
  - URL contains the selected request ID.
  - Panel tabs include Overview, Payload, Headers, Validation, Delivery, and Replays as applicable.
  - Loading, not-found, and deleted states are handled without breaking the list.

### FR-07: Structured payload viewer

- **Type:** Functional requirement
- **Description:** The inspector shall support pretty, tree, and raw views for JSON and a safe raw view for other content.
- **User value:** Makes payloads easier to scan and copy.
- **Priority:** Should have
- **Rationale:** Current body rendering is a raw block.
- **Acceptance criteria:**
  - Valid JSON is formatted without changing values.
  - Users can search and copy a JSON path or value.
  - Large and binary payloads use size limits and download/preview safeguards.
  - Raw bytes are represented accurately; encoding labels are correct.

### FR-08: Inline replay with immutable original

- **Type:** Functional requirement
- **Description:** Users shall replay from the inspector and may edit a temporary copy of method, path, headers, query, and body.
- **User value:** Supports rapid controlled reproduction.
- **Priority:** Must have
- **Rationale:** Replay is central, but the current separate page and generic result slow iteration.
- **Acceptance criteria:**
  - Original data cannot be altered by replay editing.
  - Modified fields are visibly marked.
  - Reset restores the original request copy.
  - Replay result is added to the attempt timeline.
  - Unsafe or invalid destinations are rejected with a specific reason.

### FR-09: Saved request views

- **Type:** Functional requirement
- **Description:** Users shall save a named combination of search, filters, visible columns, and sort order.
- **User value:** Removes repetitive setup.
- **Priority:** Should have
- **Rationale:** Saved filter storage exists and aligns with repeated user habits.
- **Acceptance criteria:**
  - Save, update, duplicate, rename, and delete are supported.
  - A view can be tested before saving.
  - Provider presets can seed a view without locking subsequent edits.

### FR-10: Schema management UI

- **Type:** Functional requirement
- **Description:** The dashboard shall provide schema list, create/import, edit, enable/disable, version, delete, and test workflows.
- **User value:** Removes CLI/API context switching.
- **Priority:** Should have
- **Rationale:** Schema CRUD exists but lacks a cohesive UI.
- **Acceptance criteria:**
  - Invalid schemas are rejected before activation.
  - A schema can be tested against pasted JSON or an existing request.
  - Deletion explains effects on historical results.
  - Multiple enabled schemas on one channel are clearly represented.

### FR-11: Routing rule builder and simulator

- **Type:** Functional requirement
- **Description:** The dashboard shall allow authorized users to create, order, enable, test, and explain routing rules before activation.
- **User value:** Reduces routing mistakes and makes rule behavior understandable.
- **Priority:** Should have
- **Rationale:** Routing logic exists but is not safely operable by users.
- **Acceptance criteria:**
  - Rule evaluation order is visible and reorderable.
  - A rule preview shows matching historical requests and selected target.
  - First-match and evaluate-all semantics are explicit.
  - Invalid expressions cannot be activated.
  - Runtime request details show the matched rule and criteria.

### FR-12: Filter expression correctness and diagnostics

- **Type:** Functional requirement
- **Description:** The filter engine shall implement documented operators consistently and report parse/semantic errors.
- **User value:** Prevents silent mismatch and unexpected routing.
- **Priority:** Must have
- **Rationale:** The supplied parser appears to ignore OR semantics and references unhandled match types.
- **Acceptance criteria:**
  - `=`, `!=`, regex, AND, OR, NOT, grouping, header fields, JSON paths, and exact path behavior have specification-backed tests.
  - Invalid regex and unknown fields return errors, not silent non-match.
  - The UI can display a normalized plain-language interpretation.

### FR-13: Request export and copy actions

- **Type:** Functional requirement
- **Description:** Users shall export or copy a request as JSON, curl, and sanitized diagnostic bundle.
- **User value:** Simplifies reproduction and collaboration.
- **Priority:** Should have
- **Rationale:** Export logic exists internally but is not exposed in core workflows.
- **Acceptance criteria:**
  - Export preserves method, path, query, headers, and body where safe.
  - Sensitive fields are masked by default.
  - Users receive a warning before including unmasked secrets.
  - Curl output is syntactically valid for supported payload types.

### FR-14: Data deletion and retention jobs

- **Type:** Functional requirement
- **Description:** The system shall support explicit deletion and automatic retention enforcement.
- **User value:** Limits risk and storage growth.
- **Priority:** Must have
- **Rationale:** Histories, validation results, and future response data can contain sensitive information.
- **Acceptance criteria:**
  - Retention can be disabled or configured by age/count.
  - Deletion is transactional across related records.
  - The UI reports the last cleanup result.
  - Active streaming clients handle deletion without errors.

### FR-15: Onboarding readiness checklist

- **Type:** Functional requirement
- **Description:** The empty state shall guide the user through server, client, provider endpoint, and first-event verification.
- **User value:** Improves first success and reduces setup ambiguity.
- **Priority:** Should have
- **Rationale:** Current empty-state guidance shows only an endpoint pattern.
- **Acceptance criteria:**
  - The page generates a copyable webhook URL for a chosen channel.
  - It shows a copyable forwarding command.
  - It verifies client connection and receipt of a test webhook.
  - It explains localhost/private-target security configuration accurately.

### FR-16: Request comparison

- **Type:** Functional requirement
- **Description:** Users shall compare two requests and their attempt outcomes.
- **User value:** Accelerates regression analysis.
- **Priority:** Should have
- **Rationale:** Comparing repeated webhook attempts is a likely daily behavior.
- **Acceptance criteria:**
  - Comparison supports structured JSON, headers, query, metadata, validation, and delivery.
  - Ordering-only JSON changes can be ignored.
  - Masked secrets remain masked in diffs.

### FR-17: Audit trail for destructive and outbound actions

- **Type:** Functional requirement
- **Description:** Replay, routing changes, schema changes, reveal-secret actions in shared mode, and deletion shall be auditable.
- **User value:** Improves accountability and troubleshooting.
- **Priority:** Should have
- **Rationale:** Replay and routing can have side effects, especially in shared use.
- **Acceptance criteria:**
  - Each event records actor where authentication exists, timestamp, action, object, and outcome.
  - Audit records are immutable through normal product operations.
  - Local single-user mode records actions without requiring identity.

## 5.4 Non-functional requirements

### NFR-01: Live-update performance

- **Type:** Non-functional requirement
- **Description:** The dashboard shall remain responsive during normal webhook bursts.
- **User value:** Preserves usability under realistic event traffic.
- **Priority:** Must have
- **Rationale:** Full-page refresh and unbounded updates do not scale.
- **Acceptance criteria:**
  - At 20 events/second for 60 seconds in a reference environment, the UI remains interactive.
  - New visible rows have a p95 display latency below two seconds.
  - Memory growth is bounded by the configured client buffer.

### NFR-02: Reliability and recovery

- **Type:** Non-functional requirement
- **Description:** Temporary dashboard or relay connection loss shall recover without silent data loss.
- **User value:** Builds trust in long-running monitoring.
- **Priority:** Must have
- **Rationale:** Developers may leave sessions open for hours.
- **Acceptance criteria:**
  - Reconnection is automatic and visible.
  - Missed events are reconciled from persistent storage.
  - Duplicate delivery is prevented or explicitly identified.

### NFR-03: Secure defaults

- **Type:** Non-functional requirement
- **Description:** Default configuration shall minimize unauthorized access, secret exposure, and unsafe forwarding.
- **User value:** Reduces accidental harm.
- **Priority:** Must have
- **Rationale:** The default bind address and sensitive request data create exposure risk.
- **Acceptance criteria:**
  - Default server binding and documentation are aligned with local-only use, or non-loopback binding produces a prominent warning.
  - Secret-bearing headers are masked by default.
  - Target validation is enforced consistently for forward and replay.
  - Shared deployment requires configurable authentication and transport security guidance.

### NFR-04: Accessibility

- **Type:** Non-functional requirement
- **Description:** Core dashboard workflows shall conform to WCAG 2.2 AA.
- **User value:** Ensures keyboard, screen-reader, low-vision, and color-vision accessibility.
- **Priority:** Must have
- **Rationale:** Current implementation does not demonstrate accessible semantics or complete focus treatment.
- **Acceptance criteria:**
  - All core actions are keyboard operable.
  - Status is not communicated by color alone.
  - Focus is visible and logical.
  - Expand/collapse controls expose name, role, and state.
  - Automated checks and manual keyboard/screen-reader tests pass release criteria.

### NFR-05: Data integrity

- **Type:** Non-functional requirement
- **Description:** Stored request bodies and attempt records shall preserve exact payload information and use correctly named encodings.
- **User value:** Prevents misleading debugging evidence.
- **Priority:** Must have
- **Rationale:** The reviewed model uses a `body_base64` name for hexadecimal data.
- **Acceptance criteria:**
  - Binary encoding field names match their actual encoding.
  - Round-trip tests cover arbitrary binary payloads.
  - Original requests are immutable after storage.

### NFR-06: Observability

- **Type:** Non-functional requirement
- **Description:** The server shall provide structured logs and health signals for ingestion, relay, storage, validation, routing, and replay.
- **User value:** Supports diagnosis when the debugging tool itself fails.
- **Priority:** Should have
- **Rationale:** A relay tool must make its own failures transparent.
- **Acceptance criteria:**
  - Logs include correlation IDs without logging unmasked secrets.
  - Health distinguishes basic liveness from storage and relay readiness.
  - Error categories align between API, logs, and UI.

### NFR-07: Compatibility and upgrade safety

- **Type:** Non-functional requirement
- **Description:** Database and configuration changes shall be versioned and migratable.
- **User value:** Prevents history loss during upgrades.
- **Priority:** Must have
- **Rationale:** New attempt, retention, routing, and security data require schema evolution.
- **Acceptance criteria:**
  - Migrations are idempotent and tested from supported prior versions.
  - Upgrade failure leaves a recoverable backup or transaction rollback.
  - Version shown in CLI, health endpoint, package, and UI is consistent.

### NFR-08: Test completeness for user journeys

- **Type:** Non-functional requirement
- **Description:** Automated tests shall cover core cross-component journeys rather than only interface existence.
- **User value:** Reduces regressions in the actual experience.
- **Priority:** Must have
- **Rationale:** Many supplied tests are described as pre-development interface/behavior tests and may not validate the full workflow.
- **Acceptance criteria:**
  - End-to-end tests cover first webhook, reconnect, inspect, replay success/failure, validation states, filter persistence, routing match, redaction, retention, and upgrade.
  - Accessibility and browser tests are part of CI.
  - Documentation examples are executable tests where practical.

## 5.5 UX/UI requirements

### UX-01: Unified Requests workspace

- **Type:** UX/UI requirement
- **Description:** Live and historical requests shall share one consistent workspace with stream/history modes and a detail pane.
- **User value:** Reduces navigation and mental-model fragmentation.
- **Priority:** Must have
- **Rationale:** Users debug requests, not pages.
- **Acceptance criteria:**
  - Shared search, filters, columns, and inspector operate in both modes.
  - Switching modes preserves relevant context.
  - The selected request remains visible and deep-linkable.

### UX-02: Visible lifecycle status

- **Type:** UX/UI requirement
- **Description:** Every row shall show a compact, accessible lifecycle summary.
- **User value:** Enables rapid scanning for failures.
- **Priority:** Must have
- **Rationale:** Ingestion-only metadata is insufficient.
- **Acceptance criteria:**
  - Distinct states exist for received, validating, invalid, queued, forwarding, delivered, target error, transport error, and not routed where applicable.
  - Labels and icons accompany color.
  - Hover/focus explanation and detail link are available.

### UX-03: Pause, resume, and unseen-event handling

- **Type:** UX/UI requirement
- **Description:** Users shall pause visual insertion while the system continues buffering events.
- **User value:** Prevents the list from moving during inspection.
- **Priority:** Must have
- **Rationale:** Rapid live traffic otherwise disrupts reading.
- **Acceptance criteria:**
  - Pause does not disconnect ingestion.
  - A count of unseen events appears.
  - Resume prepends buffered events without losing selection.

### UX-04: Strong empty, loading, and error states

- **Type:** UX/UI requirement
- **Description:** Each page and panel shall explain no data, filtered-out data, loading, disconnection, missing request, and operational error states.
- **User value:** Helps users recover without guessing.
- **Priority:** Must have
- **Rationale:** Developer tools often fail because state is ambiguous.
- **Acceptance criteria:**
  - Empty history distinguishes no stored requests from no filter matches.
  - Errors include a recovery action and technical details toggle.
  - No-client replay state offers a connection command rather than a generic failure.

### UX-05: Developer-oriented copy and keyboard actions

- **Type:** UX/UI requirement
- **Description:** Frequent technical values and actions shall support one-click copy and keyboard shortcuts.
- **User value:** Speeds repetitive debugging.
- **Priority:** Should have
- **Rationale:** Users repeatedly transfer IDs, URLs, JSON, and commands.
- **Acceptance criteria:**
  - Copy actions exist for request ID, webhook URL, target, headers, JSON path/value, body, and curl.
  - Shortcuts include search, previous/next request, replay, pause/resume, and close inspector.
  - Shortcut help is discoverable and does not conflict with text editing.

### UX-06: Filter clarity and persistence

- **Type:** UX/UI requirement
- **Description:** Active filters shall be visible as editable chips and preserved in the URL and pagination state.
- **User value:** Prevents hidden constraints and repeated input.
- **Priority:** Must have
- **Rationale:** Current pagination links appear to omit active filter parameters.
- **Acceptance criteria:**
  - Each filter can be removed independently.
  - “Clear all” is available.
  - Filtered count and total context are distinguishable.
  - Reload and shared links restore the filter state.

### UX-07: Safe replay interaction

- **Type:** UX/UI requirement
- **Description:** Replay controls shall make side effects, destination, and modifications explicit.
- **User value:** Prevents accidental delivery and builds confidence.
- **Priority:** Must have
- **Rationale:** Webhook replay can create real downstream actions.
- **Acceptance criteria:**
  - Destination is displayed adjacent to the action.
  - Modified requests use a different action label from exact replay.
  - External/non-local targets require enhanced warning or policy approval.
  - Double submission is prevented while an attempt is active.

### UX-08: Responsive and scalable table design

- **Type:** UX/UI requirement
- **Description:** Request lists shall remain usable across laptop widths and large histories.
- **User value:** Supports realistic developer environments.
- **Priority:** Should have
- **Rationale:** Wide tables and technical strings can overflow.
- **Acceptance criteria:**
  - Users can choose visible columns.
  - Important columns remain pinned or prioritized.
  - Overflow is handled without hiding essential actions.
  - Row virtualization or paging prevents rendering degradation.

## 5.6 Data and integration requirements

### DIR-01: Delivery-attempt data model

- **Type:** Data/integration requirement
- **Description:** Introduce a normalized attempt entity linked to request, channel, route, client, and target.
- **User value:** Powers lifecycle visibility and replay history.
- **Priority:** Must have
- **Rationale:** A replay counter alone cannot explain outcomes.
- **Acceptance criteria:**
  - Attempt records support original forward and replay types.
  - Foreign-key or application-level integrity is enforced.
  - Response bodies are size-limited and retention-aware.

### DIR-02: Connection identity and heartbeat protocol

- **Type:** Data/integration requirement
- **Description:** Relay clients shall register stable session metadata and heartbeat state through a versioned protocol.
- **User value:** Enables readiness and target transparency.
- **Priority:** Must have
- **Rationale:** Current channel lists do not expose sufficient connection metadata.
- **Acceptance criteria:**
  - Protocol includes version, session ID, channel, target metadata, capabilities, connected time, and heartbeat.
  - Older clients receive a clear compatibility response.
  - Sensitive local details can be masked according to deployment mode.

### DIR-03: Unified event schema

- **Type:** Data/integration requirement
- **Description:** Dashboard WebSocket messages shall use a documented versioned envelope for request, attempt, validation, connection, and deletion events.
- **User value:** Makes real-time UI updates reliable.
- **Priority:** Must have
- **Rationale:** Current messages expose limited event types and the UI resorts to page reload.
- **Acceptance criteria:**
  - Every message contains schema version, event ID, event type, timestamp, and entity data/reference.
  - Clients can safely ignore unknown event types.
  - Reconnect reconciliation uses an event or request cursor.

### DIR-04: Redaction configuration

- **Type:** Data/integration requirement
- **Description:** Redaction rules shall cover headers and JSON paths at display, export, logging, and retention boundaries.
- **User value:** Prevents secrets from leaking through secondary surfaces.
- **Priority:** Must have
- **Rationale:** Masking only UI text would leave logs and exports exposed.
- **Acceptance criteria:**
  - Default rules include Authorization, Cookie/Set-Cookie, common API-key headers, and configurable JSON paths.
  - Redaction applies consistently to API/UI/log/export representations.
  - Original encrypted storage, irreversible redaction, or no-storage modes are explicit configuration choices.

### DIR-05: Database migration and indexing plan

- **Type:** Data/integration requirement
- **Description:** New lifecycle queries and retention operations shall be supported by migration-managed schema and measured indexes.
- **User value:** Preserves performance as history grows.
- **Priority:** Must have
- **Rationale:** Current schema initialization uses create-if-not-exists rather than an explicit migration history.
- **Acceptance criteria:**
  - Schema version is stored.
  - Migrations cover attempts, connections, audit, retention metadata, and corrected body encoding.
  - Query plans for common request filters meet documented target datasets.

### DIR-06: Provider preset extensibility

- **Type:** Data/integration requirement
- **Description:** Provider presets shall be data-driven, versioned, and testable rather than hard-coded only in Python.
- **User value:** Makes common Stripe, GitHub, Slack, and future provider workflows easier to maintain.
- **Priority:** Could have
- **Rationale:** Existing presets show demand but hard-coded behavior limits evolution.
- **Acceptance criteria:**
  - A preset declares provider detection, useful event fields, recommended filters, and sensitive fields.
  - Users can inspect and customize a preset-derived view.
  - Preset changes are covered by fixtures.

---

## 5.7 MoSCoW summary

### Must have

BR-01, BR-02, BR-04; UR-01, UR-02, UR-03, UR-04, UR-08; FR-01 through FR-08 except FR-07 is Should, FR-12, FR-14; NFR-01 through NFR-05, NFR-07, NFR-08; UX-01 through UX-04, UX-06, UX-07; DIR-01 through DIR-05.

### Should have

BR-03, BR-05; UR-05, UR-06, UR-07; FR-07, FR-09 through FR-11, FR-13, FR-15 through FR-17; NFR-06; UX-05, UX-08.

### Could have

DIR-06, bulk replay with rate limiting, replay scenarios, provider signature helpers, import from curl, optional local notifications.

### Won’t have for now

- Public multi-tenant SaaS hosting.
- Team comments and public share links before authentication, authorization, retention, and redaction are complete.
- Production message-broker replacement semantics such as durable distributed queues, guaranteed exactly-once delivery, or enterprise workflow orchestration.
- AI-generated payload changes or autonomous replay because explainability, privacy, and safe side-effect controls must come first.
- Mobile-first monitoring because the core persona and workflows are desktop developer activities.

---

# 6. New opportunities

## 6.1 Request diff and regression workflow

**Opportunity:** Compare a known-good request and outcome against a failing one, then save the failing request as a regression fixture.

**Why users may want it:** Webhook development is iterative, and users commonly ask whether the provider payload or local behavior changed.

**Evidence and reasoning:** The product already stores history, supports replay, and performs validation. Diffing connects these capabilities into a high-value diagnostic workflow rather than adding an unrelated feature.

## 6.2 Provider-aware request views

**Opportunity:** Detect common providers and surface the most useful fields, such as event type, delivery ID, signature state, object ID, and action.

**Why users may want it:** Generic raw JSON requires repeated scanning. Provider presets already exist in filtering logic.

**Evidence and reasoning:** Stripe, GitHub, and Slack presets are explicitly present, indicating both expected traffic and a foundation for provider-aware UI. Detection must remain transparent and overridable.

## 6.3 Contract-regression dashboard

**Opportunity:** Show validation failure trends by schema version, channel, error path, and event type.

**Why users may want it:** Users need to know whether a failure is isolated or systematic after a provider or local contract change.

**Evidence and reasoning:** Validation results and history already exist. Aggregating them is a logical extension once result persistence is reliable.

## 6.4 Replay variants as test cases

**Opportunity:** Save an edited replay copy as a named local test case with expected response status or schema outcome.

**Why users may want it:** Developers repeatedly test the same edge cases after code changes.

**Evidence and reasoning:** Replay, payload storage, and schemas already support the ingredients. This should follow safe replay and immutable originals.

## 6.5 Routing explainability and simulation

**Opportunity:** Before activation, run a proposed rule against recent requests and show matches, non-matches, and first-match conflicts.

**Why users may want it:** Priority routing and regex conditions are powerful but error-prone.

**Evidence and reasoning:** The code includes ordered rules, filter expressions, and filter history. Simulation turns these into a safer product workflow and directly addresses silent parser/match risks.

## 6.6 Sanitized diagnostic bundles

**Opportunity:** Export one request, related validation, route, delivery attempts, and server/version metadata as a redacted bundle.

**Why users may want it:** Developers often need to share a reproducible issue with a teammate or attach it to a bug.

**Evidence and reasoning:** History export exists, but a lifecycle bundle would reduce manual copying while respecting sensitive data.

## 6.7 Local-first team mode

**Opportunity:** After security prerequisites, support authenticated shared dashboards with role-based access and audit.

**Why users may want it:** Integration debugging commonly involves a backend developer, QA engineer, and provider/integration owner.

**Evidence and reasoning:** Browser UI, persistent history, schemas, and routing imply collaborative value. This is explicitly deferred until authentication, redaction, retention, and audit are complete.

---

# 7. Final recommendation

## 7.1 What should be built first and why

Build **Release 1: Reliable Requests Workspace** before adding another major backend feature.

### Immediate scope

1. Replace full-page live-feed reloads with incremental, resilient event updates.
2. Introduce active connection state and target visibility.
3. Persist each delivery/replay attempt and local target response.
4. Unify Live Feed, History, Inspector, and Replay in a list-plus-detail workspace.
5. Add searchable, persistent filters and stable pagination.
6. Add safe replay with exact destination preview and detailed outcome.
7. Add secret masking, deletion, retention, and sanitized export foundations.
8. Correct filter-expression semantics and run end-to-end regression tests.
9. Reconcile documentation with actual behavior and supported CLI/API contracts.

### Why this comes first

These changes directly improve the most frequent behavior: trigger, observe, inspect, fix, replay. They also resolve the largest trust gap, whether a request reached the local application and how that application responded. Shipping schema or routing UI before this lifecycle is visible would add more configuration without solving the core diagnostic problem.

## 7.2 UI and workflow improvements to prioritize immediately

- Requests as the primary workspace.
- Stable live list with pause/resume and unseen count.
- Row status that summarizes the full lifecycle.
- Side-panel inspector with Overview, Payload, Headers, Validation, Delivery, and Replays.
- Inline replay with destination and response details.
- Connection/readiness panel by channel.
- Search and filter chips with saved URL state.
- Precise empty, disconnected, no-client, and failed-delivery states.
- Secret masking and one-click sanitized copy/export.
- Keyboard navigation and accessible status semantics.

## 7.3 Suggested delivery sequence

### Phase 0: product integrity and verification

- Restore/run the original repository rather than the flattened representation.
- Verify all 447 claimed tests and add end-to-end browser tests.
- Reconcile localhost/SSRF behavior, CLI options, schema commands, version strings, and docs.
- Confirm whether routing and filter execution are integrated into ingress and relay.

### Phase 1: lifecycle data and reliability

- Delivery-attempt model.
- Connection registry and heartbeat protocol.
- Unified versioned dashboard event envelope.
- Reconnection reconciliation.
- Database migrations and data-integrity fixes.

### Phase 2: Requests workspace

- Incremental feed.
- Unified query API.
- Split-pane inspector.
- Delivery and replay timeline.
- Inline safe replay.
- Search and persistent filters.

### Phase 3: trust and operational controls

- Redaction.
- Retention and deletion.
- Audit.
- Accessibility remediation.
- Observability and deployment warnings.

### Phase 4: advanced workflow UI

- Saved views and presets.
- Schema management and contextual validation.
- Request comparison.
- Routing rule builder and simulator.

## 7.4 Requirements most likely to improve adoption and efficiency

The highest-impact requirements are BR-01, BR-02, UR-01 through UR-04, FR-01 through FR-08, FR-12, NFR-02, UX-01 through UX-07, and DIR-01 through DIR-03. Together they transform Hookrelay from a set of capable components into a coherent debugging product.

## 7.5 Research and validation plan

Before finalizing interaction design, conduct five to eight moderated sessions across individual developers, integration engineers, and QA users. Give each participant these tasks:

1. Start Hookrelay and receive a first webhook.
2. Diagnose a request that is ingested but cannot reach a client.
3. Diagnose a request that reaches the local target but receives HTTP 500.
4. Find a specific event among 200 requests.
5. Fix a schema validation error.
6. Replay a request after a local code change.
7. Create and test a routing rule without sending traffic to the wrong target.
8. Export a sanitized diagnostic bundle.

Measure task completion, time, errors, context switches, confidence, and recovery behavior. Use findings to refine labels, lifecycle states, default columns, and confirmation rules.

---

## Appendix A: concise product-risk register

### Risk R-01: False confidence from “replay successful”

A successful API call may not prove successful local handling. Mitigate with attempt-level response recording and precise status language.

### Risk R-02: Secret exposure

Raw headers and payloads can expose credentials. Mitigate with default redaction, retention, authentication for shared mode, and sanitized export.

### Risk R-03: Unsafe replay side effects

Replaying a webhook can duplicate business actions. Mitigate with destination visibility, policy controls, warnings, immutable originals, and audit.

### Risk R-04: Routing mismatch

Silent parser limitations or priority conflicts can send traffic incorrectly. Mitigate with strict parsing, simulation, match explanations, and integration tests.

### Risk R-05: Documentation-driven setup failure

Contradictory localhost and SSRF guidance can block the core use case. Mitigate by defining one coherent security model and testing every published quick-start command.

### Risk R-06: Shared deployment exposure

Binding to `0.0.0.0` with no visible authentication may expose stored webhook data. Mitigate with safe defaults, warnings, access control, and secure deployment guidance.

---

## Appendix B: source-derived observations versus inference

### Directly observed in supplied materials

- Python 3.11+ package with Typer, FastAPI, WebSocket, requests, Jinja2, JSON Schema, SQLite/FTS5.
- CLI commands for relay, history, replay, status, listen, serve, and schema operations.
- Dashboard templates for Live Feed, History, Inspect, and Replay.
- JavaScript that reloads the page on webhook events.
- Filtering, presets, expression parsing, routing rule models, and storage methods.
- Validation result storage and schema CRUD.
- Documentation and implementation inconsistencies noted in this report.

### Clearly labeled inference used in prioritization

- Developers keep the dashboard open for long sessions.
- Users repeatedly inspect and replay the newest request.
- Users need side-by-side comparison, saved views, and keyboard navigation.
- Team usage is plausible but not yet safely supported.
- Provider-aware views would reduce scanning effort.

These inferences are strongly supported by common behavior in iterative webhook debugging and by capabilities already present in the application, but they should be validated with user research and product telemetry.
