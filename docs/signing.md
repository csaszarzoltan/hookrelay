# Hookrelay 1.8 Outgoing Signing

## Goal

Sign webhook payloads **before they leave hookrelay**, so downstream
receivers can verify authenticity and freshness. The outgoing signer
(`hookrelay.security.outgoing.OutgoingSigner`) supports the Svix
(Ed25519), Hookdeck (HMAC-SHA256), GitHub (HMAC-SHA256), and `custom`
(HMAC-SHA256) wire formats, and **always** injects an
`x-hookrelay-timestamp` header so receivers can bound replay windows.

Signing is configured per destination (`signing_config` on
[destinations](destinations.md)); there is no global signing setting. No
new environment variables are required.

This guide covers the **outgoing** signer. For verifying *inbound* webhooks
(Svix-style `t=,v1=` signatures) see
[hmac-verification-1.5.md](hmac-verification-1.5.md).

## Quick start

```python
from hookrelay.security.outgoing import OutgoingSigner

signer = OutgoingSigner(algorithm="github", secret="whsec_checkout")
payload = b'{"event": "order.created"}'

signature = signer.sign(payload)               # bare lowercase hex digest
headers = signer.build_headers(payload)        # adds x-hookrelay-timestamp etc.
print(signature)
print(headers)
```

Every delivered request carries at least:

- `x-hookrelay-timestamp` — Unix timestamp (seconds) used to sign
- `x-hookrelay-signature` — the signature (see table below)

## Algorithms

| Algorithm | Signature | Message signed | Extra headers |
|---|---|---|---|
| `svix` | base64 Ed25519 signature | `"<timestamp>.<payload>"` | `x-hookrelay-timestamp`, `x-hookrelay-signature`, `svix-id` (`msg_<sha256-prefix>`) |
| `hookdeck` | bare lowercase HMAC-SHA256 hex digest | `"<timestamp>.<payload>"` | `x-hookrelay-timestamp`, `x-hookrelay-signature` |
| `github` | bare lowercase HMAC-SHA256 hex digest | `"<timestamp>.<payload>"` | `x-hookrelay-timestamp`, `x-hookrelay-signature` |
| `custom` | bare lowercase HMAC-SHA256 hex digest | `"<timestamp>.<payload>"` | `x-hookrelay-timestamp`, `x-hookrelay-signature` |

Notes:

- The HMAC formats reuse the Svix convention of signing
  `"<timestamp>.<payload>"` and emit the bare hex digest — no `sha256=` or
  `v1=` prefix — matching what Hookdeck and GitHub consumers expect.
- `svix` additionally emits `svix-id` so Svix-compatible receivers can
  validate; the Ed25519 key is derived deterministically from the secret
  (base64-decoded 32-byte seed, else SHA-256-hashed down to 32 bytes), so
  the same secret always reproduces the same key.
- `hookdeck` and `github` currently produce identical wire signatures (both
  HMAC-SHA256 over the timestamped message); the algorithm name documents
  intent and can diverge in future releases.

## Key management

- Secrets are per-destination and stored in the `signing_config.secret`
  field of the `destinations` table. Choose long, random secrets
  (`openssl rand -base64 32`), one per destination.
- For `svix`, the secret is treated as a base64-encoded Ed25519 seed. Any
  secret yields a working, reproducible key — pass real Svix signing
  secrets (base64) for interop.
- Secrets are visible to anyone with database access or API read access to
  the destination record. Protect the server with
  `HOOKRELAY_API_TOKEN` when it is reachable by other users or networks
  (see [Access protection](../README.md#optional-access-protection)).

## Verification

Verification is available **in Python** (there is no HTTP verification
endpoint):

```python
from hookrelay.security.outgoing import verify_signature

ok = verify_signature(
    payload=b'{"event": "order.created"}',
    signature=signature,
    secret="whsec_checkout",
    algorithm="github",
    timestamp="1720000000",   # the value from x-hookrelay-timestamp
)
```

`OutgoingSigner.verify(payload, signature, timestamp=...)` is the
equivalent method. Behaviour:

- **Timestamp is required.** HMAC verify recomputes over the provided
  timestamp; a missing or wrong timestamp fails. For `svix`, the Ed25519
  verification recomputes over the provided timestamp. Always pass the
  `x-hookrelay-timestamp` value captured from the request — and apply your
  own tolerance window to reject replays (compare against the receiver's
  clock, e.g. reject `|now - ts| > 300s`).
- A tampered payload, wrong secret, or malformed signature returns `False`
  (never raises).

```python
from hookrelay.security.outgoing import OutgoingSigner

signer = OutgoingSigner("github", "whsec_checkout")
sig = signer.sign(b"data", timestamp="1720000000")
assert signer.verify(b"data", sig, timestamp="1720000000") is True
assert signer.verify(b"data", sig, timestamp="1720000001") is False   # stale ts
assert signer.verify(b"tampered", sig, timestamp="1720000000") is False
```

## Receiver-side verification examples

### GitHub-style (HMAC-SHA256)

```python
import hashlib
import hmac

def verify_github(payload: bytes, signature: str, secret: str, timestamp: str) -> bool:
    message = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())
```

### Svix-style (Ed25519)

```python
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def verify_svix(payload: bytes, signature: str, secret: str, timestamp: str) -> bool:
    raw = base64.b64decode(secret, validate=False)
    if len(raw) != 32:
        raw = hashlib.sha256(secret.encode()).digest()
    public_key = Ed25519PrivateKey.from_private_bytes(raw).public_key()
    public_key.verify(
        base64.b64decode(signature),
        f"{timestamp}.".encode() + payload,
    )
```

## CLI and API coverage

- **REST** — `signing_config` is set per destination via
  `POST /api/v1/destinations` / `PUT /api/v1/destinations/{id}` (see
  [destinations.md](destinations.md)). There is no signing-specific
  endpoint.
- **CLI** — `hookrelay destination add ... --signing-algorithm github
  --signing-secret whsec_checkout` (see [destinations.md](destinations.md)).
- **Dashboard** — the Destinations tab's *Signing* form sets `algorithm`,
  `key`/`secret`, header name, and timestamp header.

A runnable end-to-end example covering all four algorithms plus
verification is at
[`../examples/transforms_routing.py`](../examples/transforms_routing.py).

## Python API

`hookrelay.security.outgoing` is the stable interface:

| Member | Behaviour |
|---|---|
| `OutgoingSigner(algorithm, secret)` | Signer for one destination; validates algorithm (`svix`, `hookdeck`, `github`, `custom`) and non-empty secret |
| `signer.sign(payload, timestamp=None)` | Signature string (base64 Ed25519 for `svix`, bare hex HMAC otherwise); timestamp defaults to now |
| `signer.build_headers(payload, timestamp=None)` | Dict of headers to attach to the outgoing request |
| `signer.verify(payload, signature, timestamp=None)` | Constant-time verification; `False` on any mismatch (never raises) |
| `verify_signature(payload, signature, secret, algorithm, timestamp=None)` | Standalone helper wrapping a one-shot signer |
| `SUPPORTED_ALGORITHMS` | `frozenset({"svix", "hookdeck", "github", "custom"})` |
