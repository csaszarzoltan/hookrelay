"""TDD acceptance tests for v1.1 backup, restore, and tamper-evident audit data."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.backup import BackupIntegrityError, create_backup, restore_backup
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _request(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "channel": "dev",
        "method": "POST",
        "path": "/events",
        "headers": {},
        "body": b"{}",
        "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": datetime.now(UTC).isoformat(),
    }


def test_backup_manifest_checksum_and_restore_round_trip(tmp_path):
    database = tmp_path / "source.db"
    store = Storage(str(database))
    store.store_request(_request("before-backup"))
    bundle = create_backup(store, tmp_path / "backups")

    assert bundle.database_path.exists()
    assert bundle.manifest_path.exists()
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest["schema_version"] == store.schema_version
    assert manifest["sha256"] == bundle.sha256

    store.store_request(_request("after-backup"))
    restored_path = tmp_path / "restored.db"
    restore_backup(bundle.manifest_path, restored_path)
    restored = Storage(str(restored_path))
    assert restored.get_request("before-backup") is not None
    assert restored.get_request("after-backup") is None


def test_restore_rejects_tampered_backup(tmp_path):
    store = Storage(str(tmp_path / "source.db"))
    bundle = create_backup(store, tmp_path / "backups")
    with bundle.database_path.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(BackupIntegrityError):
        restore_backup(bundle.manifest_path, tmp_path / "restored.db")


def test_audit_hash_chain_detects_database_tampering(tmp_path):
    store = Storage(str(tmp_path / "audit.db"))
    first = store.record_audit_event("request.received", "system", "request", "r1", "success")
    second = store.record_audit_event("request.replay", "user:alice", "request", "r1", "success")
    verification = store.verify_audit_chain()
    assert verification == {"valid": True, "checked": 2, "broken_audit_id": None}

    store._conn.execute(
        "UPDATE audit_log SET outcome = 'failure' WHERE audit_id = ?", (first,)
    )
    store._conn.commit()
    verification = store.verify_audit_chain()
    assert verification["valid"] is False
    assert verification["broken_audit_id"] in {first, second}


def test_audit_retention_purges_old_records_and_rebuilds_chain(tmp_path):
    store = Storage(str(tmp_path / "retention.db"))
    old_id = store.record_audit_event("old.event", "system", "request", "old", "success")
    store.record_audit_event("new.event", "system", "request", "new", "success")
    old_time = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    store._conn.execute(
        "UPDATE audit_log SET created_at = ? WHERE audit_id = ?", (old_time, old_id)
    )
    store._conn.commit()

    assert store.purge_audit_events_older_than(365) == 1
    assert [row["action"] for row in store.list_audit_events()] == ["new.event"]
    assert store.verify_audit_chain()["valid"] is True


def test_backup_and_audit_admin_apis(tmp_path):
    store = Storage(str(tmp_path / "api.db"))
    store.record_audit_event("api.event", "system", "request", "r1", "success")
    _storage.set(store)
    client = TestClient(create_app())

    backup = client.post("/api/data/backups")
    assert backup.status_code == 201
    assert Path(backup.json()["manifest_path"]).exists()
    verify = client.get("/api/audit/verify")
    assert verify.json()["valid"] is True
    purge = client.post("/api/audit/purge", json={"days": 365})
    assert purge.status_code == 200
    assert "deleted" in purge.json()


def test_newer_schema_version_is_rejected_without_modification(tmp_path):
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
    )
    connection.execute(
        "INSERT INTO schema_migrations VALUES (999, 'future', '2026-08-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="newer"):
        Storage(str(path))
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 999
    connection.close()


def test_backup_cli_commands_are_registered():
    from typer.testing import CliRunner

    from hookrelay.cli import app

    result = CliRunner().invoke(app, ["data", "--help"])
    assert result.exit_code == 0
    assert "backup" in result.stdout
    assert "restore" in result.stdout
    assert "verify-audit" in result.stdout
