"""Pre-development tests for Schema Storage module (Group B).

Interface tests (imports, signatures): should pass immediately.
Behavioral tests: should raise NotImplementedError until implemented.
"""

from __future__ import annotations

import inspect

import pytest

from hookrelay.schemas import SchemaStore

# ============================================================
# Interface tests — SchemaStore class
# ============================================================

class TestSchemaStoreInterface:
    """Verify SchemaStore class and methods exist."""

    def test_schema_store_class_exists(self):
        assert inspect.isclass(SchemaStore)

    def test_schema_store_init_signature(self):
        sig = inspect.signature(SchemaStore.__init__)
        assert "storage" in sig.parameters

    def test_create_schema_exists(self):
        assert hasattr(SchemaStore, "create_schema")
        assert callable(SchemaStore.create_schema)
        sig = inspect.signature(SchemaStore.create_schema)
        params = sig.parameters
        assert "name" in params
        assert "channel" in params
        assert "schema_definition" in params
        assert "draft_version" in params
        assert params["draft_version"].default == "2020-12"
        assert "enabled" in params
        assert params["enabled"].default is True
        assert "severity_level" in params
        assert params["severity_level"].default == "error"
        assert "version" in params
        assert params["version"].default == "1.0.0"
        assert "metadata" in params

    def test_get_schema_exists(self):
        assert hasattr(SchemaStore, "get_schema")
        assert callable(SchemaStore.get_schema)
        sig = inspect.signature(SchemaStore.get_schema)
        assert "schema_id" in sig.parameters

    def test_list_schemas_exists(self):
        assert hasattr(SchemaStore, "list_schemas")
        assert callable(SchemaStore.list_schemas)
        sig = inspect.signature(SchemaStore.list_schemas)
        assert "channel" in sig.parameters
        assert "enabled_only" in sig.parameters

    def test_update_schema_exists(self):
        assert hasattr(SchemaStore, "update_schema")
        assert callable(SchemaStore.update_schema)
        sig = inspect.signature(SchemaStore.update_schema)
        assert "schema_id" in sig.parameters

    def test_delete_schema_exists(self):
        assert hasattr(SchemaStore, "delete_schema")
        assert callable(SchemaStore.delete_schema)
        sig = inspect.signature(SchemaStore.delete_schema)
        assert "schema_id" in sig.parameters


# ============================================================
# Behavioral tests — SchemaStore CRUD
# ============================================================

