"""Pre-development tests for conditional forwarding / filtering module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

from hookrelay import filters

# ============================================================
# Interface tests — RequestFilter class
# ============================================================

class TestRequestFilterInterface:
    """Verify RequestFilter class and methods exist."""

    def test_request_filter_class_exists(self):
        assert hasattr(filters, "RequestFilter")
        assert inspect.isclass(filters.RequestFilter)

    def test_by_method_exists(self):
        assert hasattr(filters.RequestFilter, "by_method")
        assert callable(filters.RequestFilter.by_method)

    def test_by_method_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_method)
        assert "method" in sig.parameters

    def test_by_path_exists(self):
        assert hasattr(filters.RequestFilter, "by_path")
        assert callable(filters.RequestFilter.by_path)

    def test_by_path_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_path)
        assert "pattern" in sig.parameters

    def test_by_source_exists(self):
        assert hasattr(filters.RequestFilter, "by_source")
        assert callable(filters.RequestFilter.by_source)

    def test_by_source_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_source)
        assert "source_ip" in sig.parameters

    def test_by_status_code_exists(self):
        assert hasattr(filters.RequestFilter, "by_status_code")
        assert callable(filters.RequestFilter.by_status_code)

    def test_by_status_code_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_status_code)
        assert "code" in sig.parameters

    def test_by_header_exists(self):
        assert hasattr(filters.RequestFilter, "by_header")
        assert callable(filters.RequestFilter.by_header)

    def test_by_header_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_header)
        assert "name" in sig.parameters
        assert "value" in sig.parameters

    def test_apply_exists(self):
        assert hasattr(filters.RequestFilter, "apply")
        assert callable(filters.RequestFilter.apply)

    def test_apply_signature(self):
        sig = inspect.signature(filters.RequestFilter.apply)
        assert "requests" in sig.parameters

    def test_reset_exists(self):
        assert hasattr(filters.RequestFilter, "reset")
        assert callable(filters.RequestFilter.reset)


# ============================================================
# Interface tests — build_filter convenience function
# ============================================================

class TestBuildFilterInterface:
    """Verify build_filter convenience function."""

    def test_build_filter_exists(self):
        assert hasattr(filters, "build_filter")
        assert callable(filters.build_filter)

    def test_build_filter_signature(self):
        sig = inspect.signature(filters.build_filter)
        params = sig.parameters
        assert "method" in params
        assert params["method"].default is None
        assert "path" in params
        assert params["path"].default is None
        assert "source" in params
        assert params["source"].default is None
        assert "status_code" in params
        assert params["status_code"].default is None


# ============================================================
# Behavioral tests — RequestFilter real behavior
# ============================================================

class TestRequestFilterBehavioral:
    """Calling RequestFilter methods works correctly."""

    def test_behavior_init_creates_filter(self):
        f = filters.RequestFilter()
        assert f is not None

    def test_behavior_by_method_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_method("POST")
        assert result is f  # chaining support

    def test_behavior_by_path_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_path("/stripe")
        assert result is f

    def test_behavior_by_source_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_source("10.0.0.1")
        assert result is f

    def test_behavior_by_status_code_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_status_code(200)
        assert result is f

    def test_behavior_by_header_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_header(
            name="X-Hub-Signature", value="sha256=abc"
        )
        assert result is f

    def test_behavior_apply_returns_matching_requests(self):
        f = filters.RequestFilter()
        f.by_method("POST")
        requests = [
            {"method": "POST", "path": "/hook", "id": "1"},
            {"method": "GET", "path": "/health", "id": "2"},
        ]
        result = f.apply(requests)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_behavior_reset_clears_filters(self):
        f = filters.RequestFilter()
        f.by_method("POST")
        f.reset()
        requests = [
            {"method": "POST", "path": "/hook"},
            {"method": "GET", "path": "/health"},
        ]
        result = f.apply(requests)
        assert len(result) == 2  # filters cleared

    def test_behavior_chained_filter_filters_correctly(self):
        f = filters.RequestFilter()
        f.by_method("POST").by_path("/hooks")
        requests = [
            {"method": "POST", "path": "/hooks", "source_ip": "10.0.0.1"},
            {"method": "POST", "path": "/other"},
            {"method": "GET", "path": "/hooks"},
        ]
        result = f.apply(requests)
        assert len(result) == 1
        assert result[0]["path"] == "/hooks"

    def test_behavior_build_filter_creates_preconfigured_filter(self):
        f = filters.build_filter(method="POST", source="203.0.113.1")
        assert isinstance(f, filters.RequestFilter)
        requests = [
            {"method": "POST", "path": "/hook", "source_ip": "203.0.113.1"},
            {"method": "POST", "path": "/hook", "source_ip": "10.0.0.1"},
        ]
        result = f.apply(requests)
        assert len(result) == 1
