"""Validation engine — JSON Schema validation with severity levels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ValidationError:
    """A single validation error, warning, or info message."""

    path: str
    schema_path: str
    message: str
    severity: str = "error"
    validator: str = ""
    validator_value: str = ""


@dataclass
class ValidationResult:
    """Result of validating a payload against a schema."""

    valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    infos: list[ValidationError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the validation result to a JSON-compatible dict."""
        return {
            "valid": self.valid,
            "errors": [asdict(e) for e in self.errors],
            "warnings": [asdict(w) for w in self.warnings],
            "infos": [asdict(i) for i in self.infos],
        }


# Draft versions supported
SUPPORTED_DRAFTS = frozenset({
    "2020-12",
    "2019-09",
    "07",
    "06",
    "04",
})

# Map short draft names to jsonschema validator classes
_DRAFT_VALIDATORS: dict[str, Any] = {}

# Cache for compiled schemas (cache_key -> validator)
_schema_cache: dict[str, Any] = {}


def _get_draft_validator(draft: str) -> Any:
    """Get the jsonschema validator class for a draft version."""
    if draft in _DRAFT_VALIDATORS:
        return _DRAFT_VALIDATORS[draft]

    import jsonschema

    _DRAFT_VALIDATORS.update({
        "2020-12": jsonschema.Draft202012Validator,
        "2019-09": jsonschema.Draft201909Validator,
        "07": jsonschema.Draft7Validator,
        "06": jsonschema.Draft6Validator,
        "04": jsonschema.Draft4Validator,
    })
    return _DRAFT_VALIDATORS[draft]


def _make_cache_key(schema: dict[str, Any], draft: str) -> str:
    """Generate a cache key from schema content and draft version."""
    raw = json.dumps(schema, sort_keys=True) + draft
    return hashlib.sha256(raw.encode()).hexdigest()


def _jsonschema_error_to_validation_error(error: Any) -> ValidationError:
    """Convert a jsonschema.ValidationError to our ValidationError."""
    path = "/" + "/".join(str(p) for p in error.absolute_path) if error.absolute_path else "/"
    schema_path = "/" + "/".join(str(p) for p in error.absolute_schema_path) if error.absolute_schema_path else "/"

    return ValidationError(
        path=path,
        schema_path=schema_path,
        message=error.message,
        severity="error",
        validator=error.validator if hasattr(error, "validator") else "",
        validator_value=str(error.validator_value) if hasattr(error, "validator_value") else "",
    )


def validate_payload(
    payload: dict[str, Any],
    schema: dict[str, Any],
    draft: str = "2020-12",
) -> ValidationResult:
    """Validate a JSON payload against a JSON Schema.

    Args:
        payload: The JSON payload to validate (as a Python dict).
        schema: The JSON Schema definition (as a Python dict).
        draft: JSON Schema draft version. Must be one of SUPPORTED_DRAFTS.

    Returns:
        A ValidationResult with valid flag and lists of errors/warnings/infos.
    """
    if draft not in SUPPORTED_DRAFTS:
        raise ValueError(
            f"Unsupported draft version '{draft}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_DRAFTS))}"
        )

    validator = compile_schema(schema, draft)
    errors = list(validator.iter_errors(payload))

    if not errors:
        return ValidationResult(valid=True)

    validation_errors = [_jsonschema_error_to_validation_error(e) for e in errors]
    return ValidationResult(valid=False, errors=validation_errors)


def compile_schema(
    schema: dict[str, Any],
    draft: str = "2020-12",
) -> Any:
    """Compile a JSON Schema into a reusable validator.

    Uses an in-memory cache keyed on schema content hash to avoid
    recompilation.

    Args:
        schema: The JSON Schema definition.
        draft: JSON Schema draft version.

    Returns:
        A compiled validator (jsonschema validator instance).
    """
    cache_key = _make_cache_key(schema, draft)
    if cache_key in _schema_cache:
        return _schema_cache[cache_key]

    validator_cls = _get_draft_validator(draft)
    import jsonschema
    validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())
    _schema_cache[cache_key] = validator
    return validator


def clear_cache() -> None:
    """Clear the compiled schema cache."""
    _schema_cache.clear()
