"""Tests for per-destination retry_policy validation.

Covers the validate_retry_policy() function added to destination_store.py
and its integration into DestinationStore.create() / .update().
"""

from __future__ import annotations

import pytest

from hookrelay.routing.destination_store import (
    DestinationStore,
    validate_retry_policy,
)
from hookrelay.storage import Storage


@pytest.fixture
def store(tmp_path) -> Storage:
    return Storage(str(tmp_path / "retry_policy.db"))


# ---------------------------------------------------------------------------
# Unit tests for validate_retry_policy()
# ---------------------------------------------------------------------------


class TestValidateRetryPolicy:
    """Direct tests against the validation function."""

    def test_none_policy_accepted(self):
        """None means no retry — always valid."""
        assert validate_retry_policy(None) is None

    def test_empty_dict_normalized_to_none(self):
        """An empty dict is equivalent to no policy."""
        assert validate_retry_policy({}) is None

    def test_valid_full_policy_accepted(self):
        """All fields present and in range passes."""
        policy = {
            "max_retries": 5,
            "base_delay_seconds": 1.0,
            "backoff_factor": 2.0,
            "max_backoff_seconds": 3600,
            "jitter": True,
        }
        result = validate_retry_policy(policy)
        assert result == policy

    def test_valid_boundary_values(self):
        """Boundary values (min and max) are accepted."""
        min_policy = {
            "max_retries": 1,
            "base_delay_seconds": 0.1,
            "backoff_factor": 1.0,
            "max_backoff_seconds": 1,
        }
        result = validate_retry_policy(min_policy)
        assert result == min_policy

        max_policy = {
            "max_retries": 20,
            "base_delay_seconds": 3600,
            "backoff_factor": 10.0,
            "max_backoff_seconds": 86400,
        }
        result = validate_retry_policy(max_policy)
        assert result == max_policy

    def test_partial_policy_accepted(self):
        """Partial policies are accepted; missing fields are left for the queue."""
        policy = {"max_retries": 3}
        result = validate_retry_policy(policy)
        assert result == {"max_retries": 3}

    def test_non_dict_rejected(self):
        """Non-dict values raise TypeError."""
        with pytest.raises(TypeError, match="retry_policy must be an object"):
            validate_retry_policy("not-a-dict")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="retry_policy must be an object"):
            validate_retry_policy([1, 2])  # type: ignore[arg-type]

    def test_max_retries_zero_rejected(self):
        """max_retries < 1 is rejected."""
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy({"max_retries": 0})

    def test_max_retries_too_high(self):
        """max_retries > 20 is rejected."""
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy({"max_retries": 21})

    def test_max_retries_not_int(self):
        """max_retries must be an int, not float/string."""
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy({"max_retries": 5.5})
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy({"max_retries": "five"})

    def test_max_retries_bool_rejected(self):
        """bool is a subclass of int — must be rejected explicitly."""
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy({"max_retries": True})

    def test_base_delay_negative(self):
        """Negative base_delay_seconds is rejected."""
        with pytest.raises(ValueError, match="base_delay_seconds"):
            validate_retry_policy({"base_delay_seconds": -1.0})

    def test_base_delay_too_high(self):
        """base_delay_seconds > 3600 is rejected."""
        with pytest.raises(ValueError, match="base_delay_seconds"):
            validate_retry_policy({"base_delay_seconds": 3601})

    def test_base_delay_not_number(self):
        """base_delay_seconds must be numeric."""
        with pytest.raises(ValueError, match="base_delay_seconds"):
            validate_retry_policy({"base_delay_seconds": "fast"})

    def test_backoff_factor_zero(self):
        """backoff_factor < 1.0 is rejected (zero or negative)."""
        with pytest.raises(ValueError, match="backoff_factor"):
            validate_retry_policy({"backoff_factor": 0.0})

    def test_backoff_factor_negative(self):
        """Negative backoff_factor is rejected."""
        with pytest.raises(ValueError, match="backoff_factor"):
            validate_retry_policy({"backoff_factor": -2.5})

    def test_backoff_factor_too_high(self):
        """backoff_factor > 10.0 is rejected."""
        with pytest.raises(ValueError, match="backoff_factor"):
            validate_retry_policy({"backoff_factor": 11.0})

    def test_backoff_factor_not_number(self):
        """backoff_factor must be numeric."""
        with pytest.raises(ValueError, match="backoff_factor"):
            validate_retry_policy({"backoff_factor": "double"})

    def test_max_backoff_zero(self):
        """max_backoff_seconds < 1 is rejected."""
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            validate_retry_policy({"max_backoff_seconds": 0})

    def test_max_backoff_negative(self):
        """Negative max_backoff_seconds is rejected."""
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            validate_retry_policy({"max_backoff_seconds": -10})

    def test_max_backoff_too_high(self):
        """max_backoff_seconds > 86400 is rejected."""
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            validate_retry_policy({"max_backoff_seconds": 86401})

    def test_max_backoff_not_number(self):
        """max_backoff_seconds must be numeric."""
        with pytest.raises(ValueError, match="max_backoff_seconds"):
            validate_retry_policy({"max_backoff_seconds": "long"})

    def test_jitter_non_bool_rejected(self):
        """jitter must be a boolean, not a string or int."""
        with pytest.raises(ValueError, match="jitter"):
            validate_retry_policy({"jitter": "yes"})
        with pytest.raises(ValueError, match="jitter"):
            validate_retry_policy({"jitter": 1})

    def test_multiple_errors_on_first_invalid(self):
        """Validation fails on the first invalid field encountered."""
        with pytest.raises(ValueError, match="max_retries"):
            validate_retry_policy(
                {"max_retries": 0, "base_delay_seconds": -1}
            )

    def test_returns_validated_copy(self):
        """Returned dict is a copy, not the original object."""
        original = {"max_retries": 5}
        result = validate_retry_policy(original)
        result["max_retries"] = 99  # mutate result
        assert original["max_retries"] == 5  # original untouched


