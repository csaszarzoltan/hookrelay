"""Per-endpoint delivery configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from hookrelay.config.retry_policy import RetryPolicy
from hookrelay.ssrf import validate_target_url

#: Protocols accepted by :meth:`EndpointConfig.validate`.
_ALLOWED_SCHEMES = ("http", "https")


@dataclass(frozen=True)
class EndpointConfig:
    """Configuration for one outbound webhook endpoint."""

    endpoint_id: str
    name: str
    url: str
    timeout_seconds: float = 30.0
    retry_policy: RetryPolicy = RetryPolicy()  # noqa: RUF009 - spec-mandated immutable default
    headers: dict[str, str] = field(default_factory=dict)
    secret: str | None = None
    enabled: bool = True
    channel: str | None = None
    idempotency_ttl_seconds: int = 86400

    def to_dict(self) -> dict:
        """Serialize to a plain dict (``retry_policy`` becomes a nested dict)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> EndpointConfig:
        """Reconstruct from a dict; unknown keys are ignored, defaults apply for missing."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        if isinstance(known.get("retry_policy"), dict):
            known["retry_policy"] = RetryPolicy.from_dict(known["retry_policy"])
        return cls(**known)

    def validate(self) -> None:
        """Raise ValueError on bad url / timeout <= 0 / max_retries < 0.

        URL validation delegates to the repo's shared SSRF guard
        (:func:`hookrelay.ssrf.validate_target_url`) so that the same
        checks apply whether the URL is supplied at configuration time
        or at enqueue/dispatch time.  Private IPs, link-local addresses,
        and system ports (< 1024) are rejected.
        """
        if not self.url:
            raise ValueError("endpoint url must not be empty")
        parsed = urlparse(self.url)
        if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
            raise ValueError(f"invalid endpoint url: {self.url!r}")
        is_valid, reason = validate_target_url(self.url)
        if not is_valid:
            raise ValueError(f"endpoint url fails SSRF guard: {reason}")
        if self.timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got {self.timeout_seconds!r}")
        if self.retry_policy.max_retries < 0:
            raise ValueError(
                f"max_retries must be >= 0, got {self.retry_policy.max_retries!r}"
            )
