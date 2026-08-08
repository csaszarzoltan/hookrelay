# Hookrelay Alerting — Rules, Evaluator, and Notifiers (v1.7.0)

Hookrelay 1.7.0 adds proactive failure alerting: declarative threshold
rules are evaluated over rolling windows of stored delivery history, and
crossed thresholds fan out to Slack, email, or a generic outbound webhook.
Alert rules, the evaluation loop, and notifier configuration are all
managed through the REST API, the `hookrelay alerts` CLI, or the
dashboard **Alerts** tab.

## How it works

Every delivery attempt Hookrelay already stores (status, endpoint,
timestamps, latency, errors) is the input to the alert engine:

```
deliveries + delivery_attempts + dlq
        │
        ▼
AlertEvaluator (daemon thread, ~60s cycle)
        │  for each enabled rule: compute metric over window_minutes
        │  threshold crossed AND cooldown elapsed?
        ▼
NotifierRegistry ──► Slack incoming webhook / SMTP email / outbound webhook
        │
        ▼
alert_history table + tamper-evident audit log (alert.fired)
```

The evaluator runs in a background daemon thread started by `create_app()`
and only starts when at least one alert rule exists. Its interval comes
from the `alert_interval_seconds` setting (default `60`); the whole
evaluator can be disabled with the `alert_evaluator_enabled` setting
(`false`). Both are read through `app_settings` (`Storage.get_setting` /
`set_setting`), so they can be tuned at runtime.

## Alert rules

A rule is a frozen dataclass (`hookrelay.alerts.rules.AlertRule`) persisted
in the `alert_rules` table (schema migration 6):

| Field | Type | Default | Notes |
|---|---|---|---|
| `rule_id` | str | — | Stable unique id (UUID hex when not supplied). |
| `name` | str | — | Human-readable name (must be non-empty). |
| `scope` | str | `"all"` | `"all"` (every endpoint) or `"endpoint"`. |
| `endpoint_id` | str \| null | — | Required when `scope == "endpoint"`. |
| `metric` | str | `"success_rate_below"` | One of the metric types below. |
| `threshold` | float | — | Crossing threshold (metric-specific range). |
| `window_minutes` | int | `15` | Rolling evaluation window. |
| `cooldown_minutes` | int | `15` | Minimum time between two fires of this rule. |
| `enabled` | bool | `true` | Paused rules (`enabled=false`) never fire. |
| `notifier_ids` | list[str] | `[]` | Notifiers to fan out to when the rule fires. |
| `created_at` / `updated_at` | str | — | ISO-8601 UTC timestamps. |
| `last_fired_at` | str \| null | — | Most recent fire (cooldown bookkeeping). |

### Metric types

| Metric | What it measures | Threshold range | Fires when |
|---|---|---|---|
| `success_rate_below` | delivered / (delivered + failed) over the window (pending excluded) | `(0, 1]` | observed rate **below** threshold |
| `consecutive_failures` | length of the **trailing** run of `failed`/`in-dlq` deliveries in the window | integer `>= 1` | observed count **>=** threshold |
| `dlq_depth_above` | total rows in the dead-letter queue (per endpoint when scoped) | integer `>= 1` | observed depth **>=** threshold |

Notes on semantics:

- **Success rate** uses the same math as `SuccessRateCalculator`:
  `delivered / (delivered + failed)`, with `pending` rows excluded.
  A rule with `threshold=0.9` fires when the rate drops below 90%.
- **Consecutive failures** counts the *trailing* run: rows are considered
  newest-first from the most recent `created_at`, and a `delivered` or
  `pending` row (or a gap of no data, or a row older than the window
  cutoff) ends the run. It is the "how broken is it right now" count, not
  the longest historical run.
- **DLQ depth** reads the `dlq` table directly; with `scope="endpoint"`
  it counts only entries for that endpoint.
- A rule that cannot be evaluated (no data in the window, or the
  `deliveries`/`dlq` table missing on a fresh database) never fires and
  never raises.

### Threshold validation

`AlertRule.validate()` rejects (HTTP 422 via the API, exit 1 via the CLI):

