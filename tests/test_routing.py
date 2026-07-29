"""Pre-development tests for conditional routing module (v0.4.0).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import routing


# ============================================================
# Interface tests — RoutingRule
# ============================================================


class TestRoutingRuleInterface:
    """Verify RoutingRule class and methods exist."""

    def test_routing_rule_class_exists(self):
        assert hasattr(routing, "RoutingRule")
        assert inspect.isclass(routing.RoutingRule)

    def test_routing_rule_init_signature(self):
        sig = inspect.signature(routing.RoutingRule.__init__)
        params = sig.parameters
        assert "rule_id" in params
        assert "name" in params
        assert "enabled" in params
        assert "priority" in params
        assert "condition" in params
        assert "target_endpoint" in params
        assert "channel" in params
        assert "max_forward_count" in params
        assert "fallback" in params

    def test_routing_rule_to_dict_exists(self):
        assert hasattr(routing.RoutingRule, "to_dict")
        assert callable(routing.RoutingRule.to_dict)

    def test_routing_rule_from_dict_exists(self):
        assert hasattr(routing.RoutingRule, "from_dict")
        assert callable(routing.RoutingRule.from_dict)

    def test_routing_rule_from_dict_is_classmethod(self):
        assert isinstance(
            inspect.getattr_static(routing.RoutingRule, "from_dict"),
            classmethod,
        )


# ============================================================
# Interface tests — RouterEngine
# ============================================================


class TestRouterEngineInterface:
    """Verify RouterEngine class and methods exist."""

    def test_router_engine_class_exists(self):
        assert hasattr(routing, "RouterEngine")
        assert inspect.isclass(routing.RouterEngine)

    def test_router_engine_init_exists(self):
        assert hasattr(routing.RouterEngine, "__init__")
        assert callable(routing.RouterEngine.__init__)

    def test_router_engine_add_rule_exists(self):
        assert hasattr(routing.RouterEngine, "add_rule")
        assert callable(routing.RouterEngine.add_rule)

    def test_router_engine_add_rule_signature(self):
        sig = inspect.signature(routing.RouterEngine.add_rule)
        assert "rule" in sig.parameters

    def test_router_engine_remove_rule_exists(self):
        assert hasattr(routing.RouterEngine, "remove_rule")
        assert callable(routing.RouterEngine.remove_rule)

    def test_router_engine_remove_rule_signature(self):
        sig = inspect.signature(routing.RouterEngine.remove_rule)
        assert "rule_id" in sig.parameters

    def test_router_engine_reorder_exists(self):
        assert hasattr(routing.RouterEngine, "reorder")
        assert callable(routing.RouterEngine.reorder)

    def test_router_engine_reorder_signature(self):
        sig = inspect.signature(routing.RouterEngine.reorder)
        assert "rule_ids" in sig.parameters

    def test_router_engine_evaluate_exists(self):
        assert hasattr(routing.RouterEngine, "evaluate")
        assert callable(routing.RouterEngine.evaluate)

    def test_router_engine_evaluate_signature(self):
        sig = inspect.signature(routing.RouterEngine.evaluate)
        assert "channel" in sig.parameters
        assert "request_data" in sig.parameters

    def test_router_engine_set_stop_on_first_exists(self):
        assert hasattr(routing.RouterEngine, "set_stop_on_first")
        assert callable(routing.RouterEngine.set_stop_on_first)

    def test_router_engine_set_stop_on_first_signature(self):
        sig = inspect.signature(routing.RouterEngine.set_stop_on_first)
        assert "enabled" in sig.parameters


# ============================================================
# Behavioral tests — RoutingRule (GREEN phase)
# ============================================================


class TestRoutingRuleBehavioral:
    """Calling RoutingRule methods works correctly."""

    def test_behavior_routing_rule_init_creates_rule(self):
        rule = routing.RoutingRule(
            rule_id="rule-1",
            name="Stripe charges",
            enabled=True,
            priority=10,
            condition="body.type~^charge",
            target_endpoint="http://localhost:9000/stripe",
            channel="stripe",
        )
        assert rule.rule_id == "rule-1"
        assert rule.name == "Stripe charges"
        assert rule.enabled is True
        assert rule.priority == 10
        assert rule.condition == "body.type~^charge"
        assert rule.target_endpoint == "http://localhost:9000/stripe"
        assert rule.channel == "stripe"
        assert rule.max_forward_count is None
        assert rule.fallback is False
        assert rule.created_at is not None

    def test_behavior_routing_rule_to_dict(self):
        rule = routing.RoutingRule(
            rule_id="rule-1",
            name="Test rule",
            enabled=True,
            priority=10,
            condition="method=POST",
            target_endpoint="http://localhost:9000/hook",
            channel="test",
            max_forward_count=5,
            fallback=False,
            created_at="2026-01-01T00:00:00Z",
        )
        d = rule.to_dict()
        assert d["rule_id"] == "rule-1"
        assert d["name"] == "Test rule"
        assert d["condition"] == "method=POST"
        assert d["max_forward_count"] == 5

    def test_behavior_routing_rule_from_dict(self):
        data = {
            "rule_id": "rule-1",
            "name": "From dict",
            "condition": "method=POST",
            "channel": "test",
            "priority": 50,
        }
        rule = routing.RoutingRule.from_dict(data)
        assert rule.rule_id == "rule-1"
        assert rule.name == "From dict"
        assert rule.priority == 50

    def test_behavior_routing_rule_minimal_fields(self):
        rule = routing.RoutingRule(
            rule_id="rule-2",
            name="catch-all",
        )
        assert rule.rule_id == "rule-2"
        assert rule.name == "catch-all"
        assert rule.enabled is True  # default
        assert rule.priority == 100  # default
        assert rule.condition is None
        assert rule.channel is None

    def test_behavior_routing_rule_with_all_fields(self):
        rule = routing.RoutingRule(
            rule_id="rule-3",
            name="GitHub pushes",
            enabled=True,
            priority=5,
            condition="header.X-GitHub-Event~^push",
            target_endpoint="http://localhost:9000/github",
            channel="github-hooks",
            max_forward_count=10,
            fallback=False,
            created_at="2026-01-01T00:00:00Z",
        )
        assert rule.rule_id == "rule-3"
        assert rule.max_forward_count == 10


class TestRouterEngineBehavioral:
    """Calling RouterEngine methods works correctly."""

    def test_behavior_router_engine_init(self):
        engine = routing.RouterEngine()
        assert engine is not None

    def test_behavior_router_engine_add_rule(self):
        engine = routing.RouterEngine()
        rule = routing.RoutingRule(
            rule_id="rule-1",
            name="test",
            condition="method=POST",
        )
        engine.add_rule(rule)
        # No exception means success

    def test_behavior_router_engine_remove_rule(self):
        engine = routing.RouterEngine()
        rule = routing.RoutingRule(rule_id="rule-1", name="test")
        engine.add_rule(rule)
        engine.remove_rule("rule-1")
        # No exception means success

    def test_behavior_router_engine_reorder(self):
        engine = routing.RouterEngine()
        r1 = routing.RoutingRule(rule_id="r1", name="first")
        r2 = routing.RoutingRule(rule_id="r2", name="second")
        engine.add_rule(r1)
        engine.add_rule(r2)
        engine.reorder(["r2", "r1"])
        # r2 has priority 0, r1 has priority 1
        assert engine._rules["r2"].priority == 0
        assert engine._rules["r1"].priority == 1

    def test_behavior_router_engine_evaluate_matches(self):
        engine = routing.RouterEngine()
        rule = routing.RoutingRule(
            rule_id="rule-1",
            name="POST catcher",
            condition="method=POST",
            channel="stripe",
        )
        engine.add_rule(rule)
        results = engine.evaluate(
            "stripe", {"method": "POST"}
        )
        assert len(results) == 1
        assert results[0][0].rule_id == "rule-1"

    def test_behavior_router_engine_evaluate_with_full_data(self):
        engine = routing.RouterEngine()
        rule = routing.RoutingRule(
            rule_id="rule-github",
            name="GitHub push",
            enabled=True,
            condition="header.X-GitHub-Event~^push",
            channel="github",
        )
        engine.add_rule(rule)
        results = engine.evaluate(
            "github",
            {
                "method": "POST",
                "path": "/webhook",
                "headers": {"X-GitHub-Event": "push"},
                "body": b'{"ref": "refs/heads/main"}',
            },
        )
        assert len(results) == 1
        assert results[0][0].rule_id == "rule-github"

    def test_behavior_router_engine_set_stop_on_first(self):
        engine = routing.RouterEngine()
        engine.set_stop_on_first(True)
        # Default is True, so this is a no-op but should not raise

    def test_behavior_router_engine_stop_on_first_off(self):
        engine = routing.RouterEngine()
        engine.set_stop_on_first(False)
        # Add two rules, both should match
        r1 = routing.RoutingRule(
            rule_id="r1", name="first", condition="method=POST",
            channel="test"
        )
        r2 = routing.RoutingRule(
            rule_id="r2", name="second", condition="method!=GET",
            channel="test"
        )
        engine.add_rule(r1)
        engine.add_rule(r2)
        results = engine.evaluate(
            "test", {"method": "POST"}
        )
        # With stop_on_first=False, both rules match
        assert len(results) == 2
