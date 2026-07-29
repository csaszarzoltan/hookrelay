"""SQLite storage for webhook request persistence."""

from __future__ import annotations

import json
import sqlite3
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

    def increment_replay_count(self, request_id: str) -> None:
        """Increment the replay counter for a request."""
        self._conn.execute(
            "UPDATE webhooks SET replayed = replayed + 1 WHERE request_id = ?",
            (request_id,),
        )
        self._conn.commit()

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
