"""Alert rule persistence — CRUD over the ``alert_rules`` SQLite table.

Rules are stored as rows (with ``notifier_ids`` JSON-encoded) and exposed
as :class:`~hookrelay.alerts.rules.AlertRule` instances. Fire history lives
in the ``alert_history`` table (migration 7) and every fire is mirrored
into the tamper-evident audit log.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.alerts.rules import AlertRule
from hookrelay.storage import Storage

_COLUMN_TYPES: dict[str, str] = {
    "rule_id": "TEXT",
    "name": "TEXT",
    "scope": "TEXT",
    "endpoint_id": "TEXT",
    "metric": "TEXT",
    "threshold": "REAL",
    "window_minutes": "INTEGER",
    "cooldown_minutes": "INTEGER",
    "enabled": "INTEGER",
    "notifier_ids": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
    "last_fired_at": "TEXT",
}

_UPDATABLE_FIELDS = {
    "name", "scope", "endpoint_id", "metric", "threshold", "window_minutes",
    "cooldown_minutes", "enabled", "notifier_ids", "last_fired_at",
}


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


class AlertRuleStore:
    """CRUD + fire-history persistence for alert rules.

    Args:
        storage: The repo-wide :class:`~hookrelay.storage.Storage` handle.
            All operations share its single SQLite connection.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    # -- row <-> dataclass helpers -------------------------------------

    @staticmethod
    def _row_to_rule(row: Any) -> AlertRule:
        data = dict(row)
        data["notifier_ids"] = json.loads(data.get("notifier_ids") or "[]")
        data["enabled"] = bool(data.get("enabled"))
        return AlertRule.from_dict(data)

    # -- CRUD ----------------------------------------------------------

    def create(self, rule: AlertRule) -> str:
        """Persist a new rule; returns its ``rule_id``."""
        rule.validate()
        self._storage._conn.execute(
            """INSERT INTO alert_rules
               (rule_id, name, scope, endpoint_id, metric, threshold,
                window_minutes, cooldown_minutes, enabled, notifier_ids,
                created_at, updated_at, last_fired_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule.rule_id, rule.name, rule.scope, rule.endpoint_id,
                rule.metric, rule.threshold, rule.window_minutes,
                rule.cooldown_minutes, int(rule.enabled),
                json.dumps(rule.notifier_ids), rule.created_at,
                rule.updated_at, rule.last_fired_at,
            ),
        )
        self._storage._conn.commit()
        return rule.rule_id

    def get(self, rule_id: str) -> AlertRule | None:
        """Return the rule with ``rule_id`` or ``None`` when unknown."""
        row = self._storage._conn.execute(
            "SELECT * FROM alert_rules WHERE rule_id = ?", (rule_id,)
        ).fetchone()
        return self._row_to_rule(row) if row else None

    def list(self) -> list[AlertRule]:
        """Return all rules (no guaranteed order)."""
        rows = self._storage._conn.execute(
            "SELECT * FROM alert_rules"
        ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def update(self, rule_id: str, **fields: Any) -> AlertRule:
        """Partially update a rule; returns the refreshed instance.

        Raises:
            KeyError: when ``rule_id`` is unknown.
            ValueError: when a field is not updatable or the merged rule
                fails validation.
        """
        current = self.get(rule_id)
        if current is None:
            raise KeyError(f"Alert rule {rule_id} not found")
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown rule fields: {sorted(unknown)}")
        merged = current.to_dict()
        merged.update(fields)
        merged["updated_at"] = _now_iso()
        rule = AlertRule.from_dict(merged)
        rule.validate()
        self._storage._conn.execute(
            """UPDATE alert_rules SET
               name = ?, scope = ?, endpoint_id = ?, metric = ?,
               threshold = ?, window_minutes = ?, cooldown_minutes = ?,
               enabled = ?, notifier_ids = ?, updated_at = ?,
               last_fired_at = ?
               WHERE rule_id = ?""",
            (
                rule.name, rule.scope, rule.endpoint_id, rule.metric,
                rule.threshold, rule.window_minutes, rule.cooldown_minutes,
                int(rule.enabled), json.dumps(rule.notifier_ids),
                rule.updated_at, rule.last_fired_at, rule_id,
            ),
        )
        self._storage._conn.commit()
        return self.get(rule_id)  # type: ignore[return-value]

    def delete(self, rule_id: str) -> bool:
        """Delete a rule; returns True when a row was removed."""
        cursor = self._storage._conn.execute(
            "DELETE FROM alert_rules WHERE rule_id = ?", (rule_id,)
        )
        self._storage._conn.commit()
        return cursor.rowcount > 0

    # -- rule lifecycle -------------------------------------------------

    def mark_fired(self, rule_id: str, at: str) -> None:
        """Persist ``last_fired_at`` for a rule (cooldown bookkeeping)."""
        self._storage._conn.execute(
            "UPDATE alert_rules SET last_fired_at = ?, updated_at = ? "
            "WHERE rule_id = ?",
            (at, at, rule_id),
        )
        self._storage._conn.commit()

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        """Toggle a rule's ``enabled`` flag; returns True when the rule exists."""
        cursor = self._storage._conn.execute(
            "UPDATE alert_rules SET enabled = ?, updated_at = ? "
            "WHERE rule_id = ?",
            (int(enabled), _now_iso(), rule_id),
        )
        self._storage._conn.commit()
        return cursor.rowcount > 0

    # -- fire history (migration 7) --------------------------------------

    def record_fire(
        self,
        *,
        rule_id: str,
        rule_name: str | None = None,
        metric: str | None = None,
        observed_value: float | None = None,
        threshold: float | None = None,
        message: str | None = None,
        fired_at: str | None = None,
        outcome: str = "success",
    ) -> str:
        """Persist one fired alert into ``alert_history`` and the audit log.

        Returns the generated ``event_id``.
        """
        event_id = uuid4().hex
        fired_at = fired_at or _now_iso()
        self._storage._conn.execute(
            """INSERT INTO alert_history
               (event_id, rule_id, rule_name, metric, observed_value,
                threshold, message, fired_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, rule_id, rule_name, metric, observed_value,
                threshold, message, fired_at,
            ),
        )
        self._storage._conn.commit()
        self._storage.record_audit_event(
            "alert.fired" if outcome == "success" else "alert.failed",
            "evaluator",
            "alert_rule",
            rule_id,
            outcome,
            details={
                "event_id": event_id,
                "metric": metric,
                "observed_value": observed_value,
                "threshold": threshold,
                "fired_at": fired_at,
            },
        )
        return event_id

    def list_history(
        self, rule_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        """Return fired-alert events, newest first.

        Args:
            rule_id: Optional filter to one rule.
            limit: Maximum rows (clamped to [1, 1000]).
        """
        limit = max(1, min(int(limit), 1000))
        query = "SELECT * FROM alert_history"
        params: list[Any] = []
        if rule_id is not None:
            query += " WHERE rule_id = ?"
            params.append(rule_id)
        query += " ORDER BY fired_at DESC, event_id DESC LIMIT ?"
        params.append(limit)
        rows = self._storage._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
