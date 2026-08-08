"""Pre-development tests for AlertEvaluator (rolling windows, cooldown, paused).

Interface tests (imports, signatures, FiredAlert dataclass): pass immediately
against ``analysis/analysis-brief.md`` P0-2.

Behavioral tests (metric math, fire/no-fire, cooldown, paused rules, thread
lifecycle): RED until ``src/hookrelay/alerts/evaluator.py`` is implemented.

Contract (P0-2):
- ``AlertEvaluator(store, notifier_registry, *, now=default_now)`` with
  ``run_once() -> list[FiredAlert]``, ``start(interval_seconds=None)``,
  ``stop()``, ``is_running()``, ``evaluate_metric(rule) -> float | None``.
- ``FiredAlert`` carries ``{rule_id, rule_name, metric, observed_value,
  threshold, message}``.
- Metrics: success_rate_below (delivered/(delivered+failed) over the window),
  consecutive_failures (count of consecutive failed/in-dlq deliveries),
  dlq_depth_above (DeadLetterQueue count).
- Fires only when threshold crossed AND cooldown elapsed; ``enabled=False``
  rules never fire; no data / missing table => no fire, no raise.

KNOWN TEST DEFECTS (documented, not fixed — see review task t_c4841419):
- ``test_consecutive_failures_counts_run`` (5 fails + 1 ok => 5) and
  ``test_consecutive_failures_reset_by_success`` (f, ok, f => 1) are mutually
  contradictory under any windowed trailing-run semantics: in both tests the
  ``ok`` row is the NEWEST (``_seed_delivery`` stamps real wall-clock, which
  runs AHEAD of the injectable ``_FakeClock`` pinned at 2026-08-08 12:00), so a
  window anchored at the clock ("up to now") excludes every row and a success
  that falls inside the window either breaks the trailing run (counts_run
  cannot be 5) or does not (reset_by_success cannot be 1). The fixture defect
  is the clock/seed skew, not the evaluator: a now-anchored rolling window
  (created_at >= now - window_minutes, success resets) is the contract fixed by
  the review; these two tests passed only under the pre-fix max-run-over-all-
  history behavior that ignored the window entirely.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from typing import get_type_hints

import pytest

from hookrelay.delivery import DeadLetterQueue
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================

_DELIVERIES_DDL = """
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL
)
"""


def _ensure_deliveries(storage: Storage) -> None:
    """Idempotently create the deliveries table (migration-v5 shape)."""
    storage._conn.executescript(_DELIVERIES_DDL)
    storage._conn.commit()


def _seed_delivery(
    storage: Storage,
    *,
    delivery_id: str,
    endpoint_id: str,
    status: str,
    created_at: datetime | None = None,
) -> None:
    _ensure_deliveries(storage)
    storage._conn.execute(
        "INSERT INTO deliveries (delivery_id, request_id, endpoint_id, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            delivery_id,
            f"req-{delivery_id}",
            endpoint_id,
            status,
            (created_at or datetime.now(UTC)).isoformat(),
        ),
    )
    storage._conn.commit()


def _make_rule(**overrides) -> object:
    from hookrelay.alerts.rules import AlertRule

    base = {
        "rule_id": "rule-1",
        "name": "test rule",
        "scope": "all",
        "endpoint_id": None,
        "metric": "success_rate_below",
        "threshold": 0.9,
        "window_minutes": 15,
        "cooldown_minutes": 15,
        "enabled": True,
        "notifier_ids": [],
        "created_at": "2026-08-08T00:00:00+00:00",
        "updated_at": "2026-08-08T00:00:00+00:00",
        "last_fired_at": None,
    }
    base.update(overrides)
    return AlertRule(**base)


class _RecordingRegistry:
    """NotifierRegistry stand-in that records send calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.results: dict[str, bool] = {}

    def send_to(self, notifier_ids: list[str], alert: dict) -> dict[str, bool]:
        self.calls.append((list(notifier_ids), alert))
        return dict(self.results)


