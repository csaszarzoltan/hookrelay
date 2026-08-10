"""Pre-development tests for new CLI commands:
  hookrelay transform test <filter> <payload.json>
  hookrelay destination add <bin> <url> --transform <id> --signing <config>

These are behavioral tests that assert target behavior as if the CLI
commands already exist.  They fail with AttributeError until the
developer adds the new functions to src/hookrelay/cli.py.

Note: interface tests for new CLI functions are not included because
the functions don't exist in the cli module yet — there is no existing
code to verify signatures against.

Target: ~14 tests (all behavioral RED).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from hookrelay import cli

# ---------------------------------------------------------------------------
# Behavioral tests — target behavior (RED until implemented)
# ---------------------------------------------------------------------------


class TestTransformTestCLI:
    """Assert expected behavior of 'hookrelay transform test'."""

    def _run_transform_test(self, filter_expr: str, payload: dict):
        """Invoke the transform test backend function."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(payload, f)
            payload_path = f.name
        try:
            result = cli.transform_test(filter_expr, payload_path)
            return result
        finally:
            os.unlink(payload_path)

    def test_identity_filter(self):
        result = self._run_transform_test(".", {"key": "value"})
        assert isinstance(result, dict)
        assert result == {"key": "value"}

    def test_add_field_filter(self):
        result = self._run_transform_test('.added = "yes"', {"existing": 1})
        assert result["added"] == "yes"
        assert result["existing"] == 1

    def test_remove_field_filter(self):
        result = self._run_transform_test('del(.secret)', {"secret": "x", "ok": 1})
        assert "secret" not in result
        assert result["ok"] == 1

    def test_uppercase_builtin(self):
        result = self._run_transform_test('.name |= uppercase', {"name": "hello"})
        assert result["name"] == "HELLO"

    def test_lowercase_builtin(self):
        result = self._run_transform_test('.name |= lowercase', {"name": "WORLD"})
        assert result["name"] == "world"

    def test_timestamp_builtin(self):
        result = self._run_transform_test('.ts = timestamp', {})
        assert "ts" in result
        assert isinstance(result["ts"], str)

    def test_uuid_builtin(self):
        result = self._run_transform_test('.id = uuid', {})
        assert "id" in result
        assert len(result["id"]) == 36

    def test_hash_builtin(self):
        result = self._run_transform_test('.hash = hash', {"data": "test"})
        assert isinstance(result["hash"], str)
        assert len(result["hash"]) == 64


class TestDestinationAddCLI:
    """Assert expected behavior of 'hookrelay destination add'."""

    def test_add_destination_returns_id(self):
        result = cli.destination_add("bin-1", "https://example.com/hook")
        assert isinstance(result, dict)
        assert "destination_id" in result
        assert result["bin_id"] == "bin-1"
        assert result["url"] == "https://example.com/hook"

    def test_add_destination_with_transform(self):
        result = cli.destination_add(
            "bin-1",
            "https://example.com/hook",
            transform_id="tf-42",
        )
        assert result["transform_id"] == "tf-42"

    def test_add_destination_with_signing(self):
        result = cli.destination_add(
            "bin-1",
            "https://example.com/hook",
            signing_config={"algorithm": "github", "secret": "whsec_abc"},
        )
        assert result["signing_config"]["algorithm"] == "github"

    def test_add_destination_with_headers(self):
        result = cli.destination_add(
            "bin-1",
            "https://example.com/hook",
            headers={"X-Custom": "value"},
        )
        assert result["headers"]["X-Custom"] == "value"

    def test_list_destinations_for_bin(self):
        cli.destination_add("bin-list", "https://example.com/hook/a")
        cli.destination_add("bin-list", "https://example.com/hook/b")
        result = cli.destination_list("bin-list")
        assert isinstance(result, list)
        assert len(result) >= 2

    def test_delete_destination(self):
        result = cli.destination_add("bin-del", "https://example.com/hook/del")
        did = result["destination_id"]
        deleted = cli.destination_delete(did)
        assert deleted is True
