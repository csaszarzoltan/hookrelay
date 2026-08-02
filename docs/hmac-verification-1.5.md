# Hookrelay 1.5 HMAC Signature Verification

## Goal

Authenticate inbound webhook payloads so Hookrelay only accepts events that
genuinely come from the expected sender. Hookrelay implements the Svix-style
scheme: an `X-Hookrelay-Signature` header carrying `t=<unix_ts>,v1=<hex>`,
with constant-time comparison and an optional timestamp-tolerance window to
defeat replay of old signatures.

## Wire format

```
X-Hookrelay-Signature: t=1785665329,v1=9bf06aa9fcaa0014d286501bcf6b35ec7f1a6caf85e0be8caa18985ec09439c2
```

- `t` — Unix timestamp when the signature was produced.
- `v1` — hex HMAC-SHA256 of `<timestamp>.<payload>` under the shared secret.
- Multiple `v1=` entries are accepted (any match verifies), which supports
  key rotation: send the new signature alongside a still-valid old one.

## Component

`hookrelay.security.HMACVerifier`:

| Method | Behaviour |
|---|---|
| `sign(payload, *, timestamp=None)` | Return `t=<unix_ts>,v1=<hex>`. Raises `ValueError` if the secret is empty. |
| `verify(payload, signature, *, now=None)` | Parse `t`/`v1`, check `|now - t| <= tolerance` (when tolerance is set), and compare digests in constant time. Returns `False` (never raises) for malformed signatures, unknown versions, out-of-tolerance timestamps, or digest mismatches. |
| `constant_time_equals(a, b)` | `hmac.compare_digest` wrapper. |

Constructor: `HMACVerifier(secret, *, algorithm="sha256", header_name="X-Hookrelay-Signature", tolerance_seconds=300)`.
Pass `tolerance_seconds=None` to skip the timestamp check entirely.

## Usage

```python
import time
from hookrelay.security import HMACVerifier

verifier = HMACVerifier(secret="whsec_demo_secret_123", tolerance_seconds=300)
payload = b'{"event": "invoice.paid", "data": {"id": 42}}'

signature = verifier.sign(payload)                     # t=<now>,v1=<hex>
assert verifier.verify(payload, signature) is True

# Tampered payload, wrong secret, or a signature older than the
# tolerance window all fail closed:
assert verifier.verify(b'{"event": "invoice.refunded"}', signature) is False
assert HMACVerifier("other-secret").verify(payload, signature) is False
stale = verifier.sign(payload, timestamp=str(int(time.time()) - 600))
assert verifier.verify(payload, stale) is False        # 600s > 300s tolerance
```

A complete, runnable version is at
[`examples/hmac_verification.py`](../examples/hmac_verification.py).

### Sample output (from the example)

```text
Signature: t=1785665329,v1=9bf06aa9fcaa0014d286501bcf6b35ec7f1a6caf85e0be8caa18985ec09439c2
Verify genuine payload : True
Verify tampered payload: False
Verify wrong secret    : False
Verify 10-min-old stamp: False
```

## Security decisions

- Comparison is constant-time (`hmac.compare_digest`) — no early-exit
  string comparison leaks digest prefix information.
- `verify()` fails closed: malformed input, unknown signature versions, and
  unparseable timestamps return `False`, never raise.
- The timestamp window (default 300 s) bounds replay of captured signatures
  while tolerating clock skew between sender and receiver.
- Use a dedicated, long random secret per endpoint (see
  [endpoint-config-1.5.md](endpoint-config-1.5.md) — `EndpointConfig.secret`).
  Rotate by emitting both the new and the old `v1=` values during the overlap.

## TDD validation

HMAC behaviour (Svix-style format, string/bytes payloads, empty-secret
rejection, round-trip verify, tamper/wrong-secret failure, tolerance window,
`tolerance=None` bypass, malformed signatures, constant-time compare) is
covered in `tests/test_security_config.py`. Final regression result:
**731 passed, 0 failed**.
