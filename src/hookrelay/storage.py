"""SQLite storage for webhook request persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from hookrelay.migrations import run_migrations
from hookrelay.query import RequestQuery, decode_cursor, encode_cursor


class Storage:
    """SQLite-backed storage for webhook requests."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        run_migrations(self._conn)
        self._backfill_audit_hash_chain()

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
                response_headers TEXT NOT NULL DEFAULT '{}',
                response_body TEXT,
                response_body_truncated INTEGER NOT NULL DEFAULT 0,
                attempted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_request
                ON delivery_attempts(request_id, attempted_at DESC);
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS request_views (
                view_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                filters TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    @property
    def schema_version(self) -> int:
        """Return the current database schema version."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        return int(row["version"])

    def migration_history(self) -> list[dict[str, Any]]:
        """Return applied migrations in ascending order."""
        rows = self._conn.execute(
            "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        return [dict(row) for row in rows]

    def append_event(self, envelope: dict[str, Any]) -> int:
        """Append one canonical event and return its monotonic cursor."""
        required = {"schema_version", "event_id", "event_type", "timestamp", "data"}
        missing = required - envelope.keys()
        if missing:
            raise ValueError(f"event envelope missing fields: {sorted(missing)}")
        cursor = self._conn.execute(
            """INSERT INTO event_log
               (event_id, schema_version, event_type, timestamp, correlation_id, data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                envelope["event_id"], envelope["schema_version"],
                envelope["event_type"], envelope["timestamp"],
                envelope.get("correlation_id"), json.dumps(envelope["data"]),
            ),
        ).lastrowid
        self._conn.commit()
        return int(cursor)

    def list_events(
        self,
        after_cursor: int = 0,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return events after a cursor for reconnect reconciliation."""
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = "SELECT * FROM event_log WHERE cursor > ?"
        params: list[Any] = [after_cursor]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY cursor ASC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item["data"])
            result.append(item)
        return result

    def query_requests(self, query: RequestQuery) -> dict[str, Any]:
        """Execute the canonical request query using opaque cursor pagination."""
        if query.q:
            items = self.search_requests(
                query=query.q, channel=query.channel, limit=10000
            )
        else:
            items = self.list_requests(channel=query.channel, limit=10000)
        if query.methods:
            items = [item for item in items if item.get("method") in query.methods]
        if query.path:
            items = [item for item in items if query.path in item.get("path", "")]
        if query.received_from:
            items = [item for item in items if item.get("received_at", "") >= query.received_from]
        if query.received_to:
            items = [item for item in items if item.get("received_at", "") <= query.received_to]
        if query.replayed is not None:
            items = [item for item in items if bool(item.get("replayed")) is query.replayed]
        if query.validation_status:
            filtered = []
            for item in items:
                results = self.get_validation_results_for_request(item["request_id"])
                status = "not_checked"
                if results:
                    status = "valid" if results[0].get("valid", True) else "invalid"
                if status == query.validation_status:
                    filtered.append(item)
            items = filtered
        if query.delivery_status:
            items = [
                item for item in items
                if (self.list_delivery_attempts(item["request_id"])[0]["status"]
                    if self.list_delivery_attempts(item["request_id"])
                    else "pending") == query.delivery_status
            ]
        items.sort(
            key=lambda item: (item.get("received_at", ""), item.get("request_id", "")),
            reverse=True,
        )
        if query.cursor:
            cursor_time, cursor_id = decode_cursor(query.cursor)
            items = [
                item for item in items
                if (item.get("received_at", ""), item.get("request_id", ""))
                < (cursor_time, cursor_id)
            ]
        page = items[: query.limit]
        next_cursor = None
        if len(items) > query.limit and page:
            last = page[-1]
            next_cursor = encode_cursor(last["received_at"], last["request_id"])
        return {
            "schema_version": query.schema_version,
            "items": page,
            "next_cursor": next_cursor,
            "applied_query": query.to_dict(),
        }

    @staticmethod
    def _redact_audit_details(value: Any, key: str = "") -> Any:
        sensitive = {"authorization", "cookie", "set-cookie", "token", "api_key", "api-key", "password"}
        if key.lower() in sensitive:
            return "••••••••"
        if isinstance(value, dict):
            return {k: Storage._redact_audit_details(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [Storage._redact_audit_details(item) for item in value]
        return value

    @staticmethod
    def _audit_hash_payload(record: dict[str, Any], previous_hash: str) -> str:
        """Return a deterministic SHA-256 hash for one audit record."""
        payload = {
            "audit_id": record["audit_id"],
            "action": record["action"],
            "actor": record["actor"],
            "object_type": record["object_type"],
            "object_id": record.get("object_id"),
            "outcome": record["outcome"],
            "correlation_id": record.get("correlation_id"),
            "details": record["details"],
            "created_at": record["created_at"],
            "previous_hash": previous_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _backfill_audit_hash_chain(self) -> None:
        """Create hashes for pre-1.1 audit rows without changing their content."""
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at ASC, audit_id ASC"
        ).fetchall()
        if not rows or all(row["record_hash"] for row in rows):
            return
        previous_hash = ""
        with self._conn:
            for row in rows:
                item = dict(row)
                details = json.loads(item["details"])
                item["details"] = details
                record_hash = self._audit_hash_payload(item, previous_hash)
                self._conn.execute(
                    "UPDATE audit_log SET previous_hash = ?, record_hash = ? WHERE audit_id = ?",
                    (previous_hash, record_hash, item["audit_id"]),
                )
                previous_hash = record_hash

    def _rebuild_audit_hash_chain(self) -> None:
        """Rebuild the chain after an intentional retention deletion."""
        self._conn.execute("UPDATE audit_log SET previous_hash = '', record_hash = ''")
        self._conn.commit()
        self._backfill_audit_hash_chain()

    def record_audit_event(
        self,
        action: str,
        actor: str,
        object_type: str,
        object_id: str | None,
        outcome: str,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        """Append a redacted, immutable audit record."""
        audit_id = uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        safe_details = self._redact_audit_details(details or {})
        previous = self._conn.execute(
            "SELECT record_hash FROM audit_log ORDER BY created_at DESC, audit_id DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["record_hash"] if previous else ""
        record = {
            "audit_id": audit_id,
            "action": action,
            "actor": actor,
            "object_type": object_type,
            "object_id": object_id,
            "outcome": outcome,
            "correlation_id": correlation_id,
            "details": safe_details,
            "created_at": created_at,
        }
        record_hash = self._audit_hash_payload(record, previous_hash)
        self._conn.execute(
            """INSERT INTO audit_log
               (audit_id, action, actor, object_type, object_id, outcome,
                correlation_id, details, created_at, previous_hash, record_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id, action, actor, object_type, object_id, outcome,
                correlation_id, json.dumps(safe_details), created_at,
                previous_hash, record_hash,
            ),
        )
        self._conn.commit()
        return audit_id

    def verify_audit_chain(self) -> dict[str, Any]:
        """Verify every audit record and its link to the previous record."""
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at ASC, audit_id ASC"
        ).fetchall()
        previous_hash = ""
        checked = 0
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            expected = self._audit_hash_payload(item, previous_hash)
            if item["previous_hash"] != previous_hash or item["record_hash"] != expected:
                return {
                    "valid": False,
                    "checked": checked,
                    "broken_audit_id": item["audit_id"],
                }
            previous_hash = item["record_hash"]
            checked += 1
        return {"valid": True, "checked": checked, "broken_audit_id": None}

    def purge_audit_events_older_than(self, days: int) -> int:
        """Purge old audit records and establish a new verifiable chain root."""
        if days < 1:
            raise ValueError("days must be at least 1")
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM audit_log WHERE created_at < ?", (cutoff,)
        )
        self._conn.commit()
        if cursor.rowcount:
            self._rebuild_audit_hash_chain()
        return cursor.rowcount

    def list_audit_events(
        self,
        limit: int = 100,
        action: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        """List immutable audit records newest first."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if action:
            query += " AND action = ?"
            params.append(action)
        if actor:
            query += " AND actor = ?"
            params.append(actor)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(max(limit, 1), 1000))
        rows = self._conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item["details"])
            result.append(item)
        return result

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

    def store_delivery_attempt(
        self,
        request_id: str,
        channel: str,
        status: str,
        target_url: str | None = None,
        response_status: int | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
        response_headers: dict[str, Any] | None = None,
        response_body: str | bytes | None = None,
    ) -> str:
        """Persist a forwarding outcome with bounded, redacted response data."""
        sensitive = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token", "api-key"}
        headers = {
            key: ("••••••••" if key.lower() in sensitive else value)
            for key, value in (response_headers or {}).items()
        }
        if isinstance(response_body, bytes):
            body_text = response_body.decode("utf-8", errors="replace")
        else:
            body_text = response_body
        truncated = False
        if body_text is not None and len(body_text.encode("utf-8")) > 16384:
            raw = body_text.encode("utf-8")[:16384]
            body_text = raw.decode("utf-8", errors="ignore")
            truncated = True
        attempt_id = uuid4().hex
        attempted_at = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO delivery_attempts
               (attempt_id, request_id, channel, target_url, status,
                response_status, duration_ms, error, response_headers,
                response_body, response_body_truncated, attempted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (attempt_id, request_id, channel, target_url, status,
             response_status, duration_ms, error, json.dumps(headers),
             body_text, 1 if truncated else 0, attempted_at),
        )
        self._conn.commit()
        return attempt_id

    def list_delivery_attempts(self, request_id: str) -> list[dict[str, Any]]:
        """Return newest-first delivery attempts for one request."""
        rows = self._conn.execute(
            "SELECT * FROM delivery_attempts WHERE request_id = ? ORDER BY attempted_at DESC",
            (request_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["response_headers"] = json.loads(item.get("response_headers") or "{}")
            item["response_body_truncated"] = bool(item["response_body_truncated"])
            result.append(item)
        return result

    def set_setting(self, key: str, value: Any) -> None:
        """Persist a JSON-serializable application setting."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT INTO app_settings(setting_key, setting_value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(setting_key) DO UPDATE SET
               setting_value = excluded.setting_value, updated_at = excluded.updated_at""",
            (key, json.dumps(value), now),
        )
        self._conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT setting_value FROM app_settings WHERE setting_key = ?", (key,)
        ).fetchone()
        return default if row is None else json.loads(row["setting_value"])

    def storage_health(self) -> dict[str, Any]:
        """Return actionable integrity, size, and row-count diagnostics."""
        from pathlib import Path

        database_path = Path(self._db_path)
        integrity = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
        mode = self._conn.execute("PRAGMA journal_mode").fetchone()[0]
        counts = {
            "requests": self._conn.execute("SELECT COUNT(*) FROM webhooks").fetchone()[0],
            "events": self._conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
            "audit_records": self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
            "delivery_attempts": self._conn.execute("SELECT COUNT(*) FROM delivery_attempts").fetchone()[0],
        }
        audit = self.verify_audit_chain()
        return {
            "integrity": integrity,
            "schema_version": self.schema_version,
            "database_path": str(database_path.resolve()),
            "database_size_bytes": database_path.stat().st_size if database_path.exists() else 0,
            "wal_size_bytes": database_path.with_name(database_path.name + "-wal").stat().st_size
            if database_path.with_name(database_path.name + "-wal").exists()
            else 0,
            "journal_mode": mode,
            "counts": counts,
            "audit_chain_valid": audit["valid"],
            "audit_checked": audit["checked"],
        }

    def set_backup_policy(
        self,
        *,
        enabled: bool,
        interval_hours: int,
        keep_last: int,
    ) -> None:
        """Persist the scheduled backup policy after strict validation."""
        if interval_hours < 1 or interval_hours > 24 * 30:
            raise ValueError("interval_hours must be between 1 and 720")
        if keep_last < 1 or keep_last > 365:
            raise ValueError("keep_last must be between 1 and 365")
        self.set_setting(
            "backup_policy",
            {
                "enabled": bool(enabled),
                "interval_hours": interval_hours,
                "keep_last": keep_last,
            },
        )

    def get_backup_policy(self) -> dict[str, Any]:
        """Return the persisted policy or conservative defaults."""
        return self.get_setting(
            "backup_policy",
            {"enabled": False, "interval_hours": 24, "keep_last": 7},
        )

    def backup_is_due(self, now: datetime | None = None) -> bool:
        """Check whether the enabled policy's interval has elapsed."""
        from datetime import timedelta

        policy = self.get_backup_policy()
        if not policy["enabled"]:
            return False
        last_backup = self.get_setting("last_backup_at")
        if not last_backup:
            return True
        now = now or datetime.now(UTC)
        return now - datetime.fromisoformat(last_backup) >= timedelta(
            hours=policy["interval_hours"]
        )

    def run_scheduled_backup(
        self,
        destination: str | Any,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run a due backup and prune old bundles according to policy."""
        from hookrelay.backup import create_backup, prune_backups

        policy = self.get_backup_policy()
        if not force and not self.backup_is_due():
            return {"status": "not_due", "policy": policy}
        import os

        bundle = create_backup(
            self,
            destination,
            encryption_key=os.getenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY") or None,
        )
        completed_at = datetime.now(UTC).isoformat()
        self.set_setting("last_backup_at", completed_at)
        pruned = prune_backups(destination, policy["keep_last"])
        self.record_audit_event(
            "data.backup", "scheduler" if not force else "local-session",
            "database", str(self._db_path), "success",
            details={"sha256": bundle.sha256, "pruned": pruned},
        )
        return {
            "status": "created",
            "database_path": str(bundle.database_path),
            "manifest_path": str(bundle.manifest_path),
            "sha256": bundle.sha256,
            "completed_at": completed_at,
            "pruned": pruned,
        }

    def delete_request(self, request_id: str) -> bool:
        self._init_validation_results_table()
        with self._conn:
            self._conn.execute("DELETE FROM delivery_attempts WHERE request_id = ?", (request_id,))
            self._conn.execute("DELETE FROM validation_results WHERE request_id = ?", (request_id,))
            cursor = self._conn.execute("DELETE FROM webhooks WHERE request_id = ?", (request_id,))
        return cursor.rowcount > 0

    def purge_requests_older_than(self, days: int) -> int:
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

    def increment_replay_count(self, request_id: str) -> None:
        """Increment the replay counter for a request."""
        self._conn.execute(
            "UPDATE webhooks SET replayed = replayed + 1 WHERE request_id = ?",
            (request_id,),
        )
        self._conn.commit()

    def save_request_view(self, name: str, filters: dict[str, Any]) -> str:
        """Save a named request query after validating supported fields."""
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("view name must not be empty")
        existing = self._conn.execute(
            "SELECT 1 FROM request_views WHERE name = ? COLLATE NOCASE",
            (cleaned_name,),
        ).fetchone()
        if existing:
            raise ValueError(f"request view '{cleaned_name}' already exists")
        allowed = {"q", "channel", "method", "path", "validation_status", "limit"}
        cleaned = {key: value for key, value in filters.items() if key in allowed and value not in (None, "")}
        view_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO request_views(view_id, name, filters, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (view_id, cleaned_name, json.dumps(cleaned), now, now),
        )
        self._conn.commit()
        return view_id

    def get_request_view(self, view_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM request_views WHERE view_id = ?", (view_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["filters"] = json.loads(item["filters"])
        return item

    def list_request_views(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM request_views ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["filters"] = json.loads(item["filters"])
            result.append(item)
        return result

    def delete_request_view(self, view_id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM request_views WHERE view_id = ?", (view_id,))
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
