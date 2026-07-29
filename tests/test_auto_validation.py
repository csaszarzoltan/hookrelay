"""Pre-development tests for Auto-Validation on Ingestion (Group E).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

from hookrelay import ingester

# ============================================================
# Interface tests — Auto-validation integration
# ============================================================

class TestAutoValidationInterface:
    """Verify auto-validation functions exist."""

    def test_auto_validate_on_ingest_exists(self):
        """ingester should have an auto_validate function."""
        assert hasattr(ingester, "auto_validate")

    def test_auto_validate_signature(self):
        sig = inspect.signature(ingester.auto_validate)
        params = sig.parameters
        assert "channel" in params
        assert "body" in params
        assert "headers" in params

    def test_receive_webhook_integration(self):
        """receive_webhook should call auto_validate internally (or have hook)."""
        sig = inspect.signature(ingester.receive_webhook)
        # Check it still has original params
        assert "channel" in sig.parameters


# ============================================================
# Behavioral tests — Auto-validation behavior
# ============================================================

class TestAutoValidationBehavioral:
    """Call auto-validation functions with expected outcomes."""

    def test_behavior_auto_validate_json_payload_with_matching_schema(self):
        """Auto-validation should run when matching schema exists."""
        body = b'{"name": "Alice", "age": 30}'
        result = ingester.auto_validate(
            channel="users",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert result is not None
        assert "validated" in result
        assert "results" in result

    def test_behavior_auto_validate_skips_non_json(self):
        """Non-JSON payloads should be skipped gracefully (not raise)."""
        body = b"<xml><data>hello</data></xml>"
        result = ingester.auto_validate(
            channel="users",
            body=body,
            headers={"Content-Type": "application/xml"},
        )
        # Should not raise, should indicate skip
        assert result is not None
        assert result.get("skipped") is True or result.get("validated") is False

    def test_behavior_auto_validate_never_blocks_ingestion(self):
        """Validation failure should never raise an exception."""
        body = b'{"bad": json'  # Invalid JSON
        result = ingester.auto_validate(
            channel="users",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        # Should not raise, should gracefully handle parse error
        assert result is not None

    def test_behavior_auto_validate_with_no_matching_schema(self):
        """When no schema matches the channel, should indicate no validation."""
        body = b'{"name": "Alice"}'
        result = ingester.auto_validate(
            channel="nonexistent-channel",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert result is not None
        # Should indicate no schema found (not an error)
        assert result.get("no_schema") is True or result.get("validated") is False

    def test_behavior_auto_validate_multiple_schemas(self):
        """Multiple schemas on same channel should all be evaluated."""
        body = b'{"name": "Bob"}'
        result = ingester.auto_validate(
            channel="multi-schema-channel",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert result is not None
        results_list = result.get("results", [])
        assert len(results_list) >= 2  # Multiple schema results

    def test_behavior_auto_validate_invalid_payload_reports_errors(self):
        """Invalid JSON payload against schema should report errors."""
        body = b'{"name": 123, "age": "not-a-number"}'
        result = ingester.auto_validate(
            channel="strict-channel",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        assert result is not None
        results_list = result.get("results", [])
        if results_list:
            assert any(not r.get("valid", True) for r in results_list)

    def test_behavior_auto_validate_empty_body(self):
        """Empty body should not raise."""
        result = ingester.auto_validate(
            channel="users",
            body=b"",
            headers={"Content-Type": "application/json"},
        )
        assert result is not None

    def test_behavior_receive_webhook_includes_validation(self):
        """receive_webhook should emit validation status in returned dict."""
        result = ingester.receive_webhook(
            channel="test",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=b'{"name": "Alice"}',
            query_params=None,
            source_ip="127.0.0.1",
        )
        assert isinstance(result, dict)
        # Should include validation info
        assert "validation_status" in result or "validation" in result
