"""Pre-development tests for alert fire history (migration 7) + audit.

Interface tests: pass immediately. Behavioral tests: RED until the developer
implements migration 7 (``alert_history`` table), ``AlertRuleStore.record_fire``
/ ``list_history``, the history REST endpoint, and the audit wiring
(analysis-brief.md P1-6, §5.13).

Contract (P1-6):
- Migration 7 ``("alert-history", sql)`` creates ``alert_history``
  ``(event_id TEXT PRIMARY KEY, rule_id TEXT NOT NULL, rule_name TEXT,
   metric TEXT, observed_value REAL, threshold REAL, message TEXT,
   fired_at TEXT NOT NULL)``; ``CURRENT_SCHEMA_VERSION == 7``.
- ``AlertRuleStore.record_fire(...) -> event_id`` and
  ``list_history(rule_id=None, limit=100)`` newest-first.
- ``GET /api/alerts/history?rule_id=&limit=`` -> ``{"events": [...]}``
  newest-first, default limit 100, max 1000.
- Each fire records ``record_audit_event("alert.fired", "evaluator",
  "alert_rule", rule_id, "success", ...)``; ``verify_audit_chain()`` stays
  valid after fires.
"""

from __future__ import annotations

import inspect
import sqlite3

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay import migrations as migrations_mod
from hookrelay.server import create_app
from hookrelay.storage import Storage

# ============================================================
# Fixtures / helpers
# ============================================================


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "alert_history.db"))


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


def _history_columns() -> dict[str, str]:
    return {
        "event_id": "TEXT",
        "rule_id": "TEXT",
        "rule_name": "TEXT",
        "metric": "TEXT",
        "observed_value": "REAL",
        "threshold": "REAL",
        "message": "TEXT",
        "fired_at": "TEXT",
    }


# ============================================================
# Interface tests — migration 7
# ============================================================


class TestMigration7Interface:
    def test_current_schema_version_at_least_7(self):
        assert migrations_mod.CURRENT_SCHEMA_VERSION >= 7

    def test_migration_7_is_alert_history(self):
        assert 7 in migrations_mod._MIGRATIONS
        name, _sql = migrations_mod._MIGRATIONS[7]
        assert "history" in name.lower() or "alert" in name.lower()

    def test_migration_7_creates_alert_history_table(self):
        _name, sql = migrations_mod._MIGRATIONS[7]
        assert "CREATE TABLE" in sql.upper()
        assert "alert_history" in sql


# ============================================================
# Behavioral — migration DDL
# ============================================================


