"""Pre-development tests for filter/routing storage persistence (v0.4.0).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay.storage import Storage


# ============================================================
# Interface tests — FilterSet CRUD
# ============================================================


class TestFilterSetStorageInterface:
    """Verify FilterSet CRUD methods exist on Storage."""

    def test_save_filter_set_exists(self):
        assert hasattr(Storage, "save_filter_set")
        assert callable(Storage.save_filter_set)

    def test_save_filter_set_signature(self):
        sig = inspect.signature(Storage.save_filter_set)
        assert "self" in sig.parameters
        assert "name" in sig.parameters
        assert "channel" in sig.parameters
        assert "filter_expression" in sig.parameters

    def test_load_filter_set_exists(self):
        assert hasattr(Storage, "load_filter_set")
        assert callable(Storage.load_filter_set)

    def test_load_filter_set_signature(self):
        sig = inspect.signature(Storage.load_filter_set)
        assert "filter_set_id" in sig.parameters

    def test_list_filter_sets_exists(self):
        assert hasattr(Storage, "list_filter_sets")
        assert callable(Storage.list_filter_sets)

    def test_list_filter_sets_signature(self):
        sig = inspect.signature(Storage.list_filter_sets)
        assert "channel" in sig.parameters

    def test_delete_filter_set_exists(self):
        assert hasattr(Storage, "delete_filter_set")
        assert callable(Storage.delete_filter_set)

    def test_delete_filter_set_signature(self):
        sig = inspect.signature(Storage.delete_filter_set)
        assert "filter_set_id" in sig.parameters


# ============================================================
# Interface tests — RoutingRule CRUD
# ============================================================


class TestRoutingRuleStorageInterface:
    """Verify RoutingRule CRUD methods exist on Storage."""

    def test_save_routing_rule_exists(self):
        assert hasattr(Storage, "save_routing_rule")
        assert callable(Storage.save_routing_rule)

    def test_save_routing_rule_signature(self):
        sig = inspect.signature(Storage.save_routing_rule)
        assert "name" in sig.parameters
        assert "channel" in sig.parameters
        assert "condition" in sig.parameters
        assert "target_endpoint" in sig.parameters

    def test_list_routing_rules_exists(self):
        assert hasattr(Storage, "list_routing_rules")
        assert callable(Storage.list_routing_rules)

    def test_list_routing_rules_signature(self):
        sig = inspect.signature(Storage.list_routing_rules)
        assert "channel" in sig.parameters

    def test_update_routing_rule_exists(self):
        assert hasattr(Storage, "update_routing_rule")
        assert callable(Storage.update_routing_rule)

    def test_update_routing_rule_signature(self):
        sig = inspect.signature(Storage.update_routing_rule)
        assert "rule_id" in sig.parameters
        assert "updates" in sig.parameters

    def test_delete_routing_rule_exists(self):
        assert hasattr(Storage, "delete_routing_rule")
        assert callable(Storage.delete_routing_rule)

    def test_delete_routing_rule_signature(self):
        sig = inspect.signature(Storage.delete_routing_rule)
        assert "rule_id" in sig.parameters

    def test_reorder_routing_rules_exists(self):
        assert hasattr(Storage, "reorder_routing_rules")
        assert callable(Storage.reorder_routing_rules)

    def test_reorder_routing_rules_signature(self):
        sig = inspect.signature(Storage.reorder_routing_rules)
        assert "ordered_ids" in sig.parameters


# ============================================================
# Interface tests — FilterHistory
# ============================================================


class TestFilterHistoryInterface:
    """Verify FilterHistory methods exist on Storage."""

    def test_log_filter_execution_exists(self):
        assert hasattr(Storage, "log_filter_execution")
        assert callable(Storage.log_filter_execution)

    def test_log_filter_execution_signature(self):
        sig = inspect.signature(Storage.log_filter_execution)
        assert "filter_set_id" in sig.parameters
        assert "request_id" in sig.parameters
        assert "matched" in sig.parameters
        assert "matched_criteria" in sig.parameters

    def test_query_filter_history_exists(self):
        assert hasattr(Storage, "query_filter_history")
        assert callable(Storage.query_filter_history)

    def test_query_filter_history_signature(self):
        sig = inspect.signature(Storage.query_filter_history)
        assert "filter_set_id" in sig.parameters
        assert "limit" in sig.parameters
        assert "offset" in sig.parameters


# ============================================================
# Behavioral tests — FilterSet CRUD (GREEN phase)
# ============================================================


class TestFilterSetStorageBehavioral:
    """Calling FilterSet CRUD methods works correctly."""

    def _make_store(self):
        import tempfile
        store = Storage(tempfile.mktemp(suffix=".db"))
        return store

    def test_behavior_save_filter_set_creates_and_returns_id(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Stripe charges",
            channel="stripe",
            filter_expression="method=POST AND body.type~^charge",
        )
        assert fs_id is not None
        assert isinstance(fs_id, str)
        assert len(fs_id) > 0

    def test_behavior_save_and_load_filter_set(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Stripe charges", channel="stripe",
            filter_expression="method=POST AND body.type~^charge",
        )
        loaded = store.load_filter_set(fs_id)
        assert loaded is not None
        assert loaded["name"] == "Stripe charges"
        assert loaded["channel"] == "stripe"

    def test_behavior_load_filter_set_nonexistent_returns_none(self):
        store = self._make_store()
        result = store.load_filter_set("nonexistent")
        assert result is None

    def test_behavior_list_filter_sets_returns_all(self):
        store = self._make_store()
        store.save_filter_set(name="A", channel="ch1", filter_expression="method=POST")
        store.save_filter_set(name="B", channel="ch2", filter_expression="method=GET")
        all_sets = store.list_filter_sets()
        assert len(all_sets) == 2

    def test_behavior_list_filter_sets_with_channel(self):
        store = self._make_store()
        store.save_filter_set(name="A", channel="stripe", filter_expression="method=POST")
        store.save_filter_set(name="B", channel="github", filter_expression="method=GET")
        stripe_sets = store.list_filter_sets(channel="stripe")
        assert len(stripe_sets) == 1
        assert stripe_sets[0]["name"] == "A"

    def test_behavior_delete_filter_set_returns_true(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Test", channel="test", filter_expression="method=POST"
        )
        assert store.delete_filter_set(fs_id) is True
        assert store.load_filter_set(fs_id) is None


class TestRoutingRuleStorageBehavioral:
    """Calling RoutingRule CRUD methods works correctly."""

    def _make_store(self):
        import tempfile
        return Storage(tempfile.mktemp(suffix=".db"))

    def test_behavior_save_routing_rule_creates_and_returns_id(self):
        store = self._make_store()
        rule_id = store.save_routing_rule(
            name="Stripe to localhost",
            channel="stripe",
            condition="body.type~^charge",
            target_endpoint="http://localhost:9000/hooks",
        )
        assert rule_id is not None
        assert isinstance(rule_id, str)

    def test_behavior_save_routing_rule_minimal(self):
        store = self._make_store()
        rule_id = store.save_routing_rule(
            name="catch-all",
            channel="default",
        )
        assert rule_id is not None

    def test_behavior_list_routing_rules_returns_rules(self):
        store = self._make_store()
        store.save_routing_rule(name="R1", channel="c1")
        store.save_routing_rule(name="R2", channel="c1")
        rules = store.list_routing_rules()
        assert len(rules) >= 2

    def test_behavior_list_routing_rules_with_channel(self):
        store = self._make_store()
        store.save_routing_rule(name="R1", channel="stripe")
        store.save_routing_rule(name="R2", channel="github")
        stripe_rules = store.list_routing_rules(channel="stripe")
        assert len(stripe_rules) == 1
        assert stripe_rules[0]["name"] == "R1"

    def test_behavior_update_routing_rule_updates_fields(self):
        store = self._make_store()
        rule_id = store.save_routing_rule(
            name="Original", channel="test", priority=100
        )
        result = store.update_routing_rule(
            rule_id, {"priority": 50, "enabled": False}
        )
        assert result is True
        rules = store.list_routing_rules(channel="test")
        updated = [r for r in rules if r["rule_id"] == rule_id][0]
        assert updated["priority"] == 50
        assert updated["enabled"] is False

    def test_behavior_delete_routing_rule_returns_true(self):
        store = self._make_store()
        rule_id = store.save_routing_rule(name="Test", channel="test")
        assert store.delete_routing_rule(rule_id) is True

    def test_behavior_reorder_routing_rules_changes_priorities(self):
        store = self._make_store()
        id1 = store.save_routing_rule(name="A", channel="test", priority=10)
        id2 = store.save_routing_rule(name="B", channel="test", priority=20)
        id3 = store.save_routing_rule(name="C", channel="test", priority=30)
        result = store.reorder_routing_rules([id3, id2, id1])
        assert result is True
        rules = store.list_routing_rules(channel="test")
        # After reorder, first element should be id3 (priority 0)
        assert rules[0]["rule_id"] == id3


class TestFilterHistoryBehavioral:
    """Calling FilterHistory methods works correctly."""

    def _make_store(self):
        import tempfile
        return Storage(tempfile.mktemp(suffix=".db"))

    def test_behavior_log_filter_execution_returns_id(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Test", channel="test", filter_expression="method=POST"
        )
        history_id = store.log_filter_execution(
            filter_set_id=fs_id,
            request_id="req-1",
            matched=True,
            matched_criteria='["method=POST"]',
        )
        assert history_id is not None

    def test_behavior_log_filter_execution_no_criteria(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Test", channel="test", filter_expression="method=POST"
        )
        history_id = store.log_filter_execution(
            filter_set_id=fs_id,
            request_id="req-2",
            matched=False,
        )
        assert history_id is not None

    def test_behavior_query_filter_history_returns_results(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Test", channel="test", filter_expression="method=POST"
        )
        store.log_filter_execution(fs_id, "req-1", True, '["method=POST"]')
        results = store.query_filter_history()
        assert len(results) >= 1

    def test_behavior_query_filter_history_with_filter(self):
        store = self._make_store()
        fs_id1 = store.save_filter_set(
            name="FS1", channel="test", filter_expression="method=POST"
        )
        fs_id2 = store.save_filter_set(
            name="FS2", channel="test", filter_expression="method=GET"
        )
        store.log_filter_execution(fs_id1, "req-1", True)
        store.log_filter_execution(fs_id2, "req-2", True)
        results = store.query_filter_history(filter_set_id=fs_id1)
        assert len(results) == 1

    def test_behavior_query_filter_history_with_pagination(self):
        store = self._make_store()
        fs_id = store.save_filter_set(
            name="Test", channel="test", filter_expression="method=POST"
        )
        for i in range(5):
            store.log_filter_execution(fs_id, f"req-{i}", True)
        results = store.query_filter_history(
            filter_set_id=fs_id, limit=3, offset=0
        )
        assert len(results) == 3
