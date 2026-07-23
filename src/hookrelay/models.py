"""Data models for webhook requests and filtering."""

from __future__ import annotations

import datetime as _dt
from typing import Any


class WebhookRequest:
    """Represents a received webhook request."""

    def __init__(
        self,
        request_id: str,
        channel: str,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes | None,
        query_params: dict[str, str] | None,
        source_ip: str,
        received_at: _dt.datetime | None = None,
        replayed: int = 0,
    ) -> None:
        self.request_id = request_id
        self.channel = channel
        self.method = method
        self.path = path
        self.headers = headers
        self.body = body
        self.query_params = query_params or {}
        self.source_ip = source_ip
        self.received_at = received_at or _dt.datetime.now(tz=_dt.UTC)
        self.replayed = replayed

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (for JSON/WS transport)."""
        return {
            "request_id": self.request_id,
            "channel": self.channel,
            "method": self.method,
            "path": self.path,
            "headers": self.headers,
            "body": self.body.decode("utf-8", errors="replace") if self.body is not None else None,
            "body_base64": self.body.hex() if self.body is not None else None,
            "query_params": self.query_params,
            "source_ip": self.source_ip,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "replayed": self.replayed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebhookRequest:
        """Deserialize from dictionary."""
        body: bytes | None = None
        if data.get("body") is not None:
            body = data["body"].encode("utf-8")
        elif data.get("body_base64") is not None:
            body = bytes.fromhex(data["body_base64"])

        received_at = None
        if data.get("received_at"):
            received_at = _dt.datetime.fromisoformat(data["received_at"])

        return cls(
            request_id=data.get("request_id", ""),
            channel=data.get("channel", ""),
            method=data.get("method", "POST"),
            path=data.get("path", "/"),
            headers=data.get("headers", {}),
            body=body,
            query_params=data.get("query_params", {}),
            source_ip=data.get("source_ip", ""),
            received_at=received_at,
            replayed=data.get("replayed", 0),
        )


class FilterCriteria:
    """Filtering criteria for request queries."""

    def __init__(
        self,
        method: str | None = None,
        path: str | None = None,
        source: str | None = None,
        status_code: int | None = None,
        channel: str | None = None,
    ) -> None:
        self.method = method
        self.path = path
        self.source = source
        self.status_code = status_code
        self.channel = channel

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.method is not None:
            d["method"] = self.method
        if self.path is not None:
            d["path"] = self.path
        if self.source is not None:
            d["source"] = self.source
        if self.status_code is not None:
            d["status_code"] = self.status_code
        if self.channel is not None:
            d["channel"] = self.channel
        return d
