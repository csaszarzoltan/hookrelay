# Hookrelay 1.5 Endpoint Configuration

## Goal

Declare delivery behaviour per outbound endpoint in one place: target URL,
timeout, retry policy, extra headers, and the HMAC secret used to verify
inbound signatures for that endpoint. Configuration is validated up front
(including the SSRF guard) instead of failing at dispatch time.

## Components

### EndpointConfig

`hookrelay.config.endpoint.EndpointConfig` — frozen dataclass:

| Field | Default | Meaning |
|---|---|---|
| `endpoint_id` / `name` | — | Stable identifiers for the endpoint. |
| `url` | — | Outbound target (http/https only). |
| `timeout_seconds` | `30.0` | Per-attempt timeout. |
| `retry_policy` | `RetryPolicy()` | Backoff/retry behaviour. |
| `headers` | `{}` | Extra headers attached to every delivery. |
| `secret` | `None` | HMAC secret for verifying inbound signatures. |
| `enabled` | `True` | Delivery toggle. |
| `channel` | `None` | Optional channel association. |
| `idempotency_ttl_seconds` | `86400` | Idempotency key TTL for this endpoint. |

Methods:

- `validate()` — raise `ValueError` on an empty URL, a non-http(s)/hostless
  URL, a URL that fails the SSRF guard, `timeout_seconds <= 0`, or
  `retry_policy.max_retries < 0`.
- `to_dict()` / `from_dict()` — lossless JSON round-trip (`retry_policy`
  serializes to a nested dict; unknown keys are ignored on reconstruction).

### RetryPolicy

`hookrelay.config.retry_policy.RetryPolicy` — frozen dataclass with
`max_retries` (5), `backoff_factor` (2.0), `base_delay_seconds` (1.0),
`max_backoff_seconds` (3600.0), `jitter` (True). `backoff_delay(attempt)`
returns `min(max_backoff, base * factor**attempt)` plus optional jitter in
`[0, delay)`. See [delivery-infrastructure-1.5.md](delivery-infrastructure-1.5.md).

### HeaderManager

`hookrelay.config.headers.HeaderManager` — builds outbound header sets and
redacts sensitive values:

| Method | Behaviour |
|---|---|
| `prepare(source_headers=None)` | `base_headers + allowlisted source headers + injected` (injected win). |
| `add_injected(name, value)` | Register a header always present in `prepare()` output. |
| `redact(headers)` | Mask sensitive names with `[REDACTED]`. |

Sensitive names (case-insensitive): `authorization`, `proxy-authorization`,
`cookie`, `set-cookie`, `x-api-key`, `api-key`, `x-auth-token`,
`x-authentication-token`. The same vocabulary backs response-header redaction
in the dashboard.

## Usage

```python
from hookrelay.config.endpoint import EndpointConfig
from hookrelay.config.headers import HeaderManager
from hookrelay.config.retry_policy import RetryPolicy

cfg = EndpointConfig(
    endpoint_id="ep-stripe",
    name="Stripe webhook consumer",
    url="https://example.com/webhooks/stripe",
    timeout_seconds=10.0,
    retry_policy=RetryPolicy(max_retries=3, base_delay_seconds=0.5, jitter=False),
    headers={"X-Forwarded-By": "hookrelay"},
    secret="whsec_abc123",
    channel="stripe",
    idempotency_ttl_seconds=3600,
)
cfg.validate()                       # SSRF guard + scheme + sanity checks
restored = EndpointConfig.from_dict(cfg.to_dict())
assert restored == cfg

hm = HeaderManager(
    base_headers={"User-Agent": "hookrelay/1.5.0"},
    forward_allowlist={"x-request-id"},
    injected={"X-Hookrelay-Signature": "t=1234567890,v1=abc"},
)
outbound = hm.prepare({"x-request-id": "req-9", "Authorization": "Bearer secret"})
redacted = hm.redact({"Authorization": "Bearer secret", "X-Custom": "ok"})
```

A complete, runnable version is at
[`examples/endpoint_config.py`](../examples/endpoint_config.py).

### Sample output (from the example)

```text
Validated endpoint: Stripe webhook consumer -> https://example.com/webhooks/stripe
Round-trip equal: True
Backoff delays (s): [0.5, 1.0, 2.0, 4.0]
Prepared headers: {'User-Agent': 'hookrelay/1.5.0', 'x-request-id': 'req-9', 'X-Hookrelay-Signature': 't=1234567890,v1=abc'}
Redacted headers: {'Authorization': '[REDACTED]', 'X-Custom': 'ok'}
```

## Security decisions

- `EndpointConfig.validate()` is an SSRF chokepoint: it runs the same
  `hookrelay.ssrf.validate_target_url` guard as `RetryQueue.enqueue()`, so a
  private/loopback/link-local target, a system port (< 1024), or a
  non-http(s) protocol is rejected at configuration time — not at dispatch.
- Header forwarding is allowlist-only; everything not explicitly allowed is
  dropped, and sensitive values are redacted before logging or display.

## TDD validation

Endpoint configuration behaviour (validation rules, SSRF rejection, frozen
dataclass, round-trip serialization, header allowlist/redaction) is covered in
`tests/test_security_config.py`. Final regression result: **731 passed,
0 failed**.
