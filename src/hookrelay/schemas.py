"""Schema storage — CRUD for JSON Schema definitions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.validation import SUPPORTED_DRAFTS

VALID_SEVERITY_LEVELS = frozenset({"error", "warning", "info"})


class SchemaStore:
    """SQLite-backed store for JSON Schema definitions."""

    def __init__(self, storage: Any) -> None:
        """Initialize SchemaStore with a Storage instance.

        Args:
            storage: A hookrelay.storage.Storage instance for DB access.
        """
        self._storage = storage
        self._conn = storage._conn
        self._init_table()

    def _init_table(self) -> None:
        """Ensure the schemas table exists."""
        self._storage._init_schema_table()

    def _validate_inputs(
        self,
        name: str,
        channel: str,
        schema_definition: dict[str, Any],
        draft_version: str,
        severity_level: str,
    ) -> None:
        """Validate schema creation inputs."""
        if not name or not name.strip():
            raise ValueError("name must not be empty")
        if not channel or not channel.strip():
            raise ValueError("channel must not be empty")
        if not isinstance(schema_definition, dict):
            raise TypeError("schema_definition must be a dict")
        if draft_version not in SUPPORTED_DRAFTS:
            raise ValueError(
                f"draft version '{draft_version}' not supported. "
                f"Supported: {', '.join(sorted(SUPPORTED_DRAFTS))}"
            )
        if severity_level not in VALID_SEVERITY_LEVELS:
            raise ValueError(
                f"severity_level '{severity_level}' not valid. "
                f"Must be one of: {', '.join(sorted(VALID_SEVERITY_LEVELS))}"
            )

    def create_schema(
        self,
        name: str,
        channel: str,
        schema_definition: dict[str, Any],
        draft_version: str = "2020-12",
        enabled: bool = True,
        severity_level: str = "error",
        version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a new JSON Schema.

        Args:
            name: Human-readable schema name.
            channel: Webhook channel this schema applies to.
            schema_definition: The JSON Schema definition (as a Python dict).
            draft_version: JSON Schema draft version (e.g. '2020-12', '2019-09', '07').
            enabled: Whether this schema is active for auto-validation.
            severity_level: Default severity ('error', 'warning', 'info').
            version: Schema version string.
            metadata: Optional user-defined tags/labels.

        Returns:
            The created schema record as a dict.
        """
        self._validate_inputs(name, channel, schema_definition, draft_version, severity_level)

        schema_id = uuid4().hex
        now = datetime.now(tz=UTC).isoformat()

        self._conn.execute(
            """INSERT INTO schemas
               (schema_id, name, version, channel, schema_definition, draft_version,
                enabled, created_at, updated_at, metadata, severity_level)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                schema_id,
                name.strip(),
                version,
                channel.strip(),
                json.dumps(schema_definition),
                draft_version,
                1 if enabled else 0,
                now,
                now,
                json.dumps(metadata or {}),
                severity_level,
            ),
        )
        self._conn.commit()
        return self.get_schema(schema_id)  # type: ignore[return-value]

    def get_schema(self, schema_id: str) -> dict[str, Any] | None:
        """Retrieve a schema by its ID.

        Args:
            schema_id: The schema's unique ID.

        Returns:
            The schema record or None if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM schemas WHERE schema_id = ?",
            (schema_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_schemas(
        self,
        channel: str | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List registered schemas, optionally filtered by channel.

        Args:
            channel: Optional channel filter.
            enabled_only: If True (default), only return enabled schemas.

        Returns:
            List of schema records.
        """
        query = "SELECT * FROM schemas WHERE 1=1"
        params: list[Any] = []

        if channel is not None:
            query += " AND channel = ?"
            params.append(channel)
        if enabled_only:
            query += " AND enabled = 1"

        query += " ORDER BY created_at DESC"

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_schema(
        self,
        schema_id: str,
        **updates: Any,
    ) -> dict[str, Any] | None:
        """Update a schema's fields.

        Args:
            schema_id: The schema's unique ID.
            **updates: Fields to update (name, channel, schema_definition, etc.).

        Returns:
            The updated schema record, or None if not found.
        """
        # Check schema exists
        existing = self.get_schema(schema_id)
        if existing is None:
            return None

        # Build update query for allowed fields
        allowed_fields = {
            "name", "channel", "schema_definition", "draft_version",
            "enabled", "severity_level", "version", "metadata",
        }
        set_clauses: list[str] = []
        params: list[Any] = []

        for field, value in updates.items():
            if field not in allowed_fields:
                continue
            if field == "schema_definition":
                if not isinstance(value, dict):
                    raise TypeError("schema_definition must be a dict")
                set_clauses.append("schema_definition = ?")
                params.append(json.dumps(value))
            elif field == "metadata":
                set_clauses.append("metadata = ?")
                params.append(json.dumps(value or {}))
            elif field == "enabled":
                set_clauses.append("enabled = ?")
                params.append(1 if value else 0)
            else:
                set_clauses.append(f"{field} = ?")
                params.append(value)

        if not set_clauses:
            return existing

        now = datetime.now(tz=UTC).isoformat()
        set_clauses.append("updated_at = ?")
        params.append(now)
        params.append(schema_id)

        # Build the SET clause from allowlisted fragments only; values are
        # always passed as ? parameters, never interpolated into SQL.
        self._conn.execute(
            "UPDATE schemas SET " + ", ".join(set_clauses) + " WHERE schema_id = ?",
            params,
        )
        self._conn.commit()
        return self.get_schema(schema_id)

    def delete_schema(self, schema_id: str) -> bool:
        """Delete a schema by ID.

        Args:
            schema_id: The schema's unique ID.

        Returns:
            True if deleted, False if not found.
        """
        cursor = self._conn.execute(
            "DELETE FROM schemas WHERE schema_id = ?",
            (schema_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _row_to_dict(self, row: Any) -> dict[str, Any]:
        """Convert a SQLite row to a dict with proper types."""
        d = dict(row)
        # Parse JSON fields
        for field in ("schema_definition", "metadata"):
            if isinstance(d.get(field), str):
                d[field] = json.loads(d[field])
        # Convert integer to bool for enabled
        if "enabled" in d:
            d["enabled"] = bool(d["enabled"])
        return d