class TestSchemaStoreCRUDBehavioral:
    """Call SchemaStore CRUD methods with expected behavior."""

    @pytest.fixture
    def store(self):
        """Create a SchemaStore with an in-memory Storage."""
        import os
        import tempfile

        from hookrelay.storage import Storage
        db_path = os.path.join(tempfile.gettempdir(), "hookrelay_test_schemas.db")
        storage = Storage(db_path)
        return SchemaStore(storage)

    def test_behavior_create_schema_returns_record(self, store):
        """create_schema() should return a schema record with generated ID."""
        schema_def = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        result = store.create_schema(
            name="user-profile",
            channel="users",
            schema_definition=schema_def,
        )
        assert result is not None
        assert "schema_id" in result
        assert result["name"] == "user-profile"
        assert result["channel"] == "users"
        assert result["draft_version"] == "2020-12"
        assert result["enabled"] is True

    def test_behavior_get_schema_returns_record(self, store):
        """get_schema() should return the stored record."""
        schema_def = {"type": "object"}
        created = store.create_schema(
            name="test-get",
            channel="test",
            schema_definition=schema_def,
        )
        retrieved = store.get_schema(created["schema_id"])
        assert retrieved is not None
        assert retrieved["schema_id"] == created["schema_id"]
        assert retrieved["name"] == "test-get"

    def test_behavior_get_schema_returns_none_for_missing(self, store):
        """get_schema() should return None for unknown schema_id."""
        result = store.get_schema("nonexistent-id")
        assert result is None

    def test_behavior_list_schemas_returns_all(self, store):
        """list_schemas() should return all schema records."""
        store.create_schema(name="s1", channel="ch1", schema_definition={"type": "object"})
        store.create_schema(name="s2", channel="ch2", schema_definition={"type": "object"})
        results = store.list_schemas()
        assert len(results) >= 2

    def test_behavior_list_schemas_filter_by_channel(self, store):
        """list_schemas(channel='payments') should filter by channel."""
        store.create_schema(name="pay1", channel="payments", schema_definition={"type": "object"})
        store.create_schema(name="ord1", channel="orders", schema_definition={"type": "object"})
        results = store.list_schemas(channel="payments")
        assert all(r["channel"] == "payments" for r in results)

    def test_behavior_list_schemas_enabled_only(self, store):
        """list_schemas(enabled_only=True) should only return enabled schemas."""
        store.create_schema(name="enabled1", channel="ch", schema_definition={"type": "object"}, enabled=True)
        store.create_schema(name="disabled1", channel="ch", schema_definition={"type": "object"}, enabled=False)
        results = store.list_schemas(enabled_only=True)
        assert all(r["enabled"] for r in results)

    def test_behavior_update_schema_modifies_fields(self, store):
        """update_schema() should modify specified fields."""
        created = store.create_schema(
            name="before", channel="ch", schema_definition={"type": "object"},
        )
        updated = store.update_schema(
            created["schema_id"],
            name="after",
            enabled=False,
        )
        assert updated is not None
        assert updated["name"] == "after"
        assert updated["enabled"] is False

    def test_behavior_update_schema_returns_none_for_missing(self, store):
        """update_schema() should return None for unknown id."""
        result = store.update_schema("nonexistent", name="new")
        assert result is None

    def test_behavior_delete_schema_removes_record(self, store):
        """delete_schema() should remove and return True."""
        created = store.create_schema(
            name="todelete", channel="ch", schema_definition={"type": "object"},
        )
        deleted = store.delete_schema(created["schema_id"])
        assert deleted is True
        # Verify it's gone
        assert store.get_schema(created["schema_id"]) is None

    def test_behavior_delete_schema_returns_false_for_missing(self, store):
        """delete_schema() should return False for unknown id."""
        result = store.delete_schema("nonexistent")
        assert result is False


# ============================================================
# Behavioral tests — Validation & Edge Cases
# ============================================================

class TestSchemaStoreValidationBehavioral:
    """SchemaStore should validate inputs."""

    @pytest.fixture
    def store(self):
        import os
        import tempfile

        from hookrelay.storage import Storage
        db_path = os.path.join(tempfile.gettempdir(), "hookrelay_test_schemas_valid.db")
        storage = Storage(db_path)
        return SchemaStore(storage)

    def test_behavior_create_schema_rejects_empty_name(self, store):
        """create_schema() with empty name should raise ValueError."""
        with pytest.raises(ValueError, match="name"):
            store.create_schema(name="", channel="ch", schema_definition={"type": "object"})

    def test_behavior_create_schema_rejects_empty_channel(self, store):
        """create_schema() with empty channel should raise ValueError."""
        with pytest.raises(ValueError, match="channel"):
            store.create_schema(name="test", channel="", schema_definition={"type": "object"})

    def test_behavior_create_schema_rejects_invalid_schema_def(self, store):
        """create_schema() with non-dict schema_definition should raise TypeError."""
        with pytest.raises((TypeError, ValueError)):
            store.create_schema(name="test", channel="ch", schema_definition="not-a-dict")

    def test_behavior_create_schema_rejects_unsupported_draft(self, store):
        """create_schema() with unsupported draft should raise ValueError."""
        with pytest.raises(ValueError, match="draft"):
            store.create_schema(
                name="test", channel="ch",
                schema_definition={"type": "object"},
                draft_version="03",  # Unsupported
            )

    def test_behavior_create_schema_rejects_invalid_severity(self, store):
        """create_schema() with invalid severity should raise ValueError."""
        with pytest.raises(ValueError, match="severity"):
            store.create_schema(
                name="test", channel="ch",
                schema_definition={"type": "object"},
                severity_level="critical",  # Invalid
            )
