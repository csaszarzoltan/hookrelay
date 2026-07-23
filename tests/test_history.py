"""Pre-development tests for history browser module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

from hookrelay import history

# ============================================================
# Interface tests — function existence and signatures
# ============================================================

class TestHistoryInterface:
    """Verify history module functions exist with correct signatures."""

    def test_get_history_exists(self):
        assert hasattr(history, "get_history")
        assert callable(history.get_history)

    def test_get_history_signature(self):
        sig = inspect.signature(history.get_history)
        params = sig.parameters
        assert "channel" in params
        assert params["channel"].default is None
        assert "limit" in params
        assert params["limit"].default == 20
        assert "offset" in params
        assert params["offset"].default == 0
        assert "method" in params
        assert params["method"].default is None
        assert "path" in params
        assert params["path"].default is None
        assert "source" in params
        assert params["source"].default is None

    def test_get_request_detail_exists(self):
        assert hasattr(history, "get_request_detail")
        assert callable(history.get_request_detail)

    def test_get_request_detail_signature(self):
        sig = inspect.signature(history.get_request_detail)
        assert "request_id" in sig.parameters

    def test_search_history_exists(self):
        assert hasattr(history, "search_history")
        assert callable(history.search_history)

    def test_search_history_signature(self):
        sig = inspect.signature(history.search_history)
        params = sig.parameters
        assert "query" in params
        assert "channel" in params
        assert params["channel"].default is None
        assert "limit" in params
        assert params["limit"].default == 20

    def test_export_history_exists(self):
        assert hasattr(history, "export_history")
        assert callable(history.export_history)

    def test_export_history_signature(self):
        sig = inspect.signature(history.export_history)
        params = sig.parameters
        assert "channel" in params
        assert params["channel"].default is None
        assert "format" in params
        assert params["format"].default == "json"
        assert "output" in params
        assert params["output"].default is None


# ============================================================
# Behavioral tests — real behavior (returns data or empty)
# ============================================================

class TestHistoryBehavioral:
    """Calling history functions returns expected results."""

    def test_behavior_get_history_no_args_returns_list(self):
        """get_history() without a storage configured returns []."""
        result = history.get_history()
        assert isinstance(result, list)

    def test_behavior_get_history_with_channel_returns_list(self):
        result = history.get_history(channel="test")
        assert isinstance(result, list)

    def test_behavior_get_history_paginated_returns_list(self):
        result = history.get_history(limit=10, offset=5)
        assert isinstance(result, list)

    def test_behavior_get_history_filtered_returns_list(self):
        result = history.get_history(
            method="POST", path="/stripe", source="203.0.113.1"
        )
        assert isinstance(result, list)

    def test_behavior_get_request_detail_returns_none(self):
        """get_request_detail with no storage returns None."""
        result = history.get_request_detail(request_id="req-123")
        assert result is None

    def test_behavior_search_history_returns_list(self):
        result = history.search_history(query="stripe", channel="test")
        assert isinstance(result, list)

    def test_behavior_export_history_returns_string(self):
        result = history.export_history(channel="test", format="json")
        assert isinstance(result, str)
