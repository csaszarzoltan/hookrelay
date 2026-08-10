"""JQ-style payload transformation engine.

The engine applies an ordered list of JQ-style filter expressions to a JSON
payload.  Each filter string may contain one or more statements separated by
pipes (``|``), drawn from the following sub-language:

* ``.``                          → identity (no-op, useful for previews)
* ``.field = <json>``            → set/add a field to a JSON value
* ``del(.field)``                → remove a field
* ``.old = .new`` / rename       → rename via ``.new = .old | del(.old)``
* ``.field |= <builtin>``        → apply a built-in to a field's value
* ``.field = <builtin>``         → assign a generated value (timestamp/uuid/hash)
* ``.field :: <type>``           → type conversion (integer/string/float/bool)

Supported built-ins: ``uppercase``, ``lowercase``, ``timestamp``, ``uuid``,
``hash`` (SHA-256 hex) and ``mask_secrets``.

A filter list can also be built programmatically via
:meth:`TransformationEngine.add_field`, :meth:`remove_field`,
:meth:`rename_field` and :meth:`convert_type`, which layer deterministic
operations on top of any parsed filters. :func:`apply_builtins` applies a
single named built-in to one path and is the unit used by the CLI preview.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

#: Well-known built-in transformation functions.
_BUILTINS: dict[str, Callable[[str], str]] = {
    "uppercase": lambda v: v.upper(),
    "lowercase": lambda v: v.lower(),
}


def _now_timestamp() -> str:
    """Return the current time as an ISO-8601 UTC string."""
    return datetime.now(UTC).isoformat()


def _new_uuid() -> str:
    """Return a standard (36-char) UUID4 string."""
    return str(uuid.uuid4())


def _sha256_hex(value: Any) -> str:
    """Return the hex SHA-256 digest of ``value`` coerced to a string."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _masked(value: Any) -> str:
    """Return a masked form of ``value`` suitable for logs/previews."""
    if isinstance(value, str) and value.startswith("«redacted"):
        # Input from a prior masking pass — mask again for consistency.
        return "***"
    text = str(value)
    if not text:
        return "***"
    if len(text) <= 4:
        return "***"
    return text[:2] + "*" * (len(text) - 4) + text[-2:]


def apply_builtins(
    payload: dict[str, Any], function_name: str, target_path: str
) -> dict[str, Any]:
    """Apply a named built-in function to the value at ``target_path``.

    Supported builtins: ``uppercase``, ``lowercase``, ``timestamp``, ``uuid``,
    ``hash`` (SHA-256 hex), ``mask_secrets``.

    Args:
        payload: The payload to transform (copied, not mutated in place).
        function_name: One of the supported builtin names.
        target_path: Dotted path of the field to transform (**without** a
            leading dot).

    Returns:
        A new payload with the transformation applied.
    """
    work = dict(payload)

    def _set(path: str, value: Any) -> None:
        keys = _split_path(path)
        if not keys:
            return
        node = work
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value

    if function_name == "uppercase":
        _set(target_path, _BUILTINS["uppercase"](_stringify(_get_path(work, target_path))))
    elif function_name == "lowercase":
        _set(target_path, _BUILTINS["lowercase"](_stringify(_get_path(work, target_path))))
    elif function_name == "timestamp":
        _set(target_path, _now_timestamp())
    elif function_name == "uuid":
        _set(target_path, _new_uuid())
    elif function_name == "hash":
        _set(target_path, _sha256_hex(_get_path(work, target_path)))
    elif function_name == "mask_secrets":
        _set(target_path, _masked(_get_path(work, target_path)))
    else:
        raise ValueError(f"unknown builtin: {function_name}")
    return work