# ---------------------------------------------------------------------------
# Integration: DestinationStore.create() rejects invalid retry_policy
# ---------------------------------------------------------------------------


class TestStoreCreateRetryPolicy:
    """Ensure create() propagates validation errors."""

    VALID_URL = "https://example.com/hook"

    def test_create_with_valid_retry_policy(self, store):
        ds = DestinationStore(store)
        dest = ds.create("bin-1", self.VALID_URL, retry_policy={"max_retries": 3})
        assert dest["retry_policy"] == {"max_retries": 3}

    def test_create_with_none_retry_policy(self, store):
        ds = DestinationStore(store)
        dest = ds.create("bin-1", self.VALID_URL, retry_policy=None)
        assert dest["retry_policy"] == {}

    def test_create_rejects_invalid_max_retries(self, store):
        ds = DestinationStore(store)
        with pytest.raises(ValueError, match="max_retries"):
            ds.create("bin-1", self.VALID_URL, retry_policy={"max_retries": 0})

    def test_create_rejects_negative_delay(self, store):
        ds = DestinationStore(store)
        with pytest.raises(ValueError, match="base_delay_seconds"):
            ds.create(
                "bin-1",
                self.VALID_URL,
                retry_policy={"base_delay_seconds": -1.0},
            )


# ---------------------------------------------------------------------------
# Integration: DestinationStore.update() rejects invalid retry_policy
# ---------------------------------------------------------------------------


class TestStoreUpdateRetryPolicy:
    """Ensure update() propagates validation errors."""

    VALID_URL = "https://example.com/hook"

    def _create_dest(self, store) -> str:
        ds = DestinationStore(store)
        return ds.create("bin-1", self.VALID_URL)["destination_id"]

    def test_update_with_valid_retry_policy(self, store):
        ds = DestinationStore(store)
        dest_id = self._create_dest(store)
        updated = ds.update(dest_id, retry_policy={"max_retries": 10})
        assert updated is not None
        assert updated["retry_policy"] == {"max_retries": 10}

    def test_update_rejects_invalid_policy(self, store):
        ds = DestinationStore(store)
        dest_id = self._create_dest(store)
        with pytest.raises(ValueError, match="backoff_factor"):
            ds.update(dest_id, retry_policy={"backoff_factor": 0.0})

    def test_update_skips_validation_when_none(self, store):
        """None means 'don't change' — should not trigger validation."""
        ds = DestinationStore(store)
        dest_id = self._create_dest(store)
        ds.update(dest_id, retry_policy={"max_retries": 3})
        # Update without retry_policy — should keep the existing value.
        updated = ds.update(dest_id, enabled=False)
        assert updated is not None
        assert updated["retry_policy"] == {"max_retries": 3}
