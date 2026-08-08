"""Explicit, idempotent SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

CURRENT_SCHEMA_VERSION = 7

_MIGRATIONS: dict[int, tuple[str, str]] = {
    1: (
        "baseline-core",
        """CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL, updated_at TEXT NOT NULL
        );""",
    ),
    2: (
        "events-and-audit",
        """CREATE TABLE IF NOT EXISTS event_log (
            cursor INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            schema_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            correlation_id TEXT,
            data TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_event_log_type_cursor ON event_log(event_type, cursor);
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT,
            outcome TEXT NOT NULL,
            correlation_id TEXT,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);""",
    ),
    3: (
        "canonical-query-metadata",
        """CREATE TABLE IF NOT EXISTS query_schema_metadata (
            schema_name TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO query_schema_metadata(schema_name, schema_version, updated_at)
        VALUES ('request_query', 1, CURRENT_TIMESTAMP);""",
    ),
    4: (
        "audit-hash-chain",
        """ALTER TABLE audit_log ADD COLUMN previous_hash TEXT NOT NULL DEFAULT '';
        ALTER TABLE audit_log ADD COLUMN record_hash TEXT NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS idx_audit_hash ON audit_log(record_hash);""",
    ),
    5: (
        "delivery-delivery-id",
        """CREATE TABLE IF NOT EXISTS _mig5_dummy (dummy INTEGER);
        DROP TABLE IF EXISTS _mig5_dummy;
        """,
    ),
    6: (
        "alert-rules",
        """CREATE TABLE IF NOT EXISTS alert_rules (
            rule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            scope TEXT NOT NULL,
            endpoint_id TEXT,
            metric TEXT NOT NULL,
            threshold REAL NOT NULL,
            window_minutes INTEGER NOT NULL DEFAULT 15,
            cooldown_minutes INTEGER NOT NULL DEFAULT 15,
            enabled INTEGER NOT NULL DEFAULT 1,
            notifier_ids TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_fired_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_alert_rules_scope_endpoint
            ON alert_rules(scope, endpoint_id);""",
    ),
    7: (
        "alert-history",
        """CREATE TABLE IF NOT EXISTS alert_history (
            event_id TEXT PRIMARY KEY,
            rule_id TEXT NOT NULL,
            rule_name TEXT,
            metric TEXT,
            observed_value REAL,
            threshold REAL,
            message TEXT,
            fired_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_alert_history_fired_at
            ON alert_history(fired_at DESC);""",
    ),
}


def run_migrations(connection: sqlite3.Connection) -> None:
    """Apply all pending migrations transactionally and record their history."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )
    current = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()[0]
    if current > CURRENT_SCHEMA_VERSION:
        raise RuntimeError("database schema is newer than this Hookrelay version")
    for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
        name, sql = _MIGRATIONS[version]
        with connection:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now(UTC).isoformat()),
            )