def _stringify(value: Any) -> str:
    """Coerce ``value`` to a string for string-oriented builtins."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _split_path(path: str) -> list[str]:
    """Split a dotted path into keys, tolerating leading/trailing dots."""
    return [p for p in path.strip().strip(".").split(".") if p]


def _get_path(payload: dict[str, Any], path: str) -> Any:
    """Return the value at a dotted ``path`` or ``None`` if absent."""
    node: Any = payload
    for key in _split_path(path):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _convert(value: Any, target_type: str) -> Any:
    """Coerce ``value`` to ``target_type`` (integer/string/float/bool)."""
    t = (target_type or "").strip().lower()
    if t in ("int", "integer"):
        return int(value)
    if t in ("str", "string"):
        return str(value)
    if t in ("float", "number"):
        return float(value)
    if t in ("bool", "boolean"):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    raise ValueError(f"unsupported target type: {target_type}")


# ---------------------------------------------------------------------------
# JQ-style filter parsing
# ---------------------------------------------------------------------------


class _Op:
    """Base class for a single parsed transformation operation."""

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply this operation to ``payload`` and return the result."""
        raise NotImplementedError


class _SetOp(_Op):
    """Set/add a field to a literal value."""

    def __init__(self, path: str, value: Any) -> None:
        self.path = path
        self.value = value

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        work = dict(payload)
        keys = _split_path(self.path)
        if not keys:
            return work
        node = work
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = self.value
        return work


class _DelOp(_Op):
    """Remove a field."""

    def __init__(self, path: str) -> None:
        self.path = path

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        work = dict(payload)
        keys = _split_path(self.path)
        if not keys:
            return work
        node = work
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):
                return work
            node = node[key]
        node.pop(keys[-1], None)
        return work


class _BuiltinOp(_Op):
    """Apply a built-in function, either to a value or as a generator."""

    def __init__(self, path: str, function_name: str, *, assign: bool) -> None:
        self.path = path
        self.function_name = function_name
        self.assign = assign

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        return apply_builtins(payload, self.function_name, self.path)


class _ConvertOp(_Op):
    """Convert a field's type (``.field :: integer``)."""

    def __init__(self, path: str, target_type: str) -> None:
        self.path = path
        self.target_type = target_type

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        work = dict(payload)
        keys = _split_path(self.path)
        if not keys:
            return work
        node = work
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):
                return work
            node = node[key]
        if keys[-1] in node:
            node[keys[-1]] = _convert(node[keys[-1]], self.target_type)
        return work


_PATH_RE = re.compile(r"^\s*(?:\.?[A-Za-z0-9_]+)(?:\.[A-Za-z0-9_]+)*\s*$")
_STRING_RE = re.compile(r'^"(.*)"$', re.DOTALL)


def _parse_scalar(token: str) -> Any:
    """Parse a scalar JSON literal (string/number/bool/null/object)."""
    token = token.strip()
    try:
        return json.loads(token)
    except (json.JSONDecodeError, ValueError):
        pass
    # Bare word constants used by the mini-JQ dialect.
    if token == "true":
        return True
    if token == "false":
        return False
    if token == "null":
        return None
    # Bare date keyword used in API example filters.
    if token == "now":
        return _now_timestamp()
    if token:
        m = _STRING_RE.match(token)
        if m:
            return m.group(1)
    return token


def _parse_statement(stmt: str) -> _Op:
    """Parse a single transformation statement into an :class:`_Op`."""
    stmt = stmt.strip()
    if not stmt or stmt == ".":
        return _SetOp("", None)  # identity no-op

    # del(.field)
    del_match = re.match(r"^del\s*\(\s*(\.?[A-Za-z0-9_.]+)\s*\)$", stmt)
    if del_match:
        return _DelOp(del_match.group(1))

    # .field |= builtin
    up_match = re.match(
        r"^\.?([A-Za-z0-9_.]+)\s*\|\=\s*([A-Za-z0-9_]+)\s*$", stmt
    )
    if up_match:
        return _BuiltinOp(up_match.group(1), up_match.group(2), assign=False)

    # .field :: type  (type conversion)
    conv_match = re.match(
        r"^\.?([A-Za-z0-9_.]+)\s*::\s*([A-Za-z0-9_]+)\s*$", stmt
    )
    if conv_match:
        return _ConvertOp(conv_match.group(1), conv_match.group(2))

    # .field = <value-or-builtin>
    eq_match = re.match(
        r"^(\.?[A-Za-z0-9_.]+)\s*=\s*(.+)$", stmt
    )
    if eq_match:
        path = eq_match.group(1)
        rhs = eq_match.group(2).strip()
        if rhs in _BUILTINS or rhs in ("timestamp", "uuid", "hash", "mask_secrets"):
            return _BuiltinOp(path, rhs, assign=True)
        # rename: .new = .old — treat the RHS dotted path as a source
        source_match = re.match(r"^\.?[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$", rhs)
        if source_match and _get_path_source(rhs):
            return _RenameOp(rhs, path)
        return _SetOp(path, _parse_scalar(rhs))

    # bare .field = handled above; unknown → treat as literal field set
    return _SetOp(stmt, None)


