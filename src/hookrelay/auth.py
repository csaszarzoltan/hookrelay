"""Optional token authentication for dashboard, API, and WebSocket access."""

from __future__ import annotations

import hashlib
import hmac
import os

SESSION_COOKIE = "hookrelay_session"


def configured_token() -> str | None:
    """Return the configured access token, or None for local open mode."""
    value = os.getenv("HOOKRELAY_API_TOKEN", "").strip()
    return value or None


def session_value(token: str) -> str:
    """Derive a non-reversible cookie value from the configured token."""
    return hashlib.sha256(("hookrelay-session-v1:" + token).encode()).hexdigest()


def token_matches(candidate: str | None, expected: str | None = None) -> bool:
    """Compare an access token in constant time."""
    expected = expected if expected is not None else configured_token()
    return bool(candidate and expected and hmac.compare_digest(candidate, expected))


def session_matches(candidate: str | None, token: str | None = None) -> bool:
    """Validate a derived session cookie in constant time."""
    token = token if token is not None else configured_token()
    return bool(candidate and token and hmac.compare_digest(candidate, session_value(token)))



def request_actor(request) -> str:
    """Return a safe audit actor label for a browser or Bearer request."""
    from hookrelay.audit import actor_fingerprint

    token = configured_token()
    if not token:
        return "local-session"
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer ") and token_matches(bearer[7:], token):
        return actor_fingerprint(token)
    if session_matches(request.cookies.get(SESSION_COOKIE), token):
        return actor_fingerprint(token)
    return "unauthenticated"
