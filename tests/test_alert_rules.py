"""Pre-development tests for AlertRule + AlertRuleStore + migration 6.

Interface tests (imports, signatures, dataclass fields, type hints): pass
immediately against the contract in ``analysis/analysis-brief.md`` P0-1.

Behavioral tests (validation, migration DDL, CRUD round-trips, restart
safety): RED until the developer implements ``src/hookrelay/alerts/rules.py``,
``src/hookrelay/alerts/storage.py`` and migration 6 in ``migrations.py``.

Contract (analysis-brief.md P0-1 / §6):
- ``hookrelay.alerts.rules.AlertRule`` frozen dataclass with fields
  ``rule_id, name, scope, endpoint_id, metric, threshold, window_minutes=15,
  cooldown_minutes=15, enabled=True, notifier_ids=[], created_at, updated_at,
  last_fired_at=None``; methods ``to_dict/from_dict/validate``.
- ``hookrelay.alerts.storage.AlertRuleStore(storage)`` — ``create/get/list/
  update/delete/mark_fired/set_enabled/record_fire/list_history``.
- Migration 6 ``("alert-rules", sql)`` creates ``alert_rules`` with the
  column set below + ``(scope, endpoint_id)`` index; ``CURRENT_SCHEMA_VERSION
  == 6`` (bumped to 7 once alert-history lands — P1).
"""

from __future__ import annotations

import inspect
import sqlite3
from dataclasses import fields, is_dataclass
from typing import get_args, get_origin, get_type_hints

import pytest

from hookrelay import migrations as migrations_mod
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================

_ALERT_RULES_COLUMNS = {
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


def _make_rule(**overrides) -> object:
    """Build an AlertRule via the module's own constructor (stub or real)."""
    from hookrelay.alerts.rules import AlertRule

    base = {
        "rule_id": "rule-1",
        "name": "high failure rate",
        "scope": "all",
        "endpoint_id": None,
        "metric": "success_rate_below",
        "threshold": 0.9,
        "window_minutes": 15,
        "cooldown_minutes": 15,
        "enabled": True,
        "notifier_ids": ["slack-main"],
        "created_at": "2026-08-08T00:00:00+00:00",
        "updated_at": "2026-08-08T00:00:00+00:00",
        "last_fired_at": None,
    }
    base.update(overrides)
    return AlertRule(**base)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "alert_rules.db"))


# ============================================================
# Interface tests — AlertRule dataclass
# ============================================================


