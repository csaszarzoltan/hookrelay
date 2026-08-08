# Hookrelay — Failure Alerting & Delivery Insights: Requirements Analysis & Task Specs

**Feature:** Threshold-based failure alerting (Slack / SMTP email / outbound webhook notifiers) + delivery-insights REST API + dashboard Alerts/Insights views + CLI subcommands (US-001..US-003)
**Repo:** /home/zoltan/hookrelay (branch main, HEAD 8b3837e, v1.6.0, 871 tests green)
**Date:** 2026-08-08
**Author:** analyst (t_c62b22db)
**Idea:** hookrelay-caf266 (state/idea-vault.jsonl, US-001..US-003)
**Parent epic:** t_d00eb8c4
**Status:** ANALYSIS BRIEF — requirements + task specs for the pre-tester (t_8bb289f4) → developer (t_e1822ddb) → tester (t_daf9c7d4) pipeline. No code written. Baseline verified: `.venv/bin/python -m pytest -q` → **871 passed**; `ruff check src tests` → 4 pre-existing fixable errors, all in `tests/test_filters.py` (unused/redefined `pytest` import, F401/F811 — pre-existing, not introduced by this feature).

---

## 0. Executive Summary

Hookrelay v1.6.0 captures, stores, replays and dead-letters every delivery attempt, and its team dashboard already computes success rates and p50/p95/p99 latency — but there is **no alert engine and no per-endpoint insights REST surface** (verified line-level: grep for `AlertRule`/`alert_rules`/`WebhookAlert`/`Notifier` = zero hits in `src/hookrelay`; `/api/dashboard/metrics` is the only metrics endpoint; the only "slack" string in the codebase is a *filter preset* for incoming relay rules in `src/hookrelay/filters.py:304-309`, unrelated to outbound notifications). Operators discover failed deliveries only when a customer complains.

This brief specifies the **failure-alerting + delivery-insights layer** as a set of new modules that follow the repo's existing patterns exactly:

1. **`src/hookrelay/alerts/` package** — `rules.py` (AlertRule dataclass + validate), `storage.py` (alert_rules SQLite table via **migration 6** in `migrations.py`), `evaluator.py` (60s configurable loop, rolling windows, per-rule cooldown, paused rules), `notifiers.py` (Slack incoming webhook, SMTP email, generic outbound webhook) — **reusing `hookrelay.ssrf.validate_target_url` for every outbound target** (Slack URL, outbound webhook URL, and the alert HTTP client), the same guard `EndpointConfig.validate` already enforces for endpoint URLs.
2. **`src/hookrelay/insights/service.py`** — read-only aggregations over the existing `deliveries` + `delivery_attempts` tables (the exact tables `dashboard/metrics.py`, `latency.py`, `success_rate.py` already read), plus **`src/hookrelay/insights/api.py`** exposing `GET /api/insights/endpoints` and `GET /api/insights/timeseries` with 422 validation (mirroring the `/api/dashboard/metrics` handler at `server.py:362-381`).
3. **Dashboard** — an **Alerts tab** (Jinja `alerts.html` following the `index.html`/`settings.html` nav pattern) and an **Insights view** with a time-series chart (zero-dependency inline `<canvas>` JS in `dashboard.js`, the same inline-script pattern the v1.6.0 Bins view uses — no new JS framework).
4. **CLI** — `hookrelay alerts list|create|delete` and `hookrelay insights endpoints|timeseries` Typer subapps, cloned from the existing `schema_app`/`delivery_app`/`dlq_app` subapp pattern (`cli.py:279-284`, 655-691).

**Key decisions (rationale in §3):** stdlib-first implementation (**zero new runtime dependencies** — alert engine, SQLite persistence, SMTP via `smtplib`, HTTP via the already-pinned `requests`); migration-6 SQLite persistence (not `app_settings` JSON — rules need real queries); evaluator runs in a **background thread started by `create_app()`** (blocking HTTP/SMTP, so it must not live on the FastAPI event loop); failure reasons for insights come from `delivery_attempts.error` free-text (bucketed by HTTP status class first, error substring second); UI state via `app_settings` JSON (same as `retention_days`/`backup_policy`).

**Priority split (effort-aware, maps to US-001..003):**
- **P0 (core loop, US-001):** migration 6 + `AlertRuleStore` CRUD, `AlertEvaluator` (all three metric types, cooldown, paused), notifiers (Slack + outbound webhook first; SMTP included in same module), alerts REST + Alerts dashboard tab + `hookrelay alerts` CLI, notifier validation on save with SSRF reuse. → `tests/test_alert_rules.py` (part 1) + `tests/test_alert_evaluator.py` + `tests/test_notifiers.py`.
- **P1 (insights, US-003):** `InsightsService` (endpoints + timeseries), insights REST API with 422 validation, Insights dashboard chart, `hookrelay insights` CLI, SMTP notifier hardening (HTML + auth/TLS), notifier send-history table (migration 7) + audit events. → `tests/test_insights_api.py` + `tests/test_insights_service.py` + `tests/test_alert_history.py`.
- **P2 (optional polish):** DLQ-depth rule with `dlq` table check (US-002 — currently `dlq` table only exists once `DeadLetterQueue` runs, so the rule is safe-but-noisy on fresh DBs; documented as P2), per-notifier test button, multi-channel fan-out, alert recovery (OK) notifications.

---

## 1. Current State Assessment

### 1.1 Verified repo state (hookrelay @ 8b3837e, v1.6.0, branch main, remote csaszarzoltan/hookrelay)

