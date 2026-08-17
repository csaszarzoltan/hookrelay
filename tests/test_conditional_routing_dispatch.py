"""Tests for conditional routing integration in the dispatcher.

Verifies that RouterEngine evaluation is wired into deliver_captured_request()
and that routing rules with target_destination_ids correctly filter which
destinations receive the delivery.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from hookrelay import _storage
from hookrelay.storage import Storage


@pytest.fixture(autouse=True)
def restore_global_storage():
    previous = _storage.get()
    yield
    _storage.set(previous)


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "conditional_routing.db"))


@pytest.fixture
def dispatcher_module():
    import hookrelay.delivery.dispatcher as disp
    return disp


@pytest.fixture
def allow_destination_ssrf(monkeypatch):
    def _allow(url, allow_private=False, allowed_protocols=None):
        return True, None
    import hookrelay.routing.destination_store as dst_mod
    monkeypatch.setattr(dst_mod, "validate_target_url", _allow, raising=False)


class _FakeTransport:
    """Records outgoing calls; simulates success."""
    def __init__(self, *, status_code: int = 200):
        self.status_code = status_code
        self.calls: list[dict[str, Any]] = []

    def request(self, method, url, headers, data, timeout):
        self.calls.append({"method": method, "url": url, "data": data})
        class _Resp:
            status_code = self.status_code
            text = '{"ok": true}'
        return _Resp()


def _make_bin(store: Storage, bin_id: str) -> None:
    store.create_bin(bin_id, f"bin {bin_id}", "2026-08-10T00:00:00+00:00")


def _make_dest(store: Storage, bin_id: str, url: str) -> dict:
    from hookrelay.routing.destination_store import DestinationStore as DS
    return DS(store).create(bin_id, url)


def _make_rule(store: Storage, bin_id: str, **kwargs) -> str:
    defaults = {
        "name": "test-rule",
        "channel": bin_id,
        "enabled": True,
        "priority": 100,
    }
    defaults.update(kwargs)
    return store.save_routing_rule(**defaults)


def _store_request(store: Storage, bin_id: str, body: dict) -> str:
    return store.store_request({
        "request_id": f"req-{bin_id}",
        "channel": bin_id,
        "method": "POST",
        "path": "/",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body).encode(),
        "query_params": {},
        "source_ip": "203.0.113.1",
        "received_at": "2026-08-10T00:00:00+00:00",
    })


class TestConditionalRoutingDispatch:
    def test_no_rules_broadcasts_to_all(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """No routing rules → broadcast to all destinations (backward compat)."""
        bin_id = "bin-no-rules"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        request_id = _store_request(store, bin_id, {"event": "test"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] in sent_urls

    def test_matching_rule_selects_destinations(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Rule with condition + target_destination_ids routes to specific destinations."""
        bin_id = "bin-match"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        _make_rule(
            store, bin_id,
            name="select-a",
            condition='body.event~invoice.paid',
            target_destination_ids=[dest_a["destination_id"]],
            priority=0,
        )
        request_id = _store_request(store, bin_id, {"event": "invoice.paid"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] not in sent_urls

    def test_no_matching_rule_fallback_broadcast(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """No rule matches → fallback broadcast to all destinations."""
        bin_id = "bin-fallback"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        _make_rule(
            store, bin_id,
            name="select-a",
            condition='body.event~invoice.paid',
            target_destination_ids=[dest_a["destination_id"]],
            priority=0,
        )
        # Different event — won't match the rule
        request_id = _store_request(store, bin_id, {"event": "user.created"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] in sent_urls

    def test_disabled_rule_ignored(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Disabled rules don't affect routing → broadcast."""
        bin_id = "bin-disabled"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        _make_rule(
            store, bin_id,
            name="disabled-rule",
            condition='body.event~invoice.paid',
            target_destination_ids=[dest_a["destination_id"]],
            enabled=False,
            priority=0,
        )
        request_id = _store_request(store, bin_id, {"event": "invoice.paid"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        # Both destinations should receive the delivery
        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls

    def test_multiple_rules_first_match(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """First-match-wins: the highest-priority matching rule is used."""
        bin_id = "bin-first"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        # Lower priority number = evaluated first
        _make_rule(
            store, bin_id,
            name="first",
            condition='body.event~invoice.paid',
            target_destination_ids=[dest_a["destination_id"]],
            priority=0,
        )
        _make_rule(
            store, bin_id,
            name="second",
            condition='body.event~invoice.paid',
            target_destination_ids=[dest_b["destination_id"]],
            priority=10,
        )
        request_id = _store_request(store, bin_id, {"event": "invoice.paid"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] not in sent_urls

    def test_rule_with_condition_and_destination_ids(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Rule with condition + target_destination_ids: only matched destinations get delivery."""
        bin_id = "bin-cond-dest"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        dest_c = _make_dest(store, bin_id, "https://c.example.com/hook")
        _make_rule(
            store, bin_id,
            name="route-to-ab",
            condition='body.event~deploy',
            target_destination_ids=[
                dest_a["destination_id"],
                dest_b["destination_id"],
            ],
            priority=0,
        )
        request_id = _store_request(store, bin_id, {"event": "deploy"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] in sent_urls
        assert dest_c["url"] not in sent_urls

    def test_rule_with_no_condition_matches_all(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Rule with no condition but with target_destination_ids → routes to specified destinations."""
        bin_id = "bin-no-cond"
        _make_bin(store, bin_id)
        dest_a = _make_dest(store, bin_id, "https://a.example.com/hook")
        dest_b = _make_dest(store, bin_id, "https://b.example.com/hook")
        _make_rule(
            store, bin_id,
            name="all-match",
            condition=None,
            target_destination_ids=[dest_a["destination_id"]],
            priority=0,
        )
        request_id = _store_request(store, bin_id, {"event": "anything"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            deliver_captured_request(bin_id, request_id, store)

        sent_urls = {c["url"] for c in transport.calls}
        assert dest_a["url"] in sent_urls
        assert dest_b["url"] not in sent_urls

    def test_backward_compat_no_routing_rules(
        self, store, dispatcher_module, allow_destination_ssrf
    ):
        """Existing bins without routing rules still broadcast to all destinations."""
        bin_id = "bin-compat"
        _make_bin(store, bin_id)
        dest = _make_dest(store, bin_id, "https://compat.example.com/hook")
        request_id = _store_request(store, bin_id, {"data": "test"})

        transport = _FakeTransport()
        with mock.patch.object(dispatcher_module.requests, "request", autospec=True) as fake:
            fake.side_effect = transport.request
            from hookrelay.delivery.dispatcher import deliver_captured_request
            results = deliver_captured_request(bin_id, request_id, store)

        assert len(results) == 1
        assert results[0]["destination_id"] == dest["destination_id"]
        assert transport.calls[0]["url"] == dest["url"]