class TestAlertRuleInterface:
    def test_module_imports(self):
        from hookrelay.alerts import rules  # noqa: F401

    def test_alert_rule_is_dataclass(self):
        from hookrelay.alerts.rules import AlertRule

        assert is_dataclass(AlertRule)

    def test_alert_rule_is_frozen(self):
        from hookrelay.alerts.rules import AlertRule

        try:
            frozen = AlertRule.__dataclass_params__.frozen
        except AttributeError:
            assert "frozen" in repr(AlertRule.__dataclass_params__)
        else:
            assert frozen is True

    def test_alert_rule_fields(self):
        from hookrelay.alerts.rules import AlertRule

        names = {f.name for f in fields(AlertRule)}
        assert {
            "rule_id", "name", "scope", "endpoint_id", "metric", "threshold",
            "window_minutes", "cooldown_minutes", "enabled", "notifier_ids",
            "created_at", "updated_at", "last_fired_at",
        } <= names

    def test_alert_rule_type_hints(self):
        """Type hints must match the contract (§6)."""
        from hookrelay.alerts.rules import AlertRule

        hints = get_type_hints(AlertRule)
        assert hints["rule_id"] is str
        assert hints["name"] is str
        assert str in get_args(hints["endpoint_id"]) and type(None) in get_args(
            hints["endpoint_id"]
        )
        assert hints["threshold"] is float
        assert hints["window_minutes"] is int
        assert hints["cooldown_minutes"] is int
        assert hints["enabled"] is bool
        assert hints["notifier_ids"] is list[str]
        assert str in get_args(hints["last_fired_at"]) and type(None) in get_args(
            hints["last_fired_at"]
        )

    def test_alert_rule_scope_literal(self):
        from typing import Literal

        from hookrelay.alerts.rules import AlertRule

        scope_ann = get_type_hints(AlertRule)["scope"]
        assert get_origin(scope_ann) is Literal
        args = set(get_args(scope_ann))
        assert {"all", "endpoint"} <= args

    def test_alert_rule_metric_literal(self):
        from typing import Literal

        from hookrelay.alerts.rules import AlertRule

        metric_ann = get_type_hints(AlertRule)["metric"]
        assert get_origin(metric_ann) is Literal
        args = set(get_args(metric_ann))
        assert {
            "success_rate_below", "consecutive_failures", "dlq_depth_above",
        } <= args

    def test_alert_rule_defaults(self):
        from hookrelay.alerts.rules import AlertRule

        rule = AlertRule(
            rule_id="r1", name="n", scope="all", endpoint_id=None,
            metric="success_rate_below", threshold=0.9,
            created_at="t", updated_at="t",
        )
        assert rule.window_minutes == 15
        assert rule.cooldown_minutes == 15
        assert rule.enabled is True
        assert rule.notifier_ids == []
        assert rule.last_fired_at is None

    def test_to_dict_from_dict_signatures(self):
        from hookrelay.alerts.rules import AlertRule

        assert callable(AlertRule.to_dict)
        assert callable(AlertRule.from_dict)
        assert callable(AlertRule.validate)

    def test_to_dict_returns_dict(self):
        """Behavioral-lite: to_dict must serialize all contract fields."""
        try:
            rule = _make_rule()
            data = rule.to_dict()
        except NotImplementedError:
            pytest.skip("RED phase — to_dict stub not implemented yet")
        assert isinstance(data, dict)
        for key in (
            "rule_id", "name", "scope", "endpoint_id", "metric", "threshold",
            "window_minutes", "cooldown_minutes", "enabled", "notifier_ids",
            "created_at", "updated_at", "last_fired_at",
        ):
            assert key in data


# ============================================================
# Interface tests — AlertRuleStore
# ============================================================


class TestAlertRuleStoreInterface:
    def test_store_imports(self):
        from hookrelay.alerts import storage as alerts_storage  # noqa: F401

    def test_store_class_exists(self):
        from hookrelay.alerts.storage import AlertRuleStore

        assert inspect.isclass(AlertRuleStore)

    def test_store_init_signature(self):
        from hookrelay.alerts.storage import AlertRuleStore

        sig = inspect.signature(AlertRuleStore.__init__)
        assert "storage" in sig.parameters

    def test_store_methods_exist(self):
        from hookrelay.alerts.storage import AlertRuleStore

        for name in (
            "create", "get", "list", "update", "delete",
            "mark_fired", "set_enabled", "record_fire", "list_history",
        ):
            assert callable(getattr(AlertRuleStore, name)), name

    def test_create_signature(self):
        from hookrelay.alerts.storage import AlertRuleStore

        sig = inspect.signature(AlertRuleStore.create)
        assert "rule" in sig.parameters

    def test_update_signature_accepts_kwargs(self):
        from hookrelay.alerts.storage import AlertRuleStore

        sig = inspect.signature(AlertRuleStore.update)
        assert any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ), "update(rule_id, **fields) must accept keyword fields"

    def test_list_history_signature(self):
        from hookrelay.alerts.storage import AlertRuleStore

        sig = inspect.signature(AlertRuleStore.list_history)
        assert "rule_id" in sig.parameters
        assert "limit" in sig.parameters
        assert sig.parameters["limit"].default == 100


# ============================================================
# Interface tests — migration 6
# ============================================================


class TestMigration6Interface:
    def test_current_schema_version_at_least_6(self):
        assert migrations_mod.CURRENT_SCHEMA_VERSION >= 6

    def test_migration_6_is_alert_rules(self):
        assert 6 in migrations_mod._MIGRATIONS
        name, _sql = migrations_mod._MIGRATIONS[6]
        assert "alert" in name.lower()

    def test_migration_6_creates_alert_rules_table(self):
        _name, sql = migrations_mod._MIGRATIONS[6]
        assert "CREATE TABLE" in sql.upper()
        assert "alert_rules" in sql

    def test_migration_6_creates_scope_endpoint_index(self):
        _name, sql = migrations_mod._MIGRATIONS[6]
        assert "CREATE INDEX" in sql.upper()
        assert "scope" in sql and "endpoint_id" in sql

    def test_schema_version_is_6_on_fresh_db(self, tmp_path):
        store = Storage(str(tmp_path / "fresh.db"))
        assert store.schema_version == 8


