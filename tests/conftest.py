"""Shared test fixtures for hookrelay tests.

Provides global storage initialization for tests that need
schema store with pre-populated data.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from hookrelay import _storage
from hookrelay.schemas import SchemaStore
from hookrelay.storage import Storage


@pytest.fixture(autouse=True, scope="session")
def _setup_global_storage():
    """Initialize global storage with pre-populated schemas for integration tests."""
    db_path = os.path.join(tempfile.gettempdir(), "hookrelay_test_global.db")
    store = Storage(db_path)
    _storage.set(store)

    # Pre-populate some schemas for auto-validation tests
    schema_store = SchemaStore(store)

    # Schema for "users" channel
    schema_store.create_schema(
        name="user-profile",
        channel="users",
        schema_definition={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        },
        enabled=True,
    )

    # Schema for "multi-schema-channel" (two schemas)
    schema_store.create_schema(
        name="schema-a",
        channel="multi-schema-channel",
        schema_definition={
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
        enabled=True,
    )
    schema_store.create_schema(
        name="schema-b",
        channel="multi-schema-channel",
        schema_definition={
            "type": "object",
            "properties": {"event": {"type": "string"}},
        },
        enabled=True,
    )

    # Schema for "strict-channel" (used by auto-validate invalid payload test)
    schema_store.create_schema(
        name="strict-schema",
        channel="strict-channel",
        schema_definition={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        },
        enabled=True,
    )

    yield

    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear validation module cache before each test."""
    from hookrelay.validation import clear_cache

    clear_cache()