- empty `name`
- unknown `scope` or `metric`
- `success_rate_below` threshold outside `(0, 1]`
- `consecutive_failures` / `dlq_depth_above` threshold `< 1`
- `scope="endpoint"` without `endpoint_id`
- `window_minutes` / `cooldown_minutes` `< 1`

### Cooldown and paused rules

- **Cooldown** — after a rule fires, `last_fired_at` is persisted and the
  rule will not fire again until `now - last_fired_at >= cooldown_minutes`
  (default 15 min). This prevents alert storms while a condition persists
  across 60-second evaluation cycles.
- **Paused rules** — `enabled=false` rules are skipped entirely by the
  evaluation loop; they never fire and never produce history events. Toggle
  via `PATCH /api/alerts/rules/{id}` with `{"enabled": false}` (the
  dashboard Alerts tab has an enable/disable button).

### Fire history and audit

Every fire is recorded in the `alert_history` table (migration 7) —
`event_id`, `rule_id`, `rule_name`, `metric`, `observed_value`,
`threshold`, `message`, `fired_at` — and mirrored into the tamper-evident
audit log as `alert.fired` (or `alert.failed` when no notifier delivered).
Browse it with `GET /api/alerts/history` or from the dashboard.

## Managing rules

### REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/alerts/rules` | List all rules. |
| `POST` | `/api/alerts/rules` | Create a rule (201; 422 invalid, 404 unknown notifier). |
| `PATCH` | `/api/alerts/rules/{rule_id}` | Partial update (404 unknown, 422 invalid). |
| `DELETE` | `/api/alerts/rules/{rule_id}` | Delete (204; 404 unknown). |
| `GET` | `/api/alerts/history?rule_id=&limit=` | Fire history, newest first (limit clamped to [1, 1000]). |
| `GET` | `/api/alerts/status` | Evaluator status (`interval_seconds`, `evaluator_running`). `last_run_at` is currently always `null` — the loop does not expose a run timestamp. |

Create a rule — alert when the checkout endpoint's success rate drops
below 90% over the last hour:

```bash
curl -X POST http://localhost:8000/api/alerts/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "checkout success rate",
    "scope": "endpoint",
    "endpoint_id": "ep-checkout",
    "metric": "success_rate_below",
    "threshold": 0.9,
    "window_minutes": 60,
    "cooldown_minutes": 15
  }'
```

Response (201):

```json
{
  "rule_id": "8ee685a4e8bb4e8abca4aa3157099d34",
  "name": "checkout success rate",
  "scope": "endpoint",
  "endpoint_id": "ep-checkout",
  "metric": "success_rate_below",
  "threshold": 0.9,
  "window_minutes": 60,
  "cooldown_minutes": 15,
  "enabled": true,
  "notifier_ids": [],
  "created_at": "2026-08-08T19:19:33.720155+00:00",
  "updated_at": "2026-08-08T19:19:33.720155+00:00",
  "last_fired_at": null
}
```

Pause a rule (dashboard toggle equivalent):

```bash
curl -X PATCH http://localhost:8000/api/alerts/rules/8ee685a4e8bb4e8abca4aa3157099d34 \
  -H "Content-Type: application/json" -d '{"enabled": false}'
```

Invalid payloads return **422** with a `{"detail": ...}` body, e.g.:

```json
{"detail": "name must not be empty"}
```

### CLI

```bash
hookrelay alerts list
hookrelay alerts create checkout-success --metric success_rate_below --threshold 0.9 --window-minutes 60
hookrelay alerts delete <rule_id>
```

`create` options: `--scope` (`all`|`endpoint`), `--endpoint-id`,
`--metric`, `--threshold` (required), `--window-minutes`,
`--cooldown-minutes`, and repeatable `--notifier <id>`. Rules are printed
as JSON; `delete` of an unknown rule exits 1 with an error message.
Invalid values exit 1 with the validation message on stderr, e.g.
`Error: success_rate_below threshold must be in (0, 1]` (the API's
422 body is the same message).

### Python API

```python
from hookrelay.alerts.rules import AlertRule
from hookrelay.alerts.storage import AlertRuleStore
from hookrelay.storage import Storage

store = Storage("webhooks.db")
rule_store = AlertRuleStore(store)
rule_id = rule_store.create(AlertRule(
    rule_id="rule-1",
    name="ep1 success",
    scope="endpoint",
    endpoint_id="ep-1",
    metric="success_rate_below",
    threshold=0.9,
    window_minutes=60,
    cooldown_minutes=15,
))
print(rule_store.get(rule_id).to_dict())
rule_store.delete(rule_id)
```