| Layer | Location | Verified pattern |
|---|---|---|
| Persistence | `src/hookrelay/storage.py` (1252 lines) | single `sqlite3` connection (`check_same_thread=False`, `Row` factory); `_init_schema()` creates tables with `CREATE TABLE IF NOT EXISTS`; **explicit versioned migrations** in `migrations.py` (`CURRENT_SCHEMA_VERSION = 5`, dict `_MIGRATIONS[version] = (name, sql)`, applied transactionally + recorded in `schema_migrations`); `app_settings` key/value JSON table (`set_setting`/`get_setting`) used for `retention_days`, `backup_policy` |
| Delivery data | `delivery_attempts` table (`storage.py:105-120`) | per-attempt rows: `attempt_id, request_id, delivery_id, channel, endpoint_id, target_url, status, response_status, duration_ms, error, response_headers, response_body, attempted_at` — **all the data alert windows and insights need is already persisted**; `store_delivery_attempt` (`storage.py:495`) redacts sensitive headers, truncates response bodies at 16 KB |
| Deliveries (canonical) | `deliveries` table (schema in `delivery/tracker.py:25-46`) | `delivery_id, request_id, endpoint_id, target_url, method, headers, body, idempotency_key, status, attempt_count, next_attempt_at, last_error, policy, created_at, updated_at`; statuses `pending/delivered/failed/in-dlq`; indexes on `(status, next_attempt_at)` and `(endpoint_id)` |
| DLQ | `src/hookrelay/delivery/dlq.py` | `dlq` table (created lazily by `DeadLetterQueue._ensure_schema`, NOT in migrations); `count()`, `list_entries(limit, endpoint_id)`, `requeue()` |
| Dashboard analyzers | `src/hookrelay/dashboard/metrics.py`, `latency.py`, `success_rate.py` | all **read-only** over `deliveries`/`delivery_attempts` with rolling `window_minutes` cutoffs (`created_at >= now - window`); `LatencyTracker.percentiles()` → p50/p95/p99 nearest-rank; `SuccessRateCalculator.rate()` → delivered/(delivered+failed), pending excluded; `MetricsCollector.time_series(bucket_minutes, window_minutes)` → zero-filled chronological buckets. **Insights should reuse these exact queries, not duplicate them** |
| Dashboard composition | `src/hookrelay/dashboard/service.py` | `DashboardService.summary/time_series/endpoint_breakdown` |
| Metrics endpoint | `server.py:362-381` `GET /api/dashboard/metrics` | FastAPI query params + **manual 422 via `HTTPException`** (not Pydantic `Query(ge=...)` — that returns FastAPI's default 422 body; both patterns exist in the repo, the manual one is what `/api/dashboard/metrics` uses) |
| SSRF guard | `src/hookrelay/ssrf.py` | `validate_target_url(url, allow_private=False, allowed_protocols=("http","https")) -> (bool, reason)`; blocks private ranges, link-local, CGNAT, system ports < 1024, re-resolves DNS on every call (rebinding-safe). **Reuse for Slack URL + outbound webhook URL + alert HTTP client** — same as `EndpointConfig.validate` (`config/endpoint.py:42-64`) |
| Server wiring | `src/hookrelay/server.py` `create_app()` | routers **mounted flat** (`app.router.routes.append(route)` — Starlette `include_router` wrapping breaks tests iterating `app.routes`; see comment at `server.py:609-612`); auth middleware: public paths list (add `/api/insights/`, `/api/alerts/` are NOT public — they stay token-protected); `_get_or_create_storage()` returns process-wide store |
| Dashboard UI | `src/hookrelay/dashboard/__init__.py` `create_dashboard_router()` | **two coexisting patterns**: (a) Jinja2 templates (`index.html`/`history.html`/`settings.html`; nav = `<nav class="dashboard-nav">` with `.nav-links` `<a>` items; `templates = Jinja2Templates(...)` at `dashboard/__init__.py:32`); (b) v1.6.0 Bins view (`bins/dashboard.py`) = **inline HTML string + inline `<script>`** served via its own router, with an `esc()` helper and `fetch()` calls — zero new JS framework |
| Live feed | `dashboard/connection_manager.py` + `/dashboard/ws/live` | `ConnectionManager` broadcast; Bins view subscribes for `bin.capture` events (pattern available for future alert events) |
| CLI | `src/hookrelay/cli.py` (746 lines, Typer) | **backend functions with plain signatures + thin `@app.command` wrappers** (testable without Typer); subapps via `app.add_typer(x_app, name="x")` — `schema` (line 284), `delivery` (655), `dlq` (679); `_get_storage()` at line 37 |
| Tests | `tests/` (37 modules) | `conftest.py` autouse session fixture seeds a global storage + schemas; tests use `TestClient` (httpx2 pinned in dev extra); TDD interface-first pattern (see `tests/test_dashboard.py` docstring) |
| Deps | `pyproject.toml` | Python 3.11+, FastAPI, uvicorn, Jinja2, `requests>=2.32,<3`, `typer>=0.12,<1`, `jsonschema`, `cryptography`, `websocket-client`; dev: pytest, pytest-asyncio, **httpx2**, ruff. **No SMTP/HTTP libs needed — stdlib `smtplib` + pinned `requests` cover everything** |

### 1.2 Gap analysis (what does NOT exist — verified line-level 2026-08-08)

- No `alerts/` package, no `AlertRule`/`AlertRuleStore`, no alert evaluator, no notifier code (grep `AlertRule|alert_rules|WebhookAlert|Notifier` in `src/hookrelay` = zero hits).
- No `insights/` package; no per-endpoint insights REST (`/api/insights/*` absent; `/api/dashboard/metrics` is the only metrics endpoint).
- No `alert_rules` table and no migration 6 (migrations cap at v5).
- No `alerts`/`insights` CLI subcommands.
- No Alerts/Insights dashboard views; nav has Live Feed / History / Bins / Backups / Settings only.
- No SMTP/Slack/outbound-webhook notification code (the "slack" string at `filters.py:304` is an incoming-rule filter preset, not a notifier).
- No alert fire history / send log table.

### 1.3 Constraints & risks (verified)

| Risk | Detail | Mitigation |
|---|---|---|
| No alert engine today | zero alert/notifier code (verified) | greenfield modules, but on well-understood storage + analyzer patterns |
| `deliveries`/`dlq` tables are lazily created | `DeadLetterQueue._ensure_schema()` creates `deliveries`/`dlq` on first use; a fresh DB may lack them until a delivery runs | all readers must guard with the existing `_deliveries_table_exists()` pattern (`metrics.py:21-30`, `latency.py:18-23`) — missing table ⇒ treat as empty; **do not raise** |
| Evaluator does blocking I/O (HTTP/SMTP) | running it on the FastAPI event loop would stall every endpoint | background **thread** (daemon) started by `create_app()`; interval from `app_settings` `alert_interval_seconds` (default 60); no asyncio |
| Notifier URLs are SSRF targets | Slack webhook URLs and outbound webhook URLs are user-supplied URLs the server will POST to | reuse `ssrf.validate_target_url` on save AND at fire time (same as `EndpointConfig.validate`); `allow_private=False` by default — tests use `127.0.0.1` via an explicit test-only `allow_private` override on the notifier client (documented) |
| Alert storms | a rule firing every 60s cycle | per-rule `cooldown_minutes` (default 15), `last_fired_at` persisted in the rules table, `paused` flag |
| No failure-reason taxonomy | insights "top failure reason" needs a reason per failed delivery | derive from `delivery_attempts.error` free-text, bucketed by `response_status` class (5xx/4xx/timeout/conn/other) first, error substring second; documented as a derived field |
| Thread/DB safety | evaluator thread + API handlers share one `sqlite3` connection (`check_same_thread=False` already) | serialized access is acceptable at this scale (SQLite write lock); evaluator uses short transactions; no long-lived cursors across cycles |
| Two dashboard UI patterns | Jinja templates (index/settings) AND inline-HTML router (Bins) coexist | Alerts tab = **Jinja** (matches nav + form patterns; auth middleware already routes `/dashboard/*` through token check); Insights chart = inline `<canvas>` JS in `dashboard.js` (matches Bins inline-script precedent, zero deps) |
| Migration discipline | repo has strict `_MIGRATIONS` dict + `schema_migrations` ledger; tests assert `schema_version` | add migration **6** (`alert-rules`); do not create tables ad-hoc in `Storage.__init__` |
| 422 contract | parent epic requires 422 on bad window/bucket | manual `HTTPException(422)` in the handler (the `/api/dashboard/metrics` pattern), not bare FastAPI validation |
| Baseline ruff | `tests/test_filters.py` already has 4 fixable F401/F811 errors | **pre-existing** (verified before this feature); do not fix in this feature's scope unless trivial — note in PR |

---

## 2. Clustered Options

### 2.1 Alert-rule persistence

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. SQLite `alert_rules` table via migration 6** | real queries (list by endpoint/type, `last_fired_at` updates); matches `bins`/`deliveries` precedent; restart-safe | one migration to write | ✅ **Chosen** |
| B. `app_settings` JSON blob | zero schema work | rules not queryable; concurrent updates clobber; last_fired_at bookkeeping awkward | ❌ |
| C. Separate JSON file | human-editable | no atomicity, no shared-conn pattern, diverges from repo | ❌ |

### 2.2 Evaluator execution model

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Daemon background thread started by `create_app()`** | blocking HTTP/SMTP fine; no event-loop stalls; interval from settings; stops on process exit | thread lifecycle must be careful (daemon=True) | ✅ **Chosen** |
| B. FastAPI `BackgroundTasks`/asyncio task | async-native | blocking notifiers would stall the loop; no periodic loop primitive; harder to test deterministically | ❌ |
| C. APScheduler | cron-style | new runtime dep; overkill; repo pattern is explicit loops (`backup_is_due`/`run_scheduled_backup` already poll-based) | ❌ |
| D. CLI-only trigger | simplest | no "react in minutes" story (epic goal) | ❌ |

### 2.3 Notifier transport

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. stdlib `smtplib` (SMTP) + pinned `requests` (Slack + outbound webhook)** | **zero new runtime deps**; `requests` already in `pyproject.toml`; smtplib battle-tested | SMTP needs TLS/STARTTLS handling (P1 hardening) | ✅ **Chosen** |
| B. `httpx` for HTTP notifiers | already in dev extra | not a runtime dep; async client adds complexity for a thread-based evaluator | ❌ |
| C. `email-validator`/`slack-sdk` packages | richer validation | new deps; slack-sdk unnecessary for incoming webhooks (plain POST) | ❌ |

### 2.4 Insights aggregation source

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. New `InsightsService` over `deliveries` + `delivery_attempts`, reusing analyzer queries** | single source of truth; latency percentiles already proven (`LatencyTracker`); per-endpoint breakdown already proven (`SuccessRateCalculator.breakdown`) | needs a thin new module (no duplication) | ✅ **Chosen** |
| B. Reuse `DashboardService` directly | zero new code | its payloads are dashboard-shaped (summary strip), not per-endpoint insights-shaped; timeseries has no latency/failure-reason | ❌ |
| C. SQLAlchemy/Alembic rewrite | production-grade | not repo pattern (raw sqlite3 everywhere); massive scope | ❌ |

### 2.5 Failure-reason taxonomy

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Derived: status-class bucket first (`5xx`/`4xx`/`timeout`/`connection`/`other`), then `error` substring** | zero schema change; deterministic; testable | heuristic | ✅ **Chosen** |
| B. New `failure_reason` column + classification at store time | precise | schema change + classification pass on every attempt; more scope | ❌ (P2 candidate) |

### 2.6 Dashboard UI approach

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Jinja Alerts tab (`alerts.html`, nav item) + inline `<canvas>` chart in `dashboard.js`** | matches both repo patterns (Jinja for pages, inline JS for interactive views — Bins precedent); no new framework | chart is hand-rolled (fine: one line graph) | ✅ **Chosen** |
| B. Chart.js via CDN | prettier charts | new external dep; offline/self-host story breaks; CSP/security gate friction | ❌ |
| C. Server-rendered `<table>` only | simplest | not a "chart" (epic AC5 requires a time-series chart) | ❌ |

---

## 3. Chosen Tech Stack (with rationale)

| Layer | Choice | Rationale |
|---|---|---|
| Backend framework | FastAPI (existing) | repo standard; manual 422 pattern at `/api/dashboard/metrics` |
| Persistence | SQLite — **migration 6** `alert_rules` table + `app_settings` JSON for interval/notifier config + `alert_history` (migration 7, P1) | repo pattern (`migrations.py` dict + `schema_migrations`); zero new infra |
| Alert rules | `AlertRule` frozen dataclass + `validate()` (clone `EndpointConfig` pattern) | dataclass + strict validation matches `config/endpoint.py`; no ORM |
| Evaluator | `AlertEvaluator` class with `run_once()`/`start()`/`stop()`; daemon thread with `interval` from settings (default 60s) | testable `run_once()`; thread keeps blocking notifiers off the event loop; mirrors `backup_is_due` poll philosophy |
| Rolling windows | per-rule `window_minutes` (default 15) over `deliveries.created_at`; same cutoff SQL as `SuccessRateCalculator` | proven query shape; no new aggregation code |
| Notifiers | `Notifier` ABC + `SlackNotifier` (incoming webhook POST), `SmtpNotifier` (stdlib smtplib), `WebhookNotifier` (generic JSON POST) + `NotifierRegistry` | ABC matches `TTSProvider`/`LLMProvider` precedent; registry gives fan-out + testability |
| SSRF | **reuse `hookrelay.ssrf.validate_target_url`** on save + at fire time; `allow_private=False`; test-only override documented | same guard `EndpointConfig.validate` uses; security gate expects reuse, not a fork |
| Insights | `InsightsService` (read-only) composing `MetricsCollector`/`LatencyTracker`/`SuccessRateCalculator` + failure-reason classifier; router `insights/api.py` with manual 422 | reuses proven analyzers; no duplication |
| UI | Jinja `alerts.html` + nav item; Insights `<canvas>` line chart in `dashboard.js`; `esc()` helper for any injected strings | both repo patterns (index.html Jinja; Bins inline JS); zero new JS deps |
| CLI | Typer subapps `alerts` + `insights` (backend functions + thin wrappers) | `schema`/`delivery`/`dlq` subapp precedent |
| HTTP client | `requests` (already pinned `>=2.32,<3`) with `timeout=10`, no redirects for outbound notifier | existing dep; redirect-following is an SSRF bypass vector — disable |
| Runtime deps | **none added** | smtplib is stdlib; requests already pinned; evaluator is stdlib `threading` |
| Tests | pytest + `TestClient` (httpx2, dev extra) — same as `test_bins_api.py`; mock SMTP via `smtpd`-style fake server or monkeypatched `smtplib`; mock HTTP via `responses`-free `requests` monkeypatch or a local `http.server` thread | repo test patterns; no new test deps required (monkeypatch is stdlib pytest) |

---

## 4. Prioritized Task List (P0 / P1 / P2)

> Each task spec includes **module name, expected behavior, interface description, and dependencies**. The pre-tester (t_8bb289f4) writes the RED test files named below; the developer (t_e1822ddb) implements to those interfaces; the tester (t_daf9c7d4) runs the full-suite gate. See §5 for acceptance criteria per task.

### P0 — Alert engine core loop (US-001)

**P0-1. Migration 6: `alert_rules` table + `AlertRuleStore`**
- **Module:** `src/hookrelay/migrations.py` (migration 6), `src/hookrelay/alerts/rules.py`, `src/hookrelay/alerts/storage.py`
- **Expected behavior:** `CURRENT_SCHEMA_VERSION` → 6; migration 6 creates `alert_rules` (`rule_id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT NOT NULL, endpoint_id TEXT, metric TEXT NOT NULL, threshold REAL NOT NULL, window_minutes INTEGER NOT NULL DEFAULT 15, cooldown_minutes INTEGER NOT NULL DEFAULT 15, enabled INTEGER NOT NULL DEFAULT 1, notifier_ids TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL` + index on `(scope, endpoint_id)`). Store CRUD round-trips rules, persists `last_fired_at` (column `last_fired_at TEXT`), survives restart (new `Storage` instance on same DB sees rules). `AlertRule.validate()` raises `ValueError` on bad metric/threshold/scope/window.
- **Interfaces:**
  - `AlertRule` frozen dataclass: `rule_id: str, name: str, scope: Literal["all","endpoint"], endpoint_id: str | None, metric: Literal["success_rate_below","consecutive_failures","dlq_depth_above"], threshold: float, window_minutes: int = 15, cooldown_minutes: int = 15, enabled: bool = True, notifier_ids: list[str] = [], created_at: str, updated_at: str, last_fired_at: str | None = None`; `to_dict()`, `from_dict()`, `validate()`.
  - `AlertRuleStore(storage: Storage)` — `create(rule: AlertRule) -> str`, `get(rule_id) -> AlertRule | None`, `list() -> list[AlertRule]`, `update(rule_id, **fields) -> AlertRule`, `delete(rule_id) -> bool`, `mark_fired(rule_id, at: str)`, `set_enabled(rule_id, enabled: bool) -> bool` (delete/update raise `KeyError` on unknown id, mirroring `DeadLetterQueue.requeue`).
- **Dependencies:** `storage.py` connection, `migrations.py`; none new.

**P0-2. Alert evaluator (60s configurable loop, rolling windows, cooldown, paused rules)**
- **Module:** `src/hookrelay/alerts/evaluator.py`
- **Expected behavior:** `run_once()` computes each enabled rule's metric over its rolling `window_minutes` from stored `deliveries`/`dlq` rows; fires (via notifier registry) only when threshold crossed AND `now - last_fired_at >= cooldown_minutes` (default 15 min); paused (`enabled=False`) rules never fire; `start(interval_seconds=60)` launches a daemon thread running `run_once()` on the interval until `stop()`; thread-safe via a `threading.Event`; a rule that cannot be evaluated (missing `deliveries` table, no data) does not fire and does not raise.
- **Interfaces:** `class AlertEvaluator(store: AlertRuleStore, notifier_registry: NotifierRegistry, *, now: Callable[[], datetime] = default_now)` — `run_once() -> list[FiredAlert]` (each `{rule_id, rule_name, metric, observed_value, threshold, message}`), `start(interval_seconds: int | None = None)`, `stop()`, `is_running() -> bool`; `evaluate_metric(rule: AlertRule) -> float | None` (pure-ish, returns None when no data — **unit-testable with seeded storage**); window cutoff identical to `SuccessRateCalculator` (`created_at >= now - timedelta(minutes=window_minutes)`).
- **Metric semantics (unit-test contract):** `success_rate_below`: rate = delivered/(delivered+failed) over window; fires when `rate < threshold` (e.g. threshold 0.9). `consecutive_failures`: count of consecutive `failed`/`in-dlq` deliveries per endpoint (or all) up to now; fires when `count >= threshold` (e.g. 5). `dlq_depth_above`: `DeadLetterQueue(storage).count()` (or per-endpoint `list_entries` count) >= threshold (P2 for per-endpoint; P0 evaluates overall count).
- **Dependencies:** P0-1 store, `delivery/dlq.py`, dashboard analyzer query shapes, notifiers (P0-3).

**P0-3. Notifiers: Slack incoming webhook, SMTP email, generic outbound webhook (+ registry, SSRF-protected)**
- **Module:** `src/hookrelay/alerts/notifiers.py`
- **Expected behavior:** `Notifier` ABC (`send(alert: dict) -> bool`, `validate() -> None` raising `ValueError`, `type: str`, `health() -> bool`); three implementations:
  - `SlackNotifier(webhook_url)` — POST `{text: "<hookrelay> <alert message>"}` to the Slack incoming-webhook URL; `validate()` runs `ssrf.validate_target_url` (http/https only) and rejects non-Slack-host targets only if desired (default: any SSRF-safe https URL is accepted — keep the guard, not host allowlists);
  - `SmtpNotifier(host, port=587, username=None, password=None, from_addr, to_addrs: list[str])` — stdlib `smtplib` with STARTTLS when available; `validate()` checks host/port/from/to presence and from-addr basic shape;
  - `WebhookNotifier(url, headers=None)` — generic POST with JSON payload `{"alert": {...}, "type": "hookrelay.alert", "version": 1}`; **SSRF guard on save + at fire**; `requests.post(..., timeout=10, allow_redirects=False)` (redirect-following is an SSRF bypass).
  - `NotifierRegistry` — `register(notifier)`, `get(notifier_id) -> Notifier`, `send_to(notifier_ids, alert) -> dict[str, bool]` (per-notifier success map; one failure never blocks others).
  - Config persistence (P0 minimal): notifier definitions stored as JSON in `app_settings` under key `alert_notifiers` (`{notifier_id: {...}}`); `validate()` runs on save; failed validation → 422 at the API/CLI boundary.
- **Interfaces:** `class Notifier(ABC): type: str; def send(self, alert: dict) -> bool; def validate(self) -> None; def health(self) -> bool`; `class NotifierRegistry: register, get, send_to, list_notifiers() -> list[dict]`; module helpers `validate_notifier_payload(payload: dict) -> Notifier` (raises `ValueError` with reason on invalid URL/SSRF/type).
- **Dependencies:** `ssrf.py` (reused), `requests` (pinned), stdlib `smtplib`/`email.message`; none new.

**P0-4. Alerts REST API (rules CRUD + notifiers CRUD, 422 on invalid)**
- **Module:** `src/hookrelay/alerts/api.py` — router mounted in `create_app()` **flat** (`app.router.routes.append` — see `server.py:609-612` comment), NOT public (token-protected by existing middleware).
- **Expected behavior:**
  - `GET  /api/alerts/rules` → `{rules: [...]}` (all rules).
  - `POST /api/alerts/rules` body `{name, scope, endpoint_id?, metric, threshold, window_minutes?, cooldown_minutes?, enabled?, notifier_ids?}` → 201 `{rule_id, ...}`; 422 on bad metric/threshold/scope/empty name; 404 on unknown `notifier_id`.
  - `PATCH /api/alerts/rules/{rule_id}` → `{...}` (partial update; `enabled` toggle for the dashboard switch); 404 unknown; 422 invalid fields.
  - `DELETE /api/alerts/rules/{rule_id}` → 204; 404 unknown.
  - `GET  /api/alerts/notifiers` → `{notifiers: [...]}`; `POST /api/alerts/notifiers` body `{type: "slack"|"smtp"|"webhook", ...}` → 201; 422 on SSRF/validation failure (`ValueError` → `HTTPException(422, detail=str(e))`); `DELETE /api/alerts/notifiers/{notifier_id}` → 204.
  - `GET /api/alerts/status` → `{interval_seconds, evaluator_running, last_run_at}` (useful for the dashboard + tests).
  - All error bodies JSON `{"detail": ...}`.
- **Interfaces:** router function `create_alerts_router() -> APIRouter`; request/response via plain dicts (repo style — `bins/api.py` uses `dict[str, Any] | None` bodies, not pydantic models for CRUD; keep that).
- **Dependencies:** P0-1 store, P0-3 registry, P0-2 evaluator (for status).

**P0-5. Evaluator startup wiring in `create_app()`**
- **Module:** `src/hookrelay/server.py`
- **Expected behavior:** `create_app()` builds `AlertEvaluator` + starts the daemon thread with interval from `get_setting("alert_interval_seconds", 60)`; interval is overridable via `set_setting` (test hook: `stop()` then restart with test interval, or construct evaluator directly in tests); evaluator stop is best-effort on process exit (daemon thread — no shutdown hook needed, but `atexit`/lifespan cleanup is a P1 nicety).
- **Dependencies:** P0-2, P0-3.

**P0-6. Dashboard Alerts tab (Jinja)**
- **Module:** `src/hookrelay/dashboard/__init__.py` (route) + `src/hookrelay/dashboard/templates/alerts.html` (+ nav item in `index.html` — `Alerts` link between History and Backups)
- **Expected behavior:** `GET /dashboard/alerts` renders rules list (name, scope, metric, threshold, window, cooldown, enabled badge, last fired) + create form (metric select, scope select, threshold number, window/cooldown minutes, notifier multi-select) + enable/disable toggle buttons (PATCH) + delete buttons (DELETE, confirm); all mutations via `fetch()` to `/api/alerts/*`; server-rendered initial state; `esc()`-style escaping for all injected values (Jinja autoescaping covers templates; JS must use textContent or an esc helper for API-driven rows); no error overlay (alert banner with `role="alert"`).
- **Interfaces:** `create_dashboard_router()` gains `GET /dashboard/alerts` → `TemplateResponse(request, "alerts.html", {rules, notifiers, interval_seconds})`.
- **Dependencies:** P0-4 API; existing Jinja patterns.

**P0-7. CLI: `hookrelay alerts list|create|delete`**
- **Module:** `src/hookrelay/cli.py` — `alerts_app = typer.Typer(name="alerts")`, `app.add_typer(alerts_app, name="alerts")` + backend functions `alerts_list() -> list[dict]`, `alerts_create(name, scope, metric, threshold, endpoint_id, window_minutes, cooldown_minutes, notifier_ids) -> dict`, `alerts_delete(rule_id) -> bool` (mirroring `schema_*` backend functions at `cli.py:343-445`); output JSON (list) / human line (create/delete), mirroring `_schema_*_cmd` echo style.
- **Dependencies:** P0-1 store.

### P1 — Delivery Insights + notifier hardening (US-003)

**P1-1. InsightsService (endpoints + timeseries)**
- **Module:** `src/hookrelay/insights/service.py`
- **Expected behavior:** read-only aggregations over `deliveries` + `delivery_attempts`:
  - `endpoints(window: str = "24h") -> list[dict]`: per endpoint `{endpoint_id, deliveries, success_rate, p50_ms, p95_ms, p99_ms, top_failure_reason}` — reuse `MetricsCollector.count_by_endpoint`, `SuccessRateCalculator.breakdown`, `LatencyTracker.percentiles(endpoint_id=...)` with the window converted to `window_minutes`; `top_failure_reason` from the classifier below; endpoint list sorted by endpoint_id.
  - `timeseries(metric: str = "deliveries", window: str = "24h", bucket: str = "hourly") -> list[dict]`: buckets `{bucket, value}` (plus `delivered`/`failed` for metric=deliveries) — reuse `MetricsCollector.time_series(bucket_minutes, window_minutes)`; metrics: `deliveries` (delivered/failed counts), `success_rate` (per-bucket rate), `latency_p95` (per-bucket p95 from delivery_attempts.duration_ms).
  - `classify_failure_reason(row) -> str`: status-class bucket (`5xx`, `4xx`, `timeout`, `connection`, `other`) from `response_status`/`error` — pure function, unit-testable.
  - **Window parsing helper** `parse_window(window: str) -> int minutes` supporting `15m`, `1h`, `24h`, `7d` (default 24h); invalid → `ValueError` (API layer turns it into 422).
  - **Bucket parsing** `parse_bucket(bucket: str) -> int minutes`: `hourly` → 60, `daily` → 1440 (default hourly); anything else → `ValueError`.
  - Missing `deliveries` table → empty results (same guard as analyzers), never raises.
- **Dependencies:** `dashboard/metrics.py`, `dashboard/latency.py`, `dashboard/success_rate.py` (reuse, do not duplicate).

**P1-2. Insights REST API with 422 validation**
- **Module:** `src/hookrelay/insights/api.py` — router mounted flat in `create_app()`; NOT public.
- **Expected behavior:**
  - `GET /api/insights/endpoints?window=24h` → `{window, endpoints: [...]}`; 422 for invalid window (`detail`: `"window must be one of 15m, 1h, 24h, 7d"`).
  - `GET /api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly` → `{metric, window, bucket, buckets: [...]}`; 422 for invalid metric (`deliveries|success_rate|latency_p95`), invalid window, invalid bucket (`hourly|daily`). Manual `HTTPException(status_code=422, ...)` exactly like `/api/dashboard/metrics` (`server.py:362-381`).
- **Dependencies:** P1-1.

**P1-3. Dashboard Insights view (time-series chart)**
- **Module:** `src/hookrelay/dashboard/__init__.py` + `templates/insights.html` + `static/dashboard.js` (chart renderer)
- **Expected behavior:** `GET /dashboard/insights` renders an Insights page: endpoint table (from `/api/insights/endpoints`) + a `<canvas>` line chart of deliveries (delivered vs failed, or success rate) over the last 24h fetched from `/api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly`; chart drawn with plain Canvas 2D in `dashboard.js` (function `renderInsightsChart(canvas, buckets)`), no external libs; nav link `Insights` in `index.html`; no console errors; `esc()` for API-driven text.
- **Dependencies:** P1-2 API; existing inline-JS precedent (Bins view).

**P1-4. CLI: `hookrelay insights endpoints|timeseries`**
- **Module:** `src/hookrelay/cli.py` — `insights_app = typer.Typer(name="insights")`; backend `insights_endpoints(window: str = "24h") -> list[dict]`, `insights_timeseries(metric: str = "deliveries", window: str = "24h", bucket: str = "hourly") -> list[dict]`; echo JSON (mirrors `schema_get` output style).
- **Dependencies:** P1-1 service (direct storage access, like `alerts_*` use the store).

**P1-5. SMTP notifier hardening + notifier config surface**
- **Module:** `src/hookrelay/alerts/notifiers.py` (+ `alerts/api.py`)
- **Expected behavior:** SMTP supports `use_tls`/`starttls` flags + auth; `health()` does a real SMTP `NOOP` (wrapped in try/except, never raises); alerts API gains `POST /api/alerts/notifiers/{id}/test` → fires a synthetic alert through the notifier, returns `{ok: bool, detail}` (mocked in tests); notifier list returns `{type, id, summary}` with secrets redacted (never echo `password`/webhook URL query tokens).
- **Dependencies:** P0-3, P0-4.

**P1-6. Alert fire history + audit (migration 7)**
- **Module:** `src/hookrelay/migrations.py` (migration 7: `alert_history` table `(event_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, rule_name TEXT, metric TEXT, observed_value REAL, threshold REAL, message TEXT, fired_at TEXT NOT NULL)`) + `AlertRuleStore.record_fire(...)` + `list_history(rule_id=None, limit=100)`
- **Expected behavior:** every fire is persisted; `GET /api/alerts/history?rule_id=&limit=` returns newest-first entries; `record_audit_event("alert.fired", "evaluator", "alert_rule", rule_id, "success", details={...})` on each fire (repo audit pattern, `storage.py:317`); evaluator failure to send → audit `"alert.failed"` + history row still written with `delivered: false` marker (P1 keeps it simple: history row + audit, no retry queue).
- **Dependencies:** P0-1, P0-2, `storage.py` audit.

### P2 — Optional polish (in-cycle only if P0/P1 land clean)

- **P2-1. Per-endpoint DLQ-depth rules** — `dlq_depth_above` with `endpoint_id` scope: count `dlq` rows filtered by endpoint via `DeadLetterQueue.list_entries`; on fresh DBs with no `dlq` table the rule evaluates as no-data (never fires). (US-002 core is the *metric*; overall count ships in P0-2, per-endpoint is P2.)
- **P2-2. Recovery (OK) notifications** — fire a second alert when a rule's metric returns to healthy (cooldown-independent), so operators get "resolved" pings; requires tracking `fired_at` + healthy-state in the evaluator.
- **P2-3. `alert.fired` live event** — broadcast fires over `/dashboard/ws/live` (`ConnectionManager.broadcast({"type": "alert.fired", ...})`) so the dashboard can flash a banner without polling.
- **P2-4. Notifier test button in the dashboard Alerts tab** (wires P1-5 `/test` endpoint).
- **P2-5. Failure-reason column** — classification at store time (`delivery_attempts.failure_reason`), replacing derived classification in P1-1.

---

## 5. Acceptance Criteria per Task

### 5.1 P0-1 Migration 6 + AlertRuleStore
- [ ] `CURRENT_SCHEMA_VERSION == 6`; `Storage(db).schema_version == 6` after init; `migration_history()` contains version 6 `alert-rules`.
- [ ] `alert_rules` table exists with all columns + `(scope, endpoint_id)` index; idempotent re-init (fresh + pre-existing v5 DB both migrate cleanly; schema_migrations ledger records v6 once).
- [ ] `create`/`get`/`list`/`update`/`delete` round-trip all fields incl. `notifier_ids` (list↔JSON) and `last_fired_at`; unknown id → `KeyError` for update/delete; `mark_fired` persists timestamp.
- [ ] `AlertRule.validate()` rejects: empty name, unknown metric, threshold out of (0, 1] for `success_rate_below`, threshold < 1 for `consecutive_failures`/`dlq_depth_above`, `scope="endpoint"` without `endpoint_id`, window/cooldown < 1.
- [ ] Restart-safe: a second `Storage`/`AlertRuleStore` on the same DB sees the rules.

### 5.2 P0-2 Alert evaluator
- [ ] `evaluate_metric` returns correct values for all three metrics from seeded `deliveries`/`dlq` rows (rate math identical to `SuccessRateCalculator`; consecutive-failure count; dlq depth).
- [ ] `run_once` fires only when threshold crossed; respects `cooldown_minutes` (second fire before cooldown elapses is suppressed; after cooldown fires again); `enabled=False` rules never fire.
- [ ] No data / missing `deliveries` table → no fire, no exception.
- [ ] `start(interval_seconds=...)` runs `run_once` periodically in a thread; `stop()` halts; `is_running()` reflects state.
- [ ] Fired alerts carry `{rule_id, rule_name, metric, observed_value, threshold, message}`.

### 5.3 P0-3 Notifiers
- [ ] SlackNotifier POSTs `{"text": ...}` to the webhook URL (monkeypatched `requests.post` in tests; SSRF-invalid URL rejected by `validate()`).
- [ ] WebhookNotifier POSTs JSON with `allow_redirects=False`, `timeout=10`; **SSRF guard blocks private/link-local/system-port targets on save and at fire** (parameterized tests against `ssrf.validate_target_url` cases); `allow_private=True` test hook exists and is documented as test-only.
- [ ] SmtpNotifier sends via `smtplib` (monkeypatched SMTP in tests: message has From/To/Subject/Body; STARTTLS attempted when offered); `validate()` rejects empty host/port/from/to.
- [ ] `NotifierRegistry.send_to([ids], alert)` returns per-id success map; one failing notifier doesn't block others.
- [ ] Notifier definitions persist under `app_settings["alert_notifiers"]`; invalid payload (bad type/URL/SSRF) raises `ValueError` → 422 at API/CLI boundary.

### 5.4 P0-4 Alerts REST API
- [ ] Rules CRUD: 201 create (with `rule_id`), 200 list/PATCH, 204 DELETE; 404 unknown rule; 422 bad metric/threshold/scope/empty name; 404 unknown notifier_id on create.
- [ ] Notifiers CRUD: 201/200/204; 422 on SSRF/validation failure (`{"detail": ...}`); 404 unknown.
- [ ] `GET /api/alerts/status` returns `{interval_seconds, evaluator_running, last_run_at}`.
- [ ] All error bodies JSON `{"detail": ...}`; endpoints NOT public (401 when `HOOKRELAY_TOKEN` set and no auth header — existing middleware covers, add one test).

### 5.5 P0-5 Evaluator wiring
- [ ] `create_app()` starts the evaluator thread; interval read from `alert_interval_seconds` setting (default 60); setting change honored on next start.
- [ ] No regression: full suite still green (`871 + new` passed via `.venv/bin/python -m pytest -q`).

### 5.6 P0-6 Dashboard Alerts tab
- [ ] `GET /dashboard/alerts` 200 (auth middleware applies), renders rules + notifier multi-select + create form; server-rendered initial state matches `/api/alerts/rules`.
- [ ] Enable/disable toggle PATCHes `enabled` and re-renders the badge without page reload; delete requires confirm; create posts and refreshes the list.
- [ ] No error overlay; API errors render a `role="alert"` banner; no console errors (JS uses textContent/esc for API-driven strings).

### 5.7 P0-7 Alerts CLI
- [ ] `hookrelay alerts list` prints JSON array of rules (empty → "No alert rules found."); `create` prints created rule JSON; `delete` prints confirmation; unknown rule → exit code 1 with message (mirrors `_schema_*_cmd`/`schema_delete` behavior at `cli.py:323-329`).
- [ ] Backend functions `alerts_list`/`alerts_create`/`alerts_delete` are plain-python testable (no typer dependency in signatures).

### 5.8 P1-1 InsightsService
- [ ] `endpoints("24h")` returns per-endpoint `{endpoint_id, deliveries, success_rate, p50_ms, p95_ms, p99_ms, top_failure_reason}`; values match the analyzer outputs on the same seeded data.
- [ ] `timeseries("deliveries","24h","hourly")` returns 24 zero-filled hourly buckets with delivered/failed counts (same shape as `MetricsCollector.time_series` + value aggregation); `success_rate` and `latency_p95` metrics return per-bucket values (None buckets for no data).
- [ ] `classify_failure_reason` maps: response_status 5xx → `"5xx"`, 4xx → `"4xx"`, timeout error text → `"timeout"`, connection-refused/DNS error text → `"connection"`, else `"other"`.
- [ ] `parse_window` accepts `15m/1h/24h/7d`; `parse_bucket` accepts `hourly/daily`; invalid → `ValueError`.
- [ ] Missing `deliveries` table → empty lists, no exception.

### 5.9 P1-2 Insights REST API
- [ ] `GET /api/insights/endpoints?window=24h` 200 shape `{window, endpoints}`; `window=99` → **422** with `{"detail": "window must be one of 15m, 1h, 24h, 7d"}`.
- [ ] `GET /api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly` 200 shape `{metric, window, bucket, buckets}`; invalid metric → 422; invalid bucket (`weekly`) → 422.
- [ ] Endpoints NOT public (401 without auth when token configured).
- [ ] No regression on `/api/dashboard/metrics` (both endpoints coexist).

### 5.10 P1-3 Insights dashboard view
- [ ] `GET /dashboard/insights` 200; endpoint table populated from the API; `<canvas>` chart renders (assert canvas element present + JS path exercised via browser-helper/E2E); nav link `Insights` present on all dashboard pages; no console errors.

### 5.11 P1-4 Insights CLI
- [ ] `hookrelay insights endpoints` / `hookrelay insights timeseries` print JSON; invalid window → error + exit code 1.

### 5.12 P1-5 SMTP hardening + notifier test endpoint
- [ ] SMTP STARTTLS/auth flags honored (monkeypatched smtplib asserts `starttls()`/`login()` called when configured); `health()` returns bool without raising.
- [ ] `POST /api/alerts/notifiers/{id}/test` returns `{ok: true, detail}` on success and `{ok: false, detail}` on failure (never 500s); 404 unknown notifier.
- [ ] Notifier list never includes `password` or URL query tokens (redaction test).

### 5.13 P1-6 Fire history + audit
- [ ] Migration 7 `alert_history` table exists; every fire writes a row (rule, metric, observed, threshold, message, fired_at).
- [ ] `GET /api/alerts/history?rule_id=&limit=` newest-first, default limit 100, max 1000.
- [ ] Each fire records `record_audit_event("alert.fired", "evaluator", "alert_rule", rule_id, "success", ...)`; `verify_audit_chain()` still valid after fires.

### 5.14 Cross-cutting (all P0/P1)
- [ ] Pre-tester TDD suite (RED first): `tests/test_alert_rules.py`, `tests/test_alert_evaluator.py`, `tests/test_notifiers.py`, `tests/test_alerts_api.py`, `tests/test_alert_history.py`, `tests/test_insights_service.py`, `tests/test_insights_api.py` (naming per pre-tester card); interface tests pass immediately; behavioral tests fail cleanly pre-implementation (NotImplementedError or assert-fail, no crashes); **no** `pytest.raises(NotImplementedError)` on the feature's own public methods post-implementation.
- [ ] Full suite green via `.venv/bin/python -m pytest -q` (871 baseline + new); `ruff check src tests` introduces **zero new** violations (4 pre-existing F401/F811 in `tests/test_filters.py` are out of scope; fix only if trivial).
- [ ] Runtime deps: **none added** — any new import must resolve from stdlib or existing pinned deps; if a dep becomes unavoidable, it MUST be added to `pyproject.toml` `dependencies` (not just `.venv`).
- [ ] Security gate: SSRF reuse (`ssrf.validate_target_url`) on every outbound notifier target; no f-string SQL (parameterized queries only); no blocking calls in async handlers (notifier/evaluator work happens in the evaluator thread; any sync `requests` in async handlers must be `def`-declared routes or `run_in_executor`, per the Bins forward precedent at `bins/api.py:183-207`).
- [ ] UI gates (tester, t_daf9c7d4): Playwright smoke (dashboard loads, Alerts tab renders, Insights chart renders, no error overlay) + browser-helper visual verification of `/dashboard/alerts` and `/dashboard/insights` per the parent epic.
- [ ] Docs (documenter, t_cea9ba8e): CHANGELOG v1.7.0 entry, README alerting section, `docs/ALERTS.md` (rule + notifier setup), `docs/INSIGHTS.md` (API reference) — parent epic AC8.
- [ ] `git commit` + push (branch main, HTTPS remote), `git-push-verify.sh` passes.

---

## 6. Interface Contract Summary (for the pre-tester)

Canonical API surface (repo convention — flat `app.routes` mounting, manual 422, JSON `{"detail": ...}` errors, token-protected):

```
GET    /api/alerts/rules                          -> {rules: [...]}
POST   /api/alerts/rules                          -> 201 {rule_id, ...}   | 422 invalid | 404 unknown notifier
PATCH  /api/alerts/rules/{rule_id}                -> {...}                 | 404 | 422
DELETE /api/alerts/rules/{rule_id}                -> 204                   | 404
GET    /api/alerts/notifiers                      -> {notifiers: [...]}    (secrets redacted)
POST   /api/alerts/notifiers                      -> 201 {...}             | 422 SSRF/validation
DELETE /api/alerts/notifiers/{notifier_id}        -> 204                   | 404
POST   /api/alerts/notifiers/{notifier_id}/test   -> {ok, detail}          (P1)
GET    /api/alerts/history?rule_id=&limit=        -> {events: [...]}       (P1)
GET    /api/alerts/status                         -> {interval_seconds, evaluator_running, last_run_at}
GET    /api/insights/endpoints?window=24h         -> {window, endpoints: [...]}   | 422 bad window
GET    /api/insights/timeseries?metric=deliveries&window=24h&bucket=hourly
                                                 -> {metric, window, bucket, buckets: [...]} | 422
GET    /dashboard/alerts    (Jinja page)
GET    /dashboard/insights  (Jinja page + canvas chart)
CLI:   hookrelay alerts list|create|delete | hookrelay insights endpoints|timeseries
```

Alert rule JSON (POST/PATCH/GET item):
```
{rule_id, name, scope: "all"|"endpoint", endpoint_id: str|null,
 metric: "success_rate_below"|"consecutive_failures"|"dlq_depth_above",
 threshold: float, window_minutes: int, cooldown_minutes: int,
 enabled: bool, notifier_ids: [str], created_at, updated_at, last_fired_at: str|null}
```

Notifier JSON (POST body):
```
{type: "slack", webhook_url: str}
{type: "smtp", host: str, port: int, username?: str, password?: str,
 from_addr: str, to_addrs: [str], use_tls?: bool}
{type: "webhook", url: str, headers?: {str: str}}
```

Key module contracts for interface tests (imports/signatures):
- `hookrelay.alerts.rules`: `AlertRule` frozen dataclass (fields above), `validate()`.
- `hookrelay.alerts.storage`: `AlertRuleStore(storage)` — `create/get/list/update/delete/mark_fired/set_enabled/record_fire/list_history`.
- `hookrelay.alerts.evaluator`: `AlertEvaluator(store, notifier_registry, *, now=None)` — `run_once() -> list[dict]`, `start(interval_seconds=None)`, `stop()`, `is_running()`, `evaluate_metric(rule) -> float | None`.
- `hookrelay.alerts.notifiers`: `Notifier` ABC (`type`, `send(alert) -> bool`, `validate()`, `health()`), `SlackNotifier`, `SmtpNotifier`, `WebhookNotifier`, `NotifierRegistry` (`register/get/send_to/list_notifiers`), `validate_notifier_payload(dict) -> Notifier`.
- `hookrelay.alerts.api`: `create_alerts_router() -> APIRouter`.
- `hookrelay.insights.service`: `InsightsService(storage)` — `endpoints(window="24h")`, `timeseries(metric="deliveries", window="24h", bucket="hourly")`, `classify_failure_reason(row) -> str`, `parse_window(str) -> int`, `parse_bucket(str) -> int`.
- `hookrelay.insights.api`: `create_insights_router() -> APIRouter`.
- `hookrelay.cli`: `alerts_list/alerts_create/alerts_delete/insights_endpoints/insights_timeseries` (plain signatures); `alerts_app`/`insights_app` Typer subapps.
- `hookrelay.migrations`: `CURRENT_SCHEMA_VERSION == 6` (P0) → `7` (P1); `_MIGRATIONS[6]` = `("alert-rules", sql)`, `_MIGRATIONS[7]` = `("alert-history", sql)`.
