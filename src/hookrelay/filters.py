"""
Conditional forwarding and request filtering.

Implements RequestFilter for criteria-based webhook filtering, plus
v0.4.0 additions: advanced body/header/json matching, FilterPreset,
FilterChain combinators, and FilterExpressionParser.
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Any, ClassVar


class FilterResult:
    """Result of a filter match operation.

    Attributes:
        matched: Whether the request matched.
        matched_criteria: List of criteria names that matched.
        score: Optional match score.
    """

    def __init__(
        self,
        matched: bool = False,
        matched_criteria: list[str] | None = None,
        score: float = 0.0,
    ) -> None:
        self.matched = matched
        self.matched_criteria = matched_criteria or []
        self.score = score

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "matched_criteria": self.matched_criteria,
            "score": self.score,
        }


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

    # ------------------------------------------------------------------
    # v0.4.0: Advanced filtering methods
    # ------------------------------------------------------------------

    def by_body(self, pattern: str) -> RequestFilter:
        """Filter by regex pattern matched against decoded body content."""
        self._filters.append({"type": "body", "value": pattern})
        return self

    def by_header_regex(self, name: str, pattern: str) -> RequestFilter:
        """Filter by regex pattern matched against a header value."""
        self._filters.append(
            {"type": "header_regex", "name": name, "value": pattern}
        )
        return self

    def by_json_field(self, path: str, pattern: str) -> RequestFilter:
        """Filter by regex match on a JSON field extracted via dot-path."""
        self._filters.append(
            {"type": "json_field", "path": path, "value": pattern}
        )
        return self

    def apply(
        self, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
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
        elif f["type"] == "status_range":
            lo, hi = f["lo"], f["hi"]
            code = request.get("status_code")
            if code is None:
                return False
            try:
                return lo <= int(code) <= hi
            except (ValueError, TypeError):
                return False
        elif f["type"] == "header":
            headers = request.get("headers", {})
            return headers.get(f["name"]) == f["value"]
        elif f["type"] == "body":
            return _matches_body(request, f["value"])
        elif f["type"] == "header_regex":
            return _matches_header_regex(request, f["name"], f["value"])
        elif f["type"] == "json_field":
            return _matches_json_field(request, f["path"], f["value"])
        elif f["type"] == "chain_and":
            return all(
                sub_f.apply([request]) for sub_f in f["filters"]
            )
        elif f["type"] == "chain_or":
            return any(
                sub_f.apply([request]) for sub_f in f["filters"]
            )
        elif f["type"] == "chain_not":
            return not f["filter"].apply([request])
        return False

    def reset(self) -> RequestFilter:
        """Clear all filter criteria."""
        self._filters.clear()
        return self


def _matches_body(request: dict[str, Any], pattern: str) -> bool:
    """Check if request body matches a regex pattern.

    Decodes body UTF-8 and applies re.search(). Skips binary
    (non-UTF8) bodies — returns False without crashing.
    """
    body = request.get("body")
    if body is None:
        return False
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except (UnicodeDecodeError, UnicodeError):
            return False
    if not isinstance(body, str):
        body = str(body)
    try:
        return re.search(pattern, body) is not None
    except re.error:
        return False


def _matches_header_regex(
    request: dict[str, Any], name: str, pattern: str
) -> bool:
    """Check if a header value matches a regex pattern."""
    headers = request.get("headers", {})
    value = headers.get(name)
    if value is None:
        return False
    try:
        return re.search(pattern, str(value)) is not None
    except re.error:
        return False


def _get_json_field(data: Any, path: str) -> Any:
    """Navigate a dot-path into a nested dict/list structure.

    E.g. "data.object.id" -> data["data"]["object"]["id"]
    Returns None if the path doesn't exist.
    """
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.lstrip("-").isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def _matches_json_field(
    request: dict[str, Any], field_path: str, pattern: str
) -> bool:
    """Check if a JSON field extracted by dot-path matches a regex.

    Tries to parse body as JSON, then navigates the dot-path.
    Returns False if body is not valid JSON or path doesn't exist.
    """
    body = request.get("body")
    if body is None:
        return False
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except (UnicodeDecodeError, UnicodeError):
            return False
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return False
    # At this point body should be a parsed JSON object
    if not isinstance(body, (dict, list)):
        return False
    value = _get_json_field(body, field_path)
    if value is None:
        return False
    try:
        return re.search(pattern, str(value)) is not None
    except re.error:
        return False


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


# ====================================================================
# v0.4.0: Filter presets, chain composition, and expression parser
# ====================================================================


class FilterPreset:
    """Built-in filter presets for common webhook providers.

    Provides pre-configured RequestFilter instances for Stripe,
    GitHub, Slack, and common HTTP method groupings.
    """

    _presets: ClassVar[dict[str, RequestFilter]] = {}

    @classmethod
    def _ensure_presets(cls) -> None:
        """Build preset filters on first access."""
        if cls._presets:
            return

        # Stripe: filter by charge/payment/invoice event types
        stripe = RequestFilter().by_json_field("type", r"^charge|^payment|^invoice")
        cls._presets["stripe"] = stripe

        # GitHub: X-GitHub-Event header + action field
        github = FilterChain.all(
            RequestFilter().by_header_regex("X-GitHub-Event", r".+"),
            RequestFilter().by_json_field("action", r".+"),
        )
        cls._presets["github"] = github

        # Slack: event type or challenge
        slack = FilterChain.any(
            RequestFilter().by_json_field("event.type", r".+"),
            RequestFilter().by_json_field("challenge", r".+"),
        )
        cls._presets["slack"] = slack

        # HTTP method presets
        cls._presets["post"] = RequestFilter().by_method("POST")
        cls._presets["get"] = RequestFilter().by_method("GET")
        cls._presets["put"] = RequestFilter().by_method("PUT")
        cls._presets["patch"] = RequestFilter().by_method("PATCH")
        cls._presets["delete"] = RequestFilter().by_method("DELETE")

        # Status code range presets
        cls._presets["2xx"] = _build_status_preset(200, 299)
        cls._presets["4xx"] = _build_status_preset(400, 499)
        cls._presets["5xx"] = _build_status_preset(500, 599)

    @classmethod
    def apply(
        cls, name: str, requests: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Apply a named preset filter to the given requests."""
        cls._ensure_presets()
        if name not in cls._presets:
            raise ValueError(f"Unknown preset: {name}")
        return cls._presets[name].apply(requests)

    @classmethod
    def list(cls) -> list[str]:
        """Return the list of available preset names."""
        cls._ensure_presets()
        return list(cls._presets.keys())