def _get_path_source(path: str) -> bool:
    """Return True if ``path`` looks like a source path (doesn't matter for parse)."""
    return bool(path)


class _RenameOp(_Op):
    """Rename a field: move the value from ``source_path`` to ``target_path``."""

    def __init__(self, source_path: str, target_path: str) -> None:
        self.source_path = source_path
        self.target_path = target_path

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        src = _split_path(self.source_path)
        dst = _split_path(self.target_path)
        if not src or not dst:
            return dict(payload)
        value = _get_path(payload, self.source_path)
        work = _DelOp(self.source_path).apply(payload)
        keys = dst
        node = work
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value
        return work


def _parse_filters(filters: list[str]) -> list[_Op]:
    """Parse a list of filter strings into an ordered list of operations."""
    ops: list[_Op] = []
    for expression in filters or []:
        # Split on pipes but not on |= (update-assign operator)
        # Use a simple state machine or replace first
        parts = []
        current = ""
        i = 0
        while i < len(expression):
            if expression[i] == "|" and i + 1 < len(expression) and expression[i + 1] == "=":
                current += "|="
                i += 2
            elif expression[i] == "|":
                parts.append(current)
                current = ""
                i += 1
            else:
                current += expression[i]
                i += 1
        parts.append(current)

        for stmt in parts:
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt == ".":
                continue
            ops.append(_parse_statement(stmt))
    return ops


class TransformationEngine:
    """Apply JQ-style filter transformations to JSON payloads.

    Parameters
    ----------
    filters : list[str]
        Ordered list of JQ-style filter expressions.
    """

    def __init__(self, filters: list[str]) -> None:
        self._filters = list(filters or [])
        self._ops: list[_Op] = _parse_filters(self._filters)

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply all filters to ``payload`` and return the transformed dict."""
        work: dict[str, Any] = dict(payload)
        for op in self._ops:
            result = op.apply(work)
            if isinstance(result, dict):
                work = result
        return work

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return transformation result without persisting (dry-run)."""
        return self.apply(payload)

    def add_field(self, path: str, value: Any) -> None:
        """Add/register a literal field to be set on every apply."""
        self._ops.append(_SetOp(path, value))

    def remove_field(self, path: str) -> None:
        """Register a field to be removed on every apply."""
        self._ops.append(_DelOp(path))

    def rename_field(self, old_path: str, new_path: str) -> None:
        """Register a field rename (``old_path`` → ``new_path``)."""
        self._ops.append(_RenameOp(old_path, new_path))

    def convert_type(self, path: str, target_type: str) -> None:
        """Register a type conversion for ``path`` (integer/string/float/bool)."""
        self._ops.append(_ConvertOp(path, target_type))


def preview_transformation(
    filters: list[str], payload: dict[str, Any]
) -> dict[str, Any]:
    """One-shot convenience: create an engine, apply the filters, return result.

    Args:
        filters: Ordered list of JQ-style filter expressions.
        payload: The payload to transform.

    Returns:
        The transformed payload as a dict.
    """
    return TransformationEngine(filters).apply(payload)
