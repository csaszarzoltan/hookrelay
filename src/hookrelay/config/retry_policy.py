"""Retry policy with exponential backoff for outbound deliveries."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff policy for delivery retries."""

    max_retries: int = 5
    backoff_factor: float = 2.0
    base_delay_seconds: float = 1.0
    max_backoff_seconds: float = 3600.0
    jitter: bool = True

    def backoff_delay(self, attempt: int) -> float:
        """min(max_backoff, base_delay * factor**attempt), plus jitter in [0, delay)."""
        base = min(
            self.max_backoff_seconds,
            self.base_delay_seconds * (self.backoff_factor**attempt),
        )
        if not self.jitter:
            return base
        return base + random.random() * base

    def to_dict(self) -> dict:
        """Serialize to a plain dict (all five fields)."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RetryPolicy:
        """Reconstruct from a dict; missing keys fall back to defaults."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)
