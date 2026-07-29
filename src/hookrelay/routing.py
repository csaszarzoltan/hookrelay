"""Conditional routing rules for webhook forwarding.

Provides RoutingRule data model and RouterEngine for evaluating
rules against incoming webhook payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hookrelay.filters import FilterExpressionParser


class RoutingRule:
    """A conditional routing rule that directs matching webhooks to a target.

    Fields:
        rule_id: Unique identifier for the rule.
        name: Human-readable name.
        enabled: Whether the rule is active.
        priority: Evaluation order (lower = evaluated first).
        condition: Filter expression string or RequestFilter specification.
        target_endpoint: URL to forward matching requests to.
        channel: The webhook channel this rule applies to.
        max_forward_count: Optional cap on forwarding frequency.
        fallback: If True, this rule acts as a catch-all default.
        created_at: ISO-format timestamp.
    """

    def __init__(
        self,
        rule_id: str,
        name: str,
        enabled: bool = True,
        priority: int = 100,
        condition: str | None = None,
        target_endpoint: str | None = None,
        channel: str | None = None,
        max_forward_count: int | None = None,
        fallback: bool = False,
        created_at: str | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.name = name
        self.enabled = enabled
        self.priority = priority
        self.condition = condition
        self.target_endpoint = target_endpoint
        self.channel = channel
        self.max_forward_count = max_forward_count
        self.fallback = fallback
        self.created_at = created_at or datetime.now(
            UTC
        ).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "condition": self.condition,
            "target_endpoint": self.target_endpoint,
            "channel": self.channel,
            "max_forward_count": self.max_forward_count,
            "fallback": self.fallback,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingRule:
        """Deserialize from dictionary."""
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            condition=data.get("condition"),
            target_endpoint=data.get("target_endpoint"),
            channel=data.get("channel"),
            max_forward_count=data.get("max_forward_count"),
            fallback=data.get("fallback", False),
            created_at=data.get("created_at"),
        )

    def __repr__(self) -> str:
        return (
            f"RoutingRule(rule_id={self.rule_id!r}, name={self.name!r}, "
            f"priority={self.priority})"
        )


class RouterEngine:
    """Evaluates routing rules against incoming webhooks.

    Supports first-match-wins mode (default) and evaluate-all mode.
    Unmatched requests fall back to broadcast to all clients.
    """

    def __init__(self) -> None:
        self._rules: dict[str, RoutingRule] = {}
        self._priority_order: list[str] = []  # rule_ids sorted by priority
        self._stop_on_first: bool = True

    def add_rule(self, rule: RoutingRule) -> None:
        """Add a routing rule."""
        self._rules[rule.rule_id] = rule
        self._resort()

    def remove_rule(self, rule_id: str) -> None:
        """Remove a routing rule by ID."""
        self._rules.pop(rule_id, None)
        self._priority_order = [r for r in self._priority_order if r != rule_id]

    def reorder(self, rule_ids: list[str]) -> None:
        """Reorder rules by priority (first = highest priority)."""
        # Validate all ids exist
        for rid in rule_ids:
            if rid not in self._rules:
                raise ValueError(f"Unknown rule_id: {rid}")

        # Reassign priorities based on order (0 = highest)
        self._priority_order = rule_ids
        for i, rid in enumerate(rule_ids):
            self._rules[rid].priority = i

    def evaluate(
        self, channel: str, request_data: dict[str, Any]
    ) -> list[tuple[RoutingRule, dict[str, Any]]]:
        """Evaluate rules against a request.

        Returns list of (rule, match_result) tuples for matched rules.
        In first-match-wins mode, at most one result is returned.
        """
        results: list[tuple[RoutingRule, dict[str, Any]]] = []

        for rid in self._priority_order:
            rule = self._rules[rid]
            if not rule.enabled:
                continue
            if rule.channel and rule.channel != channel:
                continue

            # Build RequestFilter from condition expression
            if rule.condition:
                try:
                    request_filter = FilterExpressionParser.parse(
                        rule.condition
                    )
                    matched = request_filter.apply([request_data])
                    is_match = len(matched) > 0
                except Exception:
                    is_match = False
            else:
                # No condition = matches all requests
                is_match = True

            if is_match:
                match_result = {
                    "rule_id": rule.rule_id,
                    "matched": True,
                    "condition": rule.condition or "(none)",
                    "matched_criteria": [rule.condition or "fallback"],
                }
                results.append((rule, match_result))
                if self._stop_on_first:
                    break

        return results

    def set_stop_on_first(self, enabled: bool) -> None:
        """Set stop-on-first-match mode (default: True)."""
        self._stop_on_first = enabled

    def _resort(self) -> None:
        """Re-sort priority order based on rule priorities."""
        sorted_rules = sorted(
            self._rules.values(), key=lambda r: (r.priority, r.rule_id)
        )
        self._priority_order = [r.rule_id for r in sorted_rules]
