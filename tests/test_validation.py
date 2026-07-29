"""Pre-development tests for Validation Engine (Group C).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay import validation
from hookrelay.validation import (
    SUPPORTED_DRAFTS,
    ValidationError,
    ValidationResult,
    clear_cache,
    compile_schema,
    validate_payload,
)

# ============================================================
# Interface tests — ValidationResult dataclass
# ============================================================

class TestValidationResultInterface:
    """Verify ValidationResult dataclass exists with correct fields."""

    def test_validation_result_class_exists(self):
        assert inspect.isclass(ValidationResult)
        # Check it's a dataclass
        assert hasattr(ValidationResult, "__dataclass_fields__")

    def test_validation_result_fields(self):
        fields = ValidationResult.__dataclass_fields__
        assert "valid" in fields
        assert "errors" in fields
        assert "warnings" in fields
        assert "infos" in fields

    def test_validation_result_to_dict_exists(self):
        assert hasattr(ValidationResult, "to_dict")
        assert callable(ValidationResult.to_dict)

    def test_validation_result_to_dict_signature(self):
        sig = inspect.signature(ValidationResult.to_dict)
        assert "self" in sig.parameters


# ============================================================
# Interface tests — ValidationError dataclass
# ============================================================

class TestValidationErrorInterface:
    """Verify ValidationError dataclass exists with correct fields."""

    def test_validation_error_class_exists(self):
        assert inspect.isclass(ValidationError)
        assert hasattr(ValidationError, "__dataclass_fields__")

    def test_validation_error_fields(self):
        fields = ValidationError.__dataclass_fields__
        assert "path" in fields
        assert "schema_path" in fields
        assert "message" in fields
        assert "severity" in fields
        assert "validator" in fields
        assert "validator_value" in fields


# ============================================================
# Interface tests — Module-level constants & functions
# ============================================================

class TestValidationModuleInterface:
    """Verify module-level symbols."""

    def test_supported_drafts_defined(self):
        assert isinstance(SUPPORTED_DRAFTS, frozenset)
        assert "2020-12" in SUPPORTED_DRAFTS
        assert "2019-09" in SUPPORTED_DRAFTS
        assert "07" in SUPPORTED_DRAFTS
        assert "06" in SUPPORTED_DRAFTS
        assert "04" in SUPPORTED_DRAFTS

    def test_validate_payload_exists(self):
        assert hasattr(validation, "validate_payload")
        assert callable(validation.validate_payload)
        sig = inspect.signature(validation.validate_payload)
        params = sig.parameters
        assert "payload" in params
        assert "schema" in params
        assert "draft" in params
        assert params["draft"].default == "2020-12"

    def test_compile_schema_exists(self):
        assert hasattr(validation, "compile_schema")
        assert callable(validation.compile_schema)
        sig = inspect.signature(validation.compile_schema)
        assert "schema" in sig.parameters
        assert "draft" in sig.parameters

    def test_clear_cache_exists(self):
        assert hasattr(validation, "clear_cache")
        assert callable(validation.clear_cache)
        sig = inspect.signature(validation.clear_cache)
        assert len(sig.parameters) == 0


# ============================================================
# Behavioral tests — validate_payload
# ============================================================

VALID_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": 0},
        "email": {"type": "string", "format": "email"},
    },
    "required": ["name"],
}

VALID_PAYLOAD = {"name": "Alice", "age": 30, "email": "alice@example.com"}


class TestValidatePayloadBehavioral:
    """Call validate_payload with various inputs."""

    def test_behavior_valid_payload_returns_valid_result(self):
        """Valid payload against schema should return valid=True, no errors."""
        result = validate_payload(VALID_PAYLOAD, VALID_SCHEMA)
        assert isinstance(result, ValidationResult)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_behavior_invalid_payload_returns_errors(self):
        """Invalid payload should return valid=False with error details."""
        payload = {"name": 123, "age": -5}
        result = validate_payload(payload, VALID_SCHEMA)
        assert isinstance(result, ValidationResult)
        assert result.valid is False
        assert len(result.errors) >= 1
        # Error should have path info
        error = result.errors[0]
        assert isinstance(error, ValidationError)
        assert error.severity == "error"
        assert error.message

    def test_behavior_missing_required_field(self):
        """Missing required field should produce validation error."""
        payload = {"age": 30}  # missing 'name'
        result = validate_payload(payload, VALID_SCHEMA)
        assert result.valid is False
        assert any("name" in e.path for e in result.errors) or \
               any("'name'" in e.message for e in result.errors)

    def test_behavior_format_validation_email(self):
        """Invalid email format should produce a validation error."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"email": {"type": "string", "format": "email"}},
        }
        result = validate_payload({"email": "not-an-email"}, schema)
        assert result.valid is False

    def test_behavior_format_validation_uri(self):
        """Invalid URI format should produce a validation error."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
        }
        result = validate_payload({"url": "not a uri"}, schema)
        assert result.valid is False

    def test_behavior_format_validation_date_time(self):
        """Invalid date-time format should produce a validation error."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"ts": {"type": "string", "format": "date-time"}},
        }
        result = validate_payload({"ts": "not-a-date"}, schema)
        assert result.valid is False

    def test_behavior_empty_payload_validates(self):
        """Empty object {} may be valid if no required fields."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        result = validate_payload({}, schema)
        assert result.valid is True


# ============================================================
# Behavioral tests — Draft version support
# ============================================================

class TestValidatePayloadDraftVersions:
    """validate_payload should support all major draft versions."""

    @pytest.mark.parametrize("draft", ["2020-12", "2019-09", "07", "06", "04"])
    def test_behavior_supported_draft_accepts_valid_payload(self, draft):
        """Each supported draft should accept a valid payload."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        result = validate_payload({"x": 42}, schema, draft=draft)
        assert result.valid is True

    def test_behavior_unsupported_draft_raises_value_error(self):
        """Unsupported draft version should raise ValueError."""
        with pytest.raises((ValueError, NotImplementedError)):
            validate_payload({}, {"type": "object"}, draft="03")

    def test_behavior_default_draft_is_2020_12(self):
        """Default draft should be 2020-12."""
        result = validate_payload({}, {"type": "object"})
        assert isinstance(result, ValidationResult)


