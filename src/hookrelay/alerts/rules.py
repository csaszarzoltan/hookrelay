"""Alert rule model — frozen dataclass plus strict validation.

A rule describes a threshold that, when crossed over a rolling window of
delivery history, should raise an alert through the configured notifiers.
Rules are immutable once created (frozen dataclass); field changes go
through ``AlertRuleStore.update`` which returns a new instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Metric = Literal["success_rate_below", "consecutive_failures", "dlq_depth_above"]
Scope = Literal["all", "endpoint"]

_VALID_METRICS: frozenset[str] = frozenset(
    {"success_rate_below", "consecutive_failures", "dlq_depth_above"}
)
_VALID_SCOPES: frozenset[str] = frozenset({"all", "endpoint"})


@dataclass(frozen=True)
class AlertRule:
    """A single alerting threshold rule.

    Attributes:
        rule_id: Stable unique identifier (primary key in the store).
        name: Human-readable rule name (must be non-empty).
        scope: ``"all"`` evaluates over every endpoint; ``"endpoint"``
            restricts evaluation to ``endpoint_id``.
        endpoint_id: Endpoint filter, required when ``scope == "endpoint"``.
        metric: Which delivery statistic is observed.
        threshold: Crossing threshold for the metric (metric-specific range).
        window_minutes: Rolling evaluation window.
        cooldown_minutes: Minimum time between two fires of this rule.
        enabled: Paused rules (``enabled=False``) never fire.
        notifier_ids: Notifiers to fan out to when the rule fires.
        created_at / updated_at: ISO-8601 UTC timestamps.
        last_fired_at: ISO-8601 UTC timestamp of the most recent fire.
    """

    rule_id: str
    name: str
    scope: Scope
    endpoint_id: str | None
    metric: Metric
    threshold: float
    window_minutes: int = 15
    cooldown_minutes: int = 15
    enabled: bool = True
    notifier_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_fired_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the rule to a JSON-safe dict (all contract fields)."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "scope": self.scope,
            "endpoint_id": self.endpoint_id,
            "metric": self.metric,
            "threshold": self.threshold,
            "window_minutes": self.window_minutes,
            "cooldown_minutes": self.cooldown_minutes,
            "enabled": self.enabled,
            "notifier_ids": list(self.notifier_ids),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_fired_at": self.last_fired_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertRule:
        """Rebuild a rule from a dict (e.g. a JSON API payload or DB row)."""
        return cls(
            rule_id=str(data["rule_id"]),
            name=str(data["name"]),
            scope=data["scope"],  # type: ignore[arg-type]
            endpoint_id=data.get("endpoint_id"),
            metric=data["metric"],  # type: ignore[arg-type]
            threshold=float(data["threshold"]),
            window_minutes=int(data.get("window_minutes", 15)),
            cooldown_minutes=int(data.get("cooldown_minutes", 15)),
            enabled=bool(data.get("enabled", True)),
            notifier_ids=list(data.get("notifier_ids") or []),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            last_fired_at=data.get("last_fired_at"),
        )

    def validate(self) -> None:
        """Validate the rule, raising ``ValueError`` on the first problem.

        Enforces: non-empty name; known scope/metric; metric-specific
        threshold ranges (success-rate in (0, 1], counts >= 1);
        ``endpoint`` scope requires an endpoint id; window/cooldown >= 1.
        """
        if not self.name or not self.name.strip():
            raise ValueError("name must not be empty")
        if self.scope not in _VALID_SCOPES:
            raise ValueError(f"scope must be one of {sorted(_VALID_SCOPES)}")
        if self.metric not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        if self.metric == "success_rate_below":
            if not 0.0 < self.threshold <= 1.0:
                raise ValueError("success_rate_below threshold must be in (0, 1]")
        else:
            if self.threshold < 1:
                raise ValueError(
                    f"{self.metric} threshold must be >= 1"
                )
        if self.scope == "endpoint" and not self.endpoint_id:
            raise ValueError("scope 'endpoint' requires endpoint_id")
        if self.window_minutes < 1:
            raise ValueError("window_minutes must be >= 1")
        if self.cooldown_minutes < 1:
            raise ValueError("cooldown_minutes must be >= 1")
