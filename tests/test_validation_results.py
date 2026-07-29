"""Pre-development tests for Validation Results Persistence (Group D).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import storage as storage_module

# ============================================================
# Interface tests — Storage extension for validation results
# ============================================================

class TestValidationResultsStorageInterface:
    """Verify storage methods for validation results exist."""

    def test_storage_has_validation_results_methods(self):
        """Storage class should have validation results methods."""
        # Check the Storage class has the expected methods
        assert hasattr(storage_module.Storage, "store_validation_result")
        assert callable(storage_module.Storage.store_validation_result)

    def test_store_validation_result_signature(self):
        sig = inspect.signature(storage_module.Storage.store_validation_result)
        params = sig.parameters
        assert "self" in params
        assert "request_id" in params
        assert "schema_id" in params
        assert "result" in params

    def test_get_validation_result_exists(self):
        assert hasattr(storage_module.Storage, "get_validation_result")
        assert callable(storage_module.Storage.get_validation_result)

    def test_get_validation_result_signature(self):
        sig = inspect.signature(storage_module.Storage.get_validation_result)
        assert "request_id" in sig.parameters

    def test_get_validation_results_for_request_exists(self):
        assert hasattr(storage_module.Storage, "get_validation_results_for_request")
        assert callable(storage_module.Storage.get_validation_results_for_request)

    def test_get_validation_results_for_request_signature(self):
        sig = inspect.signature(storage_module.Storage.get_validation_results_for_request)
        assert "request_id" in sig.parameters


# ============================================================
# Behavioral tests — Store and retrieve validation results
# ============================================================

class TestValidationResultsBehavioral:
    """Call validation results storage methods with expected outcomes."""

    @pytest.fixture
    def store(self):
        """Create a fresh in-memory Storage instance."""
        import os
        import tempfile
        db_path = os.path.join(tempfile.gettempdir(), "hookrelay_test_validation_results.db")
        s = storage_module.Storage(db_path)
        yield s
        os.unlink(db_path)

    @pytest.fixture
    def sample_validation_result(self):
        """A sample validation result dict."""
        return {
            "valid": False,
            "errors": [
                {
                    "path": "/name",
                    "schema_path": "/properties/name",
                    "message": "'abc' is not of type 'integer'",
                    "severity": "error",
                    "validator": "type",
                    "validator_value": "integer",
                },
            ],
            "warnings": [],
            "infos": [],
        }

    def test_behavior_store_validation_result_returns_id(self, store, sample_validation_result):
        """store_validation_result() should return a result_id."""
        # First store a webhook to satisfy FK
        request_id = store.store_request({
            "request_id": "req-001",
            "channel": "test",
            "method": "POST",
            "body": b'{"name": 123}',
        })
        result_id = store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=sample_validation_result,
        )
        assert result_id is not None
        assert isinstance(result_id, str)
        assert len(result_id) > 0

    def test_behavior_get_validation_result_returns_record(self, store, sample_validation_result):
        """get_validation_result() should return stored record."""
        request_id = store.store_request({
            "request_id": "req-002",
            "channel": "test",
            "body": b'{"x": 1}',
        })
        store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=sample_validation_result,
        )
        retrieved = store.get_validation_result(request_id)
        assert retrieved is not None

    def test_behavior_get_validation_result_has_correct_fields(self, store, sample_validation_result):
        """Retrieved record should have the expected structure."""
        request_id = store.store_request({
            "request_id": "req-003",
            "channel": "test",
            "body": b'{"x": 1}',
        })
        store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=sample_validation_result,
        )
        retrieved = store.get_validation_result(request_id)
        assert retrieved["request_id"] == request_id
        assert retrieved["schema_id"] == "schema-001"
        assert retrieved["valid"] is False
        assert "errors" in retrieved
        assert "validated_at" in retrieved

    def test_behavior_get_validation_result_returns_none_for_missing(self, store):
        """get_validation_result() for non-existent request should return None."""
        result = store.get_validation_result("nonexistent-request")
        assert result is None

    def test_behavior_get_multiple_results_for_request(self, store, sample_validation_result):
        """Multiple validation results for same request should be retrievable."""
        request_id = store.store_request({
            "request_id": "req-004",
            "channel": "test",
            "body": b'{"x": 1}',
        })
        store.store_validation_result(
            request_id=request_id,
            schema_id="schema-a",
            result=sample_validation_result,
        )
        store.store_validation_result(
            request_id=request_id,
            schema_id="schema-b",
            result={"valid": True, "errors": [], "warnings": [], "infos": []},
        )
        results = store.get_validation_results_for_request(request_id)
        assert len(results) == 2

    def test_behavior_cascade_delete_on_webhook_removes_results(self, store, sample_validation_result):
        """Deleting a webhook should cascade-delete its validation results."""
        request_id = store.store_request({
            "request_id": "req-cascade",
            "channel": "test",
            "body": b'{"x": 1}',
        })
        store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=sample_validation_result,
        )
        # Delete the webhook
        store._conn.execute("DELETE FROM webhooks WHERE request_id = ?", (request_id,))
        store._conn.commit()
        # Verify validation result is also gone
        result = store.get_validation_result(request_id)
        assert result is None

    def test_behavior_store_validation_result_with_valid_payload(self, store):
        """Storing a valid (no errors) validation result should work."""
        request_id = store.store_request({
            "request_id": "req-valid",
            "channel": "test",
            "body": b'{"name": "Alice"}',
        })
        valid_result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "infos": [],
        }
        result_id = store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=valid_result,
        )
        assert result_id is not None
        retrieved = store.get_validation_result(request_id)
        assert retrieved["valid"] is True

    def test_behavior_store_validation_result_with_warnings(self, store):
        """Validation result with warnings should store them correctly."""
        request_id = store.store_request({
            "request_id": "req-warn",
            "channel": "test",
            "body": b'{"name": "Alice"}',
        })
        warn_result = {
            "valid": True,
            "errors": [],
            "warnings": [
                {
                    "path": "/name",
                    "message": "Name is longer than typical",
                    "severity": "warning",
                },
            ],
            "infos": [],
        }
        result_id = store.store_validation_result(
            request_id=request_id,
            schema_id="schema-001",
            result=warn_result,
        )
        assert result_id is not None
        retrieved = store.get_validation_result(request_id)
        assert retrieved["valid"] is True  # Warnings don't invalidate