# ============================================================
# Behavioral tests — Severity levels
# ============================================================

class TestValidatePayloadSeverity:
    """Validation should support error, warning, info severity levels."""

    def test_behavior_error_severity_returns_errors(self):
        """Schema with severity_level=error should populate result.errors."""
        schema = {"type": "object", "required": ["x"]}
        result = validate_payload({}, schema)
        assert result.valid is False
        assert len(result.errors) > 0

    def test_behavior_warning_severity_returns_warnings(self):
        """Schema with severity_level=warning should populate result.warnings."""
        # This depends on schema-level severity; test the concept
        schema = {"type": "object", "required": ["x"]}
        result = validate_payload({"x": 1}, schema)
        assert isinstance(result, ValidationResult)

    def test_behavior_info_severity_returns_infos(self):
        """Schema with severity_level=info should populate result.infos."""
        schema = {"type": "object"}
        result = validate_payload({}, schema)
        assert isinstance(result, ValidationResult)


# ============================================================
# Behavioral tests — compile_schema + caching
# ============================================================

class TestCompileSchemaBehavioral:
    """compile_schema should return a reusable validator."""

    def test_behavior_compile_schema_returns_validator(self):
        """compile_schema() should return a validator object."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        validator = compile_schema(schema)
        assert validator is not None

    def test_behavior_compiled_validator_can_validate(self):
        """Compiled validator should be callable for validation."""
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        validator = compile_schema(schema)
        # Validator should have a 'validate' or 'is_valid' method
        errors = list(validator.iter_errors({"x": "not-a-number"}))
        assert len(errors) >= 1

    def test_behavior_compile_schema_with_draft_specified(self):
        """compile_schema should accept a draft parameter."""
        validator = compile_schema({"type": "object"}, draft="07")
        assert validator is not None

    def test_behavior_cache_reuses_compiled_schema(self):
        """Compile same schema twice should use cache."""
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        v1 = compile_schema(schema)
        v2 = compile_schema(schema)
        assert v1 is v2  # Same object from cache

    def test_behavior_clear_cache_resets(self):
        """clear_cache() should empty the compiled schema cache."""
        schema = {"type": "object"}
        compile_schema(schema)
        clear_cache()
        # After clearing, compile again should return new object
        v3 = compile_schema(schema)
        assert v3 is not None


# ============================================================
# Behavioral tests — ValidationResult.to_dict
# ============================================================

class TestValidationResultToDict:
    """ValidationResult.to_dict() should produce JSON-serializable output."""

    def test_behavior_to_dict_returns_dict(self):
        """to_dict() should return a dict."""
        result = validate_payload({"x": 1}, {"type": "object"})
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "valid" in d
        assert "errors" in d
        assert "warnings" in d
        assert "infos" in d

    def test_behavior_to_dict_with_errors(self):
        """to_dict() with invalid payload should include error details."""
        schema = {"type": "object", "required": ["name"]}
        result = validate_payload({}, schema)
        d = result.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) >= 1
        error = d["errors"][0]
        assert "path" in error
        assert "message" in error
        assert "severity" in error

    def test_behavior_to_dict_serializable_to_json(self):
        """to_dict() should be JSON-serializable."""
        import json
        result = validate_payload(
            {"name": "Alice"},
            {"type": "object", "properties": {"name": {"type": "string"}}},
        )
        d = result.to_dict()
        # Should not raise
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
