"""TDD acceptance tests for v1.2 scheduled backup and storage operations."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.backup import create_backup, prune_backups
from hookrelay.server import create_app
from hookrelay.storage import Storage


def test_backup_retention_prunes_complete_bundles(tmp_path):
    store = Storage(str(tmp_path / "live.db"))
    backup_dir = tmp_path / "backups"
    bundles = [create_backup(store, backup_dir) for _ in range(3)]
    for index, bundle in enumerate(bundles):
        manifest = json.loads(bundle.manifest_path.read_text())
        manifest["created_at"] = (
            datetime.now(UTC) - timedelta(days=30 - index)
        ).isoformat()
        bundle.manifest_path.write_text(json.dumps(manifest))
    result = prune_backups(backup_dir, keep_last=1)
    assert result["deleted_bundles"] == 2
    assert len(list(backup_dir.glob("*.json"))) == 1
    assert len(list(backup_dir.glob("*.db"))) == 1


def test_storage_health_reports_integrity_size_counts_and_wal(tmp_path):
    store = Storage(str(tmp_path / "health.db"))
    store.store_request({
        "request_id": "health", "channel": "dev", "method": "POST",
        "path": "/hook", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1", "received_at": datetime.now(UTC).isoformat(),
    })
    health = store.storage_health()
    assert health["integrity"] == "ok"
    assert health["schema_version"] >= 4
    assert health["database_size_bytes"] > 0
    assert health["counts"]["requests"] == 1
    assert "audit_chain_valid" in health


def test_backup_policy_round_trip_and_due_detection(tmp_path):
    store = Storage(str(tmp_path / "policy.db"))
    store.set_backup_policy(enabled=True, interval_hours=24, keep_last=7)
    policy = store.get_backup_policy()
    assert policy == {"enabled": True, "interval_hours": 24, "keep_last": 7}
    assert store.backup_is_due() is True
    store.set_setting("last_backup_at", datetime.now(UTC).isoformat())
    assert store.backup_is_due() is False


def test_run_scheduled_backup_creates_bundle_and_prunes(tmp_path):
    store = Storage(str(tmp_path / "scheduled.db"))
    store.set_backup_policy(enabled=True, interval_hours=1, keep_last=2)
    result = store.run_scheduled_backup(tmp_path / "backups", force=True)
    assert Path(result["manifest_path"]).exists()
    assert result["pruned"]["remaining_bundles"] == 1
    assert store.get_setting("last_backup_at") is not None


def test_storage_admin_apis_report_health_and_manage_policy(tmp_path):
    store = Storage(str(tmp_path / "api.db"))
    _storage.set(store)
    client = TestClient(create_app())
    health = client.get("/api/data/health")
    assert health.status_code == 200
    assert health.json()["integrity"] == "ok"
    updated = client.put("/api/data/backup-policy", json={
        "enabled": True, "interval_hours": 12, "keep_last": 5,
    })
    assert updated.status_code == 200
    assert updated.json()["keep_last"] == 5
    run = client.post("/api/data/backups/run", json={"force": True})
    assert run.status_code == 201
    assert Path(run.json()["manifest_path"]).exists()


def test_settings_page_exposes_data_health_and_backup_controls(tmp_path):
    store = Storage(str(tmp_path / "ui.db"))
    _storage.set(store)
    page = TestClient(create_app()).get("/dashboard/settings")
    assert page.status_code == 200
    assert 'id="storage-health"' in page.text
    assert 'id="backup-enabled"' in page.text
    assert 'id="backup-interval"' in page.text
    assert 'id="backup-keep-last"' in page.text
    assert 'id="run-backup"' in page.text