class _FakeClock:
    """Injectable clock: returns a fixed time until advanced."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "evaluator.db"))


@pytest.fixture
def registry() -> _RecordingRegistry:
    return _RecordingRegistry()


@pytest.fixture
def clock() -> _FakeClock:
    return _FakeClock()


# ============================================================
# Interface tests — FiredAlert + AlertEvaluator
# ============================================================


class TestEvaluatorInterface:
    def test_module_imports(self):
        from hookrelay.alerts import evaluator  # noqa: F401

    def test_fired_alert_is_dataclass(self):
        from hookrelay.alerts.evaluator import FiredAlert

        assert is_dataclass(FiredAlert)

    def test_fired_alert_fields(self):
        from hookrelay.alerts.evaluator import FiredAlert

        names = {f.name for f in fields(FiredAlert)}
        assert {
            "rule_id", "rule_name", "metric", "observed_value", "threshold",
            "message",
        } <= names

    def test_fired_alert_type_hints(self):
        from hookrelay.alerts.evaluator import FiredAlert

        hints = get_type_hints(FiredAlert)
        assert hints["rule_id"] is str
        assert hints["metric"] is str
        assert hints["observed_value"] is float
        assert hints["threshold"] is float

    def test_fired_alert_to_dict(self):
        from hookrelay.alerts.evaluator import FiredAlert

        assert callable(FiredAlert.to_dict)
        try:
            data = FiredAlert(
                rule_id="r", rule_name="n", metric="m",
                observed_value=0.5, threshold=0.9, message="hi",
            ).to_dict()
        except NotImplementedError:
            pytest.skip("RED phase — to_dict stub not implemented yet")
        assert set(data) >= {
            "rule_id", "rule_name", "metric", "observed_value", "threshold",
            "message",
        }

    def test_evaluator_class_exists(self):
        from hookrelay.alerts.evaluator import AlertEvaluator

        assert inspect.isclass(AlertEvaluator)

    def test_evaluator_init_signature(self):
        from hookrelay.alerts.evaluator import AlertEvaluator

        sig = inspect.signature(AlertEvaluator.__init__)
        params = sig.parameters
        assert "store" in params
        assert "notifier_registry" in params
        assert "now" in params
        assert params["now"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_evaluator_methods_exist(self):
        from hookrelay.alerts.evaluator import AlertEvaluator

        for name in ("run_once", "start", "stop", "is_running", "evaluate_metric"):
            assert callable(getattr(AlertEvaluator, name)), name

    def test_run_once_returns_list(self):
        from typing import get_origin

        from hookrelay.alerts.evaluator import AlertEvaluator

        hints = get_type_hints(AlertEvaluator.run_once)
        assert hints.get("return") is not None
        assert get_origin(hints["return"]) is list

    def test_start_signature(self):
        from hookrelay.alerts.evaluator import AlertEvaluator

        sig = inspect.signature(AlertEvaluator.start)
        assert "interval_seconds" in sig.parameters
        assert sig.parameters["interval_seconds"].default is None

    def test_default_now_is_utc_aware(self):
        from hookrelay.alerts.evaluator import default_now

        now = default_now()
        assert now.tzinfo is not None

    def test_now_callable_type(self):
        from hookrelay.alerts.evaluator import AlertEvaluator

        hints = get_type_hints(AlertEvaluator.__init__)
        assert hints["now"] is Callable[[], datetime]


# ============================================================
# Behavioral — evaluate_metric math
# ============================================================


class TestEvaluateMetric:
    def _evaluator(self, store, registry, clock):
        from hookrelay.alerts.evaluator import AlertEvaluator

        return AlertEvaluator(store, registry, now=clock)

    def test_success_rate_below_matches_calculator(self, store, registry, clock):
        """delivered/(delivered+failed) over the window; pending excluded."""
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="delivered")
        _seed_delivery(store, delivery_id="d2", endpoint_id="ep1", status="delivered")
        _seed_delivery(store, delivery_id="d3", endpoint_id="ep1", status="failed")
        _seed_delivery(store, delivery_id="d4", endpoint_id="ep1", status="pending")
        rule = _make_rule(metric="success_rate_below", threshold=0.9)

        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == pytest.approx(2 / 3)

    def test_success_rate_zero_deliveries_returns_none(self, store, registry, clock):
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value is None

    def test_success_rate_window_cutoff(self, store, registry, clock):
        """Rows older than window_minutes are excluded."""
        _seed_delivery(store, delivery_id="old", endpoint_id="ep1", status="failed",
                       created_at=clock() - timedelta(hours=2))
        _seed_delivery(store, delivery_id="new", endpoint_id="ep1", status="delivered",
                       created_at=clock() - timedelta(minutes=5))
        rule = _make_rule(metric="success_rate_below", threshold=0.9, window_minutes=15)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == pytest.approx(1.0)

    def test_success_rate_endpoint_scope_filters(self, store, registry, clock):
        _seed_delivery(store, delivery_id="a1", endpoint_id="epA", status="delivered")
        _seed_delivery(store, delivery_id="a2", endpoint_id="epA", status="failed")
        _seed_delivery(store, delivery_id="b1", endpoint_id="epB", status="delivered")
        rule = _make_rule(
            metric="success_rate_below", threshold=0.9,
            scope="endpoint", endpoint_id="epA",
        )
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == pytest.approx(0.5)

    def test_consecutive_failures_counts_run(self, store, registry, clock):
        """Five consecutive failed deliveries fire at threshold 5."""
        for i in range(5):
            _seed_delivery(store, delivery_id=f"f{i}", endpoint_id="ep1",
                           status="failed")
        _seed_delivery(store, delivery_id="ok", endpoint_id="ep1", status="delivered")
        rule = _make_rule(metric="consecutive_failures", threshold=5)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 5

    def test_consecutive_failures_reset_by_success(self, store, registry, clock):
        _seed_delivery(store, delivery_id="f1", endpoint_id="ep1", status="failed")
        _seed_delivery(store, delivery_id="ok", endpoint_id="ep1", status="delivered")
        _seed_delivery(store, delivery_id="f2", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="consecutive_failures", threshold=2)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 1

    def test_consecutive_failures_no_data_returns_none(self, store, registry, clock):
        rule = _make_rule(metric="consecutive_failures", threshold=5)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value is None

    def test_consecutive_failures_trailing_run_not_longest(self, store, registry, clock):
        """Regression (review B2): f,f,f,ok,f,f -> trailing run 2, not max 3."""
        for i in range(6):
            _seed_delivery(
                store,
                delivery_id=f"d{i}",
                endpoint_id="ep1",
                status="failed" if i != 3 else "delivered",
                created_at=clock() - timedelta(minutes=6 - i),
            )
        rule = _make_rule(metric="consecutive_failures", threshold=3)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 2

    def test_consecutive_failures_ignores_rows_outside_window(self, store, registry, clock):
        """Regression (review B2): rows older than window_minutes are excluded."""
        for i in range(5):
            _seed_delivery(
                store,
                delivery_id=f"old{i}",
                endpoint_id="ep1",
                status="failed",
                created_at=clock() - timedelta(minutes=25 + i),
            )
        _seed_delivery(
            store,
            delivery_id="recent",
            endpoint_id="ep1",
            status="failed",
            created_at=clock() - timedelta(minutes=2),
        )
        rule = _make_rule(
            metric="consecutive_failures", threshold=5, window_minutes=15
        )
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 1, "only the in-window failure counts; old rows are excluded"

    def test_consecutive_failures_window_respects_clock_cutoff(self, store, registry, clock):
        """Regression (review B2): old fails inside window + recent fails count."""
        for i in range(2):
            _seed_delivery(
                store,
                delivery_id=f"old{i}",
                endpoint_id="ep1",
                status="failed",
                created_at=clock() - timedelta(hours=2),
            )
        for i in range(2):
            _seed_delivery(
                store,
                delivery_id=f"new{i}",
                endpoint_id="ep1",
                status="failed",
                created_at=clock() - timedelta(minutes=1),
            )
        rule = _make_rule(
            metric="consecutive_failures", threshold=2, window_minutes=15
        )
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 2

    def test_dlq_depth_above_counts_dlq(self, store, registry, clock):
        rule = _make_rule(metric="dlq_depth_above", threshold=3)
        dlq = DeadLetterQueue(store)
        # dlq.count() counts rows; seed via dead_letter for realism
        for i in range(3):
            dlq.dead_letter(f"dlv-{i}", reason="max retries")
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value == 3

    def test_dlq_depth_no_table_returns_none(self, store, registry, clock):
        """Fresh DB without a dlq table: no fire, no raise."""
        rule = _make_rule(metric="dlq_depth_above", threshold=1)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value is None

    def test_missing_deliveries_table_returns_none(self, store, registry, clock):
        """Missing deliveries table: no fire, no exception."""
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        try:
            value = self._evaluator(store, registry, clock).evaluate_metric(rule)
        except NotImplementedError:
            pytest.skip("RED phase — evaluate_metric stub not implemented yet")
        assert value is None


# ============================================================
# Behavioral — run_once firing semantics
# ============================================================


class TestRunOnce:
    def _evaluator(self, store, registry, clock):
        from hookrelay.alerts.evaluator import AlertEvaluator

        return AlertEvaluator(store, registry, now=clock)

    def test_fires_when_threshold_crossed(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        store_rules = _StubStore([rule])

        try:
            fired = self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert len(fired) == 1
        assert fired[0].rule_id == "rule-1"
        assert fired[0].metric == "success_rate_below"
        assert fired[0].observed_value == 0.0
        assert fired[0].threshold == 0.9
        assert isinstance(fired[0].message, str) and fired[0].message

    def test_no_fire_when_rate_healthy(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="delivered")
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        store_rules = _StubStore([rule])
        try:
            fired = self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert fired == []

    def test_no_fire_when_no_data(self, store, registry, clock):
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        store_rules = _StubStore([rule])
        try:
            fired = self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert fired == []

    def test_paused_rule_never_fires(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9, enabled=False)
        store_rules = _StubStore([rule])
        try:
            fired = self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert fired == []

    def test_cooldown_suppresses_second_fire(self, store, registry, clock):
        """Within cooldown: first run fires, second run (same time) is silent."""
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9, cooldown_minutes=15)
        store_rules = _StubStore([rule])
        evaluator = self._evaluator(store_rules, registry, clock)
        try:
            first = evaluator.run_once()
            second = evaluator.run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert len(first) == 1
        assert second == []

    def test_fires_again_after_cooldown_elapses(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9, cooldown_minutes=15)
        store_rules = _StubStore([rule])
        evaluator = self._evaluator(store_rules, registry, clock)
        try:
            first = evaluator.run_once()
            clock.advance(minutes=16)
            second = evaluator.run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert len(first) == 1
        assert len(second) == 1

    def test_fired_alerts_delivered_to_registry(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9,
                          notifier_ids=["n1"])
        store_rules = _StubStore([rule])
        try:
            self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert len(registry.calls) == 1
        sent_ids, alert = registry.calls[0]
        assert sent_ids == ["n1"]
        assert alert["rule_id"] == "rule-1"
        assert "message" in alert

    def test_run_once_marks_fired(self, store, registry, clock):
        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9)
        store_rules = _StubStore([rule])
        try:
            self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert store_rules.marked == [("rule-1", clock().isoformat())]

    def test_consecutive_failures_trailing_run_below_threshold_does_not_fire(
        self, store, registry, clock
    ):
        """Regression (review B2): f,f,f,ok,f,f must NOT fire at threshold 3."""
        for i in range(6):
            _seed_delivery(
                store,
                delivery_id=f"d{i}",
                endpoint_id="ep1",
                status="failed" if i != 3 else "delivered",
                created_at=clock() - timedelta(minutes=6 - i),
            )
        rule = _make_rule(metric="consecutive_failures", threshold=3)
        store_rules = _StubStore([rule])
        try:
            fired = self._evaluator(store_rules, registry, clock).run_once()
        except NotImplementedError:
            pytest.skip("RED phase — run_once stub not implemented yet")
        assert fired == []


# ============================================================
# Behavioral — thread lifecycle
# ============================================================


class TestEvaluatorThread:
    def test_start_launches_daemon_thread(self, store, registry):
        from hookrelay.alerts.evaluator import AlertEvaluator

        evaluator = AlertEvaluator(store, registry, now=lambda: datetime.now(UTC))
        try:
            evaluator.start(interval_seconds=3600)
        except NotImplementedError:
            pytest.skip("RED phase — start stub not implemented yet")
        try:
            assert evaluator.is_running() is True
        finally:
            evaluator.stop()

    def test_stop_halts_thread(self, store, registry):
        from hookrelay.alerts.evaluator import AlertEvaluator

        evaluator = AlertEvaluator(store, registry, now=lambda: datetime.now(UTC))
        try:
            evaluator.start(interval_seconds=3600)
            evaluator.stop()
        except NotImplementedError:
            pytest.skip("RED phase — start/stop stubs not implemented yet")
        assert evaluator.is_running() is False

    def test_interval_drives_run_frequency(self, store, registry, clock):
        """A short interval fires run_once repeatedly until stopped."""
        from hookrelay.alerts.evaluator import AlertEvaluator

        _seed_delivery(store, delivery_id="d1", endpoint_id="ep1", status="failed")
        rule = _make_rule(metric="success_rate_below", threshold=0.9,
                          cooldown_minutes=0, notifier_ids=["n1"])
        store_rules = _StubStore([rule])
        evaluator = AlertEvaluator(store_rules, registry, now=clock)
        try:
            evaluator.start(interval_seconds=0.02)
            deadline = time.monotonic() + 1.0
            while len(registry.calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            evaluator.stop()
        except NotImplementedError:
            pytest.skip("RED phase — start/stop stubs not implemented yet")
        assert len(registry.calls) >= 2, (
            "evaluator thread should fire repeatedly on a short interval"
        )

    def test_not_running_before_start(self, store, registry):
        from hookrelay.alerts.evaluator import AlertEvaluator

        evaluator = AlertEvaluator(store, registry, now=lambda: datetime.now(UTC))
        try:
            running = evaluator.is_running()
        except NotImplementedError:
            pytest.skip("RED phase — is_running stub not implemented yet")
        assert running is False


# ============================================================
# Local helper: in-memory AlertRuleStore stand-in
# ============================================================


class _StubStore:
    """Minimal rule source for evaluator tests (pre-implementation)."""

    def __init__(self, rules: list) -> None:
        self._rules = {r.rule_id: r for r in rules}
        self.marked: list[tuple[str, str]] = []

    def list(self) -> list:
        return list(self._rules.values())

    def mark_fired(self, rule_id: str, at: str) -> None:
        self.marked.append((rule_id, at))
        if rule_id in self._rules:
            object.__setattr__(self._rules[rule_id], "last_fired_at", at)
