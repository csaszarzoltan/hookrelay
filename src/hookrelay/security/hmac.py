"""HMAC-SHA256 signature verification for inbound webhook payloads.

Svix-style ``t=<unix_ts>,v1=<hex>`` signatures with constant-time comparison
and an optional timestamp-tolerance window.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime

#: Signature prefix for the algorithm (v1 = SHA-256 as produced by :meth:`HMACVerifier.sign`).
_SIGNATURE_VERSION = "v1"


class HMACVerifier:
    """Sign and verify webhook payloads with HMAC-SHA256."""

    def __init__(
        self,
        secret: str,
        *,
        algorithm: str = "sha256",
        header_name: str = "X-Hookrelay-Signature",
        tolerance_seconds: int | None = 300,
    ) -> None:
        self.secret = secret
        self.algorithm = algorithm
        self.header_name = header_name
        self.tolerance_seconds = tolerance_seconds

    def _message_bytes(self, payload: bytes | str, timestamp: str) -> bytes:
        """Normalize ``payload`` and prefix it with ``<timestamp>.`` (Svix wire format)."""
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return f"{timestamp}.".encode() + payload

    def _digest(self, payload: bytes | str, timestamp: str) -> str:
        """Compute the hex HMAC digest for ``payload`` under ``timestamp``."""
        if not self.secret:
            raise ValueError("secret must not be empty")
        algorithm = getattr(hashlib, self.algorithm)
        mac = hmac.new(self.secret.encode("utf-8"), self._message_bytes(payload, timestamp), algorithm)
        return mac.hexdigest()

    def sign(self, payload: bytes | str, *, timestamp: str | None = None) -> str:
        """Return 't=<unix_ts>,v1=<hex>'; ValueError if secret empty."""
        if not self.secret:
            raise ValueError("secret must not be empty")
        if timestamp is None:
            timestamp = str(int(time.time()))
        return f"t={timestamp},{_SIGNATURE_VERSION}={self._digest(payload, timestamp)}"

    def verify(
        self,
        payload: bytes | str,
        signature: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Parse t/v1, check |now - t| <= tolerance (if set), constant-time compare.

        Returns ``False`` (never raises) for malformed signatures, unknown
        versions, out-of-tolerance timestamps, or digest mismatches.
        """
        timestamp: str | None = None
        digests: list[str] = []
        for part in signature.split(","):
            if "=" not in part:
                return False
            key, _, value = part.partition("=")
            if key == "t":
                timestamp = value
            elif key == _SIGNATURE_VERSION:
                digests.append(value)
        if timestamp is None or not digests:
            return False

        if self.tolerance_seconds is not None:
            try:
                signed_ts = int(timestamp)
            except ValueError:
                return False
            now_dt = now or datetime.now(UTC)
            age = abs(int(now_dt.timestamp()) - signed_ts)
            if age > self.tolerance_seconds:
                return False

        try:
            expected = self._digest(payload, timestamp)
        except ValueError:
            return False
        return any(self.constant_time_equals(expected, digest) for digest in digests)

    @staticmethod
    def constant_time_equals(a: str, b: str) -> bool:
        """Timing-safe comparison via hmac.compare_digest."""
        return hmac.compare_digest(a, b)
