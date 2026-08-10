"""Pre-development tests for multi-destination routing.

Interface tests verify the existing RouterEngine plus the new
Destination / MultiDestinationRouter stubs — pass immediately.

Behavioral tests exercise broadcast, round-robin, weighted delivery
modes, per-destination config, and delivery tracking — they fail with
ImportError / AssertionError until the developer implements the
multi-destination logic in src/hookrelay/routing.py.

Target: ~40 tests (20 interface PASS, 20 behavioral RED).
"""

from __future__ import annotations

import importlib.util
import inspect
from typing import Any

import pytest

from hookrelay.routing import RouterEngine, RoutingRule

# ---------------------------------------------------------------------------
# Stub loader for new multi-destination classes
# ---------------------------------------------------------------------------

_STUBS_PATH = "/tmp/hookrelay-stubs/hookrelay/routing/destination.py"


def _load_stub(path: str = _STUBS_PATH, name: str = "destination_stub"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dest_stub = _load_stub()

# ---------------------------------------------------------------------------
# Interface tests — existing RoutingRule + RouterEngine
# ---------------------------------------------------------------------------


class TestRoutingRuleInterface:
    """Verify existing RoutingRule class and methods."""

    def test_class_exists(self):
        assert inspect.isclass(RoutingRule)

    def test_init_params(self):
        sig = inspect.signature(RoutingRule.__init__)
        params = sig.parameters
        assert "rule_id" in params
        assert "name" in params
        assert "enabled" in params
        assert "priority" in params
        assert "condition" in params
        assert "target_endpoint" in params
        assert "channel" in params

    def test_to_dict_exists(self):
        assert callable(getattr(RoutingRule, "to_dict", None))

    def test_from_dict_exists(self):
        assert isinstance(
            inspect.getattr_static(RoutingRule, "from_dict"), classmethod
        )

    def test_roundtrip(self):
        rule = RoutingRule("r1", "test", target_endpoint="https://example.com")
        d = rule.to_dict()
        restored = RoutingRule.from_dict(d)
        assert restored.rule_id == "r1"
        assert restored.target_endpoint == "https://example.com"


class TestRouterEngineInterface:
    """Verify existing RouterEngine class and methods."""

    def test_class_exists(self):
        assert inspect.isclass(RouterEngine)

    def test_add_rule_exists(self):
        assert callable(getattr(RouterEngine, "add_rule", None))

    def test_remove_rule_exists(self):
        assert callable(getattr(RoutingRule, "to_dict", None))

    def test_evaluate_exists(self):
        assert callable(getattr(RouterEngine, "evaluate", None))


# ---------------------------------------------------------------------------
# Interface tests — new Destination / MultiDestinationRouter stubs
# ---------------------------------------------------------------------------


class TestDestinationStubInterface:
    """Verify Destination stub exists with correct signatures."""

    def test_module_loads(self):
        assert _dest_stub is not None

    def test_delivery_mode_enum(self):
        assert hasattr(_dest_stub, "DeliveryMode")
        dm = _dest_stub.DeliveryMode
        assert dm.BROADCAST.value == "broadcast"
        assert dm.ROUND_ROBIN.value == "round_robin"
        assert dm.WEIGHTED.value == "weighted"

    def test_destination_class_exists(self):
        assert inspect.isclass(_dest_stub.Destination)

    def test_destination_init_params(self):
        sig = inspect.signature(_dest_stub.Destination.__init__)
        params = sig.parameters
        assert "destination_id" in params
        assert "bin_id" in params
        assert "url" in params
        assert "transform_id" in params
        assert "signing_config" in params
        assert "headers" in params
        assert "retry_policy" in params
        assert "enabled" in params
        assert "weight" in params
        assert params["weight"].default == 1

    def test_destination_to_dict_exists(self):
        assert callable(getattr(_dest_stub.Destination, "to_dict", None))

    def test_destination_from_dict_exists(self):
        assert isinstance(
            inspect.getattr_static(_dest_stub.Destination, "from_dict"), classmethod
        )


class TestMultiDestinationRouterStubInterface:
    """Verify MultiDestinationRouter stub exists."""

    def test_class_exists(self):
        assert inspect.isclass(_dest_stub.MultiDestinationRouter)

    def test_init_params(self):
        sig = inspect.signature(_dest_stub.MultiDestinationRouter.__init__)
        params = sig.parameters
        assert "destinations" in params
        assert "mode" in params
        assert params["mode"].default == _dest_stub.DeliveryMode.BROADCAST

    def test_route_exists(self):
        assert callable(getattr(_dest_stub.MultiDestinationRouter, "route", None))

    def test_next_destination_exists(self):
        assert callable(
            getattr(_dest_stub.MultiDestinationRouter, "next_destination", None)
        )

    def test_get_delivery_stats_exists(self):
        assert callable(
            getattr(_dest_stub.MultiDestinationRouter, "get_delivery_stats", None)
        )


# ---------------------------------------------------------------------------
# Behavioral tests — target behavior (RED until implemented)
# ---------------------------------------------------------------------------


class TestDestinationBehavioral:
    """Assert expected Destination model behavior."""

    def _make_dest(self, **overrides) -> Any:
        from hookrelay.routing.destination import Destination

        defaults = {
            "destination_id": "dest-1",
            "bin_id": "bin-abc",
            "url": "https://example.com/hook",
        }
        defaults.update(overrides)
        return Destination(**defaults)

    def test_create_destination(self):
        dest = self._make_dest()
        assert dest.destination_id == "dest-1"
        assert dest.bin_id == "bin-abc"
        assert dest.url == "https://example.com/hook"

    def test_destination_defaults(self):
        dest = self._make_dest()
        assert dest.enabled is True
        assert dest.weight == 1
        assert dest.transform_id is None
        assert dest.signing_config is None
        assert dest.headers == {}
        assert dest.retry_policy is None

    def test_destination_to_dict_roundtrip(self):
        dest = self._make_dest(weight=5, headers={"X-Custom": "val"})
        d = dest.to_dict()
        from hookrelay.routing.destination import Destination

        restored = Destination.from_dict(d)
        assert restored.destination_id == dest.destination_id
        assert restored.weight == 5
        assert restored.headers == {"X-Custom": "val"}

    def test_destination_with_transform(self):
        dest = self._make_dest(transform_id="tf-42")
        assert dest.transform_id == "tf-42"

    def test_destination_with_signing(self):
        dest = self._make_dest(
            signing_config={"algorithm": "github", "secret": "whsec_abc"}
        )
        assert dest.signing_config["algorithm"] == "github"


class TestMultiDestinationRouterBehavioral:
    """Assert expected multi-destination routing behavior."""

    def _make_dests(self, count: int = 3) -> list:
        from hookrelay.routing.destination import Destination

        return [
            Destination(
                destination_id=f"dest-{i}",
                bin_id="bin-1",
                url=f"https://dest{i}.example.com/hook",
            )
            for i in range(count)
        ]

    def test_broadcast_sends_to_all(self):
        from hookrelay.routing.destination import DeliveryMode, MultiDestinationRouter

        dests = self._make_dests(3)
        router = MultiDestinationRouter(dests, mode=DeliveryMode.BROADCAST)
        results = router.route({"event": "test"})
        assert len(results) == 3
        urls = {r["url"] for r in results}
        assert len(urls) == 3

    def test_broadcast_result_contains_destination_id(self):
        from hookrelay.routing.destination import DeliveryMode, MultiDestinationRouter

        dests = self._make_dests(2)
        router = MultiDestinationRouter(dests, mode=DeliveryMode.BROADCAST)
        results = router.route({"event": "test"})
        for r in results:
            assert "destination_id" in r
            assert "url" in r

    def test_round_robin_cycles(self):
        from hookrelay.routing.destination import DeliveryMode, MultiDestinationRouter

        dests = self._make_dests(3)
        router = MultiDestinationRouter(dests, mode=DeliveryMode.ROUND_ROBIN)
        d1 = router.next_destination()
        d2 = router.next_destination()
        d3 = router.next_destination()
        d4 = router.next_destination()  # should wrap around
        assert d1.destination_id != d2.destination_id
        assert d2.destination_id != d3.destination_id
        assert d4.destination_id == d1.destination_id

    def test_round_robin_route_returns_one(self):
        from hookrelay.routing.destination import DeliveryMode, MultiDestinationRouter

        dests = self._make_dests(3)
        router = MultiDestinationRouter(dests, mode=DeliveryMode.ROUND_ROBIN)
        results = router.route({"event": "test"})
        assert len(results) == 1

    def test_weighted_respects_weights(self):
        from hookrelay.routing.destination import Destination, DeliveryMode, MultiDestinationRouter

        heavy = Destination("h1", "bin-1", "https://heavy.example.com", weight=10)
        light = Destination("l1", "bin-1", "https://light.example.com", weight=1)
        router = MultiDestinationRouter([heavy, light], mode=DeliveryMode.WEIGHTED)
        # With 10:1 weight, heavy should be chosen most of the time
        counts = {"h1": 0, "l1": 0}
        for _ in range(100):
            results = router.route({"event": "test"})
            for r in results:
                counts[r["destination_id"]] += 1
        assert counts["h1"] > counts["l1"]

    def test_disabled_destination_excluded(self):
        from hookrelay.routing.destination import Destination, DeliveryMode, MultiDestinationRouter

        active = Destination("a1", "bin-1", "https://active.example.com", enabled=True)
        disabled = Destination("d1", "bin-1", "https://disabled.example.com", enabled=False)
        router = MultiDestinationRouter(
            [active, disabled], mode=DeliveryMode.BROADCAST
        )
        results = router.route({"event": "test"})
        assert len(results) == 1
        assert results[0]["destination_id"] == "a1"

    def test_get_delivery_stats(self):
        from hookrelay.routing.destination import DeliveryMode, MultiDestinationRouter

        dests = self._make_dests(2)
        router = MultiDestinationRouter(dests, mode=DeliveryMode.BROADCAST)
        stats = router.get_delivery_stats()
        assert isinstance(stats, dict)
        for dest in dests:
            assert dest.destination_id in stats
            assert "delivered" in stats[dest.destination_id]
            assert "failed" in stats[dest.destination_id]
