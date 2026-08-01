"""Explicit, idempotent SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

CURRENT_SCHEMA_VERSION = 3

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
