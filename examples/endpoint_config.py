"""Endpoint configuration example (hookrelay v1.5.0).

Shows per-endpoint delivery configuration: EndpointConfig (timeout,
retry policy, headers, HMAC secret), RetryPolicy backoff math, and
HeaderManager allowlist/redaction for outbound requests.

Usage:
    python examples/endpoint_config.py
"""

from __future__ import annotations

from hookrelay.config.endpoint import EndpointConfig
from hookrelay.config.headers import HeaderManager
from hookrelay.config.retry_policy import RetryPolicy


def main() -> None:
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
    cfg.validate()  # SSRF guard + scheme + timeout/retry sanity checks
    print(f"Validated endpoint: {cfg.name} -> {cfg.url}")

    restored = EndpointConfig.from_dict(cfg.to_dict())
    print(f"Round-trip equal: {restored == cfg}")
    print(f"Backoff delays (s): {[round(cfg.retry_policy.backoff_delay(i), 2) for i in range(4)]}")

    hm = HeaderManager(
        base_headers={"User-Agent": "hookrelay/1.5.0"},
        forward_allowlist={"x-request-id"},
        injected={"X-Hookrelay-Signature": "t=1234567890,v1=abc"},
    )
    outbound = hm.prepare({"x-request-id": "req-9", "Authorization": "Bearer secret"})
    print(f"Prepared headers: {outbound}")
    print(f"Redacted headers: {hm.redact({'Authorization': 'Bearer secret', 'X-Custom': 'ok'})}")


if __name__ == "__main__":
    main()