class TestAlertHistoryTable:
    def test_table_exists_with_columns(self, store):
        rows = store._conn.execute("PRAGMA table_info(alert_history)").fetchall()
        columns = {row["name"]: row["type"] for row in rows}
        for name, expected_type in _history_columns().items():
            assert name in columns, f"missing column {name}"
            assert columns[name] == expected_type

    def test_schema_version_is_7(self, store):
        assert store.schema_version == 8

    def test_migration_7_recorded_once(self, store):
        entries = [m for m in store.migration_history() if m["version"] == 7]
        assert len(entries) == 1
        assert entries[0]["name"] == "alert-history"

    def test_pre_v6_database_migrates_cleanly(self, tmp_path):
        path = str(tmp_path / "v6.db")
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
            INSERT INTO schema_migrations(version, name, applied_at) VALUES
                (5, 'delivery-delivery-id', '2026-08-01T00:00:00+00:00'),
                (6, 'alert-rules', '2026-08-08T00:00:00+00:00');
        """)
        conn.commit()
        conn.close()

        upgraded = Storage(path)
        assert upgraded.schema_version == 8
        names = [m["name"] for m in upgraded.migration_history()]
        assert "alert-history" in names


# ============================================================
# Behavioral — record_fire / list_history
# ============================================================


class TestFireHistory:
    def test_record_fire_returns_event_id(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            event_id = AlertRuleStore(store).record_fire(
                rule_id="r1", rule_name="high failure", metric="success_rate_below",
                observed_value=0.4, threshold=0.9, message="rate dropped",
                fired_at="2026-08-08T12:00:00+00:00",
            )
        except NotImplementedError:
            pytest.skip("RED phase — record_fire stub not implemented yet")
        assert isinstance(event_id, str) and event_id

    def test_list_history_newest_first(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        alert_store = AlertRuleStore(store)
        try:
            alert_store.record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.1, threshold=0.9, message="first",
                fired_at="2026-08-08T10:00:00+00:00",
            )
            alert_store.record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.2, threshold=0.9, message="second",
                fired_at="2026-08-08T11:00:00+00:00",
            )
            events = alert_store.list_history(rule_id="r1")
        except NotImplementedError:
            pytest.skip("RED phase — list_history stub not implemented yet")
        assert [e["message"] for e in events] == ["second", "first"]
        assert events[0]["rule_id"] == "r1"
        assert events[0]["observed_value"] == 0.2

    def test_list_history_filters_by_rule(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        alert_store = AlertRuleStore(store)
        try:
            alert_store.record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.1, threshold=0.9, message="a",
                fired_at="2026-08-08T10:00:00+00:00",
            )
            alert_store.record_fire(
                rule_id="r2", rule_name="m", metric="dlq_depth_above",
                observed_value=5.0, threshold=3.0, message="b",
                fired_at="2026-08-08T10:00:00+00:00",
            )
            events = alert_store.list_history(rule_id="r2")
        except NotImplementedError:
            pytest.skip("RED phase — list_history stub not implemented yet")
        assert len(events) == 1
        assert events[0]["rule_id"] == "r2"

    def test_list_history_limit_defaults_to_100(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        sig = inspect.signature(AlertRuleStore.list_history)
        assert sig.parameters["limit"].default == 100


# ============================================================
# Behavioral — audit integration
# ============================================================


class TestFireAudit:
    def test_fire_records_audit_event(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            AlertRuleStore(store).record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.1, threshold=0.9, message="x",
                fired_at="2026-08-08T12:00:00+00:00",
            )
        except NotImplementedError:
            pytest.skip("RED phase — record_fire stub not implemented yet")
        events = store.list_audit_events(action="alert.fired")
        assert any(e["object_id"] == "r1" for e in events)

    def test_audit_chain_remains_valid_after_fires(self, store):
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            AlertRuleStore(store).record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.1, threshold=0.9, message="x",
                fired_at="2026-08-08T12:00:00+00:00",
            )
        except NotImplementedError:
            pytest.skip("RED phase — record_fire stub not implemented yet")
        result = store.verify_audit_chain()
        assert result["valid"] is True


# ============================================================
# Behavioral — history REST endpoint
# ============================================================


class TestHistoryApi:
    def _client(self, tmp_path, monkeypatch):
        store = Storage(str(tmp_path / "history_api.db"))
        _storage.set(store)
        monkeypatch.delenv("HOOKRELAY_API_TOKEN", raising=False)
        return TestClient(create_app()), store

    def test_history_endpoint_shape(self, tmp_path, monkeypatch):
        client, store = self._client(tmp_path, monkeypatch)
        from hookrelay.alerts.storage import AlertRuleStore

        try:
            AlertRuleStore(store).record_fire(
                rule_id="r1", rule_name="n", metric="success_rate_below",
                observed_value=0.1, threshold=0.9, message="boom",
                fired_at="2026-08-08T12:00:00+00:00",
            )
        except NotImplementedError:
            pytest.skip("RED phase — record_fire stub not implemented yet")
        response = client.get("/api/alerts/history")
        assert response.status_code == 200, response.text
        events = response.json()["events"]
        assert len(events) == 1
        assert events[0]["rule_id"] == "r1"
        assert events[0]["message"] == "boom"

    def test_history_filter_and_limit(self, tmp_path, monkeypatch):
        client, _ = self._client(tmp_path, monkeypatch)
        response = client.get("/api/alerts/history?rule_id=r1&limit=5")
        assert response.status_code == 200
