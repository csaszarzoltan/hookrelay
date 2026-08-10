"""Outgoing payload signing for webhooks delivered to downstream destinations.

Supports the Svix (Ed25519), Hookdeck (HMAC-SHA256), GitHub (HMAC-SHA256)
and ``custom`` (HMAC-SHA256) wire formats.  Every format always injects the
``x-hookrelay-timestamp`` header so receivers can bound replay windows.

The HMAC-SHA256 formats sign the message ``"<timestamp>.<payload>"`` (the
Svix convention reused by Hookdeck and GitHub) and emit the bare lowercase
hex digest — no ``sha256=`` or ``v1=`` prefix — matching what Hookdeck and
GitHub consumers expect.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

#: Algorithms supported by :class:`OutgoingSigner`.
SUPPORTED_ALGORITHMS = frozenset({"svix", "hookdeck", "github", "custom"})


def _normalize_payload(payload: bytes | str) -> bytes:
    """Coerce ``payload`` to bytes (UTF-8 for strings)."""
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return payload


def _hmac_hex(secret: str, message: bytes) -> str:
    """Return the HMAC-SHA256 hex digest of ``message`` under ``secret``."""
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _signed_message(payload: bytes, timestamp: str) -> bytes:
    """Return the canonical ``"<timestamp>.<payload>"`` message bytes."""
    return f"{timestamp}.".encode() + payload


def _ed25519_signer(secret: str) -> Any:
    """Return a stable Ed25519 private key derived (deterministically) from ``secret``.

    The secret is treated as a base64-encoded seed (Svix material).  If it
    cannot be base64-decoded to exactly 32 bytes, we hash it down to a
    32-byte seed so any secret yields a working, reproducible Ed25519 key.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        raw = base64.b64decode(secret, validate=False)
    except Exception:
        raw = b""
    if len(raw) != 32:
        raw = hashlib.sha256(secret.encode("utf-8")).digest()
    return Ed25519PrivateKey.from_private_bytes(raw)


class OutgoingSigner:
    """Sign outgoing webhook payloads for a specific destination.

    Parameters
    ----------
    algorithm : str
        One of ``svix``, ``hookdeck``, ``github``, ``custom``.
    secret : str
        Base64-encoded (or arbitrary) signing secret material.
    """

    SUPPORTED_ALGORITHMS = SUPPORTED_ALGORITHMS

    def __init__(self, algorithm: str, secret: str) -> None:
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise ValueError(
                f"unsupported algorithm '{algorithm}'; "
                f"supported: {', '.join(sorted(SUPPORTED_ALGORITHMS))}"
            )
        if not secret:
            raise ValueError("secret must not be empty")
        self.algorithm = algorithm
        self.secret = secret

    def sign(self, payload: bytes, *, timestamp: str | None = None) -> str:
        """Return the signature string for ``payload``.

        Args:
            payload: The raw request body to sign (bytes or str).
            timestamp: Unix timestamp string; defaults to the current time.

        Returns:
            The signature.  For HMAC-SHA256 algorithms this is the bare hex
            digest; for ``svix`` it is a base64-encoded Ed25519 signature.
        """
        data = _normalize_payload(payload)
        if timestamp is None:
            timestamp = str(int(time.time()))
        if self.algorithm == "svix":
            return self._svix_sign(data, timestamp)
        return _hmac_hex(self.secret, _signed_message(data, timestamp))

    def _svix_sign(self, payload: bytes, timestamp: str) -> str:
        """Sign with Ed25519 and return a base64 signature string."""
        private_key = _ed25519_signer(self.secret)
        message = _signed_message(payload, timestamp)
        signature = private_key.sign(message)
        return base64.b64encode(signature).decode("ascii")

    def build_headers(
        self, payload: bytes, *, timestamp: str | None = None
    ) -> dict[str, str]:
        """Return a dict of headers to attach to the outgoing request.

        Always includes ``x-hookrelay-timestamp`` and, for HMAC formats,
        ``x-hookrelay-signature`` containing the bare hex digest.  For Svix
        the signature is placed in ``x-hookrelay-signature`` and a ``svix-id``
        header is included so Svix-compatible receivers can validate.

        Args:
            payload: The raw outgoing body.
            timestamp: Optional explicit timestamp (defaults to now).

        Returns:
            A dict of header name → value.
        """
        if timestamp is None:
            timestamp = str(int(time.time()))
        signature = self.sign(payload, timestamp=timestamp)
        headers: dict[str, str] = {
            "x-hookrelay-timestamp": timestamp,
            "x-hookrelay-signature": signature,
        }
        if self.algorithm == "svix":
            headers["svix-id"] = "msg_" + hashlib.sha256(
                f"{timestamp}.{signature}".encode()
            ).hexdigest()[:16]
        return headers

    def verify(
        self, payload: bytes, signature: str, *, timestamp: str | None = None
    ) -> bool:
        """Verify ``signature`` against ``payload`` (used by the verification endpoint).

        Args:
            payload: The raw outgoing body.
            signature: The signature to verify.
            timestamp: The timestamp used to sign; optional for HMAC verify
                (a wrong/missing timestamp fails), but for Ed25519 the
                verification recomputes over the provided timestamp.

        Returns:
            True if the signature is valid.
        """
        data = _normalize_payload(payload)
        if not signature:
            return False
        try:
            if self.algorithm == "svix":
                return self._svix_verify(data, signature, timestamp)
            if timestamp is None:
                return False
            expected = _hmac_hex(self.secret, _signed_message(data, timestamp))
            return hmac.compare_digest(expected, signature.lower())
        except Exception:
            return False

    def _svix_verify(self, payload: bytes, signature: str, timestamp: str | None) -> bool:
        """Verify a base64 Ed25519 signature under the derived key."""
        from cryptography.exceptions import InvalidSignature

        if timestamp is None:
            return False
        try:
            signature_bytes = base64.b64decode(signature, validate=True)
            private_key = _ed25519_signer(self.secret)
            public_key = private_key.public_key()
            message = _signed_message(payload, timestamp)
            public_key.verify(signature_bytes, message)
            return True
        except (InvalidSignature, Exception):
            return False


def verify_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str,
    *,
    timestamp: str | None = None,
) -> bool:
    """Standalone helper: verify a signature against a known secret/algorithm.

    Args:
        payload: The raw signed body (bytes or str).
        signature: The signature string to verify.
        secret: The signing secret.
        algorithm: One of ``svix``, ``hookdeck``, ``github``, ``custom``.
        timestamp: The timestamp used at signing time (defaults to now).

    Returns:
        True if the signature is valid for the given secret/algorithm.
    """
    signer = OutgoingSigner(algorithm=algorithm, secret=secret)
    return signer.verify(payload, signature, timestamp=timestamp)
