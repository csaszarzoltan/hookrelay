"""Pre-development tests for conditional forwarding / filtering module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

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

# ============================================================
# v0.4.0: Advanced filtering — interface tests
# ============================================================


class TestRequestFilterAdvancedInterface:
    """Verify new v0.4.0 methods exist on RequestFilter."""

    def test_by_body_exists(self):
        assert hasattr(filters.RequestFilter, "by_body")
        assert callable(filters.RequestFilter.by_body)

    def test_by_body_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_body)
        assert "pattern" in sig.parameters

    def test_by_header_regex_exists(self):
        assert hasattr(filters.RequestFilter, "by_header_regex")
        assert callable(filters.RequestFilter.by_header_regex)

    def test_by_header_regex_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_header_regex)
        assert "name" in sig.parameters
        assert "pattern" in sig.parameters

    def test_by_json_field_exists(self):
        assert hasattr(filters.RequestFilter, "by_json_field")
        assert callable(filters.RequestFilter.by_json_field)

    def test_by_json_field_signature(self):
        sig = inspect.signature(filters.RequestFilter.by_json_field)
        assert "path" in sig.parameters
        assert "pattern" in sig.parameters


class TestFilterPresetInterface:
    """Verify FilterPreset class and methods exist."""

    def test_filter_preset_class_exists(self):
        assert hasattr(filters, "FilterPreset")
        assert inspect.isclass(filters.FilterPreset)

    def test_filter_preset_apply_exists(self):
        assert hasattr(filters.FilterPreset, "apply")
        assert callable(filters.FilterPreset.apply)

    def test_filter_preset_apply_signature(self):
        sig = inspect.signature(filters.FilterPreset.apply)
        assert "name" in sig.parameters
        assert "requests" in sig.parameters

    def test_filter_preset_list_exists(self):
        assert hasattr(filters.FilterPreset, "list")
        assert callable(filters.FilterPreset.list)


class TestFilterChainInterface:
    """Verify FilterChain class and methods exist."""

    def test_filter_chain_class_exists(self):
        assert hasattr(filters, "FilterChain")
        assert inspect.isclass(filters.FilterChain)

    def test_filter_chain_all_exists(self):
        assert hasattr(filters.FilterChain, "all")
        assert callable(filters.FilterChain.all)

    def test_filter_chain_any_exists(self):
        assert hasattr(filters.FilterChain, "any")
        assert callable(filters.FilterChain.any)

    def test_filter_chain_not_exists(self):
        assert hasattr(filters.FilterChain, "not_")
        assert callable(filters.FilterChain.not_)


class TestFilterExpressionParserInterface:
    """Verify FilterExpressionParser class and methods exist."""

    def test_expression_parser_class_exists(self):
        assert hasattr(filters, "FilterExpressionParser")
        assert inspect.isclass(filters.FilterExpressionParser)

    def test_expression_parser_parse_exists(self):
        assert hasattr(filters.FilterExpressionParser, "parse")
        assert callable(filters.FilterExpressionParser.parse)

    def test_expression_parser_parse_signature(self):
        sig = inspect.signature(filters.FilterExpressionParser.parse)
        assert "expression" in sig.parameters


# ============================================================
# v0.4.0: Advanced filtering — behavioral tests (GREEN phase)
# ============================================================


class TestRequestFilterAdvancedBehavioral:
    """Calling new v0.4.0 methods works correctly."""

    def test_behavior_by_body_matches_text_body(self):
        f = filters.RequestFilter().by_body(r"test.*pattern")
        requests = [
            {"body": b"this is a test pattern here"},
            {"body": b"no match here"},
        ]
        result = f.apply(requests)
        assert len(result) == 1

    def test_behavior_by_body_returns_self(self):
        f = filters.RequestFilter()
        result = f.by_body("pattern")
        assert result is f  # chaining support

    def test_behavior_by_body_with_empty_pattern(self):
        f = filters.RequestFilter().by_body("")
        requests = [
            {"body": b"anything"},
            {"body": b""},
        ]
        result = f.apply(requests)
        # Empty pattern matches everything
        assert len(result) == 2

    def test_behavior_by_body_with_binary_body(self):
        f = filters.RequestFilter().by_body(r".*")
        requests = [
            {"body": b"hello"},
            # Non-decodable bytes
            {"body": b"\xff\xfe\x00\x01"},
        ]
        result = f.apply(requests)
        # Binary body is skipped (not matched), only first matches
        assert len(result) == 1

    def test_behavior_by_header_regex_matches(self):
        f = filters.RequestFilter().by_header_regex("X-Custom", r"val.*")
        requests = [
            {"headers": {"X-Custom": "value123"}},
            {"headers": {"X-Custom": "other"}},
        ]
        result = f.apply(requests)
        assert len(result) == 1

    def test_behavior_by_header_regex_with_empty_name(self):
        f = filters.RequestFilter().by_header_regex("", r".*")
        requests = [{"headers": {"X-Custom": "value"}}]
        result = f.apply(requests)
        # Empty header name — won't match any header
        assert len(result) == 0

    def test_behavior_by_header_regex_with_empty_pattern(self):
        f = filters.RequestFilter().by_header_regex("X-Custom", "")
        requests = [{"headers": {"X-Custom": "value"}}]
        result = f.apply(requests)
        # Empty pattern matches everything
        assert len(result) == 1

    def test_behavior_by_header_regex_with_invalid_regex(self):
        f = filters.RequestFilter().by_header_regex("X-Custom", r"[invalid")
        requests = [{"headers": {"X-Custom": "value"}}]
        result = f.apply(requests)
        # Invalid regex — no match
        assert len(result) == 0

    def test_behavior_by_json_field_matches(self):
        f = filters.RequestFilter().by_json_field("data.event", r"^evt_")
        requests = [
            {"body": b'{"data": {"event": "evt_123"}}'},
            {"body": b'{"data": {"event": "other"}}'},
        ]
        result = f.apply(requests)
        assert len(result) == 1

    def test_behavior_by_json_field_empty_path(self):
        f = filters.RequestFilter().by_json_field("", r".*")
        requests = [{"body": b'{"key": "value"}'}]
        result = f.apply(requests)
        # Empty path — no extraction
        assert len(result) == 0

    def test_behavior_by_json_field_empty_pattern(self):
        f = filters.RequestFilter().by_json_field("data.event", "")
        requests = [{"body": b'{"data": {"event": "evt_123"}}'}]
        result = f.apply(requests)
        # Empty pattern matches everything
        assert len(result) == 1

    def test_behavior_by_json_field_nested_path(self):
        f = filters.RequestFilter().by_json_field("data.object.id", r"^evt_")
        requests = [
            {
                "body": b'{"data": {"object": {"id": "evt_123"}}}'
            },
            {"body": b'{"data": {"object": {"id": "other"}}}'},
        ]
        result = f.apply(requests)
        assert len(result) == 1

    def test_behavior_by_json_field_missing_field(self):
        f = filters.RequestFilter().by_json_field("nonexistent.field", r".*")
        requests = [{"body": b'{"data": {"event": "test"}}'}]
        result = f.apply(requests)
        assert len(result) == 0


class TestFilterPresetBehavioral:
    """Calling FilterPreset methods works correctly."""

    def test_behavior_filter_preset_apply_stripe(self):
        reqs = [{"body": b'{"type": "charge.completed"}'}]
        result = filters.FilterPreset.apply("stripe", reqs)
        assert len(result) == 1

    def test_behavior_filter_preset_apply_with_requests(self):
        reqs = [
            {"method": "POST", "body": b'{"type": "charge.completed"}'},
            {"method": "GET", "body": b'{"type": "ping"}'},
        ]
        result = filters.FilterPreset.apply("stripe", reqs)
        assert len(result) == 1  # only charge/..., not ping

    def test_behavior_filter_preset_list_returns_names(self):
        names = filters.FilterPreset.list()
        assert isinstance(names, list)
        assert "stripe" in names
        assert "github" in names
        assert "post" in names
        assert "get" in names

    def test_behavior_filter_preset_apply_http_methods(self):
        reqs = [
            {"method": "POST", "path": "/hook"},
            {"method": "GET", "path": "/health"},
        ]
        result = filters.FilterPreset.apply("post", reqs)
        assert len(result) == 1
        assert result[0]["method"] == "POST"

    def test_behavior_filter_preset_apply_unknown_raises(self):
        import pytest
        with pytest.raises(ValueError):
            filters.FilterPreset.apply("nonexistent", [])


class TestFilterChainBehavioral:
    """Calling FilterChain methods works correctly."""

    def test_behavior_chain_all_returns_request_filter(self):
        result = filters.FilterChain.all()
        from hookrelay.filters import RequestFilter
        assert isinstance(result, RequestFilter)

    def test_behavior_chain_all_with_filters(self):
        f1 = filters.RequestFilter().by_method("POST")
        f2 = filters.RequestFilter().by_path("/hooks")
        combined = filters.FilterChain.all(f1, f2)
        requests = [
            {"method": "POST", "path": "/hooks"},
            {"method": "POST", "path": "/other"},
            {"method": "GET", "path": "/hooks"},
        ]
        result = combined.apply(requests)
        assert len(result) == 1
        assert result[0]["path"] == "/hooks"
        assert result[0]["method"] == "POST"

    def test_behavior_chain_any_returns_request_filter(self):
        result = filters.FilterChain.any()
        from hookrelay.filters import RequestFilter
        assert isinstance(result, RequestFilter)

    def test_behavior_chain_any_with_filters(self):
        f1 = filters.RequestFilter().by_method("POST")
        f2 = filters.RequestFilter().by_method("GET")
        combined = filters.FilterChain.any(f1, f2)
        requests = [
            {"method": "POST", "path": "/hook"},
            {"method": "GET", "path": "/health"},
            {"method": "PUT", "path": "/update"},
        ]
        result = combined.apply(requests)
        assert len(result) == 2

    def test_behavior_chain_not_returns_request_filter(self):
        f = filters.RequestFilter().by_method("POST")
        result = filters.FilterChain.not_(f)
        from hookrelay.filters import RequestFilter
        assert isinstance(result, RequestFilter)

    def test_behavior_chain_not_with_filter(self):
        f = filters.RequestFilter().by_method("POST")
        not_f = filters.FilterChain.not_(f)
        requests = [
            {"method": "POST", "path": "/hook"},
            {"method": "GET", "path": "/health"},
        ]
        result = not_f.apply(requests)
        assert len(result) == 1
        assert result[0]["method"] == "GET"

    def test_behavior_chain_nested_composition(self):
        f1 = filters.RequestFilter().by_method("POST")
        f2 = filters.RequestFilter().by_path("/hooks")
        f3 = filters.RequestFilter().by_method("GET")
        combined = filters.FilterChain.any(
            filters.FilterChain.all(f1, f2),
            filters.FilterChain.not_(f3),
        )
        requests = [
            {"method": "POST", "path": "/hooks"},
            {"method": "GET", "path": "/hooks"},
            {"method": "PUT", "path": "/hooks"},
        ]
        result = combined.apply(requests)
        assert len(result) == 2  # POST+hooks + not(GET)


class TestFilterExpressionParserBehavioral:
    """FilterExpressionParser works correctly."""

    def test_behavior_parse_simple_expression(self):
        result = filters.FilterExpressionParser.parse("method=POST")
        from hookrelay.filters import RequestFilter
        assert isinstance(result, RequestFilter)
        requests = [
            {"method": "POST", "path": "/hook"},
            {"method": "GET", "path": "/health"},
        ]
        matched = result.apply(requests)
        assert len(matched) == 1

    def test_behavior_parse_with_regex_operator(self):
        result = filters.FilterExpressionParser.parse("path~^/stripe")
        requests = [
            {"method": "POST", "path": "/stripe/hooks"},
            {"method": "POST", "path": "/other"},
        ]
        matched = result.apply(requests)
        assert len(matched) == 1

    def test_behavior_parse_with_and(self):
        result = filters.FilterExpressionParser.parse(
            "method=POST AND path~^/stripe"
        )
        requests = [
            {"method": "POST", "path": "/stripe/hooks"},
            {"method": "POST", "path": "/other"},
            {"method": "GET", "path": "/stripe/hooks"},
        ]
        matched = result.apply(requests)
        assert len(matched) == 1

    def test_behavior_parse_with_json_field(self):
        result = filters.FilterExpressionParser.parse(
            "body.type~^charge"
        )
        requests = [
            {"body": b'{"type": "charge.completed"}'},
            {"body": b'{"type": "ping"}'},
        ]
        matched = result.apply(requests)
        assert len(matched) == 1

    def test_behavior_parse_empty_string(self):
        result = filters.FilterExpressionParser.parse("")
        from hookrelay.filters import RequestFilter
        assert isinstance(result, RequestFilter)

    def test_behavior_parse_with_header_regex(self):
        result = filters.FilterExpressionParser.parse(
            "header.X-GitHub-Event~^push"
        )
        requests = [
            {"headers": {"X-GitHub-Event": "push"}},
            {"headers": {"X-GitHub-Event": "pull_request"}},
        ]
        matched = result.apply(requests)
        assert len(matched) == 1
