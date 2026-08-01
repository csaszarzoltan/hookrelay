"""TDD acceptance tests for the v1.4 backup center workflow."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.backup import create_backup
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _client(tmp_path):
    store = Storage(str(tmp_path / "backup-center.db"))
    _storage.set(store)
    return TestClient(create_app()), store


def test_backup_center_lists_verified_bundles_with_restore_preview(tmp_path):
    client, store = _client(tmp_path)
    store.store_request({
        "request_id": "preview-request", "channel": "dev", "method": "POST",
        "path": "/events", "headers": {}, "body": b"{}", "query_params": {},
        "source_ip": "127.0.0.1", "received_at": datetime.now(UTC).isoformat(),
    })
    bundle = create_backup(store, tmp_path / "backups")
    response = client.get("/dashboard/backups")
    assert response.status_code == 200
    assert "Backup center" in response.text
    assert bundle.manifest_path.name in response.text
    assert "Verified" in response.text
    assert "1 request" in response.text
    assert 'data-action="inspect-backup"' in response.text


def test_backup_center_empty_state_is_actionable(tmp_path):
    client, _ = _client(tmp_path)
    response = client.get("/dashboard/backups")
    assert response.status_code == 200
    assert "No backup bundles yet" in response.text
    assert 'id="create-first-backup"' in response.text


def test_backup_catalog_summary_reports_valid_invalid_and_total_size(tmp_path):
    client, store = _client(tmp_path)
    create_backup(store, tmp_path / "backups")
    invalid = tmp_path / "backups" / "broken.json"
    invalid.write_text('{"broken": true}')
    response = client.get("/api/data/backups/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["valid"] == 1
    assert payload["invalid"] == 1
    assert payload["total_size_bytes"] > 0


def test_backup_manifest_delete_requires_confirmation_and_deletes_pair(tmp_path):
    client, store = _client(tmp_path)
    bundle = create_backup(store, tmp_path / "backups")
    denied = client.delete(
        "/api/data/backups",
        params={"manifest_path": str(bundle.manifest_path)},
    )
    assert denied.status_code == 400
    deleted = client.delete(
        "/api/data/backups",
        params={"manifest_path": str(bundle.manifest_path), "confirm": "true"},
    )
    assert deleted.status_code == 204
    assert not bundle.manifest_path.exists()
    assert not bundle.database_path.exists()
    audit = store.list_audit_events(action="data.backup.delete")
    assert audit and audit[0]["outcome"] == "success"


def test_backup_delete_rejects_path_outside_managed_directory(tmp_path):
    client, _ = _client(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    response = client.delete(
        "/api/data/backups",
        params={"manifest_path": str(outside), "confirm": "true"},
    )
    assert response.status_code == 400
    assert outside.exists()


def test_backup_navigation_is_present_on_dashboard_pages(tmp_path):
    client, _ = _client(tmp_path)
    for path in ("/dashboard/", "/dashboard/history", "/dashboard/settings", "/dashboard/backups"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/dashboard/backups"' in response.text