## Notifiers

Notifiers are named channels the registry fans fired alerts out to.
Definitions persist as JSON under `app_settings["alert_notifiers"]`
(not a dedicated table) and are rebuilt on startup; invalid persisted
definitions are skipped so a corrupt settings blob cannot crash the
evaluator.

| Type | Channel | Required fields |
|---|---|---|
| `slack` | Slack incoming-webhook URL | `webhook_url` |
| `smtp` | Email over SMTP (stdlib `smtplib`) | `host`, `from_addr`, `to_addrs` |
| `webhook` | Generic outbound webhook (JSON POST) | `url` (optional `headers`) |

### Security behaviour

- **SSRF guard at save and at fire.** Every outbound target (Slack
  webhook URL and outbound webhook URL) is validated through the repo's
  `hookrelay.ssrf.validate_target_url` — when the notifier is saved and
  again right before the POST. DNS is re-resolved per call, so a URL that
  was safe at save time is re-checked at fire time; an unsafe target makes
  `send` fail closed (returns `False`, no request is made).
- **No `allow_private` via the API.** `allow_private` is a test-only
  constructor override. The API rejects any payload containing it
  (422) and it is never persisted to settings, so notifiers rebuilt
  from settings stay SSRF-guarded. Private/loopback/metadata targets
  (e.g. `http://192.168.1.10:8000/hook`) are rejected at save time.
- **Secret redaction.** `GET /api/alerts/notifiers` never echoes secrets:
  Slack webhook URLs are masked to `https://hooks.slack.com/services/***`
  (the path token is never exposed) and SMTP passwords are dropped
  entirely. Full values exist only in the persisted settings payload and
  the live notifier object.
- **Redirects disabled** on outbound webhook sends (`allow_redirects=False`)
  so a compromised target cannot bounce the alert to an internal address.

### REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/alerts/notifiers` | List redacted notifier summaries. |
| `POST` | `/api/alerts/notifiers` | Create a notifier (201; 422 SSRF/validation). |
| `DELETE` | `/api/alerts/notifiers/{notifier_id}` | Delete (204; 404 unknown). |
| `POST` | `/api/alerts/notifiers/{notifier_id}/test` | Send a synthetic alert through the channel (`{ok, detail}`; never 500s). |

Slack:

```bash
curl -X POST http://localhost:8000/api/alerts/notifiers \
  -H "Content-Type: application/json" \
  -d '{"type": "slack", "webhook_url": "https://hooks.slack.com/services/EXAMPLE/EXAMPLE/EXAMPLE"}'
```

Email (STARTTLS + optional auth, `use_tls` for implicit TLS):

```bash
curl -X POST http://localhost:8000/api/alerts/notifiers \
  -H "Content-Type: application/json" \
  -d '{
    "type": "smtp",
    "host": "smtp.example.com",
    "port": 587,
    "username": "alerts-bot",
    "password": "smtp-password",
    "from_addr": "alerts@example.com",
    "to_addrs": ["ops@example.com"]
  }'
```

Outbound webhook (JSON envelope posted with `allow_redirects=False`,
timeout 10s):

```bash
curl -X POST http://localhost:8000/api/alerts/notifiers \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webhook",
    "url": "https://example.com/hookrelay-alerts",
    "headers": {"X-Team": "platform"}
  }'
```

Each create returns `{"id": "<type>-<n>", "notifier_id": "<id>", "type": "..."}`
— use that id in `notifier_ids` on rules and in the `/test` endpoint.
SSRF-blocked URLs return 422, e.g.:

```json
{"detail": "URL blocked by SSRF protection: Resolved to private IP: 192.168.1.10"}
```

### What a fired alert looks like

**Slack** receives a single text message prefixed with `<hookrelay> `:

```json
{"text": "<hookrelay> Success rate 30.0% is below threshold 90.0% over the last 60 minute(s)"}
```

**Outbound webhook** receives the full alert envelope:

```json
{
  "alert": {
    "rule_id": "rule-1",
    "rule_name": "ep1 success",
    "metric": "success_rate_below",
    "observed_value": 0.3,
    "threshold": 0.9,
    "message": "Success rate 30.0% is below threshold 90.0% over the last 60 minute(s)"
  },
  "type": "hookrelay.alert",
  "version": 1
}
```

**Email** gets a plain-text message with subject
`Hookrelay alert: <rule name>`.

Per-metric message templates:

- `success_rate_below` — `Success rate {observed:.1%} is below threshold {threshold:.1%} over the last {window} minute(s)`
- `consecutive_failures` — `{observed:.0f} consecutive failures (threshold {threshold:.0f}) over the last {window} minute(s)`
- `dlq_depth_above` — `Dead-letter queue depth {observed:.0f} is above threshold {threshold:.0f}`

### Python API

```python
from hookrelay.alerts.notifiers import (
    NotifierRegistry,
    SlackNotifier,
    SmtpNotifier,
    WebhookNotifier,
    validate_notifier_payload,
)

registry = NotifierRegistry()
registry.register(SlackNotifier("https://hooks.slack.com/services/EXAMPLE/EXAMPLE/EXAMPLE"))
registry.register(SmtpNotifier(
    host="smtp.example.com", port=587,
    from_addr="alerts@example.com", to_addrs=["ops@example.com"],
))
registry.register(validate_notifier_payload(
    {"type": "webhook", "url": "https://example.com/alerts"}
))

ok = registry.send_to(["slack-1", "webhook-3"], {
    "rule_id": "rule-1",
    "rule_name": "ep1 success",
    "metric": "success_rate_below",
    "observed_value": 0.3,
    "threshold": 0.9,
    "message": "Success rate 30.0% is below threshold 90.0%",
})
print(ok)  # {notifier_id: bool} per-notifier success map
```

`send_to` never lets one failing notifier block the others: it returns a
`{notifier_id: bool}` success map and the evaluator records
`outcome="failed"` in history/audit when no notifier delivered.

## Evaluation loop

- Runs every `alert_interval_seconds` (default 60) in a daemon thread
  named `hookrelay-alert-evaluator`, started by `create_app()` when rules
  exist; blocking HTTP/SMTP I/O never touches the event loop.
- The success-rate window is anchored to the later of the evaluator's
  clock and the most recent delivery, keeping the metric correct under
  clock skew between writer and evaluator.
- A cycle that raises (missing table, transient error) is swallowed and
  the loop continues; a rule with no data simply does not fire.

## Dashboard

The **Alerts** tab at `/dashboard/alerts` shows the rules list (name,
scope, metric, threshold, window, cooldown, enabled badge, last fired),
a create form, enable/disable toggles, and delete buttons — all mutations
go through the `/api/alerts/*` endpoints via `fetch()`.

## Example: end-to-end

```bash
# 1. Create a Slack notifier (id printed as slack-1)
curl -X POST http://localhost:8000/api/alerts/notifiers \
  -H "Content-Type: application/json" \
  -d '{"type": "slack", "webhook_url": "https://hooks.slack.com/services/EXAMPLE/EXAMPLE/EXAMPLE"}'

# 2. Alert when checkout success rate falls below 90% in the last hour
curl -X POST http://localhost:8000/api/alerts/rules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "checkout success rate",
    "scope": "endpoint",
    "endpoint_id": "ep-checkout",
    "metric": "success_rate_below",
    "threshold": 0.9,
    "window_minutes": 60,
    "notifier_ids": ["slack-1"]
  }'

# 3. Verify the notifier channel with a synthetic alert
curl -X POST http://localhost:8000/api/alerts/notifiers/slack-1/test

# 4. Watch evaluator status and fire history
curl http://localhost:8000/api/alerts/status
curl "http://localhost:8000/api/alerts/history?rule_id=<rule_id>&limit=10"
```

## Related

- [Insights API](insights-api.md) — per-endpoint stats and time series over
  the same delivery data
- [Delivery infrastructure](delivery-infrastructure-1.5.md) — retry queue
  and delivery tracking
- [Dead-letter queue](dead-letter-queue-1.5.md) — DLQ inspect/requeue