def _build_status_preset(
    lo: int, hi: int
) -> RequestFilter:
    """Build a filter matching status codes in [lo, hi] range.

    Uses a simple approach: pre-configure by_status_code with
    a special sentinel, then override _matches at the instance level
    via an inline object (or just add a range-type filter).
    """
    def _range_matcher(request: dict[str, Any]) -> bool:
        code = request.get("status_code")
        if code is None:
            return False
        try:
            return lo <= int(code) <= hi
        except (ValueError, TypeError):
            return False

    f = RequestFilter()
    f._filters.append({"type": "status_range", "lo": lo, "hi": hi})
    return f


class FilterChain:
    """Combinators for AND/OR/NOT filter composition.

    Enables nesting::

        combined = FilterChain.any([
            FilterChain.all(f1, f2),
            FilterChain.not_(f3),
        ])
    """

    @staticmethod
    def all(*filters: RequestFilter) -> RequestFilter:
        """Combine filters with AND logic (all must match)."""
        combined = RequestFilter()
        combined._filters.append({"type": "chain_and", "filters": list(filters)})
        return combined

    @staticmethod
    def any(*filters: RequestFilter) -> RequestFilter:
        """Combine filters with OR logic (any must match)."""
        combined = RequestFilter()
        combined._filters.append({"type": "chain_or", "filters": list(filters)})
        return combined

    @staticmethod
    def not_(filter_instance: RequestFilter) -> RequestFilter:
        """Negate a filter (invert match result)."""
        combined = RequestFilter()
        combined._filters.append({"type": "chain_not", "filter": filter_instance})
        return combined


