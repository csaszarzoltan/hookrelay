"""Pre-development tests for the JQ-style payload transformation engine.

Interface tests (imports, signatures, type hints): load stubs from
/tmp/hookrelay-stubs and verify contracts — pass immediately.

Behavioral tests (apply, preview, builtins): import from the real
hookrelay package and assert target behavior — fail with ImportError /
NotImplementedError / AssertionError until the developer implements
src/hookrelay/transforms/engine.py.

Target: ~35 tests (15 interface PASS, 20 behavioral RED).
"""

from __future__ import annotations

import importlib.util
import inspect
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Stub loader — load stub modules from /tmp without touching the real package
# ---------------------------------------------------------------------------

_STUBS_PATH = "/tmp/hookrelay-stubs/hookrelay/transforms/engine.py"


def _load_stub(path: str = _STUBS_PATH, name: str = "transforms_engine_stub"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_engine_stub = _load_stub()

# ---------------------------------------------------------------------------
# Interface tests — TransformationEngine stub
# ---------------------------------------------------------------------------


class TestTransformEngineStubInterface:
    """Verify TransformationEngine stub exists with correct signatures."""

    def test_module_loads(self):
        assert _engine_stub is not None

    def test_engine_class_exists(self):
        assert inspect.isclass(_engine_stub.TransformationEngine)

    def test_engine_init_signature(self):
        sig = inspect.signature(_engine_stub.TransformationEngine.__init__)
        params = sig.parameters
        assert "self" in params
        assert "filters" in params
        assert params["filters"].annotation in (list[str], "list[str]")

    def test_engine_apply_exists(self):
        assert hasattr(_engine_stub.TransformationEngine, "apply")
        assert callable(_engine_stub.TransformationEngine.apply)

    def test_engine_apply_signature(self):
        sig = inspect.signature(_engine_stub.TransformationEngine.apply)
        params = sig.parameters
        assert "self" in params
        assert "payload" in params

    def test_engine_preview_exists(self):
        assert hasattr(_engine_stub.TransformationEngine, "preview")
        assert callable(_engine_stub.TransformationEngine.preview)

    def test_engine_add_field_exists(self):
        assert callable(getattr(_engine_stub.TransformationEngine, "add_field", None))

    def test_engine_remove_field_exists(self):
        assert callable(getattr(_engine_stub.TransformationEngine, "remove_field", None))

    def test_engine_rename_field_exists(self):
        assert callable(getattr(_engine_stub.TransformationEngine, "rename_field", None))

    def test_engine_convert_type_exists(self):
        assert callable(getattr(_engine_stub.TransformationEngine, "convert_type", None))


class TestBuiltinFunctionsStubInterface:
    """Verify built-in function helpers exist."""

    def test_apply_builtins_exists(self):
        assert hasattr(_engine_stub, "apply_builtins")
        assert callable(_engine_stub.apply_builtins)

    def test_apply_builtins_signature(self):
        sig = inspect.signature(_engine_stub.apply_builtins)
        params = sig.parameters
        assert "payload" in params
        assert "function_name" in params
        assert "target_path" in params

    def test_preview_transformation_exists(self):
        assert hasattr(_engine_stub, "preview_transformation")
        assert callable(_engine_stub.preview_transformation)

    def test_preview_transformation_signature(self):
        sig = inspect.signature(_engine_stub.preview_transformation)
        params = sig.parameters
        assert "filters" in params
        assert "payload" in params


# ---------------------------------------------------------------------------
# Behavioral tests — target behavior (RED until implemented)
# ---------------------------------------------------------------------------


class TestTransformationEngineBehavioral:
    """Assert expected behavior of the transformation engine.

    These tests exercise the real module (not the stub) and fail with
    ImportError / NotImplementedError until the developer implements
    src/hookrelay/transforms/engine.py.
    """

    def _get_engine(self, filters: list[str] | None = None):
        from hookrelay.transforms.engine import TransformationEngine

        return TransformationEngine(filters or [])

    def test_apply_returns_dict(self):
        engine = self._get_engine([])
        result = engine.apply({"key": "value"})
        assert isinstance(result, dict)

    def test_apply_identity_on_empty_filters(self):
        engine = self._get_engine([])
        payload = {"name": "test", "count": 42}
        result = engine.apply(payload)
        assert result == payload

    def test_add_field(self):
        engine = self._get_engine([])
        engine.add_field("new_key", "new_value")
        result = engine.apply({"existing": 1})
        assert result["new_key"] == "new_value"
        assert result["existing"] == 1

    def test_remove_field(self):
        engine = self._get_engine([])
        engine.remove_field("secret")
        result = engine.apply({"secret": "hidden", "safe": "ok"})
        assert "secret" not in result
        assert result["safe"] == "ok"

    def test_rename_field(self):
        engine = self._get_engine([])
        engine.rename_field("old_name", "new_name")
        result = engine.apply({"old_name": "val"})
        assert "new_name" in result
        assert result["new_name"] == "val"
        assert "old_name" not in result

    def test_convert_type_string_to_int(self):
        engine = self._get_engine([])
        engine.convert_type("count", "integer")
        result = engine.apply({"count": "42"})
        assert result["count"] == 42

    def test_convert_type_int_to_string(self):
        engine = self._get_engine([])
        engine.convert_type("id", "string")
        result = engine.apply({"id": 123})
        assert result["id"] == "123"

    def test_preview_does_not_persist(self):
        engine = self._get_engine([])
        engine.add_field("preview_only", True)
        preview = engine.apply({"x": 1})
        assert preview.get("preview_only") is True

    def test_filter_uppercase_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins({"name": "hello"}, "uppercase", "name")
        assert result["name"] == "HELLO"

    def test_filter_lowercase_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins({"name": "WORLD"}, "lowercase", "name")
        assert result["name"] == "world"

    def test_filter_timestamp_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins({}, "timestamp", "created_at")
        assert "created_at" in result
        assert isinstance(result["created_at"], str)

    def test_filter_uuid_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins({}, "uuid", "id")
        assert "id" in result
        assert len(result["id"]) == 36  # standard UUID length

    def test_filter_hash_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins({"data": "secret"}, "hash", "data")
        assert isinstance(result["data"], str)
        assert len(result["data"]) == 64  # SHA-256 hex length

    def test_filter_mask_secrets_builtin(self):
        from hookrelay.transforms.engine import apply_builtins

        result = apply_builtins(
            {"api_key": "sk-1234567890abcdef"}, "mask_secrets", "api_key"
        )
        assert result["api_key"] != "sk-1234567890abcdef"
        assert "***" in result["api_key"]

    def test_preview_transformation_helper(self):
        from hookrelay.transforms.engine import preview_transformation

        result = preview_transformation([], {"key": "val"})
        assert isinstance(result, dict)
        assert result == {"key": "val"}
