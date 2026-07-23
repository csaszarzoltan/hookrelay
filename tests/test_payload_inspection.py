"""Pre-development tests for payload inspection module.

Interface tests (imports, signatures): should pass immediately.
Behavioral tests (stub execution): should raise NotImplementedError.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import ingester, models

# ============================================================
# Interface tests — ingester functions
# ============================================================

class TestIngesterInterface:
    """Verify ingester functions exist and have correct signatures."""

    def test_receive_webhook_exists(self):
        assert hasattr(ingester, "receive_webhook")
        assert callable(ingester.receive_webhook)

    def test_receive_webhook_signature(self):
        sig = inspect.signature(ingester.receive_webhook)
        params = sig.parameters
        assert "channel" in params
        assert "method" in params
        assert "headers" in params
        assert "body" in params
        assert "query_params" in params
        assert "source_ip" in params

    def test_extract_method_exists(self):
        assert hasattr(ingester, "extract_method")
        assert callable(ingester.extract_method)

    def test_extract_method_signature(self):
        sig = inspect.signature(ingester.extract_method)
        assert "headers" in sig.parameters
        assert "default" in sig.parameters

    def test_extract_headers_exists(self):
        assert hasattr(ingester, "extract_headers")
        assert callable(ingester.extract_headers)

    def test_extract_headers_signature(self):
        sig = inspect.signature(ingester.extract_headers)
        assert "raw_headers" in sig.parameters

    def test_extract_body_exists(self):
        assert hasattr(ingester, "extract_body")
        assert callable(ingester.extract_body)

    def test_extract_body_signature(self):
        sig = inspect.signature(ingester.extract_body)
        assert "raw_body" in sig.parameters
        assert "max_size" in sig.parameters

    def test_extract_query_params_exists(self):
        assert hasattr(ingester, "extract_query_params")
        assert callable(ingester.extract_query_params)

    def test_validate_payload_size_exists(self):
        assert hasattr(ingester, "validate_payload_size")
        assert callable(ingester.validate_payload_size)

    def test_validate_payload_size_signature(self):
        sig = inspect.signature(ingester.validate_payload_size)
        assert "body" in sig.parameters
        assert "max_size" in sig.parameters


# ============================================================
# Interface tests — Models
# ============================================================

class TestModelsInterface:
    """Verify model classes exist and have correct signatures."""

    def test_webhook_request_class_exists(self):
        assert hasattr(models, "WebhookRequest")
        assert inspect.isclass(models.WebhookRequest)

    def test_webhook_request_init_signature(self):
        sig = inspect.signature(models.WebhookRequest.__init__)
        params = sig.parameters
        assert "request_id" in params
        assert "channel" in params
        assert "method" in params
        assert "path" in params
        assert "headers" in params
        assert "body" in params
        assert "query_params" in params
        assert "source_ip" in params

    def test_webhook_request_to_dict_exists(self):
        assert hasattr(models.WebhookRequest, "to_dict")
        assert callable(models.WebhookRequest.to_dict)

    def test_webhook_request_from_dict_exists(self):
        assert hasattr(models.WebhookRequest, "from_dict")
        assert callable(models.WebhookRequest.from_dict)

    def test_filter_criteria_class_exists(self):
        assert hasattr(models, "FilterCriteria")
        assert inspect.isclass(models.FilterCriteria)

    def test_filter_criteria_init_signature(self):
        sig = inspect.signature(models.FilterCriteria.__init__)
        assert "method" in sig.parameters
        assert "path" in sig.parameters
        assert "source" in sig.parameters
        assert "channel" in sig.parameters


# ============================================================
# Behavioral tests — ingester real behavior
# ============================================================

class TestIngesterBehavioral:
    """Calling ingester functions returns expected results."""

    def test_behavior_receive_webhook_returns_dict(self):
        result = ingester.receive_webhook(
            channel="test",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=b'{"key": "value"}',
            query_params={"ref": "abc"},
            source_ip="203.0.113.1",
        )
        assert isinstance(result, dict)
        assert result["channel"] == "test"
        assert result["method"] == "POST"
        assert result["source_ip"] == "203.0.113.1"
        assert "request_id" in result
        assert "received_at" in result

    def test_behavior_extract_method_returns_header_value(self):
        result = ingester.extract_method({"X-Forwarded-Method": "PUT"})
        assert result == "PUT"

    def test_behavior_extract_method_default_returns_default(self):
        result = ingester.extract_method({}, default="POST")
        assert result == "POST"

    def test_behavior_extract_headers_normalizes_keys(self):
        result = ingester.extract_headers({
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=abc123",
        })
        assert "Content-Type" in result
        assert result["Content-Type"] == "application/json"

    def test_behavior_extract_body_returns_bytes(self):
        result = ingester.extract_body(b'{"key": "value"}')
        assert isinstance(result, bytes)
        assert result == b'{"key": "value"}'

    def test_behavior_extract_body_with_max_size_raises_on_overflow(self):
        with pytest.raises(ValueError):
            ingester.extract_body(b"x" * 1000, max_size=500)

    def test_behavior_extract_query_params_returns_dict(self):
        result = ingester.extract_query_params({"ref": "abc", "source": "github"})
        assert result == {"ref": "abc", "source": "github"}

    def test_behavior_validate_payload_size_returns_true(self):
        assert ingester.validate_payload_size(b"test payload") is True

    def test_behavior_validate_payload_size_under_limit_returns_true(self):
        assert ingester.validate_payload_size(b"small", max_size=1000) is True

    def test_behavior_validate_payload_size_over_limit_returns_false(self):
        assert ingester.validate_payload_size(b"x" * 2000, max_size=100) is False


# ============================================================
# Behavioral tests — Model real behavior
# ============================================================

class TestModelsBehavioral:
    """Model constructors and methods work correctly."""

    def test_behavior_webhook_request_init_creates_instance(self):
        req = models.WebhookRequest(
            request_id="abc-123",
            channel="test",
            method="POST",
            path="/",
            headers={"Content-Type": "application/json"},
            body=b'{"key": "value"}',
            query_params={},
            source_ip="203.0.113.1",
        )
        assert req.request_id == "abc-123"
        assert req.channel == "test"
        assert req.method == "POST"

    def test_behavior_to_dict_returns_dict(self):
        req = models.WebhookRequest(
            request_id="abc-123",
            channel="test",
            method="POST",
            path="/",
            headers={"Content-Type": "application/json"},
            body=b'{"key": "value"}',
            query_params={},
            source_ip="203.0.113.1",
        )
        d = req.to_dict()
        assert d["request_id"] == "abc-123"
        assert d["method"] == "POST"
        assert d["channel"] == "test"

    def test_behavior_from_dict_returns_request(self):
        req = models.WebhookRequest.from_dict({
            "request_id": "xyz-789",
            "channel": "demo",
            "method": "PUT",
            "path": "/hook",
            "headers": {"X-Custom": "val"},
            "body": "test body",
            "query_params": {},
            "source_ip": "10.0.0.1",
        })
        assert req.request_id == "xyz-789"
        assert req.method == "PUT"
        assert req.channel == "demo"

    def test_behavior_filter_criteria_init_creates_instance(self):
        fc = models.FilterCriteria(method="POST", channel="test")
        assert fc.method == "POST"
        assert fc.channel == "test"
        assert fc.path is None