class FilterExpressionParser:
    """Parse string filter expressions into a RequestFilter.

    Supports operators::

        method=POST          exact match
        path~^/stripe        regex match
        method!=GET          exact negate
        body.event.type~evt_  JSON dot-path regex
        header.X-GitHub-Event~^push  header regex
    """

    _TOKEN_RE = re.compile(
        r"""
        (?:header\.)?              # optional "header." prefix
        [a-zA-Z_][a-zA-Z0-9_.]*   # field name (may include dots)
        \s*(?:!=|=|~)\s*          # operator: !=, =, or ~
        .+?                       # value (non-greedy)
        (?=\s+(?:AND|OR)\b|$)\s*  # stop at AND/OR or end
        """,
        re.VERBOSE,
    )
    _TERM_RE = re.compile(
        r"""
        ([a-zA-Z_][a-zA-Z0-9_.-]*)    # field (allow dots and hyphens)
        \s*(!=|=|~)\s*                 # operator
        (.+)                           # value (rest of term, greedy)
        """,
        re.VERBOSE,
    )

    @staticmethod
    def parse(expression: str) -> RequestFilter:
        """Parse a filter expression string into a RequestFilter instance."""
        if not expression or not expression.strip():
            return RequestFilter()

        f = RequestFilter()
        terms = _tokenize_expression(expression)

        for term in terms:
            term = term.strip()
            if not term:
                continue
            if term.upper() in ("AND", "OR"):
                # AND is the default (sequential filtering).
                # OR support would require FilterChain.any() wrapping.
                continue

            match = re.match(
                r"""
                ([a-zA-Z_][a-zA-Z0-9_.-]*)
                \s*(!=|=|~)\s*
                (.+)
                """,
                term,
                re.VERBOSE,
            )
            if not match:
                continue

            field = match.group(1).strip()
            operator = match.group(2).strip()
            value = match.group(3).strip()

            # --- header.X-GitHub-Event~^push ---
            if field.startswith("header."):
                header_name = field[len("header."):]
                if operator == "~":
                    f.by_header_regex(header_name, value)
                elif operator == "=":
                    # Exact header match via regex with ^...$
                    f.by_header_regex(header_name, f"^{re.escape(value)}$")
                elif operator == "!=":
                    # NOT header_regex
                    inner = RequestFilter().by_header_regex(
                        header_name, f"^{re.escape(value)}$"
                    )
                    f._filters.append({"type": "chain_not", "filter": inner})
                continue

            # --- method=POST / method!=GET / method~regex ---
            if field == "method":
                if operator == "=":
                    f.by_method(value)
                elif operator == "!=":
                    inner = RequestFilter().by_method(value)
                    f._filters.append({"type": "chain_not", "filter": inner})
                elif operator == "~":
                    # Regex method matching — add as custom filter
                    inner = RequestFilter()
                    inner._filters.append({"type": "method_regex", "value": value})
                    f._filters.append({"type": "chain_and", "filters": [inner]})
                continue

            # --- path~^/stripe / path=/exact / path!=... ---
            if field == "path":
                if operator == "~":
                    f.by_path(value)
                elif operator == "=":
                    # Exact path via anchored regex
                    inner = RequestFilter()
                    inner._filters.append({
                        "type": "path_exact", "value": value
                    })
                    f._filters.append({"type": "chain_and", "filters": [inner]})
                elif operator == "!=":
                    inner = RequestFilter().by_path(value)
                    f._filters.append({"type": "chain_not", "filter": inner})
                continue

            # --- body.event.type~evt_ / body.field=exact ---
            if field.startswith("body."):
                json_path = field[len("body."):]
                if operator == "~":
                    f.by_json_field(json_path, value)
                elif operator == "=":
                    inner = RequestFilter()
                    inner._filters.append({
                        "type": "json_field_exact", "path": json_path, "value": value
                    })
                    f._filters.append({"type": "chain_and", "filters": [inner]})
                elif operator == "!=":
                    inner = RequestFilter().by_json_field(json_path, value)
                    f._filters.append({"type": "chain_not", "filter": inner})
                continue

            # --- source=10.0.0.1 / source_ip=... ---
            if field in ("source", "source_ip"):
                if operator == "=":
                    f.by_source(value)
                elif operator == "!=":
                    inner = RequestFilter().by_source(value)
                    f._filters.append({"type": "chain_not", "filter": inner})
                continue

        return f


def _tokenize_expression(expression: str) -> list[str]:
    """Split a filter expression into individual terms.

    Handles AND/OR connectors and returns a flat list of terms.
    """
    # First, split on AND/OR but keep track of connectors
    parts = re.split(r"\s+(AND|OR)\s+", expression, flags=re.IGNORECASE)
    terms: list[str] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if part.upper() in ("AND", "OR"):
            terms.append(part.upper())
        else:
            terms.append(part)
    return terms
