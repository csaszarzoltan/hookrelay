"""Canonical request-query model and opaque cursor helpers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, replace

_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
_ALLOWED_VALIDATION = frozenset({"valid", "invalid", "not_checked"})
_ALLOWED_DELIVERY = frozenset({"delivered", "target_error", "transport_error", "pending"})


@dataclass(frozen=True, slots=True)
class RequestQuery:
    """Versioned, validated query definition used by APIs and saved views."""

    schema_version: int = 1
    q: str | None = None
    channel: str | None = None
    methods: list[str] | None = None
    path: str | None = None
    validation_status: str | None = None
    delivery_status: str | None = None
    received_from: str | None = None
    received_to: str | None = None
    replayed: bool | None = None
    sort: str = "received_at_desc"
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported query schema_version")
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if self.sort != "received_at_desc":
            raise ValueError("only received_at_desc sorting is supported")
        normalized = [method.upper() for method in (self.methods or [])]
        if any(method not in _ALLOWED_METHODS for method in normalized):
            raise ValueError("unsupported HTTP method")
        object.__setattr__(self, "methods", normalized or None)
        if self.validation_status and self.validation_status not in _ALLOWED_VALIDATION:
            raise ValueError("unsupported validation_status")
        if self.delivery_status and self.delivery_status not in _ALLOWED_DELIVERY:
            raise ValueError("unsupported delivery_status")
        if self.cursor:
            decode_cursor(self.cursor)

    def with_cursor(self, cursor: str | None) -> RequestQuery:
        return replace(self, cursor=cursor)

    def to_dict(self) -> dict:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if getattr(self, field) is not None
        }


def encode_cursor(received_at: str, request_id: str) -> str:
    payload = json.dumps([received_at, request_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return str(value[0]), str(value[1])
    except Exception as exc:
        raise ValueError("invalid request cursor") from exc
