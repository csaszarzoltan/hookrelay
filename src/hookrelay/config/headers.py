"""Header preparation and redaction for outbound deliveries."""

from __future__ import annotations

#: Header names (lowercase) whose values must never be logged or forwarded.
SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "x-authentication-token",
    }
)

#: Replacement value used by :meth:`HeaderManager.redact`.
_REDACTED = "[REDACTED]"


class HeaderManager:
    """Build outbound header sets and redact sensitive values."""

    def __init__(
        self,
        *,
        base_headers: dict[str, str] | None = None,
        injected: dict[str, str] | None = None,
        forward_allowlist: set[str] | None = None,
    ) -> None:
        self._base_headers = dict(base_headers or {})
        self._injected = dict(injected or {})
        self._forward_allowlist = set(forward_allowlist or ())

    def prepare(self, source_headers: dict[str, str] | None = None) -> dict[str, str]:
        """base + allowlisted source headers + injected (injected win)."""
        out = dict(self._base_headers)
        if source_headers:
            allowed = {name.lower() for name in self._forward_allowlist}
            for name, value in source_headers.items():
                if name.lower() in allowed:
                    out[name] = value
        out.update(self._injected)
        return out

    def add_injected(self, name: str, value: str) -> None:
        """Register a header that will always be present in :meth:`prepare` output."""
        self._injected[name] = value

    def redact(self, headers: dict[str, str]) -> dict[str, str]:
        """Mask sensitive names (authorization, cookie, x-api-key, ...)."""
        return {
            name: (_REDACTED if name.lower() in SENSITIVE_HEADER_NAMES else value)
            for name, value in headers.items()
        }
