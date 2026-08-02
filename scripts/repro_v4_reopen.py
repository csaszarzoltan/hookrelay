"""Verify F4: a faithful pre-existing v4 DB (delivery_attempts WITHOUT
delivery_id/endpoint_id, migrations 1-4 applied) reopens cleanly.

The old code crashed on reopen with "no such column: delivery_id" because
_init_schema's CREATE INDEX ran before the ALTER. With the fix, the columns
are added before the index DDL and migration 5 (no-op) applies.
"""
import os
import sqlite3
import tempfile

p = os.path.join(tempfile.gettempdir(), "hookrelay_v4_reopen_test.db")
if os.path.exists(p):
    os.remove(p)

# ---- Build the exact DDL a v4 database would have (mirrors storage.py _init_schema
# ---- minus delivery_id/endpoint_id + idx_delivery_delivery_id, plus migrations 1-4).
conn = sqlite3.connect(p)
conn.executescript(
    """
    CREATE TABLE webhooks (
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
    CREATE VIRTUAL TABLE webhooks_fts USING fts5(
        request_id UNINDEXED, channel, method, path, headers, body,
        content='webhooks', content_rowid='rowid'
    );
    CREATE TABLE delivery_attempts (
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
    CREATE INDEX idx_delivery_request ON delivery_attempts(request_id, attempted_at DESC);
    CREATE TABLE app_settings (
        setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE request_views (
        view_id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        filters TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE event_log (
        cursor INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        schema_version INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        correlation_id TEXT,
        data TEXT NOT NULL
    );
    CREATE TABLE audit_log (
        audit_id TEXT PRIMARY KEY,
        action TEXT NOT NULL,
        actor TEXT NOT NULL,
        object_type TEXT NOT NULL,
        object_id TEXT,
        outcome TEXT NOT NULL,
        correlation_id TEXT,
        details TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        previous_hash TEXT NOT NULL DEFAULT '',
        record_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
    );
    INSERT INTO schema_migrations (version, name, applied_at) VALUES
        (1, 'baseline-core', '2026-01-01T00:00:00+00:00'),
        (2, 'events-and-audit', '2026-01-01T00:00:00+00:00'),
        (3, 'canonical-query-metadata', '2026-01-01T00:00:00+00:00'),
        (4, 'audit-hash-chain', '2026-01-01T00:00:00+00:00');
    """
)
conn.commit()
conn.close()

from hookrelay.storage import Storage

s = Storage(p)
cols = {r["name"] for r in s._conn.execute("PRAGMA table_info(delivery_attempts)").fetchall()}
assert "delivery_id" in cols and "endpoint_id" in cols, f"columns missing: {cols}"
idx = s._conn.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_delivery_delivery_id'"
).fetchone()
assert idx, "idx_delivery_delivery_id missing"
assert s.schema_version == 5, f"schema_version={s.schema_version}, expected 5"
print("V4 REOPEN OK: columns added, index created, migration 5 applied, schema_version =", s.schema_version)
os.remove(p)
