"""Alert evaluator — periodic threshold evaluation over delivery history.

Runs a configurable loop (default 60s) in a daemon thread; each cycle
evaluates every enabled rule's metric over its rolling ``window_minutes``
and fires through the notifier registry only when the threshold is crossed
AND the per-rule cooldown has elapsed. Rules that cannot be evaluated (no
data, missing table) never fire and never raise.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hookrelay.alerts.rules import AlertRule
from hookrelay.alerts.storage import AlertRuleStore
from hookrelay.delivery import DeadLetterQueue

_FIRE_MESSAGES: dict[str, str] = {
    "success_rate_below": (
        "Success rate {observed:.1%} is below threshold {threshold:.1%} "
        "over the last {window} minute(s)"
    ),
    "consecutive_failures": (
        "{observed:.0f} consecutive failures (threshold {threshold:.0f}) "
        "over the last {window} minute(s)"
    ),
    "dlq_depth_above": (
        "Dead-letter queue depth {observed:.0f} is above threshold "
        "{threshold:.0f}"
    ),
}


@dataclass(frozen=True)
class FiredAlert:
    """One fired alert payload handed to the notifier registry."""

    rule_id: str
    rule_name: str
    metric: str
    observed_value: float
    threshold: float
    message: str

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "metric": self.metric,
            "observed_value": self.observed_value,
            "threshold": self.threshold,
            "message": self.message,
        }


def default_now() -> datetime:
    """Return the current UTC time (the evaluator's default clock)."""
    return datetime.now(UTC)


class AlertEvaluator:
    """Evaluate alert rules on a configurable loop.

    Args:
        store: Rule source (``list`` / ``mark_fired`` are required).
        notifier_registry: Object with ``send_to(notifier_ids, alert)``.
        now: Injectable clock for deterministic tests (defaults to UTC now).
    """

    def __init__(
        self,
        store: Any,
        notifier_registry: Any,
        *,
        now: Callable[[], datetime] = default_now,
    ) -> None:
        self._store = store
        self._registry = notifier_registry
        self._now = now
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # -- public API -----------------------------------------------------

    def run_once(self) -> list[Any]:
        """Evaluate every enabled rule once and fire crossed thresholds.

        Returns the list of :class:`FiredAlert` payloads that fired this
        cycle. Fires are also delivered to the registry and recorded as
        history + audit events.
        """
        fired: list[Any] = []
        now = self._now()
        try:
            rules = self._store.list()
        except Exception:
            return fired
        for rule in rules:
            if not rule.enabled:
                continue
            value = self.evaluate_metric(rule)
            if value is None:
                continue
            if not self._threshold_crossed(rule, value):
                continue
            if not self._cooldown_elapsed(rule, now):
                continue
            alert = FiredAlert(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                metric=rule.metric,
                observed_value=value,
                threshold=rule.threshold,
                message=self._build_message(rule, value),
            )
            self._deliver(rule, alert, now)
            fired.append(alert)
        return fired

    def start(self, interval_seconds: int | None = None) -> None:
        """Launch the daemon loop thread.

        Args:
            interval_seconds: Cycle period; ``None`` keeps the evaluator's
                default (60). A thread already running is left untouched.
        """
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(interval_seconds if interval_seconds is not None else 60,),
            name="hookrelay-alert-evaluator",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to stop and join the thread."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def is_running(self) -> bool:
        """Return True while the loop thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def evaluate_metric(self, rule: AlertRule) -> float | None:
        """Compute a rule's current metric value (or ``None`` for no data).

        ``success_rate_below``: delivered/(delivered+failed) over the
        window (pending excluded — same math as SuccessRateCalculator).
        ``consecutive_failures``: length of the trailing run of
        failed/in-dlq deliveries.
        ``dlq_depth_above``: total rows in the dead-letter queue.
        """
        if rule.metric == "success_rate_below":
            return self._success_rate(rule)
        if rule.metric == "consecutive_failures":
            return self._consecutive_failures(rule)
        if rule.metric == "dlq_depth_above":
            return self._dlq_depth(rule)
        return None

    # -- metric implementations -----------------------------------------

    def _success_rate(self, rule: AlertRule) -> float | None:
        conn = self._storage_conn()
        if not _deliveries_table_exists(conn):
            return None
        conditions = ["status IN ('delivered', 'failed', 'in-dlq')"]
        params: list[Any] = []
        if rule.scope == "endpoint" and rule.endpoint_id:
            conditions.append("endpoint_id = ?")
            params.append(rule.endpoint_id)
        # Window anchor: the later of the evaluator's clock and the most
        # recent delivery. The window then spans [anchor - window, anchor],
        # i.e. "the last window_minutes of delivery activity". Anchoring on
        # the latest delivery keeps the metric correct under clock skew
        # between the writer and the evaluator (and keeps tests with an
        # injectable clock deterministic).
        anchor = self._now()
        latest = conn.execute(
            "SELECT MAX(created_at) AS latest FROM deliveries"
        ).fetchone()
        latest_ts = latest["latest"] if latest and latest["latest"] else None
        if latest_ts:
            try:
                latest_dt = datetime.fromisoformat(latest_ts)
                if latest_dt.tzinfo is None:
                    latest_dt = latest_dt.replace(tzinfo=UTC)
                anchor = max(anchor, latest_dt)
            except (TypeError, ValueError):
                pass
        cutoff = anchor - timedelta(minutes=rule.window_minutes)
        conditions.append("created_at >= ?")
        params.append(cutoff.isoformat())
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM deliveries WHERE "
            + " AND ".join(conditions)
            + " GROUP BY status",
            params,
        ).fetchall()
        delivered = failed = 0
        for row in rows:
            if row["status"] == "delivered":
                delivered += int(row["n"])
            else:
                failed += int(row["n"])
        total = delivered + failed
        if total == 0:
            return None
        return delivered / total

    def _consecutive_failures(self, rule: AlertRule) -> float | None:
        """Trailing consecutive run of failed/in-dlq deliveries in window.

        ``consecutive_failures`` semantics: the number of most recent
        deliveries (per endpoint when scoped) that are ``failed`` or
        ``in-dlq``, counted within the rule's rolling ``window_minutes``
        and only up to now — i.e. the *trailing* run, not the longest
        run in history. Rows are considered newest-first from the most
        recent ``created_at``; a ``delivered``/``pending`` row (or a gap
        of no data, or a row older than the window cutoff) ends the run
        and older rows are not counted. Matches the analyzer contract
        \"count of consecutive failed/in-dlq deliveries up to now\".

        Note: the window is anchored to the evaluator clock (``now``),
        matching the other metrics. Rows with ``created_at`` in the
        future relative to ``now`` are outside the \"up to now\" window
        and never start or extend the run.
        """
        conn = self._storage_conn()
        if not _deliveries_table_exists(conn):
            return None
        params: list[Any] = []
        conditions = ["created_at >= ?"]
        params.append(
            (self._now() - timedelta(minutes=rule.window_minutes)).isoformat()
        )
        if rule.scope == "endpoint" and rule.endpoint_id:
            conditions.append("endpoint_id = ?")
            params.append(rule.endpoint_id)
        query = "SELECT status FROM deliveries"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        rows = conn.execute(
            query + " ORDER BY created_at DESC, delivery_id DESC", params
        ).fetchall()
        trailing = 0
        for row in rows:
            if row["status"] in ("failed", "in-dlq"):
                trailing += 1
            else:
                break
        return float(trailing) if trailing > 0 else None

    def _dlq_depth(self, rule: AlertRule) -> float | None:
        conn = self._storage_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'dlq'"
            ).fetchone()
        except Exception:
            return None
        if row is None:
            # No dlq table yet (fresh DB): the rule cannot be evaluated.
            return None
        try:
            dlq = DeadLetterQueue(self._storage_handle())
            if rule.scope == "endpoint" and rule.endpoint_id:
                entries = dlq.list_entries(limit=100000, endpoint_id=rule.endpoint_id)
                return float(len(entries))
            return float(dlq.count())
        except Exception:
            return None

    # -- fire helpers ----------------------------------------------------

    @staticmethod
    def _threshold_crossed(rule: AlertRule, value: float) -> bool:
        if rule.metric == "success_rate_below":
            return value < rule.threshold
        return value >= rule.threshold

    def _cooldown_elapsed(self, rule: AlertRule, now: datetime) -> bool:
        if not rule.last_fired_at:
            return True
        try:
            last = datetime.fromisoformat(rule.last_fired_at)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return now - last >= timedelta(minutes=rule.cooldown_minutes)

    def _build_message(self, rule: AlertRule, value: float) -> str:
        template = _FIRE_MESSAGES.get(rule.metric, "{metric} threshold crossed")
        return template.format(
            observed=value,
            threshold=rule.threshold,
            window=rule.window_minutes,
            metric=rule.metric,
        )

    def _deliver(self, rule: AlertRule, alert: FiredAlert, now: datetime) -> None:
        """Send the alert, then persist last_fired_at + history/audit."""
        fired_at = now.isoformat()
        results: dict[str, bool] = {}
        try:
            results = self._registry.send_to(list(rule.notifier_ids), alert.to_dict())
        except Exception:
            results = {}
        delivered = bool(results) and all(results.values())
        try:
            self._store.mark_fired(rule.rule_id, fired_at)
        except Exception:
            pass
        try:
            self._store.record_fire(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                metric=rule.metric,
                observed_value=alert.observed_value,
                threshold=alert.threshold,
                message=alert.message,
                fired_at=fired_at,
                outcome="success" if delivered else "failed",
            )
        except Exception:
            pass

    # -- thread loop ------------------------------------------------------

    def _loop(self, interval_seconds: int) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                pass
            self._stop_event.wait(timeout=interval_seconds)

    # -- storage plumbing --------------------------------------------------

    def _storage_handle(self) -> Any:
        """Return the underlying Storage handle.

        The evaluator receives a rule store (which may be a stub in tests);
        when it wraps a real :class:`AlertRuleStore`, the backing Storage
        is recovered for metric queries.
        """
        if isinstance(self._store, AlertRuleStore):
            return self._store._storage
        return getattr(self._store, "_storage", self._store)

    def _storage_conn(self) -> Any:
        return getattr(self._storage_handle(), "_conn", None)


def _deliveries_table_exists(conn: Any) -> bool:
    """Return True when the ``deliveries`` table exists (else treat as empty)."""
    if conn is None:
        return False
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'deliveries'"
    ).fetchone()
    return row is not None
