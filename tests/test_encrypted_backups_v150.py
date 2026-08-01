"""TDD acceptance tests for v1.5 encrypted backup bundles."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hookrelay import _storage
from hookrelay.backup import (
    BackupIntegrityError,
    create_backup,
    inspect_backup,
    restore_backup,
)
from hookrelay.server import create_app
from hookrelay.storage import Storage


def _request(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "channel": "secure",
        "method": "POST",
        "path": "/private",
        "headers": {"authorization": "Bearer secret"},
        "body": b'{"customer":"private-value"}',
        "query_params": {},
        "source_ip": "127.0.0.1",
        "received_at": datetime.now(UTC).isoformat(),
    }


def test_encrypted_backup_does_not_contain_plaintext_and_restores(tmp_path):
    store = Storage(str(tmp_path / "live.db"))
    store.store_request(_request("encrypted-request"))
    bundle = create_backup(store, tmp_path / "backups", encryption_key="backup-secret")
    manifest = json.loads(bundle.manifest_path.read_text())

    assert manifest["encrypted"] is True
    assert manifest["encryption"]["algorithm"] == "AES-256-GCM"
    assert bundle.database_path.suffix == ".enc"
    encrypted = bundle.database_path.read_bytes()
    assert b"private-value" not in encrypted
    assert not encrypted.startswith(b"SQLite format 3")

    restored_path = tmp_path / "restored.db"
    restore_backup(bundle.manifest_path, restored_path, encryption_key="backup-secret")
    restored = Storage(str(restored_path))
    assert restored.get_request("encrypted-request") is not None


def test_wrong_or_missing_encryption_key_is_rejected(tmp_path):
    store = Storage(str(tmp_path / "live.db"))
    bundle = create_backup(store, tmp_path / "backups", encryption_key="correct-key")
    with pytest.raises(BackupIntegrityError, match="encryption key"):
        restore_backup(bundle.manifest_path, tmp_path / "missing.db")
    with pytest.raises(BackupIntegrityError, match="decrypt"):
        restore_backup(
            bundle.manifest_path,
            tmp_path / "wrong.db",
            encryption_key="wrong-key",
        )


def test_encrypted_backup_inspection_requires_key_for_content_counts(tmp_path):
    store = Storage(str(tmp_path / "live.db"))
    store.store_request(_request("inspect-request"))
    bundle = create_backup(store, tmp_path / "backups", encryption_key="inspect-key")

    locked = inspect_backup(bundle.manifest_path)
    assert locked["valid"] is True
    assert locked["encrypted"] is True
    assert locked["content_access"] == "key_required"
    assert locked["counts"]["requests"] is None

    unlocked = inspect_backup(bundle.manifest_path, encryption_key="inspect-key")
    assert unlocked["valid"] is True
    assert unlocked["content_access"] == "verified"
    assert unlocked["counts"]["requests"] == 1


def test_backup_api_encrypts_when_environment_key_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY", "api-encryption-key")
    store = Storage(str(tmp_path / "api.db"))
    _storage.set(store)
    response = TestClient(create_app()).post("/api/data/backups")
    assert response.status_code == 201
    payload = response.json()
    assert payload["encrypted"] is True
    manifest = json.loads(Path(payload["manifest_path"]).read_text())
    assert manifest["encrypted"] is True


def test_backup_center_labels_encrypted_bundles(tmp_path, monkeypatch):
    monkeypatch.setenv("HOOKRELAY_BACKUP_ENCRYPTION_KEY", "center-key")
    store = Storage(str(tmp_path / "center.db"))
    create_backup(store, tmp_path / "backups", encryption_key="center-key")
    _storage.set(store)
    page = TestClient(create_app()).get("/dashboard/backups")
    assert page.status_code == 200
    assert "Encrypted" in page.text
    assert "Key required for content preview" in page.text


def test_plaintext_backup_remains_backward_compatible(tmp_path):
    store = Storage(str(tmp_path / "legacy.db"))
    store.store_request(_request("legacy-request"))
    bundle = create_backup(store, tmp_path / "backups")
    manifest = json.loads(bundle.manifest_path.read_text())
    assert manifest.get("encrypted", False) is False
    restored_path = tmp_path / "restored.db"
    restore_backup(bundle.manifest_path, restored_path)
    assert Storage(str(restored_path)).get_request("legacy-request") is not None
