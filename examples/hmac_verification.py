"""HMAC-SHA256 webhook signature verification example (hookrelay v1.5.0).

Shows how to sign outbound payloads and verify inbound webhook
signatures using the Svix-style `t=<unix_ts>,v1=<hex>` scheme,
including tamper detection and stale-timestamp (replay) rejection.

Usage:
    python examples/hmac_verification.py
"""

from __future__ import annotations

import time

from hookrelay.security import HMACVerifier


def main() -> None:
    verifier = HMACVerifier(secret="whsec_demo_secret_123", tolerance_seconds=300)
    payload = b'{"event": "invoice.paid", "data": {"id": 42}}'

    signature = verifier.sign(payload)
    print(f"Signature: {signature}")

    print(f"Verify genuine payload : {verifier.verify(payload, signature)}")
    tampered = b'{"event": "invoice.refunded"}'
    print(f"Verify tampered payload: {verifier.verify(tampered, signature)}")
    print(f"Verify wrong secret    : {HMACVerifier('other-secret').verify(payload, signature)}")

    # A signature generated 10 minutes ago is outside the 300s tolerance.
    stale = verifier.sign(payload, timestamp=str(int(time.time()) - 600))
    print(f"Verify 10-min-old stamp: {verifier.verify(payload, stale)}")


if __name__ == "__main__":
    main()
