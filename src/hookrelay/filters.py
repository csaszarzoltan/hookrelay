"""Conditional forwarding and request filtering."""

from __future__ import annotations

import fnmatch
import re
from typing import Any


class RequestFilter:
    """Filter webhook requests by multiple criteria."""

    def __init__(self) -> None:
        self._filters: list[dict[str, Any]] = []

    def by_method(self, method: str) -> RequestFilter:
        """Filter by HTTP method (POST, PUT, PATCH, etc.)."""
        self._filters.append({"type": "method", "value": method.upper()})
        return self

    def by_path(self, pattern: str) -> RequestFilter:
        """Filter by URL path pattern (plain string or regex)."""
        self._filters.append({"type": "path", "value": pattern})
        return self

    def by_source(self, source_ip: str) -> RequestFilter:
        """Filter by source IP address."""
        self._filters.append({"type": "source", "value": source_ip})
        return self

    def by_status_code(self, code: int) -> RequestFilter:
        """Filter by forwarded response status code."""
        self._filters.append({"type": "status_code", "value": code})
        return self

    def by_header(self, name: str, value: str) -> RequestFilter:
        """Filter by the presence of a header with a specific value."""
        self._filters.append(
            {"type": "header", "name": name, "value": value}
        )
        return self

    def apply(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply all set filters and return matching requests."""
        results = list(requests)
        for f in self._filters:
            results = [r for r in results if self._matches(r, f)]
        return results

    def _matches(self, request: dict[str, Any], f: dict[str, Any]) -> bool:
        if f["type"] == "method":
            return request.get("method", "").upper() == f["value"].upper()
        elif f["type"] == "path":
            pattern = f["value"]
            req_path = request.get("path", "")
            # Try regex first, fall back to glob
            try:
                if re.match(pattern, req_path):
                    return True
            except re.error:
                pass
            return fnmatch.fnmatch(req_path, pattern)
        elif f["type"] == "source":
            return request.get("source_ip", "") == f["value"]
        elif f["type"] == "status_code":
            return request.get("status_code") == f["value"]
        elif f["type"] == "header":
            headers = request.get("headers", {})
            return headers.get(f["name"]) == f["value"]
        return False

    def reset(self) -> RequestFilter:
        """Clear all filter criteria."""
        self._filters.clear()
        return self


def build_filter(
    method: str | None = None,
    path: str | None = None,
    source: str | None = None,
    status_code: int | None = None,
) -> RequestFilter:
    """Convenience: build a RequestFilter from optional criteria."""
    f = RequestFilter()
    if method is not None:
        f.by_method(method)
    if path is not None:
        f.by_path(path)
    if source is not None:
        f.by_source(source)
    if status_code is not None:
        f.by_status_code(status_code)
    return f
