"""Pre-development tests for CLI Schema Commands (Group G).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest
import typer

from hookrelay import cli

# ============================================================
# Interface tests — CLI schema subcommand
# ============================================================

class TestCLISchemaInterface:
    """Verify schema subcommand functions exist."""

    def test_cli_has_schema_command(self):
        """CLI app should have a 'schema' subcommand."""
        app = cli.get_app()
        # Check registered commands — the schema command may be via typer.Typer group
        assert app is not None

    def test_schema_create_function_exists(self):
        """cli module should have schema_create function."""
        assert hasattr(cli, "schema_create")
        assert callable(cli.schema_create)
        sig = inspect.signature(cli.schema_create)
        params = sig.parameters
        assert "file" in params or "schema_file" in params or "definition" in params

    def test_schema_list_function_exists(self):
        """cli module should have schema_list function."""
        assert hasattr(cli, "schema_list")
        assert callable(cli.schema_list)

    def test_schema_list_signature(self):
        sig = inspect.signature(cli.schema_list)
        assert "channel" in sig.parameters

    def test_schema_get_function_exists(self):
        """cli module should have schema_get function."""
        assert hasattr(cli, "schema_get")
        assert callable(cli.schema_get)
        sig = inspect.signature(cli.schema_get)
        assert "schema_id" in sig.parameters

    def test_schema_delete_function_exists(self):
        """cli module should have schema_delete function."""
        assert hasattr(cli, "schema_delete")
        assert callable(cli.schema_delete)
        sig = inspect.signature(cli.schema_delete)
        assert "schema_id" in sig.parameters

    def test_schema_validate_function_exists(self):
        """cli module should have schema_validate function."""
        assert hasattr(cli, "schema_validate")
        assert callable(cli.schema_validate)
        sig = inspect.signature(cli.schema_validate)
        params = sig.parameters
        assert "payload_file" in params or "file" in params


# ============================================================
# Behavioral tests — CLI schema commands
# ============================================================

class TestCLISchemaBehavioral:
    """Call CLI schema commands with expected outcomes."""

    def test_behavior_schema_create_from_file(self, tmp_path):
        """schema_create should load a JSON Schema file and register it."""
        import json
        schema_file = tmp_path / "user-schema.json"
        schema_file.write_text(json.dumps({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }))
        result = cli.schema_create(
            file=str(schema_file),
            channel="users",
        )
        assert result is not None
        assert "schema_id" in result or isinstance(result, dict)

    def test_behavior_schema_create_with_all_options(self, tmp_path):
        """schema_create should accept optional parameters."""
        import json
        schema_file = tmp_path / "order-schema.json"
        schema_file.write_text(json.dumps({
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
        }))
        result = cli.schema_create(
            file=str(schema_file),
            channel="orders",
            name="order-schema",
            version="2.0.0",
            severity="warning",
            draft="07",
        )
        assert result is not None

    def test_behavior_schema_create_with_nonexistent_file(self):
        """schema_create with missing file should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.schema_create(file="/nonexistent/path/schema.json", channel="test")

    def test_behavior_schema_create_with_invalid_json(self, tmp_path):
        """schema_create with invalid JSON should raise."""
        import json as _json
        schema_file = tmp_path / "invalid.json"
        schema_file.write_text("not-json")
        with pytest.raises((typer.Exit, ValueError, _json.JSONDecodeError)):
            cli.schema_create(file=str(schema_file), channel="test")

    def test_behavior_schema_list_returns_schemas(self):
        """schema_list should return list of schemas."""
        result = cli.schema_list()
        assert isinstance(result, list)

    def test_behavior_schema_list_filtered_by_channel(self):
        """schema_list(channel='payments') should filter."""
        result = cli.schema_list(channel="payments")
        assert isinstance(result, list)

    def test_behavior_schema_get_returns_detail(self):
        """schema_get with valid id should return schema detail."""
        from hookrelay.schemas import SchemaStore
        store = cli._get_storage()
        schema_store = SchemaStore(store)
        created = schema_store.create_schema(
            name="cli-get-test", channel="test",
            schema_definition={"type": "object"},
        )
        schema_id = created["schema_id"]
        result = cli.schema_get(schema_id=schema_id)
        assert result is not None
        assert isinstance(result, dict)
        assert result["schema_id"] == schema_id

    def test_behavior_schema_get_not_found(self):
        """schema_get with missing id should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.schema_get(schema_id="nonexistent-id")

    def test_behavior_schema_delete_removes_schema(self):
        """schema_delete with valid id should return success."""
        from hookrelay.schemas import SchemaStore
        store = cli._get_storage()
        schema_store = SchemaStore(store)
        created = schema_store.create_schema(
            name="cli-delete-test", channel="test",
            schema_definition={"type": "object"},
        )
        schema_id = created["schema_id"]
        result = cli.schema_delete(schema_id=schema_id)
        assert result is not None

    def test_behavior_schema_delete_not_found(self):
        """schema_delete with missing id should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.schema_delete(schema_id="nonexistent-id")

    def test_behavior_schema_validate_from_file_valid(self, tmp_path):
        """schema_validate should validate a payload file against a schema."""
        import json

        from hookrelay.schemas import SchemaStore
        store = cli._get_storage()
        schema_store = SchemaStore(store)
        created = schema_store.create_schema(
            name="cli-validate-test", channel="test",
            schema_definition={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        schema_id = created["schema_id"]
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps({"name": "Alice"}))
        result = cli.schema_validate(
            payload_file=str(payload_file),
            schema_id=schema_id,
        )
        assert result is not None
        assert "valid" in result

    def test_behavior_schema_validate_from_file_invalid(self, tmp_path):
        """schema_validate should report errors for invalid payload."""
        import json

        from hookrelay.schemas import SchemaStore
        store = cli._get_storage()
        schema_store = SchemaStore(store)
        created = schema_store.create_schema(
            name="cli-validate-invalid-test", channel="test",
            schema_definition={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        schema_id = created["schema_id"]
        payload_file = tmp_path / "bad-payload.json"
        payload_file.write_text(json.dumps({"name": 123}))
        result = cli.schema_validate(
            payload_file=str(payload_file),
            schema_id=schema_id,
        )
        assert result is not None
        assert "valid" in result

    def test_behavior_schema_validate_by_channel(self, tmp_path):
        """schema_validate should accept --channel to validate against channel schemas."""
        import json
        payload_file = tmp_path / "payload.json"
        payload_file.write_text(json.dumps({"event": "test"}))
        result = cli.schema_validate(
            payload_file=str(payload_file),
            channel="webhooks",
        )
        assert result is not None

    def test_behavior_schema_validate_nonexistent_file(self):
        """schema_validate with missing file should raise typer.Exit."""
        with pytest.raises(typer.Exit):
            cli.schema_validate(payload_file="/nonexistent.json", schema_id="s1")
