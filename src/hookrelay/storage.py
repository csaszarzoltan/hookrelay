"""SQLite storage for webhook request persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


class Storage:
    """SQLite-backed storage for webhook requests."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS webhooks (
                request_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                method TEXT NOT NULL DEFAULT 'POST',
                path TEXT NOT NULL DEFAULT '/',
                headers TEXT NOT NULL DEFAULT '{}',
                body BLOB,
                query_params TEXT NOT NULL DEFAULT '{}',
                source_ip TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL,
                replayed INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_webhooks_channel ON webhooks(channel);
            CREATE INDEX IF NOT EXISTS idx_webhooks_method ON webhooks(method);
            CREATE INDEX IF NOT EXISTS idx_webhooks_received_at ON webhooks(received_at DESC);
            CREATE VIRTUAL TABLE IF NOT EXISTS webhooks_fts USING fts5(
                request_id UNINDEXED,
                channel,
                method,
                path,
                headers,
                body,
                content='webhooks',
                content_rowid='rowid'
            );
            CREATE TRIGGER IF NOT EXISTS webhooks_ai AFTER INSERT ON webhooks
            BEGIN
                INSERT INTO webhooks_fts(rowid, request_id, channel, method, path, headers, body)
                VALUES (new.rowid, new.request_id, new.channel, new.method, new.path, new.headers, coalesce(new.body, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS webhooks_ad AFTER DELETE ON webhooks
            BEGIN
                INSERT INTO webhooks_fts(webhooks_fts, rowid, request_id, channel, method, path, headers, body)
                VALUES ('delete', old.rowid, old.request_id, old.channel, old.method, old.path, old.headers, coalesce(old.body, ''));
            END;
            CREATE TRIGGER IF NOT EXISTS webhooks_au AFTER UPDATE ON webhooks
            BEGIN
                INSERT INTO webhooks_fts(webhooks_fts, rowid, request_id, channel, method, path, headers, body)
                VALUES ('delete', old.rowid, old.request_id, old.channel, old.method, old.path, old.headers, coalesce(old.body, ''));
                INSERT INTO webhooks_fts(rowid, request_id, channel, method, path, headers, body)
                VALUES (new.rowid, new.request_id, new.channel, new.method, new.path, new.headers, coalesce(new.body, ''));
            END;
            CREATE TABLE IF NOT EXISTS delivery_attempts (
                attempt_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                target_url TEXT,
                status TEXT NOT NULL,
                response_status INTEGER,
                duration_ms REAL,
                error TEXT,
                attempted_at TEXT NOT NULL,
                FOREIGN KEY(request_id) REFERENCES webhooks(request_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_request
                ON delivery_attempts(request_id, attempted_at DESC);
            CREATE TABLE IF NOT EXISTS request_views (
                view_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                filters TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def store_request(self, request: dict[str, Any]) -> str:
        """Store a webhook request and return its ID."""
        request_id = request.get("request_id", uuid4().hex)
        body = request.get("body")
        if isinstance(body, str):
            body = body.encode("utf-8")

        self._conn.execute(
            """INSERT INTO webhooks
               (request_id, channel, method, path, headers, body, query_params, source_ip, received_at, replayed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                request.get("channel", ""),
                request.get("method", "POST"),
                request.get("path", "/"),
                json.dumps(request.get("headers", {})),
                body,
                json.dumps(request.get("query_params", {})),
                request.get("source_ip", ""),
                request.get("received_at", ""),
                request.get("replayed", 0),
            ),
        )
        self._conn.commit()
        return request_id

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        # Parse JSON fields
        if isinstance(d.get("headers"), str):
            d["headers"] = json.loads(d["headers"])
        if isinstance(d.get("query_params"), str):
            d["query_params"] = json.loads(d["query_params"])
        return d

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Retrieve a stored request by ID."""
        row = self._conn.execute(
            "SELECT * FROM webhooks WHERE request_id = ?", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_requests(
        self,
        channel: str | None = None,
        limit: int = 20,
        offset: int = 0,
        method: str | None = None,
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        """List requests with optional filters, newest first."""
        query = "SELECT * FROM webhooks WHERE 1=1"
        params: list[Any] = []

        if channel is not None:
            query += " AND channel = ?"
            params.append(channel)
        if method is not None:
            query += " AND method = ?"
            params.append(method)
        if path is not None:
            query += " AND path LIKE ?"
            params.append(f"%{path}%")

        query += " ORDER BY received_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_request(self, request_id: str) -> bool:
        """Delete one request and all related diagnostic records."""
        self._init_validation_results_table()
        with self._conn:
            self._conn.execute(
                "DELETE FROM delivery_attempts WHERE request_id = ?", (request_id,)
            )
            self._conn.execute(
                "DELETE FROM validation_results WHERE request_id = ?", (request_id,)
            )
            cursor = self._conn.execute(
                "DELETE FROM webhooks WHERE request_id = ?", (request_id,)
            )
        return cursor.rowcount > 0

    def purge_requests_older_than(self, days: int) -> int:
        """Delete requests older than the provided positive retention period."""
        if days < 1:
            raise ValueError("days must be at least 1")
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT request_id FROM webhooks WHERE received_at < ?", (cutoff,)
        ).fetchall()
        for row in rows:
            self.delete_request(row["request_id"])
        return len(rows)

    def count_requests(self, channel: str | None = None) -> int:
        """Count stored requests."""
        if channel is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM webhooks WHERE channel = ?",
                (channel,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM webhooks").fetchone()
        return row["cnt"] if row else 0


    def store_delivery_attempt(
        self,
        request_id: str,
        channel: str,
        status: str,
        target_url: str | None = None,
        response_status: int | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> str:
        """Persist one local forwarding or replay outcome."""
        attempt_id = uuid4().hex
        attempted_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO delivery_attempts
               (attempt_id, request_id, channel, target_url, status,
                response_status, duration_ms, error, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attempt_id, request_id, channel, target_url, status,
                response_status, duration_ms, error, attempted_at,
            ),
        )
        self._conn.commit()
        return attempt_id

    def list_delivery_attempts(self, request_id: str) -> list[dict[str, Any]]:
        """Return newest-first delivery attempts for a request."""
        rows = self._conn.execute(
            """SELECT * FROM delivery_attempts
               WHERE request_id = ? ORDER BY attempted_at DESC""",
            (request_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def increment_replay_count(self, request_id: str) -> None:
        """Increment the replay counter for a request."""
        self._conn.execute(
            "UPDATE webhooks SET replayed = replayed + 1 WHERE request_id = ?",
            (request_id,),
        )
        self._conn.commit()

    def save_request_view(self, name: str, filters: dict[str, Any]) -> str:
        """Save a named request-search configuration."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("view name must not be empty")
        existing = self._conn.execute(
            "SELECT view_id FROM request_views WHERE name = ? COLLATE NOCASE",
            (cleaned_name,),
        ).fetchone()
        if existing:
            raise ValueError(f"request view '{cleaned_name}' already exists")
        allowed = {"q", "channel", "method", "path", "validation_status", "limit"}
        cleaned = {
            key: value for key, value in filters.items()
            if key in allowed and value not in (None, "")
        }
        view_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO request_views
               (view_id, name, filters, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (view_id, cleaned_name, json.dumps(cleaned), now, now),
        )
        self._conn.commit()
        return view_id

    def get_request_view(self, view_id: str) -> dict[str, Any] | None:
        """Load one saved request view."""
        row = self._conn.execute(
            "SELECT * FROM request_views WHERE view_id = ?", (view_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["filters"] = json.loads(result["filters"])
        return result

    def list_request_views(self) -> list[dict[str, Any]]:
        """List saved request views by name."""
        rows = self._conn.execute(
            "SELECT * FROM request_views ORDER BY name COLLATE NOCASE"
        ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["filters"] = json.loads(item["filters"])
            results.append(item)
        return results

    def delete_request_view(self, view_id: str) -> bool:
        """Delete one saved request view."""
        cursor = self._conn.execute(
            "DELETE FROM request_views WHERE view_id = ?", (view_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def search_requests(
        self,
        query: str,
        channel: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search stored requests by full-text query."""
        fts_query = ' OR '.join(
            f'"{word}"' if word else word for word in query.split()
        ) or query
        sql = (
            "SELECT w.* FROM webhooks w "
            "JOIN webhooks_fts fts ON w.rowid = fts.rowid "
            "WHERE webhooks_fts MATCH ?"
        )
        params: list[Any] = [fts_query]
        if channel is not None:
            sql += " AND w.channel = ?"
            params.append(channel)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ============================================================
    # Schema table management
    # ============================================================

    def _init_schema_table(self) -> None:
        """Create the schemas table if it doesn't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS schemas (
                schema_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL DEFAULT '1.0.0',
                channel TEXT NOT NULL,
                schema_definition TEXT NOT NULL,
                draft_version TEXT NOT NULL DEFAULT '2020-12',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                severity_level TEXT NOT NULL DEFAULT 'error'
            );
            CREATE INDEX IF NOT EXISTS idx_schemas_channel ON schemas(channel);
        """)
        self._conn.commit()

    def _init_validation_results_table(self) -> None:
        """Create the validation_results table if it doesn't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS validation_results (
                result_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                schema_id TEXT NOT NULL,
                valid INTEGER NOT NULL DEFAULT 0,
                errors TEXT,
                warnings TEXT,
                infos TEXT,
                validated_at TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'error'
            );
            CREATE INDEX IF NOT EXISTS idx_validation_request ON validation_results(request_id);
            CREATE INDEX IF NOT EXISTS idx_validation_schema ON validation_results(schema_id);
            CREATE TRIGGER IF NOT EXISTS tr_validation_results_cascade_ad
            AFTER DELETE ON webhooks
            BEGIN
                DELETE FROM validation_results WHERE request_id = old.request_id;
            END;
        """)
        self._conn.commit()

    # ============================================================
    # v0.4.0: Filter sets, routing rules, and filter history
    # ============================================================

    def _init_filter_tables(self) -> None:
        """Create filter_sets, routing_rules, and filter_history tables."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS filter_sets (
                filter_set_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel TEXT NOT NULL,
                filter_expression TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_filter_sets_channel ON filter_sets(channel);

            CREATE TABLE IF NOT EXISTS routing_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 100,
                condition TEXT,
                target_endpoint TEXT,
                max_forward_count INTEGER,
                fallback INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routing_rules_channel ON routing_rules(channel);

            CREATE TABLE IF NOT EXISTS filter_history (
                history_id TEXT PRIMARY KEY,
                filter_set_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                matched INTEGER NOT NULL DEFAULT 0,
                matched_criteria TEXT,
                executed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_filter_history_set ON filter_history(filter_set_id);
            CREATE INDEX IF NOT EXISTS idx_filter_history_request ON filter_history(request_id);
        """)
        self._conn.commit()

    def save_filter_set(
        self, name: str, channel: str, filter_expression: str
    ) -> str:
        """Save a named filter set and return its ID."""
        self._init_filter_tables()
        filter_set_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO filter_sets
               (filter_set_id, name, channel, filter_expression, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filter_set_id, name, channel, filter_expression, now, now),
        )
        self._conn.commit()
        return filter_set_id

    def load_filter_set(self, filter_set_id: str) -> dict[str, Any] | None:
        """Load a filter set by ID."""
        self._init_filter_tables()
        row = self._conn.execute(
            "SELECT * FROM filter_sets WHERE filter_set_id = ?",
            (filter_set_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_filter_sets(self, channel: str | None = None) -> list[dict[str, Any]]:
        """List filter sets, optionally filtered by channel."""
        self._init_filter_tables()
        if channel is not None:
            rows = self._conn.execute(
                "SELECT * FROM filter_sets WHERE channel = ? ORDER BY created_at DESC",
                (channel,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM filter_sets ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_filter_set(self, filter_set_id: str) -> bool:
        """Delete a filter set. Returns True if deleted."""
        self._init_filter_tables()
        cur = self._conn.execute(
            "DELETE FROM filter_sets WHERE filter_set_id = ?",
            (filter_set_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def save_routing_rule(
        self,
        name: str,
        channel: str,
        condition: str | None = None,
        target_endpoint: str | None = None,
        priority: int = 100,
        enabled: bool = True,
        max_forward_count: int | None = None,
        fallback: bool = False,
    ) -> str:
        """Save a routing rule and return its rule_id."""
        self._init_filter_tables()
        rule_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO routing_rules
               (rule_id, name, channel, enabled, priority, condition,
                target_endpoint, max_forward_count, fallback, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rule_id, name, channel,
                1 if enabled else 0,
                priority, condition, target_endpoint,
                max_forward_count, 1 if fallback else 0,
                now, now,
            ),
        )
        self._conn.commit()
        return rule_id

    def list_routing_rules(
        self, channel: str | None = None
    ) -> list[dict[str, Any]]:
        """List routing rules, optionally filtered by channel."""
        self._init_filter_tables()
        if channel is not None:
            rows = self._conn.execute(
                "SELECT * FROM routing_rules WHERE channel = ? ORDER BY priority ASC",
                (channel,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM routing_rules ORDER BY priority ASC"
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d["enabled"])
            d["fallback"] = bool(d["fallback"])
            result.append(d)
        return result

    def update_routing_rule(
        self, rule_id: str, updates: dict[str, Any]
    ) -> bool:
        """Update a routing rule's fields. Returns True if updated."""
        self._init_filter_tables()
        if not updates:
            return False
        # Map boolean fields to integers for SQLite
        field_map: dict[str, Any] = {}
        for k, v in updates.items():
            if k in ("enabled", "fallback"):
                field_map[k] = 1 if v else 0
            else:
                field_map[k] = v
        field_map["updated_at"] = datetime.now(UTC).isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in field_map)
        values = list(field_map.values()) + [rule_id]
        cur = self._conn.execute(
            f"UPDATE routing_rules SET {set_clause} WHERE rule_id = ?",
            values,
        )
        self._conn.commit()
        return cur.rowcount > 0

    def delete_routing_rule(self, rule_id: str) -> bool:
        """Delete a routing rule. Returns True if deleted."""
        self._init_filter_tables()
        cur = self._conn.execute(
            "DELETE FROM routing_rules WHERE rule_id = ?",
            (rule_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def reorder_routing_rules(self, ordered_ids: list[str]) -> bool:
        """Reorder routing rules by priority based on ordered_ids."""
        self._init_filter_tables()
        now = datetime.now(UTC).isoformat()
        updated = 0
        for i, rid in enumerate(ordered_ids):
            cur = self._conn.execute(
                "UPDATE routing_rules SET priority = ?, updated_at = ? WHERE rule_id = ?",
                (i, now, rid),
            )
            updated += cur.rowcount
        self._conn.commit()
        return updated > 0

    def log_filter_execution(
        self,
        filter_set_id: str,
        request_id: str,
        matched: bool,
        matched_criteria: str | None = None,
    ) -> str:
        """Log a filter execution result. Returns history_id."""
        self._init_filter_tables()
        history_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO filter_history
               (history_id, filter_set_id, request_id, matched, matched_criteria, executed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (history_id, filter_set_id, request_id, 1 if matched else 0, matched_criteria, now),
        )
        self._conn.commit()
        return history_id

    def query_filter_history(
        self,
        filter_set_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query filter execution history."""
        self._init_filter_tables()
        if filter_set_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM filter_history WHERE filter_set_id = ? ORDER BY executed_at DESC LIMIT ? OFFSET ?",
                (filter_set_id, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM filter_history ORDER BY executed_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["matched"] = bool(d["matched"])
            result.append(d)
        return result

    def store_validation_result(
        self,
        request_id: str,
        schema_id: str,
        result: dict,
    ) -> str:
        """Store a validation result.

        Args:
            request_id: The webhook request ID.
            schema_id: The schema ID.
            result: Validation result dict with valid, errors, warnings, infos.

        Returns:
            The result_id.
        """
        import json as json_mod
        from datetime import UTC, datetime
        from uuid import uuid4

        result_id = uuid4().hex
        now = datetime.now(tz=UTC).isoformat()

        self._init_validation_results_table()
        self._conn.execute(
            """INSERT INTO validation_results
               (result_id, request_id, schema_id, valid, errors, warnings, infos, validated_at, severity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                result_id,
                request_id,
                schema_id,
                1 if result.get("valid") else 0,
                json_mod.dumps(result.get("errors", [])),
                json_mod.dumps(result.get("warnings", [])),
                json_mod.dumps(result.get("infos", [])),
                now,
                "error",
            ),
        )
        self._conn.commit()
        return result_id

    def get_validation_result(self, request_id: str) -> dict | None:
        """Get validation result for a request.

        Args:
            request_id: The webhook request ID.

        Returns:
            The validation result dict, or None if not found.
        """
        self._init_validation_results_table()
        import json as json_mod
        row = self._conn.execute(
            "SELECT * FROM validation_results WHERE request_id = ? ORDER BY validated_at DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        for field in ("errors", "warnings", "infos"):
            if isinstance(d.get(field), str):
                d[field] = json_mod.loads(d[field])
        d["valid"] = bool(d["valid"])
        return d

    def get_validation_results_for_request(self, request_id: str) -> list[dict]:
        """Get all validation results for a request.

        Args:
            request_id: The webhook request ID.

        Returns:
            List of validation result dicts.
        """
        self._init_validation_results_table()
        import json as json_mod
        rows = self._conn.execute(
            "SELECT * FROM validation_results WHERE request_id = ? ORDER BY validated_at DESC",
            (request_id,),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for field in ("errors", "warnings", "infos"):
                if isinstance(d.get(field), str):
                    d[field] = json_mod.loads(d[field])
            d["valid"] = bool(d["valid"])
            results.append(d)
        return results