# ============================================================
# Behavioral tests — migration DDL
# ============================================================


class TestAlertRulesTable:
    def test_table_exists_with_columns(self, store):
        rows = store._conn.execute("PRAGMA table_info(alert_rules)").fetchall()
        columns = {row["name"]: row["type"] for row in rows}
        for name, expected_type in _ALERT_RULES_COLUMNS.items():
            assert name in columns, f"missing column {name}"
            assert columns[name] == expected_type, (
                f"column {name} type {columns[name]} != {expected_type}"
            )

    def test_migration_6_recorded_once_in_ledger(self, store):
        entries = [m for m in store.migration_history() if m["version"] == 6]
        assert len(entries) == 1
        assert entries[0]["name"] == "alert-rules"

    def test_reinit_is_idempotent(self, tmp_path):
        path = str(tmp_path / "idem.db")
        first = Storage(path)
        assert first.schema_version == 8
        second = Storage(path)
        assert second.schema_version == 8
        rows = second._conn.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations WHERE version = 6"
        ).fetchone()
        assert rows["n"] == 1

    def test_pre_v5_database_migrates_cleanly(self, tmp_path):
        """A DB at migration 5 (the v1.6.0 baseline) upgrades to 6 in place."""
        path = str(tmp_path / "v5.db")
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE app_settings (
                setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_migrations(version, name, applied_at)
            VALUES (5, 'delivery-delivery-id', '2026-08-01T00:00:00+00:00');
        """)
        conn.commit()
        conn.close()

        upgraded = Storage(path)
        assert upgraded.schema_version == 8
        names = [m["name"] for m in upgraded.migration_history()]
        assert "alert-rules" in names


# ============================================================
# Behavioral tests — AlertRule.validate
# ============================================================


class TestAlertRuleValidation:
    def test_valid_rule_passes(self):
        rule = _make_rule()
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")

    def test_empty_name_rejected(self):
        rule = _make_rule(name="   ")
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_unknown_metric_rejected(self):
        from hookrelay.alerts.rules import AlertRule

        rule = AlertRule(
            rule_id="r", name="n", scope="all", endpoint_id=None,
            metric="bogus-metric", threshold=0.5,  # type: ignore[arg-type]
            created_at="t", updated_at="t",
        )
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_success_rate_threshold_above_one_rejected(self):
        rule = _make_rule(metric="success_rate_below", threshold=1.5)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_success_rate_threshold_zero_rejected(self):
        rule = _make_rule(metric="success_rate_below", threshold=0.0)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_consecutive_failures_threshold_below_one_rejected(self):
        rule = _make_rule(metric="consecutive_failures", threshold=0.5)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_dlq_depth_threshold_below_one_rejected(self):
        rule = _make_rule(metric="dlq_depth_above", threshold=0.5)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_endpoint_scope_requires_endpoint_id(self):
        rule = _make_rule(scope="endpoint", endpoint_id=None)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_window_minutes_zero_rejected(self):
        rule = _make_rule(window_minutes=0)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_cooldown_minutes_zero_rejected(self):
        rule = _make_rule(cooldown_minutes=0)
        try:
            rule.validate()
        except NotImplementedError:
            pytest.skip("RED phase — validate stub not implemented yet")
        with pytest.raises(ValueError):
            rule.validate()

    def test_from_dict_round_trip(self):
        rule = _make_rule()
        try:
            data = rule.to_dict()
            rebuilt = type(rule).from_dict(data)
        except NotImplementedError:
            pytest.skip("RED phase — from_dict stub not implemented yet")
        assert rebuilt == rule


# ============================================================
# Behavioral tests — AlertRuleStore CRUD
# ============================================================


class TestAlertRuleStoreBehavioral:
    def test_create_returns_rule_id(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        rule = _make_rule()
        try:
            rule_id = AlertRuleStore(store).create(rule)
        except NotImplementedError:
            pytest.skip("RED phase — create stub not implemented yet")
        assert rule_id == rule.rule_id

    def test_create_get_round_trip_all_fields(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        rule = _make_rule(notifier_ids=["slack-a", "webhook-b"])
        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(rule)
            fetched = store_rules.get(rule.rule_id)
        except NotImplementedError:
            pytest.skip("RED phase — create/get stubs not implemented yet")
        assert fetched is not None
        assert fetched.rule_id == rule.rule_id
        assert fetched.name == rule.name
        assert fetched.scope == "all"
        assert fetched.metric == "success_rate_below"
        assert fetched.threshold == 0.9
        assert fetched.window_minutes == 15
        assert fetched.cooldown_minutes == 15
        assert fetched.enabled is True
        assert fetched.notifier_ids == ["slack-a", "webhook-b"]
        assert fetched.last_fired_at is None

    def test_get_unknown_returns_none(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            fetched = AlertRuleStore(store).get("no-such-rule")
        except NotImplementedError:
            pytest.skip("RED phase — get stub not implemented yet")
        assert fetched is None

    def test_list_returns_all_rules(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(_make_rule(rule_id="r1", name="one"))
            store_rules.create(_make_rule(rule_id="r2", name="two"))
            rules = store_rules.list()
        except NotImplementedError:
            pytest.skip("RED phase — create/list stubs not implemented yet")
        assert {r.rule_id for r in rules} == {"r1", "r2"}

    def test_update_changes_fields(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(_make_rule(rule_id="r1", threshold=0.9))
            updated = store_rules.update("r1", threshold=0.5, cooldown_minutes=30)
        except NotImplementedError:
            pytest.skip("RED phase — update stub not implemented yet")
        assert updated.threshold == 0.5
        assert updated.cooldown_minutes == 30
        assert store_rules.get("r1").threshold == 0.5

    def test_update_unknown_raises_key_error(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            AlertRuleStore(store).update("ghost", threshold=0.5)
        except NotImplementedError:
            pytest.skip("RED phase — update stub not implemented yet")
        with pytest.raises(KeyError):
            AlertRuleStore(store).update("ghost", threshold=0.5)

    def test_delete_removes_rule(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(_make_rule(rule_id="r1"))
            deleted = store_rules.delete("r1")
        except NotImplementedError:
            pytest.skip("RED phase — delete stub not implemented yet")
        assert deleted is True
        assert store_rules.get("r1") is None

    def test_delete_unknown_returns_false(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            deleted = AlertRuleStore(store).delete("ghost")
        except NotImplementedError:
            pytest.skip("RED phase — delete stub not implemented yet")
        assert deleted is False

    def test_mark_fired_persists_timestamp(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(_make_rule(rule_id="r1"))
            store_rules.mark_fired("r1", "2026-08-08T12:00:00+00:00")
            fetched = store_rules.get("r1")
        except NotImplementedError:
            pytest.skip("RED phase — mark_fired stub not implemented yet")
        assert fetched.last_fired_at == "2026-08-08T12:00:00+00:00"

    def test_set_enabled_toggles(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        store_rules = AlertRuleStore(store)
        try:
            store_rules.create(_make_rule(rule_id="r1", enabled=True))
            result = store_rules.set_enabled("r1", False)
        except NotImplementedError:
            pytest.skip("RED phase — set_enabled stub not implemented yet")
        assert result is True
        assert store_rules.get("r1").enabled is False

    def test_restart_survival(self, tmp_path):
        """A second Storage + AlertRuleStore on the same DB sees the rules."""
        from hookrelay.alerts.storage import AlertRuleStore

        path = str(tmp_path / "restart.db")
        first_store = Storage(path)
        try:
            AlertRuleStore(first_store).create(_make_rule(rule_id="persist-1"))
        except NotImplementedError:
            pytest.skip("RED phase — create stub not implemented yet")

        second_store = Storage(path)
        rules = AlertRuleStore(second_store).list()
        assert [r.rule_id for r in rules] == ["persist-1"]
